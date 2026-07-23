---
name: clasp-apps-script-api-executable-setup
description: Configure an Apps Script project so clasp run can work by wiring a standard GCP project, custom OAuth desktop client, executionApi manifest, deployment, and the Apps Script UI project-number association step.
---
## Origem
Criada a partir do contexto: `/home/lucas/Downloads/pp-leads-brasil/organizejr-pp-leads/ploomes_crm`

# Goal

Make a Google Apps Script project runnable via `clasp run`, not just `clasp pull` and `clasp push`.

## When to use

Use this when:
- `clasp pull` and `clasp push` already work,
- but `clasp run <function>` fails,
- and the script still needs a standard GCP project, custom OAuth desktop client, and Apps Script execution API setup.

## Checklist

1. Confirm `clasp` auth works.
2. Ensure the local folder contains:
   - `.clasp.json`
   - `appsscript.json`
3. Add `projectId` to `.clasp.json`.
4. Add `executionApi` to `appsscript.json`.
5. Push the updated manifest.
6. Create a new version and deployment.
7. Log in again with a user-provided OAuth desktop client JSON.
8. In the Apps Script UI, associate the script with the standard GCP project by project number.
9. Retry `clasp run`.

## Practical procedure

### 1. Local clasp config

`.clasp.json` should include:

```json
{
  "scriptId": "<SCRIPT_ID>",
  "projectId": "<GCP_PROJECT_ID>",
  "rootDir": ""
}
```

### 2. Manifest

`appsscript.json` should include:

```json
{
  "timeZone": "America/Bahia",
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "executionApi": {
    "access": "ANYONE"
  },
  "oauthScopes": [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/script.external_request",
    "https://www.googleapis.com/auth/script.scriptapp"
  ]
}
```

### 3. Push and deploy

From the Apps Script folder:

```bash
npx -y @google/clasp push -f
npx -y @google/clasp version "execution api enabled"
npx -y @google/clasp deploy -d "execution api enabled"
```

### 4. Use a custom OAuth desktop client

If the downloaded client secret file is named like:

```text
client_secret_519875906048-xxxx.apps.googleusercontent.com.json
```

then `519875906048` is likely the GCP project number needed in the Apps Script UI association step.

Log in with the downloaded OAuth client and the project scopes:

```bash
npx -y @google/clasp login --creds /path/to/client_secret.json --use-project-scopes --include-clasp-scopes
```

Check the active user:

```bash
npx -y @google/clasp show-authorized-user
```

Expected good sign:
- the user is correct,
- OAuth client says `user-provided`, not `google-provided`.

### 5. Required manual UI step

In the Apps Script editor:

```text
Project Settings
→ Google Cloud Platform (GCP) Project
→ Change project
```

Paste the standard GCP project number, not the project ID.

This step is required when local clasp config alone is not enough.

### 6. Headless-safe helpers inside the Apps Script

If you want `clasp run` to work outside the Apps Script UI:

- avoid depending on `SpreadsheetApp.getActiveSpreadsheet()`;
- prefer `SpreadsheetApp.openById(<spreadsheetId>)`;
- avoid hard dependency on `SpreadsheetApp.getUi()` in runnable functions;
- use a helper that falls back to `Logger.log(...)` and returns text when there is no UI context.

Typical helper pattern:

```javascript
function notify_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    Logger.log(message);
  }
  return message;
}
```

And for sheet access:

```javascript
function getSheet_() {
  const spreadsheetId =
    PropertiesService.getScriptProperties().getProperty('PLOOMES_SPREADSHEET_ID') ||
    CONFIG.SPREADSHEET_ID;
  const spreadsheet = spreadsheetId
    ? SpreadsheetApp.openById(spreadsheetId)
    : SpreadsheetApp.getActiveSpreadsheet();
  return spreadsheet.getSheetByName(CONFIG.SHEET_NAME);
}
```

## Diagnostics

### Symptom: `clasp run` says function not found / API executable

Typical message:

```text
Script function not found. Please make sure script is deployed as API executable.
```

Meaning:
- push or deploy may be incomplete,
- `executionApi` may be missing,
- or the script is not yet associated to the standard GCP project in the Apps Script UI.

### Symptom: `PERMISSION_DENIED`

Typical after switching to custom OAuth creds:
- OAuth client exists,
- but the Apps Script project is still not associated to the same standard GCP project.

### Symptom: `SpreadsheetApp.getActiveSpreadsheet` / `openById` permission errors

Typical message:

```text
You do not have permission to call SpreadsheetApp.getActiveSpreadsheet
```

or:

```text
You do not have permission to call SpreadsheetApp.openById
```

Meaning:
- the OAuth client was not reauthorized with the project scopes,
- or `oauthScopes` is missing the required Sheets scopes in `appsscript.json`.

### Symptom: `clasp apis` says project ID missing

Meaning:
- `.clasp.json` lacks `projectId`.

## Notes

- `clasp pull` and `clasp push` working does not imply `clasp run` is ready.
- The Apps Script UI association to the standard GCP project is the easy-to-miss step.
- Keep a `.claspignore` so unrelated local files are not pushed with the script.
