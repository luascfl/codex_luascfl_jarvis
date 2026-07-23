---
name: github-push-protection-cleanup
description: Use when git push is blocked by GitHub push protection for secrets in local unpushed commits and the local branch is intended to be authoritative.
---

# GitHub push protection cleanup

Use this when `git push` is rejected by GitHub push protection because local, unpushed commits contain secrets, and the user says the local branch is the authoritative version.

## Safety rules

- Do not paste or expose the secret values in chat.
- Treat old blocked commits as tainted. A later commit that removes the secret is not enough because push protection scans the whole pushed range.
- Preserve a local backup branch before rewriting history.
- Do not blindly commit dirty working tree files. Separate already committed local history from unstaged user/runtime changes.

## Procedure

1. Inspect branch and remote.

```bash
git status --short --branch
git remote -v
```

2. Try the push once if the failure is not yet known.

```bash
git push origin main
```

3. If GitHub reports push protection, identify the affected files and commits from the remote error. Do not repeat the secret values.

4. Sanitize the current working tree. For Google OAuth examples, replace hardcoded defaults with environment lookups or placeholders, for example:

```python
env["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
env["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")
```

5. Verify current files without printing secrets. Use regex counts, not raw grep output.

```python
import re
from pathlib import Path
text = Path("jarvis.py").read_text(encoding="utf-8")
patterns = {
    "google_oauth_client_id": re.compile(r"\b\d{12}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com\b"),
    "google_oauth_client_secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]+\b"),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]+"),
}
print({name: len(p.findall(text)) for name, p in patterns.items()})
```

6. Create a local backup branch before rewriting.

```bash
git branch backup/pre-push-secret-cleanup-$(date +%Y%m%d%H%M%S)
```

7. Squash local unpushed commits onto the remote base. This removes tainted commit history while keeping the final staged delta.

```bash
git reset --soft origin/main
```

8. Re-stage sanitized files that had secrets, because after `reset --soft` the index may still contain the tainted version.

```bash
git add jarvis.py mcp_config.json
```

9. Scan the staged tree without printing secret values.

```python
import subprocess, re
from pathlib import Path
repo = Path.cwd()
proc = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], stdout=subprocess.PIPE, check=True)
files = [p.decode() for p in proc.stdout.split(b"\0") if p]
patterns = {
    "google_oauth_client_id": re.compile(r"\b\d{12}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com\b"),
    "google_oauth_client_secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]+\b"),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]+"),
}
findings = []
for rel in files:
    show = subprocess.run(["git", "show", f":{rel}"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if show.returncode != 0:
        continue
    text = show.stdout.decode("utf-8", "ignore")
    counts = {name: len(p.findall(text)) for name, p in patterns.items()}
    if any(counts.values()):
        findings.append((rel, counts))
print({"staged_files": len(files), "findings": findings})
```

10. Commit the clean squashed delta and push.

```bash
git commit -m "Consolidate local updates"
git push origin main
```

If the reset creates staged plus unstaged changes (`MM`, `AM`, `AD`), remember that `git commit` includes only the staged snapshot. Keep unrelated unstaged user/runtime changes out of the cleanup commit unless the user explicitly asked to publish them.
