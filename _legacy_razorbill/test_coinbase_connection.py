#!/usr/bin/env python3
"""
Quick test script to verify Coinbase Advanced Trade API connection
"""
import sys
from razor_bill.config import settings
from loguru import logger

def test_coinbase_connection():
    """Test Coinbase API connection"""
    logger.info("Testing Coinbase Advanced Trade API connection...")
    logger.info(f"Executor mode: {settings.executor_mode}")
    logger.info(f"Sandbox mode: {settings.coinbase_sandbox}")
    
    # Check credentials
    if settings.coinbase_api_key_name and settings.coinbase_private_key:
        logger.info("✅ Found API key name and private key")
        logger.info(f"API Key Name: {settings.coinbase_api_key_name[:50]}...")
    elif settings.coinbase_api_key:
        logger.info("⚠️  Using legacy API key format")
    else:
        logger.error("❌ No Coinbase credentials found!")
        logger.error("Please set COINBASE_API_KEY_NAME and COINBASE_PRIVATE_KEY in .env")
        return False
    
    # Try to initialize the executor
    try:
        if settings.executor_mode == "coinbase":
            from razor_bill.coinbase_executor import CoinbaseExecutor
            executor = CoinbaseExecutor()
            logger.info("✅ Coinbase executor initialized successfully!")
            logger.info(f"   Sandbox mode: {settings.coinbase_sandbox}")
            return True
        else:
            logger.warning(f"Executor mode is '{settings.executor_mode}', not 'coinbase'")
            logger.info("Set EXECUTOR_MODE=coinbase in .env to test Coinbase connection")
            return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize Coinbase executor: {e}")
        logger.error("Please check your credentials and .env configuration")
        return False

if __name__ == "__main__":
    success = test_coinbase_connection()
    sys.exit(0 if success else 1)

