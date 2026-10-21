# Match plugin types, runtime and resolution target

## Signals and mechanism

An exact DSH SDK pin does not pin TypeScript peer dependencies. DSH 0.1.5-rc.1 packages declare caret peers; npm selected rc.3 for a transitive peer while the root agent remained rc.1, causing ERESOLVE. Also, uv's generic macOS platform resolves against macOS 13, while the official SDK runtime wheel requires macOS 14.

## Diagnosis and handling

Read installed SDK code and the exact npm release declarations. Pin the transitive DSH peer closure with overrides and a package lock, rather than force-installing incompatible peers. Compile the Python lock with MACOSX_DEPLOYMENT_TARGET=14.0. Check real startup independently of type checking: the packaged runtime also extracts native modules and opens loopback sockets.

Only deliver authenticated commands to a custom plugin and let Python own governed effects. An event-stream loss must revoke pending approval and work; restoring a session must not resume its old inbox. Validate this by killing the owned process while approval is pending, then checking persisted effects after resume.

## Boundaries and evidence

Verified once on macOS arm64, SDK/runtime 0.1.5rc1 and npm types 0.1.5-rc.1. Not a guarantee for newer releases or Windows. Review the peer closure and profile row IDs on upgrades.

- `bridge/dsh/package.json`, `bridge/dsh/package-lock.json`
- `requirements-dev-macos.in`, `core/agent/dsh/runtime.py`
- `scripts/smoke_dsh_bridge.py`: real model, midstream cancellation, approval-time crash and no replay
- `reports/2026-10-16_p1_dsh_bridge.md`: observed results and limitations

## Recheck live configuration before blaming a new transport

On 2026-10-16, P1/P2 real model checks had passed, while a later Electron test and the independent stdio smoke both failed. A sanitized SDK startup check reported an empty exact model name. Presence-only inspection showed all three local LLM settings empty; their file modification time had changed. Restoring configuration made both transports work. The reason for the external file change was not established. Do not treat an earlier successful check as evidence that mutable configuration is still present; compare the known-good transport and inspect presence/model/host without displaying key values. `DshRuntime.start` now rejects empty settings before SDK initialization; desktop health reports `model_configured`. Verified once; this is not a general diagnosis for every JsonRpcError.

## TypeScript SDK launch semantics and npm resolution (2026-10-21)

The rc.1 TypeScript SDK's `dshBin` is a JavaScript module argument to `process.execPath`, despite its suggestive name. Passing the Python distribution's standalone Mach-O directly is not supported by that public option. The T1 qualification uses a compiled TS entry which calls POSIX `process.execve` with the verified native runtime. The bridge-reported PID equals the entry PID; normal SDK shutdown and injected SIGKILL both left that PID absent. This was verified once inside Electron 44.8.0 utilityProcess / Node 24.22.0 on macOS arm64. The final package must preserve/verify Node-mode fuse support; do not generalize to Windows or a different SDK release.

Set `ELECTRON_RUN_AS_NODE` only for the SDK-created entry. Setting it on `utilityProcess.fork` caused the Electron Helper to reject `--type=utility` and other Chromium arguments before the worker could run. This is an environment ownership issue, not an ONNX binary incompatibility.

The SDK imports a larger DSH dependency tree than the original bridge. Reusing the bridge's partial overrides selected rc.3 packages; even after adding overrides, the initial installed tree/lock retained 43 nested rc.3 entries. A fresh task-owned install with the complete DSH-family overrides resolved everything to rc.1. `qualification/ts-runtime/verify-dependencies.ts` checks the entire lock, rather than only top-level versions. No force/legacy-peer install was used. Keep original user work and lockfiles intact; the discarded tree in this case was generated solely for qualification.

Evidence: `qualification/ts-runtime/native-entry.cts`, `worker.cts`, `verify-dependencies.ts`, and `reports/2026-10-21_t1_typescript_qualification.md`. This is component feasibility, not completion of the TS business migration or independent application packaging. The earlier Python ownership description applies to the still-default backend; T4 will move that owner to TS without changing the governed-effects boundary.

## Workspace hoisting and relocation (2026-10-21)

After consolidating three npm locks into a root workspace, a package's own node_modules no longer represented its runtime closure. Recursive copying at every dependency edge then exceeded 1000 copies because DSH shares a dense peer graph. The final copier resolves each installed package from its importer, copies each resolved source once, and links dependencies inside a private output store. A synthetic cycle with two versions of one package still loaded correctly after deleting the source and moving the output; the actual Electron/DSH/ONNX relocation also passed. This is verified once on macOS, not a claim about Windows symlink packaging. See `scripts/ts/runtime-copy.test.mjs`, `scripts/ts/copy-runtime-dependencies.mjs`, and `reports/2026-10-21_t2_typescript_contracts.md`. Root `package-lock.json` now replaces the historical per-project lock paths listed above.

A separate native-only failure came from including only `src/**/*.ts`, which excluded the `.cts` utility entry. `tsc` succeeded while Electron could not find the entry. Include `.cts` explicitly and test actual startup from a clean compiled snapshot; unit imports alone cannot cover omitted entrypoints.

T3 found a second lockfile boundary: generating the root lock from a populated installation tree left 631 third-party entries without archive integrity, despite successful `npm ci`. Exact-version metadata from the official registry filled missing SHA512/resolved fields without changing package versions or paths. The dependency verifier now requires SHA512 for all 724 third-party entries; a fresh isolated install passed. Inspect lock metadata itself, not only install exit status. This diagnosis is verified once for this generated workspace lock and does not imply all npm-generated locks omit hashes.

## T4: compatible host/plugin peers and strict empty context

On 2026-10-21, declaring the production TS SDK exposed Cordis plugins requiring host 4.0.5 while rc.1 uses 4.0.2. Incremental lock generation retained incompatible rows despite overrides. Re-resolve from a clean installation tree, explicitly constrain the compatible plugin releases, compare all package-version sets, and run `npm ls --all` as well as checksum/license validation. DSH stays rc.1; frontend versions stay fixed. Verified once with a clean snapshot installation and actual Electron execution.

The real bridge also rejects `context: ''` through its nonempty text validator. Omit the field when no context exists. A permissive fake engine hid this until the native model probe; `packages/service/src/tasks.test.ts` now asserts it. Do not normalize omitted and empty fields indiscriminately. See `reports/2026-10-21_t4_typescript_tasks.md` for evidence and remaining combined model-fault check.

## Final desktop package entry ownership (2026-10-21, T9 in progress)

The first full TS app copied `packages/service/dist` separately from the private dependency closure. Development passed because root workspace hoisting supplied its imports; relocation failed at the business worker's module phase (`ERR_MODULE_NOT_FOUND`). The package now links `packages/service` and other workspace entries to their own resolved package directories inside `Resources/app/node_modules`, retaining importer-local peers. The bridge's direct runtime import is explicitly rooted as well. Do not fix this by adding developer search paths.

Verified once with the relocated full app under `/usr/bin:/bin` PATH: SQLite handshake, verified file-source workflow, then actual bundled DSH model reply. `desktop/tests/package-smoke.cjs` and `scripts/ts/verify-package.mjs` also check packaged identity and internal links/file hashes. This is an unnotarized local candidate; physical voice and complete legacy-test retirement are still pending.
## Layered policy parity during a language migration

T9's command parser retained the DSH executable/flag allowlist but missed a delete-path rule inherited through Python `SafetyGuardrails.assess_shell_command`: wildcard characters `*?[]` were forbidden. A parse-only reproduction accepted `rm *.tmp`, `rm file?.txt`, and `rm [abc].txt`; no command was executed. Passing argument vectors without a shell prevents glob expansion but does not preserve the old admission policy.

Port effective behavior through every policy layer, not just the innermost command table. `packages/service/src/tools.test.ts` now exercises the original blocked grammar and wildcard cases through both `commandArguments` and `GovernedTools`, asserting zero approval requests and unchanged synthetic content. Ordinary mapped commands remain parseable. Verified once on 2026-10-21; this does not establish filesystem race immunity for all subprocesses.
