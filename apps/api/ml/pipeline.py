from __future__ import annotations

from ml.features import build_features
from ml.inference import SignalResult, predict
from ml.langfuse_tracing import child_span, trace_pipeline
from markets import get_market_adapter


def run_signal_pipeline(
    ticker: str,
    timeframe: str = "daily",
    *,
    asset_class: str = "equity",
) -> SignalResult:
    """Fetch market data, build features, run inference. Returns a SignalResult.

    The market data source is chosen by `asset_class` via the MarketAdapter
    registry (yfinance for equities, Coinbase for crypto)."""
    adapter = get_market_adapter(asset_class)
    with trace_pipeline(ticker, timeframe) as root:
        with child_span("fetch_ohlcv", ticker=ticker, timeframe=timeframe, asset_class=asset_class) as fetch:
            df = adapter.fetch_ohlcv(ticker, timeframe)
            fetch.update(output={"rows": len(df)})

        with child_span("build_features") as feat:
            features = build_features(df)
            feat.update(
                output={
                    "rows": len(features),
                    "columns": len(features.columns),
                }
            )

        with child_span("predict", asset_class=asset_class) as pred:
            result = predict(features, asset_class=asset_class)
            pred.update(
                output={
                    "signal": result.signal,
                    "confidence": result.confidence,
                    "predicted_return": result.predicted_return,
                    "model_version": result.model_version,
                }
            )

        root.update(
            output={
                "signal": result.signal,
                "confidence": result.confidence,
                "predicted_return": result.predicted_return,
                "model_version": result.model_version,
            }
        )
        return result
