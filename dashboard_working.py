#!/usr/bin/env python3
"""
RazorBill Trading Dashboard - Working Version
A comprehensive Streamlit dashboard for monitoring trades, signals, and performance
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import asyncio
from datetime import datetime, timedelta
import time
from typing import Dict, List, Optional

from razor_bill.db import SessionLocal, Candle, FeatureRow, SignalRow, PositionRow, OrderRow, ExitStateRow
from razor_bill.config import settings
from sqlalchemy import desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

# Page config
st.set_page_config(
    page_title="RazorBill Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .positive-pnl {
        color: #00C851;
        font-weight: bold;
    }
    .negative-pnl {
        color: #ff4444;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=30)
def get_positions_data():
    """Get current positions from database"""
    async def _get_positions():
        async with SessionLocal() as session:
            try:
                positions_query = await session.execute(
                    text("""
                    SELECT symbol, qty, entry_px, entry_time, unrealized_pnl
                    FROM positions 
                    WHERE qty != 0
                    ORDER BY entry_time DESC
                    """)
                )
                positions = positions_query.fetchall()
                
                return [
                    {
                        "symbol": pos[0],
                        "qty": float(pos[1]),
                        "entry_px": float(pos[2]),
                        "entry_time": str(pos[3]),
                        "unrealized_pnl": float(pos[4]) if pos[4] else 0.0
                    }
                    for pos in positions
                ]
            except Exception as e:
                st.error(f"Error getting positions: {e}")
                return []
    
    return asyncio.run(_get_positions())

@st.cache_data(ttl=10)
def get_signals_data(limit: int = 50):
    """Get recent trading signals"""
    async def _get_signals():
        async with SessionLocal() as session:
            try:
                signals_query = await session.execute(
                    text("""
                    SELECT symbol, signal, conf, t, weight_model, weight_sent, weight_regime
                    FROM signals 
                    ORDER BY t DESC 
                    LIMIT :limit
                    """),
                    {"limit": limit}
                )
                signals = signals_query.fetchall()
                
                return [
                    {
                        "symbol": sig[0],
                        "signal": float(sig[1]),
                        "conf": float(sig[2]),
                        "t": str(sig[3]),
                        "model_pred": float(sig[4]) if sig[4] else 0.0,
                        "sentiment_pred": float(sig[5]) if sig[5] else 0.0,
                        "regime_pred": float(sig[6]) if sig[6] else 0.0
                    }
                    for sig in signals
                ]
            except Exception as e:
                st.error(f"Error getting signals: {e}")
                return []
    
    return asyncio.run(_get_signals())

@st.cache_data(ttl=60)
def get_market_data(symbol: str, limit: int = 100):
    """Get market data for a symbol"""
    async def _get_market_data():
        async with SessionLocal() as session:
            try:
                candles_query = await session.execute(
                    text("""
                    SELECT t, o, h, l, c, v
                    FROM candles 
                    WHERE symbol = :symbol
                    ORDER BY t DESC 
                    LIMIT :limit
                    """),
                    {"symbol": symbol, "limit": limit}
                )
                candles = candles_query.fetchall()
                
                return [
                    {
                        "t": str(candle[0]),
                        "o": float(candle[1]),
                        "h": float(candle[2]),
                        "l": float(candle[3]),
                        "c": float(candle[4]),
                        "v": float(candle[5])
                    }
                    for candle in candles
                ]
            except Exception as e:
                st.error(f"Error getting market data: {e}")
                return []
    
    return asyncio.run(_get_market_data())

@st.cache_data(ttl=60)
def get_performance_data():
    """Get performance metrics"""
    async def _get_performance():
        async with SessionLocal() as session:
            try:
                # Get total P&L
                pnl_query = await session.execute(
                    text("""
                    SELECT SUM(unrealized_pnl) as total_pnl, COUNT(*) as total_trades
                    FROM positions 
                    WHERE unrealized_pnl IS NOT NULL
                    """)
                )
                pnl_result = pnl_query.fetchone()
                
                # Get recent performance (last 24 hours)
                recent_query = await session.execute(
                    text("""
                    SELECT COUNT(*) as recent_trades, AVG(unrealized_pnl) as avg_pnl
                    FROM positions 
                    WHERE entry_time > datetime('now', '-1 day')
                    """)
                )
                recent_result = recent_query.fetchone()
                
                return {
                    "total_pnl": float(pnl_result.total_pnl) if pnl_result.total_pnl else 0.0,
                    "total_trades": int(pnl_result.total_trades) if pnl_result.total_trades else 0,
                    "recent_trades_24h": int(recent_result.recent_trades) if recent_result.recent_trades else 0,
                    "avg_pnl": float(recent_result.avg_pnl) if recent_result.avg_pnl else 0.0,
                    "equity": 10000.0,
                    "return_pct": (float(pnl_result.total_pnl) / 10000.0 * 100) if pnl_result.total_pnl else 0.0
                }
            except Exception as e:
                st.error(f"Error getting performance data: {e}")
                return {
                    "total_pnl": 0.0,
                    "total_trades": 0,
                    "recent_trades_24h": 0,
                    "avg_pnl": 0.0,
                    "equity": 10000.0,
                    "return_pct": 0.0
                }
    
    return asyncio.run(_get_performance())

def create_price_chart(symbol: str, candles: List[Dict]):
    """Create candlestick chart"""
    if not candles:
        return None
    
    df = pd.DataFrame(candles)
    
    # Handle datetime conversion more robustly
    try:
        df['t'] = pd.to_datetime(df['t'], errors='coerce')
        df = df.dropna(subset=['t'])  # Remove rows with invalid dates
        df = df.sort_values('t')
    except Exception as e:
        st.error(f"Error parsing dates: {e}")
        return None
    
    fig = go.Figure(data=go.Candlestick(
        x=df['t'],
        open=df['o'],
        high=df['h'],
        low=df['l'],
        close=df['c'],
        name=symbol
    ))
    
    fig.update_layout(
        title=f"{symbol} Price Chart",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        height=400,
        showlegend=False
    )
    
    return fig

def main():
    # Header
    st.markdown('<h1 class="main-header">📈 RazorBill Trading Dashboard</h1>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("🎛️ Controls")
        
        # Auto-refresh toggle
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=False)
        
        # Symbol selector
        selected_symbol = st.selectbox(
            "Select Symbol",
            options=settings.universe_list,
            index=0
        )
        
        # Manual refresh button
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Main content
    if auto_refresh:
        time.sleep(30)
        st.rerun()
    
    # Get data
    try:
        positions = get_positions_data()
        signals = get_signals_data()
        market_data = get_market_data(selected_symbol)
        performance = get_performance_data()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return
    
    # Performance Overview
    st.header("📊 Performance Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total P&L",
            f"${performance['total_pnl']:,.2f}",
            delta=f"{performance['return_pct']:.2f}%"
        )
    
    with col2:
        st.metric(
            "Total Trades",
            performance['total_trades'],
            delta=performance['recent_trades_24h']
        )
    
    with col3:
        st.metric(
            "Average P&L",
            f"${performance['avg_pnl']:,.2f}",
            delta="per trade"
        )
    
    with col4:
        st.metric(
            "Equity",
            f"${performance['equity']:,.2f}",
            delta=f"{performance['return_pct']:.2f}%"
        )
    
    # Current Positions
    st.header("💼 Current Positions")
    
    if positions:
        positions_df = pd.DataFrame(positions)
        st.dataframe(positions_df, width='stretch', hide_index=True)
        
        # Positions chart
        if len(positions) > 1:
            fig_positions = px.bar(
                positions_df,
                x='symbol',
                y='unrealized_pnl',
                title="P&L by Position",
                color='unrealized_pnl',
                color_continuous_scale=['red', 'green']
            )
            st.plotly_chart(fig_positions, width='stretch')
    else:
        st.info("No current positions")
    
    # Market Data Charts
    st.header(f"📈 Market Data - {selected_symbol}")
    
    if market_data:
        price_chart = create_price_chart(selected_symbol, market_data)
        if price_chart:
            st.plotly_chart(price_chart, width='stretch')
    else:
        st.warning(f"No market data available for {selected_symbol}")
    
    # Trading Signals
    st.header("🎯 Recent Trading Signals")
    
    if signals:
        signals_df = pd.DataFrame(signals)
        st.dataframe(signals_df.head(20), width='stretch', hide_index=True)
    else:
        st.info("No recent signals")
    
    # Bot Status
    st.header("🤖 Bot Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.success("🟢 Trading Bot: Running")
    
    with col2:
        st.info(f"📊 Universe: {len(settings.universe_list)} symbols")
    
    with col3:
        st.info(f"⏰ Last Update: {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
