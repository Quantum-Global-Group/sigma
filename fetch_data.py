#!/usr/bin/env python3
"""
RazorBill Data Ingestion Service
Fetches historical market data from Coinbase and populates the database
"""

import asyncio
import argparse
from datetime import datetime, timezone
from loguru import logger

from razor_bill.data_fetcher import fetch_historical_data, update_latest_data
from razor_bill.config import settings


async def main():
    parser = argparse.ArgumentParser(description='RazorBill Data Ingestion Service')
    parser.add_argument('--symbols', nargs='+', help='Symbols to fetch (default: from config)')
    parser.add_argument('--days', type=int, default=30, help='Days of historical data to fetch (default: 30)')
    parser.add_argument('--update', action='store_true', help='Update latest data instead of full historical fetch')
    parser.add_argument('--test', action='store_true', help='Test the data fetcher with a small sample')
    
    args = parser.parse_args()
    
    if args.test:
        logger.info("Testing data fetcher with BTC-USD...")
        symbols = ['BTC-USD']
        days = 1
    else:
        symbols = args.symbols or settings.universe_list
        days = args.days
    
    logger.info(f"Starting data ingestion for symbols: {symbols}")
    logger.info(f"Configuration: {days} days of data, universe: {settings.universe}")
    
    try:
        if args.update:
            logger.info("Updating latest data...")
            results = await update_latest_data(symbols)
        else:
            logger.info(f"Fetching {days} days of historical data...")
            results = await fetch_historical_data(symbols, days)
        
        # Summary
        total_candles = sum(results.values())
        successful_symbols = [s for s, count in results.items() if count > 0]
        failed_symbols = [s for s, count in results.items() if count == 0]
        
        logger.info("=" * 50)
        logger.info("DATA INGESTION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Total candles fetched: {total_candles}")
        logger.info(f"Successful symbols: {successful_symbols}")
        
        if failed_symbols:
            logger.warning(f"Failed symbols: {failed_symbols}")
        
        logger.info("Data ingestion complete!")
        
    except Exception as e:
        logger.error(f"Data ingestion failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
