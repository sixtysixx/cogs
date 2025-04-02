import discord
from redbot.core import commands
from groq import Groq
import asyncio
import logging
from dotenv import load_dotenv
import os

load_dotenv()


class bchat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_histories = {}
        self.ai_channel_id = 1306745560077959199  # Specific channel ID
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.system_prompt = """You are a business assistant chatbot dedicated to helping users with a wide range of business-related inquiries. Your key responsibilities include:

    Providing Accurate and Relevant Information:
        Ensure your responses are precise and directly address the user's questions.
        Verify the information you provide to maintain reliability.

    Maintaining a Friendly and Professional Tone:
        Create a welcoming atmosphere for users by using a warm and professional demeanor.
        Acknowledge user concerns and express your eagerness to assist.

    Requesting Clarification When Necessary:
        If you encounter insufficient information to provide a complete answer, politely ask the user for more details or clarification.
        Use open-ended questions to encourage users to share additional context.

    Delivering Detailed and Actionable Responses:
        Break down complex topics into clear, manageable steps.
        Utilize bullet points or numbered lists to enhance readability and comprehension.
        Ensure that your answers include practical advice or next steps when applicable.

    Ensuring Consistency and Reliability:
        Maintain a consistent approach in your responses to build user trust.
        Regularly update your knowledge base to provide the most current and accurate information.

"""
        self.logger = logging.getLogger(__name__)

    async def generate_ai_response(self, user_id, message):
        """Centralized method to generate AI response"""
        try:
            # Limit conversation history to prevent excessive token usage
            if len(self.user_histories.get(user_id, [])) > 10:
                self.user_histories[user_id] = self.user_histories[user_id][-10:]

            # Add user message to history
            if user_id not in self.user_histories:
                self.user_histories[user_id] = []
            self.user_histories[user_id].append({"role": "user", "content": message})

            # Prepare messages for API call
            messages = [
                {"role": "system", "content": self.system_prompt},
                *self.user_histories[user_id],
            ]

            # Generate response with timeout
            async with asyncio.timeout(60):
                completion = await asyncio.to_thread(
                    self.groq_client.chat.completions.create,
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.5,
                    max_tokens=8000,
                    top_p=0.5,
                    stream=False,
                )

            # Extract and store AI response
            full_response = completion.choices[0].message.content
            self.user_histories[user_id].append(
                {"role": "assistant", "content": full_response}
            )

            return full_response

        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout for user {user_id}")
            return "Request timed out. Please try again later."
        except Exception as e:
            self.logger.error(f"AI generation error: {e}")
            return f"An error occurred: {str(e)}"

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listener to handle messages in the specific AI channel"""
        # Ignore messages from bots and in other channels
        if message.author.bot or message.channel.id != self.ai_channel_id:
            return

        # Process the message as an AI chat request
        try:
            # Send processing indicator
            processing_msg = await message.channel.send(
                f"{message.author.mention} Processing your request..."
            )

            # Generate AI response
            response = await self.generate_ai_response(
                message.author.id, message.content
            )
            await processing_msg.delete()

            # Split and send response
            chunks = [response[i : i + 4000] for i in range(0, len(response), 4000)]
            for chunk in chunks:
                embed = discord.Embed(
                    title="AI Business Assistant",
                    description=chunk,
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="Use !!clearbchat to reset conversation")

                # Reply directly to the user
                await message.reply(embed=embed)

        except Exception as e:
            await message.channel.send(
                f"{message.author.mention} An unexpected error occurred: {e}"
            )

    @commands.command(name="bchat")
    async def code(self, ctx, *, message):
        """Traditional chat command"""
        processing_msg = await ctx.send("Processing your request...")

        try:
            response = await self.generate_ai_response(ctx.author.id, message)
            await processing_msg.delete()

            # Split and send response
            chunks = [response[i : i + 2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                embed = discord.Embed(
                    title="AI Business Assistant",
                    description=chunk,
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="Use !!clearbchat to reset conversation")
                await ctx.send(embed=embed)

        except Exception as e:
            await processing_msg.delete()
            await ctx.send(f"An unexpected error occurred: {e}")

    @commands.command(name="clearbchat")
    async def clear_history(self, ctx):
        """Clear individual user's chat history"""
        user_id = ctx.author.id
        if user_id in self.user_histories:
            del self.user_histories[user_id]
            await ctx.send("Conversation history cleared.", delete_after=5)
        else:
            await ctx.send("No conversation history found.", delete_after=5)

    @commands.command(name="wipecbc")
    @commands.is_owner()
    async def wipe_all_history(self, ctx):
        """Wipe all conversation histories (owner-only)"""
        self.user_histories.clear()
        await ctx.send("All conversation histories have been wiped.")


async def setup(bot):
    await bot.add_cog(bchat(bot))
