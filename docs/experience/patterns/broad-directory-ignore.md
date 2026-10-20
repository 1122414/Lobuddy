# Broad directory ignore and source completeness

## Signals and mechanism

A clean working tree does not establish source completeness. An unanchored Git ignore rule such as `skills/` matches directories with that name below the repository root, including `core/skills/`. Already tracked files remain tracked, while newly created siblings can be silently excluded from ordinary staging. Default file-search tools may also omit ignored source paths.

## Supporting case

At Lobuddy commit `9a27479`, `.gitignore` contains `skills/`. The tree includes `core/skills/skill_manager.py`, `skill_registry.py`, and `skill_maintenance.py`, but lacks `skill_schema.py`, `skill_selector.py`, `skill_candidate_extractor.py`, and `skill_validator.py` despite imports in application code or tests.

On 2026-10-16, Python 3.12.7 imports confirmed all four modules missing and `SkillManager` failing on `core.skills.skill_schema`. `git check-ignore -v --no-index` matched all four paths to `.gitignore:56`. This verifies the missing-source and ignore-rule interaction once; it does **not** prove how the original author lost or omitted these files.

During P0 implementation on the same date, searching **all refs** found the four implementations in `a2d51c2`, outside the current branch's history. They were recovered with only the schema classes required by the current callers; unrelated later evaluation types were not imported. The ignore rule was anchored to `/skills/`. The six skill test files, including `tests/test_skill_source_recovery.py`, passed 34 tests; `scripts/smoke_legacy_startup.py` composed the real Qt UI and exited with temporary data. This is one verified recovery, not evidence that every later feature from that commit is compatible. Full-suite failures are separately recorded in the P0 report.

## Diagnosis and handling

1. Compare filesystem inventory, internal imports, and `git ls-tree -r --name-only HEAD core/skills`; do not rely only on default `rg --files` or a clean `git status`.
2. Use `git check-ignore -v --no-index <path>` to identify the exact matching rule without creating files.
3. Search `git log --all -- <missing-path>` as well as the current branch. Recover intended implementations from a trusted working copy or history and verify caller/test contracts. Do not invent empty replacement modules or merge unrelated later features merely to recover a file.
4. If only the root runtime directory is intended to be ignored, consider `/skills/`; inspect the resulting untracked inventory before staging.
5. Validate imports, relevant tests (`tests/test_skill_manager.py`, `tests/test_skill_selector.py`, `tests/test_skill_candidate_extractor.py`, `tests/test_52_integration.py`), and source completeness in a fresh checkout.

## Limits

This method does not recover missing code or establish that every missing module is caused by Git ignore rules. Dynamic imports, generated modules, submodules, and intentionally optional integrations need separate interpretation. Changing ignore rules does not remove already tracked bytecode or runtime data; those need separately reviewed ordinary changes.

Full baseline and unexecuted checks: [2026-10-16 project scan](../../../reports/2026-10-16_project_scan.md).
