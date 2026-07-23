---
name: zotero-collection-reconciliation
description: "Regras para reconciliar renames de pastas no Google Drive com coleções do Zotero, mesclar coleções órfãs e lidar com diretórios duplicados e vazios."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_zotero/zotero_sync_webdav`

# Zotero Collection Reconciliation

## zotero-drive-rename-reconciliation

## Problem pattern

A user renames drive folders directly, for example under `.../zoterodb/UNEB Psicologia 2026.1`.
The sync must then:
- create missing Zotero collections for the renamed non-empty folders
- move existing items so collection membership follows the drive path
- remove old collections that become empty duplicates after the move
- update `.zotero_folders.json` if stale keys remain

## Safe reconciliation sequence

1. Ensure the drive mount is healthy first.
2. Reload project module and connect to Zotero.
3. Fetch all attachments and parent bibliographic items.
4. Fetch collections and build the collection path model.
5. Run `ensure_drive_content_collections(...)` to create missing collections for renamed non-empty drive folders.
6. Re-fetch collections if creation occurred.
7. Build local storage and drive path indexes.
8. Run `reconcile_drive_collection_paths(...)` so item collection membership follows the renamed drive folders.
9. Re-fetch collections again.
10. Run `cleanup_empty_duplicate_zotero_collections(...)` to remove old superseded sibling collections that are now empty.
11. Remove empty drive directories if cleanup deleted any old collection mirrors.
12. If `.zotero_folders.json` still points to removed keys, prune or replace those mappings with the new collection keys.

## Important sequencing rule

Do NOT run empty duplicate collection cleanup immediately after `ensure_drive_content_collections(...)` and before drive-authoritative reconciliation. Newly created collections will still be empty at that moment and can be deleted prematurely. Cleanup is safe only after collection membership has been reconciled.

## Verification targets

- `python3 -m py_compile zotero_sync_webdav.py zotero_storage_quota_audit.py`
- live collection check under the relevant parent collection
- confirm old renamed-away collection keys are gone
- confirm new collection names exist
- confirm `.zotero_folders.json` contains the new keys, not the removed ones

## Example outcomes to expect

- `created_zotero_collections_from_drive > 0` when new folder names did not exist in Zotero
- `drive_authoritative_collection_updates > 0` when item memberships moved to follow the drive
- `deleted_empty_duplicate_collections > 0` when the old collections became empty and safe to remove

---

## zotero-stale-renamed-collection-merge

## Problem pattern

Observed shape:

- new drive folder exists and has files, e.g. `Psicopatologia Larissa e Jailson`
- old drive folder is empty, e.g. `PS0029 - Psicopatologia Larissa`
- Zotero still has both sibling collections
- the old collection is empty and childless
- `.zotero_folders.json` still points to the old collection key/path

This slips past `cleanup_empty_duplicate_zotero_collections()` when the names are not cosmetic variants under `normalize_duplicate_collection_core_name()`. Example:

- `PS0029 - Psicopatologia Larissa` -> `psicopatologia larissa`
- `Psicopatologia Larissa e Jailson` -> `psicopatologia larissa e jailson`

Those normalize differently, so the automatic duplicate cleanup does not merge them.

## Safe repair sequence

1. Read the drive parent directory and confirm:
   - old folder is empty
   - new folder has content
2. Fetch live Zotero collections and isolate the two sibling keys.
3. Confirm the old collection:
   - same parent as the new one
   - has no child collections
   - has no collection items
4. Delete the old collection through Pyzotero using the live `version`:
   - `zot.delete_collection({'key': old_key, 'version': old_version})`
   - treat disappearance on re-fetch as success even if Pyzotero does not expose a status code cleanly
5. Update `TARGET_FOLDER/.zotero_folders.json`:
   - remove the old key
   - add or replace the new key with the renamed drive path
6. Remove the old empty drive directory.
7. Re-fetch collections and verify only the new collection remains.

## Verification targets

- live Zotero collection query shows only the survivor
- survivor still has items
- `.zotero_folders.json` contains the new key/path and no old key
- old empty drive directory is gone

## Notes

- This is a live data repair, not a code edit.
- If the old collection still has items or child collections, do not delete it blindly; reconcile memberships first.
- Pyzotero delete may succeed even when the returned object does not expose `status_code`; always re-fetch and verify absence of the deleted key.

---

## zotero-drive-rename-merge-with-move-evidence

## Problem

A pure name-based heuristic is unsafe:

- semantic renames like `Psicopatologia Larissa` -> `Psicopatologia Larissa e Jailson` are not cosmetic duplicates
- fuzzy/name similarity can merge unrelated sibling collections
- moving only some attachments between sibling folders must NOT be treated as a folder rename

## Safe pattern

Base the merge on **move evidence**, not on names.

### 1. Record old -> new collection migrations during drive-authoritative reconciliation

In `sync_item_collections_to_drive_collection(...)`, when managed collection membership changes to the drive-inferred collection, record:

- `(old_collection_key, new_collection_key) -> {item_keys...}`

Do this only for managed collection keys that were actually replaced.

### 2. Let `reconcile_drive_collection_paths(...)` return that move evidence

The reconciliation pass already knows:

- the current drive path
- the inferred drive collection key
- the current Zotero-managed collection key(s)
- whether the content hash matches a known local Zotero attachment

This is the right place to collect evidence that content really moved.

### 3. Merge only when an old collection fully drains into ONE sibling destination

Create a post-reconcile helper, e.g. `merge_drive_renamed_collections(...)`, that deletes the old collection ONLY when all of these are true:

- the old collection migrated to exactly one destination sibling
- the old and new collections share the same `parentCollection`
- the old collection has no child collections
- `zot.collection_items(old_key, limit=1)` is empty
- the old drive directory is empty or absent
- the new drive directory exists and is non-empty

This is how the code distinguishes:

- **full rename / full drain** -> merge allowed
- **partial move** -> old collection still has items, so no merge
- **fan-out move** -> more than one destination, so no merge

### 4. Rewrite `.zotero_folders.json` from the live collection model

Do not patch individual keys opportunistically only.
Create/write helpers like:

- `write_registered_folders(...)`
- `sync_registered_folders_state(...)`

and regenerate `.zotero_folders.json` from `collection_by_key` after collection cleanup/merge settles.

## Wiring order

The merge pass must run AFTER:

1. `ensure_drive_content_collections(...)`
2. `reconcile_drive_collection_paths(...)`

Then rebuild collection models / expected-path indexes as needed before the main file loop relies on them.

## Tests to require

Add focused unit tests for:

- successful full-drain sibling merge
- blocked ambiguous fan-out
- folder-state file rewrite from current `relative_path` values

## Notes

- Keep the older cosmetic duplicate cleanup separate. That helper still handles bracket/prefix variants.
- The semantic drive-rename fix should not depend on fuzzy or approximate name matching.

---

## zotero-empty-duplicate-collections

## Problem pattern

In this project, duplicate drive folders can be recreated by Zotero collections, not just by stray directories on disk.
A purely drive-side cleanup is not enough when Zotero still contains an empty duplicate collection.

Typical indicators:
- One duplicate folder is empty on disk.
- The canonical sibling has PDFs.
- `.zotero_folders.json` still maps the duplicate path.
- Running sync recreates the empty folder.

## Investigation steps

1. Read both duplicate drive paths directly.
   - Confirm whether one is empty and the other has content.
2. Grep `.zotero_folders.json` for the duplicate names.
3. Use the live Zotero API through project helpers:
   - `load_config()`
   - `connect_zotero_client()`
   - `fetch_zotero_collections()`
4. Check whether the duplicate paths correspond to real Zotero collections.
5. For candidate duplicate collections, inspect:
   - same parent collection
   - same normalized core name after stripping cosmetic suffixes like `[Lucas]` and prefixes like `PS0104 - `
   - item presence via `zot.collection_items(key, limit=1)`
   - child-collection presence

## Safe cleanup rule

Delete a duplicate Zotero collection only when ALL of these are true:
- it is a sibling of the canonical collection
- it normalizes to the same core name
- it is empty
- it has no child collections
- exactly one sibling in the group is non-empty

This project now implements that policy in `cleanup_empty_duplicate_zotero_collections()`.

## Live repair sequence

1. Make sure the drive mount is healthy first.
2. Reload config and connect to Zotero.
3. Fetch collections.
4. Run `cleanup_empty_duplicate_zotero_collections(zot, collections, stats)`.
5. Re-fetch collections.
6. Remove now-orphaned empty drive directories with `remove_empty_directories(TARGET_FOLDER, stats, 'removed_empty_drive_dirs')`.
7. Verify:
   - duplicate collection key is gone from live Zotero collections
   - duplicate drive folder path no longer exists
   - canonical sibling remains
   - stale removed keys are pruned from `.zotero_folders.json` if present

## Verification targets

- `python3 -m py_compile zotero_sync_webdav.py zotero_storage_quota_audit.py`
- `python3 -m unittest discover -s tests -p 'test_collection_duplicate_cleanup.py' -v`
- direct path check on the duplicate folder
- live collection check confirming the removed key is absent and the keeper key remains

## Notes

- The helper depends on collection `version` for safe optimistic deletion. If deletes fail with `412 Precondition Failed`, confirm the payload includes the live collection version.
- If multiple siblings have items, do not auto-delete any of them. That case is ambiguous and must be preserved.

---
