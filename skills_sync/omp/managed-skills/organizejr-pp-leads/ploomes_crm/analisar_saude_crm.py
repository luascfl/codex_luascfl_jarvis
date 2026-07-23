#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import jwt
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU"
SHEET_NAME = "Clientes"

NEW_COLUMNS = [
    "E-mail - Empresa",
    "ICP Considerado",
    "Score ICP (0-10)",
    "Saúde CRM (0-100)",
    "Precisa de enrichment?",
    "Motivos de enrichment",
]
DROP_COLUMNS = ["CPF - Pessoa", "Data de nascimento - Pessoa"]

SCHOOL_TERMS = ["escola", "colegio", "colégio", "creche", "educação", "educacao", "cursinho", "instituto", "faculdade", "universidade"]
COMM_TERMS = ["comunicação", "comunicacao", "jornalismo", "publicidade", "propaganda", "design", "marketing", "audiovisual", "relações públicas", "relacoes publicas", "mídia", "midia"]
EJ_TERMS = ["empresa júnior", "empresa junior", " jr", "júnior", "junior", "ej ", "mej/lead"]
TOPO_TERMS = ["contabilidade", "consultoria", "empresa", "escritório", "escritorio", "rh", "recursos humanos"]


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def norm(value: Any) -> str:
    return clean(value).casefold()


def emailish(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean(value)))


def digits(value: Any) -> str:
    return "".join(ch for ch in clean(value) if ch.isdigit())


def service():
    creds_path = Path('/home/lucas/.config/gcloud/legacy_credentials/gemini-cli-sa@probable-life-428216-k8.iam.gserviceaccount.com/adc.json')
    creds_json = json.loads(creds_path.read_text())
    now = int(time.time())
    claims = {
        'iss': creds_json['client_email'],
        'scope': 'https://www.googleapis.com/auth/spreadsheets',
        'aud': creds_json['token_uri'],
        'exp': now + 3600,
        'iat': now,
    }
    token = jwt.encode(claims, creds_json['private_key'], algorithm='RS256')
    access_token = requests.post(
        creds_json['token_uri'],
        data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': token},
        timeout=60,
    ).json()['access_token']
    return build('sheets', 'v4', credentials=Credentials(access_token))


def sheet_values(svc, spreadsheet_id: str, sheet_name: str):
    return svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute().get('values', [])


def delete_columns(svc, spreadsheet_id: str, sheet_name: str, headers: list[str]):
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet = next(s for s in meta['sheets'] if s['properties']['title'] == sheet_name)
    sheet_id = sheet['properties']['sheetId']
    positions = [headers.index(name) for name in DROP_COLUMNS if name in headers]
    for idx in sorted(positions, reverse=True):
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [{'deleteDimension': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': idx, 'endIndex': idx + 1}}}]},
        ).execute()
        del headers[idx]
    return headers


def ensure_columns(headers: list[str]) -> list[str]:
    for name in NEW_COLUMNS:
        if name not in headers:
            headers.append(name)
    return headers


def kind(row: dict[str, str]) -> str:
    company = clean(row.get('Razão Social - Empresa'))
    person = clean(row.get('Nome - Pessoa'))
    if company and person:
        return 'empresa_com_pessoa'
    if company:
        return 'empresa_sem_pessoa'
    if person:
        return 'pessoa_sem_empresa'
    return 'ignorar'


def infer_icp(row: dict[str, str]) -> tuple[str, float]:
    text = ' '.join(clean(row.get(k)) for k in row).casefold()
    company = norm(row.get('Razão Social - Empresa'))
    segment = norm(row.get('Segmento de atuação - Empresa'))
    markers = norm(row.get('Marcadores - Empresa'))
    has_school = any(term in text for term in SCHOOL_TERMS)
    has_comm = any(term in text for term in COMM_TERMS)
    has_ej = any(term in text or term in company or term in markers for term in EJ_TERMS)
    has_topo = any(term in text or term in segment for term in TOPO_TERMS)
    score = 0.0
    label = 'Sem ICP válido'
    if has_school:
        label = 'Base | Educação e capacitação'
        score = 6.5
        if clean(row.get('Cidade - Empresa')): score += 0.8
        if emailish(row.get('E-mail - Empresa')) or emailish(row.get('E-mail do Responsável')): score += 1.0
        if clean(row.get('Observações')): score += 0.7
        if clean(row.get('Site')): score += 0.5
    elif has_ej and has_comm:
        label = 'Meio | EJ de comunicação'
        score = 7.0
        if clean(row.get('CNPJ - Empresa')): score += 0.7
        if clean(row.get('Site')): score += 0.6
        if emailish(row.get('E-mail - Empresa')) or emailish(row.get('E-mail do Responsável')): score += 0.9
        if clean(row.get('Observações')): score += 0.8
    elif has_ej:
        label = 'Meio | EJ de alta demanda operacional'
        score = 6.2
        if clean(row.get('CNPJ - Empresa')): score += 0.8
        if clean(row.get('Site')): score += 0.6
        if emailish(row.get('E-mail - Empresa')) or emailish(row.get('E-mail do Responsável')): score += 0.8
        if clean(row.get('Observações')): score += 0.6
    elif clean(row.get('Razão Social - Empresa')) and has_topo:
        label = 'Topo | Mercado sênior'
        score = 5.8
        if clean(row.get('CNPJ - Empresa')): score += 1.0
        if clean(row.get('Site')): score += 0.7
        if emailish(row.get('E-mail - Empresa')) or emailish(row.get('E-mail do Responsável')): score += 0.8
        if clean(row.get('Observações')): score += 0.5
    return label, round(min(score, 10.0), 1)


def health(row: dict[str, str], icp_label: str) -> tuple[int, str, str]:
    problems = []
    score = 100
    row_kind = kind(row)
    company = clean(row.get('Razão Social - Empresa'))
    person = clean(row.get('Nome - Pessoa'))
    company_email = clean(row.get('E-mail - Empresa'))
    person_email = clean(row.get('E-mail - Pessoa'))
    responsible_email = clean(row.get('E-mail do Responsável'))
    phone = digits(row.get('Telefones - Pessoa'))
    site = clean(row.get('Site'))
    cnpj = digits(row.get('CNPJ - Empresa'))
    company_id = clean(row.get('Ploomes Id Empresa'))
    person_id = clean(row.get('Ploomes Id Pessoa'))
    obs = clean(row.get('Observações'))

    if row_kind == 'ignorar':
        return 0, 'SIM', 'sem empresa ou pessoa'
    if company and not cnpj:
        score -= 12
        problems.append('sem CNPJ da empresa')
    if company and not site:
        score -= 8
        problems.append('sem site da empresa')
    if company and not (emailish(company_email) or emailish(responsible_email)):
        score -= 12
        problems.append('sem e-mail da empresa')
    if person and not emailish(person_email):
        score -= 10
        problems.append('sem e-mail da pessoa')
    if not phone:
        score -= 10
        problems.append('sem telefone')
    if row_kind == 'empresa_sem_pessoa':
        score -= 18
        problems.append('empresa sem pessoa vinculada')
    if not obs:
        score -= 8
        problems.append('sem observações')
    if company and not company_id:
        score -= 15
        problems.append('empresa sem ID do Ploomes')
    if person and not person_id:
        score -= 15
        problems.append('pessoa sem ID do Ploomes')
    if icp_label == 'Sem ICP válido':
        score -= 15
        problems.append('sem ICP válido')
    score = max(0, score)
    need = 'SIM' if score < 75 or problems else 'NÃO'
    return score, need, '; '.join(problems)


def main():
    ap = argparse.ArgumentParser(description='Analisa a saúde do CRM direto no Google Sheets.')
    ap.add_argument('--spreadsheet-id', default=SPREADSHEET_ID)
    ap.add_argument('--sheet-name', default=SHEET_NAME)
    args = ap.parse_args()
    svc = service()
    values = sheet_values(svc, args.spreadsheet_id, args.sheet_name)
    if not values:
        raise SystemExit('Planilha vazia ou aba não encontrada.')
    headers = values[0]
    headers = delete_columns(svc, args.spreadsheet_id, args.sheet_name, headers)
    values = sheet_values(svc, args.spreadsheet_id, args.sheet_name)
    headers = ensure_columns(values[0])
    rows = values[1:]
    idx = {h:i for i,h in enumerate(headers)}
    out = [headers]
    for raw in rows:
        row = {h: (raw[i] if i < len(raw) else '') for h,i in idx.items() if h not in NEW_COLUMNS}
        kind_value = kind(row)
        company_email = clean(row.get('E-mail - Empresa'))
        responsible_email = clean(row.get('E-mail do Responsável'))
        person_email = clean(row.get('E-mail - Pessoa'))
        if kind_value in {'empresa_sem_pessoa','empresa_com_pessoa'} and not emailish(company_email) and emailish(responsible_email):
            row['E-mail - Empresa'] = responsible_email
        else:
            row['E-mail - Empresa'] = company_email
        if kind_value in {'empresa_com_pessoa','pessoa_sem_empresa'} and not emailish(person_email) and emailish(responsible_email):
            row['E-mail - Pessoa'] = responsible_email
        icp_label, icp_score = infer_icp(row)
        crm_health, need_enrichment, reasons = health(row, icp_label)
        final_row = []
        for h in headers:
            if h == 'E-mail - Empresa':
                final_row.append(row.get('E-mail - Empresa',''))
            elif h == 'E-mail - Pessoa':
                final_row.append(row.get('E-mail - Pessoa',''))
            elif h == 'ICP Considerado':
                final_row.append(icp_label)
            elif h == 'Score ICP (0-10)':
                final_row.append(f'{icp_score:.1f}')
            elif h == 'Saúde CRM (0-100)':
                final_row.append(str(crm_health))
            elif h == 'Precisa de enrichment?':
                final_row.append(need_enrichment)
            elif h == 'Motivos de enrichment':
                final_row.append(reasons)
            else:
                i = idx.get(h)
                final_row.append(raw[i] if i is not None and i < len(raw) else '')
        out.append(final_row)
    svc.spreadsheets().values().update(
        spreadsheetId=args.spreadsheet_id,
        range=args.sheet_name,
        valueInputOption='USER_ENTERED',
        body={'values': out}
    ).execute()
    print(json.dumps({'rows_updated': len(rows), 'headers': headers}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
