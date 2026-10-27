import os
import random
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.user_db import add_or_update_user_db, get_user_role_db, set_helper_started_db
from modules.database.config_db import get_template, format_template_string
from modules.allowance.referral import process_referral_with_notification
from modules.allowance.allowance import get_user_quota_summary

HELPER_CATEGORY_CONFIG = {
    "book": {
        "label": "Books",
        "username_envs": ("BOOK_HELPER_BOT_USERNAME", "BOOK_HELPER_USERNAME", "BOOK_HELPER_NAME", "HELPER_BOT_USERNAME"),
        "token_envs": ("BOOK_HELPER_BOT_TOKENS", "BOOK_HELPER_TOKENS", "BOOK_HELPER_TOKEN", "HELPER_BOT_TOKENS"),
    },
    "movie": {
        "label": "Movies",
        "username_envs": ("MOVIE_HELPER_BOT_USERNAME", "MOVIE_HELPER_USERNAME", "MOVIE_HELPER_NAME", "HELPER_BOT_USERNAME"),
        "token_envs": ("MOVIE_HELPER_BOT_TOKENS", "MOVIE_HELPER_TOKENS", "MOVIE_HELPER_TOKEN", "HELPER_BOT_TOKENS"),
    },
    "anime": {
        "label": "Anime",
        "username_envs": ("ANIME_HELPER_BOT_USERNAME", "ANIME_HELPER_USERNAME", "ANIME_HELPER_NAME", "HELPER_BOT_USERNAME"),
        "token_envs": ("ANIME_HELPER_BOT_TOKENS", "ANIME_HELPER_TOKENS", "ANIME_HELPER_TOKEN", "HELPER_BOT_TOKENS"),
    },
}


def _split_env_list(raw_value: str):
    if not raw_value:
        return []
    values = []
    for chunk in raw_value.replace(";", ",").replace("\n", ",").replace("|", ",").split(","):
        item = chunk.strip().strip("@ ")
        if item:
            values.append(item)
    return values


def _read_helper_values(category: str, env_key_name: str):
    config = HELPER_CATEGORY_CONFIG.get(category, {})
    env_names = config.get(env_key_name, ())
    values = []
    for key in env_names:
        value = os.getenv(key)
        if value:
            values.extend(_split_env_list(value))
    return values


def get_helper_bot_username(category: str):
    values = _read_helper_values(category, "username_envs")
    if values:
        return random.choice(values).strip("@")
    return ""


def get_helper_bot_token(category: str):
    values = _read_helper_values(category, "token_envs")
    if values:
        return random.choice(values)
    return ""


async def fetch_helper_bot_username_from_token(category: str, context: ContextTypes.DEFAULT_TYPE | None = None):
    username = get_helper_bot_username(category)
    if username:
        return username

    token_values = _read_helper_values(category, "token_envs")
    if not token_values:
        return ""

    token = random.choice(token_values)
    try:
        bot = Bot(token)
        me = await bot.get_me()
        returned_username = (me.username or "").strip("@")
        if returned_username:
            return returned_username
    except Exception:
        pass

    # Final fallback: if the token itself is a Telegram bot token, the username is not discoverable without API access.
    # In that case, we keep the token-based selection but avoid crashing.
    return ""


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
    elif args and args[0].startswith("helper_init_"):
        category = args[0].replace("helper_init_", "", 1).strip("_").lower()
        label = HELPER_CATEGORY_CONFIG.get(category, {}).get("label", category.title())
        referral_notice = f"\n\n✅ <b>{label} Helper Bot Activated!</b> You can now click any {label.lower()} search result to receive files in the posting channel and DM."

    tpl = get_template("start")
    raw_txt = tpl.get("text") or "Hi <b>{user_name}</b>, welcome to <b>{bot_title}</b>! 👋"
    text = format_template_string(raw_txt, {"user_name": user.first_name or "User"}) + referral_notice

    bot_uname = context.bot.username or "Bot"
    ref_link = f"https://t.me/{bot_uname}?start=ref_{user.id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20and%20earn%20%2B10%20bonus%20quota"

    kb = [
        [InlineKeyboardButton("🔍 Search All", callback_data="search_menu"), InlineKeyboardButton("📖 Help Menu", callback_data="help_button")],
        [InlineKeyboardButton("🎬 Movie Search", callback_data="movie_search_menu"), InlineKeyboardButton("⛩️ Anime Search", callback_data="anime_search_menu")],
        [InlineKeyboardButton("📚 Books Helper", callback_data="helper_menu_book"), InlineKeyboardButton("🎬 Movies Helper", callback_data="helper_menu_movie")],
        [InlineKeyboardButton("⛩️ Anime Helper", callback_data="helper_menu_anime"), InlineKeyboardButton("📊 My Quota", callback_data="quota_menu")],
        [InlineKeyboardButton("📤 Refer & Earn +10", url=share_url)],
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
    elif d.startswith("helper_menu_"):
        await q.answer()
        category = d.replace("helper_menu_", "", 1).strip("_").lower()
        label = HELPER_CATEGORY_CONFIG.get(category, {}).get("label", category.title())
        helper_username = await fetch_helper_bot_username_from_token(category, context)
        helper_token = get_helper_bot_token(category)
        if helper_username:
            start_link = f"https://t.me/{helper_username}?start=helper_init_{category}"
            helper_note = "Random helper bot selected from the configured category pool."
            if helper_token:
                helper_note = "Random helper bot and token selected from the configured category pool."
            txt = (
                f"📦 <b>{label} Helper Bot</b>\n\n"
                f"Start the dedicated helper bot here: <a href='{start_link}'>@{helper_username}</a>\n\n"
                f"{helper_note}\n"
                f"This helper is intended only for {label.lower()} file delivery in the posting channel and DM."
            )
        else:
            env_name = next(iter(HELPER_CATEGORY_CONFIG.get(category, {}).get("username_envs", ("HELPER_BOT_USERNAME",))), "HELPER_BOT_USERNAME")
            txt = (
                f"📦 <b>{label} Helper Bot</b>\n\n"
                f"No helper bot is configured yet for this category. Add <code>{env_name}</code> to your env.txt or .env file to enable dedicated {label.lower()} delivery.\n\n"
                f"You can also provide a comma-separated token list in <code>{category.upper()}_HELPER_BOT_TOKENS</code> and the bot will fetch the username automatically using the token."
            )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("≼ Back to Start", callback_data="start_menu")]])
        await q.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
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
