import os
import sys
import asyncio
import logging
from pyrogram import Client, filters, idle
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

def auth_filter(_, __, message: Message):
    if not message.chat:
        return False
    # Only allow messages from the specified admin group
    if config.ADMIN_GROUP_ID and message.chat.id == config.ADMIN_GROUP_ID:
        return True
    return False

auth = filters.create(auth_filter)

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

@bot.on_message(filters.command("update") & auth)
async def update_command(client: Client, message: Message):
    m = await message.reply("Pulling updates from repository...")
    try:
        process = await asyncio.create_subprocess_shell(
            "git pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = (stdout.decode() + stderr.decode()).strip()
        
        if "Already up to date." in output:
            return await m.edit("Bot is already up to date.")
            
        await m.edit(f"Update pulled successfully. Restarting bot...\n\n`{output[:1000]}`")
        
        with open("restart.txt", "w") as f:
            f.write(f"{message.chat.id}")
            
        await bot.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await m.edit(f"Failed to update: {e}")

@bot.on_message(filters.command("restart") & auth)
async def restart_command(client: Client, message: Message):
    m = await message.reply("Restarting bot...")
    try:
        with open("restart.txt", "w") as f:
            f.write(f"{message.chat.id}")
            
        await bot.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await m.edit(f"Failed to restart: {e}")

async def main():
    logger.info("Bot is starting...")
    await bot.start()
    
    if os.path.exists("restart.txt"):
        try:
            with open("restart.txt", "r") as f:
                chat_id = f.read().strip()
            
            if chat_id:
                await bot.send_message(int(chat_id), "Bot is running...")
        except Exception as e:
            logger.error(f"Failed to send restart message: {e}")
        finally:
            if os.path.exists("restart.txt"):
                os.remove("restart.txt")
                
    logger.info("Bot is idle and listening for commands...")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped silently.")
