---
name: gupy-educorp-participant-name-search
description: Use when Gupy EduCorp admin UI participant inclusion fails or participant search returns no individual users in pathway edit modals.
---

# Gupy EduCorp participant name search fix

When adding participants in the Gupy/Niduu admin UI pathway editor, search participants by **name only** in the `6. Participantes` modal. Do not use e-mail as a fallback unless the user explicitly asks.

## Symptom

- `6. Participantes` opens `Selecionar participantes` with `#input-search` / placeholder `Pesquisar participantes/grupos`.
- Native JS setter updates the input value but individual users do not appear.
- Prior searches may leave Puppeteer keyboard state stuck with `Control` down, causing typing to fail or leave only partial text.

## Fix

For the participant modal input `#input-search`, prefer real keyboard typing, not the native setter used for course search controlled inputs.

Required keyboard sequence:

```js
await page.keyboard.up("Control").catch(() => {});
await page.mouse.click(target.x, target.y);
await page.keyboard.down("Control");
await page.keyboard.press("A");
await page.keyboard.up("Control");
await page.keyboard.press("Backspace");
await page.keyboard.type(participantName, {delay: 5});
await page.keyboard.press("Enter");
```

Then select the exact visible name match and click `Incluir`.

## Verification

A successful run returns or observes:

```json
{
  "selectedCount": 5,
  "included": true,
  "results": [{"status": "selected", "value": "PERSON NAME"}]
}
```

After inclusion, the participants section may show `Participantes sem grupo`; do not require every individual name to remain visible on the collapsed page. Trust `included: true` plus selected statuses, or open `VER PARTICIPANTES` for visual confirmation when needed.

## Guardrail

If a manual diagnostic search by e-mail was attempted, do not bake that into the automation. The durable flow is name-only search for participants.
