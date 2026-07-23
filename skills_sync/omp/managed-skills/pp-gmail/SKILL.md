---
name: pp-gmail
description: "Printing Press CLI for Gmail, including Gmail API commands, agent mode, MCP setup, draft safety workflows, and headless OAuth refresh for gmail-pp-cli."
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/pp-gmail`

# Gmail — Printing Press CLI

## Prerequisites: Install the CLI

This skill drives the `gmail-pp-cli` binary. **You must verify the CLI is installed before invoking any command from this skill.** If it is missing, install it first:

1. Install via the Printing Press installer:
   ```bash
   npx -y @mvanhorn/printing-press-library install gmail --cli-only
   ```
2. Verify: `gmail-pp-cli --version`
3. Ensure `$GOPATH/bin` (or `$HOME/go/bin`) is on `$PATH`.

If the `npx` install fails before this CLI has a public-library category, install Node or use the category-specific Go fallback after publish.

If `--version` reports "command not found" after install, the install step did not put the binary on `$PATH`. Do not proceed with skill commands until verification succeeds.

The Gmail API lets you view and manage Gmail mailbox data like threads, messages, and labels.

## Unique Capabilities

These capabilities aren't available in any other tool for this API.
- **`drafts compose-safe`** — Create a Gmail draft from explicit recipients, subject, and body input, then re-read the saved Gmail draft and return the canonical `confirmation_hash` for sending.
- **`drafts send-confirm`** — Send an existing draft only when the caller supplies the canonical confirmation hash derived from the saved Gmail draft.
- **`drafts preview-hash`** — Re-read a saved Gmail draft, render the RFC 2822 MIME preview metadata, and output the canonical confirmation hash used by send-confirm.
- **`drafts policy-check`** — Inspect a draft request for risky recipients, missing subject, secret-looking attachment extensions, and accidental inclusion of certificate or key material before draft creation.

## Command Reference

**drafts** — Manage drafts

- `gmail-pp-cli drafts create` — Creates a new draft with the `DRAFT` label.
- `gmail-pp-cli drafts delete` — Immediately and permanently deletes the specified draft. Does not simply trash it.
- `gmail-pp-cli drafts get` — Gets the specified draft.
- `gmail-pp-cli drafts list` — Lists the drafts in the user's mailbox.
- `gmail-pp-cli drafts send` — Sends the specified, existing draft to the recipients in the `To`, `Cc`, and `Bcc` headers.
- `gmail-pp-cli drafts update` — Replaces a draft's content.

**gmail-profile** — Manage gmail profile

- `gmail-pp-cli gmail-profile` — Gets the current user's Gmail profile.

**history** — Manage history

- `gmail-pp-cli history` — Lists the history of all changes to the given mailbox.

**labels** — Manage labels

- `gmail-pp-cli labels create` — Creates a new label.
- `gmail-pp-cli labels delete` — Immediately and permanently deletes the specified label and removes it from any messages and threads that it is applied
- `gmail-pp-cli labels get` — Gets the specified label.
- `gmail-pp-cli labels list` — Lists all labels in the user's mailbox.
- `gmail-pp-cli labels patch` — Patch the specified label.
- `gmail-pp-cli labels update` — Updates the specified label.

**messages** — Manage messages

- `gmail-pp-cli messages batch-delete` — Deletes many messages by message ID.
- `gmail-pp-cli messages batch-modify` — Modifies the labels on the specified messages.
- `gmail-pp-cli messages delete` — Immediately and permanently deletes the specified message. This operation cannot be undone. Prefer `messages.
- `gmail-pp-cli messages get` — Gets the specified message.
- `gmail-pp-cli messages import` — Imports a message into only this user's mailbox
- `gmail-pp-cli messages insert` — Directly inserts a message into only this user's mailbox similar to `IMAP APPEND`
- `gmail-pp-cli messages list` — Lists the messages in the user's mailbox.
- `gmail-pp-cli messages send` — Sends the specified message to the recipients in the `To`, `Cc`, and `Bcc` headers.

**settings** — Manage settings

- `gmail-pp-cli settings create` — Adds a delegate with its verification status set directly to `accepted`, without sending any verification email.
- `gmail-pp-cli settings create-gmail` — Creates a filter. Note: you can only create a maximum of 1,000 filters.
- `gmail-pp-cli settings create-gmail-2` — Creates a forwarding address.
- `gmail-pp-cli settings create-gmail-3` — Creates a custom 'from' send-as alias.
- `gmail-pp-cli settings create-gmail-4` — Creates and configures a client-side encryption identity that's authorized to send mail from the user account.
- `gmail-pp-cli settings create-gmail-5` — Creates and uploads a client-side encryption S/MIME public key certificate chain and private key metadata for the
- `gmail-pp-cli settings delete` — Removes the specified delegate (which can be of any verification status)
- `gmail-pp-cli settings delete-gmail` — Immediately and permanently deletes the specified filter.
- `gmail-pp-cli settings delete-gmail-2` — Deletes the specified forwarding address and revokes any verification that may have been required.
- `gmail-pp-cli settings delete-gmail-3` — Deletes the specified send-as alias. Revokes any verification that may have been required for using it.
- `gmail-pp-cli settings delete-gmail-4` — Deletes a client-side encryption identity.
- `gmail-pp-cli settings delete-gmail-5` — Deletes the specified S/MIME config for the specified send-as alias.
- `gmail-pp-cli settings disable` — Turns off a client-side encryption key pair.
- `gmail-pp-cli settings enable` — Turns on a client-side encryption key pair that was turned off.
- `gmail-pp-cli settings get` — Gets the specified delegate.
- `gmail-pp-cli settings get-auto-forwarding` — Gets the auto-forwarding setting for the specified account.
- `gmail-pp-cli settings get-gmail` — Gets a filter.
- `gmail-pp-cli settings get-gmail-2` — Gets the specified forwarding address.
- `gmail-pp-cli settings get-gmail-3` — Gets the specified send-as alias.
- `gmail-pp-cli settings get-gmail-4` — Retrieves a client-side encryption identity configuration.
- `gmail-pp-cli settings get-gmail-5` — Retrieves an existing client-side encryption key pair.
- `gmail-pp-cli settings get-gmail-6` — Gets the specified S/MIME config for the specified send-as alias.
- `gmail-pp-cli settings get-imap` — Gets IMAP settings.
- `gmail-pp-cli settings get-language` — Gets language settings.
- `gmail-pp-cli settings get-pop` — Gets POP settings.
- `gmail-pp-cli settings get-vacation` — Gets vacation responder settings.
- `gmail-pp-cli settings insert` — Insert (upload) the given S/MIME config for the specified send-as alias.
- `gmail-pp-cli settings list` — Lists the delegates for the specified account.
- `gmail-pp-cli settings list-gmail` — Lists the message filters of a Gmail user.
- `gmail-pp-cli settings list-gmail-2` — Lists the forwarding addresses for the specified account.
- `gmail-pp-cli settings list-gmail-3` — Lists the send-as aliases for the specified account.
- `gmail-pp-cli settings list-gmail-4` — Lists the client-side encrypted identities for an authenticated user.
- `gmail-pp-cli settings list-gmail-5` — Lists client-side encryption key pairs for an authenticated user.
- `gmail-pp-cli settings list-gmail-6` — Lists S/MIME configs for the specified send-as alias.
- `gmail-pp-cli settings obliterate` — Deletes a client-side encryption key pair permanently and immediately.
- `gmail-pp-cli settings patch` — Patch the specified send-as alias.
- `gmail-pp-cli settings patch-gmail` — Associates a different key pair with an existing client-side encryption identity.
- `gmail-pp-cli settings set-default` — Sets the default S/MIME config for the specified send-as alias.
- `gmail-pp-cli settings update` — Updates a send-as alias. If a signature is provided, Gmail will sanitize the HTML before saving it with the alias.
- `gmail-pp-cli settings update-auto-forwarding` — Updates the auto-forwarding setting for the specified account.
- `gmail-pp-cli settings update-imap` — Updates IMAP settings.
- `gmail-pp-cli settings update-language` — Updates language settings.
- `gmail-pp-cli settings update-pop` — Updates POP settings.
- `gmail-pp-cli settings update-vacation` — Updates vacation responder settings.
- `gmail-pp-cli settings verify` — Sends a verification email to the specified send-as alias address. The verification status must be `pending`.

**stop** — Manage stop

- `gmail-pp-cli stop` — Stop receiving push notifications for the given user mailbox.

**threads** — Manage threads

- `gmail-pp-cli threads delete` — Immediately and permanently deletes the specified thread. Any messages that belong to the thread are also deleted.
- `gmail-pp-cli threads get` — Gets the specified thread.
- `gmail-pp-cli threads list` — Lists the threads in the user's mailbox.

**watch** — Manage watch

- `gmail-pp-cli watch` — Set up or update a push notification watch on the given user mailbox.


### Finding the right command

When you know what you want to do but not which command does it, ask the CLI directly:

```bash
gmail-pp-cli which "<capability in your own words>"
```

`which` resolves a natural-language capability query to the best matching command from this CLI's curated feature index. Exit code `0` means at least one match; exit code `2` means no confident match — fall back to `--help` or use a narrower query.

## Recipes

### Create a draft without sending it

```bash
gmail-pp-cli drafts compose-safe --to person@example.com --subject 'Review request' --body 'Please review this draft.' --json
```

`compose-safe` returns a `preflight_hash` for the locally generated MIME and a `confirmation_hash` recalculated from the saved Gmail draft. Use the returned `confirmation_hash` with `send-confirm`; Gmail may normalize headers and MIME boundaries after creation.

### Verify a draft before sending

```bash
gmail-pp-cli drafts preview-hash draft_123 --json
```

### Block risky certificate attachments

```bash
gmail-pp-cli drafts policy-check --attach ./certificate.pfx --json
```

## Auth Setup

Run `gmail-pp-cli auth setup` for the URL and steps to obtain a token (add `--launch` to open the URL). Then store it:

```bash
gmail-pp-cli auth set-token YOUR_TOKEN_HERE
```

Or set `GMAIL_OAUTH2C` as an environment variable.

Run `gmail-pp-cli doctor` to verify setup.

### Headless OAuth refresh for `invalid_grant`

When `gmail-pp-cli` returns `invalid_grant`, do not use the global `python3 jarvis.py google-auth-refresh --force` flow. `gmail-pp-cli` is a separate app with its own token and client credentials in `~/.config/gmail-pp-cli/config.toml`.

Procedure:

1. Read `~/.config/gmail-pp-cli/config.toml` to get `client_id` and `client_secret`. Do not print these values in chat.
2. Run the login flow in a background process and save the log in the active project directory or in `~/.local/share/gmail-pp-cli/`, never in `/tmp`:

   ```bash
   mkdir -p ~/.local/share/gmail-pp-cli
   gmail-pp-cli auth login \
     --client-id 'YOUR_CLIENT_ID' \
     --client-secret 'YOUR_CLIENT_SECRET' \
     --scope 'https://mail.google.com/' > ~/.local/share/gmail-pp-cli/oauth-login.log 2>&1 &
   ```

3. Read the log, extract the `https://accounts.google.com/o/oauth2/auth?...` URL, and give only that URL to the user.
4. After the user authorizes in the browser, the localhost callback saves the new token. Then run `gmail-pp-cli doctor`.


## Agent Mode

Add `--agent` to any command. Expands to: `--json --compact --no-input --no-color --yes`.

- **Pipeable** — JSON on stdout, errors on stderr
- **Filterable** — `--select` keeps a subset of fields. Dotted paths descend into nested structures; arrays traverse element-wise. Critical for keeping context small on verbose APIs:

  ```bash
  gmail-pp-cli drafts list --agent --select id,name,status
  ```
- **Previewable** — `--dry-run` shows the request without sending
- **Offline-friendly** — sync/search commands can use the local SQLite store when available
- **Non-interactive** — never prompts, every input is a flag
- **Explicit retries** — use `--idempotent` only when an already-existing create should count as success, and `--ignore-missing` only when a missing delete target should count as success

### Response envelope

Commands that read from the local store or the API wrap output in a provenance envelope:

```json
{
  "meta": {"source": "live" | "local", "synced_at": "...", "reason": "..."},
  "results": <data>
}
```

Parse `.results` for data and `.meta.source` to know whether it's live or local. A human-readable `N results (live)` summary is printed to stderr only when stdout is a terminal AND no machine-format flag (`--json`, `--csv`, `--compact`, `--quiet`, `--plain`, `--select`) is set — piped/agent consumers and explicit-format runs get pure JSON on stdout.

## Agent Feedback

When you (or the agent) notice something off about this CLI, record it:

```
gmail-pp-cli feedback "the --since flag is inclusive but docs say exclusive"
gmail-pp-cli feedback --stdin < notes.txt
gmail-pp-cli feedback list --json --limit 10
```

Entries are stored locally at `~/.local/share/gmail-pp-cli/feedback.jsonl`. They are never POSTed unless `GMAIL_FEEDBACK_ENDPOINT` is set AND either `--send` is passed or `GMAIL_FEEDBACK_AUTO_SEND=true`. Default behavior is local-only.

Write what *surprised* you, not a bug report. Short, specific, one line: that is the part that compounds.

## Output Delivery

Every command accepts `--deliver <sink>`. The output goes to the named sink in addition to (or instead of) stdout, so agents can route command results without hand-piping. Three sinks are supported:

| Sink | Effect |
|------|--------|
| `stdout` | Default; write to stdout only |
| `file:<path>` | Atomically write output to `<path>` (tmp + rename) |
| `webhook:<url>` | POST the output body to the URL (`application/json` or `application/x-ndjson` when `--compact`) |

Unknown schemes are refused with a structured error naming the supported set. Webhook failures return non-zero and log the URL + HTTP status on stderr.

## Named Profiles

A profile is a saved set of flag values, reused across invocations. Use it when a scheduled agent calls the same command every run with the same configuration - HeyGen's "Beacon" pattern.

```
gmail-pp-cli profile save briefing --json
gmail-pp-cli --profile briefing drafts list
gmail-pp-cli profile list --json
gmail-pp-cli profile show briefing
gmail-pp-cli profile delete briefing --yes
```

Explicit flags always win over profile values; profile values win over defaults. `agent-context` lists all available profiles under `available_profiles` so introspecting agents discover them at runtime.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Usage error (wrong arguments) |
| 3 | Resource not found |
| 4 | Authentication required |
| 5 | API error (upstream issue) |
| 7 | Rate limited (wait and retry) |
| 10 | Config error |

## Argument Parsing

Parse `$ARGUMENTS`:

1. **Empty, `help`, or `--help`** → show `gmail-pp-cli --help` output
2. **Starts with `install`** → ends with `mcp` → MCP installation; otherwise → see Prerequisites above
3. **Anything else** → Direct Use (execute as CLI command with `--agent`)

## MCP Server Installation

Install the MCP binary from this CLI's published public-library entry or pre-built release, then register it:

```bash
claude mcp add gmail-pp-mcp -- gmail-pp-mcp
```

Verify: `claude mcp list`

## Direct Use

1. Check if installed: `which gmail-pp-cli`
   If not found, offer to install (see Prerequisites at the top of this skill).
2. Match the user query to the best command from the Unique Capabilities and Command Reference above.
3. Execute with the `--agent` flag:
   ```bash
   gmail-pp-cli <command> [subcommand] [args] --agent
   ```
4. If ambiguous, drill into subcommand help: `gmail-pp-cli <command> --help`.
