"""Prompt budget controller for memory injection."""

from dataclasses import dataclass


@dataclass
class MemoryBundle:
    """A bundle of memory content with a priority."""

    content: str
    priority: int = 0
    source: str = ""


class PromptBudget:
    """Controls how much memory can be injected into a prompt."""

    def __init__(self, max_chars: int = 4000, max_percent: float = 0.20) -> None:
        self.max_chars = max_chars
        self.max_percent = max_percent

    def allocate(self, prompt: str, bundles: list[MemoryBundle]) -> list[MemoryBundle]:
        if prompt:
            budget = min(self.max_chars, int(len(prompt) * self.max_percent))
        else:
            budget = self.max_chars
        selected: list[MemoryBundle] = []
        used = 0
        for bundle in sorted(bundles, key=lambda b: b.priority, reverse=True):
            if used + len(bundle.content) <= budget:
                selected.append(bundle)
                used += len(bundle.content)
            else:
                break
        return selected

    def get_budget(self, prompt: str) -> int:
        return min(self.max_chars, int(len(prompt) * self.max_percent))
