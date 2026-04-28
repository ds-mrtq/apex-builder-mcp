-- apex-builder-mcp/scripts/revoke_mcp_user.sql
-- Drop the dedicated MCP user. Use to clean up after testing.

drop user &mcp_user cascade;

prompt MCP user dropped.
