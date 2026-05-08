"""Risk management, sizing, and exits.

Bodies are ported wholesale from razorBill (`risk_manager.py`, `sizing.py`,
`exits.py`, `portfolio_manager.py`). This package exposes the public surface
the worker tick uses; implementations land in the subtree step."""

from __future__ import annotations

__all__: list[str] = []
