"""Qt-based HITL approval provider with cross-thread signal delivery.

Bridges between the async worker thread (where _ToolTracker runs) and
the main Qt UI thread (where dialogs must be shown). Uses Qt Signal for
thread-safe cross-thread delivery and asyncio.wrap_future for async
await on the worker side.
"""

import asyncio
import concurrent.futures
import logging
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger("lobuddy.hitl_provider")

from core.safety.hitl_approval import HitlApprovalDecision, HitlApprovalRequest


class QtHitlApprovalProvider(QObject):
    approval_requested = Signal(object)

    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self._pending: dict[str, concurrent.futures.Future] = {}

    def set_parent_window(self, parent_window):
        self._parent_window = parent_window

    @Slot(object)
    def _show_dialog(self, request: HitlApprovalRequest):
        from ui.hitl_confirmation_dialog import HitlConfirmationDialog

        dialog = HitlConfirmationDialog(request, parent=self._parent_window)
        dialog.confirmed.connect(
            lambda req_id, approved, reason: self._on_dialog_result(req_id, approved, reason)
        )
        dialog.show()

    def _on_dialog_result(self, request_id: str, approved: bool, reason: str):
        future = self._pending.pop(request_id, None)
        if future is None:
            return
        if future.done():
            return
        try:
            future.set_result(
                HitlApprovalDecision(
                    request_id=request_id,
                    approved=approved,
                    decided_at=datetime.now(timezone.utc),
                    reason=reason,
                )
            )
        except Exception:
            pass

    async def request_approval(self, request: HitlApprovalRequest) -> HitlApprovalDecision:
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._pending[request.request_id] = future
        self.approval_requested.emit(request)
        try:
            decision = await asyncio.wrap_future(future)
            return decision
        except Exception:
            from core.safety.hitl_approval import HitlApprovalDecision

            return HitlApprovalDecision.rejected_now(
                request.request_id, reason="HITL approval failed"
            )
        finally:
            self._pending.pop(request.request_id, None)
