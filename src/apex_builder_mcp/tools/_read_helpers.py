"""Shared read helpers — branch on auth_mode for SQLcl-vs-pool reads.

Mirror of `_write_helpers.py` for the 6 read tools that previously assumed
the oracledb pool was always available. With `auth_mode=sqlcl` (default),
reads go through the SQLcl subprocess path using pipe-separated output
parsing; with `auth_mode=password`, the existing oracledb pool path is used.

Each public ``query_*`` function branches on ``resolve_auth_mode(profile)``.
Both paths must return identical-shape values so calling tools are oblivious
to which path was taken.

Output separator
----------------
SQLcl path renders pipe-separated rows using ``'|||'`` (triple pipe). Three
pipes is sufficiently rare in real APEX metadata (workspace names, view
columns, etc.) to avoid collisions while remaining easy to grep for.
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
