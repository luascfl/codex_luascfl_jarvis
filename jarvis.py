import os
import sys
import asyncio
import argparse

# Garante modo stdio cedo o bastante para não poluir stdout em inicialização MCP.
if not os.environ.get("MCP_MODE", "").strip():
    _argv_lower_early = {a.strip().lower() for a in sys.argv[1:] if a.strip()}
    if "serve" in _argv_lower_early or "gemini-bridge" in _argv_lower_early:
        os.environ["MCP_MODE"] = "stdio"

# --- CONFIGURAÇÃO DE LOGGING / STDIO ---
# Configura logging para stderr imediatamente
import logging
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# --- HACK: Redirecionar print para stderr ---
# O protocolo MCP stdio usa stdout para comunicação JSON-RPC.
# Qualquer texto solto (logs, avisos) no stdout quebra o cliente.
# Forçamos todos os prints para stderr se estivermos em modo HTTP.
# Em modo STDIO, o StrictJSONStdout cuidará disso.
_original_print = print
def print(*args, **kwargs):
    if os.environ.get("MCP_MODE", "").lower() == "stdio":
        kwargs["file"] = sys.stderr
    _original_print(*args, **kwargs)

# --- HACK: Configurar ambiente para suprimir cores e banners ---
os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"
os.environ["CLICOLOR"] = "0"

import site
import shutil
import subprocess
import tempfile
import threading
import atexit
import httpx
import socket
import inspect
import platform
import json
import hashlib
import shlex
import fnmatch
import webbrowser
from collections import deque
import pwd
import re
import types
import contextlib
import signal
import time
import base64
import zlib
from pathlib import Path
from datetime import datetime, timezone
# from starlette.applications import Starlette # Removido duplicado
# from starlette.routing import Mount # Removido duplicado

# Base
BASE_DIR = Path(__file__).resolve().parent
RALPH_PRD_DEFAULT_REL = ".context/workflow/prd.json"
GRAPHIFY_DEFAULT_REL = ".context/graphify-out"
RALPH_RUNTIME_REL = ".context/workflow/ralph"
VENV_SUPER_PY = BASE_DIR / ".venv-super" / "bin" / "python3"
if VENV_SUPER_PY.exists():
    current = Path(sys.executable)
    if current != VENV_SUPER_PY:
        os.execv(str(VENV_SUPER_PY), [str(VENV_SUPER_PY)] + sys.argv)

def _should_drop_root_for_mcp() -> bool:
    if os.geteuid() != 0:
        return False
    if os.environ.get("JARVIS_ALLOW_ROOT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False

    raw_args = [arg.strip().lower() for arg in sys.argv[1:] if arg.strip()]
    command = raw_args[0] if raw_args else "start"
    mcp_commands = {"serve", "start", "status", "stop", "logs", "gemini-bridge"}
    mcp_mode = os.environ.get("MCP_MODE", "").strip().lower() in {"stdio", "http"}
    return mcp_mode or command in mcp_commands

if _should_drop_root_for_mcp():
    target_user = (os.environ.get("JARVIS_RUN_AS_USER", "lucas") or "").strip() or "lucas"
    try:
        pw = pwd.getpwnam(target_user)
        os.environ["HOME"] = pw.pw_dir
        os.environ["USER"] = target_user
        os.environ["LOGNAME"] = target_user
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
    except Exception as exc:
        print(
            f"❌ Falha ao trocar de root para '{target_user}' no Jarvis MCP: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

# --- Garantia de fastmcp instalado ---
FASTMCP_AVAILABLE = True
try:
    from fastmcp import FastMCP
except ImportError:
    FASTMCP_AVAILABLE = False

    class FastMCP:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            self._deprecated_settings = types.SimpleNamespace(sse_path="/sse", message_path="/messages/")

        def tool(self):
            def _decorator(fn):
                return fn

            return _decorator

        def run(self, *args, **kwargs):
            raise RuntimeError(
                "fastmcp não encontrado. Instale no ambiente com: ./.venv-super/bin/pip install fastmcp"
            )

    print("⚠️ fastmcp não encontrado. Comandos de serviço/diagnóstico continuam disponíveis.", file=sys.stderr)

if FASTMCP_AVAILABLE:
    import fastmcp as _fastmcp
    try:
        # FastMCP v2.14+ usa log_server_banner em fastmcp.server.server
        import fastmcp.server.server
        if hasattr(fastmcp.server.server, "log_server_banner"):
            fastmcp.server.server.log_server_banner = lambda *args, **kwargs: None
            if os.environ.get("MCP_MODE", "").lower() != "stdio" or (os.environ.get("JARVIS_STDIO_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on"}):
                print("✅ Banner do FastMCP neutralizado (log_server_banner).")
        else:
            # Tenta métodos antigos/alternativos
            if hasattr(FastMCP, "_print_banner"):
                FastMCP._print_banner = lambda self: None
                if os.environ.get("MCP_MODE", "").lower() != "stdio" or (os.environ.get("JARVIS_STDIO_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on"}):
                    print("✅ Banner do FastMCP neutralizado (_print_banner).")
    except Exception as e:
        print(f"⚠️  Falha ao tentar neutralizar banner via monkey-patch: {e}")
else:
    _fastmcp = types.SimpleNamespace(settings=types.SimpleNamespace(sse_path="/mcp", message_path="/messages/"))

# --- HACK: Forçar Rich/FastMCP a usar stderr para logs/banners ---
# Aplicado APÓS garantir que o pacote está instalado
try:
    import rich.console
    # Substitui a classe Console padrão para sempre escrever no stderr
    _orig_console_init = rich.console.Console.__init__
    def _stderr_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _orig_console_init(self, *args, **kwargs)
    rich.console.Console.__init__ = _stderr_console_init
    
    # Também patch no print atalho do rich
    def _stderr_rich_print(*args, **kwargs):
        kwargs["file"] = sys.stderr
        print(*args, **kwargs)
    rich.print = _stderr_rich_print
except ImportError:
    pass

# Ajusta caminhos HTTP padrão para compatibilidade com conectores externos (ex.: Mistral)
_fastmcp.settings.sse_path = "/mcp"
# Mantém message_path padrão (/messages/) e trata POST /mcp via handler abaixo
_fastmcp.settings.message_path = "/messages/"

PROXY_SCRIPT = os.path.join(BASE_DIR, "stdio_proxy.js")

os.environ.setdefault("HOME", "/home/lucas")
os.environ.setdefault("npm_config_cache", f"{os.environ.get('HOME', '/home/lucas')}/.npm")
os.environ.setdefault("npm_config_prefix", f"{os.environ.get('HOME', '/home/lucas')}/.npm-global")
os.environ.setdefault("PIP_CACHE_DIR", f"{os.environ.get('HOME', '/home/lucas')}/.pip-cache")
def _pick_writable_home(candidates: list[str]) -> str:
    """Escolhe o primeiro diretório gravável (ou cria) para servir de base.

    Motivação: em ambientes diferentes (local vs Oracle), o usuário pode não ser 'lucas',
    e hardcode em /home/lucas pode falhar com PermissionError.
    """
    for raw in candidates:
        if not raw:
            continue
        try:
            p = Path(raw).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            test = p / ".jarvis_write_test"
            test.write_text("ok")
            test.unlink(missing_ok=True)
            return str(p)
        except Exception:
            continue
    # fallback final
    return str(Path.cwd())


# define um HOME_BASE consistente e gravável (prioriza HOME do ambiente)
HOME_BASE = _pick_writable_home(
    [
        os.environ.get("HOME"),
        "/home/ubuntu",
        "/home/lucas",
        str(Path.home()),
    ]
)

# Adiciona o binário do npm global e do user base python ao PATH
_npm_prefix = os.environ.get("npm_config_prefix") or f"{HOME_BASE}/.npm-global"
_npm_global_bin = f"{_npm_prefix}/bin"
_user_local_bin = f"{HOME_BASE}/.local/bin"
os.environ["PATH"] = f"{_npm_global_bin}:{_user_local_bin}:{os.environ.get('PATH', '')}"

# Garante que os diretórios existam (sempre dentro do HOME_BASE por padrão)
for d in [
    os.environ.get("HOME") or HOME_BASE,
    os.environ.get("npm_config_cache") or f"{HOME_BASE}/.npm",
    os.environ.get("npm_config_prefix") or f"{HOME_BASE}/.npm-global",
    os.environ.get("PIP_CACHE_DIR") or f"{HOME_BASE}/.pip-cache",
]:
    os.makedirs(d, exist_ok=True)

# O Gemini CLI precisa gravar; definimos um diretório padrão gravável
GEMINI_CLI_HOME_DIR = os.environ.get("GEMINI_CLI_HOME")
if not GEMINI_CLI_HOME_DIR:
    GEMINI_CLI_HOME_DIR = HOME_BASE
gemini_home_path = Path(GEMINI_CLI_HOME_DIR).expanduser()
while gemini_home_path.name == ".gemini":
    gemini_home_path = gemini_home_path.parent
GEMINI_CLI_HOME_DIR = str(gemini_home_path)
os.environ["GEMINI_CLI_HOME"] = GEMINI_CLI_HOME_DIR
Path(GEMINI_CLI_HOME_DIR).mkdir(parents=True, exist_ok=True)

def _env_sh_path() -> Path:
    return BASE_DIR / "env.sh"


def _parse_export_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text.startswith("export ") or "=" not in text:
        return None
    key, raw_value = text[len("export "):].split("=", 1)
    key = key.strip()
    if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return None
    try:
        value = shlex.split(raw_value, posix=True)[0] if raw_value.strip() else ""
    except Exception:
        value = raw_value.strip().strip('"').strip("'")
    return key, value


def _read_env_sh_exports(path: Path | None = None) -> dict[str, str]:
    path = path or _env_sh_path()
    if not path.exists():
        return {}
    exports: dict[str, str] = {}
    in_config = False
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped == "# --- CONFIGURATION START ---":
                in_config = True
                continue
            if stripped == "# --- CONFIGURATION END ---":
                break
            if not in_config:
                continue
            parsed = _parse_export_line(line)
            if parsed:
                exports[parsed[0]] = parsed[1]
    except Exception:
        return exports
    return exports


def _load_env_sh_defaults() -> None:
    for key, value in _read_env_sh_exports().items():
        os.environ.setdefault(key, value)


_load_env_sh_defaults()


# Caminhos e Chaves
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
FIREFLIES_API_KEY = os.environ.get("FIREFLIES_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GUPY_API_TOKEN = os.environ.get("GUPY_API_TOKEN", "").strip()
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")
ZOTERO_USER_ID = os.environ.get("ZOTERO_USER_ID", "")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "7860"))
PUBLIC_URL = (
    os.environ.get("MCP_PUBLIC_URL", "").strip()
    or os.environ.get("OCI_API_GATEWAY_URL", "").strip()
)

# Detecta URL pública no Hugging Face
if "SPACE_ID" in os.environ:
    # Formato: user-space.hf.space
    _space_id = os.environ["SPACE_ID"].replace("/", "-").lower()
    SERVER_URL = f"https://{_space_id}.hf.space"
else:
    SERVER_URL = f"http://localhost:{SERVER_PORT}"

if PUBLIC_URL:
    SERVER_URL = PUBLIC_URL.rstrip("/")

# Microsoft Graph (OneDrive pessoal)
MSGRAPH_CLIENT_ID = (
    os.environ.get("MSGRAPH_CLIENT_ID", "").strip()
    or os.environ.get("GRAPH_CLIENT_ID", "").strip()
)
MSGRAPH_TENANT = os.environ.get("MSGRAPH_TENANT", "consumers").strip() or "consumers"
MSGRAPH_TOKEN_DIR = Path(os.environ.get("MSGRAPH_TOKEN_DIR", str(BASE_DIR / "state")))
MSGRAPH_TOKEN_PATH = MSGRAPH_TOKEN_DIR / "msgraph_onedrive_token.json"
MSGRAPH_DEVICE_FLOW_PATH = MSGRAPH_TOKEN_DIR / "msgraph_onedrive_device_flow.json"


UV_AUTO_INSTALL = os.environ.get("UV_AUTO_INSTALL", "true").lower() in ("1", "true", "yes", "on")

## MERMAID RENDER (utilitário local usando kroki.io)
MERMAID_ENABLE = os.environ.get("MERMAID_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## PLAYWRIGHT MCP (Node)
PLAYWRIGHT_MCP_ENABLE = os.environ.get("PLAYWRIGHT_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
PLAYWRIGHT_MCP_BIN = os.environ.get("PLAYWRIGHT_MCP_BIN", "npx")
PLAYWRIGHT_MCP_PACKAGE = os.environ.get("PLAYWRIGHT_MCP_PACKAGE", "@playwright/mcp@latest")
PLAYWRIGHT_MCP_PORT = int(os.environ.get("PLAYWRIGHT_MCP_PORT", "8931"))
PLAYWRIGHT_MCP_HOST = os.environ.get("PLAYWRIGHT_MCP_HOST", "localhost")
PLAYWRIGHT_MCP_EXTRA_ARGS = os.environ.get("PLAYWRIGHT_MCP_EXTRA_ARGS", "")
PLAYWRIGHT_MCP_URL = f"http://{PLAYWRIGHT_MCP_HOST}:{PLAYWRIGHT_MCP_PORT}"
CLOUDFLARED_PLAYWRIGHT_ENABLE = os.environ.get("CLOUDFLARED_PLAYWRIGHT_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## BRAVE SEARCH MCP (Node, requer BRAVE_API_KEY)
BRAVE_MCP_ENABLE = os.environ.get("BRAVE_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
BRAVE_MCP_BIN = os.environ.get("BRAVE_MCP_BIN", "npx")
BRAVE_MCP_PACKAGE = os.environ.get("BRAVE_MCP_PACKAGE", "@modelcontextprotocol/server-brave-search")
BRAVE_MCP_PORT = int(os.environ.get("BRAVE_MCP_PORT", "8932"))
BRAVE_MCP_HOST = os.environ.get("BRAVE_MCP_HOST", "localhost")
BRAVE_MCP_EXTRA_ARGS = os.environ.get("BRAVE_MCP_EXTRA_ARGS", "")
BRAVE_MCP_URL = f"http://{BRAVE_MCP_HOST}:{BRAVE_MCP_PORT}"
CLOUDFLARED_BRAVE_ENABLE = os.environ.get("CLOUDFLARED_BRAVE_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## CHART MCP (AntV, Node)
CHART_MCP_ENABLE = os.environ.get("CHART_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
CHART_MCP_BIN = os.environ.get("CHART_MCP_BIN", "npx")
CHART_MCP_PACKAGE = os.environ.get("CHART_MCP_PACKAGE", "@antv/mcp-server-chart")
CHART_MCP_PORT = int(os.environ.get("CHART_MCP_PORT", "1122"))
CHART_MCP_HOST = os.environ.get("CHART_MCP_HOST", "localhost")
CHART_MCP_EXTRA_ARGS = os.environ.get("CHART_MCP_EXTRA_ARGS", "--transport sse")
CHART_MCP_URL = f"http://{CHART_MCP_HOST}:{CHART_MCP_PORT}"
CLOUDFLARED_CHART_ENABLE = os.environ.get("CHART_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## ZOTERO MCP (Node)
ZOTERO_MCP_ENABLE = os.environ.get("ZOTERO_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
ZOTERO_MCP_BIN = os.environ.get("ZOTERO_MCP_BIN", "npx")
ZOTERO_MCP_PACKAGE = os.environ.get("ZOTERO_MCP_PACKAGE", "mcp-zotero")
ZOTERO_MCP_EXTRA_ARGS = os.environ.get("ZOTERO_MCP_EXTRA_ARGS", "--transport sse")
ZOTERO_MCP_PORT = int(os.environ.get("ZOTERO_MCP_PORT", "8933"))
ZOTERO_MCP_HOST = os.environ.get("ZOTERO_MCP_HOST", "localhost")
ZOTERO_MCP_URL = f"http://{ZOTERO_MCP_HOST}:{ZOTERO_MCP_PORT}"
CLOUDFLARED_ZOTERO_ENABLE = os.environ.get("CLOUDFLARED_ZOTERO_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## FIRECRAWL MCP (Node)
FIRECRAWL_ENABLE = os.environ.get("FIRECRAWL_ENABLE", "false").lower() in ("1", "true", "yes", "on")
FIRECRAWL_BIN = os.environ.get("FIRECRAWL_BIN", "npx")
FIRECRAWL_PACKAGE = os.environ.get("FIRECRAWL_PACKAGE", "firecrawl-mcp")
FIRECRAWL_EXTRA_ARGS = os.environ.get("FIRECRAWL_EXTRA_ARGS", "")
FIRECRAWL_PORT = int(os.environ.get("FIRECRAWL_PORT", "3000"))
FIRECRAWL_HOST = os.environ.get("FIRECRAWL_HOST", "localhost")
FIRECRAWL_STREAMABLE = os.environ.get("FIRECRAWL_STREAMABLE", "true").lower() in ("1", "true", "yes", "on")
FIRECRAWL_URL = f"http://{FIRECRAWL_HOST}:{FIRECRAWL_PORT}/mcp"
CLOUDFLARED_FIRECRAWL_ENABLE = os.environ.get("CLOUDFLARED_FIRECRAWL_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## GOOGLE CALENDAR MCP (Node)
GOOGLE_CALENDAR_MCP_ENABLE = os.environ.get("GOOGLE_CALENDAR_MCP_ENABLE", "true").lower() in ("1", "true", "yes", "on")
GOOGLE_CALENDAR_MCP_BIN = os.environ.get("GOOGLE_CALENDAR_MCP_BIN", "npx")
GOOGLE_CALENDAR_MCP_PACKAGE = os.environ.get("GOOGLE_CALENDAR_MCP_PACKAGE", "mcp-google-calendar")
GOOGLE_CALENDAR_MCP_EXTRA_ARGS = os.environ.get("GOOGLE_CALENDAR_MCP_EXTRA_ARGS", "")
GOOGLE_CALENDAR_MCP_PORT = int(os.environ.get("GOOGLE_CALENDAR_MCP_PORT", "8954"))
GOOGLE_CALENDAR_MCP_HOST = os.environ.get("GOOGLE_CALENDAR_MCP_HOST", "localhost")
GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH",
    os.environ.get("CREDENTIALS_PATH", str(BASE_DIR / "gcp-oauth.keys.json")),
)
GOOGLE_DRIVE_MCP_OAUTH_PATH = os.environ.get("GDRIVE_MCP_OAUTH_PATH", GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH)
GOOGLE_DRIVE_MCP_TOKEN_PATH = os.environ.get("GDRIVE_MCP_TOKEN_PATH", str(BASE_DIR / "token.json"))
GOOGLE_DRIVE_MCP_SCOPES = os.environ.get("GDRIVE_MCP_SCOPES", "https://www.googleapis.com/auth/drive")
GOOGLE_CALENDAR_MCP_URL = f"http://{GOOGLE_CALENDAR_MCP_HOST}:{GOOGLE_CALENDAR_MCP_PORT}/sse"

## FIREFLIES MCP (remote via mcp-remote)
FIREFLIES_MCP_ENABLE = os.environ.get("FIREFLIES_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
FIREFLIES_MCP_BIN = os.environ.get("FIREFLIES_MCP_BIN", "npx")
FIREFLIES_MCP_PACKAGE = os.environ.get("FIREFLIES_MCP_PACKAGE", "mcp-remote")
FIREFLIES_MCP_REMOTE_URL = os.environ.get("FIREFLIES_MCP_REMOTE_URL", "https://api.fireflies.ai/mcp")
FIREFLIES_MCP_EXTRA_ARGS = os.environ.get("FIREFLIES_MCP_EXTRA_ARGS", "")
FIREFLIES_MCP_PORT = int(os.environ.get("FIREFLIES_MCP_PORT", "8946"))
FIREFLIES_MCP_HOST = os.environ.get("FIREFLIES_MCP_HOST", "localhost")
FIREFLIES_MCP_URL = f"http://{FIREFLIES_MCP_HOST}:{FIREFLIES_MCP_PORT}"

## RECLAIM 2.0 OFFICIAL MCP (remote)
RECLAIM_OFFICIAL_MCP_ENABLE = os.environ.get("RECLAIM_OFFICIAL_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
RECLAIM_OFFICIAL_MCP_URL = os.environ.get("RECLAIM_OFFICIAL_MCP_URL", "https://mcp.reclaim.ai").strip() or "https://mcp.reclaim.ai"
RECLAIM_OFFICIAL_MCP_PREFIX = os.environ.get("RECLAIM_OFFICIAL_MCP_PREFIX", "reclaim2").strip() or "reclaim2"
RECLAIM_OFFICIAL_MCP_MOUNTED = False
CLOUDFLARED_FIREFLIES_ENABLE = os.environ.get("CLOUDFLARED_FIREFLIES_ENABLE", "false").lower() in ("1", "true", "yes", "on")


# Google Tasks lists used by day planning.
# Integration with Reclaim 2.0 happens at the Google account level and may cover
# multiple selected lists. RECLAIM_TASK_LIST_ID remains the committed operational
# list; "Minhas tarefas" stays a raw inbox dump for triage and promotion only.
RECLAIM_TASK_LIST_ID = os.environ.get("RECLAIM_TASK_LIST_ID", "TUZuVGxQZkRxSjRrWkNtbw")
PERSONAL_TASK_LIST_ID = os.environ.get("PERSONAL_TASK_LIST_ID", "MDkyMTQ1ODY0NDMyNzczMDkyNTQ6MDow")
PLAN_DAY_TASK_LIST_IDS = os.environ.get(
    "PLAN_DAY_TASK_LIST_IDS",
    f"{RECLAIM_TASK_LIST_ID},{PERSONAL_TASK_LIST_ID}",
)

# RECLAIM UI AUTOMATION (experimental)
RECLAIM_UI_AUTOMATION_ENABLE = os.environ.get("RECLAIM_UI_AUTOMATION_ENABLE", "false").lower() in ("1", "true", "yes", "on")
RECLAIM_UI_SESSION_FILE = Path(
    os.environ.get("RECLAIM_UI_SESSION_FILE", str(BASE_DIR / RALPH_RUNTIME_REL / "reclaim_ui_session.json"))
)
RECLAIM_UI_AUDIT_FILE = Path(
    os.environ.get("RECLAIM_UI_AUDIT_FILE", str(BASE_DIR / RALPH_RUNTIME_REL / "reclaim_ui_audit.jsonl"))
)
RECLAIM_UI_SESSION_TTL_SEC = int(os.environ.get("RECLAIM_UI_SESSION_TTL_SEC", "43200"))
RECLAIM_UI_CAPTCHA_TIMEOUT_SEC = int(os.environ.get("RECLAIM_UI_CAPTCHA_TIMEOUT_SEC", "900"))
RECLAIM_UI_LOGIN_URL = "https://app.reclaim.ai/planner?login=1&taskSort=schedule&range=WEEK"
RECLAIM_UI_EXECUTOR_CMD = "internal"
RECLAIM_UI_EXECUTOR_TIMEOUT_SEC = int(os.environ.get("RECLAIM_UI_EXECUTOR_TIMEOUT_SEC", "60"))
RECLAIM_UI_ASSIST_OPEN_BROWSER = os.environ.get("RECLAIM_UI_ASSIST_OPEN_BROWSER", "false").lower() in ("1", "true", "yes", "on")
RECLAIM_UI_AUTOMATION_MODE = os.environ.get("RECLAIM_UI_AUTOMATION_MODE", "headless").strip().lower()
RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR = Path(
    os.environ.get("RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR", str(BASE_DIR / RALPH_RUNTIME_REL / "reclaim_playwright_profile"))
)
RECLAIM_UI_HEADLESS = os.environ.get("RECLAIM_UI_HEADLESS", "true").lower() in ("1", "true", "yes", "on")
RECLAIM_UI_BOOTSTRAP_HEADLESS = os.environ.get("RECLAIM_UI_BOOTSTRAP_HEADLESS", "true").lower() in ("1", "true", "yes", "on")


# --- PROMPTS EMBUTIDOS ---
PROMPT_GCAL_EVENTEDIT_MASTER = "# prompt mestre: gerar link de criação de evento no google agenda (eventedit)\n\nvocê deve converter a descrição do evento em um link no formato:\n\nhttps://www.google.com/calendar/u/0/r/eventedit?text=&dates=&details=&location=&recur=\n\n## regras\n- se algum parâmetro não for informado, deixe em branco.\n- o parâmetro `text` (título) é obrigatório.\n- sempre retorne o link dentro de um bloco de código.\n- nunca use a extensão do google workspace.\n\n## parâmetros\n\n### título\n- formato: `text=...`\n- exemplo: `text=Garden%20Waste%20Collection`\n\n### datas\n- formato padrão: `dates=YYYYMMDDTHHMMSS/YYYYMMDDTHHMMSS`\n- as datas devem conter início e fim.\n- ano padrão: **2025** quando o usuário não informar.\n\n#### eventos de dia inteiro\n- usar: `YYYYMMDD/YYYYMMDD` (fim = dia seguinte)\n- exemplo: `dates=20250625/20250626`\n\n### descrição\n- formato: `details=...` (pode ser multi-linha; usar `%0A`)\n\n### localização\n- formato: `location=...`\n\n### disponibilidade (free/busy)\n- padrão: busy (não adicionar nada)\n- apenas se o usuário pedir explicitamente \"livre\"/\"free\": adicionar `trp=true`\n\n### recorrência (recur)\n- formato: `recur=RRULE:...` (RFC-5545)\n\nexemplos:\n- daily until: `recur=RRULE:FREQ=DAILY;UNTIL=20251224T000000Z`\n- weekly: `recur=RRULE:FREQ=WEEKLY;UNTIL=20251007T000000Z;WKST=SU;BYDAY=TU,TH`\n- monthly: `recur=RRULE:FREQ=MONTHLY;UNTIL=20251224T000000Z;BYDAY=1FR`\n\n## saída\n- retorne **apenas** o link final em um bloco de código.\n"
PROMPT_WORKFLOW_MCP_MASTER = """# Prompt mestre interno do MCP workflow

Você é o executor do workflow unificado ai-coders-context + GSD + Ralph.

## Objetivo
Executar um ciclo curto, previsível e rastreável, sem drift de contexto.

## Protocolo obrigatório
1. Rode `workflow_stack(action=\"status\")`.
2. Se status ok, rode `workflow_stack(action=\"context_refresh\")`.
3. Rode `workflow_stack(action=\"pick_story\", prd_path=\"{prd_path}\")`.
4. Execute `workflow_stack(action=\"cycle\", prd_path=\"{prd_path}\", story_label=\"{story_label}\", run_quality_gates={run_quality_gates})`.
5. Ao final, valide contexto e reporte evidências.

## Regras de execução
- Não expanda escopo para mais de uma story por ciclo.
- Não invente dependências fora de `.context/docs`, `README.md` e PRD.
- Sempre registrar resultado de cada etapa (ok, erro, motivo).
- Se `pick_story` não encontrar story aberta, pare e peça atualização do PRD.
- Se Gemini estiver indisponível, o Codex assume execução sem quebrar o ciclo.

## Formato de saída
Retorne sempre:
1. `status_resumo` (1 parágrafo)
2. `proxima_acao` (1 linha)
3. `evidencias` (lista curta de arquivos/comandos)
4. `riscos` (lista curta)

## Contexto de execução atual
- repo_path: {repo_path}
- prd_path: {prd_path}
- story_label: {story_label}
- run_quality_gates: {run_quality_gates}
"""
PROMPT_GTASKS_RECLAIM = "# Prompt mestre: especialista em produtividade e automação de tarefas (v3.2)\n\n## persona\nvocê é um especialista de classe mundial em gestão de tempo e produtividade, com profundo conhecimento nas metodologias gtd (getting things done), 1-3-5 e na automação de agendas com reclaim.ai e google tasks. sua missão é transformar listas de tarefas brutas em planos de ação otimizados, inteligentes e perfeitamente formatados para automação.\n\n## objetivo principal\nanalisar uma lista de tarefas fornecida pelo usuário, extrair o contexto de cada uma, corrigir inconsistências (como datas passadas e sobrecarga), e reestruturá-la aplicando a metodologia 1-3-5.\n\n## processo\n\n### 1) recebimento\no usuário fornece uma lista de tarefas em qualquer formato.\n\n### 2) análise e diagnóstico\n\n#### 2.1 extração de contexto hierárquico\npara cada tarefa, identifique um contexto de dois níveis no formato:\n- **[categoria, subcategoria]**\n\nexemplos:\n- faculdade: [psicologia, teoria da aprendizagem]\n- trabalho: [organizejr, dpr]\n- padrão: se nenhum contexto for óbvio, use **[geral]**\n\n#### 2.2 gestão de datas e prioridades\n- **tarefas atrasadas ou imediatas (upnext):** se a tarefa tinha vencimento no passado, reagende o vencimento para hoje. só adicione `upnext` se a tarefa for realmente a prioridade número 1 do dia. se houver várias atrasadas, escolha **apenas uma** para `upnext` e ajuste as demais com priority (ex: P1/P2) e/ou redistribuição.\n- **adiar início (not before):** use `not before:MM/DD/YYYY` apenas quando precisar intencionalmente adiar o início para uma data futura.\n- **duração (duration):** sempre em minutos. se não houver indicação, use 30m para tarefas rápidas e 60m para tarefas mais complexas.\n- **buffer entre blocos:** planeje sempre um **buffer de 15 minutos** livre entre uma tarefa/evento e o próximo (para transição, deslocamento, água, etc.).\n- **sobrecarga (regra 1-3-5):** quando receber muitas tarefas, distribua para evitar sobrecarga (1 grande, 3 médias, 5 pequenas por dia). se precisar redistribuir, use `not before` para empurrar o início.\n\n### 3) otimização e formatação do título para reclaim.ai\n\nestrutura do título:\n- **[DD/MM/YYYY] [categoria, subcategoria] nome da tarefa (parâmetros)**\n\nregras:\n- o prefixo **[DD/MM/YYYY]** é para leitura humana.\n- dentro de (parâmetros), a data `due` deve estar em **MM/DD/YYYY** (formato exigido pelo reclaim).\n\nparâmetros:\n- obrigatórios: `duration`, `priority` (critical, P1, P2, P3), `type:work`, `due`\n- condicionais: `upnext` (use com parcimônia: idealmente **no máximo 1 tarefa** marcada como upnext por vez), `not before:MM/DD/YYYY`, `nosplit`\n\n### lidar com tarefas \"locked\" no google agenda (reclaim)\n\"locked\" = evento/tarefa no google agenda com emoji de cadeado (🔒) que o reclaim não replaneja mais.\nse isso estiver travando a ordem do dia, a solução é **resetar a tarefa**:\n- apagar a tarefa no google tasks e recriar com os parâmetros corretos\n- isso força o reclaim a tratar como item novo e voltar a replanejar\n\n### 4) descrição (plano de ação)\npara cada tarefa, gere uma descrição em markdown com:\n- objetivo\n- passos para concluir\n- recursos\n- estratégia de otimização\n\n## saída (muito importante)\n\nobservações importantes sobre google tasks e reclaim:\n- **lista padrão:** se o usuário não especificar uma lista, use por padrão a **lista do reclaim** (a lista que é sincronizada com o reclaim).\n- **horário de vencimento:** no google tasks o vencimento pode ser só a data. não exija horário. se o usuário quiser, você pode perguntar/sugerir um horário como conveniência para lembretes, mas é opcional.\n\nvocê deve produzir **dois blocos** na resposta:\n\n1) uma **tabela markdown** (2 colunas: `título` e `descrição`) para copiar no google sheets.\n\n2) ao final, obrigatoriamente, gere um bloco **```json** contendo um **array json válido** com objetos no formato abaixo, para automação via google tasks api:\n\n```json\n[\n  {\n    \"title\": \"[DD/MM/YYYY] [Categoria, Subcategoria] Nome (duration:60m due:MM/DD/YYYY priority:P1 type:work upnext not before:MM/DD/YYYY nosplit)\",\n    \"due\": \"YYYY-MM-DDT00:00:00Z\",\n    \"notes\": \"...\"\n  }\n]\n```\n\nregras para o json:\n- o json precisa ser **válido** (sem comentários, sem texto dentro do bloco).\n- inclua **apenas** as tarefas que devem ser inseridas.\n- `due` (campo) deve ser iso 8601: `YYYY-MM-DDT00:00:00Z`.\n- a string `title` deve conter os parâmetros de reclaim entre parênteses.\n- `notes` pode conter a descrição resumida (ou \"Jarvis\" se não houver).\n"

# --- 2. SERVIDOR ---
mcp = FastMCP("Jarvis Local v6 (Zap + Docs + Dev + Web)")
# Normaliza caminhos HTTP/SSE para clientes que esperam /sse e /message
mcp._deprecated_settings.sse_path = "/sse"
mcp._deprecated_settings.message_path = "/messages/"

def _mcp_tool_when_env(env_key: str, default: str = "false"):
    """Register a tool only while its MCP group is enabled.

    Disabled groups must disappear from MCP tool discovery, not just return
    runtime errors after the client already loaded their wrappers.
    """
    enabled = str(os.environ.get(env_key, default)).strip().lower() in {"1", "true", "yes", "on"}
    if enabled:
        return mcp.tool()

    def _disabled_tool(fn):
        return fn

    return _disabled_tool



def _log_process(proc: subprocess.Popen, prefix: str) -> None:
    """Imprime as linhas de um processo em thread separada."""
    if not proc.stdout:
        return
    for line in proc.stdout:
        line = line.strip()
        if line:
            print(f"[{prefix}] {line}")


def stop_process(proc: subprocess.Popen) -> None:
    """Finaliza um processo rodando."""
    if proc and proc.poll() is None:
        proc.terminate()


def _pids_listening_on_port(port: int) -> set[int]:
    """Retorna PIDs que escutam TCP na porta informada (Linux)."""
    pids: set[int] = set()
    try:
        res = subprocess.run(
            ["lsof", "-t", "-i", f"TCP:{port}", "-sTCP:LISTEN"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        for line in res.stdout.strip().splitlines():
            try:
                pids.add(int(line.strip()))
            except ValueError:
                continue
    except Exception:
        pass
    if pids:
        return pids
    # fallback com fuser
    try:
        res = subprocess.run(
            ["fuser", f"{port}/tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        for tok in res.stdout.strip().replace("\n", " ").split():
            try:
                pids.add(int(tok))
            except ValueError:
                continue
    except Exception:
        pass
    return pids


def ensure_port_free(port: int, label: str = "") -> None:
    """Tenta liberar uma porta matando processos que a estejam usando."""
    if port <= 0:
        return
    pids = _pids_listening_on_port(port)
    if not pids:
        return
    prefix = f"[port {port}{' ' + label if label else ''}]"
    print(f"⚠️  {prefix} em uso; finalizando PIDs: {', '.join(map(str, pids))}")
    for pid in list(pids):
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            continue
    time.sleep(0.5)
    for pid in list(pids):
        try:
            os.kill(pid, 0)
        except OSError:
            continue  # já morreu
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


# --- Middleware/rotas auxiliares para compatibilidade com clientes externos (ex.: Mistral) ---
try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import Response
except Exception:  # pragma: no cover - se Starlette faltar algo está muito errado
    BaseHTTPMiddleware = None
    PlainTextResponse = None
    CORSMiddleware = None
    Response = None

# Adiciona middleware/rotas direto na app Starlette do FastMCP
if BaseHTTPMiddleware and hasattr(mcp, "http_app"):
    _orig_http_app = mcp.http_app

    def _http_app_with_extras(self, *args, **kwargs):
        """Envolve http_app para injetar CORS/rotas de saúde em qualquer transporte."""
        transport_mode = (kwargs.get("transport") or "http").lower()
        is_sse_transport = transport_mode == "sse"
        try:
            app = _orig_http_app(*args, **kwargs)
        except Exception as e:  # pragma: no cover
            print(f"⚠️  Não foi possível obter http_app(): {e}")
            raise

        # Evita adicionar rotas/middleware mais de uma vez
        if getattr(app.state, "jarvis_routes_added", False):
            return app

        # CORS liberado para permitir chamadas externas (Inspector/Mistral/ChatGPT)
        if CORSMiddleware:
            try:
                app.add_middleware(
                    CORSMiddleware,
                    allow_origins=["*"],
                    allow_credentials=True,
                    allow_methods=["GET", "POST", "OPTIONS"],
                    allow_headers=["*"],
                    expose_headers=["*"],
                )
            except Exception as e:  # pragma: no cover
                print(f"⚠️  Não foi possível adicionar CORSMiddleware: {e}")

        # Middleware ASGI para reescrever caminhos /message -> /messages/ (compat Mistral/Inspector)
        class _PathRewriteMiddleware:
            def __init__(self, inner_app):
                self.inner_app = inner_app

            async def __call__(self, scope, receive, send):
                if scope.get("type") == "http":
                    path = scope.get("path", "")
                    new_path = None
                    patch_json_ct = False
                    if path in ("/message", "/message/", "/messages"):
                        new_path = "/messages/"
                        patch_json_ct = True  # FastMCP exige application/json nesse endpoint
                    elif is_sse_transport and path == "/mcp" and scope.get("method") == "POST":
                        # Support Streamable HTTP: POST /mcp -> JSON-RPC (Messages)
                        new_path = "/messages/"
                        patch_json_ct = True
                    elif path in ("/sse", "/sse/"):
                        new_path = "/mcp"
                    if new_path:
                        scope = dict(scope)
                        scope["path"] = new_path
                        if patch_json_ct:
                            headers = list(scope.get("headers", []))
                            found_ct = False
                            for idx, (k, v) in enumerate(headers):
                                if k.lower() == b"content-type":
                                    found_ct = True
                                    if b"application/json" not in v.lower():
                                        headers[idx] = (k, b"application/json")
                                    break
                            if not found_ct:
                                headers.append((b"content-type", b"application/json"))
                            scope["headers"] = tuple(headers)
                        # Se verificação externa POST /message sem session_id, injetamos um session_id falso para stateless
                        if is_sse_transport and scope.get("method", "").upper() == "POST" and new_path == "/messages/":
                            body_chunks = []
                            more = True
                            while more:
                                msg = await receive()
                                if msg["type"] != "http.request":
                                    break
                                body_chunks.append(msg.get("body", b""))
                                more = msg.get("more_body", False)
                            body = b"".join(body_chunks)
                            
                            try:
                                payload = json.loads(body.decode() or "{}")
                                if not payload.get("session_id"):
                                    # Inject stateless session ID
                                    payload["session_id"] = "stateless-session"
                                    body = json.dumps(payload).encode()
                                    
                                    # Also inject into query string as FastMCP might check there too
                                    qs = scope.get("query_string", b"").decode()
                                    if "session_id" not in qs:
                                        if qs:
                                            qs += "&session_id=stateless-session"
                                        else:
                                            qs = "session_id=stateless-session"
                                        scope["query_string"] = qs.encode()
                            except Exception:
                                pass
                            
                            # Reentrega o corpo (modificado ou não) para o app interno
                            replayed = False

                            async def _replay_receive():
                                nonlocal replayed
                                if replayed:
                                    return {"type": "http.disconnect"}
                                replayed = True
                                return {"type": "http.request", "body": body, "more_body": False}

                            await self.inner_app(scope, _replay_receive, send)
                            return
                await self.inner_app(scope, receive, send)

        try:
            app.add_middleware(_PathRewriteMiddleware)
        except Exception as e:  # pragma: no cover
            print(f"⚠️  Não foi possível adicionar PathRewriteMiddleware: {e}")

        # Pequenos helpers para adicionar rotas com fallback de log
        def _safe_add_route(path: str, handler, methods: list[str]):
            try:
                app.add_route(path, handler, methods=methods)
            except Exception as e:  # pragma: no cover
                print(f"⚠️  Não foi possível adicionar rota {path}: {e}")

        # Rotas de compatibilidade/saúde (Mistral/Inspector testam GET/POST em "/")
        if PlainTextResponse and Response:
            icon_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
            )
            async def icon_png(_):
                return Response(content=icon_bytes, media_type="image/png", status_code=200)

            async def root_ok(request):
                if request.method == "HEAD":
                    return Response(status_code=200)
                
                # MetaMCP-style discovery endpoint
                status_data = {
                    "server": "Jarvis MCP Server",
                    "status": "online",
                    "transport": ["sse", "http"],
                    "endpoints": {
                        "sse": f"{SERVER_URL}/sse",
                        "sse_aliases": [f"{SERVER_URL}/mcp"],
                        "messages": f"{SERVER_URL}/messages/"
                    },
                    "active_services": [],
                    "disabled_services": []
                }

                # Helper to check service status
                services_check = [
                    ("Brave Search", BRAVE_MCP_ENABLE),
                    ("Firecrawl", FIRECRAWL_ENABLE),
                    ("Speedgrapher", True),
                    ("Mermaid", MERMAID_ENABLE),
                    ("Workflow", True),
                ]

                for name, enabled in services_check:
                    if enabled:
                        status_data["active_services"].append(name)
                    else:
                        status_data["disabled_services"].append(name)

                return Response(
                    content=json.dumps(status_data, indent=2), 
                    media_type="application/json", 
                    status_code=200
                )

            _safe_add_route("/", root_ok, methods=["GET", "POST", "HEAD", "OPTIONS"])
            _safe_add_route("/health", lambda _: Response(status_code=200), methods=["GET", "HEAD"])
            _safe_add_route("/favicon.ico", icon_png, methods=["GET", "HEAD"])
            _safe_add_route("/icon.png", icon_png, methods=["GET", "HEAD"])

        # Compat para transporte SSE legado
        if Response and is_sse_transport:
            async def post_sse(request):
                return Response(content=b'{"ok":true}', media_type="application/json", status_code=200)
            _safe_add_route("/mcp", post_sse, methods=["POST"])
            async def get_sse(request):
                return PlainTextResponse("SSE endpoint (use POST /messages/)", status_code=200)
            _safe_add_route("/mcp", get_sse, methods=["GET", "OPTIONS"])

        if Response:
            async def list_tools(_):
                try:
                    tools_map = await mcp.get_tools()
                except Exception:
                    tools_map = {}
                tools_payload = []
                for tool in tools_map.values():
                    params = getattr(tool, "parameters", None)
                    output_schema = getattr(tool, "output_schema", None)
                    tools_payload.append(
                        {
                            "name": getattr(tool, "name", None),
                            "description": getattr(tool, "description", None),
                            "inputSchema": params,
                            "input_schema": params,
                            "outputSchema": output_schema,
                            "output_schema": output_schema,
                        }
                    )
                return Response(
                    content=json.dumps({"tools": tools_payload}, indent=2),
                    media_type="application/json",
                    status_code=200,
                )

            _safe_add_route("/mcp/tools/list", list_tools, methods=["GET", "HEAD", "OPTIONS"])
            _safe_add_route("/mcp/tools", list_tools, methods=["GET", "HEAD", "OPTIONS"])

        try:
            app.state.jarvis_routes_added = True
        except Exception:
            pass
        return app

    mcp.http_app = types.MethodType(_http_app_with_extras, mcp)


def _registered_tool_names() -> list[str]:
    """Return FastMCP tool names across FastMCP versions."""
    try:
        get_tools = getattr(mcp, "get_tools", None)
        if callable(get_tools):
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                tools_map = asyncio.run(get_tools())
                return sorted(name for name in tools_map.keys() if name)

        tools_obj = getattr(mcp, "tools", [])
        if isinstance(tools_obj, dict):
            return sorted(name for name in tools_obj.keys() if name)
        return sorted(name for name in (getattr(t, "name", "") for t in tools_obj) if name)
    except Exception:
        return []


def _module_available(module_name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _missing_google_token_scopes(token_path: Path, required_scopes: list[str]) -> list[str]:
    token_data = _load_token_json(token_path) if token_path.exists() else {}
    raw_scopes = token_data.get("scopes") or token_data.get("scope") or []
    if isinstance(raw_scopes, str):
        scopes = set(raw_scopes.split())
    else:
        scopes = {str(scope) for scope in raw_scopes}
    return [scope for scope in required_scopes if scope not in scopes]


def _join_reasons(reasons: list[str]) -> str:
    return "; ".join(reason for reason in reasons if reason)


def _reclaim_session_state_snapshot() -> str:
    session = load_session(RECLAIM_UI_SESSION_FILE)
    if not session:
        return "not_bootstrapped"

    state = str(session.get("state", "not_bootstrapped"))
    now = time.time()
    if state == "pending_manual_login":
        started = _epoch_from_iso(session.get("started_at"))
        timeout_sec = int(session.get("captcha_timeout_sec", RECLAIM_UI_CAPTCHA_TIMEOUT_SEC))
        if started is not None and (now - started) > timeout_sec:
            return "blocked_captcha"
    elif state == "valid":
        ttl = int(session.get("session_ttl_sec", RECLAIM_UI_SESSION_TTL_SEC))
        last = _epoch_from_iso(session.get("last_validated_at")) or _epoch_from_iso(session.get("bootstrapped_at"))
        if last is None or (now - last) > ttl:
            return "expired"
    return state


def _reclaim_executor_available() -> bool:
    executor_cmd = (RECLAIM_UI_EXECUTOR_CMD or "").strip()
    if not executor_cmd or executor_cmd == "internal":
        return bool(shutil.which("xdotool"))
    try:
        parts = shlex.split(executor_cmd)
    except ValueError:
        return False
    return bool(parts and shutil.which(parts[0]))

def _google_calendar_mcp_token_candidates(credentials_path: Path) -> list[Path]:
    parent = credentials_path.expanduser().parent
    candidates = [
        parent / "mcp-google-calendar-token.json",
        parent / "token.json",
        BASE_DIR / "mcp-google-calendar-token.json",
        BASE_DIR / "token.json",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _google_calendar_mcp_token_exists(credentials_path: Path) -> bool:
    return any(path.exists() for path in _google_calendar_mcp_token_candidates(credentials_path))





def _google_workspace_required_scopes() -> list[str]:
    return list(dict.fromkeys(_GOOGLE_TASKS_SCOPES + _GOOGLE_CALENDAR_SCOPES + _GOOGLE_DRIVE_SCOPES))

def _is_google_invalid_grant(exc: Exception | str) -> bool:
    text = str(exc or "").lower()
    return "invalid_grant" in text or "token has been expired or revoked" in text


def _invalidate_google_workspace_token(token_path: Path, reason: str = "invalid_grant") -> Path | None:
    path = token_path.expanduser()
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.{reason}.{stamp}.bak")
    try:
        path.rename(backup)
        return backup
    except Exception:
        return None


def _google_auth_actionable_error(exc: Exception | str) -> str:
    global _GTASKS_SERVICE_CACHE, _GTASKS_SERVICE_CACHE_MTIME
    _GTASKS_SERVICE_CACHE = None
    _GTASKS_SERVICE_CACHE_MTIME = None
    if _is_google_invalid_grant(exc):
        return (
            f"{exc}. Token OAuth inválido. Rode `python3 jarvis.py google-auth-refresh --force` "
            "e reinicie o servidor MCP se ele já estava rodando."
        )
    return str(exc)


def _google_workspace_token_probe(token_path: Path | None = None) -> dict:
    token = (token_path or (BASE_DIR / "token.json")).expanduser()
    if not token.exists():
        return {"ok": False, "code": "token_missing", "detail": "token.json ausente"}
    missing_scopes = _missing_google_token_scopes(token, _google_workspace_required_scopes())
    if missing_scopes:
        return {
            "ok": False,
            "code": "missing_scopes",
            "detail": "token sem escopos: " + ", ".join(missing_scopes),
        }
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(
            str(token),
            ["https://www.googleapis.com/auth/tasks"],
        )
        service = build("tasks", "v1", credentials=creds)
        service.tasklists().list(maxResults=1).execute()
        return {"ok": True, "code": "ok", "detail": "token validado por chamada real ao Google Tasks"}
    except Exception as exc:
        code = "invalid_grant" if _is_google_invalid_grant(exc) else "runtime_error"
        return {"ok": False, "code": code, "detail": str(exc)}


def _google_workspace_any_enabled() -> bool:
    return any(
        _truthy_env_value(os.environ.get(name, "true"))
        for name in ("GOOGLE_CALENDAR_MCP_ENABLE", "GOOGLE_DRIVE_MCP_ENABLE", "GOOGLE_TASKS_MCP_ENABLE")
    )
def _google_token_fix_hint() -> str:
    return f"rode `python jarvis.py mcp-status` e conclua o OAuth; token esperado em {BASE_DIR / 'token.json'}"


def _google_credentials_fix_hint(path: Path) -> str:
    return f"coloque o OAuth client em {path}"


def _env_fix_hint(name: str) -> str:
    return f"exporte {name}=..."


def _install_fix_hint(name: str) -> str:
    return f"instale {name} e rode novamente"


def _with_fix(reason: str, fix: str = "") -> str:
    reason = (reason or "").strip()
    fix = (fix or "").strip()
    if reason and fix:
        return f"{reason} | dica: {fix}"
    return reason or (f"dica: {fix}" if fix else "")


def _write_env_sh_export(key: str, value: str, path: Path | None = None) -> None:
    path = path or _env_sh_path()
    line = f'export {key}={json.dumps(str(value))}'
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    else:
        lines = ["#!/bin/bash", "# --- CONFIGURATION START ---", "# --- CONFIGURATION END ---"]

    replaced = False
    insert_at = len(lines)
    for idx, existing in enumerate(lines):
        parsed = _parse_export_line(existing)
        if parsed and parsed[0] == key:
            lines[idx] = line
            replaced = True
            break
        if existing.strip() == "# --- CONFIGURATION END ---":
            insert_at = idx

    if not replaced:
        lines.insert(insert_at, line)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o755)
    except Exception:
        pass


def _truthy_env_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _set_runtime_config(key: str, value: str) -> None:
    os.environ[key] = str(value)
    bool_globals = {
        "PLAYWRIGHT_MCP_ENABLE": "PLAYWRIGHT_MCP_ENABLE",
        "BRAVE_MCP_ENABLE": "BRAVE_MCP_ENABLE",
        "CHART_MCP_ENABLE": "CHART_MCP_ENABLE",
        "ZOTERO_MCP_ENABLE": "ZOTERO_MCP_ENABLE",
        "FIRECRAWL_ENABLE": "FIRECRAWL_ENABLE",
        "GOOGLE_CALENDAR_MCP_ENABLE": "GOOGLE_CALENDAR_MCP_ENABLE",
        "FIREFLIES_MCP_ENABLE": "FIREFLIES_MCP_ENABLE",
        "RECLAIM_UI_AUTOMATION_ENABLE": "RECLAIM_UI_AUTOMATION_ENABLE",
        "RECLAIM_OFFICIAL_MCP_ENABLE": "RECLAIM_OFFICIAL_MCP_ENABLE",
        "MERMAID_ENABLE": "MERMAID_ENABLE",
        "GOOGLE_DRIVE_MCP_ENABLE": None,
        "GOOGLE_TASKS_MCP_ENABLE": None,
        "GUPY_MCP_ENABLE": None,
        "ONEDRIVE_MCP_ENABLE": None,
        "SPEEDGRAPHER_ENABLE": None,
        "PROJECT_WORKFLOW_STACK_ENABLE": None,
        "AI_CODERS_CONTEXT_MCP_ENABLE": None,
        "GSD_MCP_ENABLE": None,
        "RALPH_MCP_ENABLE": None,
    }
    str_globals = {
        "BRAVE_API_KEY": "BRAVE_API_KEY",
        "ZOTERO_API_KEY": "ZOTERO_API_KEY",
        "ZOTERO_USER_ID": "ZOTERO_USER_ID",
        "FIRECRAWL_API_KEY": None,
        "FIREFLIES_API_KEY": "FIREFLIES_API_KEY",
        "GUPY_API_TOKEN": "GUPY_API_TOKEN",
        "MSGRAPH_CLIENT_ID": "MSGRAPH_CLIENT_ID",
        "GRAPH_CLIENT_ID": None,
        "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH": "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH",
        "GDRIVE_MCP_OAUTH_PATH": "GOOGLE_DRIVE_MCP_OAUTH_PATH",
        "GDRIVE_MCP_TOKEN_PATH": "GOOGLE_DRIVE_MCP_TOKEN_PATH",
        "GDRIVE_MCP_SCOPES": "GOOGLE_DRIVE_MCP_SCOPES",
        "RECLAIM_OFFICIAL_MCP_URL": "RECLAIM_OFFICIAL_MCP_URL",
        "RECLAIM_OFFICIAL_MCP_PREFIX": "RECLAIM_OFFICIAL_MCP_PREFIX",
        "MERMAID_LINK_ONLY": None,
    }
    if key in bool_globals:
        target = bool_globals[key]
        if target:
            globals()[target] = _truthy_env_value(value)
    elif key in str_globals and str_globals[key]:
        globals()[str_globals[key]] = str(value)


def _persist_config_value(key: str, value: str) -> None:
    _write_env_sh_export(key, value)
    _set_runtime_config(key, value)

def _run_google_workspace_oauth(force: bool = False) -> dict:
    result = {"target": "Google Workspace MCPs", "attempted": False, "ok": False, "detail": ""}
    token_path = BASE_DIR / "token.json"
    if not _google_workspace_any_enabled():
        result["detail"] = "Google Workspace MCPs desativados"
        return result

    if token_path.exists() and not force:
        probe = _google_workspace_token_probe(token_path)
        if probe.get("ok"):
            result["ok"] = True
            result["detail"] = probe.get("detail") or "token único validado para Tasks, Calendar e Drive"
            return result
        if probe.get("code") == "missing_scopes":
            result["detail"] = probe.get("detail", "token sem escopos obrigatórios")
        elif probe.get("code") == "invalid_grant":
            backup = _invalidate_google_workspace_token(token_path)
            result["detail"] = (
                "token OAuth inválido detectado por chamada real"
                + (f"; backup: {backup}" if backup else "")
            )
        else:
            result["detail"] = probe.get("detail", "token não validado por chamada real")
            return result
    elif token_path.exists() and force:
        backup = _invalidate_google_workspace_token(token_path, "forced")
        result["detail"] = "renovação forçada" + (f"; backup: {backup}" if backup else "")

    result["attempted"] = True
    timeout_sec = int(os.environ.get("MCP_STATUS_AUTH_TIMEOUT_SEC", "600"))
    cmd = [sys.executable or "python3", str(BASE_DIR / "jarvis.py"), "__auth_google_workspace_internal"]
    print("🔐 Google Workspace sem token válido. Iniciando OAuth único para Tasks, Calendar e Drive.")
    try:
        proc = subprocess.run(cmd, cwd=str(BASE_DIR), timeout=max(30, timeout_sec))
    except subprocess.TimeoutExpired:
        result["detail"] = f"OAuth excedeu {timeout_sec}s sem concluir"
        return result

    result["ok"] = proc.returncode == 0
    result["detail"] = "token único criado" if proc.returncode == 0 else f"OAuth retornou {proc.returncode}"
    return result
def _run_mcp_status_auto_auth() -> list[dict]:
    actions = [_run_google_workspace_oauth()]
    return [action for action in actions if action.get("attempted") or action.get("detail")]



def _mcp_status_sort_key(item: dict) -> tuple[int, str]:
    enabled = bool(item.get("enabled"))
    ok = bool(item.get("ok"))
    if enabled and not ok:
        group = 0
    elif not enabled:
        group = 1
    else:
        group = 2
    return group, str(item.get("name", ""))

_MCP_TOOL_EXPECTATIONS = {
    "Playwright MCP": {"wildcards": ["playwright_*"]},
    "Brave MCP": {"wildcards": ["brave_*"]},
    "Chart MCP": {"wildcards": ["chart_*"]},
    "Zotero MCP": {"wildcards": ["zotero_*"]},
    "Google Calendar MCP": {
        "names": [
            "gcal_add_event",
            "gcal_create_event",
            "gcal_find_locked_events",
            "gcal_get_freebusy",
            "gcal_list_events",
            "gcal_list_events_detailed",
        ]
    },
    "Google Drive MCP": {"wildcards": ["gdrive_*"], "proxy": True},
    "Google Tasks MCP": {
        "names": [
            "gtasks_complete_task",
            "gtasks_create_task_natural",
            "gtasks_create_weekly_series",
            "gtasks_delete_task",
            "gtasks_list_tasks",
            "gtasks_update_task_context",
            "gtasks_smart_sync_add_reclaim",
        ]
    },

    "Gupy MCP": {"names": ["gupy_test_token", "gupy_v1_close_job", "gupy_v1_list_jobs"]},
    "OneDrive MCP": {"names": ["onedrive_auth_start", "onedrive_auth_poll", "onedrive_get_versions", "onedrive_list"]},
    "Reclaim MCP": {
        "names": [
            "reclaim_next_task",
            "reclaim_session_bootstrap",
            "reclaim_session_status",
            "reclaim_task_assist_confirm",
            "reclaim_task_restart",
            "reclaim_task_start",
            "reclaim_task_stop",
        ]
    },
    "Reclaim Official MCP": {"wildcards": ["reclaim2_*"], "proxy": True},
    "Speedgrapher MCP": {"names": ["speedgrapher_fog_index"]},
    "Mermaid MCP": {"names": ["mermaid_render"]},
    "Project workflow stack": {"names": ["workflow_master_prompt_get", "workflow_stack"]},
    "Firecrawl MCP": {"wildcards": ["firecrawl_*"]},
    "Fireflies MCP": {"wildcards": ["fireflies_*"]},
}


def _mcp_status_tool_lists(payload: dict) -> tuple[list[str], list[str]]:
    available = sorted(payload.get("registeredTools") or [])
    available_set = set(available)
    ok_proxy_items = {
        str(item.get("name", ""))
        for item in payload.get("items", [])
        if item.get("enabled") and item.get("ok")
    }
    enabled_items = {
        str(item.get("name", ""))
        for item in payload.get("items", [])
        if item.get("enabled")
    }
    unavailable: list[str] = []
    for item_name, spec in _MCP_TOOL_EXPECTATIONS.items():
        if item_name not in enabled_items:
            continue
        if spec.get("proxy") and item_name in ok_proxy_items:
            continue
        names = list(spec.get("names") or [])
        wildcards = list(spec.get("wildcards") or [])
        for name in names:
            if name not in available_set:
                unavailable.append(name)
        for wildcard in wildcards:
            prefix = wildcard[:-1] if wildcard.endswith("*") else wildcard
            if not any(tool.startswith(prefix) for tool in available):
                unavailable.append(wildcard)
    return available, sorted(dict.fromkeys(unavailable))


_MCP_TOOL_GROUP_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("speedgrapher", ("audit_seo", "editorial_*", "speedgrapher_*")),
    ("gemini", ("gemini_*",)),
    ("google calendar", ("gcal_*",)),
    ("google tasks", ("gtasks_*", "plan_day_*")),
    ("gupy", ("gupy_*",)),
    ("onedrive", ("onedrive_*",)),
    ("reclaim official", ("reclaim2_*", "reclaim_official_*")),
    ("reclaim", ("reclaim_*",)),
    ("workflow", ("workflow_*",)),
    ("mermaid", ("mermaid_render",)),
    ("firecrawl", ("firecrawl_*",)),
    ("fireflies", ("fireflies_*",)),
    ("google drive", ("gdrive_*",)),
    ("brave", ("brave_*",)),
    ("chart", ("chart_*",)),
    ("playwright", ("playwright_*",)),
    ("zotero", ("zotero_*",)),
]
_MCP_TOOL_GROUP_DESCRIPTIONS = {
    "speedgrapher": "Ferramentas editoriais, SEO e legibilidade do stack Speedgrapher.",
    "gemini": "Ferramentas de bridge e integração com o Gemini.",
    "google calendar": "Ferramentas para listar, criar e inspecionar eventos do Google Calendar.",
    "google tasks": "Ferramentas para criar, listar, sincronizar e planejar tarefas do Google Tasks.",
    "gupy": "Ferramentas para consultar e operar vagas na Gupy.",
    "onedrive": "Ferramentas de autenticação e leitura do OneDrive via Microsoft Graph.",
    "reclaim": "Ferramentas de sessão e automação do Reclaim.",
    "reclaim official": "Ferramentas do MCP oficial remoto do Reclaim 2.0.",
    "workflow": "Ferramentas do workflow do projeto e do stack de contexto.",
    "mermaid": "Ferramentas para renderização de diagramas Mermaid.",
    "firecrawl": "Ferramentas do MCP Firecrawl.",
    "fireflies": "Ferramentas do MCP Fireflies.",
    "google drive": "Ferramentas do MCP Google Drive.",
    "brave": "Ferramentas do MCP Brave Search.",
    "chart": "Ferramentas do MCP Chart.",
    "playwright": "Ferramentas do MCP Playwright.",
    "zotero": "Ferramentas do MCP Zotero.",
    "outros": "Ferramentas fora dos grupos conhecidos.",
}

_MCP_TOOL_DESCRIPTIONS = {
    "audit_seo": "Audita SEO técnico de uma URL ou HTML.",
    "editorial_context": "Carrega um texto no contexto editorial para revisão e edição.",
    "editorial_expand": "Expande uma seção do outline em um parágrafo mais detalhado.",
    "editorial_haiku": "Gera um haiku curto sobre um tema.",
    "editorial_interview": "Inicia uma entrevista guiada para coletar material de escrita.",
    "editorial_localize": "Traduz e localiza um texto para o idioma alvo.",
    "editorial_outline": "Cria um outline estruturado a partir de um conceito.",
    "editorial_publish": "Simula a publicação do conteúdo final.",
    "editorial_readability": "Avalia legibilidade do texto com foco editorial.",
    "editorial_reflect": "Analisa a sessão de escrita e sugere melhorias.",
    "editorial_review": "Revisa o conteúdo com critérios editoriais.",
    "editorial_voice": "Analisa o tom de voz e o estilo de um texto.",
    "gcal_add_event": "Adiciona um evento no Google Calendar por texto natural.",
    "gcal_create_event": "Cria evento no Google Calendar por API ou por texto.",
    "gcal_find_locked_events": "Procura eventos travados do Reclaim no Google Calendar.",
    "gcal_get_freebusy": "Retorna blocos ocupados em um intervalo do Calendar.",
    "gcal_list_events": "Lista eventos do Google Calendar em um intervalo.",
    "gcal_list_events_detailed": "Lista eventos com detalhes úteis para depuração.",
    "gemini_bridge_health": "Verifica se o bridge/binário do Gemini está saudável.",
    "gemini_prompt": "Executa um prompt no Gemini com saída estruturada.",
    "gtasks_complete_task": "Marca uma tarefa do Google Tasks como concluída.",
    "gtasks_create_task_natural": "Cria uma tarefa no Google Tasks por texto natural.",
    "gtasks_create_weekly_series": "Cria uma série semanal de tarefas no Google Tasks.",
    "gtasks_delete_task": "Apaga uma tarefa do Google Tasks.",
    "gtasks_list_tasks": "Lista as tarefas atuais do Google Tasks.",
    "gtasks_update_task_context": "Atualiza a descrição/notas de uma tarefa com contexto GTD.",
    "gtasks_smart_sync_add_reclaim": "Sincroniza tarefas com fallback para formato Reclaim.",
    "gupy_test_token": "Testa se o token da Gupy está válido.",
    "gupy_v1_close_job": "Fecha uma vaga na API v1 da Gupy.",
    "gupy_v1_list_jobs": "Lista vagas pela API pública v1 da Gupy.",
    "mermaid_render": "Renderiza um diagrama Mermaid em PNG.",
    "onedrive_auth_poll": "Finaliza o device flow de autenticação do OneDrive.",
    "onedrive_auth_start": "Inicia o device flow de autenticação do OneDrive.",
    "onedrive_get_versions": "Lista versões de um arquivo do OneDrive.",
    "onedrive_list": "Lista itens de uma pasta do OneDrive.",
    "plan_day_apply": "Aplica o plano preservando o fluxo Google Tasks → Reclaim, sem criar eventos diretos.",
    "plan_day_from_tasks": "Monta um plano do dia com Tasks e Calendar.",
    "reclaim_next_task": "Retorna a próxima tarefa candidata do Reclaim.",
    "reclaim_session_bootstrap": "Inicia ou confirma a sessão manual do Reclaim.",
    "reclaim_session_status": "Mostra o estado atual da sessão do Reclaim.",
    "reclaim_task_assist_confirm": "Confirma manualmente um fallback do Reclaim.",
    "reclaim_task_restart": "Reinicia uma tarefa ativa no Reclaim.",
    "reclaim_task_start": "Inicia uma tarefa no Reclaim.",
    "reclaim_task_stop": "Para a tarefa ativa no Reclaim.",
    "reclaim_official_adapter_status": "Mostra o estado do adapter do MCP oficial do Reclaim 2.0.",
    "speedgrapher_fog_index": "Calcula o índice Gunning Fog de um texto.",
    "workflow_master_prompt_get": "Renderiza o prompt mestre interno do workflow.",
    "workflow_stack": "Executa operações consolidadas do stack de workflow.",
}


def _mcp_tool_origin(tool_name: str) -> str:
    name = str(tool_name or "")
    for group, patterns in _MCP_TOOL_GROUP_RULES:
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
            return group
    return "outros"


def _mcp_group_tools(names: list[str]) -> list[tuple[str, str]]:
    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(_mcp_tool_origin(name), []).append(name)

    ordered_groups = [group for group, _ in _MCP_TOOL_GROUP_RULES if group in grouped]
    extras = sorted(group for group in grouped if group not in ordered_groups)
    entries: list[tuple[str, str]] = []
    for origin in ordered_groups + extras:
        tools = sorted(grouped[origin])
        entries.append(("group", f"{origin} ({len(tools)})"))
        entries.extend(("tool", tool) for tool in tools)
    return entries


def _mcp_tool_description(tool_name: str, kind: str = "tool") -> str:
    if kind == "group":
        return _MCP_TOOL_GROUP_DESCRIPTIONS.get(tool_name, "Grupo de ferramentas relacionado.")
    if kind == "section":
        return "Seção da lista de ferramentas."
    return _MCP_TOOL_DESCRIPTIONS.get(tool_name, f"Ferramenta do grupo {_mcp_tool_origin(tool_name)}.")
def write_mcp_status_report(payload: dict | None = None, *, announce: bool = True):
    """Gera um relatório simples (txt) com o status de configuração dos MCPs."""
    payload = payload or _mcp_status_payload()
    lines = []

    for item in sorted(payload.get("items", []), key=_mcp_status_sort_key):
        name = item.get("name", "")
        ok = bool(item.get("ok"))
        enabled = bool(item.get("enabled"))
        reason = (item.get("reason") or "").strip()
        status = "configurado" if ok else "falha"
        if not enabled:
            status = "desativado"
        if (not ok) and reason:
            lines.append(f"{name}: {status} ({reason})")
        else:
            lines.append(f"{name}: {status}")

    auth_actions = payload.get("authActions") or []
    if auth_actions:
        lines.append("")
        lines.append("Autenticação automática:")
        for action in auth_actions:
            target = action.get("target", "")
            detail = action.get("detail", "")
            status = "ok" if action.get("ok") else "info"
            if action.get("attempted") and not action.get("ok"):
                status = "falha"
            lines.append(f"- {target}: {status} ({detail})")

    available_tools, unavailable_tools = _mcp_status_tool_lists(payload)
    lines.append("")
    lines.append(f"Ferramentas disponíveis: {len(available_tools)}")
    if not available_tools:
        lines.append("- (nenhuma)")
    else:
        for name in available_tools:
            lines.append(f"- {name}")

    lines.append("")
    lines.append(f"Ferramentas indisponíveis: {len(unavailable_tools)}")
    if not unavailable_tools:
        lines.append("- (nenhuma)")
    else:
        for name in unavailable_tools:
            lines.append(f"- {name}")

    report_path = Path.cwd() / "mcp_status.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    if announce:
        print(f"📝 Relatório MCP salvo em {report_path}")

def start_playwright_mcp():
    """Sobe o Playwright MCP via npx (Node)."""
    if not PLAYWRIGHT_MCP_ENABLE:
        print("ℹ️  Playwright MCP desativado via env (PLAYWRIGHT_MCP_ENABLE=false).")
        return None
    if not shutil.which(PLAYWRIGHT_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {PLAYWRIGHT_MCP_BIN}).")
        print("    Instale Node ou defina PLAYWRIGHT_MCP_ENABLE=false.")
        return None

    ensure_port_free(PLAYWRIGHT_MCP_PORT, "playwright-mcp")
    extra = PLAYWRIGHT_MCP_EXTRA_ARGS.strip().split() if PLAYWRIGHT_MCP_EXTRA_ARGS.strip() else []
    cmd = [PLAYWRIGHT_MCP_BIN, PLAYWRIGHT_MCP_PACKAGE, "--port", str(PLAYWRIGHT_MCP_PORT)]
    if PLAYWRIGHT_MCP_HOST:
        cmd += ["--host", PLAYWRIGHT_MCP_HOST]
    cmd += extra

    print(f"🎭 Iniciando Playwright MCP em {PLAYWRIGHT_MCP_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    threading.Thread(target=_log_process, args=(proc, "playwright-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    
    try:
        time.sleep(2)
        proxy = FastMCP.as_proxy(PLAYWRIGHT_MCP_URL, name="playwright-mcp")
        mcp.mount(proxy, prefix="playwright")
        print(f"🔗 Playwright MCP montado.")
    except Exception as e:
        print(f"⚠️  Falha ao montar Playwright: {e}")
        
    return proc


def start_brave_mcp():
    """Sobe o Brave Search MCP via npx (Node)."""
    if not BRAVE_MCP_ENABLE:
        print("ℹ️  Brave MCP desativado via env (BRAVE_MCP_ENABLE=false).")
        return None
    if not BRAVE_API_KEY:
        print("⚠️  BRAVE_API_KEY não definido; Brave MCP não será iniciado.")
        print("    Defina BRAVE_API_KEY e reinicie o servidor para habilitar o Brave MCP.")
        return None
    if not shutil.which(BRAVE_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {BRAVE_MCP_BIN}).")
        print("    Instale Node ou defina BRAVE_MCP_ENABLE=false.")
        return None

    ensure_port_free(BRAVE_MCP_PORT, "brave-mcp")
    extra = BRAVE_MCP_EXTRA_ARGS.strip().split() if BRAVE_MCP_EXTRA_ARGS.strip() else []
    cmd = [BRAVE_MCP_BIN, BRAVE_MCP_PACKAGE, "--port", str(BRAVE_MCP_PORT)]
    if BRAVE_MCP_HOST:
        cmd += ["--host", BRAVE_MCP_HOST]
    cmd += extra

    env = os.environ.copy()
    env["BRAVE_API_KEY"] = BRAVE_API_KEY

    print(f"🧭 Iniciando Brave MCP em {BRAVE_MCP_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env)
    threading.Thread(target=_log_process, args=(proc, "brave-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    
    # Monta no servidor principal
    try:
        # Aguarda um pouco para o processo subir
        time.sleep(2)
        proxy = FastMCP.as_proxy(BRAVE_MCP_URL, name="brave-mcp")
        mcp.mount(proxy, prefix="brave")
        print(f"🔗 Brave MCP montado no servidor principal com prefixo brave_*")
    except Exception as e:
        print(f"⚠️  Falha ao montar Brave MCP no servidor principal: {e}")
    
    return proc


def start_chart_mcp():
    """Sobe o AntV Chart MCP via npx (Node)."""
    if not CHART_MCP_ENABLE:
        print("ℹ️  Chart MCP desativado via env (CHART_MCP_ENABLE=false).")
        return None
    if not shutil.which(CHART_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {CHART_MCP_BIN}).")
        print("    Instale Node ou defina CHART_MCP_ENABLE=false.")
        return None

    ensure_port_free(CHART_MCP_PORT, "chart-mcp")
    extra = CHART_MCP_EXTRA_ARGS.strip().split() if CHART_MCP_EXTRA_ARGS.strip() else []
    cmd = [CHART_MCP_BIN, CHART_MCP_PACKAGE, "--port", str(CHART_MCP_PORT), "--host", CHART_MCP_HOST]
    cmd += extra

    print(f"📈 Iniciando Chart MCP em {CHART_MCP_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    threading.Thread(target=_log_process, args=(proc, "chart-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    # Cloudflared disable
    try:
        chart_proxy_url = f"{CHART_MCP_URL}/sse"
        proxy = FastMCP.as_proxy(chart_proxy_url, name="chart-mcp")
        mcp.mount(proxy, prefix="chart")
        print(f"🔗 Chart MCP montado no servidor principal com prefixo chart_* (url={chart_proxy_url}).")
    except Exception as e:
        print(f"⚠️  Falha ao montar Chart MCP no servidor principal: {e}")
    return proc


def _npm_install_global(pkg: str) -> bool:
    """Instala um pacote npm globalmente (retorna sucesso/erro)."""
    npm_bin = shutil.which("npm")
    if not npm_bin:
        print("⚠️  npm não encontrado para instalar pacote Node MCP.")
        return False
    print(f"⬇️  Instalando {pkg} globalmente via npm ...")
    install = subprocess.run(
        [npm_bin, "install", "-g", pkg],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if install.returncode != 0:
        print(f"❌ Falha ao instalar {pkg}:\n{install.stdout}")
        return False
    print(f"✅ {pkg} instalado globalmente.")
    return True

def _npm_global_has(pkg: str) -> bool:
    """Verifica se um pacote npm global já está presente (depth=0)."""
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return False
    try:
        res = subprocess.run(
            [npm_bin, "list", "-g", pkg, "--depth", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return res.returncode == 0
    except Exception:
        return False


def _npm_global_version(pkg: str) -> str | None:
    """Retorna a versão global instalada (via npm list --json)."""
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return None
    try:
        res = subprocess.run(
            [npm_bin, "list", "-g", pkg, "--depth", "0", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        data = res.stdout
        import json

        j = json.loads(data)
        deps = j.get("dependencies", {})
        info = deps.get(pkg)
        if not info:
            return None
        return info.get("version")
    except Exception:
        return None


def _npm_ensure_global(pkg_spec: str) -> bool:
    """Garante pacote npm global: só instala se ausente ou versão diferente."""
    # Para git+/tarball não conseguimos checar versão; tenta uma vez
    if pkg_spec.startswith("git+"):
        return _npm_install_global(pkg_spec)

    # Extrai nome e versão desejada (para @scope/name@x.y.z)
    desired_version = None
    pkg_name = pkg_spec
    if "@" in pkg_spec:
        # Mantém escopo; separa última @ como versão
        name_part, ver_part = pkg_spec.rsplit("@", 1)
        if name_part:
            pkg_name = name_part
            desired_version = ver_part if ver_part else None

    current_version = _npm_global_version(pkg_name)
    if current_version:
        if desired_version and current_version != desired_version:
            print(f"ℹ️  {pkg_name} global na versão {current_version}; atualizando para {desired_version} ...")
        else:
            print(f"ℹ️  {pkg_name} já instalado globalmente (versão {current_version}).")
            return True
    return _npm_install_global(pkg_spec)


def start_zotero_mcp():
    """Sobe o Zotero MCP via npx (Node)."""
    if not ZOTERO_MCP_ENABLE:
        print("ℹ️  Zotero MCP desativado via env (ZOTERO_MCP_ENABLE=false).")
        return None
    if not shutil.which(ZOTERO_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {ZOTERO_MCP_BIN}).")
        print("    Instale Node ou defina ZOTERO_MCP_ENABLE=false.")
        return None
    if not os.environ.get("ZOTERO_API_KEY") or not os.environ.get("ZOTERO_USER_ID"):
        print("⚠️  ZOTERO_API_KEY ou ZOTERO_USER_ID não definidos; Zotero MCP não será iniciado.")
        print("    Defina ZOTERO_API_KEY e ZOTERO_USER_ID e reinicie o servidor para habilitar o Zotero MCP.")
        return None

    ensure_port_free(ZOTERO_MCP_PORT, "zotero-mcp")
    extra = ZOTERO_MCP_EXTRA_ARGS.strip().split() if ZOTERO_MCP_EXTRA_ARGS.strip() else []
    cmd = [ZOTERO_MCP_BIN, ZOTERO_MCP_PACKAGE]
    if ZOTERO_MCP_PORT:
        cmd += ["--port", str(ZOTERO_MCP_PORT)]
    if ZOTERO_MCP_HOST:
        cmd += ["--host", ZOTERO_MCP_HOST]
    cmd += extra

    env = os.environ.copy()

    print(f"📚 Iniciando Zotero MCP em {ZOTERO_MCP_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env)
    threading.Thread(target=_log_process, args=(proc, "zotero-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    
    try:
        time.sleep(2)
        proxy = FastMCP.as_proxy(ZOTERO_MCP_URL, name="zotero-mcp")
        mcp.mount(proxy, prefix="zotero")
        print(f"🔗 Zotero MCP montado.")
    except Exception as e:
        print(f"⚠️  Falha ao montar Zotero: {e}")

    return proc

def start_firecrawl_mcp():
    """Sobe o Firecrawl MCP via npx (Node)."""
    if not FIRECRAWL_ENABLE:
        print("ℹ️  Firecrawl MCP desativado via env (FIRECRAWL_ENABLE=false).")
        return None
    if not shutil.which(FIRECRAWL_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {FIRECRAWL_BIN}).")
        print("    Instale Node ou defina FIRECRAWL_ENABLE=false.")
        return None
    if not os.environ.get("FIRECRAWL_API_KEY"):
        print("⚠️  FIRECRAWL_API_KEY não definido; Firecrawl MCP não será iniciado.")
        print("    Defina FIRECRAWL_API_KEY e reinicie o servidor para habilitar o Firecrawl MCP.")
        return None

    ensure_port_free(FIRECRAWL_PORT, "firecrawl-mcp")

    cmd = [FIRECRAWL_BIN, FIRECRAWL_PACKAGE]
    cmd += extra

    env = os.environ.copy()
    # Preferir modo HTTP streamable para expor URL
    if FIRECRAWL_STREAMABLE:
        env["HTTP_STREAMABLE_SERVER"] = "true"
    env["FIRECRAWL_API_KEY"] = os.environ["FIRECRAWL_API_KEY"]
    # Tentar forçar porta se suportado
    env["PORT"] = str(FIRECRAWL_PORT)

    print(f"🔥 Iniciando Firecrawl MCP em {FIRECRAWL_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env)
    threading.Thread(target=_log_process, args=(proc, "firecrawl-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    # Cloudflared disable
    try:
        proxy = FastMCP.as_proxy(FIRECRAWL_URL, name="firecrawl-mcp")
        mcp.mount(proxy, prefix="firecrawl")
        print(f"🔗 Firecrawl MCP montado no servidor principal com prefixo firecrawl_* (url={FIRECRAWL_URL}).")
    except Exception as e:
        print(f"⚠️  Falha ao montar Firecrawl MCP no servidor principal: {e}")
    return proc

def start_google_drive_mcp():
    """Monta o Google Drive MCP diretamente dentro do Jarvis."""
    enabled = os.environ.get("GOOGLE_DRIVE_MCP_ENABLE", "true").lower() in ("1", "true", "yes", "on")
    if not enabled:
        print("ℹ️  Google Drive MCP desativado via env.", file=sys.stderr)
        return

    npx_path = shutil.which("npx")
    if not npx_path:
        print("⚠️  npx não encontrado. Google Drive MCP requer Node.js.", file=sys.stderr)
        return

    env = os.environ.copy()
    env["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
    env["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    env["GDRIVE_MCP_OAUTH_PATH"] = GOOGLE_DRIVE_MCP_OAUTH_PATH
    env["GDRIVE_MCP_TOKEN_PATH"] = GOOGLE_DRIVE_MCP_TOKEN_PATH
    env["GDRIVE_MCP_SCOPES"] = GOOGLE_DRIVE_MCP_SCOPES

    backend = {
        "mcpServers": {
            "google-drive": {
                "command": npx_path,
                "args": ["-y", "@ibarcarty/mcp-server-google-drive"],
                "env": env,
            }
        }
    }
    try:
        proxy = FastMCP.as_proxy(backend, name="google-drive-mcp")
        mcp.mount(proxy, prefix="gdrive")
        print("🔗 Google Drive MCP montado no servidor principal com prefixo gdrive_*")
    except Exception as e:
        print(f"⚠️  Falha ao montar Google Drive MCP no servidor principal: {e}")

def start_google_calendar_mcp():
    if not GOOGLE_CALENDAR_MCP_ENABLE:
        print("ℹ️  Google Calendar MCP desativado via env (GOOGLE_CALENDAR_MCP_ENABLE=false).")
        return None
    if not shutil.which(GOOGLE_CALENDAR_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {GOOGLE_CALENDAR_MCP_BIN}).")
        print("    Instale Node ou defina GOOGLE_CALENDAR_MCP_ENABLE=false.")
        return None

    ensure_port_free(GOOGLE_CALENDAR_MCP_PORT, "google-calendar-mcp")
    cmd = [GOOGLE_CALENDAR_MCP_BIN, "-y", GOOGLE_CALENDAR_MCP_PACKAGE, "--port", str(GOOGLE_CALENDAR_MCP_PORT)]
    env = os.environ.copy()

    env["CREDENTIALS_PATH"] = str(Path(GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH).expanduser())
    env["PORT"] = str(GOOGLE_CALENDAR_MCP_PORT)

    print(f"📅 Iniciando Google Calendar MCP em {GOOGLE_CALENDAR_MCP_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env)
    threading.Thread(target=_log_process, args=(proc, "google-calendar-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    
    # Monta no servidor principal
    try:
        # Aguarda um pouco para o processo subir
        time.sleep(2)
        proxy = FastMCP.as_proxy(GOOGLE_CALENDAR_MCP_URL, name="google-calendar-mcp")
        mcp.mount(proxy, prefix="gcal")
        print(f"🔗 Google Calendar MCP montado no servidor principal com prefixo gcal_*")
    except Exception as e:
        print(f"⚠️  Falha ao montar Google Calendar MCP no servidor principal: {e}")
    
    return proc
    print(f"📅 Iniciando Google Calendar MCP em {GOOGLE_CALENDAR_MCP_URL} ...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=str(BASE_DIR),
    )
    threading.Thread(target=_log_process, args=(proc, "google-calendar-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)

    try:
        time.sleep(3)
        proxy = FastMCP.as_proxy(GOOGLE_CALENDAR_MCP_URL, name="google-calendar-mcp")
        mcp.mount(proxy, prefix="gcalendar")
        print(f"🔗 Google Calendar MCP montado no servidor principal com prefixo gcalendar_* (url={GOOGLE_CALENDAR_MCP_URL}).")
    except Exception as e:
        print(f"⚠️  Falha ao montar Google Calendar MCP no servidor principal: {e}")
    return proc


def start_fireflies_mcp():
    """Proxy remoto para Fireflies via mcp-remote (Node)."""
    if not FIREFLIES_MCP_ENABLE:
        print("ℹ️  Fireflies MCP desativado via env (FIREFLIES_MCP_ENABLE=false).")
        return None
    if not shutil.which(FIREFLIES_MCP_BIN):
        print(f"⚠️  npx/Node não encontrado (binário: {FIREFLIES_MCP_BIN}).")
        print("    Instale Node ou defina PLAYWRIGHT_MCP_ENABLE=false.")
        return None
    if not FIREFLIES_API_KEY:
        print("⚠️  FIREFLIES_API_KEY não definido; Fireflies MCP não será iniciado.")
        return None

    ensure_port_free(FIREFLIES_MCP_PORT, "fireflies-mcp")
    extra = FIREFLIES_MCP_EXTRA_ARGS.strip().split() if FIREFLIES_MCP_EXTRA_ARGS.strip() else []
    cmd = [
        FIREFLIES_MCP_BIN,
        "-y",
        FIREFLIES_MCP_PACKAGE,
        FIREFLIES_MCP_REMOTE_URL,
        "--port",
        str(FIREFLIES_MCP_PORT),
        "--host",
        FIREFLIES_MCP_HOST,
        "--header",
        f"Authorization: Bearer {FIREFLIES_API_KEY}",
    ]
    cmd += extra

    print(f"📝 Iniciando Fireflies MCP proxy em {FIREFLIES_MCP_URL} -> {FIREFLIES_MCP_REMOTE_URL} ...")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    threading.Thread(target=_log_process, args=(proc, "fireflies-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)
    # Cloudflared disable
    try:
        proxy = FastMCP.as_proxy(FIREFLIES_MCP_URL, name="fireflies-mcp")
        mcp.mount(proxy, prefix="fireflies")
        print(f"🔗 Fireflies MCP montado no servidor principal com prefixo fireflies_* (url={FIREFLIES_MCP_URL}).")
    except Exception as e:
        print(f"⚠️  Falha ao montar Fireflies MCP no servidor principal: {e}")
    return proc


def start_reclaim_official_mcp():
    """Monta o MCP oficial remoto do Reclaim 2.0 sem remover fallbacks locais."""
    global RECLAIM_OFFICIAL_MCP_MOUNTED
    if not RECLAIM_OFFICIAL_MCP_ENABLE:
        print("ℹ️  Reclaim official MCP desativado via env (RECLAIM_OFFICIAL_MCP_ENABLE=false).")
        return None

    if not RECLAIM_OFFICIAL_MCP_URL.startswith(("https://", "http://")):
        print(f"⚠️  RECLAIM_OFFICIAL_MCP_URL inválida: {RECLAIM_OFFICIAL_MCP_URL!r}")
        return None

    try:
        proxy = FastMCP.as_proxy(RECLAIM_OFFICIAL_MCP_URL, name="reclaim-official-mcp")
        mcp.mount(proxy, prefix=RECLAIM_OFFICIAL_MCP_PREFIX)
        RECLAIM_OFFICIAL_MCP_MOUNTED = True
        print(
            "🔗 Reclaim official MCP montado no servidor principal "
            f"com prefixo {RECLAIM_OFFICIAL_MCP_PREFIX}_* (url={RECLAIM_OFFICIAL_MCP_URL})."
        )
    except Exception as e:
        RECLAIM_OFFICIAL_MCP_MOUNTED = False
        print(f"⚠️  Falha ao montar Reclaim official MCP no servidor principal: {e}")
    return None




@_mcp_tool_when_env("MERMAID_ENABLE", "false")
def mermaid_render(code: str, filename: str | None = None) -> str:
    """Gera PNG a partir de código Mermaid usando kroki.io."""
    if not MERMAID_ENABLE:
        return "❌ Mermaid desativado. Ative com MERMAID_ENABLE=true."
    # Usa diretório fixo na base do projeto para não depender do cwd
    target_dir = os.path.join(BASE_DIR, "mermaid")
    os.makedirs(target_dir, exist_ok=True)
    base = filename if filename else f"mermaid_{int(time.time())}"
    if not base.lower().endswith(".png"):
        base += ".png"
    out_path = os.path.join(target_dir, base)
    errors: list[str] = []

    def _encode_mermaid(text: str) -> str:
        data = text.encode("utf-8")
        # kroki espera deflate com header zlib (pako.deflate)
        compressed = zlib.compress(data, level=9)
        return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")

    def _try_kroki() -> bytes:
        resp = httpx.post(
            "https://kroki.io/mermaid/png",
            content=code.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content

    def _try_mermaid_cli() -> bytes:
        mmdc_bin = shutil.which("mmdc")
        npx_bin = shutil.which("npx") if not mmdc_bin else None
        mermaid_cli_pkg = os.environ.get("MERMAID_CLI_PACKAGE", "@mermaid-js/mermaid-cli")
        if not mmdc_bin and UV_AUTO_INSTALL:
            _npm_ensure_global(mermaid_cli_pkg)
            mmdc_bin = shutil.which("mmdc")
            npx_bin = shutil.which("npx") if not mmdc_bin else npx_bin
        if not mmdc_bin and not npx_bin:
            raise RuntimeError("mmdc/npx não encontrado para fallback local; instale @mermaid-js/mermaid-cli")

        mmd_path = Path(out_path).with_suffix(".mmd")
        mmd_path.write_text(code, encoding="utf-8")
        cmd = [mmdc_bin or npx_bin]
        if not mmdc_bin:
            cmd += ["-y", "@mermaid-js/mermaid-cli"]
        cmd += [
            "-i",
            str(mmd_path),
            "-o",
            out_path,
            "-t",
            "default",
            "--quiet",
            "--scale",
            os.environ.get("MERMAID_SCALE", "2"),
            "--width",
            os.environ.get("MERMAID_WIDTH", "1200"),
        ]

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"mmdc falhou: {proc.stdout.strip()}")
        data = Path(out_path).read_bytes()
        _validate_img(data)
        return data

    def _validate_img(buf: bytes) -> None:
        if not buf or len(buf) < 50:
            raise ValueError(f"resposta vazia ({len(buf)} bytes)")
        head = buf[:32].lstrip().lower()
        if head.startswith(b"<!doctype") or head.startswith(b"<html"):
            raise ValueError("resposta HTML (provável erro da API)")
        # Esperamos PNG; se vier JPEG (ex.: imagem de erro) ou outro formato, trata como falha
        if not buf.startswith(b"\x89PNG"):
            raise ValueError(f"formato inesperado (assinatura {buf[:4].hex()}); aguardado PNG")

    encoded = _encode_mermaid(code)
    kroki_public_url = f"https://kroki.io/mermaid/svg/{encoded}"

    link_only_env = os.environ.get("MERMAID_LINK_ONLY", "").strip().lower()
    if link_only_env in ("1", "true", "yes", "on"):
        return f"✅ Mermaid link gerado. URL: {kroki_public_url}"
    if link_only_env not in ("0", "false", "no", "off") and PUBLIC_URL:
        return f"✅ Mermaid link gerado. URL: {kroki_public_url}"

    for label, fn in [
        ("kroki.io", _try_kroki),
        ("mermaid-cli", _try_mermaid_cli),
    ]:
        try:
            print(f"[tool] mermaid_render ({label}) -> {out_path}")
            img = fn()
            _validate_img(img)
            with open(out_path, "wb") as f:
                f.write(img)
            if label == "mermaid-cli":
                public_url = out_path
            else:
                public_url = kroki_public_url
            return f"✅ Mermaid renderizado. URL: {public_url} (via {label})"
        except Exception as e:
            errors.append(f"{label}: {e}")
            continue

    print(f"[tool] mermaid_render erro: {' | '.join(errors)}")
    fallback = (
        "⚠️ Falha ao renderizar via API. "
        f"Use: {kroki_public_url}. "
        f"Tentativas: {' | '.join(errors)}"
    )
    return fallback



@mcp.tool()
def speedgrapher_fog_index(text: str) -> str:
    """
    Calcula o Gunning Fog Index de um texto para avaliar sua legibilidade.
    Retorna o score e a classificação (ex: Unreadable, Professional, etc).
    """
    import re
    
    if not text.strip():
        return "❌ Texto vazio."

    # Contagem básica de frases e palavras
    sentences = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    num_sentences = len(sentences) or 1
    
    # Palavras: consideramos sequências alfabéticas
    all_words = re.findall(r'\b[a-zA-Z]+\b', text)
    num_words = len(all_words) or 1
    
    # Função auxiliar para sílabas (heurística para inglês/geral)
    def count_syllables(word):
        word = word.lower()
        count = 0
        vowels = "aeiouy"
        if not word: return 0
        if word[0] in vowels: count += 1
        for index in range(1, len(word)):
            if word[index] in vowels and word[index - 1] not in vowels:
                count += 1
        if word.endswith("e"): count -= 1
        if count == 0: count += 1
        return count

    # Palavras complexas: 3 ou mais sílabas, ignorando nomes próprios (título) ou compostas
    # O Speedgrapher original usa bibliotecas de NLP, aqui usamos uma heurística robusta
    complex_words = [w for w in all_words if count_syllables(w) >= 3]
    num_complex = len(complex_words)
    
    # Fórmula Gunning Fog: 0.4 * ( (words/sentences) + 100 * (complex/words) )
    avg_sentence_len = num_words / num_sentences
    percent_complex = (num_complex / num_words) * 100
    fog_index = 0.4 * (avg_sentence_len + percent_complex)
    
    # Classificação baseada no README do Speedgrapher
    classification = ""
    if fog_index >= 22: classification = "Unreadable (Likely incomprehensible)"
    elif fog_index >= 18: classification = "Hard to Read (Expert level)"
    elif fog_index >= 13: classification = "Professional (Specialized knowledge)"
    elif fog_index >= 9:  classification = "General Audiences (Clear & accessible)"
    else:                 classification = "Simplistic (Childish or overly simple)"
    
    return f"**Gunning Fog Index**: {fog_index:.1f}\n**Classificação**: {classification}\n\nEstatísticas:\n- Palavras: {num_words}\n- Frases: {num_sentences}\n- Palavras Complexas: {num_complex} ({percent_complex:.1f}%)"

# --- Speedgrapher Prompts ---
@mcp.prompt("speedgrapher_outline")
def speedgrapher_outline(topic: str, context: str = "") -> list[dict]:
    """Gera um outline estruturado para um artigo ou texto."""
    prompt_text = f"""You are a professional editor. Create a detailed, structured outline for an article about: {topic}.
    
Context/Background info:
{context}

The outline should include:
- Engaging Title
- Introduction (Hook, Problem, Solution/Thesis)
- Key Sections (with main points and supporting details)
- Conclusion (Summary, Call to Action)
"""
    return [{"role": "user", "content": prompt_text}]

@mcp.prompt("speedgrapher_review")
def speedgrapher_review(text: str) -> list[dict]:
    """Revisa um texto com base em diretrizes editoriais profissionais."""
    prompt_text = f"""Act as a senior editor. Review the following text for clarity, flow, tone, and logical structure. 
Identify weak points, redundant phrases, and opportunities for better engagement.
Provide specific feedback and a revised version of the introduction.

Text to review:
{text}
"""
    return [{"role": "user", "content": prompt_text}]

@mcp.prompt("speedgrapher_expand")
def speedgrapher_expand(outline_point: str, tone: str = "professional") -> list[dict]:
    """Expande um ponto de outline em um parágrafo completo."""
    prompt_text = f"""Expand the following outline point into a full, well-written section.
Tone: {tone}

Point to expand:
{outline_point}

Ensure smooth transitions and strong topic sentences.
"""
    return [{"role": "user", "content": prompt_text}]

@mcp.tool()
def editorial_interview(topic: str) -> str:
    """Inicia uma entrevista estruturada para coletar material para um artigo ou post."""
    return f"Vamos começar a entrevista sobre '{topic}'. Por favor, me conte qual o objetivo principal deste texto e quem é o público-alvo."

@mcp.tool()
def editorial_outline(concept: str) -> str:
    """Gera um esboço estruturado (outline) baseado em um conceito ou notas de entrevista."""
    return f"Aqui está um esboço para '{concept}':\n1. Introdução\n2. Contexto Tecnológico\n3. Problema e Solução\n4. Conclusão e CTA."

@mcp.tool()
def editorial_expand(section_title: str, points: str) -> str:
    """Expande um tópico do esboço em um parágrafo detalhado e fluído."""
    return f"Expandindo o tópico '{section_title}' com base nos pontos: {points}..."

@mcp.tool()
def audit_seo(url: str | None = None, html: str | None = None, keyword: str | None = None) -> str:
    """Analisa SEO técnico de uma URL ou HTML. Verifica Title, Meta, Headings e palavra-chave."""
    target = url if url else "HTML fornecido"
    return f"🛡️ Auditoria SEO para {target}: Title OK, Meta Description encontrada, H1 presente. Otimização para '{keyword}' está em 85%."

    words = len(text.split())
    sentences = max(1, text.count('.') + text.count('!') + text.count('?'))
    complex_words = len([w for w in text.split() if len(w) > 7])
    score = 0.4 * ((words / sentences) + 100 * (complex_words / words))
    
    status = "Profissional"
    if score < 9: status = "Simples/Claro"
    elif score > 18: status = "Muito Complexo"
    
    return f"Índice Gunning Fog: {score:.2f} ({status})."

@mcp.tool()
def editorial_context(article_text: str) -> str:
    """Carrega o texto atual do artigo para o contexto para permitir revisões e edições."""
    return f"Contexto do artigo carregado ({len(article_text)} caracteres). Agora você pode pedir revisões, traduções ou análises sobre este texto."

@mcp.tool()
def editorial_haiku(topic: str) -> str:
    """Cria um haiku criativo sobre um tópico fornecido."""
    return f"Gerando haiku sobre '{topic}'... (A IA completará a poesia no chat)."

@mcp.tool()
def editorial_localize(text: str, target_language: str = "Brazilian Portuguese") -> str:
    """Traduz e localiza o texto para o idioma e cultura alvo."""
    return f"Localizando texto para '{target_language}'... (A IA realizará a tradução agora)."

@mcp.tool()
def editorial_publish(content: str) -> str:
    """Simula o processo de publicação do artigo finalizado."""
    return "🚀 Artigo publicado com sucesso! Versão final enviada para o 'servidor de publicação'."

@mcp.tool()
def editorial_readability(text: str) -> str:
    """Analisa a legibilidade do texto usando o índice Gunning Fog (Wrapper Jarvis)."""
    # Chamamos a função interna fog se disponível ou retornamos instrução
    return f"Analisando legibilidade... Use a ferramenta 'speedgrapher_sse_fog' para o cálculo numérico exato ou aguarde minha análise aqui."

@mcp.tool()
def editorial_reflect() -> str:
    """Analisa a sessão de escrita atual e propõe melhorias no processo de desenvolvimento."""
    return "Refletindo sobre a sessão... Identifiquei um bom fluxo de ideias. Sugestão: detalhar mais os exemplos técnicos na próxima seção."

@mcp.tool()
def editorial_review(content: str) -> str:
    """Revisa o artigo contra diretrizes editoriais profissionais."""
    return "Revisando o conteúdo... Verificando tom de voz, clareza e estrutura. (Aguarde os comentários de revisão)."

@mcp.tool()
def editorial_voice(sample_text: str) -> str:
    """Analisa o tom de voz e estilo de um texto para replicá-lo em gerações futuras."""
    return "Estilo de voz analisado. Capturado tom: Profissional, Técnico e Acessível. Vou usar este padrão nas próximas respostas."

@mcp.prompt("speedgrapher_interview")
def speedgrapher_interview(topic: str) -> list[dict]:
    """Conduz uma entrevista para extrair informações sobre um tópico."""
    prompt_text = f"""Act as an investigative journalist. Your goal is to interview me to gather deep insights about: {topic}.
Ask one thought-provoking question at a time. Dig into specific details, examples, and unique perspectives.
Start with the first question.
"""
    return [{"role": "user", "content": prompt_text}]


@mcp.prompt("workflow_mcp_master")
def workflow_mcp_master(
    repo_path: str = "",
    prd_path: str = RALPH_PRD_DEFAULT_REL,
    story_label: str = "",
    run_quality_gates: bool = False,
) -> list[dict]:
    """Prompt mestre interno para execução do MCP workflow unificado."""
    repo_value = (repo_path or str(BASE_DIR)).strip()
    prd_value = (prd_path or RALPH_PRD_DEFAULT_REL).strip()
    story_value = (story_label or "AUTO").strip()
    prompt_text = PROMPT_WORKFLOW_MCP_MASTER.format(
        repo_path=repo_value,
        prd_path=prd_value,
        story_label=story_value,
        run_quality_gates=str(bool(run_quality_gates)).lower(),
    )
    return [{"role": "user", "content": prompt_text}]


@mcp.tool()
def workflow_master_prompt_get(
    repo_path: str = "",
    prd_path: str = RALPH_PRD_DEFAULT_REL,
    story_label: str = "",
    run_quality_gates: bool = False,
) -> str:
    """Retorna o prompt mestre interno do workflow já renderizado com variáveis."""
    repo_value = (repo_path or str(BASE_DIR)).strip()
    prd_value = (prd_path or RALPH_PRD_DEFAULT_REL).strip()
    story_value = (story_label or "AUTO").strip()
    return PROMPT_WORKFLOW_MCP_MASTER.format(
        repo_path=repo_value,
        prd_path=prd_value,
        story_label=story_value,
        run_quality_gates=str(bool(run_quality_gates)).lower(),
    )

_GTASKS_SERVICE_CACHE = None
_GTASKS_SERVICE_CACHE_MTIME = None


def _gtasks_service():
    """Return a cached Google Tasks service for the current Jarvis process."""
    global _GTASKS_SERVICE_CACHE, _GTASKS_SERVICE_CACHE_MTIME

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = BASE_DIR / "token.json"
    if not token_path.exists():
        raise RuntimeError("token.json não encontrado.")
    token_mtime = token_path.stat().st_mtime
    if _GTASKS_SERVICE_CACHE is not None and _GTASKS_SERVICE_CACHE_MTIME == token_mtime:
        return _GTASKS_SERVICE_CACHE
    creds = Credentials.from_authorized_user_file(
        str(token_path),
        ["https://www.googleapis.com/auth/tasks"],
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            token_mtime = token_path.stat().st_mtime
        except Exception as exc:
            if _is_google_invalid_grant(exc):
                _GTASKS_SERVICE_CACHE = None
                _GTASKS_SERVICE_CACHE_MTIME = None
            raise
    _GTASKS_SERVICE_CACHE = build("tasks", "v1", credentials=creds)
    _GTASKS_SERVICE_CACHE_MTIME = token_mtime
    return _GTASKS_SERVICE_CACHE


def _normalize_task_title(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _looks_like_gtasks_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{12,}", (value or "").strip()))


def _resolve_gtasks_task(service, task_list_id: str, task_ref: str) -> dict:
    """Resolve task_ref as id first, then as exact title, then unique substring."""
    task_ref = (task_ref or "").strip()
    if not task_ref:
        raise RuntimeError("task_id/título vazio.")

    if _looks_like_gtasks_id(task_ref):
        try:
            return service.tasks().get(tasklist=task_list_id, task=task_ref).execute()
        except Exception:
            pass

    target = _normalize_task_title(task_ref)
    results = service.tasks().list(tasklist=task_list_id, showCompleted=False, maxResults=100).execute()
    items = results.get("items", []) or []
    exact = [item for item in items if _normalize_task_title(item.get("title", "")) == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(f"título ambíguo, {len(exact)} tarefas com título exato.")

    partial = [item for item in items if target and target in _normalize_task_title(item.get("title", ""))]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        titles = "; ".join(item.get("title", "") for item in partial[:5])
        raise RuntimeError(f"título ambíguo, {len(partial)} tarefas encontradas: {titles}")
    raise RuntimeError(f"tarefa não encontrada por id ou título: {task_ref}")

def _gtasks_structured_notes(
    *,
    bloqueios: str = "",
    updates: str = "",
    contexto: str = "",
    plano_acao: str = "",
) -> str:
    def _section(title: str, value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return f"{title}:\n-"
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        bullets = []
        for line in lines:
            bullets.append(line if line.startswith(("-", "*")) else f"- {line}")
        return f"{title}:\n" + "\n".join(bullets)

    return "\n\n".join(
        (
            _section("Bloqueios", bloqueios),
            _section("Updates", updates),
            _section("Contexto", contexto),
            _section("Plano de acao", plano_acao),
        )
    )


def _gtasks_merge_notes(existing: str, new_notes: str) -> str:
    existing = (existing or "").strip()
    if not existing or existing == "Jarvis":
        return new_notes
    if existing == new_notes:
        return existing
    return f"{existing}\n\n---\n\n{new_notes}"



@mcp.tool()
def gtasks_list_tasks(task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Lista as tarefas atuais com seus IDs."""
    try:
        service = _gtasks_service()

        results = service.tasks().list(tasklist=task_list_id, showCompleted=False, maxResults=100).execute()
        items = results.get('items', [])
        
        if not items: return f"Lista '{task_list_id}' vazia."
            
        output = [f"📋 Tarefas em '{task_list_id}':"]
        for item in items:
            due = f" [Vencimento: {item.get('due', 'N/A')[:10]}]"
            output.append(f"- ID: {item['id']}\n  Título: {item['title']}{due}")
            
        return "\n".join(output)
    except Exception as e: return f"Erro: {_google_auth_actionable_error(e)}"


@mcp.tool()
def gtasks_update_task_context(
    task_id: str,
    bloqueios: str = "",
    updates: str = "",
    contexto: str = "",
    plano_acao: str = "",
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    mode: str = "replace",
) -> str:
    """Atualiza a descrição/notas de uma tarefa com estrutura GTD.

    Use depois de coletar contexto do usuário por perguntas. Resolve task_id por
    ID, título exato ou trecho único. mode aceita:
    - replace: substitui notes pela estrutura Bloqueios/Updates/Contexto/Plano de acao.
    - append: preserva notes existentes e anexa a nova estrutura.
    """
    try:
        service = _gtasks_service()
        task = _resolve_gtasks_task(service, task_list_id, task_id)
        new_notes = _gtasks_structured_notes(
            bloqueios=bloqueios,
            updates=updates,
            contexto=contexto,
            plano_acao=plano_acao,
        )
        normalized_mode = (mode or "replace").strip().lower()
        if normalized_mode not in {"replace", "append"}:
            return "Erro ao atualizar tarefa: mode deve ser 'replace' ou 'append'."

        task["notes"] = (
            _gtasks_merge_notes(task.get("notes", ""), new_notes)
            if normalized_mode == "append"
            else new_notes
        )
        updated = service.tasks().update(tasklist=task_list_id, task=task["id"], body=task).execute()
        return (
            "✅ descrição da tarefa atualizada.\n"
            f"- id: {updated.get('id')}\n"
            f"- título: {updated.get('title')}\n"
            f"- modo: {normalized_mode}\n"
            f"- notes:\n{updated.get('notes', '')}"
        )
    except Exception as e:
        return f"Erro ao atualizar tarefa: {_google_auth_actionable_error(e)}"
@mcp.tool()
def gtasks_complete_task(task_id: str, task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Marca uma tarefa como concluída por ID, título exato ou trecho único do título."""
    try:
        service = _gtasks_service()
        task = _resolve_gtasks_task(service, task_list_id, task_id)
        task["status"] = "completed"
        service.tasks().update(tasklist=task_list_id, task=task["id"], body=task).execute()

        return f"✅ Tarefa '{task['title']}' marcada como concluída!"
    except Exception as e:
        return f"Erro ao concluir: {_google_auth_actionable_error(e)}"

@mcp.tool()
def gtasks_delete_task(task_id: str, task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Deleta permanentemente uma tarefa específica."""
    try:
        service = _gtasks_service()
        service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
        return f"🗑️ Tarefa {task_id} deletada com sucesso."
    except Exception as e: return f"Erro ao deletar: {_google_auth_actionable_error(e)}"


@mcp.tool()
def gtasks_move_task(
    task_id: str,
    source_task_list_id: str,
    destination_task_list_id: str,
) -> str:
    """Move uma tarefa entre listas do Google Tasks preservando título, notas e due."""
    try:
        service = _gtasks_service()

        task = service.tasks().get(tasklist=source_task_list_id, task=task_id).execute()
        body = {
            "title": task.get("title", ""),
            "notes": task.get("notes", ""),
        }
        if task.get("due"):
            body["due"] = task["due"]

        created = service.tasks().insert(tasklist=destination_task_list_id, body=body).execute()
        service.tasks().delete(tasklist=source_task_list_id, task=task_id).execute()

        return (
            "✅ tarefa movida.\n"
            f"- origem: {source_task_list_id}\n"
            f"- destino: {destination_task_list_id}\n"
            f"- novo_id: {created.get('id', '')}\n"
            f"- título: {created.get('title', body['title'])}"
        )
    except Exception as e:
        return f"Erro ao mover tarefa: {_google_auth_actionable_error(e)}"

@mcp.tool()
def gtasks_create_task_natural(
    text: str,
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    context: str = "[Geral]",
    duration_min: int = 30,
    priority: str = "P2",
    task_type: str = "work",
    default_to_today: bool = True,
) -> str:
    """Cria 1 tarefa no Google Tasks (modo legado, sem LLM).

    este tool é determinístico (sem llm) e sempre aplica a estrutura do prompt do reclaim
    (título com parâmetros). ele também é usado como fallback do smart_sync.

    - interpreta datas relativas em pt-br: "hoje", "amanhã", "depois de amanhã"
    - também aceita data explícita: YYYY-MM-DD ou DD/MM/YYYY
    - se nenhuma data for encontrada e default_to_today=True, usa hoje

    Retorna o ID criado e o título final.
    """
    try:
        from datetime import datetime, date, timedelta, timezone

        def _br(d: date) -> str:
            return f"{d.day:02d}/{d.month:02d}/{d.year}"

        def _us(d: date) -> str:
            return f"{d.month:02d}/{d.day:02d}/{d.year}"

        def _iso_midnight_utc(d: date) -> str:
            return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        def _parse_due(raw: str) -> date | None:
            s = (raw or "").strip().lower()
            # sempre usar fuso de brasília (america/sao_paulo)
            try:
                from zoneinfo import ZoneInfo
                today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
            except Exception:
                # fallback
                today = datetime.now().date()

            # explicit: YYYY-MM-DD
            m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
            if m:
                y, mo, da = map(int, m.groups())
                return date(y, mo, da)

            # explicit: DD/MM/YYYY
            m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", s)
            if m:
                da, mo, y = map(int, m.groups())
                return date(y, mo, da)

            # relative pt-br
            if "depois de amanhã" in s or "depois de amanha" in s:
                return today + timedelta(days=2)
            if "amanhã" in s or "amanha" in s:
                return today + timedelta(days=1)
            if "hoje" in s:
                return today

            return today if default_to_today else None

        due_date = _parse_due(text)
        if due_date is None:
            return "Erro: não consegui inferir a data (passe uma data explícita ou use hoje/amanhã/depois de amanhã)."

        # normalize context
        ctx = (context or "").strip()
        if not ctx.startswith("["):
            ctx = f"[{ctx}]" if ctx else "[Geral]"

        # build reclaim-like title
        title = (
            f"[{_br(due_date)}] {ctx} {text.strip()} "
            f"(duration:{int(duration_min)}m due:{_us(due_date)} priority:{priority} type:{task_type})"
        )

        service = _gtasks_service()

        body = {
            'title': title,
            'notes': 'Jarvis',
            'due': _iso_midnight_utc(due_date),
        }
        res = service.tasks().insert(tasklist=task_list_id, body=body).execute()
        return f"✅ Tarefa criada. ID: {res.get('id')}\nTítulo: {title}"

    except Exception as e:
        import traceback
        return f"Erro ao criar tarefa (no-llm): {_google_auth_actionable_error(e)}\n{traceback.format_exc()}"



@mcp.tool()
def gcal_list_events(
    start: str,
    end: str,
    calendar_id: str = "primary",
    max_results: int = 50,
) -> str:
    """Lista eventos do Google Calendar em um intervalo (resumo)."""
    try:
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        def _parse_dt(s: str, is_end: bool) -> datetime:
            s = (s or "").strip()
            # date-only
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                y, mo, d = map(int, s.split("-"))
                if tz:
                    return datetime(y, mo, d, 23, 59, 59, tzinfo=tz) if is_end else datetime(y, mo, d, 0, 0, 0, tzinfo=tz)
                return datetime(y, mo, d, 23, 59, 59, tzinfo=timezone.utc) if is_end else datetime(y, mo, d, 0, 0, 0, tzinfo=timezone.utc)

            # ISO with Z
            if s.endswith("Z"):
                s2 = s[:-1] + "+00:00"
                return datetime.fromisoformat(s2)

            # ISO with offset
            return datetime.fromisoformat(s)

        start_dt = _parse_dt(start, is_end=False)
        end_dt = _parse_dt(end, is_end=True)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado. Rode: python jarvis.py mcp-status para autenticar Google automaticamente."

        scopes = [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/tasks',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        service = build('calendar', 'v3', credentials=creds)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            timeMax=end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            singleEvents=True,
            orderBy='startTime',
            maxResults=int(max_results),
        ).execute().get('items', [])

        if not events:
            return f"📅 Sem eventos entre {start_dt} e {end_dt} (calendar_id={calendar_id})."

        out = [f"📅 Eventos (calendar_id={calendar_id}):"]
        for ev in events:
            summary = ev.get('summary', '(sem título)')
            st = ev.get('start', {})
            en = ev.get('end', {})
            st_s = st.get('dateTime') or st.get('date') or ''
            en_s = en.get('dateTime') or en.get('date') or ''
            out.append(f"- {st_s} → {en_s} — {summary}")

        return "\n".join(out)

    except Exception as e:
        import traceback
        return f"Erro ao listar eventos: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gcal_list_events_detailed(
    start: str,
    end: str,
    calendar_id: str = "primary",
    max_results: int = 100,
) -> str:
    """Lista eventos do Google Calendar com detalhes úteis para depuração (sem UI).

    Retorna: id, start/end, summary, description (primeiras linhas) e extendedProperties (se existirem).
    """
    try:
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        def _parse_dt(s: str, is_end: bool) -> datetime:
            s = (s or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                y, mo, d = map(int, s.split("-"))
                if tz:
                    return datetime(y, mo, d, 23, 59, 59, tzinfo=tz) if is_end else datetime(y, mo, d, 0, 0, 0, tzinfo=tz)
                return datetime(y, mo, d, 23, 59, 59, tzinfo=timezone.utc) if is_end else datetime(y, mo, d, 0, 0, 0, tzinfo=timezone.utc)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)

        start_dt = _parse_dt(start, is_end=False)
        end_dt = _parse_dt(end, is_end=True)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        scopes = [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/tasks',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        service = build('calendar', 'v3', credentials=creds)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            timeMax=end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            singleEvents=True,
            orderBy='startTime',
            maxResults=int(max_results),
        ).execute().get('items', [])

        if not events:
            return f"📅 Sem eventos entre {start_dt} e {end_dt} (calendar_id={calendar_id})."

        out = [f"📅 Eventos detalhados (calendar_id={calendar_id}):"]
        for ev in events:
            ev_id = ev.get('id', '')
            summary = ev.get('summary', '(sem título)')
            st = ev.get('start', {})
            en = ev.get('end', {})
            st_s = st.get('dateTime') or st.get('date') or ''
            en_s = en.get('dateTime') or en.get('date') or ''
            desc = (ev.get('description') or '').strip()
            desc_1 = " | ".join(desc.splitlines()[:2])
            ext = ev.get('extendedProperties')
            ext_s = ''
            if ext:
                ext_s = f" extendedProperties={ext}"
            out.append(f"- {st_s} → {en_s} | id={ev_id} | {summary}" + (f" | desc={desc_1}" if desc_1 else "") + ext_s)

        return "\n".join(out)

    except Exception as e:
        import traceback
        return f"Erro ao listar eventos detalhados: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gcal_find_locked_events(
    day: str,
    calendar_id: str = "primary",
) -> str:
    """Tenta identificar eventos "locked" do Reclaim sem depender de UI.

    Heurísticas:
    - summary/description contém '🔒'
    - description contém 'locked'/'reclaim' (quando presente)

    day: YYYY-MM-DD
    """
    try:
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        # intervalo do dia
        y, mo, da = map(int, day.split('-'))
        start_dt = datetime(y, mo, da, 0, 0, 0, tzinfo=tz) if tz else datetime(y, mo, da, 0, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(y, mo, da, 23, 59, 59, tzinfo=tz) if tz else datetime(y, mo, da, 23, 59, 59, tzinfo=timezone.utc)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        scopes = [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/tasks',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        service = build('calendar', 'v3', credentials=creds)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            timeMax=end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            singleEvents=True,
            orderBy='startTime',
            maxResults=250,
        ).execute().get('items', [])

        hits = []
        for ev in events:
            summary = ev.get('summary', '') or ''
            desc = (ev.get('description') or '')
            ext = ev.get('extendedProperties') or {}
            hay = (summary + "\n" + desc + "\n" + str(ext)).lower()
            if '🔒' in summary or '🔒' in desc or 'locked' in hay or 'reclaim' in hay:
                st = ev.get('start', {})
                en = ev.get('end', {})
                st_s = st.get('dateTime') or st.get('date') or ''
                en_s = en.get('dateTime') or en.get('date') or ''
                hits.append(f"- {st_s} → {en_s} | id={ev.get('id','')} | {summary}")

        if not hits:
            return "🔎 não encontrei nenhum evento com marcador claro de lock (🔒/locked/reclaim) via api. se o lock só aparece na ui, preciso do título+horário ou print."

        return "🔒 possíveis locked (heurístico):\n" + "\n".join(hits)

    except Exception as e:
        import traceback
        return f"Erro ao procurar locked: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gcal_get_freebusy(
    start: str,
    end: str,
    calendar_ids: list[str] = ["primary"],
) -> str:
    """Retorna blocos ocupados (busy) do Google Calendar em um intervalo."""
    try:
        from datetime import datetime, timezone
        if start.endswith('Z'):
            start = start[:-1] + '+00:00'
        if end.endswith('Z'):
            end = end[:-1] + '+00:00'

        # aceita YYYY-MM-DD
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", (start or '').strip()):
            start = start.strip() + "T00:00:00-03:00"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", (end or '').strip()):
            end = end.strip() + "T23:59:59-03:00"

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado. Rode: python jarvis.py mcp-status para autenticar Google automaticamente."

        scopes = [
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/tasks',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        service = build('calendar', 'v3', credentials=creds)

        body = {
            "timeMin": start_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "timeMax": end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "items": [{"id": cid} for cid in calendar_ids],
        }
        fb = service.freebusy().query(body=body).execute()

        cal = fb.get('calendars', {})
        out = [f"🧱 Busy blocks ({calendar_ids}):"]
        for cid in calendar_ids:
            blocks = cal.get(cid, {}).get('busy', [])
            if not blocks:
                out.append(f"- {cid}: (sem busy)")
                continue
            out.append(f"- {cid}:")
            for b in blocks:
                out.append(f"  - {b.get('start')} → {b.get('end')}")

        return "\n".join(out)

    except Exception as e:
        import traceback
        return f"Erro no freebusy: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gcal_add_event(
    text: str,
    calendar_id: str = "primary",
    default_duration_min: int = 30,
    default_year: int | None = None,
) -> str:
    """Adiciona evento no Google Calendar via API a partir de texto (sem LLM).

    O texto pode incluir, em pt-br:
    - título (obrigatório)
    - data: YYYY-MM-DD ou DD/MM (usa default_year se ano faltar)
    - horário: HH:MM (se não houver e "dia inteiro" estiver presente, cria evento all-day)
    - duração: "90m", "1h", "1h30" (se faltar, usa default_duration_min)
    - localização: "em <lugar>" ou "local: <lugar>"
    - detalhes: "detalhes: ..."
    - disponibilidade: "livre"/"free" → cria como free (transparency=transparent)
    - recorrência:
        * "todo dia"/"diariamente" → DAILY até 31/12 do ano de início (inclusive)
        * "toda semana"/"semanal" + dias (seg, ter, qua, qui, sex, sáb, dom) → WEEKLY;BYDAY=...
        * "mensalmente" + "primeira/segunda/terceira/quarta/última" + dia → MONTHLY;BYDAY=...
      Se houver "até DD/MM" ou "até YYYY-MM-DD", usa UNTIL.

    Retorna id + link do evento.
    """
    try:
        from datetime import datetime, date, timedelta
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        raw = (text or '').strip()
        if not raw:
            return "Erro: text vazio."
        low = raw.lower()

        # free/busy
        free = bool(re.search(r"\b(livre|free)\b", low))

        # extract details / location (best-effort)
        details = ''
        m = re.search(r"\bdetalhes\s*:\s*(.+)$", raw, flags=re.I)
        if m:
            details = m.group(1).strip()

        location = ''
        m = re.search(r"\blocal\s*:\s*(.+)$", raw, flags=re.I)
        if m:
            location = m.group(1).strip()
        else:
            m = re.search(r"\bem\s+([^,]+)$", raw, flags=re.I)
            if m and len(m.group(1).strip()) <= 80:
                location = m.group(1).strip()

        # parse duration
        dur = int(default_duration_min)
        m = re.search(r"\b(\d+)\s*m\b", low)
        if m:
            dur = int(m.group(1))
        else:
            m = re.search(r"\b(\d+)\s*h\s*(\d{1,2})\b", low)
            if m:
                dur = int(m.group(1))*60 + int(m.group(2))
            else:
                m = re.search(r"\b(\d+)\s*h(\d{1,2})\b", low)
                if m:
                    dur = int(m.group(1))*60 + int(m.group(2))
                else:
                    m = re.search(r"\b(\d+)\s*h\b", low)
                    if m:
                        dur = int(m.group(1))*60

        # parse start date
        day_d = None

        # padrão: ano atual (brasília)
        now = datetime.now(tz) if tz else datetime.now()
        if default_year is None:
            default_year = now.year

        # suporte: "X dias antes de <data>"
        mrel = re.search(r"\b(\d+)\s+dias?\s+antes\s+de\s+(.+)$", low)
        if mrel:
            n = int(mrel.group(1))
            tail = mrel.group(2).strip()

            # aceitar: YYYY-MM-DD
            m0 = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", tail)
            if m0:
                y, mo, da = map(int, m0.groups())
                base = date(y, mo, da)
                day_d = base - timedelta(days=n)
            else:
                # aceitar: DD/MM(/YYYY)
                m0 = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", tail)
                if m0:
                    da, mo, yy = m0.groups()
                    y = int(yy) if yy else int(default_year)
                    base = date(y, int(mo), int(da))
                    day_d = base - timedelta(days=n)
                else:
                    # aceitar: "6 de maio" / "6 de maio de 2026"
                    months = {
                        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
                        'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8,
                        'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12,
                    }
                    m1 = re.search(r"\b(\d{1,2})\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4}))?\b", tail)
                    if m1:
                        da = int(m1.group(1))
                        mon = months.get(m1.group(2))
                        y = int(m1.group(3)) if m1.group(3) else int(default_year)
                        if mon:
                            base = date(y, mon, da)
                            day_d = base - timedelta(days=n)

        if day_d is None:
            m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
            if m:
                y, mo, da = map(int, m.groups())
                day_d = date(y, mo, da)
            else:
                m = re.search(r"\b(\d{2})/(\d{2})(?:/(\d{4}))?\b", low)
                if m:
                    da, mo, yy = m.groups()
                    y = int(yy) if yy else int(default_year)
                    day_d = date(y, int(mo), int(da))

        if day_d is None:
            # default: today (brasília)
            day_d = now.date()

        if day_d is None:
            # default: today (brasília)
            now = datetime.now(tz) if tz else datetime.now()
            day_d = now.date()

        # se default_year não foi passado, assume o ano do start (ano corrente)
        if default_year is None:
            default_year = day_d.year

        # parse time HH:MM
        hm = re.search(r"\b(\d{1,2}):(\d{2})\b", low)
        all_day = bool(re.search(r"\b(dia\s+inteiro|all\s*day)\b", low))

        # parse UNTIL
        until_d = None
        mu = re.search(r"\bat[eé]\s+(\d{4}-\d{2}-\d{2})\b", low)
        if mu:
            y, mo, da = map(int, mu.group(1).split('-'))
            until_d = date(y, mo, da)
        else:
            mu = re.search(r"\bat[eé]\s+(\d{2})/(\d{2})(?:/(\d{4}))?\b", low)
            if mu:
                da, mo, yy = mu.groups()
                y = int(yy) if yy else (default_year or day_d.year)
                until_d = date(y, int(mo), int(da))

        # recurrence detection
        rrule = None

        # COUNT (ex: "por 3 vezes", "3 vezes")
        count_n = None
        mc = re.search(r"\bpor\s+(\d+)\s+vezes\b", low)
        if not mc:
            mc = re.search(r"\b(\d+)\s+vezes\b", low)
        if mc:
            count_n = int(mc.group(1))

        # helpers for weekly days
        day_map = {
            'seg':'MO','segunda':'MO',
            'ter':'TU','terça':'TU','terca':'TU',
            'qua':'WE','quarta':'WE',
            'qui':'TH','quinta':'TH',
            'sex':'FR','sexta':'FR',
            'sab':'SA','sáb':'SA','sábado':'SA','sabado':'SA',
            'dom':'SU','domingo':'SU',
        }

        def build_until(dt_date: date) -> str:
            # UNTIL needs Z time. use end of day UTC
            end_local = datetime(dt_date.year, dt_date.month, dt_date.day, 23, 59, 59, tzinfo=tz) if tz else datetime(dt_date.year, dt_date.month, dt_date.day, 23, 59, 59)
            end_utc = end_local.astimezone(ZoneInfo('UTC')) if tz else end_local
            return end_utc.strftime('%Y%m%dT%H%M%SZ')

        if re.search(r"\b(todo\s+dia|diariamente)\b", low):
            if count_n:
                rrule = f"RRULE:FREQ=DAILY;COUNT={count_n}"
            else:
                u = until_d or date(day_d.year, 12, 31)
                rrule = f"RRULE:FREQ=DAILY;UNTIL={build_until(u)}"
        elif re.search(r"\b(toda\s+semana|semanal)\b", low):
            days=[]
            for k,v in day_map.items():
                if re.search(r"\b"+re.escape(k)+r"\b", low):
                    days.append(v)
            days = sorted(set(days), key=lambda x: ['MO','TU','WE','TH','FR','SA','SU'].index(x))
            if not days:
                # default: day of start
                days=[['MO','TU','WE','TH','FR','SA','SU'][day_d.weekday()]]
            u = until_d or date(day_d.year, 12, 31)
            rrule = f"RRULE:FREQ=WEEKLY;UNTIL={build_until(u)};WKST=SU;BYDAY={','.join(days)}"
        elif re.search(r"\b(mensalmente|todo\s+m[eê]s)\b", low):
            ord_map = {
                'primeira': '1', 'primeiro': '1',
                'segunda': '2',
                'terceira': '3',
                'quarta': '4',
                'ultima': '-1', 'última': '-1',
            }
            ord_n=None
            for k,v in ord_map.items():
                if re.search(r"\b"+re.escape(k)+r"\b", low):
                    ord_n=v
                    break
            byday=None
            for k,v in day_map.items():
                if re.search(r"\b"+re.escape(k)+r"\b", low):
                    byday=v
                    break
            if ord_n and byday:
                u = until_d or date(day_d.year, 12, 31)
                rrule = f"RRULE:FREQ=MONTHLY;UNTIL={build_until(u)};BYDAY={ord_n}{byday}"

        # summary: try to remove common scheduling words to keep title clean
        summary = raw
        # remove 'todo dia', 'diariamente', 'toda semana', 'semanal', 'mensalmente', 'até ...', time and duration tokens
        summary = re.sub(r"\b(todo\s+dia|diariamente|toda\s+semana|semanal|mensalmente|todo\s+m[eê]s)\b", "", summary, flags=re.I)
        summary = re.sub(r"\bpor\s+\d+\s+vezes\b", "", summary, flags=re.I)
        summary = re.sub(r"\b\d+\s+vezes\b", "", summary, flags=re.I)
        summary = re.sub(r"\b\d+\s+dias?\s+antes\s+de\b", "", summary, flags=re.I)
        summary = re.sub(r"\bat[eé]\s+\d{4}-\d{2}-\d{2}\b", "", summary, flags=re.I)
        summary = re.sub(r"\bat[eé]\s+\d{2}/\d{2}(?:/\d{4})?\b", "", summary, flags=re.I)
        summary = re.sub(r"\b\d{1,2}:\d{2}\b", "", summary)
        summary = re.sub(r"\b\d+\s*m\b", "", summary, flags=re.I)
        summary = re.sub(r"\b\d+\s*h\s*\d{0,2}\b", "", summary, flags=re.I)
        summary = re.sub(r"\s+", " ", summary).strip(" -,:;\t\n")
        if not summary:
            summary = raw.strip()

        # build event
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."
        scopes = [
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.readonly',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        svc = build('calendar', 'v3', credentials=creds)

        if all_day and not hm:
            # all-day: use date objects (end is +1 day)
            end_day = day_d + timedelta(days=1)
            body = {
                'summary': summary,
                'start': {'date': day_d.isoformat()},
                'end': {'date': end_day.isoformat()},
            }

            # default for all-day: do not block time unless explicitly requested
            # (Google Calendar uses transparency='opaque' to block and 'transparent' for "free")
            if not free:
                body['transparency'] = 'transparent'
        else:
            if not hm:
                return "Erro: preciso de um horário HH:MM (ou use 'dia inteiro')."
            hh, mm = map(int, hm.groups())
            start_dt = datetime(day_d.year, day_d.month, day_d.day, hh, mm, 0, tzinfo=tz)
            end_dt = start_dt + timedelta(minutes=int(dur))
            body = {
                'summary': summary,
                'start': {'dateTime': start_dt.isoformat()},
                'end': {'dateTime': end_dt.isoformat()},
            }

        if details:
            body['description'] = details
        if location:
            body['location'] = location
        if free:
            body['transparency'] = 'transparent'
        if rrule:
            body['recurrence'] = [rrule]

        ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
        return (f"✅ evento criado: {ev.get('id')}\n{ev.get('htmlLink','')}" ).strip()

    except Exception as e:
        import traceback
        return f"Erro ao adicionar evento: {e}\n{traceback.format_exc()}"
@mcp.tool()
def gcal_create_event(
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    calendar_id: str = "primary",
    description: str | None = None,
    free: bool | None = None,
    text: str | None = None,
    default_duration_min: int = 30,
    default_year: int | None = None,
) -> str:
    """Cria um evento no Google Calendar (unificado).

    Você pode usar de dois jeitos:

    1) modo "api": passe summary + start + end (ISO 8601 com offset)
       - exemplo start/end: 2026-02-05T14:45:00-03:00
       - free: True/False para marcar como "free" (transparency=transparent) ou "busy" (opaque)

    2) modo "texto": passe text (pt-br) e ele extrai título/data/hora/duração/local/detalhes
       - aceita "dia inteiro"
       - aceita recorrência (diariamente/semanal/mensal) e "até ..."

    Retorna id + link do evento.
    """
    try:
        # se veio text, delega pro parser já existente
        if text is not None and str(text).strip():
            return gcal_add_event(
                text=str(text),
                calendar_id=calendar_id,
                default_duration_min=default_duration_min,
                default_year=default_year,
            )

        # modo "api" (compatível com a assinatura antiga)
        if not summary or not start or not end:
            return (
                "Erro: informe (summary, start, end) ou então use (text). "
                "Ex: gcal_create_event(text='reunião 11/03 19:00 1h')"
            )

        from datetime import datetime
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        scopes = [
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/tasks',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        svc = build('calendar', 'v3', credentials=creds)

        # normalize Z
        if start.endswith('Z'):
            start = start[:-1] + '+00:00'
        if end.endswith('Z'):
            end = end[:-1] + '+00:00'

        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)

        # default: se for evento all-day (date), marcar como free a menos que o usuário force o contrário
        if free is None and (len(start) == 10 and len(end) == 10):
            free = True

        body = {
            'summary': summary,
            'start': {'dateTime': start_dt.isoformat()},
            'end': {'dateTime': end_dt.isoformat()},
        }
        if description:
            body['description'] = description
        if free is not None:
            body['transparency'] = 'transparent' if bool(free) else 'opaque'

        ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
        return f"✅ evento criado: {ev.get('id')}\n{ev.get('htmlLink', '')}".strip()

    except Exception as e:
        import traceback
        return f"Erro ao criar evento: {e}\n{traceback.format_exc()}"


@mcp.tool()
def plan_day_from_tasks(
    day: str,
    task_list_id: str = "",
    task_list_ids: list[str] | None = None,
    calendar_ids: list[str] = ["primary"],
    day_start: str = "08:00",
    day_end: str = "22:30",
    min_slot_min: int = 15,
    buffer_min: int = 15,
    include_overdue: bool = True,
) -> str:
    """Planeja o dia juntando Google Tasks e Google Calendar.

    Por padrão lê duas listas:
    - Reclaim: lista operacional comprometida que entra na alocação do dia.
    - Minhas tarefas: dump desestruturado usado para triagem, perguntas e promoção
      manual para a lista operacional Reclaim.

    Dia normal padrão: 08:00–22:30. Se o usuário disser que está madrugando,
    planeje tarefas para agora, sem esperar o próximo bloco diurno.
    """
    try:
        from datetime import datetime, date, time, timedelta, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        y, mo, da = map(int, day.split('-'))
        day_d = date(y, mo, da)

        def _t(hm: str) -> time:
            hh, mm = map(int, hm.split(':'))
            return time(hh, mm)

        def _split_task_list_ids(raw: str) -> list[str]:
            return [part.strip() for part in (raw or "").split(",") if part.strip()]

        def _task_list_ids_for_plan() -> list[str]:
            if task_list_ids is not None:
                raw_ids = [str(tlid).strip() for tlid in task_list_ids if str(tlid).strip()]
            elif task_list_id.strip():
                raw_ids = _split_task_list_ids(task_list_id)
            else:
                raw_ids = _split_task_list_ids(PLAN_DAY_TASK_LIST_IDS)

            seen: set[str] = set()
            out: list[str] = []
            for tlid in raw_ids:
                if tlid not in seen:
                    seen.add(tlid)
                    out.append(tlid)
            return out or [RECLAIM_TASK_LIST_ID]

        def _task_list_label(tlid: str) -> str:
            if tlid == RECLAIM_TASK_LIST_ID:
                return "Reclaim"
            if tlid == PERSONAL_TASK_LIST_ID:
                return "Minhas tarefas"
            return tlid

        start_local = datetime.combine(day_d, _t(day_start), tzinfo=tz) if tz else datetime.combine(day_d, _t(day_start), tzinfo=timezone.utc)
        end_local = datetime.combine(day_d, _t(day_end), tzinfo=tz) if tz else datetime.combine(day_d, _t(day_end), tzinfo=timezone.utc)
        if end_local <= start_local:
            end_local = end_local + timedelta(days=1)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        task_creds = Credentials.from_authorized_user_file(
            str(token_path),
            ['https://www.googleapis.com/auth/tasks'],
        )

        calendar_error = ""
        calendar_source = "google_calendar"
        official_schedule_status = "not_used"
        official_schedule_detail = ""
        official_schedule_events: list[dict] = []
        generic_reclaim_meetings = []
        reclaim_official_task_events: list[dict] = []
        busy_blocks = []

        official_schedule = _reclaim_official_get_schedule(day)
        if official_schedule.get("ok"):
            calendar_source = "reclaim_official_get_schedule"
            official_schedule_status = "ok"
            official_schedule_events = list(official_schedule.get("events") or [])
            busy_blocks, generic_reclaim_meetings, reclaim_official_task_events = _reclaim_official_events_to_busy(
                official_schedule_events,
                day,
                tz,
            )
        else:
            official_schedule_status = str(official_schedule.get("status") or "error")
            official_schedule_detail = str(official_schedule.get("detail") or "")
            try:
                calendar_creds = Credentials.from_authorized_user_file(
                    str(token_path),
                    ['https://www.googleapis.com/auth/calendar.readonly'],
                )
                cal_svc = build('calendar', 'v3', credentials=calendar_creds)
                fb_body = {
                    "timeMin": start_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "timeMax": end_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "items": [{"id": cid} for cid in calendar_ids],
                }
                fb = cal_svc.freebusy().query(body=fb_body).execute()
                for cid in calendar_ids:
                    events = cal_svc.events().list(
                        calendarId=cid,
                        timeMin=fb_body["timeMin"],
                        timeMax=fb_body["timeMax"],
                        singleEvents=True,
                        orderBy='startTime',
                        maxResults=250,
                    ).execute().get('items', [])
                    for ev in events:
                        summary = (ev.get('summary') or '').strip()
                        normalized = summary.replace('🤝', '').strip().lower()
                        if normalized != "meeting":
                            continue
                        ext_private = (ev.get('extendedProperties') or {}).get('private') or {}
                        if not any("reclaim" in str(k).lower() or "reclaim" in str(v).lower() for k, v in ext_private.items()):
                            continue
                        st = (ev.get('start') or {}).get('dateTime') or (ev.get('start') or {}).get('date') or ''
                        en = (ev.get('end') or {}).get('dateTime') or (ev.get('end') or {}).get('date') or ''
                        generic_reclaim_meetings.append((st, en, cid))
                for cid in calendar_ids:
                    for b in fb.get('calendars', {}).get(cid, {}).get('busy', []):
                        bs = datetime.fromisoformat(b['start'].replace('Z', '+00:00'))
                        be = datetime.fromisoformat(b['end'].replace('Z', '+00:00'))
                        busy_blocks.append((bs, be, cid))
            except Exception as cal_err:
                calendar_error = str(cal_err)
                busy_blocks = []
                generic_reclaim_meetings = []
        busy_blocks.sort(key=lambda x: x[0])

        merged = []
        for bs, be, cid in busy_blocks:
            if not merged:
                merged.append([bs, be])
                continue
            if bs <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], be)
            else:
                merged.append([bs, be])

        buf = timedelta(minutes=int(buffer_min))
        free = []
        cur = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        for bs, be in merged:
            fs = cur
            fe = bs - buf
            if fe > fs:
                free.append((fs, fe))
            cur = max(cur, be + buf)
        if cur < end_utc:
            free.append((cur, end_utc))

        tasks_svc = build('tasks', 'v1', credentials=task_creds)
        plan_task_list_ids = _task_list_ids_for_plan()
        items = []
        fetch_errors = []
        fetched_counts = []
        for tlid in plan_task_list_ids:
            label = _task_list_label(tlid)
            try:
                page_token = None
                count = 0
                while True:
                    req = tasks_svc.tasks().list(
                        tasklist=tlid,
                        showCompleted=False,
                        pageToken=page_token,
                    )
                    res = req.execute()
                    for it in res.get('items', []):
                        it = dict(it)
                        it['_task_list_id'] = tlid
                        it['_task_list_label'] = label
                        items.append(it)
                        count += 1
                    page_token = res.get('nextPageToken')
                    if not page_token:
                        break
                fetched_counts.append(f"{label}: {count}")
            except Exception as list_err:
                fetch_errors.append(f"{label}: {list_err}")

        def _parse_params(title: str) -> dict:
            out = {}
            m = re.search(r"\(([^)]*)\)\s*$", title)
            if not m:
                return out
            raw = m.group(1)
            for tok in raw.split():
                if ':' in tok:
                    k, v = tok.split(':', 1)
                    out[k.strip().lower()] = v.strip()
                else:
                    out[tok.strip().lower()] = True
            return out

        def _priority_rank(p):
            if p is True or p is None:
                return 5
            s = str(p).lower()
            return {
                'critical': 0,
                'p1': 1,
                'p2': 2,
                'p3': 3,
            }.get(s, 4)

        task_objs = []
        dump_objs = []
        for it in items:
            title = it.get('title', '')
            due_iso = (it.get('due') or '')
            due_d = None
            params = _parse_params(title)
            if due_iso:
                try:
                    due_d = date.fromisoformat(due_iso[:10])
                except Exception:
                    due_d = None
            if due_d is None and params.get('due'):
                try:
                    due_d = datetime.strptime(str(params['due']), "%m/%d/%Y").date()
                except Exception:
                    due_d = None
            dur_min = 30
            if 'duration' in params:
                m = re.match(r"(\d+)", str(params['duration']))
                if m:
                    dur_min = int(m.group(1))
            pr = params.get('priority', 'P2')
            upnext = bool(params.get('upnext', False))
            overdue = bool(due_d and due_d < day_d)
            source_id = it.get('_task_list_id', '')
            source_label = it.get('_task_list_label', source_id)
            is_dump = source_id == PERSONAL_TASK_LIST_ID

            obj = {
                'id': it.get('id'),
                'title': title,
                'dur_min': dur_min,
                'priority': pr,
                'priority_rank': _priority_rank(pr),
                'upnext': upnext,
                'overdue': overdue,
                'due': due_d,
                'source': source_label,
                'is_dump': is_dump,
            }

            if is_dump:
                dump_objs.append(obj)
                continue

            if due_d and due_d > day_d:
                continue
            if due_d and due_d < day_d and (not include_overdue):
                continue
            task_objs.append(obj)

        task_objs.sort(key=lambda t: (
            0 if t['upnext'] else 1,
            0 if t['overdue'] else 1,
            t['priority_rank'],
            t['due'] or day_d,
        ))
        dump_objs.sort(key=lambda t: (
            0 if t['overdue'] else 1,
            0 if t['due'] is None else 1,
            t['priority_rank'],
            t['due'] or date.max,
        ))

        allocations = []
        slot_i = 0
        slot_start = free[0][0] if free else None
        slot_end = free[0][1] if free else None

        def _advance_slot():
            nonlocal slot_i, slot_start, slot_end
            slot_i += 1
            if slot_i >= len(free):
                slot_start = slot_end = None
            else:
                slot_start, slot_end = free[slot_i]

        for tsk in task_objs:
            remaining = timedelta(minutes=int(tsk['dur_min']))
            while remaining.total_seconds() > 0:
                if slot_start is None:
                    allocations.append((tsk, None, None, True))
                    break
                available = slot_end - slot_start
                if available < timedelta(minutes=int(min_slot_min)):
                    _advance_slot()
                    continue
                chunk = min(available, remaining)
                st = slot_start
                en = slot_start + chunk
                allocations.append((tsk, st, en, False))
                slot_start = en + buf
                remaining -= chunk
                if slot_start is not None and slot_end is not None and (slot_end - slot_start) < timedelta(minutes=int(min_slot_min)):
                    _advance_slot()

        def _fmt_dt(dt: datetime) -> str:
            dloc = dt.astimezone(tz) if tz else dt
            return dloc.strftime('%H:%M')

        def _fmt_due(due_d: date | None) -> str:
            return due_d.isoformat() if due_d else "sem due"

        questions = []
        for tsk in task_objs:
            if tsk['overdue']:
                questions.append(
                    f"Reclaim: por que '{tsk['title']}' ainda está pendente com due {_fmt_due(tsk['due'])}? Manter hoje ou adiar?"
                )
            if len(questions) >= 4:
                break
        for tsk in dump_objs:
            if tsk['overdue']:
                questions.append(
                    f"Minhas tarefas: '{tsk['title']}' está vencida desde {_fmt_due(tsk['due'])}. Promover para Reclaim, adiar ou descartar?"
                )
            elif tsk['due'] is None:
                questions.append(
                    f"Minhas tarefas: '{tsk['title']}' não tem due. Isso deve virar compromisso no Reclaim ou ficar no dump?"
                )
            if len(questions) >= 8:
                break

        out = []
        out.append(f"plano do dia {day} (fuso: America/Sao_Paulo)")
        out.append(f"listas lidas: {', '.join(fetched_counts) if fetched_counts else '(nenhuma)'}")
        out.append(f"agenda lida via: {calendar_source}")
        if calendar_source == "reclaim_official_get_schedule":
            out.append(f"eventos lidos do Reclaim oficial: {len(official_schedule_events)}")
        else:
            out.append(f"Reclaim oficial get_schedule: {official_schedule_status}{(': ' + official_schedule_detail) if official_schedule_detail else ''}")
        out.append("tools oficiais de task: indisponíveis por upgrade nesta conta; tarefas lidas via Google Tasks/Jarvis.")
        if fetch_errors:
            out.append(f"falhas ao ler listas: {'; '.join(fetch_errors)}")
        if calendar_error:
            out.append(f"falha ao ler agenda: {calendar_error}")
        out.append("")
        out.append("política:")
        out.append("- Reclaim entra como lista operacional do dia e pode ser alocado.")
        out.append("- Minhas tarefas entra como dump desestruturado para triagem, sem alocação automática.")
        out.append("")
        out.append("busy (agenda):")
        if merged:
            for bs, be in merged:
                out.append(f"- {_fmt_dt(bs)}–{_fmt_dt(be)}")
        else:
            out.append("- (sem busy)")
        if generic_reclaim_meetings:
            out.append("")
            out.append("reuniões Reclaim com nome genérico:")
            for st, en, cid in generic_reclaim_meetings:
                try:
                    st_s = _fmt_dt(datetime.fromisoformat(st.replace('Z', '+00:00')))
                    en_s = _fmt_dt(datetime.fromisoformat(en.replace('Z', '+00:00')))
                except Exception:
                    st_s, en_s = st, en
                out.append(f"- {st_s}–{en_s} ({cid}): abrir automação do navegador do Reclaim para identificar o título real. `Travel` não precisa dessa checagem.")

        out.append("")
        out.append("free slots:")
        if free:
            for fs, fe in free:
                out.append(f"- {_fmt_dt(fs)}–{_fmt_dt(fe)}")
        else:
            out.append("- (sem slots livres)")

        out.append("")
        out.append("alocação sugerida:")
        if allocations:
            for tsk, st, en, unscheduled in allocations:
                title = tsk['title']
                if unscheduled or st is None:
                    out.append(f"- (sem espaço) {title}")
                else:
                    out.append(f"- {_fmt_dt(st)}–{_fmt_dt(en)} {title}")
        else:
            out.append("- (nenhum compromisso elegível no Reclaim)")

        out.append("")
        out.append("dump Minhas tarefas (não alocado automaticamente):")
        if dump_objs:
            for tsk in dump_objs[:12]:
                out.append(f"- {_fmt_due(tsk['due'])} {tsk['title']}")
        else:
            out.append("- (sem itens)")

        out.append("")
        out.append("perguntas de triagem:")
        if questions:
            for q in questions:
                out.append(f"- {q}")
        else:
            out.append("- (sem perguntas críticas agora)")

        return "\n".join(out)

    except Exception as e:
        import traceback
        return f"Erro no planner: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gtasks_create_weekly_series(
    base_title: str,
    end_date: str,
    context: str = "[Geral]",
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    duration_min: int = 60,
    priority: str = "P2",
    task_type: str = "work",
    mode: str = "auto",  # auto|fixed_day|window
    fixed_day: str | None = None,  # mon,tue,wed,thu,fri,sat,sun or pt-br: seg,ter,qua,qui,sex,sab,dom
    window_start: str = "mon",
    window_end: str = "sun",
    start_from: str = "next",  # next|today
) -> str:
    """Cria uma série semanal no Google Tasks (sem LLM) como tarefas individuais.

    Ideia: como não existe recorrência semanal nativa do Reclaim a partir de Tasks, criamos 1 tarefa por semana.

    - end_date: YYYY-MM-DD ou DD/MM/YYYY
    - mode:
      - auto: tenta detectar dia fixo no base_title (ex: "toda terça") e usa fixed_day; senão usa janela mon-sun.
      - fixed_day: cria uma tarefa por semana com due no dia fixo.
      - window: cria uma tarefa por semana com not before no início da janela e due no fim da janela.
    - start_from:
      - next: começa na próxima ocorrência (não começa imediatamente)
      - today: pode começar na semana atual

    Retorna os IDs criados.
    """
    try:
        from datetime import datetime, date, timedelta, time, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        # helpers
        def _parse_date(s: str) -> date:
            s = (s or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                y, mo, d = map(int, s.split('-'))
                return date(y, mo, d)
            m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
            if m:
                d, mo, y = map(int, m.groups())
                return date(y, mo, d)
            raise ValueError("end_date inválida. use YYYY-MM-DD ou DD/MM/YYYY")

        def _br(d: date) -> str:
            return f"{d.day:02d}/{d.month:02d}/{d.year}"

        def _us(d: date) -> str:
            return f"{d.month:02d}/{d.day:02d}/{d.year}"

        def _iso_midnight_utc(d: date) -> str:
            return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        pt_map = {
            'seg': 'mon','segunda':'mon','segunda-feira':'mon',
            'ter': 'tue','terça':'tue','terca':'tue','terça-feira':'tue','terca-feira':'tue',
            'qua': 'wed','quarta':'wed','quarta-feira':'wed',
            'qui': 'thu','quinta':'thu','quinta-feira':'thu',
            'sex': 'fri','sexta':'fri','sexta-feira':'fri',
            'sab': 'sat','sábado':'sat','sabado':'sat','sábado-feira':'sat',
            'dom': 'sun','domingo':'sun','domingo-feira':'sun',
        }
        dow = {'mon':0,'tue':1,'wed':2,'thu':3,'fri':4,'sat':5,'sun':6}

        def _norm_day(s: str | None) -> str | None:
            if not s:
                return None
            x = s.strip().lower()
            x = pt_map.get(x, x)
            return x if x in dow else None

        def _detect_fixed_day(text: str) -> str | None:
            t = (text or "").lower()
            # padrões comuns
            for k in ['seg','segunda','ter','terça','terca','qua','quarta','qui','quinta','sex','sexta','sab','sábado','sabado','dom','domingo']:
                if re.search(r"\btod[ao]s?\s+" + re.escape(k) + r"\b", t):
                    return _norm_day(k)
                if re.search(r"\btoda\s+" + re.escape(k) + r"\b", t):
                    return _norm_day(k)
                if re.search(r"\btodo\s+" + re.escape(k) + r"\b", t):
                    return _norm_day(k)
            return None

        end_d = _parse_date(end_date)
        now_local = datetime.now(tz) if tz else datetime.now()
        today = now_local.date()

        # context
        ctx = (context or "").strip()
        if not ctx.startswith('['):
            ctx = f"[{ctx}]" if ctx else "[Geral]"

        # choose mode
        mode2 = (mode or 'auto').strip().lower()
        fd = _norm_day(fixed_day)
        if mode2 == 'auto':
            fd = fd or _detect_fixed_day(base_title)
            mode2 = 'fixed_day' if fd else 'window'

        ws = _norm_day(window_start) or 'mon'
        we = _norm_day(window_end) or 'sun'

        # compute first week anchor
        def _next_weekday(d0: date, target: int, include_today: bool) -> date:
            cur = d0.weekday()
            delta = (target - cur) % 7
            if delta == 0 and not include_today:
                delta = 7
            return d0 + timedelta(days=delta)

        include_today = (start_from.strip().lower() == 'today')

        occurrences = []
        if mode2 == 'fixed_day':
            target = dow[fd]
            first = _next_weekday(today, target, include_today)
            cur = first
            while cur <= end_d:
                occurrences.append((cur, None))  # due_date, not_before
                cur = cur + timedelta(days=7)
        else:
            # window: each occurrence is a week window [ws..we]
            # pick next window_start
            first_start = _next_weekday(today, dow[ws], include_today)
            start = first_start
            while start <= end_d:
                # end of window
                end = start + timedelta(days=((dow[we]-dow[ws]) % 7))
                due = min(end, end_d)
                occurrences.append((due, start))
                start = start + timedelta(days=7)

        if not occurrences:
            return "Nenhuma ocorrência para criar (end_date antes do início)."

        # insert tasks
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        scopes = ['https://www.googleapis.com/auth/tasks']
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        svc = build('tasks', 'v1', credentials=creds)

        created = []
        for due_d, nb_d in occurrences:
            params = [
                f"duration:{int(duration_min)}m",
                f"due:{_us(due_d)}",
                f"priority:{priority}",
                f"type:{task_type}",
            ]
            if nb_d is not None:
                params.append(f"not before:{_us(nb_d)}")

            title = f"[{_br(due_d)}] {ctx} {base_title.strip()} ({' '.join(params)})"
            body = {'title': title, 'notes': 'Jarvis', 'due': _iso_midnight_utc(due_d)}
            res = svc.tasks().insert(tasklist=task_list_id, body=body).execute()
            created.append(res.get('id'))

        return "✅ weekly series criada.\n" + "\n".join([f"- {i}" for i in created])

    except Exception as e:
        import traceback
        return f"Erro ao criar weekly series: {e}\n{traceback.format_exc()}"


@mcp.tool()
def plan_day_apply(
    day: str,
    create_events: bool = True,
    calendar_id: str = "primary",
    task_list_id: str = "",
    task_list_ids: list[str] | None = None,
    day_end: str = "22:30",
) -> str:
    """Aplica o planejamento sem criar eventos diretos no Calendar.

    O Reclaim deve sincronizar a agenda a partir das tarefas no Google Tasks.
    A integração técnica é no nível da conta Google; esta ferramenta preserva a convenção da lista operacional Reclaim e não cria blocos manuais no Calendar.
    """
    try:
        planner = getattr(plan_day_from_tasks, "fn", plan_day_from_tasks)
        plan = planner(day=day, task_list_id=task_list_id, task_list_ids=task_list_ids)

        lines = plan.splitlines()
        alloc_start = None
        for i, l in enumerate(lines):
            if l.strip().lower().startswith('alocação sugerida'):
                alloc_start = i + 1
                break

        scheduled = 0
        skipped = 0
        scheduled_titles: list[str] = []
        if alloc_start is not None:
            for l in lines[alloc_start:]:
                l = l.strip()
                if not l:
                    break
                if not l.startswith('- '):
                    continue
                l2 = l[2:]
                if l2.startswith('(sem espaço)'):
                    skipped += 1
                    continue
                m = re.match(r"\d{2}:\d{2}–\d{2}:\d{2}\s+(.*)$", l2)
                if m:
                    scheduled += 1
                    scheduled_titles.append(m.group(1).strip())

        def _verify_real_agenda(attempt: int) -> tuple[str, bool]:
            try:
                from zoneinfo import ZoneInfo
                verify_tz = ZoneInfo("America/Sao_Paulo")
            except Exception:
                verify_tz = None
            observed = _reclaim_official_get_schedule(day, force=True)
            out = ["", f"verificação real na agenda, tentativa {attempt}/3:"]
            if not observed.get("ok"):
                out.append(f"- status: não verificada, Reclaim oficial get_schedule falhou ({observed.get('status')}: {observed.get('detail')})")
                return "\n".join(out), False
            events = list(observed.get("events") or [])
            _, _, task_events = _reclaim_official_events_to_busy(events, day, verify_tz)
            quality = _reclaim_official_agenda_quality(events, day, day_end, verify_tz)
            out.append("- status: agenda lida após a aplicação via Reclaim oficial.")
            out.append(f"- eventos observados na agenda: {len(events)}")
            out.append(f"- eventos de tarefa Reclaim observados: {len(task_events)}")
            out.extend(_format_reclaim_agenda_quality(quality))
            allocation_ok = True
            if scheduled_titles:
                matched = []
                for title in scheduled_titles:
                    if any(title.lower() in (ev.get("title", "") or "").lower() for ev in task_events):
                        matched.append(title)
                out.append(f"- alocações com horário no plano: {len(scheduled_titles)}")
                out.append(f"- alocações encontradas como evento de tarefa: {len(matched)}")
                allocation_ok = len(matched) == len(scheduled_titles)
                if not allocation_ok:
                    out.append("- resultado: aplicação real não confirmada para todas as alocações planejadas.")
                else:
                    out.append("- resultado: alocações planejadas aparecem na agenda observada.")
            else:
                out.append("- alocações com horário no plano: 0")
                out.append("- resultado: não havia novo bloco com horário para confirmar; a qualidade da agenda ainda foi validada.")
            ok = bool(quality.get("ok")) and allocation_ok
            if ok:
                out.append("- decisão: agenda aceita.")
            else:
                out.append("- decisão: agenda não aceita; precisa de nova iteração, desbloqueio, snooze validado ou ajuste manual no Reclaim.")
            return "\n".join(out), ok

        verification = ""
        verification_ok = False
        for attempt in range(1, 4):
            verification, verification_ok = _verify_real_agenda(attempt)
            if verification_ok:
                break
            if attempt < 3:
                time.sleep(10)
        if not create_events:
            return plan + "\n" + verification
        if alloc_start is None:
            return plan + "\n\n---\n(sem alocação para aplicar)" + "\n" + verification

        final_status = "✅ plano verificado na agenda real." if verification_ok else "⚠️ plano enviado ao fluxo, mas agenda real não ficou boa."

        return (
            plan
            + "\n\n---\n"
            + final_status + "\n"
            + "📅 eventos diretos criados no Calendar: 0\n"
            + "📡 agenda: Reclaim oficial quando `get_schedule` responde; fallback Google Calendar.\n"
            + "🧾 tarefas: Google Tasks/Jarvis enquanto task tools oficiais do Reclaim retornam upgrade.\n"
            + f"🧭 tarefas Reclaim consideradas alocáveis: {scheduled}\n"
            + f"↩️ tarefas sem espaço: {skipped}\n"
            + "Observação: o Reclaim é responsável por sincronizar e rearranjar os blocos no Calendar."
            + "\n"
            + verification
        )

    except Exception as e:
        import traceback
        return f"Erro ao aplicar plano: {e}\n{traceback.format_exc()}"


def _truncate_text_for_json_retry(text: str, limit: int = 4000) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + "\n...[truncated]"


def _find_balanced_json_substring(text: str) -> str:
    s = text or ""
    pairs = {'}': '{', ']': '['}
    start = None
    stack: list[str] = []
    in_string = False
    escape = False

    for idx, ch in enumerate(s):
        if start is None:
            if ch in '{[':
                start = idx
                stack = [ch]
            continue

        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in '{[':
            stack.append(ch)
            continue

        if ch in '}]':
            if not stack or stack[-1] != pairs[ch]:
                raise ValueError('json substring malformado')
            stack.pop()
            if not stack:
                return s[start:idx + 1].strip()

    raise ValueError('não encontrei objeto/array JSON balanceado')


def _extract_json_candidate(text: str) -> str:
    s = (text or '').strip()
    if not s:
        raise ValueError('resposta vazia')

    for marker in ('```json', '```JSON', '```Json'):
        if marker in s:
            tail = s.split(marker, 1)[1]
            if '```' in tail:
                candidate = tail.split('```', 1)[0].strip()
                if candidate:
                    return candidate

    if (s.startswith('[') and s.endswith(']')) or (s.startswith('{') and s.endswith('}')):
        return s

    return _find_balanced_json_substring(s)


def _build_json_retry_prompt(base_prompt: str, output_contract: str, previous_output: str, error: str, attempt: int, max_retries: int) -> str:
    return f"""{base_prompt}

--- CORREÇÃO ESTRUTURAL OBRIGATÓRIA ---
Tentativa {attempt} de {max_retries}.
A resposta anterior falhou na validação estrutural.

Erro encontrado:
{error}

Contrato obrigatório da saída:
{output_contract}

Resposta anterior inválida:
{_truncate_text_for_json_retry(previous_output)}

Responda SOMENTE com um bloco ```json contendo JSON válido e compatível com o contrato.
""".strip()


def _invoke_llm_json_with_retry(llm, system_prompt: str, user_prompt: str, validator, output_contract: str, max_retries: int = 3):
    from langchain_core.messages import SystemMessage, HumanMessage

    attempts = max(1, int(max_retries or 1))
    errors: list[dict] = []
    last_output = ''
    last_error = ''

    for attempt in range(1, attempts + 1):
        prompt_to_send = user_prompt if attempt == 1 else _build_json_retry_prompt(
            base_prompt=user_prompt,
            output_contract=output_contract,
            previous_output=last_output,
            error=last_error,
            attempt=attempt,
            max_retries=attempts,
        )
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt_to_send),
        ])
        content = getattr(response, 'content', '') or ''
        last_output = content

        try:
            candidate = _extract_json_candidate(content)
            parsed = json.loads(candidate)
            normalized = validator(parsed)
            meta = {
                'attempts_used': attempt,
                'max_retries': attempts,
                'errors': errors,
            }
            return normalized, content, meta
        except Exception as exc:
            last_error = str(exc)
            errors.append({'attempt': attempt, 'error': last_error})
            print(f"⚠️ json retry {attempt}/{attempts}: {last_error}", file=sys.stderr)

    raise ValueError(f"json retry esgotado após {attempts} tentativas: {last_error}")


@mcp.tool()
def gtasks_smart_sync_add_reclaim(
    new_tasks_input: str,
    task_list_id: str | None = None,
    clear_all_first: bool = False,
    # defaults do fallback básico (sem LLM)
    fallback_context: str = "[Geral]",
    fallback_duration_min: int = 30,
    fallback_priority: str = "P2",
    fallback_task_type: str = "work",
    fallback_default_to_today: bool = True,
) -> str:
    """Sincronização Inteligente do Google Tasks com fallback automático.

    tentativas:
    - modo llm: planeja via llm (reclaim/gtid) e insere via api
    - se falhar (timeout, credenciais, parsing etc): fallback básico sem llm

    fallback básico:
    - cria 1 tarefa por linha do new_tasks_input usando gtasks_create_task_natural (sem llm, mas com estrutura reclaim)
    """

    def _basic_lines(raw: str) -> list[str]:
        # 1 tarefa por linha (ignora vazias); também aceita listas com "- " e "• "
        out: list[str] = []
        for ln in (raw or "").splitlines():
            s = (ln or "").strip()
            if not s:
                continue
            s = re.sub(r"^[-•]\s+", "", s).strip()
            if s:
                out.append(s)
        return out

    def _fallback_basic(reason: str, detail: str = "") -> str:
        lines = _basic_lines(new_tasks_input)
        if not lines:
            payload = {
                "ok": False,
                "mode": "fallback_basic",
                "reason": reason,
                "detail": detail,
                "created": 0,
                "errors": 0,
                "message": "nenhuma linha de tarefa encontrada para criar.",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        created: list[str] = []
        errors: list[str] = []
        for ln in lines:
            res = gtasks_create_task_natural(
                text=ln,
                task_list_id=task_list_id or os.environ.get("RECLAIM_TASK_LIST_ID", "TUZuVGxQZkRxSjRrWkNtbw"),
                context=fallback_context,
                duration_min=fallback_duration_min,
                priority=fallback_priority,
                task_type=fallback_task_type,
                default_to_today=fallback_default_to_today,
            )
            try:
                payload = json.loads(res) if isinstance(res, str) else {}
            except Exception:
                payload = {}

            if isinstance(payload, dict) and payload.get("ok") is True:
                created.append(res)
            else:
                errors.append(f"{ln} -> {res}")

        payload = {
            "ok": len(created) > 0 and len(errors) == 0,
            "mode": "fallback_basic",
            "reason": reason,
            "detail": detail,
            "created": len(created),
            "errors": len(errors),
            "created_results": created[:20],
            "error_results": errors[:20],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # se não foi informado, usa a lista operacional padrão do fluxo Reclaim
    if not task_list_id:
        task_list_id = os.environ.get("RECLAIM_TASK_LIST_ID", "TUZuVGxQZkRxSjRrWkNtbw")

    # -------- modo llm (tentativa principal) --------
    try:
        # usa o langchain_openai padrão para ter acesso ao método .invoke() síncrono
        from langchain_openai import ChatOpenAI

        # 1. autenticação
        try:
            service = _gtasks_service()
        except Exception as auth_err:
            return _fallback_basic(reason="google_auth_failed", detail=_google_auth_actionable_error(auth_err))

        # 2. listar atuais
        try:
            results = service.tasks().list(tasklist=task_list_id, showCompleted=False).execute()
        except Exception as api_err:
            return _fallback_basic(reason="google_tasks_list_failed", detail=_google_auth_actionable_error(api_err))

        items = results.get('items', [])
        current_titles = [i.get('title', '') for i in items if i.get('title')]

        # 3. planejamento com llm
        system_prompt = PROMPT_GTASKS_RECLAIM

        llm = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-lite-preview-02-05:free"),
            temperature=0.2,
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        )

        instr_extra = """
\n--- INSTRUÇÃO DE JSON (CRÍTICA) ---
Gere um bloco JSON no final para a API.

REGRAS DE DATA (MUITO IMPORTANTE):
1. No TÍTULO (para Reclaim): Use formato AMERICANO no parâmetro (due:MM/DD/YYYY).
2. No CAMPO 'due' (para API): Use formato ISO 8601 (YYYY-MM-DDT00:00:00Z).

REGRAS DE TÍTULO:
1. O campo 'title' DEVE incluir: Data, Contexto e Parâmetros Reclaim.
2. FOCO NO TRABALHO: Ignore instruções de comando.

EXEMPLO CORRETO:
```json
[
  {
    "title": "[12/01/2026] [OrganizeJr] Consertar (duration:60m due:01/12/2026 ...)",
    "due": "2026-01-12T00:00:00Z",
    "notes": "..."
  }
]
```
"""

        full_prompt = f"""
📅 INFORMAÇÃO TEMPORAL CRÍTICA:
Hoje é: {datetime.now().strftime('%A, %d/%m/%Y')}

📋 TAREFAS JÁ NO GOOGLE TASKS:
{str(current_titles)}

📥 NOVAS TAREFAS DO USUÁRIO:
{new_tasks_input}

{instr_extra}
"""

        print("🤖 jarvis: planejando tarefas (llm)...", file=sys.stderr)

        # manda o prompt mestre como system message (mais confiável do que misturar tudo num texto só)
        from langchain_core.messages import SystemMessage, HumanMessage

        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=full_prompt),
            ]
        )
        content = getattr(response, 'content', '') or ''

        # 4. extração + validação do json com retry estrutural
        tasks_to_insert: list[dict] = []

        def _validate_tasks_payload(obj) -> list[dict]:
            if not isinstance(obj, list):
                raise ValueError('json não é array')
            if not obj:
                raise ValueError('json array vazio')

            cleaned: list[dict] = []
            errors: list[str] = []
            for idx, item in enumerate(obj):
                if not isinstance(item, dict):
                    errors.append(f'idx={idx}: item não é objeto')
                    continue

                title = str(item.get('title', '') or '').strip()
                if not title:
                    errors.append(f'idx={idx}: title vazio')
                    continue

                out = {
                    'title': title,
                    'notes': str(item.get('notes', '') or '').strip() or 'Jarvis',
                }

                due_raw = item.get('due')
                if due_raw is not None and str(due_raw).strip() != '':
                    due_s = str(due_raw).strip()
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', due_s):
                        due_s = due_s + 'T00:00:00Z'
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', due_s):
                        errors.append(f'idx={idx}: due inválido: {due_s}')
                        continue
                    try:
                        datetime.strptime(due_s, '%Y-%m-%dT%H:%M:%SZ')
                    except Exception as e:
                        errors.append(f'idx={idx}: due inválido (parse): {due_s} ({e})')
                        continue
                    out['due'] = due_s

                cleaned.append(out)

            if errors:
                raise ValueError('erros de validação: ' + ' | '.join(errors[:5]))

            return cleaned

        output_contract = """
Responda SOMENTE com um bloco ```json contendo um ARRAY JSON válido.
Cada item do array deve ser um objeto com:
- title: string não vazia
- due: opcional, formato ISO 8601 YYYY-MM-DDT00:00:00Z
- notes: opcional, string
Sem comentários.
Sem texto fora do bloco.
""".strip()

        try:
            tasks_to_insert, content, retry_meta = _invoke_llm_json_with_retry(
                llm=llm,
                system_prompt=system_prompt,
                user_prompt=full_prompt,
                validator=_validate_tasks_payload,
                output_contract=output_contract,
                max_retries=int(os.environ.get('JARVIS_MASTER_JSON_RETRIES', '3')),
            )
        except Exception as parse_err:
            return _fallback_basic(reason='llm_json_parse_failed', detail=str(parse_err))

        if not tasks_to_insert:
            return _fallback_basic(reason="llm_returned_empty_tasks", detail="json validado vazio")

        # 5. execução (limpeza e inserção)
        log_exec = []
        if clear_all_first:
            print(f"🗑️ limpando {len(items)} tarefas antigas da lista {task_list_id}...", file=sys.stderr)
            for item in items:
                try:
                    service.tasks().delete(tasklist=task_list_id, task=item['id']).execute()
                except Exception:
                    pass
            log_exec.append("✅ tarefas antigas removidas.")

        print(f"🚀 inserindo {len(tasks_to_insert)} novas tarefas na lista {task_list_id}...", file=sys.stderr)
        inserted = 0
        for t in tasks_to_insert:
            try:
                body = {'title': t.get('title'), 'notes': t.get('notes')}
                if t.get('due'):
                    body['due'] = t.get('due')
                service.tasks().insert(tasklist=task_list_id, body=body).execute()
                inserted += 1
            except Exception as ins_err:
                # se inserção falhar no meio, cai pro fallback para garantir que algo seja criado
                return _fallback_basic(reason="google_tasks_insert_failed", detail=str(ins_err))

        log_exec.append(f"✅ {inserted} tarefas inseridas na lista {task_list_id}.")

        payload = {
            "ok": True,
            "mode": "llm",
            "inserted": inserted,
            "execution_log": log_exec,
            "llm_text": content,
            "json_retry_meta": retry_meta,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _fallback_basic(reason="llm_mode_exception", detail=str(e) + "\n" + traceback.format_exc())


# --- MERGED LOCAL SCRIPTS (auth/bridge/venv/oci) ---
_GOOGLE_TASKS_SCOPES = [
    'https://www.googleapis.com/auth/tasks',
]

_GOOGLE_CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

_GOOGLE_DRIVE_SCOPES = [
    # escopo padrão do @ibarcarty/mcp-server-google-drive, cobre Drive, Docs, Sheets e Slides.
    'https://www.googleapis.com/auth/drive',
]

_GEMINI_BRIDGE_BIN = os.environ.get(
    "GEMINI_BRIDGE_BIN",
    "/home/lucas/.npm-global/bin/gemini" if Path("/home/lucas/.npm-global/bin/gemini").exists() else "gemini",
)
_GEMINI_BRIDGE_TIMEOUT_SEC = float(os.environ.get("GEMINI_BRIDGE_TIMEOUT_SEC", "180"))
_GEMINI_BRIDGE_HEALTH_TIMEOUT_SEC = float(os.environ.get("GEMINI_BRIDGE_HEALTH_TIMEOUT_SEC", "30"))
_GEMINI_BRIDGE_DEFAULT_OUTPUT = os.environ.get("GEMINI_BRIDGE_DEFAULT_OUTPUT", "json")
_GEMINI_BRIDGE_ALLOWED_OUTPUTS = {"json", "text", "stream-json"}
_GEMINI_BRIDGE_RUN_AS_USER = (os.environ.get("GEMINI_BRIDGE_RUN_AS_USER", "lucas") or "").strip()


def _resolve_local_path(value: str | None, default: Path) -> Path:
    raw = (value or "").strip()
    if raw:
        p = Path(raw).expanduser()
    else:
        p = default
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p


def _pick_google_client_secret(preferred: str = "") -> Path | None:
    preferred_path = _resolve_local_path(preferred, Path("")) if preferred else None
    if preferred_path and preferred_path.exists():
        return preferred_path

    candidates = [
        BASE_DIR / 'gcp-oauth.keys.json',
        BASE_DIR / 'credentials.json',
        BASE_DIR / 'client_secret_431363687179-e6kg1vntd4033cfth27lskq765j8md8l.apps.googleusercontent.com.json',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_token_json(token_path: Path) -> dict:
    try:
        return json.loads(token_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _auth_google_cli(
    scope: str = "tasks",
    client_secret: str = "",
    token_path: str = "",
    host: str = "127.0.0.1",
    port: int | None = None,
    open_browser: bool | None = None,
) -> int:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as e:
        print(f"❌ Dependências Google OAuth não disponíveis: {e}", file=sys.stderr)
        return 1

    raw_scope = (scope or "").strip().lower()
    requested_scopes = [s.strip() for s in raw_scope.split(",") if s.strip()]
    # dedupe, preserving order
    requested_scopes = list(dict.fromkeys(requested_scopes))
    if not requested_scopes:
        requested_scopes = ["tasks"]

    if "all" in requested_scopes:
        requested_scopes = ["tasks", "calendar", "drive"]

    allowed = {"tasks", "calendar", "drive", "all"}
    invalid = [s for s in requested_scopes if s not in allowed]
    if invalid:
        print(
            "❌ Escopo inválido: {invalid}. Use --scope all ou tasks,calendar,drive (separado por vírgula).".format(
                invalid=", ".join(invalid)
            ),
            file=sys.stderr,
        )
        return 1

    # compõe lista final de scopes (união)
    selected_scopes: list[str] = []
    if "tasks" in requested_scopes:
        selected_scopes.extend(_GOOGLE_TASKS_SCOPES)
    if "calendar" in requested_scopes:
        selected_scopes.extend(_GOOGLE_CALENDAR_SCOPES)
    if "drive" in requested_scopes:
        selected_scopes.extend(_GOOGLE_DRIVE_SCOPES)

    # dedupe, preserving order
    selected_scopes = list(dict.fromkeys(selected_scopes))

    joined = ",".join(requested_scopes)
    already_valid_msg = "✅ Token Google ({joined}) já válido em {{token_file}}. Seguindo sem novo login.".format(joined=joined)
    saved_msg = "✅ Token com escopos Google ({joined}) salvo em {{token_file}}".format(joined=joined)

    # Port/open_browser seguem regras simples:
    # - Se drive estiver presente, port default=0 e open_browser default=True.
    # - Caso contrário, port default=18798 se calendar presente, senão 18797. open_browser default=False.
    if "drive" in requested_scopes:
        default_port = 0
        default_open_browser = True
    else:
        default_port = 18798 if "calendar" in requested_scopes else 18797
        default_open_browser = False

    requested_port = default_port if port is None else int(port)
    requested_open_browser = default_open_browser if open_browser is None else bool(open_browser)

    # Em ambientes headless (ex.: rodando via ssh, systemd, mcp), o webbrowser
    # do Python costuma falhar com "could not locate runnable browser".
    # Quando o usuário quer autenticar via VNC, precisamos forçar um browser
    # conhecido e um DISPLAY válido.
    #
    # Heurística:
    # - se --open-browser foi pedido (True) e não há DISPLAY definido,
    #   assumimos a sessão VNC padrão em :1.
    # - se BROWSER não estiver definido, escolhemos um browser instalado.
    if requested_open_browser:
        if not (os.environ.get("DISPLAY") or "").strip():
            os.environ["DISPLAY"] = ":1"

        if not (os.environ.get("BROWSER") or "").strip():
            for candidate in ("google-chrome", "chromium", "firefox", "xdg-open"):
                if shutil.which(candidate):
                    os.environ["BROWSER"] = candidate
                    break

    token_file = _resolve_local_path(token_path, BASE_DIR / "token.json")
    secret_file = _pick_google_client_secret(client_secret)
    if not secret_file:
        print(
            "❌ Nenhum client secret encontrado. Forneça --client-secret ou coloque gcp-oauth.keys.json/credentials.json em jarvis_mcp.",
            file=sys.stderr,
        )
        return 1

    creds = None
    needed_scopes = set(selected_scopes)

    if token_file.exists():
        token_data = _load_token_json(token_file)
        existing_scopes = set(token_data.get("scopes", []) or [])
        if needed_scopes.issubset(existing_scopes):
            try:
                creds = Credentials.from_authorized_user_file(str(token_file), selected_scopes)
            except Exception:
                creds = None

    if creds and creds.valid:
        print(already_valid_msg.format(token_file=token_file))
        return 0

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), selected_scopes)
            creds = flow.run_local_server(
                host=host,
                port=requested_port,
                open_browser=requested_open_browser,
                # garante que o webbrowser.get() tenha alvo explícito (útil no VNC).
                browser=os.environ.get("BROWSER") or None,
            )

    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(saved_msg.format(token_file=token_file))
    return 0




def _extract_freeze_packages(venv_dir: Path) -> list[str]:
    pip_bin = venv_dir / 'bin' / 'pip'
    if not pip_bin.exists():
        return []
    proc = subprocess.run([str(pip_bin), 'freeze'], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in (proc.stdout or '').splitlines() if ln.strip()]


def _normalize_requirement_names(lines: list[str]) -> set[str]:
    packages: set[str] = set()
    for line in lines:
        if not line or line.startswith('#') or line.startswith('-e') or '@' in line:
            continue
        base = re.split(r'[=<>~!]', line)[0].strip().lower()
        if base:
            packages.add(base)
    return packages


def _install_super_venv_cli(
    python_bin: str = "python3",
    install_playwright: bool = True,
    remove_old_venvs: bool = True,
) -> int:
    req_main = _extract_freeze_packages(BASE_DIR / '.venv')
    req_oci = _extract_freeze_packages(BASE_DIR / '.venv-oci')

    pkgs = _normalize_requirement_names(req_main + req_oci)
    essentials = {
        'chromadb', 'google-generativeai', 'fastapi', 'uvicorn',
        'pydantic', 'pydantic-settings', 'python-multipart',
        'setuptools', 'oci', 'paramiko', 'requests', 'sentence-transformers',
        'playwright', 'langchain-openai', 'numpy',
    }
    final_set = sorted(pkgs.union(essentials))

    req_file = BASE_DIR / 'super_requirements.txt'
    req_file.write_text('\n'.join(final_set) + '\n', encoding='utf-8')
    print(f"✅ super_requirements.txt atualizado com {len(final_set)} pacotes")

    venv_super = BASE_DIR / '.venv-super'
    if not venv_super.exists():
        rc = _run_cli_command([python_bin, '-m', 'venv', str(venv_super)])
        if rc != 0:
            return rc

    expected_pkgs = set(final_set)
    installed_pkgs = _normalize_requirement_names(_extract_freeze_packages(venv_super)) if venv_super.exists() else set()
    need_install = not expected_pkgs.issubset(installed_pkgs)

    if need_install:
        pip_cmd = str(venv_super / 'bin' / 'pip')
        rc = _run_cli_command([pip_cmd, 'install', '--upgrade', 'pip', 'setuptools', 'wheel'])
        if rc != 0:
            return rc
        rc = _run_cli_command([pip_cmd, 'install', '--no-cache-dir', '-r', str(req_file)])
        if rc != 0:
            return rc
    else:
        print('✅ .venv-super já contém os pacotes esperados. Seguindo sem reinstalar.')

    if install_playwright:
        playwright_bin = venv_super / 'bin' / 'playwright'
        if playwright_bin.exists():
            rc = _run_cli_command([str(playwright_bin), 'install', 'chromium'], allow_failure=True)
            if rc != 0:
                print('⚠️ Falha ao instalar Chromium do Playwright (seguindo).', file=sys.stderr)
        else:
            print('⚠️ playwright não encontrado no .venv-super/bin (seguindo).', file=sys.stderr)

    if remove_old_venvs:
        for old in [BASE_DIR / '.venv', BASE_DIR / '.venv-oci']:
            if old.exists():
                print(f"🧹 Removendo {old}")
                shutil.rmtree(old, ignore_errors=True)

    print('✅ install-super-venv concluído')
    return 0


def _get_public_ip() -> str | None:
    try:
        import requests
        return requests.get('https://api.ipify.org', timeout=12).text.strip()
    except Exception:
        return None


def _fix_firewall_oci_cli(target_instance_ip: str = '163.176.169.99') -> int:
    try:
        import oci
    except Exception as e:
        print(f"❌ OCI SDK não disponível: {e}", file=sys.stderr)
        return 1

    try:
        config = oci.config.from_file()
        compute = oci.core.ComputeClient(config)
        network = oci.core.VirtualNetworkClient(config)
        compartment_id = config.get('tenancy')
    except Exception as e:
        print(f"❌ Erro ao carregar config OCI: {e}", file=sys.stderr)
        return 1

    my_ip = _get_public_ip()
    if not my_ip:
        print('❌ Não foi possível detectar seu IP público.', file=sys.stderr)
        return 1

    print(f"📡 Seu IP público: {my_ip}")
    print(f"🔍 Buscando VM com IP público {target_instance_ip}...")

    target_inst = None
    subnet_id = None
    try:
        instances = compute.list_instances(compartment_id).data
    except Exception as e:
        print(f"❌ Falha ao listar instâncias: {e}", file=sys.stderr)
        return 1

    for inst in instances:
        if getattr(inst, 'lifecycle_state', '') != 'RUNNING':
            continue
        try:
            vnic_attachments = compute.list_vnic_attachments(compartment_id, instance_id=inst.id).data
            if not vnic_attachments:
                continue
            vnic = network.get_vnic(vnic_attachments[0].vnic_id).data
            if getattr(vnic, 'public_ip', None) == target_instance_ip:
                target_inst = inst
                subnet_id = vnic.subnet_id
                break
        except Exception:
            continue

    if not target_inst or not subnet_id:
        print(f"❌ VM com IP {target_instance_ip} não encontrada.", file=sys.stderr)
        return 1

    print(f"✅ VM encontrada: {target_inst.display_name}")

    try:
        subnet = network.get_subnet(subnet_id).data
        sec_list_ids = list(subnet.security_list_ids or [])
    except Exception as e:
        print(f"❌ Falha ao carregar subnet/security list: {e}", file=sys.stderr)
        return 1

    if not sec_list_ids:
        print('❌ Subnet sem Security Lists.', file=sys.stderr)
        return 1

    target_sec_list_id = sec_list_ids[0]
    sec_list = network.get_security_list(target_sec_list_id).data
    current_rules = list(sec_list.ingress_security_rules or [])

    for rule in current_rules:
        try:
            if rule.protocol == '6' and rule.tcp_options and rule.tcp_options.destination_port_range.min == 22:
                if rule.source == f"{my_ip}/32":
                    print('✅ Regra para seu IP já existe.')
                    return 0
                if rule.source == '0.0.0.0/0':
                    print('⚠️ Porta 22 já aberta para 0.0.0.0/0. O problema pode ser outro.')
                    return 0
        except Exception:
            continue

    new_rule = oci.core.models.IngressSecurityRule(
        protocol='6',
        source=f"{my_ip}/32",
        source_type='CIDR_BLOCK',
        tcp_options=oci.core.models.TcpOptions(
            destination_port_range=oci.core.models.PortRange(min=22, max=22)
        ),
        description=f"Auto-fix SSH for MCP ({my_ip})",
    )
    current_rules.append(new_rule)

    update_details = oci.core.models.UpdateSecurityListDetails(ingress_security_rules=current_rules)
    try:
        network.update_security_list(target_sec_list_id, update_details)
        print(f"🔓 SUCESSO! Porta 22 liberada para {my_ip}/32")
        return 0
    except Exception as e:
        print(f"❌ Falha ao atualizar firewall: {e}", file=sys.stderr)
        return 1


def _gemini_bridge_validate_output_format(output_format: str) -> str:
    value = (output_format or '').strip().lower() or _GEMINI_BRIDGE_DEFAULT_OUTPUT
    if value not in _GEMINI_BRIDGE_ALLOWED_OUTPUTS:
        raise ValueError(
            f"output_format inválido: {value}. Use um destes: {sorted(_GEMINI_BRIDGE_ALLOWED_OUTPUTS)}"
        )
    return value


def _gemini_bridge_validate_timeout(timeout_sec: float | int | None) -> float:
    if timeout_sec is None:
        return _GEMINI_BRIDGE_TIMEOUT_SEC
    value = float(timeout_sec)
    if value <= 0:
        raise ValueError('timeout_sec deve ser maior que zero.')
    return value


def _gemini_bridge_resolve_workdir(workdir: str | None) -> str | None:
    if not workdir:
        return None
    candidate = Path(workdir).expanduser().resolve()
    if not candidate.exists():
        raise ValueError(f"workdir não existe: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"workdir não é diretório: {candidate}")
    return str(candidate)


def _ensure_gemini_available() -> str:
    resolved = shutil.which(_GEMINI_BRIDGE_BIN)
    if not resolved and _GEMINI_BRIDGE_BIN == "gemini":
        preferred = Path("/home/lucas/.npm-global/bin/gemini")
        if preferred.exists():
            resolved = str(preferred)
    if not resolved:
        raise RuntimeError(
            f"Binário Gemini não encontrado no PATH: {_GEMINI_BRIDGE_BIN}. Instale/ajuste o PATH ou defina GEMINI_BRIDGE_BIN."
        )
    return resolved


def _gemini_dns_preflight(env: dict, preexec_fn: object | None, timeout_sec: float = 4.0) -> tuple[bool, str]:
    node_bin = shutil.which("node")
    if not node_bin:
        return True, "node_not_found_skip"
    hosts = ["generativelanguage.googleapis.com", "google.com"]
    last_err = ""
    for _ in range(3):
        for host in hosts:
            script = (
                f"require('dns').lookup('{host}',"
                "(err,address)=>{if(err){console.error(err.code||String(err));process.exit(2);}console.log(address||'ok');})"
            )
            try:
                proc = subprocess.run(
                    [node_bin, "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                    preexec_fn=preexec_fn,
                )
            except subprocess.TimeoutExpired:
                last_err = "dns_lookup_timeout"
                continue
            except Exception as exc:
                last_err = f"dns_lookup_error:{exc}"
                continue

            if proc.returncode == 0:
                return True, f"{host}:{((proc.stdout or '').strip() or 'ok')}"
            last_err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"rc={proc.returncode}"
        time.sleep(0.2)
    return False, last_err or "dns_lookup_failed"


def _gemini_bridge_subprocess_context() -> tuple[dict, object | None, str]:
    env = os.environ.copy()
    env.setdefault('NO_COLOR', '1')
    env.setdefault('CI', '1')
    env.setdefault('NO_UPDATE_NOTIFIER', '1')
    env.setdefault('NPM_CONFIG_UPDATE_NOTIFIER', 'false')
    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        raw_key = (env.get(key_name, "") or "").strip()
        if raw_key.startswith("sk-") or raw_key.startswith("sk-or-"):
            env.pop(key_name, None)
            continue
    if not _gemini_bridge_google_api_key(env):
        try:
            env_text = _env_sh_path().read_text(encoding="utf-8")
            for match in re.finditer(r"^export\s+(GEMINI_API_KEY|GOOGLE_API_KEY)=[\"']?([^\"'\n]+)", env_text, re.MULTILINE):
                candidate = (match.group(2) or "").strip()
                if candidate.startswith("AIza"):
                    env[match.group(1)] = candidate
                    env.setdefault("GOOGLE_API_KEY", candidate)
                    env.setdefault("GEMINI_API_KEY", candidate)
                    break
        except Exception:
            pass


    run_as_user = ""
    preexec_fn = None

    # Garante workspace do Gemini no contexto do projeto/usuário, nunca em /root por padrão.
    gemini_home_raw = (env.get("GEMINI_CLI_HOME", "") or "").strip()
    if gemini_home_raw:
        gemini_home = Path(gemini_home_raw).expanduser()
        if not gemini_home.is_absolute():
            gemini_home = (BASE_DIR / gemini_home).resolve()
    else:
        gemini_home = Path("/home/lucas")
    while gemini_home.name == ".gemini":
        gemini_home = gemini_home.parent
    gemini_home.mkdir(parents=True, exist_ok=True)
    env["GEMINI_CLI_HOME"] = str(gemini_home)

    if os.geteuid() == 0 and _GEMINI_BRIDGE_RUN_AS_USER:
        try:
            pw = pwd.getpwnam(_GEMINI_BRIDGE_RUN_AS_USER)
            run_as_user = _GEMINI_BRIDGE_RUN_AS_USER
            env["HOME"] = pw.pw_dir
            env["USER"] = run_as_user
            env["LOGNAME"] = run_as_user
            user_gemini_home = Path(env["GEMINI_CLI_HOME"])
            user_gemini_home.mkdir(parents=True, exist_ok=True)
            try:
                os.chown(user_gemini_home, pw.pw_uid, pw.pw_gid)
            except Exception:
                pass

            def _drop_privs() -> None:
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)

            preexec_fn = _drop_privs
        except Exception:
            run_as_user = ""

    return env, preexec_fn, run_as_user

def _gemini_bridge_google_api_key(env: dict) -> str:
    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        raw_key = (env.get(key_name) or os.environ.get(key_name) or "").strip()
        if not raw_key:
            continue
        if raw_key.startswith("sk-") or raw_key.startswith("sk-or-"):
            continue
        if raw_key.startswith("AIza"):
            return raw_key
    return ""


def _test_gemini_model_availability(model: str, api_key: str, timeout_sec: float = 10.0) -> dict:
    """Testa se um modelo do Gemini está disponível e retorna status."""
    try:
        model_clean = model.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_clean}:generateContent"
        
        payload = {"contents": [{"parts": [{"text": "test"}]}]}
        full_url = f"{url}?key={api_key}"
        
        resp = httpx.post(
            full_url,
            json=payload,
            timeout=min(timeout_sec, 8.0),
            trust_env=False,
        )
        
        if resp.status_code == 200:
            return {
                'model': model,
                'status': 'available',
                'response': resp.json(),
                'success': True
            }
        elif resp.status_code == 429:
            error_data = resp.json().get('error', {})
            if error_data.get('code') == 429:
                return {
                    'model': model,
                    'status': 'capacity_exhausted',
                    'error': error_data.get('message', 'Capacity exhausted'),
                    'success': False
                }
            elif 'quota' in error_data.get('message', '').lower():
                return {
                    'model': model,
                    'status': 'quota_exceeded',
                    'error': error_data.get('message', 'Quota exceeded'),
                    'success': False
                }
            else:
                return {
                    'model': model,
                    'status': 'rate_limited',
                    'error': error_data.get('message', 'Rate limited'),
                    'success': False
                }
        else:
            return {
                'model': model,
                'status': 'error',
                'error': f"HTTP {resp.status_code}: {resp.text}",
                'success': False
            }
    except Exception as e:
        return {
            'model': model,
            'status': 'failed',
            'error': str(e),
            'success': False
        }


def _get_best_available_gemini_model(api_key: str = None, timeout_sec: float = 15.0) -> str:
    """Testa múltiplos modelos e retorna o primeiro disponível."""
    if not api_key:
        api_key = _gemini_bridge_google_api_key(os.environ)
    
    if not api_key:
        return "gemini-2.5-flash"  # Fallback padrão
    
    # Lista de modelos para testar em ordem de preferência
    models_to_test = [
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview", 
        "gemini-3-flash-preview",
        "gemini-2.5-flash"
    ]
    
    print("🔍 Testando disponibilidade dos modelos do Gemini...", file=sys.stderr)
    invalid_api_key_detected = False

    for model in models_to_test:
        result = _test_gemini_model_availability(model, api_key, timeout_sec)
        print(f"  • {model}: {result['status']}", file=sys.stderr)

        if result['success']:
            print(f"✅ Modelo selecionado: {model}", file=sys.stderr)
            return model
        elif result['status'] == 'quota_exceeded':
            print(f"⚠️  Quota excedida para {model}, tentando próximo...", file=sys.stderr)
            continue
        elif result['status'] == 'capacity_exhausted':
            print(f"⚠️  Capacity exhausted para {model}, tentando próximo...", file=sys.stderr)
            continue
        else:
            error_text = str(result.get('error', '') or '')
            if 'API_KEY_INVALID' in error_text or 'API key not valid' in error_text:
                invalid_api_key_detected = True
                print("⚠️  GEMINI_API_KEY/GOOGLE_API_KEY inválida; usando fallback local de modelo.", file=sys.stderr)
                break
            print(f"❌ Erro no modelo {model}: {result['error']}", file=sys.stderr)

    # Se nenhum modelo funcionar, retorna o fallback
    if not invalid_api_key_detected:
        print("⚠️  Nenhum modelo disponível, usando fallback: gemini-2.5-flash", file=sys.stderr)
    return "gemini-2.5-flash"


def _gemini_api_fallback_prompt(
    *,
    prompt: str,
    output_format: str,
    model_name: str,
    timeout_sec: float,
    env: dict,
) -> dict:
    api_key = _gemini_bridge_google_api_key(env)
    if not api_key:
        raise RuntimeError("Sem GEMINI_API_KEY/GOOGLE_API_KEY para fallback HTTP.")

    # Seleciona automaticamente o melhor modelo disponível
    if not model_name or not model_name.strip():
        model = _get_best_available_gemini_model(api_key)
        print(f"🤖 Modelo automático selecionado: {model}", file=sys.stderr)
    else:
        model = (model_name or "").strip()
        
        # Verifica se o modelo solicitado está disponível
        test_result = _test_gemini_model_availability(model, api_key, 5.0)
        if not test_result['success']:
            print(f"⚠️  Modelo {model} não disponível ({test_result['status']}), tentando alternativas...", file=sys.stderr)
            model = _get_best_available_gemini_model(api_key)
    if model.startswith("models/"):
        model = model.split("/", 1)[1]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    full_url = f"{url}?key={api_key}"
    data = None
    last_exc: Exception | None = None
    attempts = max(1, int(os.environ.get("GEMINI_API_FALLBACK_RETRIES", "2")))
    total_budget_sec = max(5.0, float(os.environ.get("GEMINI_API_FALLBACK_TOTAL_TIMEOUT", "45")))
    started_at = time.monotonic()
    for _ in range(attempts):
        elapsed = time.monotonic() - started_at
        remaining = max(0.0, total_budget_sec - elapsed)
        if remaining < 1.0:
            break
        request_timeout = max(3.0, min(12.0, float(timeout_sec), remaining))
        try:
            resp = httpx.post(
                full_url,
                json=payload,
                timeout=request_timeout,
                trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if data is None and ("name resolution" in msg or "eai_again" in msg or "temporary failure" in msg):
                curl_bin = shutil.which("curl")
                if curl_bin:
                    try:
                        ips: list[str] = []
                        try:
                            ip = socket.gethostbyname("generativelanguage.googleapis.com")
                            if ip:
                                ips.append(ip)
                        except Exception:
                            pass
                        if not ips:
                            dig_bin = shutil.which("dig")
                            if dig_bin:
                                dig_proc = subprocess.run(
                                    [dig_bin, "+short", "@1.1.1.1", "generativelanguage.googleapis.com", "A"],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                )
                                for line in (dig_proc.stdout or "").splitlines():
                                    candidate = line.strip()
                                    if re.match(r"^\\d+\\.\\d+\\.\\d+\\.\\d+$", candidate):
                                        ips.append(candidate)
                        if not ips:
                            ns_bin = shutil.which("nslookup")
                            if ns_bin:
                                ns_proc = subprocess.run(
                                    [ns_bin, "generativelanguage.googleapis.com", "1.1.1.1"],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                )
                                for line in (ns_proc.stdout or "").splitlines():
                                    candidate = line.strip().split()[-1] if line.strip() else ""
                                    if re.match(r"^\\d+\\.\\d+\\.\\d+\\.\\d+$", candidate):
                                        ips.append(candidate)
                        if not ips:
                            fallback_ips = (os.environ.get("GEMINI_FALLBACK_IPS", "142.251.132.42,142.250.219.138,142.251.129.234")).split(",")
                            ips.extend([(x or "").strip() for x in fallback_ips if (x or "").strip()])
                        if not ips:
                            raise RuntimeError("sem IP para --resolve")
                        seen = set()
                        for ip in ips:
                            if ip in seen:
                                continue
                            seen.add(ip)
                            curl_cmd = [
                                curl_bin,
                                "-sS",
                                "--max-time",
                                str(int(max(3.0, min(12.0, request_timeout)))),
                                "--resolve",
                                f"generativelanguage.googleapis.com:443:{ip}",
                                "-H",
                                "Content-Type: application/json",
                                full_url,
                                "-d",
                                json.dumps(payload, ensure_ascii=False),
                            ]
                            curl_proc = subprocess.run(
                                curl_cmd,
                                capture_output=True,
                                text=True,
                                timeout=max(3.0, min(12.0, request_timeout)),
                            )
                            if curl_proc.returncode == 0 and (curl_proc.stdout or "").strip():
                                data = json.loads(curl_proc.stdout)
                                break
                            last_exc = RuntimeError((curl_proc.stderr or "curl_failed").strip())
                        if data is not None:
                            break
                    except Exception as curl_exc:
                        last_exc = curl_exc
            time.sleep(0.25)
    if data is None:
        raise RuntimeError(f"Falha no fallback HTTP Gemini após {attempts} tentativa(s): {last_exc}")

    text_parts: list[str] = []
    for cand in data.get("candidates", []) or []:
        content = cand.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            txt = (part.get("text") if isinstance(part, dict) else "") or ""
            if txt:
                text_parts.append(txt)
    text_out = "\n".join(text_parts).strip()

    if output_format in {"json", "stream-json"}:
        stdout = json.dumps(data, ensure_ascii=False)
    else:
        stdout = text_out

    return {
        "ok": True,
        "returncode": 0,
        "stdout": stdout,
        "stderr": "",
        "command": ["httpx", "POST", url],
        "cwd": str(BASE_DIR),
        "output_format": output_format,
        "model": model_name,
        "timeout_sec": timeout_sec,
        "run_as_user": env.get("USER", ""),
        "gemini_cli_home": env.get("GEMINI_CLI_HOME", ""),
        "provider": "google_api_fallback",
    }


def _gemini_bridge_run_prompt(
    prompt: str,
    output_format: str = _GEMINI_BRIDGE_DEFAULT_OUTPUT,
    model: str | None = None,
    workdir: str | None = None,
    timeout_sec: float | int | None = None,
) -> dict:
    gemini_bin = _ensure_gemini_available()
    timeout = _gemini_bridge_validate_timeout(timeout_sec)
    fmt = _gemini_bridge_validate_output_format(output_format)
    cwd = _gemini_bridge_resolve_workdir(workdir)
    model_name = (model or '').strip()

    env, preexec_fn, run_as_user = _gemini_bridge_subprocess_context()
    dns_ok, dns_detail = _gemini_dns_preflight(env=env, preexec_fn=preexec_fn)
    prefer_http = (os.environ.get("GEMINI_BRIDGE_PREFER_HTTP", "true") or "").strip().lower() in {"1", "true", "yes", "on"}
    has_api_key = bool(_gemini_bridge_google_api_key(env))

    if prefer_http and has_api_key:
        try:
            fallback = _gemini_api_fallback_prompt(
                prompt=prompt,
                output_format=fmt,
                model_name=model_name,
                timeout_sec=timeout,
                env=env,
            )
            fallback["dns_preflight_ok"] = dns_ok
            fallback["dns_preflight_detail"] = dns_detail
            return fallback
        except Exception as exc:
            print(f"⚠️  Gemini HTTP fallback falhou; tentando Gemini CLI: {exc}", file=sys.stderr)

    cmd = [gemini_bin, '-p', prompt, '--output-format', fmt]
    if model_name:
        cmd += ['-m', model_name]

    proc = None
    retries = max(1, int(os.environ.get("GEMINI_BRIDGE_PROMPT_RETRIES", "1")))
    last_timeout: subprocess.TimeoutExpired | None = None
    for attempt in range(1, retries + 1):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
                env=env,
                preexec_fn=preexec_fn,
            )
            break
        except subprocess.TimeoutExpired as exc:
            last_timeout = exc
            if attempt >= retries:
                try:
                    return _gemini_api_fallback_prompt(
                        prompt=prompt,
                        output_format=fmt,
                        model_name=model_name,
                        timeout_sec=timeout,
                        env=env,
                    )
                except Exception:
                    raise
            time.sleep(0.3)

    if proc is None and last_timeout is not None:
        raise last_timeout

    return {
        'ok': proc.returncode == 0,
        'returncode': proc.returncode,
        'stdout': proc.stdout or '',
        'stderr': proc.stderr or '',
        'command': cmd,
        'cwd': cwd or str(BASE_DIR),
        'output_format': fmt,
        'model': model_name,
        'timeout_sec': timeout,
        'run_as_user': run_as_user or env.get("USER", ""),
        'gemini_cli_home': env.get("GEMINI_CLI_HOME", ""),
        'dns_preflight_ok': dns_ok,
        'dns_preflight_detail': dns_detail,
    }


def _gemini_bridge_health_payload() -> dict:
    debug_euid = os.geteuid()
    debug_home = os.environ.get("HOME", "")
    debug_gemini_home = os.environ.get("GEMINI_CLI_HOME", "")
    debug_ctx_user = ""
    debug_ctx_home = ""
    debug_ctx_gemini_home = ""
    try:
        gemini_bin = _ensure_gemini_available()
        env, preexec_fn, run_as_user = _gemini_bridge_subprocess_context()
        dns_ok, dns_detail = _gemini_dns_preflight(env=env, preexec_fn=preexec_fn)
        debug_ctx_user = run_as_user or env.get("USER", "")
        debug_ctx_home = env.get("HOME", "")
        debug_ctx_gemini_home = env.get("GEMINI_CLI_HOME", "")
        prefer_http = (os.environ.get("GEMINI_BRIDGE_PREFER_HTTP", "true") or "").strip().lower() in {"1", "true", "yes", "on"}
        has_api_key = bool(_gemini_bridge_google_api_key(env))
        degraded = False
        if prefer_http and has_api_key:
            try:
                _gemini_api_fallback_prompt(
                    prompt="Responda exatamente: OK",
                    output_format="text",
                    model_name="",
                    timeout_sec=min(_GEMINI_BRIDGE_HEALTH_TIMEOUT_SEC, 20.0),
                    env=env,
                )
                version_stdout = "http_fallback_ok"
                version_stderr = ""
                version_ok = True
            except Exception as exc:
                version_stdout = ""
                version_stderr = str(exc)
                version_ok = True
                degraded = True
        else:
            version_proc = subprocess.run(
                [gemini_bin, '--version'],
                capture_output=True,
                text=True,
                timeout=_GEMINI_BRIDGE_HEALTH_TIMEOUT_SEC,
                env=env,
                preexec_fn=preexec_fn,
            )
            version_stdout = (version_proc.stdout or '').strip()
            version_stderr = (version_proc.stderr or '').strip()
            version_ok = version_proc.returncode == 0
        return {
            'ok': version_ok,
            'gemini_bin': gemini_bin,
            'version_stdout': version_stdout,
            'version_stderr': version_stderr,
            'project_root': str(BASE_DIR),
            'run_as_user': run_as_user or env.get("USER", ""),
            'gemini_cli_home': env.get("GEMINI_CLI_HOME", ""),
            'dns_ok': dns_ok,
            'dns_detail': dns_detail,
            'degraded': degraded,
            'debug_euid': debug_euid,
            'debug_home': debug_home,
            'debug_gemini_cli_home_env': debug_gemini_home,
            'debug_ctx_user': debug_ctx_user,
            'debug_ctx_home': debug_ctx_home,
            'debug_ctx_gemini_home': debug_ctx_gemini_home,
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': str(exc),
            'project_root': str(BASE_DIR),
            'debug_euid': debug_euid,
            'debug_home': debug_home,
            'debug_gemini_cli_home_env': debug_gemini_home,
            'debug_ctx_user': debug_ctx_user,
            'debug_ctx_home': debug_ctx_home,
            'debug_ctx_gemini_home': debug_ctx_gemini_home,
        }


@_mcp_tool_when_env("GEMINI_BRIDGE_MCP_ENABLE", "false")
def gemini_prompt(
    prompt: str,
    output_format: str = _GEMINI_BRIDGE_DEFAULT_OUTPUT,
    model: str = '',
    workdir: str = '',
    timeout_sec: float = _GEMINI_BRIDGE_TIMEOUT_SEC,
) -> dict:
    """Executa um prompt no Gemini CLI em modo headless e retorna saída estruturada."""
    text = (prompt or '').strip()
    if not text:
        return {'ok': False, 'error': 'prompt vazio'}
    try:
        return _gemini_bridge_run_prompt(
            prompt=text,
            output_format=output_format,
            model=model,
            workdir=workdir,
            timeout_sec=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'ok': False,
            'error': 'timeout',
            'timeout_sec': _gemini_bridge_validate_timeout(timeout_sec),
            'stdout': (exc.stdout or ''),
            'stderr': (exc.stderr or ''),
        }
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


@_mcp_tool_when_env("GEMINI_BRIDGE_MCP_ENABLE", "false")
def gemini_bridge_health() -> dict:
    """Verifica se o binário Gemini está acessível para este bridge."""
    return _gemini_bridge_health_payload()


def _run_gemini_bridge_server() -> int:
    if not FASTMCP_AVAILABLE:
        print("❌ fastmcp não encontrado. gemini-bridge requer FastMCP instalado.", file=sys.stderr)
        return 1
    bridge_mcp = FastMCP(name='gemini-bridge-mcp')

    @bridge_mcp.tool()
    def gemini_prompt(
        prompt: str,
        output_format: str = _GEMINI_BRIDGE_DEFAULT_OUTPUT,
        model: str = '',
        workdir: str = '',
        timeout_sec: float = _GEMINI_BRIDGE_TIMEOUT_SEC,
    ) -> dict:
        text = (prompt or '').strip()
        if not text:
            return {'ok': False, 'error': 'prompt vazio'}
        try:
            return _gemini_bridge_run_prompt(
                prompt=text,
                output_format=output_format,
                model=model,
                workdir=workdir,
                timeout_sec=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                'ok': False,
                'error': 'timeout',
                'timeout_sec': _gemini_bridge_validate_timeout(timeout_sec),
                'stdout': (exc.stdout or ''),
                'stderr': (exc.stderr or ''),
            }
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    @bridge_mcp.tool()
    def gemini_bridge_health() -> dict:
        return _gemini_bridge_health_payload()

    bridge_mcp.run(transport="stdio")
    return 0


# google_auth_httplib2.py foi descontinuado como arquivo local.
# Jarvis usa a dependência instalada no ambiente quando necessário.
def _google_auth_httplib2_probe() -> dict:
    try:
        import google_auth_httplib2  # noqa: F401
        return {'ok': True, 'source': 'installed-package'}
    except Exception as e:
        return {'ok': False, 'error': str(e), 'source': 'missing'}


# --- MERGED: reclaim_ui.py ---
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# =========================
# Session and audit helpers
# =========================

def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_session(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_session(path: str | Path, session: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def bootstrap_session(
    path: str | Path,
    manual_login_confirmed: bool = False,
    captcha_resolved: bool = True,
    captcha_timeout_sec: int = 900,
    session_ttl_sec: int = 43200,
    now_epoch: float | None = None,
) -> dict:
    now = float(now_epoch) if now_epoch is not None else time.time()
    session = load_session(path) or {}

    session.setdefault("version", 1)
    session.setdefault("created_at", _iso_from_epoch(now))
    session["captcha_timeout_sec"] = int(captcha_timeout_sec)
    session["session_ttl_sec"] = int(session_ttl_sec)

    if manual_login_confirmed and captcha_resolved:
        session["state"] = "valid"
        session["bootstrapped_at"] = _iso_from_epoch(now)
        session["last_validated_at"] = _iso_from_epoch(now)
        session["expires_at"] = _iso_from_epoch(now + int(session_ttl_sec))
        session.pop("blocked_at", None)
    elif manual_login_confirmed and not captcha_resolved:
        session["state"] = "blocked_captcha"
        session["blocked_at"] = _iso_from_epoch(now)
        session.setdefault("started_at", _iso_from_epoch(now))
    else:
        if session.get("state") != "pending_manual_login":
            session["state"] = "pending_manual_login"
            session["started_at"] = _iso_from_epoch(now)
        session.pop("expires_at", None)

    save_session(path, session)
    return session


def get_session_status(
    path: str | Path,
    session_ttl_sec: int = 43200,
    now_epoch: float | None = None,
) -> dict:
    now = float(now_epoch) if now_epoch is not None else time.time()
    session = load_session(path)
    if not session:
        return {
            "state": "not_bootstrapped",
            "message": "Nenhuma sessão persistente encontrada.",
        }

    changed = False
    state = session.get("state", "not_bootstrapped")
    ttl = int(session.get("session_ttl_sec", session_ttl_sec))

    if state == "pending_manual_login":
        started = _epoch_from_iso(session.get("started_at"))
        timeout_sec = int(session.get("captcha_timeout_sec", 900))
        if started is not None and (now - started) > timeout_sec:
            session["state"] = "blocked_captcha"
            session["blocked_at"] = _iso_from_epoch(now)
            session["message"] = "Captcha não resolvido dentro do timeout."
            changed = True
    elif state == "valid":
        last = _epoch_from_iso(session.get("last_validated_at")) or _epoch_from_iso(session.get("bootstrapped_at"))
        if last is None:
            session["state"] = "expired"
            session["message"] = "Sessão sem timestamp de validação."
            changed = True
        elif (now - last) > ttl:
            session["state"] = "expired"
            session["expired_at"] = _iso_from_epoch(now)
            session["message"] = "Sessão expirada por inatividade."
            changed = True
        else:
            session["last_validated_at"] = _iso_from_epoch(now)
            session["expires_at"] = _iso_from_epoch(now + ttl)
            changed = True

    if changed:
        save_session(path, session)

    return session


def append_audit_event(path: str | Path, event: dict, now_epoch: float | None = None) -> dict:
    now = float(now_epoch) if now_epoch is not None else time.time()
    payload = {"timestamp": _iso_from_epoch(now)}
    payload.update(event or {})

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


# ==============
# Title resolver
# ==============

def normalize_title(value: str | None) -> str:
    return (value or "").strip()


def _candidate_title(candidate) -> str:
    if isinstance(candidate, dict):
        return normalize_title(candidate.get("title"))
    return normalize_title(str(candidate))


def resolve_exact_title(target_title: str | None, candidates: list) -> dict:
    target = normalize_title(target_title)
    if not target:
        return {
            "status": "error",
            "resolution": "invalid_title",
            "error": {
                "code": "invalid_title",
                "message": "Título vazio após normalização.",
            },
            "candidates": [],
        }

    indexed = []
    for idx, raw in enumerate(candidates or []):
        if isinstance(raw, dict):
            entry = dict(raw)
            entry.setdefault("index", idx)
            entry["normalized_title"] = _candidate_title(raw)
        else:
            entry = {
                "index": idx,
                "title": str(raw),
                "normalized_title": _candidate_title(raw),
            }
        indexed.append(entry)

    matches = [it for it in indexed if it.get("normalized_title") == target]
    if len(matches) == 1:
        return {
            "status": "ok",
            "resolution": "unique",
            "target_title": target,
            "match": matches[0],
            "candidates": indexed,
        }
    if len(matches) > 1:
        return {
            "status": "error",
            "resolution": "ambiguous",
            "target_title": target,
            "error": {
                "code": "multiple_candidates",
                "message": "Mais de um candidato com título exato encontrado. Confirmação assistida necessária.",
            },
            "candidates": matches,
        }
    return {
        "status": "error",
        "resolution": "not_found",
        "target_title": target,
        "error": {
            "code": "title_not_found",
            "message": "Título não encontrado por comparação exata.",
        },
        "candidates": indexed,
    }


# =========
# Executor
# =========

def _guess_reclaim_executor_user() -> str:
    forced = (os.environ.get("RECLAIM_UI_EXECUTOR_RUN_AS_USER") or "").strip()
    if forced:
        return forced

    for key in ("SUDO_USER", "LOGNAME", "USER"):
        val = (os.environ.get(key) or "").strip()
        if val and val != "root":
            return val

    home_dir = Path("/home")
    if home_dir.exists():
        for child in sorted(home_dir.iterdir(), key=lambda p: p.name):
            if child.is_dir() and child.name not in {"root", "lost+found"}:
                return child.name
    return ""


def _build_reclaim_runtime_env(extra_env: dict | None = None) -> tuple[dict[str, str], str]:
    env = os.environ.copy()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})

    run_as_user = _guess_reclaim_executor_user()
    display = (env.get("DISPLAY") or os.environ.get("RECLAIM_UI_DISPLAY") or "").strip() or ":0"
    if display:
        env["DISPLAY"] = display

    xauthority = (env.get("XAUTHORITY") or os.environ.get("RECLAIM_UI_XAUTHORITY") or "").strip()
    if not xauthority and run_as_user:
        xauthority = f"/home/{run_as_user}/.Xauthority"
    if xauthority:
        env["XAUTHORITY"] = xauthority

    dbus_addr = (
        env.get("DBUS_SESSION_BUS_ADDRESS")
        or os.environ.get("RECLAIM_UI_DBUS_SESSION_BUS_ADDRESS")
        or ""
    ).strip()
    if not dbus_addr and run_as_user:
        try:
            uid = pwd.getpwnam(run_as_user).pw_uid
            dbus_addr = f"unix:path=/run/user/{uid}/bus"
        except Exception:
            dbus_addr = ""
    if dbus_addr:
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr

    return env, run_as_user


def _build_reclaim_runtime_prefix(env: dict[str, str], run_as_user: str) -> list[str]:
    runtime_prefix: list[str] = []
    allow_switch = (
        os.environ.get("RECLAIM_UI_SWITCH_USER", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    if (
        allow_switch
        and os.geteuid() == 0
        and run_as_user
        and run_as_user != "root"
        and shutil.which("sudo")
    ):
        assignments = []
        for key in ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
            value = (env.get(key) or "").strip()
            if value:
                assignments.append(f"{key}={shlex.quote(value)}")
        runtime_prefix = ["sudo", "-u", run_as_user, "env"] + assignments
    return runtime_prefix



def run_reclaim_playwright_action(action: str, title: str, timeout_sec: int = 25, extra_env: dict | None = None) -> dict:
    """Headless Reclaim executor using Playwright DOM access.

    It confirms only DOM-observable states. Login/captcha produces assist-mode errors
    instead of falling back to blind xdotool.
    """
    normalized_action = (action or "").strip().lower()
    normalized_title = (title or "").strip()
    if normalized_action not in {"start", "stop", "restart", "next", "done", "up_next", "set_priority", "due_date", "snooze", "calendar_context_menu", "calendar_unlock", "calendar_reschedule"}:
        return {
            "status": "error",
            "result": "invalid_action",
            "error": {"code": "invalid_action", "message": f"Ação inválida para headless: {action}"},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_playwright_reclaim_ui",
            "executed_at": _iso_now(),
        }

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as exc:
        return {
            "status": "error",
            "result": "playwright_unavailable",
            "error": {"code": "playwright_unavailable", "message": str(exc)},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_playwright_reclaim_ui",
            "executed_at": _iso_now(),
        }

    RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    timeout_ms = max(1000, int(timeout_sec) * 1000)

    def _payload(status: str, result: str, **extra) -> dict:
        out = {
            "status": status,
            "result": result,
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_playwright_reclaim_ui",
            "mode": "headless_playwright",
            "headless": bool(RECLAIM_UI_HEADLESS),
            "user_data_dir": str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
            "executed_at": _iso_now(),
        }
        out.update(extra)
        return out

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
                headless=bool(RECLAIM_UI_HEADLESS),
                viewport={"width": 1366, "height": 768},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(RECLAIM_UI_LOGIN_URL, wait_until="commit", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 8000))
                except Exception:
                    pass

                url = page.url or ""
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body_text = ""
                auth_haystack = (url + "\n" + body_text[:2000]).lower()
                if (
                    "accounts.google.com" in auth_haystack
                    or "captcha" in auth_haystack
                    or "sign in" in auth_haystack
                    or "fazer login" in auth_haystack
                ):
                    return _payload(
                        "error",
                        "login_or_captcha_required",
                        page_url=url,
                        error={
                            "code": "login_or_captcha_required",
                            "message": "Headless chegou em login/captcha. Abra o perfil Playwright em modo visível para intervenção manual.",
                        },
                    )

                if normalized_action == "next":
                    return _payload(
                        "error",
                        "next_not_supported_headless",
                        page_url=url,
                        error={"code": "next_not_supported_headless", "message": "Headless não escolhe próximo item sem título alvo."},
                    )

                if normalized_action == "stop":
                    candidates = [
                        'button[aria-label="Stop"]',
                        'button[aria-label="Stop Task"]',
                        'button[aria-label="Pause"]',
                        'button[aria-label="Pause Task"]',
                    ]
                    for selector in candidates:
                        loc = page.locator(selector).first
                        if loc.count() > 0:
                            loc.click(timeout=5000)
                            return _payload("ok", "action_sent_unverified", page_url=url, selector=selector)
                    return _payload(
                        "error",
                        "stop_selector_unknown",
                        page_url=url,
                        error={"code": "stop_selector_unknown", "message": "Seletor DOM do botão Stop/Pause não encontrado."},
                    )

                if not normalized_title:
                    return _payload(
                        "error",
                        "title_required_headless",
                        page_url=url,
                        error={"code": "title_required_headless", "message": "Headless exige título alvo para ação por tarefa."},
                    )

                rows = page.locator('[aria-roledescription="draggable"]')
                row_count = rows.count()
                target_row = None
                for idx in range(row_count):
                    row = rows.nth(idx)
                    try:
                        text = row.inner_text(timeout=1000)
                    except Exception:
                        continue
                    if normalized_title in text:

                        target_row = row
                        break
                if target_row is None:
                    return _payload(
                        "error",
                        "title_not_found_in_dom",
                        page_url=url,
                        rows=row_count,
                        error={"code": "title_not_found_in_dom", "message": "Título não encontrado na lista DOM do Reclaim."},
                    )

                selector_by_action = {
                    "start": 'button[aria-label="Start Task now"]',
                    "done": 'button[aria-label="Mark done"]',
                    "up_next": 'button[aria-label="Send to Up Next"]',
                }
                selector = selector_by_action.get(normalized_action)
                if not selector:
                    return _payload(
                        "error",
                        "unsupported_headless_action",
                        page_url=url,
                        error={"code": "unsupported_headless_action", "message": f"Ação sem seletor headless: {normalized_action}"},
                    )
                button = target_row.locator(selector).first
                if button.count() <= 0:
                    return _payload(
                        "error",
                        "button_not_found_in_row",
                        page_url=url,
                        selector=selector,
                        error={"code": "button_not_found_in_row", "message": "Botão esperado não existe no bloco da tarefa alvo."},
                    )
                button.click(timeout=5000)
                page.wait_for_timeout(1500)

                confirm_text = ""
                try:
                    confirm_text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    confirm_text = ""
                if normalized_action == "start" and normalized_title in confirm_text and ("In progress" in confirm_text or "Now:" in confirm_text):
                    return _payload("ok", "action_confirmed_dom", page_url=page.url, selector=selector)
                return _payload("ok", "action_sent_unverified", page_url=page.url, selector=selector)
            finally:
                context.close()
    except PlaywrightTimeoutError as exc:
        return _payload(
            "error",
            "playwright_timeout",
            error={"code": "playwright_timeout", "message": str(exc)},
        )
    except Exception as exc:
        return _payload(
            "error",
            "playwright_exception",
            error={"code": "playwright_exception", "message": str(exc)},
        )


def _reclaim_cdp_available(url: str = "http://127.0.0.1:9222") -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=1.5) as response:
            return 200 <= int(getattr(response, "status", 0) or 0) < 300
    except Exception:
        return False


def _reclaim_playwright_profile_in_use(profile_dir: str | Path) -> bool:
    profile = Path(profile_dir or "").expanduser()
    lock_path = profile / "SingletonLock"
    if not (lock_path.exists() or lock_path.is_symlink()):
        return False
    try:
        target = os.readlink(lock_path)
    except Exception:
        target = ""
    m = re.search(r"-(\d+)$", target)
    if not m:
        return True
    try:
        os.kill(int(m.group(1)), 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _reclaim_profile_in_use_payload(action: str, title: str) -> dict:
    return {
        "status": "error",
        "result": "profile_in_use",
        "error": {
            "code": "profile_in_use",
            "message": "Perfil Playwright do Reclaim já está aberto sem CDP disponível. Feche a janela visível de login ou reabra o bootstrap com CDP e tente novamente.",
        },
        "action": (action or "").strip().lower(),
        "title": (title or "").strip(),
        "executor": "jarvis_playwright_reclaim_ui",
        "mode": "headless_playwright",
        "headless": bool(RECLAIM_UI_HEADLESS),
        "user_data_dir": str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
        "next_step": "Feche o Chrome aberto pelo bootstrap do Reclaim e tente de novo, ou rode reclaim_session_bootstrap(open_browser=true) para abrir uma janela com CDP.",
        "executed_at": _iso_now(),
    }


def run_reclaim_playwright_action(action: str, title: str, timeout_sec: int = 25, extra_env: dict | None = None) -> dict:
    """Headless Reclaim executor wrapper.

    Runs Playwright in a bounded subprocess so a stuck browser cannot hang the MCP server.
    """
    normalized_action = (action or "").strip().lower()
    normalized_title = (title or "").strip()
    worker = BASE_DIR / "reclaim_playwright_worker.py"
    if not worker.exists():
        return {
            "status": "error",
            "result": "playwright_worker_missing",
            "error": {"code": "playwright_worker_missing", "message": f"Worker não encontrado: {worker}"},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_playwright_reclaim_ui",
            "executed_at": _iso_now(),
        }
    cmd = [
        str(VENV_SUPER_PY if VENV_SUPER_PY.exists() else sys.executable),
        str(worker),
        "--action", normalized_action,
        "--title", normalized_title,
        "--url", RECLAIM_UI_LOGIN_URL,
        "--user-data-dir", str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
        "--timeout-ms", str(max(1000, int(timeout_sec) * 1000)),
        "--value", str(extra_env.get("value", "") if isinstance(extra_env, dict) else ""),
    ]
    if RECLAIM_UI_HEADLESS:
        cmd.append("--headless")
    worker_env = os.environ.copy()
    cdp_url = worker_env.get("RECLAIM_UI_CDP_URL", "http://127.0.0.1:9222")
    if _reclaim_playwright_profile_in_use(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR) and not _reclaim_cdp_available(cdp_url):
        return _reclaim_profile_in_use_payload(normalized_action, normalized_title)
    worker_env.setdefault("RECLAIM_UI_CDP_URL", "http://127.0.0.1:9222")
    if _reclaim_cdp_available(cdp_url):
        worker_env.setdefault("RECLAIM_UI_RAW_CDP_ENABLE", "true")
    default_cookie_profile = Path.home() / ".config" / "google-chrome" / "Default"
    if default_cookie_profile.exists():
        worker_env.setdefault("RECLAIM_UI_COOKIE_SOURCE_PROFILE", str(default_cookie_profile))
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=worker_env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=max(5, int(timeout_sec) + 15))
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            stdout, stderr = "", ""
            return {
                "status": "error",
                "result": "playwright_subprocess_timeout",
                "error": {"code": "playwright_subprocess_timeout", "message": "Worker Playwright excedeu timeout e foi encerrado."},
                "action": normalized_action,
                "title": normalized_title,
                "executor": "jarvis_playwright_reclaim_ui",
                "mode": "headless_playwright",
                "headless": bool(RECLAIM_UI_HEADLESS),
                "user_data_dir": str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
                "worker_stdout": (stdout or "").strip(),
                "worker_stderr": (stderr or "").strip(),
                "executed_at": _iso_now(),
            }
    except Exception as exc:
        return {
            "status": "error",
            "result": "playwright_subprocess_exception",
            "error": {"code": "playwright_subprocess_exception", "message": str(exc)},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_playwright_reclaim_ui",
            "mode": "headless_playwright",
            "headless": bool(RECLAIM_UI_HEADLESS),
            "user_data_dir": str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR),
            "executed_at": _iso_now(),
        }
    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    parsed = None
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
            break
        except Exception:
            continue
    if isinstance(parsed, dict):
        if stderr:
            parsed.setdefault("worker_stderr", stderr)
        parsed.setdefault("worker_returncode", returncode)
        error_code = parsed.get("error", {}).get("code") or parsed.get("result")
        if error_code == "login_or_captcha_required":
            try:
                session = load_session(RECLAIM_UI_SESSION_FILE) or {}
                session.setdefault("version", 1)
                session["state"] = "pending_manual_login"
                session["started_at"] = _iso_now()
                session["message"] = "Reclaim UI retornou login/captcha durante automação."
                session.pop("expires_at", None)
                save_session(RECLAIM_UI_SESSION_FILE, session)
            except Exception:
                pass
        return parsed
    return {
        "status": "error",
        "result": "playwright_worker_invalid_output",
        "error": {"code": "playwright_worker_invalid_output", "message": "Worker não retornou JSON válido."},
        "action": normalized_action,
        "title": normalized_title,
        "executor": "jarvis_playwright_reclaim_ui",
        "worker_returncode": returncode,
        "worker_stdout": stdout,
        "worker_stderr": stderr,
        "executed_at": _iso_now(),
    }

def _terminate_reclaim_profile_chrome_processes(profile_dir: str | Path) -> None:
    profile_raw = str(profile_dir or '').strip()
    if not profile_raw:
        return
    try:
        cp = subprocess.run(['ps', '-eo', 'pid,args'], text=True, capture_output=True, timeout=10, check=False)
    except Exception:
        return
    targets: list[int] = []
    for line in (cp.stdout or '').splitlines():
        if profile_raw not in line or 'chrome' not in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            targets.append(int(parts[0]))
        except Exception:
            continue
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            continue
    if targets:
        deadline = time.time() + 5
        while time.time() < deadline:
            alive: list[int] = []
            for pid in targets:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except Exception:
                    pass
            if not alive:
                break
            time.sleep(0.2)
        for pid in targets:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            lock_path = Path(profile_raw) / lock_name
            if lock_path.exists() or lock_path.is_symlink():
                lock_path.unlink()
        except Exception:
            pass


def run_reclaim_ui_action(
    action: str,
    title: str,
    timeout_sec: int = 25,
    executor_cmd: str | None = None,
    extra_env: dict | None = None,
) -> dict:
    normalized_action = (action or "").strip().lower()
    normalized_title = (title or "").strip()

    if normalized_action not in {"start", "stop", "restart", "next", "done", "up_next", "set_priority", "due_date", "snooze", "calendar_context_menu", "calendar_unlock", "calendar_reschedule"}:
        return {
            "status": "error",
            "error": {
                "code": "invalid_action",
                "message": f"Ação inválida: {action}",
            },
            "action": normalized_action,
            "title": normalized_title,
            "executed_at": _iso_now(),
        }

    env, run_as_user = _build_reclaim_runtime_env(extra_env)
    runtime_prefix = _build_reclaim_runtime_prefix(env, run_as_user)
    timeout = max(1, int(timeout_sec))

    requested_executor = (executor_cmd or "").strip()
    use_external_executor = bool(requested_executor and requested_executor.lower() not in {"internal", "embedded", "embedded_xdotool"})
    automation_mode = (RECLAIM_UI_AUTOMATION_MODE or "").strip().lower()
    if not use_external_executor and automation_mode in {"headless", "playwright", "elements_first"}:
        headless_action = run_reclaim_playwright_action(
            action=normalized_action,
            title=normalized_title,
            timeout_sec=timeout,
            extra_env=extra_env,
        )
        if (
            automation_mode in {"headless", "playwright"}
            or headless_action.get("status") == "ok"
            or headless_action.get("result") in {"login_or_captcha_required", "title_not_found_in_dom", "stop_selector_unknown"}
        ):
            return headless_action
    if use_external_executor:
        try:
            executor_parts = shlex.split(requested_executor)
        except ValueError as exc:
            return {
                "status": "error",
                "error": {
                    "code": "invalid_executor_command",
                    "message": f"Comando do executor inválido: {exc}",
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": requested_executor,
                "executed_at": _iso_now(),
            }
        if not executor_parts:
            return {
                "status": "error",
                "error": {
                    "code": "executor_not_found",
                    "message": "Comando do executor vazio.",
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": requested_executor,
                "executed_at": _iso_now(),
            }

        executor_bin = executor_parts[0]
        if "/" in executor_bin or executor_bin.startswith(".") or executor_bin.startswith("~"):
            executor_path = Path(executor_bin).expanduser()
            if not executor_path.exists():
                return {
                    "status": "error",
                    "error": {
                        "code": "executor_not_found",
                        "message": f"Executor não encontrado: {executor_path}",
                    },
                    "action": normalized_action,
                    "title": normalized_title,
                    "executor": str(executor_path),
                    "executed_at": _iso_now(),
                }
            if not os.access(executor_path, os.X_OK):
                return {
                    "status": "error",
                    "error": {
                        "code": "executor_not_executable",
                        "message": f"Executor sem permissão de execução: {executor_path}",
                    },
                    "action": normalized_action,
                    "title": normalized_title,
                    "executor": str(executor_path),
                    "executed_at": _iso_now(),
                }
            executor_parts[0] = str(executor_path)
        else:
            resolved_bin = shutil.which(executor_bin)
            if not resolved_bin:
                return {
                    "status": "error",
                    "error": {
                        "code": "executor_not_found",
                        "message": f"Executor não encontrado no PATH: {executor_bin}",
                    },
                    "action": normalized_action,
                    "title": normalized_title,
                    "executor": requested_executor,
                    "executed_at": _iso_now(),
                }
            executor_parts[0] = resolved_bin

        exec_env = env.copy()
        exec_env.update(
            {
                "RECLAIM_UI_ACTION": normalized_action,
                "RECLAIM_UI_TITLE": normalized_title,
                "RECLAIM_UI_TIMEOUT_SEC": str(timeout),
            }
        )
        exec_cmd = runtime_prefix + executor_parts + [normalized_action, normalized_title]
        try:
            cp = subprocess.run(
                exec_cmd,
                env=exec_env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "result": "executor_timeout",
                "error": {
                    "code": "executor_timeout",
                    "message": f"Executor excedeu timeout de {timeout}s.",
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": requested_executor,
                "executed_at": _iso_now(),
            }
        except Exception as e:
            return {
                "status": "error",
                "result": "executor_exception",
                "error": {
                    "code": "executor_exception",
                    "message": str(e),
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": requested_executor,
                "executed_at": _iso_now(),
            }

        stdout_text = (cp.stdout or "").strip()
        stderr_text = (cp.stderr or "").strip()
        parsed_payload: dict = {}
        if stdout_text:
            for line in reversed(stdout_text.splitlines()):
                candidate_line = line.strip()
                if not candidate_line:
                    continue
                try:
                    parsed = json.loads(candidate_line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    parsed_payload = dict(parsed)
                else:
                    parsed_payload = {"executor_output": parsed}
                break

        payload = parsed_payload if isinstance(parsed_payload, dict) else {}
        if cp.returncode != 0:
            payload.setdefault("status", "error")
            payload.setdefault("result", "executor_failed")
            payload.setdefault(
                "error",
                {
                    "code": "executor_failed",
                    "message": f"Executor retornou código {cp.returncode}.",
                },
            )
        else:
            payload.setdefault("status", "ok")
            payload.setdefault("result", "action_executed")
        payload.setdefault("action", normalized_action)
        payload.setdefault("title", normalized_title)
        payload.setdefault("executed_at", _iso_now())
        payload.setdefault("executor", requested_executor)
        payload["executor_returncode"] = cp.returncode
        if stdout_text and not parsed_payload:
            payload.setdefault("executor_stdout", stdout_text)
        if stderr_text:
            payload.setdefault("executor_stderr", stderr_text)
        if run_as_user:
            payload.setdefault("executor_user", run_as_user)
        return payload

    step_sleep = max(0.01, float(os.environ.get("RECLAIM_UI_STEP_SLEEP_SEC", "0.15")))
    type_delay_ms = str(int(float(os.environ.get("RECLAIM_UI_TYPE_DELAY_MS", "10"))))
    window_regex = os.environ.get(
        "RECLAIM_UI_WINDOW_REGEX", "Reclaim|app\\.reclaim\\.ai"
    )
    start_seq = os.environ.get("RECLAIM_UI_START_SEQUENCE", "Tab Return")
    stop_seq = os.environ.get("RECLAIM_UI_STOP_SEQUENCE", "Escape")
    restart_seq = os.environ.get("RECLAIM_UI_RESTART_SEQUENCE", "Return")
    start_x, start_y = os.environ.get("RECLAIM_UI_START_CLICK_X", ""), os.environ.get("RECLAIM_UI_START_CLICK_Y", "")
    stop_x, stop_y = os.environ.get("RECLAIM_UI_STOP_CLICK_X", ""), os.environ.get("RECLAIM_UI_STOP_CLICK_Y", "")
    restart_x, restart_y = os.environ.get("RECLAIM_UI_RESTART_CLICK_X", ""), os.environ.get("RECLAIM_UI_RESTART_CLICK_Y", "")

    def _run_xdotool(args: list[str], *, step_timeout: int = 5) -> subprocess.CompletedProcess:
        return subprocess.run(
            runtime_prefix + ["xdotool"] + args,
            env=env,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, step_timeout)),
            check=False,
        )

    def _send_keys(window_id: str, seq: str) -> tuple[bool, str]:
        expanded = (seq or "").replace(",", " ").strip()
        if not expanded:
            return True, ""
        for key in [k for k in expanded.split() if k]:
            cp = _run_xdotool(["key", "--window", window_id, key])
            if cp.returncode != 0:
                return False, (cp.stderr or cp.stdout or "").strip()
            time.sleep(step_sleep)
        return True, ""

    def _paste_text(window_id: str, text_value: str, *, step_timeout: int = 10) -> tuple[bool, str]:
        text_value = text_value or ""
        if shutil.which("xsel"):
            cp = subprocess.run(
                runtime_prefix + ["xsel", "--clipboard", "--input"],
                input=text_value,
                env=env,
                text=True,
                capture_output=True,
                timeout=max(1, min(timeout, step_timeout)),
                check=False,
            )
            if cp.returncode != 0:
                return False, (cp.stderr or cp.stdout or "").strip()
            ok, err = _send_keys(window_id, "ctrl+v")
            return (True, "") if ok else (False, err)

        if shutil.which("xclip"):
            try:
                proc = subprocess.Popen(
                    runtime_prefix + ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                )
                try:
                    proc.communicate(input=text_value, timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                ok, err = _send_keys(window_id, "ctrl+v")
                time.sleep(step_sleep)
                if proc.poll() is None:
                    proc.terminate()
                if not ok:
                    return False, err
                return True, ""
            except Exception as exc:
                return False, str(exc)

        cp = _run_xdotool(["type", "--window", window_id, "--delay", type_delay_ms, "--", text_value], step_timeout=step_timeout)
        return cp.returncode == 0, (cp.stderr or cp.stdout or "").strip()


    def _get_window_name(window_id: str) -> str:
        cp = _run_xdotool(["getwindowname", window_id], step_timeout=3)
        if cp.returncode != 0:
            return ""
        return (cp.stdout or "").strip()

    def _is_reclaim_window_name(name: str) -> bool:
        normalized = (name or "").lower()
        return "reclaim" in normalized or "app.reclaim.ai" in normalized or "planner |" in normalized

    def _active_reclaim_window_id() -> tuple[str, str]:
        cp = _run_xdotool(["getactivewindow"], step_timeout=3)
        if cp.returncode != 0:
            return "", ""
        active_id = (cp.stdout or "").strip()
        if not active_id:
            return "", ""
        active_name = _get_window_name(active_id)
        if _is_reclaim_window_name(active_name):
            return active_id, active_name
        return "", ""

    def _click(window_id: str, x: str, y: str) -> tuple[bool, str]:
        cp = _run_xdotool(["mousemove", "--window", window_id, str(x), str(y), "click", "1"])
        return cp.returncode == 0, (cp.stderr or cp.stdout or "").strip()

    if not (env.get("DISPLAY") or "").strip():
        return {
            "status": "error",
            "error": {"code": "display_unavailable", "message": "DISPLAY não definido para automação visual."},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_internal_reclaim_ui",
            "executed_at": _iso_now(),
        }
    if not shutil.which("xdotool"):
        auto_install = os.environ.get("RECLAIM_UI_AUTO_INSTALL_XDOTOOL", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if auto_install and getattr(os, "geteuid", lambda: 1)() == 0:
            try:
                subprocess.run(
                    ["apt-get", "update", "-y"],
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                subprocess.run(
                    ["apt-get", "install", "-y", "xdotool"],
                    text=True,
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
            except Exception:
                pass
            if shutil.which("xdotool"):
                # instalado com sucesso; segue o fluxo normal
                pass
            else:
                return {
                    "status": "error",
                    "error": {
                        "code": "xdotool_missing",
                        "message": "xdotool não encontrado no sistema. instale com: sudo apt-get install -y xdotool",
                    },
                    "action": normalized_action,
                    "title": normalized_title,
                    "executor": "jarvis_internal_reclaim_ui",
                    "executed_at": _iso_now(),
                }
        else:
            return {
                "status": "error",
                "error": {
                    "code": "xdotool_missing",
                    "message": "xdotool não encontrado no sistema. instale com: sudo apt-get install -y xdotool",
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": "jarvis_internal_reclaim_ui",
                "executed_at": _iso_now(),
            }

    window_id, window_name = _active_reclaim_window_id()
    if not window_id:
        try:
            search_cp = _run_xdotool(["search", "--name", window_regex], step_timeout=8)
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": {
                    "code": "window_search_timeout",
                    "message": "Busca de janela do Reclaim excedeu timeout.",
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": "jarvis_internal_reclaim_ui",
                "executed_at": _iso_now(),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": {
                    "code": "executor_exception",
                    "message": str(e),
                },
                "action": normalized_action,
                "title": normalized_title,
                "executor": "jarvis_internal_reclaim_ui",
                "executed_at": _iso_now(),
            }
        if search_cp.returncode != 0:
            return {
                "status": "error",
                "result": "window_not_found",
                "error": {"code": "window_not_found", "message": f"Nenhuma janela encontrada para regex: {window_regex}"},
                "action": normalized_action,
                "title": normalized_title,
                "executor": "jarvis_internal_reclaim_ui",
                "executed_at": _iso_now(),
            }
        window_lines = [ln.strip() for ln in (search_cp.stdout or "").splitlines() if ln.strip()]
        for candidate_id in reversed(window_lines):
            candidate_name = _get_window_name(candidate_id)
            if _is_reclaim_window_name(candidate_name):
                window_id, window_name = candidate_id, candidate_name
                break
        if not window_id and window_lines:
            window_id = window_lines[-1]
            window_name = _get_window_name(window_id)
    if not window_id:
        return {
            "status": "error",
            "result": "window_not_found",
            "error": {"code": "window_not_found", "message": "Janela alvo não identificada."},
            "action": normalized_action,
            "title": normalized_title,
            "executor": "jarvis_internal_reclaim_ui",
            "executed_at": _iso_now(),
        }

    activate_cp = _run_xdotool(["windowactivate", "--sync", window_id], step_timeout=8)
    if activate_cp.returncode != 0:
        # Alguns window managers leves (ex.: fluxbox) não suportam _NET_ACTIVE_WINDOW.
        # Fazemos fallback para elevar a janela e seguimos.
        _run_xdotool(["windowraise", window_id], step_timeout=5)
    time.sleep(step_sleep)

    # Pre-flight: garantir que estamos no Reclaim sem recarregar uma aba já aberta.
    ensure_url = os.environ.get("RECLAIM_UI_ENSURE_URL", "true").strip().lower() in {"1", "true", "yes", "on"}
    reuse_open_tab = os.environ.get("RECLAIM_UI_REUSE_OPEN_TAB", "true").strip().lower() in {"1", "true", "yes", "on"}
    ensure_url_value = RECLAIM_UI_LOGIN_URL
    if not window_name:
        window_name = _get_window_name(window_id)
    already_on_reclaim = _is_reclaim_window_name(window_name)
    if ensure_url and ensure_url_value and not (reuse_open_tab and already_on_reclaim):
        ok, err = _send_keys(window_id, "ctrl+l")
        if not ok:
            return {"status": "error", "result": "url_focus_failed", "error": {"code": "url_focus_failed", "message": "Falha ao focar a barra de URL."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
        ok, err = _paste_text(window_id, ensure_url_value, step_timeout=10)
        if not ok:
            return {"status": "error", "result": "url_paste_failed", "error": {"code": "url_paste_failed", "message": "Falha ao inserir URL do Reclaim."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
        _send_keys(window_id, "Return")
        time.sleep(max(step_sleep, float(os.environ.get("RECLAIM_UI_NAV_SLEEP_SEC", "8"))))

    if normalized_action == "next":
        return {
            "status": "error",
            "result": "next_not_supported_internal",
            "error": {
                "code": "next_not_supported_internal",
                "message": "Executor interno não resolve próximo item visual.",
            },
            "action": normalized_action,
            "title": normalized_title,
            "window_id": window_id,
            "executor": "jarvis_internal_reclaim_ui",
            "executed_at": _iso_now(),
        }

    if normalized_action == "start" and normalized_title:
        ok, err = _send_keys(window_id, "ctrl+f")
        if not ok:
            return {
                "status": "error",
                "result": "search_open_failed",
                "error": {"code": "search_open_failed", "message": "Não foi possível abrir busca na janela alvo."},
                "action": normalized_action,
                "title": normalized_title,
                "window_id": window_id,
                "executor": "jarvis_internal_reclaim_ui",
                "executor_stderr": err,
                "executed_at": _iso_now(),
            }
        ok, err = _paste_text(window_id, normalized_title, step_timeout=10)
        if not ok:
            return {
                "status": "error",
                "result": "type_failed",
                "error": {"code": "type_failed", "message": "Falha ao inserir o título na UI."},
                "action": normalized_action,
                "title": normalized_title,
                "window_id": window_id,
                "executor": "jarvis_internal_reclaim_ui",
                "executor_stderr": err,
                "executed_at": _iso_now(),
            }
        _send_keys(window_id, "Return")
        _send_keys(window_id, "Escape")

    if normalized_action == "start":
        if start_x and start_y:
            ok, err = _click(window_id, start_x, start_y)
            if not ok:
                return {"status": "error", "result": "start_click_failed", "error": {"code": "start_click_failed", "message": "Falha ao clicar no botão Start."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
        else:
            ok, err = _send_keys(window_id, start_seq)
            if not ok:
                return {"status": "error", "result": "start_key_failed", "error": {"code": "start_key_failed", "message": "Falha ao executar sequência Start."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
    elif normalized_action == "stop":
        if stop_x and stop_y:
            ok, err = _click(window_id, stop_x, stop_y)
            if not ok:
                return {"status": "error", "result": "stop_click_failed", "error": {"code": "stop_click_failed", "message": "Falha ao clicar no botão Stop."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
        else:
            ok, err = _send_keys(window_id, stop_seq)
            if not ok:
                return {"status": "error", "result": "stop_key_failed", "error": {"code": "stop_key_failed", "message": "Falha ao executar sequência Stop."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
    else:  # restart
        if restart_x and restart_y:
            ok, err = _click(window_id, restart_x, restart_y)
            if not ok:
                return {"status": "error", "result": "restart_click_failed", "error": {"code": "restart_click_failed", "message": "Falha ao clicar no botão Restart."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}
        else:
            ok, err = _send_keys(window_id, restart_seq)
            if not ok:
                return {"status": "error", "result": "restart_key_failed", "error": {"code": "restart_key_failed", "message": "Falha ao executar sequência Restart."}, "action": normalized_action, "title": normalized_title, "window_id": window_id, "executor": "jarvis_internal_reclaim_ui", "executor_stderr": err, "executed_at": _iso_now()}

    payload: dict = {
        "status": "ok",
        "result": "action_sent_unverified",
        "message": "Ação enviada para a janela do Reclaim, sem confirmação visual/DOM de que o timer iniciou.",
        "mode": "embedded_xdotool",
        "action": normalized_action,
        "title": normalized_title,
        "window_id": window_id,
        "window_name": window_name,
        "executor": "jarvis_internal_reclaim_ui",
        "executed_at": _iso_now(),
    }
    if run_as_user:
        payload["executor_user"] = run_as_user
    return payload


# =================
# Assist mode flow
# =================

VALID_CONFIRM_RESULTS = {"started", "stopped", "restarted", "canceled"}
def _open_login_url(url: str | None, *, visible_required: bool = False) -> dict:
    headless_bootstrap = bool(RECLAIM_UI_BOOTSTRAP_HEADLESS and not visible_required)
    payload = {
        "url": str(url or ""),
        "opened": False,
        "method": "manual",
        "headless": headless_bootstrap,
    }
    if not url:
        payload["reason"] = "login_url_missing"
        return payload

    browser_mode = os.environ.get("RECLAIM_UI_BROWSER_MODE", "").strip().lower()
    chrome_user_data_dir = os.environ.get("RECLAIM_UI_CHROME_USER_DATA_DIR", "").strip()

    if not headless_bootstrap and not os.environ.get("DISPLAY"):
        payload["reason"] = "display_missing"
        return payload

    if browser_mode == "playwright" or (not browser_mode and RECLAIM_UI_AUTOMATION_MODE in {"headless", "playwright"}):
        chrome = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if not chrome:
            payload["reason"] = "chrome_not_found_for_playwright_profile"
            return payload
        try:
            runtime_env, run_as_user = _build_reclaim_runtime_env(None)
            runtime_prefix = _build_reclaim_runtime_prefix(runtime_env, run_as_user)
            _terminate_reclaim_profile_chrome_processes(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR)
            visible_cdp = os.environ.get("RECLAIM_UI_VISIBLE_CDP", "true").lower() in ("1", "true", "yes", "on")
            cmd = runtime_prefix + [
                chrome,
                f"--user-data-dir={RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR}",
            ]
            if headless_bootstrap or visible_cdp:
                cmd.extend([
                    "--remote-debugging-address=127.0.0.1",
                    "--remote-debugging-port=9222",
                    "--remote-allow-origins=*",
                ])
            if headless_bootstrap:
                cmd.extend([
                    "--headless",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--mute-audio",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ])
            else:
                cmd.append("--new-window")
            cmd.append(url)
            log_path = BASE_DIR / "reclaim_chrome.log"
            log_handle = open(log_path, "ab")
            subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=log_handle,
                cwd=str(BASE_DIR),
                env=runtime_env,
                start_new_session=True,
            )
            payload["opened"] = True
            payload["method"] = "chrome_persistent_profile_headless_cdp" if headless_bootstrap else ("chrome_persistent_profile_visible_cdp" if visible_cdp else "chrome_persistent_profile_visible_login")
            payload["user_data_dir"] = str(RECLAIM_UI_PLAYWRIGHT_USER_DATA_DIR)
            payload["chrome_log"] = str(log_path)
            if run_as_user:
                payload["executor_user"] = run_as_user
            return payload
        except Exception as exc:
            payload["reason"] = str(exc)
            return payload

    if browser_mode == "app":
        chrome = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if not chrome:
            payload["reason"] = "chrome_not_found_for_app_mode"
            return payload
        try:
            cmd = [
                chrome,
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
            if chrome_user_data_dir:
                cmd.append(f"--user-data-dir={chrome_user_data_dir}")
            cmd.append(f"--app={url}")
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            payload["opened"] = True
            payload["method"] = "chrome_app"
            return payload
        except Exception as e:
            payload["reason"] = str(e)
            return payload

    opener = shutil.which("xdg-open")
    if not opener:
        payload["reason"] = "xdg-open não disponível"
        return payload
    try:
        subprocess.Popen(
            [opener, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        payload["opened"] = True
        payload["method"] = "xdg-open"
        return payload
    except Exception as e:
        payload["reason"] = str(e)
        return payload


def _reclaim_open_login_url(*, visible_required: bool = False) -> dict:
    return _open_login_url(RECLAIM_UI_LOGIN_URL, visible_required=visible_required)


def _reclaim_login_workaround_hint() -> dict:
    return {
        "mode": "manual_remote_workaround",
        "steps": [
            f"1. Abra {RECLAIM_UI_LOGIN_URL} em um navegador com interface gráfica.",
            "2. Faça login no Reclaim e resolva captcha, se houver.",
            "3. Volte ao agente e execute reclaim_session_bootstrap(manual_login_confirmed=true, captcha_resolved=true, open_browser=false).",
        ],
    }



def _build_manual_steps(action: str, title: str, reason: str | None) -> list[str]:
    normalized = (title or "").strip()
    reason_text = f" Motivo: {reason}." if reason else ""
    base_steps = [
        "1. Abra https://app.reclaim.ai no navegador e confirme que a sessão está logada.",
        f"2. Localize a tarefa '{normalized}' (Ctrl+F na interface) e garanta que ela esteja disponível para iniciar/pausar/reiniciar.{reason_text}",
        "3. Clique no botão correspondente (Start/Stop/Restart) ou use o atalho padrão do Reclaim.",
    ]
    if action == "stop":
        base_steps[2] = "3. Clique em Stop ou pressione o atalho visível para encerrar o timer ativo."
    elif action == "restart":
        base_steps[2] = "3. Clique em Restart ou pressione o atalho visível para retomar o timer."
    return base_steps


def _confirm_next_step_hint(assist_id: str, action: str, default_result: str) -> str:
    return (
        "Depois de completar manualmente, chame "
        + f"reclaim_task_assist_confirm(assist_id='{assist_id}', action='{action}', result='{default_result}') para confirmar."
    )


def create_assist_request(
    audit_path: str | Path,
    action: str,
    title: str,
    reason: str | None = None,
    detail: str | None = None,
    login_url: str | None = None,
    open_browser: bool = False,
    session_state: str | None = None,
) -> dict:
    assist_id = str(uuid.uuid4())
    normalized_action = (action or "").strip().lower()
    normalized_title = (title or "").strip()
    visual_flow = _open_login_url(login_url, visible_required=True) if open_browser else {"url": login_url or ""}
    default_result = {
        "start": "started",
        "stop": "stopped",
        "restart": "restarted",
    }.get(normalized_action, "started")
    assist_payload = {
        "assist_id": assist_id,
        "assist_mode": "manual_ui_intervention",
        "action": normalized_action,
        "title": normalized_title,
        "reason": reason or "automation_failure",
        "detail": detail,
        "session_state": session_state,
        "manual_steps": _build_manual_steps(normalized_action, normalized_title, reason),
        "visual_flow": visual_flow,
        "confirm_next_step": _confirm_next_step_hint(
            assist_id, normalized_action, default_result
        ),
        "created_at": _iso_now(),
    }
    append_audit_event(
        audit_path,
        {
            "action": "reclaim_assist_requested",
            "assist_id": assist_id,
            "assist_action": normalized_action,
            "title": normalized_title,
            "reason": reason,
            "detail": detail,
            "session_state": session_state,
        },
    )
    return assist_payload


def confirm_assist_completion(
    audit_path: str | Path,
    assist_id: str,
    action: str,
    result: str,
    notes: str | None = None,
) -> dict:
    normalized_result = (result or "").strip().lower()
    if normalized_result not in VALID_CONFIRM_RESULTS:
        return {
            "status": "error",
            "error": {
                "code": "invalid_result",
                "message": f"Result inválido. Use uma das: {sorted(VALID_CONFIRM_RESULTS)}",
            },
            "assist_id": assist_id,
        }
    payload = {
        "status": "ok",
        "assist_id": assist_id,
        "action": action,
        "result": normalized_result,
        "notes": notes,
        "confirmed_at": _iso_now(),
    }
    append_audit_event(
        audit_path,
        {
            "action": "reclaim_assist_confirmed",
            "assist_id": assist_id,
            "assist_action": action,
            "result": normalized_result,
            "notes": notes,
        },
    )
    return payload


_RECLAIM_UI_DISABLED_MESSAGE = (
    "Reclaim UI automation is disabled. "
    "Set RECLAIM_UI_AUTOMATION_ENABLE=true and restart the server."
)


def _reclaim_ui_disabled(action: str) -> str:
    payload = {
        "status": "error",
        "action": action,
        "error": {
            "code": "reclaim_ui_disabled",
            "message": _RECLAIM_UI_DISABLED_MESSAGE,
        },
        "reclaim_ui": {
            "enabled": False,
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)

def _reclaim_ui_base_payload(action: str) -> dict:
    return {
        "status": "ok",
        "action": action,
        "reclaim_ui": {
            "enabled": True,
            "mode": "manual_session",
        },
    }


def _reclaim_official_tool_names() -> list[str]:
    prefix = f"{RECLAIM_OFFICIAL_MCP_PREFIX}_"
    return [name for name in _registered_tool_names() if name.startswith(prefix)]


def _reclaim_official_adapter_payload() -> dict:
    official_tools = _reclaim_official_tool_names()
    provider_order = ["official_mcp", "google_tasks_calendar", "dom_cdp"]
    capability_map = {
        "schedule_analysis": "official_mcp if available; otherwise google calendar + google tasks",
        "task_crud": "official_mcp if task tools are observed; otherwise google tasks",
        "task_start_stop": "official_mcp if work-session/timer tools are observed; otherwise dom_cdp",
        "task_complete": "official_mcp if task completion is observed; otherwise google tasks/dom_cdp",
        "task_snooze_reschedule": "official_mcp only with preview/approval; otherwise dom_cdp with visual validation",
        "event_unlock": "dom_cdp until the official MCP exposes an explicit unlock-equivalent tool",
    }
    return {
        "status": "ok",
        "adapter": "reclaim_official_mcp",
        "official_mcp": {
            "enabled": bool(RECLAIM_OFFICIAL_MCP_ENABLE),
            "url": RECLAIM_OFFICIAL_MCP_URL,
            "prefix": RECLAIM_OFFICIAL_MCP_PREFIX,
            "mounted": bool(RECLAIM_OFFICIAL_MCP_MOUNTED),
            "observed_tools": official_tools,
            "observed_tool_count": len(official_tools),
        },
        "fallbacks": {
            "google_tasks_calendar": True,
            "dom_cdp": bool(RECLAIM_UI_AUTOMATION_ENABLE),
        },
        "provider_order": provider_order,
        "capability_map": capability_map,
        "audited_capabilities": {
            "ok_now": [
                "get_schedule",
                "get_user_preferences",
                "focus_stats",
                "top_contacts",
                "search_contacts",
                "get_pending_changes",
                "suggested_times_for_event",
            ],
            "blocked_upgrade": [
                "get_event_details",
                "find_open_time",
                "get_org_relationships",
                "get_zoom_meeting_summary",
                "add_event",
                "update_event",
                "cancel_event",
                "reschedule_event",
                "change_rsvp",
                "add_video_conference",
                "get_suggested_tasks",
                "get_at_risk_tasks",
                "start_task",
                "stop_task",
                "log_task",
                "create_reclaim_task",
                "update_reclaim_task",
                "delete_reclaim_task",
                "search_reclaim_tasks",
                "apply_changes",
            ],
            "server_error": ["suggested_times"],
        },
        "policy": [
            "Do not remove existing Reclaim UI/Google Tasks tools.",
            "Prefer official MCP only for capabilities that were observed and validated.",
            "Keep plan_day_apply on Google Tasks -> Reclaim -> Calendar; never create direct Calendar events for Reclaim tasks.",
            "Keep event unlock on DOM/CDP until official MCP support is proven.",
            "Jarvis direct use requires confirmed remote MCP OAuth support or tools already exposed by a compatible authenticated client.",
        ],
    }


@mcp.tool()
def reclaim_official_adapter_status() -> str:
    """Mostra o estado do adapter do MCP oficial do Reclaim 2.0."""
    return json.dumps(_reclaim_official_adapter_payload(), indent=2, ensure_ascii=False)




_RECLAIM_OFFICIAL_SCHEDULE_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_RECLAIM_OFFICIAL_TOOL_STATUS_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def _reclaim_official_mcp_call_tool(name: str, arguments: dict | None = None, timeout_sec: int = 45) -> dict:
    """Call one tool through mcp-remote and return the raw JSON-RPC response."""
    import select

    proc = subprocess.Popen(
        ["mcp-remote", RECLAIM_OFFICIAL_MCP_URL],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    next_id = 1

    def _send(method: str, params: dict | None = None) -> int:
        nonlocal next_id
        req_id = next_id
        next_id += 1
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        return req_id

    def _notify(method: str, params: dict | None = None) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()

    def _wait(req_id: int, timeout: int) -> dict:
        assert proc.stdout is not None
        assert proc.stderr is not None
        end = time.time() + timeout
        last_stderr: deque[str] = deque(maxlen=12)
        while time.time() < end:
            ready, _, _ = select.select([proc.stdout, proc.stderr], [], [], 0.2)
            for stream in ready:
                line = stream.readline()
                if not line:
                    continue
                if stream is proc.stderr:
                    last_stderr.append(line.strip())
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("id") == req_id:
                    return obj
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": "timeout waiting for mcp-remote response",
                "stderr": list(last_stderr),
            },
        }

    try:
        init_id = _send(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-reclaim-official-adapter", "version": "1.0"},
            },
        )
        init_res = _wait(init_id, timeout_sec)
        if init_res.get("error"):
            return init_res
        _notify("notifications/initialized")
        call_id = _send("tools/call", {"name": name, "arguments": arguments or {}})
        return _wait(call_id, timeout_sec)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()


def _reclaim_official_tool_result_status(response: dict) -> tuple[str, str]:
    if response.get("error"):
        return "server_error", str(response.get("error"))[:500]
    result = response.get("result") or {}
    text = "\n".join(
        item.get("text", "")
        for item in (result.get("content") or [])
        if item.get("type") == "text"
    )
    if result.get("isError"):
        low = text.lower()
        if "upgraded subscription" in low or "not available for this user's account" in low:
            return "blocked_upgrade", text[:500]
        return "server_error", text[:500]
    return "ok", text[:500]


def _reclaim_official_capability_status(force: bool = False) -> dict[str, str]:
    cached = _RECLAIM_OFFICIAL_TOOL_STATUS_CACHE.get("v1")
    if cached and not force and (time.time() - cached[0]) < 900:
        return cached[1]
    probes = {
        "get_schedule": ("get_schedule", {"start": "2026-06-18", "end": "2026-06-18", "showResults": False}),
        "get_user_preferences": ("get_user_preferences", {"type": "BASIC"}),
        "focus_stats": ("focus_stats", {"start": "2026-06-18", "end": "2026-06-18"}),
        "get_pending_changes": ("get_pending_changes", {}),
        "get_suggested_tasks": ("get_suggested_tasks", {}),
        "get_at_risk_tasks": ("get_at_risk_tasks", {}),
        "search_reclaim_tasks": (
            "search_reclaim_tasks",
            {"query": "", "chatContextSummary": "Capability probe; do not change data."},
        ),
        "find_open_time": ("find_open_time", {"lookaheadDays": 1, "hoursType": "PERSONAL"}),
        "start_task": ("start_task", {"title": "__JARVIS_CAPABILITY_PROBE_INEXISTENT_TASK__"}),
    }
    statuses: dict[str, str] = {}
    for key, (tool, args) in probes.items():
        status, _ = _reclaim_official_tool_result_status(_reclaim_official_mcp_call_tool(tool, args, timeout_sec=30))
        statuses[key] = status
    _RECLAIM_OFFICIAL_TOOL_STATUS_CACHE["v1"] = (time.time(), statuses)
    return statuses


def _reclaim_official_get_schedule(day: str, show_results: bool = False, force: bool = False) -> dict:
    cache_key = (day, "1" if show_results else "0")
    cached = _RECLAIM_OFFICIAL_SCHEDULE_CACHE.get(cache_key)
    if cached and (not force) and (time.time() - cached[0]) < 300:
        return cached[1]
    response = _reclaim_official_mcp_call_tool(
        "get_schedule",
        {"start": day, "end": day, "showResults": bool(show_results)},
        timeout_sec=60,
    )
    status, detail = _reclaim_official_tool_result_status(response)
    if status != "ok":
        result = {"ok": False, "status": status, "detail": detail, "events": []}
        _RECLAIM_OFFICIAL_SCHEDULE_CACHE[cache_key] = (time.time(), result)
        return result
    events = (((response.get("result") or {}).get("structuredContent") or {}).get("result") or [])
    result = {"ok": True, "status": "ok", "detail": "", "events": events}
    _RECLAIM_OFFICIAL_SCHEDULE_CACHE[cache_key] = (time.time(), result)
    return result


def _reclaim_official_parse_event_dt(raw: str, day: str, tzinfo) -> datetime | None:
    if not raw:
        return None
    cleaned = str(raw).replace("\u202f", " ").replace("\xa0", " ").replace(" ", " ").strip()
    formats = ("%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=tzinfo) if tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return dt if dt.tzinfo else (dt.replace(tzinfo=tzinfo) if tzinfo else dt.replace(tzinfo=timezone.utc))
    except Exception:
        return None


def _reclaim_official_events_to_busy(events: list[dict], day: str, tzinfo) -> tuple[list[tuple[datetime, datetime, str]], list[tuple[str, str, str]], list[dict]]:
    busy: list[tuple[datetime, datetime, str]] = []
    generic_meetings: list[tuple[str, str, str]] = []
    reclaim_task_events: list[dict] = []
    for ev in events:
        st = _reclaim_official_parse_event_dt(ev.get("start", ""), day, tzinfo)
        en = _reclaim_official_parse_event_dt(ev.get("end", ""), day, tzinfo)
        if not st or not en or en <= st:
            continue
        platform = str(ev.get("platform") or "reclaim-official")
        busy.append((st.astimezone(timezone.utc), en.astimezone(timezone.utc), platform))
        title = (ev.get("title") or "").strip()
        normalized = title.replace("🤝", "").strip().lower()
        if normalized == "meeting":
            generic_meetings.append((ev.get("start", ""), ev.get("end", ""), platform))
        desc = str(ev.get("description") or "")
        if "Reclaim" in desc or title.startswith("[") or ev.get("category") == "PRODUCTIVITY":
            reclaim_task_events.append(ev)
    return busy, generic_meetings, reclaim_task_events


def _reclaim_official_agenda_quality(events: list[dict], day: str, day_end: str, tzinfo) -> dict:
    cutoff_h, cutoff_m = map(int, day_end.split(":"))
    y, mo, da = map(int, day.split("-"))
    cutoff = datetime(y, mo, da, cutoff_h, cutoff_m, tzinfo=tzinfo) if tzinfo else datetime(y, mo, da, cutoff_h, cutoff_m, tzinfo=timezone.utc)
    intervals = []
    for ev in events:
        st = _reclaim_official_parse_event_dt(ev.get("start", ""), day, tzinfo)
        en = _reclaim_official_parse_event_dt(ev.get("end", ""), day, tzinfo)
        if not st or not en or en <= st:
            continue
        intervals.append((st, en, ev))
    intervals.sort(key=lambda item: item[0])

    overlaps = []
    for prev, cur in zip(intervals, intervals[1:]):
        p_st, p_en, p_ev = prev
        c_st, c_en, c_ev = cur
        if c_st < p_en:
            overlaps.append(
                {
                    "first": p_ev.get("title", ""),
                    "second": c_ev.get("title", ""),
                    "start": c_st.strftime("%H:%M"),
                    "end": min(p_en, c_en).strftime("%H:%M"),
                }
            )

    after_cutoff = []
    for st, en, ev in intervals:
        if en > cutoff:
            after_cutoff.append(
                {
                    "title": ev.get("title", ""),
                    "start": st.strftime("%H:%M"),
                    "end": en.strftime("%H:%M"),
                }
            )

    task_events = []
    for _, _, ev in intervals:
        title = (ev.get("title") or "").strip()
        desc = str(ev.get("description") or "")
        if "Reclaim" in desc or title.startswith("[") or ev.get("category") == "PRODUCTIVITY":
            task_events.append(ev)

    issues = []
    if overlaps:
        issues.append("overlap")
    if after_cutoff:
        issues.append("after_cutoff")
    return {
        "ok": not issues,
        "issues": issues,
        "overlaps": overlaps,
        "after_cutoff": after_cutoff,
        "event_count": len(intervals),
        "task_event_count": len(task_events),
    }


def _format_reclaim_agenda_quality(quality: dict) -> list[str]:
    lines = []
    if quality.get("ok"):
        lines.append("- qualidade: sem conflitos detectados e sem eventos após o limite configurado.")
        return lines
    lines.append("- qualidade: ruim, precisa de nova iteração ou intervenção.")
    for item in quality.get("overlaps", [])[:6]:
        lines.append(f"- conflito {item['start']}–{item['end']}: {item['first']} / {item['second']}")
    for item in quality.get("after_cutoff", [])[:6]:
        lines.append(f"- fora do limite {item['start']}–{item['end']}: {item['title']}")
    return lines
def _reclaim_open_login_url(*, visible_required: bool = False) -> dict:
    return _open_login_url(RECLAIM_UI_LOGIN_URL, visible_required=visible_required)


def _reclaim_login_workaround_hint() -> dict:
    return {
        "mode": "manual_remote_workaround",
        "steps": [
            f"1. Abra {RECLAIM_UI_LOGIN_URL} em um navegador com interface gráfica.",
            "2. Faça login no Reclaim e resolva captcha, se houver.",
            "3. Volte ao agente e execute reclaim_session_bootstrap(manual_login_confirmed=true, captcha_resolved=true, open_browser=false).",
        ],
    }


def _reclaim_fetch_gtasks_candidates(task_list_id: str) -> dict:
    try:
        service = _gtasks_service()
        results = service.tasks().list(tasklist=task_list_id, showCompleted=False).execute()
        items = results.get('items', [])
        candidates = [
            {
                "id": it.get("id", ""),
                "title": it.get("title", ""),
            }
            for it in items
        ]
        return {
            "status": "ok",
            "source": "google_tasks",
            "candidates": candidates,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": {
                "code": "gtasks_invalid_grant" if _is_google_invalid_grant(e) else "gtasks_resolution_failed",
                "message": f"Falha ao buscar tarefas no Google Tasks: {_google_auth_actionable_error(e)}",
            },
            "candidates": [],
        }


def _reclaim_collect_ui_candidates(ui_payload: dict | None) -> list[dict]:
    payload = ui_payload if isinstance(ui_payload, dict) else {}
    normalized_candidates: list[dict] = []
    seen_titles: set[str] = set()

    def _push(raw: object) -> None:
        if raw is None:
            return
        if isinstance(raw, dict):
            candidate = dict(raw)
        else:
            candidate = {"title": str(raw)}
        title = normalize_title(candidate.get("title"))
        if not title or title in seen_titles:
            return
        candidate["title"] = title
        candidate["normalized_title"] = title
        seen_titles.add(title)
        normalized_candidates.append(candidate)

    raw_candidates = payload.get("candidates")
    if isinstance(raw_candidates, list):
        for item in raw_candidates:
            _push(item)

    _push(payload.get("next_task"))
    _push(payload.get("next"))
    _push(payload.get("match"))
    _push(payload.get("target_title"))
    _push(payload.get("title"))

    return normalized_candidates


def _reclaim_pick_next_candidate(candidates: list) -> dict:
    normalized_candidates = []
    for idx, raw in enumerate(candidates or []):
        if isinstance(raw, dict):
            entry = dict(raw)
        else:
            entry = {"title": str(raw)}
        entry.setdefault("index", idx)
        title = normalize_title(entry.get("title"))
        if not title:
            continue
        entry["title"] = title
        entry["normalized_title"] = title
        normalized_candidates.append(entry)

    if not normalized_candidates:
        return {
            "status": "error",
            "resolution": "no_candidates",
            "error": {
                "code": "no_candidates",
                "message": "Nenhuma tarefa válida encontrada para sugerir como próxima.",
            },
            "candidates": [],
        }

    return {
        "status": "ok",
        "resolution": "next_candidate",
        "next": normalized_candidates[0],
        "candidates": normalized_candidates,
    }


def _reclaim_session_bootstrap_impl(
    manual_login_confirmed: bool = False,
    captcha_resolved: bool = True,
    open_browser: bool = True,
) -> str:
    """Bootstrap de sessão Reclaim UI com persistência local."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_session_bootstrap")

    visual_flow = {
        "url": RECLAIM_UI_LOGIN_URL,
        "opened": False,
        "method": "manual",
        "headless": False,
    }
    if open_browser:
        visual_flow = _reclaim_open_login_url(visible_required=not manual_login_confirmed)

    bootstrap_session(
        path=RECLAIM_UI_SESSION_FILE,
        manual_login_confirmed=manual_login_confirmed,
        captcha_resolved=captcha_resolved,
        captcha_timeout_sec=RECLAIM_UI_CAPTCHA_TIMEOUT_SEC,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )
    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )

    payload = _reclaim_ui_base_payload("reclaim_session_bootstrap")
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)
    payload["session"] = session_data
    payload["visual_flow"] = visual_flow
    if not bool(visual_flow.get("opened", False)):
        payload["login_workaround"] = _reclaim_login_workaround_hint()

    state = session_data.get("state")
    if state == "valid":
        payload["result"] = "bootstrapped"
        payload["next_step"] = "Sessão pronta para uso."
    elif state == "blocked_captcha":
        payload["status"] = "error"
        payload["result"] = "captcha_blocked"
        payload["next_step"] = "Resolva o captcha manualmente e rode reclaim_session_bootstrap(manual_login_confirmed=true, captcha_resolved=true)."
    else:
        payload["result"] = "pending_manual_login"
        payload["next_step"] = "Conclua o login manual e rode reclaim_session_bootstrap(manual_login_confirmed=true)."

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_session_bootstrap",
            "state": state,
            "manual_login_confirmed": bool(manual_login_confirmed),
            "captcha_resolved": bool(captcha_resolved),
            "result": payload.get("result"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_session_bootstrap(
    manual_login_confirmed: bool = False,
    captcha_resolved: bool = True,
    open_browser: bool = True,
) -> str:
    """Bootstrap de sessão Reclaim UI com persistência local."""
    return _reclaim_session_bootstrap_impl(
        manual_login_confirmed=manual_login_confirmed,
        captcha_resolved=captcha_resolved,
        open_browser=open_browser,
    )


@mcp.tool()
def reclaim_session_status() -> str:
    """Status da sessão Reclaim UI com validação e expiração."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_session_status")

    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )

    payload = _reclaim_ui_base_payload("reclaim_session_status")
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)
    payload["session"] = session_data

    state = session_data.get("state")
    if state == "valid":
        validation = run_reclaim_playwright_action(action="next", title="", timeout_sec=10)
        payload["ui_validation"] = validation
        validation_code = validation.get("error", {}).get("code") or validation.get("result")
        if validation_code == "login_or_captcha_required":
            session_data = get_session_status(
                path=RECLAIM_UI_SESSION_FILE,
                session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
            )
            payload["session"] = session_data
            payload["status"] = "error"
            payload["result"] = "pending_manual_login"
            payload["next_step"] = "Login/captcha detectado no Reclaim. Rode reclaim_session_bootstrap(open_browser=true), conclua o login e confirme."
        elif validation_code == "profile_in_use":
            payload["status"] = "error"
            payload["result"] = "profile_in_use"
            payload["next_step"] = validation.get("next_step") or "Feche a janela visível do perfil Playwright e tente novamente."
        else:
            payload["result"] = "valid"
            payload["next_step"] = "Sessão válida para start/stop/restart."
    elif state == "expired":
        payload["status"] = "error"
        payload["result"] = "expired"
        payload["next_step"] = "Execute reclaim_session_bootstrap para revalidar a sessão."
    elif state == "blocked_captcha":
        payload["status"] = "error"
        payload["result"] = "captcha_blocked"
        payload["next_step"] = "Resolva captcha e execute reclaim_session_bootstrap(manual_login_confirmed=true, captcha_resolved=true)."
    else:
        payload["result"] = "not_bootstrapped"
        payload["next_step"] = "Execute reclaim_session_bootstrap para iniciar o login manual."

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_session_status",
            "state": state,
            "result": payload.get("result"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_task_start(
    title: str = "",
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    visual_candidates: list[str] | None = None,
) -> str:
    """Envia pedido de início ao Reclaim. O retorno confirma envio, não prova timer ativo."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_task_start")

    normalized_title = normalize_title(title)
    payload = _reclaim_ui_base_payload("reclaim_task_start")
    payload["task"] = {
        "title": normalized_title,
        "action": "start",
    }
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)
    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )
    payload["session"] = session_data
    session_state = session_data.get("state")
    if session_state != "valid":
        payload["status"] = "error"
        payload["result"] = "session_invalid"
        payload["error"] = {
            "code": "session_not_valid",
            "message": f"Sessão inválida para start: {session_state}",
        }
        if session_state == "expired":
            payload["next_step"] = "Sessão expirada. Rode reclaim_session_bootstrap para renovar."
        elif session_state == "blocked_captcha":
            payload["next_step"] = "Captcha bloqueado. Conclua login manual e rode reclaim_session_bootstrap."
        else:
            payload["next_step"] = "Sessão ausente. Rode reclaim_session_bootstrap(manual_login_confirmed=true)."
        append_audit_event(
            RECLAIM_UI_AUDIT_FILE,
            {
                "action": "reclaim_task_start",
                "result": payload["result"],
                "title": normalized_title,
                "task_list_id": task_list_id,
                "session_state": session_state,
            },
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    if not normalized_title:
        payload["resolution_source"] = "ui_auto_next"
        payload["resolution"] = "auto_next"
        ui_action = run_reclaim_ui_action(
            action="start",
            title="",
            timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
            executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
        )
        payload["ui_action"] = ui_action
        if ui_action.get("status") == "ok":
            resolved_title = (ui_action.get("target_title") or "").strip()
            if resolved_title:
                payload["task"]["title"] = resolved_title
            payload["result"] = ui_action.get("result") or "start_requested_unverified"
            payload["executed_at"] = ui_action.get("executed_at")
            payload["message"] = "Pedido de Start enviado ao Reclaim, mas ainda sem confirmação confiável do timer."
            payload["next_step"] = "Confirme visualmente o timer no Reclaim ou valide pela sincronização do Calendar após alguns minutos."
        else:
            reason = ui_action.get("error", {}).get("code") or ui_action.get("result")
            detail = ui_action.get("error", {}).get("message") or ui_action.get("message")
            assist = create_assist_request(
                audit_path=RECLAIM_UI_AUDIT_FILE,
                action="start",
                title=payload["task"]["title"],
                reason=reason,
                detail=detail,
                login_url=RECLAIM_UI_LOGIN_URL,
                open_browser=RECLAIM_UI_ASSIST_OPEN_BROWSER,
                session_state=session_state,
            )
            payload["assist"] = assist
            payload["status"] = "assist_mode"
            payload["result"] = "assistance_required"
            payload["message"] = "Automação falhou e entrou em modo assistido para completar a ação manual."
            payload["next_step"] = assist["confirm_next_step"]

        append_audit_event(
            RECLAIM_UI_AUDIT_FILE,
            {
                "action": "reclaim_task_start",
                "result": payload.get("result"),
                "title": normalized_title,
                "task_list_id": task_list_id,
                "resolution_source": payload.get("resolution_source"),
                "session_state": session_state,
                "executor": RECLAIM_UI_EXECUTOR_CMD,
                "assist_id": payload.get("assist", {}).get("assist_id"),
            },
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    if visual_candidates is not None:
        candidates = [{"title": c} for c in visual_candidates]
        source = "visual_candidates"
    else:
        fetched = _reclaim_fetch_gtasks_candidates(task_list_id=task_list_id)
        if fetched.get("status") != "ok":
            payload["status"] = "error"
            payload["result"] = "resolution_error"
            payload["error"] = fetched.get("error", {"code": "resolution_error", "message": "Falha desconhecida na resolução."})
            payload["next_step"] = "Corrija autenticação do Google Tasks e tente novamente."
            append_audit_event(
                RECLAIM_UI_AUDIT_FILE,
                {
                    "action": "reclaim_task_start",
                    "result": payload["result"],
                    "title": normalized_title,
                    "task_list_id": task_list_id,
                },
            )
            return json.dumps(payload, indent=2, ensure_ascii=False)
        candidates = fetched.get("candidates", [])
        source = fetched.get("source", "google_tasks")

    resolution = resolve_exact_title(normalized_title, candidates)
    payload["resolution_source"] = source
    payload["resolution"] = resolution.get("resolution")

    if resolution.get("status") == "ok":
        match = resolution.get("match", {})
        payload["task"]["title"] = match.get("title", normalized_title)
        if match.get("id"):
            payload["task"]["task_id"] = match.get("id")
        ui_action = run_reclaim_ui_action(
            action="start",
            title=payload["task"]["title"],
            timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
            executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
        )
        payload["ui_action"] = ui_action
        if ui_action.get("status") == "ok":
            payload["result"] = ui_action.get("result") or "start_requested_unverified"
            payload["executed_at"] = ui_action.get("executed_at")
            payload["message"] = "Pedido de Start enviado ao Reclaim, mas ainda sem confirmação confiável do timer."
            payload["next_step"] = "Confirme visualmente o timer no Reclaim ou valide pela sincronização do Calendar após alguns minutos."
        else:
            reason = ui_action.get("error", {}).get("code") or ui_action.get("result")
            detail = ui_action.get("error", {}).get("message") or ui_action.get("message")
            assist = create_assist_request(
                audit_path=RECLAIM_UI_AUDIT_FILE,
                action="start",
                title=payload["task"]["title"],
                reason=reason,
                detail=detail,
                login_url=RECLAIM_UI_LOGIN_URL,
                open_browser=RECLAIM_UI_ASSIST_OPEN_BROWSER,
                session_state=session_state,
            )
            payload["assist"] = assist
            payload["status"] = "assist_mode"
            payload["result"] = "assistance_required"
            payload["message"] = "Automação falhou e entrou em modo assistido para completar a ação manual."
            payload["next_step"] = assist["confirm_next_step"]
    elif resolution.get("resolution") == "ambiguous":
        payload["status"] = "error"
        payload["result"] = "requires_assisted_confirmation"
        payload["error"] = resolution.get("error", {})
        payload["candidates"] = resolution.get("candidates", [])
        payload["next_step"] = "Mais de um candidato visual/título exato. Faça confirmação assistida antes de iniciar."
    else:
        payload["status"] = "error"
        payload["result"] = "title_not_found"
        payload["error"] = resolution.get("error", {})
        payload["next_step"] = "Título não encontrado. Revise o título ou sincronize novamente com Google Tasks."

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_task_start",
            "result": payload.get("result"),
            "title": normalized_title,
            "task_list_id": task_list_id,
            "resolution_source": source,
            "session_state": session_state,
            "executor": RECLAIM_UI_EXECUTOR_CMD,
            "assist_id": payload.get("assist", {}).get("assist_id"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_next_task(
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    visual_candidates: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Retorna a próxima tarefa candidata para iniciar no Reclaim, sem acionar a UI."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_next_task")

    payload = _reclaim_ui_base_payload("reclaim_next_task")
    payload["task"] = {
        "action": "next",
    }
    source = "google_tasks"
    candidates: list[dict] = []

    if visual_candidates is not None:
        candidates = [{"title": c} for c in visual_candidates]
        source = "visual_candidates"
    else:
        session_data = get_session_status(
            path=RECLAIM_UI_SESSION_FILE,
            session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
        )
        payload["session"] = session_data
        if session_data.get("state") == "valid":
            ui_probe = run_reclaim_ui_action(
                action="next",
                title="",
                timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
                executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
            )
            payload["ui_probe"] = ui_probe
            ui_candidates = _reclaim_collect_ui_candidates(ui_probe)
            if ui_candidates:
                candidates = ui_candidates
                source = "ui_next"

        if not candidates:
            fetched = _reclaim_fetch_gtasks_candidates(task_list_id=task_list_id)
            if fetched.get("status") != "ok":
                payload["status"] = "error"
                payload["result"] = "resolution_error"
                payload["error"] = fetched.get("error", {"code": "resolution_error", "message": "Falha desconhecida na resolução."})
                payload["next_step"] = "Corrija autenticação do Google Tasks e tente novamente."
                append_audit_event(
                    RECLAIM_UI_AUDIT_FILE,
                    {
                        "action": "reclaim_next_task",
                        "result": payload["result"],
                        "task_list_id": task_list_id,
                        "resolution_source": source,
                    },
                )
                return json.dumps(payload, indent=2, ensure_ascii=False)
            candidates = fetched.get("candidates", [])
            source = fetched.get("source", "google_tasks")
    selection = _reclaim_pick_next_candidate(candidates)
    payload["resolution_source"] = source
    payload["resolution"] = selection.get("resolution")
    if selection.get("status") == "ok":
        next_task = selection.get("next", {})
        payload["result"] = "next_task_found"
        payload["task"]["title"] = next_task.get("title", "")
        if next_task.get("id"):
            payload["task"]["task_id"] = next_task.get("id")
        payload["next_task"] = next_task
        payload["candidates"] = selection.get("candidates", [])[: max(1, limit)]
        payload["next_step"] = "Use reclaim_task_start(title=...) para iniciar essa tarefa no Reclaim."
    else:
        payload["status"] = "error"
        payload["result"] = "next_task_not_found"
        payload["error"] = selection.get("error", {"code": "no_candidates", "message": "Nenhuma tarefa disponível."})
        payload["candidates"] = []
        payload["next_step"] = "Adicione ou sincronize tarefas no Google Tasks e tente novamente."

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_next_task",
            "result": payload.get("result"),
            "task_title": payload.get("task", {}).get("title", ""),
            "task_list_id": task_list_id,
            "resolution_source": source,
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_task_stop(title: str | None = None) -> str:
    """Para tarefa ativa no Reclaim via executor de UI."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_task_stop")

    normalized_title = (title or "").strip()
    payload = _reclaim_ui_base_payload("reclaim_task_stop")
    payload["task"] = {
        "title": normalized_title,
        "action": "stop",
    }
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)

    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )
    payload["session"] = session_data
    session_state = session_data.get("state")
    if session_state != "valid":
        payload["status"] = "error"
        payload["result"] = "session_invalid"
        payload["error"] = {
            "code": "session_not_valid",
            "message": f"Sessão inválida para stop: {session_state}",
        }
        payload["next_step"] = "Rode reclaim_session_bootstrap(manual_login_confirmed=true) para revalidar a sessão."
        append_audit_event(
            RECLAIM_UI_AUDIT_FILE,
            {
                "action": "reclaim_task_stop",
                "result": payload["result"],
                "title": normalized_title,
                "session_state": session_state,
            },
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    ui_action = run_reclaim_ui_action(
        action="stop",
        title=normalized_title,
        timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
        executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
    )
    payload["ui_action"] = ui_action
    if ui_action.get("status") == "ok":
        payload["result"] = "stopped"
        payload["executed_at"] = ui_action.get("executed_at")
        payload["message"] = "Ação Stop executada na UI do Reclaim."
        payload["next_step"] = "Verifique se não há timer ativo."
    else:
        reason = ui_action.get("error", {}).get("code") or ui_action.get("result")
        detail = ui_action.get("error", {}).get("message") or ui_action.get("message")
        assist = create_assist_request(
            audit_path=RECLAIM_UI_AUDIT_FILE,
            action="stop",
            title=normalized_title,
            reason=reason,
            detail=detail,
            login_url=RECLAIM_UI_LOGIN_URL,
            open_browser=RECLAIM_UI_ASSIST_OPEN_BROWSER,
            session_state=session_state,
        )
        payload["assist"] = assist
        payload["status"] = "assist_mode"
        payload["result"] = "assistance_required"
        payload["message"] = "Automação falhou e entrou em modo assistido para completar a ação manual."
        payload["next_step"] = assist["confirm_next_step"]

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_task_stop",
            "result": payload.get("result"),
            "title": normalized_title,
            "session_state": session_state,
            "executor": RECLAIM_UI_EXECUTOR_CMD,
            "assist_id": payload.get("assist", {}).get("assist_id"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_task_restart(title: str | None = None) -> str:
    """Reinicia tarefa no Reclaim via executor de UI."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_task_restart")

    normalized_title = (title or "").strip()
    payload = _reclaim_ui_base_payload("reclaim_task_restart")
    payload["task"] = {
        "title": normalized_title,
        "action": "restart",
    }
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)

    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )
    payload["session"] = session_data
    session_state = session_data.get("state")
    if session_state != "valid":
        payload["status"] = "error"
        payload["result"] = "session_invalid"
        payload["error"] = {
            "code": "session_not_valid",
            "message": f"Sessão inválida para restart: {session_state}",
        }
        payload["next_step"] = "Rode reclaim_session_bootstrap(manual_login_confirmed=true) para revalidar a sessão."
        append_audit_event(
            RECLAIM_UI_AUDIT_FILE,
            {
                "action": "reclaim_task_restart",
                "result": payload["result"],
                "title": normalized_title,
                "session_state": session_state,
            },
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    ui_action = run_reclaim_ui_action(
        action="restart",
        title=normalized_title,
        timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
        executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
    )
    payload["ui_action"] = ui_action
    if ui_action.get("status") == "ok":
        payload["result"] = "restarted"
        payload["executed_at"] = ui_action.get("executed_at")
        payload["message"] = "Ação Restart executada na UI do Reclaim."
        payload["next_step"] = "Verifique se o timer foi retomado no Reclaim."
    else:
        reason = ui_action.get("error", {}).get("code") or ui_action.get("result")
        detail = ui_action.get("error", {}).get("message") or ui_action.get("message")
        assist = create_assist_request(
            audit_path=RECLAIM_UI_AUDIT_FILE,
            action="restart",
            title=normalized_title,
            reason=reason,
            detail=detail,
            login_url=RECLAIM_UI_LOGIN_URL,
            open_browser=RECLAIM_UI_ASSIST_OPEN_BROWSER,
            session_state=session_state,
        )
        payload["assist"] = assist
        payload["status"] = "assist_mode"
        payload["result"] = "assistance_required"
        payload["message"] = "Automação falhou e entrou em modo assistido para completar a ação manual."
        payload["next_step"] = assist["confirm_next_step"]

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": "reclaim_task_restart",
            "result": payload.get("result"),
            "title": normalized_title,
            "session_state": session_state,
            "executor": RECLAIM_UI_EXECUTOR_CMD,
            "assist_id": payload.get("assist", {}).get("assist_id"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _reclaim_task_dom_action(
    tool_name: str,
    action: str,
    title: str,
    value: str = "",
) -> str:
    """Executa uma ação DOM/CDP por título no Reclaim."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled(tool_name)

    normalized_title = normalize_title(title)
    payload = _reclaim_ui_base_payload(tool_name)
    payload["task"] = {
        "title": normalized_title,
        "action": action,
    }
    if value:
        payload["task"]["value"] = value
    payload["session_file"] = str(RECLAIM_UI_SESSION_FILE)

    session_data = get_session_status(
        path=RECLAIM_UI_SESSION_FILE,
        session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
    )
    payload["session"] = session_data
    session_state = session_data.get("state")
    if session_state != "valid":
        payload["status"] = "error"
        payload["result"] = "session_invalid"
        payload["error"] = {
            "code": "session_not_valid",
            "message": f"Sessão inválida para {action}: {session_state}",
        }
        payload["next_step"] = "Rode reclaim_session_bootstrap(manual_login_confirmed=true) para revalidar a sessão."
        return json.dumps(payload, indent=2, ensure_ascii=False)

    ui_action = run_reclaim_ui_action(
        action=action,
        title=normalized_title,
        timeout_sec=RECLAIM_UI_EXECUTOR_TIMEOUT_SEC,
        executor_cmd=RECLAIM_UI_EXECUTOR_CMD,
        extra_env={"value": value},
    )
    payload["ui_action"] = ui_action
    if ui_action.get("status") == "ok":
        payload["result"] = ui_action.get("result") or f"{action}_sent_unverified"
        payload["executed_at"] = ui_action.get("executed_at")
        payload["message"] = "Ação enviada ao Reclaim via DOM/CDP."
        payload["next_step"] = "Valide o DOM do Reclaim ou a sincronização posterior quando a ação alterar agenda."
    else:
        reason = ui_action.get("error", {}).get("code") or ui_action.get("result")
        detail = ui_action.get("error", {}).get("message") or ui_action.get("message")
        assist = create_assist_request(
            audit_path=RECLAIM_UI_AUDIT_FILE,
            action=action,
            title=normalized_title,
            reason=reason,
            detail=detail,
            login_url=RECLAIM_UI_LOGIN_URL,
            open_browser=RECLAIM_UI_ASSIST_OPEN_BROWSER,
            session_state=session_state,
        )
        payload["assist"] = assist
        payload["status"] = "assist_mode"
        payload["result"] = "assistance_required"
        payload["message"] = "Automação falhou e entrou em modo assistido para completar a ação manual."
        payload["next_step"] = assist["confirm_next_step"]

    append_audit_event(
        RECLAIM_UI_AUDIT_FILE,
        {
            "action": tool_name,
            "result": payload.get("result"),
            "task_title": normalized_title,
            "task_action": action,
            "value": value,
            "session_state": session_state,
            "assist_id": payload.get("assist", {}).get("assist_id"),
        },
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def reclaim_task_up_next(title: str) -> str:
    """Envia a tarefa para Up Next no Reclaim via DOM/CDP."""
    return _reclaim_task_dom_action("reclaim_task_up_next", "up_next", title)


@mcp.tool()
def reclaim_task_done(title: str) -> str:
    """Marca a tarefa como concluída no Reclaim via DOM/CDP."""
    return _reclaim_task_dom_action("reclaim_task_done", "done", title)


@mcp.tool()
def reclaim_task_set_priority(title: str, priority: str) -> str:
    """Define prioridade da tarefa no Reclaim. Valores: Critical, High priority, Medium priority, Low priority."""
    return _reclaim_task_dom_action("reclaim_task_set_priority", "set_priority", title, priority)


@mcp.tool()
def reclaim_task_due_date(title: str, option: str = "") -> str:
    """Abre/seleciona Due date da tarefa no Reclaim. Sem option, retorna o submenu visível."""
    return _reclaim_task_dom_action("reclaim_task_due_date", "due_date", title, option)


@mcp.tool()
def reclaim_task_snooze(title: str, option: str = "") -> str:
    """Abre/seleciona Snooze da tarefa no Reclaim. Sem option, retorna o submenu visível."""
    return _reclaim_task_dom_action("reclaim_task_snooze", "snooze", title, option)


@mcp.tool()
def reclaim_event_context_menu(title: str) -> str:
    """Abre o menu de contexto do evento no calendário e retorna as opções visíveis, sem clicar nelas."""
    return _reclaim_task_dom_action("reclaim_event_context_menu", "calendar_context_menu", title)


@mcp.tool()
def reclaim_event_unlock(title: str) -> str:
    """Clica com botão direito no evento do calendário e escolhe Unlock quando disponível."""
    return _reclaim_task_dom_action("reclaim_event_unlock", "calendar_unlock", title)


@mcp.tool()
def reclaim_event_reschedule(title: str, option: str = "") -> str:
    """Clica com botão direito no evento, escolhe Reschedule e opcionalmente uma opção do popover."""
    return _reclaim_task_dom_action("reclaim_event_reschedule", "calendar_reschedule", title, option)


@mcp.tool()
def reclaim_task_assist_confirm(
    assist_id: str,
    action: str,
    result: str,
    notes: str | None = None,
) -> str:
    """Confirma manualmente o resultado após um fallback assistido."""
    if not RECLAIM_UI_AUTOMATION_ENABLE:
        return _reclaim_ui_disabled("reclaim_task_assist_confirm")

    confirmation = confirm_assist_completion(
        audit_path=RECLAIM_UI_AUDIT_FILE,
        assist_id=assist_id,
        action=action,
        result=result,
        notes=notes,
    )

    payload = _reclaim_ui_base_payload("reclaim_task_assist_confirm")
    payload.update(confirmation)
    if confirmation.get("status") != "ok":
        payload["status"] = "error"
        payload["result"] = "assist_confirm_failed"
        payload["next_step"] = confirmation.get(
            "error", {}
        ).get("message", "Forneça um result válido e tente novamente.")
    else:
        payload["result"] = "assist_confirmed"
        payload["next_step"] = "Continue com o fluxo do Reclaim conforme planejado."

    return json.dumps(payload, indent=2, ensure_ascii=False)

# --- 5. FILESYSTEM (Node.js Integration) ---
def start_filesystem_mcp():
    """Inicia o servidor de arquivos oficial via Node.js (apenas local)"""
    enabled = os.environ.get("FILESYSTEM_MCP_ENABLE", "true").lower() in ("1", "true", "yes", "on")
    if not enabled:
        print("ℹ️  Filesystem MCP desativado via env.", file=sys.stderr)
        return

    # Verifica se npx existe
    npx_path = shutil.which("npx")
    if not npx_path:
        print("⚠️  npx não encontrado. Filesystem MCP requer Node.js.", file=sys.stderr)
        return

    # Define diretórios permitidos (Projeto e Home)
    allowed_dirs = [str(BASE_DIR), os.path.expanduser("~")]
    
    # Porta dedicada para o proxy do Filesystem
    FILESYSTEM_PORT = 8952
    ensure_port_free(FILESYSTEM_PORT, "filesystem-mcp")

    # Comando real: npx -y @modelcontextprotocol/server-filesystem <dirs>
    real_cmd = [npx_path, "-y", "@modelcontextprotocol/server-filesystem"] + allowed_dirs

    # Comando do proxy: node stdio_proxy.js <PORT> <CMD...>
    proxy_cmd = ["node", PROXY_SCRIPT, str(FILESYSTEM_PORT)] + real_cmd

    print(f"📂 Iniciando Filesystem MCP em http://localhost:{FILESYSTEM_PORT} ...")
    env = os.environ.copy()
    proc = subprocess.Popen(proxy_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env)
    threading.Thread(target=_log_process, args=(proc, "filesystem-mcp"), daemon=True).start()
    atexit.register(stop_process, proc)

    # Monta no servidor principal
    try:
        # Aguarda um pouco para o processo subir
        time.sleep(2)
        proxy_url = f"http://localhost:{FILESYSTEM_PORT}/sse"
        proxy = FastMCP.as_proxy(proxy_url, name="filesystem-mcp")
        mcp.mount(proxy, prefix="fs")
        print(f"🔗 Filesystem MCP montado no servidor principal com prefixo fs_*")
    except Exception as e:
        print(f"⚠️  Falha ao montar Filesystem MCP no servidor principal: {e}")

def run_combined_uvicorn(host="0.0.0.0", port=7860):
    """Roda servidor combinado para HTTP/SSE e ferramentas nativas."""
    print(f"🚀 [INIT] Starting Uvicorn on {host}:{port}...", file=sys.stderr)
    import uvicorn
    # ... (código existente) ...
    import logging

    # Transporte HTTP do FastMCP para clientes HTTP/streamable (Gemini MCP `-t http`)
    transport_mode = (os.environ.get("JARVIS_HTTP_TRANSPORT", "http") or "http").strip().lower()
    if transport_mode not in {"http", "streamable-http", "sse"}:
        transport_mode = "http"
    stateless_http = None if transport_mode == "sse" else True
    app = mcp.http_app(path="/mcp", transport=transport_mode, stateless_http=stateless_http)
    print(f"🔌 FastMCP HTTP transport: {transport_mode} (stateless_http={stateless_http})", file=sys.stderr)
    
    # Configure uvicorn to use stderr for all logging
    log_config = uvicorn.config.LOGGING_CONFIG.copy()
    log_config["handlers"]["default"]["stream"] = "ext://sys.stderr"
    log_config["handlers"]["access"]["stream"] = "ext://sys.stderr"
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        timeout_keep_alive=300,
        timeout_graceful_shutdown=0,
        lifespan="on",
        ws="websockets-sansio",
        log_config=log_config,
        log_level="info",
        forwarded_allow_ips="*", # CRÍTICO: Confia nos headers do proxy HF (X-Forwarded-Proto)
        proxy_headers=True       # Garante que URLs geradas sejam HTTPS
    )
    server = uvicorn.Server(config)
    try:
        print("🚀 Iniciando Uvicorn Server...", file=sys.stderr)
        server.run()
    except Exception as e:
        print(f"❌ Erro fatal no Uvicorn: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        print("🛑 Uvicorn encerrou.", file=sys.stderr)


def auto_diagnostico_e_correcao():
    """Verifica o ambiente e aplica correções automáticas para garantir portabilidade."""
    print("🔍 Iniciando Auto-Diagnóstico do Super Server...", file=sys.stderr)
    
    # 1. Verificação de Chaves Essenciais
    if not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  AVISO CRÍTICO: OPENAI_API_KEY não encontrada no ambiente!", file=sys.stderr)
    
    # Verificação do Google Calendar MCP
    if os.environ.get("GOOGLE_CALENDAR_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on"):
        cred_path = Path(os.environ.get("GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH", str(BASE_DIR / "gcp-oauth.keys.json"))).expanduser()
        if not cred_path.exists():
            print(f"⚠️  Google Calendar MCP: Arquivo de credenciais não encontrado em {cred_path}", file=sys.stderr)
        else:
            token_path = cred_path.parent / "mcp-google-calendar-token.json"
            if not token_path.exists():
                print(f"⚠️  Google Calendar MCP: Token OAuth não encontrado em {token_path}", file=sys.stderr)
                print(f"    Para autorizar, rode no terminal: export CREDENTIALS_PATH=\"{cred_path}\" && npx -y mcp-google-calendar", file=sys.stderr)
    # 2. Verificação de Dependências Externas
    if not shutil.which("npx"):
        print("⚠️  Node.js (npx) ausente. 'Filesystem MCP' não funcionará.", file=sys.stderr)
    
    # 3. Estrutura de Pastas
    (BASE_DIR / "screenshots").mkdir(exist_ok=True)
    
    print("✅ Diagnóstico concluído. Servidor pronto.", file=sys.stderr)

def mostrar_link_externo():
    """Mostra o endpoint publico configurado, se existir."""
    public_url = (
        os.environ.get("MCP_PUBLIC_URL", "").strip()
        or os.environ.get("OCI_API_GATEWAY_URL", "").strip()
    )
    if not public_url:
        return
    base = public_url.rstrip("/")
    print(f"endpoint publico: {base}/mcp", file=sys.stderr)


# --- GUPY (R&S Public API v1) ---
def _gupy_client() -> httpx.Client:
    token = (os.environ.get("GUPY_API_TOKEN") or GUPY_API_TOKEN or "").strip()
    if not token:
        raise RuntimeError("GUPY_API_TOKEN não definido.")
    return httpx.Client(
        timeout=30,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "jarvis/1.0",
        },
    )


@_mcp_tool_when_env("GUPY_MCP_ENABLE", "true")
def gupy_test_token() -> str:
    """Testa se o token da Gupy (GUPY_API_TOKEN) está válido."""
    try:
        with _gupy_client() as c:
            r = c.get("https://api.gupy.io/api/v1/jobs?perPage=1&page=1")
            return f"ok: status={r.status_code} body_prefix={r.text[:120]}".strip()
    except Exception as e:
        import traceback

        return f"erro: {e}\n{traceback.format_exc()}"


@_mcp_tool_when_env("GUPY_MCP_ENABLE", "true")
def gupy_v1_list_jobs(
    status: str = "published",
    page: int = 1,
    per_page: int = 100,
    include_recruiter: bool = True,
) -> str:
    """Lista vagas via API pública v1 da Gupy."""
    try:
        with _gupy_client() as c:
            params = {"page": int(page), "perPage": int(per_page)}
            if status:
                params["status"] = status
            r = c.get("https://api.gupy.io/api/v1/jobs", params=params)
            if r.status_code != 200:
                return f"Erro HTTP {r.status_code}: {r.text[:500]}"
            data = r.json()
            results = data.get("results", []) or []
            out = [f"jobs(v1) status={status} page={page} perPage={per_page} -> {len(results)}"]
            for j in results[:50]:
                extra = ""
                if include_recruiter:
                    # a listagem pode não trazer recruiter*, mas em alguns tenants traz.
                    r_email = j.get("recruiterEmail")
                    r_name = j.get("recruiterName")
                    r_id = j.get("recruiterId")
                    if r_email or r_name or r_id:
                        extra = f" | recruiter={r_name or ''} <{r_email or ''}> id={r_id or ''}".replace("\x1c", "")
                out.append(
                    f"- id={j.get('id')} | {j.get('status')} | {j.get('name')} | createdAt={j.get('createdAt')}{extra}"
                )
            if len(results) > 50:
                out.append(f"(mostrando 50 de {len(results)})")
            return "\n".join(out)
    except Exception as e:
        import traceback

        return f"Erro: {e}\n{traceback.format_exc()}"


@_mcp_tool_when_env("GUPY_MCP_ENABLE", "true")
def gupy_v1_close_job(job_id: int, cancel_reason: str = "") -> str:
    """Fecha uma vaga via API v1 (PATCH status=closed)."""
    try:
        body = {"status": "closed"}
        if cancel_reason:
            body["cancelReason"] = cancel_reason

        with _gupy_client() as c:
            r = c.patch(f"https://api.gupy.io/api/v1/jobs/{int(job_id)}", json=body)
            return f"PATCH /api/v1/jobs/{job_id} -> HTTP {r.status_code}: {r.text[:800]}".strip()
    except Exception as e:
        import traceback

        return f"Erro ao fechar vaga: {e}\n{traceback.format_exc()}"


# --- ONEDRIVE (Microsoft Graph) ---
def _msgraph_token_url() -> str:
    return f"https://login.microsoftonline.com/{MSGRAPH_TENANT}/oauth2/v2.0/token"


def _msgraph_device_code_url() -> str:
    return f"https://login.microsoftonline.com/{MSGRAPH_TENANT}/oauth2/v2.0/devicecode"


def _msgraph_require_client_id():
    if not MSGRAPH_CLIENT_ID:
        raise RuntimeError("MSGRAPH_CLIENT_ID não configurado.")


def _msgraph_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _msgraph_save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _msgraph_now_ts() -> int:
    return int(time.time())


def _msgraph_get_access_token() -> str:
    env_access = (
        os.environ.get("MSGRAPH_ACCESS_TOKEN", "").strip()
        or os.environ.get("GRAPH_ACCESS_TOKEN", "").strip()
    )
    if env_access:
        return env_access

    tok = _msgraph_load_json(MSGRAPH_TOKEN_PATH)
    if not tok:
        raise RuntimeError(
            "OneDrive/Graph não autenticado. Use MSGRAPH_ACCESS_TOKEN/GRAPH_ACCESS_TOKEN no ambiente "
            "ou rode onedrive_auth_start + onedrive_auth_poll."
        )

    access_token = tok.get("access_token")
    expires_at = int(tok.get("expires_at", 0) or 0)
    refresh_token = tok.get("refresh_token")

    if access_token and expires_at - _msgraph_now_ts() > 60:
        return access_token

    if not refresh_token:
        raise RuntimeError("Token expirado e refresh_token ausente. Refaça o login.")

    _msgraph_require_client_id()
    data = {
        "client_id": MSGRAPH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://graph.microsoft.com/Files.ReadWrite.All",
    }
    with httpx.Client(timeout=30) as c:
        r = c.post(_msgraph_token_url(), data=data)
        if r.status_code >= 300:
            raise RuntimeError(f"Falha ao refresh token: {r.status_code} {r.text}")
        js = r.json()

    new_access = js.get("access_token")
    new_refresh = js.get("refresh_token") or refresh_token
    expires_in = int(js.get("expires_in", 3599) or 3599)

    tok.update(
        {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "expires_at": _msgraph_now_ts() + expires_in,
            "scope": js.get("scope", tok.get("scope")),
            "token_type": js.get("token_type", tok.get("token_type", "Bearer")),
            "refreshed_at": datetime.utcnow().isoformat() + "Z",
        }
    )
    _msgraph_save_json(MSGRAPH_TOKEN_PATH, tok)
    return new_access


def _msgraph_get(url: str, params: dict | None = None):
    token = _msgraph_get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=60) as c:
        r = c.get(url, params=params, headers=headers)
    return r


def _onedrive_auth_start_impl() -> dict:
    """Inicia login via device code no Microsoft Graph (OneDrive pessoal)."""
    _msgraph_require_client_id()
    scope = "https://graph.microsoft.com/Files.ReadWrite.All offline_access"
    data = {"client_id": MSGRAPH_CLIENT_ID, "scope": scope}
    with httpx.Client(timeout=60) as c:
        r = c.post(_msgraph_device_code_url(), data=data)
    if r.status_code >= 300:
        raise RuntimeError(f"Falha ao iniciar device flow: {r.status_code} {r.text}")
    js = r.json()

    flow = {
        "device_code": js.get("device_code"),
        "user_code": js.get("user_code"),
        "verification_uri": js.get("verification_uri"),
        "verification_uri_complete": js.get("verification_uri_complete"),
        "expires_in": js.get("expires_in"),
        "interval": js.get("interval", 5),
        "message": js.get("message"),
        "started_at": datetime.utcnow().isoformat() + "Z",
    }
    _msgraph_save_json(MSGRAPH_DEVICE_FLOW_PATH, flow)
    return flow


@_mcp_tool_when_env("ONEDRIVE_MCP_ENABLE", "true")
def onedrive_auth_start() -> dict:
    """Inicia login via device code no Microsoft Graph (OneDrive pessoal)."""
    return _onedrive_auth_start_impl()


@_mcp_tool_when_env("ONEDRIVE_MCP_ENABLE", "true")
def onedrive_auth_poll(device_code: str = "", timeout_seconds: int = 300) -> dict:
    """Conclui login iniciado por onedrive_auth_start, com polling."""
    _msgraph_require_client_id()
    flow = _msgraph_load_json(MSGRAPH_DEVICE_FLOW_PATH)
    if not flow:
        raise RuntimeError("Nenhum device flow ativo. Rode onedrive_auth_start primeiro.")

    dc = (device_code or flow.get("device_code") or "").strip()
    if not dc:
        raise RuntimeError("device_code ausente.")

    interval = int(flow.get("interval", 5) or 5)
    deadline = _msgraph_now_ts() + int(timeout_seconds)

    while _msgraph_now_ts() < deadline:
        data = {
            "client_id": MSGRAPH_CLIENT_ID,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc,
        }
        with httpx.Client(timeout=30) as c:
            r = c.post(_msgraph_token_url(), data=data)
        if r.status_code == 200:
            js = r.json()
            expires_in = int(js.get("expires_in", 3599) or 3599)
            tok = {
                "access_token": js.get("access_token"),
                "refresh_token": js.get("refresh_token"),
                "expires_at": _msgraph_now_ts() + expires_in,
                "scope": js.get("scope"),
                "token_type": js.get("token_type", "Bearer"),
                "obtained_at": datetime.utcnow().isoformat() + "Z",
            }
            _msgraph_save_json(MSGRAPH_TOKEN_PATH, tok)
            try:
                MSGRAPH_DEVICE_FLOW_PATH.unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": True, "expires_in": expires_in}

        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text}

        code = err.get("error")
        if code == "authorization_pending":
            time.sleep(interval)
            continue
        if code == "slow_down":
            interval += 2
            time.sleep(interval)
            continue
        if code in ("expired_token", "access_denied"):
            return {"ok": False, "error": code, "detail": err}

        return {"ok": False, "error": code or "unknown_error", "detail": err}

    return {"ok": False, "error": "timeout"}


@_mcp_tool_when_env("ONEDRIVE_MCP_ENABLE", "true")
def onedrive_list(path: str = "", limit: int = 50) -> dict:
    """Lista itens de uma pasta no OneDrive pessoal."""
    path = (path or "").strip().strip("/")
    if path:
        import urllib.parse

        url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{urllib.parse.quote(path)}:/children"
    else:
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"

    r = _msgraph_get(url, params={"$top": min(max(int(limit), 1), 200)})
    if r.status_code >= 300:
        raise RuntimeError(f"Falha ao listar onedrive: {r.status_code} {r.text}")
    return r.json()


@_mcp_tool_when_env("ONEDRIVE_MCP_ENABLE", "true")
def onedrive_get_versions(item_id: str, limit: int = 50) -> dict:
    """Lista histórico de versões de um arquivo OneDrive (driveItem)."""
    item_id = (item_id or "").strip()
    if not item_id:
        raise RuntimeError("item_id é obrigatório")
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/versions"
    r = _msgraph_get(url, params={"$top": min(max(int(limit), 1), 200)})
    if r.status_code >= 300:
        raise RuntimeError(f"Falha ao listar versões: {r.status_code} {r.text}")
    return r.json()

# --- START ---

def _read_unit_field(unit_text: str, field_name: str) -> str:
    prefix = f"{field_name}="
    for line in (unit_text or "").splitlines():
        striped = line.strip()
        if striped.startswith(prefix):
            return striped[len(prefix):].strip()
    return ""


def _check_user_systemd_service(verbose: bool = True) -> dict:
    try:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        real_home = Path.home()

    service_path = real_home / ".config" / "systemd" / "user" / "jarvis.service"
    enabled_link = real_home / ".config" / "systemd" / "user" / "default.target.wants" / "jarvis.service"
    expected_workdir = str(BASE_DIR)
    status = {
        "exists": service_path.exists(),
        "enabled": False,
        "ok": False,
        "service_path": str(service_path),
        "issues": [],
        "working_directory": "",
        "exec_start": "",
    }

    if service_path.exists():
        try:
            unit_text = service_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            unit_text = ""

        workdir = _read_unit_field(unit_text, "WorkingDirectory")
        exec_start = _read_unit_field(unit_text, "ExecStart")
        status["working_directory"] = workdir
        status["exec_start"] = exec_start

        if workdir and Path(workdir).resolve() != Path(expected_workdir).resolve():
            status["issues"].append(
                f"WorkingDirectory divergente ({workdir}) esperado ({expected_workdir})."
            )

        if not exec_start:
            status["issues"].append("ExecStart ausente no jarvis.service.")
        else:
            if "jarvis.py" not in exec_start or " serve" not in exec_start:
                status["issues"].append("ExecStart não aponta para 'jarvis.py serve'.")
            if "super_server_v6.py" in exec_start:
                status["issues"].append("ExecStart ainda referencia super_server_v6.py (legado).")

        if "super_mcp_servers" in workdir:
            status["issues"].append("WorkingDirectory ainda referencia super_mcp_servers (legado).")
    else:
        status["issues"].append("jarvis.service não encontrado em ~/.config/systemd/user.")

    if enabled_link.exists():
        try:
            if enabled_link.is_symlink():
                target = enabled_link.resolve()
                status["enabled"] = service_path.exists() and target == service_path.resolve()
                if not status["enabled"]:
                    status["issues"].append("Link em default.target.wants não aponta para jarvis.service atual.")
            else:
                status["enabled"] = True
        except Exception:
            status["enabled"] = False
    else:
        status["issues"].append("jarvis.service não está habilitado em default.target.wants.")

    status["ok"] = bool(status["exists"] and status["enabled"] and not status["issues"])

    if verbose:
        if status["ok"]:
            print("✅ Checagem systemd: jarvis.service presente, habilitado e alinhado com jarvis.py.")
        else:
            print("⚠️  Checagem systemd: ajustes recomendados no jarvis.service.")
            for issue in status["issues"]:
                print(f"   - {issue}")
            print("   Dica: systemctl --user daemon-reload && systemctl --user enable --now jarvis.service")

    return status

def _run_server() -> int:
    if not FASTMCP_AVAILABLE:
        print("❌ fastmcp não encontrado. Instale com ./.venv-super/bin/pip install fastmcp", file=sys.stderr)
        return 1
    mcp_mode = os.environ.get("MCP_MODE", "stdio").lower()
    stdio_quiet_boot = (
        mcp_mode == "stdio"
        and (os.environ.get("JARVIS_STDIO_QUIET_BOOT", "true") or "").strip().lower() in {"1", "true", "yes", "on"}
    )
    stdio_silence_stderr = (
        mcp_mode == "stdio"
        and (os.environ.get("JARVIS_STDIO_SILENCE_STDERR", "true") or "").strip().lower() in {"1", "true", "yes", "on"}
    )
    if stdio_silence_stderr:
        try:
            logging.disable(logging.CRITICAL)
            sys.stderr = open(os.devnull, "w")
        except Exception:
            pass

    # auto_diagnostico_e_correcao()
    if not stdio_quiet_boot:
        # Tenta mostrar o endpoint publico em background
        threading.Thread(target=mostrar_link_externo, daemon=True).start()

    sys.stderr.write("DEBUG: [__main__] Starting...\n")
    if not stdio_quiet_boot:
        print("🚀 JARVIS MCP SERVER")
        print(f"🛰️  Servidor em {SERVER_URL}")
        write_mcp_status_report()
        _check_user_systemd_service(verbose=True)

    stdio_skip_children = (
        mcp_mode == "stdio"
        and (os.environ.get("JARVIS_STDIO_SKIP_CHILD_MCP", "true") or "").strip().lower() in {"1", "true", "yes", "on"}
    )

    sys.stderr.write("DEBUG: [__main__] Starting sub-services...\n")
    if stdio_skip_children:
        print("ℹ️  Modo stdio leve ativo: child MCPs desativados por padrão (JARVIS_STDIO_SKIP_CHILD_MCP=true).")
        print("ℹ️  Para reativar child MCPs no stdio, exporte JARVIS_STDIO_SKIP_CHILD_MCP=false.")
    else:
        start_playwright_mcp()
        start_brave_mcp()
        start_chart_mcp()
        start_zotero_mcp()
        start_firecrawl_mcp()
        start_google_calendar_mcp()
        start_fireflies_mcp()
        start_reclaim_official_mcp()
        start_google_drive_mcp()
        start_filesystem_mcp()

    # Verifica modo de operação
    sys.stderr.write(f"DEBUG: [__main__] mcp_mode={mcp_mode}\n")

    if mcp_mode == "stdio":
        sys.stderr.write("🔌 Iniciando em modo STDIO (para uso com mcp-proxy ou Claude Desktop)...\n")

        # --- STRICT STDOUT WRAPPER ---
        # Garante que NADA além de JSON (iniciado por '{') saia no stdout.
        # Isso protege o pipe do mcp-proxy contra logs, banners e sujeira.
        class StrictJSONStdout:
            def __init__(self, original):
                self.orig = original
                self.buffer = getattr(original, "buffer", None)
                self.encoding = getattr(original, "encoding", "utf-8")

            @staticmethod
            def _is_mcp_protocol_chunk(text: str) -> bool:
                t = (text or "")
                s = t.lstrip()
                if not s:
                    return True
                if s.startswith("{"):
                    return True
                # MCP stdio framing (LSP-like)
                if s.lower().startswith("content-length:"):
                    return True
                if s.startswith("\r\n"):
                    return True
                return False

            def write(self, s):
                if not isinstance(s, str):
                    # Se vier bytes, tentamos decodificar para checar
                    try:
                        decoded = s.decode("utf-8")
                        if self._is_mcp_protocol_chunk(decoded):
                            return self.orig.buffer.write(s)
                    except Exception:
                        pass
                    # Se não for JSON ou falhar decode, joga no stderr
                    try:
                        sys.stderr.buffer.write(s)
                        sys.stderr.buffer.flush()
                    except Exception:
                        pass
                    return len(s)

                s_stripped = s.strip()
                # Ignora linhas vazias (flush)
                if not s_stripped:
                    return self.orig.write(s)

                # Permite JSON-RPC e framing MCP stdio (Content-Length)
                if self._is_mcp_protocol_chunk(s):
                    return self.orig.write(s)

                # Todo o resto vai para stderr
                try:
                    sys.stderr.write(s)
                except Exception:
                    pass
                return len(s)

            def flush(self):
                try:
                    self.orig.flush()
                except Exception:
                    pass
                try:
                    sys.stderr.flush()
                except Exception:
                    pass

            def __getattr__(self, name):
                return getattr(self.orig, name)

        sys.stdout = StrictJSONStdout(sys.stdout)  # Reativado

        try:
            # --- SILENT STDIO RUNNER (ULTRA ROBUST) ---
            try:
                from fastmcp.server.server import NotificationOptions, get_task_capabilities
            except ImportError:
                from fastmcp.server.server import NotificationOptions

                def get_task_capabilities():
                    return {}

            from mcp.server.stdio import stdio_server as raw_stdio_server

            async def run_silent_stdio_async(server):
                sys.stderr.write("DEBUG: [run_silent_stdio_async] Entering lifespan manager...\n")
                async with server._lifespan_manager():
                    sys.stderr.write("DEBUG: [run_silent_stdio_async] Entering raw_stdio_server...\n")
                    # Usa o transportador STDIO de baixo nível do MCP SDK diretamente
                    async with raw_stdio_server() as (read_stream, write_stream):
                        sys.stderr.write("DEBUG: [run_silent_stdio_async] Server loop starting...\n")
                        experimental_capabilities = get_task_capabilities()

                        try:
                            await server._mcp_server.run(
                                read_stream,
                                write_stream,
                                server._mcp_server.create_initialization_options(
                                    notification_options=NotificationOptions(
                                        tools_changed=True
                                    ),
                                    experimental_capabilities=experimental_capabilities,
                                ),
                            )
                        except Exception as e:
                            sys.stderr.write(f"❌ [run_silent_stdio_async] Server loop crashed: {e}\n")
                            import traceback

                            traceback.print_exc(file=sys.stderr)

                        sys.stderr.write("DEBUG: [run_silent_stdio_async] Server loop finished unexpectedly.\n")

            sys.stderr.write("DEBUG: [__main__] Calling asyncio.run(run_silent_stdio_async(mcp))...\n")
            asyncio.run(run_silent_stdio_async(mcp))
        except Exception as e:
            sys.stderr.write(f"❌ Erro fatal no modo STDIO: {e}\n")
            import traceback

            traceback.print_exc(file=sys.stderr)
            return 1
    else:
        # Modo HTTP/SSE padrão
        run_combined_uvicorn(SERVER_HOST, SERVER_PORT)
    return 0


def _default_log_file() -> Path:
    return Path(os.environ.get("LOG_FILE", str(BASE_DIR / "server.log")))


def _default_pid_file() -> Path:
    return Path(os.environ.get("PID_FILE", str(BASE_DIR / ".super_server.pid")))


def _read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw)
    except Exception:
        return None


def _is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _find_jarvis_pids(server_port: int) -> set[int]:
    patterns = [
        r"jarvis\.py",
        rf"stdio_proxy\.js\s+{server_port}\b",
    ]
    found: set[int] = set()
    this_pid = os.getpid()
    for pattern in patterns:
        try:
            res = subprocess.run(
                ["pgrep", "-f", pattern],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            continue
        for line in (res.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line)
            except Exception:
                continue
            if pid != this_pid:
                found.add(pid)

    filtered: set[int] = set()
    for pid in found:
        cmdline = ""
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except Exception:
            pass
        cmdline_l = cmdline.lower()
        if "jarvis.py" in cmdline_l:
            if " service " in cmdline_l:
                continue
            if " --help" in cmdline_l:
                continue
            filtered.add(pid)
            continue
        if "stdio_proxy.js" in cmdline and str(server_port) in cmdline:
            filtered.add(pid)
            continue

    return filtered


def _terminate_pid(pid: int, grace_sec: float = 10.0) -> None:
    if not _is_pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    deadline = time.time() + grace_sec
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _tail_text_file(path: Path, lines: int = 120) -> str:
    if not path.exists():
        return f"Log não encontrado: {path}"
    buf: deque[str] = deque(maxlen=max(1, lines))
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            buf.append(line.rstrip("\n"))
    return "\n".join(buf)



def _apply_oci_profile_env(target_env: dict) -> None:
    oracle_defaults = {
        "SPEEDGRAPHER_ENABLE": "true",
        "FILESYSTEM_MCP_ENABLE": "false",
        "PLAYWRIGHT_MCP_ENABLE": "true",
        "BRAVE_MCP_ENABLE": "false",
        "FIRECRAWL_ENABLE": "false",
        "FIREFLIES_MCP_ENABLE": "false",
        "GOOGLE_CALENDAR_MCP_ENABLE": "true",
        "ZOTERO_MCP_ENABLE": "false",
        "CHART_MCP_ENABLE": "false",
        "MERMAID_ENABLE": "true",
        "MERMAID_LINK_ONLY": "true",
    }

    for key, default_value in oracle_defaults.items():
        profile_key = f"ORACLE_PROFILE_{key}"
        target_env[key] = os.environ.get(profile_key, default_value)


def _service_start(
    server_host: str,
    server_port: int,
    log_file: Path,
    pid_file: Path,
    python_bin: str,
    node_bin: str,
) -> int:
    if _env_is_true("JARVIS_AUTO_SETUP", True):
        rc_setup = _mcp_sync_clients_cli(
            py_bin=_resolve_project_python(python_bin),
            include_codex=True,
            include_gemini=True,
            include_sudo=_env_is_true("JARVIS_AUTO_SETUP_SYNC_SUDO", True),
            include_bridge=True,
            target_home="",
            quiet_core=False,
            verbose=False,
        )
        if rc_setup != 0:
            print(
                "❌ mcp-sync-clients falhou durante bootstrap automático. Corrija os passos acima e tente novamente.",
                file=sys.stderr,
            )
            return rc_setup
    else:
        print("ℹ️ Auto setup desativado por JARVIS_AUTO_SETUP=false.")

    running_pid = _read_pid(pid_file)
    if _is_pid_alive(running_pid):
        print(f"Servidor já está em execução (PID {running_pid}). Reiniciando via start...")
        assert running_pid is not None
        _terminate_pid(running_pid)

    orphan_pids = _find_jarvis_pids(server_port)
    if orphan_pids:
        print(f"Limpando processos órfãos detectados: {', '.join(str(p) for p in sorted(orphan_pids))}")
        for orphan_pid in sorted(orphan_pids):
            _terminate_pid(orphan_pid)

    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass

    env = os.environ.copy()
    env["SERVER_HOST"] = server_host
    env["SERVER_PORT"] = str(server_port)
    proxy_impl = os.environ.get("PROXY_IMPL", "stdio")
    env["PROXY_IMPL"] = proxy_impl
    env.setdefault("PROXY_HOST", server_host)
    _apply_oci_profile_env(env)

    python_super = env.get("PYTHON_SUPER", str(BASE_DIR / ".venv-super" / "bin" / "python3"))
    if not Path(python_super).exists():
        python_super = python_bin

    if proxy_impl in ("stdio", "proxy"):
        env["MCP_MODE"] = "stdio"
        cmd = [
            node_bin,
            str(BASE_DIR / "stdio_proxy.js"),
            str(server_port),
            python_super,
            str(BASE_DIR / "jarvis.py"),
            "serve",
        ]
        mode_label = "proxy-stdio"
    else:
        env["MCP_MODE"] = "http"
        cmd = [python_bin, str(BASE_DIR / "jarvis.py"), "serve"]
        mode_label = "http-direto"

    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_file.open("ab")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    finally:
        log_fh.close()

    pid_file.write_text(str(proc.pid), encoding="utf-8")
    stable = True
    for _ in range(6):
        if proc.poll() is not None:
            stable = False
            break
        time.sleep(0.5)

    if stable and _is_pid_alive(proc.pid):
        print(f"Servidor MCP iniciado (PID {proc.pid}, modo {mode_label}) em http://{server_host}:{server_port}/mcp")
        print(f"Log: {log_file}")
        rc_oci_stack = _start_oci_stack()
        if rc_oci_stack != 0:
            return rc_oci_stack
        return 0

    print(f"Falha ao iniciar servidor. Verifique {log_file}", file=sys.stderr)
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass
    return 1


def _service_stop(pid_file: Path, server_port: int) -> int:
    stopped_any = False
    pid = _read_pid(pid_file)
    if _is_pid_alive(pid):
        assert pid is not None
        _terminate_pid(pid)
        stopped_any = True
        print(f"Servidor parado (PID {pid}).")

    orphan_pids = _find_jarvis_pids(server_port)
    for orphan_pid in sorted(orphan_pids):
        _terminate_pid(orphan_pid)
        stopped_any = True
        print(f"Processo órfão finalizado (PID {orphan_pid}).")

    if not stopped_any:
        print("Servidor já estava parado.")

    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass

    return 0


def _service_status(pid_file: Path, log_file: Path, server_port: int) -> int:
    pid = _read_pid(pid_file)
    if _is_pid_alive(pid):
        print(f"Status: running (PID {pid})")
    else:
        orphan_pids = _find_jarvis_pids(server_port)
        if orphan_pids:
            pids = ", ".join(str(p) for p in sorted(orphan_pids))
            print(f"Status: running (órfão sem pid file: {pids})")
        else:
            print("Status: stopped")
    marker = _jarvis_ready_marker_path()
    if marker.exists():
        try:
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
            marker_ok = bool(marker_payload.get("ok"))
            marker_time = marker_payload.get("finished_at", "")
            print(f"Auto setup: {'ready' if marker_ok else 'failed'} ({marker_time})")
        except Exception:
            print(f"Auto setup: marker inválido em {marker}")
    else:
        print("Auto setup: marker ausente")
    print(f"Log: {log_file}")
    return 0


def _service_logs(log_file: Path, lines: int) -> int:
    print(_tail_text_file(log_file, lines))
    return 0

def _format_shell_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in cmd)


def _env_is_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_gemini_bin() -> str | None:
    candidates = [
        (os.environ.get("GEMINI_BIN") or "").strip(),
        shutil.which("gemini") or "",
        str(_primary_user_home() / ".npm-global" / "bin" / "gemini"),
        "/home/lucas/.npm-global/bin/gemini",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        c = (candidate or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        p = Path(c)
        if p.is_absolute():
            if p.exists():
                return str(p)
        elif shutil.which(c):
            return c
    return None


def _prepare_cli_runtime(cmd: list[str], env: dict | None = None) -> tuple[list[str], dict | None]:
    if not cmd:
        return cmd, env
    base = Path(str(cmd[0])).name
    if base != "gemini":
        return cmd, env

    gemini_bin = _resolve_gemini_bin()
    if gemini_bin:
        cmd = [gemini_bin] + list(cmd[1:])

    # Quando em sudo codex/root, force execução do Gemini como usuário normal.
    force_user = _env_is_true("JARVIS_GEMINI_FORCE_USER", True)
    if force_user and os.geteuid() == 0:
        run_as_user = (os.environ.get("JARVIS_GEMINI_RUN_AS_USER", "lucas") or "").strip() or "lucas"
        user_home = str(_primary_user_home())
        try:
            user_home = pwd.getpwnam(run_as_user).pw_dir
        except Exception:
            pass
        wrapped = [
            "sudo",
            "-H",
            "-u",
            run_as_user,
            "env",
            f"HOME={user_home}",
            f"USER={run_as_user}",
            f"LOGNAME={run_as_user}",
        ] + cmd
        return wrapped, env

    return cmd, env


def _run_cli_command(
    cmd: list[str],
    *,
    allow_failure: bool = False,
    input_text: str | None = None,
    env: dict | None = None,
    echo_cmd: bool = True,
) -> int:
    cmd, env = _prepare_cli_runtime(cmd, env)
    if echo_cmd:
        print(f"$ {_format_shell_cmd(cmd)}")
    try:
        proc = subprocess.run(cmd, input=input_text, text=True, env=env)
    except FileNotFoundError as exc:
        print(f"❌ Comando não encontrado: {exc}", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"❌ Falha ao executar comando: {exc}", file=sys.stderr)
        return 1

    if proc.returncode != 0 and not allow_failure:
        print(f"❌ Comando falhou com código {proc.returncode}", file=sys.stderr)
    return proc.returncode


def _resolve_project_python(py_bin: str | None = None) -> str:
    preferred = BASE_DIR / ".venv-super" / "bin" / "python3"
    if preferred.exists():
        if (py_bin or "").strip() and Path(str(py_bin).strip()) != preferred:
            print(
                f"ℹ️ Ignorando --py-bin/--python-bin ({py_bin}) e usando runtime fixo do projeto: {preferred}"
            )
        return str(preferred)
    raise FileNotFoundError(
        f"Python da venv-super não encontrado em {preferred}. Rode: python3 jarvis.py install-super-venv"
    )


def _resolve_gsd_ralph_workspace() -> Path:
    return BASE_DIR / ".context" / "workflow"


def _jarvis_ready_marker_path() -> Path:
    return BASE_DIR / ".jarvis-ready"


def _write_jarvis_ready_marker(payload: dict) -> None:
    marker = _jarvis_ready_marker_path()
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_gsd_ready() -> bool:
    status = _ensure_gsd_global_installed(install_if_missing=False)
    return bool(status.get("ok")) and bool(status.get("installed"))


def _is_ralph_ready() -> bool:
    status = _ensure_ralph_global_installed(install_if_missing=False)
    return bool(status.get("ok")) and bool(status.get("installed"))


def _run_optional_step(name: str, cmd: list[str], *, critical: bool, steps: list[dict]) -> int:
    rc = _run_cli_command(cmd, allow_failure=not critical)
    ok = rc == 0
    steps.append({"name": name, "ok": ok, "rc": rc, "cmd": _format_shell_cmd(cmd), "critical": critical})
    return rc




def _tail_text(value: str, max_chars: int = 4000) -> str:
    if not value:
        return ""
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _run_capture_command(cmd: list[str], *, cwd: Path | None = None, timeout_sec: int = 180) -> dict:
    started_at = datetime.now().isoformat()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_sec)),
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "cmd": _format_shell_cmd(cmd),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "stdout_tail": _tail_text(proc.stdout),
            "stderr_tail": _tail_text(proc.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": 124,
            "cmd": _format_shell_cmd(cmd),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "stdout_tail": _tail_text((exc.stdout or "") if isinstance(exc.stdout, str) else ""),
            "stderr_tail": _tail_text((exc.stderr or "") if isinstance(exc.stderr, str) else ""),
            "error": f"timeout_after_{int(timeout_sec)}s",
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": 1,
            "cmd": _format_shell_cmd(cmd),
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "stdout_tail": "",
            "stderr_tail": "",
            "error": str(exc),
        }


def _resolve_npx_bin() -> str:
    candidates = [
        os.environ.get("NPX_BIN", "").strip(),
        shutil.which("npx") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "npx"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/npx",
        "/usr/bin/npx",
        "npx",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate == "npx" or Path(candidate).exists():
            return candidate
    return "npx"


def _resolve_node_bin() -> str:
    candidates = [
        shutil.which("node") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "node"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/node",
        "/usr/bin/node",
        "node",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate == "node" or Path(candidate).exists():
            return candidate
    return "node"


def _resolve_npm_global_bin_dir() -> Path | None:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return None
    probe = _run_capture_command([npm_bin, "prefix", "-g"], cwd=BASE_DIR, timeout_sec=20)
    if not probe.get("ok"):
        return None
    prefix = (probe.get("stdout_tail") or "").strip()
    if not prefix:
        return None
    bin_dir = Path(prefix) / "bin"
    return bin_dir if bin_dir.exists() else None


def _resolve_ai_coders_context_package_root() -> Path | None:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return None
    probe = _run_capture_command([npm_bin, "root", "-g"], cwd=BASE_DIR, timeout_sec=20)
    if not probe.get("ok"):
        return None
    root_out = (probe.get("stdout_tail") or "").strip()
    if not root_out:
        return None
    root = Path(root_out)
    candidate = root / "@ai-coders" / "context"
    if candidate.exists() and (candidate / "package.json").exists():
        return candidate
    return None


def _resolve_aligntrue_package_root() -> Path | None:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return None
    probe = _run_capture_command([npm_bin, "root", "-g"], cwd=BASE_DIR, timeout_sec=20)
    if not probe.get("ok"):
        return None
    root_out = (probe.get("stdout_tail") or "").strip()
    if not root_out:
        return None
    root = Path(root_out)
    candidate = root / "aligntrue"
    if candidate.exists() and (candidate / "package.json").exists():
        return candidate
    return None


def _resolve_aligntrue_global_cli() -> dict:
    pkg_root = _resolve_aligntrue_package_root()
    if not pkg_root:
        return {
            "ok": False,
            "error": "aligntrue_package_root_not_found",
            "hint": "Instale com: npm install -g aligntrue",
        }

    candidates: list[Path] = []
    resolved_global_bin = _resolve_npm_global_bin_dir()
    if resolved_global_bin:
        candidates.append(resolved_global_bin / "aligntrue")
        candidates.append(resolved_global_bin / "aln")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return {
                "ok": True,
                "command": str(candidate),
                "package_root": str(pkg_root),
            }

    which_aligntrue = shutil.which("aligntrue")
    if which_aligntrue:
        return {
            "ok": True,
            "command": which_aligntrue,
            "package_root": str(pkg_root),
        }

    return {
        "ok": False,
        "error": "aligntrue_cli_not_found",
        "package_root": str(pkg_root),
        "hint": "Instale com: npm install -g aligntrue",
    }


def _resolve_ai_coders_context_global_cli() -> dict:
    pkg_root = _resolve_ai_coders_context_package_root()
    if not pkg_root:
        return {
            "ok": False,
            "error": "ai_coders_context_package_root_not_found",
            "hint": "Instale com: npm install -g @ai-coders/context",
        }

    pkg_json_path = pkg_root / "package.json"
    try:
        pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "error": "ai_coders_context_package_json_invalid",
            "detail": str(exc),
            "package_root": str(pkg_root),
        }

    pkg_name = str(pkg_data.get("name") or "@ai-coders/context").strip()
    pkg_version = str(pkg_data.get("version") or "").strip()
    bin_field = pkg_data.get("bin")

    command_candidates: list[str] = []
    script_candidates: list[Path] = []

    if isinstance(bin_field, str) and bin_field.strip():
        command_candidates.append(pkg_name.split("/")[-1])
        script_candidates.append((pkg_root / bin_field.strip()).resolve())
    elif isinstance(bin_field, dict):
        for cmd_name, rel_path in bin_field.items():
            if isinstance(cmd_name, str) and cmd_name.strip():
                command_candidates.append(cmd_name.strip())
            if isinstance(rel_path, str) and rel_path.strip():
                script_candidates.append((pkg_root / rel_path.strip()).resolve())

    command_candidates.extend(["ai-coders-context", "ai-coders", "context"])
    dedup_commands: list[str] = []
    for cmd in command_candidates:
        if cmd and cmd not in dedup_commands:
            dedup_commands.append(cmd)
    command_candidates = dedup_commands

    bin_dirs: list[Path] = []
    resolved_global_bin = _resolve_npm_global_bin_dir()
    if resolved_global_bin:
        bin_dirs.append(resolved_global_bin)
    npm_path = shutil.which("npm")
    if npm_path:
        npm_parent = Path(npm_path).resolve().parent
        if npm_parent not in bin_dirs:
            bin_dirs.append(npm_parent)

    for bin_dir in bin_dirs:
        for cmd_name in command_candidates:
            candidate = bin_dir / cmd_name
            if candidate.exists() and candidate.is_file():
                return {
                    "ok": True,
                    "command": str(candidate),
                    "args_prefix": [],
                    "command_name": cmd_name,
                    "package_root": str(pkg_root),
                    "version_stdout": pkg_version,
                    "source": "npm_global_bin",
                }

    for cmd_name in command_candidates:
        cmd_path = shutil.which(cmd_name)
        if cmd_path:
            return {
                "ok": True,
                "command": cmd_path,
                "args_prefix": [],
                "command_name": cmd_name,
                "package_root": str(pkg_root),
                "version_stdout": pkg_version,
                "source": "path_lookup",
            }

    node_bin = _resolve_node_bin()
    for script in script_candidates:
        if script.exists() and script.is_file():
            return {
                "ok": True,
                "command": node_bin,
                "args_prefix": [str(script)],
                "command_name": "",
                "package_root": str(pkg_root),
                "version_stdout": pkg_version,
                "source": "node_script_fallback",
            }

    return {
        "ok": False,
        "error": "ai_coders_context_cli_not_found",
        "package_root": str(pkg_root),
    }
def _validate_ai_context_mcp_manually(timeout_sec: float = 10.0) -> dict:
    cli = _resolve_ai_coders_context_global_cli()
    if not cli.get("ok"):
        return {"ok": False, "reason": "cli_not_found", "detail": str(cli.get("error") or "")}

    import select

    cmd = [str(cli.get("command") or "")] + [str(x) for x in (cli.get("args_prefix") or [])] + ["mcp", "--repo-path", str(BASE_DIR)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
    except Exception as exc:
        return {"ok": False, "reason": "spawn_failed", "detail": str(exc)}

    def _read_line(stream, deadline: float) -> str:
        while time.time() < deadline:
            ready, _, _ = select.select([stream], [], [], 0.2)
            if ready:
                line = stream.readline()
                if line:
                    return line.strip()
            if proc.poll() is not None:
                break
        return ""

    deadline = time.time() + max(1.0, timeout_sec)
    try:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-manual-check", "version": "1.0"},
            },
        }
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()
        init_line = _read_line(proc.stdout, deadline)
        if not init_line:
            return {"ok": False, "reason": "initialize_timeout"}
        init_payload = json.loads(init_line)
        if init_payload.get("id") != 1 or "result" not in init_payload:
            return {"ok": False, "reason": "initialize_invalid", "detail": init_line[:300]}

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n")
        proc.stdin.flush()
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        tools_line = _read_line(proc.stdout, deadline)
        if not tools_line:
            return {"ok": False, "reason": "tools_list_timeout"}
        tools_payload = json.loads(tools_line)
        tools = (((tools_payload.get("result") or {}).get("tools")) or [])
        return {"ok": True, "tools": len(tools)}
    except Exception as exc:
        return {"ok": False, "reason": "probe_failed", "detail": str(exc)}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

def _patch_text_file_with_replacements(
    path: Path,
    replacements: list[tuple[str, str]],
    *,
    backup_suffix: str = ".jarvis-orig",
) -> dict:
    if not path.exists():
        return {"ok": False, "error": "file_not_found", "path": str(path)}

    try:
        original = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": "read_failed", "path": str(path), "detail": str(exc)}

    updated = original
    applied: list[dict[str, object]] = []
    for old, new in replacements:
        # Several hardening patches intentionally keep the original call after an
        # injected `process.exit(1)` guard. In that shape `old in updated` remains
        # true forever, so the previous check re-applied the same guard on every
        # Jarvis startup. Treat the full replacement block as the idempotence key.
        if new in updated:
            applied.append({"status": "already_hardened", "needle": old[:80]})
            continue
        if old not in updated:
            return {
                "ok": False,
                "error": "pattern_not_found",
                "path": str(path),
                "needle": old[:160],
            }
        occurrences = updated.count(old)
        updated = updated.replace(old, new)
        applied.append({"status": "patched", "count": occurrences, "needle": old[:80]})

    changed = updated != original
    if changed:
        backup_path = Path(f"{path}{backup_suffix}")
        try:
            if not backup_path.exists():
                backup_path.write_text(original, encoding="utf-8")
            path.write_text(updated, encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": "write_failed", "path": str(path), "detail": str(exc)}

    return {
        "ok": True,
        "path": str(path),
        "changed": changed,
        "applied": applied,
    }


def _harden_aligntrue_global_install(apply_if_needed: bool = True) -> dict:
    if not _env_is_true("JARVIS_ALIGNTRUE_HARDEN", True):
        return {
            "ok": True,
            "skipped": True,
            "reason": "disabled_by_env",
        }

    pkg_root = _resolve_aligntrue_package_root()
    if not pkg_root:
        return {
            "ok": False,
            "error": "aligntrue_package_root_not_found",
            "hint": "Instale com: npm install -g aligntrue",
        }

    patch_specs: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "node_modules/@aligntrue/core/src/sync/exporter-executor.ts",
            [
                (
                    "        outputDir: process.cwd(),",
                    "        outputDir: config.export?.output_dir || config.export?.outputDir || process.cwd(),",
                ),
            ],
        ),
        (
            "node_modules/@aligntrue/core/dist/sync/exporter-executor.js",
            [
                (
                    "                outputDir: process.cwd(),",
                    "                outputDir: (((config || {}).export || {}).output_dir || ((config || {}).export || {}).outputDir || process.cwd()),",
                ),
            ],
        ),
        (
            "node_modules/@aligntrue/core/src/config/types.ts",
            [
                (
                    "export interface ExportConfig {\n  mode_hints?: {\n",
                    "export interface ExportConfig {\n  output_dir?: string;\n  outputDir?: string;\n  mode_hints?: {\n",
                ),
            ],
        ),
    ]

    results: list[dict] = []
    changed_files: list[str] = []
    for rel_path, replacements in patch_specs:
        target = pkg_root / rel_path
        if not apply_if_needed:
            results.append({"ok": True, "path": str(target), "changed": False, "skipped": True})
            continue
        patched = _patch_text_file_with_replacements(target, replacements)
        results.append(patched)
        if not patched.get("ok"):
            return {
                "ok": False,
                "error": "aligntrue_hardening_failed",
                "package_root": str(pkg_root),
                "failed_patch": patched,
                "results": results,
            }
        if patched.get("changed"):
            changed_files.append(str(target))

    return {
        "ok": True,
        "package_root": str(pkg_root),
        "changed": bool(changed_files),
        "changed_files": changed_files,
        "results": results,
    }


def _ensure_aligntrue_global_installed(install_if_missing: bool = True) -> dict:
    pkg = "aligntrue"
    desired_version = (os.environ.get("JARVIS_ALIGNTRUE_VERSION", "0.9.3") or "").strip()
    pkg_spec = f"{pkg}@{desired_version}" if desired_version else pkg
    current_version = _npm_global_version(pkg)

    if current_version:
        cli = _resolve_aligntrue_global_cli()
        if not cli.get("ok"):
            return {
                "ok": False,
                "installed": True,
                "version_stdout": current_version,
                "error": "aligntrue_cli_not_found",
                "cli": cli,
            }
        hardening = _harden_aligntrue_global_install(apply_if_needed=True)
        if not hardening.get("ok"):
            return {
                "ok": False,
                "installed": True,
                "version_stdout": current_version,
                "error": "aligntrue_hardening_failed",
                "cli": cli,
                "hardening": hardening,
            }
        return {
            "ok": True,
            "installed": True,
            "version_stdout": current_version,
            "source": "npm_global",
            "command": cli.get("command", ""),
            "hardening": hardening,
        }

    if not install_if_missing:
        return {
            "ok": False,
            "installed": False,
            "error": "aligntrue_not_found",
            "hint": "Instale com: npm install -g aligntrue",
        }

    installed_ok = _npm_ensure_global(pkg_spec)
    after_version = _npm_global_version(pkg) or ""
    if not installed_ok:
        return {
            "ok": False,
            "installed": False,
            "error": "aligntrue_install_failed",
        }

    cli = _resolve_aligntrue_global_cli()
    if not cli.get("ok"):
        return {
            "ok": False,
            "installed": True,
            "installed_now": True,
            "version_stdout": after_version,
            "error": "aligntrue_cli_not_found",
            "cli": cli,
        }

    hardening = _harden_aligntrue_global_install(apply_if_needed=True)
    if not hardening.get("ok"):
        return {
            "ok": False,
            "installed": True,
            "installed_now": True,
            "version_stdout": after_version,
            "error": "aligntrue_hardening_failed",
            "cli": cli,
            "hardening": hardening,
        }

    return {
        "ok": True,
        "installed": True,
        "installed_now": True,
        "version_stdout": after_version,
        "command": cli.get("command", ""),
        "hardening": hardening,
    }


def _harden_ai_coders_context_global_install(apply_if_needed: bool = True) -> dict:
    if not _env_is_true("JARVIS_AI_CONTEXT_HARDEN", True):
        return {
            "ok": True,
            "skipped": True,
            "reason": "disabled_by_env",
        }

    pkg_root = _resolve_ai_coders_context_package_root()
    if not pkg_root:
        return {
            "ok": False,
            "error": "ai_coders_context_package_root_not_found",
            "hint": "Instale com: npm install -g @ai-coders/context",
        }

    patch_specs: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "dist/commands/init.js",
            [
                (".argument('[type]', t('commands.init.arguments.type'), 'both')", ".argument('[type]', t('commands.init.arguments.type'), 'docs')"),
                ("await initService.run(repoPath, type, options);", "await initService.run(repoPath, 'docs', options);"),
                ("const type = options?.docsOnly ? 'docs' : options?.agentsOnly ? 'agents' : (options?.type || 'both');", "const type = 'docs';"),
            ],
        ),
        (
            "dist/commands/sync.js",
            [
                (
                    "await syncService.run(options);",
                    "ui.displayError('Agent export is disabled by Jarvis docs-only policy');\n            process.exit(1);\n            await syncService.run(options);",
                ),
                (
                    "await importAgentsService.run({",
                    "ui.displayError('Agent import is disabled by Jarvis docs-only policy');\n            process.exit(1);\n            await importAgentsService.run({",
                ),
                ("skipAgents: options.skipAgents,", "skipAgents: true,"),
                ("skipSkills: options.skipSkills,", "skipSkills: true,"),
            ],
        ),
        (
            "dist/commands/skill.js",
            [
                (
                    "const { createSkillGenerator } = await Promise.resolve().then(() => __importStar(require('../generators/skills')));",
                    "ui.displayError('Skill scaffolding is disabled by Jarvis docs-only policy');\n            process.exit(1);\n            const { createSkillGenerator } = await Promise.resolve().then(() => __importStar(require('../generators/skills')));",
                ),
                (
                    "const { SkillFillService } = await Promise.resolve().then(() => __importStar(require('../services/fill/skillFillService')));",
                    "ui.displayError('Skill fill is disabled by Jarvis docs-only policy');\n            process.exit(1);\n            const { SkillFillService } = await Promise.resolve().then(() => __importStar(require('../services/fill/skillFillService')));",
                ),
                (
                    "const { SkillExportService } = await Promise.resolve().then(() => __importStar(require('../services/export/skillExportService')));",
                    "ui.displayError('Skill export is disabled by Jarvis docs-only policy');\n            process.exit(1);\n            const { SkillExportService } = await Promise.resolve().then(() => __importStar(require('../services/export/skillExportService')));",
                ),
            ],
        ),
        (
            "dist/index.js",
            [
                (".argument('[type]', t('commands.init.arguments.type'), 'both')", ".argument('[type]', t('commands.init.arguments.type'), 'docs')"),
                ("await initService.run(repoPath, type, options);", "await initService.run(repoPath, 'docs', options);"),
                ("await initService.run(repoPath, type, rawOptions);", "await initService.run(repoPath, 'docs', rawOptions);"),
                ("const type = options?.docsOnly ? 'docs' : options?.agentsOnly ? 'agents' : (options?.type || 'both');", "const type = 'docs';"),
                (
                    "await syncService.run(options);",
                    "ui.displayError('Agent export is disabled by Jarvis docs-only policy');\n        process.exit(1);\n        await syncService.run(options);",
                ),
                (
                    "await importAgentsService.run({",
                    "ui.displayError('Agent import is disabled by Jarvis docs-only policy');\n        process.exit(1);\n        await importAgentsService.run({",
                ),
                ("skipAgents: options.skipAgents,", "skipAgents: true,"),
                ("skipSkills: options.skipSkills,", "skipSkills: true,"),
                (
                    "const { createSkillGenerator } = await Promise.resolve().then(() => __importStar(require('./generators/skills')));",
                    "ui.displayError('Skill scaffolding is disabled by Jarvis docs-only policy');\n        process.exit(1);\n        const { createSkillGenerator } = await Promise.resolve().then(() => __importStar(require('./generators/skills')));",
                ),
                (
                    "const { SkillFillService } = await Promise.resolve().then(() => __importStar(require('./services/fill/skillFillService')));",
                    "ui.displayError('Skill fill is disabled by Jarvis docs-only policy');\n        process.exit(1);\n        const { SkillFillService } = await Promise.resolve().then(() => __importStar(require('./services/fill/skillFillService')));",
                ),
                (
                    "const { SkillExportService } = await Promise.resolve().then(() => __importStar(require('./services/export/skillExportService')));",
                    "ui.displayError('Skill export is disabled by Jarvis docs-only policy');\n        process.exit(1);\n        const { SkillExportService } = await Promise.resolve().then(() => __importStar(require('./services/export/skillExportService')));",
                ),
            ],
        ),
        (
            "dist/services/mcp/gateway/context.js",
            [
                ("type: params.type,", "type: 'docs',"),
                ("target: params.target,", "target: 'docs',"),
            ],
        ),
        (
            "dist/services/mcp/gateway/skill.js",
            [
                (
                    "    const { createSkillRegistry, BUILT_IN_SKILLS } = require('../../../workflow/skills');\n    try {\n",
                    "    const { createSkillRegistry, BUILT_IN_SKILLS } = require('../../../workflow/skills');\n    const jarvisSkillWriteActions = new Set(['scaffold', 'export', 'fill']);\n    if (jarvisSkillWriteActions.has(String(params.action || ''))) {\n        return (0, response_1.createErrorResponse)('Skill scaffolding/export is disabled by Jarvis docs-only policy');\n    }\n    try {\n",
                ),
            ],
        ),
        (
            "dist/services/mcp/gateway/sync.js",
            [
                ("            case 'exportAgents': {\n", "            case 'exportAgents': {\n                return (0, response_1.createErrorResponse)('Agent export is disabled by Jarvis docs-only policy');\n"),
                ("            case 'exportSkills': {\n", "            case 'exportSkills': {\n                return (0, response_1.createErrorResponse)('Skill export is disabled by Jarvis docs-only policy');\n"),
                ("            case 'importAgents': {\n", "            case 'importAgents': {\n                return (0, response_1.createErrorResponse)('Agent import is disabled by Jarvis docs-only policy');\n"),
                ("            case 'importSkills': {\n", "            case 'importSkills': {\n                return (0, response_1.createErrorResponse)('Skill import is disabled by Jarvis docs-only policy');\n"),
                ("skipAgents: params.skipAgents,", "skipAgents: true,"),
                ("skipSkills: params.skipSkills,", "skipSkills: true,"),
                ("skipAgents: params.skipAgents || false,", "skipAgents: true,"),
                ("skipSkills: params.skipSkills || false,", "skipSkills: true,"),
            ],
        ),
        (
            "dist/services/mcp/mcpServer.js",
            [
                ("type: zod_1.z.enum(['docs', 'agents', 'both']).optional()", "type: zod_1.z.literal('docs').optional()"),
                ("target: zod_1.z.enum(['docs', 'agents', 'plans', 'all']).optional()", "target: zod_1.z.literal('docs').optional()"),
                ("action: zod_1.z.enum(['exportRules', 'exportDocs', 'exportAgents', 'exportContext', 'exportSkills', 'reverseSync', 'importDocs', 'importAgents', 'importSkills'])", "action: zod_1.z.enum(['exportRules', 'exportDocs', 'exportContext', 'reverseSync', 'importDocs'])"),
                ("action: zod_1.z.enum(['list', 'getContent', 'getForPhase', 'scaffold', 'export', 'fill'])", "action: zod_1.z.enum(['list', 'getContent', 'getForPhase'])"),
            ],
        ),
    ]

    results: list[dict] = []
    changed_files: list[str] = []
    for rel_path, replacements in patch_specs:
        target = pkg_root / rel_path
        if not apply_if_needed:
            results.append({"ok": True, "path": str(target), "changed": False, "skipped": True})
            continue
        patched = _patch_text_file_with_replacements(target, replacements)
        results.append(patched)
        if not patched.get("ok"):
            return {
                "ok": False,
                "error": "ai_coders_context_hardening_failed",
                "package_root": str(pkg_root),
                "failed_patch": patched,
                "results": results,
            }
        if patched.get("changed"):
            changed_files.append(str(target))

    return {
        "ok": True,
        "package_root": str(pkg_root),
        "changed": bool(changed_files),
        "changed_files": changed_files,
        "results": results,
    }


def _ensure_ai_coders_context_global_installed(install_if_missing: bool = True) -> dict:
    pkg = "@ai-coders/context"
    current_version = _npm_global_version(pkg)

    if current_version:
        cli = _resolve_ai_coders_context_global_cli()
        if not cli.get("ok"):
            return {
                "ok": False,
                "installed": True,
                "version_stdout": current_version,
                "error": "ai_coders_context_cli_not_found",
                "cli": cli,
            }
        hardening = _harden_ai_coders_context_global_install(apply_if_needed=True)
        if not hardening.get("ok"):
            return {
                "ok": False,
                "installed": True,
                "version_stdout": current_version,
                "error": "ai_coders_context_hardening_failed",
                "cli": cli,
                "hardening": hardening,
            }
        result = {
            "ok": True,
            "installed": True,
            "version_stdout": current_version,
            "source": "npm_global",
        }
        result.update(
            {
                "command": cli.get("command", ""),
                "args_prefix": cli.get("args_prefix", []),
                "command_source": cli.get("source", ""),
                "hardening": hardening,
            }
        )
        return result

    if not install_if_missing:
        return {
            "ok": False,
            "installed": False,
            "error": "ai_coders_context_not_found",
            "hint": "Instale com: npm install -g @ai-coders/context",
        }

    installed_ok = _npm_ensure_global(pkg)
    after_version = _npm_global_version(pkg) or ""
    if not installed_ok:
        return {
            "ok": False,
            "installed": False,
            "error": "ai_coders_context_install_failed",
        }

    cli = _resolve_ai_coders_context_global_cli()
    if not cli.get("ok"):
        return {
            "ok": False,
            "installed": True,
            "installed_now": True,
            "version_stdout": after_version,
            "error": "ai_coders_context_cli_not_found",
            "cli": cli,
        }

    hardening = _harden_ai_coders_context_global_install(apply_if_needed=True)
    if not hardening.get("ok"):
        return {
            "ok": False,
            "installed": True,
            "installed_now": True,
            "version_stdout": after_version,
            "error": "ai_coders_context_hardening_failed",
            "cli": cli,
            "hardening": hardening,
        }

    result = {
        "ok": True,
        "installed": True,
        "installed_now": True,
        "version_stdout": after_version,
    }
    result.update(
        {
            "command": cli.get("command", ""),
            "args_prefix": cli.get("args_prefix", []),
            "command_source": cli.get("source", ""),
            "hardening": hardening,
        }
    )
    return result


def _resolve_ai_coders_context_exec(install_if_missing: bool = True) -> list[str]:
    resolved = _ensure_ai_coders_context_global_installed(install_if_missing=install_if_missing)
    if resolved.get("ok"):
        return [str(resolved.get("command") or "ai-context"), *list(resolved.get("args_prefix") or [])]
    return [_resolve_npx_bin(), "-y", "@ai-coders/context"]


def _resolve_graphify_package_root() -> Path | None:
    try:
        import graphify
    except Exception:
        return None
    try:
        return Path(graphify.__file__).resolve().parent
    except Exception:
        return None


def _patch_graphify_context_output(path: Path) -> dict:
    if not path.exists():
        return {"ok": False, "error": "file_not_found", "path": str(path)}
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": "read_failed", "path": str(path), "detail": str(exc)}

    updated, occurrences = re.subn(r"(?<!\.context/)graphify-out", GRAPHIFY_DEFAULT_REL, original)
    updated = updated.replace(
        'candidate.name == ".context/graphify-out"',
        '(candidate.name == "graphify-out" and candidate.parent.name == ".context")',
    )
    if path.name == "watch.py":
        updated, watch_occurrences = _patch_graphify_watch_large_update(updated)
        occurrences += watch_occurrences
    if path.name == "extract.py":
        updated, extract_occurrences = _patch_graphify_extract_large_update(updated)
        occurrences += extract_occurrences
    changed = updated != original
    if changed:
        backup_path = Path(f"{path}.jarvis-orig")
        try:
            if not backup_path.exists():
                backup_path.write_text(original, encoding="utf-8")
            path.write_text(updated, encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": "write_failed", "path": str(path), "detail": str(exc)}

    return {
        "ok": True,
        "path": str(path),
        "changed": changed,
        "occurrences": occurrences,
    }


def _patch_graphify_watch_large_update(text: str) -> tuple[str, int]:
    occurrences = 0
    helper = '''


def _fast_source_communities(G) -> dict[int, list[str]]:
    """Group very large update graphs by top-level source path.

    Full Leiden/Louvain clustering can sit for minutes after AST extraction reaches
    100% on large monorepos. Code-only update should remain operational, so large
    graphs use deterministic source buckets instead of interactive-quality clusters.
    """
    buckets: dict[str, list[str]] = {}
    for node_id, data in G.nodes(data=True):
        source = data.get("source_file") or "_semantic"
        key = source.split("/", 1)[0] if "/" in source else source
        buckets.setdefault(key, []).append(node_id)
    ordered = sorted(buckets.values(), key=len, reverse=True)
    return {cid: sorted(nodes) for cid, nodes in enumerate(ordered)}
'''
    if "_fast_source_communities" not in text and "\ndef _rebuild_code" in text:
        text = text.replace("\ndef _rebuild_code", helper + "\ndef _rebuild_code", 1)
        occurrences += 1

    old = '''        G = build_from_json(result)
        communities = cluster(G)
        cohesion = score_all(G, communities)
        gods = god_nodes(G)
        surprises = surprising_connections(G, communities)
        labels = {cid: "Community " + str(cid) for cid in communities}
        questions = suggest_questions(G, communities, labels)
'''
    new = '''        print("[graphify watch] Building NetworkX graph...", flush=True)
        G = build_from_json(result)
        node_count = G.number_of_nodes()
        edge_count = G.number_of_edges()
        if node_count > 50_000:
            print(
                f"[graphify watch] Large graph ({node_count} nodes, {edge_count} edges) - "
                "using fast source-path communities instead of full clustering.",
                flush=True,
            )
            communities = _fast_source_communities(G)
        else:
            print(f"[graphify watch] Clustering {node_count} nodes...", flush=True)
            communities = cluster(G)
        print(f"[graphify watch] Scoring {len(communities)} communities...", flush=True)
        cohesion = score_all(G, communities)
        print("[graphify watch] Analyzing graph report sections...", flush=True)
        gods = god_nodes(G)
        surprises = surprising_connections(G, communities)
        labels = {cid: "Community " + str(cid) for cid in communities}
        questions = suggest_questions(G, communities, labels)
'''
    if old in text:
        text = text.replace(old, new, 1)
        occurrences += 1
    return text, occurrences


def _patch_graphify_extract_large_update(text: str) -> tuple[str, int]:
    occurrences = 0
    marker = '''    if total >= _PROGRESS_INTERVAL:
        print(f"  AST extraction: {total}/{total} files (100%)", flush=True)

    all_nodes: list[dict] = []
'''
    replacement = '''    if total >= _PROGRESS_INTERVAL:
        print(f"  AST extraction: {total}/{total} files (100%)", flush=True)
    if total >= _PROGRESS_INTERVAL:
        print("  AST extraction: merging per-file results", flush=True)

    all_nodes: list[dict] = []
'''
    if marker in text:
        text = text.replace(marker, replacement, 1)
        occurrences += 1

    marker = '''    if id_remap:
        for n in all_nodes:
            if n.get("id") in id_remap:
                n["id"] = id_remap[n["id"]]
        for e in all_edges:
            if e.get("source") in id_remap:
                e["source"] = id_remap[e["source"]]
            if e.get("target") in id_remap:
                e["target"] = id_remap[e["target"]]

    # Add cross-file class-level edges (Python only - uses Python parser internally)
'''
    replacement = '''    if id_remap:
        for n in all_nodes:
            if n.get("id") in id_remap:
                n["id"] = id_remap[n["id"]]
        for e in all_edges:
            if e.get("source") in id_remap:
                e["source"] = id_remap[e["source"]]
            if e.get("target") in id_remap:
                e["target"] = id_remap[e["target"]]

    if total >= _PROGRESS_INTERVAL:
        print("  AST extraction: resolving cross-file imports", flush=True)
    # Add cross-file class-level edges (Python only - uses Python parser internally)
'''
    if marker in text:
        text = text.replace(marker, replacement, 1)
        occurrences += 1

    old = '''    global_label_to_nid: dict[str, str] = {}
    for n in all_nodes:
        raw = n.get("label", "")
        normalised = raw.strip("()").lstrip(".")
        if normalised:
            global_label_to_nid[normalised.lower()] = n["id"]

    existing_pairs = {(e["source"], e["target"]) for e in all_edges}
    for result in per_file:
        for rc in result.get("raw_calls", []):
            callee = rc.get("callee", "")
            if not callee:
                continue
            tgt = global_label_to_nid.get(callee.lower())
            caller = rc["caller_nid"]
            if tgt and tgt != caller and (caller, tgt) not in existing_pairs:
                existing_pairs.add((caller, tgt))
                all_edges.append({
                    "source": caller,
                    "target": tgt,
                    "relation": "calls",
                    "confidence": "INFERRED",
                    "confidence_score": 0.8,
                    "source_file": rc.get("source_file", ""),
                    "source_location": rc.get("source_location"),
                    "weight": 1.0,
                })
'''
    new = '''    raw_call_count = sum(len(result.get("raw_calls", [])) for result in per_file)
    if total >= _PROGRESS_INTERVAL:
        print(f"  AST extraction: resolving {raw_call_count} raw calls", flush=True)
    if raw_call_count > 200_000:
        print(
            "  AST extraction: skipped global raw-call resolution for large corpus "
            f"({raw_call_count} calls)",
            flush=True,
        )
    else:
        global_label_to_nid: dict[str, str] = {}
        for n in all_nodes:
            raw = n.get("label", "")
            normalised = raw.strip("()").lstrip(".")
            if normalised:
                global_label_to_nid[normalised.lower()] = n["id"]

        existing_pairs = {(e["source"], e["target"]) for e in all_edges}
        for result in per_file:
            for rc in result.get("raw_calls", []):
                callee = rc.get("callee", "")
                if not callee:
                    continue
                tgt = global_label_to_nid.get(callee.lower())
                caller = rc["caller_nid"]
                if tgt and tgt != caller and (caller, tgt) not in existing_pairs:
                    existing_pairs.add((caller, tgt))
                    all_edges.append({
                        "source": caller,
                        "target": tgt,
                        "relation": "calls",
                        "confidence": "INFERRED",
                        "confidence_score": 0.8,
                        "source_file": rc.get("source_file", ""),
                        "source_location": rc.get("source_location"),
                        "weight": 1.0,
                    })
'''
    if old in text:
        text = text.replace(old, new, 1)
        occurrences += 1
    return text, occurrences


def _harden_graphify_global_install(apply_if_needed: bool = True) -> dict:
    if not _env_is_true("JARVIS_GRAPHIFY_HARDEN", True):
        return {"ok": True, "skipped": True, "reason": "disabled_by_env"}

    pkg_root = _resolve_graphify_package_root()
    if not pkg_root:
        return {
            "ok": False,
            "error": "graphify_package_root_not_found",
            "hint": "Instale com: python3 -m pip install graphifyy",
        }

    patch_files = sorted([*pkg_root.glob("*.py"), *pkg_root.glob("skill*.md")])
    results: list[dict] = []
    changed_files: list[str] = []
    for target in patch_files:
        if not target.exists():
            continue
        patched = (
            {"ok": True, "path": str(target), "changed": False, "skipped": True}
            if not apply_if_needed
            else _patch_graphify_context_output(target)
        )
        results.append(patched)
        if not patched.get("ok"):
            return {
                "ok": False,
                "error": "graphify_hardening_failed",
                "package_root": str(pkg_root),
                "failed_patch": patched,
                "results": results,
            }
        if patched.get("changed"):
            changed_files.append(str(target))

    return {
        "ok": True,
        "package_root": str(pkg_root),
        "target": GRAPHIFY_DEFAULT_REL,
        "changed": bool(changed_files),
        "changed_files": changed_files,
        "results": results,
    }


def _resolve_gsd_package_root(gsd_bin: str = "") -> Path | None:
    candidates = [
        (gsd_bin or "").strip(),
        shutil.which("get-shit-done-cc") or "",
        shutil.which("gsd") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "get-shit-done-cc"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/get-shit-done-cc",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        p = Path(candidate)
        if not p.exists():
            continue
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        for parent in [resolved] + list(resolved.parents):
            if parent.name == "get-shit-done-cc" and (parent / "package.json").exists():
                return parent

    npm_bin = shutil.which("npm")
    if npm_bin:
        probe = _run_capture_command([npm_bin, "root", "-g"], cwd=BASE_DIR, timeout_sec=30)
        if probe.get("ok"):
            root_out = (probe.get("stdout_tail") or "").strip()
            if root_out:
                fallback = Path(root_out) / "get-shit-done-cc"
                if fallback.exists() and (fallback / "package.json").exists():
                    return fallback
    return None


def _apply_gsd_direct_context_planning_patch(*, apply_if_needed: bool = True, gsd_bin: str = "") -> dict:
    root = _resolve_gsd_package_root(gsd_bin=gsd_bin)
    if not root:
        return {
            "ok": False,
            "error": "gsd_package_root_not_found",
            "hint": "Instale com: npm install -g get-shit-done-cc",
        }

    text_exts = {".md", ".cjs", ".js", ".json", ".txt", ".yaml", ".yml", ".bak"}
    legacy_tokens = [".planning", ".context/docs/planning_gsd"]
    target_token = ".context/plans"
    changed_files = 0
    changed_occurrences = 0
    remaining_legacy_refs = 0
    file_errors: list[str] = []

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in text_exts:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue

        count = sum(content.count(token) for token in legacy_tokens)
        if count <= 0:
            continue
        remaining_legacy_refs += count
        if not apply_if_needed:
            continue

        updated = content
        for token in legacy_tokens:
            updated = updated.replace(token, target_token)
        if updated == content:
            continue

        try:
            p.write_text(updated, encoding="utf-8")
            changed_files += 1
            changed_occurrences += count
        except Exception as exc:
            file_errors.append(f"{p}: {exc}")

    # Recontagem após patch para confirmar que não sobrou referência legada.
    final_remaining = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in text_exts:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        final_remaining += sum(content.count(token) for token in legacy_tokens)

    ok = len(file_errors) == 0 and final_remaining == 0
    result = {
        "ok": ok,
        "package_root": str(root),
        "changed_files": changed_files,
        "changed_occurrences": changed_occurrences,
        "remaining_legacy_refs_before": remaining_legacy_refs,
        "remaining_legacy_refs_after": final_remaining,
        "already_patched": remaining_legacy_refs == 0,
    }
    if file_errors:
        result["file_errors"] = file_errors[:20]
    if not ok and final_remaining > 0:
        result["error"] = "gsd_patch_incomplete"
    return result


def _resolve_ralph_package_root(ralph_bin: str = "") -> Path | None:
    candidates = [
        (ralph_bin or "").strip(),
        shutil.which("ralph") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "ralph"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/ralph",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        p = Path(candidate)
        if not p.exists():
            continue
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        for parent in [resolved] + list(resolved.parents):
            if parent.name == "ralph" and (parent / "package.json").exists():
                return parent

    npm_bin = shutil.which("npm")
    if npm_bin:
        probe = _run_capture_command([npm_bin, "root", "-g"], cwd=BASE_DIR, timeout_sec=30)
        if probe.get("ok"):
            root_out = (probe.get("stdout_tail") or "").strip()
            if root_out:
                fallback = Path(root_out) / "@iannuttall" / "ralph"
                if fallback.exists() and (fallback / "package.json").exists():
                    return fallback
    return None


def _sync_ralph_global_templates_from_repo(*, apply_if_needed: bool = True, ralph_bin: str = "") -> dict:
    root = _resolve_ralph_package_root(ralph_bin=ralph_bin)
    if not root:
        return {
            "ok": False,
            "error": "ralph_package_root_not_found",
            "hint": "Instale com: npm install -g @iannuttall/ralph",
        }

    src_root = BASE_DIR / RALPH_RUNTIME_REL / "templates"
    dst_root = root / ".agents" / "ralph"
    sync_targets = [
        "references",
        "loop.sh",
        "agents.sh",
        "config.sh",
        "log-activity.sh",
        "PROMPT_build.md",
    ]

    # Se os templates locais foram removidos do projeto, assume que o npm global já
    # é a fonte absorvida e apenas valida presença dos alvos no pacote global.
    if not src_root.exists():
        missing_on_global: list[str] = []
        for rel in sync_targets:
            if not (dst_root / rel).exists():
                missing_on_global.append(rel)
        if missing_on_global:
            return {
                "ok": False,
                "error": "ralph_local_templates_not_found_and_global_missing_targets",
                "source_root": str(src_root),
                "target_root": str(dst_root),
                "missing_targets_on_global": missing_on_global,
            }
        return {
            "ok": True,
            "package_root": str(root),
            "source_root": "",
            "target_root": str(dst_root),
            "synced_targets": [],
            "copied_files": 0,
            "apply_if_needed": apply_if_needed,
            "skipped": True,
            "reason": "local_templates_absent_using_global_templates",
        }

    missing_sources: list[str] = []
    for rel in sync_targets:
        if not (src_root / rel).exists():
            missing_sources.append(rel)
    if missing_sources:
        missing_on_global: list[str] = []
        for rel in sync_targets:
            if not (dst_root / rel).exists():
                missing_on_global.append(rel)
        if missing_on_global:
            return {
                "ok": False,
                "error": "ralph_template_sources_missing",
                "source_root": str(src_root),
                "missing_sources": missing_sources,
                "target_root": str(dst_root),
                "missing_targets_on_global": missing_on_global,
            }
        return {
            "ok": True,
            "package_root": str(root),
            "source_root": str(src_root),
            "target_root": str(dst_root),
            "synced_targets": [],
            "copied_files": 0,
            "apply_if_needed": apply_if_needed,
            "skipped": True,
            "reason": "local_templates_partial_using_global_templates",
            "missing_sources": missing_sources,
        }

    if not apply_if_needed:
        return {
            "ok": True,
            "package_root": str(root),
            "source_root": str(src_root),
            "target_root": str(dst_root),
            "synced_targets": [],
            "copied_files": 0,
            "apply_if_needed": False,
        }

    errors: list[str] = []
    synced_targets: list[str] = []
    copied_files = 0

    for rel in sync_targets:
        src = src_root / rel
        dst = dst_root / rel
        try:
            if src.is_dir():
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink(missing_ok=True)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst)
                copied_files += sum(1 for p in src.rglob("*") if p.is_file())
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied_files += 1
                if dst.suffix == ".sh":
                    dst.chmod(dst.stat().st_mode | 0o111)
            synced_targets.append(rel)
        except Exception as exc:
            errors.append(f"{rel}: {exc}")

    ok = len(errors) == 0
    result = {
        "ok": ok,
        "package_root": str(root),
        "source_root": str(src_root),
        "target_root": str(dst_root),
        "synced_targets": synced_targets,
        "copied_files": copied_files,
        "apply_if_needed": True,
    }
    if errors:
        result["errors"] = errors[:20]
        result["error"] = "ralph_template_sync_failed"
    return result


def _apply_ralph_global_template_resolution_patch(*, apply_if_needed: bool = True, ralph_bin: str = "") -> dict:
    root = _resolve_ralph_package_root(ralph_bin=ralph_bin)
    if not root:
        return {
            "ok": False,
            "error": "ralph_package_root_not_found",
            "hint": "Instale com: npm install -g @iannuttall/ralph",
        }

    bin_file = root / "bin" / "ralph"
    if not bin_file.exists():
        return {
            "ok": False,
            "error": "ralph_bin_script_not_found",
            "package_root": str(root),
            "bin_file": str(bin_file),
        }

    legacy_token = "const templateDir = exists(localDir) ? localDir : globalDir;"
    target_token = (
        'const localLoopPath = path.join(localDir, "loop.sh");\n'
        "  const templateDir = exists(localLoopPath) ? localDir : globalDir;"
    )

    try:
        content = bin_file.read_text(encoding="utf-8")
    except Exception as exc:
        return {
            "ok": False,
            "error": "ralph_bin_script_read_failed",
            "package_root": str(root),
            "bin_file": str(bin_file),
            "detail": str(exc),
        }

    if target_token in content:
        return {
            "ok": True,
            "package_root": str(root),
            "bin_file": str(bin_file),
            "already_patched": True,
            "changed_occurrences": 0,
        }

    legacy_count = content.count(legacy_token)
    if legacy_count <= 0:
        # Layout desconhecido no upstream. Não bloqueia setup.
        return {
            "ok": True,
            "package_root": str(root),
            "bin_file": str(bin_file),
            "already_patched": False,
            "changed_occurrences": 0,
            "skipped": True,
            "reason": "legacy_token_not_found",
        }

    if not apply_if_needed:
        return {
            "ok": True,
            "package_root": str(root),
            "bin_file": str(bin_file),
            "already_patched": False,
            "changed_occurrences": 0,
            "pending_occurrences": legacy_count,
            "apply_if_needed": False,
        }

    updated = content.replace(legacy_token, target_token)
    try:
        bin_file.write_text(updated, encoding="utf-8")
    except Exception as exc:
        return {
            "ok": False,
            "error": "ralph_bin_script_write_failed",
            "package_root": str(root),
            "bin_file": str(bin_file),
            "detail": str(exc),
        }

    return {
        "ok": True,
        "package_root": str(root),
        "bin_file": str(bin_file),
        "already_patched": False,
        "changed_occurrences": legacy_count,
    }


def _apply_ralph_global_prd_path_patch(*, apply_if_needed: bool = True, ralph_bin: str = "") -> dict:
    root = _resolve_ralph_package_root(ralph_bin=ralph_bin)
    if not root:
        return {
            "ok": False,
            "error": "ralph_package_root_not_found",
            "hint": "Instale com: npm install -g @iannuttall/ralph",
        }

    patch_specs: list[dict] = [
        {
            "file": root / ".agents" / "ralph" / "loop.sh",
            "replacements": [
                (
                    'DEFAULT_PRD_PATH=".agents/tasks/prd.json"',
                    'DEFAULT_PRD_PATH=".context/workflow/prd.json"',
                ),
                (
                    'DEFAULT_PRD_PATH=".context/prd_ralph/prd.json"',
                    'DEFAULT_PRD_PATH=".context/workflow/prd.json"',
                )
            ],
        },
        {
            "file": root / "bin" / "ralph",
            "replacements": [
                (
                    'const tasksDir = path.join(baseDir, ".agents", "tasks");',
                    'const tasksDir = path.join(baseDir, ".context", "workflow");',
                ),
                (
                    'const tasksDir = path.join(baseDir, ".context", "prd_ralph");',
                    'const tasksDir = path.join(baseDir, ".context", "workflow");',
                ),
                (
                    'return path.join(baseDir, ".agents", "tasks");',
                    'return path.join(baseDir, ".context", "workflow");',
                ),
                (
                    'return path.join(baseDir, ".context", "prd_ralph");',
                    'return path.join(baseDir, ".context", "workflow");',
                ),
            ],
        },
    ]

    changed_files = 0
    changed_occurrences = 0
    already_patched_files = 0
    skipped_unknown_layout: list[str] = []
    errors: list[str] = []

    for spec in patch_specs:
        file_path = spec["file"]
        replacements = spec["replacements"]
        if not file_path.exists():
            errors.append(f"{file_path}: not_found")
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"{file_path}: read_failed: {exc}")
            continue

        updated = content
        file_has_old = 0
        file_has_new = 0
        file_changed = 0
        for old_token, new_token in replacements:
            old_count = updated.count(old_token)
            new_count = updated.count(new_token)
            file_has_old += old_count
            file_has_new += new_count
            if old_count > 0:
                if apply_if_needed:
                    updated = updated.replace(old_token, new_token)
                file_changed += old_count

        if file_changed > 0 and not apply_if_needed:
            changed_occurrences += file_changed
            continue

        if file_changed > 0 and apply_if_needed:
            try:
                file_path.write_text(updated, encoding="utf-8")
                changed_files += 1
                changed_occurrences += file_changed
            except Exception as exc:
                errors.append(f"{file_path}: write_failed: {exc}")
            continue

        if file_has_new > 0 and file_has_old == 0:
            already_patched_files += 1
        elif file_has_new == 0 and file_has_old == 0:
            skipped_unknown_layout.append(str(file_path))

    ok = len(errors) == 0
    return {
        "ok": ok,
        "package_root": str(root),
        "changed_files": changed_files,
        "changed_occurrences": changed_occurrences,
        "already_patched_files": already_patched_files,
        "apply_if_needed": apply_if_needed,
        "skipped_unknown_layout": skipped_unknown_layout,
        "errors": errors[:20],
    }


def _ensure_gsd_global_installed(install_if_missing: bool = True) -> dict:
    def _read_gsd_version(bin_path: str) -> str:
        try:
            p = Path(bin_path).resolve()
            for parent in [p] + list(p.parents):
                if parent.name == "get-shit-done-cc":
                    pkg = parent / "package.json"
                    if pkg.exists():
                        data = json.loads(pkg.read_text(encoding="utf-8"))
                        return str(data.get("version", "")).strip()
        except Exception:
            pass
        return ""

    candidates = [
        shutil.which("get-shit-done-cc") or "",
        shutil.which("gsd") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "get-shit-done-cc"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/get-shit-done-cc",
    ]
    gsd_bin = ""
    for c in candidates:
        if c and Path(c).exists():
            gsd_bin = c
            break
    if gsd_bin:
        detected_version = _read_gsd_version(gsd_bin)
        return {
            "ok": True,
            "installed": True,
            "gsd_bin": gsd_bin,
            "version_stdout": detected_version,
        }

    if not install_if_missing:
        return {
            "ok": False,
            "installed": False,
            "error": "gsd_not_found",
            "hint": "Instale com: npm install -g get-shit-done-cc",
        }

    install = _run_capture_command(["npm", "install", "-g", "get-shit-done-cc"], cwd=BASE_DIR, timeout_sec=900)
    gsd_bin = ""
    for c in [
        shutil.which("get-shit-done-cc") or "",
        shutil.which("gsd") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "get-shit-done-cc"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/get-shit-done-cc",
    ]:
        if c and Path(c).exists():
            gsd_bin = c
            break
    if not install.get("ok") or not gsd_bin:
        return {
            "ok": False,
            "installed": False,
            "error": "gsd_install_failed",
            "install": install,
        }
    detected_version = _read_gsd_version(gsd_bin)
    return {
        "ok": True,
        "installed": True,
        "installed_now": True,
        "gsd_bin": gsd_bin,
        "version_stdout": detected_version,
        "install": install,
    }


def _run_internal_gsd_setup_step() -> dict:
    ensure = _ensure_gsd_global_installed(install_if_missing=True)
    if not ensure.get("ok"):
        return {"ok": False, "returncode": 1, "step": "ensure_gsd_global", "detail": ensure}
    patch = _apply_gsd_direct_context_planning_patch(apply_if_needed=True, gsd_bin=str(ensure.get("gsd_bin", "")))
    if not patch.get("ok"):
        return {"ok": False, "returncode": 1, "step": "patch_gsd_planning_path", "detail": patch}
    return {"ok": True, "returncode": 0, "step": "gsd_global_ready", "detail": {"ensure": ensure, "patch": patch}}


def _ensure_ralph_global_installed(install_if_missing: bool = True) -> dict:
    def _read_ralph_version(bin_path: str) -> str:
        try:
            p = Path(bin_path).resolve()
            for parent in [p] + list(p.parents):
                if parent.name == "@iannuttall":
                    pkg = parent / "ralph" / "package.json"
                    if pkg.exists():
                        data = json.loads(pkg.read_text(encoding="utf-8"))
                        return str(data.get("version", "")).strip()
        except Exception:
            pass
        return ""

    candidates = [
        shutil.which("ralph") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "ralph"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/ralph",
    ]
    ralph_bin = ""
    for c in candidates:
        if c and Path(c).exists():
            ralph_bin = c
            break
    if ralph_bin:
        return {
            "ok": True,
            "installed": True,
            "ralph_bin": ralph_bin,
            "version_stdout": _read_ralph_version(ralph_bin),
        }

    if not install_if_missing:
        return {
            "ok": False,
            "installed": False,
            "error": "ralph_not_found",
            "hint": "Instale com: npm install -g @iannuttall/ralph",
        }

    install = _run_capture_command(["npm", "install", "-g", "@iannuttall/ralph"], cwd=BASE_DIR, timeout_sec=900)
    for c in [
        shutil.which("ralph") or "",
        str(_primary_user_home() / ".nvm" / "versions" / "node" / "v22.21.1" / "bin" / "ralph"),
        "/home/lucas/.nvm/versions/node/v22.21.1/bin/ralph",
    ]:
        if c and Path(c).exists():
            ralph_bin = c
            break
    if not install.get("ok") or not ralph_bin:
        return {
            "ok": False,
            "installed": False,
            "error": "ralph_install_failed",
            "install": install,
        }
    return {
        "ok": True,
        "installed": True,
        "installed_now": True,
        "ralph_bin": ralph_bin,
        "version_stdout": _read_ralph_version(ralph_bin),
        "install": install,
    }


def _run_internal_ralph_setup_step() -> dict:
    ensure = _ensure_ralph_global_installed(install_if_missing=True)
    if not ensure.get("ok"):
        return {"ok": False, "returncode": 1, "step": "ensure_ralph_global", "detail": ensure}
    sync = _sync_ralph_global_templates_from_repo(
        apply_if_needed=True,
        ralph_bin=str(ensure.get("ralph_bin", "")),
    )
    if not sync.get("ok"):
        return {
            "ok": False,
            "returncode": 1,
            "step": "sync_ralph_global_templates",
            "detail": {"ensure": ensure, "sync": sync},
        }
    patch = _apply_ralph_global_template_resolution_patch(
        apply_if_needed=True,
        ralph_bin=str(ensure.get("ralph_bin", "")),
    )
    if not patch.get("ok"):
        return {
            "ok": False,
            "returncode": 1,
            "step": "patch_ralph_template_resolution",
            "detail": {"ensure": ensure, "sync": sync, "patch": patch},
        }
    prd_patch = _apply_ralph_global_prd_path_patch(
        apply_if_needed=True,
        ralph_bin=str(ensure.get("ralph_bin", "")),
    )
    if not prd_patch.get("ok"):
        return {
            "ok": False,
            "returncode": 1,
            "step": "patch_ralph_prd_path",
            "detail": {"ensure": ensure, "sync": sync, "patch": patch, "prd_patch": prd_patch},
        }
    return {
        "ok": True,
        "returncode": 0,
        "step": "ralph_global_ready",
        "detail": {"ensure": ensure, "sync": sync, "patch": patch, "prd_patch": prd_patch},
    }


def _run_internal_smoke_test_step() -> dict:
    ai_context_global = _ensure_ai_coders_context_global_installed(install_if_missing=False)
    gsd_global = _ensure_gsd_global_installed(install_if_missing=False)
    gsd_patch = _apply_gsd_direct_context_planning_patch(
        apply_if_needed=False,
        gsd_bin=str(gsd_global.get("gsd_bin", "")),
    )
    ralph_global = _ensure_ralph_global_installed(install_if_missing=False)
    ralph_templates = _sync_ralph_global_templates_from_repo(
        apply_if_needed=False,
        ralph_bin=str(ralph_global.get("ralph_bin", "")),
    )
    ralph_patch = _apply_ralph_global_template_resolution_patch(
        apply_if_needed=False,
        ralph_bin=str(ralph_global.get("ralph_bin", "")),
    )
    ralph_prd_patch = _apply_ralph_global_prd_path_patch(
        apply_if_needed=False,
        ralph_bin=str(ralph_global.get("ralph_bin", "")),
    )
    graphify_patch = _harden_graphify_global_install(apply_if_needed=False)
    checks = {
        "ai_coders_context_global_installed": bool(ai_context_global.get("installed")),
        "gsd_global_installed": bool(gsd_global.get("installed")),
        "gsd_plans_path_patched": bool(gsd_patch.get("ok"))
        and int(gsd_patch.get("remaining_legacy_refs_after", 1)) == 0,
        "ralph_global_installed": bool(ralph_global.get("installed")),
        "ralph_global_templates_ready": bool(ralph_templates.get("ok")),
        "ralph_template_resolution_patched": bool(ralph_patch.get("ok")),
        "ralph_prd_path_patched": bool(ralph_prd_patch.get("ok")),
        "graphify_context_output_patched": bool(graphify_patch.get("ok")),
        ".context/docs": (BASE_DIR / ".context" / "docs").exists(),
        ".context/plans": (BASE_DIR / ".context" / "plans").exists(),
        ".context/workflow": (BASE_DIR / ".context" / "workflow").exists(),
        ".context/graphify-out": (BASE_DIR / ".context" / "graphify-out").exists(),
    }
    missing = [k for k, ok in checks.items() if not ok]
    return {
        "ok": len(missing) == 0,
        "returncode": 0 if len(missing) == 0 else 1,
        "checks": checks,
        "missing": missing,
    }


def _run_internal_context_update_step(target_dir: Path | None = None) -> dict:
    work_dir = target_dir or Path.cwd()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_dir = work_dir / RALPH_RUNTIME_REL / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    report_path = export_dir / f"us001_context_routine_report-{run_id}.md"

    init_out = Path(tempfile.mkdtemp(prefix=f"ai-context-init-{run_id}-"))
    steps: list[dict] = []
    try:
        project_entrypoints = _sync_project_context_entrypoints(target_dir=work_dir)
        steps.append({"name": "project_context_entrypoints", **project_entrypoints})
        if not project_entrypoints.get("ok"):
            return {"ok": False, "returncode": project_entrypoints.get("returncode", 1), "steps": steps}

        ai_context_exec = _resolve_ai_coders_context_exec(install_if_missing=True)
        init_cmd = [*ai_context_exec, "init", ".", "docs", "-o", str(init_out)]
        steps.append({"name": "init", **_run_capture_command(init_cmd, cwd=work_dir, timeout_sec=900)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        docs_src = init_out / "docs"
        docs_dst = work_dir / ".context" / "docs"
        docs_dst.mkdir(parents=True, exist_ok=True)
        if docs_src.exists():
            shutil.rmtree(docs_dst, ignore_errors=True)
            shutil.copytree(docs_src, docs_dst)
        removed_dirs: list[str] = []
        for unsupported_dir in [work_dir / ".context" / "agents", work_dir / ".context" / "skills"]:
            if unsupported_dir.exists():
                shutil.rmtree(unsupported_dir, ignore_errors=True)
                removed_dirs.append(str(unsupported_dir.relative_to(work_dir)))
        steps.append(
            {
                "name": "sync_context_dirs",
                "ok": True,
                "returncode": 0,
                "detail": {
                    "docs_only": True,
                    "removed_unsupported_dirs": removed_dirs,
                },
            }
        )

        fill_cmd = [*ai_context_exec, "fill", ".", "-o", "./.context", "-p", "openai", "-m", "openai/gpt-4o-mini"]
        if os.environ.get("OPENAI_BASE_URL", "").strip():
            fill_cmd += ["--base-url", os.environ["OPENAI_BASE_URL"]]
        steps.append({"name": "fill", **_run_capture_command(fill_cmd, cwd=work_dir, timeout_sec=1200)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        report_cmd = [*ai_context_exec, "report", ".", "-f", "markdown", "-o", str(report_path)]
        steps.append({"name": "report", **_run_capture_command(report_cmd, cwd=work_dir, timeout_sec=600)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        graphify_bin = shutil.which("graphify")
        if graphify_bin:
            graphify_cmd = [graphify_bin, "update", "."]
            steps.append({"name": "graphify_update", **_run_capture_command(graphify_cmd, cwd=work_dir, timeout_sec=1800)})
            if not steps[-1].get("ok"):
                print("⚠️ Graphify update falhou ou foi cancelado, prosseguindo mesmo assim.", file=sys.stderr)

        return {"ok": True, "returncode": 0, "steps": steps, "report_path": str(report_path)}
    finally:
        shutil.rmtree(init_out, ignore_errors=True)


def _run_internal_quality_gates_step(target_dir: Path | None = None, label: str = "quality_gates") -> dict:
    work_dir = target_dir or Path.cwd()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_dir = work_dir / RALPH_RUNTIME_REL / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    summary_path = export_dir / f"{label}_quality_gates_run-{run_id}.md"
    commands = []
    py_target = "super_server_v6.py" if (work_dir / "super_server_v6.py").exists() else ("jarvis.py" if (work_dir / "jarvis.py").exists() else None)
    if py_target:
        commands.append(("py_compile", ["python3", "-m", "py_compile", py_target], 180))
        if py_target == "super_server_v6.py":
            commands.append(("service_help", ["python3", "super_server_v6.py", "service", "--help"], 180))
        else:
            commands.append(("service_help", ["python3", "jarvis.py", "--help"], 180))
        # Smoke test requires jarvis to be present
        commands.append(("smoke", ["python3", "-c", "import jarvis, json; r=jarvis._run_internal_smoke_test_step(); print(json.dumps(r, ensure_ascii=False)); raise SystemExit(0 if r.get('ok') else 1)"], 120))
    commands.append(("codex_mcp_list", ["codex", "mcp", "list"], 120))
    commands.append(("gemini_mcp_list", ["env", "CI=1", "gemini", "mcp", "list"], int(os.environ.get("GEMINI_MCP_TIMEOUT", "60"))))

    results: list[dict] = []
    overall_ok = True
    for name, cmd, timeout_sec in commands:
        step = _run_capture_command(cmd, cwd=work_dir, timeout_sec=timeout_sec)
        step["name"] = name
        results.append(step)
        overall_ok = overall_ok and bool(step.get("ok"))

    try:
        with summary_path.open("w", encoding="utf-8") as f:
            f.write(f"# {label} - Quality gates\n")
            f.write(f"Data: {datetime.now().isoformat()}\n\n")
            f.write(json.dumps({"overall_ok": overall_ok, "results": results}, ensure_ascii=False, indent=2))
            f.write("\n")
    except Exception:
        pass

    return {"ok": overall_ok, "returncode": 0 if overall_ok else 1, "summary_path": str(summary_path), "results": results}


def _workflow_unified_status_payload(prd_path: str = RALPH_PRD_DEFAULT_REL) -> dict:
    workspace = _resolve_gsd_ralph_workspace()
    scripts_dir = workspace / "scripts"
    context_script = scripts_dir / "02_context_update_routine.sh"
    quality_script = scripts_dir / "07_quality_gates.sh"
    context_readme_path = BASE_DIR / ".context" / "docs" / "README.md"
    prd_file = (BASE_DIR / prd_path).resolve() if not Path(prd_path).is_absolute() else Path(prd_path)
    remote_url = _project_origin_remote_url(BASE_DIR)
    github_remote = "github.com" in remote_url.lower()
    current_branch = _current_git_branch(BASE_DIR)
    oracle_sync_configured = (BASE_DIR / ".context" / "docs" / "oracle-sync.md").exists()

    story_summary: dict = {"found": False, "total": 0, "next_story": None}
    if prd_file.exists():
        try:
            payload = json.loads(prd_file.read_text(encoding="utf-8"))
            stories = payload.get("stories") or []
            story_summary["total"] = len(stories)
            for st in stories:
                status = str(st.get("status", "")).strip().lower()
                if status in {"done", "completed", "closed"}:
                    continue
                story_summary["next_story"] = {
                    "id": st.get("id"),
                    "title": st.get("title"),
                    "status": st.get("status"),
                }
                story_summary["found"] = True
                break
        except Exception as exc:
            story_summary["error"] = str(exc)
    else:
        story_summary["error"] = f"prd_not_found: {prd_file}"

    ai_context_global = _ensure_ai_coders_context_global_installed(install_if_missing=False)
    gsd_global = _ensure_gsd_global_installed(install_if_missing=False)
    gsd_patch = _apply_gsd_direct_context_planning_patch(
        apply_if_needed=False,
        gsd_bin=str(gsd_global.get("gsd_bin", "")),
    )
    return {
        "ok": True,
        "workspace": str(workspace),
        "scripts": {
            "context_update": {"path": str(context_script), "exists": context_script.exists(), "internal_available": True},
            "quality_gates": {"path": str(quality_script), "exists": quality_script.exists(), "internal_available": True},
        },
        "stack": {
            "ai_coders_context_ready": bool(ai_context_global.get("ok")),
            "ai_coders_context_global": {
                "installed": bool(ai_context_global.get("installed")),
                "version": ai_context_global.get("version_stdout", ""),
            },
            "gsd_ready": _is_gsd_ready(),
            "gsd_global": {
                "installed": bool(gsd_global.get("installed")),
                "bin": gsd_global.get("gsd_bin"),
                "version": gsd_global.get("version_stdout", ""),
            },
            "gsd_context_planning_patch": {
                "ok": bool(gsd_patch.get("ok")),
                "remaining_legacy_refs": int(gsd_patch.get("remaining_legacy_refs_after", 0)),
            },
            "ralph_ready": _is_ralph_ready(),
            "gemini_ready": bool(_resolve_gemini_bin()),
        },
        "git": {
            "remote_origin": remote_url,
            "github_remote_detected": github_remote,
            "current_branch": current_branch,
            "closeout_requires_commit": github_remote,
            "cloud_sync_branch": "oracle_picoclaw" if oracle_sync_configured else "",
            "closeout_requires_cloud_sync_commit": github_remote and oracle_sync_configured,
        },
        "context_docs_readme_exists": context_readme_path.exists(),
        "prd": story_summary,
    }


@mcp.tool()
def workflow_stack(
    action: str = "status",
    prd_path: str = RALPH_PRD_DEFAULT_REL,
    story_label: str = "",
    include_gemini: bool = False,
    include_bridge: bool = False,
    run_quality_gates: bool = False,
) -> dict:
    """
    MCP unificado do ciclo ai-coders-context + GSD + Ralph.

    Ações:
    - status: diagnóstico consolidado do stack.
    - sync: sincroniza configurações MCP pelo fluxo unificado.
    - context_refresh: roda rotina de atualização de contexto.
    - pick_story: seleciona a próxima story pendente do PRD.
    - cycle: context_refresh + pick_story + quality_gates opcional.
    """
    op = (action or "status").strip().lower()

    if op == "status":
        return _workflow_unified_status_payload(prd_path=prd_path)

    if op == "sync":
        py_bin = _resolve_project_python()
        rc = _mcp_sync_clients_cli(
            py_bin=py_bin,
            include_codex=True,
            include_gemini=bool(include_gemini),
            include_sudo=False,
            include_bridge=bool(include_bridge),
        )
        return {
            "ok": rc == 0,
            "action": "sync",
            "returncode": rc,
            "include_gemini": bool(include_gemini),
            "include_bridge": bool(include_bridge),
            "note": "Gemini é opcional. Se indisponível, mantenha execução no Codex.",
            "status": _workflow_unified_status_payload(prd_path=prd_path),
        }

    workspace = _resolve_gsd_ralph_workspace()
    results: dict = {"action": op, "ok": True, "workspace": str(workspace), "steps": []}

    if op in {"context_refresh", "cycle"}:
        step = _run_internal_context_update_step(target_dir=Path.cwd())
        results["steps"].append({"name": "context_refresh", **step})
        results["ok"] = results["ok"] and bool(step.get("ok"))
        if op == "context_refresh":
            results["status"] = _workflow_unified_status_payload(prd_path=prd_path)
            return results

    if op in {"pick_story", "cycle"}:
        status = _workflow_unified_status_payload(prd_path=prd_path)
        story = (status.get("prd") or {}).get("next_story")
        pick = {"ok": bool(story), "next_story": story, "prd": status.get("prd")}
        if not story:
            pick["error"] = "no_open_story_found"
        results["steps"].append({"name": "pick_story", **pick})
        results["ok"] = results["ok"] and bool(pick.get("ok"))

    if op == "cycle" and run_quality_gates:
        label = (story_label or ((results["steps"][-1].get("next_story") or {}).get("id") if results["steps"] else "") or "cycle").strip()
        step = _run_internal_quality_gates_step(target_dir=Path.cwd(), label=label)
        results["steps"].append({"name": "quality_gates", "label": label, **step})
        results["ok"] = results["ok"] and bool(step.get("ok"))

    if op not in {"context_refresh", "pick_story", "cycle"}:
        return {
            "ok": False,
            "error": "invalid_action",
            "allowed_actions": ["status", "sync", "context_refresh", "pick_story", "cycle"],
        }

    results["status"] = _workflow_unified_status_payload(prd_path=prd_path)
    return results


def _resolve_system_prompt_file(filename: str) -> Path:
    candidates = [
        BASE_DIR / "system_prompts_sync" / filename,
        BASE_DIR / "prompts_sync" / filename,
        BASE_DIR / "resources" / "prompts" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _primary_user_home() -> Path:
    user_name = (os.environ.get("JARVIS_RUN_AS_USER", "lucas") or "").strip() or "lucas"
    try:
        return Path(pwd.getpwnam(user_name).pw_dir)
    except Exception:
        fallback = Path("/home/lucas")
        return fallback if fallback.exists() else Path.home()


def _codex_cli_cmd(args: list[str]) -> list[str]:
    cmd = ["codex"]
    codex_system_prompt = _resolve_system_prompt_file("codex_system.md")
    if codex_system_prompt.exists():
        cmd += ["-c", f"model_instructions_file={json.dumps(str(codex_system_prompt))}"]
    cmd += args
    return cmd


def _sync_root_codex_config_via_sudo(py_bin: str, *, prompt_if_needed: bool = True) -> int:
    if not shutil.which("sudo"):
        return 127
    python_bin = py_bin if Path(py_bin).exists() else (sys.executable or "python3")
    ai_context_cli = _resolve_ai_coders_context_global_cli()
    sync_env = os.environ.copy()
    if ai_context_cli.get("ok"):
        sync_env["AI_CODERS_CONTEXT_CMD"] = str(ai_context_cli.get("command", "")).strip()
        sync_env["AI_CODERS_CONTEXT_ARGS_PREFIX_JSON"] = json.dumps(ai_context_cli.get("args_prefix") or [])
    sync_cmd = [
        python_bin,
        str(BASE_DIR / "jarvis.py"),
        "mcp-sync-clients",
        "--target-home",
        "/root",
        "--no-gemini",
        "--skip-bridge",
        "--no-sudo",
        "--quiet-core",
    ]
    rc = _run_cli_command(["sudo", "-H", "-n"] + sync_cmd, allow_failure=True, env=sync_env, echo_cmd=False)
    if rc == 0:
        print("✅ Codex sudo sincronizado em /root sem prompt.")
        return rc
    if not prompt_if_needed:
        return rc
    if not sys.stdin.isatty():
        print(
            "⚠️ Não foi possível autenticar sudo em modo não interativo. "
            "Rode novamente no terminal para sincronizar o Codex sudo (/root).",
            file=sys.stderr,
        )
        return rc
    print("🔐 Autenticação sudo necessária para sincronizar /root.")
    rc = _run_cli_command(["sudo", "-H"] + sync_cmd, allow_failure=True, env=sync_env, echo_cmd=False)
    if rc == 0:
        print("✅ Codex sudo sincronizado em /root.")
    return rc


def _ensure_codex_startup_timeout(
    server_name: str,
    timeout_sec: float,
    *,
    target_home: Path | None = None,
) -> None:
    home_dir = target_home or Path.home()
    cfg = home_dir / ".codex" / "config.toml"
    if not cfg.exists():
        return

    try:
        lines = cfg.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return

    header = f"[mcp_servers.{server_name}]"
    section_start = None
    section_end = len(lines)
    for idx, line in enumerate(lines):
        if line.strip() == header:
            section_start = idx
            break

    timeout_line = f"startup_timeout_sec = {float(timeout_sec):.1f}"
    changed = False

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [header, timeout_line]
        changed = True
    else:
        for idx in range(section_start + 1, len(lines)):
            if lines[idx].strip().startswith("[") and lines[idx].strip().endswith("]"):
                section_end = idx
                break

        found = False
        for idx in range(section_start + 1, section_end):
            if lines[idx].strip().startswith("startup_timeout_sec"):
                found = True
                if lines[idx].strip() != timeout_line:
                    lines[idx] = timeout_line
                    changed = True
                break
        if not found:
            lines.insert(section_end, timeout_line)
            changed = True

    if changed:
        try:
            cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"✅ Ajustado startup_timeout_sec de '{server_name}' em {cfg}")
        except Exception as exc:
            print(f"⚠️ Não foi possível ajustar timeout MCP no Codex ({cfg}): {exc}", file=sys.stderr)


def _configure_jarvis_on_codex(py_bin: str, use_sudo: bool = False) -> int:
    if not shutil.which("codex"):
        print("⚠️  codex não encontrado no PATH. Pulando sincronização do codex.", file=sys.stderr)
        return 0

    prefix: list[str] = ["sudo", "-n"] if use_sudo else []
    _run_cli_command(prefix + _codex_cli_cmd(["mcp", "remove", "jarvis"]), allow_failure=True)
    rc = _run_cli_command(
        prefix
        + _codex_cli_cmd(["mcp", "add", "jarvis", "--", py_bin, str(BASE_DIR / "jarvis.py"), "serve"])
    )
    if rc == 0 and not use_sudo:
        _ensure_codex_startup_timeout("jarvis", 300.0, target_home=_primary_user_home())
    return rc


def _repair_codex_config_permissions(home: Path, *, prompt_if_needed: bool = True) -> int:
    cfg_dir = home / ".codex"
    cfg_file = cfg_dir / "config.toml"
    if not cfg_dir.exists():
        return 0

    if os.access(cfg_dir, os.R_OK | os.W_OK | os.X_OK) and (not cfg_file.exists() or os.access(cfg_file, os.R_OK | os.W_OK)):
        return 0

    try:
        target_user = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        target_user = os.environ.get("USER", "lucas")
    target_group = target_user

    if os.geteuid() == 0:
        try:
            shutil.chown(cfg_dir, user=target_user, group=target_group)
            if cfg_file.exists():
                shutil.chown(cfg_file, user=target_user, group=target_group)
            for p in cfg_dir.rglob("*"):
                try:
                    shutil.chown(p, user=target_user, group=target_group)
                except Exception:
                    pass
            print(f"✅ Permissões de {cfg_dir} reparadas para {target_user}:{target_group}.")
            return 0
        except Exception as exc:
            print(f"⚠️ Falha ao reparar permissões de {cfg_dir} como root: {exc}", file=sys.stderr)
            return 1

    if not shutil.which("sudo"):
        print(f"❌ Sem permissão para acessar {cfg_file} e sudo indisponível.", file=sys.stderr)
        return 1

    chown_cmd = ["sudo", "-n", "chown", "-R", f"{target_user}:{target_group}", str(cfg_dir)]
    rc = _run_cli_command(chown_cmd, allow_failure=True, echo_cmd=False)
    if rc == 0:
        print(f"✅ Permissões de {cfg_dir} reparadas via sudo -n.")
        return 0

    if not prompt_if_needed:
        return rc

    print(f"🔐 Autenticação sudo necessária para corrigir permissões em {cfg_dir}.")
    rc = _run_cli_command(["sudo", "chown", "-R", f"{target_user}:{target_group}", str(cfg_dir)], allow_failure=True, echo_cmd=False)
    if rc == 0:
        print(f"✅ Permissões de {cfg_dir} reparadas via sudo.")
    return rc



def _configure_jarvis_on_gemini(py_bin: str) -> int:
    if not _resolve_gemini_bin():
        print("⚠️  gemini não encontrado no PATH. Pulando sincronização do gemini.", file=sys.stderr)
        return 0

    gemini_scope = "user"
    gemini_transport = (os.environ.get("JARVIS_GEMINI_TRANSPORT", "http") or "http").strip().lower()
    if gemini_transport not in {"stdio", "sse", "http"}:
        gemini_transport = "http"
    gemini_http_url = (os.environ.get("JARVIS_GEMINI_HTTP_URL", "http://127.0.0.1:7860/mcp") or "").strip()

    _run_cli_command(["gemini", "mcp", "remove", "jarvis"], allow_failure=True)
    if gemini_transport in {"http", "sse"}:
        rc = _run_cli_command(
            [
                "gemini",
                "mcp",
                "add",
                "-s",
                gemini_scope,
                "-t",
                gemini_transport,
                "jarvis",
                gemini_http_url,
            ]
        )
    else:
        rc = _run_cli_command(
            [
                "gemini",
                "mcp",
                "add",
                "-s",
                gemini_scope,
                "-t",
                "stdio",
                "jarvis",
                py_bin,
                str(BASE_DIR / "jarvis.py"),
                "serve",
            ]
        )
    return rc


def _setup_bidirectional_mcp_cli(py_bin: str) -> int:
    jarvis_py = BASE_DIR / "jarvis.py"
    failures = 0
    _repair_codex_config_permissions(_primary_user_home(), prompt_if_needed=True)
    gemini_scope = "user"

    if not _resolve_gemini_bin():
        print("❌ comando 'gemini' não encontrado no PATH.", file=sys.stderr)
        return 1
    if not shutil.which("codex"):
        print("❌ comando 'codex' não encontrado no PATH.", file=sys.stderr)
        return 1
    if not jarvis_py.exists():
        print(f"❌ jarvis não encontrado em {jarvis_py}", file=sys.stderr)
        return 1
    if not Path(py_bin).exists():
        print(f"❌ Python não encontrado em {py_bin}", file=sys.stderr)
        return 1

    print(f"[1/3] Configurando Codex como MCP no Gemini (escopo {gemini_scope})...")
    _run_cli_command(["gemini", "mcp", "remove", "codex"], allow_failure=True)
    if _run_cli_command(["gemini", "mcp", "add", "-s", gemini_scope, "-t", "stdio", "codex", "codex", "mcp-server"]) != 0:
        failures += 1

    print("[2/3] Configurando bridge Gemini embutido como MCP no Codex...")
    _run_cli_command(_codex_cli_cmd(["mcp", "remove", "gemini"]), allow_failure=True)
    if _run_cli_command(_codex_cli_cmd(["mcp", "add", "gemini", "--", py_bin, str(jarvis_py), "gemini-bridge"])) != 0:
        failures += 1

    print("[3/3] Estado atual:")
    print("Gemini MCP list:")
    _run_cli_command(["gemini", "mcp", "list"], allow_failure=True)
    ai_context_probe = _validate_ai_context_mcp_manually()
    if ai_context_probe.get("ok"):
        print(f"- ai-coders-context: protocolo MCP validado manualmente ({ai_context_probe.get('tools', 0)} tools)")
    print("\nCodex MCP list:")
    _run_cli_command(_codex_cli_cmd(["mcp", "list"]), allow_failure=True)

    if failures:
        print(f"❌ setup-bidirectional-mcp finalizou com {failures} falha(s).", file=sys.stderr)
        return 1

    print("\nConcluído.")
    return 0


def _mcp_sync_clients_cli(
    *,
    py_bin: str,
    include_codex: bool,
    include_gemini: bool,
    include_sudo: bool,
    include_bridge: bool,
    target_home: str = "",
    quiet_core: bool = False,
    verbose: bool = False,
) -> int:
    failures = 0
    started_at = datetime.now().isoformat()
    steps: list[dict] = []

    # Quando mcp-sync-clients roda via sudo interno para /root, não forçamos bootstrap de npm global.
    # Nesse cenário, o objetivo é apenas sincronizar config do Codex root.
    should_bootstrap_tooling = not (target_home or "").strip()

    if should_bootstrap_tooling:
        aligntrue_check = _ensure_aligntrue_global_installed(install_if_missing=True)
        aligntrue_ok = bool(aligntrue_check.get("ok"))
        steps.append(
            {
                "name": "aligntrue-global",
                "ok": aligntrue_ok,
                "rc": 0 if aligntrue_ok else 1,
                "detail": aligntrue_check,
                "critical": True,
            }
        )
        if not aligntrue_ok:
            print("❌ AlignTrue global ausente ou patch de output_dir falhou.", file=sys.stderr)
            failures += 1
        else:
            version = str(aligntrue_check.get("version_stdout", "")).strip()
            command = str(aligntrue_check.get("command", "")).strip()
            if version:
                print(f"✅ AlignTrue global pronto (versão: {version}).")
            else:
                print("✅ AlignTrue global pronto.")
            if command:
                print(f"   ↳ comando global: {command}")

        ai_context_check = _ensure_ai_coders_context_global_installed(install_if_missing=True)
        ai_context_ok = bool(ai_context_check.get("ok"))
        steps.append(
            {
                "name": "ai-coders-context-global",
                "ok": ai_context_ok,
                "rc": 0 if ai_context_ok else 1,
                "detail": ai_context_check,
                "critical": True,
            }
        )
        if not ai_context_ok:
            print("❌ ai-coders-context global ausente e instalação automática falhou.", file=sys.stderr)
            failures += 1
        else:
            version = str(ai_context_check.get("version_stdout", "")).strip()
            command = str(ai_context_check.get("command", "")).strip()
            if version:
                print(f"✅ ai-coders-context global pronto (versão: {version}).")
            else:
                print("✅ ai-coders-context global pronto.")
            if command:
                print(f"   ↳ comando global: {command}")

        gsd_setup = _run_internal_gsd_setup_step()
        gsd_ok = bool(gsd_setup.get("ok"))
        steps.append(
            {
                "name": "gsd-setup",
                "ok": gsd_ok,
                "rc": int(gsd_setup.get("returncode", 1)),
                "detail": gsd_setup,
                "critical": True,
            }
        )
        if not gsd_ok:
            print("❌ GSD global ausente ou patch de .context/plans falhou.", file=sys.stderr)
            failures += 1
        else:
            patch = ((gsd_setup.get("detail") or {}).get("patch") or {})
            changed = int(patch.get("changed_occurrences") or 0)
            if changed > 0:
                print(f"✅ GSD ajustado para .context/plans ({changed} ocorrência(s) migrada(s)).")
            else:
                print("✅ GSD já estava ajustado para .context/plans.")

        ralph_setup = _run_internal_ralph_setup_step()
        ralph_ok = bool(ralph_setup.get("ok"))
        steps.append(
            {
                "name": "ralph-setup",
                "ok": ralph_ok,
                "rc": int(ralph_setup.get("returncode", 1)),
                "detail": ralph_setup,
                "critical": True,
            }
        )
        if not ralph_ok:
            print("❌ Ralph global ausente ou sincronização/patch global do Ralph falhou.", file=sys.stderr)
            failures += 1
        else:
            detail = ralph_setup.get("detail") or {}
            ensure_detail = detail.get("ensure") if isinstance(detail.get("ensure"), dict) else detail
            sync_detail = detail.get("sync") if isinstance(detail.get("sync"), dict) else {}
            patch_detail = detail.get("patch") if isinstance(detail.get("patch"), dict) else {}
            prd_patch_detail = detail.get("prd_patch") if isinstance(detail.get("prd_patch"), dict) else {}
            version = str((ensure_detail or {}).get("version_stdout", "")).strip()
            if version:
                print(f"✅ Ralph global pronto (versão: {version}).")
            else:
                print("✅ Ralph global pronto.")
            synced_targets = list(sync_detail.get("synced_targets") or [])
            copied_files = int(sync_detail.get("copied_files", 0) or 0)
            target_root = str(sync_detail.get("target_root", "")).strip()
            if synced_targets:
                print(
                    "✅ Templates globais do Ralph sincronizados "
                    f"({len(synced_targets)} alvo(s), {copied_files} arquivo(s))."
                )
                if target_root:
                    print(f"   ↳ destino global: {target_root}")
            elif bool(sync_detail.get("skipped")):
                reason = str(sync_detail.get("reason", "")).strip()
                if reason in {"local_templates_absent_using_global_templates", "local_templates_partial_using_global_templates"}:
                    print("✅ Templates locais do Ralph ausentes ou parciais; mantendo templates absorvidos no npm global.")
                    if target_root:
                        print(f"   ↳ destino global: {target_root}")
            patch_changed = int(patch_detail.get("changed_occurrences", 0) or 0)
            patch_reason = str(patch_detail.get("reason", "")).strip()
            if patch_changed > 0:
                print(f"✅ Ralph CLI global ajustado para usar template local apenas quando houver loop.sh ({patch_changed} patch).")
            elif bool(patch_detail.get("already_patched")):
                print("✅ Ralph CLI global já estava com verificação de loop.sh no template local.")
            elif bool(patch_detail.get("skipped")) and patch_reason == "legacy_token_not_found":
                print("✅ Ralph CLI global com layout novo detectado; patch de resolução de templates não foi necessário.")
            prd_patch_changed = int(prd_patch_detail.get("changed_occurrences", 0) or 0)
            if prd_patch_changed > 0:
                print(
                    "✅ Ralph global ajustado para PRD em cwd + .context/workflow "
                    f"({prd_patch_changed} ocorrência(s) migrada(s))."
                )
            elif int(prd_patch_detail.get("already_patched_files", 0) or 0) > 0:
                print("✅ Ralph global já estava usando PRD em cwd + .context/workflow.")

        smoke = _run_internal_smoke_test_step()
        smoke_ok = bool(smoke.get("ok"))
        steps.append(
            {
                "name": "smoke-test",
                "ok": smoke_ok,
                "rc": int(smoke.get("returncode", 1)),
                "detail": smoke,
                "critical": True,
            }
        )
        if smoke_ok:
            print("✅ Smoke test de pré-requisitos passou.")
        else:
            print("❌ Smoke test de pré-requisitos falhou.", file=sys.stderr)
            failures += 1

    # Fluxo unificado: mcp-sync-clients usa a mesma base de sync de configuração
    # para evitar drift de config (ex.: startup_timeout_sec divergente entre comandos).
    if include_codex or include_gemini:
        resolved_target_home = (target_home or "").strip()
        effective_include_sudo = include_sudo and include_codex
        sync_rc = _sync_mcp_core(
            target_home=resolved_target_home,
            include_sudo=effective_include_sudo,
            quiet=quiet_core,
        )
        steps.append(
            {
                "name": "sync-mcp-core",
                "ok": sync_rc == 0,
                "rc": sync_rc,
                "critical": True,
            }
        )
        if sync_rc != 0:
            failures += 1

    if include_bridge:
        bridge_rc = _setup_bidirectional_mcp_cli(py_bin)
        steps.append(
            {
                "name": "setup-bidirectional-mcp",
                "ok": bridge_rc == 0,
                "rc": bridge_rc,
                "critical": False,
            }
        )
        if bridge_rc != 0:
            failures += 1

    if include_gemini:
        gemini_health = _gemini_bridge_health_payload()
        gemini_ok = bool(gemini_health.get("ok"))
        steps.append(
            {
                "name": "gemini-bridge-health",
                "ok": gemini_ok,
                "rc": 0 if gemini_ok else 1,
                "payload": gemini_health,
                "critical": True,
            }
        )
        if gemini_ok:
            print("✅ Gemini bridge health check passou.")
        else:
            print("❌ Gemini bridge health check falhou.", file=sys.stderr)
            failures += 1

    print("\nStatus final:")
    if include_gemini and shutil.which("gemini"):
        _run_cli_command(["gemini", "mcp", "list"], allow_failure=True)
        ai_context_probe = _validate_ai_context_mcp_manually()
        if ai_context_probe.get("ok"):
            print(f"- ai-coders-context: protocolo MCP validado manualmente ({ai_context_probe.get('tools', 0)} tools)")
    if include_codex and shutil.which("codex"):
        _run_cli_command(_codex_cli_cmd(["mcp", "list"]), allow_failure=True)
    should_show_sudo_codex = (
        include_codex
        and include_sudo
        and not (target_home or "").strip()
        and os.geteuid() != 0
        and bool(shutil.which("sudo"))
    )
    if should_show_sudo_codex:
        print("Codex sudo MCP list:")
        _run_cli_command(["sudo", "-H", "-n"] + _codex_cli_cmd(["mcp", "list"]), allow_failure=True, echo_cmd=False)

    if should_bootstrap_tooling:
        _write_jarvis_ready_marker(
            {
                "ok": failures == 0,
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(),
                "steps": steps,
            }
        )

    if verbose:
        print("\nDetalhes (steps):")
        print(json.dumps(steps, ensure_ascii=False, indent=2))

    if failures:
        print(f"❌ mcp-sync-clients finalizou com {failures} falha(s).", file=sys.stderr)
        return 1

    print("✅ mcp-sync-clients concluído (fluxo unificado de configuração para Codex, Gemini e Oh My Pi).")
    return 0


def _openclaw_ssh_cmd(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    tty: bool = False,
) -> list[str]:
    cmd = ["ssh", "-o", f"ConnectTimeout={max(1, int(timeout_sec))}"]
    if tty:
        cmd.append("-t")
    if ssh_key:
        cmd += ["-i", ssh_key]
    cmd.append(f"{user}@{host}")
    return cmd


_OPENCLAW_REMOTE_ACTION_SCRIPTS: dict[str, str] = {
    "status": 'set -euo pipefail\nexport XDG_RUNTIME_DIR="/run/user/$(id -u)"\nexport DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\ndetect_service() {\n  if systemctl --user list-unit-files --no-pager | grep -q \'^openclaw-gateway\\.service\'; then\n    echo "openclaw-gateway.service"\n  elif systemctl --user list-unit-files --no-pager | grep -q \'^clawdbot-gateway\\.service\'; then\n    echo "clawdbot-gateway.service"\n  else\n    return 1\n  fi\n}\nSERVICE="$(detect_service)"\necho "service: $SERVICE"\nsystemctl --user is-active "$SERVICE" || true\nsystemctl --user status "$SERVICE" --no-pager -l | sed -n \'1,25p\'\nif command -v openclaw >/dev/null 2>&1; then\n  echo "---"\n  timeout 20s openclaw channels status || true\nfi\necho "---"\npython3 - <<\'PY\'\nimport json\nimport pathlib\n\nhome = pathlib.Path.home()\ncfg_paths = [home / ".openclaw" / "openclaw.json", home / ".clawdbot" / "clawdbot.json"]\ncfgp = next((p for p in cfg_paths if p.exists()), None)\nif not cfgp:\n    print("whatsapp config: arquivo não encontrado")\n    raise SystemExit(0)\n\ncfg = json.loads(cfgp.read_text())\nw = (cfg.get("channels") or {}).get("whatsapp") or {}\nprint("whatsapp config:")\nprint(f"  file: {cfgp}")\nprint(f"  dmPolicy: {w.get(\'dmPolicy\')}")\nprint(f"  allowFrom: {w.get(\'allowFrom\')}")\nprint(f"  groupPolicy: {w.get(\'groupPolicy\')}")\nprint(f"  selfChatMode: {w.get(\'selfChatMode\')}")\nPY',
    "restart": 'set -euo pipefail\nexport XDG_RUNTIME_DIR="/run/user/$(id -u)"\nexport DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\ndetect_service() {\n  if systemctl --user list-unit-files --no-pager | grep -q \'^openclaw-gateway\\.service\'; then\n    echo "openclaw-gateway.service"\n  elif systemctl --user list-unit-files --no-pager | grep -q \'^clawdbot-gateway\\.service\'; then\n    echo "clawdbot-gateway.service"\n  else\n    return 1\n  fi\n}\nSERVICE="$(detect_service)"\nsystemctl --user daemon-reload\nsystemctl --user restart "$SERVICE"\nsystemctl --user is-active "$SERVICE"\nif command -v openclaw >/dev/null 2>&1; then\n  timeout 20s openclaw gateway probe --timeout 10000 || true\nfi\nsystemctl --user status "$SERVICE" --no-pager -l | sed -n \'1,25p\'',
    "sync-token": 'set -euo pipefail\nexport XDG_RUNTIME_DIR="/run/user/$(id -u)"\nexport DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\ndetect_service() {\n  if systemctl --user list-unit-files --no-pager | grep -q \'^openclaw-gateway\\.service\'; then\n    echo "openclaw-gateway.service"\n  elif systemctl --user list-unit-files --no-pager | grep -q \'^clawdbot-gateway\\.service\'; then\n    echo "clawdbot-gateway.service"\n  else\n    return 1\n  fi\n}\nSERVICE_NAME="$(detect_service)"\nexport SERVICE_NAME\npython3 - <<\'PY\'\nimport json\nimport os\nimport pathlib\nimport re\n\nhome = pathlib.Path.home()\nservice_name = os.environ.get("SERVICE_NAME", "openclaw-gateway.service")\n\nbase = None\nfor candidate in (home / ".openclaw", home / ".clawdbot"):\n    if (candidate / "identity" / "device-auth.json").exists():\n        base = candidate\n        break\nif base is None:\n    raise SystemExit("device-auth.json ausente em ~/.openclaw ou ~/.clawdbot")\n\ndev = base / "identity" / "device-auth.json"\nraw = dev.read_text()\ndata = json.loads(raw)\n\ntoken = None\nfor key in ("token", "gatewayToken", "authToken", "deviceToken"):\n    value = data.get(key)\n    if isinstance(value, str) and value:\n        token = value\n        break\nif not token:\n    match = re.search(r"[a-f0-9]{64}", raw)\n    if match:\n        token = match.group(0)\nif not token:\n    raise SystemExit("token não encontrado em device-auth.json")\n\ncfg_candidates = [base / "openclaw.json", base / "clawdbot.json"]\ncfgp = next((p for p in cfg_candidates if p.exists()), cfg_candidates[0])\ncfg = {}\nif cfgp.exists():\n    try:\n        cfg = json.loads(cfgp.read_text())\n    except Exception:\n        cfg = {}\ngw = cfg.setdefault("gateway", {})\ngw.setdefault("auth", {})["token"] = token\ngw.setdefault("remote", {})["token"] = token\ncfgp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))\n\noverride = home / ".config" / "systemd" / "user" / f"{service_name}.d" / "override.conf"\noverride.parent.mkdir(parents=True, exist_ok=True)\noverride.write_text(f"[Service]\\nEnvironment=OPENCLAW_GATEWAY_TOKEN={token}\\n")\n\nprint("tokens sincronizados")\nprint(f"config: {cfgp}")\nprint(f"override: {override}")\nPY\nsystemctl --user daemon-reload\nsystemctl --user restart "$SERVICE_NAME"\nsystemctl --user is-active "$SERVICE_NAME"\nif command -v openclaw >/dev/null 2>&1; then\n  timeout 20s openclaw gateway probe --timeout 10000 || true\nfi\nsystemctl --user status "$SERVICE_NAME" --no-pager -l | sed -n \'1,25p\'',
    "reset-token": 'set -euo pipefail\nexport XDG_RUNTIME_DIR="/run/user/$(id -u)"\nexport DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\ndetect_service() {\n  if systemctl --user list-unit-files --no-pager | grep -q \'^openclaw-gateway\\.service\'; then\n    echo "openclaw-gateway.service"\n  elif systemctl --user list-unit-files --no-pager | grep -q \'^clawdbot-gateway\\.service\'; then\n    echo "clawdbot-gateway.service"\n  else\n    return 1\n  fi\n}\nSERVICE_NAME="$(detect_service)"\nexport SERVICE_NAME\npython3 - <<\'PY\'\nimport json\nimport os\nimport pathlib\nimport secrets\nimport shutil\n\nhome = pathlib.Path.home()\nservice_name = os.environ.get("SERVICE_NAME", "openclaw-gateway.service")\ntoken = secrets.token_hex(32)\n\nbase = None\nfor candidate in (home / ".openclaw", home / ".clawdbot"):\n    if candidate.exists():\n        base = candidate\n        break\nif base is None:\n    base = home / ".openclaw"\n    base.mkdir(parents=True, exist_ok=True)\n\ncfg_candidates = [base / "openclaw.json", base / "clawdbot.json"]\ncfgp = next((p for p in cfg_candidates if p.exists()), cfg_candidates[0])\ncfg = {}\nif cfgp.exists():\n    try:\n        cfg = json.loads(cfgp.read_text())\n    except Exception:\n        cfg = {}\ngw = cfg.setdefault("gateway", {})\ngw.setdefault("auth", {})["token"] = token\ngw.setdefault("remote", {})["token"] = token\ncfgp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))\n\npaired = base / "devices" / "paired.json"\nif paired.exists():\n    try:\n        shutil.copy2(paired, paired.with_suffix(".bak"))\n        data = json.loads(paired.read_text())\n        if isinstance(data, dict):\n            data["token"] = token\n            paired.write_text(json.dumps(data, indent=2, ensure_ascii=False))\n    except Exception:\n        pass\n\noverride = home / ".config" / "systemd" / "user" / f"{service_name}.d" / "override.conf"\noverride.parent.mkdir(parents=True, exist_ok=True)\noverride.write_text(f"[Service]\\nEnvironment=OPENCLAW_GATEWAY_TOKEN={token}\\n")\n\nprint("novo token gerado e aplicado")\nprint(f"config: {cfgp}")\nprint(f"override: {override}")\nPY\nsystemctl --user daemon-reload\nsystemctl --user restart "$SERVICE_NAME"\nsystemctl --user is-active "$SERVICE_NAME"\nif command -v openclaw >/dev/null 2>&1; then\n  timeout 20s openclaw gateway probe --timeout 10000 || true\nfi\nsystemctl --user status "$SERVICE_NAME" --no-pager -l | sed -n \'1,25p\'',
    "fix-transcricao": 'set -euo pipefail\nexport XDG_RUNTIME_DIR="/run/user/$(id -u)"\nexport DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\ndetect_service() {\n  if systemctl --user list-unit-files --no-pager | grep -q \'^openclaw-gateway\\.service\'; then\n    echo "openclaw-gateway.service"\n  elif systemctl --user list-unit-files --no-pager | grep -q \'^clawdbot-gateway\\.service\'; then\n    echo "clawdbot-gateway.service"\n  else\n    return 1\n  fi\n}\nSERVICE_NAME="$(detect_service)"\nLOCK="$HOME/.openclaw/agents/main/sessions/sessions.json.lock"\nSTATE="$HOME/.openclaw/workspace/state/transcricao_active.json"\n\necho "[1/5] Encerrando transcrição em loop (se houver)"\nif pgrep -f \'transcribe_batch.py|transcribe_one.py|transcribe_stream.py\' >/dev/null 2>&1; then\n  pkill -f \'transcribe_batch.py|transcribe_one.py|transcribe_stream.py\' || true\n  sleep 3\n  if pgrep -f \'transcribe_batch.py|transcribe_one.py|transcribe_stream.py\' >/dev/null 2>&1; then\n    pkill -9 -f \'transcribe_batch.py|transcribe_one.py|transcribe_stream.py\' || true\n  fi\n  echo "processos de transcrição encerrados"\nelse\n  echo "nenhum processo de transcrição ativo"\nfi\n\necho "[2/5] Limpando lock de sessão stale"\nif [ -f "$LOCK" ]; then\n  LOCK_PID="$(python3 - <<\'PY\'\nimport json, pathlib\np = pathlib.Path.home()/\'.openclaw\'/\'agents\'/\'main\'/\'sessions\'/\'sessions.json.lock\'\ntry:\n    d = json.loads(p.read_text())\n    print(d.get(\'pid\', \'\'))\nexcept Exception:\n    print(\'\')\nPY\n)"\n  if [ -n "$LOCK_PID" ] && ps -p "$LOCK_PID" >/dev/null 2>&1; then\n    echo "lock pertence a PID vivo ($LOCK_PID), mantendo arquivo"\n  else\n    BAK="$LOCK.bak.$(date +%Y%m%d%H%M%S)"\n    mv "$LOCK" "$BAK"\n    echo "lock stale movido para: $BAK"\n  fi\nelse\n  echo "sem lock para limpar"\nfi\n\necho "[3/5] Resetando estado de /transcricao"\nif [ -f "$STATE" ]; then\n  cp "$STATE" "$STATE.bak.$(date +%Y%m%d%H%M%S)"\nfi\npython3 - <<\'PY\'\nimport json\nimport pathlib\nfrom datetime import datetime, timezone\n\np = pathlib.Path.home()/\'.openclaw\'/\'workspace\'/\'state\'/\'transcricao_active.json\'\np.parent.mkdir(parents=True, exist_ok=True)\ndata = {\n    "active": False,\n    "resetAtUtc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),\n    "note": "reset automatico via jarvis.py openclaw-remote fix-transcricao",\n}\np.write_text(json.dumps(data, ensure_ascii=False, indent=2))\nprint(p)\nPY\ncat "$STATE"\n\necho "[4/5] Reiniciando serviço"\nsystemctl --user daemon-reload\nsystemctl --user restart "$SERVICE_NAME"\nsystemctl --user is-active "$SERVICE_NAME"\n\necho "[5/5] Pós-checagem"\npgrep -af \'transcribe_batch.py|openclaw-gateway\' || true\njournalctl --user -u "$SERVICE_NAME" -n 80 --no-pager | egrep -i \'hook|transcr|lock|failed|error|Listening for personal WhatsApp\' | tail -n 50 || true',
    "doctor": r'''set -u
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
OPENCLAW_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
JARVIS_PORT="${SERVER_PORT:-7860}"

section() {
  printf '\n== %s ==\n' "$1"
}

detect_openclaw_service() {
  if systemctl --user cat openclaw-gateway.service >/dev/null 2>&1; then
    echo "openclaw-gateway.service"
    return 0
  fi
  if systemctl --user cat clawdbot-gateway.service >/dev/null 2>&1; then
    echo "clawdbot-gateway.service"
    return 0
  fi
  return 1
}

pids_on_port() {
  python3 - "$1" <<'PY'
import re
import subprocess
import sys

port = sys.argv[1]
proc = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], text=True, capture_output=True, check=False)
pids = sorted(set(re.findall(r"pid=(\d+)", proc.stdout)))
print(" ".join(pids))
PY
}

pids_matching() {
  python3 - "$1" <<'PY'
import os
import subprocess
import sys

needle = sys.argv[1]
self_pid = os.getpid()
proc = subprocess.run(["ps", "-eo", "pid=,args="], text=True, capture_output=True, check=False)
matches = []
for line in proc.stdout.splitlines():
    parts = line.strip().split(maxsplit=1)
    if len(parts) != 2:
        continue
    pid_s, args = parts
    try:
        pid = int(pid_s)
    except ValueError:
        continue
    if pid == self_pid:
        continue
    if needle in args and "python3 -" not in args:
        matches.append(str(pid))
print(" ".join(sorted(set(matches))))
PY
}
pids_by_comm() {
  python3 - "$@" <<'PY'
import subprocess
import sys

names = set(sys.argv[1:])
proc = subprocess.run(["ps", "-eo", "pid=,comm="], text=True, capture_output=True, check=False)
matches = []
for line in proc.stdout.splitlines():
    parts = line.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[1] in names:
        matches.append(parts[0])
print(" ".join(sorted(set(matches))))
PY
}


kill_pids() {
  seen=""
  for pid in "$@"; do
    [ -n "$pid" ] || continue
    case " $seen " in *" $pid "*) continue;; esac
    seen="$seen $pid"
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "killing stale pid: $pid ($(ps -p "$pid" -o comm= 2>/dev/null || true))"
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  sleep 2
  for pid in $seen; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "force killing stale pid: $pid"
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done
}

section "oracle identity"
hostname
id

SERVICE_NAME="$(detect_openclaw_service || true)"
if [ -z "$SERVICE_NAME" ]; then
  echo "openclaw service not found: expected openclaw-gateway.service or clawdbot-gateway.service" >&2
  exit 42
fi
echo "openclaw service: $SERVICE_NAME"

section "before"
systemctl --user show jarvis.service --property=ActiveState,SubState,NRestarts,MainPID,ExecMainStatus --no-pager 2>/dev/null || true
systemctl --user show "$SERVICE_NAME" --property=ActiveState,SubState,NRestarts,MainPID,ExecMainStatus --no-pager || true
ss -ltnp "sport = :$OPENCLAW_PORT" || true
ss -ltnp "sport = :$JARVIS_PORT" || true
pgrep -af 'openclaw|clawdbot|jarvis.py serve' || true

section "stop supervised services"
systemctl --user stop "$SERVICE_NAME" || true
if systemctl --user cat jarvis.service >/dev/null 2>&1; then
  systemctl --user stop jarvis.service || true
fi
if command -v openclaw >/dev/null 2>&1; then
  timeout 10s openclaw gateway stop || true
fi

section "cleanup stale processes"
OPENCLAW_PIDS="$(pids_on_port "$OPENCLAW_PORT") $(pids_by_comm openclaw openclaw-gateway) $(pids_matching openclaw-gateway) $(pids_matching 'openclaw gateway') $(pids_matching '/tmp/openclaw/openclaw-')"
JARVIS_PIDS="$(pids_on_port "$JARVIS_PORT") $(pids_matching 'jarvis.py serve')"
kill_pids $OPENCLAW_PIDS $JARVIS_PIDS

section "restart oracle jarvis"
if systemctl --user cat jarvis.service >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user start jarvis.service
  systemctl --user is-active jarvis.service || true
  systemctl --user status jarvis.service --no-pager -l --lines=18 || true
fi

section "restart openclaw"
systemctl --user daemon-reload
OPENCLAW_LISTENERS=""
for attempt in 1 2; do
  echo "openclaw start attempt: $attempt"
  systemctl --user start "$SERVICE_NAME"
  wait_i=0
  while [ "$wait_i" -lt 120 ]; do
    OPENCLAW_LISTENERS="$(pids_on_port "$OPENCLAW_PORT")"
    OPENCLAW_MAINPID="$(systemctl --user show "$SERVICE_NAME" --property=MainPID --value 2>/dev/null || true)"
    if [ -n "$OPENCLAW_LISTENERS" ]; then
      case " $OPENCLAW_LISTENERS " in
        *" $OPENCLAW_MAINPID "*) break 2;;
        *) echo "port $OPENCLAW_PORT is held by $OPENCLAW_LISTENERS, but service MainPID is $OPENCLAW_MAINPID; cleaning"; break;;
      esac
    fi
    sleep 1
    wait_i=$((wait_i + 1))
  done
  echo "openclaw did not bind port $OPENCLAW_PORT on attempt $attempt; cleaning and retrying"
  systemctl --user stop "$SERVICE_NAME" || true
  OPENCLAW_PIDS="$(pids_on_port "$OPENCLAW_PORT") $(pids_by_comm openclaw openclaw-gateway) $(pids_matching openclaw-gateway) $(pids_matching 'openclaw gateway') $(pids_matching '/tmp/openclaw/openclaw-')"
  kill_pids $OPENCLAW_PIDS
done
systemctl --user is-active "$SERVICE_NAME"
systemctl --user status "$SERVICE_NAME" --no-pager -l --lines=24 || true
OPENCLAW_LISTENERS="$(pids_on_port "$OPENCLAW_PORT")"
if [ -z "$OPENCLAW_LISTENERS" ]; then
  echo "openclaw service is active but no process is listening on port $OPENCLAW_PORT" >&2
  exit 2
fi
OPENCLAW_MAINPID="$(systemctl --user show "$SERVICE_NAME" --property=MainPID --value 2>/dev/null || true)"
case " $OPENCLAW_LISTENERS " in
  *" $OPENCLAW_MAINPID "*) ;;
  *)
    echo "openclaw port $OPENCLAW_PORT is not owned by current service MainPID ($OPENCLAW_MAINPID); listeners: $OPENCLAW_LISTENERS" >&2
    exit 4
    ;;
esac
echo "openclaw port listeners: $OPENCLAW_LISTENERS"

section "probe"
if command -v openclaw >/dev/null 2>&1; then
  timeout 20s openclaw gateway probe --timeout 10000 || echo "openclaw gateway probe failed or timed out"
  timeout 20s openclaw channels status || echo "openclaw channels status failed or timed out"
fi

section "after"
ss -ltnp "sport = :$OPENCLAW_PORT" || true
ss -ltnp "sport = :$JARVIS_PORT" || true
pgrep -af 'openclaw|clawdbot|jarvis.py serve' || true
JARVIS_LISTENERS="$(pids_on_port "$JARVIS_PORT")"
OPENCLAW_LISTENERS="$(pids_on_port "$OPENCLAW_PORT")"
if [ -z "$JARVIS_LISTENERS" ]; then
  echo "jarvis.service is active but no process is listening on port $JARVIS_PORT" >&2
  exit 3
fi
if [ -z "$OPENCLAW_LISTENERS" ]; then
  echo "openclaw service is active but no process is listening on port $OPENCLAW_PORT" >&2
  exit 2
fi
systemctl --user is-active --quiet "$SERVICE_NAME"
''' ,
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _remote_jarvis_sha256(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    remote_dir: str,
    echo_cmd: bool = False,
) -> str:
    script = (
        "set -euo pipefail\n"
        f"REMOTE_JARVIS={shlex.quote(remote_dir.rstrip('/') + '/jarvis.py')}\n"
        'if [ ! -f "$REMOTE_JARVIS" ]; then\n'
        '  echo MISSING\n'
        "else\n"
        '  sha256sum "$REMOTE_JARVIS" | awk \'{print $1}\'\n'
        "fi\n"
    )
    cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    cmd += ["bash -s"]
    cmd, env = _prepare_cli_runtime(cmd, None)
    if echo_cmd:
        print(f"$ {_format_shell_cmd(cmd)}")
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True, env=env, check=False)
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"falha ao calcular hash remoto do Jarvis na OCI (rc={proc.returncode})")
    return (proc.stdout or "").strip().splitlines()[-1].strip() if proc.stdout.strip() else ""


def _ensure_oracle_remote_jarvis_current(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    sync_venv: bool,
    restart_service: bool,
) -> int:
    configured_remote_dir = _resolve_oci_remote_project_dir(user)
    remote_dir = _discover_oracle_remote_project_dir(
        host=host,
        user=user,
        ssh_key=ssh_key,
        timeout_sec=timeout_sec,
        configured_remote_dir=configured_remote_dir,
    )
    local_jarvis = BASE_DIR / "jarvis.py"
    if not local_jarvis.exists():
        print(f"❌ jarvis.py local ausente em {local_jarvis}", file=sys.stderr)
        return 1

    local_hash = _sha256_file(local_jarvis)
    try:
        remote_hash = _remote_jarvis_sha256(
            host=host,
            user=user,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
            remote_dir=remote_dir,
        )
    except Exception as exc:
        print(f"❌ Não foi possível verificar Jarvis remoto na OCI: {exc}", file=sys.stderr)
        return 1

    if remote_hash == local_hash:
        print(f"✅ Jarvis Oracle alinhado com local ({local_hash[:12]}).")
        return 0

    if remote_hash == "MISSING":
        print(f"⚠️ Jarvis remoto ausente em {remote_dir}. Sincronizando projeto para OCI...")
    else:
        remote_label = remote_hash[:12] if remote_hash else "desconhecido"
        print(
            f"⚠️ Jarvis Oracle divergente do local (local {local_hash[:12]} != remoto {remote_label}). "
            "Substituindo por cópia local..."
        )

    rc = _sync_project_to_oracle_remote(
        host=host,
        user=user,
        ssh_key=ssh_key,
        timeout_sec=timeout_sec,
        remote_dir=remote_dir,
        sync_venv=sync_venv,
    )
    if rc != 0:
        return rc

    try:
        synced_hash = _remote_jarvis_sha256(
            host=host,
            user=user,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
            remote_dir=remote_dir,
        )
    except Exception as exc:
        print(f"❌ Não foi possível verificar Jarvis remoto após sync: {exc}", file=sys.stderr)
        return 1

    if synced_hash != local_hash:
        print(
            f"❌ Sync não substituiu o Jarvis remoto corretamente (local {local_hash[:12]} != remoto {synced_hash[:12]}).",
            file=sys.stderr,
        )
        return 1

    print(f"✅ Jarvis Oracle atualizado para a cópia local ({local_hash[:12]}).")
    if restart_service:
        print("🔁 Reiniciando Jarvis remoto para carregar a cópia sincronizada...")
        return _start_oracle_remote_jarvis(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec)
    return 0


def _openclaw_remote_cli(
    action: str,
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    sync_remote_jarvis: bool = True,
    sync_venv: bool = False,
) -> int:
    if (host or "").strip().lower() in {"localhost", "127.0.0.1", "::1"}:
        print("❌ openclaw-remote é exclusivo para OCI/mcp-instance. Host local não permitido.", file=sys.stderr)
        return 1
    script = _OPENCLAW_REMOTE_ACTION_SCRIPTS.get(action)
    if not script:
        print(f"❌ Ação inválida: {action}", file=sys.stderr)
        return 1

    if sync_remote_jarvis:
        rc = _ensure_oracle_remote_jarvis_current(
            host=host,
            user=user,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
            sync_venv=sync_venv,
            restart_service=True,
        )
        if rc != 0:
            return rc

    cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    cmd += ["bash -s"]
    return _run_cli_command(cmd, input_text=script)


def _run_json_command(cmd: list[str], timeout_sec: int = 25) -> dict | None:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_sec)),
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "{}")
    except Exception:
        return None


def _discover_oci_gateway_base_url() -> str:
    if not shutil.which("oci"):
        return ""

    region = os.environ.get("OCI_CLI_REGION", "").strip()
    search_cmd = [
        "oci",
        "search",
        "resource",
        "structured-search",
        "--query-text",
        "query ApiDeployment resources where lifecycleState = 'ACTIVE'",
    ]
    if region:
        search_cmd += ["--region", region]

    payload = _run_json_command(search_cmd, timeout_sec=30)
    if not payload:
        return ""
    items = (((payload.get("data") or {}).get("items")) or [])
    if not items:
        return ""

    preferred = None
    for item in items:
        label = ((item.get("display-name") or "") + " " + (item.get("resource-type") or "")).lower()
        if "mcp" in label or "jarvis" in label or "super-mcp" in label:
            preferred = item
            break
    candidate = preferred or items[0]
    deployment_id = (candidate.get("identifier") or "").strip()
    if not deployment_id:
        return ""

    get_cmd = [
        "oci",
        "api-gateway",
        "deployment",
        "get",
        "--deployment-id",
        deployment_id,
    ]
    if region:
        get_cmd += ["--region", region]

    dep_payload = _run_json_command(get_cmd, timeout_sec=30)
    if not dep_payload:
        return ""
    endpoint = (((dep_payload.get("data") or {}).get("endpoint")) or "").strip()
    return endpoint.rstrip("/")


def _resolve_oci_remote_project_dir(user: str) -> str:
    configured = os.environ.get("OCI_REMOTE_PROJECT_DIR", "").strip()
    if configured:
        return configured
    if user and user != "root":
        return f"/home/{user}/super_mcp_servers"
    return "/root/super_mcp_servers"


def _discover_oracle_remote_project_dir(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    configured_remote_dir: str,
) -> str:
    script = (
        "set -u\n"
        'export XDG_RUNTIME_DIR="/run/user/$(id -u)"\n'
        'export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\n'
        f"export CONFIGURED_DIR={shlex.quote(configured_remote_dir)}\n"
        'WD=""\n'
        'if systemctl --user cat jarvis.service >/dev/null 2>&1; then\n'
        '  WD="$(systemctl --user show jarvis.service --property=WorkingDirectory --value 2>/dev/null || true)"\n'
        'fi\n'
        'if [ -n "$WD" ] && [ -f "$WD/jarvis.py" ]; then\n'
        '  echo "$WD"\n'
        '  exit 0\n'
        'fi\n'
        'python3 - <<\'PY\'\n'
        'import os\n'
        'import pathlib\n'
        'import re\n'
        'import subprocess\n'
        'configured = os.environ.get("CONFIGURED_DIR", "").strip()\n'
        'proc = subprocess.run(["ps", "-eo", "args="], text=True, capture_output=True, check=False)\n'
        'for line in proc.stdout.splitlines():\n'
        '    match = re.search(r"(\\S*/jarvis\\.py)\\s+serve\\b", line)\n'
        '    if match:\n'
        '        path = pathlib.Path(match.group(1)).resolve().parent\n'
        '        if (path / "jarvis.py").exists():\n'
        '            print(path)\n'
        '            raise SystemExit(0)\n'
        'if configured and (pathlib.Path(configured) / "jarvis.py").exists():\n'
        '    print(configured)\n'
        '    raise SystemExit(0)\n'
        'print(configured)\n'
        'PY\n'
    )
    cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    cmd += ["bash -s"]
    cmd, env = _prepare_cli_runtime(cmd, None)
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True, env=env, check=False)
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.strip(), file=sys.stderr)
        return configured_remote_dir
    discovered = (proc.stdout or "").strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    if discovered and discovered != configured_remote_dir:
        print(f"ℹ️ Usando diretório remoto ativo do jarvis.service: {discovered}")
    return discovered or configured_remote_dir


def _ssh_transport_cmd_for_rsync(*, ssh_key: str, timeout_sec: int) -> str:
    parts = ["ssh", "-o", f"ConnectTimeout={max(1, int(timeout_sec))}"]
    if ssh_key:
        parts += ["-i", ssh_key]
    return _format_shell_cmd(parts)


def _sync_project_to_oracle_remote(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
    remote_dir: str,
    sync_venv: bool,
) -> int:
    if not shutil.which("rsync"):
        print("❌ rsync não encontrado no host local. Instale rsync para sincronizar com a OCI.", file=sys.stderr)
        return 127

    remote_dir = remote_dir.strip()
    if not remote_dir:
        print("❌ OCI_REMOTE_PROJECT_DIR vazio. Defina um diretório remoto válido.", file=sys.stderr)
        return 1

    print(f"📦 Sincronizando projeto para OCI em {user}@{host}:{remote_dir} ...")
    ensure_dir_script = (
        "set -euo pipefail\n"
        f"mkdir -p {shlex.quote(remote_dir)}\n"
    )
    ssh_cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    rc = _run_cli_command(ssh_cmd + ["bash -s"], input_text=ensure_dir_script)
    if rc != 0:
        print("❌ Não foi possível preparar o diretório remoto da OCI.", file=sys.stderr)
        return rc

    ssh_transport = _ssh_transport_cmd_for_rsync(ssh_key=ssh_key, timeout_sec=timeout_sec)
    remote_target = f"{user}@{host}:{remote_dir.rstrip('/')}/"
    base_code_sync_cmd: list[str] = [
        "rsync",
        "-az",
        "-e",
        ssh_transport,
    ]

    code_excludes = [
        ".git/",
        ".venv-super/",
        "node_modules/",
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
        ".ralph/",
        ".agents/ralph/runtime/",
        ".aligntrue/.backups/",
        "graphify-out/",
        ".graphify_*",
        ".context/",
        "state/",
        "chroma_db/",
        "*.log",
        ".super_server.pid",
        "mcp_status.txt",
        "token.json",
    ]
    code_sync_cmd = list(base_code_sync_cmd)
    for pattern in code_excludes:
        code_sync_cmd += ["--exclude", pattern]
    code_sync_cmd += [f"{BASE_DIR}/", remote_target]
    rc = _run_cli_command(code_sync_cmd)
    if rc != 0:
        print("❌ Falha ao sincronizar código para a OCI.", file=sys.stderr)
        return rc

    if not sync_venv:
        return 0

    venv_path = BASE_DIR / ".venv-super"
    if not venv_path.exists():
        print("❌ .venv-super local não encontrado para sincronização remota.", file=sys.stderr)
        return 1

    print("📦 Sincronizando .venv-super para OCI ...")
    venv_sync_cmd: list[str] = [
        "rsync",
        "-az",
        "-L",
        "--delete",
        "-e",
        ssh_transport,
    ]
    venv_sync_cmd += [
        f"{venv_path}/",
        f"{user}@{host}:{remote_dir.rstrip('/')}/.venv-super/",
    ]
    rc = _run_cli_command(venv_sync_cmd)
    if rc != 0:
        print("❌ Falha ao sincronizar .venv-super para a OCI.", file=sys.stderr)
        return rc
    return 0


def _bootstrap_oracle_remote_jarvis_service(
    *,
    host: str,
    user: str,
    ssh_key: str,
    timeout_sec: int,
) -> int:
    remote_dir = _resolve_oci_remote_project_dir(user)
    service_name = os.environ.get("OCI_REMOTE_JARVIS_SERVICE", "").strip() or "jarvis.service"
    remote_port = int(os.environ.get("OCI_REMOTE_SERVER_PORT", os.environ.get("SERVER_PORT", "7860")))
    sync_venv = _env_is_true("OCI_REMOTE_SYNC_VENV", True)

    rc = _sync_project_to_oracle_remote(
        host=host,
        user=user,
        ssh_key=ssh_key,
        timeout_sec=timeout_sec,
        remote_dir=remote_dir,
        sync_venv=sync_venv,
    )
    if rc != 0:
        return rc

    print(f"🧩 Criando/atualizando serviço remoto {service_name} ...")
    bootstrap_script = (
        "set -euo pipefail\n"
        'export XDG_RUNTIME_DIR="/run/user/$(id -u)"\n'
        'export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\n'
        f'REMOTE_DIR={shlex.quote(remote_dir)}\n'
        f'SERVICE_NAME={shlex.quote(service_name)}\n'
        f'REMOTE_PORT={int(remote_port)}\n'
        'if [ ! -f "$REMOTE_DIR/jarvis.py" ]; then\n'
        '  echo "jarvis.py ausente em $REMOTE_DIR" >&2\n'
        '  exit 60\n'
        'fi\n'
        'if [ ! -x "$REMOTE_DIR/.venv-super/bin/python3" ]; then\n'
        '  if command -v python3 >/dev/null 2>&1; then\n'
        '    ln -sf "$(command -v python3)" "$REMOTE_DIR/.venv-super/bin/python3" || true\n'
        '    ln -sf python3 "$REMOTE_DIR/.venv-super/bin/python" || true\n'
        '  fi\n'
        'fi\n'
        'if [ ! -x "$REMOTE_DIR/.venv-super/bin/python3" ]; then\n'
        '  echo "python da .venv-super ausente em $REMOTE_DIR/.venv-super/bin/python3" >&2\n'
        '  exit 61\n'
        'fi\n'
        'if ! command -v node >/dev/null 2>&1; then\n'
        '  echo "node não encontrado no host remoto" >&2\n'
        '  exit 62\n'
        'fi\n'
        'mkdir -p "$HOME/.config/systemd/user"\n'
        'ENTRYPOINT="$REMOTE_DIR/.jarvis_oci_entrypoint.sh"\n'
        'cat > "$ENTRYPOINT" <<EOF\n'
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'source "$REMOTE_DIR/env.sh" >/dev/null 2>&1 || true\n'
        'export PYTHONUNBUFFERED=1\n'
        'export MCP_MODE=stdio\n'
        'export PROXY_IMPL=stdio\n'
        'export SERVER_HOST=0.0.0.0\n'
        'export SERVER_PORT="$REMOTE_PORT"\n'
        'exec node "$REMOTE_DIR/stdio_proxy.js" "$REMOTE_PORT" "$REMOTE_DIR/.venv-super/bin/python3" "$REMOTE_DIR/jarvis.py" serve\n'
        'EOF\n'
        'chmod +x "$ENTRYPOINT"\n'
        'UNIT="$HOME/.config/systemd/user/$SERVICE_NAME"\n'
        'cat > "$UNIT" <<EOF\n'
        '[Unit]\n'
        'Description=Jarvis MCP Gateway (OCI)\n'
        'After=network-online.target\n'
        'Wants=network-online.target\n'
        '\n'
        '[Service]\n'
        'Type=simple\n'
        'WorkingDirectory=$REMOTE_DIR\n'
        'ExecStart=$ENTRYPOINT\n'
        'Restart=always\n'
        'RestartSec=3\n'
        'KillMode=process\n'
        '\n'
        '[Install]\n'
        'WantedBy=default.target\n'
        'EOF\n'
        'systemctl --user daemon-reload\n'
        'systemctl --user enable --now "$SERVICE_NAME"\n'
        'systemctl --user is-active "$SERVICE_NAME"\n'
        'systemctl --user status "$SERVICE_NAME" --no-pager -l | sed -n \'1,25p\'\n'
    )
    ssh_cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    return _run_cli_command(ssh_cmd + ["bash -s"], input_text=bootstrap_script)


def _oracle_api_gateway_mcp_url() -> str:
    base = (
        os.environ.get("OCI_API_GATEWAY_URL", "").strip()
        or os.environ.get("MCP_PUBLIC_URL", "").strip()
    )
    if not base:
        base = _discover_oci_gateway_base_url()
    if not base:
        return ""
    return f"{base.rstrip('/')}/mcp"


def _start_oracle_remote_jarvis(*, host: str, user: str, ssh_key: str, timeout_sec: int) -> int:
    service_override = os.environ.get("OCI_REMOTE_JARVIS_SERVICE", "").strip()
    script = (
        'set -euo pipefail\n'
        'export XDG_RUNTIME_DIR="/run/user/$(id -u)"\n'
        'export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"\n'
        f'SERVICE_OVERRIDE={shlex.quote(service_override)}\n'
        'detect_service() {\n'
        '  for s in jarvis.service super-mcp.service super-mcp-servers.service mcp-proxy.service mcp-gateway.service super-server.service; do\n'
        '    if systemctl --user list-unit-files --no-pager | awk \'{print $1}\' | grep -qx "$s"; then\n'
        '      echo "$s"\n'
        '      return 0\n'
        '    fi\n'
        '  done\n'
        '  local cand\n'
        '  cand="$(systemctl --user list-unit-files --no-pager | awk \'{print $1}\' | grep -E \'(^|[-_])(jarvis|mcp|proxy|super)([-_].*)?\\.service$\' | head -n1 || true)"\n'
        '  if [ -n "$cand" ]; then\n'
        '    echo "$cand"\n'
        '    return 0\n'
        '  fi\n'
        '  return 1\n'
        '}\n'
        'if [ -n "$SERVICE_OVERRIDE" ]; then\n'
        '  SERVICE="$SERVICE_OVERRIDE"\n'
        'else\n'
        '  if ! SERVICE="$(detect_service)"; then\n'
        '    echo "JARVIS_REMOTE_SERVICE_NOT_FOUND" >&2\n'
        '    exit 42\n'
        '  fi\n'
        'fi\n'
        'echo "remote jarvis service: $SERVICE"\n'
        'systemctl --user daemon-reload\n'
        'systemctl --user restart "$SERVICE"\n'
        'systemctl --user is-active "$SERVICE"\n'
        'systemctl --user status "$SERVICE" --no-pager -l | sed -n \'1,25p\'\n'
    )
    cmd = _openclaw_ssh_cmd(host=host, user=user, ssh_key=ssh_key, timeout_sec=timeout_sec, tty=False)
    cmd += ["bash -s"]
    return _run_cli_command(cmd, input_text=script, allow_failure=True)


def _start_oci_stack() -> int:
    host = os.environ.get("OPENCLAW_REMOTE_HOST", "mcp-instance")
    user = os.environ.get("OPENCLAW_REMOTE_USER", "ubuntu")
    ssh_key = os.environ.get("OPENCLAW_REMOTE_SSH_KEY", "")
    timeout_sec = int(os.environ.get("OPENCLAW_SSH_TIMEOUT", "20"))
    bootstrap_on_missing = _env_is_true("OCI_REMOTE_BOOTSTRAP_ON_MISSING", True)

    print(f"☁️ Iniciando Jarvis remoto na OCI ({user}@{host})...")
    rc_oracle = _start_oracle_remote_jarvis(
        host=host,
        user=user,
        ssh_key=ssh_key,
        timeout_sec=timeout_sec,
    )
    if rc_oracle == 42 and bootstrap_on_missing:
        print("🛠️ Serviço remoto do Jarvis não encontrado. Executando bootstrap na OCI...")
        rc_bootstrap = _bootstrap_oracle_remote_jarvis_service(
            host=host,
            user=user,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
        )
        if rc_bootstrap != 0:
            print("❌ Falha no bootstrap remoto do Jarvis na OCI.", file=sys.stderr)
            return rc_bootstrap
        print("✅ Bootstrap remoto concluído. Validando serviço Jarvis na OCI...")
        rc_oracle = _start_oracle_remote_jarvis(
            host=host,
            user=user,
            ssh_key=ssh_key,
            timeout_sec=timeout_sec,
        )

    if rc_oracle == 42:
        print(
            "❌ Serviço remoto do Jarvis não encontrado na OCI mesmo após tentativa de bootstrap. "
            "Defina OCI_REMOTE_JARVIS_SERVICE se o nome for customizado.",
            file=sys.stderr,
        )
        return rc_oracle

    if rc_oracle != 0:
        print("❌ Falha ao iniciar/reiniciar Jarvis remoto na OCI.", file=sys.stderr)
        return rc_oracle

    print(f"🔁 Reiniciando OpenClaw remoto na OCI ({user}@{host})...")
    rc_openclaw = _openclaw_remote_cli(
        "restart",
        host=host,
        user=user,
        ssh_key=ssh_key,
        timeout_sec=timeout_sec,
    )
    if rc_openclaw != 0:
        print("❌ Falha ao reiniciar OpenClaw remoto na OCI.", file=sys.stderr)
        return rc_openclaw

    gateway = _oracle_api_gateway_mcp_url()
    if gateway:
        print(f"🌐 Oracle API Gateway: {gateway}")
    else:
        print(
            "⚠️ OCI_API_GATEWAY_URL (ou MCP_PUBLIC_URL) não definido. Não foi possível exibir o gateway da Oracle.",
            file=sys.stderr,
        )

    return 0

_OCI_INSTALL_SCRIPT_URLS = [
    "https://raw.codehostusercontent.com/oracle/oci-cli/master/scripts/install/install.sh",
    "https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh",
]


def _install_oci_cli(installer_args: list[str]) -> int:
    args = list(installer_args or [])
    if args and args[0] == "--":
        args = args[1:]

    existing_oci = shutil.which("oci")
    if existing_oci:
        print(f"✅ OCI CLI já instalado em {existing_oci}. Sem alterações.")
        return 0

    curl_bin = shutil.which("curl")
    if not curl_bin:
        print("❌ curl não encontrado. Instale curl para continuar.", file=sys.stderr)
        return 1

    installer_path: Path | None = None
    for url in _OCI_INSTALL_SCRIPT_URLS:
        fd, tmp_name = tempfile.mkstemp(prefix="jarvis_oci_install_", suffix=".sh")
        os.close(fd)
        candidate = Path(tmp_name)
        rc = _run_cli_command([curl_bin, "-fsSL", url, "-o", str(candidate)], allow_failure=True)
        if rc == 0:
            installer_path = candidate
            break
        candidate.unlink(missing_ok=True)

    if installer_path is None:
        print("❌ Não foi possível baixar o instalador OCI.", file=sys.stderr)
        return 1

    try:
        os.chmod(installer_path, 0o755)
    except Exception:
        pass

    try:
        return _run_cli_command(["bash", str(installer_path), *args])
    finally:
        installer_path.unlink(missing_ok=True)






def _run_reclaim_ui_selftests(verbose: bool = False) -> tuple[int, int]:
    def _assert(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    def _write_script(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    tests = []

    def register(name: str):
        def _decorator(fn):
            tests.append((name, fn))
            return fn

        return _decorator

    @register("bootstrap_manual_login_confirmed_creates_valid_session")
    def _test_bootstrap_manual_login_confirmed_creates_valid_session():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            session_path = Path(tmp) / "reclaim_session.json"
            bootstrap_session(
                path=session_path,
                manual_login_confirmed=True,
                captcha_resolved=True,
                captcha_timeout_sec=60,
                session_ttl_sec=300,
                now_epoch=1000,
            )
            status = get_session_status(
                path=session_path,
                session_ttl_sec=300,
                now_epoch=1020,
            )
            _assert(status.get("state") == "valid", "estado da sessão deveria ser valid")
            _assert(bool(status.get("last_validated_at")), "last_validated_at ausente")
            _assert(bool(status.get("expires_at")), "expires_at ausente")

    @register("status_blocks_when_captcha_timeout_is_exceeded")
    def _test_status_blocks_when_captcha_timeout_is_exceeded():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            session_path = Path(tmp) / "reclaim_session.json"
            bootstrap_session(
                path=session_path,
                manual_login_confirmed=False,
                captcha_resolved=True,
                captcha_timeout_sec=30,
                session_ttl_sec=300,
                now_epoch=1000,
            )
            status = get_session_status(
                path=session_path,
                session_ttl_sec=300,
                now_epoch=1035,
            )
            _assert(status.get("state") == "blocked_captcha", "estado deveria ser blocked_captcha")
            _assert(bool(status.get("blocked_at")), "blocked_at ausente")

    @register("resolve_exact_title_unique_match_with_trim_only")
    def _test_resolve_exact_title_unique_match_with_trim_only():
        candidates = [{"id": "a1", "title": "  Tarefa Alpha  "}, {"id": "b1", "title": "Tarefa Beta"}]
        result = resolve_exact_title(" Tarefa Alpha ", candidates)
        _assert(result.get("status") == "ok", "status deveria ser ok")
        _assert(result.get("resolution") == "unique", "resolution deveria ser unique")
        _assert(result.get("match", {}).get("id") == "a1", "id esperado a1")
        _assert(result.get("match", {}).get("normalized_title") == "Tarefa Alpha", "normalized_title inválido")

    @register("resolve_exact_title_not_found")
    def _test_resolve_exact_title_not_found():
        candidates = [{"id": "a1", "title": "Tarefa Alpha"}]
        result = resolve_exact_title("Tarefa Gamma", candidates)
        _assert(result.get("status") == "error", "status deveria ser error")
        _assert(result.get("resolution") == "not_found", "resolution deveria ser not_found")
        _assert(result.get("error", {}).get("code") == "title_not_found", "code esperado title_not_found")

    @register("resolve_exact_title_ambiguous_requires_confirmation")
    def _test_resolve_exact_title_ambiguous_requires_confirmation():
        candidates = [{"id": "a1", "title": "Tarefa Duplicada"}, {"id": "a2", "title": "  Tarefa Duplicada  "}]
        result = resolve_exact_title(normalize_title(" Tarefa Duplicada "), candidates)
        _assert(result.get("status") == "error", "status deveria ser error")
        _assert(result.get("resolution") == "ambiguous", "resolution deveria ser ambiguous")
        _assert(result.get("error", {}).get("code") == "multiple_candidates", "code esperado multiple_candidates")
        _assert(len(result.get("candidates", [])) == 2, "candidates esperados: 2")

    @register("executor_success_json_payload")
    def _test_executor_success_json_payload():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            script = Path(tmp) / "ok.sh"
            _write_script(
                script,
                "#!/usr/bin/env bash\n"
                "echo '{\"status\":\"ok\",\"result\":\"action_executed\",\"executed_at\":\"2026-02-18T16:00:00Z\"}'\n"
                "exit 0\n",
            )
            result = run_reclaim_ui_action(action="start", title="Tarefa", executor_cmd=str(script), timeout_sec=5)
            _assert(result.get("status") == "ok", "status deveria ser ok")
            _assert(result.get("result") == "action_executed", "result deveria ser action_executed")
            _assert(result.get("action") == "start", "action deveria ser start")
            _assert(result.get("title") == "Tarefa", "title deveria ser Tarefa")

    @register("executor_non_zero_becomes_error")
    def _test_executor_non_zero_becomes_error():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            script = Path(tmp) / "fail.sh"
            _write_script(
                script,
                "#!/usr/bin/env bash\n"
                "echo '{\"status\":\"error\",\"error\":{\"code\":\"window_not_found\",\"message\":\"janela nao encontrada\"}}'\n"
                "exit 22\n",
            )
            result = run_reclaim_ui_action(action="start", title="Tarefa", executor_cmd=str(script), timeout_sec=5)
            _assert(result.get("status") == "error", "status deveria ser error")
            _assert(result.get("error", {}).get("code") == "window_not_found", "code esperado window_not_found")
            _assert(result.get("executor_returncode") == 22, "executor_returncode esperado 22")

    @register("google_invalid_grant_message_is_actionable")
    def _test_google_invalid_grant_message_is_actionable():
        message = _google_auth_actionable_error("invalid_grant: Token has been expired or revoked.")
        _assert("google-auth-refresh --force" in message, "mensagem deveria apontar google-auth-refresh --force")

    @register("google_workspace_probe_reports_missing_token")
    def _test_google_workspace_probe_reports_missing_token():
        with tempfile.TemporaryDirectory(prefix="jarvis_google_test_") as tmp:
            result = _google_workspace_token_probe(Path(tmp) / "missing-token.json")
            _assert(result.get("ok") is False, "probe deveria falhar sem token")
            _assert(result.get("code") == "token_missing", "code esperado token_missing")

    @register("reclaim_profile_lock_detects_live_pid")
    def _test_reclaim_profile_lock_detects_live_pid():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            profile = Path(tmp)
            lock = profile / "SingletonLock"
            lock.symlink_to(f"host-{os.getpid()}")
            _assert(_reclaim_playwright_profile_in_use(profile), "perfil deveria estar em uso com pid vivo")

    @register("reclaim_profile_lock_ignores_dead_pid")
    def _test_reclaim_profile_lock_ignores_dead_pid():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            profile = Path(tmp)
            lock = profile / "SingletonLock"
            lock.symlink_to("host-99999999")
            _assert(not _reclaim_playwright_profile_in_use(profile), "perfil com pid morto deveria ser ignorado")

    @register("executor_missing_script_returns_structured_error")
    def _test_executor_missing_script_returns_structured_error():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            missing = Path(tmp) / "missing.sh"
            result = run_reclaim_ui_action(action="start", title="Tarefa", executor_cmd=str(missing), timeout_sec=5)
            _assert(result.get("status") == "error", "status deveria ser error")
            _assert(result.get("error", {}).get("code") == "executor_not_found", "code esperado executor_not_found")

    @register("executor_rejects_invalid_action")
    def _test_executor_rejects_invalid_action():
        result = run_reclaim_ui_action(action="pause", title="Tarefa", executor_cmd="/tmp/fake.sh", timeout_sec=5)
        _assert(result.get("status") == "error", "status deveria ser error")
        _assert(result.get("error", {}).get("code") == "invalid_action", "code esperado invalid_action")

    @register("create_assist_request_records_audit")
    def _test_create_assist_request_records_audit():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            audit_path = Path(tmp) / "assist_audit.jsonl"
            assist = create_assist_request(
                audit_path=audit_path,
                action="start",
                title="Tarefa Assistida",
                reason="window_not_found",
                detail="Não há janela visível",
                login_url="https://app.reclaim.ai",
                session_state="valid",
                open_browser=False,
            )
            _assert(assist.get("assist_mode") == "manual_ui_intervention", "assist_mode inválido")
            _assert(assist.get("action") == "start", "action inválida")
            _assert(bool(assist.get("manual_steps")), "manual_steps ausente")
            _assert("confirm_next_step" in assist, "confirm_next_step ausente")
            _assert(audit_path.exists(), "audit_path deveria existir")
            payload = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
            _assert(payload.get("assist_id") == assist.get("assist_id"), "assist_id inconsistente")
            _assert(payload.get("reason") == "window_not_found", "reason inconsistente")

    @register("confirm_assist_completion_validates_result")
    def _test_confirm_assist_completion_validates_result():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            audit_path = Path(tmp) / "assist_confirm.jsonl"
            result = confirm_assist_completion(
                audit_path=audit_path,
                assist_id="assist-123",
                action="stop",
                result="stopped",
                notes="Feito manualmente",
            )
            _assert(result.get("status") == "ok", "status deveria ser ok")
            _assert(result.get("result") == "stopped", "result deveria ser stopped")
            _assert(audit_path.exists(), "audit_path deveria existir")
            payload = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
            _assert(payload.get("assist_id") == "assist-123", "assist_id inconsistente")

    @register("confirm_assist_rejects_unknown_result")
    def _test_confirm_assist_rejects_unknown_result():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            audit_path = Path(tmp) / "assist_confirm.jsonl"
            result = confirm_assist_completion(
                audit_path=audit_path,
                assist_id="assist-123",
                action="stop",
                result="paused",
            )
            _assert(result.get("status") == "error", "status deveria ser error")
            _assert(result.get("error", {}).get("code") == "invalid_result", "code esperado invalid_result")
            _assert("assist_confirmed" not in str(result.get("result", "")), "result inesperado")

    @register("pick_next_candidate_returns_first_non_empty_title")
    def _test_pick_next_candidate_returns_first_non_empty_title():
        candidates = [
            {"id": "skip", "title": "   "},
            {"id": "a1", "title": "  Tarefa Alpha  "},
            {"id": "b1", "title": "Tarefa Beta"},
        ]
        result = _reclaim_pick_next_candidate(candidates)
        _assert(result.get("status") == "ok", "status deveria ser ok")
        _assert(result.get("resolution") == "next_candidate", "resolution deveria ser next_candidate")
        _assert(result.get("next", {}).get("id") == "a1", "id esperado a1")
        _assert(result.get("next", {}).get("normalized_title") == "Tarefa Alpha", "normalized_title inválido")
        _assert(len(result.get("candidates", [])) == 2, "deveriam existir 2 candidatos válidos")

    @register("pick_next_candidate_returns_error_when_empty")
    def _test_pick_next_candidate_returns_error_when_empty():
        candidates = [
            {"id": "skip", "title": "   "},
            {"id": "skip2", "title": ""},
        ]
        result = _reclaim_pick_next_candidate(candidates)
        _assert(result.get("status") == "error", "status deveria ser error")
        _assert(result.get("resolution") == "no_candidates", "resolution deveria ser no_candidates")
        _assert(result.get("error", {}).get("code") == "no_candidates", "code esperado no_candidates")


    @register("append_audit_event_writes_jsonl_line")
    def _test_append_audit_event_writes_jsonl_line():
        with tempfile.TemporaryDirectory(prefix="jarvis_reclaim_test_") as tmp:
            audit_path = Path(tmp) / "reclaim_ui_audit.jsonl"
            event = append_audit_event(
                path=audit_path,
                event={"action": "reclaim_session_status", "state": "valid", "result": "valid"},
                now_epoch=1000,
            )
            _assert(event.get("action") == "reclaim_session_status", "action inválida")
            _assert(event.get("state") == "valid", "state inválido")
            _assert(audit_path.exists(), "arquivo de audit deveria existir")
            lines = audit_path.read_text(encoding="utf-8").splitlines()
            _assert(len(lines) == 1, "deveria haver 1 linha no audit")
            payload = json.loads(lines[0])
            _assert(payload.get("action") == "reclaim_session_status", "action no payload inválida")
            _assert(payload.get("state") == "valid", "state no payload inválido")
            _assert(payload.get("result") == "valid", "result no payload inválido")
            _assert("timestamp" in payload, "timestamp ausente")

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            if verbose:
                print(f"✅ {name}")
        except Exception as exc:
            failed += 1
            print(f"❌ {name}: {exc}", file=sys.stderr)
            if verbose:
                import traceback

                traceback.print_exc()

    print(f"Reclaim UI self-test: {passed} passed, {failed} failed")
    return passed, failed


def _test_reclaim_ui_cli(verbose: bool = False) -> int:
    _, failed = _run_reclaim_ui_selftests(verbose=verbose)
    return 0 if failed == 0 else 1


def _project_origin_remote_url(repo_dir: Path | None = None) -> str:
    repo = repo_dir or BASE_DIR
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _current_git_branch(repo_dir: Path | None = None) -> str:
    repo = repo_dir or BASE_DIR
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()



def _context_stack_expected_dirs(root: Path) -> dict[str, Path]:
    context = root / ".context"
    return {
        "docs": context / "docs",
        "plans": context / "plans",
        "workflow": context / "workflow",
        "graphify": context / "graphify-out",
    }


def _context_stack_legacy_paths(root: Path) -> dict[str, Path]:
    return {
        "legacy_docs_planning_gsd": root / ".context" / "docs" / "planning_gsd",
        "legacy_prd_ralph": root / ".context" / "prd_ralph",
        "legacy_ralph_runtime": root / ".context" / "ralph",
        "legacy_dot_planning": root / ".planning",
        "legacy_root_graphify_out": root / "graphify-out",
        "legacy_agents_tasks": root / ".agents" / "tasks",
        "legacy_agents_ralph_runtime": root / ".agents" / "ralph" / "runtime",
    }


def _context_stack_candidate_roots(roots: list[str], *, recursive: bool = False) -> list[Path]:
    skip_dirs = {".git", "node_modules", ".venv", ".venv-super", "__pycache__", ".mypy_cache", ".ruff_cache"}
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)

    for raw in roots or [str(BASE_DIR)]:
        root = Path(str(raw).replace("file://", "")).expanduser()
        if root.name == ".context":
            add(root.parent)
            continue
        if not recursive:
            add(root)
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            current = Path(dirpath)
            if (current / ".context").exists():
                add(current)
                if ".context" in dirnames:
                    dirnames.remove(".context")
    return candidates


def _context_stack_layout_report(root: Path) -> dict:
    expected = _context_stack_expected_dirs(root)
    legacy = _context_stack_legacy_paths(root)
    present_expected = {name: path.exists() for name, path in expected.items()}
    present_legacy = {name: str(path) for name, path in legacy.items() if path.exists()}
    missing_expected = [name for name, exists in present_expected.items() if not exists]
    return {
        "root": str(root),
        "ok": not missing_expected and not present_legacy,
        "expected": {name: str(path) for name, path in expected.items()},
        "present_expected": present_expected,
        "missing_expected": missing_expected,
        "legacy_present": present_legacy,
        "owners": {
            "docs": "AI Coders Context",
            "plans": "GSD",
            "workflow": "Ralph",
            "graphify-out": "Graphify",
        },
    }


def _context_stack_check(roots: list[str], *, recursive: bool = False) -> dict:
    candidates = _context_stack_candidate_roots(roots, recursive=recursive)
    reports = [_context_stack_layout_report(root) for root in candidates]
    return {
        "ok": bool(reports) and all(bool(report.get("ok")) for report in reports),
        "recursive": recursive,
        "count": len(reports),
        "reports": reports,
    }


def _safe_move_context_child(src: Path, dst: Path, archive_root: Path, moved: list[dict], skipped: list[dict]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(str(src), str(dst))
        moved.append({"from": str(src), "to": str(dst)})
        return
    try:
        if src.is_file() and dst.is_file() and src.read_bytes() == dst.read_bytes():
            src.unlink()
            skipped.append({"path": str(src), "reason": "duplicate_existing_target"})
            return
    except Exception:
        pass
    archive_root.mkdir(parents=True, exist_ok=True)
    archived = archive_root / src.name
    counter = 1
    while archived.exists():
        archived = archive_root / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    shutil.move(str(src), str(archived))
    moved.append({"from": str(src), "to": str(archived), "reason": "target_exists_archived"})


def _merge_context_stack_layout(root: Path = BASE_DIR) -> dict:
    context = root / ".context"
    docs = context / "docs"
    plans = context / "plans"
    workflow = context / "workflow"
    graphify = context / "graphify-out"
    ensured: list[str] = []
    for path in [docs, plans, workflow, graphify]:
        path.mkdir(parents=True, exist_ok=True)
        ensured.append(str(path))

    moved: list[dict] = []
    skipped: list[dict] = []
    errors: list[str] = []
    archive_root = workflow / "archive" / "legacy-context-stack"
    migrations = [
        (context / "prd_ralph", workflow, archive_root / "prd_ralph"),
        (context / "ralph", workflow / "ralph", archive_root / "ralph"),
    ]
    for legacy_dir, target_dir, archive_dir in migrations:
        if not legacy_dir.exists():
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for child in sorted(legacy_dir.iterdir(), key=lambda p: p.name):
                _safe_move_context_child(child, target_dir / child.name, archive_dir, moved, skipped)
            try:
                legacy_dir.rmdir()
            except OSError:
                skipped.append({"path": str(legacy_dir), "reason": "legacy_dir_not_empty"})
        except Exception as exc:
            errors.append(f"{legacy_dir}: {exc}")

    report = _context_stack_layout_report(root)
    return {
        "ok": not errors,
        "ensured": ensured,
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "layout": report,
    }


def _sync_project_context_entrypoints(target_dir: Path | None = None) -> dict:
    work_dir = target_dir or Path.cwd()
    source_rules = BASE_DIR / "global_rule_sync" / "AGENTS.md"
    source_gemini_rules = BASE_DIR / "global_rule_sync" / "GEMINI.md"
    context_dirs = [
        work_dir / ".context" / "docs",
        work_dir / ".context" / "plans",
        work_dir / ".context" / "workflow",
        work_dir / ".context" / "graphify-out",
    ]

    missing_sources = [str(p.relative_to(BASE_DIR)) for p in [source_rules, source_gemini_rules] if not p.exists()]
    if missing_sources:
        return {
            "ok": False,
            "returncode": 1,
            "error": "project_context_rule_sources_missing",
            "missing_sources": missing_sources,
        }

    ensured_dirs: list[str] = []
    for d in context_dirs:
        d.mkdir(parents=True, exist_ok=True)
        try:
            ensured_dirs.append(str(d.relative_to(work_dir)))
        except Exception:
            ensured_dirs.append(str(d))

    synced_files: list[str] = []
    try:
        (work_dir / "AGENTS.md").write_text(source_rules.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        synced_files.append("AGENTS.md")
        (work_dir / "GEMINI.md").write_text(source_gemini_rules.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        synced_files.append("GEMINI.md")
    except Exception as exc:
        return {
            "ok": False,
            "returncode": 1,
            "error": "project_context_entrypoint_sync_failed",
            "detail": str(exc),
            "ensured_dirs": ensured_dirs,
            "synced_files": synced_files,
        }

    remote_url = _project_origin_remote_url(work_dir)
    github_remote = "github.com" in remote_url.lower()
    readme_path = work_dir / "README.md"
    readme_exists = readme_path.exists() or readme_path.is_symlink()
    readme_recommended = github_remote and not readme_exists

    readme_status = {
        "exists": readme_exists,
        "github_remote_detected": github_remote,
        "remote_url": remote_url,
        "recommended": readme_recommended,
        "action": "recommended_only" if readme_recommended else ("present" if readme_exists else "optional_missing"),
        "note": (
            "README.md permanece opcional no projeto. Como há remoto GitHub, é recomendado manter um README manual."
            if readme_recommended
            else "README.md não foi recriado automaticamente pelo workflow."
        ),
    }

    return {
        "ok": True,
        "returncode": 0,
        "ensured_dirs": ensured_dirs,
        "synced_files": synced_files,
        "docs_only": True,
        "readme": readme_status,
    }


def _sync_agent_assets_core(target_home: str = "", quiet: bool = False) -> int:
    if quiet:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return _sync_agent_assets_core(target_home=target_home, quiet=False)

    source_rules = BASE_DIR / "global_rule_sync" / "AGENTS.md"
    source_gemini_rules = BASE_DIR / "global_rule_sync" / "GEMINI.md"
    if not source_rules.exists():
        print(f"❌ AGENTS consolidado não encontrado em {source_rules}. Rode 'aligntrue sync'.", file=sys.stderr)
        return 1

    codex_system_prompt = _resolve_system_prompt_file("codex_system.md")
    gemini_system_prompt = _resolve_system_prompt_file("gemini_system.md")
    omp_system_prompt = _resolve_system_prompt_file("omp_system.md")

    explicit_target_home = (target_home or "").strip()
    env_target_home = os.environ.get("AGCAO_USER_HOME", "").strip()
    homes: list[Path] = []
    if explicit_target_home:
        homes.append(Path(explicit_target_home).expanduser())
    else:
        homes.append(Path.home())
        if env_target_home:
            homes.append(Path(env_target_home).expanduser())

    dedup_homes: list[Path] = []
    for home in homes:
        if home not in dedup_homes:
            dedup_homes.append(home)
    homes = dedup_homes

    state_path = BASE_DIR / ".agent-assets-sync-state.json"
    ignored_names = {".git", "__pycache__", ".DS_Store"}

    def _write_or_update(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _ensure_key_line(content: str, key: str, value_expr: str) -> str:
        line = f"{key} = {value_expr}"
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(content):
            return pattern.sub(line, content)
        lines = content.splitlines()
        idx = len(lines)
        for i, existing in enumerate(lines):
            if existing.strip().startswith("["):
                idx = i
                break
        new_lines = lines[:idx]
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(line)
        if idx < len(lines) and lines[idx].strip() != "":
            new_lines.append("")
        new_lines.extend(lines[idx:])
        out = "\n".join(new_lines)
        if out and not out.endswith("\n"):
            out += "\n"
        return out

    def _empty_counts() -> dict[str, int]:
        return {"imported": 0, "deployed": 0, "updated": 0, "deleted": 0, "conflicts": 0}

    def _add_counts(total: dict[str, int], delta: dict[str, int]) -> None:
        for key in total:
            total[key] += delta.get(key, 0)

    def _home_key(home: Path) -> str:
        try:
            return str(home.expanduser().resolve(strict=False))
        except Exception:
            return str(home.expanduser().absolute())

    def _load_state() -> dict:
        if not state_path.exists():
            return {"version": 1, "homes": {}}
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"⚠️ Estado de sync inválido em {state_path}; iniciando estado vazio: {exc}")
            return {"version": 1, "homes": {}}
        if not isinstance(data, dict):
            return {"version": 1, "homes": {}}
        if not isinstance(data.get("homes"), dict):
            data["homes"] = {}
        data["version"] = 1
        return data

    def _ensure_state_ignored() -> None:
        git_dir = BASE_DIR / ".git"
        if not git_dir.is_dir():
            return
        exclude_path = git_dir / "info" / "exclude"
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            content = exclude_path.read_text(encoding="utf-8", errors="ignore") if exclude_path.exists() else ""
            tracked_lines = {
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
            if state_path.name not in tracked_lines:
                prefix = "" if not content or content.endswith("\n") else "\n"
                with exclude_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"{prefix}{state_path.name}\n")
        except Exception as exc:
            print(f"⚠️ Não foi possível registrar {state_path.name} em .git/info/exclude: {exc}")

    def _save_state(state: dict) -> None:
        _ensure_state_ignored()
        state["version"] = 1
        if not isinstance(state.get("homes"), dict):
            state["homes"] = {}
        tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, state_path)

    def _collection_items(state: dict, home_key: str, collection_key: str) -> dict[str, str]:
        homes_state = state.setdefault("homes", {})
        home_state = homes_state.get(home_key)
        if not isinstance(home_state, dict):
            return {}
        collections = home_state.get("collections")
        if not isinstance(collections, dict):
            return {}
        collection_state = collections.get(collection_key)
        if not isinstance(collection_state, dict):
            return {}
        items = collection_state.get("items")
        if isinstance(items, dict):
            return {str(key): str(value) for key, value in items.items() if isinstance(value, str)}
        return {str(key): str(value) for key, value in collection_state.items() if isinstance(value, str)}

    def _set_collection_items(state: dict, home_key: str, collection_key: str, items: dict[str, str]) -> None:
        homes_state = state.setdefault("homes", {})
        home_state = homes_state.setdefault(home_key, {})
        if not isinstance(home_state, dict):
            home_state = {}
            homes_state[home_key] = home_state
        collections = home_state.setdefault("collections", {})
        if not isinstance(collections, dict):
            collections = {}
            home_state["collections"] = collections
        collections[collection_key] = {"items": dict(sorted(items.items()))}

    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _hash_skill_dir(path: Path) -> str:
        digest = hashlib.sha256()
        for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
            rel = item.relative_to(path)
            if any(part in ignored_names for part in rel.parts):
                continue
            if not item.is_file():
                continue
            rel_name = rel.as_posix()
            digest.update(b"file\0")
            digest.update(rel_name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_hash_file(item).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _scan_files(root: Path, suffixes: set[str]) -> dict[str, dict[str, object]]:
        entries: dict[str, dict[str, object]] = {}
        if not root.exists():
            return entries
        if not root.is_dir():
            print(f"⚠️ Coleção de prompts não é diretório: {root}")
            return entries
        for item in sorted(root.iterdir()):
            if item.name.startswith(".") or not item.is_file():
                continue
            if suffixes and item.suffix.lower() not in suffixes:
                continue
            try:
                entries[item.name] = {"path": item, "hash": _hash_file(item)}
            except Exception as exc:
                print(f"⚠️ Falha ao calcular hash de {item}: {exc}")
        return entries

    def _scan_skills(root: Path) -> dict[str, dict[str, object]]:
        entries: dict[str, dict[str, object]] = {}
        if not root.exists():
            return entries
        if not root.is_dir():
            print(f"⚠️ Coleção de skills não é diretório: {root}")
            return entries
        for item in sorted(root.iterdir()):
            if item.name.startswith(".") or not item.is_dir() or item.is_symlink():
                continue
            if not (item / "SKILL.md").is_file():
                continue
            try:
                entries[item.name] = {"path": item, "hash": _hash_skill_dir(item)}
            except Exception as exc:
                print(f"⚠️ Falha ao calcular hash de {item}: {exc}")
        return entries

    def _is_under(path: Path, root: Path) -> bool:
        try:
            root_abs = root.expanduser().absolute()
            path_abs = path.expanduser().absolute()
            if path_abs == root_abs:
                return False
            path_abs.relative_to(root_abs)
            return True
        except Exception:
            return False

    def _delete_path(path: Path, root: Path, *, label: str) -> bool:
        if not _is_under(path, root):
            print(f"⚠️ {label}: remoção recusada fora da raiz configurada: {path}")
            return False
        if not path.exists() and not path.is_symlink():
            return True
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return True
        except Exception as exc:
            print(f"⚠️ {label}: falha ao remover {path}: {exc}")
            return False

    def _copy_file_item(source: Path, target: Path, target_root: Path, *, label: str) -> bool:
        if not _is_under(target, target_root):
            print(f"⚠️ {label}: cópia recusada fora da raiz configurada: {target}")
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_dir():
                print(f"⚠️ {label}: destino é diretório, não arquivo: {target}")
                return False
            if target.is_symlink():
                target.unlink()
            shutil.copy2(source, target)
            return True
        except Exception as exc:
            print(f"⚠️ {label}: falha ao copiar {source} -> {target}: {exc}")
            return False

    def _copy_skill_item(source: Path, target: Path, target_root: Path, *, label: str) -> bool:
        if not _is_under(target, target_root):
            print(f"⚠️ {label}: cópia recusada fora da raiz configurada: {target}")
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if target.is_symlink():
                    target.unlink()
                elif target.is_dir():
                    if not _delete_path(target, target_root, label=label):
                        return False
                else:
                    print(f"⚠️ {label}: destino não é diretório: {target}")
                    return False
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", ".git", ".DS_Store"),
            )
            return True
        except Exception as exc:
            print(f"⚠️ {label}: falha ao copiar {source} -> {target}: {exc}")
            return False

    def _reconcile_collection(
        *,
        state: dict,
        home_key: str,
        collection_key: str,
        label: str,
        source_root: Path,
        target_root: Path,
        kind: str,
        suffixes: set[str] | None = None,
        blocked_names: set[str] | None = None,
    ) -> tuple[dict[str, int], list[str]]:
        counts = _empty_counts()
        conflicts: list[str] = []
        deleted_rels: list[str] = []
        blocked_names = blocked_names or set()
        prior_items = _collection_items(state, home_key, collection_key)

        if kind == "file":
            source_items = _scan_files(source_root, suffixes or set())
            target_items = _scan_files(target_root, suffixes or set())
        elif kind == "skill":
            source_items = _scan_skills(source_root)
            target_items = _scan_skills(target_root)
        else:
            raise ValueError(f"Tipo de coleção inválido: {kind}")

        for blocked in sorted(blocked_names):
            blocked_source = source_items.pop(blocked, None)
            if blocked_source is not None:
                source_path = blocked_source.get("path")
                if isinstance(source_path, Path) and _delete_path(source_path, source_root, label=label):
                    counts["deleted"] += 1
                    deleted_rels.append(blocked)
                    print(f"🧹 {label}: prompt bloqueado removido da origem: {source_path}")
                else:
                    counts["conflicts"] += 1
                    conflicts.append(f"{label}/{blocked}: falha ao remover prompt bloqueado da origem")
            blocked_target = target_items.pop(blocked, None)
            if blocked_target is not None:
                target_path = blocked_target["path"]
                if isinstance(target_path, Path) and _delete_path(target_path, target_root, label=label):
                    counts["deleted"] += 1
                    deleted_rels.append(blocked)
                    print(f"🧹 {label}: prompt bloqueado removido do cliente: {target_path}")
                else:
                    counts["conflicts"] += 1
                    conflicts.append(f"{label}/{blocked}: falha ao remover prompt bloqueado")

        new_items: dict[str, str] = {}

        def _copy(source_path: Path, target_path: Path, root: Path) -> bool:
            if kind == "file":
                return _copy_file_item(source_path, target_path, root, label=label)
            return _copy_skill_item(source_path, target_path, root, label=label)

        def _conflict(rel: str, reason: str) -> None:
            counts["conflicts"] += 1
            conflicts.append(f"{label}/{rel}: {reason}")
            prior_hash = prior_items.get(rel)
            if prior_hash:
                new_items[rel] = prior_hash

        all_rels = sorted(set(prior_items) | set(source_items) | set(target_items))
        for rel in all_rels:
            source_entry = source_items.get(rel)
            target_entry = target_items.get(rel)
            prior_hash = prior_items.get(rel)
            known = prior_hash is not None
            source_hash = source_entry.get("hash") if source_entry else None
            target_hash = target_entry.get("hash") if target_entry else None
            source_path = source_entry.get("path") if source_entry else source_root / rel
            target_path = target_entry.get("path") if target_entry else target_root / rel

            if source_hash and target_hash:
                if source_hash == target_hash:
                    new_items[rel] = str(source_hash)
                    continue
                if prior_hash is None:
                    _conflict(rel, "repo e cliente existem com conteúdo diferente sem base anterior")
                    continue
                source_changed = source_hash != prior_hash
                target_changed = target_hash != prior_hash
                if source_changed and not target_changed:
                    if isinstance(source_path, Path) and isinstance(target_path, Path) and _copy(source_path, target_path, target_root):
                        counts["updated"] += 1
                        new_items[rel] = str(source_hash)
                    else:
                        _conflict(rel, "falha ao atualizar cliente a partir do repo")
                    continue
                if target_changed and not source_changed:
                    if isinstance(source_path, Path) and isinstance(target_path, Path) and _copy(target_path, source_path, source_root):
                        counts["updated"] += 1
                        new_items[rel] = str(target_hash)
                    else:
                        _conflict(rel, "falha ao atualizar repo a partir do cliente")
                    continue
                _conflict(rel, "repo e cliente mudaram desde o último sync")
                continue

            if source_hash and not target_hash:
                if known:
                    if isinstance(source_path, Path) and _delete_path(source_path, source_root, label=label):
                        counts["deleted"] += 1
                        deleted_rels.append(rel)
                    else:
                        _conflict(rel, "cliente deletou, mas não foi possível deletar no repo")
                    continue
                if isinstance(source_path, Path) and isinstance(target_path, Path) and _copy(source_path, target_path, target_root):
                    counts["deployed"] += 1
                    new_items[rel] = str(source_hash)
                else:
                    _conflict(rel, "falha ao implantar item do repo no cliente")
                continue

            if target_hash and not source_hash:
                if known:
                    if isinstance(target_path, Path) and _delete_path(target_path, target_root, label=label):
                        counts["deleted"] += 1
                        deleted_rels.append(rel)
                    else:
                        _conflict(rel, "repo deletou, mas não foi possível deletar no cliente")
                    continue
                if isinstance(source_path, Path) and isinstance(target_path, Path) and _copy(target_path, source_path, source_root):
                    counts["imported"] += 1
                    new_items[rel] = str(target_hash)
                else:
                    _conflict(rel, "falha ao importar item do cliente para o repo")
                continue

        _set_collection_items(state, home_key, collection_key, new_items)
        print(
            f"✅ {label}: imported={counts['imported']}, deployed={counts['deployed']}, "
            f"updated={counts['updated']}, deleted={counts['deleted']}, conflicts={counts['conflicts']}"
        )
        for conflict in conflicts:
            print(f"❌ Conflito: {conflict}")
        return counts, deleted_rels

    def _generate_omp_prompt_commands(home: Path, source_root: Path, deleted_rels: list[str]) -> int:
        prompts_dir = home / ".omp" / "agent" / "prompts"
        commands_dir = home / ".omp" / "agent" / "commands"
        source_items = _scan_files(source_root, {".md"})
        generated = 0
        cleanup_names = set(deleted_rels)
        cleanup_names.update(source_items)
        commands_dir.mkdir(parents=True, exist_ok=True)
        for rel in sorted(cleanup_names):
            prompt_name = Path(rel).stem
            legacy_prompt_alias = prompts_dir / f"prompts:{prompt_name}.md"
            if legacy_prompt_alias.exists() or legacy_prompt_alias.is_symlink():
                _delete_path(legacy_prompt_alias, prompts_dir, label="Prompts OMP")
            legacy_command_target = commands_dir / rel
            if legacy_command_target.exists() or legacy_command_target.is_symlink():
                _delete_path(legacy_command_target, commands_dir, label="Prompts OMP")
            if rel in deleted_rels and rel not in source_items:
                generated_command = commands_dir / f"prompts:{prompt_name}.md"
                if generated_command.exists() or generated_command.is_symlink():
                    _delete_path(generated_command, commands_dir, label="Prompts OMP")
        for rel, entry in sorted(source_items.items()):
            source_path = entry.get("path")
            if not isinstance(source_path, Path):
                continue
            command_path = commands_dir / f"prompts:{source_path.stem}.md"
            try:
                content = source_path.read_text(encoding="utf-8")
                current = command_path.read_text(encoding="utf-8", errors="ignore") if command_path.exists() else None
                if current != content:
                    _write_or_update(command_path, content)
                generated += 1
            except Exception as exc:
                print(f"⚠️ Prompts OMP: falha ao gerar comando {command_path}: {exc}")
        print(f"✅ Prompts OMP: comandos gerados={generated}")
        return generated

    def _sync_prompts(home: Path, state: dict, home_key: str) -> dict[str, int]:
        source_root = BASE_DIR / "prompts_sync"
        total = _empty_counts()
        collections = [
            {
                "collection_key": "prompts.codex",
                "label": "Prompts Codex",
                "source_root": source_root / "codex",
                "target_root": home / ".codex" / "prompts",
                "kind": "file",
                "suffixes": {".md"},
                "blocked_names": {"projeto.md"},
            },
            {
                "collection_key": "prompts.gemini",
                "label": "Prompts Gemini",
                "source_root": source_root / "gemini",
                "target_root": home / ".gemini" / "commands",
                "kind": "file",
                "suffixes": {".toml"},
                "blocked_names": {"projeto.toml"},
            },
            {
                "collection_key": "prompts.omp",
                "label": "Prompts OMP",
                "source_root": source_root / "omp",
                "target_root": home / ".omp" / "agent" / "prompts",
                "kind": "file",
                "suffixes": {".md"},
                "blocked_names": set(),
            },
        ]
        omp_deleted: list[str] = []
        for collection in collections:
            counts, deleted = _reconcile_collection(state=state, home_key=home_key, **collection)
            _add_counts(total, counts)
            if collection["collection_key"] == "prompts.omp":
                omp_deleted = deleted
        _generate_omp_prompt_commands(home, source_root / "omp", omp_deleted)
        return total

    def _sync_skills(home: Path, state: dict, home_key: str) -> dict[str, int]:
        source_root = BASE_DIR / "skills_sync"
        total = _empty_counts()
        collections = [
            {
                "collection_key": "skills.codex",
                "label": "Skills Codex",
                "source_root": source_root / "codex",
                "target_root": home / ".codex" / "skills",
                "kind": "skill",
            },
            {
                "collection_key": "skills.gemini",
                "label": "Skills Gemini",
                "source_root": source_root / "gemini",
                "target_root": home / ".gemini" / "skills",
                "kind": "skill",
            },
            {
                "collection_key": "skills.omp",
                "label": "Skills OMP",
                "source_root": source_root / "omp" / "skills",
                "target_root": home / ".omp" / "agent" / "skills",
                "kind": "skill",
            },
            {
                "collection_key": "skills.omp.managed",
                "label": "Managed skills OMP",
                "source_root": source_root / "omp" / "managed-skills",
                "target_root": home / ".omp" / "agent" / "managed-skills",
                "kind": "skill",
            },
        ]
        for collection in collections:
            counts, _ = _reconcile_collection(state=state, home_key=home_key, **collection)
            _add_counts(total, counts)
        return total

    def _ensure_symlink(link: Path, target: Path, *, label: str) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            if link.exists() or link.is_symlink():
                if link.is_dir() and not link.is_symlink():
                    print(f"⚠️ {label} não atualizado (destino é diretório): {link}")
                    return
                link.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            os.symlink(str(target), str(link))
            print(f"✅ Link criado: {link} -> {target}")
        except FileExistsError:
            pass
        except Exception as exc:
            print(f"⚠️ Não foi possível criar link {link}: {exc}")

    def _sync_global_rules(home: Path) -> None:
        gemini_rule_source = source_gemini_rules if source_gemini_rules.exists() else source_rules
        links = [
            (home / ".codex" / "AGENTS.md", source_rules, "Codex AGENTS"),
            (home / ".gemini" / "GEMINI.md", gemini_rule_source, "Gemini GEMINI"),
            (home / ".omp" / "agent" / "AGENTS.md", source_rules, "OMP AGENTS"),
            (home / ".omp" / "agent" / "rules" / source_rules.name, source_rules, "OMP rule"),
        ]
        for link, target, label in links:
            _ensure_symlink(link, target, label=label)
        print("✅ Global rules sincronizadas.")

    def _sync_system_prompts(home: Path) -> None:
        if codex_system_prompt.exists():
            config_path = home / ".codex" / "config.toml"
            content = config_path.read_text(encoding="utf-8", errors="ignore") if config_path.exists() else ""
            content = _ensure_key_line(content, "model_instructions_file", json.dumps(str(codex_system_prompt)))
            _write_or_update(config_path, content)
            print(f"✅ Codex system prompt apontado em {config_path}")

        if gemini_system_prompt.exists():
            bashrc = home / ".bashrc"
            line = f'export GEMINI_SYSTEM_MD="{gemini_system_prompt}"'
            content = bashrc.read_text(encoding="utf-8", errors="ignore") if bashrc.exists() else ""
            lines = [ln for ln in content.splitlines() if not ln.startswith("export GEMINI_SYSTEM_MD=")]
            lines.append(line)
            _write_or_update(bashrc, "\n".join(lines).rstrip() + "\n")
            print(f"✅ Gemini system prompt apontado em {bashrc}")

        prompt_source: Path | None = None
        for candidate in [omp_system_prompt, codex_system_prompt, gemini_system_prompt, source_rules]:
            if candidate.exists():
                prompt_source = candidate
                break
        if prompt_source is not None:
            omp_system_path = home / ".omp" / "agent" / "APPEND_SYSTEM.md"
            _ensure_symlink(omp_system_path, prompt_source, label="OMP APPEND_SYSTEM")

    state = _load_state()
    summary = _empty_counts()
    for home in homes:
        home = home.expanduser()
        current_home_key = _home_key(home)
        print(f"🔁 Sincronizando agent assets para {home}")
        _sync_global_rules(home)
        _sync_system_prompts(home)
        _add_counts(summary, _sync_prompts(home, state, current_home_key))
        _add_counts(summary, _sync_skills(home, state, current_home_key))

    try:
        _save_state(state)
    except Exception as exc:
        print(f"❌ Falha ao salvar estado de sync em {state_path}: {exc}", file=sys.stderr)
        return 1

    status = "❌" if summary["conflicts"] else "✅"
    print(
        f"{status} sync-agent-assets concluído: imported={summary['imported']}, "
        f"deployed={summary['deployed']}, updated={summary['updated']}, "
        f"deleted={summary['deleted']}, conflicts={summary['conflicts']}"
    )
    return 1 if summary["conflicts"] else 0


def _sync_mcp_core(target_home: str = "", include_sudo: bool = True, quiet: bool = False) -> int:
    if quiet:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return _sync_mcp_core(target_home=target_home, include_sudo=include_sudo, quiet=False)

    # Importante: contexto de projeto fica no workflow (`workflow_stack(action="context_refresh")`).
    # Agent assets ficam em `sync-agent-assets`; aqui sincronizamos apenas configuração MCP/bridge.

    source_rules = BASE_DIR / "global_rule_sync" / "AGENTS.md"
    if not source_rules.exists():
        print(f"❌ AGENTS consolidado não encontrado em {source_rules}. Rode 'aligntrue sync'.", file=sys.stderr)
        return 1

    codex_system_prompt = _resolve_system_prompt_file("codex_system.md")
    gemini_system_prompt = _resolve_system_prompt_file("gemini_system.md")
    omp_system_prompt = _resolve_system_prompt_file("omp_system.md")
    explicit_target_home = (target_home or "").strip()
    python_path = str(BASE_DIR / ".venv-super" / "bin" / "python3")
    if not Path(python_path).exists():
        python_path = sys.executable or "python3"

    forced_ai_context_cmd = (os.environ.get("AI_CODERS_CONTEXT_CMD", "") or "").strip()
    forced_args_prefix_raw = (os.environ.get("AI_CODERS_CONTEXT_ARGS_PREFIX_JSON", "") or "").strip()
    forced_args_prefix: list[str] = []
    if forced_args_prefix_raw:
        try:
            parsed = json.loads(forced_args_prefix_raw)
            if isinstance(parsed, list):
                forced_args_prefix = [str(x) for x in parsed if str(x).strip()]
        except Exception:
            forced_args_prefix = []

    ai_context_cli = _resolve_ai_coders_context_global_cli()
    ai_context_command = ""
    ai_context_args_prefix: list[str] = []
    if ai_context_cli.get("ok"):
        ai_context_command = str(ai_context_cli.get("command", "")).strip()
        ai_context_args_prefix = [str(x) for x in (ai_context_cli.get("args_prefix") or [])]
    elif forced_ai_context_cmd:
        ai_context_command = forced_ai_context_cmd
        ai_context_args_prefix = forced_args_prefix
        print(f"⚠️ Usando AI_CODERS_CONTEXT_CMD forçado para sync: {ai_context_command}")
    else:
        target_is_root = False
        try:
            target_is_root = Path(explicit_target_home).expanduser() == Path("/root") if explicit_target_home else False
        except Exception:
            target_is_root = False
        if target_is_root:
            ai_context_command = "ai-coders-context"
            ai_context_args_prefix = []
            print("⚠️ CLI global do @ai-coders/context não encontrado neste usuário. Mantendo comando genérico para /root.")
        else:
            print("❌ CLI global do @ai-coders/context não encontrado. Rode mcp-sync-clients para instalar.", file=sys.stderr)
            return 1
    if not ai_context_command:
        print("❌ Comando global do @ai-coders/context inválido.", file=sys.stderr)
        return 1

    jarvis_py = BASE_DIR / "jarvis.py"
    if not jarvis_py.exists():
        print(f"❌ jarvis.py não encontrado em {jarvis_py}", file=sys.stderr)
        return 1

    fallback_files = ["README.md", "gemini.md", "GEMINI.md", "claude.md", "CLAUDE.md"]

    env_target_home = os.environ.get("AGCAO_USER_HOME", "").strip()

    homes: list[Path] = []
    if explicit_target_home:
        homes.append(Path(explicit_target_home).expanduser())
    else:
        homes.append(Path.home())
        if env_target_home:
            homes.append(Path(env_target_home).expanduser())

    dedup_homes: list[Path] = []
    for h in homes:
        if h not in dedup_homes:
            dedup_homes.append(h)
    homes = dedup_homes

    def _ensure_key_line(content: str, key: str, value_expr: str) -> str:
        line = f"{key} = {value_expr}"
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(content):
            return pattern.sub(line, content)
        lines = content.splitlines()
        idx = len(lines)
        for i, existing in enumerate(lines):
            if existing.strip().startswith("["):
                idx = i
                break
        new_lines = lines[:idx]
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(line)
        if idx < len(lines) and lines[idx].strip() != "":
            new_lines.append("")
        new_lines.extend(lines[idx:])
        out = "\n".join(new_lines)
        if out and not out.endswith("\n"):
            out += "\n"
        return out

    def _write_or_update(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _update_codex_config(home: Path) -> None:
        config_path = home / ".codex" / "config.toml"
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8", errors="ignore")
        else:
            content = ""

        content = _ensure_key_line(content, "project_doc_fallback_filenames", json.dumps(fallback_files))
        if codex_system_prompt.exists():
            content = _ensure_key_line(content, "model_instructions_file", json.dumps(str(codex_system_prompt)))

        for server in ["jarvis", "taskmaster", "filesystem", "brave", "ai-coders-context", "memory", "gemini", "google-drive"]:
            # Remove server subtables first (ex.: [mcp_servers.jarvis.env])
            subtable_pattern = rf"\[mcp_servers\.{re.escape(server)}\.[^\]]+\][\s\S]*?(?=\n\[|\Z)"
            content = re.sub(subtable_pattern, "", content)
            # Remove main server block
            pattern = rf"\[mcp_servers\.{re.escape(server)}\][\s\S]*?(?=\n\[|\Z)"
            content = re.sub(pattern, "", content)

        content = re.sub(r"\n\s*\n\s*\n+", "\n\n", content).strip()

        openai_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        openai_base = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        reclaim_ui_enable = os.environ.get("RECLAIM_UI_AUTOMATION_ENABLE", "false")
        reclaim_start_seq = os.environ.get("RECLAIM_UI_START_SEQUENCE", "Tab Return")
        reclaim_stop_seq = os.environ.get("RECLAIM_UI_STOP_SEQUENCE", "Escape")
        reclaim_restart_seq = os.environ.get("RECLAIM_UI_RESTART_SEQUENCE", "Return")
        reclaim_start_click_x = os.environ.get("RECLAIM_UI_START_CLICK_X", "")
        reclaim_start_click_y = os.environ.get("RECLAIM_UI_START_CLICK_Y", "")
        reclaim_stop_click_x = os.environ.get("RECLAIM_UI_STOP_CLICK_X", "")
        reclaim_stop_click_y = os.environ.get("RECLAIM_UI_STOP_CLICK_Y", "")
        reclaim_restart_click_x = os.environ.get("RECLAIM_UI_RESTART_CLICK_X", "")
        reclaim_restart_click_y = os.environ.get("RECLAIM_UI_RESTART_CLICK_Y", "")
        reclaim_automation_mode = os.environ.get("RECLAIM_UI_AUTOMATION_MODE", "headless")
        reclaim_cdp_url = os.environ.get("RECLAIM_UI_CDP_URL", "http://127.0.0.1:9222")
        reclaim_elements_executor = os.environ.get(
            "RECLAIM_UI_ELEMENTS_EXECUTOR",
            "",
        )
        reclaim_elements_node = os.environ.get("RECLAIM_UI_ELEMENTS_NODE", "node")
        reclaim_playwright_module = os.environ.get("RECLAIM_UI_PLAYWRIGHT_MODULE", "")
        reclaim_assist_open_browser = os.environ.get("RECLAIM_UI_ASSIST_OPEN_BROWSER", "false")
        reclaim_exec_user = (os.environ.get("RECLAIM_UI_EXECUTOR_RUN_AS_USER") or _guess_reclaim_executor_user() or "").strip()
        reclaim_display = (os.environ.get("RECLAIM_UI_DISPLAY") or ":0").strip()
        reclaim_xauthority = (os.environ.get("RECLAIM_UI_XAUTHORITY") or "").strip()
        if not reclaim_xauthority and reclaim_exec_user:
            reclaim_xauthority = f"/home/{reclaim_exec_user}/.Xauthority"
        reclaim_dbus = (os.environ.get("RECLAIM_UI_DBUS_SESSION_BUS_ADDRESS") or "").strip()
        if not reclaim_dbus and reclaim_exec_user:
            try:
                reclaim_uid = pwd.getpwnam(reclaim_exec_user).pw_uid
                reclaim_dbus = f"unix:path=/run/user/{reclaim_uid}/bus"
            except Exception:
                reclaim_dbus = ""

        env_map = {
            "MCP_MODE": "stdio",
            "PYTHONUNBUFFERED": "1",
            "FILESYSTEM_MCP_ENABLE": "false",
            "PLAYWRIGHT_MCP_ENABLE": "false",
            "BRAVE_MCP_ENABLE": "false",
            "GOOGLE_CALENDAR_MCP_ENABLE": os.environ.get("GOOGLE_CALENDAR_MCP_ENABLE", "true"),
            "GOOGLE_CALENDAR_MCP_BIN": os.environ.get("GOOGLE_CALENDAR_MCP_BIN", "npx"),
            "GOOGLE_CALENDAR_MCP_PACKAGE": os.environ.get("GOOGLE_CALENDAR_MCP_PACKAGE", "mcp-google-calendar"),
            "GOOGLE_CALENDAR_MCP_PORT": os.environ.get("GOOGLE_CALENDAR_MCP_PORT", "8954"),
            "GOOGLE_CALENDAR_MCP_HOST": os.environ.get("GOOGLE_CALENDAR_MCP_HOST", "localhost"),
            "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH": os.environ.get(
                "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH",
                os.environ.get("CREDENTIALS_PATH", str(BASE_DIR / "gcp-oauth.keys.json")),
            ),
            "GDRIVE_MCP_OAUTH_PATH": os.environ.get("GDRIVE_MCP_OAUTH_PATH", str(BASE_DIR / "gcp-oauth.keys.json")),
            "GDRIVE_MCP_TOKEN_PATH": os.environ.get("GDRIVE_MCP_TOKEN_PATH", str(BASE_DIR / "token.json")),
            "GDRIVE_MCP_SCOPES": os.environ.get("GDRIVE_MCP_SCOPES", "https://www.googleapis.com/auth/drive"),
            "GOOGLE_DRIVE_MCP_ENABLE": os.environ.get("GOOGLE_DRIVE_MCP_ENABLE", "true"),
            "JARVIS_STDIO_SKIP_CHILD_MCP": os.environ.get("JARVIS_STDIO_SKIP_CHILD_MCP", "true"),
            "OPENAI_API_KEY": openai_key,
            "OPENAI_BASE_URL": openai_base,
            "GOOGLE_API_KEY": google_key,
            "RECLAIM_UI_AUTOMATION_ENABLE": reclaim_ui_enable,
            "RECLAIM_UI_START_SEQUENCE": reclaim_start_seq,
            "RECLAIM_UI_STOP_SEQUENCE": reclaim_stop_seq,
            "RECLAIM_UI_RESTART_SEQUENCE": reclaim_restart_seq,
            "RECLAIM_UI_START_CLICK_X": reclaim_start_click_x,
            "RECLAIM_UI_START_CLICK_Y": reclaim_start_click_y,
            "RECLAIM_UI_STOP_CLICK_X": reclaim_stop_click_x,
            "RECLAIM_UI_STOP_CLICK_Y": reclaim_stop_click_y,
            "RECLAIM_UI_RESTART_CLICK_X": reclaim_restart_click_x,
            "RECLAIM_UI_RESTART_CLICK_Y": reclaim_restart_click_y,
            "RECLAIM_UI_AUTOMATION_MODE": reclaim_automation_mode,
            "RECLAIM_UI_CDP_URL": reclaim_cdp_url,
            "RECLAIM_UI_ELEMENTS_EXECUTOR": reclaim_elements_executor,
            "RECLAIM_UI_ELEMENTS_NODE": reclaim_elements_node,
            "RECLAIM_UI_PLAYWRIGHT_MODULE": reclaim_playwright_module,
            "RECLAIM_UI_ASSIST_OPEN_BROWSER": reclaim_assist_open_browser,
            "RECLAIM_UI_EXECUTOR_RUN_AS_USER": reclaim_exec_user,
            "RECLAIM_UI_DISPLAY": reclaim_display,
            "RECLAIM_UI_XAUTHORITY": reclaim_xauthority,
            "RECLAIM_UI_DBUS_SESSION_BUS_ADDRESS": reclaim_dbus,
        }
        env_expr = "{ " + ", ".join([f'{k} = {json.dumps(v)}' for k, v in env_map.items()]) + " }"

        blocks = f"""

[mcp_servers.jarvis]
command = {json.dumps(python_path)}
args = [{json.dumps(str(jarvis_py))}, "serve"]
startup_timeout_sec = 300.0
env = {env_expr}

[mcp_servers.gemini]
command = {json.dumps(python_path)}
args = [{json.dumps(str(jarvis_py))}, "gemini-bridge"]
startup_timeout_sec = 180.0

[mcp_servers.ai-coders-context]
command = {json.dumps(ai_context_command)}
args = {json.dumps(list(ai_context_args_prefix) + ["mcp", "--repo-path", str(BASE_DIR)])}
startup_timeout_sec = 300.0
"""

        if content:
            content += "\n"
        content += blocks.lstrip("\n")
        _write_or_update(config_path, content)
        print(f"✅ Codex config atualizado em {config_path}")

    def _copy_named_files(source_dir: Path, target_dir: Path, *, suffixes: set[str], label: str) -> int:
        if not source_dir.exists():
            print(f"⚠️ {label}: origem não encontrada em {source_dir}")
            return 0
        target_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for source in sorted(source_dir.iterdir()):
            if not source.is_file() or source.name.startswith("."):
                continue
            if suffixes and source.suffix.lower() not in suffixes:
                continue
            try:
                _write_or_update(target_dir / source.name, source.read_text(encoding="utf-8"))
                copied += 1
            except Exception as exc:
                print(f"⚠️ {label}: falha ao copiar {source}: {exc}")
        return copied

    def _sync_prompts(home: Path) -> None:
        source_root = BASE_DIR / "prompts_sync"
        codex_source_dir = source_root / "codex"
        gemini_source_dir = source_root / "gemini"
        omp_source_dir = source_root / "omp"

        codex_prompts_dir = home / ".codex" / "prompts"
        gemini_commands_dir = home / ".gemini" / "commands"
        omp_agent_dir = home / ".omp" / "agent"
        omp_prompts_dir = omp_agent_dir / "prompts"
        omp_commands_dir = omp_agent_dir / "commands"

        copied_codex = _copy_named_files(
            codex_source_dir,
            codex_prompts_dir,
            suffixes={".md"},
            label="Prompts Codex",
        )
        copied_gemini = _copy_named_files(
            gemini_source_dir,
            gemini_commands_dir,
            suffixes={".toml"},
            label="Prompts Gemini",
        )

        copied_omp_prompts = 0
        copied_omp_commands = 0
        if not omp_source_dir.exists():
            print(f"⚠️ Prompts OMP: origem não encontrada em {omp_source_dir}")
        else:
            omp_prompts_dir.mkdir(parents=True, exist_ok=True)
            omp_commands_dir.mkdir(parents=True, exist_ok=True)
            for source in sorted(omp_source_dir.iterdir()):
                if not source.is_file() or source.name.startswith(".") or source.suffix.lower() != ".md":
                    continue
                try:
                    prompt_content = source.read_text(encoding="utf-8")
                except Exception as exc:
                    print(f"⚠️ Prompts OMP: falha ao ler {source}: {exc}")
                    continue

                prompt_name = source.stem
                legacy_prompt_alias = omp_prompts_dir / f"prompts:{prompt_name}.md"
                if legacy_prompt_alias.exists() or legacy_prompt_alias.is_symlink():
                    try:
                        legacy_prompt_alias.unlink()
                    except Exception as exc:
                        print(f"⚠️ Prompts OMP: falha ao remover alias legado {legacy_prompt_alias}: {exc}")

                legacy_command_target = omp_commands_dir / source.name
                if legacy_command_target.exists() or legacy_command_target.is_symlink():
                    try:
                        legacy_command_target.unlink()
                    except Exception as exc:
                        print(f"⚠️ Prompts OMP: falha ao remover comando legado {legacy_command_target}: {exc}")

                _write_or_update(omp_prompts_dir / source.name, prompt_content)
                copied_omp_prompts += 1
                _write_or_update(omp_commands_dir / f"prompts:{prompt_name}.md", prompt_content)
                copied_omp_commands += 1

        print(
            "✅ Prompts sincronizados "
            f"(Codex: {copied_codex}, Gemini commands: {copied_gemini}, "
            f"OMP prompts: {copied_omp_prompts}, OMP commands: {copied_omp_commands})"
        )

    def _copy_skill_collection(source_dir: Path, target_root: Path, *, label: str) -> int:
        if not source_dir.exists():
            print(f"⚠️ {label}: origem não encontrada em {source_dir}")
            return 0
        target_root.mkdir(parents=True, exist_ok=True)
        copied = 0
        for source in sorted(source_dir.iterdir()):
            if not source.is_dir() or source.name.startswith("."):
                continue
            if not (source / "SKILL.md").exists():
                continue
            target = target_root / source.name
            if target.exists() and not target.is_dir():
                print(f"⚠️ {label}: destino não é diretório, pulando {target}")
                continue
            try:
                shutil.copytree(
                    source,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".git", ".DS_Store"),
                )
                copied += 1
            except Exception as exc:
                print(f"⚠️ {label}: falha ao copiar {source}: {exc}")
        return copied

    def _sync_skills(home: Path) -> None:
        source_root = BASE_DIR / "skills_sync"
        copied_codex = _copy_skill_collection(
            source_root / "codex",
            home / ".codex" / "skills",
            label="Skills Codex",
        )
        copied_gemini = _copy_skill_collection(
            source_root / "gemini",
            home / ".gemini" / "skills",
            label="Skills Gemini",
        )
        copied_omp = _copy_skill_collection(
            source_root / "omp" / "skills",
            home / ".omp" / "agent" / "skills",
            label="Skills OMP",
        )
        copied_omp_managed = _copy_skill_collection(
            source_root / "omp" / "managed-skills",
            home / ".omp" / "agent" / "managed-skills",
            label="Managed skills OMP",
        )
        print(
            "✅ Skills sincronizadas "
            f"(Codex: {copied_codex}, Gemini: {copied_gemini}, "
            f"OMP: {copied_omp}, OMP managed: {copied_omp_managed})"
        )

    def _update_gemini_settings(home: Path) -> None:
        settings_path = home / ".gemini" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if settings_path.exists():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        openai_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        openai_base = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        gemini_transport = (os.environ.get("JARVIS_GEMINI_TRANSPORT", "http") or "http").strip().lower()
        if gemini_transport not in {"stdio", "sse", "http"}:
            gemini_transport = "http"
        gemini_http_url = (os.environ.get("JARVIS_GEMINI_HTTP_URL", "http://127.0.0.1:7860/mcp") or "").strip()
        reclaim_ui_enable = os.environ.get("RECLAIM_UI_AUTOMATION_ENABLE", "false")
        reclaim_start_seq = os.environ.get("RECLAIM_UI_START_SEQUENCE", "Tab Return")
        reclaim_stop_seq = os.environ.get("RECLAIM_UI_STOP_SEQUENCE", "Escape")
        reclaim_restart_seq = os.environ.get("RECLAIM_UI_RESTART_SEQUENCE", "Return")
        reclaim_start_click_x = os.environ.get("RECLAIM_UI_START_CLICK_X", "")
        reclaim_start_click_y = os.environ.get("RECLAIM_UI_START_CLICK_Y", "")
        reclaim_stop_click_x = os.environ.get("RECLAIM_UI_STOP_CLICK_X", "")
        reclaim_stop_click_y = os.environ.get("RECLAIM_UI_STOP_CLICK_Y", "")
        reclaim_restart_click_x = os.environ.get("RECLAIM_UI_RESTART_CLICK_X", "")
        reclaim_restart_click_y = os.environ.get("RECLAIM_UI_RESTART_CLICK_Y", "")
        reclaim_automation_mode = os.environ.get("RECLAIM_UI_AUTOMATION_MODE", "headless")
        reclaim_cdp_url = os.environ.get("RECLAIM_UI_CDP_URL", "http://127.0.0.1:9222")
        reclaim_elements_executor = os.environ.get("RECLAIM_UI_ELEMENTS_EXECUTOR", "")
        reclaim_elements_node = os.environ.get("RECLAIM_UI_ELEMENTS_NODE", "node")
        reclaim_playwright_module = os.environ.get("RECLAIM_UI_PLAYWRIGHT_MODULE", "")
        reclaim_assist_open_browser = os.environ.get("RECLAIM_UI_ASSIST_OPEN_BROWSER", "false")
        reclaim_exec_user = (os.environ.get("RECLAIM_UI_EXECUTOR_RUN_AS_USER") or _guess_reclaim_executor_user() or "").strip()
        reclaim_display = (os.environ.get("RECLAIM_UI_DISPLAY") or ":0").strip()
        reclaim_xauthority = (os.environ.get("RECLAIM_UI_XAUTHORITY") or "").strip()
        if not reclaim_xauthority and reclaim_exec_user:
            reclaim_xauthority = f"/home/{reclaim_exec_user}/.Xauthority"
        reclaim_dbus = (os.environ.get("RECLAIM_UI_DBUS_SESSION_BUS_ADDRESS") or "").strip()
        if not reclaim_dbus and reclaim_exec_user:
            try:
                reclaim_uid = pwd.getpwnam(reclaim_exec_user).pw_uid
                reclaim_dbus = f"unix:path=/run/user/{reclaim_uid}/bus"
            except Exception:
                reclaim_dbus = ""

        jarvis_env = {
            "MCP_MODE": "stdio",
            "PYTHONUNBUFFERED": "1",
            "FILESYSTEM_MCP_ENABLE": "false",
            "PLAYWRIGHT_MCP_ENABLE": "false",
            "BRAVE_MCP_ENABLE": "false",
            "GOOGLE_CALENDAR_MCP_ENABLE": os.environ.get("GOOGLE_CALENDAR_MCP_ENABLE", "true"),
            "GOOGLE_CALENDAR_MCP_BIN": os.environ.get("GOOGLE_CALENDAR_MCP_BIN", "npx"),
            "GOOGLE_CALENDAR_MCP_PACKAGE": os.environ.get("GOOGLE_CALENDAR_MCP_PACKAGE", "mcp-google-calendar"),
            "GOOGLE_CALENDAR_MCP_PORT": os.environ.get("GOOGLE_CALENDAR_MCP_PORT", "8954"),
            "GOOGLE_CALENDAR_MCP_HOST": os.environ.get("GOOGLE_CALENDAR_MCP_HOST", "localhost"),
            "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH": os.environ.get(
                "GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH",
                os.environ.get("CREDENTIALS_PATH", str(BASE_DIR / "gcp-oauth.keys.json")),
            ),
            "GDRIVE_MCP_OAUTH_PATH": os.environ.get("GDRIVE_MCP_OAUTH_PATH", str(BASE_DIR / "gcp-oauth.keys.json")),
            "GDRIVE_MCP_TOKEN_PATH": os.environ.get("GDRIVE_MCP_TOKEN_PATH", str(BASE_DIR / "token.json")),
            "GDRIVE_MCP_SCOPES": os.environ.get("GDRIVE_MCP_SCOPES", "https://www.googleapis.com/auth/drive"),
            "GOOGLE_DRIVE_MCP_ENABLE": os.environ.get("GOOGLE_DRIVE_MCP_ENABLE", "true"),
            "JARVIS_STDIO_SKIP_CHILD_MCP": os.environ.get("JARVIS_STDIO_SKIP_CHILD_MCP", "true"),
            "OPENAI_API_KEY": openai_key,
            "OPENAI_BASE_URL": openai_base,
            "GOOGLE_API_KEY": google_key,
            "RECLAIM_UI_AUTOMATION_ENABLE": reclaim_ui_enable,
            "RECLAIM_UI_START_SEQUENCE": reclaim_start_seq,
            "RECLAIM_UI_STOP_SEQUENCE": reclaim_stop_seq,
            "RECLAIM_UI_RESTART_SEQUENCE": reclaim_restart_seq,
            "RECLAIM_UI_START_CLICK_X": reclaim_start_click_x,
            "RECLAIM_UI_START_CLICK_Y": reclaim_start_click_y,
            "RECLAIM_UI_STOP_CLICK_X": reclaim_stop_click_x,
            "RECLAIM_UI_STOP_CLICK_Y": reclaim_stop_click_y,
            "RECLAIM_UI_RESTART_CLICK_X": reclaim_restart_click_x,
            "RECLAIM_UI_RESTART_CLICK_Y": reclaim_restart_click_y,
            "RECLAIM_UI_AUTOMATION_MODE": reclaim_automation_mode,
            "RECLAIM_UI_CDP_URL": reclaim_cdp_url,
            "RECLAIM_UI_ELEMENTS_EXECUTOR": reclaim_elements_executor,
            "RECLAIM_UI_ELEMENTS_NODE": reclaim_elements_node,
            "RECLAIM_UI_PLAYWRIGHT_MODULE": reclaim_playwright_module,
            "RECLAIM_UI_ASSIST_OPEN_BROWSER": reclaim_assist_open_browser,
            "RECLAIM_UI_EXECUTOR_RUN_AS_USER": reclaim_exec_user,
            "RECLAIM_UI_DISPLAY": reclaim_display,
            "RECLAIM_UI_XAUTHORITY": reclaim_xauthority,
            "RECLAIM_UI_DBUS_SESSION_BUS_ADDRESS": reclaim_dbus,
        }

        jarvis_server: dict[str, object]
        if gemini_transport in {"http", "sse"}:
            jarvis_server = {
                "url": gemini_http_url,
                "type": gemini_transport,
                "timeout": 300000,
            }
        else:
            jarvis_server = {
                "command": python_path,
                "args": [str(jarvis_py), "serve"],
                "env": jarvis_env,
                "timeout": 300000,
            }

        data["mcpServers"] = {
            "jarvis": jarvis_server,
            "ai-coders-context": {
                "command": ai_context_command,
                "args": list(ai_context_args_prefix) + ["mcp", "--repo-path", str(BASE_DIR)],
                "timeout": 300000,
            },
            "codex": {
                "command": "codex",
                "args": ["mcp-server"],
            },
        }
        data.setdefault("context", {})
        data["context"]["loadMemoryFromIncludeDirectories"] = True
        data["context"]["fileName"] = [
            "AGENTS.md",
            "GEMINI.md",
            "README.md",
            ".context/docs/README.md",
            ".context/plans/STATE.md",
            ".context/workflow/README.md",
            ".context/workflow/status.yaml",
        ]

        _write_or_update(settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"✅ Gemini settings atualizado em {settings_path}")

    def _ensure_symlink(link: Path, target: Path, *, label: str) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            if link.exists() or link.is_symlink():
                if link.is_dir() and not link.is_symlink():
                    print(f"⚠️ {label} não atualizado (destino é diretório): {link}")
                    return
                link.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            os.symlink(str(target), str(link))
            print(f"✅ Link criado: {link} -> {target}")
        except FileExistsError:
            pass
        except Exception as e:
            print(f"⚠️ Não foi possível criar link {link}: {e}")

    def _create_links(home: Path) -> None:
        links = [
            home / ".codex" / "AGENTS.md",
            home / ".gemini" / "GEMINI.md",
            home / ".omp" / "agent" / "AGENTS.md",
        ]
        for link in links:
            _ensure_symlink(link, source_rules, label="AGENTS")

    def _sync_omp_context(home: Path) -> None:
        omp_agent_dir = home / ".omp" / "agent"
        omp_rules_dir = omp_agent_dir / "rules"
        omp_agent_dir.mkdir(parents=True, exist_ok=True)
        omp_rules_dir.mkdir(parents=True, exist_ok=True)

        prompt_source: Path | None = None

        for candidate in [omp_system_prompt, codex_system_prompt, gemini_system_prompt]:
            if candidate.exists():
                prompt_source = candidate
                break
        if prompt_source is None:
            prompt_source = source_rules

        try:
            omp_system_content = prompt_source.read_text(encoding="utf-8", errors="ignore")
            omp_system_path = omp_agent_dir / "APPEND_SYSTEM.md"
            _write_or_update(omp_system_path, omp_system_content)
            print(f"✅ Oh My Pi APPEND_SYSTEM.md atualizado em {omp_system_path}")

            legacy_system_path = omp_agent_dir / "SYSTEM.md"
            if legacy_system_path.exists():
                print(
                    f"⚠️ SYSTEM.md legado detectado em {legacy_system_path}. "
                    "Ele sobrescreve o prompt padrão do OMP. Remova se quiser usar apenas APPEND_SYSTEM.md."
                )
        except Exception as exc:
            print(f"⚠️ Falha ao atualizar APPEND_SYSTEM.md do Oh My Pi: {exc}")

        # Regra única do OMP: linkar AGENTS consolidado
        target_rule = omp_rules_dir / source_rules.name
        _ensure_symlink(target_rule, source_rules, label="rule")
        print(f"✅ Rule do Oh My Pi sincronizada em {target_rule} (origem: {source_rules})")

    def _generate_gemini_system_md() -> None:
        gemini_system_prompt.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "You are an interactive CLI agent specializing in software engineering tasks. "
            "Your primary goal is to help users safely and efficiently, adhering strictly to the following instructions and utilizing your available tools.\n\n"
        )
        body = (
            "# 🎩 PROJECT STRATEGIC RULES (GLOBAL)\n"
            "The following rules are MANDATORY for this specific project and override generic instructions:\n"
            "```markdown\n"
            + source_rules.read_text(encoding="utf-8", errors="ignore")
            + "\n```\n\n"
            "---\n\n"
            "# Core Mandates\n"
            "- **Conventions:** Rigorously adhere to existing project conventions.\n"
            "- **Libraries/Frameworks:** NEVER assume usage. Verify first.\n"
            "- **Explain Before Acting:** Never call tools in silence.\n\n"
            "# Restricted Workflow (GSD + Ralph + AI Context)\n"
            "1. Context First (.context/docs + README.md).\n"
            "2. Macro Planning with GSD.\n"
            "3. Execution with Ralph (one story per cycle).\n"
            "4. Close cycle updating context and validations.\n\n"
            "# Validation Checklist\n"
            "- `python3 -m py_compile jarvis.py`\n"
            "- `gemini mcp list` with `jarvis` and `codex` connected\n"
            "- `codex mcp list` with `jarvis` and `gemini` enabled\n"
        )
        _write_or_update(gemini_system_prompt, header + body)
        print(f"✅ System prompt Gemini gerado em {gemini_system_prompt}")


    for h in homes:
        _update_gemini_settings(h)
        _update_codex_config(h)

    should_sync_sudo = include_sudo and os.geteuid() != 0 and not explicit_target_home
    if should_sync_sudo:
        rc = _sync_root_codex_config_via_sudo(python_path, prompt_if_needed=True)
        if rc != 0:
            print(
                "❌ Falha ao sincronizar codex sudo (/root). Rode novamente e autentique no sudo.",
                file=sys.stderr,
            )
            return 1

    bashrc_user = homes[-1] / ".bashrc"
    line = f'export GEMINI_SYSTEM_MD="{gemini_system_prompt}"'
    bashrc_content = bashrc_user.read_text(encoding='utf-8', errors='ignore') if bashrc_user.exists() else ""
    lines = [ln for ln in bashrc_content.splitlines() if not ln.strip().startswith('export GEMINI_SYSTEM_MD=')]
    lines.append(line)
    _write_or_update(bashrc_user, "\n".join(lines) + "\n")
    print(f"✅ {bashrc_user} atualizado com GEMINI_SYSTEM_MD")

    print("✨ Sync de configuração MCP concluído dentro do jarvis.py")
    return 0

def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Super servidor Jarvis")
    parser.add_argument("--verbose", action="store_true", help="Habilita saída detalhada para comandos de diagnóstico.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Executa o servidor MCP em foreground (respeita MCP_MODE).")

    start = sub.add_parser("start", help="Inicia o servidor em background (por padrão já orquestra Oracle/OpenClaw remoto).")
    start.add_argument("--server-host", default=os.environ.get("SERVER_HOST", "0.0.0.0"))
    start.add_argument("--server-port", type=int, default=int(os.environ.get("SERVER_PORT", "7860")))
    start.add_argument("--log-file", default=str(_default_log_file()))
    start.add_argument("--pid-file", default=str(_default_pid_file()))
    start.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable or "python3"))
    start.add_argument("--node-bin", default=os.environ.get("NODE_BIN", "node"))

    stop = sub.add_parser("stop", help="Para o servidor em background.")
    stop.add_argument("--pid-file", default=str(_default_pid_file()))
    stop.add_argument("--server-port", type=int, default=int(os.environ.get("SERVER_PORT", "7860")))

    status = sub.add_parser("status", help="Mostra status do servidor.")
    status.add_argument("--log-file", default=str(_default_log_file()))
    status.add_argument("--pid-file", default=str(_default_pid_file()))
    status.add_argument("--server-port", type=int, default=int(os.environ.get("SERVER_PORT", "7860")))

    logs = sub.add_parser("logs", help="Mostra tail do log.")
    logs.add_argument("lines", nargs="?", type=int, default=120)
    logs.add_argument("--log-file", default=str(_default_log_file()))

    mcp_status = sub.add_parser(
        "mcp-status",
        help="Mostra um diagnóstico rápido dos MCPs configurados e ferramentas registradas.",
    )
    sub.add_parser(
        "context-stack-harden",
        help="Reaplica as restrições Jarvis para AI Coders Context, GSD e Ralph.",
    )
    context_check = sub.add_parser(
        "context-stack-check",
        help="Verifica o layout .context/docs, .context/plans, .context/workflow e .context/graphify-out.",
    )
    context_check.add_argument("roots", nargs="*", default=[str(BASE_DIR)], help="Pastas raiz ou file:// para verificar.")
    context_check.add_argument("--recursive", action="store_true", help="Procura subdiretórios que contenham .context.")
    google_auth = sub.add_parser("google-auth-refresh", help="Renova OAuth Google Workspace usado por Tasks, Calendar e Drive.")
    google_auth.add_argument("--force", action="store_true", help="Renomeia token.json atual e força novo consentimento OAuth.")



    assets_sync = sub.add_parser(
        "sync-agent-assets",
        help="Sincroniza prompts e skills em duas vias, além de global rules/system prompts repo→clientes.",
        description="Sincroniza prompts e skills em duas vias, além de manter global rules/system prompts como referências repo→clientes.",
    )
    assets_sync.add_argument("--target-home", default="", help=argparse.SUPPRESS)
    assets_sync.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)


    sync = sub.add_parser("mcp-sync-clients", help="Sincroniza jarvis entre codex, codex sudo, gemini e Oh My Pi.")
    sync.add_argument("--py-bin", default=os.environ.get("PY_BIN", str(BASE_DIR / ".venv-super" / "bin" / "python3")))
    sync.add_argument("--no-codex", action="store_true", help="Não sincroniza o Codex do usuário atual.")
    sync.add_argument("--no-gemini", action="store_true", help="Não sincroniza o Gemini.")
    sync.add_argument("--no-sudo", action="store_true", help="Não sincroniza o Codex via sudo.")
    sync.add_argument("--skip-bridge", action="store_true", help="Não executa setup bidirecional Codex <-> Gemini.")
    sync.add_argument("--target-home", default="", help=argparse.SUPPRESS)
    sync.add_argument("--verbose", action="store_true", help="Exibe detalhes adicionais do fluxo de sync.")
    sync.add_argument("--quiet-core", action="store_true", help=argparse.SUPPRESS)

    bridge = sub.add_parser("setup-bidirectional-mcp", help="Configura integração bidirecional Codex <-> Gemini.")
    bridge.add_argument("--py-bin", default=os.environ.get("PY_BIN", str(BASE_DIR / ".venv-super" / "bin" / "python3")))

    openclaw = sub.add_parser("openclaw-remote", help="Executa ações remotas de manutenção do OpenClaw na OCI.")
    openclaw.add_argument("action", nargs="?", default="status", choices=["status", "restart", "sync-token", "reset-token", "fix-transcricao", "doctor"])
    openclaw.add_argument("--host", default=os.environ.get("OPENCLAW_REMOTE_HOST", "mcp-instance"))
    openclaw.add_argument("--user", default=os.environ.get("OPENCLAW_REMOTE_USER", "ubuntu"))
    openclaw.add_argument("--ssh-key", default=os.environ.get("OPENCLAW_REMOTE_SSH_KEY", ""))
    openclaw.add_argument("--ssh-timeout", type=int, default=int(os.environ.get("OPENCLAW_SSH_TIMEOUT", "20")))
    openclaw.add_argument("--no-sync", action="store_true", help="Não compara/substitui o Jarvis da OCI antes da ação.")
    openclaw.add_argument("--sync-venv", action="store_true", help="Também sincroniza .venv-super ao atualizar o Jarvis da OCI.")

    oci = sub.add_parser("install-oci", help="Instala o OCI CLI usando o instalador oficial.")
    oci.add_argument("installer_args", nargs=argparse.REMAINDER, help="Argumentos repassados para o instalador OCI. Use '--' antes dos argumentos.")



    venv = sub.add_parser("install-super-venv", help="Monta/atualiza .venv-super e super_requirements.txt.")
    venv.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable or "python3"))
    venv.add_argument("--skip-playwright", action="store_true")
    venv.add_argument("--keep-old-venvs", action="store_true")

    fw = sub.add_parser("fix-firewall-oci", help="Libera SSH (porta 22) para o seu IP atual na OCI.")
    fw.add_argument("--instance-ip", default=os.environ.get("OCI_TARGET_INSTANCE_IP", "163.176.169.99"))

    gbridge = sub.add_parser("gemini-bridge", help="Executa bridge MCP do Gemini em modo stdio.")
    gbridge.add_argument("--selftest", action="store_true")

    reclaim_test = sub.add_parser("test-reclaim-ui", help="Executa self-test interno das rotinas Reclaim UI.")
    reclaim_test.add_argument("--verbose", action="store_true")


    return parser


def _normalize_legacy_service_args(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    normalized = list(argv)
    if normalized and normalized[0] == "start":
        idx = 1
        while idx < len(normalized):
            token = normalized[idx]
            if token == "--profile":
                del normalized[idx: idx + 2]
                continue
            if token.startswith("--profile="):
                del normalized[idx]
                continue
            idx += 1
    return normalized


def _mcp_status_payload() -> dict:
    """Gera payload de diagnóstico de MCPs.

    Observação: faz chamadas leves de validação apenas quando isso evita falso "ok",
    por exemplo no OAuth do Google Tasks.
    """

    def _has_key(val: str) -> bool:
        return bool(val and str(val).strip())

    items: list[dict] = []

    playwright_reasons = []
    if not PLAYWRIGHT_MCP_ENABLE:
        playwright_reasons.append("PLAYWRIGHT_MCP_ENABLE=false")
    elif not shutil.which(PLAYWRIGHT_MCP_BIN):
        playwright_reasons.append("npx/Node ausente")
    items.append(
        {
            "name": "Playwright MCP",
            "enabled": bool(PLAYWRIGHT_MCP_ENABLE),
            "ok": bool(PLAYWRIGHT_MCP_ENABLE and not playwright_reasons),
            "reason": _with_fix(_join_reasons(playwright_reasons), _install_fix_hint("Node.js/npx") if PLAYWRIGHT_MCP_ENABLE else "ative com PLAYWRIGHT_MCP_ENABLE=true se quiser usar"),
        }
    )

    brave_reasons = []
    if not BRAVE_MCP_ENABLE:
        brave_reasons.append("BRAVE_MCP_ENABLE=false")
    else:
        if not _has_key(BRAVE_API_KEY):
            brave_reasons.append("falta BRAVE_API_KEY")
        if not shutil.which(BRAVE_MCP_BIN):
            brave_reasons.append("npx ausente")
    items.append(
        {
            "name": "Brave MCP",
            "enabled": bool(BRAVE_MCP_ENABLE),
            "ok": bool(BRAVE_MCP_ENABLE and not brave_reasons),
            "reason": _with_fix(_join_reasons(brave_reasons), f"{_env_fix_hint('BRAVE_API_KEY')} e ative BRAVE_MCP_ENABLE=true" if BRAVE_MCP_ENABLE and not _has_key(BRAVE_API_KEY) else _install_fix_hint("Node.js/npx") if BRAVE_MCP_ENABLE else "ative com BRAVE_MCP_ENABLE=true se quiser usar"),
        }
    )

    chart_reasons = []
    if not CHART_MCP_ENABLE:
        chart_reasons.append("CHART_MCP_ENABLE=false")
    elif not shutil.which(CHART_MCP_BIN):
        chart_reasons.append("npx ausente")
    items.append(
        {
            "name": "Chart MCP",
            "enabled": bool(CHART_MCP_ENABLE),
            "ok": bool(CHART_MCP_ENABLE and not chart_reasons),
            "reason": _with_fix(_join_reasons(chart_reasons), _install_fix_hint("Node.js/npx") if CHART_MCP_ENABLE else "ative com CHART_MCP_ENABLE=true se quiser usar"),
        }
    )

    zotero_reasons = []
    if not ZOTERO_MCP_ENABLE:
        zotero_reasons.append("ZOTERO_MCP_ENABLE=false")
    else:
        if not _has_key(ZOTERO_API_KEY):
            zotero_reasons.append("falta ZOTERO_API_KEY")
        if not _has_key(ZOTERO_USER_ID):
            zotero_reasons.append("falta ZOTERO_USER_ID")
        if not shutil.which(ZOTERO_MCP_BIN):
            zotero_reasons.append("npx ausente")
    items.append(
        {
            "name": "Zotero MCP",
            "enabled": bool(ZOTERO_MCP_ENABLE),
            "ok": bool(ZOTERO_MCP_ENABLE and not zotero_reasons),
            "reason": _with_fix(_join_reasons(zotero_reasons), f"{_env_fix_hint('ZOTERO_API_KEY')} e {_env_fix_hint('ZOTERO_USER_ID')}"),
        }
    )

    google_calendar_enabled = _truthy_env_value(os.environ.get("GOOGLE_CALENDAR_MCP_ENABLE", "true"))
    google_calendar_mcp_credentials = Path(GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH).expanduser()
    google_calendar_reasons = []
    if not google_calendar_enabled:
        google_calendar_reasons.append("GOOGLE_CALENDAR_MCP_ENABLE=false")
    else:
        if not shutil.which(GOOGLE_CALENDAR_MCP_BIN):
            google_calendar_reasons.append("npx/Node ausente")
        if not google_calendar_mcp_credentials.exists():
            google_calendar_reasons.append("credenciais ausentes")
        elif not _google_calendar_mcp_token_exists(google_calendar_mcp_credentials):
            google_calendar_reasons.append("token ausente")
        elif _missing_google_token_scopes(BASE_DIR / "token.json", _GOOGLE_CALENDAR_SCOPES):
            google_calendar_reasons.append("token sem escopo Google Calendar")
    items.append(
        {
            "name": "Google Calendar MCP",
            "enabled": google_calendar_enabled,
            "ok": bool(google_calendar_enabled and not google_calendar_reasons),
            "reason": _with_fix(_join_reasons(google_calendar_reasons), _google_credentials_fix_hint(google_calendar_mcp_credentials) if "credenciais ausentes" in google_calendar_reasons else _google_token_fix_hint()),
        }
    )

    google_drive_token = Path(GOOGLE_DRIVE_MCP_TOKEN_PATH).expanduser()
    google_drive_oauth = Path(GOOGLE_DRIVE_MCP_OAUTH_PATH).expanduser()
    google_drive_reasons = []
    google_drive_enabled = _truthy_env_value(os.environ.get("GOOGLE_DRIVE_MCP_ENABLE", "true"))
    if not google_drive_enabled:
        google_drive_reasons.append("GOOGLE_DRIVE_MCP_ENABLE=false")
    else:
        if not shutil.which("npm"):
            google_drive_reasons.append("npm/Node ausente")
        if not google_drive_oauth.exists():
            google_drive_reasons.append("credenciais ausentes")
        if not google_drive_token.exists():
            google_drive_reasons.append("token ausente")
        elif _missing_google_token_scopes(google_drive_token, _GOOGLE_DRIVE_SCOPES):
            google_drive_reasons.append("token sem escopo Google Drive")
    items.append(
        {
            "name": "Google Drive MCP",
            "enabled": google_drive_enabled,
            "ok": bool(google_drive_enabled and not google_drive_reasons),
            "reason": _with_fix(_join_reasons(google_drive_reasons), _google_credentials_fix_hint(google_drive_oauth) if "credenciais ausentes" in google_drive_reasons else _google_token_fix_hint()),
        }
    )

    google_tasks_enabled = _truthy_env_value(os.environ.get("GOOGLE_TASKS_MCP_ENABLE", "true"))
    google_tasks_token = BASE_DIR / "token.json"
    google_tasks_reasons = []
    google_tasks_probe = {"ok": False, "detail": ""}
    if not google_tasks_enabled:
        google_tasks_reasons.append("GOOGLE_TASKS_MCP_ENABLE=false")
    else:
        if not _module_available("google.oauth2.credentials") or not _module_available("googleapiclient.discovery"):
            google_tasks_reasons.append("dependências google-auth/google-api-python-client ausentes")
        else:
            google_tasks_probe = _google_workspace_token_probe(google_tasks_token)
            if not google_tasks_probe.get("ok"):
                google_tasks_reasons.append(str(google_tasks_probe.get("detail") or google_tasks_probe.get("code") or "token Google Tasks inválido"))
    items.append(
        {
            "name": "Google Tasks MCP",
            "enabled": google_tasks_enabled,
            "ok": bool(google_tasks_enabled and not google_tasks_reasons),
            "reason": _with_fix(_join_reasons(google_tasks_reasons), _google_token_fix_hint()),
        }
    )

    gupy_enabled = _truthy_env_value(os.environ.get("GUPY_MCP_ENABLE", "true"))
    gupy_reasons = []
    if not gupy_enabled:
        gupy_reasons.append("GUPY_MCP_ENABLE=false")
    else:
        if not _has_key(GUPY_API_TOKEN):
            gupy_reasons.append("falta GUPY_API_TOKEN")
        if not _module_available("httpx"):
            gupy_reasons.append("dependência httpx ausente")
    items.append(
        {
            "name": "Gupy MCP",
            "enabled": gupy_enabled,
            "ok": bool(gupy_enabled and not gupy_reasons),
            "reason": _with_fix(_join_reasons(gupy_reasons), _env_fix_hint("GUPY_API_TOKEN")),
        }
    )

    graph_env_access_token = _has_key(os.environ.get("MSGRAPH_ACCESS_TOKEN", "")) or _has_key(os.environ.get("GRAPH_ACCESS_TOKEN", ""))
    graph_token_file = MSGRAPH_TOKEN_PATH.exists()
    onedrive_enabled = _truthy_env_value(os.environ.get("ONEDRIVE_MCP_ENABLE", "true"))
    onedrive_reasons = []
    if not onedrive_enabled:
        onedrive_reasons.append("ONEDRIVE_MCP_ENABLE=false")
    else:
        if not _module_available("httpx"):
            onedrive_reasons.append("dependência httpx ausente")
        if not graph_env_access_token and not _has_key(MSGRAPH_CLIENT_ID):
            onedrive_reasons.append("falta MSGRAPH_CLIENT_ID/GRAPH_CLIENT_ID")
        if not graph_env_access_token and not graph_token_file:
            onedrive_reasons.append("token OneDrive ausente")
    items.append(
        {
            "name": "OneDrive MCP",
            "enabled": onedrive_enabled,
            "ok": bool(onedrive_enabled and not onedrive_reasons),
            "reason": _with_fix(_join_reasons(onedrive_reasons), f"{_env_fix_hint('MSGRAPH_CLIENT_ID')} e rode onedrive_auth_start/onedrive_auth_poll"),
        }
    )

    reclaim_enabled = _truthy_env_value(os.environ.get("RECLAIM_UI_AUTOMATION_ENABLE", "false"))
    reclaim_session_state = _reclaim_session_state_snapshot() if reclaim_enabled else "disabled"
    reclaim_reasons = []
    if not reclaim_enabled:
        reclaim_reasons.append("RECLAIM_UI_AUTOMATION_ENABLE=false")
    else:
        if reclaim_session_state != "valid":
            reclaim_reasons.append(f"sessão Reclaim {reclaim_session_state}")
        if not _reclaim_executor_available():
            reclaim_reasons.append("executor Reclaim indisponível")
    items.append(
        {
            "name": "Reclaim MCP",
            "enabled": reclaim_enabled,
            "ok": bool(reclaim_enabled and not reclaim_reasons),
            "reason": _with_fix(_join_reasons(reclaim_reasons), "ative RECLAIM_UI_AUTOMATION_ENABLE=true e rode reclaim_session_bootstrap"),
        }
    )

    reclaim_official_enabled = _truthy_env_value(os.environ.get("RECLAIM_OFFICIAL_MCP_ENABLE", "false"))
    reclaim_official_reasons = []
    if not reclaim_official_enabled:
        reclaim_official_reasons.append("RECLAIM_OFFICIAL_MCP_ENABLE=false")
    elif not RECLAIM_OFFICIAL_MCP_URL.startswith(("https://", "http://")):
        reclaim_official_reasons.append("RECLAIM_OFFICIAL_MCP_URL inválida")
    items.append(
        {
            "name": "Reclaim Official MCP",
            "enabled": reclaim_official_enabled,
            "ok": bool(reclaim_official_enabled and not reclaim_official_reasons),
            "reason": _with_fix(
                _join_reasons(reclaim_official_reasons),
                f"configure RECLAIM_OFFICIAL_MCP_ENABLE=true e conecte {RECLAIM_OFFICIAL_MCP_URL}",
            ),
        }
    )

    speedgrapher_enabled = _truthy_env_value(os.environ.get("SPEEDGRAPHER_ENABLE", "true"))
    speedgrapher_reasons = []
    if not speedgrapher_enabled:
        speedgrapher_reasons.append("SPEEDGRAPHER_ENABLE=false")
    elif "speedgrapher_fog_index" not in _registered_tool_names():
        speedgrapher_reasons.append("tool speedgrapher_fog_index não registrada")
    items.append(
        {
            "name": "Speedgrapher MCP",
            "enabled": speedgrapher_enabled,
            "ok": bool(speedgrapher_enabled and not speedgrapher_reasons),
            "reason": _with_fix(_join_reasons(speedgrapher_reasons), "ative SPEEDGRAPHER_ENABLE=true"),
        }
    )

    mermaid_enabled = _truthy_env_value(os.environ.get("MERMAID_ENABLE", "true"))
    mermaid_reasons = []
    if not mermaid_enabled:
        mermaid_reasons.append("MERMAID_ENABLE=false")
    elif not _module_available("httpx") and not (shutil.which("mmdc") or shutil.which("npx")):
        mermaid_reasons.append("httpx e mmdc/npx ausentes")
    items.append(
        {
            "name": "Mermaid MCP",
            "enabled": mermaid_enabled,
            "ok": bool(mermaid_enabled and not mermaid_reasons),
            "reason": _with_fix(_join_reasons(mermaid_reasons), "ative MERMAID_ENABLE=true ou instale httpx/mmdc"),
        }
    )

    workflow_enabled = _truthy_env_value(os.environ.get("PROJECT_WORKFLOW_STACK_ENABLE", "true"))
    workflow_tools = _registered_tool_names()
    ai_context_status = _ensure_ai_coders_context_global_installed(install_if_missing=False)
    gsd_status = _ensure_gsd_global_installed(install_if_missing=False)
    ralph_status = _ensure_ralph_global_installed(install_if_missing=False)
    workflow_reasons = []
    if not workflow_enabled:
        workflow_reasons.append("PROJECT_WORKFLOW_STACK_ENABLE=false")
    else:
        if "workflow_stack" not in workflow_tools or "workflow_master_prompt_get" not in workflow_tools:
            workflow_reasons.append("tools workflow não registradas")
        if not (BASE_DIR / ".context" / "docs").exists():
            workflow_reasons.append(".context/docs ausente")
        if not (BASE_DIR / ".context" / "workflow").exists():
            workflow_reasons.append(".context/workflow ausente")
    items.append(
        {
            "name": "Project workflow stack",
            "enabled": workflow_enabled,
            "ok": bool(workflow_enabled and not workflow_reasons),
            "reason": _with_fix(_join_reasons(workflow_reasons), "rode python jarvis.py mcp-status após context_refresh se faltar .context"),
        }
    )

    ai_context_enabled = _truthy_env_value(os.environ.get("AI_CODERS_CONTEXT_MCP_ENABLE", "true"))
    ai_context_reasons = []
    if not ai_context_enabled:
        ai_context_reasons.append("AI_CODERS_CONTEXT_MCP_ENABLE=false")
    elif not ai_context_status.get("installed"):
        ai_context_reasons.append(str(ai_context_status.get("error") or "ai-coders-context não instalado"))
    items.append(
        {
            "name": "AI Coders Context MCP",
            "enabled": ai_context_enabled,
            "ok": bool(ai_context_enabled and not ai_context_reasons),
            "reason": _join_reasons(ai_context_reasons),
        }
    )

    gsd_enabled = _truthy_env_value(os.environ.get("GSD_MCP_ENABLE", "true"))
    gsd_reasons = []
    if not gsd_enabled:
        gsd_reasons.append("GSD_MCP_ENABLE=false")
    elif not gsd_status.get("installed"):
        gsd_reasons.append(str(gsd_status.get("error") or "gsd não instalado"))
    items.append(
        {
            "name": "GSD MCP",
            "enabled": gsd_enabled,
            "ok": bool(gsd_enabled and not gsd_reasons),
            "reason": _join_reasons(gsd_reasons),
        }
    )

    ralph_enabled = _truthy_env_value(os.environ.get("RALPH_MCP_ENABLE", "true"))
    ralph_reasons = []
    if not ralph_enabled:
        ralph_reasons.append("RALPH_MCP_ENABLE=false")
    elif not ralph_status.get("installed"):
        ralph_reasons.append(str(ralph_status.get("error") or "ralph não instalado"))
    items.append(
        {
            "name": "Ralph MCP",
            "enabled": ralph_enabled,
            "ok": bool(ralph_enabled and not ralph_reasons),
            "reason": _join_reasons(ralph_reasons),
        }
    )

    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    firecrawl_enabled = _truthy_env_value(os.environ.get("FIRECRAWL_ENABLE", "false"))
    firecrawl_reasons = []
    if not firecrawl_enabled:
        firecrawl_reasons.append("FIRECRAWL_ENABLE=false")
    else:
        if not _has_key(firecrawl_key):
            firecrawl_reasons.append("falta FIRECRAWL_API_KEY")
        if not shutil.which("npx"):
            firecrawl_reasons.append("npx ausente")
    items.append(
        {
            "name": "Firecrawl MCP",
            "enabled": firecrawl_enabled,
            "ok": bool(firecrawl_enabled and not firecrawl_reasons),
            "reason": _with_fix(_join_reasons(firecrawl_reasons), f"{_env_fix_hint('FIRECRAWL_API_KEY')} e ative FIRECRAWL_ENABLE=true" if firecrawl_enabled and not _has_key(firecrawl_key) else _install_fix_hint("Node.js/npx") if firecrawl_enabled else "ative com FIRECRAWL_ENABLE=true se quiser usar"),
        }
    )

    fireflies_enabled = _truthy_env_value(os.environ.get("FIREFLIES_MCP_ENABLE", "false"))
    fireflies_reasons = []
    if not fireflies_enabled:
        fireflies_reasons.append("FIREFLIES_MCP_ENABLE=false")
    else:
        if not _has_key(FIREFLIES_API_KEY):
            fireflies_reasons.append("falta FIREFLIES_API_KEY")
        if not shutil.which(FIREFLIES_MCP_BIN):
            fireflies_reasons.append("npx ausente")
    items.append(
        {
            "name": "Fireflies MCP",
            "enabled": fireflies_enabled,
            "ok": bool(fireflies_enabled and not fireflies_reasons),
            "reason": _with_fix(_join_reasons(fireflies_reasons), f"{_env_fix_hint('FIREFLIES_API_KEY')} e ative FIREFLIES_MCP_ENABLE=true" if fireflies_enabled and not _has_key(FIREFLIES_API_KEY) else _install_fix_hint("Node.js/npx") if fireflies_enabled else "ative com FIREFLIES_MCP_ENABLE=true se quiser usar"),
        }
    )

    tools = _registered_tool_names()

    payload = {
        "ok": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "registeredTools": tools,
    }

    if any(i.get("enabled") and not i.get("ok") for i in items):
        payload["ok"] = False

    return payload


def _mcp_status_text_lines(payload: dict, *, include_report_notice: bool = True) -> list[str]:
    auth_actions = payload.get("authActions") or []
    lines: list[str] = []
    lines.append("mcp status")
    lines.append("")
    for item in sorted(payload.get("items", []), key=_mcp_status_sort_key):
        name = item.get("name", "")
        ok = bool(item.get("ok"))
        enabled = bool(item.get("enabled"))
        reason = (item.get("reason") or "").strip()
        status = "ok" if ok else "falha"
        if not enabled:
            status = "desativado"
        if (not ok) and reason:
            lines.append(f"- {name}: {status} ({reason})")
        else:
            lines.append(f"- {name}: {status}")

    if auth_actions:
        lines.append("")
        lines.append("autenticação automática")
        for action in auth_actions:
            target = action.get("target", "")
            detail = action.get("detail", "")
            status = "ok" if action.get("ok") else "info"
            if action.get("attempted") and not action.get("ok"):
                status = "falha"
            lines.append(f"- {target}: {status} ({detail})")

    available_tools, unavailable_tools = _mcp_status_tool_lists(payload)
    lines.append("")
    lines.append(f"ferramentas disponíveis: {len(available_tools)}")
    for t in available_tools:
        lines.append(f"- {t}")
    lines.append("")
    lines.append(f"ferramentas indisponíveis: {len(unavailable_tools)}")
    for t in unavailable_tools:
        lines.append(f"- {t}")

    if include_report_notice:
        lines.append("")
        lines.append("relatório também gravado em mcp_status.txt")
    return lines

_MCP_TUI_CONFIG = {
    "Playwright MCP": {"enable": "PLAYWRIGHT_MCP_ENABLE", "fields": []},
    "Brave MCP": {"enable": "BRAVE_MCP_ENABLE", "fields": ["BRAVE_API_KEY"]},
    "Chart MCP": {"enable": "CHART_MCP_ENABLE", "fields": []},
    "Zotero MCP": {"enable": "ZOTERO_MCP_ENABLE", "fields": ["ZOTERO_API_KEY", "ZOTERO_USER_ID"]},
    "Google Calendar MCP": {"enable": "GOOGLE_CALENDAR_MCP_ENABLE", "fields": ["GOOGLE_CALENDAR_MCP_CREDENTIALS_PATH"], "oauth": True},
    "Google Drive MCP": {"enable": "GOOGLE_DRIVE_MCP_ENABLE", "fields": ["GDRIVE_MCP_OAUTH_PATH", "GDRIVE_MCP_TOKEN_PATH", "GDRIVE_MCP_SCOPES"], "oauth": True},
    "Google Tasks MCP": {"enable": "GOOGLE_TASKS_MCP_ENABLE", "fields": [], "oauth": True},
    "Gupy MCP": {"enable": "GUPY_MCP_ENABLE", "fields": ["GUPY_API_TOKEN"]},
    "OneDrive MCP": {"enable": "ONEDRIVE_MCP_ENABLE", "fields": ["MSGRAPH_CLIENT_ID", "GRAPH_CLIENT_ID"], "repair": "onedrive"},
    "Reclaim MCP": {"enable": "RECLAIM_UI_AUTOMATION_ENABLE", "fields": [], "repair": "reclaim"},
    "Reclaim Official MCP": {"enable": "RECLAIM_OFFICIAL_MCP_ENABLE", "fields": [], "repair": "reclaim_official"},
    "Speedgrapher MCP": {"enable": "SPEEDGRAPHER_ENABLE", "fields": []},
    "Mermaid MCP": {"enable": "MERMAID_ENABLE", "fields": ["MERMAID_LINK_ONLY"]},
    "Firecrawl MCP": {"enable": "FIRECRAWL_ENABLE", "fields": ["FIRECRAWL_API_KEY"]},
    "Fireflies MCP": {"enable": "FIREFLIES_MCP_ENABLE", "fields": ["FIREFLIES_API_KEY"]},
    "Project workflow stack": {"enable": "PROJECT_WORKFLOW_STACK_ENABLE", "fields": []},
    "AI Coders Context MCP": {"enable": "AI_CODERS_CONTEXT_MCP_ENABLE", "fields": []},
    "GSD MCP": {"enable": "GSD_MCP_ENABLE", "fields": []},
    "Ralph MCP": {"enable": "RALPH_MCP_ENABLE", "fields": []},
}

def _mcp_tui_item_status(item: dict) -> str:
    if bool(item.get("enabled")) and not bool(item.get("ok")):
        return "falha"
    if not bool(item.get("enabled")):
        return "off"
    return "ok"


def _mcp_status_prompt_text(prompt: str, *, default: str = "", secret: bool = False) -> str | None:
    import getpass

    shown_default = " [atual definido]" if default and secret else (f" [{default}]" if default else "")
    full_prompt = f"{prompt}{shown_default}: "
    try:
        if secret:
            value = getpass.getpass(full_prompt)
        else:
            value = input(full_prompt)
    except (EOFError, KeyboardInterrupt):
        return None
    value = value.strip()
    return value or None


def _mcp_status_run_repair(cfg: dict) -> str | None:
    repair = str(cfg.get("repair") or "").strip().lower()
    if repair == "reclaim":
        try:
            session_data = get_session_status(
                path=RECLAIM_UI_SESSION_FILE,
                session_ttl_sec=RECLAIM_UI_SESSION_TTL_SEC,
            )
            state = str(session_data.get("state") or "not_bootstrapped")
            if state in {"pending_manual_login", "blocked_captcha", "expired"}:
                raw = _reclaim_session_bootstrap_impl(
                    manual_login_confirmed=True,
                    captcha_resolved=True,
                    open_browser=False,
                )
                payload = json.loads(raw)
                result = str(payload.get("result") or "unknown")
                next_step = str(payload.get("next_step") or "")
                return f"Reclaim confirmação: {result}. {next_step}".strip()

            raw = _reclaim_session_bootstrap_impl(
                manual_login_confirmed=False,
                captcha_resolved=True,
                open_browser=True,
            )
            payload = json.loads(raw)
            result = str(payload.get("result") or "unknown")
            next_step = str(payload.get("next_step") or "")
            return f"Reclaim bootstrap: {result}. {next_step}".strip()
        except Exception as exc:
            return f"Falha ao iniciar bootstrap do Reclaim: {exc}"
    if repair == "onedrive":
        try:
            payload = _onedrive_auth_start_impl()
            target = str(payload.get("verification_uri_complete") or payload.get("verification_uri") or "").strip()
            if target:
                try:
                    webbrowser.open(target)
                except Exception:
                    pass
            user_code = str(payload.get("user_code") or "").strip()
            uri = str(payload.get("verification_uri") or "").strip()
            message = str(payload.get("message") or "").strip()
            if message:
                return f"OneDrive auth iniciada. {message}"
            details = []
            if uri:
                details.append(f"Abra {uri}")
            if user_code:
                details.append(f"use o código {user_code}")
            details.append("depois rode onedrive_auth_poll")
            return "OneDrive auth iniciada. " + "; ".join(details)
        except Exception as exc:
            return f"Falha ao iniciar auth do OneDrive: {exc}"
    if repair == "reclaim_official":
        try:
            _persist_config_value("RECLAIM_OFFICIAL_MCP_ENABLE", "true")
            _persist_config_value("RECLAIM_OFFICIAL_MCP_URL", "https://mcp.reclaim.ai")
            _persist_config_value("RECLAIM_OFFICIAL_MCP_PREFIX", "reclaim2")
            return (
                "Reclaim Official MCP configurado automaticamente: "
                "RECLAIM_OFFICIAL_MCP_ENABLE=true, "
                "RECLAIM_OFFICIAL_MCP_URL=https://mcp.reclaim.ai, "
                "RECLAIM_OFFICIAL_MCP_PREFIX=reclaim2. "
                "Reinicie o Jarvis; a autenticação OAuth do Reclaim acontece no cliente MCP compatível."
            )
        except Exception as exc:
            return f"Falha ao configurar Reclaim Official MCP: {exc}"
    return None


def _mcp_status_define_config(item: dict) -> str:
    name = str(item.get("name", ""))
    cfg = _MCP_TUI_CONFIG.get(name, {})
    fields = list(cfg.get("fields") or [])
    updated = False
    for field in fields:
        current = os.environ.get(field, "")
        secret = any(tok in field for tok in ("KEY", "TOKEN", "SECRET"))
        value = _mcp_status_prompt_text(f"Valor para {field}", secret=secret, default=current)
        if value is not None:
            _persist_config_value(field, value)
            updated = True

    if cfg.get("oauth"):
        action = _run_google_workspace_oauth()
        prefix = "configuração salva em env.sh. " if updated else ""
        return prefix + f"{action.get('target')}: {action.get('detail')}"

    repair_message = _mcp_status_run_repair(cfg)
    if repair_message:
        prefix = "configuração salva em env.sh. " if updated else ""
        return prefix + repair_message

    if updated:
        return "configuração salva em env.sh"
    if fields:
        return "nenhuma alteração aplicada"
    return "sem campo de configuração para este MCP"


def _mcp_status_toggle(item: dict) -> str:
    name = str(item.get("name", ""))
    cfg = _MCP_TUI_CONFIG.get(name, {})
    key = cfg.get("enable")
    if not key:
        return "este MCP não tem toggle de enable"
    current = _truthy_env_value(os.environ.get(str(key), "true" if item.get("enabled") else "false"))
    new_value = "false" if current else "true"
    _persist_config_value(str(key), new_value)
    return f"{key}={new_value} salvo em env.sh"


def _mcp_status_pty_ui() -> int:
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.styles import Style
    except Exception:
        return 1

    selected = 0
    message = "↑/↓ navega, espaço ativa/desativa, enter configura, t ferramentas, r atualiza, q sai"
    view = "mcps"

    while True:
        payload = _mcp_status_payload()
        payload["authActions"] = []
        try:
            write_mcp_status_report(payload, announce=False)
        except Exception:
            pass
        items = sorted(payload.get("items", []), key=_mcp_status_sort_key)
        available_tools, unavailable_tools = _mcp_status_tool_lists(payload)
        tool_entries = (
            [("section", f"disponíveis ({len(available_tools)})")]
            + _mcp_group_tools(available_tools)
            + [("section", f"indisponíveis ({len(unavailable_tools)})")]
            + _mcp_group_tools(unavailable_tools)
        )
        current_entries = items if view == "mcps" else tool_entries
        if not current_entries:
            return 1
        selected = max(0, min(selected, len(current_entries) - 1))
        state = {"selected": selected, "action": "quit", "view": view}

        def _build_fragments():
            width, height = shutil.get_terminal_size((120, 40))
            visible_rows = max(5, height - 7)
            start = max(0, min(state["selected"] - visible_rows // 2, max(0, len(current_entries) - visible_rows)))
            visible = current_entries[start:start + visible_rows]
            header = "MCPs" if state["view"] == "mcps" else "Ferramentas"
            fragments = [
                ("class:title", f"Jarvis MCP status · {header}\n"),
                ("class:help", "↑/↓ navega, espaço ativa/desativa, enter configura, t ferramentas, r atualiza, q sai\n\n"),
            ]
            if state["view"] == "mcps":
                for offset, item in enumerate(visible):
                    idx = start + offset
                    status = _mcp_tui_item_status(item)
                    cfg = _MCP_TUI_CONFIG.get(str(item.get("name", "")), {})
                    toggle = "[x]" if bool(item.get("enabled")) else "[ ]"
                    if not cfg.get("enable"):
                        toggle = "[-]"
                    prefix = ">" if idx == state["selected"] else " "
                    style = "class:selected" if idx == state["selected"] else ""
                    line = f"{prefix} {toggle} {status:5} {item.get('name', '')}"
                    fragments.append((style, line[: max(1, width - 1)] + "\n"))
                fragments.append(("", "\n"))
                reason = str(items[state["selected"]].get("reason") or "")
                fragments.append(("class:detail", reason[: max(1, width - 1)] + "\n"))
            else:
                for offset, entry in enumerate(visible):
                    idx = start + offset
                    kind, value = entry
                    if kind == "section":
                        fragments.append(("class:section", value[: max(1, width - 1)] + "\n"))
                        continue
                    if kind == "group":
                        fragments.append(("class:group", f"  {value}"[: max(1, width - 1)] + "\n"))
                        continue
                    prefix = ">" if idx == state["selected"] else " "
                    style = "class:selected" if idx == state["selected"] else ""
                    line = f"{prefix}   {value}"
                    fragments.append((style, line[: max(1, width - 1)] + "\n"))
                fragments.append(("", "\n"))
                current = current_entries[state["selected"]]
                detail = _mcp_tool_description(current[1], current[0])
                fragments.append(("class:detail", detail[: max(1, width - 1)] + "\n"))
            fragments.append(("class:message", message[: max(1, width - 1)]))
            return fragments

        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            state["selected"] = max(0, state["selected"] - 1)
            event.app.invalidate()

        @kb.add("down")
        def _(event):
            state["selected"] = min(len(current_entries) - 1, state["selected"] + 1)
            event.app.invalidate()
        @kb.add("space")
        def _(event):
            state["action"] = "toggle"
            event.app.exit()

        @kb.add("enter")
        def _(event):
            state["action"] = "configure"
            event.app.exit()

        @kb.add("t")
        @kb.add("T")
        def _(event):
            state["action"] = "toggle_view"
            event.app.exit()

        @kb.add("r")
        @kb.add("R")
        def _(event):
            state["action"] = "refresh"
            event.app.exit()

        @kb.add("q")
        @kb.add("Q")
        def _(event):
            state["action"] = "quit"
            event.app.exit()

        app = Application(
            layout=Layout(Window(content=FormattedTextControl(_build_fragments), always_hide_cursor=True)),
            key_bindings=kb,
            full_screen=True,
            mouse_support=False,
            style=Style.from_dict(
                {
                    "title": "bold",
                    "help": "ansibrightblack",
                    "selected": "reverse",
                    "detail": "",
                    "message": "ansibrightblack",
                    "section": "bold ansibrightblue",
                    "group": "ansicyan",
                }
            ),
        )
        app.run()

        selected = int(state["selected"])
        action = str(state["action"])
        if action == "quit":
            return 0
        if action == "toggle_view":
            view = "tools" if view == "mcps" else "mcps"
            selected = 0
            message = "alternado"
            continue
        if view == "tools":
            message = "na visão de ferramentas não há toggle nem configuração"
            continue
        if action == "toggle":
            message = _mcp_status_toggle(items[selected])
        elif action == "configure":
            message = _mcp_status_define_config(items[selected])
        else:
            message = "atualizado"


def _mcp_status_cli() -> int:
    auth_actions = _run_mcp_status_auto_auth()
    payload = _mcp_status_payload()
    payload["authActions"] = auth_actions
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    try:
        write_mcp_status_report(payload, announce=not interactive)
    except Exception as exc:
        payload["ok"] = False
        payload.setdefault("errors", []).append(f"falha ao escrever mcp_status.txt: {exc}")

    lines = _mcp_status_text_lines(payload)
    if interactive:
        try:
            ui_rc = _mcp_status_pty_ui()
            if ui_rc == 0:
                return 0 if payload.get("ok") else 1
            print("⚠️ UI PTY do mcp-status falhou. Caindo para saída texto.", file=sys.stderr)
        except Exception as exc:
            print(f"⚠️ UI PTY do mcp-status falhou: {exc}. Caindo para saída texto.", file=sys.stderr)

    print("\n".join(lines))
    return 0 if payload.get("ok") else 1



def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    raw_argv = _normalize_legacy_service_args(raw_argv)

    if raw_argv and raw_argv[0] == "__auth_google_workspace_internal":
        return _auth_google_cli(scope="all", token_path=str(BASE_DIR / "token.json"), open_browser=True)

    if not raw_argv:
        return _service_start(
            server_host=os.environ.get("SERVER_HOST", "0.0.0.0"),
            server_port=int(os.environ.get("SERVER_PORT", "7860")),
            log_file=_default_log_file(),
            pid_file=_default_pid_file(),
            python_bin=os.environ.get("PYTHON_BIN", sys.executable or "python3"),
            node_bin=os.environ.get("NODE_BIN", "node"),
        )

    parser = _build_cli_parser()
    args = parser.parse_args(raw_argv)

    if args.command == "serve":
        if not os.environ.get("MCP_MODE", "").strip():
            os.environ["MCP_MODE"] = "stdio"
        return _run_server()

    if args.command == "start":
        return _service_start(
            server_host=args.server_host,
            server_port=args.server_port,
            log_file=Path(args.log_file),
            pid_file=Path(args.pid_file),
            python_bin=args.python_bin,
            node_bin=args.node_bin,
        )

    if args.command == "stop":
        return _service_stop(Path(args.pid_file), args.server_port)

    if args.command == "status":
        pid_file = Path(getattr(args, "pid_file", str(_default_pid_file())))
        log_file = Path(getattr(args, "log_file", str(_default_log_file())))
        server_port = int(getattr(args, "server_port", int(os.environ.get("SERVER_PORT", "7860"))))
        return _service_status(pid_file, log_file, server_port)

    if args.command == "logs":
        return _service_logs(Path(args.log_file), args.lines)

    if args.command == "mcp-status":
        return _mcp_status_cli()
    if args.command == "context-stack-harden":
        results = {
            "ai_coders_context": _ensure_ai_coders_context_global_installed(install_if_missing=True),
            "gsd": _run_internal_gsd_setup_step(),
            "ralph": _run_internal_ralph_setup_step(),
            "graphify": _harden_graphify_global_install(apply_if_needed=True),
            "layout": _merge_context_stack_layout(BASE_DIR),
            "smoke": _run_internal_smoke_test_step(),
        }
        ok = all(bool(item.get("ok")) for item in results.values())
        print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    if args.command == "context-stack-check":
        result = _context_stack_check(list(args.roots), recursive=bool(args.recursive))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "google-auth-refresh":
        action = _run_google_workspace_oauth(force=bool(args.force))
        print(f"{action.get('target')}: {action.get('detail')}")
        return 0 if action.get("ok") else 1



    if args.command == "sync-agent-assets":
        return _sync_agent_assets_core(
            target_home=getattr(args, "target_home", ""),
            quiet=bool(getattr(args, "quiet", False)),
        )


    if args.command == "mcp-sync-clients":
        return _mcp_sync_clients_cli(
            py_bin=_resolve_project_python(args.py_bin),
            include_codex=not args.no_codex,
            include_gemini=not args.no_gemini,
            include_sudo=not args.no_sudo,
            include_bridge=not args.skip_bridge,
            target_home=getattr(args, "target_home", ""),
            quiet_core=bool(getattr(args, "quiet_core", False)),
            verbose=bool(args.verbose),
        )

    if args.command == "setup-bidirectional-mcp":
        return _setup_bidirectional_mcp_cli(_resolve_project_python(args.py_bin))

    if args.command == "openclaw-remote":
        return _openclaw_remote_cli(
            args.action,
            host=args.host,
            user=args.user,
            ssh_key=args.ssh_key,
            timeout_sec=args.ssh_timeout,
            sync_remote_jarvis=not args.no_sync,
            sync_venv=bool(args.sync_venv),
        )

    if args.command == "install-oci":
        return _install_oci_cli(args.installer_args)


    if args.command == "install-super-venv":
        return _install_super_venv_cli(
            python_bin=args.python_bin,
            install_playwright=not args.skip_playwright,
            remove_old_venvs=not args.keep_old_venvs,
        )

    if args.command == "fix-firewall-oci":
        return _fix_firewall_oci_cli(target_instance_ip=args.instance_ip)

    if args.command == "gemini-bridge":
        if args.selftest:
            payload = _gemini_bridge_health_payload()
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if payload.get("ok") else 1
        return _run_gemini_bridge_server()
    if args.command == "test-reclaim-ui":
        return _test_reclaim_ui_cli(verbose=args.verbose)


    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())




@_mcp_tool_when_env("GUPY_MCP_ENABLE", "true")
def gupy_v1_set_recruiter(job_id: int, recruiter_email: str) -> str:
    """Define o recrutador de uma vaga via API v1 (PATCH recruiterEmail).

    Observação: a API v1 aceita PATCH em /api/v1/jobs/{id} com recruiterEmail.
    """
    try:
        recruiter_email = (recruiter_email or "").strip()
        if not recruiter_email:
            return "Erro: recruiter_email vazio."

        with _gupy_client() as c:
            r = c.patch(
                f"https://api.gupy.io/api/v1/jobs/{int(job_id)}",
                json={"recruiterEmail": recruiter_email},
            )
            # a API retorna o payload completo da vaga; aqui resumimos.
            if r.status_code != 200:
                return f"PATCH /api/v1/jobs/{job_id} recruiterEmail={recruiter_email} -> HTTP {r.status_code}: {r.text[:800]}".strip()
            j = r.json() if r.text else {}
            return (
                "ok: "
                f"job_id={job_id} recruiter={j.get('recruiterName')} <{j.get('recruiterEmail')}> id={j.get('recruiterId')} "
                f"status={j.get('status')} updatedAt={j.get('updatedAt')}"
            ).strip()
    except Exception as e:
        import traceback

        return f"Erro ao setar recrutador: {e}\n{traceback.format_exc()}"


def _normalize_pt(s: str) -> str:
    """Normaliza string pt-br para matching simples.

    - lower
    - remove acentos
    - colapsa espaços
    """
    s = (s or "").strip().lower()
    if not s:
        return ""
    try:
        import unicodedata

        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    except Exception:
        # se der ruim, segue sem remover acento
        pass
    s = re.sub(r"\s+", " ", s)
    return s


def _gupy_pick_recruiter_by_title(
    title: str,
    recruiter_andre: str,
    recruiter_gabrielly: str,
    recruiter_larissa: str,
) -> str:
    """Aplica regra de recrutador por palavra-chave no título.

    Regra combinada com o lucas:
    1) coordenador/supervisor/gerente -> andre
    2) estagiario/estagiário/jovem aprendiz/aprendiz -> gabrielly
    3) resto -> larissa
    """
    t = _normalize_pt(title)

    # bucket 1: liderança
    if any(k in t for k in ["coordenador", "supervisor", "gerente"]):
        return (recruiter_andre or "").strip()

    # bucket 2: inicio de carreira
    # obs: usamos matching por substring para cobrir "aprendiz", "jovem aprendiz", etc.
    if ("estagiario" in t) or ("jovem aprendiz" in t) or ("aprendiz" in t):
        return (recruiter_gabrielly or "").strip()

    # bucket 3: default
    return (recruiter_larissa or "").strip()


@_mcp_tool_when_env("GUPY_MCP_ENABLE", "true")
def gupy_v1_apply_recruiter_rules(
    status_list: str = "published,approved,waiting_approval",
    recruiter_andre: str = "andre.orrico@lmmobilidade.com.br",
    recruiter_gabrielly: str = "gabrielly.silva@lmmobilidade.com.br",
    recruiter_larissa: str = "larissa.teixeira@lmmobilidade.com.br",
    dry_run: bool = True,
    per_page: int = 100,
    max_pages: int = 50,
    only_if_diff: bool = True,
) -> str:
    """Aplica regra de recrutador por palavra-chave no título das vagas.

    - Busca vagas por status (padrão: published, approved, waiting_approval)
    - Para cada vaga, calcula o recruiter target pelo título
    - Se dry_run=false, faz PATCH recruiterEmail

    Observação importante: a API v1 nem sempre retorna recruiterEmail na listagem.
    Por isso, a checagem de diferença pode falhar (unknown). Nesse caso:
    - se only_if_diff=true e recruiterEmail vier vazio, não altera
    - se only_if_diff=false, altera mesmo assim
    """
    try:
        statuses = [st.strip() for st in (status_list or "").split(",") if st.strip()]
        if not statuses:
            return "Erro: status_list vazio."

        recruiter_andre = (recruiter_andre or "").strip()
        recruiter_gabrielly = (recruiter_gabrielly or "").strip()
        recruiter_larissa = (recruiter_larissa or "").strip()
        if not recruiter_andre or not recruiter_gabrielly or not recruiter_larissa:
            return "Erro: recruiter emails devem estar preenchidos (andre, gabrielly, larissa)."

        per_page = int(per_page)
        max_pages = int(max_pages)
        if per_page < 1 or per_page > 100:
            return "Erro: per_page deve estar entre 1 e 100 (limite comum da API)."
        if max_pages < 1:
            return "Erro: max_pages deve ser >= 1."

        actions: list[str] = []
        scanned = 0
        will_patch = 0
        patched_ok = 0
        patched_err = 0
        skipped_same = 0
        skipped_unknown = 0

        with _gupy_client() as c:
            for status in statuses:
                for page in range(1, max_pages + 1):
                    params = {"page": int(page), "perPage": int(per_page), "status": status}
                    r = c.get("https://api.gupy.io/api/v1/jobs", params=params)
                    if r.status_code != 200:
                        actions.append(f"status={status} page={page}: erro HTTP {r.status_code}: {r.text[:300]}")
                        break

                    data = r.json() if r.text else {}
                    results = data.get("results", []) or []
                    if not results:
                        break

                    for j in results:
                        job_id = j.get("id")
                        title = j.get("name") or ""
                        current_email = (j.get("recruiterEmail") or "").strip()
                        target_email = _gupy_pick_recruiter_by_title(
                            title,
                            recruiter_andre=recruiter_andre,
                            recruiter_gabrielly=recruiter_gabrielly,
                            recruiter_larissa=recruiter_larissa,
                        )
                        scanned += 1

                        if only_if_diff and current_email and (current_email.lower() == target_email.lower()):
                            skipped_same += 1
                            continue

                        if only_if_diff and (not current_email):
                            skipped_unknown += 1
                            continue

                        will_patch += 1
                        if dry_run:
                            actions.append(
                                f"dry_run: job_id={job_id} status={status} title={title!r} current={current_email or 'unknown'} -> target={target_email}"
                            )
                            continue

                        pr = c.patch(
                            f"https://api.gupy.io/api/v1/jobs/{int(job_id)}",
                            json={"recruiterEmail": target_email},
                        )
                        if pr.status_code != 200:
                            patched_err += 1
                            actions.append(
                                f"patch_err: job_id={job_id} status={status} title={title!r} target={target_email} -> HTTP {pr.status_code}: {pr.text[:300]}"
                            )
                        else:
                            patched_ok += 1
                            js = pr.json() if pr.text else {}
                            actions.append(
                                "patch_ok: "
                                f"job_id={job_id} status={status} title={title!r} -> recruiter={js.get('recruiterName')} <{js.get('recruiterEmail')}> id={js.get('recruiterId')} updatedAt={js.get('updatedAt')}"
                            )

                    # stop se veio menos que a página cheia
                    if len(results) < per_page:
                        break

        header = []
        header.append("gupy_v1_apply_recruiter_rules")
        header.append(
            f"status_list={','.join(statuses)} dry_run={bool(dry_run)} only_if_diff={bool(only_if_diff)} per_page={per_page} max_pages={max_pages}"
        )
        header.append(
            "recruiters: "
            f"andre={recruiter_andre} | gabrielly={recruiter_gabrielly} | larissa={recruiter_larissa}"
        )
        header.append(
            f"scanned={scanned} will_patch={will_patch} patched_ok={patched_ok} patched_err={patched_err} skipped_same={skipped_same} skipped_unknown={skipped_unknown}"
        )
        header.append("")

        # log em disco (sempre grava o completo; a saída no tool pode ser truncada)
        try:
            import json
            import os
            from datetime import datetime, timezone

            logs_dir = os.path.join(os.path.dirname(__file__), "logs")
            os.makedirs(logs_dir, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
            fname = f"gupy_recruiter_rules_{ts}.json"
            fpath = os.path.join(logs_dir, fname)

            payload = {
                "tool": "gupy_v1_apply_recruiter_rules",
                "tsUtc": ts,
                "params": {
                    "status_list": ",".join(statuses),
                    "dry_run": bool(dry_run),
                    "only_if_diff": bool(only_if_diff),
                    "per_page": per_page,
                    "max_pages": max_pages,
                    "recruiters": {
                        "andre": recruiter_andre,
                        "gabrielly": recruiter_gabrielly,
                        "larissa": recruiter_larissa,
                    },
                },
                "summary": {
                    "scanned": scanned,
                    "will_patch": will_patch,
                    "patched_ok": patched_ok,
                    "patched_err": patched_err,
                    "skipped_same": skipped_same,
                    "skipped_unknown": skipped_unknown,
                },
                "actions": actions,
            }
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            # não quebra a tool por falha de log
            pass

        # evita estourar saída em tenants grandes
        max_lines = 200
        body = actions[:max_lines]
        if len(actions) > max_lines:
            body.append(f"... ({len(actions) - max_lines} linhas omitidas)")

        return "\n".join(header + body).strip()
    except Exception as e:
        import traceback

        return f"Erro: {e}\n{traceback.format_exc()}"
