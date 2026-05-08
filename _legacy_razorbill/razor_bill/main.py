#!/usr/bin/env python3
"""
RazorBill Trading Bot - Main Entry Point
"""

import asyncio
import sys
from loguru import logger

from .pipeline import main
from .config import settings


def setup_logging():
    """Setup logging configuration"""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(
        "logs/razorbill.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="1 day",
        retention="30 days"
    )


async def run_bot():
    """Run the trading bot"""
    logger.info(f"Starting RazorBill bot in {settings.env} mode")
    logger.info(f"Universe: {settings.universe}")
    logger.info(f"Equity: ${settings.equity:,.2f}")
    logger.info(f"Window: {settings.window} bars")
    
    try:
        await main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    setup_logging()
    asyncio.run(run_bot())