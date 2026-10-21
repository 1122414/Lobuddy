"""Cross-stage forgetting and additive migration / snapshot invariants."""

import json
from pathlib import Path

from core.config import Settings
from core.models.chat import ChatMessage
from core.service.knowledge import KnowledgeService
from core.service.protocol import TurnState
from core.service.relationship_protocol import RelationProposal
from core.service.workflow_evaluation import context_definition
from core.storage.db import Database
from core.storage.learning_repo import LearningRepository
from core.storage.upgrade_backup import create_backup, import_backup, restore_snapshot


def service(root: Path):
    settings = Settings(
        llm_api_key="test",
        _env_file=None,
        data_dir=root / "data",
        workspace_path=root / "workspace",
        memory_enable_migration=False,
    )
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    db = Database(settings)
    db.init_database(allow_desktop=True)
    return KnowledgeService(settings, db)


class TestEvolutionIntegration:
    def test_forgetting_correction_erases_skill_derivations_and_blocks_jobs(self, tmp_path):
        k = service(tmp_path)
        k.chat.get_or_create_session("s")
        text = "以后整理文件时先给我按类型的数量。"
        k.chat.save_message(ChatMessage(id="t", session_id="s", role="user", content=text))
        relation = k.relationship.admit(
            RelationProposal(
                kind="preference", key="file-order", content=text, quote=text, source_ids=["t"]
            ),
            "s",
            trusted_explicit=True,
        )
        assert relation and relation.status == "active"
        turn = TurnState(
            turn_id="t",
            task_id="task",
            session_id="s",
            engine_id="e",
            lane="foreground",
            status="completed",
            input_text=text,
        )
        identity = k.learn_outcome(turn)["candidate_id"]
        created = k.skills.approve_candidate(identity)
        assert created and text in k.skills.get_content(created.id)
        k.skills.archive_skill(created.id)
        jobs = LearningRepository(k.db)
        for kind in ("relationship", "skill_evidence", "workflow_proposal"):
            jobs.enqueue(kind, "t", 0)
        # A superseded source is already excluded from retrieval before final forgetting.
        with k.db.transaction() as conn:
            conn.execute("INSERT INTO relationship_barrier VALUES('t','fixture')")
        k.relationship.forget(relation.id)
        assert k.learn_outcome(turn) == {"skipped": "forgotten_source"}
        assert text not in k.skills.get_content(created.id)
        assert all(
            text not in json.dumps(row, ensure_ascii=False) for row in k.skills.versions(created.id)
        )
        assert all(text not in p.read_text() for p in k.skills._archive_dir.glob("*.md"))
        assert k.skills.get_candidate(identity).status == "rejected"
        assert all(j.attempts == 3 for j in jobs.jobs())
        restarted = KnowledgeService(k.settings, k.db)
        assert restarted.learn_outcome(turn) == {"skipped": "forgotten_source"}

    def test_additive_schema_twice_and_full_snapshot_restore(self, tmp_path):
        k = service(tmp_path / "original")
        candidate = k.workflows.propose(context_definition("compact"), "测试来源", ["fixture"])
        k.workflows.evaluate(candidate.version_id)
        k.workflows.context({"records": [{"id": "kept"}]}, "fixture-run")

        def dump(db):
            with db.get_connection() as conn:
                tables = (
                    "workflow_version",
                    "workflow_active",
                    "workflow_observation",
                    "relationship",
                    "relationship_barrier",
                    "learning_schema",
                    "skill_version",
                    "skill_candidate_revision",
                )
                return {
                    table: [
                        tuple(r) for r in conn.execute("SELECT * FROM " + table + " ORDER BY rowid")
                    ]
                    for table in tables
                }

        before = dump(k.db)
        KnowledgeService(k.settings, k.db)
        KnowledgeService(k.settings, k.db)
        assert dump(k.db) == before
        backup = tmp_path / "backup"
        target = tmp_path / "imported"
        create_backup(k.settings.data_dir, k.settings.workspace_path, backup)
        assert import_backup(backup, target)["imported"] is True
        assert import_backup(backup, target)["imported"] is False
        imported = service(target)
        assert dump(imported.db) == before
        restored = tmp_path / "restored"
        restore_snapshot(backup, restored)
        assert (restored / "data/lobuddy.db").read_bytes() == (
            backup / "data/lobuddy.db"
        ).read_bytes()

    def test_later_different_scenario_cannot_hide_unknown_goal(self, tmp_path):
        from core.service.outcomes import Outcome, OutcomeRepository

        k = service(tmp_path)
        r = OutcomeRepository(k.db)
        r.save(Outcome(turn_id="multi", scenario="organize", reason="仅预览，未复制"))
        r.save(Outcome(turn_id="multi", scenario="digest", verdict="verified", reason="来源完整"))
        assert r.get("multi").verdict == "unknown"
        assert "未复制" in r.get("multi").reason

    def test_legacy_current_skill_body_is_snapshotted_before_first_edit(self, tmp_path):
        from core.skills.skill_schema import SkillRecord, SkillStatus

        k = service(tmp_path)
        k.skills.create_skill(
            SkillRecord(
                id="old",
                name="old",
                path="",
                description="legacy",
                version=7,
                status=SkillStatus.ACTIVE,
            ),
            "original",
        )
        with k.db.transaction() as conn:
            conn.execute("UPDATE skill_record SET content='' WHERE id='old'")
            conn.execute("DELETE FROM skill_version WHERE skill_id='old'")
        k.skills.patch_skill("old", "updated")
        assert [(v["version"], v["content"]) for v in k.skills.versions("old")] == [
            (8, "updated"),
            (7, "original"),
        ]
