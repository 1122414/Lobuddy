# Preserve recovery boundaries during native upgrades

## Signals and mechanism

Copying SQLite bytes while WAL is active can omit committed rows. Restoring the business DB without DSH session files leaves engine-session mappings pointing to missing execution records. Removing plaintext credentials before checking the native store can leave a working installation unable to authenticate.

## Handling

Use SQLite online backup, private file permissions and a complete checksummed manifest. Stop the runtime before copying its session files. Import into a fresh sibling directory, validate paths and integrity, then atomically rename the directory into place. Never mutate the original DB during an import. Mark the schema version so the transitional legacy entry refuses upgraded databases. An exact snapshot restore uses the matching old program and restored data; it is not a reverse migration.

Write and read back every credential in the app's own Keychain namespace before removing any legacy binding. Preserve the entire original `.env` and DB credential rows when native storage fails. Parse dotenv bindings rather than deleting lines, because quoted multiline values span lines. Detect concurrent edits before replacing the file. Never pass a secret in process arguments or return it to the renderer.

P8 exposed a second credential boundary: a primary LLM key in the environment must not suppress an optional Fish key in Keychain, and an older stored optional key must not overwrite its explicit replacement. Resolve precedence independently per field. Both directions are covered by `tests/test_voice_service.py`; configuration unit tests mock native storage and use temporary directories. The legacy adapter fixture also required explicit data/log paths: a temporary workspace alone still allowed memory projections to write the checkout's default data directory. After correcting that fixture, full regression passed with the original projection unchanged.

## Supporting observations

The old full-suite compile check used cwd-relative source paths and failed when tests were run in an isolated directory to avoid writing test memory into user data. Resolve code paths from `__file__`; keep mutable fixtures in temporary directories.

Google's unauthenticated HTML search returned a navigation-only page and DuckDuckGo rejected the request in this environment. A successful HTTP response is not proof of useful search results. The bounded Bing RSS path returns structured items and source links; reject missing items and XML entity declarations. Recheck availability instead of treating one provider's success as universal.

## Evidence and limits

Verified once on macOS arm64, 2026-10-16. `tests/test_upgrade_data.py` verifies idempotent imports, corruption rejection, stopped-runtime backup, unchanged source and credential failure preservation. `scripts/smoke_native_capabilities.py` verifies synthetic native Keychain items, opening a disposable document and public web reads. The real legacy DB was backed up/imported/restored with identical pet/session IDs and values. Secrets are not included in experience records. See `reports/2026-10-16_p5_capabilities.md`. Windows credential storage and public distribution signing remain separate acceptance work.

## Default entrypoints and readiness can still target the old runtime

On 2026-10-19, changing pyproject entrypoints did not update the already-installed `.venv/bin/lobuddy`; editable-install metadata must be refreshed too. The old health command invoked legacy bootstrap, so using it against desktop data could initialize the wrong runtime. Keep legacy bootstrap available for its own entry, use a read-only DSH diagnostic for the default command, and share settings decoding rather than silently ignoring database overrides. `tests/test_desktop_health.py` verifies no directory creation, corrupt DB preservation, stored settings, redacted errors and no Qt/nanobot imports; the bundled interpreter check also passed. This checks local readiness, not provider connectivity or real audio devices.
