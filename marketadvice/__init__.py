from .marketadvice import MarketAdvice

async def setup(bot):
    await bot.add_cog(MarketAdvice(bot))