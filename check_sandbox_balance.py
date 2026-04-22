#!/usr/bin/env python3
"""
Check Coinbase sandbox account balance
"""
import sys
from razor_bill.config import settings
from razor_bill.coinbase_executor import CoinbaseExecutor
from loguru import logger

def check_balance():
    """Check Coinbase sandbox account balance"""
    logger.info("Checking Coinbase sandbox account balance...")
    logger.info(f"Sandbox mode: {settings.coinbase_sandbox}")
    
    try:
        # Initialize the executor (which creates the Coinbase client)
        executor = CoinbaseExecutor()
        
        # Get accounts
        logger.info("Fetching account information...")
        accounts = executor.client.get_accounts()
        
        # Handle different response structures
        accounts_list = []
        if hasattr(accounts, 'accounts'):
            accounts_list = accounts.accounts
        elif hasattr(accounts, '__iter__') and not isinstance(accounts, str):
            accounts_list = list(accounts)
        elif isinstance(accounts, dict) and 'accounts' in accounts:
            accounts_list = accounts['accounts']
        elif isinstance(accounts, list):
            accounts_list = accounts
        
        if not accounts_list:
            logger.warning("No accounts found or unexpected response format")
            logger.info(f"Response type: {type(accounts)}")
            logger.info(f"Response: {accounts}")
            return
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Coinbase Sandbox Account Balances")
        logger.info(f"{'='*60}\n")
        
        total_usd_value = 0.0
        
        for account in accounts_list:
            # Extract account info (handle different structures)
            account_name = None
            currency = None
            balance = None
            available = None
            
            if hasattr(account, 'name'):
                account_name = account.name
            elif isinstance(account, dict):
                account_name = account.get('name')
            
            if hasattr(account, 'currency'):
                currency = account.currency
            elif isinstance(account, dict):
                currency = account.get('currency')
            
            if hasattr(account, 'available_balance'):
                available = account.available_balance
            elif isinstance(account, dict):
                available = account.get('available_balance', account.get('available'))
            
            if hasattr(account, 'balance'):
                balance = account.balance
            elif isinstance(account, dict):
                balance = account.get('balance')
            
            # Convert to dict if needed for easier access
            if not isinstance(account, dict) and hasattr(account, '__dict__'):
                account_dict = account.__dict__
            elif hasattr(account, 'to_dict'):
                account_dict = account.to_dict()
            else:
                account_dict = account if isinstance(account, dict) else {}
            
            # Try to get USD value if available
            usd_value = None
            if 'usd_value' in account_dict:
                usd_value = float(account_dict['usd_value'])
            elif hasattr(account, 'usd_value'):
                usd_value = float(account.usd_value)
            
            # Display account info
            if currency and (balance or available):
                # Parse available balance (might be dict or string)
                available_amount = None
                if isinstance(available, dict):
                    available_amount = float(available.get('value', 0))
                elif available:
                    try:
                        available_amount = float(available)
                    except (ValueError, TypeError):
                        available_amount = None
                
                balance_str = str(balance) if balance else "N/A"
                available_str = f"{available_amount} {currency}" if available_amount is not None else str(available) if available else "N/A"
                
                logger.info(f"Account: {account_name or 'N/A'}")
                logger.info(f"  Currency: {currency}")
                logger.info(f"  Balance: {balance_str}")
                logger.info(f"  Available: {available_str}")
                
                # Estimate USD value (rough conversion for display)
                if available_amount and available_amount > 0:
                    if currency == 'USD':
                        total_usd_value += available_amount
                    elif currency == 'USDC':
                        total_usd_value += available_amount  # USDC ≈ USD
                    elif currency == 'BTC':
                        # Rough estimate: 1 BTC ≈ $40,000 (adjust as needed)
                        btc_price = 40000
                        total_usd_value += available_amount * btc_price
                    elif currency == 'ETH':
                        # Rough estimate: 1 ETH ≈ $2,500 (adjust as needed)
                        eth_price = 2500
                        total_usd_value += available_amount * eth_price
                
                if usd_value:
                    logger.info(f"  USD Value: ${usd_value:.2f}")
                    total_usd_value += usd_value
                logger.info("")
        
        if total_usd_value > 0:
            logger.info(f"{'='*60}")
            logger.info(f"Total Portfolio Value: ${total_usd_value:.2f} USD")
            logger.info(f"{'='*60}\n")
        
        logger.info("✅ Balance check complete!")
        
    except Exception as e:
        logger.error(f"❌ Error checking balance: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    check_balance()

