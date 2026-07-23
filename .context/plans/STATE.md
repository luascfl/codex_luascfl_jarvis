# Estado, Jarvis context stack

## Status atual

- Fase macro: centralização do contexto em `.context`.
- GSD canônico: `.context/plans`.
- Ralph canônico: `.context/workflow`.
- AI Coders Context canônico: `.context/docs`.

## Evidência mais recente

Verificação executada no Jarvis local:

```bash
.venv-super/bin/python3 -m py_compile jarvis.py
python3 jarvis.py sync-agent-assets --target-home /home/lucas/Downloads/codex_luascfl_jarvis/.sync-assets-test
python3 jarvis.py mcp-sync-clients --target-home /home/lucas/Downloads/codex_luascfl_jarvis/.sync-mcp-test --no-sudo --skip-bridge --no-gemini --quiet-core
graphify update .
```

Resultado e contrato operacional registrados:

- `jarvis.py` compila sem erro.
- `sync-agent-assets` deve operar como sincronização bidirecional segura para prompts e skills: importa itens novos que existam só no cliente, implanta itens novos que existam só no repositório, propaga deleções de itens já conhecidos pelo manifesto e falha com conflito quando ambos os lados mudaram de forma divergente.
- O manifesto local ignorado `.agent-assets-sync-state.json` distingue importação inicial de deleção sincronizada.
- `global_rule_sync/` continua saída AlignTrue repo-to-client only; `system_prompts_sync/` continua fonte/config repo-to-client only.
- Prompts de comando do Oh My Pi são mirrors gerados a partir de `prompts_sync/omp`, não fontes de importação.
- O prompt de projeto permanece OMP-only em `prompts_sync/omp/projeto.md`; equivalentes Codex/Gemini (`projeto.md`/`projeto.toml`) são bloqueados/stale se aparecerem em clientes.
- `mcp-sync-clients` não copia prompts ou skills no sandbox testado.
- Graphify atualizou `.context/graphify-out`.

## Próxima ação operacional

Quando houver atualização de dependências globais do contexto, reinstalar apenas os pacotes canônicos e reaplicar o hardening:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
npm install -g @ai-coders/context get-shit-done-cc @iannuttall/ralph
python3 jarvis.py context-stack-harden && python3 jarvis.py context-stack-check .
```

Depois, se os clientes precisarem receber artefatos de agente ou configuração MCP:

```bash
python3 jarvis.py sync-agent-assets
python3 jarvis.py mcp-sync-clients
```

## Riscos conhecidos

1. Atualizações de `@ai-coders/context`, `get-shit-done-cc` ou `@iannuttall/ralph` podem sobrescrever patches globais.
2. `graphify update .` pode demorar ou encerrar antes de concluir por causa do tamanho do repositório.
3. Arquivos scaffold em `.context/docs` ainda podem estar parcialmente genéricos; eles só devem permanecer se forem documentação técnica curada, não planejamento, story ou grafo.

## Convenção de uso

- Planejamento macro entra aqui, em `PROJECT.md` e `STATE.md`.
- Story incremental continua em `.context/workflow/prd.json`.
- Documentação técnica longa continua em `.context/docs/*.md`.
