#!/bin/bash
# Clear the apex-builder-mcp:ereport_test8001 password from Win Cred Mgr.
# Useful if the saved password is wrong or you want to force a re-prompt.

cd "$(dirname "$0")/.." || exit 2

./.venv/Scripts/python.exe -c "
import keyring
keyring.delete_password('apex-builder-mcp', 'ereport_test8001')
print('Cleared keyring entry: apex-builder-mcp:ereport_test8001')
"
