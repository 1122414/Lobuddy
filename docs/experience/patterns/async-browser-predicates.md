# Await IPC predicates outside browser waitForFunction

Signals: a native test reports readiness immediately even though a service operation has not completed, or later assertions intermittently fail after an asynchronous wait.

Mechanism: the installed Playwright implementation invokes `predicate()` and tests its immediate truthiness. An async predicate returns a truthy Promise; the polling loop stops before inspecting whether its resolved value is false. Awaiting the resulting handle does not restart polling.

Diagnosis: inspect the installed runtime and verify a false asynchronous predicate stays pending. P8 found this when a settings download test returned before the model files existed. The test closed Electron and correctly cancelled the still-running download, producing a false success claim that was withdrawn.

Handling: `desktop/tests/wait-for.cjs` awaits `page.evaluate(predicate, arg)` on every iteration, with an explicit deadline. The paired `wait-for.test.cjs` proves false async results are retried and eventually time out. Update existing IPC waits; keep final DOM, data and side-effect assertions. Do not infer that every older end-to-end test failed: many had independent final assertions.

Validation: helper verified once on 2026-10-16. Corrected P3 desktop and P7 companionship native smoke tests passed with real model calls. P8 settings/model readiness and developer-package voice tests passed; synthetic MediaStream tests do not establish physical microphone or echo behavior. Results and limits are recorded in `reports/2026-10-16_p8_voice.md`. Applicability is to the inspected installed Playwright runtime; do not assume every browser polling API has this behavior.
