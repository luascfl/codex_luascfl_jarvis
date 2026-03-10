---
description: "Regra global para regeneracao de contexto de projeto"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Regeneracao de contexto de projeto

Quando o usuario pedir para regenerar ou atualizar o contexto no nivel do projeto:

- use o `ai-coders-context` para regenerar e preencher apenas `.context/docs`
- nao gere nem use `.context/agents` e `.context/skills`
- depois da regeneracao dos docs, revise e atualize manualmente os arquivos de fachada e instrucao do projeto quando fizer sentido
- priorize revisao manual de `README.md`, `AGENTS.md` e `GEMINI.md`
- trate `README.md`, `AGENTS.md` e `GEMINI.md` como curadoria manual, nao como output bruto de scaffold
- se algum desses arquivos nao existir no projeto, atualize apenas os existentes e relevantes
