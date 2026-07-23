## Testing Strategy

Quality here is validated through artifact integrity and post-write verification rather than unit tests.

## Test Types
- **Source validation**: confirm claims against `farmaciajr_transcricao.txt`
- **Write verification**: re-read the edited Google Doc tab after every write
- **Artifact consistency**: ensure `farmaciajr_lead.json` aligns with the transcript and ata

## Running Tests
- Read the relevant Google Doc tab after `batchUpdate`
- Compare expected section text with the returned tab content

## Quality Gates
- No unsupported commercial claim
- No stale recommendation after lead direction changes
- Every major doc edit verified by a post-write read
