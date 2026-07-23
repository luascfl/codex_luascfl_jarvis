---
name: omp-execution-mode-guidance
description: "Use when explaining or adding Oh My Pi execution-mode guidance for normal, goal, loop, timeboxed goal work, compaction autoContinue, prewalk, plan-yolo, orchestrate, workflowz, or vibe in a project prompt."
---

## Origem
Consolidada a partir do prompt canônico `/home/lucas/.omp/agent/prompts/projeto.md`.

## Escopo
Use quando Lucas perguntar como escolher entre modos de execução do Oh My Pi, ou pedir para adicionar orientação sobre esses modos ao prompt do projeto.

Mantenha apenas esta skill para orientação de modos OMP. Não crie skills separadas para `goal`, `/loop`, timebox ou `/vibe`; atualize esta skill quando houver nova evidência durável.

## Regra central
Trate modos do Oh My Pi como mecânica de sessão, não como fonte de verdade do projeto. Eles não substituem contexto oficial, PRD, DoD, validação, Graphify, GSD, Ralph nem workflow específico do repositório.

## Hierarquia recomendada

- Modo normal: uma story, uma tarefa comum ou uma correção limitada, com validação observável.
- `goal`: objetivo longo, verificável e com critério de conclusão. Use para melhoria contínua, trabalho longo sem novo input ou objetivo que precisa de julgamento. Só marque completo após evidência real.
- Timebox real de `goal`: prefira limite externo da sessão, por exemplo `omp --max-time=30m`. Tempo escrito dentro de `/goal set ...` é só intenção, não garantia técnica.
- `/loop`: repetidor mecânico do próximo prompt depois de cada turno. Use só para ciclos repetitivos, limitados e com próxima unidade clara. Não use como backlog, estratégia ampla ou substituto de `goal`.
- `goal` + `/loop`: não recomende como padrão. É tecnicamente possível manter um goal ativo enquanto `/loop` repete prompt, mas o loop vira o motor e o goal vira quase só contexto.
- `loop.mode`: controla apenas o intervalo do `/loop`: `prompt` reenfileira o mesmo prompt, `compact` compacta antes de reenviar e `reset` limpa/reinicia a sessão antes de reenviar.
- `compaction.autoContinue`: continuidade de contexto após compactação automática bem-sucedida. Não cria tarefa, backlog, estratégia ou objetivo novo.
- `prewalk`: bom quando o modelo forte deve planejar e a execução restante pode ir para `@smol` no próximo edit/write. Não use quando a execução ainda exige julgamento contínuo.
- `plan-yolo`: estado de lançamento para planejar, autoaprovar e depois executar. Não confundir com estratégia de projeto.
- `orchestrate`: paralelismo por subagentes independentes. O agente principal faz escopo, contratos e consolidação.
- `workflowz`: fluxo multiagente determinístico, útil para pesquisa ampla, revisão, migração ou cobertura com barreiras e verificação final centralizada.
- `/vibe`: modo diretor sobre workers persistentes `fast` e `good`. Enquanto `/vibe` está ativo, o diretor não deve editar, rodar comandos, pesquisar, compilar ou grepar diretamente; deve usar `read` e as ferramentas de vibe para coordenar workers.

## Vibe mode

Fatos duráveis sobre `/vibe`:

- O agente principal vira diretor.
- O toolset do diretor fica limitado a `read`, `vibe_spawn`, `vibe_send`, `vibe_wait`, `vibe_kill` e `vibe_list`.
- Use `fast` para trabalho mecânico, pequeno, bem especificado e de baixa latência.
- Use `good` para design, debug difícil, refatoração multi-arquivo e decisões com julgamento.
- Faça um worker por workstream independente.
- O brief do worker deve ser completo, porque ele começa sem histórico da conversa.
- Continue a mesma sessão por workstream, em vez de respawnar sem necessidade.
- Verifique claims dos workers por `read` antes de construir em cima do resultado.
- Mate workers concluídos ou travados.

## Templates prontos

### Goal com timebox real

```bash
omp --max-time=30m
```

Depois, dentro da sessão:

```text
/goal set Usar AGENTS.md, .context/docs, .context/docs/planning_gsd/STATE.md, .context/prd_ralph/README.md, .context/prd_ralph/prd.json quando existir e graphify-out/GRAPH_REPORT.md para escolher e executar a próxima melhoria segura do projeto. Trabalhe uma story Ralph por ciclo; se faltar milestone ou story, faça o bootstrap mínimo antes; use Graphify para impacto e relações entre módulos; implemente no máximo uma mudança coesa por turno; valide com comando real ou smoke test; rode graphify update . após alterar código; atualize o contexto no fechamento; pare e reporte bloqueio se não houver ação segura.
```

### Loop seguro sem goal

```text
/loop {tempo}
Execute a próxima unidade mecânica da fila já definida. Não escolha nova estratégia; não abra backlog paralelo; não mude escopo; processe no máximo um item claro por turno; valide o resultado da unidade; rode graphify update . se alterar código; pare se não houver próximo item objetivo.
```

### Texto para prompt do projeto

```md
## Modos de execução Oh My Pi
- Trate modos do Oh My Pi como mecânica de sessão, não como fonte de verdade do projeto. Eles não substituem o contexto oficial, PRD, DoD nem validação.
- Padrão: execute no modo interativo normal para uma story ou tarefa comum, com validação observável.
- Goal mode: use para objetivo longo e verificável. Para timebox real, prefira limite externo da sessão, por exemplo `omp --max-time=30m`. Só marque completo após evidência real.
- Loop, loop.mode e compaction auto-continue: `/loop` repete o próximo prompt depois de cada turno; use só para ciclos mecânicos com limite claro, não para objetivos amplos. `loop.mode` controla esse intervalo: `prompt` reenfileira o mesmo prompt, `compact` compacta antes de reenviar e `reset` limpa/reinicia a sessão antes de reenviar. `compaction.autoContinue` só agenda retomada interna após compactação automática pós-turno bem-sucedida; não é backlog.
- Prewalk: use quando um modelo forte deve planejar e a execução restante pode ir para `@smol` no próximo edit/write. Não use quando a execução exigir julgamento contínuo.
- Vibe mode: use para dirigir workers `fast` e `good`; não edite nem execute diretamente no modo diretor.
- Ao sugerir um modo, recomende o menor mecanismo suficiente.
```

## Verificação

Depois de editar um prompt:

1. Releia a seção alterada.
2. Procure os termos centrais: `Goal mode`, `/loop`, `loop.mode`, `compaction.autoContinue`, `prewalk`, `vibe`, `--max-time`.
3. Confirme que não houve criação de skill duplicada sobre o mesmo tema.
4. Confirme que não ficaram artefatos temporários em `tmp/`, `/tmp/` ou no diretório atual sem relação clara com o projeto.

## Fontes primárias a revalidar quando houver dúvida

- `omp --help`, para confirmar `--max-time`.
- `omp config get loop.mode`.
- `omp config get compaction.autoContinue`.
- `packages/coding-agent/src/modes/loop-limit.ts`, para `/loop [count|duration]`.
- `packages/coding-agent/src/modes/interactive-mode.ts`, para runtime do loop e interação com goal.
- `packages/coding-agent/src/config/settings-schema.ts`, para `loop.mode`.
- `packages/coding-agent/src/prompts/system/auto-continue.md`, para compaction continuation.
- `packages/coding-agent/src/slash-commands/builtin-registry.ts`, para `/prewalk`.
- `packages/coding-agent/src/prompts/system/vibe-mode-active.md`, `packages/coding-agent/src/tools/vibe.ts` e `packages/coding-agent/test/interactive-mode-vibe-toggle.test.ts`, para `/vibe`.
