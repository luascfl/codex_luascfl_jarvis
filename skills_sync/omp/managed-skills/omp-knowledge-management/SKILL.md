---
name: omp-knowledge-management
description: "Rules for creating, listing, moving, downgrading skills, and fixing duplicated prompts within OMP profiles and directories."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_jarvis`

# Oh My Pi Knowledge Management (Skills & Prompts)

This document consolidates rules for creating, listing, moving, and downgrading managed skills and prompts within Oh My Pi (OMP) ecosystems.

## 1. Creating and Listing Managed Skills

**Creation (Origin Tracking):**
The system does not track skill origins natively. When using `manage_skill` to `create`:
1. Infer origin by searching `~/Downloads` for relevant keywords.
2. If unknown, ask the user.
3. Inject `## Origem` at the top of the `body` (e.g., `Criada a partir do contexto: /absolute/path`).

**Hard Enforcement:**
- Never call `manage_skill` with `action="create"` unless the `body` starts with `## Origem`.
- Never call `manage_skill` with `action="update"` on a managed skill that lacks `## Origem`; add it in the same update.
- If the origin is unknown, stop and ask the user before creating the skill, instead of writing `Desconhecida` into a newly created managed skill.
- `Desconhecida (Skill Antiga/Legado)` is only acceptable for old skills discovered during listing, never for new managed skills.

**Listing ("quais skills eu tenho?"):**
Do NOT just spit out folder names. Map ALL skills across ecosystems:
1. `~/.omp/agent/managed-skills/`
2. `~/.omp/agent/skills/` and `~/.omp/skills/`
3. `~/.agents/skills/`
4. `~/.gemini/skills/`
5. `~/.codex/skills/`
6. `./.omp/skills/`
- Output a markdown table with: **Name**, **Installation Path**, and **Origin** (read from `SKILL.md`). Warn if conflicts exist.
- **Merge Indicator (Grouping):** Always count and group how many skills exist for each origin folder. If an origin folder has multiple skills, highlight this list to the user as a strong indicator that those skills are candidates to be merged.
  - **Exception:** Do not flag skills with origin "Global" or "Desconhecida" as merge candidates.
  - **Performance & Over-merging Check:** Grouping by origin is an indicator, NOT a mandate. Before proposing a merge, evaluate the AI context performance. Does merging them create a highly cohesive skill, or a bloated "Frankenstein" skill that pollutes the prompt? If the origin contains distinct operational domains (e.g., coding/PRD rules vs. browser DOM automation vs. data forensics), it is better to categorize them into separate, well-defined skills to preserve context relevance.


**Single Canonical Location Rule:**
- If a skill exists in `~/.omp/agent/managed-skills/`, the same skill name MUST NOT exist in `~/.codex/skills/`, `~/.gemini/skills/`, or `~/.claude/skills/`.
- When converting a Codex/Gemini/Claude skill into a managed skill, first preserve the full content, then remove the provider copy, then create or restore the managed skill.
- After every conversion or cleanup, explicitly verify that no managed skill name remains duplicated in Codex, Gemini, or Claude.
- If the provider copy is a symlink, unlink only the symlink entry and never delete the target unless the user explicitly asks.

## 2. Scope Downgrade ("Transferir a skill pra cá")

When the user asks to "transferir a skill pra cá" (Scope Downgrade):
1. **Read:** Read the `SKILL.md` of the specified global skill.
2. **Dump:** Save the content to `CONTEXTO_SKILL.md` or `INSTRUCOES.md` in the current working directory.
3. **Delete:** Immediately use `manage_skill action="delete"` to remove the global managed skill so it only lives locally.

## 3. Merging Skill into Prompt (`projeto.md`)

When asked to move a skill into the `projeto` prompt:
1. Read the skill (`~/.omp/agent/managed-skills/<name>/SKILL.md`) and the prompt (`~/.omp/agent/prompts/projeto.md`).
2. Merge ONLY durable operational content into the prompt (skip frontmatter/origin/fluff).
3. Verify the prompt contains the new rules.
4. Delete the managed skill using `manage_skill action="delete"`.
5. Report the updated prompt and confirm skill deletion.

## 4. Prompt Duplicate Triage

If OMP Extension Control Center shows duplicate prompts (e.g., `projeto` and `prompts:projeto`):
1. Search narrowly: `~/.omp/agent/prompts/*projeto*.md` and `~/.codex/prompts/*projeto*.md`. Note that files with `:` may require Python `Path` to read/delete properly.
2. Hash check: Compare `SHA-256` hashes of duplicates.
3. Cleanup: 
   - Keep `~/.omp/agent/prompts/projeto.md` as canonical.
   - Delete duplicates like `prompts:projeto.md` or `~/.codex/prompts/projeto.md` if hashes match.
   - Merge orphan skills before deletion if needed.

## 5. Profile Visibility & Migration

**Visibility Issue:** 
Named profiles (`--profile <name>`) isolate OMP state to `~/.omp/profiles/<name>/agent/...`. They do NOT inherit from `~/.omp/agent/...`. External provider skills (like `~/.codex/skills`) remain visible globally, but OMP managed skills do not.

**Moving Skills Between Profiles:**
1. Identify source and destination roots.
2. Copy skill directories to the destination.
3. Verify integrity (confirm existence and compare `SKILL.md` hashes).
4. ONLY after exact verification, delete the source directories.
5. Report the migration counts.
