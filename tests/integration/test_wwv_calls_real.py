"""Gate 2: 5 sample WWV_FLOW_IMP_PAGE calls on real DB DEV.

WARNING: this creates a sandbox app, mutates it, then drops it.
Run only on DEV with intent.
"""
from __future__ import annotations

import os
import secrets

import oracledb
import pytest

pytestmark = pytest.mark.integration


def _real_creds():
    dsn = os.environ.get("APEX_TEST_DSN")
    user = os.environ.get("APEX_TEST_USER")
    pw = os.environ.get("APEX_TEST_PASSWORD")
    workspace_id = os.environ.get("APEX_TEST_WORKSPACE_ID")  # numeric
    schema = os.environ.get("APEX_TEST_SCHEMA")
    if not all([dsn, user, pw, workspace_id, schema]):
        pytest.skip("APEX_TEST_DSN/USER/PASSWORD/WORKSPACE_ID/SCHEMA not set")
    return dsn, user, pw, int(workspace_id), schema


@pytest.fixture
def sandbox_app_id():
    return 900000 + secrets.randbelow(99999)


def test_5_sample_calls_succeed(sandbox_app_id):
    dsn, user, pw, ws_id, schema = _real_creds()
    conn = oracledb.connect(user=user, password=pw, dsn=dsn)
    try:
        cur = conn.cursor()
        # Create a sandbox app first using the public-but-internal init flow
        cur.execute(
            """
            begin
              wwv_flow_application_install.set_workspace_id(:ws);
              wwv_flow_application_install.set_schema(:sc);
              wwv_flow_application_install.set_application_id(:aid);
              wwv_flow_application_install.generate_offset;
              wwv_flow_imp.create_application(
                p_id => :aid,
                p_owner => :sc,
                p_name => '_TEST_APEXBLD_' || :aid,
                p_alias => '_TST_' || :aid,
                p_application_group => 0
              );
            end;
            """,
            ws=ws_id, sc=schema, aid=sandbox_app_id,
        )
        # 5 sample calls
        cur.execute(
            """
            begin
              wwv_flow_imp_page.create_page(
                p_id => 1, p_name => 'Sandbox', p_step_title => 'Sandbox'
              );
              wwv_flow_imp_page.create_page_plug(
                p_id => 100, p_plug_name => 'TestRegion',
                p_plug_template => 0, p_plug_display_sequence => 10,
                p_plug_source_type => 'NATIVE_HTML',
                p_plug_query_options => 'DERIVED_REPORT_COLUMNS'
              );
              wwv_flow_imp_page.create_page_item(
                p_id => 200, p_name => 'P1_TEST',
                p_item_sequence => 10, p_item_plug_id => 100,
                p_display_as => 'NATIVE_TEXT_FIELD'
              );
              wwv_flow_imp_page.create_page_button(
                p_id => 300, p_button_sequence => 10, p_button_plug_id => 100,
                p_button_name => 'BTN_OK', p_button_action => 'SUBMIT',
                p_button_template_id => 0, p_button_image_alt => 'OK'
              );
              wwv_flow_imp_page.create_page_process(
                p_id => 400, p_process_sequence => 10, p_process_type => 'NATIVE_PLSQL',
                p_process_name => 'PROC_TEST', p_process_sql_clob => 'null;'
              );
              commit;
            end;
            """
        )
        # Verify metadata
        cur.execute(
            "select count(*) from apex_application_page_regions where application_id = :a",
            a=sandbox_app_id,
        )
        (region_count,) = cur.fetchone()
        assert region_count >= 1
    finally:
        # Cleanup
        try:
            cur.execute(
                "begin wwv_flow_imp.remove_flow(:a); commit; end;",
                a=sandbox_app_id,
            )
        except Exception:
            pass
        conn.close()
