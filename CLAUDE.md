# apex-builder-mcp — Claude Code context

MCP server (Python 3.12+, FastMCP) for Oracle APEX 24.2 on Oracle DB 19c. Tools are organized by category and lazy-loaded; auth is dual-path (SQLcl saved-connection or oracledb pool).

## Commands

```bash
# Editable install (run inside the repo)
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# Tests
.venv/Scripts/python.exe -m pytest tests/unit -q               # always runs, no DB
.venv/Scripts/python.exe -m pytest tests/integration --integration   # needs live DB

# Lint / type check
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m mypy src
```

After editing source: **kill running `apex-builder-mcp.exe` processes** so MCP clients respawn with the new code. Editable install means `src/` is live, but the long-running server process holds the previous import.

## Layout

```
src/apex_builder_mcp/
├── __main__.py            # FastMCP entrypoint
├── connection/            # profile, credential (keyring), pool (oracledb),
│                          # sqlcl_subprocess (sql -name <conn>),
│                          # sqlcl_metadata (connmgr show), auth_mode, state
├── tools/                 # MCP tool handlers, one module per domain
│   ├── connection.py      # apex_connect / disconnect / status / list_profiles
│   ├── _read_helpers.py   # shared read query funcs (branch on auth_mode)
│   ├── _write_helpers.py  # shared write funcs (env gating, ACL snapshot)
│   └── …                  # pages, regions, items, buttons, processes, etc.
├── registry/              # @apex_tool decorator + Category enum + LazyToolLoader
├── schema/                # pydantic Profile + ApexBuilderError dataclass
├── apex_api/              # PL/SQL wrappers (wwv_flow_imp_page, etc.)
├── audit/                 # ACL snapshot/diff/restore + audit log
└── guard/                 # SQL guard, env guard, dry-run, runtime checks
```

Profile YAML lives at `~/.apex-builder-mcp/profiles.yaml`.

## Auth model — two modes (default `sqlcl`)

| `auth_mode` | apex_connect does | Keyring? | oracledb pool? |
|---|---|---|---|
| `sqlcl` *(default, recommended)* | `verify_sqlcl_connection(profile.sqlcl_name)` | No | No |
| `password` | `get_password()` from OS keyring → `oracledb.create_pool(...)` | Yes (`apex_setup_profile`) | Yes |

In `sqlcl` mode all read/write helpers route through `run_sqlcl(profile.sqlcl_name, sql)` which calls `sql -name <conn>` — SQLcl resolves credentials from its own encrypted store. **`pool_connected: False` in `apex_status` is expected in this mode** (interpret via the `auth_mode` field).

Never duplicate a password into the keyring unless you have a measured reason to need the oracledb pool path.

## Tool conventions

- Register with `@apex_tool(name="apex_xxx", category=Category.YYY)` from `registry/tool_decorator.py`.
- Raise `ApexBuilderError(code=..., message=..., suggestion=..., metadata=...)` — these become structured MCP errors. The `code` is the public contract.
- Lazy categories (8 total): `CORE`, `LAZY_META`, `AUDIT_BASICS`, `AUDIT_AUX` always load (= 13 tools at boot); `READ_DB`, `READ_APEX` auto-load post-connect (+21 tools); `WRITE_CORE` (includes `apex_generate_*`), `BRIDGES` require explicit `apex_load_category(name=...)`.
- Write tools must respect `profile.environment` gating: PROD = reject, TEST = dry-run unless explicit apply, DEV = full write. See `_write_helpers.py`.

## Gotchas

- **FastMCP 3.2.4 does NOT emit `notifications/tools/list_changed`** when `add_tool`/`remove_tool` is called on a running server (verified — no such code path in fastmcp/server/**). Tools loaded mid-session via `apex_connect` (auto-loads READ_DB/READ_APEX) or `apex_load_category` register server-side but stay invisible to MCP clients that cache the handshake tool list (Claude Code, as of 2026-05-19). **Workaround:** set `APEX_BUILDER_EAGER_CATEGORIES` in the server's env (`.mcp.json`):
  - `all` — every category visible at handshake (recommended for build sessions)
  - `read_db,read_apex,write_core` — comma-separated names
  - unset — keeps the original lazy behavior (only safe for clients that honor `tools/list_changed`)
- **Never call `getpass`, `input()`, or any blocking stdin read from a tool.** MCP stdio transport pipes stdin from a JSON-RPC client; reads block forever. Use `prompt_if_missing=False` and raise `CRED_MISSING` instead.
- `apex_connect` is wrapped in an overall budget (`APEX_BUILDER_CONNECT_TIMEOUT_SEC`, default 60s) and tracks `stage` for the timeout error. `oracledb.create_pool` uses `tcp_connect_timeout` (`APEX_BUILDER_TCP_CONNECT_TIMEOUT_SEC`, default 10s).
- SQLcl 26.1 emits **plain text** to non-TTY pipes (no ANSI). `_parse_connmgr_show` still strips ANSI defensively.
- `apex_application_install.generate_offset` + reimport is fragile for full apps with shared components (FK errors) — see Phase 0 report. Use incremental write tools instead.
- No native APEX 24.2 procs for `apex_copy_page`, `apex_update_region`, `apex_update_item`, `apex_delete_button`, `apex_add_page_js`, `apex_add_app_css` — workarounds documented in the respective tool module docstrings.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `APEX_BUILDER_EAGER_CATEGORIES` | unset | Pre-load lazy categories at server startup so they're visible at MCP handshake. Values: `all` \| comma list (e.g. `read_db,read_apex,write_core`) |
| `APEX_BUILDER_CONNECT_TIMEOUT_SEC` | 60 | Overall budget for `apex_connect` (min 5). On timeout error includes the active stage. |
| `APEX_BUILDER_TCP_CONNECT_TIMEOUT_SEC` | 10 | `oracledb.create_pool` TCP connect timeout (password mode only). |

## Companion repo

User-facing docs, skills, and the workspace template (`.mcp.json`, downstream `CLAUDE.md`, `AGENTS.md`) live at `oracle-apex-skill-builder` (separate repo, not a submodule).

## References

- `README.md` — install + run
- `docs/PHASE_0_REPORT.md`, `docs/PLAN_2A_REPORT.md`, `docs/PLAN_2B_REPORT.md` — design decisions and verification gates
- `scripts/grant_mcp_user.sql` — least-privilege DB user setup
