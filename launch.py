#!/usr/bin/env python3
"""
RazorBill Complete Trading System Launcher
Starts all services: trading bot, data updates, and dashboard
"""

import subprocess
import time
import os
import signal
import sys
from pathlib import Path

def start_service(name, command, background=True):
    """Start a service and return the process"""
    print(f"🚀 Starting {name}...")
    try:
        if background:
            process = subprocess.Popen(command, shell=True, preexec_fn=os.setsid)
            print(f"✅ {name} started (PID: {process.pid})")
            return process
        else:
            subprocess.run(command, shell=True)
    except Exception as e:
        print(f"❌ Failed to start {name}: {e}")
        return None

def main():
    print("🎯 RazorBill Trading System Launcher")
    print("=" * 50)
    
    # Change to project directory
    os.chdir(Path(__file__).parent)
    
    processes = []
    
    try:
        # Get the virtual environment Python path
        venv_python = os.path.join(os.getcwd(), ".venv", "bin", "python")
        
        # Start trading bot
        bot_process = start_service("Trading Bot", f"{venv_python} -m razor_bill.main")
        if bot_process:
            processes.append(("Trading Bot", bot_process))
        
        # Wait a moment for bot to initialize
        time.sleep(2)
        
        # Start data update service
        data_process = start_service("Data Update Service", f"{venv_python} update_data.py")
        if data_process:
            processes.append(("Data Update Service", data_process))
        
        # Wait a moment for data service to initialize
        time.sleep(2)
        
        # Start Streamlit dashboard
        print("🌐 Starting Streamlit Dashboard...")
        print("📊 Dashboard will be available at: http://localhost:8501")
        print("⏹️  Press Ctrl+C to stop all services")
        print("=" * 50)
        
        # Start dashboard in foreground (this will block)
        dashboard_process = start_service("Streamlit Dashboard", f"{venv_python} -m streamlit run dashboard.py --server.port 8501", background=False)
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all services...")
        
        # Stop all background processes
        for name, process in processes:
            try:
                print(f"⏹️  Stopping {name}...")
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                print(f"✅ {name} stopped")
            except Exception as e:
                print(f"⚠️  Error stopping {name}: {e}")
        
        print("👋 All services stopped. Goodbye!")

if __name__ == "__main__":
    main()
