---
name: context-stack-selection
description: "Use when comparing or updating the project management/context stack across AI Coders Context, GSD, Ralph, and Graphify."
---

# Context stack selection

Use this when deciding how to manage project context with AI Coders Context, GSD, Ralph, and Graphify.

## Recommended stack

Default to **AI Coders Context + GSD + Ralph + Graphify** when the project has non-trivial code, multiple files, or architectural questions.

Use strict ownership boundaries:

| Component | Owns | Must not own |
|---|---|---|
| AI Coders Context | Canonical curated technical context in `.context/docs`; scaffolded docs structure; semantic maps and structural summaries | Backlog, current story execution, raw logs, `.context/skills`, `.context/agents`, plans, workflow runtime |
| GSD | Macro plan, milestones, phases, dependencies and decisions in `.context/plans` | Implementation detail for each story, technical docs, legacy `.planning` |
| Ralph | Execution workflow, current story/PRD, Definition of Done, validation evidence and runtime under `.context/workflow` | Architecture map, long documentation, roadmap, legacy `.context/prd_ralph`, legacy `.context/ralph`, legacy `.agents/tasks` |
| Graphify | Knowledge graph, god nodes, communities, cross-module paths and impact relations in `.context/graphify-out` | PRD, backlog, story state, roadmap, manual docs |

## Canonical folder model

```text
.context/
  docs/          # AI Coders Context
  plans/         # GSD
  workflow/      # Ralph
  graphify-out/  # Graphify generated outputs
```

Questions each folder answers:

- `.context/docs`: what the system is.
- `.context/plans`: where the system is going.
- `.context/workflow`: what is being executed now.
- `.context/graphify-out`: how modules connect in the extracted graph.

## Jarvis permanent hardening procedure

For Lucas's restricted stack in `/home/lucas/Downloads/codex_luascfl_jarvis`, the durable enforcement point is `jarvis.py`.

Run this after installing, reinstalling, or updating `@ai-coders/context`, `get-shit-done-cc`, `@iannuttall/ralph`, or Graphify:

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
python3 jarvis.py context-stack-harden
```

For a full sync after hardening:

```bash
python3 jarvis.py context-stack-harden && python3 jarvis.py mcp-sync-clients
```

To audit this layout in one or more repositories:

```bash
python3 jarvis.py context-stack-check /path/to/repo
python3 jarvis.py context-stack-check /path/to/parent --recursive
```

## What `context-stack-harden` must enforce

1. **AI Coders Context docs policy**
   - It may create and maintain `.context/docs`.
   - `init` is forced to docs mode even if `both`, `agents`, or `skills` is requested.
   - `sync` forces `skipAgents: true` and `skipSkills: true`.
   - CLI and MCP skill write actions are blocked: scaffold/fill/export/import.
   - MCP schemas expose only skill read actions: list/getContent/getForPhase.
   - `workflow_stack(context_refresh)` creates `.context/docs` and removes `.context/agents` and `.context/skills`.

2. **GSD planning path policy**
   - Replace legacy `.planning` and `.context/docs/planning_gsd` with `.context/plans` in the global `get-shit-done-cc` package.

3. **Ralph workflow policy**
   - Use `.context/workflow/prd.json` instead of `.agents/tasks/prd.json` or `.context/prd_ralph/prd.json`.
   - Runtime files belong under `.context/workflow/ralph`.
   - Sync or validate Ralph templates under the global package.
   - Patch template resolution so incomplete local `.agents/ralph` folders do not override the global template unless `loop.sh` exists.

4. **Graphify output policy**
   - Use `.context/graphify-out`, never root-level `graphify-out`.
   - For large graphs, skip HTML above 5,000 nodes and use fast source-path communities above 50,000 nodes.

## Verification commands

```bash
cd /home/lucas/Downloads/codex_luascfl_jarvis
.venv-super/bin/python3 -m py_compile jarvis.py
.venv-super/bin/python3 -c 'import jarvis, json; r=jarvis._run_internal_smoke_test_step(); print(json.dumps(r, ensure_ascii=False)); raise SystemExit(0 if r.get("ok") else 1)'
python3 jarvis.py context-stack-check .
```

Expected smoke keys all true:

- `ai_coders_context_global_installed`
- `gsd_global_installed`
- `gsd_plans_path_patched`
- `ralph_global_installed`
- `ralph_global_templates_ready`
- `ralph_template_resolution_patched`
- `ralph_prd_path_patched`
- `graphify_context_output_patched`
- `.context/docs`
- `.context/plans`
- `.context/workflow`
- `.context/graphify-out`

## Ranking heuristic

For context management, rank combinations as:

1. AI Coders Context + GSD + Ralph + Graphify
2. AI Coders Context + GSD + Ralph
3. AI Coders Context + Ralph + Graphify
4. GSD + Ralph + Graphify
5. AI Coders Context + GSD + Graphify
6. AI Coders Context + Ralph
7. AI Coders Context + Graphify
8. AI Coders Context + GSD
9. Ralph + Graphify
10. GSD + Graphify
11. AI Coders Context
12. GSD + Ralph
13. Graphify
14. Ralph
15. GSD

This ranking is a heuristic. It optimizes for canonical context, code structure, execution continuity, macro planning, drift control, and operational overhead.

## Decision check

Use the full stack only if roles stay separate. If the prompt makes every tool read and write every kind of context, reduce scope. The failure mode is duplicated context and stale competing sources of truth.
