import os
import sys
import subprocess
import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Bot")

GROUP_ID = -1003552827391

class BotClient(Client):
    async def start(self):
        await super().start()
        logger.info("Bot started successfully.")
        # Send startup message only if restarted via /update command
        if os.environ.get("BOT_JUST_UPDATED") == "1":
            try:
                await self.send_message(GROUP_ID, "Bot is running...")
            except Exception as e:
                logger.error(f"Failed to send startup message: {e}")
            os.environ.pop("BOT_JUST_UPDATED", None)

# Initialize the Bot client
app = BotClient(
    "controller_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    """
    Working /start command handler.
    Replies: Bot is working successfully ✅
    """
    await message.reply("Bot is working successfully ✅")

@app.on_message(filters.command("update") & filters.chat(GROUP_ID))
async def update_command(client: Client, message: Message):
    """
    /update command for admins. Pulls latest changes from git and restarts.
    """
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
    os.environ["BOT_JUST_UPDATED"] = "1"
    os.execl(sys.executable, sys.executable, *sys.argv)

if __name__ == "__main__":
    app.run()
