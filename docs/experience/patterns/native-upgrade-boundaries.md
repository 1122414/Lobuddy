# Preserve recovery boundaries during native upgrades

## Signals and mechanism

Copying SQLite bytes while WAL is active can omit committed rows. Restoring the business DB without DSH session files leaves engine-session mappings pointing to missing execution records. Removing plaintext credentials before checking the native store can leave a working installation unable to authenticate.

## Handling

Use SQLite online backup, private file permissions and a complete checksummed manifest. Stop the runtime before copying its session files. Import into a fresh sibling directory, validate paths and integrity, then atomically rename the directory into place. Never mutate the original DB during an import. Mark the schema version so the transitional legacy entry refuses upgraded databases. An exact snapshot restore uses the matching old program and restored data; it is not a reverse migration.

Write and read back every credential in the app's own Keychain namespace before removing any legacy binding. Preserve the entire original `.env` and DB credential rows when native storage fails. Parse dotenv bindings rather than deleting lines, because quoted multiline values span lines. Detect concurrent edits before replacing the file. Never pass a secret in process arguments or return it to the renderer.

## Supporting observations

The old full-suite compile check used cwd-relative source paths and failed when tests were run in an isolated directory to avoid writing test memory into user data. Resolve code paths from `__file__`; keep mutable fixtures in temporary directories.

Google's unauthenticated HTML search returned a navigation-only page and DuckDuckGo rejected the request in this environment. A successful HTTP response is not proof of useful search results. The bounded Bing RSS path returns structured items and source links; reject missing items and XML entity declarations. Recheck availability instead of treating one provider's success as universal.

## Evidence and limits

Verified once on macOS arm64, 2026-10-16. `tests/test_upgrade_data.py` verifies idempotent imports, corruption rejection, stopped-runtime backup, unchanged source and credential failure preservation. `scripts/smoke_native_capabilities.py` verifies synthetic native Keychain items, opening a disposable document and public web reads. The real legacy DB was backed up/imported/restored with identical pet/session IDs and values. Secrets are not included in experience records. See `reports/2026-10-16_p5_capabilities.md`. Windows credential storage and public distribution signing remain separate acceptance work.
