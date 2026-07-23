## Data Flow & Integrations

Data enters this workspace from a Google Doc that contains multiple tabs for the same lead interaction. The transcript is read, the ata is updated, and proposal content is written back into its own tab.

## Module Dependencies
- **Google Docs API** -> source and sink for live lead artifacts
- **Python helper script** -> authentication, reads, and writes
- **Local JSON/TXT artifacts** -> persistence and validation layer

## Service Layer
- Google token generation via service account JWT
- `documents.get?includeTabsContent=true` for reads
- `documents.batchUpdate` for tab creation and tab content edits

## High-level Flow
1. Read Google Doc tabs.
2. Extract transcript and ata text.
3. Normalize insights into `farmaciajr_lead.json`.
4. Draft or revise commercial content.
5. Write changes back into the relevant Google Doc tab.
6. Re-read the tab to verify the final content.

## External Integrations
- **Google Docs API** — live document read/write
- **Google OAuth token endpoint** — service account token exchange

## Observability & Failure Modes
- Failed token exchange blocks all operations.
- Missing tab IDs or stale end indexes break writes.
- Verification requires a post-write read of the edited tab.
