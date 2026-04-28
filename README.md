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
