# Multiwindow ownership and appearance admission

Signals: a new transparent window becomes the first automation target; opening quick chat rejects an existing approval; a re-created pet loses scale despite unchanged preferences.

Mechanism: renderer creation order is not readiness order. Reload policy copied onto initial navigation turns an observation surface into a cancellation trigger. Cached appearance is only valid for the window instance to which it was applied.

Handling: `desktop/electron/windows.ts` creates the pet after management navigation completes, authenticates each main frame against its exact surface URL, broadcasts one service's events, and only denies approvals on subsequent loads/close/crash. Clear applied preferences when replacing a pet window. Tests locate native windows by exact URL, never by `getAllWindows()[0]`.

Related asset boundary: validate animated images completely, then persist the same byte buffer (`ImageStore.import_bytes`); a second path read would create a validation/use race. Keep original animation bytes, bound total decoded pixels, and serve only the selected hash through a private image protocol. New image palette extraction must not call legacy `ThemeGenerator.extract_palette`, which globally enables truncated-image decoding.

Supporting checks: `desktop/tests/desktop-smoke.cjs` opens a second surface during live approval, rejects there, permits another real write, and rejects reloads; `desktop/tests/companion-smoke.cjs` exercises real model, focus, custom image, theme and restart; `tests/test_companion_service.py` checks GIF bytes, theme IDs and unchanged Pillow flags.

Validation: verified once on macOS arm64, 2026-10-16. Negative-coordinate/removal geometry is unit-tested in DIP; simultaneous physical monitors are not evidence supplied by this test. This does not qualify future microphone permissions or audio-window ownership.

## Native tests must isolate the Electron profile too

E0 learning smoke exited with code 0 before a window appeared while the manual preview was running. Separate LOBUDDY_DATA_DIR/LOBUDDY_WORKSPACE did not separate Electron's single-instance lock. Set a temporary `app.setPath('userData', ...)` before requiring main, and retain the actual app path via `app.setAppPath(...)`; isolate both service data and Chromium profile. Do not close the user's app to make tests pass. Verified once by `desktop/tests/learning-smoke.cjs` (settings, maintenance and restart) on 2026-10-16.

## An open observation panel still needs reconciliation

N4's dialogue panel originally fetched only when session identity changed. A quick-chat utterance could update that same session while management continued showing the old intent/boundaries. Reconcile while mounted with at most one request in flight, clear stale session state on a switch, and ignore responses after unmount. The native `desktop/tests/dialogue-smoke.cjs` now leaves the panel open, changes intent and removes a boundary through the shared service, and verifies the displayed state follows. The pre-fix listening assertion timed out at seven seconds; post-fix passed on 2026-10-19. This verifies synchronization, not subjective conversational naturalness.


### Long-running voice tests and native hide events

On 2026-10-19 the voice soak observed off with no error even though `document.visibilityState` still said visible. Native event recording then showed quick-window hide followed by the main-process voice-stop event; the user confirmed manually hiding the windows. This was the intended privacy lifecycle, not a second capture-overload fault. The earlier uninstrumented 24-minute stop cannot independently be classified from its report.

Record native hide/show/close and power events alongside renderer control/storage events before diagnosing an unexplained stop. Resource tests may use transparent noninteractive windows, a hidden Dock entry and muted synthetic output to avoid interfering with desktop work; keep real hide/close handlers intact and report the test configuration. This does not validate physical microphone permissions, echo or audible playback. Evidence: `reports/2026-10-19_n6_voice_lifecycle_short_v2.json` and `reports/2026-10-19_n6_voice_isolated_short.json`; verified once with native events and direct user feedback.
