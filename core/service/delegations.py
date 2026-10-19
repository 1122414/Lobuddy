"""Coordinate explicit delegations with the existing governed task queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import JsonValue

from core.service.delegation_protocol import (
    DelegationChange,
    DelegationReference,
    DelegationRun,
    DelegationSpec,
)
from core.service.protocol import METHODS, RpcRequest
from core.storage.delegation_repo import DelegationRepository

if TYPE_CHECKING:
    from core.service.application import ApplicationService


class DelegationService:
    def __init__(self, service: ApplicationService, repo: DelegationRepository) -> None:
        self.service = service
        self.repo = repo

    async def handle(self, request: RpcRequest) -> JsonValue:
        action = request.method.removeprefix("delegation.")
        params = METHODS[request.method].model_validate(request.params)
        if action == "create":
            assert isinstance(params, DelegationSpec)
            return self.repo.create(request.id, params).model_dump(mode="json")
        if action == "list":
            return [value.model_dump(mode="json") for value in self.repo.list()]
        if action == "get":
            assert isinstance(params, DelegationReference)
            detail = self.repo.detail(params.delegation_id)
            detail.outcomes = [
                self.service.ledger.outcomes.get(run.turn_id) for run in detail.runs if run.turn_id
            ]
            return detail.model_dump(mode="json")
        assert isinstance(params, DelegationChange)
        if action == "run":
            return (await self.run(request.id, params)).model_dump(mode="json")
        value = self.repo.change(request.id, action, params)
        if action in ("pause", "cancel"):
            for run in self.repo.detail(value.id).runs:
                if run.turn_id and run.status in ("reserved", "running"):
                    await self.service.cancel(run.turn_id)
        return value.model_dump(mode="json")

    async def run(self, request_id: str, params: DelegationChange) -> DelegationRun:
        previous = self.repo.replayed_run(request_id, params)
        if previous:
            return previous
        value = self.repo.get(params.delegation_id)
        version = self.service.knowledge.workflows.active(value.spec.kind)
        run, created = self.repo.claim(request_id, params, version.version_id)
        if not created:
            return next(item for item in self.repo.detail(value.id).runs if item.id == run.id)
        session_id = value.spec.session_id or "delegation-" + value.id
        self.service.chat.get_or_create_session(session_id, title=value.spec.goal[:100])
        inputs: dict[str, JsonValue] = (
            {"sources": list(value.spec.sources)}
            if value.spec.kind == "source-digest"
            else {"source": value.spec.source_directory, "output": value.spec.output_directory}
        )
        try:
            await self.service.handle(
                RpcRequest(
                    jsonrpc="2.0",
                    id="delegation-run-" + run.id,
                    method="turn.send",
                    params={
                        "session_id": session_id,
                        "text": value.spec.goal,
                        "lane": "background",
                        "workflow_id": value.spec.kind,
                        "workflow_input": inputs,
                    },
                ),
                delegation_run=run,
            )
        except BaseException:
            # An interrupted handoff is kept for reconciliation, never silently retried.
            self.repo.recover(run.id)
            raise
        return next(item for item in self.repo.detail(value.id).runs if item.id == run.id)
