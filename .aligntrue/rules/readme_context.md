---
description: "Forca leitura do README como contexto de projeto"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Contexto de README

O README.md do projeto deve ser tratado como fonte de contexto obrigatoria, no mesmo nivel de importancia dos arquivos de instrucoes globais.

## Regras por agente

- Se estiver rodando no Codex: leia AGENTS.md primeiro, depois README.md, `.context/docs/README.md`, `.context/docs/planning_gsd/STATE.md` e `.context/prd_ralph/README.md`.
- Se estiver rodando no Gemini: leia AGENTS.md primeiro, depois README.md, `.context/docs/README.md`, `.context/docs/planning_gsd/STATE.md` e `.context/prd_ralph/README.md`.
- GEMINI.md e CLAUDE.md sao arquivos de compatibilidade quando AGENTS.md nao estiver disponivel.
