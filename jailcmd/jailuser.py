import os
import logging
import asyncio
import concurrent.futures
import pathlib
import tempfile
from datetime import datetime, timedelta
from typing import List, Optional, Set, Dict, Any
from dataclasses import dataclass, field

import discord
from redbot.core import commands, data_manager
from discord.utils import get

# Configure logging for the cog using RedBot's standard logging setup
log = logging.getLogger("red.jailuser")

# Define constants for better readability and maintainability
DEFAULT_JAIL_ROLE_ID: int = 1245077976316379187  # Default ID for the jail role
DEFAULT_LOG_CHANNEL_ID: int = 1274393459683360839  # Default ID for the log channel
DEFAULT_SPECIFIC_ROLE_ID: int = (
    1286171116951310407  # Default ID for specific role required for command access
)
DEFAULT_ALLOWED_SERVERS: List[int] = [
    1014562212007915601
]  # Default list of allowed server IDs
DEFAULT_MEMBER_ROLE_ID: int = (
    1014566237558284338  # Default ID for the standard member role
)
DEFAULT_ALT_JAIL_ROLE_ID: int = (
    1280228557318000783  # Default ID for an alternative jail role for checks
)

MAX_USERS_PER_COMMAND: int = (
    20  # Maximum number of users that can be processed per command invocation
)
TEMP_MESSAGE_DELAY_SECONDS: int = (
    5  # Duration for temporary messages to stay before deletion
)
PURGE_RETRY_DELAY_SECONDS: int = 5  # Delay between retries for message purging
MAX_PURGE_RETRIES: int = 3  # Maximum number of retries for message purging
PURGE_MESSAGE_LIMIT: int = (
    100  # Maximum number of messages to fetch and purge per channel
)
CLEANUP_INTERVAL_SECONDS: int = (
    86400  # Interval (24 hours) for cleaning up old log files
)
ACCOUNT_AGE_SPAM_THRESHOLD_DAYS: int = (
    90  # Account age threshold for automatic spam jailing
)
SPAM_CHECK_ROLE_COUNT_THRESHOLD: int = (
    1  # Maximum roles a new member can have to be considered for spam jail (e.g., just @everyone)
)

# Category IDs where messages should be purged during jailing
CATEGORIES_TO_PURGE: Set[int] = {
    1276399856465874974,
    1014562212544774204,
}

# Keywords for profile scanning in usernames and nicknames
SUSPICIOUS_USERNAME_KEYWORDS: List[str] = [
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
]

# Keywords for profile scanning in bios and pronouns
SUSPICIOUS_BIO_PRONOUNS_KEYWORDS: List[str] = [
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
]


@dataclass
class JailSettings:
    """Dataclass to hold sensitive IDs and configuration settings, loaded from environment variables or defaults."""

    # Jail role ID, loaded from environment variable JAIL_ROLE_ID or uses default
    jail_role_id: int = field(
        default_factory=lambda: int(
            os.getenv("JAIL_ROLE_ID", str(DEFAULT_JAIL_ROLE_ID))
        )
    )
    # Log channel ID, loaded from environment variable LOG_CHANNEL_ID or uses default
    log_channel_id: int = field(
        default_factory=lambda: int(
            os.getenv("LOG_CHANNEL_ID", str(DEFAULT_LOG_CHANNEL_ID))
        )
    )
    # Specific role ID for command access, loaded from environment variable SPECIFIC_ROLE_ID or uses default
    specific_role_id: int = field(
        default_factory=lambda: int(
            os.getenv("SPECIFIC_ROLE_ID", str(DEFAULT_SPECIFIC_ROLE_ID))
        )
    )
    # Allowed server IDs, loaded from comma-separated string in ALLOWED_SERVERS env var or uses default
    allowed_servers: List[int] = field(
        default_factory=lambda: [
            int(s.strip())
            for s in os.getenv(
                "ALLOWED_SERVERS", ",".join(map(str, DEFAULT_ALLOWED_SERVERS))
            ).split(",")
        ]
    )
    default_member_role_id: int = (
        DEFAULT_MEMBER_ROLE_ID  # Default member role ID constant
    )
    alt_jail_role_id: int = (
        DEFAULT_ALT_JAIL_ROLE_ID  # Alternative jail role ID constant
    )


@dataclass
class UserProfileScanResult:
    """Dataclass to hold results of a user profile scan, including the user and found keywords."""

    user: discord.Member  # The Discord member object
    keywords: List[str]  # List of suspicious keywords found


class JailUser(commands.Cog):
    """A cog for jailing and unjailing users, with moderation features like message purging and profile scanning."""

    def __init__(self, bot: commands.Bot):
        """Initializes the JailUser cog with bot instance, configuration, logger, and thread pool."""
        self.bot: commands.Bot = bot  # Stores the bot instance
        self.config: JailSettings = (
            JailSettings()
        )  # Load configuration settings from environment variables or defaults
        self.logger: logging.Logger = log  # Use the configured logger for all logging
        self.thread_pool: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=10)
        )  # Creates a thread pool for offloading blocking I/O tasks

        # Cache Discord objects (roles, channels) per guild ID for efficiency and robustness in multi-guild environments
        self.jail_roles: Dict[int, Optional[discord.Role]] = (
            {}
        )  # Cache jail roles per guild ID
        self.log_channels: Dict[int, Optional[discord.TextChannel]] = (
            {}
        )  # Cache log channels per guild ID

        # Define the directory for storing purged message logs, relative to the cog's data path
        self.purged_logs_dir: pathlib.Path = (
            pathlib.Path(data_manager.cog_data_path(self)) / "purged_logs"
        )
        try:
            self.purged_logs_dir.mkdir(
                exist_ok=True, parents=True
            )  # Creates the purged_logs directory if it doesn't exist
            self.logger.info(
                f"Ensured purged logs directory exists: {self.purged_logs_dir}"
            )  # Log successful directory creation
        except PermissionError as e:
            self.logger.critical(
                f"Critical error: Could not create directory {self.purged_logs_dir}: {e}",
                exc_info=True,
            )  # Log critical permission error with traceback
            raise  # Re-raises the exception to halt cog loading if directory creation fails
        except Exception as e:
            self.logger.critical(
                f"Critical error: An unexpected error occurred creating directory {self.purged_logs_dir}: {e}",
                exc_info=True,
            )  # Log other critical errors with traceback
            raise  # Re-raises the exception

    async def get_jail_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        """Fetches and caches the jail role for a specific guild, logging a warning if not found."""
        # Check if the role is not cached or if the cached role is None (meaning it wasn't found previously)
        if guild.id not in self.jail_roles or self.jail_roles[guild.id] is None:
            self.jail_roles[guild.id] = guild.get_role(
                self.config.jail_role_id
            )  # Fetch role by ID from the guild
            if self.jail_roles[guild.id] is None:  # If role not found in the guild
                self.logger.warning(
                    f"Jail role with ID {self.config.jail_role_id} not found in guild {guild.name} ({guild.id})."
                )  # Log a warning
        return self.jail_roles[guild.id]  # Return the cached role

    async def get_log_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        """Fetches and caches the log channel for a specific guild, ensuring it's a text channel in the correct guild."""
        # Check if the channel is not cached or if the cached channel is None
        if guild.id not in self.log_channels or self.log_channels[guild.id] is None:
            channel: Optional[discord.abc.GuildChannel] = self.bot.get_channel(
                self.config.log_channel_id
            )  # Fetch channel object by ID
            if isinstance(
                channel, discord.TextChannel
            ):  # Ensure the fetched object is a text channel
                if (
                    channel.guild.id == guild.id
                ):  # Verify the channel is in the correct guild
                    self.log_channels[guild.id] = channel  # Cache the channel
                else:
                    self.logger.warning(
                        f"Log channel with ID {self.config.log_channel_id} is not in guild {guild.name} ({guild.id})."
                    )  # Log warning if channel is in a different guild
                    self.log_channels[guild.id] = (
                        None  # Set to None if not in the correct guild
                    )
            else:
                self.logger.warning(
                    f"Log channel with ID {self.config.log_channel_id} not found or is not a text channel."
                )  # Log warning if not found or wrong type
                self.log_channels[guild.id] = None  # Set to None
        return self.log_channels[guild.id]  # Return the cached channel

    async def log_action(
        self,
        user: discord.Member,
        ctx: commands.Context,
        reason: str,
        action_type: str,  # "Jailed" or "Released" to customize log message
        purged_messages_file: Optional[pathlib.Path] = None,
    ) -> None:
        """Logs jailing/unjailing actions to the configured log channel, optionally attaching a purged messages file."""
        log_channel: Optional[discord.TextChannel] = await self.get_log_channel(
            ctx.guild
        )  # Get the log channel for the current guild

        if not log_channel:  # If log channel is not found or not in the correct guild
            self.logger.warning(
                f"Log channel not found for guild {ctx.guild.name} ({ctx.guild.id}). Cannot log action for user {user.id}."
            )  # Log warning
            return  # Exit if no log channel

        action_emoji: str = (
            "🔒" if action_type == "Jailed" else "🔓"
        )  # Determine emoji based on action type
        jail_timestamp: str = (
            f"<t:{int(datetime.now().timestamp())}:F>"  # Get current timestamp formatted for Discord display
        )

        log_message: str = (  # Format the detailed log message string
            f"{action_emoji} User {action_type}:\n"
            f"• User: {user.mention} (ID: {user.id})\n"
            f"• {action_type} By: {ctx.author.name} (ID: {ctx.author.id})\n"
            f"• Timestamp: {jail_timestamp}\n"
            f"• Reason: {reason}"
        )

        try:
            # Check if a purged messages file exists, is not empty, and should be attached
            if (
                purged_messages_file
                and purged_messages_file.exists()
                and purged_messages_file.stat().st_size > 0
            ):
                with purged_messages_file.open(
                    "rb"
                ) as file:  # Open the purged messages file in binary read mode
                    await log_channel.send(  # Send the log message with the purged messages file attached
                        log_message,
                        file=discord.File(
                            file, filename=f"{user.id}_purged_messages.txt"
                        ),  # Create a discord.File object from the file
                    )
            else:
                await log_channel.send(
                    log_message
                )  # Send the log message without any attachment
            self.logger.info(
                f"Logged {action_type} action for user {user.id} by {ctx.author.id}."
            )  # Log successful logging
        except (
            discord.Forbidden
        ):  # Catch Forbidden error if bot lacks permissions to send messages
            self.logger.error(
                f"Bot lacks permissions to send messages in log channel {log_channel.id} in guild {ctx.guild.id}.",
                exc_info=True,
            )  # Log permission error with traceback
        except (
            discord.HTTPException
        ) as e:  # Catch HTTPException during log sending (e.g., rate limits)
            self.logger.error(
                f"HTTPException during log sending for user {user.id}: {e}",
                exc_info=True,
            )  # Log HTTP error with traceback
        except (
            Exception
        ) as e:  # Catch any other unexpected exception during log sending
            self.logger.error(
                f"Error logging action for user {user.id}: {e}", exc_info=True
            )  # Log generic error with traceback

    @commands.command(name="unjail")
    @commands.max_concurrency(
        5, per=commands.BucketType.guild, wait=True
    )  # Limit command concurrency to prevent abuse/overload
    async def unjail(
        self,
        ctx: commands.Context,
        *users: commands.Greedy[discord.Member],  # Accepts multiple user mentions/IDs
        reason: str,  # Mandatory reason for unjailing
    ) -> None:
        """Unjails one or more users, removing their jail role and restoring default roles."""
        # Check if the command is used in an allowed server
        if ctx.guild.id not in self.config.allowed_servers:
            await self.send_temp_message(
                ctx, "You do not have permission to use this command in this server."
            )  # Inform user
            return  # Exit the command

        if not reason:  # Ensure a reason is provided for auditability
            await self.send_temp_message(
                ctx, "Please provide a reason for unjailing."
            )  # Prompt for reason
            return  # Exit the command

        # Fetch the specific role required for command usage
        specific_role: Optional[discord.Role] = ctx.guild.get_role(
            self.config.specific_role_id
        )
        # Check if the author has 'ban_members' permission or the specific role
        if not (
            ctx.author.guild_permissions.ban_members
            or (specific_role and specific_role in ctx.author.roles)
        ):
            await self.send_temp_message(
                ctx, "You do not have permission to use this command."
            )  # Inform user
            return  # Exit the command

        # Get the jail role for the current guild
        jail_role: Optional[discord.Role] = await self.get_jail_role(ctx.guild)
        if not jail_role:  # If jail role is not found in the guild
            await self.send_temp_message(
                ctx,
                "Jail role not found in this server. Please ensure it's configured correctly.",
            )  # Inform user
            return  # Exit

        users_to_unjail: List[discord.Member] = users[
            :MAX_USERS_PER_COMMAND
        ]  # Limit processing to a maximum number of users

        # Filter the provided users to only include those who are actually jailed
        jailed_users: List[discord.Member] = [
            user
            for user in users_to_unjail
            if jail_role in user.roles
            or any(
                role.id == self.config.alt_jail_role_id for role in user.roles
            )  # Check for main or alternative jail role
        ]

        if not jailed_users:  # If none of the specified users are currently jailed
            await self.send_temp_message(
                ctx,
                "No specified users are currently jailed or they do not have the designated jail role.",
            )  # Inform user
            return  # Exit the command

        reply_message: discord.Message = await ctx.send(
            "Releasing user(s)..."
        )  # Send an initial processing message
        unjail_tasks: List[asyncio.Task[Any]] = (
            []
        )  # Initialize a list to hold asynchronous tasks for parallel execution

        for user in jailed_users:  # Iterate through each user to be unjailed
            try:
                # Identify roles to remove: all roles except the default member role and @everyone role
                roles_to_remove: List[discord.Role] = [
                    role
                    for role in user.roles
                    if role.id != self.config.default_member_role_id
                    and role.id != ctx.guild.id
                ]
                if roles_to_remove:  # If there are roles to remove
                    await user.remove_roles(
                        *roles_to_remove, reason=f"Unjailed by {ctx.author.name}"
                    )  # Remove the identified roles with a reason
                    self.logger.info(
                        f"Removed {len(roles_to_remove)} roles from user {user.id} during unjail."
                    )  # Log role removal

                # Add the default member role back if the user doesn't already have it
                default_member_role: Optional[discord.Role] = ctx.guild.get_role(
                    self.config.default_member_role_id
                )
                if default_member_role and default_member_role not in user.roles:
                    await user.add_roles(
                        default_member_role, reason=f"Unjailed by {ctx.author.name}"
                    )  # Add the default member role
                    self.logger.info(
                        f"Added default role to user {user.id} during unjail."
                    )  # Log role addition

                await self.log_action(
                    user, ctx, reason, "Released"
                )  # Log the unjailing action
                response: str = (
                    f"{user.mention} has been unjailed."  # Create a success message for the user
                )
                unjail_tasks.append(
                    self.send_temp_message(ctx, response)
                )  # Add sending a temporary message to the task list
            except (
                discord.Forbidden
            ):  # Catch Discord.Forbidden if the bot lacks permissions to modify roles
                self.logger.error(
                    f"Bot lacks permissions to unjail user {user.id} in guild {ctx.guild.id}.",
                    exc_info=True,
                )  # Log permission error with traceback
                await self.send_temp_message(
                    ctx, f"Failed to unjail {user.mention} due to missing permissions."
                )  # Inform user
            except (
                Exception
            ) as e:  # Catch any other unexpected exception during unjailing
                self.logger.error(
                    f"Error unjailing user {user.id}: {e}", exc_info=True
                )  # Log generic error with traceback
                await self.send_temp_message(
                    ctx, f"An error occurred while unjailing {user.mention}."
                )  # Inform user

        await asyncio.gather(
            *unjail_tasks
        )  # Execute all temporary message sending tasks concurrently
        await ctx.message.delete()  # Delete the command invocation message
        await reply_message.delete()  # Delete the initial "Releasing user(s)..." message

    @commands.command(name="jail")
    @commands.max_concurrency(
        5, per=commands.BucketType.guild, wait=True
    )  # Limit command concurrency
    async def jail(
        self,
        ctx: commands.Context,
        *users: commands.Greedy[discord.Member],  # Accepts multiple user mentions/IDs
        reason: str,  # Mandatory reason for jailing
    ) -> None:
        """Jails one or more users, removing their roles and purging recent messages."""
        # Check if the command is used in an allowed server
        if ctx.guild.id not in self.config.allowed_servers:
            await self.send_temp_message(
                ctx, "You do not have permission to use this command in this server."
            )  # Inform user
            return  # Exit the command
        if not reason:  # Ensure a reason is provided
            await self.send_temp_message(
                ctx, "Please provide a reason for jailing."
            )  # Prompt for reason
            return  # Exit the command

        # Fetch the specific role required for command usage
        specific_role: Optional[discord.Role] = ctx.guild.get_role(
            self.config.specific_role_id
        )
        # Check if the author has 'ban_members' permission or the specific role
        if not (
            ctx.author.guild_permissions.ban_members
            or (specific_role and specific_role in ctx.author.roles)
        ):
            await self.send_temp_message(
                ctx, "You do not have permission to use this command."
            )  # Inform user
            return  # Exit the command

        # Get the jail role for the current guild
        jail_role: Optional[discord.Role] = await self.get_jail_role(ctx.guild)
        if not jail_role:  # If jail role is not found
            await self.send_temp_message(
                ctx,
                "Jail role not found in this server. Please ensure it's configured correctly.",
            )  # Inform user
            return  # Exit

        users_to_jail: List[discord.Member] = users[
            :MAX_USERS_PER_COMMAND
        ]  # Limit processing to a maximum number of users

        # Filter the provided users to identify those already jailed
        already_jailed: List[discord.Member] = [
            user
            for user in users_to_jail
            if any(
                role.id in {self.config.jail_role_id, self.config.alt_jail_role_id}
                for role in user.roles
            )
        ]

        # If all specified users are already jailed, inform the user and provide previous jail logs
        if len(already_jailed) == len(users_to_jail):
            log_channel: Optional[discord.TextChannel] = await self.get_log_channel(
                ctx.guild
            )  # Get the log channel
            tasks: List[asyncio.Task[Any]] = []  # Initialize tasks list
            for user in already_jailed:  # For each user already jailed
                jail_links: List[str] = []  # List to store links to previous jail logs
                if log_channel:  # Only search history if log channel is available
                    async for message in log_channel.history(
                        limit=250
                    ):  # Iterate through recent log channel history
                        # Check if the log message pertains to this user being jailed previously
                        if (
                            f"ID: {user.id}" in message.content
                            and "User Jailed:" in message.content
                        ):
                            jail_links.append(message.jump_url)  # Add the message link
                            if len(jail_links) >= 3:  # Stop after finding a few links
                                break
                response: str = f"{user.mention} is already jailed."  # Base response
                if jail_links:  # If previous logs were found
                    response += "\nPrevious jail logs:\n" + "\n".join(
                        jail_links
                    )  # Append log links
                tasks.append(
                    self.send_temp_message(ctx, response)
                )  # Add task to send temporary message
            await asyncio.gather(
                *tasks
            )  # Execute all temporary message sending tasks concurrently
            await ctx.message.delete()  # Delete the command invocation message
            return  # Exit the command

        reply_message: discord.Message = await ctx.send(
            "Jailing user(s)..."
        )  # Send an initial processing message

        async def process_user(user: discord.Member) -> None:
            """Helper asynchronous function to process each user for jailing, including role changes and message purging."""
            if (
                user not in ctx.guild.members
            ):  # Ensure the user is still a member of the guild
                await self.send_temp_message(
                    ctx, f"{user.name} is not a member of this guild."
                )  # Inform user
                self.logger.warning(
                    f"Attempted to jail non-guild member {user.id}."
                )  # Log warning
                return  # Exit if user is not a member

            # Re-check if user is already jailed (important for concurrency to avoid re-processing)
            if any(
                role.id in {self.config.jail_role_id, self.config.alt_jail_role_id}
                for role in user.roles
            ):
                self.logger.info(
                    f"Skipping user {user.id} as they are already jailed during batch processing."
                )  # Log skip
                return  # Exit if already jailed

            try:
                # Remove all roles except @everyone (which is at index 0 in user.roles, or by ID)
                roles_to_remove: List[discord.Role] = [
                    role
                    for role in user.roles
                    if role.id != ctx.guild.id  # Exclude the @everyone role
                ]
                if roles_to_remove:  # If there are roles to remove
                    await user.remove_roles(
                        *roles_to_remove, reason=f"Jailed by {ctx.author.name}"
                    )  # Remove all roles
                    self.logger.info(
                        f"Removed {len(roles_to_remove)} roles from user {user.id}."
                    )  # Log role removal
                await user.add_roles(
                    jail_role, reason=f"Jailed by {ctx.author.name}"
                )  # Add the jail role
                self.logger.info(
                    f"Added jail role to user {user.id}."
                )  # Log role addition

                # Define a unique path for the purged messages log file (with timestamp)
                purged_messages_file: pathlib.Path = (
                    self.purged_logs_dir
                    / f"{user.id}_purged_messages_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
                )

                def write_messages_to_file(
                    messages: List[discord.Message], file_path: pathlib.Path
                ) -> None:
                    """Synchronous helper function to write a list of Discord messages to a file."""
                    try:
                        with file_path.open(
                            "w", buffering=8192, encoding="utf-8"
                        ) as file:  # Open in write mode with buffering and UTF-8 encoding
                            for message in messages:  # Iterate and write each message
                                file.write(
                                    f"[{message.created_at}] {message.author.name} ({message.author.id}): {message.content}\n"
                                )
                        self.logger.info(
                            f"Successfully wrote {len(messages)} purged messages to {file_path}."
                        )  # Log successful write
                    except Exception as e:
                        self.logger.error(
                            f"Failed to write purged messages to {file_path}: {e}",
                            exc_info=True,
                        )  # Log error with traceback

                async def process_channel_for_purge(
                    channel: discord.abc.GuildChannel,
                ) -> List[discord.Message]:
                    """Asynchronous helper to purge messages from a given channel or thread for a specific user."""
                    if not isinstance(
                        channel, (discord.TextChannel, discord.Thread)
                    ):  # Ensure it's a text channel or thread
                        self.logger.warning(
                            f"Attempted to purge non-text channel/thread: {channel.name} ({channel.id}). Skipping."
                        )  # Log warning
                        return []
                    return await self.purge_with_retry(
                        channel, user
                    )  # Call the purge with retry logic

                all_purged_messages: List[discord.Message] = (
                    []
                )  # List to collect all messages purged for the user
                try:
                    for (
                        category_id
                    ) in (
                        CATEGORIES_TO_PURGE
                    ):  # Iterate through predefined categories for purging
                        category: Optional[discord.CategoryChannel] = (
                            ctx.guild.get_channel(category_id)
                        )  # Fetch the category object
                        if category and isinstance(
                            category, discord.CategoryChannel
                        ):  # If category exists and is a CategoryChannel
                            channels_to_process: List[discord.abc.GuildChannel] = [
                                channel
                                for channel in category.channels
                                if isinstance(
                                    channel, (discord.TextChannel, discord.Thread)
                                )  # Filter for text channels and threads within the category
                            ]

                            # Gather results from processing all relevant channels/threads concurrently
                            channel_purge_results: List[List[discord.Message]] = (
                                await asyncio.gather(
                                    *[
                                        process_channel_for_purge(channel)
                                        for channel in channels_to_process
                                    ],
                                    return_exceptions=True,  # Return exceptions to handle them gracefully
                                )
                            )

                            for (
                                result
                            ) in channel_purge_results:  # Iterate through purge results
                                if isinstance(
                                    result, list
                                ):  # If the result is a list of messages
                                    all_purged_messages.extend(
                                        result
                                    )  # Add them to the total purged messages
                                else:  # If the result is an exception
                                    self.logger.error(
                                        f"Error purging messages in a channel for user {user.id}: {result}",
                                        exc_info=True,
                                    )  # Log the error

                    if all_purged_messages:  # If any messages were purged
                        # Run the synchronous file writing in the thread pool to avoid blocking the event loop
                        await self.bot.loop.run_in_executor(
                            self.thread_pool,
                            write_messages_to_file,
                            all_purged_messages,
                            purged_messages_file,
                        )
                    else:
                        self.logger.info(
                            f"No messages purged for user {user.id} in specified categories."
                        )  # Log if no messages were purged
                        purged_messages_file = None  # Set to None if no messages were purged to avoid attaching empty file

                except (
                    Exception
                ) as e:  # Catch any exception during file operations or message processing
                    self.logger.error(
                        f"Failed to process and write purged messages for user {user.id}: {e}",
                        exc_info=True,
                    )  # Log error with traceback
                    purged_messages_file = (
                        None  # Ensure no file is attached if an error occurred
                    )

                await self.log_action(
                    user, ctx, reason, "Jailed", purged_messages_file
                )  # Log the jailing action
            except (
                discord.Forbidden
            ):  # Catch Forbidden error if the bot lacks permissions
                self.logger.error(
                    f"Bot lacks permissions to jail user {user.id} in guild {ctx.guild.id}.",
                    exc_info=True,
                )  # Log permission error with traceback
                await self.send_temp_message(
                    ctx, f"Failed to jail {user.mention} due to missing permissions."
                )  # Inform user
            except Exception as e:  # Catch any other unexpected exception
                self.logger.error(
                    f"Error jailing user {user.id}: {e}", exc_info=True
                )  # Log generic error with traceback
                await self.send_temp_message(
                    ctx, f"An error occurred while jailing {user.mention}."
                )  # Inform user

        # Process users concurrently who are not already jailed
        await asyncio.gather(
            *[
                process_user(user)
                for user in users_to_jail
                if user not in already_jailed
            ]
        )

        if reply_message:  # If the initial "Jailing user(s)..." message exists
            await reply_message.edit(
                content="Jail operation complete."
            )  # Edit the message to indicate completion
            await asyncio.sleep(TEMP_MESSAGE_DELAY_SECONDS)  # Wait for a short duration
            await reply_message.delete()  # Delete the message
        await ctx.message.delete()  # Delete the command invocation message

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Automatically jails new members if they meet spam prevention criteria (e.g., very new account with few roles)."""
        if (
            member.guild.id not in self.config.allowed_servers
        ):  # Check if the member joined an allowed server
            return  # Exit if not an allowed server

        jail_role: Optional[discord.Role] = await self.get_jail_role(
            member.guild
        )  # Get the jail role for the member's guild
        if not jail_role:  # If jail role not found in the guild
            self.logger.warning(
                f"Jail role not found in guild {member.guild.name} ({member.guild.id}) for on_member_join event. Cannot auto-jail."
            )  # Log warning
            return  # Exit

        account_age: timedelta = (
            datetime.now(member.created_at.tzinfo) - member.created_at
        )  # Calculate the age of the member's account

        # Check for spam criteria: account younger than threshold days and has few roles (i.e., only @everyone)
        if (
            account_age < timedelta(days=ACCOUNT_AGE_SPAM_THRESHOLD_DAYS)
            and len(member.roles) <= SPAM_CHECK_ROLE_COUNT_THRESHOLD
        ):
            try:
                await member.add_roles(
                    jail_role,
                    reason="Automatic spam prevention (new account, few roles)",
                )  # Add the jail role to the new member
                self.logger.info(
                    f"Automatically jailed new member {member.id} for spam prevention. Account age: {account_age.days} days."
                )  # Log auto-jailing

                log_channel: Optional[discord.TextChannel] = await self.get_log_channel(
                    member.guild
                )  # Get the log channel for the guild
                if log_channel:  # If log channel is available
                    jail_timestamp: str = (
                        f"<t:{int(datetime.now().timestamp())}:F>"  # Get current timestamp formatted for Discord
                    )
                    log_message: str = (  # Format the log message for auto-jailing
                        f"🚫 Spam Prevention - Auto Jailed:\n"
                        f"• User: {member.mention} (ID: {member.id})\n"
                        f"• Account Age: {account_age.days} days\n"
                        f"• Jailed at: {jail_timestamp}"
                    )
                    await log_channel.send(
                        log_message
                    )  # Send the auto-jail log message
                    self.logger.info(
                        f"Logged auto-jail for {member.id}."
                    )  # Log successful logging
            except discord.Forbidden:  # Catch Forbidden error if bot lacks permissions
                self.logger.error(
                    f"Bot lacks permissions to auto-jail member {member.id} in guild {member.guild.id}.",
                    exc_info=True,
                )  # Log permission error with traceback
            except Exception as e:  # Catch any other unexpected exception
                self.logger.error(
                    f"Error processing new member {member.id} for auto-jail: {e}",
                    exc_info=True,
                )  # Log generic error with traceback

    async def send_temp_message(
        self,
        ctx: commands.Context,
        content: str,
        delay: int = TEMP_MESSAGE_DELAY_SECONDS,
    ) -> None:
        """Sends a temporary message to the context channel that gets deleted after a specified delay."""
        if ctx.channel:  # Ensure the context has a valid channel
            try:
                message: discord.Message = await ctx.channel.send(
                    content
                )  # Send the message
                await asyncio.sleep(delay)  # Wait for the specified delay
                await message.delete()  # Delete the message
            except (
                discord.NotFound
            ):  # Catch if the message or channel was deleted before the bot could act
                self.logger.debug(
                    f"Temporary message or channel not found for deletion in ctx {ctx.channel.id}."
                )  # Log debug info
            except (
                discord.Forbidden
            ):  # Catch Forbidden error if bot lacks permissions to delete messages
                self.logger.warning(
                    f"Bot lacks permissions to delete temporary message in channel {ctx.channel.id}."
                )  # Log warning
            except Exception as e:  # Catch any other unexpected exception
                self.logger.error(
                    f"Error sending/deleting temporary message in channel {ctx.channel.id}: {e}",
                    exc_info=True,
                )  # Log generic error with traceback

    async def purge_with_retry(
        self,
        channel: discord.abc.GuildChannel,
        user: discord.Member,
        max_retries: int = MAX_PURGE_RETRIES,
    ) -> List[discord.Message]:
        """Purges messages by a specific user in a channel with retry logic for rate limits and other HTTP exceptions."""
        if not isinstance(
            channel, (discord.TextChannel, discord.Thread)
        ):  # Ensure the channel is a text channel or thread
            self.logger.warning(
                f"Attempted to purge non-text channel/thread: {channel.name} ({channel.id}). Skipping."
            )  # Log warning
            return []

        retries: int = 0  # Initialize retry counter
        while retries < max_retries:  # Loop until maximum retries are reached
            try:
                # Purge messages by the specified user, up to a defined limit
                purged_messages: List[discord.Message] = await channel.purge(
                    limit=PURGE_MESSAGE_LIMIT, check=lambda m: m.author == user
                )
                self.logger.info(
                    f"Purged {len(purged_messages)} messages from user {user.id} in channel {channel.id}."
                )  # Log successful purge
                return purged_messages  # Return the list of purged messages on success
            except (
                discord.Forbidden
            ):  # Catch Forbidden error if bot lacks permissions to purge
                self.logger.error(
                    f"Bot lacks permissions to purge messages in channel {channel.id} in guild {channel.guild.id}.",
                    exc_info=True,
                )  # Log permission error with traceback
                return []  # Return empty list on permission error
            except (
                discord.HTTPException
            ) as e:  # Catch HTTPException, which includes rate limits (status 429)
                if e.status == 429:  # Specifically check for rate limit error
                    retry_after: float = (
                        e.retry_after
                        if hasattr(e, "retry_after")
                        else PURGE_RETRY_DELAY_SECONDS
                    )  # Get retry_after value or use default
                    self.logger.warning(
                        f"Purge rate limited in channel {channel.id}. Retrying after {retry_after}s... (Attempt {retries + 1}/{max_retries})"
                    )  # Log rate limit
                    await asyncio.sleep(
                        retry_after
                    )  # Wait for the specified duration before retrying
                    retries += 1  # Increment retry counter
                else:  # For other HTTPExceptions (e.g., bad request, unknown channel)
                    self.logger.error(
                        f"HTTPException during purge in channel {channel.id}: {e}",
                        exc_info=True,
                    )  # Log the error with traceback
                    return []  # Return an empty list on other HTTP errors
            except Exception as e:  # Catch any other unexpected exception during purge
                self.logger.error(
                    f"Generic exception during purge in channel {channel.id}: {e}",
                    exc_info=True,
                )  # Log the error with traceback
                return []  # Return an empty list on error
        self.logger.error(
            f"Failed to purge messages for user {user.id} in channel {channel.id} after {max_retries} retries."
        )  # Log failure after all retries
        return []  # Return an empty list if all retries fail

    async def send_with_retry(
        self,
        channel: discord.abc.Messageable,
        message_content: str,
        file_path: Optional[pathlib.Path] = None,
        max_retries: int = MAX_PURGE_RETRIES,
    ) -> None:
        """Sends a message to a channel with retry logic for rate limits, optionally attaching a file."""
        retries: int = 0  # Initialize retry counter
        while retries < max_retries:  # Loop until maximum retries are reached
            try:
                if (
                    file_path and file_path.exists()
                ):  # Check if a file path is provided and the file exists
                    with file_path.open(
                        "rb"
                    ) as file:  # Open the file in binary read mode
                        await channel.send(  # Send the message with the file attached
                            message_content,
                            file=discord.File(
                                file, filename=file_path.name
                            ),  # Use pathlib.Path.name for filename
                        )
                else:  # If no file path is provided or file doesn't exist
                    await channel.send(
                        message_content
                    )  # Send the message without attachment
                self.logger.info(
                    f"Successfully sent message to channel {channel.id}."
                )  # Log successful send
                break  # Exit loop on successful send
            except (
                discord.Forbidden
            ):  # Catch Forbidden error if bot lacks permissions to send
                self.logger.error(
                    f"Bot lacks permissions to send messages in channel {channel.id}.",
                    exc_info=True,
                )  # Log permission error with traceback
                break  # Exit loop on permission error
            except (
                discord.HTTPException
            ) as e:  # Catch HTTPException (e.g., rate limits)
                if e.status == 429:  # Check for rate limit
                    retry_after: float = (
                        e.retry_after
                        if hasattr(e, "retry_after")
                        else PURGE_RETRY_DELAY_SECONDS
                    )  # Get retry_after or use default
                    self.logger.warning(
                        f"Send rate limited to channel {channel.id}. Retrying after {retry_after}s... (Attempt {retries + 1}/{max_retries})"
                    )  # Log rate limit
                    await asyncio.sleep(retry_after)  # Wait for the specified duration
                    retries += 1  # Increment retry counter
                else:  # For other HTTPExceptions
                    self.logger.error(
                        f"HTTPException during send to channel {channel.id}: {e}",
                        exc_info=True,
                    )  # Log error with traceback
                    break  # Exit loop on other HTTP errors
            except Exception as e:  # Catch any other unexpected exception
                self.logger.error(
                    f"Generic exception during send to channel {channel.id}: {e}",
                    exc_info=True,
                )  # Log error with traceback
                break  # Exit loop on error
        if retries == max_retries:  # If all retries failed
            self.logger.error(
                f"Failed to send message to channel {channel.id} after {max_retries} retries."
            )  # Log failure after retries

    async def cleanup_temp_files(self) -> None:
        """Removes old purged message files from the designated directory periodically."""
        self.logger.info(
            "Starting background task: cleanup_temp_files."
        )  # Log task start
        while True:  # Infinite loop for periodic cleanup
            try:
                for filename in os.listdir(
                    self.purged_logs_dir
                ):  # List files in the purged logs directory
                    file_path: pathlib.Path = (
                        self.purged_logs_dir / filename
                    )  # Create a Path object for the file
                    # Check if it's a file and ends with the expected suffix
                    if file_path.is_file() and filename.endswith(
                        "_purged_messages.txt"
                    ):
                        file_creation_time: datetime = datetime.fromtimestamp(
                            file_path.stat().st_ctime
                        )  # Get file creation time
                        if (
                            datetime.now() - file_creation_time
                        ).days > 7:  # Check if the file is older than 7 days
                            os.remove(file_path)  # Remove the old file
                            self.logger.info(
                                f"Cleaned up old log file: {file_path}"
                            )  # Log cleanup action
            except Exception as e:  # Catch any exception during file operations
                self.logger.error(
                    f"Error in file cleanup task: {e}", exc_info=True
                )  # Log error with traceback

            await asyncio.sleep(
                CLEANUP_INTERVAL_SECONDS
            )  # Wait for 24 hours before the next cleanup cycle

    def cog_load(self) -> None:
        """Method called when the cog is loaded, starts the background cleanup task."""
        self.bot.loop.create_task(
            self.cleanup_temp_files()
        )  # Create and schedule the cleanup task
        self.logger.info("JailUser cog loaded.")  # Log cog load

    def cog_unload(self) -> None:
        """Method called when the cog is unloaded, gracefully shuts down the thread pool."""
        self.thread_pool.shutdown(
            wait=True
        )  # Shut down the thread pool, waiting for active tasks to complete
        self.logger.info(
            "JailUser cog unloaded and thread pool shut down."
        )  # Log cog unload

    @commands.command(name="jailcheck")
    @commands.has_guild_permissions(
        manage_roles=True
    )  # Requires 'Manage Roles' permission
    async def force_jail_check(self, ctx: commands.Context) -> None:
        """Manually triggers a check for members with the jail role and removes any other unauthorized roles they might have."""
        initial_message: discord.Message = await ctx.send(
            "Initiating manual jail role check..."
        )  # Send an initial processing message

        try:
            guild_jail_role: Optional[discord.Role] = await self.get_jail_role(
                ctx.guild
            )  # Get the jail role for the current guild
            if not guild_jail_role:  # If jail role is not found
                await self.send_temp_message(
                    ctx,
                    "Jail role not found in this server. Please ensure it's configured correctly.",
                )  # Inform user
                return  # Exit the command

            log_channel_instance: Optional[discord.TextChannel] = (
                await self.get_log_channel(ctx.guild)
            )  # Get the log channel for the guild

            processed_members: int = 0  # Counter for members processed
            roles_removed_count: int = 0  # Counter for total roles removed

            # Iterate through all members who currently have the jail role
            for member in guild_jail_role.members:
                try:
                    # Identify roles to remove: all roles except the jail role itself and the @everyone role
                    roles_to_remove: List[discord.Role] = [
                        role
                        for role in member.roles
                        if role.id != guild_jail_role.id
                        and role.id != ctx.guild.default_role.id
                    ]

                    if roles_to_remove:  # If there are any unauthorized roles to remove
                        await member.remove_roles(
                            *roles_to_remove, reason="Manual jail role enforcement"
                        )  # Remove the roles with a specific reason
                        self.logger.info(
                            f"Manually removed {len(roles_to_remove)} roles from {member.id} during jailcheck."
                        )  # Log role removal

                        if log_channel_instance:  # If a valid log channel is available
                            role_names: str = ", ".join(
                                role.name for role in roles_to_remove
                            )  # Create a comma-separated string of removed role names
                            log_message: str = (  # Format the log message
                                f"🔒 Manual Jail Role Enforcement:\n"
                                f"• User: {member.mention} (ID: {member.id})\n"
                                f"• Roles Removed: {role_names}\n"
                                f"• Initiated by: {ctx.author.name} (ID: {ctx.author.id})"
                            )
                            await log_channel_instance.send(
                                log_message
                            )  # Send the log message
                            self.logger.info(
                                f"Logged manual jail role enforcement for {member.id}."
                            )  # Log successful logging

                        processed_members += 1  # Increment processed members counter
                        roles_removed_count += len(
                            roles_to_remove
                        )  # Add the number of removed roles to the total

                except (
                    discord.Forbidden
                ):  # Catch Forbidden error if bot lacks permissions for a specific member
                    self.logger.error(
                        f"Could not process roles for {member.name} ({member.id}) in {ctx.guild.name} due to permissions.",
                        exc_info=True,
                    )  # Log permission error with traceback
                except (
                    Exception
                ) as e:  # Catch any other unexpected exception during member processing
                    self.logger.error(
                        f"Error processing {member.name} ({member.id}) in {ctx.guild.name} during jailcheck: {e}",
                        exc_info=True,
                    )  # Log generic error with traceback

            summary_message_content: str = (  # Format the summary message content
                f"Jail role check complete.\n"
                f"Members Processed: {processed_members}\n"
                f"Total Roles Removed: {roles_removed_count}"
            )
            await initial_message.edit(
                content=summary_message_content
            )  # Edit the initial message to show the summary
            await asyncio.sleep(TEMP_MESSAGE_DELAY_SECONDS)  # Wait for a short duration
            await initial_message.delete()  # Delete the summary message

        except (
            Exception
        ) as e:  # Catch any unexpected exception in the main try block of the command
            error_message_content: str = (
                f"An error occurred during the jail role check: {e}"  # Format error message
            )
            self.logger.error(
                f"Jailcheck command error in {ctx.guild.name}: {e}", exc_info=True
            )  # Log the main error with traceback
            try:
                await initial_message.edit(
                    content=error_message_content
                )  # Try to edit the initial message to show the error
                await asyncio.sleep(TEMP_MESSAGE_DELAY_SECONDS)  # Wait
                await initial_message.delete()  # Delete
            except (
                discord.NotFound
            ):  # If initial_message was already deleted or not found
                pass  # Do nothing
            except Exception as edit_e:  # Catch other errors during edit
                self.logger.error(
                    f"Failed to edit jailcheck initial message with error: {edit_e}",
                    exc_info=True,
                )  # Log this error with traceback
        finally:
            try:
                await ctx.message.delete()  # Ensure the original command invocation message is deleted
            except discord.NotFound:  # If message already deleted
                pass  # Do nothing
            except Exception as del_e:  # Catch other errors during delete
                self.logger.error(
                    f"Failed to delete jailcheck invocation message: {del_e}",
                    exc_info=True,
                )  # Log this error with traceback

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Automatically removes roles from a member when the jail role is added to them."""
        if (
            after.guild.id not in self.config.allowed_servers
        ):  # Check if the update occurred in an allowed server
            return  # Exit if not an allowed server

        guild_jail_role: Optional[discord.Role] = await self.get_jail_role(
            after.guild
        )  # Get the jail role for the member's guild
        if not guild_jail_role:  # If jail role not found in the guild
            return  # Exit

        # Check if the jail role was newly added to the member (i.e., it's in 'after' roles but not 'before' roles)
        if guild_jail_role in after.roles and guild_jail_role not in before.roles:
            self.logger.info(
                f"Jail role added to {after.id}. Initiating automatic role removal."
            )  # Log role addition
            try:
                # Identify roles to remove: all roles except the jail role itself and the @everyone role
                roles_to_remove: List[discord.Role] = [
                    role
                    for role in after.roles
                    if role != guild_jail_role
                    and role.id != after.guild.default_role.id
                ]

                if roles_to_remove:  # If there are roles to remove
                    await after.remove_roles(
                        *roles_to_remove, reason="Jail role added automatically"
                    )  # Remove roles with a reason
                    self.logger.info(
                        f"Automatically removed {len(roles_to_remove)} roles from {after.id} after jail role addition."
                    )  # Log role removal

                    log_channel_instance: Optional[discord.TextChannel] = (
                        await self.get_log_channel(after.guild)
                    )  # Get the log channel for the guild
                    if log_channel_instance:  # If a valid log channel is available
                        role_names: str = ", ".join(
                            role.name for role in roles_to_remove
                        )  # Create string of removed role names
                        log_message: str = (  # Format the log message
                            f"🔒 Automatic Role Removal:\n"
                            f"• User: {after.mention} (ID: {after.id})\n"
                            f"• Roles Removed: {role_names}\n"
                            f"• Reason: Jail role added"
                        )
                        await log_channel_instance.send(
                            log_message
                        )  # Send the log message
                        self.logger.info(
                            f"Logged automatic role removal for {after.id}."
                        )  # Log successful logging
            except discord.Forbidden:  # Catch Forbidden error if bot lacks permissions
                self.logger.error(
                    f"Bot lacks permissions to remove roles from {after.name} ({after.id}) in {after.guild.name} (on_member_update) due to permissions.",
                    exc_info=True,
                )  # Log permission error with traceback
            except Exception as e:  # Catch any other unexpected exception
                self.logger.error(
                    f"Error in role removal for {after.name} ({after.id}) in {after.guild.name} (on_member_update): {e}",
                    exc_info=True,
                )  # Log generic error with traceback

    @commands.command(name="scanprofiles")
    @commands.has_guild_permissions(
        manage_roles=True
    )  # Requires 'Manage Roles' permission
    async def scan_profiles(self, ctx: commands.Context) -> None:
        """Scans user profiles (usernames/nicknames, bio, pronouns) for suspicious keywords and reports findings."""
        if (
            ctx.guild.id not in self.config.allowed_servers
        ):  # Check if the command is used in an allowed server
            await self.send_temp_message(
                ctx, "You do not have permission to use this command in this server."
            )  # Inform user
            return  # Exit the command

        initial_message: discord.Message = await ctx.send(
            "Scanning user profiles for suspicious keywords..."
        )  # Send an initial processing message
        found_users_data: List[UserProfileScanResult] = (
            []
        )  # List to store results for users found with keywords

        guild_jail_role: Optional[discord.Role] = await self.get_jail_role(
            ctx.guild
        )  # Get the jail role for the current guild

        try:
            # Asynchronously fetch all members in the guild
            async for member in ctx.guild.fetch_members(limit=None):
                if (
                    guild_jail_role and guild_jail_role in member.roles
                ):  # Exclude members who are already jailed
                    continue  # Skip this member

                found_keywords_for_user: List[str] = (
                    []
                )  # List to store keywords found for the current user

                # Check username and nickname for suspicious keywords
                username_text: str = member.name.lower()
                if member.nick:
                    username_text += f" {member.nick.lower()}"

                found_keywords_for_user.extend(
                    [
                        keyword
                        for keyword in SUSPICIOUS_USERNAME_KEYWORDS
                        if keyword.lower() in username_text
                    ]
                )

                # Fetch user profile for bio and pronouns (this is a bot-level method)
                user_profile: Optional[discord.UserProfile] = None
                try:
                    user_profile = await self.bot.fetch_user_profile(
                        member.id
                    )  # Use bot.fetch_user_profile
                except (
                    discord.NotFound
                ):  # User profile might not exist or be accessible
                    self.logger.debug(
                        f"User profile not found for {member.id}. Skipping bio/pronouns check."
                    )  # Log debug info
                except Exception as e:
                    self.logger.error(
                        f"Error fetching user profile for {member.id}: {e}",
                        exc_info=True,
                    )  # Log error with traceback

                # Check bio and pronouns for suspicious keywords
                bio_pronouns_text: str = ""
                if user_profile and user_profile.bio:
                    bio_pronouns_text += f" {user_profile.bio.lower()}"
                if user_profile and user_profile.pronouns:
                    bio_pronouns_text += f" {user_profile.pronouns.lower()}"

                found_keywords_for_user.extend(
                    [
                        keyword
                        for keyword in SUSPICIOUS_BIO_PRONOUNS_KEYWORDS
                        if keyword.lower() in bio_pronouns_text
                    ]
                )

                # Combine found keywords and remove duplicates
                all_found_keywords_unique: List[str] = list(
                    set(found_keywords_for_user)
                )

                if (
                    all_found_keywords_unique
                ):  # If any keywords were found for this user
                    found_users_data.append(
                        UserProfileScanResult(
                            user=member, keywords=all_found_keywords_unique
                        )
                    )  # Add user and keywords to results

        except (
            discord.Forbidden
        ):  # Catch Forbidden error if bot lacks permissions to fetch members
            await self.send_temp_message(
                ctx, "Bot lacks permissions to fetch members for scanning."
            )  # Inform user
            self.logger.error(
                f"Bot lacks permissions to fetch members in guild {ctx.guild.id} for scanprofiles.",
                exc_info=True,
            )  # Log error with traceback
            await initial_message.delete()  # Delete initial message
            await ctx.message.delete()  # Delete command message
            return
        except Exception as e:  # Catch any other unexpected exception during scanning
            await self.send_temp_message(
                ctx, f"An unexpected error occurred during profile scan: {e}"
            )  # Inform user
            self.logger.error(
                f"Unexpected error during profile scan in guild {ctx.guild.id}: {e}",
                exc_info=True,
            )  # Log error with traceback
            await initial_message.delete()  # Delete initial message
            await ctx.message.delete()  # Delete command message
            return

        # Report findings to the user
        if found_users_data:  # If any users were found with suspicious keywords
            report_content: str = (
                "Found users with suspicious keywords in their profile:\n"  # Start building the report
            )
            for entry in found_users_data:  # Iterate through the found users
                report_content += f"• {entry.user.name} (ID: {entry.user.id}): {', '.join(entry.keywords)}\n"  # Add user details and keywords

            tmp_file_path: Optional[pathlib.Path] = (
                None  # Initialize temporary file path
            )
            try:
                # Create a temporary file to store the report
                with tempfile.NamedTemporaryFile(
                    mode="w+", delete=False, encoding="utf-8", suffix=".txt"
                ) as tmp_file:
                    tmp_file.write(
                        report_content
                    )  # Write the report content to the file
                    tmp_file_path = pathlib.Path(
                        tmp_file.name
                    )  # Get the path of the temporary file

                # Determine the target channel for the report (log channel if available, otherwise command context channel)
                log_channel_instance: Optional[discord.TextChannel] = (
                    await self.get_log_channel(ctx.guild)
                )
                target_channel: discord.abc.Messageable = (
                    log_channel_instance if log_channel_instance else ctx.channel
                )

                await self.send_with_retry(  # Send the report message with the attached file
                    target_channel,
                    f"Scan complete. Found {len(found_users_data)} user(s) with suspicious keywords. Report attached.",
                    tmp_file_path,
                )
                self.logger.info(
                    f"Sent profile scan report to channel {target_channel.id}."
                )  # Log successful report send
            except (
                Exception
            ) as e:  # Catch any exception during file creation or sending
                self.logger.error(
                    f"Error creating or sending scan report file: {e}", exc_info=True
                )  # Log error with traceback
                # Fallback to sending content directly if file sending fails (may be truncated due to Discord's message limit)
                await self.send_temp_message(
                    ctx,
                    "Scan complete. An error occurred while sending the report file. Here's the raw data (may be truncated):\n"
                    + report_content[:1900],
                )
            finally:
                if (
                    tmp_file_path and tmp_file_path.exists()
                ):  # Ensure the temporary file is cleaned up
                    os.remove(tmp_file_path)  # Remove the temporary file
                    self.logger.debug(
                        f"Cleaned up temporary report file: {tmp_file_path}."
                    )  # Log temp file cleanup
            await initial_message.delete()  # Delete the initial processing message
        else:  # If no users were found with keywords
            await initial_message.edit(
                content="Scan complete. No users found with suspicious keywords."
            )  # Edit the initial message to indicate no findings
            await asyncio.sleep(TEMP_MESSAGE_DELAY_SECONDS)  # Wait for a short duration
            await initial_message.delete()  # Delete the initial message

        await ctx.message.delete()  # Delete the command invocation message


async def setup(bot: commands.Bot) -> None:
    """Adds the JailUser cog to the bot during startup."""
    await bot.add_cog(JailUser(bot))  # Adds an instance of the JailUser cog to the bot
