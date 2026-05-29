from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategyParams(BaseModel):
    """razorBill nested risk/strategy parameters. Accessed as
    `settings.strategy.{kelly_cap, risk_var_95, risk_max_drawdown}`."""

    weight_model: float = Field(default=0.6, ge=0.0, le=1.0)
    weight_sent: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_regime: float = Field(default=0.2, ge=0.0, le=1.0)
    risk_var_95: float = Field(default=0.02, ge=0.0)
    risk_max_drawdown: float = Field(default=0.25, ge=0.0, le=1.0)
    kelly_cap: float = Field(default=0.25, ge=0.0, le=1.0)
    broker_fee_bps: int = Field(default=5, ge=0)
    slippage_bps: int = Field(default=5, ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True
    api_port: int = 8000
    secret_key: str = "change-me"

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/sigma"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    redis_url: str = "redis://localhost:6379"
    redis_ttl_signal: int = 3600
    redis_ttl_api_key: int = 86400

    rate_limit_free: int = 100
    rate_limit_pro: int = 10_000
    rate_limit_enterprise: int = 1_000_000

    model_dir: str = "./ml/saved_models"
    model_version: str = "v1.0"

    clerk_secret_key: str = ""
    clerk_jwt_key: str = ""

    stripe_secret_key: str = ""
    stripe_meter_id: str = ""

    sentry_dsn: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    ibm_quantum_token: str = ""
    huggingface_token: str = ""
    iex_api_key: str = ""

    # Service-to-service auth used by apps/worker. Empty string disables the
    # bypass entirely (production must set a value).
    internal_secret: str = ""
    system_user_id: str = "00000000-0000-0000-0000-000000000001"

    # Sentiment provider selection: finbert | langextract | hybrid | none
    sentiment_provider: str = "finbert"
    sentiment_min_docs: int = 3
    # LangExtract (uses the `langextract` Python package, optionally pointed at
    # a local Ollama server via lx_model_url). razorBill convention.
    lx_model_id: str = "mistral:7b-instruct"
    lx_model_url: str = "http://127.0.0.1:11434"
    langextract_api_key: str = ""

    # Execution — per-asset-class executor selection
    #   crypto → coinbase | paper
    #   equity → alpaca   | paper
    crypto_executor: str = "paper"
    equity_executor: str = "paper"
    # Deprecated global toggle, kept as a fallback for older deploys. If set to
    # something other than "paper", it overrides the per-asset default for that
    # venue. New config should use crypto_executor / equity_executor.
    executor_mode: str = "paper"  # paper | coinbase (legacy)

    # Execution — Alpaca (equities), via the modern alpaca-py SDK
    alpaca_api_key: str = ""
    alpaca_secret: str = ""
    alpaca_paper: bool = True
    alpaca_allow_live: bool = False        # hard guardrail: live needs this true
    alpaca_data_feed: str = "iex"          # iex (free) | sip (paid)

    # Equity market data — multi-source with fallback. The EquityAdapter tries
    # providers left-to-right, skipping any whose credentials are missing, and
    # returns the first non-empty result. yfinance is the last-resort fallback.
    #   tiingo → api.tiingo.com (needs tiingo_api_key)
    #   alpaca → alpaca-py StockHistoricalDataClient (reuses alpaca creds + feed)
    #   yfinance → free, least reliable
    equity_data_providers: str = "tiingo,alpaca,yfinance"
    tiingo_api_key: str = ""
    alpaca_order_timeout_seconds: int = 20
    alpaca_allow_fractional: bool = True
    alpaca_max_order_notional: float = 0.0  # 0 disables the cap
    alpaca_max_order_shares: float = 0.0    # 0 disables the cap

    # Execution — Coinbase Advanced Trade
    coinbase_api_key_name: str = ""
    coinbase_private_key: str = ""
    coinbase_sandbox: bool = True
    coinbase_order_timeout_seconds: int = 30
    # Legacy Coinbase format (pre-Advanced-Trade) — kept for back-compat with
    # razorBill deployments still using HMAC keys.
    coinbase_api_key: str = ""
    coinbase_api_secret: str = ""
    coinbase_api_passphrase: str = ""

    # Execution — fees, slippage, latency, fills
    maker_fee_bps: int = 4
    taker_fee_bps: int = 6
    base_slippage_bps: int = 5
    smallcap_slippage_bps: int = 50
    smallcap_price_threshold_usd: float = 2.0
    order_latency_ms: int = 0
    order_latency_jitter_min_ms: int = 0
    order_latency_jitter_max_ms: int = 0
    partial_fill_pct: float = 1.0  # 0 < partial_fill_pct <= 1.0

    # Worker live-loop cadence (seconds). Per-asset-class override via env.
    worker_tick_seconds_crypto: int = 300
    worker_tick_seconds_equity: int = 900

    # Fallback sizing equity when the executor can't report a live balance
    # (paper/sim venues). Alpaca reports its real account equity instead.
    default_equity: float = 10_000.0

    # Strategy combiner (razorBill multi-strategy)
    # Legacy global list — kept as a fallback when a per-asset list is empty.
    enabled_strategies: str = "momentum,mean_reversion,breakout,regime,ml"
    strategy_weights: str = "0.2,0.2,0.2,0.2,0.2"
    # Per-asset-class strategy selection. SDE strategies (gbm/ou/heston) assume
    # daily bars (dt=1/252) so they are equity-only; crypto runs 5m bars.
    crypto_strategies: str = "momentum,mean_reversion,breakout,regime,ml,macd,fourier"
    equity_strategies: str = "momentum,mean_reversion,breakout,regime,ml,macd,fourier,gbm,ou,heston,ict"
    # Empty → combiner falls back to equal weights across the selected list.
    crypto_strategy_weights: str = ""
    equity_strategy_weights: str = ""
    min_signal_confidence: float = 0.3
    strategy: StrategyParams = StrategyParams()

    # Risk / sizing (razorBill — referenced by apps/api/risk/)
    portfolio_max_exposure: float = 0.6     # fraction of equity buys cap at
    min_cash_reserve_usd: float = 25.0
    max_concurrent_positions: int = 6
    max_portfolio_loss_pct: float = 0.10
    max_daily_loss_pct: float = 0.05
    per_trade_notional_cap_usd: float = 0.0  # 0 disables
    per_symbol_notional_caps: str = ""        # e.g. "PEPE:75,API3:50"

    @property
    def per_symbol_caps_map(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for part in self.per_symbol_notional_caps.split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    out[k.strip().upper()] = float(v.strip())
                except ValueError:
                    continue
        return out

    # Exits (razorBill — consumed by worker.tick when use_advanced_exits=True)
    use_advanced_exits: bool = True
    stop_loss_pct: float = 0.01           # 1%
    take_profit_pct: float = 0.02         # 2%
    trailing_stop_pct: float = 0.01       # 1%
    trailing_stop_pct_after_tp: float = 0.01
    trailing_lookback_bars: int = 60
    move_stop_to_breakeven: bool = True
    max_hold_hours: int = 24
    exit_on_negative_signal: bool = True
    signal_exit_threshold: float = -0.3

    # Rebuy guard — prevent immediate re-entry after a SELL on the same symbol.
    rebuy_cooldown_min: int = 15

    # RankingModel (razorBill-derived crypto regressor)
    ranking_window: int = 30                # bars per training/inference sequence
    pred_horizon_bars: int = 3              # forward return horizon for label
    ranking_signal_threshold: float = 0.005 # |predicted_return| above this → BUY/SELL
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


settings = Settings()
