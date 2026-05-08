from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
