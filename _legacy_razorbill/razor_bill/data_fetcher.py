"""
Coinbase Data Fetcher for RazorBill Trading Bot
Fetches historical candle data from Coinbase's public API
"""

import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from loguru import logger

from .config import settings
from .db import SessionLocal, Candle


class CoinbaseDataFetcher:
    """Fetches historical candle data from Coinbase's public API"""
    
    def __init__(self):
        self.base_url = "https://api.exchange.coinbase.com"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_candles(
        self, 
        symbol: str, 
        start_time: datetime, 
        end_time: datetime,
        granularity: int = 300  # 5 minutes in seconds
    ) -> List[Dict]:
        """
        Fetch historical candles from Coinbase with automatic pagination
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USD')
            start_time: Start time for data
            end_time: End time for data
            granularity: Candle granularity in seconds (300 = 5min, 900 = 15min, 3600 = 1h)
        
        Returns:
            List of candle dictionaries
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        url = f"{self.base_url}/products/{symbol}/candles"
        all_candles = []
        
        # Calculate the maximum time range for 300 candles
        max_candles = 300
        max_time_range = max_candles * granularity
        
        current_end = end_time
        current_start = start_time
        
        try:
            logger.info(f"Fetching candles for {symbol} from {start_time} to {end_time}")
            
            while current_start < current_end:
                # Calculate the end time for this batch
                batch_end = min(
                    current_start + timedelta(seconds=max_time_range),
                    current_end
                )
                
                # Convert datetime to Unix timestamps
                start_ts = int(current_start.timestamp())
                end_ts = int(batch_end.timestamp())
                
                params = {
                    'start': start_ts,
                    'end': end_ts,
                    'granularity': granularity
                }
                
                logger.info(f"Fetching batch for {symbol}: {current_start} to {batch_end}")
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data:
                            all_candles.extend(data)
                            logger.info(f"Fetched {len(data)} candles for {symbol} batch")
                        else:
                            logger.warning(f"No data returned for {symbol} batch")
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to fetch data for {symbol}: {response.status} - {error_text}")
                        break
                
                # Move to next batch
                current_start = batch_end
                
                # Add a small delay to be respectful to the API
                await asyncio.sleep(0.1)
            
            logger.info(f"Total fetched {len(all_candles)} candles for {symbol}")
            return all_candles
        
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return all_candles
    
    def parse_candle_data(self, raw_candles: List[List], symbol: str) -> List[Candle]:
        """
        Parse raw candle data from Coinbase API into Candle objects
        
        Coinbase API returns candles as:
        [timestamp, low, high, open, close, volume]
        """
        candles = []
        
        for candle_data in raw_candles:
            if len(candle_data) != 6:
                continue
            
            timestamp, low, high, open_price, close, volume = candle_data
            
            # Convert Unix timestamp to datetime
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            
            candle = Candle(
                symbol=symbol,
                t=dt,
                o=float(open_price),
                h=float(high),
                l=float(low),
                c=float(close),
                v=float(volume),
                source='coinbase'
            )
            candles.append(candle)
        
        return candles
    
    async def fetch_and_store_candles(
        self,
        symbols: List[str],
        days_back: int = 30,
        granularity: int = 300
    ) -> Dict[str, int]:
        """
        Fetch candles for multiple symbols and store them in the database
        
        Args:
            symbols: List of trading pair symbols
            days_back: Number of days of historical data to fetch
            granularity: Candle granularity in seconds
        
        Returns:
            Dictionary mapping symbols to number of candles fetched
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days_back)
        
        results = {}
        
        for symbol in symbols:
            try:
                # Fetch raw candle data
                raw_candles = await self.fetch_candles(symbol, start_time, end_time, granularity)
                
                if not raw_candles:
                    logger.warning(f"No data received for {symbol}")
                    results[symbol] = 0
                    continue
                
                # Parse into Candle objects
                candles = self.parse_candle_data(raw_candles, symbol)
                
                # Store in database
                async with SessionLocal() as session:
                    # Check for existing data to avoid duplicates
                    existing_count = await session.execute(
                        Candle.__table__.select()
                        .where(Candle.symbol == symbol)
                        .where(Candle.t >= start_time)
                    )
                    existing_rows = existing_count.fetchall()
                    
                    if existing_rows:
                        logger.info(f"Skipping {symbol} - data already exists for this period")
                        results[symbol] = len(existing_rows)
                        continue
                    
                    # Insert new candles
                    for candle in candles:
                        session.add(candle)
                    
                    await session.commit()
                    logger.info(f"Stored {len(candles)} candles for {symbol}")
                    results[symbol] = len(candles)
            
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                results[symbol] = 0
        
        return results


async def fetch_historical_data(symbols: Optional[List[str]] = None, days_back: int = 30):
    """
    Convenience function to fetch historical data for the configured universe
    
    Args:
        symbols: List of symbols to fetch (defaults to settings.universe_list)
        days_back: Number of days of historical data to fetch
    """
    if symbols is None:
        symbols = settings.universe_list
    
    logger.info(f"Fetching historical data for {len(symbols)} symbols: {symbols}")
    
    async with CoinbaseDataFetcher() as fetcher:
        results = await fetcher.fetch_and_store_candles(symbols, days_back)
        
        total_candles = sum(results.values())
        logger.info(f"Data fetch complete. Total candles fetched: {total_candles}")
        
        for symbol, count in results.items():
            logger.info(f"  {symbol}: {count} candles")
        
        return results


async def update_latest_data(symbols: Optional[List[str]] = None):
    """
    Fetch the latest candle data to keep the database updated
    
    Args:
        symbols: List of symbols to update (defaults to settings.universe_list)
    """
    if symbols is None:
        symbols = settings.universe_list
    
    logger.info(f"Updating latest data for {len(symbols)} symbols")
    
    async with CoinbaseDataFetcher() as fetcher:
        # Fetch only the last few hours of data
        results = await fetcher.fetch_and_store_candles(symbols, days_back=1, granularity=300)
        
        total_candles = sum(results.values())
        logger.info(f"Data update complete. Total new candles: {total_candles}")
        
        return results


if __name__ == "__main__":
    # Test the data fetcher
    async def test_fetcher():
        async with CoinbaseDataFetcher() as fetcher:
            # Test with BTC-USD for the last 7 days
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=7)
            
            raw_candles = await fetcher.fetch_candles("BTC-USD", start_time, end_time)
            print(f"Fetched {len(raw_candles)} candles for BTC-USD")
            
            if raw_candles:
                candles = fetcher.parse_candle_data(raw_candles, "BTC-USD")
                print(f"Parsed {len(candles)} candle objects")
                print(f"First candle: {candles[0].t} - O:{candles[0].o} H:{candles[0].h} L:{candles[0].l} C:{candles[0].c}")
    
    asyncio.run(test_fetcher())
