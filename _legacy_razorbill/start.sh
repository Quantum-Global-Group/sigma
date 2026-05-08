#!/bin/bash
# RazorBill Working Launcher
# Simple script to start the trading system

echo "🎯 RazorBill Trading System"
echo "=========================="

# Change to project directory
cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

echo "🚀 Starting services..."

# Start trading bot in background
echo "🤖 Starting Trading Bot..."
python -m razor_bill.main &
BOT_PID=$!
echo "✅ Trading Bot started (PID: $BOT_PID)"

# Wait a moment
sleep 3

# Start data update service in background
echo "📊 Starting Data Update Service..."
python update_data.py &
DATA_PID=$!
echo "✅ Data Update Service started (PID: $DATA_PID)"

# Wait a moment
sleep 2

# Start dashboard
echo "🌐 Starting Dashboard..."
echo "📊 Dashboard will be available at: http://localhost:8503"
echo "⏹️  Press Ctrl+C to stop all services"
echo "=========================="

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down services..."
    
    echo "⏹️  Stopping Trading Bot (PID: $BOT_PID)..."
    kill $BOT_PID 2>/dev/null
    
    echo "⏹️  Stopping Data Update Service (PID: $DATA_PID)..."
    kill $DATA_PID 2>/dev/null
    
    echo "✅ All services stopped"
    exit 0
}

# Set trap to cleanup on Ctrl+C
trap cleanup SIGINT

# Start dashboard in foreground
streamlit run dashboard_working.py --server.port 8503
