## Tooling & Productivity Guide

This workspace depends on lightweight tooling rather than a full application toolchain.

## Required Tooling
- Python with `requests` and `PyJWT`
- Google Docs API access via local service account
- Local file reads/writes for checkpoint artifacts

## Recommended Automation
- Keep transcript and ata snapshots locally after major edits.
- Prefer full-tab overwrite only when structure is simpler than surgical edits.
- Always pair write operations with verification reads.

## Productivity Tips
- Use the transcript file for quote hunting instead of repeatedly hitting the live doc.
- Keep one structured JSON summary (`farmaciajr_lead.json`) as the operational source of truth for the lead.
