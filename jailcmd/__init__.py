from .jailuser import JailUser

async def setup(bot):
    await bot.add_cog(JailUser(bot))
