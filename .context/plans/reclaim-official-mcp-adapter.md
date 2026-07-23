---
status: planned
generated: 2026-06-18
docs:
  - "https://help.reclaim.ai/en/articles/15265289-reclaim-2-0-claude-integration"
phases:
  - id: "phase-1"
    name: "Official MCP discovery"
  - id: "phase-2"
    name: "Capability map"
  - id: "phase-3"
    name: "Adapter implementation"
  - id: "phase-4"
    name: "Parallel validation"
  - id: "phase-5"
    name: "Policy update"
---

# Reclaim official MCP adapter plan

## Objetivo

Integrar o MCP oficial do Reclaim 2.0 em `https://mcp.reclaim.ai` sem remover as ferramentas atuais. O Jarvis deve preferir o MCP oficial quando ele cobrir o caso de uso e manter Google Tasks, Google Calendar e automacao DOM/CDP como fallback validado.

## Fonte confirmada

A documentacao oficial do Reclaim 2.0 para Claude indica o servidor MCP:

```bash
claude mcp add Reclaim -t http https://mcp.reclaim.ai
```

Capacidades declaradas pela documentacao:

- ver e analisar agenda;
- encontrar melhores horarios de reuniao;
- criar e atualizar eventos;
- proteger foco;
- detectar conflitos;
- otimizar semana;
- coordenar reunioes;
- coordenar work sessions;
- revisar e aplicar mudancas com aprovacao.

## Decisao tecnica

- Nao remover nenhuma ferramenta atual nesta fase.
- Criar uma camada adapter no Jarvis para isolar o provedor Reclaim.
- Ordem de preferencia: MCP oficial Reclaim 2.0, Google Tasks/Calendar, DOM/CDP Reclaim.
- Toda acao destrutiva ou com impacto de agenda deve preservar confirmacao ou validacao observavel.
- `plan_day_apply` continua proibido de criar eventos diretos no Calendar para tarefas Reclaim.
- `event_unlock` continua ponto critico ate prova contraria, porque a doc oficial nao menciona explicitamente unlock de evento locked.
- Jarvis direto so deve operar o MCP oficial depois que houver suporte confirmado a OAuth remoto MCP no proprio Jarvis ou depois que outro cliente compativel concluir a autenticacao e expor ferramentas reais; ate la, o caminho de autenticacao recomendado e Claude Code/Claude connector ou outro cliente MCP remoto com OAuth.

## Fase 1, descoberta do MCP oficial

1. Conectar o servidor oficial em um cliente MCP que permita listar ferramentas.
2. Confirmar autenticacao OAuth/Reclaim.
3. Exportar o inventario real de tools, resources e prompts.
4. Registrar para cada tool:
   - nome;
   - schema de entrada;
   - schema de saida;
   - se exige aprovacao;
   - se altera Calendar, task, work session ou apenas consulta.

Aceite:

- inventario real salvo ou resumido em contexto do projeto;
- diferenca clara entre capacidades documentadas e ferramentas observadas.

## Fase 2, mapa de capacidades

Comparar tools oficiais contra ferramentas atuais:

| Fluxo atual | Candidato MCP oficial | Acao |
| --- | --- | --- |
| `reclaim_next_task` | agenda/task analysis | substituir se retornar proxima tarefa com contexto suficiente |
| `reclaim_task_start` | work session/timer | substituir se iniciar trabalho real |
| `reclaim_task_stop` | work session/timer | substituir se parar trabalho real |
| `reclaim_task_done` | task update/complete | substituir se concluir task Reclaim real |
| `reclaim_task_snooze` | task/event update | substituir se snooze for explicito e validavel |
| `reclaim_task_up_next` | priority/work queue | substituir se houver equivalente |
| `reclaim_task_set_priority` | task update/priority | substituir se prioridade for campo real |
| `reclaim_event_context_menu` | none expected | manter DOM se nao houver equivalente |
| `reclaim_event_unlock` | unknown | manter DOM ate tool oficial provar suporte |
| `reclaim_event_reschedule` | event update/reschedule | substituir apenas com preview/confirmacao |

Aceite:

- cada ferramenta atual classificada como `official`, `fallback`, `hybrid` ou `keep-dom`.

## Fase 3, implementacao do adapter

Adicionar camada interna, sem mudar comandos publicos do Jarvis:

```text
reclaim_provider = official_mcp | google_tasks | dom_cdp
```

Regras:

1. APIs publicas existentes continuam iguais para o usuario.
2. Cada funcao decide provedor por capacidade, nao por preferencia cega.
3. Se o MCP oficial falhar por auth, schema ou ausencia de tool, cair para fallback atual.
4. Se o MCP oficial retornar proposta pendente, mostrar proposta e pedir confirmacao quando a ferramenta exigir approval.
5. Eventos locked continuam usando `reclaim_event_unlock` DOM ate validacao de suporte oficial.

Aceite:

- wrappers existentes continuam chamaveis;
- fallback atual permanece funcional;
- falha do MCP oficial nao quebra planejamento do dia.

## Fase 4, validacao paralela

Validar com tarefas reais pequenas, uma por vez:

1. Listar agenda pelo MCP oficial e comparar com Google Calendar.
2. Listar ou inferir tarefas pelo MCP oficial e comparar com Google Tasks/Reclaim.
3. Criar tarefa teste com parametros reais, sem categoria `[Reclaim]`.
4. Atualizar descricao da tarefa teste com estrutura:
   - Bloqueios;
   - Updates;
   - Contexto;
   - Plano de acao.
5. Iniciar work session/timer, se houver suporte.
6. Parar work session/timer, se houver suporte.
7. Concluir tarefa teste.
8. Testar reschedule com preview/approval, sem data/hora customizada insegura.
9. Testar evento locked apenas se o MCP oficial expuser tool explicita para unlock ou equivalente.

Aceite:

- matriz com resultado observado por fluxo;
- nenhum fallback removido;
- nenhuma acao de Calendar direto introduzida no planejamento Reclaim.

## Fase 5, politica e limpeza controlada

Atualizar politica operacional depois da validacao:

- quando usar MCP oficial;
- quando manter Google Tasks;
- quando manter DOM/CDP;
- quando perguntar antes de aplicar;
- quais fluxos continuam perigosos.

Nao remover codigo antigo nesta fase. Remocao so entra em plano separado depois de periodo de estabilidade.


## Implementacao inicial, 2026-06-18

- `jarvis.py` agora possui configuracao `RECLAIM_OFFICIAL_MCP_ENABLE`, `RECLAIM_OFFICIAL_MCP_URL` e `RECLAIM_OFFICIAL_MCP_PREFIX`.
- O servidor monta `https://mcp.reclaim.ai` via `FastMCP.as_proxy` quando `RECLAIM_OFFICIAL_MCP_ENABLE=true` e child MCPs estao ativos.
- O prefixo padrao e `reclaim2`, para evitar conflito com as ferramentas antigas `reclaim_*`.
- A tool `reclaim_official_adapter_status` expõe o estado do adapter, ferramentas oficiais observadas e politica de fallback.
- Nenhuma ferramenta antiga foi removida.
- `event_unlock` segue classificado como `dom_cdp` ate o MCP oficial provar suporte explicito.
- Jarvis direto ainda nao e garantia para OAuth remoto do Reclaim; o adapter esta pronto para proxy/status, mas a autenticacao inicial deve ser feita por cliente MCP compativel ate implementarmos ou confirmarmos suporte completo a OAuth remoto no Jarvis.

## Oh My Pi integration, 2026-06-18

- OMP foi configurado em `~/.omp/agent/mcp.json` com servidor `reclaim` via `mcp-remote`.
- Configuracao final:
  - `command`: `mcp-remote`
  - `args`: `["https://mcp.reclaim.ai"]`
  - `timeout`: `120000`
- `mcp-remote` foi atualizado globalmente para `0.1.38`; a versao anterior falhava porque nao aceitava `protocolVersion: 2025-11-25`.
- OAuth foi concluido via browser real apos abrir o Planner do Reclaim 2.0 e reabrir o link de autorizacao.
- Validacao direta por JSON-RPC listou 28 tools oficiais, incluindo:
  - `get_schedule`
  - `get_suggested_tasks`
  - `get_at_risk_tasks`
  - `start_task`
  - `stop_task`
  - `create_reclaim_task`
  - `update_reclaim_task`
  - `delete_reclaim_task`
  - `search_reclaim_tasks`
  - `get_pending_changes`
  - `apply_changes`
- Validacao pelo OMP confirmou carregamento do servidor oficial, mas a auditoria completa mostrou que varias tools listadas no MCP estao bloqueadas por upgrade na conta atual. Nao tratar `tools/list` como disponibilidade operacional.
- O helper local experimental de OAuth foi removido; OMP usa `mcp-remote` como bridge OAuth/stdio.

## Capability audit, 2026-06-18

Auditoria executada contra as 28 tools oficiais expostas pelo MCP Reclaim. Resultado operacional por categoria:

### Usar agora no fluxo

- `get_schedule`: fonte oficial para ler agenda Reclaim/Calendar do dia.
- `get_user_preferences`: fonte oficial para fuso, formato, calendarios e preferencias.
- `focus_stats`: analytics de foco; util para revisão semanal, nao para alocacao direta do dia.
- `top_contacts`: contatos frequentes; util para reunioes e contexto comercial.
- `search_contacts`: busca contatos, mas parcial sem permissao People/Contacts completa.
- `get_pending_changes`: leitura segura de mudanças em preview.
- `suggested_times_for_event`: pode sugerir horarios para mover evento existente. Usar apenas como consulta; nao aplicar sem plano e confirmacao.

### Nao usar no fluxo atual

Estas tools aparecem no `tools/list`, mas retornam erro de upgrade na conta atual:

- `get_event_details`
- `find_open_time`
- `get_org_relationships`
- `get_zoom_meeting_summary`
- `add_event`
- `update_event`
- `cancel_event`
- `reschedule_event`
- `change_rsvp`
- `add_video_conference`
- `get_suggested_tasks`
- `get_at_risk_tasks`
- `start_task`
- `stop_task`
- `log_task`
- `create_reclaim_task`
- `update_reclaim_task`
- `delete_reclaim_task`
- `search_reclaim_tasks`
- `apply_changes`

`suggested_times` tambem nao entra no fluxo: a chamada falhou com `Error executing suggested_times: null` mesmo com participante real.

## Plano operacional do fluxo híbrido

### Planejar meu dia

Implementar:

1. Usar `get_schedule` do Reclaim oficial como fonte principal de agenda do dia.
2. Classificar eventos do `get_schedule`:
   - compromissos externos;
   - tarefas Reclaim ja alocadas;
   - travel;
   - reunioes;
   - conflitos e blocos fora do limite normal.
3. Usar Google Tasks para ler:
   - a lista operacional Reclaim atual, enquanto task tools oficiais estiverem bloqueadas;
   - `Minhas tarefas` como dump manual.
4. Considerar explicitamente que a integração Reclaim 2.0 com Google Tasks é no nível da conta Google; no seu caso, todas as listas selecionadas no Reclaim podem sincronizar, mas a lista operacional Reclaim continua sendo a convenção principal para agenda.
5. Continuar tratando `Minhas tarefas` como triagem, nao alocacao automatica.
5. Gerar narrativa GTD:
   - questionar plano Reclaim existente;
   - priorizar tarefas simples antes de cognitivas quando fizer sentido;
   - respeitar pomodoro 45/15;
   - respeitar corte 22:30 salvo quando Lucas disser que vai madrugar.
6. Perguntar antes de fechar o plano quando faltar contexto real:
   - bloqueio;
   - proximo passo;
   - prioridade;
   - prazo;
   - energia/contexto;
   - criterio de conclusao.

Nao implementar:

- Nao usar `get_suggested_tasks`, `get_at_risk_tasks` nem `search_reclaim_tasks` enquanto retornarem erro de upgrade.
- Nao inferir disponibilidade por `find_open_time`, porque esta tool esta bloqueada.
- Nao substituir Google Tasks para tarefas Reclaim ainda.
- Nao aceitar `tools/list` como prova de que uma tool e utilizavel.

### Criar e atualizar tarefas

Implementar:

1. Criar tarefas por Google Tasks na lista operacional Reclaim com parametros no titulo enquanto `create_reclaim_task` estiver bloqueada.
2. Atualizar descricoes com `gtasks_update_task_context`.
3. Manter estrutura:
   - Bloqueios;
   - Updates;
   - Contexto;
   - Plano de acao.
4. Categoria/contexto nunca deve ser `[Reclaim]`; usar contexto real como `[OrganizeJR]`, `[Psicologia]`, `[Curriculo]`, `[Afazeres]`, `[Comercial]`.

Nao implementar:

- Nao usar `create_reclaim_task`, `update_reclaim_task`, `delete_reclaim_task` ou `search_reclaim_tasks` oficiais ate upgrade/validacao real.
- Nao migrar tarefas Google Tasks para Reclaim nativo 2.0 sem plano separado e backup.

### Start, stop, done, snooze e prioridade

Implementar:

1. Manter ferramentas Jarvis/Google Tasks/DOM como fallback atual.
2. Para concluir tarefa, preferir Google Tasks quando a tarefa veio da lista operacional Reclaim sincronizada.
3. Para `start_task` e `stop_task`, usar ferramenta oficial somente depois que deixar de retornar erro de upgrade.

Nao implementar:

- Nao usar `start_task`, `stop_task`, `log_task` oficiais agora.
- Nao criar workaround que marque tarefa como feita se a ferramenta oficial falhar.
- Nao usar snooze/reschedule customizado sem validacao visual.

### Eventos e mudanças no calendario

Implementar:

1. Usar `get_schedule` para leitura.
2. Usar `suggested_times_for_event` apenas para consulta sobre alternativa de horario.
3. Usar `get_pending_changes` para inspecionar mudanças pendentes quando alguma tool oficial de sandbox for validada no futuro.

Nao implementar:

- Nao usar `add_event`, `update_event`, `cancel_event`, `reschedule_event`, `change_rsvp`, `add_video_conference` agora; todas retornaram erro de upgrade.
- Nao chamar `apply_changes`, porque tambem esta bloqueada e aplica mudanças irreversiveis.
- Nao mudar `plan_day_apply` para criar eventos diretos no Calendar.
- Nao usar evento Calendar direto para tarefas Reclaim.

### Unlock, locked events e DOM/CDP

Implementar:

1. Continuar usando heuristica de locked via Calendar e DOM/CDP quando necessario.
2. Tentar `reclaim_event_unlock` para evento com `🔒` ou locked real.
3. Se `Unlock` nao aparecer, preferir snooze com preset claro e validacao visual.
4. Considerar que o menu pode mostrar `Reschedule` em vez de `Snooze`; nao executar automaticamente salvo quando opcao e resultado final forem confirmados visualmente.

Nao implementar:

- Nao substituir `reclaim_event_unlock` por MCP oficial. Nao ha tool oficial validada para unlock.
- Nao usar `reschedule_event` oficial para unlock; esta bloqueada e tambem nao e semanticamente unlock.

## Ordem de implementacao recomendada

1. Atualizar `plan_day_from_tasks` para aceitar agenda ja lida via Reclaim oficial ou para chamar um helper local `reclaim_official_get_schedule`.
2. Adicionar um cache curto do resultado de `get_schedule` para evitar chamadas repetidas no mesmo planejamento.
3. Marcar tools oficiais por capacidade real, nao por presença no `tools/list`.
4. Atualizar `plan_day_apply` para relatar explicitamente:
   - agenda lida via Reclaim oficial;
   - tarefas lidas via Google Tasks;
   - tools oficiais de task indisponiveis por upgrade.
5. Manter todos os fallbacks antigos.
6. Criar testes unitarios para o classificador de ferramentas oficiais:
   - `ok`;
   - `blocked_upgrade`;
   - `server_error`;
   - `dangerous_not_called`.

## Execution status, 2026-06-18

- Fluxo híbrido executado no código.
- `plan_day_from_tasks` chama `get_schedule` do Reclaim oficial como fonte principal da agenda e cai para Google Calendar quando o MCP oficial falha.
- O resultado do planejamento agora informa a origem da agenda, quantidade de eventos lidos via Reclaim oficial e que task tools oficiais seguem indisponiveis por upgrade.
- `plan_day_apply` relata explicitamente que nao cria eventos diretos, que a agenda vem do Reclaim oficial quando disponivel e que tarefas continuam via Google Tasks/Jarvis.
- Foram adicionados testes unitarios para classificacao `ok`, `blocked_upgrade`, `server_error` e parsing/classificacao de eventos do Reclaim oficial.
- `plan_day_apply` agora reitera a verificação real da agenda em ate 3 tentativas, detecta conflitos e eventos fora do limite normal, e marca a agenda como nao aceita quando o estado observado continua ruim.

## Riscos

- O endpoint oficial pode expor ferramentas diferentes por cliente, plano ou conta.
- O MCP pode operar em modelo de eventos/calendario mais do que em tasks Reclaim.
- Approval workflows podem exigir interacao que o Jarvis ainda nao representa bem.
- `unlock` pode continuar sem API direta.
- Migrar para Reclaim 2.0 pode mudar IDs, campos, semantica de due date e comportamento de tasks.

## Fora de escopo

- Remover Playwright/CDP.
- Remover Google Tasks como fonte do fluxo Reclaim.
- Migrar todas as tarefas para Reclaim 2.0 sem backup.
- Trocar `plan_day_apply` para criacao direta de eventos no Calendar.
