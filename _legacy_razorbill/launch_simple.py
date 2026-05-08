#!/usr/bin/env python3
"""
RazorBill Simple Launcher
Starts all services with proper environment setup
"""

import subprocess
import time
import os
import signal
import sys
from pathlib import Path

def main():
    print("🎯 RazorBill Trading System Launcher")
    print("=" * 50)
    
    # Change to project directory
    os.chdir(Path(__file__).parent)
    
    # Set environment variables
    env = os.environ.copy()
    env['PYTHONPATH'] = os.getcwd()
    
    processes = []
    
    try:
        # Start trading bot
        print("🚀 Starting Trading Bot...")
        bot_cmd = [".venv/bin/python", "-m", "razor_bill.main"]
        bot_process = subprocess.Popen(bot_cmd, env=env)
        processes.append(("Trading Bot", bot_process))
        print(f"✅ Trading Bot started (PID: {bot_process.pid})")
        
        # Wait for bot to initialize
        time.sleep(3)
        
        # Start data update service
        print("🚀 Starting Data Update Service...")
        data_cmd = [".venv/bin/python", "update_data.py"]
        data_process = subprocess.Popen(data_cmd, env=env)
        processes.append(("Data Update Service", data_process))
        print(f"✅ Data Update Service started (PID: {data_process.pid})")
        
        # Wait for data service to initialize
        time.sleep(2)
        
        # Start Streamlit dashboard
        print("🌐 Starting Streamlit Dashboard...")
        print("📊 Dashboard will be available at: http://localhost:8501")
        print("⏹️  Press Ctrl+C to stop all services")
        print("=" * 50)
        
        # Start dashboard in foreground
        dashboard_cmd = [".venv/bin/python", "-m", "streamlit", "run", "dashboard.py", "--server.port", "8501"]
        subprocess.run(dashboard_cmd, env=env)
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all services...")
        
        # Stop all background processes
        for name, process in processes:
            try:
                print(f"⏹️  Stopping {name}...")
                process.terminate()
                process.wait(timeout=5)
                print(f"✅ {name} stopped")
            except Exception as e:
                print(f"⚠️  Error stopping {name}: {e}")
        
        print("👋 All services stopped. Goodbye!")

if __name__ == "__main__":
    main()
