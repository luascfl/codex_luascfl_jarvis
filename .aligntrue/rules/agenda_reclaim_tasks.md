# Politica de agenda, Reclaim e Google Tasks

Regra global para operar MCPs de planejamento de dia, Reclaim, Google Tasks e Google Calendar.

Always applied. For files: `**/*`.

# Politica de agenda, Reclaim e Google Tasks

Use estas regras quando o usuario pedir planejamento do dia, captura de tarefas, revisao GTD, operacoes no Reclaim, Google Tasks ou Google Calendar.

## Modelo mental

- `Minhas tarefas` no Google Tasks e inbox manual de captura pelo celular, sem parametros e sem sincronizacao direta com agenda ou Reclaim.
- A lista do Reclaim contem tarefas que devem entrar no fluxo de agenda e precisam estar com parametros completos.
- Google Calendar deve ser afetado pelo Reclaim, nao por edicao direta de eventos, salvo quando o usuario pedir explicitamente uma operacao de calendario.
- Se uma tarefa do Google Tasks/Reclaim aparece sem due date visivel, trate como sincronizada internamente pelo Reclaim para hoje. Nao corrija manualmente apenas por ausencia de due date.
- Revise Reclaim e `Minhas tarefas` juntos para aplicar boas praticas de GTD: proximo passo claro, bloqueios visiveis, contexto atualizado e duracao plausivel.

## Planejamento do dia

- Quando o usuario disser "planeje meu dia", gere apenas simulacao com `plan_day_from_tasks` e leia as duas fontes, Reclaim e `Minhas tarefas`.
- Inclua tarefas atrasadas na simulacao para validacao do usuario.
- Separe visualmente tarefas prontas para executar, tarefas ambiguas, tarefas atrasadas e tarefas que precisam de update na descricao.
- Sugira ajustes de GTD quando fizer sentido: reescrever descricao, quebrar tarefa grande, corrigir duracao, adicionar bloqueio ou registrar contexto.
- Quando nao couber tudo no dia, use uma mistura GTD: proximo passo claro primeiro, depois due date, prioridade, desbloqueio e energia/contexto.
- Horario normal: 08:00 a 22:30.
- Se o usuario disser "vou madrugar" ou equivalente, planeje a partir do horario atual, sem esperar o proximo bloco diurno.
- O calendario e o Reclaim consideram pomodoro de 45 min de foco e 15 min de intervalo. Considere esse intervalo no planejamento sem necessariamente criar uma tarefa explicita para ele.

## Aplicacao do plano

- Quando o usuario disser "aplica o plano", "coloca na agenda" ou equivalente, pode aplicar direto via Reclaim com `plan_day_apply`, sem nova confirmacao.
- Depois de aplicar o plano, sempre verifique eventos locked com `gcal_find_locked_events`.
- Se houver conflito percebido entre Calendar e tarefa planejada, sugira rearranjo. O Reclaim normalmente ja considera o Calendar para evitar sobreposicao.
- Se houver conflito entre GTD e comando explicito do usuario, aponte o conflito e siga o comando do usuario.

## Captura e criacao de tarefas

- Quando o usuario pedir para adicionar uma tarefa, crie no Reclaim, nao em `Minhas tarefas`.
- Ao criar tarefa no Reclaim, inclua parametros obrigatorios no titulo: contexto, duracao, prioridade, tipo e due date.
- Tipo padrao: `work`.
- Prioridade padrao: `P2` quando nao houver sinal melhor.
- Contexto e duracao devem ser inferidos pela tarefa. Pergunte quando a inferencia for fraca.
- Tarefa sem data pode usar o padrao do Reclaim, que sincroniza internamente para hoje, mas nao invente data quando isso mudar a intencao do usuario.
- Para varias tarefas em texto livre, crie todas no Reclaim com `gtasks_smart_sync_add_reclaim`.
- Se a tarefa for ambigua, pergunte antes de criar.
- As notas da tarefa devem sempre conter estrutura, preenchendo o que existir e deixando claro o que falta:

```md
Bloqueios:
- ...

Updates:
- ...

Contexto:
- ...

Plano de acao:
- ...
```

## Duracao, pomodoro e split

- Duracao minima padrao: 15 min.
- Pode usar duracoes de 15, 30, 45 min ou multiplos maiores conforme a tarefa.
- Tarefas maiores devem ser pensadas em blocos de 45 min com intervalo de 15 min.
- Quando uma tarefa parecer grande demais, prefira sugerir quebra em tarefas menores ou usar o parametro de split do Reclaim quando disponivel.

## Revisao e atualizacao GTD

- Quando o usuario trouxer contexto novo durante a revisao, atualize automaticamente a descricao da tarefa quando houver ferramenta disponivel.
- Se nao houver ferramenta para editar descricao/notas existentes, gere o texto pronto para colar ou recrie a tarefa apenas quando isso for seguro.
- Para tarefas ambiguas em `Minhas tarefas`, pode inferir e promover para Reclaim quando o proximo passo parecer claro.
- Em duplicata entre `Minhas tarefas` e Reclaim, o Reclaim vence.
- Pode completar ou deletar tarefas do Google Tasks quando forem claramente duplicadas ou concluidas. Use criterio conservador: nunca delete tarefa ambigua.
- Pode corrigir prioridade errada automaticamente com `reclaim_task_set_priority`.

## Rotinas semanais

- Para rotinas semanais, use `gtasks_create_weekly_series` apenas depois de perguntar ate quando criar a serie.
- Explique que a ferramenta cria tarefas individuais por semana, porque esse fluxo nao depende de recorrencia nativa do Reclaim a partir de Google Tasks.

## Acoes do Reclaim

- Use `reclaim_next_task` quando o usuario perguntar "o que faco agora", depois de planejar o dia ou depois de concluir uma tarefa.
- Quando o usuario disser "terminei X", pode concluir direto com `reclaim_task_done`.
- Quando o usuario disser "comecar X agora", use `reclaim_task_start`.
- `reclaim_task_restart` e apenas para reiniciar tarefa.
- Quando o usuario disser "parar tarefa atual", pode usar `reclaim_task_stop`.
- Use `reclaim_task_snooze` somente quando o usuario explicitar que concluiu algo agora, mas precisa revisitar o problema ou tarefa depois de um periodo.
- Use `reclaim_task_up_next` para colocar uma tarefa simples ou importante como proxima execucao, preservando a intencao de fazer logo.
- Use `reclaim_event_unlock` para desbloquear via evento no calendario quando a tarefa estiver bloqueada ou locked no Reclaim. Nao confunda com edicao direta de tarefa.
- Se a tarefa ainda nao apareceu no DOM do Reclaim por sincronizacao pendente, aguarde a sincronizacao em vez de tentar acionar ferramentas do Reclaim sobre algo invisivel na UI.

## Frases gatilho

- "planeje meu dia" significa simular com `plan_day_from_tasks`, sem aplicar.
- "aplica o plano" ou "coloca na agenda" significa aplicar via `plan_day_apply` e depois verificar locked events.
- "o que faco agora?" significa consultar `reclaim_next_task`.
- "terminei X" significa concluir X no Reclaim.
- "comecar X agora" significa iniciar X com `reclaim_task_start`.
- "parar tarefa atual" significa parar com `reclaim_task_stop`.
- "toda terca fazer X" significa perguntar ate quando criar a serie antes de usar `gtasks_create_weekly_series`.
