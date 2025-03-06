from .AIchat import chat


async def setup(bot):
    await bot.add_cog(chat(bot))