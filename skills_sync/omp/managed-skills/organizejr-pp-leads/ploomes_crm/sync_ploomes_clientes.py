#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import gsheets_helper
from update_ploomes_clientes import build_header_map, clean, digits, find_header_row, read_cell


DEFAULT_BASE_URL = "https://api2.ploomes.com"
STATUS_SENT = "Enviado"
STATUS_ERROR = "Erro"
READY_FLAG = "SIM"
NO_FLAGS = {"NÃO", "NAO", "NO"}


def dotenv_api_key(path: str = ".env") -> str:
    env_path = Path(path)
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            if key.strip() != "PLOOMES_API_KEY":
                continue
            return value.strip().strip('"').strip("'")
        return line.strip().strip('"').strip("'")
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sincroniza a planilha operacional do Google Sheets com a API do Ploomes.")
    parser.add_argument("--workbook", help="Ignorado nesta versão (mantido apenas por compatibilidade).")
    parser.add_argument("--spreadsheet-id", required=True, help="ID da planilha do Google Sheets.")
    parser.add_argument("--sheet-name-name", default="Clientes", help="Nome da aba (default: Clientes).")
    parser.add_argument("--sheet-name", default="Clientes", help="Nome da aba. Padrão: Clientes.")
    parser.add_argument("--api-key", default=os.getenv("PLOOMES_API_KEY", "") or dotenv_api_key(Path(__file__).with_name(".env")), help="User-Key do Ploomes.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Base URL da API. Padrão: {DEFAULT_BASE_URL}.")
    parser.add_argument("--row-numbers", default="", help="Lista opcional de linhas, separadas por vírgula.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de linhas elegíveis a processar.")
    parser.add_argument("--sleep", type=float, default=0.65, help="Pausa entre requisições com efeito remoto.")
    parser.add_argument("--allow-blank-send", action="store_true", help="Também permite linhas com Enviar ao Ploomes? em branco.")
    parser.add_argument("--resync-sent", action="store_true", help="Permite reprocessar linhas já marcadas como Enviado.")
    parser.add_argument("--output", help="Ignorado nesta versão (a escrita ocorre diretamente no Google Sheets).")
    parser.add_argument("--yes", action="store_true", help="Confirma execução sem prompt interativo.")
    parser.add_argument("--json", action="store_true", help="Imprime resumo em JSON.")
    args = parser.parse_args()
    if not args.api_key:
        parser.error("PLOOMES_API_KEY ausente. Use --api-key, variável de ambiente ou .env.")
    if not args.yes and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        parser.error("use --yes em modo não interativo")
    return args


def confirm_or_exit(args: argparse.Namespace) -> None:
    if args.yes:
        return
    answer = input(f"Sincronizar a planilha {args.spreadsheet_id}/{args.sheet_name} diretamente com o Ploomes? Digite ENVIAR para confirmar: ").strip()
    if answer != "ENVIAR":
        raise SystemExit("operação cancelada")


def build_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{key}={urllib.parse.quote(str(value), safe="()',$,/")}" for key, value in params.items()
    )


def api_request(session: requests.Session, base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + build_query(params)
    response = session.request(method, url, json=payload, timeout=60)
    if 200 <= response.status_code < 300:
        text = response.text.strip()
        return response.json() if text else {}
    raise RuntimeError(f"{method} {url} -> HTTP {response.status_code}: {response.text[:1000]}")


def fetch_all(session: requests.Session, base_url: str, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    url = base_url.rstrip("/") + path + "?" + build_query(params)
    while url:
        response = session.get(url, timeout=60)
        if response.status_code != 200:
            raise RuntimeError(f"GET {url} -> HTTP {response.status_code}: {response.text[:1000]}")
        data = response.json()
        items.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", next_link) if next_link else None
    return items


def only_digits(value: Any) -> str:
    return digits(value)


def pick(row: dict[str, Any], *names: str) -> str:
    for name in names:
        if name in row:
            value = clean(row.get(name))
            if value:
                return value
    return ""


def company_name(row: dict[str, Any]) -> str:
    return pick(row, "Razão Social - Empresa", "Razao Social - Empresa", "Razão social - Empresa", "Razao social - Empresa", "Nome - Empresa", "Nome Empresa")


def person_name(row: dict[str, Any]) -> str:
    return pick(row, "Nome - Pessoa", "Nome Pessoa")


def row_kind(row: dict[str, Any]) -> str:
    has_company = bool(company_name(row))
    has_person = bool(person_name(row))
    if has_company and has_person:
        return "empresa_com_pessoa"
    if has_company:
        return "empresa_sem_pessoa"
    if has_person:
        return "pessoa_fisica_sem_empresa"
    return "ignorar"


def field_note(label: str, value: Any) -> str:
    value = clean(value)
    return f"{label}: {value}" if value else ""


def joined_note(*parts: Any) -> str:
    return "\n".join(clean(part) for part in parts if clean(part))


def normalize_date(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    parts = text.split("/")
    if len(parts) == 3:
        day, month, year = parts
        if len(year) == 2:
            year = f"20{year}"
        return f"{year.zfill(4)}-{month.zfill(2)}-{day.zfill(2)}"
    return text

def normalize_website(value: Any) -> str:
    raw = clean(value)
    if not raw:
        return ""
    if len(raw) > 200:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.casefold()
    if "google." in host:
        return ""
    return raw


def odata_escape(value: Any) -> str:
    return clean(value).replace("'", "''")


def first_contact(session: requests.Session, base_url: str, filter_expr: str) -> dict[str, Any] | None:
    data = api_request(
        session,
        base_url,
        "GET",
        "/Contacts",
        params={
            "$filter": filter_expr,
            "$select": "Id,TypeId,Name,LegalName,Email,Register,CompanyId,OriginId,Note,Website,Birthday,CreateDate",
            "$top": "1",
        },
    )
    values = data.get("value", [])
    return values[0] if values else None


def find_company(session: requests.Session, base_url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("Register"):
        found = first_contact(session, base_url, f"TypeId eq 1 and Register eq '{odata_escape(payload['Register'])}'")
        if found:
            return found
    return first_contact(session, base_url, f"TypeId eq 1 and Name eq '{odata_escape(payload['Name'])}'")


def find_person(session: requests.Session, base_url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("Email"):
        found = first_contact(session, base_url, f"TypeId eq 2 and Email eq '{odata_escape(payload['Email'])}'")
        if found:
            return found
    if payload.get("Register"):
        found = first_contact(session, base_url, f"TypeId eq 2 and Register eq '{odata_escape(payload['Register'])}'")
        if found:
            return found
    return first_contact(session, base_url, f"TypeId eq 2 and Name eq '{odata_escape(payload['Name'])}'")


def load_origins(session: requests.Session, base_url: str) -> dict[str, Any]:
    try:
        data = api_request(session, base_url, "GET", "/Contacts@Origins", params={"$select": "Id,Name", "$top": "100"})
    except Exception:
        return {}
    return {clean(item.get("Name")).casefold(): item.get("Id") for item in data.get("value", []) if clean(item.get("Name"))}


def origin_id(row: dict[str, Any], origin_by_name: dict[str, Any]) -> Any:
    name = pick(row, "Origem - Empresa", "Origem - Pessoa", "Origem")
    return origin_by_name.get(name.casefold()) if name else None


def build_company_payload(row: dict[str, Any], origin_by_name: dict[str, Any]) -> dict[str, Any] | None:
    name = company_name(row)
    if not name:
        return None
    payload: dict[str, Any] = {"TypeId": 1, "Name": name, "LegalName": name}
    cnpj = only_digits(pick(row, "CNPJ - Empresa", "CNPJ"))
    raw_site = pick(row, "Site", "Site - Empresa")
    site = normalize_website(raw_site)
    note = joined_note(
        field_note("Segmento", pick(row, "Segmento de atuação - Empresa", "Segmento - Empresa")),
        field_note("Estado", pick(row, "Estado - Empresa")),
        field_note("Cidade", pick(row, "Cidade - Empresa")),
        field_note("Marcadores", pick(row, "Marcadores - Empresa", "Marcadores")),
        pick(row, "Relação", "Relacao"),
        pick(row, "Observações", "Observacoes"),
    )
    oid = origin_id(row, origin_by_name)
    if cnpj:
        payload["Register"] = cnpj
    if raw_site and not site:
        payload["Website"] = None
    elif site:
        payload["Website"] = site
    if oid:
        payload["OriginId"] = oid
    if note:
        payload["Note"] = note
    return payload


def build_person_payload(row: dict[str, Any], origin_by_name: dict[str, Any]) -> dict[str, Any] | None:
    name = person_name(row)
    if not name:
        return None
    payload: dict[str, Any] = {"TypeId": 2, "Name": name}
    email = pick(row, "E-mail - Pessoa", "Email - Pessoa", "E-mail", "Email")
    cpf = only_digits(pick(row, "CPF - Pessoa", "CPF"))
    birthday = normalize_date(pick(row, "Data de nascimento - Pessoa", "Data nascimento - Pessoa"))
    phone = only_digits(pick(row, "Telefones - Pessoa", "Telefone - Pessoa", "Telefones"))
    note = joined_note(
        field_note("Cargo", pick(row, "Cargo - Pessoa")),
        field_note("Departamento", pick(row, "Departamento - Pessoa")),
        field_note("Marcadores", pick(row, "Marcadores - Empresa", "Marcadores")),
        pick(row, "Relação", "Relacao"),
        pick(row, "Observações", "Observacoes"),
    )
    oid = origin_id(row, origin_by_name)
    if email:
        payload["Email"] = email
    if cpf:
        payload["Register"] = cpf
    if birthday:
        payload["Birthday"] = birthday
    if phone:
        payload["Phones"] = [{"PhoneNumber": phone}]
    if oid:
        payload["OriginId"] = oid
    if note:
        payload["Note"] = note
    return payload


def normalize_compare_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return clean(value)


def payload_differs(payload: dict[str, Any], existing: dict[str, Any]) -> bool:
    for key, value in payload.items():
        if key == "Phones":
            continue
        if normalize_compare_value(value) != normalize_compare_value(existing.get(key)):
            return True
    return False


def extract_id(response: dict[str, Any]) -> Any:
    if response.get("Id"):
        return response["Id"]
    values = response.get("value", [])
    if values and values[0].get("Id"):
        return values[0]["Id"]
    return None


def extract_create_date(response: dict[str, Any]) -> str:
    if response.get("CreateDate"):
        return clean(response["CreateDate"])
    values = response.get("value", [])
    if values and values[0].get("CreateDate"):
        return clean(values[0]["CreateDate"])
    return ""


def create_or_update_contact(session: requests.Session, base_url: str, payload: dict[str, Any], finder, compare_before_update: bool = True) -> dict[str, Any]:
    existing = finder(session, base_url, payload)
    if existing:
        existing_create_date = clean(existing.get("CreateDate"))
        if compare_before_update and not payload_differs(payload, existing):
            return {"action": "unchanged", "id": existing.get("Id"), "create_date": existing_create_date, "existing": existing}
        api_request(session, base_url, "PATCH", f"/Contacts({existing['Id']})", payload=payload)
        return {"action": "updated", "id": existing.get("Id"), "create_date": existing_create_date, "existing": existing}
    response = api_request(session, base_url, "POST", "/Contacts", payload=payload)
    contact_id = extract_id(response)
    if not contact_id:
        raise RuntimeError(f"Ploomes criou contato mas não retornou Id: {json.dumps(response, ensure_ascii=False)[:800]}")
    return {"action": "created", "id": contact_id, "create_date": extract_create_date(response), "response": response}


def validate_person_payload(payload: dict[str, Any], kind: str) -> None:
    if payload.get("TypeId") != 2:
        raise RuntimeError("payload de pessoa inválido")
    if kind == "pessoa_fisica_sem_empresa":
        forbidden = {"CompanyId", "LegalName", "CNPJ", "Company"}.intersection(payload.keys())
        if forbidden:
            raise RuntimeError(f"Pessoa física sem empresa recebeu campos proibidos: {sorted(forbidden)}")


def row_to_dict(ws, header_map: dict[str, int], row_idx: int) -> dict[str, Any]:
    row = {}
    for header, col in header_map.items():
        row[header] = ws.cell_value(row_idx, col)
    return row


def eligible_rows(ws, header_map: dict[str, int], args: argparse.Namespace) -> list[int]:
    selected = {int(x.strip()) for x in args.row_numbers.split(',') if x.strip()} if args.row_numbers else None
    header_row, _ = find_header_row(ws)
    rows = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if selected and row_idx not in selected:
            continue
        row = row_to_dict(ws, header_map, row_idx)
        kind = row_kind(row)
        if kind == "ignorar":
            continue
        send_flag = clean(row.get("Enviar ao Ploomes?")).upper()
        status = clean(row.get("Status Importação"))
        if send_flag in NO_FLAGS:
            continue
        if not args.allow_blank_send and send_flag != READY_FLAG:
            continue
        if status == STATUS_SENT and not args.resync_sent:
            continue
        rows.append(row_idx)
    if args.limit is not None:
        return rows[: args.limit]
    return rows


def set_status(ws, header_map: dict[str, int], row_idx: int, *, status: str, company_id: Any = "", person_id: Any = "", error: str = "", company_create_date: str = "", person_create_date: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updates = {
        "Status Importação": status,
        "Erro Importação": error,
        "Última sincronização": now,
    }
    if company_id != "":
        updates["Ploomes Id Empresa"] = company_id
    if person_id != "":
        updates["Ploomes Id Pessoa"] = person_id
    if company_create_date and "Data de criação Empresa" in header_map:
        updates["Data de criação Empresa"] = company_create_date
    if person_create_date and "Data de criação Pessoa" in header_map:
        updates["Data de criação Pessoa"] = person_create_date
    for header, value in updates.items():
        col = header_map.get(header)
        if col:
            ws.set_cell(row_idx, col, value)


def sync(args: argparse.Namespace) -> dict[str, Any]:
    service = gsheets_helper.get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=args.spreadsheet_id, range=args.sheet_name).execute()
    values = result.get("values", [])
    if not values:
        raise SystemExit("Planilha vazia ou aba não encontrada.")
    ws = gsheets_helper.SheetData(values)
    _, headers = find_header_row(ws)
    header_map = {header: idx + 1 for idx, header in enumerate(headers) if header}
    confirm_or_exit(args)
    session = requests.Session()
    session.headers.update({
        "User-Key": args.api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    })
    api_request(session, args.base_url, "GET", "/Contacts", params={"$top": "1", "$select": "Id,Name"})
    origin_by_name = load_origins(session, args.base_url)
    rows = eligible_rows(ws, header_map, args)
    summary = {
        "spreadsheet_id": args.spreadsheet_id,
        "sheet_name": args.sheet_name,
        "rows_selected": rows,
        "processed": 0,
        "sent": 0,
        "errors": 0,
        "companies_created": 0,
        "companies_updated": 0,
        "companies_unchanged": 0,
        "persons_created": 0,
        "persons_updated": 0,
        "persons_unchanged": 0,
        "row_results": [],
    }
    for row_idx in rows:
        row = row_to_dict(ws, header_map, row_idx)
        kind = row_kind(row)
        company_id = ""
        person_id = ""
        company_create_date = ""
        person_create_date = ""
        try:
            company_payload = build_company_payload(row, origin_by_name)
            person_payload = build_person_payload(row, origin_by_name)
            if kind == "pessoa_fisica_sem_empresa" and person_payload:
                validate_person_payload(person_payload, kind)
            company_result = None
            if company_payload:
                company_result = create_or_update_contact(session, args.base_url, company_payload, find_company)
                company_id = company_result.get("id") or ""
                company_create_date = company_result.get("create_date") or ""
                summary[f"companies_{company_result['action']}"] += 1
            person_result = None
            if person_payload:
                if kind == "empresa_com_pessoa":
                    if not company_id:
                        raise RuntimeError("empresa sem Id para vincular pessoa")
                    person_payload = dict(person_payload)
                    person_payload["CompanyId"] = company_id
                validate_person_payload(person_payload, kind)
                person_result = create_or_update_contact(session, args.base_url, person_payload, find_person)
                person_id = person_result.get("id") or ""
                person_create_date = person_result.get("create_date") or ""
                summary[f"persons_{person_result['action']}"] += 1
            set_status(ws, header_map, row_idx, status=STATUS_SENT, company_id=company_id, person_id=person_id, error="", company_create_date=company_create_date, person_create_date=person_create_date)
            summary["processed"] += 1
            summary["sent"] += 1
            summary["row_results"].append({
                "row": row_idx,
                "kind": kind,
                "company": company_name(row),
                "person": person_name(row),
                "company_id": company_id,
                "person_id": person_id,
            })
            time.sleep(args.sleep)
        except Exception as exc:
            summary["processed"] += 1
            summary["errors"] += 1
            set_status(ws, header_map, row_idx, status=STATUS_ERROR, error=str(exc))
            summary["row_results"].append({
                "row": row_idx,
                "kind": kind,
                "company": company_name(row),
                "person": person_name(row),
                "error": str(exc),
            })
    if rows:
        sheet.values().update(
            spreadsheetId=args.spreadsheet_id,
            range=args.sheet_name,
            valueInputOption="USER_ENTERED",
            body={"values": ws.values},
        ).execute()
    return summary


def main() -> int:
    args = parse_args()
    summary = sync(args)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"processed={summary['processed']}")
        print(f"sent={summary['sent']}")
        print(f"errors={summary['errors']}")
        print(f"rows_selected={','.join(map(str, summary['rows_selected']))}")
        print(f"output={summary['output']}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
