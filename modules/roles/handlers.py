import sqlite3
from telegram import Update
from telegram.ext import ContextTypes
from modules.database.user_db import DB_FILE, get_user_role_db, set_user_role_db
from modules.database.config_db import get_template, format_template_string
from modules.log.startup_log import send_log_with_fallback


async def _resolve_user_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name or f"@{u.username}" or str(u.id)

    if not context.args:
        return None, None

    raw = context.args[0].strip()
    if raw.lstrip("-").isdigit():
        return int(raw), raw

    uname = raw.lstrip("@")
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT user_id, full_name FROM users WHERE LOWER(username) = LOWER(?)", (uname,)).fetchone()
    conn.close()
    if row:
        return row[0], row[1] or f"@{uname}"
    return None, raw


async def _assign_role(update: Update, context: ContextTypes.DEFAULT_TYPE, role_name: str, cmd_name: str):
    caller_id = update.effective_user.id
    caller_role = get_user_role_db(caller_id)

    if caller_role not in ("Admin", "Owner"):
        await update.effective_message.reply_text("⛔ Access denied. Only Admins and Owners can assign roles.")
        return

    if role_name == "Admin" and caller_role != "Owner":
        await update.effective_message.reply_text("⛔ Only the Bot Owner can assign the Admin role.")
        return

    target_id, target_label = await _resolve_user_target(update, context)
    if not target_id:
        await update.effective_message.reply_text(
            f"⚠️ <b>Usage:</b> <code>/{cmd_name} &lt;user_id | @username&gt;</code> (or reply to a user's message)",
            parse_mode="HTML",
        )
        return

    s_base, _ = set_user_role_db(target_id, role_name)
    quota_label = "Unlimited" if s_base >= 999999 else f"{s_base} Searches & {s_base} Requests"

    tpl = get_template("role_updated")
    text = format_template_string(
        tpl.get("text") or "🎖 <b>Role Updated!</b>\n👤 <b>User:</b> {target_user}\n🛡 <b>New Role:</b> <code>{new_role}</code>\n📊 <b>New Quota:</b> <code>{new_quota}</code>",
        {"target_user": f"{target_label} (<code>{target_id}</code>)", "new_role": role_name, "new_quota": quota_label},
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"🎉 <b>Your Role Was Updated!</b>\n\n🛡 <b>New Role:</b> <code>{role_name}</code>\n📊 <b>Base Daily Quota:</b> <code>{quota_label}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    log_msg = (
        f"🎖 <b>Role Assignment Log</b>\n\n"
        f"👮 <b>By:</b> {update.effective_user.full_name} (<code>{caller_id}</code>)\n"
        f"👤 <b>Target:</b> {target_label} (<code>{target_id}</code>)\n"
        f"🛡 <b>Assigned Role:</b> <code>{role_name}</code> ({quota_label})"
    )
    await send_log_with_fallback(context.bot, log_msg, "admin_log_group_id", "user_log_topic_id")


async def addvol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _assign_role(update, context, "Volunteer", "addvol")


async def addprom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _assign_role(update, context, "Promoter", "addprom")


async def addmod_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _assign_role(update, context, "Moderator", "addmod")


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _assign_role(update, context, "Admin", "addadmin")
