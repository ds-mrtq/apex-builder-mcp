# tests/unit/test_sqlcl_metadata.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from apex_builder_mcp.connection.sqlcl_metadata import (
    SqlclConnectionMetadata,
    SqlclConnectionNotFoundError,
    read_connection_metadata,
)


@pytest.fixture
def fake_connections_file(tmp_path: Path) -> Path:
    data = {
        "connections": [
            {
                "name": "HTC_DEV1",
                "user": "EREPORT",
                "host": "10.0.0.10",
                "port": 1521,
                "serviceName": "ORCLPDB",
            },
            {
                "name": "HTC_PROD",
                "user": "EREPORT",
                "host": "10.0.0.20",
                "port": 1521,
                "serviceName": "PRODPDB",
            },
        ]
    }
    f = tmp_path / "connections.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def test_read_known_connection(fake_connections_file):
    md = read_connection_metadata("HTC_DEV1", connections_file=fake_connections_file)
    assert isinstance(md, SqlclConnectionMetadata)
    assert md.host == "10.0.0.10"
    assert md.port == 1521
    assert md.service_name == "ORCLPDB"
    assert md.user == "EREPORT"


def test_read_unknown_connection_raises(fake_connections_file):
    with pytest.raises(SqlclConnectionNotFoundError):
        read_connection_metadata("NOPE", connections_file=fake_connections_file)


def test_dsn_property(fake_connections_file):
    md = read_connection_metadata("HTC_DEV1", connections_file=fake_connections_file)
    assert md.dsn == "10.0.0.10:1521/ORCLPDB"


def test_does_not_expose_password_field(fake_connections_file):
    md = read_connection_metadata("HTC_DEV1", connections_file=fake_connections_file)
    # explicit guard: ensure no password-like attribute exposed
    assert not hasattr(md, "password")


def test_naming_consistency_with_profile_not_found_error():
    """Both 'not found' errors in connection module must follow the *Error suffix convention."""
    from apex_builder_mcp.connection.profile import ProfileNotFoundError
    from apex_builder_mcp.connection.sqlcl_metadata import SqlclConnectionNotFoundError

    # Both are KeyError subclasses with consistent naming
    assert issubclass(ProfileNotFoundError, KeyError)
    assert issubclass(SqlclConnectionNotFoundError, KeyError)
    assert ProfileNotFoundError.__name__.endswith("Error")
    assert SqlclConnectionNotFoundError.__name__.endswith("Error")


def test_parse_connmgr_show_output():
    from apex_builder_mcp.connection.sqlcl_metadata import _parse_connmgr_show

    sample = """SQLcl: Release 26.1 Production on Tue Apr 28 21:58:38 2026

Copyright (c) 1982, 2026, Oracle.  All rights reserved.

Name: ereport_test8001
Connect String: ebstest.vicemhatien.vn:1522/TEST1
User: ereport
Password: ******
autoCommit: false
"""
    md = _parse_connmgr_show(sample, "ereport_test8001")
    assert md.host == "ebstest.vicemhatien.vn"
    assert md.port == 1522
    assert md.service_name == "TEST1"
    assert md.user == "ereport"
    assert not hasattr(md, "password")


def test_parse_connmgr_show_missing_connect_string():
    from apex_builder_mcp.connection.sqlcl_metadata import (
        SqlclConnectionNotFoundError,
        _parse_connmgr_show,
    )
    with pytest.raises(SqlclConnectionNotFoundError):
        _parse_connmgr_show("Name: x\nUser: y", "x")


def test_read_connection_metadata_falls_back_to_connmgr(monkeypatch, tmp_path):
    from apex_builder_mcp.connection.sqlcl_metadata import (
        read_connection_metadata,
    )
    nonexistent = tmp_path / "no.json"
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = (
        "Name: my_conn\nConnect String: h:1521/svc\nUser: u\n"
    )
    fake_proc.stderr = ""
    monkeypatch.setattr(
        "apex_builder_mcp.connection.sqlcl_metadata.subprocess.run",
        MagicMock(return_value=fake_proc),
    )
    md = read_connection_metadata("my_conn", connections_file=nonexistent)
    assert md.host == "h"
    assert md.port == 1521
    assert md.user == "u"
