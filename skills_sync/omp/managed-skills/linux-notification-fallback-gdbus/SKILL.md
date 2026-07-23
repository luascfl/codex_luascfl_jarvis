---
name: linux-notification-fallback-gdbus
description: "Diagnose missing Linux desktop notifications, implement notify-send to gdbus fallback, and keep blocked versus completion notification wording distinct."
---

## Origem
Criada a partir do contexto: `Global`

# Linux notification fallback with gdbus

Use this when a script tries to send Linux desktop notifications with `notify-send`, but nothing appears, `notify-send` is missing or unreliable, or the script needs clear wording for different alert classes.

## Problem pattern

- A script calls `notify-send`.
- No balloon appears.
- `notify-send` is not installed, or returns a nonzero status.
- A session notification service still exists on DBus.
- Multiple alert classes, such as blocked states and success states, reuse generic titles that look the same.

## Investigation

1. Check whether `notify-send` exists.
2. Check whether `gdbus` exists.
3. Try a direct DBus notification call:

```bash
gdbus call --session \
  --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.Notify \
  "App" 0 "" "Test" "Body" [] {} 5000
```

If it returns something like `(uint32 51,)`, the session bus accepted the notification request.

In this workstation pattern, `notify-send` may be absent while `gdbus` is present, and the direct `gdbus` notification path can still succeed.

## Transport implementation pattern

Create a helper like `send_desktop_notification(summary, body, icon="text-x-log", desktop_hint=None)` that:

1. Tries `notify-send` first if `shutil.which("notify-send")` is available.
2. If `notify-send` is unavailable or returns a nonzero status, tries `gdbus` with `org.freedesktop.Notifications.Notify`.
3. Returns `True` on success, `False` otherwise.
4. Routes every higher-level notification path through this helper.

## Wording split pattern

When a script emits more than one class of desktop alert, avoid generic alerts that all look the same. The user should recognize the alert type from the title alone.

Examples of alert classes:

- blocked or waiting state: `service unavailable`, `queue pending`, `user action required`
- success or completion state: `sync finished`

Rules:

1. Give each alert class its own summary/title constant.
   - blocked/waiting example: `Zotero fechado`
   - completion example: `Sync concluído`
2. Keep body builders separate.
   - blocked/waiting body should tell the user what action is needed now.
   - completion body should summarize results.
3. For count-based waiting states, build singular/plural wording explicitly.
4. Route both through the same notification transport helper so backend logic stays shared while wording stays distinct.

## Notes

- `notify-send` offers nicer integration for desktop-entry hints when available.
- The gdbus fallback can ignore click/open hints and still be valuable just to surface the alert.
- If both backends appear to succeed but the user still sees nothing, the next suspect is the graphical session’s notification daemon or renderer, not the script code itself.
- Distinct titles reduce ambiguity and prevent the user from needing to open the body just to know whether something is blocked or finished.

## Good regression tests

- fallback to gdbus when `notify-send` is unavailable
- no fallback when `notify-send` succeeds
- all subprocess calls mocked, no real notifications emitted
- blocked/waiting title is exact and does not regress to the completion title
- completion title is exact and does not regress to the waiting title
- singular/plural message bodies are correct for count-based waiting alerts
