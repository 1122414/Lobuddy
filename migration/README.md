# TypeScript migration verification

`baseline/` is the immutable `7195718` behavior inventory. `progress.json` is a separate, reviewed disposition ledger; an absent source ID is pending. Do not infer completion from a test file's existence or a newer test count.

Commands:

```sh
npm run check:migration
npm run check:retirement
```

The first checks frozen baseline hashes, known and unique source IDs, disposition states, retirement reasons and referenced replacement files. It permits incomplete incremental work. The second fails while any historical test remains unresolved and must pass before T9 retirement. These checks validate the ledger, not assertion equivalence; replacement tests and the stage's native/product gates must also pass.

For each reviewed source test:

- `ported`: record the replacement path and named assertions preserving the effective DSH behavior, including failure and boundary cases.
- `retired`: explain why the assertion tested an obsolete internal mechanism or behavior already absent from the DSH baseline; point to the retained observable behavior's checks. A Qt/nanobot label alone is insufficient.
- Keep unresolved behavior absent rather than claiming it is covered by a broad smoke test. Do not rewrite frozen expectations to match TS output.

For example, the old standalone command classifier accepted some interpreters, Git commands and Windows syntax that `core/agent/dsh/commands.py` already denied through its final executable/flag mapping. Retiring that classifier API does not authorize enabling those commands. Conversely, its delete-wildcard rejection was effective in DSH and had to be restored in the TS parser; see the T9 report and `packages/service/src/tools.test.ts`.

The current T9 evidence and remaining release gates are in [the cutover report](../reports/2026-10-21_t9_typescript_cutover.md). Physical microphone/echo acceptance and uninterrupted long-running checks remain independent of historical test disposition.
