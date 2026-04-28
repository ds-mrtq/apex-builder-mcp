-- apex-builder-mcp/scripts/grant_mcp_user.sql
--
-- Setup a dedicated DB user for apex-builder-mcp with minimum grants required
-- for Phase 0 + Phase 1 read tools + Phase 2 DEV writes.
--
-- Run as SYS or schema-admin on each environment.
-- Replace :mcp_user, :mcp_password, :app_schema before running.
--
-- Phase 0 grants (read + ACL + DBMS_LOCK + ALL_ARGUMENTS):
--   - SELECT on APEX_* views
--   - EXECUTE on dbms_lock
--   - SELECT on all_arguments (already granted to PUBLIC by default)
--
-- Phase 2 additional grants (DEV-write only — apply on DEV profile only):
--   - EXECUTE on wwv_flow_imp_page (CAUTION: internal package, DEV-only)
--   - EXECUTE on wwv_flow_imp
--   - EXECUTE on apex_application_install
--   - EXECUTE on apex_acl

-- ===========================================================================
-- Phase 0 grants — read + audit
-- ===========================================================================

create user &mcp_user identified by &mcp_password;

grant create session to &mcp_user;

-- APEX views (read)
grant select on apex_applications to &mcp_user;
grant select on apex_application_pages to &mcp_user;
grant select on apex_application_page_regions to &mcp_user;
grant select on apex_application_page_items to &mcp_user;
grant select on apex_application_page_proc to &mcp_user;
grant select on apex_application_page_buttons to &mcp_user;
grant select on apex_workspaces to &mcp_user;
grant select on apex_workspace_apex_users to &mcp_user;
grant select on apex_appl_acl_user_roles to &mcp_user;
grant select on apex_release to &mcp_user;

-- DB metadata
grant select on dba_objects to &mcp_user;       -- or all_objects if more restrictive
grant select on dba_tables to &mcp_user;        -- or all_tables
grant select on dba_tab_columns to &mcp_user;
grant select on dba_indexes to &mcp_user;
grant select on dba_constraints to &mcp_user;
grant select on dba_dependencies to &mcp_user;

-- DBMS_LOCK for ID allocator
grant execute on dbms_lock to &mcp_user;

-- ===========================================================================
-- Phase 2 grants — DEV-only writes (uncomment after Phase 0 PASS)
-- ===========================================================================
-- grant execute on apex_240200.wwv_flow_imp_page to &mcp_user;
-- grant execute on apex_240200.wwv_flow_imp to &mcp_user;
-- grant execute on apex_240200.wwv_flow_application_install to &mcp_user;
-- grant execute on apex_240200.apex_acl to &mcp_user;

-- Schema-specific table SELECT/INSERT/UPDATE/DELETE — only for DEV apps
-- (not granted globally; per-table per-DEV-app via session)

-- ===========================================================================
-- Explicitly DENY destructive privileges
-- ===========================================================================
-- Note: NOT granting CREATE TABLE, ALTER, DROP, CREATE PROCEDURE, GLOBAL TEMP TABLE,
-- DBA, RESOURCE roles, db link grants, etc.
-- This is least-privilege by exclusion.

prompt MCP user setup complete. Verify with: select * from session_privs;
