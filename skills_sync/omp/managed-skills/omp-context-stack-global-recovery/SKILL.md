---
name: omp-context-stack-global-recovery
description: "Use when Oh My Pi project mode, Jarvis, GSD, Ralph, AI Coders Context, or Graphify stack commands are missing, wrong, or installed from homonymous npm packages."
---

# Oh My Pi context stack global recovery

Use this when project-mode work is blocked by missing or wrong global CLIs for the stack: AI Coders Context, GSD, Ralph, and Graphify/Jarvis integration.

## Canonical npm packages

Install these global packages:

```bash
npm install -g @ai-coders/context get-shit-done-cc @iannuttall/ralph
```

Ralph packages that are not the expected stack Ralph and should be removed if they shadow `ralph`:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
```

## Recovery sequence

From the Jarvis repository, normally `/home/lucas/Downloads/codex_luascfl_jarvis`:

```bash
npm uninstall -g @wiggumdev/ralph @ralph-orchestrator/ralph-cli ralph-wiggum-cli rlph-cli
npm install -g @ai-coders/context get-shit-done-cc @iannuttall/ralph
cd /home/lucas/Downloads/codex_luascfl_jarvis
python3 jarvis.py context-stack-harden
python3 jarvis.py context-stack-check .
```

## Minimum validation

```bash
ai-context --version
npm list -g @ai-coders/context get-shit-done-cc @iannuttall/ralph --depth=0
command -v ralph
ralph help
python3 jarvis.py context-stack-check .
```

Expected canonical layout for projects:

- AI Coders Context: `.context/docs`
- GSD: `.context/plans`
- Ralph: `.context/workflow`
- Graphify: `.context/graphify-out`

## Important convention

Ralph is an operational discipline in this stack: one story per cycle, explicit DoD, and validation evidence. The Ralph CLI is optional. Do not block project execution merely because a specific `ralph build` command is absent, unless the user explicitly asked to run that CLI workflow.

If `context-stack-harden` corrupts a global package, fix the package and rerun the minimum validation before declaring success.
