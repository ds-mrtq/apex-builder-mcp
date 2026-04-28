# src/apex_builder_mcp/apex_api/boolean_emit.py
from __future__ import annotations

# Known boolean parameter names in WWV_FLOW_IMP_PAGE.* per APEX 24.2.
# Curated from skill knowledge — extend as we discover via ALL_ARGUMENTS.
_KNOWN_BOOL_PARAMS: frozenset[str] = frozenset({
    "p_use_as_row_header",
    "p_filter_exact_match",
    "p_user_resizable",
    "p_user_aggregateable",
    "p_user_sortable",
    "p_use_csv_format",
    "p_visible",
    "p_show_filter",
})


class BooleanEmitError(TypeError):
    """Raised when a non-bool value is passed where a real bool is required."""


def emit_bool(value: bool) -> str:
    """Emit real PL/SQL bool literal. Reject anything that isn't a true Python bool."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    raise BooleanEmitError(
        f"Expected bool, got {type(value).__name__}: {value!r}. "
        "APEX bool params must be real PL/SQL booleans (PLS-00306 trap)."
    )


def is_bool_param_name(param_name: str) -> bool:
    """Best-effort detection of WWV_FLOW_IMP_PAGE bool params by name."""
    return param_name.lower() in _KNOWN_BOOL_PARAMS
