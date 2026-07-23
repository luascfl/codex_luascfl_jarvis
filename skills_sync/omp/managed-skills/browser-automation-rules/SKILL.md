---
name: browser-automation-rules
description: "How to reliably automate browsers handling authenticated sessions, complex SPA clicks via CDP, and extracting DOM to bypass native download dialog timeouts."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/codex_luascfl_jarvis`

# Browser Automation Rules

When automating browsers (especially complex React SPAs or authenticated sites), follow these rules to ensure reliability, persistence, and performance.

## 0. Canonical automation owner

When an existing `.py` or `.js` automation already owns the target workflow, do not recreate the flow from scratch with fresh `xd://browser` snippets.

- First locate and run the canonical script/helper for the operation.
- If the canonical script is missing a needed selector, branch, wait, or fallback, patch that script/helper and rerun it.
- Use one-off `xd://browser` snippets only for narrow inspection, verification, or debugging evidence, not as the delivered automation path.
- After a snippet proves a fix, fold the durable logic back into the owning `.py` or `.js` before considering the task complete.
- Never leave a parallel throwaway script, ad hoc browser runner, or copied workflow beside a maintained automation file unless the user explicitly asks for a separate prototype.


## 1. Authenticated Sessions (CDP Architecture)

When a script or agent needs to use an authenticated session (e.g., Perplexity, LinkedIn) via `xd://browser`, **do not rely on passing `--user-data-dir` directly to the `xd://browser` tool's args**. Puppeteer often overrides this, creating temporary profiles and causing session loss.

To ensure true persistence of Cookies and Session Storage, separate the browser launch from the automation connection:

**Launch Chrome via `hub`**
Start the Chrome process natively using the `hub` tool, pointing to a persistent directory and exposing a debug port:
```json
{
  "op": "start",
  "name": "chrome_automation",
  "application": "/usr/bin/google-chrome",
  "args": [
    "--remote-debugging-port=9222",
    "--user-data-dir=/home/lucas/.omp/chrome-persistent-profile"
  ],
  "ready": { "port": 9222 }
}
```

**Connect `xd://browser`**
Connect to the running instance using the `cdp_url` parameter:
```json
{
  "action": "open",
  "url": "https://www.perplexity.ai/",
  "app": {
    "cdp_url": "http://127.0.0.1:9222"
  }
}
```

**Security & Session Rules**
- **Initial Login:** If the page loads unauthenticated, stop and ask the user to log in manually on the visible screen. It will persist for future runs.
- **NEVER Force-Kill:** Do not use `kill: true` or `killall`. Abruptly killing the browser process wipes **Session Storage** before it can flush to disk, logging the user out of modern SPAs like Perplexity.
- **Never Copy Profiles:** Do not attempt to use `shutil` or `cp` to copy the user's host Chrome profile. OS-level encryption (GNOME Keyring) will prevent the automation from decrypting the cookies.

## 2. Performance: Avoiding "Blind Sleeps" & Speeding up Input

Do not use arbitrary/fixed long sleeps (`wait(3000)`) in UI automation. They drastically inflate execution times when looping over multiple items.

- **Intelligent Polling (No Blind Sleeps):** Instead of waiting a fixed number of seconds for search results or UI elements to render, use active polling. Check the DOM every ~100ms inside a loop and proceed immediately as soon as the expected result or element state appears.
- **Fast Typing:** When dealing with React/SPA inputs, typing character by character with delays (mimicking human typing) is slow. Instead, focus the input, select all (`Ctrl+A`), hit `Backspace`, and use fast text insertion. For React compatibility, ensure you dispatch appropriate `input` and `change` events natively, or use minimal typing delays (`delay: 5`) combined with native clipboard commands so the input is practically instant without breaking framework listeners.
- **Agile Modal Handling:** For dialogs, popups, and drawer closings, do not wait for fixed animation durations. Poll the DOM actively checking for the CSS class or modal element to disappear from visibility, and resume immediately when it is gone.

## 3. Raw CDP Click Fallback (Bypassing React Event Blockers)

When automating complex React SPAs, standard DOM clicks (`element.click()`) or even Puppeteer's `tab.click()` might fail silently or time out. This happens because the SPA might intercept events, require specific `isTrusted` flags, or bury text inside complex hidden spans.

If `xd://browser` fails to navigate after a click, you can bypass the DOM event system entirely by sending raw Chrome DevTools Protocol (CDP) mouse events to the exact screen coordinates. Use `scrollIntoView` first, get the exact viewport coordinates, and dispatch the click.

Inside `xd://browser` run code:
```javascript
const rect = await tab.evaluate(() => {
  const el = document.querySelector('button'); // specific selector
  if (!el) return null;
  el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect();
  return {x: r.x + r.width/2, y: r.y + r.height/2};
});
if (rect) {
  await page.mouse.click(rect.x, rect.y);
}
```

## 4. DOM Extraction Fallback (Bypass Save As Dialogs)

When using `xd://browser` or Puppeteer, clicking a button like "Export", "Download", or "Save" will sometimes trigger a native OS "Save As" dialog. Because the automation environment cannot interact with native OS dialogs, the `tab.click()` command will hang and eventually **time out**.

**Do not try to intercept the download or dismiss the dialog.**

Instead, bypass the download entirely by extracting the text directly from the page DOM and writing the file yourself.

**How to extract content:**
1. Use `xd://browser` with a `run` action to execute `tab.evaluate()`.
2. Grab the `innerText` of the main content container.
3. Write the returned string to the desired local file using the `bash` or `write` tool.

**Example:**
If an "Export as Markdown" button times out, do this instead:
```json
{
  "action": "run",
  "code": "return await tab.evaluate(() => {\n  const main = document.querySelector('main') || document.body;\n  return main.innerText;\n});"
}
```
Then, take the output string and write it to `output.md` manually. This is 100% reliable and immune to native UI blocking.
