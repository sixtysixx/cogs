from redbot.core import (
    commands,
    data_manager,
)  # Imports commands and data_manager from redbot.core for cog functionality
from discord.utils import (
    get,
)  # Imports get from discord.utils for fetching objects like roles and channels
from datetime import (
    datetime,
    timedelta,
)  # Imports datetime and timedelta for time-based operations
import asyncio  # Imports asyncio for asynchronous programming
import os  # Imports os for operating system dependent functionality like file path manipulation
import discord  # Imports discord for Discord API interaction
import concurrent.futures  # Imports concurrent.futures for managing thread pools
import pathlib  # Imports pathlib for object-oriented filesystem paths
import tempfile  # Imports tempfile for creating temporary files


class JailUser(
    commands.Cog
):  # Defines the JailUser class, inheriting from commands.Cog
    def __init__(self, bot):  # Initializes the JailUser cog
        # Initializes the bot instance, jail role ID, log channel ID, and specific role ID for access
        self.bot = bot  # Stores the bot instance
        self.jail_role_id = 1245077976316379187  # ID for the jail role
        self.log_channel_id = 1274393459683360839  # ID for the log channel
        self.specific_role_id = (  # ID for the specific role required for access
            1286171116951310407
        )
        self.allowed_servers = [1014562212007915601]  # IDs for the allowed servers
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=10
        )  # Creates a thread pool for concurrent tasks
        self.jail_role = None  # Initializes jail_role to None, to be fetched later
        self.log_channel = None  # Initializes log_channel to None, to be fetched later
        self.purged_logs_dir = (  # Defines the directory for storing purged message logs
            pathlib.Path(data_manager.cog_data_path(self)) / "purged_logs"
        )
        try:  # Try block to handle potential errors during directory creation

            self.purged_logs_dir.mkdir(
                exist_ok=True, parents=True
            )  # Creates the purged_logs directory if it doesn't exist
        except (
            PermissionError
        ) as e:  # Catches PermissionError if directory creation fails
            print(  # Prints an error message if directory creation fails
                f"Critical error: Could not create directory {self.purged_logs_dir}: {e}"
            )
            raise  # Reraises the exception to halt cog loading if critical

    async def log_action(  # Defines an asynchronous method to log jailing actions
        self,
        user,
        ctx,
        reason,
        jail_timestamp,
        purged_messages_file=None,  # Parameters: user, context, reason, timestamp, and optional purged messages file
    ):
        if not self.log_channel:  # Checks if the log channel is already fetched
            self.log_channel = self.bot.get_channel(
                self.log_channel_id
            )  # Fetches the log channel object using its ID

        # More detailed log message
        log_message = (  # Formats the log message string
            f"🔒 User Jailed:\n"
            f"• User: {user.mention} (ID: {user.id})\n"
            f"• Jailed By: {ctx.author.name} (ID: {ctx.author.id})\n"
            f"• Timestamp: {jail_timestamp}\n"
            f"• Reason: {reason}"
        )

        try:  # Try block to handle potential errors during log sending
            if (
                purged_messages_file and os.path.getsize(purged_messages_file) > 0
            ):  # Checks if a purged messages file exists and is not empty
                with open(
                    purged_messages_file, "rb"
                ) as file:  # Opens the purged messages file in binary read mode
                    await self.log_channel.send(  # Sends the log message with the purged messages file attached
                        log_message,
                        file=discord.File(  # Creates a discord.File object from the purged messages file
                            file, filename=f"{user.id}_purged_messages.txt"
                        ),
                    )
            else:  # If no purged messages file or it's empty
                await self.log_channel.send(
                    log_message
                )  # Sends the log message without any attachment
        except Exception as e:  # Catches any exception during log sending
            print(
                f"Error logging action: {e}"
            )  # Prints an error message if logging fails

    @commands.command(name="unjail")  # Decorator to register the unjail command
    @commands.max_concurrency(  # Decorator to limit command concurrency
        5,
        per=commands.BucketType.guild,
        wait=True,  # Allows 5 concurrent uses per guild, waits if limit is reached
    )
    async def unjail(  # Defines the asynchronous unjail command
        self,
        ctx,
        *users: commands.Greedy[commands.MemberConverter],
        reason: str,  # Parameters: context, a list of users, and a reason string
    ):
        # Check if the server is allowed
        if (
            ctx.guild.id not in self.allowed_servers
        ):  # Checks if the command is used in an allowed server
            await ctx.send(
                "You do not have permission to use this command."
            )  # Sends a permission denial message
            return  # Exits the command

        if not reason:  # Checks if a reason was provided
            await ctx.send(
                "Please provide a reason for unjailing."
            )  # Prompts for a reason if not provided
            return  # Exits the command

        specific_role = get(
            ctx.guild.roles, id=self.specific_role_id
        )  # Fetches the specific role required for command usage
        if not (  # Checks if the author has ban permissions or the specific role
            ctx.author.guild_permissions.ban_members
            or specific_role in ctx.author.roles
        ):
            await ctx.send(
                "You do not have permission to use this command."
            )  # Sends a permission denial message
            return  # Exits the command

        if not self.jail_role:  # Checks if the jail role is already fetched
            self.jail_role = get(
                ctx.guild.roles, id=self.jail_role_id
            )  # Fetches the jail role object using its ID

        # categories_to_purge = {1305688647517077675}  # Using set for faster lookups - This line is commented out, seems unused in unjail
        users_to_unjail = users[:20]  # Limits the number of users to unjail to 20

        # Batch check for jailed users
        jailed_users = [  # Creates a list of users who are actually jailed
            user
            for user in users_to_unjail  # Iterates through the specified users
            if self.jail_role in user.roles  # Checks if the user has the jail role
            or any(
                role.id == 1280228557318000783 for role in user.roles
            )  # Checks for an alternative jail role ID
        ]

        if not jailed_users:  # Checks if any of the specified users are jailed
            await ctx.send(
                "No specified users are currently jailed."
            )  # Sends a message if no users are jailed
            return  # Exits the command

        if not self.log_channel:  # Checks if the log channel is already fetched
            self.log_channel = self.bot.get_channel(
                self.log_channel_id
            )  # Fetches the log channel object

        tasks = []  # Initializes an empty list for asyncio tasks
        reply_message = await ctx.send(
            "Releasing user(s)..."
        )  # Sends an initial processing message
        for user in jailed_users:  # Iterates through the users to be unjailed
            # Remove all roles except the specified role and @everyone
            roles_to_remove = [  # Creates a list of roles to remove from the user
                role
                for role in user.roles  # Iterates through the user's current roles
                if role.id != 1014566237558284338
                and role.id != ctx.guild.id  # Keeps a specific role and @everyone role
            ]
            await user.remove_roles(*roles_to_remove)  # Removes the identified roles
            await user.add_roles(  # Adds a specific role back to the user (likely a default member role)
                get(ctx.guild.roles, id=1014566237558284338)
            )
            unjail_timestamp = datetime.now().strftime(  # Gets the current timestamp formatted for Discord
                "<t:%s:F>" % int(datetime.now().timestamp())
            )
            # Log the unjailing
            log_message = (  # Formats the log message for unjailing
                f"🔓 User Released:\n"
                f"• User: {user.mention} (ID: {user.id})\n"
                f"• Released by: {ctx.author} (ID: {ctx.author.id})\n"
                f"• Timestamp: {unjail_timestamp}\n"
                f"• Reason for releasing: {reason}"
            )
            await self.log_channel.send(log_message)  # Sends the unjail log message

            response = f"{user.mention} has been unjailed."  # Creates a response message for the user
            tasks.append(
                self.send_temp_message(ctx, response)
            )  # Adds sending a temporary message to the task list

        await asyncio.gather(
            *tasks
        )  # Executes all temporary message sending tasks concurrently
        await ctx.message.delete()  # Deletes the author's command message
        await reply_message.delete()  # Deletes the initial "Releasing user(s)..." message

    @commands.command(name="jail")  # Decorator to register the jail command
    @commands.max_concurrency(  # Decorator to limit command concurrency
        5,
        per=commands.BucketType.guild,
        wait=True,  # Allows 5 concurrent uses per guild, waits if limit is reached
    )
    async def jail(  # Defines the asynchronous jail command
        self,
        ctx,
        *users: commands.Greedy[commands.MemberConverter],
        reason: str,  # Parameters: context, a list of users, and a reason string
    ):
        # Check if the server is allowed
        if (
            ctx.guild.id not in self.allowed_servers
        ):  # Checks if the command is used in an allowed server
            await ctx.send(
                "You do not have permission to use this command."
            )  # Sends a permission denial message
            return  # Exits the command
        if not reason:  # Checks if a reason was provided
            await ctx.send(
                "Please provide a reason for jailing."
            )  # Prompts for a reason if not provided
            return  # Exits the command

        specific_role = get(
            ctx.guild.roles, id=self.specific_role_id
        )  # Fetches the specific role required for command usage
        if not (  # Checks if the author has ban permissions or the specific role
            ctx.author.guild_permissions.ban_members
            or specific_role in ctx.author.roles
        ):
            await ctx.send(
                "You do not have permission to use this command."
            )  # Sends a permission denial message
            return  # Exits the command

        if not self.jail_role:  # Checks if the jail role is already fetched
            self.jail_role = get(
                ctx.guild.roles, id=self.jail_role_id
            )  # Fetches the jail role object using its ID

        categories_to_purge = {  # Defines a set of category IDs for message purging
            1276399856465874974,
            1014562212544774204,
        }
        users_to_jail = users[:20]  # Limits the number of users to jail to 20

        # Batch check for already jailed users
        already_jailed = [  # Creates a list of users who are already jailed
            user
            for user in users_to_jail  # Iterates through the specified users
            if any(  # Checks if the user has the jail role or an alternative jail role
                role.id in {self.jail_role_id, 1280228557318000783}
                for role in user.roles
            )
        ]

        if len(already_jailed) == len(
            users_to_jail
        ):  # Checks if all specified users are already jailed
            if not self.log_channel:  # Checks if the log channel is already fetched
                self.log_channel = self.bot.get_channel(
                    self.log_channel_id
                )  # Fetches the log channel object

            tasks = []  # Initializes an empty list for asyncio tasks
            for user in already_jailed:  # Iterates through the already jailed users
                jail_links = (
                    []
                )  # Initializes a list to store links to previous jail logs
                async for message in self.log_channel.history(
                    limit=250
                ):  # Iterates through the log channel history
                    if (  # Checks if the log message pertains to the current user being jailed
                        f"ID: {user.id}" in message.content
                        and "has been jailed by"
                        in message.content  # A more specific check might be "Jailed By:" as in log_action
                    ):
                        jail_links.append(
                            message.jump_url
                        )  # Adds the message link to the list
                        if len(jail_links) >= 3:  # Early exit once we have 3 links
                            break  # Stops searching for more links

                response = (
                    f"{user.mention} is already jailed."  # Creates a response message
                )
                if jail_links:  # Checks if any previous jail logs were found
                    response += "\nPrevious jail logs:" + "\n".join(
                        jail_links
                    )  # Appends the jail log links to the response
                tasks.append(
                    self.send_temp_message(ctx, response)
                )  # Adds sending a temporary message to the task list

            await asyncio.gather(
                *tasks
            )  # Executes all temporary message sending tasks concurrently
            await ctx.message.delete()  # Deletes the author's command message
            return  # Exits the command

        reply_message = await ctx.send(
            "Jailing user(s)..."
        )  # Sends an initial processing message

        async def process_user(
            user,
        ):  # Defines an asynchronous helper function to process each user for jailing
            if (
                user not in ctx.guild.members
            ):  # Checks if the user is a member of the current guild
                await ctx.send(
                    f"{user.name} is not a member of this guild."
                )  # Sends a message if the user is not a member
                return  # Exits the helper function

            if any(  # Checks if the user is already jailed (redundant check, but good for safety within the async task)
                role.id in {self.jail_role_id, 1280228557318000783}
                for role in user.roles
            ):
                if not self.log_channel:  # Checks if the log channel is already fetched
                    self.log_channel = self.bot.get_channel(
                        self.log_channel_id
                    )  # Fetches the log channel object

                jail_links = (
                    []
                )  # Initializes a list to store links to previous jail logs
                message = await ctx.send(
                    "Processing..."
                )  # Sends a temporary processing message

                async for msg in self.log_channel.history(
                    limit=100
                ):  # Iterates through the log channel history
                    if (
                        f"ID: {user.id}" in msg.content and "Jailed By:" in msg.content
                    ):  # Checks for previous jail logs for this user
                        jail_links.append(msg.jump_url)  # Adds the message link
                        if len(jail_links) >= 3:  # Stops after finding 3 links
                            break  # Exits the loop

                response = (
                    f"{user.mention} is already jailed."  # Creates the response message
                )
                if jail_links:  # Checks if previous jail logs were found
                    response += "\nPrevious jail logs: " + "\n".join(
                        jail_links
                    )  # Appends the links
                await message.edit(
                    content=response
                )  # Edits the temporary message to show the result
                await asyncio.sleep(10)  # Waits for 10 seconds
                await message.delete()  # Deletes the temporary message
                return  # Exits the helper function
            # Batch role operations
            roles_to_remove = user.roles[
                1:
            ]  # Creates a list of all roles except the @everyone role (index 0)
            if roles_to_remove:  # Checks if there are roles to remove
                await user.remove_roles(
                    *roles_to_remove
                )  # Removes all roles from the user
            await user.add_roles(self.jail_role)  # Adds the jail role to the user

            purged_messages_file = (  # Defines the path for the purged messages log file
                self.purged_logs_dir / f"{user.id}_purged_messages.txt"
            )

            def write_messages(
                messages, file
            ):  # Defines a synchronous helper function to write messages to a file
                file.writelines(  # Writes each message to the file
                    f"[{message.created_at}] {message.author.name}: {message.content}\n"
                    for message in messages
                )

            async def process_channel(
                channel,
            ):  # Defines an asynchronous helper function to process messages from a channel
                return await self.purge_with_retry(
                    channel, user
                )  # Calls purge_with_retry for the channel and user

            try:  # Try block to handle potential errors during file operations and message processing
                with open(  # Opens the purged messages log file
                    purged_messages_file,
                    "w",
                    buffering=8192,
                    encoding="utf-8",  # Opens in write mode with buffering and UTF-8 encoding
                ) as file:
                    for (
                        category_id
                    ) in (
                        categories_to_purge
                    ):  # Iterates through the categories to process messages from
                        category = get(
                            ctx.guild.categories, id=category_id
                        )  # Fetches the category object
                        if category:  # Checks if the category exists
                            channels_to_process = (
                                [  # Creates a list of text channels in the category
                                    channel
                                    for channel in category.channels
                                    if isinstance(channel, discord.TextChannel)
                                ]
                            )
                            threads_to_process = (
                                [  # Creates a list of threads in those text channels
                                    thread
                                    for channel in channels_to_process
                                    for thread in channel.threads
                                ]
                                # Filter out threads that are archived or locked if necessary
                                # if not thread.archived and not thread.locked
                            )

                            all_messages = await asyncio.gather(  # Gathers results from processing all channels and threads concurrently
                                *[
                                    process_channel(
                                        channel
                                    )  # Creates a task for each channel
                                    for channel in channels_to_process  # Adds text channels
                                    + threads_to_process  # Adds threads
                                ],
                                return_exceptions=True,  # Returns exceptions instead of raising them immediately
                            )

                            # Batch write messages
                            valid_messages = [  # Filters out None or Exception results from processing
                                msg
                                for msg in all_messages
                                if msg and not isinstance(msg, Exception)
                            ]
                            if (
                                valid_messages
                            ):  # Checks if any messages were successfully processed
                                await self.bot.loop.run_in_executor(  # Runs the synchronous file writing in the thread pool
                                    self.thread_pool,
                                    write_messages,
                                    [  # Flattens the list of lists of messages
                                        m for sublist in valid_messages for m in sublist
                                    ],
                                    file,  # Passes the file object to write_messages
                                )
            except (
                PermissionError
            ) as e:  # Catches PermissionError during file operations
                print(
                    f"Failed to write purged messages: {e}"
                )  # Prints an error message
                purged_messages_file = None  # Sets file to None to skip logging it

            jail_timestamp = datetime.now().strftime(  # Gets the current timestamp formatted for Discord
                "<t:%s:F>" % int(datetime.now().timestamp())
            )
            if (
                purged_messages_file and os.path.getsize(purged_messages_file) > 0
            ):  # Checks if the purged messages file exists and is not empty
                await self.log_action(  # Logs the jailing action with the purged messages file
                    user, ctx, reason, jail_timestamp, purged_messages_file
                )
            else:  # If no purged messages file or it's empty
                await self.log_action(
                    user, ctx, reason, jail_timestamp
                )  # Logs the jailing action without the file

        await asyncio.gather(  # Gathers results from processing all users to be jailed concurrently
            *[
                process_user(user)  # Creates a task for each user
                for user in users_to_jail  # Iterates through users to jail
                if user not in already_jailed  # Skips users who are already jailed
            ]
        )

        if reply_message:  # Checks if the initial "Jailing user(s)..." message exists
            await reply_message.edit(
                content="Jailed."
            )  # Edits the message to "Jailed."
            await asyncio.sleep(5)  # Waits for 5 seconds
            await reply_message.delete()  # Deletes the message
        await ctx.message.delete()  # Deletes the author's command message

    @commands.Cog.listener()  # Decorator to register an event listener
    async def on_member_join(
        self, member
    ):  # Defines an asynchronous event handler for member join
        # Only process for specific guild
        if (
            member.guild.id not in self.allowed_servers
        ):  # Checks if the member joined an allowed server
            return  # Exits if not an allowed server

        # Cached role retrieval
        if (
            not self.jail_role
        ):  # Checks if the jail role is already fetched for this guild (could be problematic if bot is in multiple allowed guilds)
            # It's better to fetch guild-specific role here or ensure self.jail_role is a dict mapping guild_id to role
            self.jail_role = get(
                member.guild.roles, id=self.jail_role_id
            )  # Fetches the jail role for the member's guild

        if (
            not self.jail_role
        ):  # If jail role still not found (e.g., wrong ID or not set up in that guild)
            print(
                f"Jail role not found in guild {member.guild.id} for on_member_join."
            )  # Logs an error
            return  # Exits

        # Calculate account age more efficiently
        account_age = (
            datetime.now(member.created_at.tzinfo) - member.created_at
        )  # Calculates the age of the member's account

        # More specific spam detection
        if (  # Checks if the account is younger than 90 days and has 1 or fewer roles (i.e., only @everyone)
            account_age < timedelta(days=90) and len(member.roles) <= 1
        ):
            try:  # Try block to handle potential errors during role assignment and logging
                # Batch role operations
                await member.add_roles(
                    self.jail_role
                )  # Adds the jail role to the new member

                # Logging
                if not self.log_channel:  # Checks if the log channel is already fetched
                    self.log_channel = self.bot.get_channel(
                        self.log_channel_id
                    )  # Fetches the log channel (assumes one log channel for all guilds)

                if (
                    self.log_channel
                ):  # Checks if the log channel was successfully fetched
                    jail_timestamp = datetime.now().strftime(  # Gets the current timestamp formatted for Discord
                        "<t:%s:F>" % int(datetime.now().timestamp())
                    )
                    log_message = (  # Formats the log message for auto-jailing
                        f"🚫 Spam Prevention:\n"
                        f"• User: {member.mention} (ID: {member.id})\n"
                        f"• Account Age: {account_age.days} days\n"
                        f"• Jailed at: {jail_timestamp}"
                    )
                    await self.log_channel.send(
                        log_message
                    )  # Sends the auto-jail log message

            except (
                discord.Forbidden
            ):  # Catches Forbidden error if bot lacks permissions
                print(
                    f"Could not process new member {member.id} due to permissions."
                )  # Prints a permission error message
            except Exception as e:  # Catches any other exception
                print(
                    f"Error processing new member {member.id}: {e}"
                )  # Prints a generic error message

    async def send_temp_message(
        self, ctx, content, delay=3
    ):  # Defines an asynchronous helper to send a temporary message
        if ctx.channel:  # Checks if the context has a valid channel
            message = await ctx.channel.send(content)  # Sends the message
            await asyncio.sleep(delay)  # Waits for the specified delay
            await message.delete()  # Deletes the message

    async def purge_with_retry(
        self, channel, user, max_retries=3
    ):  # Defines an asynchronous helper to purge messages with retries
        retries = 0  # Initializes retry counter
        while retries < max_retries:  # Loops until max retries are reached
            try:  # Try block for purging messages
                return await channel.purge(
                    limit=100, check=lambda m: m.author == user
                )  # Purges messages by the specified user
            except (
                commands.errors.CommandOnCooldown
            ):  # Catches CommandOnCooldown error (though purge isn't a command here, this might be for a custom rate limit)
                # discord.py's channel.purge can hit rate limits, but doesn't throw CommandOnCooldown.
                # It throws discord.HTTPException with status 429.
                # This suggests a custom rate limiting mechanism or a misunderstanding of the exception.
                await asyncio.sleep(5)  # Waits for 5 seconds before retrying
                retries += 1  # Increments retry counter
            except (
                discord.HTTPException
            ) as e:  # Catches HTTPException, which includes rate limits (429)
                if e.status == 429:  # Specifically checks for rate limit error
                    retry_after = (
                        e.retry_after if hasattr(e, "retry_after") else 5
                    )  # Gets retry_after value or defaults to 5
                    print(
                        f"Purge rate limited. Retrying after {retry_after}s..."
                    )  # Logs rate limit
                    await asyncio.sleep(retry_after)  # Waits for the specified duration
                    retries += 1  # Increments retry counter
                else:  # For other HTTPExceptions
                    print(f"HTTPException during purge: {e}")  # Logs the error
                    return []  # Returns an empty list on other HTTP errors
            except Exception as e:  # Catches any other exception during purge
                print(f"Generic exception during purge: {e}")  # Logs the error
                return []  # Returns an empty list on error
        return []  # Returns an empty list if all retries fail

    async def send_with_retry(
        self, channel, message, file_path=None, max_retries=3
    ):  # Defines an asynchronous helper to send messages with retries
        retries = 0  # Initializes retry counter
        while retries < max_retries:  # Loops until max retries are reached
            try:  # Try block for sending message
                if file_path:  # Checks if a file path is provided
                    with open(
                        file_path, "rb"
                    ) as file:  # Opens the file in binary read mode
                        await channel.send(  # Sends the message with the file attached
                            message,
                            file=discord.File(
                                file, filename=os.path.basename(file_path)
                            ),  # Uses os.path.basename for filename
                        )
                else:  # If no file path is provided
                    await channel.send(message)  # Sends the message without attachment
                break  # Exits loop on successful send
            except (
                commands.errors.CommandOnCooldown
            ):  # Catches CommandOnCooldown (again, likely for custom rate limits or misunderstanding)
                # discord.py's send can hit rate limits, throwing discord.HTTPException (429).
                await asyncio.sleep(5)  # Waits for 5 seconds
                retries += 1  # Increments retry counter
            except discord.HTTPException as e:  # Catches HTTPException
                if e.status == 429:  # Checks for rate limit
                    retry_after = (
                        e.retry_after if hasattr(e, "retry_after") else 5
                    )  # Gets retry_after or defaults to 5
                    print(
                        f"Send rate limited. Retrying after {retry_after}s..."
                    )  # Logs rate limit
                    await asyncio.sleep(retry_after)  # Waits
                    retries += 1  # Increments retry counter
                else:  # For other HTTPExceptions
                    print(f"HTTPException during send: {e}")  # Logs error
                    break  # Exits loop on other HTTP errors
            except Exception as e:  # Catches any other exception
                print(f"Generic exception during send: {e}")  # Logs error
                break  # Exits loop on error

    async def purge_by_category(
        self, ctx, category_id: int, user
    ):  # Defines an asynchronous helper to purge messages by category (unused in current commands)
        category = get(
            ctx.guild.categories, id=category_id
        )  # Fetches the category object
        if category:  # Checks if the category exists
            tasks = []  # Initializes an empty list for asyncio tasks
            for (
                channel
            ) in (
                category.text_channels
            ):  # Iterates through text channels in the category
                tasks.append(
                    self.purge_with_retry(channel, user)
                )  # Adds purging the channel to tasks
                tasks.extend(  # Adds purging all threads in the channel to tasks
                    self.purge_with_retry(thread, user) for thread in channel.threads
                )
            await asyncio.gather(*tasks)  # Executes all purge tasks concurrently

    async def cleanup_temp_files(
        self,
    ):  # Defines an asynchronous task to clean up old purged message files
        """Remove old purged message files periodically."""
        while True:  # Infinite loop for periodic cleanup
            try:  # Try block for file operations
                # Iterate over files in the designated purged_logs_dir
                for filename in os.listdir(
                    self.purged_logs_dir
                ):  # Lists files in the purged_logs_dir
                    if filename.endswith(
                        "_purged_messages.txt"
                    ):  # Checks if the file is a purged messages log
                        file_path = (
                            self.purged_logs_dir / filename
                        )  # Creates a Path object for the file
                        # Remove files older than 7 days
                        if (  # Checks if the file exists and is older than 7 days
                            os.path.exists(
                                file_path
                            )  # Redundant check as os.listdir implies existence, but safe
                            and (
                                datetime.now()
                                - datetime.fromtimestamp(
                                    os.path.getctime(file_path)
                                )  # Calculates file age
                            ).days
                            > 7
                        ):
                            os.remove(file_path)  # Removes the old file
                            print(
                                f"Cleaned up old log file: {file_path}"
                            )  # Logs cleanup action
            except Exception as e:  # Catches any exception during cleanup
                print(f"Error in file cleanup: {e}")  # Prints an error message

            # Run every 24 hours
            await asyncio.sleep(86400)  # Waits for 24 hours (86400 seconds)

    def cog_load(self):  # Method called when the cog is loaded
        self.bot.loop.create_task(
            self.cleanup_temp_files()
        )  # Starts the cleanup_temp_files task in the bot's event loop

    async def safe_remove_roles(
        self, member, roles_to_remove
    ):  # Defines an asynchronous helper for safely removing roles (unused in current commands)
        """Safely remove roles with error handling."""
        try:  # Try block for role removal
            if roles_to_remove:  # Checks if there are roles to remove
                await member.remove_roles(
                    *roles_to_remove, reason="Jail procedure"
                )  # Removes roles with a reason
        except discord.Forbidden:  # Catches Forbidden error
            print(
                f"Could not remove roles from {member.id} due to permissions."
            )  # Prints permission error
        except Exception as e:  # Catches any other exception
            print(f"Error removing roles from {member.id}: {e}")  # Prints generic error

    @commands.command(name="jailcheck")  # Decorator to register the jailcheck command
    @commands.has_guild_permissions(
        manage_roles=True
    )  # Permissions check: user must have "Manage Roles" permission
    async def force_jail_check(self, ctx):  # Defines the asynchronous jailcheck command
        """Manually trigger the jail role check."""
        initial_message = await ctx.send(
            "Initiating manual jail role check..."
        )  # Sends an initial processing message

        try:  # Try block for the main logic of the command
            # Run the periodic check for the current guild
            guild_jail_role = ctx.guild.get_role(
                self.jail_role_id
            )  # Fetches the jail role for the current guild
            if not guild_jail_role:  # Checks if the jail role was found
                await initial_message.edit(
                    content="Jail role not found in this server."
                )  # Edits the initial message
                await asyncio.sleep(5)  # Waits for 5 seconds
                await initial_message.delete()  # Deletes the message
                await ctx.message.delete()  # Deletes the command invocation message
                return  # Exits the command

            # Fetch log channel for this specific guild context if needed, or use the global one if appropriate
            # For now, using the globally configured log_channel_id
            log_channel_instance = self.bot.get_channel(
                self.log_channel_id
            )  # Fetches the log channel
            if (
                log_channel_instance and log_channel_instance.guild != ctx.guild
            ):  # Checks if log channel is in a different guild
                # This implies a single log channel for multiple guilds, which might be intended or an oversight.
                # If guild-specific log channels are desired, this logic needs adjustment.
                log_channel_instance = None  # Disables logging if log channel is not in the current guild (safer)
                print(
                    f"Log channel {self.log_channel_id} is not in guild {ctx.guild.name}. Logging for jailcheck disabled for this guild."
                )

            processed_members = 0  # Initializes counter for processed members
            role_removed_count = 0  # Initializes counter for removed roles

            for (
                member
            ) in (
                guild_jail_role.members
            ):  # Iterates through all members who have the jail role
                try:  # Try block for processing each member
                    # Identify roles to remove (excluding jail role and default role)
                    roles_to_remove = [  # Creates a list of roles to remove
                        role
                        for role in member.roles  # Iterates through the member's current roles
                        if role.id
                        != guild_jail_role.id  # Excludes the jail role itself
                        and role.id
                        != ctx.guild.default_role.id  # Excludes the @everyone role
                    ]

                    if (
                        roles_to_remove
                    ):  # Checks if there are any unauthorized roles to remove
                        # Remove unauthorized roles
                        await member.remove_roles(  # Removes the roles
                            *roles_to_remove,
                            reason="Manual jail role enforcement",  # Specifies a reason for the audit log
                        )

                        # Log the action
                        if (
                            log_channel_instance
                        ):  # Checks if a valid log channel is available for this guild
                            role_names = ", ".join(  # Creates a comma-separated string of removed role names
                                role.name for role in roles_to_remove
                            )
                            log_message = (  # Formats the log message
                                f"🔒 Manual Jail Role Enforcement:\n"
                                f"• User: {member.mention} (ID: {member.id})\n"
                                f"• Roles Removed: {role_names}\n"
                                f"• Initiated by: {ctx.author.name} (ID: {ctx.author.id})"
                            )
                            await log_channel_instance.send(
                                log_message
                            )  # Sends the log message

                        processed_members += 1  # Increments processed members counter
                        role_removed_count += len(
                            roles_to_remove
                        )  # Adds the number of removed roles to the total

                except (
                    discord.Forbidden
                ):  # Catches Forbidden error if bot lacks permissions for a specific member
                    # Cannot send message here as it might spam, log to console instead
                    print(
                        f"Could not process roles for {member.name} ({member.id}) in {ctx.guild.name} due to permissions."
                    )
                except (
                    Exception
                ) as e:  # Catches any other exception during member processing
                    # Cannot send message here as it might spam, log to console instead
                    print(
                        f"Error processing {member.name} ({member.id}) in {ctx.guild.name} during jailcheck: {e}"
                    )

            # Send summary
            summary_message_content = (  # Formats the summary message content
                f"Jail role check complete.\n"
                f"Members Processed: {processed_members}\n"
                f"Total Roles Removed: {role_removed_count}"
            )
            await initial_message.edit(
                content=summary_message_content
            )  # Edits the initial message to show the summary
            await asyncio.sleep(10)  # Waits for 10 seconds
            await initial_message.delete()  # Deletes the summary message

        except (
            Exception
        ) as e:  # Catches any exception in the main try block of the command
            error_message_content = f"An error occurred during the jail role check: {e}"  # Formats error message
            try:  # Try to edit the initial message to show the error
                await initial_message.edit(content=error_message_content)
                await asyncio.sleep(10)  # Waits
                await initial_message.delete()  # Deletes
            except (
                discord.NotFound
            ):  # If initial_message was already deleted or not found
                pass  # Do nothing
            except Exception as edit_e:  # Catch other errors during edit
                print(
                    f"Failed to edit jailcheck initial message with error: {edit_e}"
                )  # Log this error
            print(
                f"Jailcheck command error in {ctx.guild.name}: {e}"
            )  # Prints the main error to console

        finally:  # Finally block to ensure command message deletion
            try:  # Try to delete the original command invocation message
                await ctx.message.delete()
            except discord.NotFound:  # If message already deleted
                pass  # Do nothing
            except Exception as del_e:  # Catch other errors during delete
                print(
                    f"Failed to delete jailcheck invocation message: {del_e}"
                )  # Log this error

    @commands.Cog.listener()  # Decorator to register an event listener
    async def on_member_update(
        self, before, after
    ):  # Defines an asynchronous event handler for member updates
        """Automatically remove roles when jail role is added."""
        # Validate server
        if (
            after.guild.id not in self.allowed_servers
        ):  # Checks if the update occurred in an allowed server
            return  # Exits if not an allowed server

        # Get jail role
        # It's better to fetch guild-specific role here
        guild_jail_role = after.guild.get_role(
            self.jail_role_id
        )  # Fetches the jail role for the member's guild
        if not guild_jail_role:  # Checks if the jail role was found
            # Log if jail role isn't found in a server it's supposed to be in.
            # print(f"Jail role ID {self.jail_role_id} not found in guild {after.guild.name} for on_member_update.")
            return  # Exits if jail role not found

        # Check if jail role was just added
        if (
            guild_jail_role in after.roles and guild_jail_role not in before.roles
        ):  # Checks if the jail role was newly added
            try:  # Try block for role removal and logging
                # Store removed roles for logging
                roles_to_remove = [  # Creates a list of roles to remove
                    role
                    for role in after.roles  # Iterates through the member's current roles (after update)
                    if role != guild_jail_role
                    and role.id
                    != after.guild.default_role.id  # Excludes jail role and @everyone
                ]

                if roles_to_remove:  # Checks if there are roles to remove
                    # Remove all roles except jail role
                    await after.remove_roles(
                        *roles_to_remove, reason="Jail role added automatically"
                    )  # Removes roles with a reason

                    # Get log channel
                    # Similar to jailcheck, ensure log_channel is appropriate for the guild or handle guild-specific logging
                    log_channel_instance = self.bot.get_channel(
                        self.log_channel_id
                    )  # Fetches the log channel
                    if (
                        log_channel_instance
                        and log_channel_instance.guild != after.guild
                    ):  # Checks if log channel is in a different guild
                        log_channel_instance = None  # Disables logging if log channel is not in the current guild
                        # print(f"Log channel {self.log_channel_id} not in guild {after.guild.name}. Logging for on_member_update disabled.")

                    # Log the action
                    if (
                        log_channel_instance
                    ):  # Checks if a valid log channel is available
                        role_names = ", ".join(
                            role.name for role in roles_to_remove
                        )  # Creates string of removed role names
                        log_message = (  # Formats the log message
                            f"🔒 Automatic Role Removal:\n"
                            f"• User: {after.mention} (ID: {after.id})\n"
                            f"• Roles Removed: {role_names}\n"
                            f"• Reason: Jail role added"
                        )
                        await log_channel_instance.send(
                            log_message
                        )  # Sends the log message

            except discord.Forbidden:  # Catches Forbidden error
                print(
                    f"Could not remove roles from {after.name} ({after.id}) in {after.guild.name} (on_member_update) due to permissions."
                )  # Prints permission error
            except Exception as e:  # Catches any other exception
                print(
                    f"Error in role removal for {after.name} ({after.id}) in {after.guild.name} (on_member_update): {e}"
                )  # Prints generic error

    @commands.command(
        name="scanprofiles"
    )  # Decorator to register the scanprofiles command
    @commands.has_guild_permissions(
        manage_roles=True
    )  # Permissions check: user must have "Manage Roles" permission
    async def scan_profiles(
        self, ctx
    ):  # Defines the asynchronous scan_profiles command
        """Scans user profiles (usernames/nicknames, bio, pronouns) for suspicious keywords."""
        # Check if the server is allowed
        if (
            ctx.guild.id not in self.allowed_servers
        ):  # Checks if the command is used in an allowed server
            await ctx.send(
                "You do not have permission to use this command."
            )  # Sends a permission denial message
            return  # Exits the command

        # Define the lists of suspicious keywords
        suspicious_username_keywords = [
            "CRYPTO",
            "ECOM",
            "SHOPIFY",
            "NFT",
            "INVEST",
            "TRADING",
            "PAYMENT",
            "BITCOIN",
            "FREE",
            "BTC",
            "SCAM",
            "HACK",
            "SPAM",
        ]  # Keywords likely found in usernames/nicknames

        suspicious_bio_pronouns_keywords = [
            "FREELANCE",
            "WORK FROM HOME",
            "EARN MONEY",
            "MAKE MONEY",
            "GET RICH",
            "QUICK CASH",
            "ONLINE JOB",
            "ONLINE BUSINESS",
            "ONLINE EARNING",
            "ONLINE INCOME",
            "ONLINE INVESTMENT",
            "DM",
            "CRYPTO",
            "NFT",
            "INVEST",
            "TRADING",
            "BITCOIN",
            "BTC",
            "PROFESSIONAL",
            "FREELANCER",
            "FREELANCING",
            "EXPERT",
            "DISCORD",
            "SERVER",
            "DROPSHIPPING",
            "E-COMMERCE",
            "E-COM",
            "SHOPIFY",
            "ECOMMERCE",
            "SEO",
            "MARKETING",
            "BUSINESS",
        ]  # Keywords likely found in bios/pronouns

        initial_message = await ctx.send(
            "Scanning user profiles for suspicious keywords..."
        )  # Sends an initial processing message

        found_users_data = (
            []
        )  # Initializes a list to store data for users found with keywords

        # Fetch the jail role for exclusion
        guild_jail_role = ctx.guild.get_role(
            self.jail_role_id
        )  # Fetches the jail role for the current guild

        # Iterate through all members in the guild
        async for member in ctx.guild.fetch_members(
            limit=None
        ):  # Asynchronously fetches all members in the guild
            # Exclude members with the jail role
            if (
                guild_jail_role and guild_jail_role in member.roles
            ):  # Checks if the jail role exists and the member has it
                continue  # Skips this member if they have the jail role

            found_username_keywords = []
            found_bio_pronouns_keywords = []

            # Check username and nickname for keywords
            username_text = member.name.lower()
            if member.nick:
                username_text += f" {member.nick.lower()}"

            found_username_keywords = [
                keyword
                for keyword in suspicious_username_keywords
                if keyword.lower() in username_text
            ]

            # Fetch user profile for bio and pronouns
            user_profile = None
            try:
                user_profile = await self.bot.bot.fetch_user_profile(member.id)
            except discord.NotFound:
                # User profile not found, skip bio/pronouns check
                pass
            except Exception as e:
                print(f"Error fetching user profile for {member.id}: {e}")
                # Continue without bio/pronouns if fetching fails

            # Check bio and pronouns for keywords
            bio_pronouns_text = ""
            if user_profile and user_profile.bio:
                bio_pronouns_text += f" {user_profile.bio.lower()}"
            if user_profile and user_profile.pronouns:
                bio_pronouns_text += f" {user_profile.pronouns.lower()}"

            found_bio_pronouns_keywords = [
                keyword
                for keyword in suspicious_bio_pronouns_keywords
                if keyword.lower() in bio_pronouns_text
            ]

            # Combine found keywords, removing duplicates
            all_found_keywords = list(
                set(found_username_keywords + found_bio_pronouns_keywords)
            )

            if all_found_keywords:  # Checks if any keywords were found for this user
                found_users_data.append(  # Appends the user and found keywords to the list
                    {"user": member, "keywords": all_found_keywords}
                )

        # Report findings
        if found_users_data:  # Checks if any users were found with keywords
            report_content = "Found users with suspicious keywords in their profile:\n"  # Starts building the report content string
            for entry in found_users_data:  # Iterates through the found users data
                user = entry["user"]  # Gets the user object
                keywords = entry["keywords"]  # Gets the list of keywords
                report_content += f"• {user.name} (ID: {user.id}): {', '.join(keywords)}\n"  # Adds each user and their found keywords to the content

            # Create a temporary file to store the report
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, encoding="utf-8", suffix=".txt"
            ) as tmp_file:  # Creates a temporary file
                tmp_file.write(
                    report_content
                )  # Writes the report content to the temporary file
                tmp_file_path = tmp_file.name  # Gets the path of the temporary file

            try:  # Try block to send the file
                # Send the report as a file to the log channel if available, otherwise send to the command context
                log_channel_instance = self.bot.get_channel(
                    self.log_channel_id
                )  # Fetches the log channel
                target_channel = (
                    log_channel_instance
                    if log_channel_instance and log_channel_instance.guild == ctx.guild
                    else ctx.channel
                )  # Determines the target channel

                await target_channel.send(  # Sends the message to the target channel
                    f"Scan complete. Found {len(found_users_data)} user(s) with suspicious keywords. Report attached.",  # Message content
                    file=discord.File(
                        tmp_file_path, filename="suspicious_profiles_report.txt"
                    ),  # Attaches the temporary file
                )
                await initial_message.delete()  # Deletes the initial processing message

            except Exception as e:  # Catches any exception during file sending
                print(f"Error sending scan report file: {e}")  # Prints an error message
                # Fallback to sending content directly if file sending fails (might still hit character limit)
                try:  # Try to send the content directly
                    await initial_message.edit(
                        content=report_content
                    )  # Edits the initial message with the report content
                    await asyncio.sleep(10)  # Waits
                    await initial_message.delete()  # Deletes
                except Exception as edit_e:  # Catch errors during edit/delete
                    print(
                        f"Failed to edit/delete initial message after file send failure: {edit_e}"
                    )  # Log this error

            finally:  # Finally block to ensure temporary file cleanup
                if os.path.exists(
                    tmp_file_path
                ):  # Checks if the temporary file still exists
                    os.remove(tmp_file_path)  # Removes the temporary file

        else:  # If no users were found with keywords
            await initial_message.edit(
                content="Scan complete. No users found with suspicious keywords."
            )  # Edits the initial message
            await asyncio.sleep(5)  # Waits for 5 seconds
            await initial_message.delete()  # Deletes the initial message

        await ctx.message.delete()  # Deletes the command invocation message


async def setup(bot):  # Defines the asynchronous setup function for the cog":
    await bot.add_cog(JailUser(bot))  # Adds an instance of the JailUser cog to the bot
