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
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import SessionPasswordNeeded
from pyrogram.raw import functions, types
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Bot")

GROUP_ID = -1001552827391

login_states = {}
user_states = {}
link_cache = {}
halt_ban = False

async def check_admin(_, client: Client, message: Message):
    if not message.chat or message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        return False
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if message.from_user:
        try:
            member = await client.get_chat_member(message.chat.id, message.from_user.id)
            return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except Exception:
            return False
    return False

admin_filter = filters.create(check_admin)

async def check_cb_admin(_, client: Client, cb: CallbackQuery):
    message = cb.message
    if not message or not message.chat or message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        return False
    if cb.from_user:
        try:
            member = await client.get_chat_member(message.chat.id, cb.from_user.id)
            return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except Exception:
            return False
    return False

cb_admin = filters.create(check_cb_admin)

class BotClient(Client):
    async def start(self):
        await super().start()
        logger.info("Bot started successfully.")
        
        try:
            from pyrogram.types import BotCommand
            await self.set_bot_commands([])
        except Exception:
            pass
        
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
                idx = sys.argv.index("--updated")
                del sys.argv[idx:idx+3]

app = BotClient(
    "controller_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    if message.from_user:
        name = message.from_user.username if message.from_user.username else message.from_user.first_name
    elif message.sender_chat:
        name = message.sender_chat.username if message.sender_chat.username else message.sender_chat.title
    else:
        name = "User"
        
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
        chat_title = message.chat.title or "Unknown"
        chat_id = message.chat.id
        await client.send_message(message.chat.id, f"Hey {name}\n\n{chat_title}\n`{chat_id}`")
    else:
        await client.send_message(message.chat.id, f"Hey {name}")

@app.on_message(filters.command("update") & admin_filter)
async def update_command(client: Client, message: Message):
    msg = await client.send_message(message.chat.id, "Updating latest code...")
    try:
        process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate()
        success_text = f"Updated\nRestarting..."
        await msg.edit_text(success_text)
    except Exception as e:
        await msg.edit_text(f"Error during update...")
        return
        
    args = [sys.executable] + sys.argv
    if "--updated" in args:
        idx = args.index("--updated")
        del args[idx:idx+3]
        
    args.extend(["--updated", str(msg.chat.id), str(msg.id)])
    os.execl(sys.executable, *args)

@app.on_message(filters.command("check") & admin_filter)
async def check_command(client: Client, message: Message):
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    status_msg = await client.send_message(message.chat.id, "Checking all groups and channels...\nThis may take a minute...")
    found_any = False
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            raise Exception("Session expired or not logged in. Send /login first.")
            
        async for dialog in user_client.get_dialogs():
            if dialog.chat.id in [GROUP_ID, -1003552827391]:
                continue
                
            if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]:
                chat = dialog.chat
                try:
                    user_member = await user_client.get_chat_member(chat.id, me.id)
                    if user_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                        try:
                            bot_member = await user_client.get_chat_member(chat.id, "Ban_Karne_Wala_Bot")
                            if bot_member.status == ChatMemberStatus.ADMINISTRATOR and bot_member.privileges and bot_member.privileges.can_restrict_members:
                                found_any = True
                                member_count = chat.members_count or 0
                                title = chat.title or "Unknown"
                                
                                text = f"{title}\n{member_count} members"
                                keyboard = InlineKeyboardMarkup([[
                                    InlineKeyboardButton("Ban All", callback_data=f"b_all_{chat.id}"),
                                    InlineKeyboardButton("Custom", callback_data=f"b_cust_{chat.id}")
                                ]])
                                await client.send_message(message.chat.id, text, reply_markup=keyboard)
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")
        if user_client.is_connected:
            await user_client.disconnect()
        return
        
    if user_client.is_connected:
        await user_client.disconnect()
        
    if not found_any:
        await status_msg.edit_text("No groups or channels found where both you and Bot are admins with ban permissions...")
    else:
        await status_msg.delete()

@app.on_message(filters.command("stop") & admin_filter)
async def stop_command(client: Client, message: Message):
    global halt_ban
    halt_ban = True
    await client.send_message(message.chat.id, "Ban Process Stopped")

# ----------------- CALLBACK QUERIES ----------------- #

@app.on_callback_query(filters.regex(r"^b_all_(-\d+)$") & cb_admin)
async def cb_ban_all(client, cb: CallbackQuery):
    chat_id = int(cb.matches[0].group(1))
    title = cb.message.text.split('\n')[0] if cb.message.text else str(chat_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=f"confirm_yes_{chat_id}_inf_normal"),
        InlineKeyboardButton("Cancel", callback_data="confirm_cancel")
    ]])
    await cb.message.edit_text(f"Are you sure you want to ban all members in **{title}**?", reply_markup=keyboard)
    
@app.on_callback_query(filters.regex(r"^b_zombi_(-\d+)$") & cb_admin)
async def cb_ban_zombi(client, cb: CallbackQuery):
    chat_id = int(cb.matches[0].group(1))
    title = cb.message.text.split('\n')[0] if cb.message.text else str(chat_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=f"confirm_yes_{chat_id}_inf_zombies"),
        InlineKeyboardButton("Cancel", callback_data="confirm_cancel")
    ]])
    await cb.message.edit_text(f"Are you sure you want to ban all deleted zombie accounts in **{title}**?", reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"^b_link_all_(-\d+)$") & cb_admin)
async def cb_ban_link_all(client, cb: CallbackQuery):
    chat_id = int(cb.matches[0].group(1))
    title = cb.message.text.split('\n')[0] if cb.message.text else str(chat_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=f"confirm_yes_{chat_id}_inf_link"),
        InlineKeyboardButton("Cancel", callback_data="confirm_cancel")
    ]])
    await cb.message.edit_text(f"Are you sure you want to ban all members joined by the given link in **{title}**?", reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"^[bl]_cust_(-\d+)$") & cb_admin)
async def cb_ban_cust(client, cb: CallbackQuery):
    chat_id = int(cb.matches[0].group(1))
    mode = "link" if cb.data.startswith("l_") else "normal"
    title = cb.message.text.split('\n')[0] if cb.message.text else str(chat_id)
    user_states[cb.from_user.id] = {
        "action": "wait_cust_limit",
        "chat_id": chat_id,
        "mode": mode,
        "title": title
    }
    await cb.message.edit_text(f"Please enter the number of members to ban in **{title}**:")
    await cb.answer()

@app.on_callback_query(filters.regex(r"^confirm_yes_(-\d+)_([A-Za-z0-9_]+)_(\w+)$") & cb_admin)
async def cb_confirm_yes(client, cb: CallbackQuery):
    chat_id = int(cb.matches[0].group(1))
    limit_str = cb.matches[0].group(2)
    mode = cb.matches[0].group(3)
    target_limit = float('inf') if limit_str == "inf" else int(limit_str)
    
    await cb.message.edit_reply_markup(reply_markup=None)
    msg = await cb.message.reply_text(f"Starting Process...")
    invite_link = link_cache.get(chat_id) if mode == "link" else None
    asyncio.create_task(run_ban_process(client, msg, chat_id, target_limit, mode, invite_link=invite_link))

@app.on_callback_query(filters.regex(r"^confirm_cancel$") & cb_admin)
async def cb_confirm_cancel(client, cb: CallbackQuery):
    await cb.message.edit_text("Action Cancelled.", reply_markup=None)
    await cb.answer("Cancelled")

@app.on_callback_query(filters.regex(r"^stop_process$") & cb_admin)
async def cb_stop_process(client, cb: CallbackQuery):
    global halt_ban
    if halt_ban:
        await cb.answer("Process already stopping...")
    else:
        halt_ban = True
        await cb.answer("Stopping running process...")

# ----------------- BAN ENGINE ----------------- #

async def run_ban_process(client, status_msg, chat_id, target_limit, mode="normal", invite_link=None):
    global halt_ban
    halt_ban = False
    
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            await status_msg.edit_text("Session expired. Please /login")
            return
            
        try:
            chat = await user_client.get_chat(chat_id)
        except Exception:
            await status_msg.edit_text("Caching peer info...")
            async for _ in user_client.get_dialogs(limit=200):
                pass
            chat = await user_client.get_chat(chat_id)
            
        await status_msg.edit_text("Starting real-time ban loops...")
    except Exception as e:
        await status_msg.edit_text(f"Error initialization: {e}")
        if user_client.is_connected:
            await user_client.disconnect()
        return

    conn = http.client.HTTPSConnection("api.telegram.org")
    api_headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
    
    async def ban_via_api(target_chat, target_user):
        data = json.dumps({"chat_id": target_chat, "user_id": target_user}).encode("utf-8")
        def do_request():
            try:
                conn.request("POST", f"/bot{config.BOT_TOKEN}/banChatMember", body=data, headers=api_headers)
                return json.loads(conn.getresponse().read().decode())
            except Exception:
                try:
                    conn.close()
                    conn.connect()
                    conn.request("POST", f"/bot{config.BOT_TOKEN}/banChatMember", body=data, headers=api_headers)
                    return json.loads(conn.getresponse().read().decode())
                except Exception as e2:
                    return {"ok": False, "description": str(e2)}
        return await asyncio.to_thread(do_request)
        
    banned_count = 0
    fail_count = 0
    total_processed = 0
    seen_uids = set()
    global_start_t = None
    last_progress_t = time.time()
    
    try:
        iterator = user_client.get_chat_invite_link_joiners(chat_id, invite_link=invite_link) if mode == "link" else user_client.get_chat_members(chat_id)
        
        async for item in iterator:
            if halt_ban or total_processed >= target_limit:
                break
                
            member_user = item.user
            if not member_user or member_user.id in seen_uids:
                continue
                
            if mode != "link":
                if item.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                    continue
                if mode == "zombies" and not member_user.is_deleted:
                    continue

            uid = member_user.id
            seen_uids.add(uid)
            
            if global_start_t is None:
                global_start_t = time.time()
                
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
            
            current_t = time.time()
            if current_t - last_progress_t >= 5.0 or total_processed == target_limit:
                try:
                    if target_limit == float('inf'):
                        display_total = getattr(chat, 'members_count', 0)
                        if display_total:
                            total_str = str(display_total)
                            rem_str = str(max(0, display_total - total_processed))
                        else:
                            total_str = "All"
                            rem_str = "Calculating..."
                    else:
                        total_str = str(target_limit)
                        rem_str = str(max(0, target_limit - total_processed))
                    prog_text = (f"Ban Process Running\n\n"
                                 f"Total {total_str}\n"
                                 f"Banned {banned_count}\n"
                                 f"Remaining {rem_str}\n"
                                 f"Failed {fail_count}\n\n"
                                 f"Below or Click /stop to stop running process...")
                    stop_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Stop Process", callback_data="stop_process")]])
                    await status_msg.edit_text(prog_text, reply_markup=stop_kb)
                    last_progress_t = current_t
                except Exception:
                    pass
                    
            if not halt_ban:
                await asyncio.sleep(max(0, 0.5 - elapsed))
                    
    except Exception as e:
        await status_msg.edit_text(f"Error during ban loop process: {e}")
    finally:
        if user_client.is_connected:
            await user_client.disconnect()
            
    time_taken = int(time.time() - (global_start_t if global_start_t is not None else time.time()))
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
        
    if target_limit == float('inf') and getattr(chat, 'members_count', 0):
        total_final_str = str(getattr(chat, 'members_count', 0))
    else:
        total_final_str = "All" if target_limit == float('inf') else str(target_limit)
    final_text += (f"Total {total_final_str}\n"
                   f"Banned {banned_count}\n"
                   f"Failed {fail_count}\n\n"
                   f"Time Taken {time_str}")
        
    try:
        await status_msg.edit_text(final_text)
    except Exception:
        pass

# ----------------- LOGIN AND TEXT HANDLERS ----------------- #

@app.on_message(filters.command("login") & admin_filter)
async def login_command(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id: return
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
        pass
        
    login_states[user_id] = {'step': 'AWAITING_PHONE', 'client': user_client}
    await client.send_message(message.chat.id, "Please send your phone number with country code\ne.g. +919876543210")

@app.on_message(filters.command("cancel") & admin_filter)
async def cancel_login(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id: return
    if user_id in login_states:
        user_client = login_states[user_id]['client']
        if user_client.is_connected:
            await user_client.disconnect()
        del login_states[user_id]
        await client.send_message(message.chat.id, "Login process cancelled...")
    else:
        await client.send_message(message.chat.id, "No login process is currently running...")

@app.on_message(filters.command("logout") & admin_filter)
async def logout_command(client: Client, message: Message):
    status_msg = await client.send_message(message.chat.id, "Attempting logout...")
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if me:
            await user_client.log_out()
            await status_msg.edit_text("Logged out successfully from current session.")
        else:
            await status_msg.edit_text("No active session found to logout.")
    except Exception as e:
        await status_msg.edit_text(f"Session already inactive or error: {e}")
    finally:
        if user_client.is_connected:
            await user_client.disconnect()
            
    try:
        if os.path.exists("user_session.session"):
            os.remove("user_session.session")
    except Exception:
        pass

@app.on_message(filters.text & ~filters.command(["login", "cancel", "logout", "start", "update", "check", "stop"]) & admin_filter)
async def handle_text_steps(client: Client, message: Message):
    text = message.text.strip()
    user_id = message.from_user.id if message.from_user else None
    
    if "t.me/" in text or "telegram.me/" in text:
        asyncio.create_task(process_invite_link(client, message, text))
        return
        
    if user_id in user_states and user_states[user_id].get("action") == "wait_cust_limit":
        if text.isdigit():
            limit = int(text)
            chat_id = user_states[user_id]["chat_id"]
            mode = user_states[user_id]["mode"]
            title = user_states[user_id].get("title", str(chat_id))
            del user_states[user_id]
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes", callback_data=f"confirm_yes_{chat_id}_{limit}_{mode}"),
                InlineKeyboardButton("Cancel", callback_data="confirm_cancel")
            ]])
            await client.send_message(message.chat.id, f"Are you sure you want to ban {limit} members in **{title}**?", reply_markup=keyboard)
        else:
            await client.send_message(message.chat.id, "Please enter a valid number.")
        return

    # Handle Login Steps
    if not user_id or user_id not in login_states:
        return
        
    state = login_states[user_id]
    step = state['step']
    user_client = state['client']
    
    if step == 'AWAITING_PHONE':
        phone = text
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
        password = text
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

async def process_invite_link(client, message, link):
    status_msg = await client.send_message(message.chat.id, "Checking...")
    user_client = Client("user_session", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=False)
    
    try:
        await user_client.connect()
        me = await user_client.get_me()
        if not me:
            await status_msg.edit_text("Session expired. Please /login first.")
            return
            
        try:
            chat = await user_client.get_chat(link)
        except Exception as e:
            await status_msg.edit_text(f"Invalid or expired link: {e}")
            return
            
        try:
            user_member = await user_client.get_chat_member(chat.id, me.id)
            if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                await status_msg.edit_text("Error: You are not an admin in this chat.")
                return
                
            bot_member = await user_client.get_chat_member(chat.id, "Ban_Karne_Wala_Bot")
            if bot_member.status != ChatMemberStatus.ADMINISTRATOR or not bot_member.privileges or not bot_member.privileges.can_restrict_members:
                await status_msg.edit_text("Error: Bot is not an admin with ban permissions in this chat.")
                return
        except Exception:
            await status_msg.edit_text("Error: Missing ban permissions for you or the bot in this chat.")
            return
            
        joiner_count = 0
        try:
            from pyrogram.raw.functions.messages import GetChatInviteImporters
            from pyrogram.raw import types
            res = await user_client.invoke(GetChatInviteImporters(
                peer=await user_client.resolve_peer(chat.id),
                link=link,
                limit=1,
                offset_date=0,
                offset_user=types.InputUserEmpty()
            ))
            joiner_count = getattr(res, "count", 0)
        except Exception:
            joiner_count = "unknown"
            
        link_cache[chat.id] = link
            
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Ban All", callback_data=f"b_link_all_{chat.id}"),
            InlineKeyboardButton("Custom", callback_data=f"l_cust_{chat.id}")
        ]])
        text = f"{chat.title or 'Unknown'}\n\n{joiner_count} members joined by given link"
        await status_msg.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await status_msg.edit_text(f"Error checking link: {e}")
    finally:
        if user_client.is_connected:
            await user_client.disconnect()

if __name__ == "__main__":
    app.run()
