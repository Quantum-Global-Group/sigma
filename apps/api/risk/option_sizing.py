"""Option position sizing — defined-risk, contract-count composition (doc §4.5).

Options have a known max loss per contract, so sizing is "how many contracts
keep total max-loss within the risk budget", then floored by the layered caps:

    contracts = min(kelly_budget, risk_per_trade_cap, max_contracts,
                    drawdown_adjusted, liquidity_adjusted)

Uses fractional Kelly (never full). Pure + testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionSize:
    contracts: int
    risk_budget: float        # $ allocated to this trade's max loss
    max_loss_per_contract: float
    binding: str              # which cap bound the size


def option_position_size(
    *,
    equity: float,
    max_loss_per_contract: float,      # $ worst case for ONE contract (e.g. debit*100)
    kelly_fraction: float = 0.0,       # signed edge fraction in [0,1]; 0 → use risk_per_trade
    kelly_cap: float = 0.25,
    risk_per_trade: float = 0.02,      # fraction of equity riskable per trade
    max_contracts: int = 50,
    drawdown_factor: float = 1.0,      # 0..1, shrink after losses
    liquidity_factor: float = 1.0,     # 0..1, shrink on thin liquidity
) -> OptionSize:
    """Return the number of contracts to trade and the binding constraint."""
    if equity <= 0 or max_loss_per_contract <= 0:
        return OptionSize(0, 0.0, max_loss_per_contract, "no-budget")

    # Risk budget: the larger-bounded of fractional-Kelly and the flat per-trade cap.
    kelly = min(max(kelly_fraction, 0.0), kelly_cap)
    frac = max(kelly, risk_per_trade) if kelly > 0 else risk_per_trade
    frac *= max(0.0, min(1.0, drawdown_factor)) * max(0.0, min(1.0, liquidity_factor))
    risk_budget = equity * frac

    raw = risk_budget / max_loss_per_contract
    by_budget = int(raw)

    contracts = max(0, min(by_budget, max_contracts))
    if contracts == 0:
        binding = "below-one-contract" if by_budget == 0 else "zero"
    elif contracts == max_contracts and by_budget >= max_contracts:
        binding = "max_contracts"
    else:
        binding = "risk_budget"
    return OptionSize(
        contracts=contracts, risk_budget=round(risk_budget, 2),
        max_loss_per_contract=max_loss_per_contract, binding=binding,
    )
