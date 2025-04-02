import discord
from redbot.core import commands
import requests
import asyncio
from collections import deque
from datetime import datetime, timedelta
import random
import logging
from dotenv import load_dotenv

load_dotenv()


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class mememarket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_histories = {}
        self.request_queue = deque(maxlen=10)
        self.user_cooldowns = {}
        self.queue_lock = asyncio.Lock()
        self.channel_id = 1281393340637642822  # Set this to your channel ID
        self.bg_task = None  # Initialize as None
        self.seen_tokens = set()  # Track seen token addresses
        logger.info("Mememarket cog initialized")

    async def initialize(self):
        """Initialize background task after cog is loaded"""
        logger.info("Initializing background scanner...")
        self.bg_task = self.bot.loop.create_task(self.background_scanner())

    async def background_scanner(self):
        """Background task to scan for new tokens"""
        await self.bot.wait_until_ready()
        logger.info("Background scanner started")
        while not self.bot.is_closed():
            try:
                channel = self.bot.get_channel(self.channel_id)
                logger.debug(f"Scanning channel: {self.channel_id}")

                # Scan all token types
                token_types = {1: "New Token", 2: "About to Graduate", 3: "Graduated"}

                for type_id, type_name in token_types.items():
                    logger.debug(f"Scanning token type {type_id}: {type_name}")
                    tokens = await self.fetch_bullme_data(type_id)
                    for token in tokens:
                        if token["address"] in self.seen_tokens:
                            logger.debug(
                                f"Token {token['address']} already seen, skipping"
                            )
                            continue

                        logger.info(
                            f"New token found: {token['name']} ({token['symbol']})"
                        )
                        self.seen_tokens.add(token["address"])
                        embed = discord.Embed(
                            title=f"{type_name} Alert: {token['name']} ({token['symbol']})",
                            description=f"Chain: {token['chain'].upper()}\nAddress: {token['address']}",
                            color=discord.Color.green(),
                        )
                        embed.add_field(
                            name="Market Cap", value=f"${token['marketCap']:,.2f}"
                        )
                        embed.add_field(
                            name="24h Volume", value=f"${token['volume24h']:,.2f}"
                        )
                        embed.add_field(
                            name="Liquidity", value=f"${token['liquidity']:,.2f}"
                        )
                        embed.add_field(
                            name="Price", value=f"${float(token['priceUsd']):,.8f}"
                        )
                        embed.add_field(name="Holders", value=str(token["holders"]))
                        embed.add_field(
                            name="24h Change", value=f"{token['price_change_24h']}%"
                        )
                        await channel.send(embed=embed)
                        logger.info(f"Alert sent for token {token['name']}")

            except Exception as e:
                logger.error(f"Error in background scanner: {str(e)}", exc_info=True)
            await asyncio.sleep(15)  # Increased to 15 seconds
            logger.debug("Scanner sleeping for 15 seconds")

    async def fetch_bullme_data(self, type_id=1):
        """Fetch token data from Bullme API"""
        logger.info(f"Fetching Bullme data for type {type_id}")

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edge/120.0.0.0",
        ]

        headers = {
            "User-Agent": random.choice(user_agents),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Origin": "https://bullme.one",
            "Referer": "https://bullme.one/",
            "DNT": "1",
            "Cookie": "",
        }

        await asyncio.sleep(random.uniform(1, 3))
        logger.debug("Sleeping before API request")

        url = f"https://api.bullme.one/market/token/tokens?type={type_id}"

        for attempt in range(3):
            try:
                headers["User-Agent"] = random.choice(user_agents)
                logger.debug(f"API request attempt {attempt + 1}")

                response = requests.get(url, headers=headers, verify=False, timeout=30)
                logger.info(f"API response status: {response.status_code}")

                if response.status_code == 403:
                    logger.warning("403 Forbidden - Waiting before retry...")
                    await asyncio.sleep(10 + (attempt * 5))
                    continue

                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.debug("Successfully parsed JSON response")
                        logger.debug(f"JSON response: {data}")
                    except ValueError as e:
                        logger.error(f"JSON decode error: {str(e)}")
                        await asyncio.sleep(10 + (attempt * 5))
                        continue

                    total_tokens = len(data.get("data", []))
                    logger.info(f"Total tokens found: {total_tokens}")

                    filtered_tokens = []
                    max_age = datetime.now() - timedelta(hours=24)

                    for token in data.get("data", []):
                        try:
                            mcap = float(token.get("marketCap", 0))
                            volume = float(token.get("tradeVolume", 0))
                            liquidity = float(token.get("liquidity", 0))
                            created_at = datetime.fromtimestamp(
                                int(token.get("timestamp", 0) / 1000)
                            )
                            holders = float(token.get("top10Holder", 0)) * 100
                            price_change = float(token.get("bondingCurveProgress", 0))
                            total_supply = float(token.get("totalSupply", 0)) * (
                                10 ** token.get("decimals", 6)
                            )

                            # Calculate price
                            if total_supply != 0:
                                price_usd = mcap / total_supply
                            else:
                                price_usd = 0.0

                            if (
                                10000 <= mcap <= 100000
                                and volume >= 25000
                                and 25000 <= liquidity <= 200000
                                and created_at > max_age
                                and holders >= 50
                                and price_change >= -5.0
                            ):
                                logger.debug(
                                    f"Token {token.get('name')} passed filters"
                                )
                                token_info = {
                                    "name": token.get("name", "Unknown"),
                                    "symbol": token.get("symbol", "Unknown"),
                                    "address": token.get("address", ""),
                                    "marketCap": mcap,
                                    "volume24h": volume,
                                    "liquidity": liquidity,
                                    "priceUsd": price_usd,
                                    "chain": "solana",
                                    "age": created_at,
                                    "holders": holders,
                                    "price_change_24h": price_change,
                                    "creator": token.get("creator", "Unknown"),
                                    "website": token.get("website", ""),
                                    "twitter": token.get("twitter", ""),
                                    "telegram": token.get("telegram", ""),
                                    "rugcheck_score": token.get(
                                        "rugcheck_score", "N/A"
                                    ),
                                    "quick_buy_links": token.get("quick_buy_links", []),
                                }
                                filtered_tokens.append(token_info)
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error processing token: {str(e)}")
                            continue

                    logger.info(f"Found {len(filtered_tokens)} filtered tokens")
                    return filtered_tokens
                else:
                    logger.error(f"Error: Status code {response.status_code}")
                    await asyncio.sleep(10 + (attempt * 5))

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {str(e)}")
                await asyncio.sleep(10 + (attempt * 5))
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                await asyncio.sleep(10 + (attempt * 5))

        logger.error("All retry attempts failed")
        return []

    @commands.command()
    @commands.is_owner()
    async def testapis(self, ctx):
        """Test API connectivity and responses"""
        logger.info("Starting API tests...")
        await ctx.send("Starting API connectivity tests...")

        for type_id in [1, 2, 3]:
            logger.info(f"Testing Bullme API type {type_id}")
            tokens = await self.fetch_bullme_data(type_id)
            if tokens:
                logger.info(f"Bullme API type {type_id} working")
                test_token = tokens[0]
                logger.info(
                    f"Sample token found: {test_token['name']} ({test_token['symbol']})"
                )
                logger.info("Token details:")
                logger.info(f"  - Address: {test_token['address']}")
                logger.info(f"  - Market Cap: ${test_token['marketCap']:,.2f}")
                logger.info(f"  - Volume 24h: ${test_token['volume24h']:,.2f}")
                logger.info(f"  - Liquidity: ${test_token['liquidity']:,.2f}")
                logger.info(f"  - Holders: {test_token.get('holders', 'N/A')}")
                logger.info(
                    f"  - 24h Price Change: {test_token.get('price_change_24h', 'N/A')}%"
                )
            else:
                logger.error(f"Bullme API type {type_id} failed")

        logger.info("API tests completed")
        await ctx.send("API tests completed - check console for detailed results")

    @commands.command()
    @commands.is_owner()
    async def forcescan(self, ctx):
        """Force an immediate token scan"""
        logger.info("Starting forced token scan")
        await ctx.send("Starting forced token scan...")
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            token_types = {1: "New Token", 2: "About to Graduate", 3: "Graduated"}

            for type_id, type_name in token_types.items():
                logger.info(f"Scanning type {type_id}: {type_name}")
                tokens = await self.fetch_bullme_data(type_id)
                for token in tokens:
                    if token["address"] in self.seen_tokens:
                        logger.debug(f"Token {token['address']} already seen, skipping")
                        continue

                    logger.info(f"New token found: {token['name']}")
                    self.seen_tokens.add(token["address"])
                    embed = discord.Embed(
                        title=f"{type_name} Alert: {token['name']} ({token['symbol']})",
                        description=f"Chain: {token['chain'].upper()}\nAddress: {token['address']}",
                        color=discord.Color.green(),
                    )
                    embed.add_field(
                        name="Market Cap", value=f"${token['marketCap']:,.2f}"
                    )
                    embed.add_field(
                        name="24h Volume", value=f"${token['volume24h']:,.2f}"
                    )
                    embed.add_field(
                        name="Liquidity", value=f"${token['liquidity']:,.2f}"
                    )
                    embed.add_field(
                        name="Price", value=f"${float(token['priceUsd']):,.8f}"
                    )
                    embed.add_field(name="Holders", value=str(token["holders"]))
                    embed.add_field(
                        name="24h Change", value=f"{token['price_change_24h']}%"
                    )
                    await channel.send(embed=embed)
                    logger.info(f"Alert sent for token {token['name']}")
        logger.info("Forced scan completed")
        await ctx.send("Forced scan completed")
