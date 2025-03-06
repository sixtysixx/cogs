from redbot.core import commands
import discord
import concurrent.futures
import asyncio

class dc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Increased max workers for faster concurrent operations
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)

    @commands.command(name="dc")
    @commands.max_concurrency(3, per=commands.BucketType.guild, wait=True)
    async def delete_category(self, ctx, category_id: int):
        """Deletes all channels within the specified category ID"""
        # Direct ID lookup is faster than get()
        category = ctx.guild.get_channel(category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            await ctx.send(f"Category with ID {category_id} not found.", delete_after=5)
            return

        confirm_msg = await ctx.send(
            f"Are you sure you want to delete all channels in '{category.name}'? React with ✅ to confirm or ❌ to cancel.",
            delete_after=10
        )

        # Add reactions for confirmation
        await confirm_msg.add_reaction('✅')
        await confirm_msg.add_reaction('❌')

        def check(reaction, user):
            return (user.id == ctx.author.id and 
                    reaction.message.id == confirm_msg.id and 
                    str(reaction.emoji) in ['✅', '❌'])

        try:
            # Store channels before confirmation to avoid another API call
            channels = category.channels
            reaction, user = await self.bot.wait_for('reaction_add', check=check, timeout=10.0)

            # Clean up confirmation message
            await confirm_msg.delete()  

            if str(reaction.emoji) == '✅':
                # Batch delete channels in parallel
                delete_tasks = [channel.delete(reason=f"Category deletion by {ctx.author}") for channel in channels]
                await asyncio.gather(*delete_tasks)
                
                response = await ctx.send(f"Deleted all channels in '{category.name}'.")
                await asyncio.sleep(5)
                await response.delete()
                await ctx.message.delete()
            else:
                await ctx.send("Operation cancelled.", delete_after=5)
                await ctx.message.delete()

        except asyncio.TimeoutError:
            await ctx.send("Operation cancelled due to no confirmation.", delete_after=5)
            await confirm_msg.delete()
            await ctx.message.delete()

async def setup(bot):
    await bot.add_cog(dc(bot))