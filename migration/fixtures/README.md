# Frozen migration fixtures

These are synthetic records from the Python implementation retained at baseline `7195718`; no user database, `.env`, provider credentials, microphone or model calls were used. They supplement the immutable `migration/baseline/` inventory.

- `legacy-records.json`: actual `ApplicationService` public session/memory/skill/project/source/preference operations, plus `RelationshipService.immediate`, `edit` and `forget` fed synthetic user messages. Contains active/corrected/forgotten relationships, source barriers, old skill content/version and seeded workflow versions. Files are the synthetic workspace's text projections. Temporary roots are replaced by `__OLD_DATA__` and `__OLD_WORKSPACE__`; the TS test supplies isolated paths.
- `settings-cases.json`: public non-secret defaults and 16 coercion/validation results from `Settings(_env_file=None, ...)`, with all four credential fields explicitly empty. Includes numeric/boolean strings, booleans accepted as numeric settings, invalid ranges and enums.

`packages/service/src/storage.test.ts` imports the records into an isolated old-layout DB, backs it up, migrates it and compares persisted knowledge/version/source records and workspace files. `config.test.ts` compares settings outcomes. The tests run entirely in Node; Python was used only to produce the development oracle, not in their execution.

These fixtures verify storage compatibility, not the TS implementation of memory inference, tool execution, learning or workflow evaluation. Those remain separate T4–T8 acceptance work.
