# 📈 RazorBill Trading Dashboard

A comprehensive Streamlit dashboard for monitoring your RazorBill trading bot's performance, positions, signals, and market data.

## 🚀 Quick Start

### Option 1: Launch Everything (Recommended)
```bash
python launch.py
```
This will start:
- 🤖 Trading Bot (continuous analysis)
- 📊 Data Update Service (hourly updates)
- 🌐 Streamlit Dashboard (http://localhost:8501)

### Option 2: Manual Launch
```bash
# Terminal 1: Start trading bot
source .venv/bin/activate && python -m razor_bill.main &

# Terminal 2: Start data updates
source .venv/bin/activate && python update_data.py &

# Terminal 3: Start dashboard
source .venv/bin/activate && streamlit run dashboard.py --server.port 8501
```

## 📊 Dashboard Features

### Performance Overview
- **Total P&L**: Real-time profit/loss tracking
- **Total Trades**: Number of completed trades
- **Average P&L**: Per-trade performance
- **Equity**: Current portfolio value

### Current Positions
- Live position tracking with P&L
- Visual P&L breakdown by symbol
- Entry prices and quantities

### Market Data Charts
- **Candlestick Charts**: Price action visualization
- **Volume Charts**: Trading volume analysis
- **Symbol Selection**: Switch between BTC-USD, ETH-USD, etc.

### Trading Signals
- **Signal Strength**: Real-time signal visualization
- **Confidence Levels**: Model confidence scores
- **Signal History**: Recent signal trends

### Bot Status
- **System Health**: Bot running status
- **Universe**: Monitored symbols
- **Last Update**: Data freshness

## 🎛️ Controls

### Sidebar Controls
- **Auto-refresh**: Toggle 30-second auto-refresh
- **Symbol Selector**: Choose which asset to view
- **Time Range**: Select data timeframe
- **Manual Refresh**: Force data update

### Real-time Updates
- Dashboard automatically refreshes every 30 seconds
- Data is cached for performance
- Manual refresh clears cache

## 📱 Access

Once running, open your browser to:
```
http://localhost:8501
```

## 🔧 Configuration

The dashboard reads from your existing RazorBill configuration:
- **Universe**: Symbols from `settings.universe_list`
- **Database**: SQLite database with trading data
- **Strategy**: Model weights and parameters

## 🛠️ Troubleshooting

### Dashboard Not Loading
1. Check if trading bot is running: `ps aux | grep razor_bill`
2. Verify database has data: `python fetch_data.py --test`
3. Check port availability: `netstat -tlnp | grep 8501`

### No Data Showing
1. Ensure data fetching worked: `python fetch_data.py --days 3`
2. Check database tables: `sqlite3 razor_bill.db ".tables"`
3. Verify bot has run at least one cycle

### Performance Issues
1. Reduce auto-refresh frequency
2. Limit data range in sidebar
3. Clear browser cache

## 📈 Monitoring Tips

1. **Watch P&L Trends**: Look for consistent positive returns
2. **Signal Quality**: High confidence signals should correlate with good trades
3. **Position Sizing**: Monitor if positions are appropriately sized
4. **Market Conditions**: Adjust expectations based on market volatility

## 🔄 Integration

The dashboard integrates seamlessly with:
- **Trading Bot**: Real-time position and signal data
- **Data Service**: Fresh market data updates
- **Database**: All historical trading records
- **Configuration**: Bot settings and parameters

---

**Happy Trading! 📈🚀**
