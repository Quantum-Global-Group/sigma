from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

import mt5_client


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mt5_bridge_secret: str = ""
    mt5_paper: bool = True


settings = Settings()
app = FastAPI(title="SIGMA MT5 Bridge", version="0.1.0")


class OrderRequest(BaseModel):
    symbol: str
    side: str
    volume: float = Field(gt=0)
    client_order_id: str
    deviation: Optional[int] = None
    paper: bool = True


def require_secret(x_mt5_bridge_secret: str = Header(default="")) -> None:
    if settings.mt5_bridge_secret and x_mt5_bridge_secret != settings.mt5_bridge_secret:
        raise HTTPException(status_code=401, detail="invalid bridge secret")


@app.on_event("startup")
def startup() -> None:
    mt5_client.initialize()


@app.get("/health")
def health(_: None = Depends(require_secret)):
    return mt5_client.health()


@app.get("/account")
def account(_: None = Depends(require_secret)):
    return mt5_client.account()


@app.get("/candles")
def candles(symbol: str, timeframe: str = "4h", count: int = 360, _: None = Depends(require_secret)):
    return {
        "symbol": mt5_client.normalize_symbol(symbol),
        "timeframe": timeframe,
        "candles": mt5_client.candles(symbol, timeframe, count),
    }


@app.post("/orders")
def orders(req: OrderRequest, _: None = Depends(require_secret)):
    if not settings.mt5_paper and req.paper:
        raise HTTPException(status_code=400, detail="bridge is live but request is marked paper")
    if settings.mt5_paper is False and req.paper is False:
        # Live is allowed only when the bridge process itself was deliberately
        # started in live mode; the DGX executor has a separate allow-live flag.
        pass
    return mt5_client.market_order(
        symbol=req.symbol,
        side=req.side,
        volume=req.volume,
        client_order_id=req.client_order_id,
        deviation=req.deviation,
    )
