import discord
from redbot.core import commands
from groq import Groq
import asyncio
import logging
from dotenv import load_dotenv
import os

load_dotenv()


class chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_histories = {}
        self.ai_channel_id = 1306745560077959199  # Specific channel ID
        self.groq_client = Groq(
            api_key=os.getenv("GROQ_API_KEY")
        )
        self.system_prompt = """You are an AI language model designed to understand and interpret slang from various cultures and communities. Your goal is to assist users with a variety of tasks.


    When a user asks a question or requests assistance, recognize any slang terms in their message without explicitly acknowledging them. Simply continue with the response.
    Let's think before we respond: Analyze the context of the user's message to understand their intent, tone, and any underlying emotions. Consider how these factors influence the meaning of their request.
    Respond in a friendly and relatable tone, using appropriate slang where suitable to connect with the user. Justify your choice of slang based on the user's tone and context.
    Ensure that your responses are accurate and relevant to the user's request by cross-referencing information from reliable sources when necessary. Explain your reasoning for the information provided.
    If the user's request involves multiple steps or components, break down your response into clear, manageable parts to enhance understanding and follow-through. Provide reasoning for each step to clarify its importance.
    Provide examples or suggestions that are relevant to the user's context to illustrate your points effectively. Explain why these examples are suitable.
    Encourage user engagement by asking follow-up questions or inviting them to share more about their needs or preferences. Use reasoning to guide your questions based on the user's previous responses.
    Maintain a respectful and inclusive tone, being mindful of diverse backgrounds and experiences.
    If uncertain about a slang term or context, acknowledge the ambiguity and offer to clarify or explore further with the user. Provide reasoning for why further exploration may be beneficial.
    Strive for stability in your responses by ensuring consistency in tone, style, and accuracy across interactions. Regularly assess the effectiveness of your communication and adjust as needed to maintain clarity and reliability."""
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
                *self.user_histories[user_id]
            ]

            # Generate response with timeout
            async with asyncio.timeout(60):
                completion = await asyncio.to_thread(
                    self.groq_client.chat.completions.create,
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.5,
                    max_tokens=16000,
                    top_p=0.5,
                    stream=False
                )

            # Extract and store AI response
            full_response = completion.choices[0].message.content
            self.user_histories[user_id].append({"role": "assistant", "content": full_response})

            return full_response

        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout for user {user_id}")
            return "Request timed out. Please try again later."
        except Exception as e:
            self.logger.error(f"AI generation error: {e}")
            return f"An error occurred: {str(e)}"

    @commands.command(name="chat")
    async def code(self, ctx, *, message):
        """Traditional chat command"""
        processing_msg = await ctx.send("Processing your request...")
        
        try:
            response = await self.generate_ai_response(ctx.author.id, message)
            await processing_msg.delete()

            # Split and send response
            chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                embed = discord.Embed(
                    title="AI Assistant", 
                    description=chunk, 
                    color=discord.Color.blue()
                )
                embed.set_footer(text="Use !!clearchat to reset conversation")
                await ctx.send(embed=embed)

        except Exception as e:
            await processing_msg.delete()
            await ctx.send(f"An unexpected error occurred: {e}")

    @commands.command(name="clearchat")
    async def clear_history(self, ctx):
        """Clear individual user's chat history"""
        user_id = ctx.author.id
        if user_id in self.user_histories:
            del self.user_histories[user_id]
            await ctx.send("Conversation history cleared.", delete_after=5)
        else:
            await ctx.send("No conversation history found.", delete_after=5)

    @commands.command(name="wipecc")
    @commands.is_owner()
    async def wipe_all_history(self, ctx):
        """Wipe all conversation histories (owner-only)"""
        self.user_histories.clear()
        await ctx.send("All conversation histories have been wiped.")

async def setup(bot):
    await bot.add_cog(chat(bot))