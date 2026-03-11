---
description: "Regra global para regeneracao de contexto de projeto"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Regeneracao de contexto de projeto

Quando o usuario pedir para regenerar ou atualizar o contexto no nivel do projeto:

- use `jarvis.workflow_stack` com `action="context_refresh"` como entrada preferencial quando a tool estiver disponivel
- essa rotina do workflow deve garantir no projeto:
  - existencia de `.context/docs`
  - existencia de `.context/docs/planning_gsd`
  - existencia de `.context/prd_ralph`
  - existencia de `.context/workflow`
  - sincronizacao de `AGENTS.md`
  - sincronizacao de `GEMINI.md`
- `mcp-sync-clients` fica restrito a configuracao global dos clientes, prompts de sistema e fallback rule names
- se precisar operar direto no AI Coders Context, use esta sequencia base:
  - `context.check`
  - `context.init` apenas se a estrutura estiver faltando, e sempre em modo docs only
  - `context.listToFill`
  - `context.fill` para atualizar em massa `.context/docs`
  - `context.fillSingle` para corrigir arquivos especificos em `.context/docs`
  - `context.getMap` e `context.buildSemantic` para enriquecer ou reconstruir contexto estrutural quando houver mudanca relevante
- use o `ai-coders-context` para regenerar e preencher apenas `.context/docs`
- nao gere nem use `.context/agents` e `.context/skills`
- nao use `skill.*`, `sync.importAgents`, `sync.importSkills` nem fluxos equivalentes para contexto de projeto
- `README.md` e opcional no projeto e nao deve ser recriado automaticamente pelo workflow
- se o repositorio tiver remoto no GitHub e `README.md` estiver ausente, trate isso como recomendacao manual, nao como geracao automatica
- depois da regeneracao dos docs, revise e atualize manualmente os arquivos de fachada e instrucao do projeto quando fizer sentido
- priorize revisao manual de `README.md`, `AGENTS.md` e `GEMINI.md`
- trate `README.md`, `AGENTS.md` e `GEMINI.md` como curadoria manual, nao como output bruto de scaffold
- se algum desses arquivos nao existir no projeto, atualize apenas os existentes e relevantes
