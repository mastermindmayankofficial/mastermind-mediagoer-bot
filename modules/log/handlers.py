import os
from telegram import Update
from telegram.ext import ContextTypes
from modules.database.user_db import get_user_role_db
from modules.log.logger import get_logs_by_count, get_logs_by_time, setup_in_memory_logger
from modules.log.startup_log import send_log_with_fallback

setup_in_memory_logger()


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role_db(user_id)
    if role not in ["Admin", "Owner"]:
        await update.message.reply_text("⛔ Access denied. Only Admins and Owners can view system logs.")
        return

    args = context.args
    if not args:
        log_content = get_logs_by_count(20)
        filename = "logs_last_20.txt"
    else:
        param = args[0].lower()
        if param.endswith("m") and param[:-1].isdigit():
            mins = int(param[:-1])
            log_content = get_logs_by_time(mins)
            filename = f"logs_last_{mins}_min.txt"
        elif param.isdigit():
            count = min(1000, int(param))
            log_content = get_logs_by_count(count)
            filename = f"logs_last_{count}.txt"
        else:
            await update.message.reply_text("⚠️ Usage: <code>/log</code>, <code>/log 50</code>, or <code>/log 15m</code>", parse_mode="HTML")
            return

    temp_path = f"/tmp/{filename}"
    with open(temp_path, "w") as tf:
        tf.write(log_content)
    with open(temp_path, "rb") as tf:
        await update.message.reply_document(
            document=tf,
            filename=filename,
            caption=f"📋 <b>System Logs</b> (Requested by <code>{role}</code>)",
            parse_mode="HTML",
        )
    if os.path.exists(temp_path):
        os.remove(temp_path)


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    chat_type = chat.type
    actor = result.from_user
    actor_str = f"{actor.full_name} (<code>{actor.id}</code>)" if actor else "System"

    topic_key = "group_log_topic_id" if chat_type in ["group", "supergroup"] else ("channel_log_topic_id" if chat_type == "channel" else "general_topic_id")
    label = f"📢 <b>Bot Status Changed in {chat_type.capitalize()}</b>"
    msg = (
        f"{label}\n\n"
        f"🏷 <b>Title:</b> {chat.title or 'Private'}\n"
        f"🆔 <b>Chat ID:</b> <code>{chat.id}</code>\n"
        f"🔄 <b>Status:</b> <code>{old_status} -> {new_status}</code>\n"
        f"👤 <b>By:</b> {actor_str}"
    )
    await send_log_with_fallback(context.bot, msg, "general_log_group_id", topic_key)
