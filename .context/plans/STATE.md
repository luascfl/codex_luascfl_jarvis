# Estado, Jarvis context stack

## Status atual

- Fase macro: centralização do contexto em `.context`.
- GSD canônico: `.context/plans`.
- Ralph canônico: `.context/workflow`.
- AI Coders Context canônico: `.context/docs`.

## Evidência mais recente

Verificação executada no Jarvis local:

```bash
python3 jarvis.py context-stack-harden
```

Resultado esperado:

- AI Coders Context instalado e endurecido.
- GSD instalado e com path `.context/plans` aplicado.
- Ralph instalado, templates prontos e PRD apontando para `.context/workflow/prd.json`.
- Graphify endurecido para usar `.context/graphify-out`.

## Próxima ação operacional

Quando houver atualização de dependências globais do contexto, rodar:

```bash
python3 jarvis.py context-stack-harden && python3 jarvis.py mcp-sync-clients
```

## Riscos conhecidos

1. Atualizações de `@ai-coders/context`, `get-shit-done-cc` ou `@iannuttall/ralph` podem sobrescrever patches globais.
2. `graphify update .` pode demorar ou encerrar antes de concluir por causa do tamanho do repositório.
3. Arquivos scaffold em `.context/docs` ainda podem estar parcialmente genéricos; eles só devem permanecer se forem documentação técnica curada, não planejamento, story ou grafo.

## Convenção de uso

- Planejamento macro entra aqui, em `PROJECT.md` e `STATE.md`.
- Story incremental continua em `.context/workflow/prd.json`.
- Documentação técnica longa continua em `.context/docs/*.md`.
