import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Bot")

# Initialize the Bot client
bot = Client(
    "controller_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

@bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    # Dhoondte hain user ka naam aur ID chahe wo normal user ho ya anonymous admin
    if message.from_user:
        name = message.from_user.first_name
        uid = message.from_user.id
    elif message.sender_chat:
        name = message.sender_chat.title
        uid = message.sender_chat.id
    else:
        name = "User"
        uid = message.chat.id
        
    # User ko normal text message reply karo
    await message.reply(f"Hi {name}\n{uid}")

if __name__ == "__main__":
    logger.info("Bot is starting... (All previous complex logic removed)")
    bot.run()
