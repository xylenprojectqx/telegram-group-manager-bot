"""
Telegram Group Manager Bot
============================
Anti-spam, welcome messages, warn/ban/mute, captcha,
anti-link, word filter, and admin commands.
"""

import re
import time
import random
import logging
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    ChatMemberHandler,
)

from config import (
    TELEGRAM_BOT_TOKEN, OWNER_ID,
    WELCOME_MESSAGE, WELCOME_ENABLED, GOODBYE_MESSAGE, GOODBYE_ENABLED,
    ANTISPAM_ENABLED, SPAM_THRESHOLD, SPAM_ACTION, MUTE_DURATION_MINUTES,
    ANTILINK_ENABLED, ANTILINK_WARN,
    FLOOD_THRESHOLD, FLOOD_ACTION,
    CAPTCHA_ENABLED, CAPTCHA_TIMEOUT, CAPTCHA_FAIL_ACTION,
    MAX_WARNS, WARN_ACTION,
    WORDFILTER_ENABLED, BANNED_WORDS,
)
from database import (
    get_group, update_group, get_warns, add_warn,
    reset_warns, get_total_groups, register_user,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# === ANTI-SPAM TRACKING ===
user_messages = defaultdict(list)  # user_id -> [timestamps]
user_last_message = defaultdict(str)  # user_id -> last message text
user_flood_count = defaultdict(int)  # user_id -> same message count

# === CAPTCHA TRACKING ===
pending_captcha = {}  # user_id -> {"answer": int, "chat_id": int, "time": float}


# === HELPER FUNCTIONS ===

async def is_admin(update, user_id):
    """Check if user is admin in the chat."""
    if user_id == OWNER_ID:
        return True
    try:
        member = await update.effective_chat.get_member(user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False


async def is_bot_admin(update):
    """Check if bot is admin."""
    try:
        bot_member = await update.effective_chat.get_member(update.get_bot().id)
        return bot_member.status == "administrator"
    except:
        return False


def get_user_mention(user):
    """Get user mention HTML."""
    name = user.first_name or "User"
    return f'<a href="tg://user?id={user.id}">{name}</a>'


# === WELCOME / GOODBYE ===

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new members + captcha."""
    if not update.message or not update.message.new_chat_members:
        return
    
    chat = update.effective_chat
    
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        
        register_user(member.id)
        
        # Welcome message
        if WELCOME_ENABLED:
            name = get_user_mention(member)
            msg = WELCOME_MESSAGE.format(
                name=name,
                group=chat.title or "the group",
                count=await chat.get_member_count() if hasattr(chat, 'get_member_count') else "?",
            )
            
            # Captcha
            if CAPTCHA_ENABLED:
                a = random.randint(1, 10)
                b = random.randint(1, 10)
                answer = a + b
                
                pending_captcha[member.id] = {
                    "answer": answer,
                    "chat_id": chat.id,
                    "time": time.time(),
                }
                
                # Generate 4 options (1 correct + 3 wrong)
                options = [answer]
                while len(options) < 4:
                    wrong = random.randint(2, 20)
                    if wrong != answer and wrong not in options:
                        options.append(wrong)
                random.shuffle(options)
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(str(opt), callback_data=f"captcha_{member.id}_{opt}")
                    for opt in options
                ]])
                
                msg += f"\n\n🔐 <b>Captcha:</b> What is {a} + {b} = ?"
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
                
                # Mute until captcha solved
                try:
                    await chat.restrict_member(
                        member.id,
                        ChatPermissions(can_send_messages=False)
                    )
                except:
                    pass
            else:
                await update.message.reply_text(msg, parse_mode="HTML")


async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Goodbye message when member leaves."""
    if not GOODBYE_ENABLED:
        return
    if not update.message or not update.message.left_chat_member:
        return
    
    member = update.message.left_chat_member
    if member.is_bot:
        return
    
    name = get_user_mention(member)
    msg = GOODBYE_MESSAGE.format(name=name)
    await update.message.reply_text(msg, parse_mode="HTML")


# === CAPTCHA CALLBACK ===

async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle captcha button press."""
    query = update.callback_query
    data = query.data
    
    if not data.startswith("captcha_"):
        return
    
    parts = data.split("_")
    if len(parts) != 3:
        return
    
    target_user_id = int(parts[1])
    selected_answer = int(parts[2])
    
    # Only the target user can answer
    if query.from_user.id != target_user_id:
        await query.answer("This captcha is not for you!", show_alert=True)
        return
    
    captcha_data = pending_captcha.get(target_user_id)
    if not captcha_data:
        await query.answer("Captcha expired.", show_alert=True)
        return
    
    if selected_answer == captcha_data["answer"]:
        # Correct! Unmute
        try:
            await update.effective_chat.restrict_member(
                target_user_id,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
            )
        except:
            pass
        
        del pending_captcha[target_user_id]
        await query.edit_message_text("✅ Captcha solved! Welcome!")
    else:
        # Wrong answer
        del pending_captcha[target_user_id]
        
        if CAPTCHA_FAIL_ACTION == "kick":
            try:
                await update.effective_chat.ban_member(target_user_id)
                await update.effective_chat.unban_member(target_user_id)
            except:
                pass
            await query.edit_message_text("❌ Wrong answer. User kicked.")
        elif CAPTCHA_FAIL_ACTION == "ban":
            try:
                await update.effective_chat.ban_member(target_user_id)
            except:
                pass
            await query.edit_message_text("❌ Wrong answer. User banned.")
        else:
            await query.edit_message_text("❌ Wrong answer.")


# === ANTI-SPAM ===

async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check for spam/flood behavior."""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    # Skip private chats and admins
    if chat.type == "private":
        return
    if await is_admin(update, user_id):
        return
    
    now = time.time()
    text = update.message.text
    
    # === ANTI-SPAM (rate) ===
    if ANTISPAM_ENABLED:
        user_messages[user_id] = [t for t in user_messages[user_id] if now - t < 10]
        user_messages[user_id].append(now)
        
        if len(user_messages[user_id]) > SPAM_THRESHOLD:
            await _take_action(update, context, user_id, "spam")
            return
    
    # === ANTI-FLOOD (same message) ===
    if user_last_message[user_id] == text:
        user_flood_count[user_id] += 1
        if user_flood_count[user_id] >= FLOOD_THRESHOLD:
            await _take_action(update, context, user_id, "flood")
            user_flood_count[user_id] = 0
            return
    else:
        user_last_message[user_id] = text
        user_flood_count[user_id] = 1
    
    # === ANTI-LINK ===
    if ANTILINK_ENABLED:
        url_pattern = r'https?://[^\s]+|t\.me/[^\s]+|@[a-zA-Z]\w{3,}'
        if re.search(url_pattern, text):
            try:
                await update.message.delete()
                if ANTILINK_WARN:
                    name = get_user_mention(update.effective_user)
                    await chat.send_message(
                        f"⚠️ {name}, links are not allowed!",
                        parse_mode="HTML"
                    )
            except:
                pass
            return
    
    # === WORD FILTER ===
    if WORDFILTER_ENABLED and BANNED_WORDS:
        text_lower = text.lower()
        for word in BANNED_WORDS:
            if word.lower() in text_lower:
                try:
                    await update.message.delete()
                    name = get_user_mention(update.effective_user)
                    await chat.send_message(
                        f"⚠️ {name}, that word is not allowed!",
                        parse_mode="HTML"
                    )
                except:
                    pass
                return


async def _take_action(update, context, user_id, reason):
    """Take action against user (mute/warn/kick/ban)."""
    chat = update.effective_chat
    action = SPAM_ACTION if reason == "spam" else FLOOD_ACTION
    name = get_user_mention(update.effective_user)
    
    try:
        await update.message.delete()
    except:
        pass
    
    if action == "mute":
        try:
            if MUTE_DURATION_MINUTES > 0:
                import datetime
                until = datetime.datetime.now() + datetime.timedelta(minutes=MUTE_DURATION_MINUTES)
                await chat.restrict_member(
                    user_id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until,
                )
                await chat.send_message(
                    f"🔇 {name} muted for {MUTE_DURATION_MINUTES} min ({reason})",
                    parse_mode="HTML"
                )
            else:
                await chat.restrict_member(
                    user_id,
                    ChatPermissions(can_send_messages=False)
                )
                await chat.send_message(f"🔇 {name} muted ({reason})", parse_mode="HTML")
        except:
            pass
    
    elif action == "warn":
        count = add_warn(chat.id, user_id)
        await chat.send_message(
            f"⚠️ {name} warned ({count}/{MAX_WARNS}) — {reason}",
            parse_mode="HTML"
        )
        if count >= MAX_WARNS:
            await _final_warn_action(chat, user_id, name)
    
    elif action == "kick":
        try:
            await chat.ban_member(user_id)
            await chat.unban_member(user_id)
            await chat.send_message(f"👢 {name} kicked ({reason})", parse_mode="HTML")
        except:
            pass
    
    elif action == "ban":
        try:
            await chat.ban_member(user_id)
            await chat.send_message(f"🚫 {name} banned ({reason})", parse_mode="HTML")
        except:
            pass


async def _final_warn_action(chat, user_id, name):
    """Action when user reaches max warns."""
    if WARN_ACTION == "ban":
        try:
            await chat.ban_member(user_id)
            await chat.send_message(f"🚫 {name} banned (max warns reached)", parse_mode="HTML")
        except:
            pass
    elif WARN_ACTION == "kick":
        try:
            await chat.ban_member(user_id)
            await chat.unban_member(user_id)
            await chat.send_message(f"👢 {name} kicked (max warns reached)", parse_mode="HTML")
        except:
            pass


# === ADMIN COMMANDS ===

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/warn - warn a user."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to a message to warn the user.")
        return
    
    target = update.message.reply_to_message.from_user
    if await is_admin(update, target.id):
        await update.message.reply_text("❌ Can't warn an admin.")
        return
    
    reason = " ".join(context.args) if context.args else "No reason"
    count = add_warn(update.effective_chat.id, target.id)
    name = get_user_mention(target)
    
    await update.message.reply_text(
        f"⚠️ {name} warned ({count}/{MAX_WARNS})\nReason: {reason}",
        parse_mode="HTML"
    )
    
    if count >= MAX_WARNS:
        await _final_warn_action(update.effective_chat, target.id, name)


async def unwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unwarn - reset warns."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to reset warns.")
        return
    
    target = update.message.reply_to_message.from_user
    reset_warns(update.effective_chat.id, target.id)
    name = get_user_mention(target)
    await update.message.reply_text(f"✅ {name} warns reset to 0.", parse_mode="HTML")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ban - ban a user."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to ban the user.")
        return
    
    target = update.message.reply_to_message.from_user
    if await is_admin(update, target.id):
        await update.message.reply_text("❌ Can't ban an admin.")
        return
    
    try:
        await update.effective_chat.ban_member(target.id)
        name = get_user_mention(target)
        reason = " ".join(context.args) if context.args else ""
        msg = f"🚫 {name} has been banned."
        if reason:
            msg += f"\nReason: {reason}"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unban - unban a user."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to unban.")
        return
    
    target = update.message.reply_to_message.from_user
    try:
        await update.effective_chat.unban_member(target.id)
        name = get_user_mention(target)
        await update.message.reply_text(f"✅ {name} unbanned.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mute - mute a user."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to mute.")
        return
    
    target = update.message.reply_to_message.from_user
    if await is_admin(update, target.id):
        await update.message.reply_text("❌ Can't mute an admin.")
        return
    
    try:
        await update.effective_chat.restrict_member(
            target.id, ChatPermissions(can_send_messages=False)
        )
        name = get_user_mention(target)
        await update.message.reply_text(f"🔇 {name} muted.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unmute - unmute a user."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to unmute.")
        return
    
    target = update.message.reply_to_message.from_user
    try:
        await update.effective_chat.restrict_member(
            target.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        )
        name = get_user_mention(target)
        await update.message.reply_text(f"🔊 {name} unmuted.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kick - kick a user (can rejoin)."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to kick.")
        return
    
    target = update.message.reply_to_message.from_user
    if await is_admin(update, target.id):
        await update.message.reply_text("❌ Can't kick an admin.")
        return
    
    try:
        await update.effective_chat.ban_member(target.id)
        await update.effective_chat.unban_member(target.id)
        name = get_user_mention(target)
        await update.message.reply_text(f"👢 {name} kicked.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rules - show group rules."""
    group = get_group(update.effective_chat.id)
    rules = group.get("rules", "")
    
    if rules:
        await update.message.reply_text(f"📜 <b>Group Rules:</b>\n\n{rules}", parse_mode="HTML")
    else:
        await update.message.reply_text("No rules set. Admin can set with /setrules")


async def setrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setrules <text> - set group rules."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /setrules <rules text>")
        return
    
    rules_text = " ".join(context.args)
    update_group(update.effective_chat.id, "rules", rules_text)
    await update.message.reply_text("✅ Rules updated!")


async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pin - pin replied message."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to pin it.")
        return
    
    try:
        await update.message.reply_to_message.pin()
        await update.message.reply_text("📌 Message pinned!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unpin - unpin replied message."""
    if not await is_admin(update, update.effective_user.id):
        return
    
    try:
        await update.effective_chat.unpin_all_messages()
        await update.message.reply_text("📌 All messages unpinned!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


# === INFO COMMANDS ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start command."""
    if update.effective_chat.type == "private":
        text = (
            "🤖 <b>Group Manager Bot</b>\n\n"
            "Add me to your group and make me admin!\n\n"
            "<b>Features:</b>\n"
            "• 🔒 Anti-spam & Anti-flood\n"
            "• 🔗 Anti-link\n"
            "• 🔐 Captcha for new members\n"
            "• ⚠️ Warn system (auto-ban at limit)\n"
            "• 👢 Kick / Ban / Mute commands\n"
            "• 👋 Welcome & Goodbye messages\n"
            "• 📜 Rules command\n"
            "• 📌 Pin/Unpin\n\n"
            "Use /help for command list."
        )
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text("🤖 I'm active! Use /help for commands.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help command."""
    text = (
        "📖 <b>Commands:</b>\n\n"
        "<b>Admin Commands:</b>\n"
        "/warn - Warn user (reply)\n"
        "/unwarn - Reset warns (reply)\n"
        "/ban - Ban user (reply)\n"
        "/unban - Unban user (reply)\n"
        "/mute - Mute user (reply)\n"
        "/unmute - Unmute user (reply)\n"
        "/kick - Kick user (reply)\n"
        "/pin - Pin message (reply)\n"
        "/unpin - Unpin all\n"
        "/setrules - Set group rules\n\n"
        "<b>Everyone:</b>\n"
        "/rules - Show rules\n"
        "/help - This message\n"
        "/info - Bot info & stats"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info - bot stats."""
    groups = get_total_groups()
    text = (
        f"📊 <b>Bot Info</b>\n\n"
        f"👥 Groups: {groups}\n"
        f"🔒 Anti-spam: {'✅' if ANTISPAM_ENABLED else '❌'}\n"
        f"🔗 Anti-link: {'✅' if ANTILINK_ENABLED else '❌'}\n"
        f"🔐 Captcha: {'✅' if CAPTCHA_ENABLED else '❌'}\n"
        f"⚠️ Max warns: {MAX_WARNS}\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# === MAIN ===

def main():
    print("""
    ╔══════════════════════════════════════════╗
    ║                                          ║
    ║   🛡️ Telegram Group Manager Bot          ║
    ║   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   ║
    ║                                          ║
    ║   🔒 Anti-Spam    🔗 Anti-Link           ║
    ║   🔐 Captcha      ⚠️ Warn System         ║
    ║   👢 Kick/Ban     👋 Welcome Msg         ║
    ║                                          ║
    ╚══════════════════════════════════════════╝
    """)
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("setrules", setrules_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("unwarn", unwarn_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("unpin", unpin_command))
    
    # Captcha callback
    app.add_handler(CallbackQueryHandler(captcha_callback, pattern=r"^captcha_"))
    
    # New/left members
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))
    
    # Anti-spam/link/flood (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, check_spam))
    
    print("[✅] Bot is running! Press Ctrl+C to stop.\n")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
