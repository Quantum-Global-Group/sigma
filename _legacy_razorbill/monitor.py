#!/usr/bin/env python3
"""
RazorBill Monitoring Script
Monitors the bot's performance and provides status updates
"""

import asyncio
import requests
import time
from datetime import datetime

def check_bot_status():
    """Check if the bot is running and get status"""
    try:
        response = requests.get("http://localhost:8000/status", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def get_positions():
    """Get current positions"""
    try:
        response = requests.get("http://localhost:8000/positions", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def get_recent_signals():
    """Get recent trading signals"""
    try:
        response = requests.get("http://localhost:8000/signals?limit=10", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except requests.exceptions.RequestException:
        return None

def monitor_bot():
    """Main monitoring loop"""
    print("🚀 RazorBill Trading Bot Monitor")
    print("=" * 50)
    
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check bot status
        status = check_bot_status()
        if status:
            print(f"\n[{timestamp}] ✅ Bot Status: {status['status']}")
            print(f"💰 Equity: ${status['equity']:,.2f}")
            print(f"📊 Universe: {', '.join(status['universe'])}")
            print(f"🎯 Strategy Weights: Model={status['strategy_weights']['model']}, Sentiment={status['strategy_weights']['sentiment']}, Regime={status['strategy_weights']['regime']}")
            
            # Get positions
            positions = get_positions()
            if positions and positions.get('positions'):
                print(f"\n📈 Current Positions ({len(positions['positions'])}):")
                for pos in positions['positions']:
                    pnl = pos.get('unrealized_pnl', 0)
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    print(f"  {pos['symbol']}: {pos['qty']:.4f} @ ${pos['entry_px']:.2f} (P&L: {pnl_str})")
            else:
                print("\n📈 No current positions")
            
            # Get recent signals
            signals = get_recent_signals()
            if signals and signals.get('signals'):
                print(f"\n🎯 Recent Signals ({len(signals['signals'])}):")
                for signal in signals['signals'][:3]:  # Show last 3
                    signal_time = signal['t'].split('T')[1][:8] if 'T' in signal['t'] else signal['t'][:8]
                    print(f"  {signal_time} {signal['symbol']}: {signal['signal']:.3f} (conf: {signal['conf']:.2f})")
        else:
            print(f"\n[{timestamp}] ❌ Bot not responding")
        
        print("\n" + "=" * 50)
        time.sleep(30)  # Check every 30 seconds

if __name__ == "__main__":
    try:
        monitor_bot()
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")
