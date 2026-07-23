---
name: bitwarden-cli-automation-rules
description: "Consolidated rules for Bitwarden CLI authentication (API Key vs OAuth), session management, and programmatic bulk editing (bw encode)."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/bitwarden`

# Bitwarden CLI Automation & Authentication Rules

This skill consolidates rules for authenticating and automating tasks using the Bitwarden CLI (`bw`), including resolving authentication confusion and performing bulk edits.

## 1. Authentication: CLI vs. REST API (Crucial Distinction)

Users often confuse Personal API Keys with OAuth 2.0 Credentials. They serve different purposes.

- **CLI Authentication (Personal API Key):**
  - Used to authenticate the `bw` CLI tool (`bw login --apikey`).
  - Gives full access to the local vault.
  - Credentials obtained from: *Web Vault -> Settings -> Account -> API Key*.
- **REST API Authentication (OAuth 2.0):**
  - Used for programmatic access to REST endpoints. Requires running a local server (`bw serve`).
  - Uses `grant_type=client_credentials` and `scope=api`.
  - **DO NOT** try to use OAuth 2.0 client credentials with `bw login --apikey`. It will fail.

### Automating CLI Login
For scripts, use the Personal API Key with piped input. Never hardcode master passwords in clear text if avoidable.

```bash
# Set variables from your Personal API Key (NOT OAuth 2.0 credentials)
echo -e "${BW_CLIENTID}\n${BW_CLIENTSECRET}" | bw login --apikey

# Once logged in, you must unlock to get the session key:
export BW_SESSION=$(bw unlock --raw)
```
*Other login methods:*
- Traditional: `bw login email@example.com`
- SSO: `bw login --sso` (opens browser) or `bw login --method 0 --code <code>`

## 2. Bulk Editing / Renaming Items

To edit items programmatically via the CLI, you **MUST** use `bw encode` to prepare the JSON payload. `bw edit item` does not accept raw JSON text directly.

### Workflow for Bulk Editing

**1. Map the items:**
Extract the items you need to rename into a manageable format.
```bash
bw list items --search "term" | jq -r '.[] | "\(.id)|\(.name)"' > items.txt
```

**2. Python Automation Script:**
```python
import subprocess, json

def encode_item(item_json):
    """Encodes the modified JSON into a base64 string using bw encode"""
    result = subprocess.run(['bw', 'encode'], input=json.dumps(item_json), capture_output=True, text=True, check=True)
    return result.stdout.strip()

mapping = {"item_id_1": "New Name 1", "item_id_2": "New Name 2"}

for item_id, new_name in mapping.items():
    # 1. Get original JSON
    item = json.loads(subprocess.check_output(['bw', 'get', 'item', item_id], text=True))
    
    # 2. Modify properties
    item['name'] = new_name
    
    # 3. Encode and Apply
    encoded_json = encode_item(item)
    subprocess.run(['bw', 'edit', 'item', item_id, encoded_json], check=True)
```

### Important Rules for Editing
- **Backup:** Always export a backup (`bw export --format json`) before bulk operations.
- **Syntax:** The correct edit command is `bw edit item <ID> <ENCODED_JSON>`. Do not use the `--item` flag.
- **Sync:** Run `bw sync` after operations to ensure your local changes are pushed to the cloud vault.
