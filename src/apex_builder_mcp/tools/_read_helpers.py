"""Shared read helpers — branch on auth_mode for SQLcl-vs-pool reads.

Mirror of `_write_helpers.py` for read tools that previously assumed the
oracledb pool was always available. With `auth_mode=sqlcl` (default), reads
go through the SQLcl subprocess path using pipe-separated output parsing;
with `auth_mode=password`, the existing oracledb pool path is used.

Each public ``query_*`` function branches on ``resolve_auth_mode(profile)``.
Both paths must return identical-shape values so calling tools are oblivious
to which path was taken.

Output separator
----------------
SQLcl path renders pipe-separated rows using ``'|||'`` (triple pipe). Three
pipes is sufficiently rare in real APEX metadata (workspace names, view
columns, etc.) to avoid collisions while remaining easy to grep for.

Coverage
--------
Plan 2A baseline (6): list_lovs, search_objects, dependencies,
workspace_users, app_details, validate_app.

Plan 2A read-tool extension (13):
  apex_list_apps, apex_describe_app, apex_list_pages, apex_describe_page,
  apex_describe_acl, apex_get_page_details, apex_list_regions,
  apex_list_items, apex_list_processes, apex_list_dynamic_actions,
  apex_list_tables, apex_describe_table, apex_get_source.

Deferred
--------
``apex_run_sql`` still requires the oracledb pool — sqlcl path deferred due
to arbitrary SELECT parsing complexity (user supplies the SELECT, so no
pipe-separated trick). Under sqlcl-only mode, callers should use
``apex_search_objects``, ``apex_describe_table``, ``apex_get_source``, etc.
"""
from __future__ import annotations

from typing import Any

from apex_builder_mcp.connection.auth_mode import AuthMode, resolve_auth_mode
from apex_builder_mcp.connection.sqlcl_subprocess import run_sqlcl
from apex_builder_mcp.schema.errors import ApexBuilderError
from apex_builder_mcp.schema.profile import Profile

SEP = "|||"


def _get_pool() -> Any:
    """Lazy import to avoid circular dep at module load time."""
    from apex_builder_mcp.tools.connection import _get_or_create_pool

    return _get_or_create_pool()


def _sqlcl_or_raise(profile: Profile, sql: str, *, tool_label: str) -> str:
    result = run_sqlcl(profile.sqlcl_name, sql, timeout=30)
    if result.rc != 0:
        raise ApexBuilderError(
            code="SQLCL_QUERY_FAIL",
            message=f"{tool_label} via SQLcl failed: rc={result.rc}",
            suggestion=f"Check sqlcl saved connection '{profile.sqlcl_name}'",
        )
    return result.cleaned


def _split_row(line: str, expected_parts: int) -> list[str] | None:
    """Return stripped parts of a pipe-separated row, or None if malformed."""
    if SEP not in line:
        return None
    parts = [p.strip() for p in line.split(SEP)]
    if len(parts) != expected_parts:
        return None
    return parts


def _to_int_or_none(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 1. apex_list_lovs
# ---------------------------------------------------------------------------


def _query_lovs_sqlcl(profile: Profile, app_id: int) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select lov_id||'{SEP}'||list_of_values_name||'{SEP}'||lov_type "
        f"from apex_application_lovs where application_id = {app_id} "
        f"order by list_of_values_name;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_lovs")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 3)
        if parts is None:
            continue
        if not parts[0].isdigit():
            continue
        rows.append(
            {
                "lov_id": int(parts[0]),
                "name": parts[1],
                "lov_type": parts[2],
            }
        )
    return rows


def _query_lovs_pool(app_id: int) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select lov_id, list_of_values_name, lov_type "
            "from apex_application_lovs where application_id = :a "
            "order by list_of_values_name",
            a=app_id,
        )
        return [
            {"lov_id": r[0], "name": r[1], "lov_type": r[2]}
            for r in cur.fetchall()
        ]


def query_lovs(profile: Profile, app_id: int) -> list[dict[str, Any]]:
    """List LOVs for an APEX application. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_lovs_sqlcl(profile, app_id)
    return _query_lovs_pool(app_id)


# ---------------------------------------------------------------------------
# 2. apex_search_objects
# ---------------------------------------------------------------------------


def _query_search_objects_sqlcl(
    profile: Profile,
    pattern: str,
    object_types: list[str] | None,
) -> list[dict[str, Any]]:
    pat_esc = pattern.upper().replace("'", "''")
    if object_types:
        types_clause = ", ".join(f"'{t.replace(chr(39), chr(39) * 2)}'" for t in object_types)
        type_filter = f"and object_type in ({types_clause}) "
    else:
        type_filter = ""
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select owner||'{SEP}'||object_name||'{SEP}'||object_type||'{SEP}'||"
        f"status||'{SEP}'||to_char(last_ddl_time, 'YYYY-MM-DD HH24:MI:SS') "
        f"from all_objects where object_name like '{pat_esc}' "
        f"{type_filter}"
        "order by owner, object_name;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="search_objects")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 5)
        if parts is None:
            continue
        rows.append(
            {
                "owner": parts[0],
                "object_name": parts[1],
                "object_type": parts[2],
                "status": parts[3],
                "last_ddl_time": parts[4] if parts[4] else None,
            }
        )
    return rows


def _query_search_objects_pool(
    pattern: str,
    object_types: list[str] | None,
    max_rows: int,
) -> list[dict[str, Any]]:
    pool = _get_pool()
    pat_upper = pattern.upper()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if object_types:
            placeholders = ",".join(f":t{i}" for i in range(len(object_types)))
            sql = (
                "select owner, object_name, object_type, status, last_ddl_time "
                "from all_objects "
                "where object_name like :pat "
                f"and object_type in ({placeholders}) "
                "order by owner, object_name"
            )
            binds: dict[str, Any] = {"pat": pat_upper}
            for i, t in enumerate(object_types):
                binds[f"t{i}"] = t
            cur.execute(sql, **binds)
        else:
            cur.execute(
                "select owner, object_name, object_type, status, last_ddl_time "
                "from all_objects "
                "where object_name like :pat "
                "order by owner, object_name",
                pat=pat_upper,
            )
        return [
            {
                "owner": r[0],
                "object_name": r[1],
                "object_type": r[2],
                "status": r[3],
                "last_ddl_time": str(r[4]) if r[4] else None,
            }
            for r in cur.fetchmany(max_rows)
        ]


def query_search_objects(
    profile: Profile,
    pattern: str,
    object_types: list[str] | None,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Search Oracle objects by name pattern. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        rows = _query_search_objects_sqlcl(profile, pattern, object_types)
        return rows[:max_rows]
    return _query_search_objects_pool(pattern, object_types, max_rows)


# ---------------------------------------------------------------------------
# 3. apex_dependencies
# ---------------------------------------------------------------------------


def _query_dependencies_sqlcl(
    profile: Profile,
    object_name: str,
    object_type: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    name_esc = object_name.upper().replace("'", "''")
    type_filter_uses = (
        f"and type = '{object_type.upper()}' " if object_type else ""
    )
    type_filter_used_by = (
        f"and referenced_type = '{object_type.upper()}' " if object_type else ""
    )

    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"prompt {SEP}USES_BEGIN{SEP}\n"
        f"select owner||'{SEP}'||name||'{SEP}'||type||'{SEP}'||"
        f"referenced_owner||'{SEP}'||referenced_name||'{SEP}'||referenced_type "
        f"from all_dependencies where name = '{name_esc}' "
        f"{type_filter_uses}"
        "order by referenced_owner, referenced_name;\n"
        f"prompt {SEP}USED_BY_BEGIN{SEP}\n"
        f"select owner||'{SEP}'||name||'{SEP}'||type||'{SEP}'||"
        f"referenced_owner||'{SEP}'||referenced_name||'{SEP}'||referenced_type "
        f"from all_dependencies where referenced_name = '{name_esc}' "
        f"{type_filter_used_by}"
        "order by owner, name;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="dependencies")

    uses: list[dict[str, Any]] = []
    used_by: list[dict[str, Any]] = []
    section = "uses"
    for line in body.splitlines():
        s = line.strip()
        if f"{SEP}USES_BEGIN{SEP}" in s:
            section = "uses"
            continue
        if f"{SEP}USED_BY_BEGIN{SEP}" in s:
            section = "used_by"
            continue
        parts = _split_row(s, 6)
        if parts is None:
            continue
        record = {
            "owner": parts[0],
            "name": parts[1],
            "type": parts[2],
            "referenced_owner": parts[3],
            "referenced_name": parts[4],
            "referenced_type": parts[5],
        }
        if section == "uses":
            uses.append(record)
        else:
            used_by.append(record)
    return uses, used_by


def _query_dependencies_pool(
    object_name: str,
    object_type: str | None,
    max_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pool = _get_pool()
    obj_upper = object_name.upper()
    type_upper = object_type.upper() if object_type else None
    with pool.acquire() as conn:
        cur = conn.cursor()
        if type_upper:
            cur.execute(
                """
                select owner, name, type,
                       referenced_owner, referenced_name, referenced_type
                  from all_dependencies
                 where name = :n and type = :t
                 order by referenced_owner, referenced_name
                """,
                n=obj_upper, t=type_upper,
            )
        else:
            cur.execute(
                """
                select owner, name, type,
                       referenced_owner, referenced_name, referenced_type
                  from all_dependencies
                 where name = :n
                 order by referenced_owner, referenced_name
                """,
                n=obj_upper,
            )
        uses = [
            {
                "owner": r[0],
                "name": r[1],
                "type": r[2],
                "referenced_owner": r[3],
                "referenced_name": r[4],
                "referenced_type": r[5],
            }
            for r in cur.fetchmany(max_rows)
        ]
        if type_upper:
            cur.execute(
                """
                select owner, name, type,
                       referenced_owner, referenced_name, referenced_type
                  from all_dependencies
                 where referenced_name = :n and referenced_type = :t
                 order by owner, name
                """,
                n=obj_upper, t=type_upper,
            )
        else:
            cur.execute(
                """
                select owner, name, type,
                       referenced_owner, referenced_name, referenced_type
                  from all_dependencies
                 where referenced_name = :n
                 order by owner, name
                """,
                n=obj_upper,
            )
        used_by = [
            {
                "owner": r[0],
                "name": r[1],
                "type": r[2],
                "referenced_owner": r[3],
                "referenced_name": r[4],
                "referenced_type": r[5],
            }
            for r in cur.fetchmany(max_rows)
        ]
    return uses, used_by


def query_dependencies(
    profile: Profile,
    object_name: str,
    object_type: str | None,
    max_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Show object dependencies (uses + used_by). Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        uses, used_by = _query_dependencies_sqlcl(profile, object_name, object_type)
        return uses[:max_rows], used_by[:max_rows]
    return _query_dependencies_pool(object_name, object_type, max_rows)


# ---------------------------------------------------------------------------
# 4. apex_list_workspace_users
# ---------------------------------------------------------------------------


def _query_workspace_users_sqlcl(
    profile: Profile, workspace: str | None
) -> list[dict[str, Any]]:
    if workspace:
        ws_esc = workspace.upper().replace("'", "''")
        where = f"where workspace_name = '{ws_esc}' "
        order = "order by user_name"
    else:
        where = ""
        order = "order by workspace_name, user_name"
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select workspace_name||'{SEP}'||user_name||'{SEP}'||"
        f"nvl(email, ' ')||'{SEP}'||is_admin||'{SEP}'||"
        f"is_application_developer||'{SEP}'||account_locked||'{SEP}'||"
        f"to_char(date_last_login, 'YYYY-MM-DD HH24:MI:SS') "
        f"from apex_workspace_apex_users {where}{order};\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_workspace_users")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 7)
        if parts is None:
            continue
        rows.append(
            {
                "workspace_name": parts[0],
                "user_name": parts[1],
                "email": parts[2] if parts[2].strip() else None,
                "is_admin": parts[3],
                "is_developer": parts[4],
                "account_locked": parts[5],
                "last_login": parts[6] if parts[6] else None,
            }
        )
    return rows


def _query_workspace_users_pool(workspace: str | None) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if workspace:
            cur.execute(
                """
                select workspace_name, user_name, email,
                       is_admin, is_application_developer,
                       account_locked, date_last_login
                  from apex_workspace_apex_users
                 where workspace_name = :ws
                 order by user_name
                """,
                ws=workspace.upper(),
            )
        else:
            cur.execute(
                """
                select workspace_name, user_name, email,
                       is_admin, is_application_developer,
                       account_locked, date_last_login
                  from apex_workspace_apex_users
                 order by workspace_name, user_name
                """
            )
        return [
            {
                "workspace_name": r[0],
                "user_name": r[1],
                "email": r[2],
                "is_admin": r[3],
                "is_developer": r[4],
                "account_locked": r[5],
                "last_login": str(r[6]) if r[6] else None,
            }
            for r in cur.fetchall()
        ]


def query_workspace_users(
    profile: Profile, workspace: str | None
) -> list[dict[str, Any]]:
    """List APEX workspace users. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_workspace_users_sqlcl(profile, workspace)
    return _query_workspace_users_pool(workspace)


# ---------------------------------------------------------------------------
# 5. apex_get_app_details
# ---------------------------------------------------------------------------

# Single source of truth for the 30-column projection used by both paths so
# the returned `details` dict is identical regardless of auth mode.
_APP_DETAIL_COLS: tuple[str, ...] = (
    "APPLICATION_ID", "APPLICATION_NAME", "ALIAS", "PAGES", "OWNER",
    "WORKSPACE", "VERSION", "BUILD_STATUS", "AVAILABILITY_STATUS",
    "AUTHENTICATION_SCHEME", "PAGE_TEMPLATE", "COMPATIBILITY_MODE",
    "FILE_PREFIX", "LAST_UPDATED_ON", "LAST_UPDATED_BY", "CREATED_ON",
    "CREATED_BY", "THEME_NUMBER", "THEME_STYLE_BY_USER_PREF",
    "APPLICATION_GROUP", "APPLICATION_PRIMARY_LANGUAGE",
    "DEEP_LINKING", "DEBUGGING", "LOGO_TYPE", "LOGO_TEXT",
    "NAV_BAR_TYPE", "FRIENDLY_URL", "BUILD_OPTIONS", "IMAGE_PREFIX",
    "HOME_LINK",
)


def _query_app_details_sqlcl(
    profile: Profile, app_id: int
) -> dict[str, Any] | None:
    # Build a single concat row using nvl(..., ' ') for nullable columns so
    # absent fields don't collapse the row. Date columns use ISO string.
    select_exprs: list[str] = []
    for col in _APP_DETAIL_COLS:
        if col in {"LAST_UPDATED_ON", "CREATED_ON"}:
            # 'T' is a reserved format-element char in Oracle; escape via "T".
            expr = f"""nvl(to_char({col}, 'YYYY-MM-DD"T"HH24:MI:SS'), ' ')"""
        elif col in {"APPLICATION_ID", "PAGES", "THEME_NUMBER"}:
            expr = f"to_char(nvl({col}, -1))"
        else:
            expr = f"nvl(to_char({col}), ' ')"
        select_exprs.append(expr)
    concat_expr = f"||'{SEP}'||".join(select_exprs)

    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767\n"
        f"select {concat_expr} from apex_applications "
        f"where application_id = {app_id};\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="get_app_details")
    expected = len(_APP_DETAIL_COLS)
    for line in body.splitlines():
        parts = _split_row(line.strip(), expected)
        if parts is None:
            continue
        # Verify first part (APPLICATION_ID) parses as int matching the asked id
        first = parts[0].strip()
        if not first.lstrip("-").isdigit():
            continue
        details: dict[str, Any] = {}
        for col, raw in zip(_APP_DETAIL_COLS, parts, strict=True):
            value: Any = raw if raw.strip() else None
            if col == "APPLICATION_ID" and value is not None:
                value = int(value)
            elif col in {"PAGES", "THEME_NUMBER"} and value is not None:
                # Sentinel '-1' marks NULL.
                iv = _to_int_or_none(value)
                value = None if iv == -1 else iv
            details[col] = value
        if details.get("APPLICATION_ID") != app_id:
            continue
        return details
    return None


def _query_app_details_pool(app_id: int) -> dict[str, Any] | None:
    pool = _get_pool()
    cols_sql = ", ".join(c.lower() for c in _APP_DETAIL_COLS)
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            f"select {cols_sql} from apex_applications where application_id = :a",
            a=app_id,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    details = dict(zip(cols, row, strict=False))
    for k, v in list(details.items()):
        if hasattr(v, "isoformat"):
            details[k] = v.isoformat()
    return details


def query_app_details(profile: Profile, app_id: int) -> dict[str, Any] | None:
    """Full app metadata from apex_applications. None if not found.

    Branches on auth_mode.
    """
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_app_details_sqlcl(profile, app_id)
    return _query_app_details_pool(app_id)


# ---------------------------------------------------------------------------
# 6. apex_validate_app
# ---------------------------------------------------------------------------


def _query_validate_app_sqlcl(
    profile: Profile, app_id: int
) -> dict[str, Any] | None:
    """Run the heuristic validation queries via SQLcl, return aggregated data.

    Returns ``None`` when the app does not exist. Otherwise returns a dict:
        {
          "app_meta": (application_name, pages),
          "present_required": set[int],   # of {0, 1}
          "orphans": list[(item_id, item_name, page_id, item_plug_id)],
          "empty_pages": list[(page_id, page_name)],
        }
    """
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        # 0. App existence — emit MARKER + name+pages
        f"prompt {SEP}APP{SEP}\n"
        f"select application_name||'{SEP}'||to_char(nvl(pages, 0)) "
        f"from apex_applications where application_id = {app_id};\n"
        # 1. Required pages
        f"prompt {SEP}REQ{SEP}\n"
        f"select to_char(page_id) from apex_application_pages "
        f"where application_id = {app_id} and page_id in (0, 1);\n"
        # 2. Orphan items
        f"prompt {SEP}ORPHAN{SEP}\n"
        f"select i.item_id||'{SEP}'||i.item_name||'{SEP}'||"
        f"to_char(i.page_id)||'{SEP}'||to_char(i.item_plug_id) "
        f"from apex_application_page_items i "
        f"where i.application_id = {app_id} "
        f"and i.item_plug_id is not null and not exists ("
        f"select 1 from apex_application_page_regions r "
        f"where r.application_id = i.application_id "
        f"and r.region_id = i.item_plug_id);\n"
        # 3. Pages without regions
        f"prompt {SEP}EMPTY{SEP}\n"
        f"select to_char(p.page_id)||'{SEP}'||p.page_name "
        f"from apex_application_pages p "
        f"where p.application_id = {app_id} and p.page_id <> 0 "
        f"and not exists (select 1 from apex_application_page_regions r "
        f"where r.application_id = p.application_id "
        f"and r.page_id = p.page_id);\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="validate_app")

    section = ""
    app_meta: tuple[str, int] | None = None
    present_required: set[int] = set()
    orphans: list[tuple[int, str, int | None, int | None]] = []
    empty_pages: list[tuple[int, str]] = []

    for line in body.splitlines():
        s = line.strip()
        if f"{SEP}APP{SEP}" in s:
            section = "APP"
            continue
        if f"{SEP}REQ{SEP}" in s:
            section = "REQ"
            continue
        if f"{SEP}ORPHAN{SEP}" in s:
            section = "ORPHAN"
            continue
        if f"{SEP}EMPTY{SEP}" in s:
            section = "EMPTY"
            continue
        if not s:
            continue

        if section == "APP":
            parts = _split_row(s, 2)
            if parts is None:
                continue
            page_count = _to_int_or_none(parts[1]) or 0
            app_meta = (parts[0], page_count)
        elif section == "REQ":
            iv = _to_int_or_none(s)
            if iv is not None:
                present_required.add(iv)
        elif section == "ORPHAN":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            iid = _to_int_or_none(parts[0])
            if iid is None:
                continue
            orphans.append(
                (
                    iid,
                    parts[1],
                    _to_int_or_none(parts[2]),
                    _to_int_or_none(parts[3]),
                )
            )
        elif section == "EMPTY":
            parts = _split_row(s, 2)
            if parts is None:
                continue
            pid = _to_int_or_none(parts[0])
            if pid is None:
                continue
            empty_pages.append((pid, parts[1]))

    if app_meta is None:
        return None
    return {
        "app_meta": app_meta,
        "present_required": present_required,
        "orphans": orphans,
        "empty_pages": empty_pages,
    }


def _query_validate_app_pool(app_id: int) -> dict[str, Any] | None:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select application_name, pages from apex_applications "
            "where application_id = :a",
            a=app_id,
        )
        app_row = cur.fetchone()
        if app_row is None:
            return None
        app_meta = (str(app_row[0]), int(app_row[1] or 0))

        cur.execute(
            "select page_id from apex_application_pages "
            "where application_id = :a and page_id in (0, 1)",
            a=app_id,
        )
        present_required = {int(r[0]) for r in cur.fetchall()}

        cur.execute(
            """
            select i.item_id, i.item_name, i.page_id, i.item_plug_id
              from apex_application_page_items i
             where i.application_id = :a
               and i.item_plug_id is not null
               and not exists (
                 select 1 from apex_application_page_regions r
                  where r.application_id = i.application_id
                    and r.region_id = i.item_plug_id
               )
            """,
            a=app_id,
        )
        orphans: list[tuple[int, str, int | None, int | None]] = [
            (
                int(r[0]),
                str(r[1]),
                int(r[2]) if r[2] is not None else None,
                int(r[3]) if r[3] is not None else None,
            )
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            select p.page_id, p.page_name
              from apex_application_pages p
             where p.application_id = :a
               and p.page_id <> 0
               and not exists (
                 select 1 from apex_application_page_regions r
                  where r.application_id = p.application_id
                    and r.page_id = p.page_id
               )
            """,
            a=app_id,
        )
        empty_pages: list[tuple[int, str]] = [
            (int(r[0]), str(r[1])) for r in cur.fetchall()
        ]

    return {
        "app_meta": app_meta,
        "present_required": present_required,
        "orphans": orphans,
        "empty_pages": empty_pages,
    }


def query_validate_app(profile: Profile, app_id: int) -> dict[str, Any] | None:
    """Aggregate raw data for apex_validate_app.

    Returns None when the app does not exist; otherwise returns a dict with
    ``app_meta``, ``present_required``, ``orphans``, ``empty_pages``.
    Branches on auth_mode.
    """
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_validate_app_sqlcl(profile, app_id)
    return _query_validate_app_pool(app_id)


# ===========================================================================
# Plan 2A read-tool extension (13 tools): inspect_apex.py + inspect_db.py
# ===========================================================================
#
# Each block adds three functions:
#   _query_<thing>_sqlcl(profile, ...)  -- SQLcl subprocess path
#   _query_<thing>_pool(...)            -- oracledb pool path
#   query_<thing>(profile, ...)         -- branch on auth_mode
#
# All blocks return identical-shape values for both paths.
# ===========================================================================


# ---------------------------------------------------------------------------
# 7. apex_list_apps
# ---------------------------------------------------------------------------


def _query_list_apps_sqlcl(
    profile: Profile, workspace: str | None
) -> list[dict[str, Any]]:
    if workspace:
        ws_esc = workspace.upper().replace("'", "''")
        where = f"where workspace = '{ws_esc}' "
    else:
        where = ""
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select to_char(application_id)||'{SEP}'||application_name||'{SEP}'||"
        f"nvl(alias, ' ')||'{SEP}'||to_char(nvl(pages, 0)) "
        f"from apex_applications {where}order by application_id;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_apps")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 4)
        if parts is None:
            continue
        app_id = _to_int_or_none(parts[0])
        if app_id is None:
            continue
        rows.append(
            {
                "application_id": app_id,
                "application_name": parts[1],
                "alias": parts[2] if parts[2].strip() else None,
                "pages": _to_int_or_none(parts[3]),
            }
        )
    return rows


def _query_list_apps_pool(workspace: str | None) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if workspace:
            cur.execute(
                "select application_id, application_name, alias, pages "
                "from apex_applications where workspace = :ws "
                "order by application_id",
                ws=workspace.upper(),
            )
        else:
            cur.execute(
                "select application_id, application_name, alias, pages "
                "from apex_applications order by application_id"
            )
        return [
            {
                "application_id": r[0],
                "application_name": r[1],
                "alias": r[2],
                "pages": r[3],
            }
            for r in cur.fetchall()
        ]


def query_list_apps(
    profile: Profile, workspace: str | None
) -> list[dict[str, Any]]:
    """List APEX applications. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_apps_sqlcl(profile, workspace)
    return _query_list_apps_pool(workspace)


# ---------------------------------------------------------------------------
# 8. apex_describe_app
# ---------------------------------------------------------------------------


def _query_describe_app_sqlcl(
    profile: Profile, app_id: int
) -> dict[str, Any] | None:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        # Marker + app row
        f"prompt {SEP}APP{SEP}\n"
        f"select application_name||'{SEP}'||nvl(alias, ' ')||'{SEP}'||"
        f"to_char(nvl(pages, 0))||'{SEP}'||nvl(owner, ' ')||'{SEP}'||"
        f"nvl(authentication_scheme, ' ')||'{SEP}'||nvl(page_template, ' ') "
        f"from apex_applications where application_id = {app_id};\n"
        # Marker + LOV count
        f"prompt {SEP}LOV{SEP}\n"
        f"select to_char(count(*)) from apex_application_lovs "
        f"where application_id = {app_id};\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="describe_app")
    section = ""
    app_row: list[str] | None = None
    lov_count = 0
    for line in body.splitlines():
        s = line.strip()
        if f"{SEP}APP{SEP}" in s:
            section = "APP"
            continue
        if f"{SEP}LOV{SEP}" in s:
            section = "LOV"
            continue
        if not s:
            continue
        if section == "APP":
            parts = _split_row(s, 6)
            if parts is None:
                continue
            app_row = parts
        elif section == "LOV":
            iv = _to_int_or_none(s)
            if iv is not None:
                lov_count = iv
    if app_row is None:
        return None
    return {
        "application_name": app_row[0],
        "alias": app_row[1] if app_row[1].strip() else None,
        "pages": _to_int_or_none(app_row[2]),
        "owner": app_row[3] if app_row[3].strip() else None,
        "authentication_scheme": app_row[4] if app_row[4].strip() else None,
        "page_template": app_row[5] if app_row[5].strip() else None,
        "lov_count": lov_count,
    }


def _query_describe_app_pool(app_id: int) -> dict[str, Any] | None:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select application_name, alias, pages, owner,
                   authentication_scheme, page_template
              from apex_applications where application_id = :a
            """,
            a=app_id,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "select count(*) from apex_application_lovs where application_id = :a",
            a=app_id,
        )
        lov_row = cur.fetchone()
        lov_count = lov_row[0] if lov_row else 0
    return {
        "application_name": row[0],
        "alias": row[1],
        "pages": row[2],
        "owner": row[3],
        "authentication_scheme": row[4],
        "page_template": row[5],
        "lov_count": lov_count,
    }


def query_describe_app(profile: Profile, app_id: int) -> dict[str, Any] | None:
    """Describe an APEX app. None if not found. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_describe_app_sqlcl(profile, app_id)
    return _query_describe_app_pool(app_id)


# ---------------------------------------------------------------------------
# 9. apex_list_pages
# ---------------------------------------------------------------------------


def _query_list_pages_sqlcl(
    profile: Profile, app_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select to_char(page_id)||'{SEP}'||page_name "
        f"from apex_application_pages where application_id = {app_id} "
        f"order by page_id;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_pages")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 2)
        if parts is None:
            continue
        pid = _to_int_or_none(parts[0])
        if pid is None:
            continue
        rows.append({"page_id": pid, "page_name": parts[1]})
    return rows


def _query_list_pages_pool(app_id: int) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select page_id, page_name from apex_application_pages "
            "where application_id = :a order by page_id",
            a=app_id,
        )
        return [{"page_id": r[0], "page_name": r[1]} for r in cur.fetchall()]


def query_list_pages(profile: Profile, app_id: int) -> list[dict[str, Any]]:
    """List pages of an app. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_pages_sqlcl(profile, app_id)
    return _query_list_pages_pool(app_id)


# ---------------------------------------------------------------------------
# 10. apex_describe_page
# ---------------------------------------------------------------------------


def _query_describe_page_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> dict[str, Any] | None:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"prompt {SEP}PAGE{SEP}\n"
        f"select page_name||'{SEP}'||nvl(page_alias, ' ')||'{SEP}'||"
        f"nvl(page_mode, ' ')||'{SEP}'||nvl(requires_authentication, ' ') "
        f"from apex_application_pages where application_id = {app_id} "
        f"and page_id = {page_id};\n"
        f"prompt {SEP}REGIONS{SEP}\n"
        f"select to_char(region_id)||'{SEP}'||region_name||'{SEP}'||"
        f"nvl(display_position, ' ')||'{SEP}'||to_char(nvl(display_sequence, 0)) "
        f"from apex_application_page_regions where application_id = {app_id} "
        f"and page_id = {page_id} order by display_sequence;\n"
        f"prompt {SEP}ITEMS{SEP}\n"
        f"select to_char(item_id)||'{SEP}'||item_name||'{SEP}'||"
        f"nvl(display_as, ' ')||'{SEP}'||to_char(nvl(item_plug_id, -1)) "
        f"from apex_application_page_items where application_id = {app_id} "
        f"and page_id = {page_id} order by item_sequence;\n"
        f"prompt {SEP}BUTTONS{SEP}\n"
        f"select to_char(button_id)||'{SEP}'||button_name||'{SEP}'||"
        f"to_char(nvl(button_plug_id, -1))||'{SEP}'||nvl(button_action, ' ') "
        f"from apex_application_page_buttons where application_id = {app_id} "
        f"and page_id = {page_id};\n"
        f"prompt {SEP}PROCESSES{SEP}\n"
        f"select to_char(process_id)||'{SEP}'||process_name||'{SEP}'||"
        f"nvl(process_type, ' ')||'{SEP}'||to_char(nvl(process_sequence, 0)) "
        f"from apex_application_page_proc where application_id = {app_id} "
        f"and page_id = {page_id} order by process_sequence;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="describe_page")
    section = ""
    page_row: list[str] | None = None
    regions: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    buttons: list[dict[str, Any]] = []
    processes: list[dict[str, Any]] = []

    def _opt_int(s: str) -> int | None:
        iv = _to_int_or_none(s)
        return None if iv == -1 else iv

    for line in body.splitlines():
        s = line.strip()
        if f"{SEP}PAGE{SEP}" in s:
            section = "PAGE"
            continue
        if f"{SEP}REGIONS{SEP}" in s:
            section = "REGIONS"
            continue
        if f"{SEP}ITEMS{SEP}" in s:
            section = "ITEMS"
            continue
        if f"{SEP}BUTTONS{SEP}" in s:
            section = "BUTTONS"
            continue
        if f"{SEP}PROCESSES{SEP}" in s:
            section = "PROCESSES"
            continue
        if not s:
            continue
        if section == "PAGE":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            page_row = parts
        elif section == "REGIONS":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            rid = _to_int_or_none(parts[0])
            if rid is None:
                continue
            regions.append(
                {
                    "region_id": rid,
                    "name": parts[1],
                    "position": parts[2] if parts[2].strip() else None,
                    "sequence": _to_int_or_none(parts[3]),
                }
            )
        elif section == "ITEMS":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            iid = _to_int_or_none(parts[0])
            if iid is None:
                continue
            items.append(
                {
                    "item_id": iid,
                    "name": parts[1],
                    "display_as": parts[2] if parts[2].strip() else None,
                    "region_id": _opt_int(parts[3]),
                }
            )
        elif section == "BUTTONS":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            bid = _to_int_or_none(parts[0])
            if bid is None:
                continue
            buttons.append(
                {
                    "button_id": bid,
                    "name": parts[1],
                    "region_id": _opt_int(parts[2]),
                    "action": parts[3] if parts[3].strip() else None,
                }
            )
        elif section == "PROCESSES":
            parts = _split_row(s, 4)
            if parts is None:
                continue
            pid = _to_int_or_none(parts[0])
            if pid is None:
                continue
            processes.append(
                {
                    "process_id": pid,
                    "name": parts[1],
                    "type": parts[2] if parts[2].strip() else None,
                    "sequence": _to_int_or_none(parts[3]),
                }
            )

    if page_row is None:
        return None
    return {
        "page_name": page_row[0],
        "page_alias": page_row[1] if page_row[1].strip() else None,
        "page_mode": page_row[2] if page_row[2].strip() else None,
        "requires_authentication": page_row[3] if page_row[3].strip() else None,
        "regions": regions,
        "items": items,
        "buttons": buttons,
        "processes": processes,
    }


def _query_describe_page_pool(
    app_id: int, page_id: int
) -> dict[str, Any] | None:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select page_name, page_alias, page_mode, requires_authentication
              from apex_application_pages
             where application_id = :a and page_id = :p
            """,
            a=app_id, p=page_id,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "select region_id, region_name, display_position, display_sequence "
            "from apex_application_page_regions "
            "where application_id = :a and page_id = :p order by display_sequence",
            a=app_id, p=page_id,
        )
        regions = [
            {"region_id": r[0], "name": r[1], "position": r[2], "sequence": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select item_id, item_name, display_as, item_plug_id "
            "from apex_application_page_items "
            "where application_id = :a and page_id = :p order by item_sequence",
            a=app_id, p=page_id,
        )
        items = [
            {"item_id": r[0], "name": r[1], "display_as": r[2], "region_id": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select button_id, button_name, button_plug_id, button_action "
            "from apex_application_page_buttons "
            "where application_id = :a and page_id = :p",
            a=app_id, p=page_id,
        )
        buttons = [
            {"button_id": r[0], "name": r[1], "region_id": r[2], "action": r[3]}
            for r in cur.fetchall()
        ]
        cur.execute(
            "select process_id, process_name, process_type, process_sequence "
            "from apex_application_page_proc "
            "where application_id = :a and page_id = :p order by process_sequence",
            a=app_id, p=page_id,
        )
        processes = [
            {"process_id": r[0], "name": r[1], "type": r[2], "sequence": r[3]}
            for r in cur.fetchall()
        ]
    return {
        "page_name": row[0],
        "page_alias": row[1],
        "page_mode": row[2],
        "requires_authentication": row[3],
        "regions": regions,
        "items": items,
        "buttons": buttons,
        "processes": processes,
    }


def query_describe_page(
    profile: Profile, app_id: int, page_id: int
) -> dict[str, Any] | None:
    """Describe a page (regions, items, buttons, processes). None if not found.

    Branches on auth_mode.
    """
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_describe_page_sqlcl(profile, app_id, page_id)
    return _query_describe_page_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 11. apex_describe_acl
# ---------------------------------------------------------------------------


def _query_describe_acl_sqlcl(
    profile: Profile, app_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select user_name||'{SEP}'||role_static_id "
        f"from apex_appl_acl_user_roles where application_id = {app_id} "
        f"order by upper(user_name), role_static_id;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="describe_acl")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 2)
        if parts is None:
            continue
        rows.append({"user_name": parts[0], "role_static_id": parts[1]})
    return rows


def _query_describe_acl_pool(app_id: int) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select user_name, role_static_id from apex_appl_acl_user_roles "
            "where application_id = :a order by upper(user_name), role_static_id",
            a=app_id,
        )
        return [
            {"user_name": r[0], "role_static_id": r[1]}
            for r in cur.fetchall()
        ]


def query_describe_acl(profile: Profile, app_id: int) -> list[dict[str, Any]]:
    """ACL assignments for an app. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_describe_acl_sqlcl(profile, app_id)
    return _query_describe_acl_pool(app_id)


# ---------------------------------------------------------------------------
# 12. apex_get_page_details
# ---------------------------------------------------------------------------

_PAGE_DETAIL_COLS: tuple[str, ...] = (
    "PAGE_NAME", "PAGE_ALIAS", "PAGE_MODE", "REQUIRES_AUTHENTICATION",
    "PAGE_FUNCTION", "PAGE_TEMPLATE", "PRIMARY_NAVIGATION_LIST",
    "SECURITY_AUTHORIZATION_SCHEME", "PRIMARY_USER_INTERFACE",
    "INLINE_CSS", "JAVASCRIPT_CODE_ONLOAD", "PAGE_TEMPLATE_OPTIONS",
)


def _query_page_details_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> dict[str, Any] | None:
    select_exprs: list[str] = []
    for col in _PAGE_DETAIL_COLS:
        if col == "PAGE_TEMPLATE":
            # PAGE_TEMPLATE is a NUMBER in apex_application_pages.
            expr = f"to_char(nvl({col}, -1))"
        else:
            expr = f"nvl(to_char({col}), ' ')"
        select_exprs.append(expr)
    concat_expr = f"||'{SEP}'||".join(select_exprs)
    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767\n"
        f"select {concat_expr} from apex_application_pages "
        f"where application_id = {app_id} and page_id = {page_id};\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="get_page_details")
    expected = len(_PAGE_DETAIL_COLS)
    for line in body.splitlines():
        parts = _split_row(line.strip(), expected)
        if parts is None:
            continue
        details: dict[str, Any] = {}
        for col, raw in zip(_PAGE_DETAIL_COLS, parts, strict=True):
            value: Any = raw if raw.strip() else None
            if col == "PAGE_TEMPLATE" and value is not None:
                iv = _to_int_or_none(value)
                value = None if iv == -1 else iv
            details[col] = value
        return details
    return None


def _query_page_details_pool(
    app_id: int, page_id: int
) -> dict[str, Any] | None:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select page_name, page_alias, page_mode, requires_authentication,
                   page_function, page_template, primary_navigation_list,
                   security_authorization_scheme, primary_user_interface,
                   inline_css, javascript_code_onload, page_template_options
              from apex_application_pages
             where application_id = :a and page_id = :p
            """,
            a=app_id, p=page_id,
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row, strict=False))


def query_page_details(
    profile: Profile, app_id: int, page_id: int
) -> dict[str, Any] | None:
    """Full page metadata. None if not found. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_page_details_sqlcl(profile, app_id, page_id)
    return _query_page_details_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 13. apex_list_regions
# ---------------------------------------------------------------------------


def _query_list_regions_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767\n"
        f"select to_char(region_id)||'{SEP}'||region_name||'{SEP}'||"
        f"nvl(display_position, ' ')||'{SEP}'||to_char(nvl(display_sequence, 0))||"
        f"'{SEP}'||nvl(region_template, ' ')||'{SEP}'||"
        f"nvl(to_char(substr(source, 1, 4000)), ' ')||'{SEP}'||"
        f"nvl(source_type, ' ') "
        f"from apex_application_page_regions where application_id = {app_id} "
        f"and page_id = {page_id} order by display_sequence;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_regions")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 7)
        if parts is None:
            continue
        rid = _to_int_or_none(parts[0])
        if rid is None:
            continue
        rows.append(
            {
                "region_id": rid,
                "region_name": parts[1],
                "position": parts[2] if parts[2].strip() else None,
                "sequence": _to_int_or_none(parts[3]),
                "template": parts[4] if parts[4].strip() else None,
                "source": parts[5] if parts[5].strip() else None,
                "source_type": parts[6] if parts[6].strip() else None,
            }
        )
    return rows


def _query_list_regions_pool(
    app_id: int, page_id: int
) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select region_id, region_name, display_position, display_sequence,
                   region_template, source, source_type
              from apex_application_page_regions
             where application_id = :a and page_id = :p
             order by display_sequence
            """,
            a=app_id, p=page_id,
        )
        return [
            {
                "region_id": r[0],
                "region_name": r[1],
                "position": r[2],
                "sequence": r[3],
                "template": r[4],
                "source": r[5],
                "source_type": r[6],
            }
            for r in cur.fetchall()
        ]


def query_list_regions(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    """List regions of a page. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_regions_sqlcl(profile, app_id, page_id)
    return _query_list_regions_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 14. apex_list_items
# ---------------------------------------------------------------------------


def _query_list_items_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767\n"
        f"select to_char(item_id)||'{SEP}'||item_name||'{SEP}'||"
        f"nvl(display_as, ' ')||'{SEP}'||to_char(nvl(item_plug_id, -1))||"
        f"'{SEP}'||to_char(nvl(item_sequence, 0))||'{SEP}'||"
        f"nvl(label, ' ')||'{SEP}'||nvl(prompt, ' ') "
        f"from apex_application_page_items where application_id = {app_id} "
        f"and page_id = {page_id} order by item_sequence;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_items")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 7)
        if parts is None:
            continue
        iid = _to_int_or_none(parts[0])
        if iid is None:
            continue
        plug_id = _to_int_or_none(parts[3])
        rows.append(
            {
                "item_id": iid,
                "name": parts[1],
                "display_as": parts[2] if parts[2].strip() else None,
                "region_id": None if plug_id == -1 else plug_id,
                "sequence": _to_int_or_none(parts[4]),
                "label": parts[5] if parts[5].strip() else None,
                "prompt": parts[6] if parts[6].strip() else None,
            }
        )
    return rows


def _query_list_items_pool(
    app_id: int, page_id: int
) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            select item_id, item_name, display_as, item_plug_id,
                   item_sequence, label, prompt
              from apex_application_page_items
             where application_id = :a and page_id = :p
             order by item_sequence
            """,
            a=app_id, p=page_id,
        )
        return [
            {
                "item_id": r[0],
                "name": r[1],
                "display_as": r[2],
                "region_id": r[3],
                "sequence": r[4],
                "label": r[5],
                "prompt": r[6],
            }
            for r in cur.fetchall()
        ]


def query_list_items(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    """List items of a page. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_items_sqlcl(profile, app_id, page_id)
    return _query_list_items_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 15. apex_list_processes
# ---------------------------------------------------------------------------


def _query_list_processes_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767\n"
        f"select to_char(process_id)||'{SEP}'||process_name||'{SEP}'||"
        f"nvl(process_type, ' ')||'{SEP}'||"
        f"to_char(nvl(process_sequence, 0))||'{SEP}'||"
        f"nvl(process_point, ' ')||'{SEP}'||"
        f"nvl(to_char(substr(process_sql_clob, 1, 4000)), ' ') "
        f"from apex_application_page_proc where application_id = {app_id} "
        f"and page_id = {page_id} order by process_sequence;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_processes")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 6)
        if parts is None:
            continue
        pid = _to_int_or_none(parts[0])
        if pid is None:
            continue
        rows.append(
            {
                "process_id": pid,
                "name": parts[1],
                "type": parts[2] if parts[2].strip() else None,
                "sequence": _to_int_or_none(parts[3]),
                "point": parts[4] if parts[4].strip() else None,
                "code": parts[5] if parts[5].strip() else None,
            }
        )
    return rows


def _query_list_processes_pool(
    app_id: int, page_id: int
) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select process_id, process_name, process_type, process_sequence, "
            "process_point, process_sql_clob "
            "from apex_application_page_proc "
            "where application_id = :a and page_id = :p order by process_sequence",
            a=app_id, p=page_id,
        )
        return [
            {
                "process_id": r[0],
                "name": r[1],
                "type": r[2],
                "sequence": r[3],
                "point": r[4],
                "code": str(r[5]) if r[5] else None,
            }
            for r in cur.fetchall()
        ]


def query_list_processes(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    """List page processes. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_processes_sqlcl(profile, app_id, page_id)
    return _query_list_processes_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 16. apex_list_dynamic_actions
# ---------------------------------------------------------------------------


def _query_list_dynamic_actions_sqlcl(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    sql = (
        "set heading off feedback off pagesize 0 echo off\n"
        f"select to_char(dynamic_action_id)||'{SEP}'||dynamic_action_name||"
        f"'{SEP}'||nvl(when_event_name, ' ')||'{SEP}'||"
        f"nvl(when_element_type, ' ')||'{SEP}'||nvl(when_element, ' ') "
        f"from apex_application_page_da where application_id = {app_id} "
        f"and page_id = {page_id} order by event_sequence;\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_dynamic_actions")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 5)
        if parts is None:
            continue
        did = _to_int_or_none(parts[0])
        if did is None:
            continue
        rows.append(
            {
                "da_id": did,
                "name": parts[1],
                "event": parts[2] if parts[2].strip() else None,
                "element_type": parts[3] if parts[3].strip() else None,
                "element": parts[4] if parts[4].strip() else None,
            }
        )
    return rows


def _query_list_dynamic_actions_pool(
    app_id: int, page_id: int
) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        cur.execute(
            "select dynamic_action_id, dynamic_action_name, when_event_name, "
            "when_element_type, when_element "
            "from apex_application_page_da "
            "where application_id = :a and page_id = :p order by event_sequence",
            a=app_id, p=page_id,
        )
        return [
            {
                "da_id": r[0],
                "name": r[1],
                "event": r[2],
                "element_type": r[3],
                "element": r[4],
            }
            for r in cur.fetchall()
        ]


def query_list_dynamic_actions(
    profile: Profile, app_id: int, page_id: int
) -> list[dict[str, Any]]:
    """List dynamic actions on a page. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_dynamic_actions_sqlcl(profile, app_id, page_id)
    return _query_list_dynamic_actions_pool(app_id, page_id)


# ---------------------------------------------------------------------------
# 17. apex_list_tables (DB)
# ---------------------------------------------------------------------------


def _query_list_tables_sqlcl(
    profile: Profile, schema: str | None
) -> list[dict[str, Any]]:
    if schema:
        # Caller has already validated schema via validate_object_name.
        ws_esc = schema.upper().replace("'", "''")
        sql = (
            "set heading off feedback off pagesize 0 echo off\n"
            f"select table_name||'{SEP}'||to_char(nvl(num_rows, -1))||"
            f"'{SEP}'||nvl(to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS'), ' ') "
            f"from all_tables where owner = '{ws_esc}' order by table_name;\n"
            "exit\n"
        )
    else:
        sql = (
            "set heading off feedback off pagesize 0 echo off\n"
            f"select table_name||'{SEP}'||to_char(nvl(num_rows, -1))||"
            f"'{SEP}'||nvl(to_char(last_analyzed, 'YYYY-MM-DD HH24:MI:SS'), ' ') "
            f"from user_tables order by table_name;\n"
            "exit\n"
        )
    body = _sqlcl_or_raise(profile, sql, tool_label="list_tables")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 3)
        if parts is None:
            continue
        nr = _to_int_or_none(parts[1])
        rows.append(
            {
                "table_name": parts[0],
                "num_rows": None if nr == -1 else nr,
                "last_analyzed": parts[2] if parts[2].strip() else None,
            }
        )
    return rows


def _query_list_tables_pool(schema: str | None) -> list[dict[str, Any]]:
    pool = _get_pool()
    with pool.acquire() as conn:
        cur = conn.cursor()
        if schema:
            cur.execute(
                "select table_name, num_rows, last_analyzed "
                "from all_tables where owner = :owner order by table_name",
                owner=schema.upper(),
            )
        else:
            cur.execute(
                "select table_name, num_rows, last_analyzed "
                "from user_tables order by table_name"
            )
        return [
            {
                "table_name": r[0],
                "num_rows": r[1],
                "last_analyzed": str(r[2]) if r[2] else None,
            }
            for r in cur.fetchall()
        ]


def query_list_tables(
    profile: Profile, schema: str | None
) -> list[dict[str, Any]]:
    """List tables. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_list_tables_sqlcl(profile, schema)
    return _query_list_tables_pool(schema)


# ---------------------------------------------------------------------------
# 18. apex_describe_table (DB)
# ---------------------------------------------------------------------------


def _query_describe_table_sqlcl(
    profile: Profile, table_name: str, schema: str | None
) -> list[dict[str, Any]]:
    """Describe a table via SQLcl.

    NOTE: ``data_default`` is a LONG column in *_tab_columns and cannot be
    concatenated with strings via ``||``. Under the SQLcl path we omit it
    and return ``None`` for every column's ``default`` field. The pool path
    returns the actual default. Callers needing column defaults under
    sqlcl-only mode should use ``apex_get_source`` against the table DDL or
    query data_default through dbms_metadata.
    """
    tn_esc = table_name.upper().replace("'", "''")
    if schema:
        ws_esc = schema.upper().replace("'", "''")
        sql = (
            "set heading off feedback off pagesize 0 echo off long 32767 "
            "linesize 32767\n"
            f"select column_name||'{SEP}'||data_type||'{SEP}'||"
            f"to_char(nvl(data_length, -1))||'{SEP}'||nullable "
            f"from all_tab_columns where owner = '{ws_esc}' "
            f"and table_name = '{tn_esc}' order by column_id;\n"
            "exit\n"
        )
    else:
        sql = (
            "set heading off feedback off pagesize 0 echo off long 32767 "
            "linesize 32767\n"
            f"select column_name||'{SEP}'||data_type||'{SEP}'||"
            f"to_char(nvl(data_length, -1))||'{SEP}'||nullable "
            f"from user_tab_columns where table_name = '{tn_esc}' "
            f"order by column_id;\n"
            "exit\n"
        )
    body = _sqlcl_or_raise(profile, sql, tool_label="describe_table")
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        parts = _split_row(line.strip(), 4)
        if parts is None:
            continue
        dl = _to_int_or_none(parts[2])
        rows.append(
            {
                "name": parts[0],
                "type": parts[1],
                "length": None if dl == -1 else dl,
                "nullable": parts[3] == "Y",
                "default": None,  # LONG col — see docstring
            }
        )
    return rows


def _query_describe_table_pool(
    table_name: str, schema: str | None
) -> list[dict[str, Any]]:
    pool = _get_pool()
    owner = schema.upper() if schema else None
    with pool.acquire() as conn:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """
                select column_name, data_type, data_length, nullable, data_default
                  from all_tab_columns
                 where owner = :owner and table_name = :tn
                 order by column_id
                """,
                owner=owner, tn=table_name.upper(),
            )
        else:
            cur.execute(
                """
                select column_name, data_type, data_length, nullable, data_default
                  from user_tab_columns
                 where table_name = :tn
                 order by column_id
                """,
                tn=table_name.upper(),
            )
        return [
            {
                "name": r[0],
                "type": r[1],
                "length": r[2],
                "nullable": r[3] == "Y",
                "default": str(r[4]) if r[4] else None,
            }
            for r in cur.fetchall()
        ]


def query_describe_table(
    profile: Profile, table_name: str, schema: str | None
) -> list[dict[str, Any]]:
    """Describe table columns. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_describe_table_sqlcl(profile, table_name, schema)
    return _query_describe_table_pool(table_name, schema)


# ---------------------------------------------------------------------------
# 19. apex_get_source (DB)
# ---------------------------------------------------------------------------
#
# Source CLOB can be large and contains arbitrary code (potentially with
# pipe characters in PL/SQL string literals). We avoid the pipe-separator
# trick here and instead emit raw lines bracketed by a unique marker.


def _query_get_source_sqlcl(
    profile: Profile, object_name: str, object_type: str, schema: str | None
) -> list[str]:
    """Return source as a list of lines (mirrors pool path)."""
    obj_esc = object_name.upper().replace("'", "''")
    typ_esc = object_type.upper().replace("'", "''")
    begin_marker = f"{SEP}SRC_BEGIN{SEP}"
    end_marker = f"{SEP}SRC_END{SEP}"
    if schema:
        ws_esc = schema.upper().replace("'", "''")
        select_sql = (
            f"select text from all_source where owner = '{ws_esc}' "
            f"and name = '{obj_esc}' and type = '{typ_esc}' order by line"
        )
    else:
        select_sql = (
            f"select text from user_source where name = '{obj_esc}' "
            f"and type = '{typ_esc}' order by line"
        )
    sql = (
        "set heading off feedback off pagesize 0 echo off long 32767 "
        "linesize 32767 trimspool off\n"
        f"prompt {begin_marker}\n"
        f"{select_sql};\n"
        f"prompt {end_marker}\n"
        "exit\n"
    )
    body = _sqlcl_or_raise(profile, sql, tool_label="get_source")
    in_block = False
    src_lines: list[str] = []
    for line in body.splitlines():
        s = line.rstrip("\r")
        if begin_marker in s:
            in_block = True
            continue
        if end_marker in s:
            in_block = False
            continue
        if in_block:
            # Skip blank lines emitted between SQL*Plus prompt and result.
            if not s.strip():
                continue
            # user_source.text typically already ends with a newline; the
            # SQL*Plus output strips trailing newlines so we re-add one.
            src_lines.append(s + "\n")
    return src_lines


def _query_get_source_pool(
    object_name: str, object_type: str, schema: str | None
) -> list[str]:
    pool = _get_pool()
    owner = schema.upper() if schema else None
    with pool.acquire() as conn:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """
                select text from all_source
                 where owner = :owner and name = :n and type = :t
                 order by line
                """,
                owner=owner, n=object_name.upper(), t=object_type.upper(),
            )
        else:
            cur.execute(
                """
                select text from user_source
                 where name = :n and type = :t
                 order by line
                """,
                n=object_name.upper(), t=object_type.upper(),
            )
        return [r[0] for r in cur.fetchall()]


def query_get_source(
    profile: Profile,
    object_name: str,
    object_type: str,
    schema: str | None,
) -> list[str]:
    """Get PL/SQL source as a list of lines. Branches on auth_mode."""
    if resolve_auth_mode(profile) is AuthMode.SQLCL:
        return _query_get_source_sqlcl(profile, object_name, object_type, schema)
    return _query_get_source_pool(object_name, object_type, schema)
