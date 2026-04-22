#!/usr/bin/env python3
"""
RazorBill Data Update Service
Keeps market data fresh by updating every hour
"""

import asyncio
import time
from datetime import datetime
from loguru import logger

from razor_bill.data_fetcher import update_latest_data
from razor_bill.config import settings

async def update_data():
    """Update market data"""
    try:
        logger.info("🔄 Updating market data...")
        results = await update_latest_data()
        
        total_candles = sum(results.values())
        if total_candles > 0:
            logger.info(f"✅ Updated {total_candles} new candles")
        else:
            logger.info("ℹ️ No new data available")
        
        return True
    except Exception as e:
        logger.error(f"❌ Data update failed: {e}")
        return False

async def data_update_service():
    """Continuous data update service"""
    logger.info("🚀 Starting RazorBill Data Update Service")
    logger.info(f"📊 Monitoring symbols: {settings.universe_list}")
    logger.info("⏰ Update frequency: Every hour")
    
    while True:
        try:
            # Update data
            success = await update_data()
            
            if success:
                logger.info("✅ Data update cycle completed")
            else:
                logger.warning("⚠️ Data update cycle failed, will retry next hour")
            
            # Wait 1 hour before next update
            logger.info("😴 Sleeping for 1 hour...")
            await asyncio.sleep(3600)  # 1 hour
            
        except KeyboardInterrupt:
            logger.info("👋 Data update service stopped by user")
            break
        except Exception as e:
            logger.error(f"💥 Unexpected error in data update service: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes before retrying

if __name__ == "__main__":
    asyncio.run(data_update_service())
