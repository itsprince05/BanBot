import os
import sys
import subprocess
import logging
import asyncio
import json
import urllib.request
import time
import http.client
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Message
from pyrogram.errors import SessionPasswordNeeded
from pyrogram.raw import functions, types
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Bot")

GROUP_ID = -1003552827391

login_states = {}
halt_ban = False

class BotClient(Client):
    async def start(self):
        await super().start()
        logger.info("Bot started successfully.")
        
        # Check command structure for restart tokens
        if "--updated" in sys.argv:
            try:
                idx = sys.argv.index("--updated")
                chat_id = int(sys.argv[idx + 1])
                msg_id = int(sys.argv[idx + 2])
                try:
                    await self.edit_message_text(chat_id, msg_id, "Updated\nRestarting...")
                except Exception as e:
                    logger.error(f"Failed to edit startup message: {e}")
                # Also send a new message indicating it has started up successfully
                await asyncio.sleep(2)
                await self.send_message(GROUP_ID, "Bot is Live...")
            except Exception as outer_e:
                logger.error(f"Failed to parse restart tokens: {outer_e}")
                try:
                    await asyncio.sleep(2)
                    await self.send_message(GROUP_ID, "Bot is Live...")
                except Exception:
                    pass
            finally:
                # Remove from sys.argv so it doesn't leak into further reloads if not handled
                idx = sys.argv.index("--updated")
                del sys.argv[idx:idx+3]

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
        
    await client.send_message(message.chat.id, f"Hi {name}")

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
        await client.send_message(message.chat.id, "Only admins can use this command...")
        return
        
    msg = await client.send_message(message.chat.id, "Updating latest code...")
    try:
        process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate()
        success_text = f"Updated\nRestarting..."
        await msg.edit_text(success_text)
    except Exception as e:
        await msg.edit_text(f"Error during update...")
        return
        
    # Restart the bot
    args = [sys.executable] + sys.argv
    # Clean up any existing --updated args to avoid duplicates
    if "--updated" in args:
        idx = args.index("--updated")
        del args[idx:idx+3]
        
    args.extend(["--updated", str(msg.chat.id), str(msg.id)])
    os.execl(sys.executable, *args)

@app.on_message(filters.command("check") & filters.chat(GROUP_ID))
async def check_command(client: Client, message: Message):
    """
    /check command. Scans dialogs of the logged-in user session instance.
    Lists groups/channels where user is admin AND @Ban_Karne_Wala_Bot is an admin with ban rights.
    """
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    
    status_msg = await client.send_message(message.chat.id, "Checking all groups and channels...\nThis may take a minute...")
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
                                    # Removing minus sign for cleaner pure ID copy/paste format
                                    raw_id = str(chat.id).replace("-", "")
                                    result_list.append(f"`{raw_id}`\n{member_count} members\n{title}")
                        except Exception:
                            # Bot might not be in the group, or missing privileges info, skip it
                            pass
                except Exception:
                    # User is not admin or missing info, skip
                    pass
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")
        if user_client.is_connected:
            await user_client.disconnect()
        return
        
    if user_client.is_connected:
        await user_client.disconnect()
        
    if result_list:
        text = "\n\n".join(result_list)
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                await client.send_message(message.chat.id, text[i:i+4000])
            await status_msg.delete()
        else:
            await status_msg.edit_text(text)
    else:
        await status_msg.edit_text("No groups or channels found where both you and Bot are admins with ban permissions...")

@app.on_message(filters.regex(r"^/(-\d+)(?:\s+(\d+))?$") & filters.chat(GROUP_ID))
async def fetch_members_command(client: Client, message: Message):
    """
    Fetches 'n' amount of UIDs from a given /<id> group or channel using the user session.
    """
    match = message.matches[0]
    chat_id = int(match.group(1))
        
    limit = int(match.group(2)) if match.group(2) else 100
    
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    status_msg = await client.send_message(message.chat.id, f"Fetching up to {limit} members from {chat_id}...")
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            raise Exception("Session expired or not logged in.")
            
        try:
            chat = await user_client.get_chat(chat_id)
        except Exception:
            await status_msg.edit_text("Caching peer info...")
            async for _ in user_client.get_dialogs(limit=200):
                pass
            chat = await user_client.get_chat(chat_id)
            
        await status_msg.edit_text(f"Fetching members from {chat.title or chat_id}...")
        
        uids = []
        async for member in user_client.get_chat_members(chat_id, limit=limit):
            user = member.user
            if user and member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                uids.append(str(user.id))
                
        if uids:
            text = "\n".join(uids)
            with open("members.txt", "w") as f:
                f.write(text)
            await client.send_document(message.chat.id, document="members.txt", caption=f"Fetched {len(uids)} UIDs from `{chat_id}`")
            os.remove("members.txt")
            await status_msg.delete()
        else:
            await status_msg.edit_text("No members found or couldn't fetch...")
            
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")
        
    finally:
        if user_client.is_connected:
            await user_client.disconnect()

@app.on_message(filters.command("stop") & filters.chat(GROUP_ID))
async def stop_command(client: Client, message: Message):
    global halt_ban
    halt_ban = True
    await client.send_message(message.chat.id, "Attempting to halt any active /ban processes... Please wait a few seconds...")

@app.on_message(filters.command("ban") & filters.chat(GROUP_ID))
async def ban_command(client: Client, message: Message):
    """
    /ban <group/channel id> <n>
    Fetches the member list using the user session, then the bot bans them individually
    with timing constraints (2 users/sec, 5s delay after every 20 users).
    """
    args = message.text.split()
    if len(args) < 3:
        await client.send_message(message.chat.id, "Usage: /ban <group_id> <limit or all>")
        return
        
    raw_id_str = args[1]
    limit_str = args[2].lower()
    
    if limit_str == "all":
        target_limit = float('inf')
    else:
        try:
            target_limit = int(limit_str)
        except Exception:
            await client.send_message(message.chat.id, "Limit must be a number or 'all'.")
            return
            
    # Restore the Telegram group negative prefix if User provided clean ID
    if not raw_id_str.startswith("-"):
        chat_id = int("-" + raw_id_str)
    else:
        chat_id = int(raw_id_str)
        
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    status_msg = await client.send_message(message.chat.id, f"Initializing ban process for {chat_id}...")
    
    global halt_ban
    halt_ban = False
    
    conn = http.client.HTTPSConnection("api.telegram.org")
    api_headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    
    async def ban_via_api(target_chat, target_user):
        data = json.dumps({"chat_id": target_chat, "user_id": target_user}).encode("utf-8")
        def do_request():
            try:
                conn.request("POST", f"/bot{config.BOT_TOKEN}/banChatMember", body=data, headers=api_headers)
                response = conn.getresponse()
                return json.loads(response.read().decode())
            except Exception:
                try:
                    conn.close()
                    conn.connect()
                    conn.request("POST", f"/bot{config.BOT_TOKEN}/banChatMember", body=data, headers=api_headers)
                    response = conn.getresponse()
                    return json.loads(response.read().decode())
                except Exception as e2:
                    return {"ok": False, "description": str(e2)}
        return await asyncio.to_thread(do_request)
        
    banned_count = 0
    fail_count = 0
    total_processed = 0
    
    seen_uids = set()
    global_start_t = time.time()
    last_progress_t = time.time()
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            raise Exception("Session expired or not logged in.")
            
        try:
            chat = await user_client.get_chat(chat_id)
        except Exception:
            await status_msg.edit_text("Caching peer info...")
            async for _ in user_client.get_dialogs(limit=200):
                pass
            chat = await user_client.get_chat(chat_id)
            
        await status_msg.edit_text(f"Starting chunked ban loops for {chat.title or chat_id}...")
        
        while total_processed < target_limit and not halt_ban:
            fetch_amount = min(100, target_limit - total_processed) if target_limit != float('inf') else 100
            
            uids = []
            try:
                # Always fetch and filter exactly 'fetch_amount' fresh non-admin users
                async for member in user_client.get_chat_members(chat_id):
                    if member.user and member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                        if member.user.id not in seen_uids:
                            uids.append(member.user.id)
                            seen_uids.add(member.user.id)
                            if len(uids) >= fetch_amount:
                                break
            except Exception as e:
                logger.error(f"Error fetching chunk: {e}")
                
            if not uids:
                # No more unbanned regular members exist / list completely exhausted
                break
                
            for uid in uids:
                if halt_ban:
                    break
                    
                start_t = time.time()
                try:
                    res = await ban_via_api(chat_id, uid)
                    if res.get("ok"):
                        banned_count += 1
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1
                    
                total_processed += 1
                elapsed = time.time() - start_t
                
                # Update progress every exact 5 seconds (Time based instead of loop based)
                current_t = time.time()
                if current_t - last_progress_t >= 5.0 or total_processed == target_limit:
                    try:
                        total_str = "All" if target_limit == float('inf') else str(target_limit)
                        rem_str = "Calculating..." if target_limit == float('inf') else str(target_limit - total_processed)
                        prog_text = (f"Ban Process Running\n\n"
                                     f"Total {total_str}\n"
                                     f"Banned {banned_count}\n"
                                     f"Remaining {rem_str}\n"
                                     f"Failed {fail_count}\n\n"
                                     f"Click /stop to stop runnning process...")
                        await status_msg.edit_text(prog_text)
                        last_progress_t = current_t
                    except Exception:
                        pass
                        
                # Preserve 2 bans per second strict rate limit, without dropping to any 5 second break bounds
                if not halt_ban:
                    await asyncio.sleep(max(0, 0.5 - elapsed))
                    
    except Exception as e:
        await status_msg.edit_text(f"Error during ban loop process: {e}")
    finally:
        if user_client.is_connected:
            await user_client.disconnect()
            
    time_taken = int(time.time() - global_start_t)
    if time_taken < 60:
        time_str = f"{time_taken} seconds"
    elif time_taken < 3600:
        mins = time_taken // 60
        secs = time_taken % 60
        time_str = f"{mins}:{secs:02d}"
    else:
        hrs = time_taken // 3600
        mins = (time_taken % 3600) // 60
        secs = time_taken % 60
        time_str = f"{hrs}:{mins:02d}:{secs:02d}"
            
    if halt_ban:
        final_text = "Ban Process Stopped\n\n"
    else:
        final_text = "Ban Process Completed\n\n"
        
    total_final_str = "All" if target_limit == float('inf') else str(target_limit)
    final_text += (f"Total {total_final_str}\n"
                   f"Banned {banned_count}\n"
                   f"Failed {fail_count}\n\n"
                   f"Time Taken {time_str}")
        
    try:
        await status_msg.edit_text(final_text)
    except Exception:
        pass

@app.on_message(filters.command("login") & filters.chat(GROUP_ID))
async def login_command(client: Client, message: Message):
    """
    /login command to create and save a Pyrogram user session inside the group.
    """
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
        
    if user_id in login_states:
        await client.send_message(message.chat.id, "Login process is already running... \nSend /cancel to stop it...")
        return
        
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    try:
        await user_client.connect()
    except Exception as e:
        await client.send_message(message.chat.id, f"Error initializing client: {e}")
        return
        
    try:
        if await user_client.get_me():
            await client.send_message(message.chat.id, "Already logged in...")
            await user_client.disconnect()
            return
    except Exception:
        # Not logged in or session expired
        pass
        
    login_states[user_id] = {
        'step': 'AWAITING_PHONE',
        'client': user_client
    }
    await client.send_message(message.chat.id, "Please send your phone number with country code\ne.g. +919876543210")

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
        await client.send_message(message.chat.id, "Login process cancelled...")
    else:
        await client.send_message(message.chat.id, "No login process is currently running...")

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
            await client.send_message(message.chat.id, "Code sent! Please enter the code... \nIf your code is 12345, please send it with a space like 1 2 3 4 5")
        except Exception as e:
            await client.send_message(message.chat.id, f"Error sending code: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
            
    elif step == 'AWAITING_CODE':
        code = text.replace(" ", "")
        phone = state['phone']
        phone_code_hash = state['phone_code_hash']
        
        try:
            await user_client.sign_in(phone, phone_code_hash, code)
            await client.send_message(message.chat.id, "Login successful...")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
        except SessionPasswordNeeded:
            state['step'] = 'AWAITING_PASSWORD'
            await client.send_message(message.chat.id, "2-Step Verification is enabled...\nPlease enter your password...")
        except Exception as e:
            await client.send_message(message.chat.id, f"Error signing in: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
            
    elif step == 'AWAITING_PASSWORD':
        password = text.strip()
        try:
            await user_client.check_password(password)
            await client.send_message(message.chat.id, "Login successful...")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]
        except Exception as e:
            await client.send_message(message.chat.id, f"Error checking password: {e}")
            if user_client.is_connected:
                await user_client.disconnect()
            del login_states[user_id]

if __name__ == "__main__":
    app.run()
