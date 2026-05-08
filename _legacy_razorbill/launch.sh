#!/bin/bash
# RazorBill Trading System Launcher
# Simple bash script to start all services

echo "🎯 RazorBill Trading System Launcher"
echo "=================================================="

# Change to project directory
cd "$(dirname "$0")"

# Activate virtual environment
source .venv/bin/activate

# Function to start a service in background
start_service() {
    local name="$1"
    local command="$2"
    echo "🚀 Starting $name..."
    $command &
    local pid=$!
    echo "✅ $name started (PID: $pid)"
    echo $pid
}

# Start trading bot
bot_pid=$(start_service "Trading Bot" "python -m razor_bill.main")

# Wait for bot to initialize
sleep 3

# Start data update service
data_pid=$(start_service "Data Update Service" "python update_data.py")

# Wait for data service to initialize
sleep 2

# Start Streamlit dashboard
echo "🌐 Starting Streamlit Dashboard..."
echo "📊 Dashboard will be available at: http://localhost:8501"
echo "⏹️  Press Ctrl+C to stop all services"
echo "=================================================="

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down all services..."
    
    echo "⏹️  Stopping Trading Bot (PID: $bot_pid)..."
    kill $bot_pid 2>/dev/null
    
    echo "⏹️  Stopping Data Update Service (PID: $data_pid)..."
    kill $data_pid 2>/dev/null
    
    echo "✅ All services stopped"
    echo "👋 Goodbye!"
    exit 0
}

# Set trap to cleanup on Ctrl+C
trap cleanup SIGINT

# Start dashboard in foreground
echo "🚀 Starting Streamlit Dashboard..."
streamlit run dashboard.py --server.port 8501
