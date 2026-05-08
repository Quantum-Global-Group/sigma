from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SentimentResult:
    score: float   # [-1, 1]
    n_docs: int


class SentimentProvider(ABC):
    name: str = ""

    @abstractmethod
    def score(self, headlines: list[str]) -> SentimentResult:
        """Aggregate sentiment across headlines into a single score in [-1, 1]."""
