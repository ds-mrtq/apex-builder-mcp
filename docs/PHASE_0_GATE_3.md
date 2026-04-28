# Gate 3: Windows Credential Manager round-trip

## Run

```bash
cd /d/repos/apex-builder-mcp
./.venv/Scripts/pytest.exe tests/integration/test_keyring_real.py -v --integration
```

## Pass criteria

- [ ] keyring backend resolved (verify with `keyring --list-backends` if curious)
- [ ] set_password succeeds without exception
- [ ] get_password returns same value
- [ ] delete_password cleans up
- [ ] post-delete get_password returns None

## On FAIL

Common causes on Win 11:
- Locked-down Group Policy preventing Credential Manager access
- Backend resolution falls back to `keyring.backends.fail.Keyring` → no storage

Workaround: switch to `keyrings.alt` file vault (encrypted file in user dir).
