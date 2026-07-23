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

`python3 jarvis.py sync-agent-assets` é o ponto único de sincronização de prompts e skills entre o repositório e os clientes globais. `mcp-sync-clients` fica restrito à configuração MCP e ao bridge Codex/Gemini; ele não deve copiar prompts ou skills.

Para prompts e skills, a sincronização é bidirecional e segura:

- se um item existe só no cliente e ainda não aparece no manifesto local, ele é importado para a fonte correspondente no repositório;
- se um item existe só no repositório e ainda não aparece no manifesto local, ele é implantado no cliente;
- se um item já era conhecido pelo manifesto e foi removido de um lado, ele é removido do outro lado em vez de ser restaurado;
- se repositório e cliente mudaram desde o manifesto e os conteúdos divergem, o comando preserva os dois lados, reporta conflito e encerra com erro diferente de zero.

O manifesto local usado para diferenciar importação inicial de deleção sincronizada deve ficar no repositório como arquivo ignorado, em `.agent-assets-sync-state.json`.

| Fonte no repositório | Cliente sincronizado |
|---|---|
| `prompts_sync/codex/*.md` | `~/.codex/prompts/*.md` |
| `prompts_sync/gemini/*.toml` | `~/.gemini/commands/*.toml` |
| `prompts_sync/omp/*.md` | `~/.omp/agent/prompts/*.md` e mirrors gerados em `~/.omp/agent/commands/prompts:*.md` |
| `skills_sync/codex/<skill>/SKILL.md` | `~/.codex/skills/<skill>/` |
| `skills_sync/gemini/<skill>/SKILL.md` | `~/.gemini/skills/<skill>/` |
| `skills_sync/omp/skills/<skill>/SKILL.md` | `~/.omp/agent/skills/<skill>/` |
| `skills_sync/omp/managed-skills/<skill>/SKILL.md` | `~/.omp/agent/managed-skills/<skill>/` |

`global_rule_sync/` continua sendo saída do AlignTrue e permanece repo-to-client only: os clientes recebem essas regras como referência gerada, mas mudanças feitas no cliente não são importadas de volta como fonte.

`system_prompts_sync/` continua sendo configuração/fonte repo-to-client only para prompts de sistema. Arquivos alterados nos clientes devem ser tratados como cópias derivadas, não como origem de verdade.

Os arquivos de prompt de comando do Oh My Pi em `~/.omp/agent/commands/prompts:*.md` são mirrors gerados a partir de `prompts_sync/omp/`; eles nunca são fonte de importação. O sync deve importar apenas o prompt OMP canônico correspondente, não o mirror de comando.

O prompt de projeto é OMP-only: a fonte canônica é `prompts_sync/omp/projeto.md`. Arquivos `prompts_sync/codex/projeto.md` e `prompts_sync/gemini/projeto.toml` são nomes bloqueados/stale; se aparecerem nos clientes, devem ser removidos em vez de importados para o repositório.

## Related resources

- [Development workflow](./development-workflow.md)
- [Context stack plan](../plans/PROJECT.md)
- [Context stack state](../plans/STATE.md)
