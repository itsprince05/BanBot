import os
import sys
import subprocess
import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
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

GROUP_ID = -1003552827391

@bot.on_message(filters.command("update") & filters.chat(GROUP_ID))
async def update_command(client: Client, message: Message):
    is_admin = False
    
    if message.from_user:
        try:
            member = await client.get_chat_member(GROUP_ID, message.from_user.id)
            if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                is_admin = True
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
    elif message.sender_chat and message.sender_chat.id == GROUP_ID:
        # User is anonymous admin
        is_admin = True
        
    if not is_admin:
        await message.reply("Only admins can use this command.")
        return
        
    msg = await message.reply("Pulling latest code...")
    try:
        process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate()
        success_text = f"Git pull done:\n```\n{out}\n```\nRestarting..."
        await msg.edit_text(success_text)
    except Exception as e:
        await msg.edit_text(f"Error during git pull: {e}")
        return
        
    # Restart the bot
    os.execl(sys.executable, sys.executable, *sys.argv)

async def main():
    try:
        await bot.send_message(GROUP_ID, "Bot is running...")
    except Exception as e:
        logger.error(f"Failed to send startup msg: {e}")
    
    from pyrogram import idle
    await idle()

if __name__ == "__main__":
    logger.info("Bot is starting... (All previous complex logic removed)")
    bot.run(main())
