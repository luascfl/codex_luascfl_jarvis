---
description: "Semantica de escopo entre global, system prompt e contexto de projeto"
globs:
  - "**/*"
apply_to: alwaysOn
---

# Semantica de escopo de contexto

Quando o usuario disser "adicione isso ao global" ou "ao system prompt":

- trate como camada global
- use `.aligntrue/rules/` como fonte canonica
- reflita a regra em `system_prompts_sync/` e nos artefatos globais derivados
- nao registre isso em `.context/docs/` do projeto, exceto se o usuario pedir explicitamente documentacao local

Quando o usuario disser "adicione isso ao contexto do nivel do projeto":

- trate como contexto do cwd atual
- use `.context/docs/`, `AGENTS.md`, `GEMINI.md`, workflow e arquivos do projeto conforme necessario
- nao promova para a camada global sem pedido explicito

Quando um pedido misturar politica geral e detalhe especifico do projeto:

- separe em camadas
- coloque a politica geral no global
- coloque o detalhe operacional no contexto do projeto
- coloque comportamento executavel no workflow ou no codigo do projeto quando necessario

Quando houver alteracao na camada global:

- rode `aligntrue sync` antes de `python3 jarvis.py mcp-sync-clients`
- use `aligntrue sync` para compilar a nova regra global
- use `mcp-sync-clients` apenas para distribuir os artefatos globais ja compilados aos clientes
