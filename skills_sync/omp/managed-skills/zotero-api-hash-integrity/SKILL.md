---
name: zotero-api-hash-integrity
description: "Tratamento de integridade WebDAV (hashes SHA-256) e erros de API (Pyzotero 412 Precondition Failed, Read-only fields)."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_zotero/zotero_sync_webdav`

# Zotero Api Hash Integrity

## pyzotero-delete-with-version

## Problem

`zot.delete_collection(payload)` uses optimistic locking.
The payload must include the current live `version` from the collection object.
If you pass `0`, `None`, or an outdated version, Zotero rejects the delete.

## Correct pattern

1. Fetch the live collection objects first.
2. Keep the `version` field from each collection.
3. Build the delete payload with both:
   - `key`
   - `version`
4. Call `zot.delete_collection({'key': key, 'version': version})`.
5. Treat `204 No Content` as success.

## Symptom

Wrong payload example:
- `{'key': 'IURKP4DI', 'version': 0}`

Typical failure:
- `HTTP 412 Precondition Failed`
- `expected 0, found 50171`

## Verification

- Re-fetch collections after deletion.
- Confirm the deleted key is absent.
- If the collection had a mirrored empty drive folder, remove that empty folder afterwards.

## Notes

- This matters especially in cleanup helpers that transform fetched collection data into internal payloads. Preserve the live `version` in that internal model if later delete operations depend on it.
- The same optimistic-locking idea applies beyond collections whenever the API expects `If-Unmodified-Since-Version` semantics.

---

## zotero-api-readonly-fields

## Error Pattern
```
Invalid keys present in item N: lastRead
```

## Solution

Filter read-only fields before calling `zot.update_item()`:

```python
# Fields to REMOVE (Zotero rejects these)
readonly_fields = {'lastRead', 'dateAdded', 'dateModified', 'library'}

# Fields to KEEP (required for optimistic locking)
# - key: identifies the item
# - version: prevents concurrent modification conflicts

filtered_data = {k: v for k, v in item_data.items() if k not in readonly_fields}
zot.update_item(filtered_data)
```

## Why This Happens

- `lastRead`: Internal field tracking reading progress in Zotero UI
- `dateAdded`, `dateModified`: Managed by Zotero server
- `library`: Read-only metadata about item's library

## Critical Notes

1. **NEVER filter `key` or `version`** - these are required for the update to work
2. The error message only shows the first invalid field (e.g., `lastRead`), but multiple may be present
3. This applies to all item types, not just attachments

## Common Workflow

```python
def update_zotero_item_safe(zot, item_data):
    """Update Zotero item, filtering out read-only fields."""
    readonly_fields = {'lastRead', 'dateAdded', 'dateModified', 'library'}
    filtered_data = {k: v for k, v in item_data.items() if k not in readonly_fields}
    return zot.update_item(filtered_data)
```

---

# Zotero Sync Operation Order

**Critical**: Sync operations must happen in the correct order to avoid data issues.

## Wrong Order (causes problems)
```
1. Collect Zotero attachments
2. Process PDFs one by one (imports new during loop)
3. Rename during processing
4. No folder deduplication
```

## Correct Order
```
1. DEDUPLICATE FOLDERS (merge duplicate folders, keep one with most PDFs)
2. RENAME FILES (canonical names based on metadata)
3. IMPORT NEW ATTACHMENTS (only after organization is complete)
```

## Why This Matters

- Importing before organizing creates duplicate attachments
- Renaming during import causes API conflicts
- Folder duplicates confuse collection membership
- The script currently uses the WRONG order and needs restructuring

---

## zotero-recoverable-hash-skip-repair

## What this means

The counter may include the same PDF twice:

- once in the main drive-to-Zotero comparison path
- once in the final `ZOT->DRIVE` hash index path

So `Hash skips recuperáveis: 32` can mean 16 unique slow WebDAV PDFs.

## Procedure

1. Extract the skipped full paths from the latest successful run:

```bash
python3 - <<'PY'
import subprocess, re
r = subprocess.run(
    ['journalctl', '--user', '-u', 'zotero-sync.service', '--since', '30 minutes ago', '--no-pager'],
    text=True,
    capture_output=True,
)
paths = []
for line in r.stdout.splitlines():
    m = re.search(r'Hash skip recuperável durante índice final: (/.+)$', line)
    if m and m.group(1) not in paths:
        paths.append(m.group(1))
print('unique_paths', len(paths))
for p in paths:
    print(p)
PY
```

2. Verify the files are actually readable with a longer timeout before changing cache. A previous confirmed case showed files up to ~318 MiB reading successfully but taking 30 to 76 seconds on the first WebDAV pass.

3. Prime the Zotero sync hash cache with full SHA-256 values, not prefixes. Never write truncated hashes. Cache file:

```text
~/.cache/zotero_sync_webdav/hash_cache.json
```

Cache entry schema:

```json
{
  "hash": "<full 64-char sha256>",
  "size": <st_size>,
  "mtime_ns": <st_mtime_ns>
}
```

Safe cache writer template:

```bash
python3 - <<'PY'
import json, os, hashlib, signal
from datetime import datetime, timezone

paths = [
    # paste full paths extracted from journal here
]

class Timeout(Exception):
    pass

def handler(signum, frame):
    raise Timeout()

signal.signal(signal.SIGALRM, handler)
cache_file = os.path.expanduser('~/.cache/zotero_sync_webdav/hash_cache.json')
try:
    with open(cache_file, encoding='utf-8') as f:
        payload = json.load(f)
        entries = payload.get('entries') if payload.get('version') == 1 else {}
        if not isinstance(entries, dict):
            entries = {}
except FileNotFoundError:
    entries = {}

updated = 0
for p in paths:
    st = os.stat(p)
    signal.alarm(120)
    h = hashlib.sha256()
    try:
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
    finally:
        signal.alarm(0)
    entries[os.path.abspath(p)] = {
        'hash': h.hexdigest(),
        'size': st.st_size,
        'mtime_ns': st.st_mtime_ns,
    }
    updated += 1
    print('cached', updated, p)

os.makedirs(os.path.dirname(cache_file), exist_ok=True)
with open(cache_file, 'w', encoding='utf-8') as f:
    json.dump(
        {'version': 1, 'updated': datetime.now(timezone.utc).isoformat(), 'entries': entries},
        f,
        ensure_ascii=True,
        indent=2,
    )
print('updated_entries', updated, 'total_entries', len(entries))
PY
```

4. Verify with a real service run:

```bash
systemctl --user reset-failed zotero-sync.service
systemctl --user start zotero-sync.service
systemctl --user show zotero-sync.service --property=Result,ExecMainStatus,ActiveState,SubState --no-pager
journalctl --user -u zotero-sync.service --since '10 minutes ago' --no-pager | python3 - <<'PY'
import sys
for line in sys.stdin:
    if any(k in line for k in ['Erros:', 'Hash skips recuperáveis:', 'Bloqueios anti-duplicata:', 'Processamento concluído!']):
        print(line, end='')
PY
```

Healthy result for this repair:

```text
Result=success
ExecMainStatus=0
Hash skips recuperáveis: 0
```

## Anti-duplicate blocks

Do not auto-resolve `[DUP-RISK]` blocks unless the correct Zotero parent item is unambiguous. These require either:

- creating/locating the exact intended parent item in Zotero, then attaching the PDF there
- renaming the PDF if it is actually a different volume/aula/item
- merging/removing duplicate Zotero items when two candidates have the same title

Report the candidate keys and ask for the user's decision when ambiguous.

---
