import discord
from redbot.core import commands
from groq import Groq
import yfinance as yf
import asyncio
from collections import deque
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()


class MarketAdvice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_histories = (
            {}
        )  # Dictionary to store conversation history for each user
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.system_prompt = """You are a financial market analysis assistant. Analyze market data and provide insights on:
        - Market trends and price action
        - Support and resistance levels
        - Technical indicators
        - Trading recommendations
        Be concise and focus on actionable insights."""
        self.timeframe_candles = {
            "1m": 600,  # 10 hours of 1-min data
            "5m": 150,  # 12.5 hours of 5-min data
            "15m": 100,  # 25 hours of 15-min data
            "30m": 80,  # 40 hours of 30-min data
            "1h": 60,  # 2.5 days of hourly data
            "4h": 40,  # ~7 days of 4-hour data
            "1d": 30,  # 1 month of daily data
        }
        self.request_queue = deque(maxlen=10)  # Queue for requests
        self.user_cooldowns = {}  # Track user cooldowns
        self.queue_lock = asyncio.Lock()  # Lock for queue operations
        # Market type suffixes
        self.market_suffixes = {
            "crypto": ("-USD", "-USDT", "-BTC"),  # Crypto pairs
            "forex": ("=X",),  # Forex pairs
            "futures": ("=F",),  # Futures
            "stocks": (".", ":"),  # Stocks with exchange suffixes
        }

    @commands.command(name="clear_history")
    async def wipe_user_history(self, ctx):
        """Wipe the conversation history for the user."""
        user_id = ctx.author.id
        if user_id in self.user_histories:
            del self.user_histories[user_id]
            await ctx.send("Your conversation history has been wiped.")
        else:
            await ctx.send("You have no conversation history to wipe.")

    @commands.command(name="clear_all_histories")
    @commands.is_owner()  # This ensures only the bot owner can use this command
    async def wipe_all_history(self, ctx):
        """Wipe all conversation histories."""
        self.user_histories.clear()
        await ctx.send("All conversation histories have been wiped.")

    def format_symbol(self, symbol: str) -> str:
        """Format symbol based on market type"""
        symbol = symbol.upper()

        # Check if symbol already has a market suffix
        for suffixes in self.market_suffixes.values():
            if any(symbol.endswith(suffix) for suffix in suffixes):
                return symbol

        # Add market-specific formatting
        if "/" in symbol:  # Forex pair
            symbol = symbol.replace("/", "") + "=X"
        elif symbol.endswith("USD") or symbol.endswith("USDT"):  # Crypto
            if not symbol.endswith("T"):  # If it ends in USD but not USDT
                symbol = symbol[:-3] + "-USD"
        elif symbol.startswith("BTC") or symbol.startswith("ETH"):  # Common crypto
            symbol = symbol + "-USD"

        return symbol

    async def fetch_market_data(self, symbol, timeframe):
        """Fetch market data using yfinance with error handling"""
        try:
            formatted_symbol = self.format_symbol(symbol)
            ticker = yf.Ticker(formatted_symbol)
            # Adjust period based on timeframe to ensure we get enough data
            period_map = {
                "1m": "1d",
                "5m": "5d",
                "15m": "5d",
                "30m": "5d",
                "1h": "7d",
                "4h": "30d",
                "1d": "60d",
            }
            period = period_map.get(timeframe, "5d")
            hist = ticker.history(period=period, interval=timeframe)
            if hist.empty:
                raise ValueError(
                    "No data available for the given symbol and timeframe."
                )
            return hist
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return None

    async def generate_market_analysis(self, symbol, timeframe):
        """Generate market analysis based on fetched data"""
        try:
            data = await self.fetch_market_data(symbol, timeframe)
            if data is None:
                return "No data available for the given symbol and timeframe."

            current_price = data["Close"].iloc[-1]
            volume = data["Volume"].iloc[-1]

            # Get optimal number of candles for the timeframe
            num_candles = self.timeframe_candles.get(timeframe, 100)
            last_candles = data.tail(num_candles)
            candle_data = []
            for idx, row in last_candles.iterrows():
                candle = {
                    "timestamp": idx.strftime("%Y-%m-%d %H:%M"),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row["Volume"],
                }
                candle_data.append(candle)

            # Prepare market data for AI analysis
            market_prompt = f"""
            Analyze the following market data for {symbol.upper()}:
            Current price: ${current_price:.2f}
            Trading volume: {volume}
            Timeframe: {timeframe}

            Last {num_candles} candlesticks:
            {candle_data}

            Provide a detailed analysis including the following points:
            1. Market trend:
            - Describe the overall market trend (e.g., bullish, bearish, sideways)
            - Identify any significant candlestick patterns
            2. Support and resistance levels:
            - Identify key support and resistance levels based on recent price action
            3. Technical indicators:
            - Analyze important technical indicators (e.g., RSI, MACD, Moving Averages)
            4. Trading recommendation:
            - Clearly state a buy, sell, or hold recommendation
            - Provide entry price and stop loss levels based on recent candlestick patterns
            - List the top 3 reasons for the recommendation

            Note: Use bullet points (•) for clarity and ensure the trading recommendation is very clear.
            """

            # Generate AI analysis
            response = await self.generate_code_response(symbol, market_prompt)
            if response:
                return response
            else:
                return "Failed to generate market analysis. Please try again later. (Error: No response received.)"

        except Exception as e:
            return f"Error generating market analysis: {e}"

    async def clean_response(self, response):
        """Clean the response by removing any text before </think>"""
        if "</think>" in response:
            return response.split("</think>")[1].strip()
        return response

    async def generate_code_response(self, user_id, message):
        """Centralized method to generate code response"""
        try:
            # Limit conversation history
            if len(self.user_histories.get(user_id, [])) > 10:
                self.user_histories[user_id] = self.user_histories[user_id][-10:]

            # Add user message to history
            if user_id not in self.user_histories:
                self.user_histories[user_id] = []
            self.user_histories[user_id].append({"role": "user", "content": message})

            # Prepare messages for API call
            messages = [
                {"role": "system", "content": self.system_prompt},
                *self.user_histories[user_id],
            ]

            # Generate response with timeout
            async with asyncio.timeout(60):
                completion = await asyncio.to_thread(
                    self.groq_client.chat.completions.create,
                    model="deepseek-r1-distill-llama-70b",
                    messages=messages,
                    temperature=0.5,
                    max_tokens=16384,
                    top_p=0.5,
                    stream=False,
                )

            # Extract response
            full_response = completion.choices[0].message.content

            # Add AI response to history
            self.user_histories[user_id].append(
                {"role": "assistant", "content": full_response}
            )

            # Check if the response is None or empty
            if not full_response:
                print("Warning: Received empty response from AI.")
                return None

            return full_response

        except asyncio.TimeoutError:
            return "Request timed out. Please try again later."
        except Exception as e:
            print(f"Error in generate_code_response: {str(e)}")
            return None

    async def can_make_request(self, user_id, ctx):
        """Check if user can make a request based on cooldown and queue"""
        async with self.queue_lock:
            now = datetime.now()

            # Check user cooldown
            if user_id in self.user_cooldowns:
                last_request = self.user_cooldowns[user_id]
                if now - last_request < timedelta(minutes=1):
                    cooldown_end = last_request + timedelta(minutes=1)
                    cooldown_msg = (
                        f"You must wait, retry <t:{int(cooldown_end.timestamp())}:R>"
                    )
                    msg = await ctx.send(cooldown_msg)
                    # Schedule message deletion at cooldown end
                    wait_time = (cooldown_end - now).total_seconds()
                    self.bot.loop.create_task(self.delete_after_delay(msg, wait_time))
                    return False, None

            # Check queue length
            if len(self.request_queue) >= 10:
                return False, "Queue is full. Please try again later."

            # Add to queue and update cooldown
            self.request_queue.append(user_id)
            self.user_cooldowns[user_id] = now
            return True, None

    async def delete_after_delay(self, message, delay):
        """Helper method to delete a message after a delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except discord.NotFound:
            pass

    @commands.command(name="ma")
    async def market_analysis(self, ctx, symbol: str, timeframe: str = "15m"):
        """Generate market analysis based on user request"""
        user_id = ctx.author.id

        # Check if user can make request
        can_request, error_msg = await self.can_make_request(user_id, ctx)
        if not can_request:
            if error_msg:
                await ctx.send(error_msg)
            return

        processing_msg = await ctx.send("Generating market analysis...")

        try:
            # Generate market analysis
            analysis = await self.generate_market_analysis(symbol, timeframe)
            await processing_msg.delete()

            # Check if analysis is None
            if not analysis:
                await ctx.send(
                    "Market analysis failed: No response received.",
                    reference=ctx.message,
                )
                return

            # Clean the response
            cleaned_analysis = await self.clean_response(analysis)

            # Create and send embed
            embed = discord.Embed(
                title=f"Market Analysis for {symbol.upper()} ({timeframe})",
                description=cleaned_analysis,
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"Requested by {ctx.author.display_name}")

            # Send analysis in embed
            await ctx.send(embed=embed, reference=ctx.message)

        except Exception as e:
            await ctx.send(f"Market analysis error: {e}", reference=ctx.message)
        finally:
            # Remove request from queue
            async with self.queue_lock:
                if user_id in self.request_queue:
                    self.request_queue.remove(user_id)


async def setup(bot):
    await bot.add_cog(MarketAdvice(bot))
