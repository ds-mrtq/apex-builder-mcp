# Gate 4: SQLcl named connection metadata reader

## Run

```bash
export APEX_TEST_SQLCL_NAME="ereport_test8001"
cd /d/repos/apex-builder-mcp
./.venv/Scripts/pytest.exe tests/integration/test_sqlcl_metadata_real.py -v --integration -s
```

## Known limitation (anticipated FAIL on user's setup)

`tests/unit/test_sqlcl_metadata.py` (5 tests, all passing in unit suite) verifies parsing of the **VS Code SQL Developer Extension** `connections.json` format.

User's machine uses **SQLcl 26.1 standalone** with proprietary connection store at `~/AppData/Roaming/SQLcl/` — NOT the VS Code Extension JSON format. The current `_default_connections_file()` only looks at:
1. `$APPDATA/Code/User/globalStorage/oracle.sql-developer/connections.json`
2. `~/.oracle/sqlcl/connections.json`

Neither exists on this machine.

## Workaround already verified

Connection metadata can be extracted directly via `sql connmgr show <name>` subprocess. Sample output for `ereport_test8001`:
```
Name: ereport_test8001
Connect String: ebstest.vicemhatien.vn:1522/TEST1
User: ereport
Password: ******
autoCommit: false
```

## Recommended Plan 2A first task

Add `_read_via_connmgr_subprocess()` fallback that runs `sql /nolog` + `connmgr show <name>` + parses the human-readable output. Treat as last resort after the JSON file checks fail.

## Pass criteria for THIS gate (current implementation)

- [ ] (PASS only if VS Code Extension format is in use): metadata extracted with non-empty host/port/service/user
- [x] No password leak: `hasattr(md, "password") == False`

## Outcome on user's machine

**EXPECTED FAIL** with `FileNotFoundError`. Documented; not a blocker for Phase 0 because connection metadata for `ereport_test8001` was confirmed via direct `connmgr show` invocation.

The Phase 0 verification report should classify Gate 4 as **PARTIAL — JSON format reader works, SQLcl 26 format reader needs Plan 2A follow-up**.
