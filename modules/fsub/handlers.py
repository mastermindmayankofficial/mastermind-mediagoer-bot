from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ApplicationHandlerStop
from modules.database.config_db import (
    get_config_bool,
    get_fsub_channels_db,
    record_fsub_join_request_db,
    has_fsub_join_request_db,
    get_template,
    format_template_string,
)
from modules.database.user_db import get_user_role_db


async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Records join requests for Join-Request FSub channels."""
    req = update.chat_join_request
    if req and req.chat and req.from_user:
        record_fsub_join_request_db(req.chat.id, req.from_user.id)


async def check_user_fsub(user_id: int, bot) -> list:
    """Returns a list of FSub channel dicts the user has NOT yet satisfied."""
    if not get_config_bool("fsub_enabled", False):
        return []
    role = get_user_role_db(user_id)
    if role in ("Admin", "Owner"):
        return []

    channels = get_fsub_channels_db()
    missing = []
    for ch in channels:
        cid = int(ch["channel_id"])
        mode = ch.get("mode", "normal")
        if mode == "join_request" and has_fsub_join_request_db(cid, user_id):
            continue
        try:
            member = await bot.get_chat_member(chat_id=cid, user_id=int(user_id))
            if member.status in ("member", "administrator", "creator"):
                continue
        except Exception:
            pass
        missing.append(ch)
    return missing


async def enforce_fsub_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Middleware that prompts users to join required FSub channels before using the bot."""
    if not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return
    if update.callback_query and update.callback_query.data and update.callback_query.data.startswith(("fsub_", "cust_")):
        return
    if update.message and update.message.text and update.message.text.startswith(("/customize", "/adminhelp", "/id")):
        return

    user = update.effective_user
    missing = await check_user_fsub(user.id, context.bot)
    if not missing:
        return

    kb = []
    for ch in missing:
        cid = int(ch["channel_id"])
        title = ch.get("title") or f"Channel {cid}"
        link = ch.get("invite_link") or ""
        if not link:
            try:
                creates_req = ch.get("mode") == "join_request"
                inv = await context.bot.create_chat_invite_link(chat_id=cid, creates_join_request=creates_req)
                link = inv.invite_link
            except Exception:
                link = "https://t.me/"
        btn_label = f"📢 Join {title}" if ch.get("mode") != "join_request" else f"🔒 Request to Join {title}"
        kb.append([InlineKeyboardButton(btn_label, url=link)])

    kb.append([InlineKeyboardButton("✅ Try Again / Verify", callback_data="fsub_verify")])
    tpl = get_template("fsub_message")
    text = format_template_string(tpl.get("text"), {"user_name": user.first_name or "User"})

    if update.callback_query:
        await update.callback_query.answer("📢 Please join our required channel(s) first.", show_alert=True)
        await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    raise ApplicationHandlerStop()


async def fsub_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    missing = await check_user_fsub(q.from_user.id, context.bot)
    if missing:
        await q.answer("❌ You still haven't joined all required channels.", show_alert=True)
    else:
        await q.answer("✅ Subscription verified! You can now use the bot.", show_alert=True)
        await q.message.edit_text("✅ <b>Subscription Verified!</b>\n\nThank you for joining. You can now use /search, /request, or /help.", parse_mode="HTML")
