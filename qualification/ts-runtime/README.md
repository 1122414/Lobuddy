# T1: isolated no-Python qualification

This is a qualification harness, **not the replacement Lobuddy backend**. The current desktop remains unchanged. T2 will incorporate this temporary package into the root workspace/lock; T9 removes the development-only legacy oracle. No test opens the microphone, imports a real user database, or uses production model credentials.

The harness compiles TypeScript with the existing desktop compiler, starts Electron 44.8.0, transfers a MessagePort to a utilityProcess, and tests SQLite FTS5/backup, safeStorage roundtrip, Silero CPU inference, and the official TS SDK with the existing authenticated Lobuddy bridge. Optional Whisper/corpus runs occur in that same utilityProcess. The isolated DSH process uses synthetic configuration, disables the baseline autonomous tools/telemetry, and makes no model request.

## Commands (repository root)

```sh
npm ci
npm run setup:native
npm run build:packages
npm run --workspace @lobuddy/runtime-qualification build
node qualification/ts-runtime/dist/verify-dependencies.js
node qualification/ts-runtime/dist/download-assets.js
node qualification/ts-runtime/dist/prepare-corpus.js
node qualification/ts-runtime/dist/augment-corpus.js
```

Download writes only `.local-upgrade/ts-assets`; the official wheel is treated as a pinned ZIP container and only its native DSH executable and licenses are extracted. Python modules, pip, and installer hooks are never executed. Whisper/Silero bytes are verified by size and SHA256. This developer download is explicit, not the eventual app's first-run behavior.

Run the compiled `dist/run.js` with absolute arguments: DSH binary, Silero model, Whisper directory, a 16 kHz PCM16 mono synthetic WAV, corpus manifest and corpus directory. The first two are mandatory; speech/corpus are optional and omitted runs are reported as untested. Results are written under `.local-upgrade/`. No transcript is printed by the runtime probe; public corpus transcripts are stored only in the separate comparison result.

The corpus uses 108 source clips (80 FLEURS Mandarin and 28 Taiwan-source examples) plus 12 deterministic noise/pause variants. Source authors, revisions, licenses, reference text, transformations and WAV hashes are in `corpus-manifest.json`. Accent metadata is limited; the source label is not speaker/accent certification. The fixed CER rule applies NFKC, lowercase and punctuation/whitespace/symbol removal equally, with no hypothesis-specific correction or traditional/simplified conversion. Latency excludes loading and one warm-up. New and old benchmarks must run sequentially on the same machine.

The transitional `dist/legacy-comparison.js PYTHON MODEL CORPUS MANIFEST OUTPUT` invokes only the existing local faster-whisper model for the baseline. It is never loaded by Electron, the SDK, or the new speech probe. `dist/compare-corpus.js MANIFEST CURRENT PREVIOUS OUTPUT` exits unsuccessfully if CER increases by over 2 percentage points or warm P95 exceeds 1.2 times the baseline.

## Confirmed launch correction

The rc.1 SDK's `dshBin` means a **JavaScript module**, executed with `process.execPath`, not a native executable. `native-entry.cts` uses POSIX `process.execve` to replace that SDK-owned process with the pinned native runtime, preserving its PID and stdio. This avoids another proxy child and retains SDK shutdown ownership. The SDK launch alone sets `ELECTRON_RUN_AS_NODE`; setting it on `utilityProcess.fork` makes Chromium utility arguments fail. This route depends on the Node-mode fuse and POSIX support and must be rechecked in the final packaged application. Windows remains unqualified.

An initial install with only the bridge's overrides resolved indirect packages to rc.3. Complete DSH-family overrides and a fresh lock removed the drift; `verify-dependencies` prevents recurrence. No install scripts were run. macOS ARM64 ONNX native binaries are included in the npm package. Dependency license inventory includes libvips LGPL notices; final redistribution must preserve the native packages' notices and license obligations, not merely the top-level JS license.

## Acceptance boundary

T1 component qualification, synthetic credential-source migration, dependency/model relocation, crash teardown and the 120-case comparison passed on the recorded target machine. See `reports/2026-10-21_t1_typescript_qualification.md` for measurements and limitations. Add `--relocate` to copy dependencies/models/plugin out of the development directory, or `--crash` to inject DSH termination. This does not establish real model tool behavior, 110-method equivalence, real credential migration, microphone quality, full continuous speech, two-hour stability or product release acceptance. T2–T10 remain separate work.
