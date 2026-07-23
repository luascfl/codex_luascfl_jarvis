---
name: zotero-duplicate-metadata-rules
description: "Regras de detecção de duplicatas bibliográficas, tratamento de falsos positivos (títulos, séries, tipos) e uso de tags para revisão manual no Zotero."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_zotero/zotero_sync_webdav`

# Zotero Duplicate Metadata Rules

## zotero-type-aware-duplicate-false-positive

## Problem pattern

A title-only heuristic can mistake different document types for duplicates. Example:

- `book`: `O que é a Psicologia`
- `presentation`: `O que é a Psicologia`

These are not duplicates when the presentation is slides about the book.

## Correct user-facing advice

Tell the user:

1. Set the slide item type in Zotero to `Presentation`/`Apresentação` when the item is actually slides.
2. Prefer a more specific title when possible, such as `O que é a Psicologia, slides sobre o livro`, if future automatic attachment to the correct parent matters.
3. Same title plus different item type should not be treated as a duplicate. Same title plus same item type should still be reviewed.

## Code fix pattern

In `zotero_sync_webdav.py`:

1. For parent selection, if top candidates tie only because they share a title but have different `itemType` values, do not return them as duplicate-risk candidates. Return `(None, [])` so the upload path does not create a `[DUP-RISK]` review tag for a legitimate cross-type title collision.
2. For title-only bibliographic duplicate grouping, include `itemType` in the identity. Keep DOI identity independent of item type because DOI remains stronger evidence.

Example helpers:

```python
def top_parent_candidates_are_different_item_types(candidates: List[dict]) -> bool:
    item_types = {
        (candidate.get('itemType') or '').strip()
        for candidate in candidates
        if candidate.get('itemType')
    }
    return len(item_types) > 1
```

In `select_parent_for_new_attachment(...)`:

```python
if len(top_candidates) == 1:
    return top_candidates[0], candidates
if top_parent_candidates_are_different_item_types(top_candidates):
    return None, []
return None, candidates
```

In `bibliographic_duplicate_identity(...)`:

```python
if doi:
    return ('doi', doi)
title = entry.get('normalized_title') or ''
item_type = (entry.get('itemType') or '').strip()
if len(title) >= 20 and item_type:
    return ('title+type', f"{item_type}:{title}")
if len(title) >= 20:
    return ('title', title)
return None
```

## Regression tests

Add tests covering:

- same title with same item type still blocks automatic parent selection as duplicate risk;
- same title with different item types, e.g. `book` and `presentation`, returns no duplicate-risk candidates;
- title-only duplicate groups are separated by `itemType`;
- DOI duplicate groups still win before title and still group despite title/type differences when DOI matches.

## Verification

Run at least:

```bash
python3 -m py_compile zotero_sync_webdav.py
python3 -m unittest tests.test_bibliographic_matching
```

If notification or pending queue code was touched in the same session, also run:

```bash
python3 -m unittest tests.test_desktop_notifications tests.test_pending_import_queue
```

When deploying the script used by the systemd user service, follow `zotero-sync-deployment-rules`: copy both `zotero_sync_webdav.py` and `zotero_sync_recognizer/` to `~/.local/bin/`.

---

## zotero-title-series-and-type-false-positive-guard

## Desired behavior

- Same title plus different `itemType` is not a duplicate-risk block by itself.
- Title-only duplicate grouping must include `itemType` in the identity when no DOI exists.
- Terminal sequence markers that differ must force title match score to `0.0` when the base title is the same.
- The review tag `zotero-sync: revisar duplicata` should be removed automatically when an item no longer matches the current duplicate-risk set.

## Implementation checklist

1. In `bibliographic_duplicate_identity(entry)`:
   - keep DOI identity as `('doi', doi)`;
   - for title-only identity, include item type, e.g. `('title+type', f"{itemType}:{title}")`;
   - fall back to `('title', title)` only when item type is missing.

2. In parent matching:
   - add `top_parent_candidates_are_different_item_types(candidates)`;
   - if top tied candidates have distinct non-empty `itemType`, return `(None, [])` instead of returning candidates, so the main loop does not treat the tie as `DUP-RISK`.

3. In title scoring:
   - add a terminal sequence splitter for normalized titles matching final `i|ii|iii|iv|v|...|x` or numbers, optionally preceded by `parte|part|volume|vol|tomo|livro|capitulo|cap|chapter`;
   - if both titles share the same base but have different final sequence markers, `title_match_score(...)` returns `0.0`.

4. For stale review tags:
   - track current-risk item keys in `stats['current_review_duplicate_keys']` whenever adding or preserving the review tag;
   - add `remove_review_tag_from_item(...)` and `clear_stale_review_duplicate_tags(...)`;
   - after duplicate-risk and duplicate-cleanup processing, scan current bibliographic parent index and remove `zotero-sync: revisar duplicata` from tagged items not in the current-risk set;
   - preserve all other Zotero tags.

## Regression tests

Add tests in `tests/test_bibliographic_matching.py` for:

- `book` and `presentation` with the same title do not produce duplicate groups;
- same-title different-item-type tied candidates return no parent and no candidates, avoiding a duplicate-risk block;
- `O processo de ensinagem no grau superior I` does not match `... II` and scores `0.0`;
- stale review tag is removed when the item is no longer in `current_review_duplicate_keys`;
- current review tag is preserved when the item is still in `current_review_duplicate_keys`.

Run:

```bash
python3 -m py_compile zotero_sync_webdav.py
python3 -m unittest tests.test_bibliographic_matching tests.test_desktop_notifications tests.test_pending_import_queue
```

Deploy when this project uses the local-bin service copy:

```bash
cp zotero_sync_webdav.py ~/.local/bin/zotero_sync_webdav.py
cp -r zotero_sync_recognizer ~/.local/bin/
python3 -m py_compile ~/.local/bin/zotero_sync_webdav.py
graphify update .
```

---

## zotero-duplicate-review-tags

## Existing behavior to verify

Search the script for tag logic before editing:

- `merge_duplicate_metadata_into_keeper(...)` preserves existing `tags` from a duplicate item when a safe duplicate is merged/deleted.
- This does not necessarily mean new review tags are applied to unsafe/skipped duplicates.

Use targeted search for:

```text
REVIEW_DUPLICATE_TAG
add_review_tag_to_item
blocked_duplicate_risk
auto_duplicate_cleanup_skipped
[DUP-RISK]
```

## Recommended implementation

Add one stable review tag constant:

```python
REVIEW_DUPLICATE_TAG = "zotero-sync: revisar duplicata"
ZOTERO_READONLY_UPDATE_FIELDS = {"lastRead", "dateAdded", "dateModified", "library"}
```

Add a safe update sanitizer because Zotero rejects read-only fields such as `lastRead`:

```python
def sanitize_zotero_update_payload(item_data: dict) -> dict:
    return {
        key: value
        for key, value in item_data.items()
        if key not in ZOTERO_READONLY_UPDATE_FIELDS
    }
```

Add an idempotent tag helper:

```python
def add_review_tag_to_item(zot, item_key, reason, item=None, tag_name=REVIEW_DUPLICATE_TAG):
    if not item_key:
        return False
    current_item = item if item and item.get("data") else zot.item(item_key)
    item_data = dict(current_item.get("data") or current_item)
    tags = list(item_data.get("tags") or [])
    if any(tag.get("tag") == tag_name for tag in tags if isinstance(tag, dict)):
        return False
    tags.append({"tag": tag_name})
    item_data["tags"] = tags
    zot.update_item(sanitize_zotero_update_payload(item_data))
    if item is not None:
        item.setdefault("data", {})["tags"] = tags
    logging.info("[TAG] Item %s marcado com '%s' para revisão manual: %s", item_key, tag_name, reason)
    return True
```

Wire it in these paths:

1. In `[DUP-RISK]` candidate blocks for `parent_candidates and not parent_match`, tag the first candidate items because the drive-only PDF cannot itself be tagged until imported.
2. In safe bibliographic duplicate cleanup, when `can_delete` is false, tag the preserved duplicate item with the reason.

Track a counter such as `review_tags_applied` in `stats` and print it in the final report.

## Verification

Run:

```bash
python3 -m py_compile zotero_sync_webdav.py
python3 -m unittest tests.test_bibliographic_matching
systemctl --user reset-failed zotero-sync.service
systemctl --user start zotero-sync.service
systemctl --user show zotero-sync.service --property=Result,ExecMainStatus,ActiveState,SubState --no-pager
journalctl --user -u zotero-sync.service --since '<start time>' --no-pager | grep '[TAG]\|Etiquetas de revisão\|Bloqueios anti-duplicata\|Erros:'
```

Expected result after first run:

- `Result=success`, `ExecMainStatus=0` if no critical errors remain.
- `[TAG]` log lines for newly tagged review items.
- `Etiquetas de revisão: N` in the final report.

Expected result on later runs:

- The same tag is not duplicated.
- `Etiquetas de revisão` may be `0` if every relevant item already has the tag.

## User-facing wording

Say clearly:

- The script may already preserve existing Zotero tags when merging safe duplicates.
- That is different from applying a new review tag to unsafe duplicates.
- The stable tag to search in Zotero is `zotero-sync: revisar duplicata`.

---
