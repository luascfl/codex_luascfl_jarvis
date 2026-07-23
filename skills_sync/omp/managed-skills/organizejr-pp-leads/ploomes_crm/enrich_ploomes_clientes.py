#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
import gsheets_helper
from update_ploomes_clientes import build_header_map, clean, digits, find_header_row, normalize_website

ENRICH_HEADERS = [
    "Status Enriquecimento",
    "Fontes Enrichment",
    "Resumo Enriquecimento",
    "Link E-mail Pronto",
    "Link WhatsApp Pronto",
    "Último Enrichment",
]
ENRICH_MARKER = "Enriquecimento pp-leads:"
DEFAULT_API_BASE = "http://127.0.0.1:8080"
DEFAULT_API_TIMEOUT = 240
DEFAULT_SPREADSHEET_ID = "1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU"


def progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enriquece leads já enviados ao Ploomes usando o próprio CRM planilhado como base, com fallback opcional ao backend local do pp-leads-brasil.")
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID, help="ID da planilha do Google Sheets.")
    parser.add_argument("--sheet-name", default="Clientes", help="Nome da aba no Google Sheets. Padrão: Clientes.")
    parser.add_argument("--use-case-config", help="Diretório do recorte/ICP usado pelo backend local. Opcional; sem ele o script cai para enriquecimento baseado no CRM.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"Base local da API do pp-leads. Padrão: {DEFAULT_API_BASE}.")
    parser.add_argument("--api-timeout", type=int, default=DEFAULT_API_TIMEOUT, help="Timeout por enriquecimento, em segundos.")
    parser.add_argument("--artifact-dir", help="Diretório opcional para salvar JSONs de enrich. Se omitido, o fluxo canônico usa só Google Sheets.")
    parser.add_argument("--row-numbers", default="", help="Lista opcional de linhas, separadas por vírgula.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de linhas elegíveis.")
    parser.add_argument("--yes", action="store_true", help="Confirma execução real sem prompt.")
    parser.add_argument("--json", action="store_true", help="Imprime resumo em JSON.")
    return parser.parse_args()


def selected_rows_arg(value: str) -> set[int] | None:
    if not value.strip():
        return None
    return {int(item.strip()) for item in value.split(',') if item.strip()}


def ensure_enrichment_headers(ws, header_row: int, header_map: dict[str, int]) -> dict[str, int]:
    max_col = getattr(ws, 'max_col', None)
    if max_col is None:
        max_col = getattr(ws, 'max_column')
    next_col = max_col + 1
    for name in ENRICH_HEADERS:
        if name in header_map:
            continue
        ws.set_cell(header_row, next_col, name)
        header_map[name] = next_col
        next_col += 1
    return header_map


def row_dict(ws, header_map: dict[str, int], row_idx: int) -> dict[str, Any]:
    return {header: ws.cell_value(row_idx, col) for header, col in header_map.items()}


def eligible_rows(ws, header_map: dict[str, int], selected: set[int] | None, limit: int | None) -> list[int]:
    header_row, _ = find_header_row(ws)
    rows = []
    for row_idx in range(header_row + 1, ws.max_row + 1):
        if selected and row_idx not in selected:
            continue
        row = row_dict(ws, header_map, row_idx)
        company = clean(row.get('Razão Social - Empresa'))
        company_id = clean(row.get('Ploomes Id Empresa'))
        status = clean(row.get('Status Importação'))
        if not company or not company_id or status != 'Enviado':
            continue
        rows.append(row_idx)
    return rows[:limit] if limit is not None else rows


def wait_for_api(base_url: str, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    url = base_url.rstrip('/') + '/v1/company/11370755000102'
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code in {200, 400, 404}:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def start_local_api(repo_root: Path, use_case_config: Path | None) -> subprocess.Popen[str] | None:
    if use_case_config is None:
        return None
    if wait_for_api(DEFAULT_API_BASE, 2):
        return None
    env = os.environ.copy()
    if use_case_config.is_dir():
        env['PP_LEADS_ICP_DIR'] = str(use_case_config)
    else:
        env['PP_LEADS_USE_CASE_CONFIG'] = str(use_case_config)
    server_bin = repo_root / 'server_bin'
    if server_bin.exists():
        proc = subprocess.Popen([str(server_bin)], cwd=repo_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    else:
        proc = subprocess.Popen(['go', 'run', './cmd/server'], cwd=repo_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    if not wait_for_api(DEFAULT_API_BASE, 20):
        raise RuntimeError('API local não respondeu a tempo')
    return proc


def normalize_link(value: Any) -> str:
    if isinstance(value, list):
        return clean(value[0]) if value else ''
    return clean(value)


def read_value(ws, header_map: dict[str, int], row_idx: int, header: str) -> Any:
    col = header_map.get(header)
    return ws.cell_value(row_idx, col) if col else ''


def crm_sheet_enrichment(row: dict[str, Any]) -> dict[str, Any]:
    company = clean(row.get('Razão Social - Empresa'))
    cnpj = clean(row.get('CNPJ - Empresa'))
    site = normalize_website(clean(row.get('Site')))
    company_email = clean(row.get('E-mail - Empresa')) or clean(row.get('E-mail do Responsável'))
    person_email = clean(row.get('E-mail - Pessoa'))
    phone = digits(row.get('Telefones - Pessoa'))
    notes = clean(row.get('Observações'))
    company_payload = {
        'name': company,
        'cnpj': cnpj,
        'contacts': {
            'email': company_email,
            'site': site,
        },
        'lead_context': {
            'origem': clean(row.get('Origem - Empresa')),
            'segmento': clean(row.get('Segmento de atuação - Empresa')),
            'marcadores': clean(row.get('Marcadores - Empresa')),
            'observacoes': notes,
            'cidade': clean(row.get('Cidade - Empresa')),
            'estado': clean(row.get('Estado - Empresa')),
        },
    }
    links = {}
    if company_email:
        links['link_email_pronto'] = f"mailto:{company_email}"
    if phone:
        links['link_whatsapp_pronto'] = f"https://wa.me/55{phone}" if not phone.startswith('55') else f"https://wa.me/{phone}"
    return {
        'status': 'enriched-from-crm-sheet',
        'source': 'crm_sheet + direct lookups when available',
        'cnpj': cnpj,
        'company': company_payload,
        'sources_used': ['crm_sheet'],
        'company_goat': {'status': 'skipped'},
        'contact_goat': {'status': 'skipped'},
        'scrape_creators': {'status': 'skipped'},
        'prospecting_links': links,
        'notes': notes,
        'person_email': person_email,
    }


def run_json_command(cmd: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, proc.stderr.strip() or proc.stdout.strip() or f'cmd failed: {cmd[0]}'
    try:
        return json.loads(proc.stdout), None
    except Exception as exc:
        return None, f'json decode error: {exc}'


def enrich_from_direct_tools(row: dict[str, Any]) -> dict[str, Any]:
    payload = crm_sheet_enrichment(row)
    company = clean(row.get('Razão Social - Empresa'))
    site = normalize_website(clean(row.get('Site')))
    domain = re.sub(r'^https?://', '', site).split('/')[0] if site else ''
    if company:
        cmd = ['company-goat-pp-cli', 'snapshot', company, '--agent']
        if domain:
            cmd.extend(['--domain', domain])
        data, err = run_json_command(cmd)
        payload['company_goat'] = {'status': 'ok', 'result': data} if data is not None else {'status': 'error', 'error': err}
        data, err = run_json_command(['contact-goat-pp-cli', 'coverage', company, '--agent', '--limit', '10'])
        payload['contact_goat'] = {'status': 'ok', 'result': data} if data is not None else {'status': 'error', 'error': err}
        payload['sources_used'] = ['crm_sheet', 'company-goat', 'contact-goat']
        payload['status'] = 'enriched-from-crm-sheet-direct'
    return payload


def call_backend_enrich(base_url: str, cnpj: str, timeout_seconds: int) -> dict[str, Any]:
    url = base_url.rstrip('/') + f'/v1/enrich/{cnpj}'
    response = requests.post(url, timeout=timeout_seconds)
    if response.status_code != 200:
        raise RuntimeError(f'POST {url} -> HTTP {response.status_code}: {response.text[:1200]}')
    return response.json()


def enrichment_summary(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    sources = payload.get('sources_used', [])
    sources_text = ', '.join(clean(x) for x in sources if clean(x)) if isinstance(sources, list) else clean(sources)
    company = payload.get('company', {}) if isinstance(payload.get('company'), dict) else {}
    contacts = company.get('contacts', {}) if isinstance(company.get('contacts'), dict) else {}
    company_goat = payload.get('company_goat', {}) if isinstance(payload.get('company_goat'), dict) else {}
    contact_goat = payload.get('contact_goat', {}) if isinstance(payload.get('contact_goat'), dict) else {}
    scrape_creators = payload.get('scrape_creators', {}) if isinstance(payload.get('scrape_creators'), dict) else {}
    links = payload.get('prospecting_links', {}) if isinstance(payload.get('prospecting_links'), dict) else {}
    email_link = normalize_link(links.get('link_email_pronto'))
    whatsapp_link = normalize_link(links.get('link_whatsapp_pronto'))
    summary = ' | '.join(part for part in [
        f"status={clean(payload.get('status'))}",
        f"company-goat={clean(company_goat.get('status'))}",
        f"contact-goat={clean(contact_goat.get('status'))}",
        f"scrape-creators={clean(scrape_creators.get('status'))}",
    ] if part)
    if not email_link and clean(contacts.get('email')):
        email_link = f"mailto:{clean(contacts.get('email'))}"
    return clean(payload.get('status')), sources_text, summary, email_link, whatsapp_link


def enrichment_note(payload: dict[str, Any]) -> str:
    status, sources_text, summary, email_link, whatsapp_link = enrichment_summary(payload)
    company = payload.get('company', {}) if isinstance(payload.get('company'), dict) else {}
    contacts = company.get('contacts', {}) if isinstance(company.get('contacts'), dict) else {}
    lines = [
        ENRICH_MARKER,
        f"Status: {status}" if status else '',
        f"Fontes: {sources_text}" if sources_text else '',
        f"Resumo: {summary}" if summary else '',
        f"E-mail validado: {clean(contacts.get('email'))}" if clean(contacts.get('email')) else '',
        f"Site validado: {clean(contacts.get('site'))}" if clean(contacts.get('site')) else '',
        f"Link e-mail: {email_link}" if email_link else '',
        f"Link WhatsApp: {whatsapp_link}" if whatsapp_link else '',
    ]
    return '\n'.join(line for line in lines if line)


def merge_notes(existing: str, new_block: str) -> str:
    text = clean(existing)
    if ENRICH_MARKER in text:
        text = text.split(ENRICH_MARKER, 1)[0].rstrip()
    if text and new_block:
        return text + '\n\n' + new_block
    return text or new_block


def update_row_from_payload(ws, header_map: dict[str, int], row_idx: int, payload: dict[str, Any]) -> None:
    status, sources_text, summary, email_link, whatsapp_link = enrichment_summary(payload)
    company = payload.get('company', {}) if isinstance(payload.get('company'), dict) else {}
    contacts = company.get('contacts', {}) if isinstance(company.get('contacts'), dict) else {}
    email = clean(contacts.get('email'))
    site = normalize_website(clean(contacts.get('site')))
    updates = {
        'Status Enriquecimento': status,
        'Fontes Enrichment': sources_text,
        'Resumo Enriquecimento': summary,
        'Link E-mail Pronto': email_link,
        'Link WhatsApp Pronto': whatsapp_link,
        'Último Enrichment': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'Observações': merge_notes(read_value(ws, header_map, row_idx, 'Observações'), enrichment_note(payload)),
    }
    if email and not clean(read_value(ws, header_map, row_idx, 'E-mail - Empresa')):
        updates['E-mail - Empresa'] = email
    if site and not clean(read_value(ws, header_map, row_idx, 'Site')):
        updates['Site'] = site
    for header, value in updates.items():
        col = header_map.get(header)
        if col:
            ws.set_cell(row_idx, col, value)


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    use_case_config = Path(args.use_case_config).expanduser().resolve() if args.use_case_config else None
    artifact_dir = (repo_root / args.artifact_dir).resolve() if args.artifact_dir else None
    if not args.yes:
        raise SystemExit('use --yes para executar o enriquecimento real')
    server_proc = start_local_api(repo_root, use_case_config)
    try:
        service = gsheets_helper.get_sheets_service()
        sheet = service.spreadsheets()
        values = sheet.values().get(spreadsheetId=args.spreadsheet_id, range=args.sheet_name).execute().get('values', [])
        if not values:
            raise SystemExit('Planilha vazia ou aba não encontrada.')
        ws = gsheets_helper.SheetData(values)
        header_row, headers = find_header_row(ws)
        header_map = {header: idx + 1 for idx, header in enumerate(headers) if header}
        header_map = ensure_enrichment_headers(ws, header_row, header_map)
        selected = selected_rows_arg(args.row_numbers)
        rows = eligible_rows(ws, header_map, selected, args.limit)
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        results = []
        errors = []
        total = len(rows)
        for idx, row_idx in enumerate(rows, start=1):
            row = row_dict(ws, header_map, row_idx)
            cnpj = digits(row.get('CNPJ - Empresa'))
            company = clean(row.get('Razão Social - Empresa'))
            progress(f'[{idx}/{total}] enriquecendo linha {row_idx} | {company} | {cnpj or "sem-cnpj"}')
            try:
                if use_case_config is not None and cnpj:
                    payload = call_backend_enrich(args.api_base, cnpj, args.api_timeout)
                else:
                    payload = enrich_from_direct_tools(row)
                if artifact_dir is not None:
                    artifact_path = artifact_dir / f"{(cnpj or re.sub(r'[^a-z0-9]+','-', company.casefold()).strip('-') or 'lead')}-enrich.json"
                    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                update_row_from_payload(ws, header_map, row_idx, payload)
                results.append({'row': row_idx, 'company': company, 'status': clean(payload.get('status'))})
            except Exception as exc:
                if header_map.get('Status Enriquecimento'):
                    ws.set_cell(row_idx, header_map['Status Enriquecimento'], 'error')
                if header_map.get('Resumo Enriquecimento'):
                    ws.set_cell(row_idx, header_map['Resumo Enriquecimento'], str(exc))
                if header_map.get('Último Enrichment'):
                    ws.set_cell(row_idx, header_map['Último Enrichment'], time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
                errors.append({'row': row_idx, 'company': company, 'error': str(exc)})
                progress(f'[{idx}/{total}] erro na linha {row_idx}: {exc}')
        sheet.values().update(spreadsheetId=args.spreadsheet_id, range=args.sheet_name, valueInputOption='USER_ENTERED', body={'values': ws.values}).execute()
        summary = {
            'spreadsheet_id': args.spreadsheet_id,
            'sheet_name': args.sheet_name,
            'rows': rows,
            'artifact_dir': str(artifact_dir) if artifact_dir else '',
            'processed': len(rows),
            'succeeded': len(results),
            'errors': len(errors),
            'results': results,
            'error_rows': errors,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else summary)
        return 0 if not errors else 1
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()

if __name__ == '__main__':
    raise SystemExit(main())
