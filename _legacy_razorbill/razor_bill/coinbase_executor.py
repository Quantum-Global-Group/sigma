"""
Coinbase Advanced Trade API Executor
Implements real trading execution via Coinbase Advanced Trade API
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from coinbase.rest import RESTClient
from loguru import logger

from .config import settings
from .execution import PaperOrder


class CoinbaseExecutor:
    """Real trading executor using Coinbase Advanced Trade API"""
    
    def __init__(self):
        """Initialize Coinbase Advanced Trade client"""
        # Coinbase Advanced Trade API uses EC private key authentication
        # Check for new format first (api_key_name + private_key)
        if settings.coinbase_api_key_name and settings.coinbase_private_key:
            api_key_name = settings.coinbase_api_key_name
            private_key = settings.coinbase_private_key
            # Replace \n with actual newlines if needed
            if "\\n" in private_key:
                private_key = private_key.replace("\\n", "\n")
        # Fallback to legacy format for backward compatibility
        elif settings.coinbase_api_key and settings.coinbase_api_secret and settings.coinbase_api_passphrase:
            logger.warning("Using legacy API key format. Consider migrating to api_key_name + private_key format.")
            api_key_name = settings.coinbase_api_key
            private_key = settings.coinbase_api_secret  # In legacy format, secret might be the private key
        else:
            raise ValueError(
                "Coinbase credentials required. Set either:\n"
                "  - COINBASE_API_KEY_NAME and COINBASE_PRIVATE_KEY (recommended), or\n"
                "  - COINBASE_API_KEY, COINBASE_API_SECRET, and COINBASE_API_PASSPHRASE (legacy)"
            )
        
        # Initialize Coinbase client
        # RESTClient uses api_key (the key name/ID) and api_secret (the private key)
        # For sandbox, use api-sandbox.coinbase.com, for production use api.coinbase.com
        try:
            base_url = "api-sandbox.coinbase.com" if settings.coinbase_sandbox else "api.coinbase.com"
            self.client = RESTClient(
                api_key=api_key_name,
                api_secret=private_key,
                base_url=base_url
            )
            logger.info(f"Coinbase Advanced Trade client initialized successfully (sandbox: {settings.coinbase_sandbox})")
        except Exception as e:
            logger.error(f"Failed to initialize Coinbase client: {e}")
            raise
        
        self.orders: list[PaperOrder] = []
    
    async def market_order(self, symbol: str, side: str, qty: float, px: float) -> PaperOrder:
        """
        Execute a market order via Coinbase Advanced Trade API
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            qty: Quantity to trade (in base currency for buy, in quote currency for sell)
            px: Current market price (used for reference, market orders use best available price)
        
        Returns:
            PaperOrder with execution details
        """
        if qty <= 0:
            logger.warning(f"Invalid quantity {qty} for {symbol}, skipping order")
            return PaperOrder(
                t=datetime.now(timezone.utc),
                symbol=symbol,
                side=side,
                qty=0.0,
                px=px,
                fee=0.0,
                slip=0.0
            )
        
        try:
            # Generate a unique client order ID
            client_order_id = str(uuid.uuid4())
            
            # Place order using the appropriate method
            # For BUY: use market_order_buy with quote_size (amount in quote currency, e.g., USD)
            # For SELL: use market_order_sell with base_size (amount in base currency, e.g., BTC)
            loop = asyncio.get_event_loop()
            
            if side.lower() == "buy":
                # For buys, calculate quote_size from base quantity
                quote_size = str(qty * px)  # Convert base qty to USD amount
                logger.info(f"Placing BUY market order: {qty} {symbol} (quote_size: {quote_size})")
                
                def place_buy_order():
                    return self.client.market_order_buy(
                        client_order_id=client_order_id,
                        product_id=symbol,
                        quote_size=quote_size
                    )
                response = await loop.run_in_executor(None, place_buy_order)
            else:  # sell
                # For sells, use base_size directly
                base_size = str(qty)
                logger.info(f"Placing SELL market order: {qty} {symbol} (base_size: {base_size})")
                
                def place_sell_order():
                    return self.client.market_order_sell(
                        client_order_id=client_order_id,
                        product_id=symbol,
                        base_size=base_size
                    )
                response = await loop.run_in_executor(None, place_sell_order)
            
            # Extract order_id from response
            # CreateOrderResponse has an 'order_id' attribute or may be nested
            order_id = None
            if hasattr(response, 'order_id'):
                order_id = response.order_id
            elif hasattr(response, 'order') and hasattr(response.order, 'order_id'):
                order_id = response.order.order_id
            elif isinstance(response, dict):
                order_id = response.get("order_id") or response.get("orderId") or response.get("id")
                if not order_id and "order" in response:
                    order_id = response["order"].get("order_id") or response["order"].get("orderId") or response["order"].get("id")
            elif hasattr(response, 'id'):
                order_id = response.id
            
            if not order_id:
                logger.error(f"Failed to extract order_id from response: {response}")
                # Try to get client_order_id as fallback
                if hasattr(response, 'client_order_id'):
                    order_id = response.client_order_id
                    logger.info(f"Using client_order_id as order_id: {order_id}")
                else:
                    return PaperOrder(
                        t=datetime.now(timezone.utc),
                        symbol=symbol,
                        side=side,
                        qty=0.0,
                        px=px,
                        fee=0.0,
                        slip=0.0
                    )
            logger.info(f"Order placed: {order_id} for {symbol}")
            
            # Poll for order status until filled or timeout
            order_details = await self._poll_order_status(order_id, symbol)
            
            if not order_details:
                logger.error(f"Failed to get order details for {order_id}")
                return PaperOrder(
                    t=datetime.now(timezone.utc),
                    symbol=symbol,
                    side=side,
                    qty=0.0,
                    px=px,
                    fee=0.0,
                    slip=0.0
                )
            
            # Extract execution details (handle different response structures)
            def get_nested_value(data, *keys, default=0):
                """Get value from nested dict/object with multiple possible key names"""
                # Convert to dict if it has to_dict method
                if hasattr(data, 'to_dict'):
                    data = data.to_dict()
                elif hasattr(data, '__dict__'):
                    # Try to access as object attributes first
                    for key in keys:
                        if hasattr(data, key):
                            val = getattr(data, key, None)
                            if val is not None:
                                return val
                    # Fallback to dict conversion
                    try:
                        data = data.__dict__
                    except:
                        pass
                
                if isinstance(data, dict):
                    for key in keys:
                        if key in data:
                            return data[key]
                    # Check nested in "order" key
                    if "order" in data:
                        order_data = data["order"]
                        if hasattr(order_data, 'to_dict'):
                            order_data = order_data.to_dict()
                        for key in keys:
                            if isinstance(order_data, dict) and key in order_data:
                                return order_data[key]
                            elif hasattr(order_data, key):
                                return getattr(order_data, key, default)
                elif hasattr(data, keys[0]):
                    return getattr(data, keys[0], default)
                return default
            
            filled_size = float(get_nested_value(
                order_details, "filled_size", "filledSize", "filled", "size", default=0
            ))
            average_filled_price = float(get_nested_value(
                order_details, "average_filled_price", "averageFilledPrice", 
                "average_price", "averagePrice", "price", default=px
            ))
            total_fees = float(get_nested_value(
                order_details, "total_fees", "totalFees", "fees", "fee", default=0
            ))
            
            # Calculate slippage (difference between expected and actual price)
            expected_notional = qty * px
            actual_notional = filled_size * average_filled_price
            slippage = abs(actual_notional - expected_notional) if side == "buy" else 0.0
            
            order = PaperOrder(
                t=datetime.now(timezone.utc),
                symbol=symbol,
                side=side,
                qty=filled_size,
                px=average_filled_price,
                fee=total_fees,
                slip=slippage
            )
            
            self.orders.append(order)
            logger.info(
                f"Executed {side} {filled_size:.4f} {symbol} @ ${average_filled_price:.4f} "
                f"(fee: ${total_fees:.2f}, slip: ${slippage:.2f})"
            )
            
            return order
            
        except Exception as e:
            logger.error(f"Error executing {side} order for {symbol}: {e}")
            # Return zero-filled order on error
            return PaperOrder(
                t=datetime.now(timezone.utc),
                symbol=symbol,
                side=side,
                qty=0.0,
                px=px,
                fee=0.0,
                slip=0.0
            )
    
    async def _poll_order_status(self, order_id: str, symbol: str) -> Optional[dict]:
        """
        Poll order status until filled or timeout
        
        Args:
            order_id: Order ID from Coinbase
            symbol: Trading pair symbol
        
        Returns:
            Order details dict or None if timeout/error
        """
        timeout = settings.coinbase_order_timeout_seconds
        start_time = datetime.now(timezone.utc)
        poll_interval = 1.0  # Poll every second
        
        while True:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Order {order_id} status polling timeout after {timeout}s")
                return None
            
            try:
                loop = asyncio.get_event_loop()
                
                def get_order_status():
                    return self.client.get_order(order_id=order_id)
                
                order_details = await loop.run_in_executor(None, get_order_status)
                
                if not order_details:
                    await asyncio.sleep(poll_interval)
                    continue
                
                # Extract status from response (could be attribute or dict key)
                status = None
                if hasattr(order_details, 'order') and hasattr(order_details.order, 'status'):
                    status = order_details.order.status
                elif hasattr(order_details, 'status'):
                    status = order_details.status
                elif isinstance(order_details, dict):
                    status = order_details.get("status") or (order_details.get("order", {}).get("status") if isinstance(order_details.get("order"), dict) else None)
                
                if not status:
                    await asyncio.sleep(poll_interval)
                    continue
                    
                status = str(status).upper()
                
                if status in ["FILLED", "SETTLED"]:
                    logger.info(f"Order {order_id} filled successfully")
                    return order_details
                elif status in ["CANCELLED", "EXPIRED", "REJECTED"]:
                    logger.warning(f"Order {order_id} {status.lower()}")
                    return order_details
                else:
                    # Order still pending (OPEN, PENDING, etc.)
                    await asyncio.sleep(poll_interval)
                    continue
                    
            except Exception as e:
                logger.error(f"Error polling order status for {order_id}: {e}")
                await asyncio.sleep(poll_interval)
                continue
    
    def get_order_history(self) -> list[PaperOrder]:
        """Get all executed orders"""
        return self.orders.copy()

