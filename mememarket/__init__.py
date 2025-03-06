from .mememarket import mememarket

async def setup(bot):
    await bot.add_cog(mememarket(bot))