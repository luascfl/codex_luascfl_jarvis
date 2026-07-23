---
name: google-docs-automation-rules
description: "Consolidated rules for Google Docs API: auth (local service account), reading tabs, editing (batchUpdate), APA tables/ABNT, and ExtraSuite patches."
---

## Origem
Criada a partir do contexto: `Global`

# Google Docs Automation Rules

When interacting with Google Docs programmatically (reading, writing, formatting), use these consolidated rules and workflows to bypass UI barriers, handle authentication, and structure complex edits (like tables and tabs).

## 1. Authentication (Local Service Account Fallback)

If CLI tools fail, use raw Python with a local Service Account JSON to read/edit docs directly. The user must share the document with the SA email as Editor.

**Verified SA Path:** `/home/lucas/.config/gcloud/legacy_credentials/gemini-cli-sa@probable-life-428216-k8.iam.gserviceaccount.com/adc.json` (Has Docs API enabled).

**Python Auth Template:**
```python
import json, jwt, time, requests

with open("/home/lucas/.config/gcloud/legacy_credentials/gemini-cli-sa@probable-life-428216-k8.iam.gserviceaccount.com/adc.json") as f:
    creds = json.load(f)

now = int(time.time())
claims = {
    "iss": creds["client_email"],
    "scope": "https://www.googleapis.com/auth/documents",
    "aud": creds["token_uri"],
    "exp": now + 3600,
    "iat": now
}
token = jwt.encode(claims, creds["private_key"], algorithm="RS256")
res = requests.post(creds["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": token})
access_token = res.json().get("access_token")
headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
```

## 2. Reading Documents & Handling Tabs

To extract text or find specific tabs:

**Fetch Doc (with Tabs):**
```python
doc_id = "YOUR_DOC_ID"
url = f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true"
doc = requests.get(url, headers=headers).json()
```

**Extract Text (Basic):**
Iterate over `content = doc.get("body", {}).get("content", [])`. Check `if "paragraph" in el:` and append `element["textRun"]["content"]`. For tables, `if "table" in el: text += "[Table]\n"`.

**Finding a Target Tab:**
Iterate over `doc.get('tabs', [])` and match `tab['tabProperties']['title']`. Get the `tabId` and `last_index = tab['documentTab']['body']['content'][-1]['endIndex']`.

## 3. Editing Documents (batchUpdate)

Use `POST https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate` with a `requests` JSON payload.

- **Replacing Text:**
  ```python
  {"replaceAllText": {"containsText": {"text": "EXACT_TEXT", "matchCase": False}, "replaceText": "NEW_TEXT"}}
  ```
  *Tip: Don't include list markers (like `*` or `1.`) in `containsText` as they are paragraph metadata, not textRuns.*

- **Targeting Tabs:**
  To insert/delete text in a specific tab, add `"tabId": target_tab_id` inside the `location` or `range` object (e.g., inside `insertText.location` or `deleteContentRange.range`).

## 4. APA 7th Edition Tables & ABNT Rules

When generating APA 7th edition tables using the API:
- **ABNT Callout:** Always insert a text reference *before* the table (e.g., "Os resultados estão sumarizados na Tabela 1.").
- **Visual Rules:** Table number is **Bold**, Title is *Italic* and one line below. Table body & headings are REGULAR font. Headings and Data are Centered. First column is Left-aligned.
- **Note:** Below the table. "*Nota.*" must be italicized.

**CRITICAL API TRAPS:**
1. **Invisible Borders:** You MUST explicitly set the RGB color to `{"red":0, "green":0, "blue":0}` for solid lines, or `{}` for transparent lines. If you pass an empty `rgbColor: {}`, Google Docs draws a transparent line.
2. **Inherited Indents:** You MUST explicitly set `alignment: START`, `indentFirstLine: 0`, and `indentStart: 0` for titles and notes via `updateParagraphStyle`.
3. **Inherited Styles:** Apply an `updateTextStyle` to the whole table range setting `bold: False` and `italic: False` to clear inherited formatting.

## 5. ExtraSuite Workflow (v0.9.0 Patch)

If using `extrasuite` to pull/push Markdown:
1. `pip install extrasuite`
2. **Patch Scope Bug:** Version 0.9.0 misses Drive/Docs scopes. You MUST patch `credentials.py`:
   ```python
   # Patch extrasuite/client/credentials.py
   code = code.replace(
       '"https://www.googleapis.com/auth/presentations",',
       '"https://www.googleapis.com/auth/presentations",\n                "https://www.googleapis.com/auth/documents",\n                "https://www.googleapis.com/auth/drive",'
   )
   ```
3. **Pull:** `extrasuite docs pull "DOC_URL" ./doc_folder --service-account sa.json`
4. **Edit:** Modify files in `./doc_folder/tabs/` (do not alter YAML frontmatter).
5. **Push:** `extrasuite docs push ./doc_folder --service-account sa.json`
