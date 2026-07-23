#!/usr/bin/env python3
"""
Lista e remove clientes do tipo Pessoa no Ploomes.

Escopo padrão, em modo seguro:
  1. Lista contatos em Contacts com TypeId=2, que representa Pessoa no Ploomes.
  2. Mostra uma prévia e não apaga nada sem --delete e confirmação.
  3. Permite filtros opcionais por OriginId, e-mail ou texto no nome para reduzir o escopo.

Uso:
  python3 delete_ploomes_pessoas.py
  python3 delete_ploomes_pessoas.py --show 200
  python3 delete_ploomes_pessoas.py --name-contains Maria
  python3 delete_ploomes_pessoas.py --email-contains gmail.com
  python3 delete_ploomes_pessoas.py --origin-id 123
  python3 delete_ploomes_pessoas.py --delete
  python3 delete_ploomes_pessoas.py --delete --yes

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
PERSON_TYPE_ID = 2


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
        description="Lista e exclui clientes do tipo Pessoa no Ploomes."
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
        "--top",
        type=int,
        default=100,
        help="Quantidade por página na listagem. A documentação recomenda páginas de até 100.",
    )
    parser.add_argument(
        "--origin-id",
        type=int,
        default=None,
        help="Filtro remoto opcional por OriginId.",
    )
    parser.add_argument(
        "--email-contains",
        default=None,
        help="Filtro local opcional por trecho no e-mail.",
    )
    parser.add_argument(
        "--name-contains",
        default=None,
        help="Filtro local opcional por trecho no nome da pessoa.",
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


def build_people_filter(origin_id: int | None) -> str:
    checks = [f"TypeId eq {PERSON_TYPE_ID}"]
    if origin_id is not None:
        checks.append(f"OriginId eq {origin_id}")
    return " and ".join(checks)


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


def list_people(base_url: str, api_key: str, filter_expr: str, top: int) -> list[dict[str, Any]]:
    base_url = base_url.rstrip("/")
    query = build_query(
        {
            "$filter": filter_expr,
            "$select": "Id,TypeId,Name,LegalName,CompanyId,Email,OriginId",
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


def normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).casefold()


def apply_local_filters(
    items: list[dict[str, Any]], email_contains: str | None, name_contains: str | None
) -> list[dict[str, Any]]:
    filtered = items
    if email_contains:
        needle = email_contains.casefold()
        filtered = [item for item in filtered if needle in normalized_text(item.get("Email"))]
    if name_contains:
        needle = name_contains.casefold()
        filtered = [item for item in filtered if needle in normalized_text(item.get("Name"))]
    return filtered


def contact_id(item: dict[str, Any]) -> int | None:
    value = item.get("Id")
    return value if isinstance(value, int) else None


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in items:
        origin = str(item.get("OriginId") if item.get("OriginId") is not None else "sem_origin_id")
        summary[origin] = summary.get(origin, 0) + 1
    return dict(sorted(summary.items()))


def print_preview(items: list[dict[str, Any]], show: int) -> None:
    print(f"Clientes pessoa candidatos: {len(items)}")
    print(f"Por OriginId: {summarize(items)}")
    if not items:
        return

    print("Preview:")
    for idx, item in enumerate(items[:show], start=1):
        print(
            f"{idx:>3}. Id={item.get('Id')} | TypeId={item.get('TypeId')} | "
            f"CompanyId={item.get('CompanyId')} | OriginId={item.get('OriginId')} | "
            f"Name={item.get('Name')} | Email={item.get('Email')}"
        )
    if len(items) > show:
        print(f"... +{len(items) - show} itens")


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

    filter_expr = build_people_filter(args.origin_id)
    print(f"Filtro remoto: {filter_expr}")
    if args.email_contains or args.name_contains:
        print(
            "Filtros locais: "
            f"email_contains={args.email_contains!r}, name_contains={args.name_contains!r}"
        )

    try:
        people = list_people(args.base_url, args.api_key, filter_expr, args.top)
        candidates = apply_local_filters(people, args.email_contains, args.name_contains)
    except Exception as exc:
        print(f"Erro na listagem: {exc}", file=sys.stderr)
        return 1

    print_preview(candidates, args.show)
    if args.json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))

    if not args.delete:
        print("Modo leitura. Nada foi apagado. Use --delete para excluir depois de revisar a prévia.")
        return 0

    if not candidates:
        print("Nada para excluir.")
        return 0

    if not args.yes:
        confirm = input("Digite APAGAR para confirmar a exclusão dos clientes pessoa listados: ").strip()
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
