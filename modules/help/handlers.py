from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.user_db import get_user_role_db
from modules.database.config_db import get_template, format_template_string
from modules.log.startup_log import send_log_with_fallback

USER_HELP_MAIN = (
    "📖 <b>{bot_title} — Complete User Guide (/help)</b>\n\n"
    "Welcome! This bot indexes, searches, and delivers <b>Books, Audiobooks, Movies, TV Series, Anime & Manga</b> powered by <b>Mediagoer</b>:\n\n"
    "🔹 <b>Search & Mediagoer Lookup Commands:</b>\n"
    "• <code>/search &lt;keyword&gt;</code> — Search all indexed Books, Audiobooks, Movies & Anime\n"
    "• <code>/moviesearch &lt;title&gt;</code> — Search indexed Movies & TV Series\n"
    "• <code>/animesearch &lt;title&gt;</code> — Search indexed Anime & Manga\n"
    "• <code>/info &lt;title&gt;</code> | <code>/movieinfo</code> | <code>/animeinfo</code> — Get live Unicode metadata card\n"
    "• <code>/series &lt;name&gt;</code> | <code>/movieseries</code> | <code>/animeseries</code> — Get full series/franchise titles\n\n"
    "🔹 <b>Request & Quota Commands:</b>\n"
    "• <code>/request &lt;title&gt;</code> — Request a Book or Audiobook (Audible / Goodreads / Storytel)\n"
    "• <code>/requestmovie &lt;title&gt;</code> — Request a Movie or TV Show (IMDb / Letterboxd)\n"
    "• <code>/requestanime &lt;title&gt;</code> — Request an Anime or Manga (AniList / MAL / Kitsu)\n"
    "• <code>/quota</code> — View your daily search & request quota\n"
    "• <code>/refer</code> — Get your invite link (+10 search & +10 request bonus)\n\n"
    "👇 <b>Tap any category button below for detailed instructions:</b>"
)

USER_HELP_SECTIONS = {
    "help_sec_search": (
        "🔍 <b>How to Search & Use Mediagoer Cards</b>\n\n"
        "1. Use <code>/search &lt;keyword&gt;</code> for all media, <code>/moviesearch &lt;title&gt;</code> for Movies/TV, or <code>/animesearch &lt;title&gt;</code> for Anime/Manga.\n"
        "2. The bot searches indexed files across <b>title, series, creator/director/studio, narrator, genres, language, country, storyline, and filename</b>.\n"
        "3. Use <code>/info &lt;title&gt;</code> (or <code>/movieinfo</code>, <code>/animeinfo</code>) to fetch live Unicode metadata cards across <b>IMDb, Letterboxd, MyAnimeList, AniList, Kitsu, Goodreads, Audible, and Storytel</b>.\n"
        "4. Use <code>/series &lt;name&gt;</code> (or <code>/movieseries</code>, <code>/animeseries</code>) to list every title and short info in a series or franchise."
    ),
    "help_sec_requests": (
        "📥 <b>How to Request Books, Movies & Anime</b>\n\n"
        "1. <b>Books & Audiobooks:</b> Use <code>/request &lt;title&gt;</code> to match from Audible, Goodreads, and Storytel.\n"
        "2. <b>Movies & TV Series:</b> Use <code>/requestmovie &lt;title&gt;</code> to match from IMDb and Letterboxd.\n"
        "3. <b>Anime & Manga:</b> Use <code>/requestanime &lt;title&gt;</code> to match from AniList, MyAnimeList, and Kitsu.\n"
        "4. Tap a matched option button to attach its metadata, or use the 4-step manual request wizard."
    ),
    "help_sec_uploads": (
        "📤 <b>How File Uploads & Auto-Indexing Work</b>\n\n"
        "• <b>Supported Formats:</b> Books (<code>.epub, .pdf, .mobi, .azw3, .djvu</code>), Audiobooks (<code>.mp3, .m4b, .aax, .flac</code>), Movies & Anime (<code>.mkv, .mp4, .avi, .mov, .webm, .m4v, .srt</code>), and Manga (<code>.cbz, .cbr</code>).\n"
        "• <b>Modular Routing:</b> Uploads automatically route to <code>book_index</code>, <code>movie_index</code>, or <code>anime_index</code> and get captioned with the Mediagoer Unicode card layout.\n"
        "• <b>Rate-Limited Queue:</b> Indexing runs at max <b>10 files per batch</b> with a <b>10-second cooldown</b> between batches."
    ),
    "help_sec_quota": (
        "📊 <b>How the Quota System Works</b>\n\n"
        "• <b>Searching & Card Lookups are Free:</b> Entering <code>/search</code>, <code>/info</code>, or <code>/series</code> consumes <b>0 quota</b>.\n"
        "• <b>Search Quota Deduction:</b> 1 search quota is deducted <b>only</b> when your selected file is successfully delivered.\n"
        "• <b>Request Quota Deduction:</b> 1 request quota is deducted <b>only</b> when your request is successfully posted to the Request Log."
    ),
    "help_sec_referral": (
        "🔗 <b>How Referrals Work (+10 Bonus Quota)</b>\n\n"
        "• Run <code>/refer</code> to get your unique referral link (<code>?start=ref_&lt;id&gt;</code>).\n"
        "• When a <b>first-time user</b> starts the bot through your link, <b>both you and your friend receive +10 Search Quota and +10 Request Quota</b>!"
    ),
    "help_sec_tempfiles": (
        "⏳ <b>How Temporary File Delivery Works</b>\n\n"
        "1. Make sure you have started @{helper_bot_username}.\n"
        "2. When you click a search result button, the bot posts the file to the <b>File Posting Channel</b> and mirrors it to your DM.\n"
        "3. The file in the Posting Channel is <b>auto-deleted after 2 minutes</b> to keep storage clean."
    ),
    "help_sec_roles": (
        "🛡 <b>Roles, Quotas & Permissions</b>\n\n"
        "• <b>Banned:</b> 0 quota (restricted access)\n"
        "• <b>Normal User:</b> 10 quota (uploads need approval)\n"
        "• <b>Promoter:</b> 20 quota (boosted normal user)\n"
        "• <b>Volunteer:</b> 30 quota (direct file indexing without approval)\n"
        "• <b>Moderator:</b> 40 quota (manages book/movie/anime request queue & statuses)\n"
        "• <b>Admin / Owner:</b> Unlimited quota + system & role control"
    ),
    "help_sec_formatting": (
        "✨ <b>Callback Buttons, Placeholders & Formatting</b>\n\n"
        "🔘 <b>What Inline Buttons Do:</b>\n"
        "• <b>Result Button:</b> Sends selected file to Posting Channel & DM\n"
        "• <b>Get Media Card:</b> Generates the Unicode Mediagoer card for the query\n"
        "• <b>View Full Series:</b> Lists all books, audiobooks, movies, or anime seasons in the franchise\n"
        "• <b>Request Title:</b> Opens Mediagoer-backed request options\n"
        "• <b>Approve / Reject:</b> Allows or blocks file indexing"
    ),
}

ADMIN_HELP_MAIN = (
    "👑 <b>Admin & Owner Control Panel (/adminhelp)</b>\n\n"
    "Restricted documentation for <b>Admins & Owners</b>:\n\n"
    "🔹 <b>Role & User Commands:</b>\n"
    "• <code>/addvol &lt;user&gt;</code> — Assign Volunteer (30 quota, direct indexing)\n"
    "• <code>/addprom &lt;user&gt;</code> — Assign Promoter (20 quota)\n"
    "• <code>/addmod &lt;user&gt;</code> — Assign Moderator (40 quota, request queue)\n"
    "• <code>/addadmin &lt;user&gt;</code> — Assign Admin (Unlimited, Owner only)\n"
    "• <code>/gift &lt;user_id&gt; &lt;search&gt; &lt;req&gt;</code> — Gift bonus quota\n"
    "• <code>/ban &lt;user&gt; [reason]</code> & <code>/unban &lt;user&gt;</code>\n\n"
    "🔹 <b>Indexing, Config & Template Commands:</b>\n"
    "• <code>/index</code> | <code>/indexmovie</code> | <code>/indexanime</code> — Start indexing wizard or index replied file\n"
    "• <code>/customize</code> — Open button-driven Bot Settings & Template Dashboard\n"
    "• <code>/setconfig &lt;k&gt; &lt;v&gt;</code> | <code>/getconfig &lt;k&gt;</code> | <code>/reloadconfig</code>\n"
    "• <code>/broadcast &lt;target&gt; &lt;msg&gt;</code> | <code>/stats</code> | <code>/log</code>"
)

ADMIN_HELP_SECTIONS = {
    "adm_sec_vol": "🎖 <b>Add Volunteer (<code>/addvol &lt;user&gt;</code>)</b>\nGrants <b>30 daily quota</b> and allows direct book, movie, and anime file indexing without waiting for admin approval.",
    "adm_sec_prom": "🚀 <b>Add Promoter (<code>/addprom &lt;user&gt;</code>)</b>\nBoosts a normal user to <b>20 daily search & request quota</b>.",
    "adm_sec_mod": "🛡 <b>Add Moderator (<code>/addmod &lt;user&gt;</code>)</b>\nGrants <b>40 daily quota</b> and access to <b>Show Options</b> on Request Log entries.",
    "adm_sec_admin": "👑 <b>Add Admin (<code>/addadmin &lt;user&gt;</code>)</b>\nGrants <b>Unlimited quota</b>, upload approval rights, role assignment, broadcast, and log access.",
    "adm_sec_queue": "⏸ <b>Queue Control & Throttling</b>\nGlobal cap of <b>10 files per batch</b> + <b>10s sleep</b>. Direct user uploads pause bulk channel scans and run first.",
    "adm_sec_logs": "📋 <b>Log Configuration & Fallback</b>\nEvents route to specific log topics (Index, Request, Group, Channel, User).",
    "adm_sec_index": (
        "📚🎬⛩️ <b>Manual Indexing Commands</b>\n\n"
        "• <code>/index</code> — Interactive step-by-step channel range wizard\n"
        "• <code>/indexmovie</code> — Reply to a movie video/file to index with IMDb/Letterboxd metadata\n"
        "• <code>/indexanime</code> — Reply to an anime/manga file to index with AniList/MAL/Kitsu metadata\n"
        "• <code>/index t.me/channel/100-300</code>"
    ),
    "adm_sec_usermgmt": "👥 <b>User Management</b>\nUse <code>/ban &lt;user&gt; [reason]</code>, <code>/ban_pm</code>, <code>/ban_support</code>, <code>/unban &lt;user&gt;</code>, and <code>/gift &lt;user_id&gt; &lt;s_bonus&gt; &lt;r_bonus&gt;</code>.",
}


def build_user_help_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🔍 Search & Cards", callback_data="help_sec_search"), InlineKeyboardButton("📥 Requests", callback_data="help_sec_requests")],
        [InlineKeyboardButton("📤 Uploads", callback_data="help_sec_uploads"), InlineKeyboardButton("📊 Quota", callback_data="help_sec_quota")],
        [InlineKeyboardButton("🔗 Referral", callback_data="help_sec_referral"), InlineKeyboardButton("⏳ Temporary Files", callback_data="help_sec_tempfiles")],
        [InlineKeyboardButton("🛡 Roles", callback_data="help_sec_roles"), InlineKeyboardButton("✨ Formatting & Buttons", callback_data="help_sec_formatting")],
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("👑 Admin Commands (/adminhelp)", callback_data="help_open_admin")])
    kb.append([InlineKeyboardButton("≼ Back to Start", callback_data="start_menu")])
    return InlineKeyboardMarkup(kb)


def build_admin_help_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🎖 Add Volunteer", callback_data="adm_sec_vol"), InlineKeyboardButton("🚀 Add Promoter", callback_data="adm_sec_prom")],
        [InlineKeyboardButton("🛡 Add Moderator", callback_data="adm_sec_mod"), InlineKeyboardButton("👑 Add Admin", callback_data="adm_sec_admin")],
        [InlineKeyboardButton("⏸ Queue Control", callback_data="adm_sec_queue"), InlineKeyboardButton("📋 Logs", callback_data="adm_sec_logs")],
        [InlineKeyboardButton("📚 Indexing", callback_data="adm_sec_index"), InlineKeyboardButton("👥 User Management", callback_data="adm_sec_usermgmt")],
        [InlineKeyboardButton("🪄 Customize Bot (/customize)", callback_data="cust_open_main")],
        [InlineKeyboardButton("≼ Back to User Help", callback_data="help_menu")],
    ]
    return InlineKeyboardMarkup(kb)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    role = get_user_role_db(user.id)
    is_admin = role in ("Admin", "Owner")

    tpl = get_template("help")
    raw = tpl.get("text") or USER_HELP_MAIN
    text = format_template_string(raw, {"user_name": user.first_name or "User", "chat_title": update.effective_chat.title or "Private Chat"})
    markup = build_user_help_keyboard(is_admin)

    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    role = get_user_role_db(user.id)
    if role not in ("Admin", "Owner"):
        if update.callback_query:
            await update.callback_query.answer("⛔ Access denied — Not authorized.", show_alert=True)
        else:
            await msg.reply_text("⛔ <b>Access denied:</b> You are not authorized to view admin commands.", parse_mode="HTML")
        await send_log_with_fallback(
            context.bot,
            f"⚠️ <b>Unauthorized /adminhelp Attempt</b>\n👤 User: {user.full_name} (<code>{user.id}</code>)\n🛡 Role: <code>{role}</code>",
            "admin_log_group_id",
            "user_log_topic_id",
        )
        return

    tpl = get_template("adminhelp")
    raw = tpl.get("text") or ADMIN_HELP_MAIN
    text = format_template_string(raw, {"user_name": user.first_name or "Admin"})
    markup = build_admin_help_keyboard()

    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def help_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    data = q.data
    user = q.from_user
    role = get_user_role_db(user.id)
    is_admin = role in ("Admin", "Owner")

    if data in ("help_button", "help_menu"):
        await q.answer()
        await help_command(update, context)
    elif data == "help_open_admin":
        await adminhelp_command(update, context)
    elif data in USER_HELP_SECTIONS:
        await q.answer()
        txt = format_template_string(USER_HELP_SECTIONS[data], {"user_name": user.first_name or "User"})
        await q.message.edit_text(txt, parse_mode="HTML", reply_markup=build_user_help_keyboard(is_admin))
    elif data in ADMIN_HELP_SECTIONS:
        if not is_admin:
            await q.answer("⛔ Access denied — Not authorized.", show_alert=True)
            return
        await q.answer()
        txt = format_template_string(ADMIN_HELP_SECTIONS[data], {"user_name": user.first_name or "Admin"})
        await q.message.edit_text(txt, parse_mode="HTML", reply_markup=build_admin_help_keyboard())
