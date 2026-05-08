from __future__ import annotations

from abc import ABC, abstractmethod


class UniverseSelector(ABC):
    asset_class: str = ""

    @abstractmethod
    def select(self) -> list[str]:
        """Return the list of symbols the worker should evaluate this cycle."""
