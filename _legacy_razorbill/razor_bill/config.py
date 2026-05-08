from __future__ import annotations

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger


class StrategyParams(BaseModel):
    weight_model: float = Field(default=0.6, ge=0.0, le=1.0)
    weight_sent: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_regime: float = Field(default=0.2, ge=0.0, le=1.0)
    risk_var_95: float = Field(default=0.02, ge=0.0)
    risk_max_drawdown: float = Field(default=0.25, ge=0.0, le=1.0)
    kelly_cap: float = Field(default=0.25, ge=0.0, le=1.0)
    broker_fee_bps: int = Field(default=5, ge=0)
    slippage_bps: int = Field(default=5, ge=0)

    @field_validator("weight_regime")
    @classmethod
    def _validate_weights(cls, v: float, info: ValidationInfo) -> float:
        # called when weight_regime validated; we can access other fields
        values = info.data
        wm = values.get("weight_model", 0.0)
        ws = values.get("weight_sent", 0.0)
        wr = v
        total = wm + ws + wr
        if abs(total - 1.0) > 1e-6:
            logger.warning(
                "Strategy weights do not sum to 1.0 (sum={:.3f}). Using provided values.", total
            )
        return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "dev"
    data_interval_min: int = 5
    equity: float = 10000.0
    window: int = 30  # Reduce from 60 to 30
    universe: str = "BTC-USD,LTC-USD,ETH-USD,FIL-USD,HNT-USD"  # Only symbols with 60+ bars

    # Dynamic universe (optional)
    dynamic_universe: bool = False
    universe_quote: str = "USD"
    universe_top_n: int = 6
    universe_refresh_min: int = 30
    vol_timeframe: str = "1m"
    vol_lookback: int = 600
    min_quote_volume_24h: float = 1_000_000.0
    max_price_usd: float = 10.0
    max_market_cap_usd: float = 200_000_000.0
    # Comma-separated list of base symbols to exclude (e.g., "BTC,ETH")
    exclude_bases: str = ""

    # DB defaults to local SQLite; can be overridden to Postgres
    db_url: str = "sqlite+aiosqlite:///./bot.db"

    # Keys
    # Coinbase Advanced Trade API - use api_key_name and private_key (new format)
    coinbase_api_key_name: str | None = None  # The API key name/ID from Coinbase
    coinbase_private_key: str | None = None  # The EC private key from Coinbase
    # Legacy format (for backward compatibility, but Advanced Trade uses private_key)
    coinbase_api_key: str | None = None
    coinbase_api_secret: str | None = None
    coinbase_api_passphrase: str | None = None
    langextract_api_key: str | None = None
    
    # Executor configuration
    executor_mode: str = "paper"  # Options: "paper" or "coinbase"
    coinbase_sandbox: bool = False  # Use sandbox environment for testing
    coinbase_order_timeout_seconds: int = 30  # Timeout for order status polling

    # Sentiment config
    sentiment_provider: str = "none"  # options: none|finbert|langextract|hybrid
    sentiment_min_docs: int = 3

    strategy: StrategyParams = StrategyParams()

    lx_model_id: str = "mistral:7b-instruct"
    lx_model_url: str = "http://127.0.0.1:11434"
    # Modeling knobs
    pred_horizon_bars: int = 3  # predict next N bars return
    top_k_buy: int = 0  # 0 disables; if >0, buy top-K by model score each cycle
    # Model params (LightGBM/XGBoost)
    lgb_n_estimators: int = 200
    lgb_learning_rate: float = 0.05
    lgb_max_depth: int = -1
    lgb_subsample: float = 0.8
    lgb_colsample_bytree: float = 0.8
    lgb_reg_alpha: float = 0.0
    lgb_reg_lambda: float = 1.0
    xgb_n_estimators: int = 300
    xgb_learning_rate: float = 0.05
    xgb_max_depth: int = 6
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_alpha: float = 0.0
    xgb_reg_lambda: float = 1.0
    model_path: str = "./model.bin"
    # Universe score weights (1h, 24h, vola*liquidity)
    score_w_1h: float = 0.5
    score_w_24h: float = 0.3
    score_w_vliq: float = 0.2
    # Risk/sizing
    per_trade_notional_cap_usd: float = 0.0  # 0 disables; >0 caps notional per trade
    per_symbol_notional_caps: str = ""  # e.g., "PEPE:75,API3:50"
    portfolio_max_exposure: float = 0.6  # fraction of EQUITY; buys stop above this
    min_cash_reserve_usd: float = 25.0   # keep at least this much cash unspent
    # Stablecoin exclusion
    exclude_stablecoins: bool = True
    # Rebuy controls
    rebuy_cooldown_min: int = 15
    rebuy_lookback_min: int = 60
    max_adds_per_symbol: int = 2
    skip_add_if_unrealized_negative: bool = True
    min_add_up_pct: float = 0.02
    # Slippage
    smallcap_slippage_bps: int = 50
    smallcap_price_threshold_usd: float = 2.0
    maker_fee_bps: int = 4
    taker_fee_bps: int = 6
    order_latency_ms: int = 0
    partial_fill_pct: float = 1.0  # 0<partial<=1.0 for partial fills
    order_latency_jitter_min_ms: int = 0
    order_latency_jitter_max_ms: int = 0
    use_spread_slippage: bool = False
    spread_bps_base: int = 10
    use_liquidity_impact: bool = False
    liquidity_impact_coeff: float = 0.001
    # Exits - TEMPORARILY TIGHT FOR TESTING
    stop_loss_pct: float = 0.01    # 1% stop loss (very tight for testing)
    take_profit_pct: float = 0.02  # 2% take profit (very tight for testing)
    trailing_stop_pct: float = 0.01
    trailing_lookback_bars: int = 60
    tp_partial_fraction: float = 0.5
    trailing_stop_pct_after_tp: float = 0.01
    move_stop_to_breakeven: bool = True
    reset_positions_on_start: bool = False
    max_concurrent_positions: int = 6

    # Time-based exits - TEMPORARILY TIGHT FOR TESTING
    max_hold_hours: int = 2        # Exit after 2 hours (tight for testing)
    max_portfolio_loss_pct: float = 0.10
    max_daily_loss_pct: float = 0.05
    
    # Enhanced exit controls - TEMPORARILY TIGHT FOR TESTING
    exit_on_negative_signal: bool = True
    signal_exit_threshold: float = -0.3  # Tighter threshold
    
    # Multi-Strategy Configuration
    enabled_strategies: str = "momentum,mean_reversion,breakout,regime,ml"  # Comma-separated
    strategy_weights: str = "0.2,0.2,0.2,0.2,0.2"  # Weights for each strategy (must match enabled_strategies)
    min_signal_confidence: float = 0.3  # Minimum confidence to trade
    
    # Position Sizing Configuration
    sizing_method: str = "kelly"  # Options: kelly, volatility_target, risk_parity, fixed_fractional, atr_based
    target_volatility: float = 0.15  # Target annualized volatility (for volatility_target method)
    fixed_fractional_pct: float = 0.1  # Fixed percentage of equity (for fixed_fractional method)
    atr_risk_per_trade: float = 0.01  # Risk per trade as fraction of equity (for atr_based method)
    
    # Advanced Exit Strategy Configuration
    use_atr_trailing: bool = False
    trailing_stop_atr_multiplier: float = 2.0
    use_volatility_exit: bool = False
    volatility_exit_threshold: float = 1.5
    use_trend_reversal_exit: bool = False
    use_partial_profits: bool = False
    partial_profit_targets: str = "0.02,0.05,0.10"  # Comma-separated profit targets (2%, 5%, 10%)
    partial_profit_fractions: str = "0.25,0.25,0.25"  # Comma-separated fractions to sell at each target
    use_time_decay_exit: bool = False
    time_decay_factor: float = 0.5
    
    # Portfolio Management Configuration
    rebalance_threshold: float = 0.1  # Maximum drift before rebalancing
    rebalance_interval_hours: int = 24  # Minimum time between rebalances
    max_position_concentration: float = 0.25  # Maximum fraction of equity in single position
    min_diversification_score: float = 0.3  # Minimum diversification score
    
    # Multi-Timeframe Configuration
    use_multi_timeframe: bool = False
    primary_timeframe: str = "5m"
    higher_timeframe_filter: bool = True  # Filter entries by higher timeframe trend
    min_timeframe_alignment: float = 0.6  # Minimum alignment score to trade
    
    # Risk Management Configuration
    use_portfolio_var: bool = True  # Use portfolio-level VaR
    use_correlation_adjustment: bool = True  # Adjust sizing based on correlation
    correlation_lookback: int = 100  # Bars to use for correlation calculation
    circuit_breaker_enabled: bool = True  # Enable circuit breakers on large losses

    @property
    def universe_list(self) -> list[str]:
        return [s.strip() for s in self.universe.split(",") if s.strip()]

    @property
    def exclude_bases_list(self) -> list[str]:
        return [s.strip().upper() for s in self.exclude_bases.split(",") if s.strip()]

    @property
    def per_symbol_caps_map(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for part in self.per_symbol_notional_caps.split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    out[k.strip().upper()] = float(v.strip())
                except Exception:
                    continue
        return out
    
    @property
    def enabled_strategies_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_strategies.split(",") if s.strip()]
    
    @property
    def strategy_weights_list(self) -> list[float]:
        weights = [float(w.strip()) for w in self.strategy_weights.split(",") if w.strip()]
        # Normalize weights
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        return weights
    
    @property
    def strategy_weights_dict(self) -> dict[str, float]:
        strategies = self.enabled_strategies_list
        weights = self.strategy_weights_list
        # Pad or trim weights to match strategies
        while len(weights) < len(strategies):
            weights.append(0.0)
        weights = weights[:len(strategies)]
        return dict(zip(strategies, weights))
    
    @property
    def partial_profit_targets_list(self) -> list[float]:
        return [float(t.strip()) for t in self.partial_profit_targets.split(",") if t.strip()]
    
    @property
    def partial_profit_fractions_list(self) -> list[float]:
        return [float(f.strip()) for f in self.partial_profit_fractions.split(",") if f.strip()]


settings = Settings()
