---
name: browserclaw-wine-linux-install
description: Install and troubleshoot BrowserClaw on Linux using the Windows x64 build through Bottles Flatpak Wine when no native Linux release exists.
---

# BrowserClaw via Wine on Linux

Use when the user wants BrowserClaw, not BrowserOS, on Linux and upstream only ships Windows/macOS assets.

## Current working recipe

1. Check latest release assets through GitHub API:
   - `https://api.github.com/repos/browseros-ai/BrowserOS/releases/latest`
   - Recent BrowserClaw releases may have only Windows/macOS assets.

2. Prefer the Windows x64 ZIP/installer asset for BrowserClaw.
   - Example asset used: `BrowserClaw_v0.48.1_x64_installer.zip`
   - Verify with `sha256sum` against the GitHub release `digest`.

3. If system Wine is not installed but Bottles Flatpak exists, use Bottles' bundled Wine:
   - `flatpak info com.usebottles.bottles`
   - `flatpak run --command=wine com.usebottles.bottles --version`

4. Grant Bottles access to the install directory if using `~/Downloads`:
   ```bash
   flatpak override --user --filesystem=/home/lucas/Downloads com.usebottles.bottles
   ```

5. Create and bootstrap a Wine prefix in the project/download directory:
   ```bash
   mkdir -p /home/lucas/Downloads/BrowserClaw/wineprefix
   flatpak run --env=WINEPREFIX=/home/lucas/Downloads/BrowserClaw/wineprefix --command=wineboot com.usebottles.bottles -u
   ```

6. Run the BrowserClaw installer through Bottles Wine:
   ```bash
   flatpak run --env=WINEPREFIX=/home/lucas/Downloads/BrowserClaw/wineprefix --command=wine com.usebottles.bottles /home/lucas/Downloads/BrowserClaw/portable/BrowserClaw_vX.Y.Z_x64_installer.exe
   ```

7. Expected installed executable path:
   ```text
   /home/lucas/Downloads/BrowserClaw/wineprefix/drive_c/users/lucas/AppData/Local/BrowserClaw/Application/chrome.exe
   ```

## Launcher patterns

Directly launching `chrome.exe` may create processes without a visible managed window. A Wine virtual desktop makes the container visible, but does not guarantee Chromium will render.

Use a unique desktop name each run to avoid stale X11 `BadWindow` errors after `wineserver -k`:

```bash
#!/usr/bin/env bash
set -euo pipefail

export WINEPREFIX="/home/lucas/Downloads/BrowserClaw/wineprefix"
APP='C:\users\lucas\AppData\Local\BrowserClaw\Application\chrome.exe'
DESKTOP="BrowserClaw-$(date +%s)"

flatpak run \
  --env=WINEPREFIX="$WINEPREFIX" \
  --command=wine \
  com.usebottles.bottles \
  explorer "/desktop=${DESKTOP},1280x720" \
  "$APP" \
  --disable-gpu \
  --disable-gpu-compositing \
  --disable-software-rasterizer=false \
  --disable-features=VizDisplayCompositor,CanvasOopRasterization,GpuRasterization \
  --use-angle=swiftshader \
  --use-gl=swiftshader-webgl \
  --no-sandbox \
  --disable-dev-shm-usage \
  --new-window \
  "${@:-about:blank}" &
launcher_pid=$!

sleep 10
if command -v xdotool >/dev/null 2>&1; then
  xdotool search --class chrome.exe windowsize %@ 1200 680 windowmove %@ 20 20 windowmap %@ windowraise %@ 2>/dev/null || true
fi

wait "$launcher_pid"
```

## Verification

- `wmctrl -l` should show a `BrowserClaw-<timestamp> - Wine Desktop` container if virtual desktop starts.
- `pgrep -a chrome.exe` should show BrowserClaw's Wine processes.
- `xwininfo -root -tree` can reveal hidden or unmanaged `chrome.exe` windows. In failing cases, Chromium may create tiny unmanaged windows like `119x34`, or resized but still unrendered windows.
- Headless smoke test can be done by launching with `--headless=new --disable-gpu --no-sandbox --remote-debugging-port=9229 about:blank` and waiting for `DevTools listening`.

## Troubleshooting outcomes

### Blue Wine desktop with BrowserClaw icon only

This is Wine `explorer.exe`, not BrowserClaw. The desktop icon is the Windows shortcut created by the installer. If double-clicking it does nothing visible, launch `chrome.exe` directly via the script above. If `chrome.exe` processes exist but no managed window appears, the issue is Wine/Chromium window integration.

### `BadWindow (invalid Window parameter)` after reset

Usually caused by Wine trying to reuse a stale virtual desktop X11 window after `wineserver -k`. Fix by using a unique `/desktop=<name>,1280x720` each launch.

### Black screen

Black screen means Chromium launched but the graphics pipeline did not render. Try software rendering flags: `--disable-gpu-compositing`, `--disable-features=VizDisplayCompositor,CanvasOopRasterization,GpuRasterization`, `--use-angle=swiftshader`, `--use-gl=swiftshader-webgl`. If still black, treat it as not usable on that Wine/desktop stack.

## Cleanup/reset

If hidden or stale Wine processes exist:

```bash
flatpak run --env=WINEPREFIX=/home/lucas/Downloads/BrowserClaw/wineprefix --command=wineserver com.usebottles.bottles -k
```

## Caveat

This is compatibility, not native support. BrowserClaw is Chromium-based. Installing and headless launch may work while graphical UI remains unusable. Blue desktop only, unmanaged tiny `chrome.exe` windows, or black screen are evidence that the Windows build is not practically usable under Wine on that Linux session.
