# Lobuddy project instructions

## Current architecture

Lobuddy is an Electron + React + TypeScript personal companion on macOS arm64 (macOS 14+). Python, Qt and nanobot were retired from current source in T9; their implementations and test identities remain in Git history and `migration/baseline/`. Do not restore their old instructions or use their helpers in default development, tests, packaging or runtime.

- `desktop/`: React UI, sandboxed preload, Electron windows, safeStorage credentials and process ownership.
- `packages/contracts/`: Zod runtime schemas and inferred types for RPC, events, settings and stored JSON.
- `packages/domain/`: Electron-independent rules and state machines.
- `packages/service/`: utilityProcess business service; sole SQLite writer, raw SQL repositories, DSH/tools, memory, learning, Jev and scheduling.
- `packages/speech/`: isolated ONNX recognition/VAD worker and bounded audio lifecycle.
- `bridge/dsh/`: authenticated loopback bridge to pinned DSH runtime.
- `qualification/ts-runtime/`: native dependencies, model/runtime provenance and qualification probes.

## Changes and boundaries

Preserve UI layout and effective contracts unless explicitly requested. Validate inputs, outputs and stored JSON at trust boundaries. Do not expose filesystem, shell, credentials or unrestricted RPC to renderers. Keep SQLite transactions synchronous with explicit ownership; do not add an ORM or nested implicit transactions.

All model execution must use the governed DSH bridge. Do not enable built-in autonomous tools, bypass approvals, expand workspace paths, weaken SSRF/DNS checks or replay an unknown write. Memory writes go through MemoryWriteGateway; corrections/forgetting must invalidate derived context and persistent engine associations. Workflow candidates cannot modify the fixed evaluator, permissions, credential handling or memory gateway.

Use one root npm workspace lock. Run `npm ci` only at the root. Installation scripts are disabled; `npm run setup:native` installs the pinned Electron binary. Do not introduce Python, global executable assumptions or unpinned runtime/model downloads. Native macOS filesystem behavior and packaging require target-platform verification.

## Verification and commits

Follow the user's plan and global commit discipline: one Chinese stage commit after its required checks pass, without push or history rewriting. Preserve unrelated edits and user data.

- `npm run check`: frozen contracts, source retirement, types/builds, integration and desktop/plugin unit tests.
- `npm run check:retirement`: every one of the 1077 historical test IDs has a reviewed disposition; this does not itself prove assertions passed.
- `npm run test:desktop`: native real-model path, using isolated data and browser profiles.
- `npm run package:mac` / `npm run verify:package`: standalone bundle and dependency/provenance checks.
- `npm run test:soak` / `npm run test:voice-soak`: separate uninterrupted 7200-second checks.

Use Node's test runner and existing Playwright native fixtures. Keep all synthetic data separate from real user files. Do not print secrets or raw provider failures. Do not count short or interrupted soak runs as passed. Physical voice quality, echo, ten-round continuity and P95 measurements remain separate product gates.

Read relevant `docs/experience/README.md` entries before investigation and update reusable findings with observed evidence. Historical report links identify previous code, not current execution instructions. T10 remains pending until its actual release gates are satisfied.
