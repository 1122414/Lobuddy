"""Regression contracts for the skill implementations recovered from Git history."""

from core.skills.skill_candidate_extractor import SkillCandidateExtractor
from core.skills.skill_schema import SkillCandidate
from core.skills.skill_validator import SkillValidator


class TestRecoveredSkillContracts:
    def test_candidate_evidence_does_not_copy_credentials(self) -> None:
        candidate = SkillCandidateExtractor().extract_candidate(
            "保存为技能 user@example.com",
            ["read_file", "write_file"],
            "password=hunter22 Bearer abc123 sk-12345678901234567890",
        )
        assert candidate is not None
        for secret in ("user@example.com", "hunter22", "abc123", "sk-12345678901234567890"):
            assert secret not in candidate.proposed_content
        assert "[REDACTED" in candidate.proposed_content

    def test_extracted_workflow_passes_static_validation(self) -> None:
        candidate = SkillCandidateExtractor().extract_candidate(
            "Sort a list", ["read_file", "write_file"], "Verified sorted output"
        )
        assert candidate is not None
        valid, errors = SkillValidator().validate_static(candidate.proposed_content)
        assert valid, errors

    def test_dangerous_candidate_is_rejected(self) -> None:
        candidate = SkillCandidate(
            id="unsafe",
            title="Unsafe workflow",
            rationale="Regression fixture",
            proposed_name="unsafe-workflow",
            proposed_content="## When to use\nUse this workflow to run rm -rf /tmp/example repeatedly.",
        )
        valid, errors = SkillValidator().validate(candidate)
        assert not valid
        assert any("dangerous" in error for error in errors)
