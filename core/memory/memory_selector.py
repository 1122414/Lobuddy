"""Grounded structured-memory selection for prompt injection."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Optional

from core.config import Settings
from core.memory.memory_repository import MemoryRepository
from core.memory.memory_schema import (
    MemoryContextEvidence,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    PromptContextBundle,
)
from core.memory.privacy_mode import PrivacyModeManager
from core.memory.prompt_budget import PromptBudget
from core.memory.recall_policy import RecallPolicy, SessionRecallCandidate

logger = logging.getLogger(__name__)

_ENGLISH_STOPWORDS = {
    "about",
    "again",
    "and",
    "are",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "help",
    "how",
    "issue",
    "last",
    "me",
    "my",
    "of",
    "please",
    "problem",
    "remember",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "with",
    "you",
}
_CJK_STOP_TERMS = {
    "上次",
    "什么",
    "之前",
    "事情",
    "可以",
    "告诉",
    "问题",
    "帮我",
    "怎么",
    "怎样",
    "我们",
    "我的",
    "是否",
    "记得",
    "这个",
    "这些",
    "那个",
    "项目",
}
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]+")
_WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.+-]*")


def _term_weight(term: str) -> float:
    if term.isascii():
        return 1.2 if len(term) >= 5 else 0.8
    return {2: 0.55, 3: 0.85}.get(len(term), 1.15)


def _extract_terms(text: str, *, max_terms: int = 48) -> set[str]:
    """Extract deterministic lexical evidence without sending data elsewhere."""
    normalized = text.casefold()
    terms = {
        word
        for word in _WORD_PATTERN.findall(normalized)
        if len(word) >= 2 and word not in _ENGLISH_STOPWORDS
    }
    cjk_terms: list[str] = []
    for chunk in _CJK_PATTERN.findall(normalized):
        if 2 <= len(chunk) <= 4 and chunk not in _CJK_STOP_TERMS:
            cjk_terms.append(chunk)
        for size in (4, 3, 2):
            if len(chunk) < size:
                continue
            for index in range(len(chunk) - size + 1):
                term = chunk[index : index + size]
                if term not in _CJK_STOP_TERMS:
                    cjk_terms.append(term)
    for term in cjk_terms:
        terms.add(term)
        if len(terms) >= max_terms:
            break
    return terms


class MemorySelector:
    """Deep Module that applies scope, relevance, privacy, and budget policy."""

    _USER_SHARE = 0.34
    _SYSTEM_SHARE = 0.18
    _PROJECT_SHARE = 0.22
    _SUMMARY_SHARE = 0.12

    def __init__(
        self,
        settings: Settings,
        repo: Optional[MemoryRepository] = None,
        privacy: Optional[PrivacyModeManager] = None,
    ) -> None:
        self._settings = settings
        self._repo = repo or MemoryRepository()
        self._privacy = privacy
        self._budget = PromptBudget(
            settings.memory_prompt_budget_chars,
            settings.memory_prompt_budget_percent,
            settings.memory_prompt_budget_min_chars,
        )
        self._recall_policy = RecallPolicy(
            enabled=True,
            max_candidates_per_turn=settings.memory_max_episodic_results,
            min_relevance_threshold=settings.memory_recall_min_score,
            require_user_message_match=True,
        )

    def select_for_prompt(
        self,
        user_message: str,
        session_id: str = "",
    ) -> PromptContextBundle:
        bundle = PromptContextBundle()
        if not self._settings.memory_profile_inject_enabled:
            bundle.injection_enabled = False
            return bundle

        if session_id and self._privacy and self._privacy.is_privacy_active(session_id):
            logger.debug(
                "Memory recall suppressed because privacy is active for session=%s",
                session_id,
            )
            bundle.privacy_active = True
            return bundle

        overall_budget = self._budget.get_budget(user_message)
        query_terms = _extract_terms(user_message)
        selected_ids: set[str] = set()
        selected_item_ids: list[str] = []
        evidence: list[MemoryContextEvidence] = []
        budget_report: dict[str, int] = {}
        used_chars = 0

        user_items = self._active_items(
            self._repo.list_by_type(
                MemoryType.USER_PROFILE,
                MemoryStatus.ACTIVE,
                limit=50,
            ),
            session_id,
        )
        user_items.sort(
            key=lambda item: (item.priority, item.importance, item.updated_at),
            reverse=True,
        )
        user_cap = min(
            int(overall_budget * self._USER_SHARE),
            self._settings.memory_hot_user_profile_tokens * 4,
            self._settings.memory_profile_max_inject_chars,
            overall_budget - used_chars,
        )
        bundle.user_profile, item_evidence, item_ids = self._pack_items(
            user_items,
            max(0, user_cap),
            lambda item: f"- {item.content}",
            lambda _item: "用户档案优先级",
            selected_ids,
        )
        used_chars += len(bundle.user_profile)
        evidence.extend(item_evidence)
        selected_item_ids.extend(item_ids)
        budget_report["user_profile"] = len(bundle.user_profile)

        system_items = self._active_items(
            self._repo.list_by_type(
                MemoryType.SYSTEM_PROFILE,
                MemoryStatus.ACTIVE,
                limit=30,
            ),
            session_id,
        )
        system_items.sort(
            key=lambda item: (item.priority, item.importance, item.updated_at),
            reverse=True,
        )
        system_cap = min(
            int(overall_budget * self._SYSTEM_SHARE),
            self._settings.memory_hot_system_profile_tokens * 4,
            overall_budget - used_chars,
        )
        bundle.system_profile, item_evidence, item_ids = self._pack_items(
            system_items,
            max(0, system_cap),
            lambda item: f"- {item.content}",
            lambda _item: "助手设定优先级",
            selected_ids,
        )
        used_chars += len(bundle.system_profile)
        evidence.extend(item_evidence)
        selected_item_ids.extend(item_ids)
        budget_report["system_profile"] = len(bundle.system_profile)

        project_items = self._active_items(
            self._repo.list_by_type(
                MemoryType.PROJECT_MEMORY,
                MemoryStatus.ACTIVE,
                limit=80,
            ),
            session_id,
        )
        project_items.sort(
            key=lambda item: (
                self._score_memory(item, query_terms, session_id),
                item.priority,
                item.importance,
                item.updated_at,
            ),
            reverse=True,
        )
        project_cap = min(
            int(overall_budget * self._PROJECT_SHARE),
            self._settings.memory_hot_project_context_tokens * 4,
            overall_budget - used_chars,
        )
        bundle.project_context, item_evidence, item_ids = self._pack_items(
            project_items,
            max(0, project_cap),
            lambda item: f"- [{item.scope}] {item.content}",
            lambda item: (
                "当前请求关键词匹配" if self._score_memory(item, query_terms, session_id) > 0 else "项目上下文优先级"
            ),
            selected_ids,
        )
        used_chars += len(bundle.project_context)
        evidence.extend(item_evidence)
        selected_item_ids.extend(item_ids)
        budget_report["project_context"] = len(bundle.project_context)

        if session_id and overall_budget > used_chars:
            latest = self._repo.get_latest_summary(session_id)
            if latest:
                summary_cap = min(
                    int(overall_budget * self._SUMMARY_SHARE),
                    self._settings.memory_summary_max_chars,
                    overall_budget - used_chars,
                )
                bundle.session_summary = self._clip_text(latest.content, summary_cap)
                if bundle.session_summary:
                    used_chars += len(bundle.session_summary)
                    evidence.append(
                        MemoryContextEvidence(
                            memory_id=latest.id,
                            memory_type=MemoryType.CONVERSATION_SUMMARY,
                            reason="当前会话摘要",
                            chars=len(bundle.session_summary),
                        )
                    )
        budget_report["session_summary"] = len(bundle.session_summary)

        if user_message and query_terms and overall_budget > used_chars:
            recall_candidates = self._build_recall_candidates(query_terms, session_id)
            recalled = self._recall_policy.should_recall(recall_candidates)
            remaining_budget = overall_budget - used_chars
            bundle.retrieved_memories, item_evidence, item_ids = self._pack_items(
                [candidate.item for candidate in recalled],
                remaining_budget,
                lambda item: f"- [{item.memory_type.value}] {item.content}",
                lambda item: self._candidate_reason(recalled, item.id),
                selected_ids,
            )
            used_chars += len(bundle.retrieved_memories)
            evidence.extend(item_evidence)
            selected_item_ids.extend(item_ids)
        budget_report["retrieved_memories"] = len(bundle.retrieved_memories)

        bundle.total_chars = used_chars
        bundle.memory_budget_report = budget_report
        bundle.memory_evidence = evidence
        if selected_item_ids:
            self._repo.mark_used(selected_item_ids)
        return bundle

    def search_fts(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        return self._repo.search_fts(query, memory_type, limit)

    def _build_recall_candidates(
        self,
        query_terms: set[str],
        session_id: str,
    ) -> list[SessionRecallCandidate]:
        items = self._repo.list_recall_candidates(
            [MemoryType.EPISODIC_MEMORY, MemoryType.PROCEDURAL_MEMORY],
            limit=max(100, self._settings.memory_max_episodic_results * 40),
        )
        candidates: list[SessionRecallCandidate] = []
        for item in self._active_items(items, session_id):
            score = self._score_memory(item, query_terms, session_id)
            if score <= 0:
                continue
            overlap_count = len(query_terms & _extract_terms(f"{item.title} {item.content}"))
            candidates.append(
                SessionRecallCandidate(
                    item=item,
                    relevance_score=score,
                    source_session_id=item.source_session_id,
                    reason=f"命中 {overlap_count} 个请求关键词",
                )
            )
        return candidates

    @staticmethod
    def _candidate_reason(
        candidates: list[SessionRecallCandidate],
        item_id: str,
    ) -> str:
        for candidate in candidates:
            if candidate.item.id == item_id:
                return candidate.reason
        return "当前请求关键词匹配"

    @staticmethod
    def _pack_items(
        items: list[MemoryItem],
        cap: int,
        formatter: Callable[[MemoryItem], str],
        reason: Callable[[MemoryItem], str],
        selected_ids: set[str],
    ) -> tuple[str, list[MemoryContextEvidence], list[str]]:
        if cap <= 0:
            return "", [], []
        lines: list[str] = []
        evidence: list[MemoryContextEvidence] = []
        item_ids: list[str] = []
        used = 0
        for item in items:
            if item.id in selected_ids:
                continue
            line = formatter(item)
            contribution = len(line) + (1 if lines else 0)
            if used + contribution > cap:
                continue
            lines.append(line)
            used += contribution
            selected_ids.add(item.id)
            item_ids.append(item.id)
            evidence.append(
                MemoryContextEvidence(
                    memory_id=item.id,
                    memory_type=item.memory_type,
                    reason=reason(item),
                    chars=contribution,
                )
            )
        return "\n".join(lines), evidence, item_ids

    @staticmethod
    def _clip_text(text: str, cap: int) -> str:
        if cap <= 0:
            return ""
        if len(text) <= cap:
            return text
        if cap <= 3:
            return text[:cap]
        return text[: cap - 3].rstrip() + "..."

    @staticmethod
    def _active_items(items: list[MemoryItem], session_id: str) -> list[MemoryItem]:
        return [
            item
            for item in items
            if item.status == MemoryStatus.ACTIVE
            and not item.is_expired()
            and MemorySelector._scope_matches(item, session_id)
        ]

    @staticmethod
    def _scope_matches(item: MemoryItem, session_id: str) -> bool:
        if not item.scope.startswith("session:"):
            return True
        return bool(session_id) and item.scope.removeprefix("session:") == session_id

    @staticmethod
    def _score_memory(
        item: MemoryItem,
        query_terms: set[str],
        session_id: str,
    ) -> float:
        if not query_terms:
            return 0.0
        content_terms = _extract_terms(f"{item.title} {item.content}")
        overlap = query_terms & content_terms
        if not overlap:
            return 0.0
        matched_weight = sum(_term_weight(term) for term in overlap)
        query_weight = max(1.0, sum(_term_weight(term) for term in query_terms))
        match_strength = min(1.0, matched_weight / 4.0)
        coverage = min(1.0, matched_weight / query_weight)
        title_match = bool(query_terms & _extract_terms(item.title))
        same_session = bool(session_id and item.source_session_id == session_id)
        score = (
            0.48 * match_strength
            + 0.28 * coverage
            + (0.10 if title_match else 0.0)
            + 0.04 * item.importance
            + 0.03 * item.confidence
            + (0.03 if same_session else 0.0)
        )
        return min(1.0, score)
