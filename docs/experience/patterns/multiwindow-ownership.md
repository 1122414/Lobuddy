# Multiwindow ownership and appearance admission

Signals: a new transparent window becomes the first automation target; opening quick chat rejects an existing approval; a re-created pet loses scale despite unchanged preferences.

Mechanism: renderer creation order is not readiness order. Reload policy copied onto initial navigation turns an observation surface into a cancellation trigger. Cached appearance is only valid for the window instance to which it was applied.

Handling: `desktop/electron/windows.ts` creates the pet after management navigation completes, authenticates each main frame against its exact surface URL, broadcasts one service's events, and only denies approvals on subsequent loads/close/crash. Clear applied preferences when replacing a pet window. Tests locate native windows by exact URL, never by `getAllWindows()[0]`.

Related asset boundary: validate animated images completely, then persist the same byte buffer (`ImageStore.import_bytes`); a second path read would create a validation/use race. Keep original animation bytes, bound total decoded pixels, and serve only the selected hash through a private image protocol. New image palette extraction must not call legacy `ThemeGenerator.extract_palette`, which globally enables truncated-image decoding.

Supporting checks: `desktop/tests/desktop-smoke.cjs` opens a second surface during live approval, rejects there, permits another real write, and rejects reloads; `desktop/tests/companion-smoke.cjs` exercises real model, focus, custom image, theme and restart; `tests/test_companion_service.py` checks GIF bytes, theme IDs and unchanged Pillow flags.

Validation: verified once on macOS arm64, 2026-10-16. Negative-coordinate/removal geometry is unit-tested in DIP; simultaneous physical monitors are not evidence supplied by this test. This does not qualify future microphone permissions or audio-window ownership.

## Native tests must isolate the Electron profile too

E0 learning smoke exited with code 0 before a window appeared while the manual preview was running. Separate LOBUDDY_DATA_DIR/LOBUDDY_WORKSPACE did not separate Electron's single-instance lock. Set a temporary `app.setPath('userData', ...)` before requiring main, and retain the actual app path via `app.setAppPath(...)`; isolate both service data and Chromium profile. Do not close the user's app to make tests pass. Verified once by `desktop/tests/learning-smoke.cjs` (settings, maintenance and restart) on 2026-10-16.
