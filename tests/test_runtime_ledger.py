"""Atomic settlement: repeated events, restart recovery and rollback never multiply rewards."""

from pathlib import Path

import pytest

from core.config import Settings
from core.service.knowledge import KnowledgeService
from core.service.protocol import TurnState
from core.skills.skill_schema import SkillRecord, SkillStatus
from core.storage.db import Database
from core.storage.runtime_ledger import RuntimeLedger
from core.storage.service_repo import ServiceRepository


@pytest.fixture
def ledger(tmp_path: Path) -> RuntimeLedger:
    settings = Settings(
        llm_api_key="test", data_dir=tmp_path / "data", workspace_path=tmp_path / "workspace"
    )
    settings.workspace_path.mkdir()
    db = Database(settings)
    db.init_database()
    ServiceRepository(db)
    knowledge = KnowledgeService(settings, db)
    knowledge.skills.create_skill(
        SkillRecord(
            id="skill-a", name="skill-a", path="", description="test", status=SkillStatus.ACTIVE
        ),
        "content",
    )
    return RuntimeLedger(db)


def turn(identity: str = "a", status: str = "completed") -> TurnState:
    return TurnState.model_validate(
        {
            "turn_id": identity,
            "task_id": identity,
            "session_id": "session-a",
            "engine_id": "engine-a",
            "lane": "foreground",
            "input_text": "你好",
            "status": status,
        }
    )


class TestRuntimeLedger:
    def test_duplicate_settlement_and_skill_use(self, ledger: RuntimeLedger) -> None:
        state = turn()
        ledger.record_skill_use(state, "skill-a")
        ledger.record_skill_use(state, "skill-a")
        first = ledger.settle(state)
        assert ledger.settle(state) == first
        restarted = RuntimeLedger(ledger.db)
        assert restarted.settle(state) == first
        pet = restarted.pet.get_or_create_pet()
        assert pet.exp == 5
        assert pet.personality.diligence == 50.3
        with ledger.db.get_connection() as conn:
            assert (
                conn.execute(
                    "SELECT success_count FROM skill_record WHERE id='skill-a'"
                ).fetchone()[0]
                == 0
            )
            assert conn.execute("SELECT COUNT(*) FROM skill_use").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM task_result").fetchone()[0] == 1

    @pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
    def test_unsuccessful_turn_has_no_reward(self, ledger: RuntimeLedger, status: str) -> None:
        ledger.settle(turn(status=status))
        assert ledger.pet.get_or_create_pet().exp == 0

    def test_usage_duplicate_does_not_inflate_disjoint_cache_counts(
        self, ledger: RuntimeLedger
    ) -> None:
        value = {
            "inputTokens": 10,
            "outputTokens": 20,
            "cacheReadTokens": 30,
            "cacheWriteTokens": 40,
        }
        ledger.usage(turn(), 4, value)
        ledger.usage(turn(), 4, value)
        usage = ledger.summary()["usage"]
        assert usage == {"input": 80, "output": 20, "cached": 70, "calls": 1}

    def test_transaction_rolls_back_when_settlement_write_fails(
        self, ledger: RuntimeLedger
    ) -> None:
        with ledger.db.transaction() as conn:
            conn.execute(
                "CREATE TRIGGER reject_settlement BEFORE INSERT ON turn_settlement BEGIN SELECT RAISE(ABORT, 'injected'); END"
            )
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            ledger.settle(turn())
        assert ledger.pet.get_pet() is None
        with ledger.db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM task_record").fetchone()[0] == 0
        with ledger.db.transaction() as conn:
            conn.execute("DROP TRIGGER reject_settlement")
        ledger.settle(turn())
        assert ledger.pet.get_or_create_pet().exp == 5
