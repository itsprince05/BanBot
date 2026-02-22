import os
import sys
import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import Message, BotCommand
from pyrogram.enums import ChatType
from pyrogram.errors import (
    FloodWait, UserAdminInvalid, PeerIdInvalid, RPCError,
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
)
import config

API_ID = config.API_ID
API_HASH = config.API_HASH
BOT_TOKEN = config.BOT_TOKEN
ADMIN_GROUP_ID = config.ADMIN_GROUP_ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BanBot")

# Automatically generate SQLite session instead of SESSION_STRING
userbot = Client(
    "userbot_session",
    api_id=API_ID,
    api_hash=API_HASH
)

bot = Client(
    "controller_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

user_states = {}
login_states = {}

def auth_filter(_, __, message: Message):
    if not message.chat:
        return False
        
    # Temporary log to help us see WHAT group ID the bot is actually seeing vs what we set
    logger.info(f"Received message in Chat ID: {message.chat.id} | Allowed Group ID: {ADMIN_GROUP_ID}")
    
    # Only allow messages from the specified admin group
    if ADMIN_GROUP_ID and message.chat.id == ADMIN_GROUP_ID:
        return True
    return False

auth = filters.create(auth_filter)


# ================= LOGIN FLOW ================= #

@bot.on_message(filters.command("start") & auth)
async def start_command(client: Client, message: Message):
    await message.reply(
        "Welcome to the BanBot Controller!\n\n"
        "Commands:\n"
        "- `/login` - Login to the Userbot (Scout) account\n"
        "- `/groups` - List your admin groups\n"
        "- `/channels` - List your admin channels\n"
        "- `/update` - Update bot from git repo & restart\n"
        "- `/restart` - Restart the bot process\n"
    )

@bot.on_message(filters.command("login") & auth)
async def login_command(client: Client, message: Message):
    admin_id = message.from_user.id
    
    # Check if userbot is already logged in conceptually
    try:
        if not userbot.is_connected:
            await userbot.connect()
        me = await userbot.get_me()
        return await message.reply(f"Userbot is already logged in as {me.first_name} (@{me.username}).")
    except Exception:
        pass # Not logged in

    login_states[admin_id] = {"step": "PHONE"}
    await message.reply(
        "**Userbot Login**\n\n"
        "Please reply with the **phone number** associated with your Telegram account including the country code.\n"
        "Example: `+919876543210`\n\n"
        "Send `/cancel` at any time to abort."
    )

@bot.on_message(filters.text & auth, group=1)
async def handle_login_steps(client: Client, message: Message):
    admin_id = message.from_user.id
    if admin_id not in login_states:
        return message.continue_propagation()
        
    state = login_states[admin_id]
    step = state["step"]
    text = message.text.strip()
    
    # Ignore and handle commands during login flow
    if text.startswith("/"):
        if text == "/cancel":
            del login_states[admin_id]
            await message.reply("Login process cancelled.")
            message.stop_propagation()
        else:
            await message.reply("Please complete the login process or use `/cancel`.")
            message.stop_propagation()
    
    if step == "PHONE":
        if not text.startswith("+") and not text.isdigit():
            await message.reply("Invalid phone format. Try again (e.g., `+919876543210`).")
            message.stop_propagation()
            
        msg = await message.reply("Sending OTP code to your account...")
        try:
            if not userbot.is_connected:
                await userbot.connect()
                
            sent_code = await userbot.send_code(text)
            state["phone"] = text
            state["phone_code_hash"] = sent_code.phone_code_hash
            state["step"] = "OTP"
            
            await msg.edit_text(
                "OTP code sent securely to your Telegram app.\n\n"
                "**IMPORTANT:** To prevent Telegram from deleting the OTP, please send it with spaces between each digit!\n"
                "Example: If your OTP is `12345`, send `1 2 3 4 5`"
            )
        except Exception as e:
            del login_states[admin_id]
            # Safety disconnect to avoid connection hoarding
            if userbot.is_connected:
                await userbot.disconnect()
            await msg.edit_text(f"Failed to send code: {e}\n\nPlease try `/login` again.")
            
    elif step == "OTP":
        # Handle spaced OTP like 1 2 3 4 5
        clean_code = text.replace(" ", "")
        
        if not clean_code.isdigit():
            await message.reply("OTP should only contain numbers. Please send it with spaces like `1 2 3 4 5`.")
            message.stop_propagation()
            
        msg = await message.reply("Verifying OTP...")
        try:
            await userbot.sign_in(state["phone"], state["phone_code_hash"], clean_code)
            del login_states[admin_id]
            
            # Start the userbot properly
            await userbot.disconnect()
            await userbot.start()
            
            me = await userbot.get_me()
            await msg.edit_text(f"Login successful! Userbot is ready.\nLogged in as: **{me.first_name}**")
        except SessionPasswordNeeded:
            state["step"] = "PASSWORD"
            await msg.edit_text("Two-Step Verification is enabled. Please enter your Password.")
        except PhoneCodeInvalid:
            await msg.edit_text("Invalid OTP. Please try again or use `/cancel`.")
        except PhoneCodeExpired:
            del login_states[admin_id]
            if userbot.is_connected:
                await userbot.disconnect()
            await msg.edit_text("OTP expired. Please start over with `/login`.")
        except Exception as e:
            del login_states[admin_id]
            if userbot.is_connected:
                await userbot.disconnect()
            await msg.edit_text(f"Login failed: {e}")
            
    elif step == "PASSWORD":
        msg = await message.reply("Verifying password...")
        try:
            await userbot.check_password(text)
            del login_states[admin_id]
            
            await userbot.disconnect()
            await userbot.start()
            
            me = await userbot.get_me()
            await msg.edit_text(f"Login successful! Userbot is ready.\nLogged in as: **{me.first_name}**")
        except Exception as e:
            await msg.edit_text(f"Password verification failed: {e}\nPlease try again or use `/cancel`.")
            
    message.stop_propagation()


# ================= REST OF THE LOGIC ================= #

async def fetch_admin_chats(chat_type: str):
    """Fetches chats where the userbot is an admin with restrict powers."""
    admin_chats = []
    if not getattr(userbot, "me", None): # Fast check if initialized
        return admin_chats
        
    async for dialog in userbot.get_dialogs():
        chat = dialog.chat
        
        is_target_type = False
        if chat_type == "group" and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            is_target_type = True
        elif chat_type == "channel" and chat.type == ChatType.CHANNEL:
            is_target_type = True
            
        if is_target_type:
            try:
                member = await userbot.get_chat_member(chat.id, "me")
                if member.privileges and member.privileges.can_restrict_members:
                    admin_chats.append(chat)
            except Exception:
                pass
                
    return admin_chats

@bot.on_message(filters.command("groups") & auth)
async def list_groups(client: Client, message: Message):
    if not getattr(userbot, "me", None):
        return await message.reply("Userbot is not logged in. Please use /login first.")
        
    m = await message.reply("Fetching groups where you have 'Ban' privileges...")
    groups = await fetch_admin_chats("group")
    
    if not groups:
        return await m.edit("No groups found where you have ban privileges.")
        
    text = "**Group List:**\n\n"
    for g in groups:
        member_count = g.members_count if g.members_count else "?"
        text += f"/ban_{g.id} | [{member_count}] | {g.title}\n"
        
    await m.edit(text[:4096])

@bot.on_message(filters.command("channels") & auth)
async def list_channels(client: Client, message: Message):
    if not getattr(userbot, "me", None):
        return await message.reply("Userbot is not logged in. Please use /login first.")
        
    m = await message.reply("Fetching channels where you have 'Ban' privileges...")
    channels = await fetch_admin_chats("channel")
    
    if not channels:
        return await m.edit("No channels found where you have ban privileges.")
        
    text = "**Channel List:**\n\n"
    for c in channels:
        member_count = c.members_count if c.members_count else "?"
        text += f"/ban_{c.id} | [{member_count}] | {c.title}\n"
        
    await m.edit(text[:4096])

@bot.on_message(filters.regex(r"^/ban_(-?\d+)") & auth)
async def ban_target_selection(client: Client, message: Message):
    if not getattr(userbot, "me", None):
        return await message.reply("Userbot is not logged in. Please use /login first.")
        
    chat_id_str = message.matches[0].group(1)
    
    try:
        chat_id = int(chat_id_str)
        chat = await userbot.get_chat(chat_id)
        chat_name = chat.title
    except Exception as e:
        return await message.reply(f"Failed to fetch chat details. Error: {e}")
        
    user_states[message.from_user.id] = {
        "target_chat_id": chat_id,
        "chat_name": chat_name
    }
    
    reply_text = (f"Target set to **{chat_name}**.\n\n"
                  f"To ban fetched members, **reply to this message with the NUMBER** of bans.\n"
                  f"To ban from a custom list, **reply to this message by uploading a .txt file** containing one User ID per line.")
                 
    await message.reply(reply_text)

@bot.on_message(filters.reply & auth)
async def handle_ban_execution(client: Client, message: Message):
    admin_id = message.from_user.id
    
    if admin_id not in user_states:
        return
        
    # Check if they are replying to our interaction prompt
    if not message.reply_to_message or message.reply_to_message.from_user.id != client.me.id:
        return

    target_chat_id = user_states[admin_id]["target_chat_id"]
    chat_name = user_states[admin_id]["chat_name"]
    
    target_ids = []
    
    if message.document and message.document.file_name.endswith(".txt"):
        msg = await message.reply("Downloading and reading file...")
        file_path = await message.download()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.isdigit() or (line.startswith("-") and line[1:].isdigit()):
                        target_ids.append(int(line))
        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            return await msg.edit(f"Error reading file: {e}")
            
        if os.path.exists(file_path):
            os.remove(file_path)
        await msg.edit(f"Loaded {len(target_ids)} IDs from file.")
        
    elif message.text and message.text.isdigit():
        limit = int(message.text)
        msg = await message.reply(f"Fetching up to {limit} members from {chat_name} using Userbot...")
        try:
            async for member in userbot.get_chat_members(target_chat_id, limit=limit):
                if not member.user.is_bot and not member.user.is_self:
                    target_ids.append(member.user.id)
        except Exception as e:
            return await msg.edit(f"Error fetching members: {e}")
            
        await msg.edit(f"Fetched {len(target_ids)} members.")
    else:
        return

    if not target_ids:
        return await message.reply("No targets to ban. Ensure the list has valid IDs.")

    progress_msg = await message.reply("Starting...")
    
    successful_bans = 0
    failed_bans = 0
    total = len(target_ids)
    
    del user_states[admin_id]

    for i, user_id in enumerate(target_ids, 1):
        try:
            await client.ban_chat_member(target_chat_id, user_id)
            successful_bans += 1
            await asyncio.sleep(0.5)
            
            if successful_bans > 0 and successful_bans % 20 == 0:
                await asyncio.sleep(5)
                
        except FloodWait as e:
            logger.warning(f"FloodWait of {e.value} seconds encountered. Sleeping...")
            await asyncio.sleep(e.value + 2)
            try:
                await client.ban_chat_member(target_chat_id, user_id)
                successful_bans += 1
                await asyncio.sleep(0.5)
            except Exception as retry_e:
                failed_bans += 1
                logger.error(f"Failed ban on wait recovery for {user_id}: {retry_e}")
                
        except (UserAdminInvalid, PeerIdInvalid, RPCError) as e:
            failed_bans += 1
            logger.debug(f"Skipped {user_id}: {e}")
        except Exception as e:
            failed_bans += 1
            logger.debug(f"Unexpected error skipping {user_id}: {e}")
            
        if i % 100 == 0:
            try:
                await progress_msg.edit_text(f"Progress: {i}/{total} processed...\n(Banned: {successful_bans} | Failed: {failed_bans})")
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass

    summary = (f"**Ban Execution Complete!**\n\n"
               f"Target: **{chat_name}**\n"
               f"Successfully Banned: **{successful_bans}**\n"
               f"Failed/Skipped: **{failed_bans}**\n"
               f"Total Processed: **{total}**")
               
    await progress_msg.reply(summary)


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
            f.write(f"{message.chat.id}\n{m.id}")
            
        if getattr(userbot, "is_connected", False):
            await userbot.stop()
        await bot.stop()
        
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await m.edit(f"Failed to update: {e}")

@bot.on_message(filters.command("restart") & auth)
async def restart_command(client: Client, message: Message):
    m = await message.reply("Restarting bot...")
    try:
        with open("restart.txt", "w") as f:
            f.write(f"{message.chat.id}\n{m.id}")
            
        if getattr(userbot, "is_connected", False):
            await userbot.stop()
        await bot.stop()
        
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await m.edit(f"Failed to restart: {e}")


async def main():
    logger.info("Starting Controller Bot...")
    await bot.start()
    
    if os.path.exists("restart.txt"):
        try:
            with open("restart.txt", "r") as f:
                chat_id, msg_id = f.read().splitlines()
            try:
                await bot.edit_message_text(int(chat_id), int(msg_id), "Done!")
            except Exception:
                pass
            await bot.send_message(int(chat_id), "Bot is restarted...")
        except Exception as e:
            logger.error(f"Failed to send restart message: {e}")
        finally:
            if os.path.exists("restart.txt"):
                os.remove("restart.txt")
                
    # Setup Telegram Bot Menu Commands natively
    try:
        await bot.set_bot_commands([
            BotCommand("start", "Show the welcome message and commands"),
            BotCommand("login", "Login to the Userbot (Scout) account"),
            BotCommand("groups", "List your admin groups"),
            BotCommand("channels", "List your admin channels"),
            BotCommand("update", "Update bot from git repo & restart"),
            BotCommand("restart", "Restart the bot process")
        ])
    except Exception as e:
        logger.warning(f"Failed to set bot commands menu: {e}")
    
    logger.info("Checking Userbot Session...")
    try:
        await userbot.connect()
        me = await userbot.get_me()
        await userbot.disconnect()
        
        await userbot.start()
        logger.info(f"Userbot is logged in as {me.first_name} and running.")
    except Exception as e:
        if getattr(userbot, "is_connected", False):
            await userbot.disconnect()
        logger.info("Userbot NOT logged in. Message the Bot and send /login to authenticate.")
    
    logger.info("Bot is idle and listening for commands...")
    await idle()
    
    await bot.stop()
    if getattr(userbot, "is_connected", False):
        await userbot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped silently.")
