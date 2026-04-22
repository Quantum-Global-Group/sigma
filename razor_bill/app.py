"""
RazorBill Trading Bot - FastAPI Web Interface
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from typing import Dict, Any

from .config import settings
from .pipeline import one_cycle
from .db import SessionLocal, PositionRow, OrderRow, SignalRow

app = FastAPI(title="RazorBill Trading Bot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "RazorBill Trading Bot API", "version": "0.1.0"}


@app.get("/status")
async def get_status():
    """Get bot status"""
    return {
        "status": "running",
        "executor_mode": settings.executor_mode,
        "universe": settings.universe_list,
        "equity": settings.equity,
        "window": settings.window,
        "strategy_weights": {
            "model": settings.strategy.weight_model,
            "sentiment": settings.strategy.weight_sent,
            "regime": settings.strategy.weight_regime,
        }
    }


@app.get("/positions")
async def get_positions():
    """Get current positions"""
    async with SessionLocal() as session:
        res = await session.execute(PositionRow.__table__.select())  # type: ignore[attr-defined]
        rows = res.fetchall()
        positions = []
        for r in rows:
            positions.append({
                "symbol": r._mapping["symbol"],
                "qty": r._mapping["qty"],
                "entry_px": r._mapping["entry_px"],
                "entry_time": r._mapping["entry_time"],
                "current_px": r._mapping["current_px"],
                "unrealized_pnl": r._mapping["unrealized_pnl"],
            })
        return {"positions": positions}


@app.get("/orders")
async def get_orders(limit: int = 100):
    """Get recent orders"""
    async with SessionLocal() as session:
        res = await session.execute(
            OrderRow.__table__.select().order_by(OrderRow.t.desc()).limit(limit)  # type: ignore[attr-defined]
        )
        rows = res.fetchall()
        orders = []
        for r in rows:
            orders.append({
                "t": r._mapping["t"],
                "symbol": r._mapping["symbol"],
                "side": r._mapping["side"],
                "qty": r._mapping["qty"],
                "px": r._mapping["px"],
                "fee": r._mapping["fee"],
                "slip": r._mapping["slip"],
            })
        return {"orders": orders}


@app.post("/run_cycle")
async def run_cycle():
    """Manually trigger a trading cycle"""
    try:
        await one_cycle()
        return {"status": "success", "message": "Trading cycle completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals")
async def get_signals(limit: int = 50):
    """Get recent signals"""
    async with SessionLocal() as session:
        res = await session.execute(
            SignalRow.__table__.select().order_by(SignalRow.t.desc()).limit(limit)  # type: ignore[attr-defined]
        )
        rows = res.fetchall()
        signals = []
        for r in rows:
            signals.append({
                "t": r._mapping["t"],
                "symbol": r._mapping["symbol"],
                "signal": r._mapping["signal"],
                "conf": r._mapping["conf"],
                "risk_var_95": r._mapping["risk_var_95"],
                "atr": r._mapping["atr"],
            })
        return {"signals": signals}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)