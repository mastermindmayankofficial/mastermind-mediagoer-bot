from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.user_db import add_or_update_user_db, get_user_role_db, set_helper_started_db
from modules.database.config_db import get_template, format_template_string
from modules.allowance.referral import process_referral_with_notification
from modules.allowance.allowance import get_user_quota_summary


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    target_msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not user or not target_msg:
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    is_private = update.effective_chat and update.effective_chat.type == "private"
    is_new = add_or_update_user_db(user.id, user.username, user.full_name, today_str, helper_started=True if is_private else None)
    if is_private:
        set_helper_started_db(user.id, True)

    referral_notice = ""
    args = context.args
    if args and args[0].startswith("ref_"):
        try:
            ref_id = int(args[0].split("_", 1)[1])
            ok, msg = await process_referral_with_notification(context, ref_id, user.id, user.full_name or user.first_name, is_first_time=is_new)
            if ok:
                referral_notice = "\n\n🎁 <b>Referral bonus applied: +10 search quota, +10 request quota!</b>"
            else:
                referral_notice = f"\n\n<i>{msg}</i>"
        except ValueError:
            pass
    elif args and args[0] == "helper_init":
        referral_notice = "\n\n✅ <b>Helper Bot Activated!</b> You can now click any search result to receive files in the posting channel and DM."

    tpl = get_template("start")
    raw_txt = tpl.get("text") or "Hi <b>{user_name}</b>, welcome to <b>{bot_title}</b>! 👋"
    text = format_template_string(raw_txt, {"user_name": user.first_name or "User"}) + referral_notice

    bot_uname = context.bot.username or "Bot"
    ref_link = f"https://t.me/{bot_uname}?start=ref_{user.id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20and%20earn%20%2B10%20bonus%20quota"

    kb = [
        [InlineKeyboardButton("🔍 Search All", callback_data="search_menu"), InlineKeyboardButton("📖 Help Menu", callback_data="help_button")],
        [InlineKeyboardButton("🎬 Movie Search", callback_data="movie_search_menu"), InlineKeyboardButton("⛩️ Anime Search", callback_data="anime_search_menu")],
        [InlineKeyboardButton("📊 My Quota", callback_data="quota_menu"), InlineKeyboardButton("📤 Refer & Earn +10", url=share_url)],
    ]
    for b in tpl.get("buttons", []):
        if b.get("type") == "url":
            kb.append([InlineKeyboardButton(b["label"], url=b["target"])])
        else:
            kb.append([InlineKeyboardButton(b["label"], callback_data=b["target"])])

    role = get_user_role_db(user.id)
    if role in ("Admin", "Owner"):
        kb.append([InlineKeyboardButton("🪄 Customize Bot (/customize)", callback_data="cust_open_main"), InlineKeyboardButton("👑 Admin Help", callback_data="help_open_admin")])

    markup = InlineKeyboardMarkup(kb)
    if update.callback_query:
        await update.callback_query.answer()
        await target_msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        if tpl.get("media_type") == "photo" and tpl.get("media_id"):
            await target_msg.reply_photo(photo=tpl["media_id"], caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await target_msg.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def menu_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data
    if d in ("help_button", "help_menu", "help_open_admin") or d.startswith(("help_sec_", "adm_sec_")):
        from modules.help.handlers import help_button_callback
        await help_button_callback(update, context)
    elif d == "start_menu":
        await start_command(update, context)
    elif d == "search_menu":
        from modules.search.handlers import search_command
        await search_command(update, context)
    elif d == "stats_menu":
        from modules.stats.handlers import stats_command
        await stats_command(update, context)
    elif d in ("quota", "quota_menu"):
        await q.answer()
        s = get_user_quota_summary(q.from_user.id)
        txt = (
            f"📊 <b>Your Quota Status</b>\n\n"
            f"🛡 <b>Role:</b> <code>{s['role']}</code>\n"
            f"🔍 <b>Searches Remaining:</b> <code>{s['searches_left']} / {s['searches_limit']}</code>\n"
            f"📥 <b>Requests Remaining:</b> <code>{s['requests_left']} / {s['requests_limit']}</code>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("≼ Back to Start", callback_data="start_menu")]])
        await q.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
    elif d == "bot_owner":
        await q.answer()
        await q.message.edit_text("👑 <b>Bot Owner:</b> <code>7261537212</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("≼ Back", callback_data="start_menu")]]))
