# Gate 1: FastMCP tools/list_changed in Claude Code + Codex CLI

## Status: Server-side automated PASS. Manual CLI verification: PENDING USER RUN.

## Server-side automated test
Already passing in `tests/unit/test_entrypoint.py::test_load_category_registers_tools_with_server` — proves `loader.load(WRITE_CORE)` triggers `server.add_tool()` on the shared FastMCP instance. FastMCP 3.2.4 auto-emits `tools/list_changed` notification on `add_tool`/`remove_tool`.

## Manual CLI verification (REQUIRED for Gate 1 to fully PASS)

### Setup

Add to a sandbox project's `.mcp.json`:

```json
{
  "mcpServers": {
    "apex-builder": {
      "command": "D:/repos/apex-builder-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "apex_builder_mcp"]
    }
  }
}
```

### Verify in Claude Code CLI

1. Open Claude Code in the sandbox project.
2. Run: `claude mcp list` → see `apex-builder` connected.
3. To LLM: "list available apex tools" — should see only always-loaded (apex_status, apex_categories_list, apex_snapshot_acl, apex_list_profiles, etc. — 13 tools).
4. To LLM: "call apex_load_category with name='write_core'".
5. To LLM: "call apex_categories_list" — verify `loaded` includes `write_core`.

### Verify in Codex CLI

Same 5 steps but in a Codex session.

### Pass criteria

- ✅ Both CLIs show always-loaded tools at startup
- ✅ `apex_load_category("write_core")` succeeds without error in both
- ✅ `apex_categories_list` after load shows `write_core` in loaded set
- ✅ No errors in MCP server stderr

### Fail criteria (any one = FAIL)

- ❌ CLI hangs after notification
- ❌ `apex_categories_list` after load does NOT show new category
- ❌ Server logs notification fired but client UI doesn't update

## On FAIL

Document failing CLI + version + FastMCP version + server stderr. Fallback: set env var `APEX_BUILDER_LAZY=0` (force load all categories at startup; not yet implemented but easy follow-up).
