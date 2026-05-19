---
name: apex-mcp-surface-check
description: Diagnose which tools an apex-builder-mcp instance exposes at MCP handshake. Use when symptoms include "tool not found", "ToolSearch No matching deferred tools", apex_load_category succeeds but the client can't see new tools, FastMCP tools/list_changed suspicion, or any time you need to know what apex-builder-mcp surface is actually wired in the current configuration. Outputs total tool count, category breakdown, and presence of probe tools (apex_run_sql, apex_create_app, apex_add_page, apex_list_apps, etc.).
---

# /apex-mcp-surface-check

Quick diagnostic for the canonical "is tool X visible?" question.

## When to invoke

- Claude Code reports "tool not found" for a tool that should exist (e.g. `apex_run_sql`, `apex_create_app`)
- `apex_load_category(name=...)` returns success but the new tools aren't callable
- Auditing whether `APEX_BUILDER_EAGER_CATEGORIES` env is being honored
- Before reporting a "tool missing" bug — rule out config first

## What it does

Spawns a fresh `build_server()` instance in the apex-builder-mcp venv, calls `server.list_tools()`, reports counts + probes.

This is **server-side** state. It tells you what tools the MCP server *would* register. If a running MCP client sees fewer tools, the gap is in client-side caching (FastMCP 3.2.4 doesn't emit `notifications/tools/list_changed` — see `CLAUDE.md` § Gotchas).

## Script

Run inline via the venv Python. Honors the `APEX_BUILDER_EAGER_CATEGORIES` env var of the current shell — set it before invoking to simulate a different deployment.

```powershell
# Default config (no eager-load) — only 13 always-loaded
& "D:/repos/apex-builder-mcp/.venv/Scripts/python.exe" -c @'
import asyncio, os
from apex_builder_mcp.__main__ import build_server
from apex_builder_mcp.registry.tool_decorator import get_registered_tools

print(f"APEX_BUILDER_EAGER_CATEGORIES = {os.environ.get('APEX_BUILDER_EAGER_CATEGORIES', '<unset>')!r}")
server = build_server()
tools = asyncio.run(server.list_tools())
names = sorted(t.name for t in tools)

# Category breakdown
by_cat = {}
for rt in get_registered_tools():
    by_cat.setdefault(rt.category.value, []).append(rt.name)
visible_set = set(names)
print(f"\nTotal visible at handshake: {len(names)}")
print("Category breakdown (visible / total):")
for cat in sorted(by_cat):
    in_cat = by_cat[cat]
    vis = sum(1 for n in in_cat if n in visible_set)
    print(f"  {cat:15s}: {vis:3d} / {len(in_cat)}")

# Probes — commonly-asked-about tools
print("\nProbe tools:")
for probe in ("apex_status", "apex_connect", "apex_list_apps", "apex_run_sql",
              "apex_describe_table", "apex_create_app", "apex_add_page",
              "apex_add_region", "apex_generate_crud", "apex_apply_layout_spec",
              "apex_load_category", "apex_categories_list"):
    print(f"  {probe:30s}: {'PRESENT' if probe in visible_set else 'MISSING'}")
'@
```

## Interpreting output

| Result | Meaning |
|---|---|
| Total = 13, only `core`/`lazy_meta`/`audit_*` populated | Default lazy mode, no eager-load. After `apex_connect` server-side would load read_db/read_apex but the client never sees it (FastMCP gap). Recommend setting `APEX_BUILDER_EAGER_CATEGORIES=all` in `.mcp.json`. |
| Total ≈ 34, `read_db` + `read_apex` populated, write_* empty | Eager `read_db,read_apex` is set. Add `write_core` to env to enable write tools. |
| Total = 67, all categories populated | `APEX_BUILDER_EAGER_CATEGORIES=all` — full build surface. |
| Probe `MISSING` but category visible/total shows it should be loaded | Investigate the tool's `@apex_tool(category=...)` decorator. |
| Probe shows as visible here but Claude Code says "tool not found" | Client-side cache gap. Restart Claude Code session so the MCP server respawns. |

## Companion checks

- `apex_status` (if you can call it) — tells you connection state + auth_mode
- `apex_categories_list` (always loaded) — server-side view of which categories are loaded right now

If a category appears in `apex_categories_list` as `currently_loaded: true` but the corresponding tools are MISSING in this check, the loader bootstrap path is broken — investigate `__main__.build_server` and `LazyToolLoader._fire_notify`.
