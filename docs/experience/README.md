# Project troubleshooting experience

| Mechanism | Applicability signals | Validation status | Entry |
|---|---|---|---|
| Conversation updates override reading position | Streaming or task polling jumps a manually scrolled chat to the bottom | Verified once with the production component in Chromium on 2026-10-16 | [Chat scroll ownership](patterns/chat-scroll-ownership.md) |
| Broad directory ignore hides missing source modules | Clean working tree but internal imports fail; generated and source directories share a name | Recovery verified once on 2026-10-16: all-ref history, 34 tests and real Qt startup; historical cause of omission not established | [Directory ignore and source completeness](patterns/broad-directory-ignore.md) |
| Runtime, plugin types and target platform diverge | npm prerelease peer conflict; macOS lock fails despite native install; recovered sessions contain pending work | Verified once on macOS arm64 / DSH 0.1.5rc1, including real model, crash recovery and later live-configuration recheck | [Runtime version and recovery boundary](patterns/runtime-version-boundary.md) |
| Async task/SDK startup ownership, stale voice callbacks and obsolete Qt mocks | Concurrent queue submissions, cancelled startup leaves child, late microphone callbacks, cross-test Qt import failures | Verified across P2/P8 cases with fault injection, real model and native developer-package voice; physical echo pending | [Async lifecycle ownership](patterns/async-lifecycle-ownership.md) |
| Canonical knowledge and generated projections diverge | Deleted facts remain injected; disabled skills lose content; upserts discard audit events | Verified once with lifecycle tests and real DSH/desktop on 2026-10-16 | [Authoritative knowledge and projections](patterns/authoritative-knowledge-projections.md) |
| Durable terminal records and effect settlement diverge | Duplicate EXP/skill counters, crash after reply, cache usage totals disagree | Verified once with transaction fault injection, duplicate events and real DSH usage on 2026-10-16 | [Durable effect settlement](patterns/durable-effect-settlement.md) |
| Native migration crosses incompatible storage boundaries | WAL snapshots, missing engine sessions, lost credentials, cwd-dependent tests, default archive writes | Verified with migration checks on 2026-10-16 and isolated fixtures/relocated bundle on 2026-10-21 | [Native upgrade boundaries](patterns/native-upgrade-boundaries.md) |
| Multiple windows share one execution owner | Initial navigation cancels approvals, first-window race, stale appearance cache | Verified once with real Electron/DSH and synthetic geometry on 2026-10-16 | [Multiwindow ownership](patterns/multiwindow-ownership.md) |
| Protocol request retention definitions diverge | State polling eventually exhausts request capacity; Node/Python method lists differ | Verified once with 8300 reads and 778-test regression on 2026-10-16 | [Protocol request retention](patterns/protocol-request-retention.md) |
| Async browser predicates return truthy Promises | Native IPC wait returns before a job is ready | Runtime inspected; awaited helper and P3/P7/P8 native rechecks passed, physical acceptance separate | [Async browser predicates](patterns/async-browser-predicates.md) |

- [Verified workflow promotion](patterns/verified-workflow-promotion.md): immutable candidates, fixed holdout checks, version pinning and no replay; verified once for lossless context serialization, not semantic quality.

- [Process termination and incident evidence](patterns/process-terminal-evidence.md): signal-terminated children retain a null exitCode; verify both terminal fields and distinguish incident events from test cleanup. Verified once with native fault injection on 2026-10-19; historical closed-page cause remains unknown.

- [Explicit source lifetime](patterns/explicit-source-lifetime.md): forget/correct invalidates replay bodies, derived context and complete historical engine associations; native picker aliases and empty project identities have explicit handling. Verified once with 28 project tests and native/real-model checks on 2026-10-19.

- [Calendar wall time](patterns/calendar-wall-time.md): editing must preserve the stored timezone and resolve DST in the service; native reproduction and fixed boundary tests verified once on 2026-10-19.
- 10.19 follow-up: [durable settlement](patterns/durable-effect-settlement.md) now covers transactional completion events and periodic recovery; [multiwindow ownership](patterns/multiwindow-ownership.md) now covers mounted dialogue-panel reconciliation. Targeted regressions passed; physical voice acceptance remains separate.

- [Unresolved voice stop](unresolved.md): historical stops without native events remain unclassified; later capture overflow was fixed, while recorded window hides correctly released audio. Full continuous-voice rerun and physical acceptance remain pending.

- [Typed advisory decisions](patterns/typed-advisory-decisions.md): independent Jev judgments, confidence-aware vetoes, durable attempts and safe fallback. Verified once with 48 unit/integration cases, native desktop and 10 real synthetic cases on 2026-10-20; general decision quality remains unmeasured.

- 2026-10-21 TS qualification: [runtime version boundary](patterns/runtime-version-boundary.md) now includes the rc.1 SDK's JS-only dshBin semantics, POSIX execve PID ownership, Electron utility environment separation, and complete transitive version checking. Verified once in the target Electron runtime; final application packaging remains pending.
