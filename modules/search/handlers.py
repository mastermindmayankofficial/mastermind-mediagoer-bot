import os
import re
import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.file_db import search_indexed_files_db, get_file_by_id_db, log_file_delivery_db, mark_delivery_deleted_db
from modules.database.config_db import get_config, get_config_int, get_config_bool
from modules.database.user_db import has_started_helper_bot_db, set_helper_started_db
from modules.allowance.allowance import can_user_search, deduct_search_quota, get_user_quota_summary
from modules.log.startup_log import send_log_with_fallback
from mediagoer import Mediagoer, PROVIDER_ALIASES

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 5
_MG = Mediagoer(audible_marketplace="in", storytel_locale="in")

CATEGORY_BADGES = {
    "book": "📚 Book",
    "audiobook": "🎧 Audiobook",
    "movie": "🎬 Movie / TV",
    "anime": "⛩️ Anime",
    "manga": "🗯️ Manga",
}


def _format_result_item(idx: int, row: dict) -> str:
    """
    Formats a single indexed database search result with Unicode card fields
    (Title, Series, Year, Rating, Language, Country, Genres, Creator, Size, Category).
    """
    title = html.escape(row.get("title") or row.get("file_name") or "Unknown Title")
    series = html.escape(row.get("series") or "")
    author = html.escape(row.get("author") or "")
    narrator = html.escape(row.get("narrator") or "")
    length_str = html.escape(row.get("length_str") or "")
    rel_date = html.escape(row.get("release_date") or "")
    rating = html.escape(row.get("rating") or "")
    language = html.escape(row.get("language") or "")
    country = html.escape(row.get("country") or "")
    genres = html.escape(row.get("genres") or "")
    raw_cat = (row.get("category") or "book").lower()
    cat_label = CATEGORY_BADGES.get(raw_cat, f"📁 {html.escape(raw_cat.title())}")
    prov = (row.get("provider") or "").upper()
    size_b = int(row.get("file_size") or 0)
    size_str = f"{size_b / (1024*1024):.1f}MB" if size_b >= 1024 * 1024 else f"{size_b / 1024:.0f}KB"

    lines = [f"<b>{idx}. 🏷 𝖳𝗂𝗍𝗅𝖾 : {title}</b> ({cat_label})"]
    if series and series != "N/A":
        lines.append(f"📚 𝖲𝖾𝗋𝗂𝖾𝗌 : {series}")
    if author and author not in ("N/A", "Unknown", "Unknown Author"):
        creator_lbl = "✍️ 𝖠𝗎𝗍𝗁𝗈𝗋" if raw_cat in ("book", "audiobook", "manga") else "🎬 𝖢𝗋𝖾𝖺𝗍𝗈𝗋/𝖲𝗍𝗎𝖽𝗂𝗈"
        lines.append(f"{creator_lbl} : {author}")
    if narrator and narrator != "N/A":
        lines.append(f"🎙 𝖭𝖺𝗋𝗋𝖺𝗍𝗈𝗋 : {narrator}")

    meta_parts = []
    if rel_date and rel_date != "N/A":
        meta_parts.append(f"🔮 𝖸𝖾𝖺𝗋 : {rel_date}")
    if rating and rating != "N/A":
        meta_parts.append(f"⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌 : {rating}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    loc_parts = []
    if language and language != "N/A":
        loc_parts.append(f"🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾 : {language}")
    if country and country != "N/A":
        loc_parts.append(f"🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒 : {country}")
    if loc_parts:
        lines.append(" | ".join(loc_parts))

    if genres and genres != "N/A":
        lines.append(f"🎭 𝖦𝖾𝗇𝖾𝗋𝗌 : {genres}")

    footer_parts = [f"📦 <i>{size_str}</i>"]
    if length_str and length_str != "N/A":
        footer_parts.append(f"⏱ {length_str}")
    if prov and prov not in ("BOOK", "MOVIE", "ANIME", "AUDIOBOOK"):
        footer_parts.append(f"🌐 {html.escape(prov)}")
    lines.append(" · ".join(footer_parts))
    return "\n".join(lines)


async def perform_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    search_term: str,
    page: int = 1,
    category: str = None,
    req_callback_prefix: str = "req_from_search_",
    card_callback_prefix: str = "card_lookup_",
    page_callback_prefix: str = "search_page_",
):
    search_term = search_term.strip()
    results = search_indexed_files_db(search_term, limit=50, category=category)
    total = len(results)
    bot_title = get_config("bot_title", "Mastermind Media & Library Bot")
    cat_header = f" ({category.upper()})" if category else ""

    kb = []
    if total > 0:
        tp = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        page = max(1, min(page, tp))
        slice_rows = results[(page - 1) * ITEMS_PER_PAGE : page * ITEMS_PER_PAGE]

        item_blocks = []
        for i, r in enumerate(slice_rows, start=(page - 1) * ITEMS_PER_PAGE + 1):
            item_blocks.append(_format_result_item(i, r))
            cat_icon = CATEGORY_BADGES.get((r.get("category") or "book").lower(), "📁").split()[0]
            btn_title = (r.get("title") or r.get("file_name") or "File")[:34]
            kb.append([InlineKeyboardButton(f"{cat_icon} {i}. {btn_title}", callback_data=f"file_dl_{r['id']}")])

        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("« Prev", callback_data=f"{page_callback_prefix}{search_term[:25]}_{page-1}"))
        nav.append(InlineKeyboardButton(f"{page} / {tp}", callback_data="noop"))
        if page < tp:
            nav.append(InlineKeyboardButton("Next »", callback_data=f"{page_callback_prefix}{search_term[:25]}_{page+1}"))
        kb.append(nav)

        txt = (
            f"🔍 <b>Search results{cat_header} from {html.escape(bot_title)}'s database</b>\n\n"
            f"<b>{html.escape(search_term)}</b> · {total} match{'es' if total != 1 else ''}\n\n"
            + "\n\n".join(item_blocks)
            + "\n\n❗️❗️❗️ <b>Select a title below to get the file instantly</b> ❗️❗️❗️"
        )
    else:
        txt = (
            f"🔍 <b>Search results{cat_header} from {html.escape(bot_title)}'s database</b>\n\n"
            f"<b>{html.escape(search_term)}</b> · 0 matches\n\n"
            f"No indexed files matched your query. Tap <b>📝 Request</b> below or use <code>/info {html.escape(search_term)}</code> to fetch its metadata card!"
        )

    kb.append([
        InlineKeyboardButton("🃏 Get Media Card", callback_data=f"{card_callback_prefix}{search_term[:32]}"),
        InlineKeyboardButton("📝 Request Title", callback_data=f"{req_callback_prefix}{search_term[:32]}"),
    ])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="search_cancel")])

    if update.callback_query:
        await update.callback_query.message.edit_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        await update.callback_query.answer()
    else:
        await update.effective_message.reply_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


def _parse_provider_prefix(raw_query: str, default_provider: str = None) -> tuple:
    q = (raw_query or "").strip()
    if not q:
        return default_provider, ""
    parts = q.split(None, 1)
    first_tok = parts[0].rstrip(":").lower()
    if first_tok in PROVIDER_ALIASES and len(parts) > 1:
        return PROVIDER_ALIASES[first_tok], parts[1].strip()
    if ":" in parts[0]:
        p_cand, rest = q.split(":", 1)
        if p_cand.strip().lower() in PROVIDER_ALIASES:
            return PROVIDER_ALIASES[p_cand.strip().lower()], rest.strip()
    return default_provider, q


def _lookup_mediagoer_card_sync(query: str, provider: str = None, provider_order: tuple = None) -> tuple:
    """
    Synchronous worker to fetch a Mediagoer MediaItem across one or multiple providers.
    Returns (item, card_text).
    """
    if re.match(r"^https?://", query, re.IGNORECASE):
        try:
            item = _MG.get(query)
            if item and item.get("title"):
                return item, item.format_card()
        except Exception:
            pass

    order = [provider] if provider else list(provider_order or ("goodreads", "audible", "storytel", "imdb", "anilist", "mal", "letterboxd", "kitsu"))
    for prov in order:
        if not prov:
            continue
        try:
            results = _MG.search(query, provider=prov, results=3)
            if results:
                top = results[0]
                if top.mediaID and (not top.get("plot") or not top.get("genres")):
                    try:
                        full = _MG.get(top.mediaID, provider=prov)
                        if full and full.get("title"):
                            top = full
                    except Exception:
                        pass
                return top, top.format_card()
        except Exception:
            continue
    return None, ""


def _lookup_mediagoer_series_sync(query: str, provider: str = None, provider_order: tuple = None) -> str:
    """
    Synchronous worker to fetch a Mediagoer Series/Franchise breakdown with all titles and short info.
    """
    order = [provider] if provider else list(provider_order or ("goodreads", "audible", "storytel", "anilist", "mal", "kitsu", "letterboxd", "imdb"))

    # 1. Direct series ID or URL lookup if numeric/ASIN/URL
    if re.match(r"^(https?://|\d+|B[0-9A-Z]{9}|tt\d+)", query.strip(), re.I):
        for prov in order:
            try:
                s_info = _MG.get_series_info(query, provider=prov)
                if s_info and "Titles" in s_info:
                    return s_info
            except Exception:
                continue

    # 2. Search by title first, extract seriesID or item mediaID, and fetch full series
    for prov in order:
        try:
            results = _MG.search(query, provider=prov, results=3)
            if results:
                top = results[0]
                if top.mediaID and not top.get("seriesID"):
                    try:
                        top = _MG.get(top.mediaID, provider=prov)
                    except Exception:
                        pass
                sid = top.get("seriesID") or top.mediaID
                if sid:
                    s_obj = _MG.get_series(sid, provider=prov)
                    if s_obj and (s_obj.get("items") or s_obj.get("books") or s_obj.get("audiobooks")):
                        return s_obj.format_series_info()
        except Exception:
            continue
    return ""


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /info <query_or_url> or /card <provider: query>
    Fetches the formatted Unicode metadata card across all 8 Mediagoer providers.
    """
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        help_txt = (
            "🃏 <b>Mediagoer Metadata Card Lookup (<code>/info</code> or <code>/card</code>)</b>\n\n"
            "Extract live formatted metadata cards across <b>8 providers</b>:\n"
            "• <code>/info The Scandal</code> (Auto-detects Book / Movie / Anime)\n"
            "• <code>/movieinfo Inception</code> or <code>/info imdb: Inception</code>\n"
            "• <code>/info letterboxd: Parasite</code>\n"
            "• <code>/animeinfo Frieren</code> or <code>/info mal: Frieren</code>\n"
            "• <code>/info anilist: Solo Leveling</code>\n"
            "• <code>/info kitsu: Attack on Titan</code>\n"
            "• <code>/info goodreads: Fourth Wing</code>\n"
            "• <code>/info audible: Project Hail Mary</code>\n"
            "• <code>/info storytel: Dune</code>"
        )
        await msg.reply_text(help_txt, parse_mode="HTML")
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    wait_msg = await msg.reply_text(f"🔎 Fetching metadata card for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    try:
        item, card_text = await asyncio.wait_for(
            asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov),
            timeout=18.0,
        )
    except Exception as e:
        logger.warning(f"/info lookup error: {e}")
        item, card_text = None, ""

    if not item or not card_text:
        await wait_msg.edit_text(f"❌ Could not find metadata for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    kb = []
    if item.get("url"):
        kb.append([InlineKeyboardButton(f"🌐 View on {(item.accessSystem or 'Source').upper()}", url=item["url"])])
    if item.get("seriesID") or item.get("series") or item.accessSystem in ("mal", "anilist", "kitsu"):
        s_id = item.get("seriesID") or item.mediaID or item.get("series")
        s_query = f"{item.accessSystem}:{s_id}"
        kb.append([InlineKeyboardButton("📚 View Full Series / Franchise", callback_data=f"series_lookup_{s_query[:40]}")])
    kb.append([InlineKeyboardButton("🔍 Search in Bot Database", callback_data=f"search_page_{(item.get('title') or clean_q)[:25]}_1")])

    await wait_msg.edit_text(
        html.escape(card_text),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        disable_web_page_preview=True,
    )


async def series_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /series <series_name_or_id_or_url>
    Fetches all titles in a book/audiobook series or movie/anime franchise with short info.
    """
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        help_txt = (
            "📚 <b>Series & Franchise Lookup (<code>/series</code>)</b>\n\n"
            "Get all titles, sequence numbers, ratings, formats, and short info for any Book Series, Audiobook Series, Movie Collection, or Anime Franchise:\n"
            "• <code>/series Fourth Wing</code>\n"
            "• <code>/series audible: The Empyrean</code>\n"
            "• <code>/series goodreads: 45175</code>\n"
            "• <code>/movieseries The Dark Knight</code>\n"
            "• <code>/animeseries Solo Leveling</code>"
        )
        await msg.reply_text(help_txt, parse_mode="HTML")
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    wait_msg = await msg.reply_text(f"📚 Fetching complete series/franchise info for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    try:
        series_text = await asyncio.wait_for(
            asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov),
            timeout=20.0,
        )
    except Exception as e:
        logger.warning(f"/series lookup error: {e}")
        series_text = ""

    if not series_text:
        await wait_msg.edit_text(f"❌ No series or franchise information found for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    await wait_msg.edit_text(
        html.escape(series_text[:4000]),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _auto_delete_posted_file(bot, posting_chat_id: int, message_id: int, log_id: int, delay_seconds: int, file_name: str, receiver_id: int):
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id=int(posting_chat_id), message_id=int(message_id))
    except Exception:
        pass
    deleted_at = mark_delivery_deleted_db(log_id)
    audit_txt = (
        f"🗑 <b>Temporary File Auto-Deleted (2m Timer)</b>\n\n"
        f"📁 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
        f"👤 <b>Receiver ID:</b> <code>{receiver_id}</code>\n"
        f"📢 <b>Channel / Msg ID:</b> <code>{posting_chat_id} / {message_id}</code>\n"
        f"⏱ <b>Deleted At:</b> <code>{deleted_at}</code>"
    )
    await send_log_with_fallback(bot, audit_txt, "admin_log_group_id", "channel_log_topic_id")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if context.args:
        await perform_search(update, context, " ".join(context.args).strip(), 1)
        return
    if msg.reply_to_message and msg.reply_to_message.text:
        await perform_search(update, context, msg.reply_to_message.text.strip(), 1)
        return

    txt = (
        "🔍 <b>Multi-Media Library Search Engine</b>\n\n"
        "• <code>/search &lt;keyword&gt;</code> — Search all indexed Books, Audiobooks, Movies & Anime\n"
        "• <code>/moviesearch &lt;title&gt;</code> — Search indexed Movies & TV Series\n"
        "• <code>/animesearch &lt;title&gt;</code> — Search indexed Anime & Manga\n"
        "• <code>/info &lt;title&gt;</code> — Live Mediagoer Unicode card (IMDb, Letterboxd, MAL, AniList, Kitsu, Goodreads, Audible, Storytel)\n"
        "• <code>/series &lt;name&gt;</code> — List all titles & short info in a Series/Franchise\n\n"
        "<i>(Searching is free — quota is only used when a file is delivered!)</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Movie Search", callback_data="movie_search_menu"), InlineKeyboardButton("⛩️ Anime Search", callback_data="anime_search_menu")],
        [InlineKeyboardButton("≼ Back to Start", callback_data="start_menu")],
    ])
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        await update.callback_query.answer()
    else:
        await msg.reply_text(txt, parse_mode="HTML", reply_markup=kb)


async def search_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data
    user = q.from_user

    if d == "search_menu":
        await search_command(update, context)
    elif d == "noop":
        await q.answer("Current Page")
    elif d == "search_cancel":
        await q.answer("Search closed.")
        await q.message.delete()
    elif d.startswith("search_page_"):
        parts = d.replace("search_page_", "", 1).rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            await perform_search(update, context, parts[0], int(parts[1]))
    elif d.startswith("card_lookup_"):
        query = d.replace("card_lookup_", "", 1)
        await q.answer("Fetching Mediagoer card...")
        prov, clean_q = _parse_provider_prefix(query)
        item, card_text = await asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov)
        if item and card_text:
            kb = []
            if item.get("seriesID") or item.get("series") or item.accessSystem in ("mal", "anilist", "kitsu"):
                s_id = item.get("seriesID") or item.mediaID or item.get("series")
                s_q = f"{item.accessSystem}:{s_id}"
                kb.append([InlineKeyboardButton("📚 View Full Series", callback_data=f"series_lookup_{s_q[:40]}")])
            kb.append([InlineKeyboardButton("≼ Back to Search", callback_data=f"search_page_{clean_q[:25]}_1")])
            await q.message.edit_text(html.escape(card_text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No external metadata found.", show_alert=True)
    elif d.startswith("series_lookup_"):
        query = d.replace("series_lookup_", "", 1)
        await q.answer("Fetching full series/franchise list...")
        prov, clean_q = _parse_provider_prefix(query)
        series_text = await asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov)
        if series_text:
            kb = [[InlineKeyboardButton("≼ Back to Search", callback_data=f"search_page_{clean_q[:25]}_1")]]
            await q.message.edit_text(html.escape(series_text[:4000]), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No series entries found.", show_alert=True)
    elif d.startswith("file_dl_"):
        row_id = int(d.replace("file_dl_", ""))
        if not can_user_search(user.id):
            await q.answer("⚠️ Daily search quota reached! Use /refer or wait for reset.", show_alert=True)
            return

        if get_config_bool("require_helper_bot_start", True) and not has_started_helper_bot_db(user.id):
            helper_uname = get_config("helper_bot_username", context.bot.username or "Bot").lstrip("@")
            start_url = f"https://t.me/{helper_uname}?start=helper_init"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🚀 Start @{helper_uname}", url=start_url)]])
            await q.answer("⚠️ Please start the helper bot first to receive the file.", show_alert=True)
            await q.message.reply_text("Please start the helper bot first to receive the file.", reply_markup=kb)
            return

        row = get_file_by_id_db(row_id)
        if not row:
            await q.answer("❌ File no longer exists in database.", show_alert=True)
            return

        storage_id = get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
        posting_id = get_config("posting_channel_id", fallback_env="SEARCH_CHAT_ID") or storage_id
        file_id = row.get("file_id")
        storage_msg_id = row.get("storage_message_id")
        file_name = row.get("title") or row.get("file_name") or "Media_File"

        await q.answer("📥 Preparing temporary delivery...")
        posted_msg = None
        dm_delivered = False

        if posting_id:
            try:
                if storage_msg_id and storage_id:
                    posted_msg = await context.bot.copy_message(chat_id=int(posting_id), from_chat_id=int(storage_id), message_id=int(storage_msg_id))
                elif file_id:
                    posted_msg = await context.bot.send_document(chat_id=int(posting_id), document=file_id, caption=f"📁 <b>{html.escape(file_name)}</b>\n⏳ <i>Auto-deletes in 2 minutes</i>", parse_mode="HTML")
            except Exception as ch_err:
                await send_log_with_fallback(
                    context.bot,
                    f"⚠️ <b>Helper/Bot Channel Admin Permission Error</b>\nCould not post to <code>{posting_id}</code>: <code>{ch_err}</code>",
                    "admin_log_group_id",
                    "channel_log_topic_id",
                )

        try:
            if storage_msg_id and storage_id:
                await context.bot.copy_message(chat_id=user.id, from_chat_id=int(storage_id), message_id=int(storage_msg_id))
                dm_delivered = True
            elif file_id:
                await context.bot.send_document(chat_id=user.id, document=file_id, caption=f"📁 <b>{html.escape(file_name)}</b>", parse_mode="HTML")
                dm_delivered = True
            set_helper_started_db(user.id, True)
        except Exception:
            pass

        if not posted_msg and not dm_delivered:
            await q.message.reply_text("❌ File delivery failed. No quota was deducted.")
            return

        deduct_search_quota(user.id)
        q_sum = get_user_quota_summary(user.id)

        post_mid = getattr(posted_msg, "message_id", 0) or 0
        clean_cid = str(posting_id).replace("-100", "") if posting_id else ""
        ch_link = f"https://t.me/c/{clean_cid}" if clean_cid else "DM Delivery"
        msg_link = f"https://t.me/c/{clean_cid}/{post_mid}" if (clean_cid and post_mid) else ch_link
        del_secs = get_config_int("file_delete_after_seconds", 120)

        reply_txt = (
            f"✅ <b>File Ready for Download!</b>\n\n"
            f"📁 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
            f"📢 <b>Posting Channel:</b> <a href=\"{ch_link}\">Open Channel</a>\n"
            f"🔗 <b>Message Link:</b> <a href=\"{msg_link}\">Message #{post_mid}</a>\n"
            f"💬 <b>DM Mirror:</b> {'Sent to your DM ✅' if dm_delivered else 'Channel Link Only'}\n"
            f"📊 <b>Remaining Search Quota:</b> <code>{q_sum['searches_left']}</code>\n\n"
            f"⏳ <i>This file in the posting channel will auto-delete in {del_secs // 60} minutes.</i>"
        )
        await q.message.reply_text(reply_txt, parse_mode="HTML")

        log_id = log_file_delivery_db(file_id or "", file_name, context.bot.username or "Bot", user.id, ch_link, msg_link, post_mid, "delivered")
        audit_msg = (
            f"📤 <b>File Shared (Temporary Delivery)</b>\n\n"
            f"🆔 <b>File ID:</b> <code>{html.escape(str(file_id)[:35])}</code>\n"
            f"📁 <b>Title:</b> <code>{html.escape(file_name)}</code>\n"
            f"🤖 <b>Sender:</b> @{context.bot.username or 'Bot'}\n"
            f"👤 <b>Receiver:</b> {html.escape(user.full_name)} (<code>{user.id}</code>)\n"
            f"🔗 <b>Link:</b> {msg_link}\n"
            f"📦 <b>Status:</b> <code>delivered (auto-delete in {del_secs}s)</code>"
        )
        await send_log_with_fallback(context.bot, audit_msg, "admin_log_group_id", "channel_log_topic_id")

        if posted_msg and post_mid and get_config_bool("auto_delete_enabled", True):
            asyncio.create_task(_auto_delete_posted_file(context.bot, int(posting_id), post_mid, log_id, del_secs, file_name, user.id))
