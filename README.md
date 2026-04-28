# apex-builder-mcp

MCP server for Oracle APEX 24.2 building on Oracle DB 19c.

## Install (dev)

```bash
pip install -e ".[dev]"
```

## Run tests

```bash
pytest tests/unit/                          # unit only
pytest tests/integration/ -m integration    # integration (needs DB DEV)
```

## Status

Phase 0 — Foundation. See `docs/PHASE_0_REPORT.md` for verification gate outcomes.

## DB User Setup (Phase 0)

Before connecting, create a dedicated DB user:

```bash
sqlplus sys/password@DEV1 as sysdba
```

```sql
@scripts/grant_mcp_user.sql
-- Prompts for: mcp_user, mcp_password, app_schema
```

Then verify the user has only expected privileges:

```sql
select privilege from session_privs;
-- Should NOT include CREATE TABLE, ALTER, DROP, etc.
```
