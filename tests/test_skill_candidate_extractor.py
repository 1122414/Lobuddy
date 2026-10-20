"""Tests for SkillCandidateExtractor."""

import pytest

from core.skills.skill_candidate_extractor import SkillCandidateExtractor


class TestSkillCandidateExtractor:
    def test_should_extract_with_enough_tools(self):
        extractor = SkillCandidateExtractor(min_tools_used=2)
        assert extractor.should_extract(True, ["read_file", "write_file"]) is True

    def test_should_not_extract_with_few_tools(self):
        extractor = SkillCandidateExtractor(min_tools_used=2)
        assert extractor.should_extract(True, ["read_file"]) is False

    def test_should_not_extract_on_failure(self):
        extractor = SkillCandidateExtractor(min_tools_used=1)
        assert extractor.should_extract(False, ["read_file"]) is False

    def test_should_extract_with_strong_signal(self):
        extractor = SkillCandidateExtractor(min_tools_used=5)
        assert extractor.should_extract(True, ["read_file"], "以后这样处理") is True

    def test_extract_candidate_returns_none_when_not_qualifying(self):
        extractor = SkillCandidateExtractor(min_tools_used=5)
        result = extractor.extract_candidate("Do something", ["read_file"], "output")
        assert result is None

    def test_extract_candidate_generates_skill(self):
        extractor = SkillCandidateExtractor(min_tools_used=1)
        candidate = extractor.extract_candidate(
            "Sort a list of numbers",
            ["read_file", "exec"],
            "Used Python sorted()",
            session_id="sess1",
            task_id="task1",
        )
        assert candidate is not None
        assert "sort" in candidate.proposed_name
        assert "read_file" in candidate.proposed_content
        assert candidate.confidence == 0.7
        assert candidate.source_session_id == "sess1"

    def test_generate_name_sanitization(self):
        extractor = SkillCandidateExtractor()
        name = extractor._generate_name("Clean task name here")
        assert "-" in name
        assert all(c.isalnum() or c == "-" for c in name)

    def test_build_skill_md_format(self):
        extractor = SkillCandidateExtractor()
        md = extractor._build_skill_md("test-skill", "Do X", ["tool1"], "Result")
        assert md.startswith("---")
        assert "name: test-skill" in md
        assert "tool1" in md
        assert "Result" in md
