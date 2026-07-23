---
status: planned
generated: 2026-06-06
docs:
  - "tooling.md"
phases:
  - id: "phase-1"
    name: "DOM discovery"
  - id: "phase-2"
    name: "Action implementation"
  - id: "phase-3"
    name: "Planning integration"
  - id: "phase-4"
    name: "Validation"
---

# Reclaim task actions integration plan

## Objetivo

Integrar ações avançadas do Reclaim ao planejamento diário: `Send to Up Next`, `Restart`, `Set priority`, `Due date` e `Snooze`, usando Chrome/CDP e DOM validável, sem depender de `xdotool` como automação primária.

## Decisão técnica

- Usar o Chrome com `.ralph/reclaim_playwright_profile`, CDP em `127.0.0.1:9222` e DOM do planner já aberto.
- Manter LibreWolf apenas como fallback assistido para login/captcha.
- Toda ação por tarefa deve localizar a menor região DOM que contenha o título alvo e o controle desejado.
- Nenhuma ação é considerada concluída sem validação observável no DOM ou em sincronização posterior do Reclaim/Calendar.

## Fase 1, descoberta DOM

1. Capturar HTML real dos controles:
   - `Send to Up Next`, botão já conhecido: `button[aria-label="Send to Up Next"]`.
   - `Restart`, no topo/OmniBar ou no estado ativo da tarefa.
   - `Set priority`, dentro do menu `more-menu` ou controle de prioridade visível.
   - `Due date`, dentro do menu `more-menu` ou popover de data.
   - `Snooze`, dentro do menu `more-menu`.
2. Para cada controle, registrar:
   - seletor estável;
   - texto visível do menu/popup;
   - confirmação DOM esperada após a ação;
   - fallback assistido quando o seletor mudar.

## Fase 2, implementação das ações

Adicionar ações ao worker CDP:

- `up_next(title)`: clicar `Send to Up Next` no bloco da tarefa alvo e validar mudança no contador/lista `Up Next`.
- `restart(title)`: localizar a tarefa ativa/OmniBar e clicar o controle de restart/retomar; validar `Now:` ou `In progress`.
- `set_priority(title, priority)`: abrir `more-menu`, selecionar prioridade e validar mudança visual do indicador de prioridade.
- `set_due_date(title, date)`: abrir `more-menu`, selecionar/editar due date e validar `Next:` ou data exibida no item.
- `snooze(title, preset_or_datetime)`: abrir `more-menu`, escolher snooze e validar que a tarefa saiu do bloco atual ou mudou seu `Next:`.

## Fase 3, integração com planejamento

Atualizar o planner para usar essas ações como decisões operacionais:

- Tarefa escolhida para agora: `Send to Up Next` antes de `Start`, quando não estiver no topo.
- Tarefa interrompida mas ainda importante: `Snooze` para o próximo bloco realista.
- Tarefa antiga sem decisão: perguntar antes de mudar priority/due date.
- Tarefa que virou compromisso do dia: ajustar `due date` e prioridade no Reclaim, não só no Google Tasks.
- Tarefa urgente do dia: subir prioridade e mandar para `Up Next`.

## Fase 4, validação

Validar com cenários reais e pequenos:

1. `Send to Up Next` em uma tarefa não ativa, confirmação pelo contador/lista `Up Next`.
2. `Restart` em uma tarefa pausada/ativa, confirmação por `Now:` ou `In progress`.
3. `Set priority`, confirmação pelo indicador visual da tarefa.
4. `Due date`, confirmação por texto de data ou `Next:` atualizado.
5. `Snooze`, confirmação por mudança de `Next:` ou remoção do bloco atual.

## Riscos

- Menus do Reclaim usam classes dinâmicas, então seletores devem priorizar `aria-label`, texto visível e relação com o bloco da tarefa.
- Alguns estados aparecem no calendário antes do DOM da lista, então validação precisa distinguir agendamento de execução real.
- `Restart` e `Snooze` dependem de DOM ainda não capturado. Não implementar como confiável antes de coletar HTML desses popovers.
