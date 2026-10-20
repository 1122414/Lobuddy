"""JEV-01/02/03: typed HTTP, durable delivery policy and credential boundaries."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from core.agent.jev import ChoiceAnswer, JevClient, JevContext, JevUnavailable, request_body
from core.config import Settings
from core.config.credentials import load_settings, migrate_credentials
from core.service.application import ApplicationService
from core.service.jev_notifications import NotificationDecisions
from core.service.protocol import RpcRequest
from core.service.schedule_protocol import NotificationView
from core.service.settings_service import SettingsPatch, SettingsService
from core.storage.db import Database
from core.storage.jev_repo import JevRepository
from core.storage.notification_repo import NotificationRepository


def answer(choice="yes", probability=0.96):
    return {
        "type": "choice",
        "choice": choice,
        "confidence": (probability - 1 / 3) / (2 / 3),
        "probabilities": {
            key: probability if key == choice else (1 - probability) / 2
            for key in ("yes", "no", "unknown")
        },
    }


def response(relevant="yes", urgent="yes", duplicate="no", probability=0.96):
    return {
        "model": "jev-1.13.0",
        "answers": {
            "relevant": answer(relevant, probability),
            "time_sensitive": answer(urgent, probability),
            "duplicate": answer(duplicate, probability),
        },
        "usage": {"input_tokens": 325, "output_tokens": 0},
    }


@pytest.fixture
def setup(tmp_path):
    settings = Settings(
        _env_file=None,
        llm_api_key="synthetic-llm",
        typesafe_api_key="synthetic-jev",
        fish_api_key="",
        jev_mode="active",
        data_dir=tmp_path / "data",
        workspace_path=tmp_path / "workspace",
    )
    db = Database(settings)
    db.init_database(allow_desktop=True)
    now, quiet, calls = [1000.0], [False], []
    notices = NotificationRepository(db, lambda: now[0])
    result = [response()]

    async def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=result[0])

    decisions = NotificationDecisions(
        settings,
        db,
        notices,
        lambda: quiet[0],
        lambda identity: "准备面试资料",
        client=JevClient(httpx.MockTransport(handle)),
        clock=lambda: now[0],
    )
    notices.eligible = decisions.allowed
    return SimpleNamespace(
        settings=settings,
        db=db,
        now=now,
        quiet=quiet,
        calls=calls,
        notices=notices,
        decisions=decisions,
        result=result,
    )


def put(system, identity="n1", **kwargs):
    value = NotificationView(
        id=identity,
        source_id=identity,
        reason="task_result",
        text="面试资料整理完成",
        planned_at=1000.0,
        created_at=1000.0,
        **kwargs,
    )
    system.notices.put(value)
    return value


async def decide(system):
    system.decisions.poll()
    if system.decisions.task:
        await system.decisions.task


class TestJevTransport:
    async def test_official_contract_and_no_redirect(self):
        requests = []

        async def handle(request):
            requests.append(request)
            return httpx.Response(200, json=response())

        client = JevClient(httpx.MockTransport(handle))
        body = request_body(
            JevContext(notification="资料完成", goal="资料", recent_delivered=[]), "jev-1.13.0"
        )
        result = await client.decide(body, "synthetic-key")
        assert result.answers.time_sensitive.choice == "yes"
        assert str(requests[0].url) == "https://api.typesafe.ai/v1/systemone"
        assert requests[0].headers["authorization"] == "Bearer synthetic-key"
        assert set(json.loads(body)["questions"]) == {"relevant", "time_sensitive", "duplicate"}
        assert len(requests) == 1

    @pytest.mark.parametrize("status", [302, 401, 402, 429, 500])
    async def test_failure_is_safe_single_attempt(self, status):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(
                status, text="secret-value", headers={"location": "https://evil.invalid"}
            )

        with pytest.raises(JevUnavailable) as caught:
            await JevClient(httpx.MockTransport(handle)).decide(b"{}", "synthetic")
        assert str(caught.value) == f"http_{status}"
        assert len(calls) == 1

    async def test_timeout_has_no_request_or_secret_in_error(self):
        def handle(request):
            raise httpx.ReadTimeout("secret-value", request=request)

        with pytest.raises(JevUnavailable, match="^network_or_timeout$"):
            await JevClient(httpx.MockTransport(handle)).decide(b"{}", "synthetic")

    @pytest.mark.parametrize("body", [b"not json", b"x" * 65537, b'{"answers":{}}'])
    async def test_invalid_or_oversized_body_fails_closed(self, body):
        with pytest.raises(JevUnavailable, match="invalid_response"):
            await JevClient(
                httpx.MockTransport(lambda _: httpx.Response(200, content=body))
            ).decide(b"{}", "synthetic")

    @pytest.mark.parametrize(
        "change",
        [
            {"choice": "execute_shell"},
            {"confidence": float("nan")},
            {"confidence": 0.99},
            {"probabilities": {"yes": 1.0}},
            {"probabilities": {"yes": 0.1, "no": 0.8, "unknown": 0.1}},
            {"probabilities": {"yes": 1.2, "no": -0.1, "unknown": -0.1}},
        ],
    )
    def test_distribution_must_match_confidence_and_options(self, change):
        with pytest.raises(ValidationError):
            ChoiceAnswer.model_validate(answer() | change)


class TestNotificationDecisions:
    @pytest.mark.parametrize("mode,key", [("off", "key"), ("active", ""), ("shadow", "")])
    async def test_unconfigured_preserves_original_delivery(self, setup, mode, key):
        setup.decisions.configure(
            setup.settings.model_copy(update={"jev_mode": mode, "typesafe_api_key": key})
        )
        put(setup)
        await decide(setup)
        assert setup.notices.next(quiet=False)
        assert not setup.calls

    async def test_quiet_skips_network_and_delivery(self, setup):
        put(setup)
        setup.quiet[0] = True
        await decide(setup)
        assert not setup.calls
        assert setup.notices.next(quiet=True) is None

    async def test_explicit_reminder_is_never_gated(self, setup):
        put(setup)
        setup.notices.put(
            NotificationView(
                id="reminder",
                source_id="r",
                reason="reminder",
                text="该休息了",
                planned_at=1000.0,
                created_at=1000.0,
            )
        )
        batch = setup.notices.next(quiet=False)
        assert batch.count == 1 and batch.text == "该休息了"
        assert not setup.calls

    @pytest.mark.parametrize(
        "relevant,urgent,duplicate,probability,action",
        [
            ("yes", "yes", "no", 0.96, "notify"),
            ("yes", "no", "no", 0.96, "defer"),
            ("no", "yes", "no", 0.96, "quiet"),
            ("yes", "yes", "yes", 0.96, "quiet"),
            ("unknown", "yes", "no", 0.96, "defer"),
            ("yes", "yes", "no", 0.6, "defer"),
        ],
    )
    async def test_choice_composition_and_durable_evidence(
        self, setup, relevant, urgent, duplicate, probability, action
    ):
        value = put(setup)
        setup.result[0] = response(relevant, urgent, duplicate, probability)
        assert setup.notices.next(quiet=False) is None
        await decide(setup)
        record = setup.decisions.repo.get(value.id)
        assert record.action == action
        assert record.input_tokens == 325 and record.model == "jev-1.13.0"
        batch = setup.notices.next(quiet=False)
        assert bool(batch) == (action == "notify")
        setup.now[0] += 601
        if action == "defer":
            assert setup.notices.next(quiet=False)
        elif action == "quiet":
            assert setup.notices.next(quiet=False) is None
            assert setup.notices.read(value.id).status == "read"
        await decide(setup)
        assert len(setup.calls) == 1
        with setup.db.get_connection() as conn:
            body = conn.execute("SELECT body FROM jev_decision").fetchone()[0]
        assert value.text not in body and "synthetic-jev" not in body

    async def test_shadow_observes_without_changing_delivery(self, setup):
        setup.decisions.configure(setup.settings.model_copy(update={"jev_mode": "shadow"}))
        put(setup)
        setup.result[0] = response(duplicate="yes")
        await decide(setup)
        assert setup.decisions.repo.get("n1").action == "quiet"
        assert setup.notices.next(quiet=False)
        setup.decisions.configure(setup.settings)
        assert setup.decisions.allowed(setup.notices.get("n1"))

    async def test_confident_irrelevance_veto_does_not_require_certain_urgency(self, setup):
        put(setup)
        setup.result[0] = response(relevant="no")
        setup.result[0]["answers"]["time_sensitive"] = answer("yes", 0.6)
        await decide(setup)
        assert setup.decisions.repo.get("n1").action == "quiet"
        assert setup.notices.next(quiet=False) is None

    async def test_failed_request_defers_without_retry_or_lost_inbox(self, setup):
        setup.decisions.client = JevClient(httpx.MockTransport(lambda _: httpx.Response(429)))
        put(setup)
        await decide(setup)
        assert setup.decisions.repo.get("n1").status == "fallback"
        assert setup.notices.next(quiet=False) is None
        setup.now[0] += 601
        assert setup.notices.next(quiet=False)
        assert setup.decisions.repo.usage(setup.now[0])[0] == 1

    async def test_budget_and_restart_are_durable(self, setup):
        setup.decisions.configure(setup.settings.model_copy(update={"jev_daily_calls": 1}))
        put(setup, "n1")
        await decide(setup)
        put(setup, "n2")
        await decide(setup)
        assert len(setup.calls) == 1
        assert setup.decisions.repo.get("n2").status == "fallback"
        repo = JevRepository(setup.db)
        assert repo.usage(setup.now[0])[0] == 1
        assert repo.get("n1").input_tokens == 325

    async def test_request_byte_budget_is_pre_reserved(self, setup):
        setup.decisions.configure(setup.settings.model_copy(update={"jev_daily_request_bytes": 1}))
        put(setup)
        await decide(setup)
        assert not setup.calls
        assert setup.decisions.repo.usage(setup.now[0]) == (0, 0)
        assert setup.decisions.repo.get("n1").status == "fallback"

    @pytest.mark.parametrize("change", ["quiet", "cancel", "goal", "disable", "read"])
    async def test_late_decision_cannot_override_changed_state(self, setup, change):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(_):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=response())

        setup.decisions.client = JevClient(httpx.MockTransport(handler))
        put(setup, delegation_id="same")
        setup.decisions.poll()
        await entered.wait()
        if change == "quiet":
            setup.quiet[0] = True
        elif change == "cancel":
            setup.notices.cancel_for("same")
        elif change == "goal":
            setup.decisions.goal = lambda _: "已经改变的目标"
        elif change == "disable":
            setup.decisions.configure(setup.settings.model_copy(update={"jev_mode": "off"}))
        else:
            setup.notices.read("n1")
        release.set()
        try:
            await setup.decisions.task
        except asyncio.CancelledError:
            assert change == "disable"
        record = setup.decisions.repo.get("n1")
        assert record.status in ("stale", "interrupted") and record.action == "defer"
        assert setup.notices.next(quiet=setup.quiet[0]) is None or change == "disable"

    async def test_concurrent_polls_make_one_call_and_recover_unknown(self, setup):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(_):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=response())

        setup.decisions.client = JevClient(httpx.MockTransport(handler))
        put(setup)
        for _ in range(10):
            setup.decisions.poll()
        await entered.wait()
        assert setup.decisions.repo.usage(setup.now[0])[0] == 1
        await setup.decisions.stop(close=True)
        record = setup.decisions.repo.get("n1")
        record.status = "running"  # Simulate a process loss after durable reservation.
        setup.decisions.repo.finish("n1", record)
        restarted = JevRepository(setup.db)
        assert restarted.get("n1").status == "interrupted"
        assert restarted.usage(setup.now[0])[0] == 1

    @pytest.mark.parametrize(
        "text", ["我的密码 abc123", "我的工资信息", "synthetic-jev", "联系 test@example.com"]
    )
    async def test_private_text_never_reaches_provider(self, setup, text):
        value = put(setup)
        with setup.db.transaction() as conn:
            value.text = text
            conn.execute(
                "UPDATE notification SET body=? WHERE id=?", (value.model_dump_json(), value.id)
            )
        await decide(setup)
        assert not setup.calls
        assert setup.decisions.repo.get("n1").status == "fallback"
        assert setup.decisions.repo.usage(setup.now[0]) == (0, 0)

    async def test_context_only_uses_same_delegation(self, setup):
        value = put(setup, delegation_id="same")
        for identity, delegation in [("same-history", "same"), ("other-history", "other")]:
            notice = put(setup, identity, delegation_id=delegation)
            notice.text = identity
            notice.status, notice.delivered_at = "delivered", 999.0
            with setup.db.transaction() as conn:
                conn.execute(
                    "UPDATE notification SET body=? WHERE id=?",
                    (notice.model_dump_json(), identity),
                )
        assert setup.decisions.context(value).recent_delivered == ["same-history"]
        await decide(setup)
        assert setup.calls[0]["state"]["goal"] == "准备面试资料"

    async def test_old_pending_notice_not_hidden_by_ui_page_limit(self, setup):
        put(setup)
        for index in range(501):
            notice = put(setup, f"old-{index}")
            setup.notices.read(notice.id)
        await decide(setup)
        assert setup.decisions.repo.get("n1").action == "notify"


class TestJevConfiguration:
    def test_key_never_enters_renderer_or_plain_setting_patch(self, setup):
        service = SettingsService(setup.settings, setup.db)
        view = service.view()
        assert view.credentials["typesafe_api_key"]
        assert "typesafe_api_key" not in view.values
        assert "synthetic-jev" not in view.model_dump_json()
        with pytest.raises(ValueError):
            service.patch(SettingsPatch(values={"typesafe_api_key": "no"}))

    def test_key_migration_uses_verified_secret_store(self, setup, tmp_path):
        saved = {}
        store = SimpleNamespace(set=lambda key, value: saved.update({key: value}), get=saved.get)
        path = tmp_path / ".env"
        path.write_text("TYPESAFE_API_KEY=synthetic-jev\nJEV_MODE=shadow\n")
        assert migrate_credentials(setup.db, path, store) == 1
        assert saved == {"typesafe_api_key": "synthetic-jev"}
        assert path.read_text() == "JEV_MODE=shadow\n"

    def test_credentials_load_independently(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.config.credentials.sys.platform", "darwin")
        monkeypatch.setenv("LLM_API_KEY", "explicit-llm")
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        monkeypatch.setattr(
            "core.config.credentials.read_credentials", lambda: {"typesafe_api_key": "stored-jev"}
        )
        assert load_settings().typesafe_api_key == "stored-jev"

    async def test_service_rpc_wiring_and_live_disable(self, setup):
        setup.settings.workspace_path.mkdir()
        service = ApplicationService(
            setup.settings, setup.db, SimpleNamespace(ready=asyncio.Event()), lambda _: None
        )

        async def call(method, params=None):
            return await service.handle(
                RpcRequest(jsonrpc="2.0", id=method, method=method, params=params or {})
            )

        put(setup)
        service.scheduler.decisions.client = setup.decisions.client
        assert await call("notification.next") is None
        await service.scheduler.decisions.task
        listing = await call("notification.list")
        assert listing[0]["decision"]["action"] == "notify"
        status = await call("jev.status")
        assert status["calls_today"] == 1 and status["configured"]
        assert "synthetic-jev" not in json.dumps(status)
        await call("settings.patch", {"values": {"jev_mode": "off"}})
        assert (await call("jev.status"))["mode"] == "off"
        await service.scheduler.close()
