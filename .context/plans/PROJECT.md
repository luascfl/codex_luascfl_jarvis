# Projeto, Jarvis context stack

## Escopo

Manter o Jarvis como camada operacional local para MCPs, contexto de projeto e automações pessoais, usando um stack restrito:

- AI Coders Context: somente `.context/docs`.
- GSD: planejamento macro em `.context/plans`.
- Ralph: execução incremental e runtime em `.context/workflow`.
- Graphify: grafo estrutural em `.context/graphify-out`.

## Decisões vigentes

1. AI Coders Context não deve gerar `.context/skills` nem `.context/agents`.
2. Qualquer `ai-context init` deve ser forçado para modo `docs`.
3. Ações de escrita de skills pelo AI Coders Context devem ser bloqueadas.
4. GSD não deve usar `.planning` nem `.context/plans`; o caminho canônico é `.context/plans`.
5. Ralph não deve usar `.agents/tasks/prd.json` nem `.ralph`; o PRD ativo fica em `.context/workflow/prd.json` e o runtime fica em `.context/workflow/ralph`.
6. O comando canônico para reaplicar as restrições globais é `python3 jarvis.py context-stack-harden`.

## Componentes

| Componente | Responsabilidade | Caminho canônico |
|---|---|---|
| AI Coders Context | documentação técnica curada e mapa textual | `.context/docs` |
| GSD | milestones, fases, dependências e decisões macro | `.context/plans` |
| Ralph | story atual, DoD, evidência de validação e runtime | `.context/workflow` |
| Graphify | relações estruturais e impacto entre módulos | `.context/graphify-out` |

## Marcos

### Estabilização do stack restrito

- Garantir `@ai-coders/context` em modo docs only.
- Garantir GSD apontando para `.context/plans`.
- Garantir Ralph apontando para `.context/workflow/prd.json` e runtime em `.context/workflow/ralph`.
- Validar com `python3 jarvis.py context-stack-harden`.

### Higiene de contexto

- Remover `.context/skills` e `.context/agents` quando reaparecerem.
- Manter `.context/docs` só para documentação técnica curada.
- Manter `AGENTS.md` e `GEMINI.md` como fachadas manuais sincronizadas.

## Comandos úteis

```bash
python3 jarvis.py context-stack-harden
python3 jarvis.py mcp-status
python3 jarvis.py mcp-sync-clients
```
