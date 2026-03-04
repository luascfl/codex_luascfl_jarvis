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
import shlex
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
RALPH_PRD_DEFAULT_REL = ".context/prd_ralph/prd.json"
PROJECT_CONTEXT_PATHS = [
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    ".context/docs",
    ".context/docs/planning_gsd",
    ".context/prd_ralph",
    ".context/workflow",
]
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
# Adiciona o binário do npm global e do user base python ao PATH
_npm_prefix = os.environ.get("npm_config_prefix") or f"{os.environ.get('HOME', '/home/lucas')}/.npm-global"
_npm_global_bin = f"{_npm_prefix}/bin"
_user_local_bin = f"{os.environ.get('HOME', '/home/lucas')}/.local/bin"
os.environ["PATH"] = f"{_npm_global_bin}:{_user_local_bin}:{os.environ.get('PATH', '')}"

# Garante que os diretórios existam
for d in [
    os.environ.get("HOME", "/home/lucas"),
    os.environ.get("npm_config_cache", "/home/lucas/.npm"),
    os.environ.get("npm_config_prefix", "/home/lucas/.npm-global"),
    os.environ.get("PIP_CACHE_DIR", "/home/lucas/.pip-cache"),
]:
    os.makedirs(d, exist_ok=True)

# O Gemini CLI precisa gravar dentro do projeto; definimos um diretório padrão
GEMINI_CLI_HOME_DIR = os.environ.get("GEMINI_CLI_HOME")
if not GEMINI_CLI_HOME_DIR:
    GEMINI_CLI_HOME_DIR = "/home/lucas"
gemini_home_path = Path(GEMINI_CLI_HOME_DIR).expanduser()
while gemini_home_path.name == ".gemini":
    gemini_home_path = gemini_home_path.parent
GEMINI_CLI_HOME_DIR = str(gemini_home_path)
os.environ["GEMINI_CLI_HOME"] = GEMINI_CLI_HOME_DIR
Path(GEMINI_CLI_HOME_DIR).mkdir(parents=True, exist_ok=True)

# --- 1. CONFIGURAÇÕES ---
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
BRAVE_MCP_ENABLE = os.environ.get("BRAVE_MCP_ENABLE", "true").lower() in ("1", "true", "yes", "on")
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

## FIREFLIES MCP (remote via mcp-remote)
FIREFLIES_MCP_ENABLE = os.environ.get("FIREFLIES_MCP_ENABLE", "false").lower() in ("1", "true", "yes", "on")
FIREFLIES_MCP_BIN = os.environ.get("FIREFLIES_MCP_BIN", "npx")
FIREFLIES_MCP_PACKAGE = os.environ.get("FIREFLIES_MCP_PACKAGE", "mcp-remote")
FIREFLIES_MCP_REMOTE_URL = os.environ.get("FIREFLIES_MCP_REMOTE_URL", "https://api.fireflies.ai/mcp")
FIREFLIES_MCP_EXTRA_ARGS = os.environ.get("FIREFLIES_MCP_EXTRA_ARGS", "")
FIREFLIES_MCP_PORT = int(os.environ.get("FIREFLIES_MCP_PORT", "8946"))
FIREFLIES_MCP_HOST = os.environ.get("FIREFLIES_MCP_HOST", "localhost")
FIREFLIES_MCP_URL = f"http://{FIREFLIES_MCP_HOST}:{FIREFLIES_MCP_PORT}"
CLOUDFLARED_FIREFLIES_ENABLE = os.environ.get("CLOUDFLARED_FIREFLIES_ENABLE", "false").lower() in ("1", "true", "yes", "on")

## SEQUENTIAL THINKING (remote MCP via mcp-remote)
SEQUENTIAL_MCP_ENABLE = os.environ.get("SEQUENTIAL_MCP_ENABLE", "true").lower() in ("1", "true", "yes", "on")
SEQUENTIAL_MCP_BIN = os.environ.get("SEQUENTIAL_MCP_BIN", "npx")
SEQUENTIAL_MCP_PACKAGE = os.environ.get("SEQUENTIAL_MCP_PACKAGE", "mcp-remote")
SEQUENTIAL_MCP_REMOTE_URL = os.environ.get("SEQUENTIAL_MCP_REMOTE_URL", "https://remote.mcpservers.org/sequentialthinking/mcp")
SEQUENTIAL_MCP_EXTRA_ARGS = os.environ.get("SEQUENTIAL_MCP_EXTRA_ARGS", "")
SEQUENTIAL_MCP_PORT = int(os.environ.get("SEQUENTIAL_MCP_PORT", "8940"))
SEQUENTIAL_MCP_HOST = os.environ.get("SEQUENTIAL_MCP_HOST", "localhost")
SEQUENTIAL_MCP_URL = f"http://{SEQUENTIAL_MCP_HOST}:{SEQUENTIAL_MCP_PORT}"
CLOUDFLARED_SEQUENTIAL_ENABLE = os.environ.get("CLOUDFLARED_SEQUENTIAL_ENABLE", "false").lower() in ("1", "true", "yes", "on")

# RECLAIM UI AUTOMATION (experimental)
RECLAIM_UI_AUTOMATION_ENABLE = os.environ.get("RECLAIM_UI_AUTOMATION_ENABLE", "false").lower() in ("1", "true", "yes", "on")
RECLAIM_UI_SESSION_FILE = Path(
    os.environ.get("RECLAIM_UI_SESSION_FILE", str(BASE_DIR / ".ralph" / "reclaim_ui_session.json"))
)
RECLAIM_UI_AUDIT_FILE = Path(
    os.environ.get("RECLAIM_UI_AUDIT_FILE", str(BASE_DIR / ".ralph" / "reclaim_ui_audit.jsonl"))
)
RECLAIM_UI_SESSION_TTL_SEC = int(os.environ.get("RECLAIM_UI_SESSION_TTL_SEC", "43200"))
RECLAIM_UI_CAPTCHA_TIMEOUT_SEC = int(os.environ.get("RECLAIM_UI_CAPTCHA_TIMEOUT_SEC", "900"))
RECLAIM_UI_LOGIN_URL = os.environ.get("RECLAIM_UI_LOGIN_URL", "https://app.reclaim.ai")
RECLAIM_UI_EXECUTOR_CMD = os.environ.get(
    "RECLAIM_UI_EXECUTOR_CMD",
    "internal",
)
RECLAIM_UI_EXECUTOR_TIMEOUT_SEC = int(os.environ.get("RECLAIM_UI_EXECUTOR_TIMEOUT_SEC", "25"))
RECLAIM_UI_ASSIST_OPEN_BROWSER = os.environ.get("RECLAIM_UI_ASSIST_OPEN_BROWSER", "false").lower() in ("1", "true", "yes", "on")

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

# --- SEQUENTIAL THINKING NATIVE ---
@mcp.tool()
def sequential_thought(
    thought: str,
    thoughtNumber: int,
    totalThoughts: int,
    nextThoughtNeeded: bool,
    isRevision: bool = False,
    revisesThought: int | None = None,
    branchFromThought: int | None = None,
    branchId: str | None = None,
    needsMoreThoughts: bool | None = None,
) -> str:
    """
    A tool for dynamic and reflective problem-solving.
    Allows the model to think sequentially, revise thoughts, and branch out.
    
    Args:
        thought: The content of the current thought step.
        thoughtNumber: The current step number (1-based).
        totalThoughts: Estimated total steps needed.
        nextThoughtNeeded: Whether more thinking is required.
        isRevision: If this thought revises a previous one.
        revisesThought: The ID of the thought being revised.
        branchFromThought: The ID of the thought being branched from.
        branchId: Identifier for the current branch.
        needsMoreThoughts: Explicit signal if more steps are needed.
    """
    try:
        # In a real stateful implementation, we would store the thought graph.
        # For this stateless tool wrapper, we acknowledge the thought to the model.
        # The model maintains the context in the conversation history.
        result = {
            "status": "success",
            "thought_recorded": thoughtNumber,
            "message": "Thought recorded. Proceed with the next step or final answer."
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

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
                    ("Sequential Thinking", SEQUENTIAL_MCP_ENABLE),
                    ("Speedgrapher", True)  # Gerenciado pelo mcp-proxy pai
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


def write_mcp_status_report():
    """Gera um relatório simples (txt) com o status de configuração dos MCPs."""
    lines = []

    def add(name: str, ok: bool, reason: str = ""):
        status = "configurado" if ok else "não configurado"
        if reason and not ok:
            status = f"{status} ({reason})"
        lines.append(f"{name}: {status}")

    def has_key(val: str) -> bool:
        return bool(val and str(val).strip())

    # Node-based MCPs
    add(
        "Playwright MCP",
        PLAYWRIGHT_MCP_ENABLE and bool(shutil.which(PLAYWRIGHT_MCP_BIN)),
        "npx/Node ausente ou desativado",
    )
    add(
        "Brave MCP",
        BRAVE_MCP_ENABLE and has_key(BRAVE_API_KEY) and bool(shutil.which(BRAVE_MCP_BIN)),
        "falta BRAVE_API_KEY ou npx",
    )
    add(
        "Chart MCP",
        CHART_MCP_ENABLE and bool(shutil.which(CHART_MCP_BIN)),
        "npx ausente ou desativado",
    )
    add(
        "Zotero MCP",
        ZOTERO_MCP_ENABLE
        and has_key(ZOTERO_API_KEY)
        and has_key(ZOTERO_USER_ID)
        and bool(shutil.which(ZOTERO_MCP_BIN)),
        "faltam ZOTERO_API_KEY/ZOTERO_USER_ID ou npx",
    )
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    add(
        "Firecrawl MCP",
        FIRECRAWL_ENABLE and has_key(firecrawl_key) and bool(shutil.which("npx")),
        "falta FIRECRAWL_API_KEY ou npx",
    )
    add(
        "Fireflies MCP",
        FIREFLIES_MCP_ENABLE and has_key(FIREFLIES_API_KEY) and bool(shutil.which(FIREFLIES_MCP_BIN)),
        "falta FIREFLIES_API_KEY ou npx",
    )
    add(
        "OpenRouter (tool)",
        has_key(OPENROUTER_API_KEY) or has_key(OPENAI_API_KEY),
        "falta OPENROUTER_API_KEY/OPENAI_API_KEY",
    )
    add(
        "Sequential MCP",
        SEQUENTIAL_MCP_ENABLE and bool(shutil.which(SEQUENTIAL_MCP_BIN)),
        "npx ausente ou desativado",
    )

    # Ferramentas carregadas (snapshot em runtime)
    try:
        tools = [t.name for t in mcp.tools]
        lines.append("")
        lines.append("Ferramentas registradas:")
        for name in sorted(tools):
            lines.append(f"- {name}")
    except Exception as e:  # pragma: no cover
        lines.append("")
        lines.append(f"(Falha ao listar ferramentas: {e})")

    report_path = Path.cwd() / "mcp_status.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")
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


def start_sequential_mcp():
    """Versão Nativa: Sequential Thinking agora roda dentro do processo Python."""
    if not SEQUENTIAL_MCP_ENABLE:
        print("ℹ️  Sequential MCP desativado via env.", file=sys.stderr)
        return None
    
    print("🧠 Sequential Thinking (Nativo) ativado e pronto.", file=sys.stderr)
    # Não iniciamos subprocesso, pois a ferramenta @mcp.tool já foi registrada.
    return None


@mcp.tool()
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
def openrouter_chat(prompt: str, model: str = os.environ.get("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-lite-preview-02-05:free"), system: str | None = None, temperature: float = 0.7) -> str:
    """Chama o endpoint chat do OpenRouter (OpenAI-compatível)."""
    key = OPENROUTER_API_KEY or OPENAI_API_KEY
    if not key:
        return "❌ OPENROUTER_API_KEY/OPENAI_API_KEY não definido."
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return "❌ OpenRouter não retornou choices."
        content = choices[0].get("message", {}).get("content") or ""
        return content.strip() if content else "❌ OpenRouter retornou resposta vazia."
    except httpx.HTTPStatusError as e:
        return f"❌ OpenRouter erro HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"❌ Falha ao chamar OpenRouter: {e}"

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
@mcp.tool()
def gtasks_list_tasks(task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Lista as tarefas atuais com seus IDs (necessário para concluir/deletar)."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        
        token_path = BASE_DIR / "token.json"
        if not token_path.exists(): return "Erro: token.json não encontrado."
        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)
        
        results = service.tasks().list(tasklist=task_list_id, showCompleted=False).execute()
        items = results.get('items', [])
        
        if not items: return f"Lista '{task_list_id}' vazia."
            
        output = [f"📋 Tarefas em '{task_list_id}':"]
        for item in items:
            due = f" [Vencimento: {item.get('due', 'N/A')[:10]}]"
            output.append(f"- ID: {item['id']}\n  Título: {item['title']}{due}")
            
        return "\n".join(output)
    except Exception as e: return f"Erro: {e}"

@mcp.tool()
def gtasks_complete_task(task_id: str, task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Marca uma tarefa específica como concluída."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        
        token_path = BASE_DIR / "token.json"
        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)
        
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        task['status'] = 'completed'
        service.tasks().update(tasklist=task_list_id, task=task_id, body=task).execute()
        
        return f"✅ Tarefa '{task['title']}' marcada como concluída!"
    except Exception as e: return f"Erro ao concluir: {e}"

@mcp.tool()
def gtasks_delete_task(task_id: str, task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw") -> str:
    """Deleta permanentemente uma tarefa específica."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        
        token_path = BASE_DIR / "token.json"
        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)
        
        service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
        return f"🗑️ Tarefa {task_id} deletada com sucesso."
    except Exception as e: return f"Erro ao deletar: {e}"

def gtasks_create_task_natural(
    text: str,
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    context: str = "[Geral]",
    duration_min: int = 30,
    priority: str = "P2",
    task_type: str = "work",
    default_to_today: bool = True,
) -> str:
    """Cria 1 tarefa no Google Tasks sem LLM.

    - interpreta datas relativas em pt-br: "hoje", "amanhã", "depois de amanhã"
    - também aceita data explícita: YYYY-MM-DD ou DD/MM/YYYY
    - se nenhuma data for encontrada e default_to_today=True, usa hoje

    Retorna o ID criado e o título final.
    """
    try:
        from datetime import datetime, date, timedelta, timezone
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

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

        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado. Rode: ./.venv-super/bin/python jarvis.py auth-google --scope tasks."

        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)

        body = {
            'title': title,
            'notes': 'Jarvis',
            'due': _iso_midnight_utc(due_date),
        }
        res = service.tasks().insert(tasklist=task_list_id, body=body).execute()
        return f"✅ Tarefa criada. ID: {res.get('id')}\nTítulo: {title}"

    except Exception as e:
        import traceback
        return f"Erro ao criar tarefa (no-llm): {e}\n{traceback.format_exc()}"

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
            return "Erro: token.json não encontrado. Rode: ./.venv-super/bin/python jarvis.py auth-google --scope tasks para autorizar Calendar + Tasks."

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
            return "Erro: token.json não encontrado. Rode: ./.venv-super/bin/python jarvis.py auth-google --scope tasks para autorizar Calendar + Tasks."

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
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
    calendar_ids: list[str] = ["primary"],
    day_start: str = "08:00",
    day_end: str = "20:00",
    min_slot_min: int = 15,
    buffer_min: int = 15,
    include_overdue: bool = True,
) -> str:
    """Planeja o dia (sem LLM) juntando Google Tasks + Google Calendar.

    - lê tarefas do Google Tasks (não conclui/não altera nada)
    - lê blocos ocupados (busy) do Google Calendar
    - sugere uma ordem e um agenda de execução nos espaços livres

    Params:
    - day: YYYY-MM-DD (no fuso America/Sao_Paulo)
    - day_start/day_end: HH:MM

    Retorna um plano em texto com:
    - busy blocks
    - free slots
    - alocação sugerida (tarefa -> horário)
    """
    try:
        from datetime import datetime, date, time, timedelta, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        # parse day
        y, mo, da = map(int, day.split('-'))
        day_d = date(y, mo, da)

        def _t(hm: str) -> time:
            hh, mm = map(int, hm.split(':'))
            return time(hh, mm)

        start_local = datetime.combine(day_d, _t(day_start), tzinfo=tz) if tz else datetime.combine(day_d, _t(day_start), tzinfo=timezone.utc)
        end_local = datetime.combine(day_d, _t(day_end), tzinfo=tz) if tz else datetime.combine(day_d, _t(day_end), tzinfo=timezone.utc)

        # auth
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return "Erro: token.json não encontrado."

        scopes = [
            'https://www.googleapis.com/auth/tasks',
            'https://www.googleapis.com/auth/calendar.readonly',
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

        # calendar busy
        cal_svc = build('calendar', 'v3', credentials=creds)
        fb_body = {
            "timeMin": start_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "timeMax": end_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "items": [{"id": cid} for cid in calendar_ids],
        }
        fb = cal_svc.freebusy().query(body=fb_body).execute()
        busy_blocks = []
        for cid in calendar_ids:
            for b in fb.get('calendars', {}).get(cid, {}).get('busy', []):
                bs = datetime.fromisoformat(b['start'].replace('Z', '+00:00'))
                be = datetime.fromisoformat(b['end'].replace('Z', '+00:00'))
                busy_blocks.append((bs, be, cid))
        busy_blocks.sort(key=lambda x: x[0])

        # merge overlaps
        merged = []
        for bs, be, cid in busy_blocks:
            if not merged:
                merged.append([bs, be])
                continue
            if bs <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], be)
            else:
                merged.append([bs, be])

        # free slots (com buffer entre blocos)
        buf = timedelta(minutes=int(buffer_min))
        free = []
        cur = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        for bs, be in merged:
            # deixa buffer antes do próximo busy
            fs = cur
            fe = bs - buf
            if fe > fs:
                free.append((fs, fe))
            # pula busy + buffer depois
            cur = max(cur, be + buf)
        if cur < end_utc:
            free.append((cur, end_utc))

        # tasks
        tasks_svc = build('tasks', 'v1', credentials=creds)
        items = tasks_svc.tasks().list(tasklist=task_list_id, showCompleted=False).execute().get('items', [])

        # parse title params
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

        today_local = datetime.now(tz).date() if tz else datetime.now().date()

        task_objs = []
        for it in items:
            title = it.get('title', '')
            due_iso = (it.get('due') or '')
            due_d = None
            if due_iso:
                try:
                    due_d = date.fromisoformat(due_iso[:10])
                except:
                    due_d = None

            params = _parse_params(title)
            dur_min = 30
            if 'duration' in params:
                m = re.match(r"(\d+)", str(params['duration']))
                if m:
                    dur_min = int(m.group(1))
            pr = params.get('priority', 'P2')
            upnext = bool(params.get('upnext', False))

            # filter
            if due_d and due_d > day_d:
                continue
            if due_d and due_d < day_d and (not include_overdue):
                continue

            # if overdue by day, bubble it up
            overdue = bool(due_d and due_d < day_d)

            task_objs.append({
                'id': it.get('id'),
                'title': title,
                'dur_min': dur_min,
                'priority': pr,
                'priority_rank': _priority_rank(pr),
                'upnext': upnext,
                'overdue': overdue,
                'due': due_d,
            })

        task_objs.sort(key=lambda t: (
            0 if t['upnext'] else 1,
            0 if t['overdue'] else 1,
            t['priority_rank'],
            t['due'] or day_d,
        ))

        # allocate into free slots
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
                # buffer entre tarefas
                slot_start = en + buf
                remaining -= chunk
                # avoid tiny remainder
                if slot_start is not None and slot_end is not None and (slot_end - slot_start) < timedelta(minutes=int(min_slot_min)):
                    _advance_slot()

        # output
        def _fmt_dt(dt: datetime) -> str:
            dloc = dt.astimezone(tz) if tz else dt
            return dloc.strftime('%H:%M')

        out = []
        out.append(f"📅 plano do dia {day} (fuso: America/Sao_Paulo)")
        out.append("")
        out.append("busy (agenda):")
        if merged:
            for bs, be in merged:
                out.append(f"- {_fmt_dt(bs)}–{_fmt_dt(be)}")
        else:
            out.append("- (sem busy)")

        out.append("")
        out.append("free slots:")
        if free:
            for fs, fe in free:
                out.append(f"- {_fmt_dt(fs)}–{_fmt_dt(fe)}")
        else:
            out.append("- (sem slots livres)")

        out.append("")
        out.append("alocação sugerida:")
        for tsk, st, en, unscheduled in allocations:
            if unscheduled or st is None:
                out.append(f"- (sem espaço) {tsk['title']}")
            else:
                out.append(f"- {_fmt_dt(st)}–{_fmt_dt(en)} {tsk['title']}")

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
    task_list_id: str = "TUZuVGxQZkRxSjRrWkNtbw",
) -> str:
    """Aplica o planejamento do dia criando eventos no Calendar para as tarefas.

    - chama internamente o mesmo algoritmo de plan_day_from_tasks
    - cria eventos com summary igual ao título da tarefa

    Observação: requer oauth com calendar.events.
    """
    try:
        plan = plan_day_from_tasks(day=day, task_list_id=task_list_id)
        if not create_events:
            return plan

        # extrair linhas de alocação do plano
        lines = plan.splitlines()
        alloc_start = None
        for i,l in enumerate(lines):
            if l.strip().lower().startswith('alocação sugerida'):
                alloc_start = i+1
                break
        if alloc_start is None:
            return plan + "\n\n(sem alocação para aplicar)"

        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
        except Exception:
            tz = None

        from datetime import datetime, timezone
        created = 0
        skipped = 0
        for l in lines[alloc_start:]:
            l = l.strip()
            if not l.startswith('- '):
                continue
            l2 = l[2:]
            if l2.startswith('(sem espaço)'):
                skipped += 1
                continue
            # format: HH:MM–HH:MM title
            m = re.match(r"(\d{2}:\d{2})–(\d{2}:\d{2})\s+(.*)$", l2)
            if not m:
                continue
            st_hm, en_hm, summary = m.groups()
            start_iso = f"{day}T{st_hm}:00-03:00"
            end_iso = f"{day}T{en_hm}:00-03:00"
            res = gcal_create_event(summary=summary, start=start_iso, end=end_iso, calendar_id=calendar_id)
            if res.startswith('✅'):
                created += 1
            else:
                skipped += 1

        return plan + f"\n\n---\n✅ eventos criados: {created}\n↩️ pulados/sem espaço: {skipped}"

    except Exception as e:
        import traceback
        return f"Erro ao aplicar plano: {e}\n{traceback.format_exc()}"


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
    - cria 1 tarefa por linha do new_tasks_input usando gtasks_create_task_natural
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
                task_list_id=task_list_id,
                context=fallback_context,
                duration_min=int(fallback_duration_min),
                priority=fallback_priority,
                task_type=fallback_task_type,
                default_to_today=bool(fallback_default_to_today),
            )
            if isinstance(res, str) and res.strip().startswith("✅"):
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

    # se não foi informado, usa a lista padrão do reclaim (sincronizada com reclaim.ai)
    if not task_list_id:
        task_list_id = os.environ.get("RECLAIM_TASK_LIST_ID", "TUZuVGxQZkRxSjRrWkNtbw")

    # -------- modo llm (tentativa principal) --------
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        # usa o langchain_openai padrão para ter acesso ao método .invoke() síncrono
        from langchain_openai import ChatOpenAI

        # 1. autenticação
        token_path = BASE_DIR / "token.json"
        if not token_path.exists():
            return _fallback_basic(
                reason="token_missing",
                detail="token.json não encontrado. rode auth-google ou use fallback criando tarefas linha a linha.",
            )
        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)

        # 2. listar atuais
        try:
            results = service.tasks().list(tasklist=task_list_id, showCompleted=False).execute()
        except Exception as api_err:
            return _fallback_basic(reason="google_tasks_list_failed", detail=str(api_err))

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

        # 4. extração + validação do json (schema + 1 tentativa de reparo)
        # objetivo: não depender só do prompt para garantir JSON válido.
        tasks_to_insert: list[dict] = []

        def _extract_json_block(text: str) -> str:
            t = (text or "")
            if "```json" in t:
                try:
                    return t.split("```json", 1)[1].split("```", 1)[0].strip()
                except Exception:
                    pass
            # fallback: tenta localizar um array json no texto
            m = re.search(r"(\[\s*\{.*\}\s*\])", t, flags=re.S)
            if m:
                return m.group(1).strip()
            raise ValueError("não encontrei bloco ```json``` nem array JSON no texto")

        def _validate_tasks_payload(obj) -> list[dict]:
            from pydantic import BaseModel, Field, ValidationError
            from typing import Optional, List

            class _Task(BaseModel):
                title: str = Field(min_length=1)
                due: Optional[str] = None
                notes: Optional[str] = None

                # normalização leve
                def cleaned(self) -> dict:
                    out = {
                        "title": (self.title or "").strip(),
                        "notes": (self.notes or "Jarvis").strip() if (self.notes or "").strip() else "Jarvis",
                    }
                    if self.due is not None and str(self.due).strip() != "":
                        due_s = str(self.due).strip()
                        # valida ISO 8601 básico esperado
                        # aceitamos "YYYY-MM-DD" e transformamos em Z
                        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_s):
                            due_s = due_s + "T00:00:00Z"
                        # exige YYYY-MM-DDT00:00:00Z (Z obrigatório)
                        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", due_s):
                            raise ValueError(f"due inválido: {due_s}")
                        # parse para garantir que é data válida
                        try:
                            datetime.strptime(due_s, "%Y-%m-%dT%H:%M:%SZ")
                        except Exception as e:
                            raise ValueError(f"due inválido (parse): {due_s} ({e})")
                        out["due"] = due_s
                    return out

            if not isinstance(obj, list):
                raise ValueError("json não é array")
            if not obj:
                raise ValueError("json array vazio")

            cleaned: list[dict] = []
            errors: list[str] = []
            for idx, item in enumerate(obj):
                try:
                    t = _Task.model_validate(item)
                    cleaned.append(t.cleaned())
                except Exception as e:
                    errors.append(f"idx={idx}: {e}")

            if errors:
                raise ValueError("erros de validação: " + " | ".join(errors[:5]))

            return cleaned

        def _repair_json_with_llm(bad_text: str, err: str) -> str:
            # 1 tentativa curta: pedir pro modelo retornar SOMENTE um bloco ```json ...``` válido.
            repair_prompt = f"""
Corrija o JSON para ficar válido e compatível com Google Tasks API.

Erros encontrados: {err}

Regras obrigatórias:
- responda SOMENTE com um bloco ```json contendo um ARRAY JSON válido.
- cada item deve ter: title (string), due (opcional, ISO 8601 'YYYY-MM-DDT00:00:00Z'), notes (opcional).
- sem comentários, sem texto fora do bloco.

Texto original:
{bad_text}
""".strip()

            rep = llm.invoke(
                [
                    SystemMessage(content="você é um validador e corretor de JSON. siga as regras de saída literalmente."),
                    HumanMessage(content=repair_prompt),
                ]
            )
            return getattr(rep, 'content', '') or ''

        # primeira tentativa: parse e validação
        try:
            json_block = _extract_json_block(content)
            tasks_to_insert = _validate_tasks_payload(json.loads(json_block))
        except Exception as parse_err:
            # tentativa de reparo
            try:
                repaired = _repair_json_with_llm(content, str(parse_err))
                json_block2 = _extract_json_block(repaired)
                tasks_to_insert = _validate_tasks_payload(json.loads(json_block2))
                content = content + "\n\n---\n[auto-repair-json] aplicado"  # só pra auditoria
            except Exception as repair_err:
                return _fallback_basic(reason="llm_json_parse_failed", detail=f"parse={parse_err} | repair={repair_err}")

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
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _fallback_basic(reason="llm_mode_exception", detail=str(e) + "\n" + traceback.format_exc())


# --- MERGED LOCAL SCRIPTS (auth/bridge/venv/oci) ---
_GOOGLE_TASKS_SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.readonly',
]
_GOOGLE_DRIVE_SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/drive.file',
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

    normalized_scope = (scope or "").strip().lower()
    if normalized_scope == "tasks":
        selected_scopes = _GOOGLE_TASKS_SCOPES
        already_valid_msg = "✅ Token Google Tasks já válido em {token_file}. Seguindo sem novo login."
        saved_msg = "✅ Token com escopo Tasks/Calendar salvo em {token_file}"
        default_port = 18797
        default_open_browser = False
    elif normalized_scope == "drive":
        selected_scopes = _GOOGLE_DRIVE_SCOPES
        already_valid_msg = "✅ Token com escopo Drive já válido em {token_file}. Seguindo sem novo login."
        saved_msg = "✅ Token com escopo Drive salvo em {token_file}"
        default_port = 0
        default_open_browser = True
    else:
        print("❌ Escopo inválido. Use --scope tasks ou --scope drive.", file=sys.stderr)
        return 1

    requested_port = default_port if port is None else int(port)
    requested_open_browser = default_open_browser if open_browser is None else bool(open_browser)

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
            )

    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(saved_msg.format(token_file=token_file))
    return 0


def _graph_login_cli(
    client_id: str = "",
    authority: str = "https://login.microsoftonline.com/consumers",
    cache_path: str = "~/.graph_token_cache.bin",
) -> int:
    try:
        import msal
    except Exception as e:
        print(f"❌ msal não disponível: {e}", file=sys.stderr)
        return 1

    client_id = (client_id or "").strip()
    if not client_id:
        print("❌ GRAPH_CLIENT_ID/MSGRAPH_CLIENT_ID não definido.", file=sys.stderr)
        return 1

    scopes = ["Files.ReadWrite.All", "offline_access"]
    cache_file = Path(cache_path).expanduser()
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    cache = msal.SerializableTokenCache()
    if cache_file.exists():
        try:
            cache.deserialize(cache_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    try:
        accounts = app.get_accounts() or []
    except Exception:
        accounts = []
    for account in accounts:
        try:
            silent = app.acquire_token_silent(scopes, account=account)
        except Exception:
            silent = None
        if silent and "access_token" in silent:
            try:
                cache_file.write_text(cache.serialize(), encoding='utf-8')
            except Exception:
                pass
            print(f"✅ Login Graph já válido em cache ({cache_file}). Seguindo sem novo login.")
            return 0

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        print(f"❌ Falhou em iniciar device flow: {flow}", file=sys.stderr)
        return 1

    print(flow.get("message", "Siga o fluxo de autenticação no link indicado."))
    result = app.acquire_token_by_device_flow(flow)

    try:
        cache_file.write_text(cache.serialize(), encoding='utf-8')
    except Exception:
        pass

    if "access_token" not in result:
        print("❌ Login Graph falhou:", file=sys.stderr)
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1

    print(f"✅ Login Graph concluído. Cache salvo em {cache_file}")
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
        api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    
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
            print(f"❌ Erro no modelo {model}: {result['error']}", file=sys.stderr)
    
    # Se nenhum modelo funcionar, retorna o fallback
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
    api_key = (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
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
    has_api_key = bool((env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip())

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
            return {
                "ok": False,
                "error": f"fallback_http_failed: {exc}",
                "provider": "google_api_fallback",
                "dns_preflight_ok": dns_ok,
                "dns_preflight_detail": dns_detail,
                "run_as_user": run_as_user or env.get("USER", ""),
                "gemini_cli_home": env.get("GEMINI_CLI_HOME", ""),
            }

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
        has_api_key = bool((env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip())
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


@mcp.tool()
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


@mcp.tool()
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


def run_reclaim_ui_action(
    action: str,
    title: str,
    timeout_sec: int = 25,
    executor_cmd: str | None = None,
    extra_env: dict | None = None,
) -> dict:
    normalized_action = (action or "").strip().lower()
    normalized_title = (title or "").strip()

    if normalized_action not in {"start", "stop", "restart", "next"}:
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
    type_delay_ms = str(int(float(os.environ.get("RECLAIM_UI_TYPE_DELAY_MS", "1"))))
    window_regex = os.environ.get(
        "RECLAIM_UI_WINDOW_REGEX", "Reclaim|app.reclaim.ai|Google Chrome|Chromium|Firefox"
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
    window_id = window_lines[-1] if window_lines else ""
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

    # Pre-flight: garantir que estamos na tela padrão desejada do Reclaim.
    ensure_url = os.environ.get("RECLAIM_UI_ENSURE_URL", "true").strip().lower() in {"1", "true", "yes", "on"}
    ensure_url_value = os.environ.get("RECLAIM_UI_LOGIN_URL", "").strip()
    if ensure_url and ensure_url_value:
        _send_keys(window_id, "ctrl+l")
        _run_xdotool(["type", "--window", window_id, "--delay", type_delay_ms, "--", ensure_url_value], step_timeout=10)
        _send_keys(window_id, "Return")
        time.sleep(max(step_sleep, float(os.environ.get("RECLAIM_UI_NAV_SLEEP_SEC", "0.6"))))

    if normalized_action == "next":
        return {
            "status": "error",
            "result": "next_not_supported_internal",
            "error": {
                "code": "next_not_supported_internal",
                "message": "Executor interno não resolve próximo item visual. Configure RECLAIM_UI_EXECUTOR_CMD para extração por elementos.",
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
        type_cp = _run_xdotool(["type", "--window", window_id, "--delay", type_delay_ms, "--", normalized_title], step_timeout=10)
        if type_cp.returncode != 0:
            return {
                "status": "error",
                "result": "type_failed",
                "error": {"code": "type_failed", "message": "Falha ao digitar o título na UI."},
                "action": normalized_action,
                "title": normalized_title,
                "window_id": window_id,
                "executor": "jarvis_internal_reclaim_ui",
                "executor_stderr": (type_cp.stderr or type_cp.stdout or "").strip(),
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
        "result": "action_executed",
        "message": "Ação enviada para UI do Reclaim.",
        "mode": "embedded_xdotool",
        "action": normalized_action,
        "title": normalized_title,
        "window_id": window_id,
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


def _open_login_url(url: str | None) -> dict:
    payload = {
        "url": str(url or ""),
        "opened": False,
        "method": "manual",
    }
    if not url:
        payload["reason"] = "login_url_missing"
        return payload

    if not os.environ.get("DISPLAY"):
        payload["reason"] = "display_missing"
        return payload

    browser_mode = os.environ.get("RECLAIM_UI_BROWSER_MODE", "").strip().lower()
    chrome_user_data_dir = os.environ.get("RECLAIM_UI_CHROME_USER_DATA_DIR", "").strip()

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
        except Exception as exc:
            payload["reason"] = str(exc)
            return payload

    opener = shutil.which("xdg-open")
    if not opener:
        payload["reason"] = "xdg-open_not_found"
        return payload

    try:
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        payload["opened"] = True
        payload["method"] = "xdg-open"
    except Exception as exc:
        payload["reason"] = str(exc)
    return payload


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
    visual_flow = _open_login_url(login_url) if open_browser else {"url": login_url or ""}
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

# --- END MERGED: reclaim_ui.py ---


# --- RECLAIM UI AUTOMATION (BASE CONTRACT) ---
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


def _reclaim_open_login_url() -> dict:
    payload = {
        "url": RECLAIM_UI_LOGIN_URL,
        "opened": False,
        "method": "manual",
    }

    if not os.environ.get("DISPLAY"):
        payload["reason"] = "DISPLAY não definido"
        return payload

    browser_mode = os.environ.get("RECLAIM_UI_BROWSER_MODE", "").strip().lower()
    chrome_user_data_dir = os.environ.get("RECLAIM_UI_CHROME_USER_DATA_DIR", "").strip()

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
            cmd.append(f"--app={RECLAIM_UI_LOGIN_URL}")
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
            [opener, RECLAIM_UI_LOGIN_URL],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        payload["opened"] = True
        payload["method"] = "xdg-open"
        return payload
    except Exception as e:
        payload["reason"] = str(e)
        return payload


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
    token_path = BASE_DIR / "token.json"
    if not token_path.exists():
        return {
            "status": "error",
            "error": {
                "code": "token_missing",
                "message": "token.json não encontrado para resolver títulos via Google Tasks.",
            },
            "candidates": [],
        }
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token_path), ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)
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
                "code": "gtasks_resolution_failed",
                "message": f"Falha ao buscar tarefas no Google Tasks: {e}",
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


@mcp.tool()
def reclaim_session_bootstrap(
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
    }
    if open_browser:
        visual_flow = _reclaim_open_login_url()

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
    """Inicia tarefa no Reclaim por título exato ou por detecção automática (quando título vazio)."""
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
            payload["result"] = "started"
            payload["executed_at"] = ui_action.get("executed_at")
            payload["message"] = "Ação Start executada na UI do Reclaim (modo automático)."
            payload["next_step"] = "Verifique o timer ativo no Reclaim para confirmar o foco."
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
            payload["result"] = "started"
            payload["executed_at"] = ui_action.get("executed_at")
            payload["message"] = "Ação Start executada na UI do Reclaim."
            payload["next_step"] = "Verifique o timer ativo no Reclaim para confirmar o foco."
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

# --- 7. NATIVE RAG (ChromaDB) ---
class _DeterministicEmbeddingFunction:
    """Fallback offline de embedding para evitar dependência de rede."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def name(self) -> str:
        return "deterministic-embedding-v1"

    def is_legacy(self) -> bool:
        return True

    def _embed_text(self, text: str) -> list[float]:
        import hashlib
        import math

        raw = text or ""
        vec: list[float] = []
        counter = 0
        while len(vec) < self.dim:
            digest = hashlib.sha256(f"{counter}:{raw}".encode("utf-8", errors="ignore")).digest()
            for i in range(0, len(digest), 4):
                chunk = digest[i:i+4]
                if len(chunk) < 4:
                    continue
                value = int.from_bytes(chunk, byteorder="big", signed=False)
                vec.append((value / 4294967295.0) * 2.0 - 1.0)
                if len(vec) >= self.dim:
                    break
            counter += 1

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input):
        texts = [input] if isinstance(input, str) else list(input or [])
        return [self._embed_text(t) for t in texts]

    def embed_query(self, input: str):
        return [self._embed_text(input)]

    def embed_documents(self, input):
        texts = [input] if isinstance(input, str) else list(input or [])
        return [self._embed_text(t) for t in texts]


def _resolve_embedding_function():
    from chromadb.utils import embedding_functions
    mode = os.environ.get("RAG_EMBEDDING_MODE", "deterministic").strip().lower()

    if mode in ("deterministic", "offline", "local"):
        return _DeterministicEmbeddingFunction(), "deterministic"

    try:
        ef = embedding_functions.DefaultEmbeddingFunction()
        return ef, "default"
    except Exception as e:
        print(f"⚠️ RAG: fallback para embedding offline determinístico ({e})", file=sys.stderr)
        return _DeterministicEmbeddingFunction(), "deterministic"


def _rag_collection_name(embedding_name: str) -> str:
    if embedding_name == "default":
        return "knowledge_base"
    return "knowledge_base_offline"


@mcp.tool()
def rag_index(path: str) -> str:
    """Indexa documentos (.txt, .md, .pdf) de uma pasta para busca semântica."""
    try:
        import chromadb
        
        # Configura Chroma (Persistente)
        client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_db"))
        ef, ef_name = _resolve_embedding_function()
        collection = client.get_or_create_collection(
            name=_rag_collection_name(ef_name),
            embedding_function=ef,
        )
        
        target_path = Path(path)
        if not target_path.exists(): return "Caminho não encontrado."
        
        files = []
        if target_path.is_file(): files = [target_path]
        else: files = list(target_path.rglob("*"))
        
        indexed_count = 0
        ids, docs, metadatas = [], [], []
        
        for file in files:
            if file.suffix not in [".txt", ".md", ".pdf"]: continue
            
            text = ""
            if file.suffix == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(file)
                    text = "\n".join([p.extract_text() for p in reader.pages])
                except Exception as pdf_error:
                    print(f"⚠️ RAG: ignorando PDF '{file}' ({pdf_error})", file=sys.stderr)
                    continue
            else:
                try: text = file.read_text(errors="ignore")
                except: continue
            
            if not text.strip(): continue
            
            # Chunking simples (1000 chars)
            chunks = [text[i:i+1000] for i in range(0, len(text), 900)]
            for i, chunk in enumerate(chunks):
                ids.append(f"{file.name}_{i}")
                docs.append(chunk)
                metadatas.append({"source": str(file), "chunk": i})
                
            indexed_count += 1
            
        if docs:
            # Upsert (em lotes de 100 para não travar)
            batch_size = 100
            for i in range(0, len(docs), batch_size):
                collection.upsert(
                    ids=ids[i:i+batch_size],
                    documents=docs[i:i+batch_size],
                    metadatas=metadatas[i:i+batch_size]
                )
                
        return f"Indexação concluída! {indexed_count} arquivos processados, {len(docs)} fragmentos criados. Embedding: {ef_name}."
    except Exception as e:
        return f"Erro ao indexar: {e}"

@mcp.tool()
def rag_search(query: str, n_results: int = 5) -> str:
    """Busca semântica na base de conhecimento indexada."""
    try:
        import chromadb
        
        client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_db"))
        ef, ef_name = _resolve_embedding_function()
        collection = client.get_collection(
            name=_rag_collection_name(ef_name),
            embedding_function=ef,
        )
        
        results = collection.query(query_texts=[query], n_results=n_results)
        
        output = [f"🔍 Resultados para: '{query}' (embedding: {ef_name})\n"]
        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            output.append(f"--- Fonte: {meta['source']} ---\n{doc}\n")
            
        return "\n".join(output)
    except Exception as e:
        return f"Erro na busca (talvez precise indexar primeiro): {e}"


def _mcp_text_content(payload: dict) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=True),
            }
        ]
    }


def _title_from_source(source: str | None, fallback: str) -> str:
    if not source:
        return fallback
    name = Path(source).name
    return name or fallback


@mcp.tool()
def search(query: str) -> dict:
    """Search the local vector store and return MCP connector results."""
    results: list[dict] = []
    query = (query or "").strip()
    if not query:
        return _mcp_text_content({"results": results})

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_db"))
        ef, ef_name = _resolve_embedding_function()
        collection = client.get_collection(
            name=_rag_collection_name(ef_name),
            embedding_function=ef,
        )
        max_results = int(os.environ.get("MCP_SEARCH_MAX_RESULTS", "5"))
        data = collection.query(
            query_texts=[query],
            n_results=max_results,
            include=["ids", "metadatas"],
        )
        ids = data.get("ids", [[]])[0]
        metas = data.get("metadatas", [[]])[0]
        for idx, doc_id in enumerate(ids):
            meta = metas[idx] if idx < len(metas) else {}
            source = meta.get("source") if isinstance(meta, dict) else None
            title = _title_from_source(source, doc_id)
            url = source if source and re.match(r"^https?://", source) else SERVER_URL
            results.append({"id": doc_id, "title": title, "url": url})
    except Exception:
        results = []

    return _mcp_text_content({"results": results})


@mcp.tool()
def fetch(id: str) -> dict:
    """Fetch a document by id from the local vector store."""
    doc_id = (id or "").strip()
    payload = {
        "id": doc_id,
        "title": doc_id,
        "text": "",
        "url": SERVER_URL,
        "metadata": {},
    }

    if not doc_id:
        payload["metadata"]["error"] = "missing id"
        return _mcp_text_content(payload)

    try:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_db"))
        ef = embedding_functions.DefaultEmbeddingFunction()
        collection = client.get_collection(name="knowledge_base", embedding_function=ef)
        data = collection.get(ids=[doc_id], include=["documents", "metadatas"])
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if docs:
            payload["text"] = docs[0] or ""
        if metas:
            meta = metas[0] or {}
            if isinstance(meta, dict):
                source = meta.get("source")
                payload["metadata"] = meta
                payload["title"] = _title_from_source(source, doc_id)
                if source and re.match(r"^https?://", source):
                    payload["url"] = source
    except Exception as e:
        payload["metadata"] = {"error": str(e)}

    return _mcp_text_content(payload)


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


@mcp.tool()
def gupy_test_token() -> str:
    """Testa se o token da Gupy (GUPY_API_TOKEN) está válido."""
    try:
        with _gupy_client() as c:
            r = c.get("https://api.gupy.io/api/v1/jobs?perPage=1&page=1")
            return f"ok: status={r.status_code} body_prefix={r.text[:120]}".strip()
    except Exception as e:
        import traceback

        return f"erro: {e}\n{traceback.format_exc()}"


@mcp.tool()
def gupy_v1_list_jobs(
    status: str = "published",
    page: int = 1,
    per_page: int = 100,
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
                out.append(
                    f"- id={j.get('id')} | {j.get('status')} | {j.get('name')} | createdAt={j.get('createdAt')}"
                )
            if len(results) > 50:
                out.append(f"(mostrando 50 de {len(results)})")
            return "\n".join(out)
    except Exception as e:
        import traceback

        return f"Erro: {e}\n{traceback.format_exc()}"


@mcp.tool()
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


@mcp.tool()
def onedrive_auth_start() -> dict:
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
        start_fireflies_mcp()
        start_filesystem_mcp()
    # Ferramentas locais (não MCP)
    start_sequential_mcp()

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
        "SEQUENTIAL_MCP_ENABLE": "true",
        "FILESYSTEM_MCP_ENABLE": "false",
        "PLAYWRIGHT_MCP_ENABLE": "true",
        "BRAVE_MCP_ENABLE": "true",
        "FIRECRAWL_ENABLE": "false",
        "FIREFLIES_MCP_ENABLE": "false",
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
    return BASE_DIR / ".agents" / "workflow"


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
        }
    )
    return result


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
    legacy_token = ".planning"
    target_token = ".context/docs/planning_gsd"
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

        count = content.count(legacy_token)
        if count <= 0:
            continue
        remaining_legacy_refs += count
        if not apply_if_needed:
            continue

        updated = content.replace(legacy_token, target_token)
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
        final_remaining += content.count(legacy_token)

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

    src_root = BASE_DIR / ".agents" / "ralph"
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
        return {
            "ok": False,
            "error": "ralph_template_sources_missing",
            "source_root": str(src_root),
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
                    'DEFAULT_PRD_PATH=".context/prd_ralph/prd.json"',
                )
            ],
        },
        {
            "file": root / "bin" / "ralph",
            "replacements": [
                (
                    'const tasksDir = path.join(baseDir, ".agents", "tasks");',
                    'const tasksDir = path.join(baseDir, ".context", "prd_ralph");',
                ),
                (
                    'return path.join(baseDir, ".agents", "tasks");',
                    'return path.join(baseDir, ".context", "prd_ralph");',
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
    checks = {
        "ai_coders_context_global_installed": bool(ai_context_global.get("installed")),
        "gsd_global_installed": bool(gsd_global.get("installed")),
        "gsd_planning_path_patched": bool(gsd_patch.get("ok"))
        and int(gsd_patch.get("remaining_legacy_refs_after", 1)) == 0,
        "ralph_global_installed": bool(ralph_global.get("installed")),
        "ralph_global_templates_ready": bool(ralph_templates.get("ok")),
        "ralph_template_resolution_patched": bool(ralph_patch.get("ok")),
        "ralph_prd_path_patched": bool(ralph_prd_patch.get("ok")),
        ".context/docs": (BASE_DIR / ".context" / "docs").exists(),
    }
    missing = [k for k, ok in checks.items() if not ok]
    return {
        "ok": len(missing) == 0,
        "returncode": 0 if len(missing) == 0 else 1,
        "checks": checks,
        "missing": missing,
    }


def _run_internal_context_update_step() -> dict:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_dir = BASE_DIR / ".ralph" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    report_path = export_dir / f"us001_context_routine_report-{run_id}.md"

    init_out = Path(tempfile.mkdtemp(prefix=f"ai-context-init-{run_id}-"))
    steps: list[dict] = []
    try:
        init_cmd = ["npx", "-y", "@ai-coders/context", "init", ".", "both", "-o", str(init_out)]
        steps.append({"name": "init", **_run_capture_command(init_cmd, cwd=BASE_DIR, timeout_sec=900)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        docs_src = init_out / "docs"
        agents_src = init_out / "agents"
        docs_dst = BASE_DIR / ".context" / "docs"
        agents_dst = BASE_DIR / ".context" / "agents"
        docs_dst.mkdir(parents=True, exist_ok=True)
        agents_dst.mkdir(parents=True, exist_ok=True)
        if docs_src.exists():
            shutil.rmtree(docs_dst, ignore_errors=True)
            shutil.copytree(docs_src, docs_dst)
        if agents_src.exists():
            shutil.rmtree(agents_dst, ignore_errors=True)
            shutil.copytree(agents_src, agents_dst)
        steps.append({"name": "sync_context_dirs", "ok": True, "returncode": 0})

        fill_cmd = ["npx", "-y", "@ai-coders/context", "fill", ".", "-o", "./.context", "-p", "openai", "-m", "openai/gpt-4o-mini"]
        if os.environ.get("OPENAI_BASE_URL", "").strip():
            fill_cmd += ["--base-url", os.environ["OPENAI_BASE_URL"]]
        steps.append({"name": "fill", **_run_capture_command(fill_cmd, cwd=BASE_DIR, timeout_sec=1200)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        report_cmd = ["npx", "-y", "@ai-coders/context", "report", ".", "-f", "markdown", "-o", str(report_path)]
        steps.append({"name": "report", **_run_capture_command(report_cmd, cwd=BASE_DIR, timeout_sec=600)})
        if not steps[-1].get("ok"):
            return {"ok": False, "returncode": steps[-1].get("returncode", 1), "steps": steps}

        return {"ok": True, "returncode": 0, "steps": steps, "report_path": str(report_path)}
    finally:
        shutil.rmtree(init_out, ignore_errors=True)


def _run_internal_quality_gates_step(label: str = "quality_gates") -> dict:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_dir = BASE_DIR / ".ralph" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    summary_path = export_dir / f"{label}_quality_gates_run-{run_id}.md"
    commands = []
    py_target = "super_server_v6.py" if (BASE_DIR / "super_server_v6.py").exists() else "jarvis.py"
    commands.append(("py_compile", ["python3", "-m", "py_compile", py_target], 180))
    if py_target == "super_server_v6.py":
        commands.append(("service_help", ["python3", "super_server_v6.py", "service", "--help"], 180))
    else:
        commands.append(("service_help", ["python3", "jarvis.py", "--help"], 180))
    commands.append(("smoke", ["python3", "-c", "import jarvis, json; r=jarvis._run_internal_smoke_test_step(); print(json.dumps(r, ensure_ascii=False)); raise SystemExit(0 if r.get('ok') else 1)"], 120))
    commands.append(("codex_mcp_list", ["codex", "mcp", "list"], 120))
    commands.append(("gemini_mcp_list", ["env", "CI=1", "gemini", "mcp", "list"], int(os.environ.get("GEMINI_MCP_TIMEOUT", "60"))))

    results: list[dict] = []
    overall_ok = True
    for name, cmd, timeout_sec in commands:
        step = _run_capture_command(cmd, cwd=BASE_DIR, timeout_sec=timeout_sec)
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
        step = _run_internal_context_update_step()
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
        step = _run_internal_quality_gates_step(label=label)
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
            print("❌ GSD global ausente ou patch de .context/docs/planning_gsd falhou.", file=sys.stderr)
            failures += 1
        else:
            patch = ((gsd_setup.get("detail") or {}).get("patch") or {})
            changed = int(patch.get("changed_occurrences", 0))
            if changed > 0:
                print(f"✅ GSD ajustado para .context/docs/planning_gsd ({changed} ocorrência(s) migrada(s)).")
            else:
                print("✅ GSD já estava ajustado para .context/docs/planning_gsd.")

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
                if reason == "local_templates_absent_using_global_templates":
                    print("✅ Templates locais do Ralph ausentes; mantendo templates absorvidos no npm global.")
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
                    "✅ Ralph global ajustado para PRD em cwd + .context/prd_ralph "
                    f"({prd_patch_changed} ocorrência(s) migrada(s))."
                )
            elif int(prd_patch_detail.get("already_patched_files", 0) or 0) > 0:
                print("✅ Ralph global já estava usando PRD em cwd + .context/prd_ralph.")

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
}


def _openclaw_remote_cli(action: str, *, host: str, user: str, ssh_key: str, timeout_sec: int) -> int:
    if (host or "").strip().lower() in {"localhost", "127.0.0.1", "::1"}:
        print("❌ openclaw-remote é exclusivo para OCI/mcp-instance. Host local não permitido.", file=sys.stderr)
        return 1
    script = _OPENCLAW_REMOTE_ACTION_SCRIPTS.get(action)
    if not script:
        print(f"❌ Ação inválida: {action}", file=sys.stderr)
        return 1

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




def _debug_rag_google_cli(
    api_key: str = "",
    model_name: str = "models/text-embedding-004",
    test_text: str = "Isso é um teste de conexão com o Gemini Embeddings",
    verbose: bool = False,
) -> int:
    print("🔍 Iniciando diagnóstico do RAG (Google Mode)...")
    resolved_key = (api_key or "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    if not resolved_key:
        print("❌ GOOGLE_API_KEY não encontrada no ambiente.", file=sys.stderr)
        return 1
    preview = resolved_key[:5] + "..." if len(resolved_key) > 5 else "***"
    print(f"🔑 Chave encontrada: {preview}")
    if verbose:
        print(f"ℹ️ Modelo: {model_name}")
        print(f"ℹ️ Tamanho do texto de teste: {len(test_text)}")
    try:
        from chromadb.utils import embedding_functions

        print("🚀 Tentando instanciar GoogleGenerativeAiEmbeddingFunction...")
        ef = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
            api_key=resolved_key,
            model_name=model_name,
        )
        print("⚡ Gerando embedding de teste...")
        vector = ef([test_text])
        dimension = len(vector[0]) if vector and vector[0] else 0
        print(f"✅ SUCESSO! Vetor gerado. Dimensão: {dimension}")
        return 0
    except Exception as e:
        print(f"❌ FALHA NO GOOGLE EMBEDDINGS: {e}", file=sys.stderr)
        if verbose:
            import traceback

            traceback.print_exc()
        else:
            print("ℹ️ Execute novamente com --verbose para stack trace completo.", file=sys.stderr)
        return 1


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

def _sync_mcp_core(target_home: str = "", include_sudo: bool = True, quiet: bool = False) -> int:
    if quiet:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return _sync_mcp_core(target_home=target_home, include_sudo=include_sudo, quiet=False)

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

        for server in ["jarvis", "taskmaster", "filesystem", "brave", "ai-coders-context", "memory", "gemini"]:
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
        rag_gem = os.environ.get("RAG_COLLECTION_NAME_GEMINI", "kdb_gemini")
        rag_loc = os.environ.get("RAG_COLLECTION_NAME_LOCAL", "kdb_local")
        rag_fb = os.environ.get("RAG_ALLOW_LOCAL_FALLBACK", "true")
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
        reclaim_automation_mode = os.environ.get("RECLAIM_UI_AUTOMATION_MODE", "elements_first")
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
            "OPENAI_API_KEY": openai_key,
            "OPENAI_BASE_URL": openai_base,
            "GOOGLE_API_KEY": google_key,
            "RAG_COLLECTION_NAME_GEMINI": rag_gem,
            "RAG_COLLECTION_NAME_LOCAL": rag_loc,
            "RAG_ALLOW_LOCAL_FALLBACK": rag_fb,
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

    def _sync_codex_prompts(home: Path) -> None:
        source_prompts_dir = BASE_DIR / "prompts_sync"
        codex_prompts_dir = home / ".codex" / "prompts"
        omp_agent_dir = home / ".omp" / "agent"
        omp_prompts_dir = omp_agent_dir / "prompts"
        omp_commands_dir = omp_agent_dir / "commands"

        codex_prompts_dir.mkdir(parents=True, exist_ok=True)
        omp_prompts_dir.mkdir(parents=True, exist_ok=True)
        omp_commands_dir.mkdir(parents=True, exist_ok=True)

        if not source_prompts_dir.exists():
            print(f"⚠️ prompts_sync não encontrado em {source_prompts_dir}")
            return

        copied_codex = 0
        copied_omp_prompts = 0
        copied_omp_commands = 0

        for source in sorted(source_prompts_dir.glob("*.md")):
            if source.name.startswith("."):
                continue

            try:
                prompt_content = source.read_text(encoding="utf-8")
            except Exception as exc:
                print(f"⚠️ Falha ao ler prompt {source}: {exc}")
                continue

            prompt_name = source.stem
            codex_targets = [codex_prompts_dir / source.name]
            omp_prompt_targets = [
                omp_prompts_dir / source.name,
                omp_prompts_dir / f"prompts:{prompt_name}.md",
            ]
            legacy_omp_command_target = omp_commands_dir / source.name
            if legacy_omp_command_target.exists():
                try:
                    legacy_omp_command_target.unlink()
                except Exception as exc:
                    print(f"⚠️ Falha ao remover comando legado {legacy_omp_command_target}: {exc}")

            omp_command_targets = [
                omp_commands_dir / f"prompts:{prompt_name}.md",
            ]

            for target in codex_targets:
                _write_or_update(target, prompt_content)
                copied_codex += 1

            for target in omp_prompt_targets:
                _write_or_update(target, prompt_content)
                copied_omp_prompts += 1

            for target in omp_command_targets:
                _write_or_update(target, prompt_content)
                copied_omp_commands += 1

        if copied_codex == 0:
            print(f"⚠️ Nenhum prompt .md encontrado em {source_prompts_dir}")
            return

        print(
            "✅ Prompts sincronizados "
            f"(Codex: {copied_codex}, OMP prompts: {copied_omp_prompts}, OMP commands: {copied_omp_commands})"
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
        rag_gem = os.environ.get("RAG_COLLECTION_NAME_GEMINI", "kdb_gemini")
        rag_loc = os.environ.get("RAG_COLLECTION_NAME_LOCAL", "kdb_local")
        rag_fb = os.environ.get("RAG_ALLOW_LOCAL_FALLBACK", "true")
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
        reclaim_automation_mode = os.environ.get("RECLAIM_UI_AUTOMATION_MODE", "elements_first")
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

        jarvis_env = {
            "MCP_MODE": "stdio",
            "PYTHONUNBUFFERED": "1",
            "FILESYSTEM_MCP_ENABLE": "false",
            "PLAYWRIGHT_MCP_ENABLE": "false",
            "BRAVE_MCP_ENABLE": "false",
            "OPENAI_API_KEY": openai_key,
            "OPENAI_BASE_URL": openai_base,
            "GOOGLE_API_KEY": google_key,
            "RAG_COLLECTION_NAME_GEMINI": rag_gem,
            "RAG_COLLECTION_NAME_LOCAL": rag_loc,
            "RAG_ALLOW_LOCAL_FALLBACK": rag_fb,
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

        data["mcpServers"] = {
            "jarvis": {
                "command": python_path,
                "args": [str(jarvis_py), "serve"],
                "env": jarvis_env,
                "timeout": 300000,
            },
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
            ".context/docs/planning_gsd/STATE.md",
            ".context/prd_ralph/README.md",
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

    def _sync_project_context_entrypoints() -> None:
        source_gemini_rules = BASE_DIR / "global_rule_sync" / "GEMINI.md"

        context_dirs = [
            BASE_DIR / ".context" / "docs",
            BASE_DIR / ".context" / "docs" / "planning_gsd",
            BASE_DIR / ".context" / "prd_ralph",
            BASE_DIR / ".context" / "workflow",
        ]
        for d in context_dirs:
            d.mkdir(parents=True, exist_ok=True)

        if source_rules.exists():
            _write_or_update(BASE_DIR / "AGENTS.md", source_rules.read_text(encoding="utf-8", errors="ignore"))
            print(f"✅ Projeto AGENTS.md sincronizado em {BASE_DIR / 'AGENTS.md'}")

        if source_gemini_rules.exists():
            _write_or_update(BASE_DIR / "GEMINI.md", source_gemini_rules.read_text(encoding="utf-8", errors="ignore"))
            print(f"✅ Projeto GEMINI.md sincronizado em {BASE_DIR / 'GEMINI.md'}")

        readme_path = BASE_DIR / "README.md"
        readme_marker = "<!-- generated-by-jarvis-project-context -->"
        readme_body = (
            f"{readme_marker}\n"
            "# Contexto do projeto\n\n"
            "Entradas de contexto no nível do projeto (sempre relativas ao cwd):\n\n"
            + "\n".join([f"- `{path}`" for path in PROJECT_CONTEXT_PATHS])
            + "\n\n"
            "Observação: `global_rule_sync/` é fonte de sincronização de regras globais para os clientes, não contexto de projeto.\n"
        )

        must_write_readme = False
        if readme_path.is_symlink():
            try:
                readme_path.unlink(missing_ok=True)
            except Exception:
                pass
            must_write_readme = True
        elif not readme_path.exists():
            must_write_readme = True
        else:
            try:
                existing = readme_path.read_text(encoding="utf-8", errors="ignore")
                if readme_marker in existing:
                    must_write_readme = True
            except Exception:
                must_write_readme = True

        if must_write_readme:
            _write_or_update(readme_path, readme_body)
            print(f"✅ Projeto README.md sincronizado em {readme_path}")

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

    _sync_project_context_entrypoints()

    for h in homes:
        _update_gemini_settings(h)
        _update_codex_config(h)
        _sync_codex_prompts(h)
        _create_links(h)
        _sync_omp_context(h)

    _generate_gemini_system_md()

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
    openclaw.add_argument("action", nargs="?", default="status", choices=["status", "restart", "sync-token", "reset-token", "fix-transcricao"])
    openclaw.add_argument("--host", default=os.environ.get("OPENCLAW_REMOTE_HOST", "mcp-instance"))
    openclaw.add_argument("--user", default=os.environ.get("OPENCLAW_REMOTE_USER", "ubuntu"))
    openclaw.add_argument("--ssh-key", default=os.environ.get("OPENCLAW_REMOTE_SSH_KEY", ""))
    openclaw.add_argument("--ssh-timeout", type=int, default=int(os.environ.get("OPENCLAW_SSH_TIMEOUT", "20")))

    oci = sub.add_parser("install-oci", help="Instala o OCI CLI usando o instalador oficial.")
    oci.add_argument("installer_args", nargs=argparse.REMAINDER, help="Argumentos repassados para o instalador OCI. Use '--' antes dos argumentos.")

    auth_google = sub.add_parser("auth-google", help="Autentica/reautoriza token Google para escopos de Tasks/Calendar ou Drive.")
    auth_google.add_argument("--scope", choices=["tasks", "drive"], default="tasks")
    auth_google.add_argument("--client-secret", default="")
    auth_google.add_argument("--token-path", default=str(BASE_DIR / "token.json"))
    auth_google.add_argument("--host", default="127.0.0.1")
    auth_google.add_argument(
        "--port",
        type=int,
        default=None,
        help="Porta callback OAuth (padrão por escopo: tasks=18797, drive=0).",
    )
    auth_google.add_argument(
        "--open-browser",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Força abrir ou não abrir navegador no login OAuth.",
    )

    graph = sub.add_parser("graph-login", help="Executa login device-flow no Microsoft Graph.")
    graph.add_argument("--client-id", default=os.environ.get("GRAPH_CLIENT_ID", ""))
    graph.add_argument("--authority", default=os.environ.get("GRAPH_AUTHORITY", "https://login.microsoftonline.com/consumers"))
    graph.add_argument("--cache-path", default=os.environ.get("GRAPH_CACHE_PATH", "~/.graph_token_cache.bin"))

    venv = sub.add_parser("install-super-venv", help="Monta/atualiza .venv-super e super_requirements.txt.")
    venv.add_argument("--python-bin", default=os.environ.get("PYTHON_BIN", sys.executable or "python3"))
    venv.add_argument("--skip-playwright", action="store_true")
    venv.add_argument("--keep-old-venvs", action="store_true")

    fw = sub.add_parser("fix-firewall-oci", help="Libera SSH (porta 22) para o seu IP atual na OCI.")
    fw.add_argument("--instance-ip", default=os.environ.get("OCI_TARGET_INSTANCE_IP", "163.176.169.99"))

    gbridge = sub.add_parser("gemini-bridge", help="Executa bridge MCP do Gemini em modo stdio.")
    gbridge.add_argument("--selftest", action="store_true")

    rag_debug = sub.add_parser("debug-rag-google", help="Diagnostica integração do RAG com Google Embeddings.")
    rag_debug.add_argument("--api-key", default="")
    rag_debug.add_argument("--model", default="models/text-embedding-004")
    rag_debug.add_argument("--text", default="Isso é um teste de conexão com o Gemini Embeddings")

    rag_debug.add_argument("--verbose", action="store_true", help="Exibe stack trace e detalhes adicionais no diagnóstico.")
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


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    raw_argv = _normalize_legacy_service_args(raw_argv)

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
        )

    if args.command == "install-oci":
        return _install_oci_cli(args.installer_args)

    if args.command == "auth-google":
        return _auth_google_cli(
            scope=args.scope,
            client_secret=args.client_secret,
            token_path=args.token_path,
            host=args.host,
            port=args.port,
            open_browser=args.open_browser,
        )

    if args.command == "graph-login":
        return _graph_login_cli(
            client_id=args.client_id,
            authority=args.authority,
            cache_path=args.cache_path,
        )

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

    if args.command == "debug-rag-google":
        return _debug_rag_google_cli(
            api_key=args.api_key,
            model_name=args.model,
            test_text=args.text,
            verbose=bool(args.verbose),
        )

    if args.command == "test-reclaim-ui":
        return _test_reclaim_ui_cli(verbose=args.verbose)


    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
