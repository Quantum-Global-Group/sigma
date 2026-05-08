#!/usr/bin/env python3
"""
RazorBill Trading Dashboard
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
import requests
import json

from razor_bill.db import SessionLocal, Candle, Feature, Signal, Position, Order, ExitState
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
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
    }
    .positive-pnl {
        color: #00C851;
        font-weight: bold;
    }
    .negative-pnl {
        color: #ff4444;
        font-weight: bold;
    }
    .signal-buy {
        background-color: #d4edda;
        color: #155724;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
    }
    .signal-sell {
        background-color: #f8d7da;
        color: #721c24;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=30)  # Cache for 30 seconds
async def get_positions_data():
    """Get current positions from database"""
    async with SessionLocal() as session:
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
                "symbol": pos.symbol,
                "qty": float(pos.qty),
                "entry_px": float(pos.entry_px),
                "entry_time": pos.entry_time.isoformat() if pos.entry_time else None,
                "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0.0
            }
            for pos in positions
        ]

@st.cache_data(ttl=10)  # Cache for 10 seconds
async def get_signals_data(limit: int = 50):
    """Get recent trading signals"""
    async with SessionLocal() as session:
        signals_query = await session.execute(
            text("""
            SELECT symbol, signal, conf, t, model_pred, sentiment_pred, regime_pred
            FROM signals 
            ORDER BY t DESC 
            LIMIT :limit
            """),
            {"limit": limit}
        )
        signals = signals_query.fetchall()
        
        return [
            {
                "symbol": sig.symbol,
                "signal": float(sig.signal),
                "conf": float(sig.conf),
                "t": sig.t.isoformat() if sig.t else None,
                "model_pred": float(sig.model_pred) if sig.model_pred else 0.0,
                "sentiment_pred": float(sig.sentiment_pred) if sig.sentiment_pred else 0.0,
                "regime_pred": float(sig.regime_pred) if sig.regime_pred else 0.0
            }
            for sig in signals
        ]

@st.cache_data(ttl=60)  # Cache for 1 minute
async def get_market_data(symbol: str, limit: int = 100):
    """Get market data for a symbol"""
    async with SessionLocal() as session:
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
                "t": candle.t.isoformat() if candle.t else None,
                "o": float(candle.o),
                "h": float(candle.h),
                "l": float(candle.l),
                "c": float(candle.c),
                "v": float(candle.v)
            }
            for candle in candles
        ]

@st.cache_data(ttl=60)
async def get_performance_data():
    """Get performance metrics"""
    async with SessionLocal() as session:
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

def create_price_chart(symbol: str, candles: List[Dict]):
    """Create candlestick chart"""
    if not candles:
        return None
    
    df = pd.DataFrame(candles)
    df['t'] = pd.to_datetime(df['t'])
    df = df.sort_values('t')
    
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

def create_volume_chart(symbol: str, candles: List[Dict]):
    """Create volume chart"""
    if not candles:
        return None
    
    df = pd.DataFrame(candles)
    df['t'] = pd.to_datetime(df['t'])
    df = df.sort_values('t')
    
    fig = go.Figure(data=go.Bar(
        x=df['t'],
        y=df['v'],
        name="Volume"
    ))
    
    fig.update_layout(
        title=f"{symbol} Volume",
        xaxis_title="Time",
        yaxis_title="Volume",
        height=300,
        showlegend=False
    )
    
    return fig

def create_signal_chart(signals: List[Dict]):
    """Create signal strength chart"""
    if not signals:
        return None
    
    df = pd.DataFrame(signals)
    df['t'] = pd.to_datetime(df['t'])
    df = df.sort_values('t')
    
    fig = go.Figure()
    
    for symbol in df['symbol'].unique():
        symbol_data = df[df['symbol'] == symbol]
        fig.add_trace(go.Scatter(
            x=symbol_data['t'],
            y=symbol_data['signal'],
            mode='lines+markers',
            name=symbol,
            line=dict(width=2)
        ))
    
    fig.update_layout(
        title="Trading Signals Over Time",
        xaxis_title="Time",
        yaxis_title="Signal Strength",
        height=400,
        hovermode='x unified'
    )
    
    return fig

def main():
    # Header
    st.markdown('<h1 class="main-header">📈 RazorBill Trading Dashboard</h1>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("🎛️ Controls")
        
        # Auto-refresh toggle
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
        
        # Symbol selector
        selected_symbol = st.selectbox(
            "Select Symbol",
            options=settings.universe_list,
            index=0
        )
        
        # Time range selector
        time_range = st.selectbox(
            "Time Range",
            options=["Last 24h", "Last 3 days", "Last week", "Last month"],
            index=1
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
    positions = asyncio.run(get_positions_data())
    signals = asyncio.run(get_signals_data())
    market_data = asyncio.run(get_market_data(selected_symbol))
    performance = asyncio.run(get_performance_data())
    
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
        
        # Format P&L with colors
        def format_pnl(pnl):
            if pnl >= 0:
                return f'<span class="positive-pnl">+${pnl:.2f}</span>'
            else:
                return f'<span class="negative-pnl">-${abs(pnl):.2f}</span>'
        
        positions_df['pnl_formatted'] = positions_df['unrealized_pnl'].apply(format_pnl)
        
        st.dataframe(
            positions_df[['symbol', 'qty', 'entry_px', 'entry_time', 'pnl_formatted']],
            use_container_width=True,
            hide_index=True
        )
        
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
            st.plotly_chart(fig_positions, use_container_width=True)
    else:
        st.info("No current positions")
    
    # Market Data Charts
    st.header(f"📈 Market Data - {selected_symbol}")
    
    if market_data:
        col1, col2 = st.columns(2)
        
        with col1:
            price_chart = create_price_chart(selected_symbol, market_data)
            if price_chart:
                st.plotly_chart(price_chart, use_container_width=True)
        
        with col2:
            volume_chart = create_volume_chart(selected_symbol, market_data)
            if volume_chart:
                st.plotly_chart(volume_chart, use_container_width=True)
    else:
        st.warning(f"No market data available for {selected_symbol}")
    
    # Trading Signals
    st.header("🎯 Recent Trading Signals")
    
    if signals:
        signals_df = pd.DataFrame(signals)
        
        # Format signals
        def format_signal(signal):
            if signal > 0:
                return f'<span class="signal-buy">BUY ({signal:.3f})</span>'
            else:
                return f'<span class="signal-sell">SELL ({signal:.3f})</span>'
        
        signals_df['signal_formatted'] = signals_df['signal'].apply(format_signal)
        
        # Show recent signals table
        st.dataframe(
            signals_df[['symbol', 'signal_formatted', 'conf', 't']].head(20),
            use_container_width=True,
            hide_index=True
        )
        
        # Signal chart
        signal_chart = create_signal_chart(signals)
        if signal_chart:
            st.plotly_chart(signal_chart, use_container_width=True)
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