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
python3 jarvis.py mcp-sync-clients --target-home /home/lucas/Downloads/codex_luascfl_jarvis/.sync-test-home --no-sudo --skip-bridge --no-gemini
graphify update .
```

Resultado observado:

- `jarvis.py` compila sem erro.
- Prompts sincronizam por cliente: Codex em `prompts_sync/codex`, Gemini em `prompts_sync/gemini`, Oh My Pi em `prompts_sync/omp`.
- `skills_sync` sincroniza skills de Codex, Gemini, Oh My Pi e managed skills do Oh My Pi.
- Graphify atualizou `.context/graphify-out`.

## Próxima ação operacional

Quando houver atualização de dependências globais do contexto, reinstalar apenas os pacotes canônicos e reaplicar o hardening:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
npm install -g @ai-coders/context get-shit-done-cc @iannuttall/ralph
python3 jarvis.py context-stack-harden && python3 jarvis.py context-stack-check .
```

Depois, se os clientes MCP precisarem receber os artefatos atualizados:

```bash
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
