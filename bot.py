import os
import sys
import subprocess
import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message
from pyrogram.errors import SessionPasswordNeeded
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Bot")

GROUP_ID = -1003552827391

login_states = {}

class BotClient(Client):
    async def start(self):
        await super().start()
        logger.info("Bot started successfully.")
        # Send startup message only if restarted via /update command
        if os.environ.get("BOT_JUST_UPDATED") == "1":
            try:
                chat_id = int(os.environ.get("BOT_UPDATE_CHAT_ID", GROUP_ID))
                msg_id = int(os.environ.get("BOT_UPDATE_MSG_ID", 0))
                if msg_id:
                    await self.edit_message_text(chat_id, msg_id, "Updated\nRestarting...\nBot is live...")
                else:
                    await self.send_message(GROUP_ID, "Bot is live...")
            except Exception as e:
                logger.error(f"Failed to send startup message: {e}")
            os.environ.pop("BOT_JUST_UPDATED", None)
            os.environ.pop("BOT_UPDATE_CHAT_ID", None)
            os.environ.pop("BOT_UPDATE_MSG_ID", None)

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
    Replies: Hi {username}
    """
    if message.from_user:
        name = message.from_user.username if message.from_user.username else message.from_user.first_name
    elif message.sender_chat:
        name = message.sender_chat.username if message.sender_chat.username else message.sender_chat.title
    else:
        name = "User"
        
    await message.reply(f"Hi {name}")

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
        
    msg = await message.reply("Updating latest code...")
    try:
        process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate()
        success_text = f"Updated\nRestarting..."
        await msg.edit_text(success_text)
    except Exception as e:
        await msg.edit_text(f"Error during update: {e}")
        return
        
    # Restart the bot
    os.environ["BOT_JUST_UPDATED"] = "1"
    os.environ["BOT_UPDATE_CHAT_ID"] = str(msg.chat.id)
    os.environ["BOT_UPDATE_MSG_ID"] = str(msg.id)
    os.execl(sys.executable, sys.executable, *sys.argv)

@app.on_message(filters.command("login") & filters.chat(GROUP_ID))
async def login_command(client: Client, message: Message):
    """
    /login command to create and save a Pyrogram user session inside the group.
    """
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
        
    if user_id in login_states:
        await message.reply("Login process is already running. Send /cancel to stop it.")
        return
        
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    try:
        await user_client.connect()
    except Exception as e:
        await message.reply(f"Error initializing client: {e}")
        return
        
    try:
        if await user_client.get_me():
            await message.reply("Already logged in.")
            await user_client.disconnect()
            return
    except Exception:
        # Not logged in or session expired
        pass
        
    login_states[user_id] = {
        'step': 'AWAITING_PHONE',
        'client': user_client
    }
    await message.reply("Please send your phone number with country code (e.g. +919876543210).")

@app.on_message(filters.command("cancel") & filters.chat(GROUP_ID))
async def cancel_login(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
        
    if user_id in login_states:
        user_client = login_states[user_id]['client']
        if user_client.is_connected:
            await user_client.disconnect()
        del login_states[user_id]
        await message.reply("Login process cancelled.")
    else:
        await message.reply("No login process is currently running.")

@app.on_message(filters.chat(GROUP_ID) & filters.text & ~filters.command(["login", "cancel", "start", "update"]))
async def handle_login_steps(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id or user_id not in login_states:
        return
        
    state = login_states[user_id]
    step = state['step']
    user_client = state['client']
    text = message.text
    
    if step == 'AWAITING_PHONE':
        phone = text.strip()
        state['phone'] = phone
        try:
            sent_code = await user_client.send_code(phone)
            state['phone_code_hash'] = sent_code.phone_code_hash
            state['step'] = 'AWAITING_CODE'
            await message.reply("Code sent! Please enter the code. If your code is 12345, please send it with a space like 1 2 3 4 5 so telegram doesn't expire it.")
        except Exception as e:
            await message.reply(f"Error sending code: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
            
    elif step == 'AWAITING_CODE':
        code = text.replace(" ", "")
        phone = state['phone']
        phone_code_hash = state['phone_code_hash']
        
        try:
            await user_client.sign_in(phone, phone_code_hash, code)
            await message.reply("Login successful! Session saved as 'user_session.session'.")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
        except SessionPasswordNeeded:
            state['step'] = 'AWAITING_PASSWORD'
            await message.reply("2-Step Verification is enabled. Please enter your password.")
        except Exception as e:
            await message.reply(f"Error signing in: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
            
    elif step == 'AWAITING_PASSWORD':
        password = text.strip()
        try:
            await user_client.check_password(password)
            await message.reply("Login successful! Session saved as 'user_session.session'.")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
        except Exception as e:
            await message.reply(f"Error checking password: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]

if __name__ == "__main__":
    app.run()
