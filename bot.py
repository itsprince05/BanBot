import os
import sys
import subprocess
import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
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
    os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)

@app.on_message(filters.command("check") & filters.chat(GROUP_ID))
async def check_command(client: Client, message: Message):
    """
    /check command. Scans dialogs of the logged-in user session instance.
    Lists groups/channels where user is admin AND @Ban_Karne_Wala_Bot is an admin with ban rights.
    """
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    
    status_msg = await message.reply("Checking all groups and channels...\nThis may take a minute...")
    result_list = []
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            raise Exception("Session expired or not logged in. Send /login first.")
            
        async for dialog in user_client.get_dialogs():
            if dialog.chat.id == GROUP_ID:
                continue
                
            if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
                chat = dialog.chat
                try:
                    user_member = await user_client.get_chat_member(chat.id, me.id)
                    if user_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                        # Now check if bot is admin and has ban rights
                        try:
                            bot_member = await user_client.get_chat_member(chat.id, "Ban_Karne_Wala_Bot")
                            if bot_member.status == ChatMemberStatus.ADMINISTRATOR:
                                if bot_member.privileges and bot_member.privileges.can_restrict_members:
                                    # Output format: `/<id>` <count> <name>
                                    # If members_count is not readily available, default to 0
                                    member_count = chat.members_count or 0
                                    title = chat.title or "Unknown"
                                    result_list.append(f"`/{chat.id}` {member_count} {title}")
                        except Exception:
                            # Bot might not be in the group, or missing privileges info, skip it
                            pass
                except Exception:
                    # User is not admin or missing info, skip
                    pass
    except Exception as e:
        await status_msg.edit_text(f"Error while checking: {e}")
        if user_client.is_connected:
            await user_client.disconnect()
        return
        
    if user_client.is_connected:
        await user_client.disconnect()
        
    if result_list:
        text = "\n\n".join(result_list)
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await message.reply(text[i:i+4000])
            await status_msg.delete()
        else:
            await status_msg.edit_text(text)
    else:
        await status_msg.edit_text("No groups or channels found where both you and @Ban_Karne_Wala_Bot are admins with ban rights.")

@app.on_message(filters.regex(r"^/(-\d+)(?:\s+(\d+))?$") & filters.chat(GROUP_ID))
async def fetch_members_command(client: Client, message: Message):
    """
    Fetches 'n' amount of UIDs from a given /<id> group or channel using the user session.
    """
    match = message.matches[0]
    chat_id = int(match.group(1))
    limit = int(match.group(2)) if match.group(2) else 100
    
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    status_msg = await message.reply(f"Fetching up to {limit} members from {chat_id}...")
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            raise Exception("Session expired or not logged in.")
            
        uids = []
        async for member in user_client.get_chat_members(chat_id, limit=limit):
            user = member.user
            if user:
                uids.append(str(user.id))
                
        if uids:
            text = "\n".join(uids)
            with open("members.txt", "w") as f:
                f.write(text)
            await message.reply_document("members.txt", caption=f"Fetched {len(uids)} UIDs from `{chat_id}`")
            os.remove("members.txt")
            await status_msg.delete()
        else:
            await status_msg.edit_text("No members found or couldn't fetch.")
            
    except Exception as e:
        await status_msg.edit_text(f"Error fetching members: {e}")
        
    finally:
        if user_client.is_connected:
            await user_client.disconnect()

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
