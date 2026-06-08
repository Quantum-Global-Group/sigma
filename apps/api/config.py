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
    # SQLAlchemy statement echo. Off by default — it floods logs; use Langfuse
    # traces / Sentry / the web dashboard for observability instead of SQL logs.
    db_echo: bool = False
    api_port: int = 8001
    api_host: str = "0.0.0.0"
    secret_key: str = "change-me"
    # Comma-separated browser origins allowed to call the API (split-server dev/prod).
    cors_origins: str = "http://localhost:3001"

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

    # MLflow experiment tracking for *training* runs (Langfuse traces inference).
    # Empty tracking URI → MLflow's local ./mlruns file store (no server needed).
    mlflow_tracking_uri: str = ""
    mlflow_experiment: str = "sigma-training"

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
    #   option → moomoo   | paper
    #   forex  → oanda | mt5 | paper
    crypto_executor: str = "paper"
    equity_executor: str = "paper"
    option_executor: str = "paper"
    forex_executor: str = "paper"
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
    # returns the first non-empty result. Tiingo is the fallback when Alpaca fails.
    #   alpaca → alpaca-py StockHistoricalDataClient (reuses alpaca creds + feed)
    #   tiingo → api.tiingo.com (needs tiingo_api_key)
    equity_data_providers: str = "alpaca,tiingo"
    tiingo_api_key: str = ""
    alpaca_order_timeout_seconds: int = 20
    alpaca_allow_fractional: bool = True
    alpaca_max_order_notional: float = 0.0  # 0 disables the cap
    alpaca_max_order_shares: float = 0.0    # 0 disables the cap

    # Execution + data — Moomoo (US equities & options) via the OpenD gateway.
    # The moomoo/futu SDK connects to a local OpenD daemon, not a cloud REST API,
    # so the options worker runs where OpenD is reachable (local/VPS lab first).
    moomoo_host: str = "127.0.0.1"
    moomoo_port: int = 11111
    moomoo_trd_market: str = "US"          # TrdMarket.US
    moomoo_security_firm: str = "FUTUINC"  # SecurityFirm.FUTUINC
    moomoo_paper: bool = True
    moomoo_allow_live: bool = False        # hard guardrail: live needs this true
    # OpenD supervision — the options worker probes the gateway each tick. When it
    # is unreachable the tick is skipped; if opend_restart_command is set it runs
    # once (best-effort) to bring OpenD back. Empty = alert-only (no auto-restart).
    opend_check_enabled: bool = True
    opend_restart_command: str = ""

    # Execution + data — OANDA (forex) via the v20 REST API (oandapyV20). OANDA
    # is a cloud broker with practice + live environments; the adapter serves
    # both OHLCV (mid candles) and execution (market orders, units-based).
    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"    # practice | live (data adapter)
    oanda_paper: bool = True
    oanda_allow_live: bool = False         # hard guardrail: live needs this true
    oanda_order_timeout_seconds: int = 20

    # Execution + data — MT5 bridge (forex/CFD gateway hosted beside a Windows
    # MetaTrader terminal, e.g. BlackBull demo on EvoX2). DGX talks HTTP; it does
    # not import MetaTrader5 directly.
    mt5_bridge_url: str = ""
    mt5_bridge_secret: str = ""
    mt5_bridge_timeout_seconds: float = 10.0
    mt5_bridge_candle_count: int = 360
    mt5_paper: bool = True
    mt5_allow_live: bool = False
    mt5_qty_is_lots: bool = False
    mt5_units_per_lot: float = 100_000.0
    mt5_deviation_points: int = 20
    forex_mt5_symbols: str = ""

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

    # Retry/backoff on transient executor.place() failures (network/timeout/5xx/
    # rate-limit). Re-submission is safe because OrderIntent carries a
    # deterministic client_order_id the broker dedupes on. 0 retries disables.
    executor_max_retries: int = 2
    executor_retry_base_delay: float = 0.5  # seconds; doubles each attempt

    # Worker live-loop cadence (seconds). Per-asset-class override via env.
    worker_tick_seconds_crypto: int = 300
    worker_tick_seconds_equity: int = 900
    worker_tick_seconds_option: int = 900
    worker_tick_seconds_forex: int = 900   # H4 bars → slow cadence is fine

    # Offline full-run mode: when true the worker installs synthetic market-data
    # providers (sim/synthetic.py) so every asset class trades without network or
    # broker creds. Forex still uses real OANDA when OANDA_API_TOKEN is set.
    synthetic_data: bool = False
    # Watchable-demo aid (NOT a strategy): emit confident directional signals so
    # the full-run pipeline actually trades + populates the dashboard. Off by
    # default; only meaningful alongside synthetic_data.
    synthetic_demo_signals: bool = False

    # Fallback sizing equity when the executor can't report a live balance
    # (paper/sim venues). Alpaca reports its real account equity instead.
    default_equity: float = 10_000.0

    # Market-data harnessing — persist fetched OHLCV into the candles hypertable
    # each tick so data is reusable for backfill/training. Only the tail is
    # written per call (the upsert gap-fills); failures never break a tick.
    persist_candles: bool = True
    persist_candles_tail: int = 20

    # Outcome labeling (ml/labeling.py) — how far forward to measure a signal's
    # realized return, and the |return| below which an outcome is "flat".
    label_horizon_bars: int = 5
    label_flat_threshold: float = 0.001    # 10 bps
    # Per-asset label threshold for train_models.py (used when no --threshold flag).
    # Equity daily bars move 0.5-2% — 0.5% threshold gives ~35% BUY/SELL balance.
    # Forex 4h bars move 0.07-0.17% median — 0.1% threshold gives ~40% BUY/SELL balance.
    label_threshold_equity: float = 0.005
    label_threshold_forex: float = 0.001
    label_threshold_crypto: float = 0.002   # 5m bars rarely move 0.5%; 0.2% gives real BUY/SELL labels (was ~97% HOLD)

    # Self-evolving model loop. Promotion is human-gated: the loop proposes a
    # champion change when a candidate beats the incumbent by min_improvement on
    # directional accuracy (with >= min_samples labeled signals); a human
    # approves via /models/promotions before it goes live.
    promotion_min_improvement: float = 0.02   # +2 pts directional accuracy
    promotion_min_samples: int = 50
    # Per-asset round-trip transaction cost in basis points (bps). Used by the
    # measure-first research harnesses to report net-of-cost PnL/Sharpe, and (when
    # wired) by the worker's net-edge gate before sizing. Conservative defaults.
    cost_bps_equity: float = 2.0    # ~1bp commission + ~1bp slippage
    cost_bps_forex: float = 1.0     # spread-dominated on majors
    cost_bps_crypto: float = 8.0    # wider spreads + taker fees
    # Worker-internal scheduler (APScheduler) — runs only on the singleton holder.
    worker_scheduler_enabled: bool = True
    label_interval_hours: int = 24            # nightly: label outcomes + evaluate champion
    train_interval_hours: int = 168           # weekly: train candidate + propose promotion
    equity_snapshot_interval_hours: int = 24  # daily: record an equity-curve point
    # Nightly signal embedding job (pgvector research foundation).
    embed_signals_enabled: bool = False
    embed_signals_interval_hours: int = 24
    embed_signals_limit: int = 1000
    # Empty → defaults to the worker's WORKER_ASSET_CLASSES at runtime.
    self_evolve_asset_classes: str = ""

    # Options risk layer (P5). Net-Greek caps are in share-equivalents
    # (contract-scaled); 0 disables a cap. IV-rank bands gate strategy choice.
    option_risk_per_trade: float = 0.02       # fraction of equity riskable per option trade
    option_max_contracts: int = 50
    option_max_net_delta: float = 0.0         # 0 = no cap
    option_max_net_gamma: float = 0.0
    option_max_net_vega: float = 0.0
    option_delta_hedge_tolerance: float = 1.0
    option_max_spread_pct: float = 0.10
    option_min_volume: int = 10
    option_min_open_interest: int = 50
    option_commission_per_contract: float = 0.65
    # Max days to hold an option before a time-stop closes it at theoretical
    # value (the options worker also settles to intrinsic at expiry).
    option_max_hold_days: int = 21
    # Price-based option exits, as a fraction of the entry premium (0 disables).
    # stop closes when the mark falls to entry*(1-sl); take-profit at entry*(1+tp);
    # trailing arms once the mark has gained trailing_activate, then closes on a
    # trailing pullback from the high-water mark.
    option_stop_loss_pct: float = 0.50      # close after losing half the premium
    option_take_profit_pct: float = 1.0     # close after the premium doubles
    option_trailing_pct: float = 0.30
    option_trailing_activate_pct: float = 0.30
    # Underlying-derived option exits (opt-in; all default off so behavior is
    # unchanged). The worker computes the signal from the underlying bars and the
    # option closes when its directional thesis breaks down.
    option_use_atr_trailing: bool = False
    option_atr_multiplier: float = 2.0
    option_use_vol_regime_exit: bool = False
    option_vol_spike_mult: float = 1.5      # recent vol / baseline vol ≥ this → exit
    option_use_trend_reversal: bool = False
    option_exit_lookback_bars: int = 20

    # Strategy combiner (razorBill multi-strategy)
    # Legacy global list — kept as a fallback when a per-asset list is empty.
    enabled_strategies: str = "momentum,mean_reversion,breakout,regime,ml"
    strategy_weights: str = "0.2,0.2,0.2,0.2,0.2"
    # Per-asset-class strategy selection. SDE strategies (gbm/ou/heston) assume
    # daily bars (dt=1/252) so they are equity-only; crypto runs 5m bars.
    crypto_strategies: str = "momentum,mean_reversion,breakout,regime,ml,macd,fourier"
    # heston removed: saturated at +1.0 every bar (zero information content)
    # breakout removed: stuck at 0.0 on daily bars for current liquid universe
    equity_strategies: str = "momentum,mean_reversion,breakout,regime,ml,macd,fourier,gbm,ou,heston,ict"
    # Forex trades H4 bars, so the SDE strategies (gbm/ou/heston) — which assume
    # daily bars (dt=1/252) — are excluded.
    # breakout removed: stuck at 0.0 on 4h forex bars
    forex_strategies: str = "momentum,mean_reversion,regime,ml,macd,fourier"
    # Empty → combiner falls back to equal weights across the selected list.
    crypto_strategy_weights: str = ""
    equity_strategy_weights: str = ""
    forex_strategy_weights: str = ""
    min_signal_confidence: float = 0.3
    min_signal_confidence_forex: float = 0.15   # forex combiner scores lower; separate floor
    # Phase C: blend strategies by their learned directional edge (fit from
    # labeled signal_history) instead of equal weights. Falls back to equal when
    # no weights file / no measurable edge yet.
    use_learned_strategy_weights: bool = True
    # Minimum number of strategies that must vote in the same direction as the
    # combined signal before it is treated as actionable. 0 = disabled.
    min_strategy_agreement: int = 3             # equity: 3 of 11 must agree (incl. heston/breakout)
    # Forex agreement filter: 2/6 strategies must vote same direction.
    # Using 2 (not 3) because momentum signals are weak (0.01-0.02) and only ML + one
    # technical strategy typically agree on strong moves. Requires vote_threshold=0.01
    # (vs equity 0.05) to count these weaker signals.
    min_strategy_agreement_forex: int = 2       # forex: 2 of 6 must agree
    # Per-asset vote threshold: minimum |strength| for a strategy to count as a vote.
    # Forex signals are weaker (0.01–0.05 range vs equity 0.05–0.2), so use a
    # lower threshold when the forex filter is re-enabled.
    strategy_agreement_vote_threshold: float = 0.03        # equity (lowered: graded strategies — momentum/macd/gbm — score small intraday; 0.05 excluded them from the agreement vote)
    strategy_agreement_vote_threshold_forex: float = 0.01  # forex (weaker signals)
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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
