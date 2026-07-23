---
type: doc
name: tooling
description: Scripts, IDE settings, automation, and developer productivity tips
category: tooling
generated: 2026-07-23
status: filled
scaffoldVersion: "2.0.0"
---

# Tooling and productivity guide

Este guia registra a instalação correta do stack global usado pelo Jarvis: AI Coders Context, GSD, Ralph e Graphify. O objetivo é evitar CLIs homônimos ou pacotes parecidos que não seguem o layout endurecido do Jarvis.

## Pacotes globais corretos

| Ferramenta | Pacote npm correto | Binário esperado | Função no stack |
|---|---|---|---|
| AI Coders Context | `@ai-coders/context` | `ai-context` | Gera e atualiza `.context/docs` em modo docs only. |
| GSD | `get-shit-done-cc` | `gsd-sdk` / `gsd-tools` quando expostos pelo pacote | Mantém planejamento macro em `.context/plans`. |
| Ralph | `@iannuttall/ralph` | `ralph` | Mantém execução incremental, PRD e runtime em `.context/workflow`. |

## Pacotes Ralph que não são o Ralph deste stack

Não use estes pacotes como Ralph canônico do Jarvis:

```bash
@wiggumdev/ralph
@ralph-orchestrator/ralph-cli
ralph-wiggum-cli
rlph-cli
```

Eles podem instalar um binário chamado `ralph`, mas não são o pacote que `jarvis.py context-stack-harden` espera. O Jarvis procura e corrige o pacote global `@iannuttall/ralph`.

## Instalação global limpa

Use este fluxo quando precisar reinstalar o stack global:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
npm install -g @ai-coders/context get-shit-done-cc @iannuttall/ralph
cd /home/lucas/Downloads/codex_luascfl_jarvis
python3 jarvis.py context-stack-harden
python3 jarvis.py context-stack-check .
```

O `context-stack-harden` é obrigatório depois da instalação porque ele reaplica os patches globais do Jarvis:

- força AI Coders Context para `.context/docs` sem `.context/skills` ou `.context/agents`;
- força GSD para `.context/plans`;
- força Ralph para `.context/workflow/prd.json` e runtime em `.context/workflow/ralph`;
- força Graphify para `.context/graphify-out`.

## Verificação por CLI

```bash
ai-context --version
npm list -g @ai-coders/context get-shit-done-cc @iannuttall/ralph --depth=0
command -v ralph
ralph --help
python3 jarvis.py context-stack-check .
```

Resultado esperado:

- `ai-context` responde com a versão instalada.
- `npm list -g` mostra `@ai-coders/context`, `get-shit-done-cc` e `@iannuttall/ralph`.
- `ralph` vem do pacote `@iannuttall/ralph`, não de `@wiggumdev/ralph` ou outro homônimo.
- `context-stack-check` não mostra caminhos legados como `.context/prd_ralph`, `.planning`, `.ralph` ou `.agents/tasks`.

## Diagnóstico quando o Ralph não funciona

1. Verifique qual binário está sendo chamado:

```bash
command -v ralph
npm list -g @iannuttall/ralph @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli --depth=0
```

2. Se aparecer outro pacote com binário `ralph`, remova os homônimos e reinstale o pacote correto:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
npm install -g @iannuttall/ralph
cd /home/lucas/Downloads/codex_luascfl_jarvis
python3 jarvis.py context-stack-harden
```

3. Rode a checagem final:

```bash
python3 jarvis.py context-stack-check .
```

## Observação sobre `ralph build`

O stack do Jarvis deve tratar Ralph como execução incremental em `.context/workflow`. Se o pacote global instalado não oferecer `ralph build`, não use isso como bloqueio. O contrato operacional é uma story por ciclo, DoD explícito, evidência de validação e atualização de contexto.

## Comandos úteis do Jarvis

```bash
python3 jarvis.py context-stack-harden
python3 jarvis.py context-stack-check .
python3 jarvis.py workflow-stack --help
python3 jarvis.py mcp-status
python3 jarvis.py mcp-sync-clients
python3 jarvis.py sync-agent-assets
```

## Sincronização de agent assets

`python3 jarvis.py sync-agent-assets` lê as fontes versionadas abaixo e sincroniza os clientes globais. `mcp-sync-clients` fica restrito à configuração MCP e ao bridge Codex/Gemini:

| Fonte no repositório | Destino sincronizado |
|---|---|
| `prompts_sync/codex/*.md` | `~/.codex/prompts/*.md` |
| `prompts_sync/gemini/*.toml` | `~/.gemini/commands/*.toml` |
| `prompts_sync/omp/*.md` | `~/.omp/agent/prompts/*.md` e `~/.omp/agent/commands/prompts:*.md` |
| `skills_sync/codex/<skill>/SKILL.md` | `~/.codex/skills/<skill>/` |
| `skills_sync/gemini/<skill>/SKILL.md` | `~/.gemini/skills/<skill>/` |
| `skills_sync/omp/skills/<skill>/SKILL.md` | `~/.omp/agent/skills/<skill>/` |
| `skills_sync/omp/managed-skills/<skill>/SKILL.md` | `~/.omp/agent/managed-skills/<skill>/` |

Os prompts Codex que antes ficavam diretamente em `prompts_sync/*.md` agora ficam em `prompts_sync/codex/`. O prompt `projeto` do Oh My Pi fica em `prompts_sync/omp/projeto.md`.

## Related resources

- [Development workflow](./development-workflow.md)
- [Context stack plan](../plans/PROJECT.md)
- [Context stack state](../plans/STATE.md)
