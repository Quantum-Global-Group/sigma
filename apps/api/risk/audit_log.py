"""Decision audit log — full provenance for every option trade decision.

Captures the chain the QSP brief and Moomoo doc §5/§8 require: data → features →
signal → risk → optimizer → order, with the gate outcomes. Regulators and
post-mortems need this; it's also how we explain *why* a trade was (not) taken.
In-memory + JSON-serializable; the worker persists it (P6).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class AuditRecord:
    symbol: str
    asset_class: str = "option"
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict = field(default_factory=dict)          # source, staleness, spread
    features: dict = field(default_factory=dict)       # iv_rank, regime, etc.
    signal: dict = field(default_factory=dict)         # direction, strength, model
    strategy: Optional[str] = None
    risk: dict = field(default_factory=dict)           # sizing, greeks, limits
    gates: list[dict] = field(default_factory=list)    # [{gate, passed, reasons}]
    decision: str = "pending"                          # placed | skipped | rejected
    order: dict = field(default_factory=dict)          # client_order_id, qty, px
    notes: Optional[str] = None

    def gate(self, name: str, passed: bool, reasons: Optional[list[str]] = None) -> "AuditRecord":
        self.gates.append({"gate": name, "passed": passed, "reasons": reasons or []})
        return self

    def finalize(self, decision: str, **order_fields: Any) -> "AuditRecord":
        self.decision = decision
        if order_fields:
            self.order.update(order_fields)
        return self

    @property
    def all_gates_passed(self) -> bool:
        return all(g["passed"] for g in self.gates)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditLog:
    records: list[AuditRecord] = field(default_factory=list)

    def new(self, symbol: str, **kw) -> AuditRecord:
        rec = AuditRecord(symbol=symbol, **kw)
        self.records.append(rec)
        return rec

    def placed(self) -> list[AuditRecord]:
        return [r for r in self.records if r.decision == "placed"]

    def to_list(self) -> list[dict]:
        return [r.to_dict() for r in self.records]
