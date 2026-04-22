#!/usr/bin/env python3
"""
Simple script to create sample candle data for testing
"""

import asyncio
import numpy as np
from datetime import datetime, timezone, timedelta
from razor_bill.db import SessionLocal, Candle

async def create_sample_data():
    print('Creating sample candle data...')
    
    symbols = ['BTC-USD', 'ETH-USD', 'LTC-USD']
    base_prices = [45000, 3000, 70]
    
    for i, symbol in enumerate(symbols):
        base_price = base_prices[i]
        print(f'Creating data for {symbol} starting at ${base_price}')
        
        async with SessionLocal() as session:
            # Generate 100 bars of sample data
            for j in range(100):
                # Simple random walk with some trend
                trend = 0.0001 * np.sin(j / 20)  # Small cyclical trend
                noise = np.random.normal(0, 0.02)  # 2% volatility
                change = trend + noise
                
                if j == 0:
                    price = base_price
                else:
                    price = base_price * (1 + change)
                    base_price = price
                
                # Generate OHLC from price
                volatility = abs(np.random.normal(0, 0.01))
                high = price * (1 + volatility)
                low = price * (1 - volatility)
                open_price = price + np.random.normal(0, price * 0.005)
                close_price = price
                volume = np.random.uniform(1000, 10000)
                
                # Create timestamp (5-minute intervals)
                timestamp = datetime.now(timezone.utc) - timedelta(minutes=5 * (100 - j))
                
                candle = Candle(
                    symbol=symbol,
                    t=timestamp,
                    o=open_price,
                    h=high,
                    l=low,
                    c=close_price,
                    v=volume,
                    source='sample'
                )
                session.add(candle)
            
            await session.commit()
            print(f'Committed data for {symbol}')
    
    print('Sample data created successfully!')

if __name__ == "__main__":
    asyncio.run(create_sample_data())
