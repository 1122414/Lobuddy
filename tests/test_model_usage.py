"""Model usage evidence and nanobot usage boundary tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agent.nanobot_gateway import NanobotGateway
from core.agent.token_meter_integration import TokenMeterIntegration
from core.models.model_usage import ModelUsageEvidence, ModelUsageSource
from core.runtime.token_meter import TokenMeter


def test_provider_usage_is_preferred_and_tool_results_are_not_double_counted() -> None:
    meter = TokenMeter()
    integration = TokenMeterIntegration(meter, "provider-model")

    evidence = integration.record_task_usage(
        session_key="session-1",
        prompt="private prompt",
        raw_output="private output",
        tools_used=["read_file", "read_file"],
        actual_usage={
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "cached_tokens": 700,
        },
    )

    assert evidence == ModelUsageEvidence(
        provider_model="provider-model",
        prompt_tokens=1200,
        completion_tokens=300,
        cached_tokens=700,
        source=ModelUsageSource.PROVIDER,
    )
    assert evidence.total_tokens == 1500
    stats = meter.get_last_call_stats("session-1")
    assert stats is not None
    assert stats["total_tokens"] == 1500
    assert stats["measurement_sources"] == {"provider": 1}
    assert set(stats["modules"]) == {"model_input", "model_output"}
    assert "private prompt" not in repr(stats)


def test_local_tokenization_is_explicitly_labeled_as_estimate() -> None:
    integration = TokenMeterIntegration(TokenMeter(), "unknown-local-model")

    evidence = integration.measure(
        prompt="请帮我整理这份计划",
        raw_output="已经整理完成",
        actual_usage={},
    )

    assert evidence.source == ModelUsageSource.LOCAL_ESTIMATE
    assert evidence.total_tokens > 0
    assert evidence.cached_tokens == 0


def test_unavailable_usage_is_not_reported_as_measured_zero() -> None:
    integration = TokenMeterIntegration(TokenMeter(), "unknown-local-model")

    evidence = integration.measure(prompt="", raw_output="", actual_usage={})

    assert evidence.source == ModelUsageSource.UNAVAILABLE
    assert evidence.available is False
    assert evidence.total_tokens == 0


def test_gateway_exposes_only_nonnegative_numeric_last_usage() -> None:
    loop = SimpleNamespace(
        _last_usage={
            "prompt_tokens": 100,
            "completion_tokens": 25.9,
            "cached_tokens": -3,
            "bad": "secret",
            "flag": True,
            "nan": float("nan"),
            "mystery_metric": 88,
        }
    )
    gateway = NanobotGateway(SimpleNamespace(_loop=loop))

    assert gateway.get_last_usage() == {
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "cached_tokens": 0,
    }


@pytest.mark.parametrize(
    "values",
    [
        {
            "prompt_tokens": 20,
            "cached_tokens": 21,
            "source": ModelUsageSource.PROVIDER,
        },
        {
            "prompt_tokens": 20,
            "source": ModelUsageSource.UNAVAILABLE,
        },
        {
            "source": ModelUsageSource.LOCAL_ESTIMATE,
        },
    ],
)
def test_invalid_usage_evidence_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ModelUsageEvidence(**values)
