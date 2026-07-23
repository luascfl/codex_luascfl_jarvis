---
name: zotero-sync-daemon-ops
description: "Infraestrutura de serviços do Linux (systemd), watchers de abertura do Zotero, ciclo de vida de logs, notificações desktop e triagem de erros de runtime."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_zotero/zotero_sync_webdav`

# Zotero Sync Daemon Ops

## zotero-open-watch-service

## Problem pattern

A periodic timer or oneshot service is not enough:

- opening Zotero does NOT immediately trigger sync
- the system only notices the app at the next timer fire
- first-open notification wording may be correct in code but never fire at the right moment without a resident watcher

## Working pattern

### 1. Add a resident watch mode

Implement runtime helpers like:

- `run_open_zotero_sync_loop(interval)`
  - first iteration: `announce_start=True`, `progress=True`, `completion=True`
  - later iterations while Zotero stays open: all three false
- `run_zotero_open_watch()`
  - poll `is_zotero_running()` on a short watch interval
  - when Zotero flips open, log/print detection and hand off to `run_open_zotero_sync_loop(interval)`
  - after Zotero closes, return to waiting

### 2. Expose a dedicated CLI entrypoint

Add a subcommand:

- `watch-zotero`

This lets systemd run the watcher directly through the standard launcher.

### 3. Back it with a dedicated systemd user service

Do NOT repurpose the periodic sync service if a timer still uses it.
Create a separate service, e.g.:

- `zotero-sync-watch.service`
- `ExecStart=$launcher_path watch-zotero`
- `Type=simple`
- `Restart=always`
- `RestartSec=15`

This avoids conflicting semantics between:

- periodic/manual sync service
- always-on open-detection watcher

### 4. Keep first-open wording explicit

Use a first-open body that says the app was detected, not only that sync began.
Example:

- `Zotero aberto detectado. Primeira sync iniciada.`

### 5. Verify live

Useful live checks:

- `systemctl --user is-active zotero-sync-watch.service`
- `pgrep -a -f zotero`
- `journalctl --user -u zotero-sync-watch.service --no-pager | grep -E 'Watcher do Zotero|Zotero aberto detectado'`
- journal lines showing notification transport replies like `(uint32 N,)`

## Tests to require

Add focused tests for:

- first-open wording exact body
- `run_open_zotero_sync_loop(interval)` first iteration on / later iterations off / stop on close
- `run_zotero_open_watch()` polling until open then passing configured interval into the sync loop
- `SETUP_AUTOSTART_SHELL` markers for `zotero-sync-watch.service`, `ExecStart=$launcher_path watch-zotero`, and service enablement

## Notes

- This pattern solves the timing problem that a 2-hour timer cannot: immediate reaction to opening Zotero.
- It pairs well with a no-copy launcher (`run_zotero_sync.sh`) so watch mode also avoids drift from an outdated installed Python script copy.

---

## zotero-watch-open-alert-diagnosis

## Investigation order

1. Check watcher service state:
   - `systemctl --user status zotero-sync-watch.service --no-pager`
2. Read recent watcher journal:
   - `journalctl --user -u zotero-sync-watch.service -n 120 --no-pager`
3. Check current Zotero processes:
   - `pgrep -a -f zotero`
4. Look specifically for:
   - `👀 Watcher do Zotero ativo. Aguardando abertura do app...`
   - `✅ Zotero aberto detectado. Disparando sync imediata.`
   - `(uint32 N,)` notification transport replies from `gdbus`
   - uncaught exceptions that kill the watcher after the first sync

## Important diagnostic split

### A. No detection log
If the journal never shows `Zotero aberto detectado`, the watcher did not see a closed -> open transition.
Suspect:
- watcher not running
- Zotero never fully closed between tests
- wrong process detection logic

### B. Detection log exists, but no `(uint32 N,)`
The watcher detected the open event, but the progress-notification path did not run.
Suspect:
- first-iteration notification policy not enabled
- code path exited before `run_sync_mode(notification_policy=...)`

### C. Detection log exists and `(uint32 N,)` exists, but the user saw nothing
The desktop notification daemon/session renderer may be suppressing or not presenting accepted notifications.
The script did hand the alert to DBus.

### D. Detection log and `(uint32 N,)` exist, but the service later crashes
Inspect for a post-sync exception. One real example in this project:
- `KeyError: 'moved_drive_files_to_collection'` in the final summary because the main sync stats dict printed that field without initializing it on the main path.
- Fix: initialize `'moved_drive_files_to_collection': 0` in the primary `run_sync_mode()` stats dict, restart the watcher, and verify again.

## Live verification target

After a fix, restart the watcher:
- `systemctl --user restart zotero-sync-watch.service`

Then verify again in the journal that you see both:
- `Zotero aberto detectado. Disparando sync imediata.`
- fresh `(uint32 N,)` notification replies

## Delay explanation

If notifications now appear but feel a bit slow, remember the watcher is polling by `ZOTERO_OPEN_WATCH_POLL_SECONDS`.
Default 15s means the first-open alert may take up to ~15s, plus a few seconds of startup/prep.
Lower that value only if the user wants a faster reaction and accepts a more active watcher.

---

## zotero-sync-notification-stack

## Current architecture

### Transport layer

All desktop alerts should go through `send_desktop_notification()`.
Preferred behavior:
1. try `notify-send`
2. fallback to `gdbus` if `notify-send` is unavailable or fails

### Alert types

There are two intentionally distinct alert families:

1. Pending queue because Zotero Desktop is unavailable
   - title: `Zotero fechado`
   - body from `build_pending_queue_notification_body()`
   - user action needed now

2. Successful sync completion
   - title: `Sync concluído`
   - body summarizes added/existing/errors
   - may include log-opening hint when available

### Queue persistence

Closed-Zotero queue state is log-only:
- `zotero_pending_imports_today.log`
- `.last_pending_imports_log_date`

No `zotero_pending_imports.txt` should be reintroduced.
The queue helper reads the last snapshot from the daily log to decide whether the queue changed.

## Guardrails

- Do not bypass `send_desktop_notification()` with raw `notify-send` calls.
- Do not collapse queue and completion alerts back into one generic title.
- Do not reintroduce a txt sidecar for queue state unless the project requirements change explicitly.

## Verification

- `python3 -m unittest tests.test_desktop_notifications tests.test_pending_import_queue`
- live queue test via `update_pending_import_queue_files(['TESTE_...'])` followed by `update_pending_import_queue_files([])`
- if no notification appears, check whether `notify-send` is missing and whether `gdbus call --session ... org.freedesktop.Notifications.Notify ...` succeeds

## Typical failure modes

- `notify-send` missing from PATH, fixed by the gdbus fallback
- queue alert and completion alert using the same summary/title, fixed by separate constants
- queue artifacts not clearing after successful sync, fixed by the log-only lifecycle helper

---

## zotero-pending-queue-log-lifecycle

## What exists

This project now keeps the closed-Zotero queue only as log artifacts under `~/.cache/zotero_sync_webdav/logs`:

- `zotero_pending_imports_today.log`
  - daily log snapshots of the pending queue with timestamps
- `.last_pending_imports_log_date`
  - date marker for daily rollover of the pending queue log

There is no longer a `zotero_pending_imports.txt` sidecar file.

The implementation lives in:
- `read_last_pending_log_snapshot()`
- `update_pending_import_queue_files()`
- `build_pending_queue_notification_body()`
- `finalize_execution()`

The pending queue alert summary is intentionally distinct:
- title: `Zotero fechado`

## Expected lifecycle

### When pending imports exist

- `zotero_pending_imports_today.log` is created or appended with:
  - a daily header, once per day
  - a timestamped `Fila atualizada` block
  - item count and filenames
- A desktop notification may be sent when the current pending list differs from the most recent logged snapshot.
- The queue notification body uses singular/plural wording, for example:
  - `1 PDF novo está na fila. Abra o Zotero para sincronizá-lo.`
  - `N PDFs novos estão na fila. Abra o Zotero para sincronizá-los.`

### When a later sync finishes with no pending desktop imports

The queue state MUST be fully cleared:
- remove `zotero_pending_imports_today.log`
- remove `.last_pending_imports_log_date`

This is the intended behavior when the user opens Zotero and the queued files are finally imported.

## How to verify quickly

1. Inspect the implementation in `zotero_sync_webdav.py`:
   - `PENDING_QUEUE_NOTIFICATION_SUMMARY`
   - `PENDING_IMPORTS_LOG_FILE_NAME`
   - `PENDING_IMPORTS_LOG_DATE_FILE`
   - `read_last_pending_log_snapshot()`
   - `build_pending_queue_notification_body()`
   - `update_pending_import_queue_files()`
2. Run the focused tests:
   - `python3 -m unittest tests.test_pending_import_queue`
3. If you need a hermetic manual check, patch `LOG_DIR` to a temporary directory and call:
   - `update_pending_import_queue_files(['alpha.pdf', 'beta.pdf'])`
   - confirm only the daily pending log and date marker are created
   - confirm no `zotero_pending_imports.txt` appears
   - `update_pending_import_queue_files([])`
   - confirm both pending log artifacts are removed

## Notes

- The daily queue log is not meant to be permanent history across empty states. Once the queue drains, it is removed.
- The main sync log and the pending queue log are distinct. The queue log tracks only the waiting-for-Zotero-Desktop state.
- The notification logic does not need a txt file anymore; it compares the current queue against the last snapshot already stored in the daily pending log.

---

## zotero-sync-desktop-open-requirements

## Operations that require Zotero Desktop OPEN
1. **Importing New PDFs**: Importing new attachments safely without consuming the user's Zotero.org cloud quota relies on a local desktop plugin (`zotero-sync-recognizer`). 
2. **Metadata Recognition**: Standalone PDFs rely on the desktop plugin to fetch bibliographic metadata (parent items).
3. **Adaptive Loop**: The `run_adaptive_sync()` function enters an infinite 5-minute loop *only* if `pgrep -f zotero` detects the app is open.

*If Zotero is closed, the script intercepts new PDFs, skips them, counts them as "errors" in the final report, and places them in `zotero_pending_imports.txt` (the pending queue). This often leads to users seeing a sudden spike in "errors" equivalent to the number of new PDFs added since the last sync.* 

## Operations that work with Zotero Desktop CLOSED
1. **Folder Deduplication**: Merging duplicate drive folders based on `.zotero_folders.json`.
2. **Copy Variants Renaming**: Renaming files like `(Cópia)` or `Copy of` to their canonical names.
3. **Existing Attachment Metadata Updates**: Renaming existing files and updating their metadata directly via the Zotero Web API using `pyzotero`.
4. **Timer-based Single Shot**: The systemd timer (`zotero-sync.timer`) wakes the script every 2 hours. If Zotero is closed, it does a single full sweep of the drive, processes the above background tasks, builds the pending queue, and exits cleanly.

---

## zotero-sync-deployment-rules

## 1. Deployment Requirements
When updating or installing the script to the user's local bin directory, you **MUST** copy the recognizer plugin directory alongside it. 
```bash
cp zotero_sync_webdav.py ~/.local/bin/zotero_sync_webdav.py
cp -r zotero_sync_recognizer ~/.local/bin/
```
**Why:** The script resolves the plugin directory relative to its own `__file__`. If the folder is missing, the script will silently disable Zotero Desktop integration, fallback to the web API, and deplete the user's Zotero cloud storage quota.

## 2. Strict Execution Order
Operations inside `run_sync_mode()` MUST follow this precise order to prevent data duplication and API conflicts:
1. **Folder Deduplication**: `preprocess_drive_duplicate_folders()` must merge duplicate folders and enforce canonical collection names.
2. **File Renaming**: `preprocess_drive_copy_variants()` must resolve `(Cópia)` suffixes.
3. **Zotero API Connection**: Only after the drive is strictly organized.
4. **File Import/Sync Loop**: Process individual PDFs.

## 3. Concurrency Lock (Single Instance)
The script uses a lockfile to prevent overlapping executions: `~/.cache/zotero_sync_webdav/zotero_sync_webdav.lock`.
If a crash leaves a stale lock, the script will refuse to run.
**Recovery:** Delete the lockfile `rm ~/.cache/zotero_sync_webdav/zotero_sync_webdav.lock`.

## 4. Dependencies
The script explicitly relies on `notify-send` for OS-level alerts and `rclone` / `davfs2` for network volume mounts. If the drive mount is broken, the script will aggressively abort early to prevent accidental deletion of Zotero metadata.

---

## zotero-autostart-installed-copy-drift

## Problem pattern

The user updates code in the `zotero_sync_webdav` git repository, tests it directly from the repo, and sees the fix working.
Later, the background systemd timer or watcher runs, and the bug appears again.

Why?
The systemd units (`zotero-sync.service` and `zotero-sync-watch.service`) are hardcoded to run the *installed* copy of the script:
`ExecStart=/home/lucas/.local/bin/zotero_sync_webdav.py`

If the repo copy is modified but not copied to `~/.local/bin/`, the background services will silently run the old broken code.

## Verification steps

1. Check what the systemd service is actually running:
   ```bash
   systemctl --user cat zotero-sync.service | grep ExecStart
   ```
2. Diff the repo version against the installed version:
   ```bash
   diff zotero_sync_webdav.py ~/.local/bin/zotero_sync_webdav.py
   diff -r zotero_sync_recognizer ~/.local/bin/zotero_sync_recognizer
   ```

## Solution

Always redeploy after making changes that need to run in the background:
```bash
cp zotero_sync_webdav.py ~/.local/bin/zotero_sync_webdav.py
cp -r zotero_sync_recognizer ~/.local/bin/
```

Consider updating the `Makefile` or setup scripts if one exists, or simply running the copy command manually. Do not assume modifying the repo file changes the background service behavior.

---

## zotero-sync-runtime-repair

## Context
When `zotero_sync_webdav.py` crashes or stops syncing in the background, the issue is often infrastructure-related (mounts, credentials, lockfiles), not the python script itself.

## 1. The Stale Lockfile
**Symptom:** Script exits immediately with "Outra instância já está rodando" but no process is active.
**Diagnosis:** A previous execution crashed and left the lockfile behind.
**Fix:**
```bash
rm -f ~/.cache/zotero_sync_webdav/zotero_sync_webdav.lock
```

## 2. Broken Google Drive Mount
**Symptom:** Script aborts saying "Pasta raiz do Drive não encontrada".
**Diagnosis:** The `rclone` or `davfs2` mount died.
**Fix:** 
1. Check mount status: `systemctl --user status rclone-google-drive.service`
2. Restart the mount: `systemctl --user restart rclone-google-drive.service`
3. Wait for it to become available: `ls -la ~/Google\ Drive/zoterodb`

## 3. The `wait_webdav.sh` Whitespace Bug
**Symptom:** `rclone` works, but the sync service fails before starting python, complaining about "too many arguments" or "unexpected path".
**Diagnosis:** The `zotero_sync.env` file contains unquoted paths with spaces (like `/home/lucas/Google Drive`), breaking the bash `if [ -d $TARGET_FOLDER ]` check in `wait_webdav.sh`.
**Fix:** 
Edit `wait_webdav.sh` to properly quote variables.
```bash
# WRONG
if [ -d $TARGET_FOLDER ]; then

# CORRECT
if [ -d "$TARGET_FOLDER" ]; then
```

## 4. Rate Limits and 429 Too Many Requests
**Symptom:** Pyzotero throws 429 errors.
**Diagnosis:** The script hit the Zotero API limits.
**Fix:** Zotero API has strict backoff rules. The script must handle `Retry-After` headers. If it crashes instead, the error handling logic in `zotero_sync_webdav.py` needs to be patched to sleep and retry. Do not force immediate execution.

---

## zotero-sync-recoverable-error-exit-triage

## Problem

The Zotero sync service runs but systemd marks it as `failed`.
The journal shows a successful run summary:

```text
==================================================
Processamento concluído!
PDFs na fila: 0
PDFs adicionados/atualizados: 0
...
Erros: 3
...
```

The script exits with `sys.exit(1)` because `stats['errors'] > 0`.
Systemd sees exit code 1 and marks the unit `failed`.

## Triage

1. Do NOT assume the script crashed or that python threw an unhandled exception.
2. Read the script's final print block. If it says `Processamento concluído!`, the python run finished normally.
3. Check the `Erros` counter. It increments for recoverable skips, such as:
   - `Hash skip recuperável` (WebDAV download failed but was cached)
   - `[DUP-RISK]` (Bibliographic duplicate blocked for manual review)
   - missing credentials or missing drive mount (these abort early, but are also handled exits)

## Action

- If the errors are just duplicate-risk warnings or temporary WebDAV hash skips, the systemd `failed` state is an expected consequence of the strict exit code policy.
- To fix the "failed" state, the user must resolve the duplicates in Zotero or let the WebDAV cache heal.
- Do NOT rewrite the script to return `exit(0)` on duplicate risks unless explicitly requested. The strict exit code ensures the user gets alerted that items need manual intervention.

---

## zotero-diagnostic-failure-audit

## Core issue

The diagnostic mode (`--diagnostic`) must NEVER claim the system is fully synchronized if the drive path is missing, unreadable, or empty because the mount failed.
If the drive is inaccessible, the diagnostic report must surface a failure.

## Observed failure pattern

When `/home/lucas/Google Drive` is disconnected:
1. `wait_webdav.sh` usually blocks the main service.
2. But if the script is run manually with `--diagnostic`, it bypasses the wrapper.
3. The script checks the folder, finds nothing, iterates 0 items, and reports:
   - "Todos os PDFs locais estão no Zotero"
   - "Todos os itens do Zotero têm arquivo no Drive"

This is a **false positive success**.

## Diagnostic integrity rule

In `run_diagnostic_mode(...)` or equivalent:
1. Verify `os.path.exists(TARGET_FOLDER)`.
2. Verify `os.path.isdir(TARGET_FOLDER)`.
3. If it does not exist, abort the diagnostic with a clear error:
   `[ERRO] Diretório raiz do Drive não encontrado.`
4. If it exists but contains absolutely no `.pdf` files recursively, print a strong warning:
   `[AVISO] Nenhum PDF encontrado no Drive. O mount pode estar falhando ou o diretório está vazio.`

## Verification

Run the diagnostic manually with a fake path to ensure it fails loudly:

```bash
TARGET_FOLDER=/tmp/caminho_falso python3 zotero_sync_webdav.py --diagnostic
```

Expected output:
- Must NOT print "Todos os PDFs locais estão no Zotero".
- Must print an error about the missing directory and exit gracefully (or with exit code 1).

---
