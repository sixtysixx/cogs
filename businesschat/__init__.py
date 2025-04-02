from .businesschat import bchat


async def setup(bot):
    await bot.add_cog(bchat(bot))