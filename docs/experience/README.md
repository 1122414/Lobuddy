# Project troubleshooting experience

| Mechanism | Applicability signals | Validation status | Entry |
|---|---|---|---|
| Broad directory ignore hides missing source modules | Clean working tree but internal imports fail; generated and source directories share a name | Recovery verified once on 2026-10-16: all-ref history, 34 tests and real Qt startup; historical cause of omission not established | [Directory ignore and source completeness](patterns/broad-directory-ignore.md) |
| Runtime, plugin types and target platform diverge | npm prerelease peer conflict; macOS lock fails despite native install; recovered sessions contain pending work | Verified once on macOS arm64 / DSH 0.1.5rc1, including real model and crash recovery | [Runtime version and recovery boundary](patterns/runtime-version-boundary.md) |
