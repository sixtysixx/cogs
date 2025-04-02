from redbot.core import commands, data_manager
from discord.utils import get
from datetime import datetime, timedelta
import asyncio
import os
import discord
import concurrent.futures
import pathlib


class JailUser(commands.Cog):
    def __init__(self, bot):
        # Initializes the bot instance, jail role ID, log channel ID, and specific role ID for access
        self.bot = bot
        self.jail_role_id = 1245077976316379187  # ID for the jail role
        self.log_channel_id = 1274393459683360839  # ID for the log channel
        self.specific_role_id = (
            1286171116951310407  # ID for the specific role required for access
        )
        self.allowed_servers = [1014562212007915601]  # IDs for the allowed servers
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.jail_role = None
        self.log_channel = None
        self.purged_logs_dir = pathlib.Path(data_manager.cog_data_path(self)) / "purged_logs"
        try:
            self.purged_logs_dir.mkdir(exist_ok=True, parents=True)
        except PermissionError as e:
            print(f"Critical error: Could not create directory {self.purged_logs_dir}: {e}")
            raise

    async def log_action(
        self, user, ctx, reason, jail_timestamp, purged_messages_file=None
    ):
        if not self.log_channel:
            self.log_channel = self.bot.get_channel(self.log_channel_id)

        # More detailed log message
        log_message = (
            f"🔒 User Jailed:\n"
            f"• User: {user.mention} (ID: {user.id})\n"
            f"• Jailed By: {ctx.author.name} (ID: {ctx.author.id})\n"
            f"• Timestamp: {jail_timestamp}\n"
            f"• Reason: {reason}"
        )

        try:
            if purged_messages_file and os.path.getsize(purged_messages_file) > 0:
                with open(purged_messages_file, "rb") as file:
                    await self.log_channel.send(
                        log_message,
                        file=discord.File(
                            file, filename=f"{user.id}_purged_messages.txt"
                        ),
                    )
            else:
                await self.log_channel.send(log_message)
        except Exception as e:
            print(f"Error logging action: {e}")

    @commands.command(name="unjail")
    @commands.max_concurrency(
        5, per=commands.BucketType.guild, wait=True
    )  # Increased concurrency
    async def unjail(
        self, ctx, *users: commands.Greedy[commands.MemberConverter], reason: str
    ):
        # Check if the server is allowed
        if ctx.guild.id not in self.allowed_servers:
            await ctx.send("You do not have permission to use this command.")
            return

        if not reason:
            await ctx.send("Please provide a reason for unjailing.")
            return

        specific_role = get(ctx.guild.roles, id=self.specific_role_id)
        if not (
            ctx.author.guild_permissions.ban_members
            or specific_role in ctx.author.roles
        ):
            await ctx.send("You do not have permission to use this command.")
            return

        if not self.jail_role:
            self.jail_role = get(ctx.guild.roles, id=self.jail_role_id)

        categories_to_purge = {1305688647517077675}  # Using set for faster lookups
        users_to_unjail = users[:20]

        # Batch check for jailed users
        jailed_users = [
            user
            for user in users_to_unjail
            if self.jail_role in user.roles
            or any(role.id == 1280228557318000783 for role in user.roles)
        ]

        if not jailed_users:
            await ctx.send("No specified users are currently jailed.")
            return

        if not self.log_channel:
            self.log_channel = self.bot.get_channel(self.log_channel_id)

        tasks = []
        reply_message = await ctx.send("Releasing user(s)...")
        for user in jailed_users:
            # Remove all roles except the specified role and @everyone
            roles_to_remove = [
                role
                for role in user.roles
                if role.id != 1014566237558284338 and role.id != ctx.guild.id
            ]
            await user.remove_roles(*roles_to_remove)  # Remove other roles
            await user.add_roles(
                get(ctx.guild.roles, id=1014566237558284338)
            )  # Add the specified role
            unjail_timestamp = datetime.now().strftime(
                "<t:%s:F>" % int(datetime.now().timestamp())
            )
            # Log the unjailing
            log_message = (
                f"🔓 User Released:\n"
                f"• User: {user.mention} (ID: {user.id})\n"
                f"• Released by: {ctx.author} (ID: {ctx.author.id})\n"
                f"• Timestamp: {unjail_timestamp}\n"
                f"• Reason for releasing: {reason}"
            )
            await self.log_channel.send(log_message)

            response = f"{user.mention} has been unjailed."
            tasks.append(self.send_temp_message(ctx, response))

        await asyncio.gather(*tasks)
        await ctx.message.delete()  # Delete the author's message
        await reply_message.delete()  # Delete the reply message

    @commands.command(name="jail")
    @commands.max_concurrency(
        5, per=commands.BucketType.guild, wait=True
    )  # Increased concurrency
    async def jail(
        self, ctx, *users: commands.Greedy[commands.MemberConverter], reason: str
    ):
        # Check if the server is allowed
        if ctx.guild.id not in self.allowed_servers:
            await ctx.send("You do not have permission to use this command.")
            return
        if not reason:
            await ctx.send("Please provide a reason for jailing.")
            return

        specific_role = get(ctx.guild.roles, id=self.specific_role_id)
        if not (
            ctx.author.guild_permissions.ban_members
            or specific_role in ctx.author.roles
        ):
            await ctx.send("You do not have permission to use this command.")
            return

        if not self.jail_role:
            self.jail_role = get(ctx.guild.roles, id=self.jail_role_id)

        categories_to_purge = {  # Using set for faster lookups
            1276399856465874974,
            1014562212544774204,
        }
        users_to_jail = users[:20]

        # Batch check for already jailed users
        already_jailed = [
            user
            for user in users_to_jail
            if any(
                role.id in {self.jail_role_id, 1280228557318000783}
                for role in user.roles
            )
        ]

        if len(already_jailed) == len(users_to_jail):
            if not self.log_channel:
                self.log_channel = self.bot.get_channel(self.log_channel_id)

            tasks = []
            for user in already_jailed:
                jail_links = []
                async for message in self.log_channel.history(limit=250):
                    if (
                        f"ID: {user.id}" in message.content
                        and "has been jailed by" in message.content
                    ):
                        jail_links.append(message.jump_url)
                        if len(jail_links) >= 3:  # Early exit once we have 3 links
                            break

                response = f"{user.mention} is already jailed."
                if jail_links:
                    response += "\nPrevious jail logs:" + "\n".join(jail_links)
                tasks.append(self.send_temp_message(ctx, response))

            await asyncio.gather(*tasks)
            await ctx.message.delete()  # Delete the author's message
            return

        reply_message = await ctx.send("Jailing user(s)...")

        async def process_user(user):
            if user not in ctx.guild.members:
                await ctx.send(f"{user.name} is not a member of this guild.")
                return

            if any(
                role.id in {self.jail_role_id, 1280228557318000783}
                for role in user.roles
            ):
                if not self.log_channel:
                    self.log_channel = self.bot.get_channel(self.log_channel_id)

                jail_links = []
                message = await ctx.send("Processing...")

                async for msg in self.log_channel.history(limit=100):
                    if f"ID: {user.id}" in msg.content and "Jailed By:" in msg.content:
                        jail_links.append(msg.jump_url)
                        if len(jail_links) >= 3:
                            break

                response = f"{user.mention} is already jailed."
                if jail_links:
                    response += "\nPrevious jail logs: " + "\n".join(jail_links)
                await message.edit(content=response)
                await asyncio.sleep(10)
                await message.delete()
                return
            # Batch role operations
            roles_to_remove = user.roles[1:]  # More efficient list slicing
            if roles_to_remove:
                await user.remove_roles(*roles_to_remove)
            await user.add_roles(self.jail_role)

            purged_messages_file = (
                self.purged_logs_dir / f"{user.id}_purged_messages.txt"
            )  # Use subdirectory

            def write_messages(messages, file):
                file.writelines(
                    f"[{message.created_at}] {message.author.name}: {message.content}\n"
                    for message in messages
                )

            async def process_channel(channel):
                return await self.purge_with_retry(channel, user)

            try:
                with open(purged_messages_file, "w", buffering=8192, encoding="utf-8") as file:
                    for category_id in categories_to_purge:
                        category = get(ctx.guild.categories, id=category_id)
                        if category:
                            channels_to_process = [
                                channel
                                for channel in category.channels
                                if isinstance(channel, discord.TextChannel)
                            ]
                            threads_to_process = [
                                thread
                                for channel in channels_to_process
                                for thread in channel.threads
                            ]

                            all_messages = await asyncio.gather(
                                *[
                                    process_channel(channel)
                                    for channel in channels_to_process
                                    + threads_to_process
                                ],
                                return_exceptions=True,
                            )

                            # Batch write messages
                            valid_messages = [
                                msg
                                for msg in all_messages
                                if msg and not isinstance(msg, Exception)
                            ]
                            if valid_messages:
                                await self.bot.loop.run_in_executor(
                                    self.thread_pool,
                                    write_messages,
                                    [
                                        m for sublist in valid_messages for m in sublist
                                    ],  # Flatten list
                                    file,
                                )
            except PermissionError as e:
                print(f"Failed to write purged messages: {e}")
                purged_messages_file = None  # Skip file logging

            jail_timestamp = datetime.now().strftime(
                "<t:%s:F>" % int(datetime.now().timestamp())
            )
            if os.path.getsize(purged_messages_file) > 0:
                await self.log_action(
                    user, ctx, reason, jail_timestamp, purged_messages_file
                )
            else:
                await self.log_action(user, ctx, reason, jail_timestamp)

        await asyncio.gather(
            *[
                process_user(user)
                for user in users_to_jail
                if user not in already_jailed
            ]
        )

        if reply_message:
            await reply_message.edit(content="Jailed.")
            await asyncio.sleep(5)
            await reply_message.delete()
        await ctx.message.delete()  # Delete the author's message
    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Only process for specific guild
        if member.guild.id not in self.allowed_servers:
            return

        # Cached role retrieval
        if not self.jail_role:
            self.jail_role = get(member.guild.roles, id=self.jail_role_id)

        # Calculate account age more efficiently
        account_age = datetime.now(member.created_at.tzinfo) - member.created_at

        # More specific spam detection
        if (
            account_age < timedelta(days=90) and len(member.roles) <= 1
        ):  # Additional check for minimal role assignment
            try:
                # Batch role operations
                await member.add_roles(self.jail_role)

                # Logging
                if self.log_channel:
                    jail_timestamp = datetime.now().strftime(
                        "<t:%s:F>" % int(datetime.now().timestamp())
                    )
                    log_message = (
                        f"🚫 Spam Prevention:\n"
                        f"• User: {member.mention} (ID: {member.id})\n"
                        f"• Account Age: {account_age.days} days\n"
                        f"• Jailed at: {jail_timestamp}"
                    )
                    await self.log_channel.send(log_message)

            except discord.Forbidden:
                print(f"Could not process new member {member.id}")
    async def send_temp_message(self, ctx, content, delay=3):
        if ctx.channel:
            message = await ctx.channel.send(content)
            await asyncio.sleep(delay)
            await message.delete()

    async def purge_with_retry(self, channel, user, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                return await channel.purge(limit=100, check=lambda m: m.author == user)
            except commands.errors.CommandOnCooldown:
                await asyncio.sleep(5)
                retries += 1
            except Exception:
                return []
        return []

    async def send_with_retry(self, channel, message, file_path=None, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                if file_path:
                    with open(file_path, "rb") as file:
                        await channel.send(
                            message, file=discord.File(file, filename=file_path)
                        )
                else:
                    await channel.send(message)
                break
            except commands.errors.CommandOnCooldown:
                await asyncio.sleep(5)
                retries += 1
            except Exception:
                break

    async def purge_by_category(self, ctx, category_id: int, user):
        category = get(ctx.guild.categories, id=category_id)
        if category:
            tasks = []
            for channel in category.text_channels:
                tasks.append(self.purge_with_retry(channel, user))
                tasks.extend(
                    self.purge_with_retry(thread, user) for thread in channel.threads
                )
            await asyncio.gather(*tasks)

    async def cleanup_temp_files(self):
        """Remove old purged message files periodically."""
        while True:
            try:
                for filename in os.listdir("."):
                    if filename.endswith("_purged_messages.txt"):
                        file_path = os.path.join(".", filename)
                        # Remove files older than 7 days
                        if (
                            os.path.exists(file_path)
                            and (
                                datetime.now()
                                - datetime.fromtimestamp(os.path.getctime(file_path))
                            ).days
                            > 7
                        ):
                            os.remove(file_path)
            except Exception as e:
                print(f"Error in file cleanup: {e}")

            # Run every 24 hours
            await asyncio.sleep(86400)

    def cog_load(self):
        self.bot.loop.create_task(self.cleanup_temp_files())

    async def safe_remove_roles(self, member, roles_to_remove):
        """Safely remove roles with error handling."""
        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Jail procedure")
        except discord.Forbidden:
            print(f"Could not remove roles from {member.id}")
        except Exception as e:
            print(f"Error removing roles: {e}")

    @commands.command(name="jailcheck")
    @commands.has_permissions(administrator=True)
    async def force_jail_check(self, ctx):
        """Manually trigger the jail role check."""
        await ctx.send("Initiating manual jail role check...")

        try:
            # Run the periodic check for the current guild
            jail_role = ctx.guild.get_role(self.jail_role_id)
            if not jail_role:
                await ctx.send("Jail role not found.")
                return

            log_channel = ctx.guild.get_channel(self.log_channel_id)

            processed_members = 0
            role_removed_count = 0

            for member in jail_role.members:
                try:
                    # Identify roles to remove (excluding jail role and default role)
                    roles_to_remove = [
                        role
                        for role in member.roles
                        if role.id != jail_role.id
                        and role.id != ctx.guild.default_role.id
                    ]

                    if roles_to_remove:
                        # Remove unauthorized roles
                        await member.remove_roles(
                            *roles_to_remove, reason="Manual jail role enforcement"
                        )

                        # Log the action
                        if log_channel:
                            role_names = ", ".join(
                                role.name for role in roles_to_remove
                            )
                            log_message = (
                                f"🔒 Manual Jail Role Enforcement:\n"
                                f"• User: {member.mention} (ID: {member.id})\n"
                                f"• Roles Removed: {role_names}\n"
                                f"• Initiated by: {ctx.author} "
                            )
                            await log_channel.send(log_message)

                        processed_members += 1
                        role_removed_count += len(roles_to_remove)

                except discord.Forbidden:
                    await ctx.send(f"Could not process roles for {member.name}")
                except Exception as e:
                    await ctx.send(f"Error processing {member.name}: {e}")

            # Send summary
            await ctx.send(
                f"Jail role check complete.\n"
                f"Members Processed: {processed_members}\n"
                f"Total Roles Removed: {role_removed_count}"
            )

        except Exception as e:
            await ctx.send(f"An error occurred during the jail role check: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Automatically remove roles when jail role is added."""
        # Validate server
        if after.guild.id not in self.allowed_servers:
            return

        # Get jail role
        jail_role = after.guild.get_role(self.jail_role_id)
        if not jail_role:
            return

        # Check if jail role was just added
        if jail_role in after.roles and jail_role not in before.roles:
            try:
                # Store removed roles for logging
                removed_roles = [
                    role
                    for role in after.roles
                    if role != jail_role and role.id != after.guild.default_role.id
                ]

                if removed_roles:
                    # Remove all roles except jail role
                    await after.remove_roles(*removed_roles, reason="Jail role added")

                    # Get log channel
                    log_channel = after.guild.get_channel(self.log_channel_id)

                    # Log the action
                    if log_channel:
                        role_names = ", ".join(role.name for role in removed_roles)
                        log_message = (
                            f"🔒 Automatic Role Removal:\n"
                            f"• User: {after.mention} (ID: {after.id})\n"
                            f"• Roles Removed: {role_names}\n"
                            f"• Reason: Jail role added"
                        )
                        await log_channel.send(log_message)

            except discord.Forbidden:
                print(f"Could not remove roles from {after.name}")
            except Exception as e:
                print(f"Error in role removal: {e}")


async def setup(bot):
    await bot.add_cog(JailUser(bot))
