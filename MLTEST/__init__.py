from .MLTEST import MLTEST

async def setup(bot):
    await bot.add_cog(MLTEST(bot))