---
name: systemd-unit-ops
description: "Global systemd procedures for creating user-level services and timers, tracing failed units to their origin, and identifying safe cleanup candidates."
---

## Origem
Criada a partir do contexto: `Global`

# Systemd unit operations

Use this skill for two related systemd workflows:

1. Creating user-level `.service` and `.timer` units for background or scheduled automation without sudo.
2. Tracing failed systemd units back to their unit files, enable symlinks, package or project origin, and cleanup risk.

## 1. Create a user-level service and timer

Use user-level systemd when a script must run continuously or on a schedule without system-wide privileges.

Unit files live in:

```text
~/.config/systemd/user/
```

### Service file

Create a file such as `meuscript.service`:

```ini
[Unit]
Description=Descrição do meu script em background
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/caminho/absoluto/para/a/pasta
ExecStart=/usr/bin/env bash meu_script.sh
StandardOutput=append:/caminho/absoluto/para/log.txt
StandardError=inherit
```

Rules:

- Use absolute paths for `WorkingDirectory`, scripts and log files.
- Use `Type=oneshot` when the script runs and exits.
- Use `Type=simple` for long-running foreground daemons.
- Prefer logs in the active project directory when practical.

### Timer file

Create a timer with the same base name, such as `meuscript.timer`:

```ini
[Unit]
Description=Timer para rodar meuscript a cada 2 horas

[Timer]
OnBootSec=5min
OnUnitActiveSec=2h
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable meuscript.timer
systemctl --user start meuscript.timer
```

Useful checks:

```bash
systemctl --user status meuscript.service meuscript.timer
systemctl --user list-timers --all
systemctl --user start meuscript.service
journalctl --user -u meuscript.service
```

## 2. Trace failed unit origin

Use this when the user asks where failed systemd units came from, what folder created them, or whether they are safe cleanup candidates.

### Locate the unit in system and user scopes

```bash
python3 - <<'PY'
import subprocess
units = ['UNIT.service']
props = ['FragmentPath','SourcePath','UnitFileState','LoadState','ActiveState','SubState','ExecMainStartTimestamp']
for scope in ['system','user']:
    base = ['systemctl'] + (['--user'] if scope == 'user' else [])
    print(f'## {scope}')
    for u in units:
        r = subprocess.run(base + ['show', u, '--property=' + ','.join(props)], text=True, capture_output=True)
        if r.returncode == 0 and 'LoadState=not-found' not in r.stdout:
            print(f'### {u}')
            print(r.stdout.strip())
PY
```

### List matching unit files and enable symlinks

```bash
python3 - <<'PY'
from pathlib import Path
units = ['UNIT.service']
roots = [
    '/etc/systemd/system',
    '~/.config/systemd/user',
    '/etc/systemd/user',
    '/etc/xdg/systemd/user',
    '/usr/lib/systemd/system',
    '/usr/lib/systemd/user',
]
for root in roots:
    base = Path(root).expanduser()
    if not base.exists():
        continue
    print(f'## {base}')
    for unit in units:
        matches = []
        for p in base.rglob('*'):
            try:
                if p.name == unit or (p.is_symlink() and p.name == unit):
                    matches.append(str(p))
            except OSError:
                pass
        if matches:
            print(unit)
            for m in matches:
                print(' ', m)
PY
```

### Read unit files

Use the Read tool for discovered unit files. Inspect:

- `ExecStart`, `ExecStartPre`, `ExecStop`
- `WorkingDirectory`
- `EnvironmentFile`
- `[Install] WantedBy`

### Targeted provenance search

Use targeted search only after unit paths reveal likely source folders. Avoid broad home scans.

Examples:

- Zotero WebDAV: `~/Downloads/codex_luascfl_zotero`, `~/.local/bin`, `~/.config/zotero_sync_webdav`
- Hermes: `~/.hermes/hermes-agent`, `~/.config/systemd/user`
- Snap units: check `snap list <snap>` and `/var/snap/<snap>/<rev>`

### Capture metadata when source is unclear

```bash
python3 - <<'PY'
from pathlib import Path
import os, time
for p in ['PATH_TO_UNIT']:
    path = Path(p).expanduser()
    print(f'--- {path} ---')
    if path.exists() or path.is_symlink():
        st = path.lstat()
        print('is_symlink', path.is_symlink())
        if path.is_symlink():
            print('target', os.readlink(path))
        print('mtime', time.strftime('%Y-%m-%d %H:%M:%S %z', time.localtime(st.st_mtime)))
        print('owner_uid', st.st_uid, 'mode', oct(st.st_mode & 0o777))
    else:
        print('missing')
PY
```

## Interpretation rules

- `~/.config/systemd/user/*.service` plus `default.target.wants` is a user autostart service.
- `/etc/systemd/system/*.service` plus `multi-user.target.wants` is a system service, usually manual or local unless package-owned.
- `snap.*.service` under `/etc/systemd/user` or `/etc/xdg/systemd/user` is generated by Snap. Confirm with `snap list` and `WorkingDirectory=/var/snap/<name>/<rev>`.
- If the unit points to scripts in `~/.local/bin` and config in `~/.config/<project>`, search the matching project repo for setup or autostart code.
- Do not disable or delete units unless the user asks. First report origin, active path, creating project or package, and likely cleanup risk.
