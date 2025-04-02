from .dc import dc


async def setup(bot):
    await bot.add_cog(dc(bot))