import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.user_db import get_user_role_db, get_all_users_db
from modules.database.config_db import get_config_bool
from modules.log.startup_log import send_log_with_fallback


async def _execute_broadcast(context: ContextTypes.DEFAULT_TYPE, sender_id: int, target: str, msg_text: str, status_msg):
    users = get_all_users_db(None if target in ("everyone", "all_users", "all") else target)
    total = len(users)
    sent = 0
    failed = 0

    for u in users:
        uid = u[0]
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg_text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    summary = (
        f"📢 <b>Broadcast Completed</b>\n\n"
        f"🎯 <b>Target:</b> <code>{target}</code>\n"
        f"👥 <b>Total Recipients:</b> <code>{total}</code>\n"
        f"✅ <b>Delivered:</b> <code>{sent}</code>\n"
        f"❌ <b>Failed:</b> <code>{failed}</code>"
    )
    await status_msg.edit_text(summary, parse_mode="HTML")
    await send_log_with_fallback(context.bot, f"{summary}\n👮 <b>By:</b> <code>{sender_id}</code>", "admin_log_group_id", "general_topic_id")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if get_user_role_db(user_id) not in ("Admin", "Owner"):
        await update.effective_message.reply_text("⛔ Access denied. Only Admins and Owners can broadcast.")
        return

    if not get_config_bool("is_broadcast_enabled", True):
        await update.effective_message.reply_text("⚠️ Broadcasting is currently disabled in config (`is_broadcast_enabled=false`).")
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "• <code>/broadcast &lt;everyone|normal|promoter|volunteer|moderator&gt; &lt;message&gt;</code>\n"
            "• <code>/broadcast_confirm everyone &lt;message&gt;</code>",
            parse_mode="HTML",
        )
        return

    target = context.args[0].lower()
    msg_text = " ".join(context.args[1:])
    context.user_data["pending_broadcast"] = {"target": target, "text": msg_text}

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Broadcast", callback_data="bcast_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="bcast_cancel"),
        ]
    ])
    preview = (
        f"📢 <b>Broadcast Confirmation</b>\n\n"
        f"🎯 <b>Target Group:</b> <code>{target}</code>\n"
        f"💬 <b>Message Preview:</b>\n<blockquote>{msg_text}</blockquote>\n\n"
        f"Press <b>Confirm</b> to send or use <code>/broadcast_confirm everyone &lt;message&gt;</code>."
    )
    await update.effective_message.reply_text(preview, parse_mode="HTML", reply_markup=kb)


async def broadcast_confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if get_user_role_db(user_id) not in ("Admin", "Owner"):
        await update.effective_message.reply_text("⛔ Access denied.")
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("⚠️ <b>Usage:</b> <code>/broadcast_confirm everyone &lt;message&gt;</code>", parse_mode="HTML")
        return
    target = context.args[0].lower()
    msg_text = " ".join(context.args[1:])
    status_msg = await update.effective_message.reply_text("⏳ Broadcasting message...")
    await _execute_broadcast(context, user_id, target, msg_text, status_msg)


async def broadcast_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    if get_user_role_db(q.from_user.id) not in ("Admin", "Owner"):
        await q.answer("⛔ Access denied.", show_alert=True)
        return
    await q.answer()
    if q.data == "bcast_cancel":
        context.user_data.pop("pending_broadcast", None)
        await q.message.edit_text("❌ Broadcast cancelled.")
    elif q.data == "bcast_confirm":
        data = context.user_data.pop("pending_broadcast", None)
        if not data:
            await q.message.edit_text("⚠️ No pending broadcast found.")
            return
        await q.message.edit_text("⏳ Sending broadcast...")
        await _execute_broadcast(context, q.from_user.id, data["target"], data["text"], q.message)
