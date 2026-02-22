import os
import sys
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus
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

@bot.on_message(filters.command("update") & filters.chat(config.ADMIN_GROUP_ID))
async def update_command(client: Client, message: Message):
    # Check if the user is an admin in the group
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return await message.reply("You must be an admin to use this command.")

    m = await message.reply("Pulling updates from git...")
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
        
        # Save restart state point
        with open("restart.txt", "w") as f:
            f.write(f"{message.chat.id}\n{m.id}")
            
        await bot.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await m.edit(f"Failed to update: {e}")

async def main():
    logger.info("Starting Bot...")
    await bot.start()
    
    # Check if we just restarted from an update
    if os.path.exists("restart.txt"):
        try:
            with open("restart.txt", "r") as f:
                chat_id, msg_id = f.read().splitlines()
                
            try:
                await bot.edit_message_text(int(chat_id), int(msg_id), "Update successful!")
            except Exception:
                pass
                
            await bot.send_message(int(chat_id), "Bot is running...")
        except Exception as e:
            logger.error(f"Failed to send restart message: {e}")
        finally:
            if os.path.exists("restart.txt"):
                os.remove("restart.txt")
                
    logger.info("Bot is idle and ready.")
    await pyrogram.idle() if 'pyrogram' in globals() else await idle_fallback()

async def idle_fallback():
    import pyrogram
    await pyrogram.idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
