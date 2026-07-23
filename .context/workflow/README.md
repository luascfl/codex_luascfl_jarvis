# PRDs do Ralph

- Caminho ativo consumido por `ralph build`: `.context/prd_ralph/prd.json`
- PRDs por fase:
  - `.context/prd_ralph/prd-phase-01-estabilidade-mcp.json`
  - `.context/prd_ralph/prd-phase-02-contexto-padronizacao.json`
  - `.context/prd_ralph/prd-phase-03-execucao-incremental.json`
  - `.context/prd_ralph/prd-phase-04-documentacao-operacional.json`

## Trocar PRD ativo

Exemplo para ativar fase 2:

```bash
cp .context/prd_ralph/prd-phase-02-contexto-padronizacao.json .context/prd_ralph/prd.json
```
