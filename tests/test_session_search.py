"""Phase B: Session search service and chat repo search tests.

Verifies:
  - SessionSearchService.search() returns sanitized, bounded results
  - SessionSearchService rejects empty queries
  - ChatRepository.search_messages() works with LIKE
  - Budget limits enforced (per-item and total)
  - Scope enforcement (current_session vs all_sessions)
  - Secret sanitization (API keys, bearer tokens, emails)
"""

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from core.config import Settings
from core.storage.chat_repo import ChatRepository
from core.storage.db import Database
from core.models.chat import ChatMessage


def _make_settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        llm_api_key="test",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        workspace_path=tmp_path / "workspace",
        memory_enable_migration=False,
        **kwargs,
    )


def _make_chat_repo(tmp_path: Path) -> ChatRepository:
    settings = _make_settings(tmp_path)
    db = Database(settings)
    db.init_database()
    return ChatRepository(db=db)


def _seed_messages(repo: ChatRepository, session_id: str, messages: list[dict]) -> None:
    repo.get_or_create_session(session_id, pet_id="test", title=f"Test {session_id}")
    for i, msg in enumerate(messages):
        repo.save_message(ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=msg.get("role", "user"),
            content=msg["content"],
            created_at=datetime(2026, 5, 3, 10, i, 0),
        ))


class TestChatRepoSearch:
    def test_search_finds_matching_content(self, tmp_path: Path):
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [
            {"content": "Hello, I love Python programming"},
            {"content": "Let's use TypeScript for this project"},
            {"content": "Python is great for data science"},
        ])
        results = repo.search_messages("Python", limit=10)
        assert len(results) == 2
        assert all("Python" in r.content for r in results)

    def test_search_no_results(self, tmp_path: Path):
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [
            {"content": "Hello world"},
        ])
        results = repo.search_messages("NonexistentQuery", limit=10)
        assert len(results) == 0

    def test_search_filters_by_session(self, tmp_path: Path):
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "Python in session 1"}])
        _seed_messages(repo, "s2", [{"content": "Python in session 2"}])
        results = repo.search_messages("Python", session_id="s1", limit=10)
        assert len(results) == 1
        assert results[0].session_id == "s1"
        assert "session 1" in results[0].content

    def test_search_respects_limit(self, tmp_path: Path):
        repo = _make_chat_repo(tmp_path)
        for i in range(20):
            _seed_messages(repo, "s1", [{"content": f"Python message {i}"}])
        results = repo.search_messages("Python", limit=5)
        assert len(results) == 5

    def test_search_sorted_by_recency(self, tmp_path: Path):
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [
            {"content": "Older Python note"},
            {"content": "Newer Python note"},
        ])
        results = repo.search_messages("Python", limit=10)
        assert results[0].content == "Newer Python note"


class TestSessionSearchService:
    def _make_service(self, tmp_path: Path, **kwargs):
        from core.memory.session_search import SessionSearchService, SessionSearchScope
        settings = _make_settings(tmp_path, **kwargs)
        repo = _make_chat_repo(tmp_path)
        return SessionSearchService(settings, chat_repo=repo), SessionSearchScope

    def test_empty_query_rejected(self, tmp_path: Path):
        service, _ = self._make_service(tmp_path)
        response = service.search("", current_session_id="s1")
        assert response.total_found == 0
        assert "Empty query" in response.note

    def test_search_current_session(self, tmp_path: Path):
        service, scope = self._make_service(tmp_path)
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "Python rocks"}])
        _seed_messages(repo, "s2", [{"content": "Python elsewhere"}])
        response = service.search(
            "Python", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.total_shown >= 1
        assert all(r.session_id == "s1" for r in response.results)

    def test_search_all_sessions_controlled_by_settings(self, tmp_path: Path):
        service, scope = self._make_service(
            tmp_path, memory_session_search_default_scope="current_session"
        )
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "Chat in session one"}])
        _seed_messages(repo, "s2", [{"content": "Chat in session two"}])
        response = service.search(
            "Chat", current_session_id="s1", scope=scope.ALL_SESSIONS, limit=10,
        )
        assert response.scope == "current_session"
        assert all(r.session_id == "s1" for r in response.results)

    def test_per_item_truncation(self, tmp_path: Path):
        service, scope = self._make_service(
            tmp_path, memory_session_search_max_result_chars=10,
        )
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "A very long message that should be truncated"}])
        response = service.search(
            "very long", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.total_shown >= 1
        for r in response.results:
            assert len(r.content) <= 13

    def test_total_budget_enforcement(self, tmp_path: Path):
        service, scope = self._make_service(
            tmp_path,
            memory_session_search_max_result_chars=1000,
            memory_session_search_total_budget_chars=30,
        )
        repo = _make_chat_repo(tmp_path)
        for i in range(5):
            _seed_messages(repo, "s1", [{"content": f"Match keyword with a bit of content {i}"}])
        response = service.search(
            "keyword", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.budget_exhausted
        assert response.total_shown < response.total_found

    def test_sanitizes_api_keys(self, tmp_path: Path):
        service, scope = self._make_service(tmp_path)
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "My key is sk-1234567890abcdef1234567890abcdef"}])
        response = service.search(
            "key", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.total_shown >= 1
        assert "sk-" not in response.results[0].content
        assert "REDACTED" in response.results[0].content

    def test_sanitizes_bearer_tokens(self, tmp_path: Path):
        service, scope = self._make_service(tmp_path)
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "Auth: Bearer abc123def456ghi789jkl"}])
        response = service.search(
            "Auth", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.total_shown >= 1
        assert "Bearer" not in response.results[0].content

    def test_sanitizes_emails(self, tmp_path: Path):
        service, scope = self._make_service(tmp_path)
        repo = _make_chat_repo(tmp_path)
        _seed_messages(repo, "s1", [{"content": "Email me at user@example.com"}])
        response = service.search(
            "Email", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=5,
        )
        assert response.total_shown >= 1
        assert "user@example.com" not in response.results[0].content

    def test_limit_capped_at_10(self, tmp_path: Path):
        service, scope = self._make_service(tmp_path)
        repo = _make_chat_repo(tmp_path)
        for i in range(15):
            _seed_messages(repo, "s1", [{"content": f"Zebra message {i}"}])
        response = service.search(
            "Zebra", current_session_id="s1", scope=scope.CURRENT_SESSION, limit=50,
        )
        assert response.total_shown <= 10
