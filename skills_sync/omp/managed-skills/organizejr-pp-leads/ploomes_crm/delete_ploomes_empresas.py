#!/usr/bin/env python3
"""
Lista e remove contatos do Ploomes ligados a empresas com nome exato.

Escopo padrão, em modo seguro:
  1. Encontra empresas em Contacts com TypeId=1 e Name == "Empresa".
  2. Encontra contatos, pessoas ou empresas, cujo CompanyId aponta para essas empresas.
  3. Mostra uma prévia e não apaga nada sem --delete e confirmação.

Uso:
  python3 delete_ploomes_empresas.py
  python3 delete_ploomes_empresas.py --show 200
  python3 delete_ploomes_empresas.py --delete
  python3 delete_ploomes_empresas.py --delete --yes

A chave é lida nesta ordem:
  1. --api-key
  2. variável PLOOMES_API_KEY
  3. arquivo .env com PLOOMES_API_KEY=... ou apenas a chave em texto puro
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api2.ploomes.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


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
    env_key = os.getenv("PLOOMES_API_KEY", "").strip()
    parser = argparse.ArgumentParser(
        description="Lista e exclui contatos do Ploomes vinculados a empresas por Name exato."
    )
    parser.add_argument(
        "--api-key",
        default=env_key or dotenv_api_key(),
        help="API key do Ploomes. Padrão: PLOOMES_API_KEY ou .env.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL da API do Ploomes. Padrão: {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--name",
        default="Empresa",
        help="Valor exato para o campo Name das empresas raiz.",
    )
    parser.add_argument(
        "--legal-name",
        default=None,
        help="Opcional: também considera empresas cujo LegalName tenha este valor exato.",
    )
    parser.add_argument(
        "--type-id",
        type=int,
        default=1,
        help="TypeId usado para identificar empresas raiz. Empresa costuma ser 1.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="Quantidade por página na listagem. A documentação recomenda páginas de até 100.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Executa exclusão. Sem esta flag, roda apenas em modo leitura.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help='Confirma exclusão sem prompt manual ("APAGAR").',
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.12,
        help="Pausa entre requisições destrutivas, em segundos.",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=80,
        help="Máximo de linhas para exibir no preview.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Mostra a lista completa de candidatos em JSON, sem expor a chave.",
    )
    return parser.parse_args()


def odata_escape(value: str) -> str:
    return value.replace("'", "''")


def build_root_company_filter(type_id: int | None, name: str, legal_name: str | None) -> str:
    checks = [f"Name eq '{odata_escape(name)}'"]
    if legal_name is not None:
        checks.append(f"LegalName eq '{odata_escape(legal_name)}'")

    left = f"TypeId eq {type_id} and " if type_id is not None else ""
    if len(checks) == 1:
        return left + checks[0]
    return left + "(" + " or ".join(checks) + ")"


def build_query(params: dict[str, str]) -> str:
    parts = []
    for key, value in params.items():
        encoded = urllib.parse.quote(value, safe="()',$,/")
        parts.append(f"{key}={encoded}")
    return "&".join(parts)


def request_json(url: str, api_key: str, retries: int = 4) -> dict[str, Any]:
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Key": api_key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Resposta não JSON em {url}: {raw[:400]}") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(2**attempt, 12))
                continue
            raise RuntimeError(f"GET {url} -> HTTP {exc.code}: {body[:400]}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(min(2**attempt, 12))
                continue
            raise RuntimeError(f"Falha de rede em {url}: {exc.reason}") from exc

    raise RuntimeError(f"GET {url} falhou após {retries + 1} tentativas")


def delete_resource(url: str, api_key: str) -> tuple[bool, int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Key": api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            code = int(getattr(resp, "status", 204))
            _ = resp.read()
            return code in (200, 202, 204), code, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, exc.code, body[:400]
    except urllib.error.URLError as exc:
        return False, 0, str(exc.reason)


def list_contacts(base_url: str, api_key: str, filter_expr: str, top: int) -> list[dict[str, Any]]:
    base_url = base_url.rstrip("/")
    query = build_query(
        {
            "$filter": filter_expr,
            "$select": "Id,TypeId,Name,LegalName,CompanyId",
            "$top": str(top),
        }
    )
    next_url: str | None = f"{base_url}/Contacts?{query}"
    all_items: list[dict[str, Any]] = []

    while next_url:
        data = request_json(next_url, api_key)
        page = data.get("value", [])
        if isinstance(page, list):
            all_items.extend(page)
        link = data.get("@odata.nextLink")
        if isinstance(link, str) and link.strip():
            next_url = urllib.parse.urljoin(base_url + "/", link.strip())
        else:
            next_url = None
    return all_items


def chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def list_linked_contacts(
    base_url: str, api_key: str, company_ids: list[int], top: int
) -> list[dict[str, Any]]:
    linked: list[dict[str, Any]] = []
    for group in chunks(company_ids, 20):
        filter_expr = " or ".join(f"CompanyId eq {company_id}" for company_id in group)
        linked.extend(list_contacts(base_url, api_key, filter_expr, top))
    return linked


def contact_id(item: dict[str, Any]) -> int | None:
    value = item.get("Id")
    return value if isinstance(value, int) else None


def company_id(item: dict[str, Any]) -> int | None:
    value = item.get("CompanyId")
    return value if isinstance(value, int) else None


def build_candidates(root_companies: list[dict[str, Any]], linked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root_ids = {contact_id(item) for item in root_companies}
    root_ids.discard(None)

    by_id: dict[int, dict[str, Any]] = {}
    for item in root_companies + linked:
        item_id = contact_id(item)
        if item_id is None:
            continue
        current = dict(item)
        reasons: list[str] = []
        if item_id in root_ids:
            reasons.append("empresa_com_nome_exato")
        if company_id(item) in root_ids:
            reasons.append("vinculado_a_empresa_com_nome_exato")
        if not reasons:
            reasons.append("candidato")
        existing = by_id.get(item_id)
        if existing:
            merged = set(existing.get("Reason", []))
            merged.update(reasons)
            existing["Reason"] = sorted(merged)
        else:
            current["Reason"] = sorted(set(reasons))
            by_id[item_id] = current

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        item_id = contact_id(item) or 0
        is_root = 1 if item_id in root_ids else 0
        return is_root, item_id

    return sorted(by_id.values(), key=sort_key)


def print_preview(
    root_companies: list[dict[str, Any]], linked: list[dict[str, Any]], candidates: list[dict[str, Any]], show: int
) -> None:
    type_counts: dict[str, int] = {}
    for item in candidates:
        type_key = str(item.get("TypeId"))
        type_counts[type_key] = type_counts.get(type_key, 0) + 1

    print(f"Empresas raiz encontradas: {len(root_companies)}")
    print(f"Contatos diretamente vinculados a elas: {len(linked)}")
    print(f"Candidatos únicos para exclusão: {len(candidates)}")
    print(f"Candidatos por TypeId: {type_counts}")
    if not candidates:
        return

    print("Preview:")
    for idx, item in enumerate(candidates[:show], start=1):
        reasons = ",".join(item.get("Reason", []))
        print(
            f"{idx:>3}. Id={item.get('Id')} | TypeId={item.get('TypeId')} | "
            f"CompanyId={item.get('CompanyId')} | Reason={reasons} | "
            f"Name={item.get('Name')} | LegalName={item.get('LegalName')}"
        )
    if len(candidates) > show:
        print(f"... +{len(candidates) - show} itens")


def deletion_url(base_url: str, contact: dict[str, Any]) -> str:
    return f"{base_url.rstrip('/')}/Contacts({contact['Id']})"


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("Erro: defina --api-key, PLOOMES_API_KEY ou .env com a chave.", file=sys.stderr)
        return 2

    if args.top < 1 or args.top > 300:
        print("Erro: --top deve ficar entre 1 e 300.", file=sys.stderr)
        return 2

    root_filter = build_root_company_filter(args.type_id, args.name, args.legal_name)
    print(f"Filtro de empresas raiz: {root_filter}")
    print("Filtro de vínculos: CompanyId igual ao Id de cada empresa raiz encontrada")

    try:
        root_companies = list_contacts(args.base_url, args.api_key, root_filter, args.top)
        root_ids = [item_id for item in root_companies if (item_id := contact_id(item)) is not None]
        linked = list_linked_contacts(args.base_url, args.api_key, root_ids, args.top) if root_ids else []
        candidates = build_candidates(root_companies, linked)
    except Exception as exc:
        print(f"Erro na listagem: {exc}", file=sys.stderr)
        return 1

    print_preview(root_companies, linked, candidates, args.show)
    if args.json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))

    if not args.delete:
        print("Modo leitura. Nada foi apagado. Use --delete para excluir depois de revisar a prévia.")
        return 0

    if not candidates:
        print("Nada para excluir.")
        return 0

    if not args.yes:
        confirm = input("Digite APAGAR para confirmar a exclusão dos candidatos listados: ").strip()
        if confirm != "APAGAR":
            print("Cancelado.")
            return 0

    ok = 0
    fail = 0
    for index, item in enumerate(candidates, start=1):
        contact_id_value = contact_id(item)
        if contact_id_value is None:
            fail += 1
            continue
        url = deletion_url(args.base_url, item)
        success, code, body = delete_resource(url, args.api_key)
        if success:
            ok += 1
        else:
            fail += 1
            print(
                f"Falha Id={contact_id_value} HTTP={code} BODY={body}",
                file=sys.stderr,
            )

        if index % 20 == 0 or index == len(candidates):
            print(f"Progresso {index}/{len(candidates)} | ok={ok} | falha={fail}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"Finalizado | total={len(candidates)} | ok={ok} | falha={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
