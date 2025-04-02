from .code import code


async def setup(bot):
    await bot.add_cog(code(bot))