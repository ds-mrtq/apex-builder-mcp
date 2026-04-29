"""Wrap internal wwv_flow_imp_page.create_*/remove_* calls in import session.

Phase 0 finding: wwv_flow_imp_page.* requires g_security_group_id which is
set by wwv_flow_imp.import_begin. Without import session context, internal
API calls fail with ORA-20001 from WWV_IMP_UTIL line 142.

Use this helper for ALL write tools (apex_add_page/region/item, apex_delete_*).
"""
from __future__ import annotations

from dataclasses import dataclass

from apex_builder_mcp.connection.sqlcl_subprocess import has_db_error, run_sqlcl


class ImportSessionError(RuntimeError):
    """Raised when import session SQL fails."""


@dataclass(frozen=True)
class ImportSession:
    sqlcl_conn: str
    workspace_id: int
    application_id: int
    schema: str
    apex_release: str = "24.2.12"
    apex_version_yyyy_mm_dd: str = "2024.11.30"

    def execute(self, plsql_body: str) -> None:
        """Run a PL/SQL block wrapped in import_begin/import_end + commit.

        plsql_body must be the contents of a `begin ... end;` block (without
        the begin/end keywords themselves; this helper provides them).
        """
        sql = f"""set echo off feedback on define off verify off
whenever sqlerror exit sql.sqlcode rollback
begin
  wwv_flow_imp.import_begin(
    p_version_yyyy_mm_dd => '{self.apex_version_yyyy_mm_dd}',
    p_release => '{self.apex_release}',
    p_default_workspace_id => {self.workspace_id},
    p_default_application_id => {self.application_id},
    p_default_id_offset => 0,
    p_default_owner => '{self.schema}'
  );
end;
/
begin
{plsql_body}
end;
/
begin
  wwv_flow_imp.import_end(
    p_auto_install_sup_obj => nvl(wwv_flow_application_install.get_auto_install_sup_obj, false)
  );
  commit;
end;
/
exit
"""
        result = run_sqlcl(self.sqlcl_conn, sql, timeout=180)
        if result.rc != 0 or has_db_error(result.stdout):
            raise ImportSessionError(
                f"import session failed (rc={result.rc}):\n"
                f"{result.cleaned}\nstderr:\n{result.stderr}"
            )
