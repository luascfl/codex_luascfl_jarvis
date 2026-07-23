## Project Overview

This temporary workspace supports commercial discovery and proposal shaping for the Farmácia Jr. lead. It stores the raw transcript, the filled meeting minutes, and a structured summary used to drive follow-up proposal design in Google Docs.

> **Detailed Analysis**: This workspace is document-first, not application-first. `codebase-map.json` has limited value because the repository here is mostly artifacts instead of source modules.

## Quick Facts
- Root: `/home/lucas/Downloads/codex_latex_organizejr/tmp_farmaciajr`
- Primary artifacts: JSON and TXT
- Primary working surface: Google Docs with tab-level editing
- Main local entry points: `farmaciajr_lead.json`, `farmaciajr_modelo_ata.txt`, `farmaciajr_transcricao.txt`

## Entry Points
- `farmaciajr_lead.json` — normalized lead brief with diagnosis, evidence, and recommendation
- `farmaciajr_modelo_ata.txt` — exported reference for the meeting minutes tab
- `farmaciajr_transcricao.txt` — exported reference for the transcript tab

## Key Exports
- No code exports. This workspace exports decision artifacts and source material for commercial follow-up.

## File Structure & Code Organization
- `.context/docs/` — local project context and planning notes
- `farmaciajr_lead.json` — structured lead dossier
- `farmaciajr_modelo_ata.txt` — ata snapshot
- `farmaciajr_transcricao.txt` — transcript snapshot

## Technology Stack Summary
The workspace uses Google Docs as the live editing surface and Python scripts against the Google Docs API as the execution path. Local files act as checkpoints and recovery artifacts.

## Getting Started Checklist
1. Read `farmaciajr_lead.json` for the current commercial understanding.
2. Use `farmaciajr_transcricao.txt` when validating claims against the meeting.
3. Use the Google Doc tabs as the live surface for the ata and proposal.
4. Update this context when the lead status, scope, or proposal direction changes.
