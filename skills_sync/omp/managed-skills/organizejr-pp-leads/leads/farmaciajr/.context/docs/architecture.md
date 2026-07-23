## Architecture Notes

This workspace is a document operations project rather than a traditional software system. The architecture is a small artifact pipeline: Google Doc source -> local extraction -> structured summary -> guided updates back into the Google Doc.

## System Architecture Overview
The top-level topology is a manual-orchestrated document workflow. Meeting information is sourced from a multi-tab Google Doc, extracted through the Google Docs API, normalized into local artifacts, then written back into proposal-oriented tabs.

## Architectural Layers
- **Source layer**: Google Doc tabs (`Modelo de Ata`, `Transcrição`, `Proposta de Projeto`)
- **Extraction layer**: Python calls to the Google Docs REST API
- **Normalization layer**: `farmaciajr_lead.json`
- **Working artifact layer**: local `.txt` snapshots and proposal edits

## Detected Design Patterns
| Pattern | Confidence | Locations | Description |
| --- | --- | --- | --- |
| Source of truth + mirror | High | Google Doc + local `.txt` files | Live edits happen in Google Docs while local exports preserve recoverable snapshots. |
| Structured summary | High | `farmaciajr_lead.json` | Raw conversation is condensed into a stable dossier for downstream work. |
| Manual orchestration | High | agent-driven workflow | No daemon or app; steps are run intentionally as commercial operations. |

## Entry Points
- `farmaciajr_lead.json`
- `farmaciajr_modelo_ata.txt`
- `farmaciajr_transcricao.txt`

## Public API
| Symbol | Type | Location |
| --- | --- | --- |
| Farmácia Jr. lead dossier | JSON artifact | `farmaciajr_lead.json` |
| Ata snapshot | Text artifact | `farmaciajr_modelo_ata.txt` |
| Transcript snapshot | Text artifact | `farmaciajr_transcricao.txt` |

## Risks & Constraints
- The live Google Doc is editable and can drift from local snapshots.
- Service account access is required for direct API edits.
- Commercial recommendations must stay grounded in the transcript.

## Top Directories Snapshot
- `.context/` — context and workflow notes
- workspace root — 3 primary lead artifacts

## Related Resources
- [Project Overview](./project-overview.md)
- [Data Flow & Integrations](./data-flow.md)
