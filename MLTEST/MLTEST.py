import numpy as np
import pandas as pd
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from redbot.core import commands
import asyncio
import os
import logging
from functools import lru_cache
import atexit
from typing import Dict, Tuple, List, Optional
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='trading_bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

class MLTEST(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Load environment variables from env file
        self.api_key = os.getenv('api_key')
        self.secret_key = os.getenv('secret_key')
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Missing required environment variables for authentication")

        # Initialize Alpaca clients with error handling
        try:
            self.data_client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.secret_key
            )
            self.trading_client = TradingClient(
                api_key=self.api_key, 
                secret_key=self.secret_key
            )
        except Exception as e:
            logger.error(f"Failed to initialize Alpaca clients: {e}")
            raise
        
        # Load FinBERT model with error handling and caching
        try:
            self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert", cache_dir=".model_cache")
            self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", cache_dir=".model_cache")
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self.model.to(self.device)
            self.model.eval()  # Set model to evaluation mode
        except Exception as e:
            logger.error(f"Failed to load FinBERT model: {e}")
            raise
        
        # RL parameters - tuned for better performance
        self.learning_rate = 0.005
        self.gamma = 0.95
        self.epsilon = 0.15
        self.epsilon_decay = 0.995
        self.epsilon_min = 0.01
        self.state_size = 12
        self.action_size = 3  # buy, sell, hold
        
        # Trading limits with risk management
        self.max_position = 100
        self.max_trades_per_day = 20
        self.min_trade_interval = 300  # 5 minutes between trades
        self.trade_count = 0
        self.last_trade_time = pd.Timestamp.now()
        self.last_trade_reset = pd.Timestamp.now().date()
        
        # Initialize Q-table with persistence
        self.q_table: Dict[Tuple, np.ndarray] = self.load_q_table()
        atexit.register(self.save_q_table)
        
        # Cache for market data with TTL
        self.price_cache = {}
        self.cache_timeout = 60  # seconds
        self.last_cache_cleanup = pd.Timestamp.now()
        
        # Performance tracking
        self.total_profit = 0
        self.trades_history = []
        
    def load_q_table(self) -> Dict:
        """Load Q-table from disk if exists with error handling"""
        try:
            if os.path.exists('q_table.json'):
                with open('q_table.json', 'r') as f:
                    data = json.load(f)
                    return {tuple(eval(k)): np.array(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to load Q-table: {e}")
        return {}

    def save_q_table(self):
        """Save Q-table to disk with backup"""
        try:
            # Create backup of existing table
            if os.path.exists('q_table.json'):
                os.rename('q_table.json', 'q_table.backup.json')
            
            with open('q_table.json', 'w') as f:
                json.dump({str(k): v.tolist() for k, v in self.q_table.items()}, f)
                
            if os.path.exists('q_table.backup.json'):
                os.remove('q_table.backup.json')
        except Exception as e:
            logger.error(f"Failed to save Q-table: {e}")

    @lru_cache(maxsize=256)
    def get_state(self, prices: Tuple[float, ...], sentiment: float) -> Tuple:
        """Convert market data to state representation with technical indicators"""
        price_changes = np.diff(prices) / prices[:-1]
        volatility = np.std(price_changes[-5:])
        momentum = np.mean(price_changes[-3:])
        state = np.concatenate([
            price_changes[-self.state_size:],
            [sentiment],
            [volatility],
            [momentum]
        ])
        return tuple(state.round(4))
        
    def get_sentiment(self, text: str) -> np.ndarray:
        """Get market sentiment using FinBERT with error handling and timeout"""
        try:
            inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad(), torch.cuda.amp.autocast(enabled=True):
                outputs = self.model(**inputs)
                
            sentiment = torch.softmax(outputs.logits, dim=1)
            return sentiment[0].cpu().numpy()
        except Exception as e:
            logger.error(f"Error in sentiment analysis: {e}")
            return np.array([0.33, 0.33, 0.34])  # Slightly optimistic fallback
        
    def get_action(self, state: Tuple) -> int:
        """Choose action using epsilon-greedy policy with decay"""
        if state not in self.q_table:
            self.q_table[state] = np.zeros(self.action_size)
            
        if np.random.random() < self.epsilon:
            action = np.random.randint(self.action_size)
        else:
            action = np.argmax(self.q_table[state])
            
        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        
        return action
        
    async def execute_trade(self, symbol: str, action: int):
        """Execute trade on Alpaca with position and limit checks"""
        current_time = pd.Timestamp.now()
        
        # Check trade timing limits
        if (current_time - self.last_trade_time).seconds < self.min_trade_interval:
            logger.info("Minimum trade interval not elapsed")
            return
            
        # Reset daily trade count
        current_date = current_time.date()
        if current_date > self.last_trade_reset:
            self.trade_count = 0
            self.last_trade_reset = current_date
            
        if self.trade_count >= self.max_trades_per_day:
            logger.warning("Daily trade limit reached")
            return
            
        # Check current position and risk limits
        try:
            position = self.trading_client.get_position(symbol)
            current_qty = int(position.qty)
            current_value = float(position.market_value)
            
            # Risk management checks
            account = self.trading_client.get_account()
            portfolio_value = float(account.portfolio_value)
            position_limit = min(self.max_position, int(portfolio_value * 0.1))  # Max 10% of portfolio
            
        except Exception:
            current_qty = 0
            current_value = 0
            
        if action == 0 and current_qty >= position_limit:  # Buy
            logger.warning(f"Maximum position ({position_limit}) reached for {symbol}")
            return
        elif action == 1 and current_qty <= 0:  # Sell
            logger.warning(f"No position to sell for {symbol}")
            return
            
        # Execute trade with position sizing
        try:
            qty = self._calculate_position_size(symbol, portfolio_value)
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if action == 0 else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            self.trading_client.submit_order(order)
            self.trade_count += 1
            self.last_trade_time = current_time
            
            # Record trade
            self.trades_history.append({
                'timestamp': current_time,
                'symbol': symbol,
                'action': 'buy' if action == 0 else 'sell',
                'quantity': qty,
                'price': self.price_cache.get(symbol, (None, None))[0][-1] if symbol in self.price_cache else None
            })
            
            logger.info(f"Successfully executed {order.side} order for {symbol}, qty: {qty}")
            
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            
    def _calculate_position_size(self, symbol: str, portfolio_value: float) -> int:
        """Calculate appropriate position size based on volatility and portfolio value"""
        try:
            # Get historical volatility
            if symbol in self.price_cache:
                prices = self.price_cache[symbol][0]
                returns = np.diff(prices) / prices[:-1]
                volatility = np.std(returns) * np.sqrt(252)  # Annualized volatility
                
                # Adjust position size inversely to volatility
                base_size = portfolio_value * 0.02  # 2% base position size
                adjusted_size = base_size / (volatility * 100)  # Reduce size for higher volatility
                
                return max(1, min(self.max_position, int(adjusted_size)))
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            
        return 1  # Default to minimum size on error

def setup(bot):
    bot.add_cog(MLTEST(bot))
