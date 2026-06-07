from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""
    mt5_paper: bool = True
    mt5_deviation_points: int = 20


settings = Settings()

_TIMEFRAMES = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "daily": mt5.TIMEFRAME_D1,
    "1d": mt5.TIMEFRAME_D1,
}


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "").replace("_", "")


def initialize() -> None:
    kwargs = {}
    if settings.mt5_path:
        kwargs["path"] = settings.mt5_path
    # Pass credentials into initialize() so the terminal launches AND authenticates
    # atomically. Calling initialize(path) alone makes a freshly-launched terminal
    # auto-authorize with no/stale account, which fails with -6 (Authorization failed).
    have_creds = bool(settings.mt5_login and settings.mt5_password and settings.mt5_server)
    if have_creds:
        kwargs["login"] = settings.mt5_login
        kwargs["password"] = settings.mt5_password
        kwargs["server"] = settings.mt5_server
    if not mt5.initialize(**kwargs):
        code, msg = mt5.last_error()
        raise RuntimeError(f"mt5.initialize failed: {code} {msg}")
    if have_creds:
        if not mt5.login(settings.mt5_login, password=settings.mt5_password, server=settings.mt5_server):
            code, msg = mt5.last_error()
            raise RuntimeError(f"mt5.login failed: {code} {msg}")


def account() -> dict:
    info = mt5.account_info()
    if info is None:
        code, msg = mt5.last_error()
        raise RuntimeError(f"account_info failed: {code} {msg}")
    data = info._asdict()
    return {
        "login": data.get("login"),
        "server": data.get("server"),
        "balance": float(data.get("balance") or 0),
        "equity": float(data.get("equity") or 0),
        "currency": data.get("currency"),
        "trade_allowed": bool(data.get("trade_allowed")),
    }


def health() -> dict:
    terminal = mt5.terminal_info()
    acct = mt5.account_info()
    return {
        "connected": terminal is not None and acct is not None,
        "terminal": terminal._asdict() if terminal is not None else None,
        **(account() if acct is not None else {}),
    }


def candles(symbol: str, timeframe: str, count: int) -> list[dict]:
    sym = normalize_symbol(symbol)
    tf = _TIMEFRAMES.get(timeframe.lower(), mt5.TIMEFRAME_H4)
    mt5.symbol_select(sym, True)
    rates = mt5.copy_rates_from_pos(sym, tf, 0, count)
    if rates is None:
        code, msg = mt5.last_error()
        raise RuntimeError(f"copy_rates_from_pos failed for {sym}: {code} {msg}")
    out: list[dict] = []
    for r in rates:
        out.append({
            "date": datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).isoformat(),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["tick_volume"]),
        })
    return out


def market_order(
    *,
    symbol: str,
    side: str,
    volume: float,
    client_order_id: str,
    deviation: Optional[int] = None,
) -> dict:
    sym = normalize_symbol(symbol)
    mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        code, msg = mt5.last_error()
        raise RuntimeError(f"symbol_info_tick failed for {sym}: {code} {msg}")
    is_buy = side.lower() == "buy"
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    price = float(tick.ask if is_buy else tick.bid)
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "deviation": int(deviation if deviation is not None else settings.mt5_deviation_points),
        "magic": 260603,
        # MT5 rejects comments with punctuation (e.g. ':') AND comments that are
        # too long (this build errors -2 'Invalid comment' at >=~30 chars — a
        # 30-char exit0 client_order_id failed; <=28 verified OK via order_check).
        # Sanitize to alnum/underscore and cap well under the limit.
        "comment": "".join(c if c.isalnum() else "_" for c in client_order_id)[:24],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result is None:
        code, msg = mt5.last_error()
        raise RuntimeError(f"order_send failed for {sym}: {code} {msg}")
    data = result._asdict()
    if data.get("retcode") != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"order_send rejected: {data}")
    return {
        "ticket": str(data.get("order") or data.get("deal")),
        "status": "filled",
        "symbol": sym,
        "side": side.lower(),
        "volume": float(volume),
        "filled_qty": float(volume),
        "price": float(data.get("price") or price),
        "commission": 0.0,
        "raw": data,
    }
