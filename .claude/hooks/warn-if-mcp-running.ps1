#requires -Version 5.1
# PostToolUse hook: warn (do not block) when an Edit/Write touches src/ while
# an apex-builder-mcp.exe process is running. Editable install means edits
# are "live" on next spawn, but the running process holds the old import —
# the user typically needs to kill it before changes take effect.
#
# Receives Claude Code hook JSON on stdin. Exits 0 always (this is a nudge,
# not a gate).

$ErrorActionPreference = 'Stop'

try {
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { exit 0 }
    $payload = $raw | ConvertFrom-Json
} catch {
    exit 0  # malformed input — silently skip, never block on a hook bug
}

$fp = $payload.tool_input.file_path
if (-not $fp) { exit 0 }

# Only care about edits under apex-builder-mcp/src/**
$normalized = ($fp -replace '\\', '/').ToLower()
if ($normalized -notmatch '/apex-builder-mcp/src/') { exit 0 }
if ($normalized -notmatch '\.py$') { exit 0 }

$procs = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like '*apex-builder*' })

if ($procs.Count -eq 0) { exit 0 }

$pids = ($procs | ForEach-Object { $_.Id }) -join ', '
Write-Host "[apex-builder-mcp hook] Edit landed in src/ but $($procs.Count) MCP server process(es) are running (PIDs: $pids). Kill them so the next MCP-client call respawns with your change:"
Write-Host "  Get-Process -Name '*apex-builder*' | Stop-Process -Force"
exit 0
