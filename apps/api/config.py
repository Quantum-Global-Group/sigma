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

    # Sentiment provider selection: finbert | langextract | ollama | hybrid | none
    sentiment_provider: str = "finbert"
    langextract_api_key: str = ""
    langextract_api_url: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-instruct"

    # Execution — Coinbase Advanced Trade
    executor_mode: str = "paper"  # paper | coinbase
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

    # Strategy combiner (razorBill multi-strategy)
    enabled_strategies: str = "momentum,mean_reversion,breakout,regime,ml"
    strategy_weights: str = "0.2,0.2,0.2,0.2,0.2"
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
