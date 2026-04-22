#!/bin/bash
# RazorBill Trading Bot Setup Script

echo "🚀 Setting up RazorBill Trading Bot..."

# Check if Python 3.8+ is available
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
major_version=$(echo $python_version | cut -d. -f1)
minor_version=$(echo $python_version | cut -d. -f2)

if [ "$major_version" -lt 3 ] || ([ "$major_version" -eq 3 ] && [ "$minor_version" -lt 8 ]); then
    echo "❌ Python 3.8+ is required. Current version: $python_version"
    exit 1
fi

echo "✅ Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r razor_bill/requirements.txt

# Create logs directory
echo "📁 Creating logs directory..."
mkdir -p logs

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "⚙️ Creating .env file..."
    cat > .env << EOF
# RazorBill Configuration
ENV=dev
EQUITY=10000.0
UNIVERSE=BTC-USD,LTC-USD,ETH-USD,FIL-USD,HNT-USD
DB_URL=sqlite+aiosqlite:///./bot.db

# Coinbase Advanced Trade API credentials (for real trading)
# Required when EXECUTOR_MODE=coinbase
# COINBASE_API_KEY=your_key_here
# COINBASE_API_SECRET=your_secret_here
# COINBASE_API_PASSPHRASE=your_passphrase_here

# Executor mode: "paper" for simulated trading, "coinbase" for real trading
EXECUTOR_MODE=paper

# Coinbase sandbox mode (for testing with fake funds)
# COINBASE_SANDBOX=false

# Coinbase order timeout in seconds
# COINBASE_ORDER_TIMEOUT_SECONDS=30

# Sentiment analysis (optional)
SENTIMENT_PROVIDER=none
# LX_MODEL_ID=mistral:7b-instruct
# LX_MODEL_URL=http://127.0.0.1:11434
EOF
    echo "✅ Created .env file with default settings"
fi

echo ""
echo "🎉 Setup complete! You can now run the bot:"
echo ""
echo "  # Run the trading bot:"
echo "  python -m razor_bill.main"
echo ""
echo "  # Run the web API:"
echo "  python -m razor_bill.app"
echo ""
echo "  # Or run the web API with uvicorn directly:"
echo "  uvicorn razor_bill.app:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "📖 Check the README.md for more information"
