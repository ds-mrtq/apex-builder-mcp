---
name: ship-apex-builder-fix
description: Ship an apex-builder-mcp fix end-to-end — kill running MCP processes, rebuild venv editable install, verify version, run pytest + optional live smoke, commit with structured message, push to origin/main. Use when you've made a code change with a version bump and want to ship it in one motion.
disable-model-invocation: true
---

# /ship-apex-builder-fix

Encapsulates the ship pattern repeated across the 2026-05-19 hang-fix series (commits daac639, 55a8e24, c736c87). Use this when:

- You've edited `src/apex_builder_mcp/**`
- You've bumped `pyproject.toml` version
- You want to ship to `origin/main` in one motion

## Why this exists

Editable install (`pip install -e .`) means `src/` is live, but long-running `apex-builder-mcp.exe` processes hold the previous import. The exe file itself is also locked while a process holds it. So every ship cycle needs: **kill → reinstall → verify → test → commit → push**. Forgetting kill leads to `WinError 32 file locked`.

## Steps (run in order; stop on the first failure)

### 1. Confirm pre-ship state

```bash
cd D:/repos/apex-builder-mcp
git status                   # diff should be sensible, no surprise files
git log --oneline -3         # know what HEAD is
.venv/Scripts/python.exe -m pytest tests/unit -q   # all unit tests pass
```

If any unit test fails, **stop** — don't ship a regression.

### 2. Kill running MCP server processes

```powershell
Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -like '*apex-builder*' } |
  ForEach-Object { Write-Host "Stopping PID $($_.Id)"; Stop-Process -Id $_.Id -Force }
```

This terminates any Claude Code session's running MCP server. They'll respawn on next call.

### 3. Rebuild editable install

```bash
.venv/Scripts/python.exe -m pip install -e . --quiet
.venv/Scripts/python.exe -c "import importlib.metadata; print('version:', importlib.metadata.version('apex-builder-mcp'))"
```

The printed version must match `pyproject.toml`. If you see a stale version, check for `~pex-builder-mcp` orphan dirs in `.venv/Lib/site-packages/` and remove them.

### 4. Live smoke (optional but recommended)

Run a tiny scenario that touches the changed code:

```powershell
& "D:/repos/apex-builder-mcp/.venv/Scripts/python.exe" -c @'
# example: prove apex_connect works without keyring on auth_mode=sqlcl
from apex_builder_mcp.tools.connection import apex_connect, apex_disconnect
result = apex_connect(profile_name="DEV1")
assert result["state"] == "CONNECTED:DEV"
print("smoke PASS:", result)
apex_disconnect()
'@
```

### 5. Commit

Use HEREDOC for multi-line body. Body should explain **why** (the bug class + how the fix addresses it), not what (the diff already shows what).

```bash
git add <specific files>     # NEVER git add -A
git commit -m "$(cat <<'EOF'
<type>: <subject under 70 chars>

<paragraph: why this change, what was broken, what evidence proves it works>

Tests: <N> passed. <new tests added: ...>
Version <old> -> <new>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 6. Push

```bash
git push origin main
```

Confirm output shows `<old-sha>..<new-sha>  main -> main`.

### 7. Update downstream template if API surface or env vars changed

If the change adds/changes a public env var, MCP tool, or workflow that downstream consumers need to know:

- Update `oracle-apex-skill-builder/templates/workspace/.mcp.json` (env block)
- Update `oracle-apex-skill-builder/docs/troubleshooting.md` (new entry)
- Commit in that repo too (no remote yet — local only)

## What this skill is NOT for

- Don't use this for docs-only changes — just commit + push directly
- Don't use this if version isn't bumped — kill+rebuild is wasted work
- Don't use this for in-progress / experimental commits — push to a branch first
