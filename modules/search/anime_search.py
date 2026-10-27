import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.search.handlers import (
    perform_search,
    _parse_provider_prefix,
    _lookup_mediagoer_card_sync,
    _lookup_mediagoer_series_sync,
)

logger = logging.getLogger(__name__)
ANIME_PROVIDERS = ("anilist", "mal", "kitsu")


async def perform_anime_search(update: Update, context: ContextTypes.DEFAULT_TYPE, search_term: str, page: int = 1):
    """Searches indexed Anime & Manga files in the database."""
    await perform_search(
        update,
        context,
        search_term,
        page=page,
        category="anime",
        req_callback_prefix="areq_from_search_",
        card_callback_prefix="acard_lookup_",
        page_callback_prefix="asearch_page_",
    )


async def animesearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/animesearch <query> — Dedicated Anime & Manga search command."""
    msg = update.effective_message
    if not msg:
        return
    if context.args:
        await perform_anime_search(update, context, " ".join(context.args).strip(), 1)
        return
    if msg.reply_to_message and msg.reply_to_message.text:
        await perform_anime_search(update, context, msg.reply_to_message.text.strip(), 1)
        return

    txt = (
        "⛩️ <b>Anime & Manga Search Engine</b>\n\n"
        "• <code>/animesearch &lt;title&gt;</code> — Search indexed Anime & Manga in the library\n"
        "• <code>/animeinfo &lt;title or URL&gt;</code> — Get live Anime/Manga Unicode card from AniList, MyAnimeList (MAL), or Kitsu\n"
        "• <code>/animeseries &lt;title or ID&gt;</code> — Get full Anime/Manga/Light Novel franchise relations & seasons\n"
        "• <code>/requestanime &lt;title&gt;</code> — Request a missing Anime or Manga"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("≼ Back to Search Menu", callback_data="search_menu")]])
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        await update.callback_query.answer()
    else:
        await msg.reply_text(txt, parse_mode="HTML", reply_markup=kb)


async def animeinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/animeinfo <query_or_url> — Fetches an Anime/Manga Unicode card from AniList, MAL, or Kitsu via Mediagoer."""
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        await msg.reply_text(
            "⛩️ <b>Anime & Manga Metadata Card (<code>/animeinfo</code>)</b>\n\n"
            "• <code>/animeinfo Solo Leveling</code>\n"
            "• <code>/animeinfo mal: Frieren</code>\n"
            "• <code>/animeinfo anilist: Chainsaw Man</code>\n"
            "• <code>/animeinfo kitsu: Attack on Titan</code>",
            parse_mode="HTML",
        )
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    if prov not in ANIME_PROVIDERS:
        prov = None
    wait_msg = await msg.reply_text(f"⛩️ Fetching anime/manga metadata card for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    item, card_text = await asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov, ANIME_PROVIDERS)
    if not item or not card_text:
        await wait_msg.edit_text(f"❌ Could not find anime/manga metadata on AniList/MAL/Kitsu for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    kb = []
    if item.get("url"):
        kb.append([InlineKeyboardButton(f"🌐 View on {(item.accessSystem or 'AniList').upper()}", url=item["url"])])
    if item.mediaID:
        kb.append([InlineKeyboardButton("⛩️ View Full Franchise / Seasons", callback_data=f"aseries_lookup_{item.accessSystem}:{item.mediaID}"[:60])])
    kb.append([InlineKeyboardButton("🔍 Search Anime in Database", callback_data=f"asearch_page_{(item.get('title') or clean_q)[:25]}_1")])

    await wait_msg.edit_text(
        html.escape(card_text),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
        disable_web_page_preview=True,
    )


async def animeseries_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/animeseries <query_or_id> — Fetches all seasons, sequels, manga, and light novels in an Anime franchise."""
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        await msg.reply_text(
            "⛩️ <b>Anime & Manga Franchise Lookup (<code>/animeseries</code>)</b>\n\n"
            "• <code>/animeseries Solo Leveling</code>\n"
            "• <code>/animeseries mal: 52991</code>\n"
            "• <code>/animeseries anilist: Demon Slayer</code>",
            parse_mode="HTML",
        )
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    if prov not in ANIME_PROVIDERS:
        prov = None
    wait_msg = await msg.reply_text(f"⛩️ Fetching anime/manga franchise relations for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    series_text = await asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov, ANIME_PROVIDERS)
    if not series_text:
        await wait_msg.edit_text(f"❌ No anime/manga franchise entries found for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    await wait_msg.edit_text(html.escape(series_text[:4000]), parse_mode="HTML", disable_web_page_preview=True)


async def anime_search_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data

    if d == "anime_search_menu":
        await animesearch_command(update, context)
    elif d.startswith("asearch_page_"):
        parts = d.replace("asearch_page_", "", 1).rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            await perform_anime_search(update, context, parts[0], int(parts[1]))
    elif d.startswith("acard_lookup_"):
        query = d.replace("acard_lookup_", "", 1)
        await q.answer("Fetching AniList/MAL/Kitsu card...")
        prov, clean_q = _parse_provider_prefix(query)
        item, card_text = await asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov, ANIME_PROVIDERS)
        if item and card_text:
            kb = [[InlineKeyboardButton("≼ Back to Anime Search", callback_data=f"asearch_page_{clean_q[:25]}_1")]]
            await q.message.edit_text(html.escape(card_text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No anime metadata found.", show_alert=True)
    elif d.startswith("aseries_lookup_"):
        query = d.replace("aseries_lookup_", "", 1)
        await q.answer("Fetching anime franchise...")
        prov, clean_q = _parse_provider_prefix(query)
        series_text = await asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov, ANIME_PROVIDERS)
        if series_text:
            kb = [[InlineKeyboardButton("≼ Back to Anime Search", callback_data=f"asearch_page_{clean_q[:25]}_1")]]
            await q.message.edit_text(html.escape(series_text[:4000]), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No franchise entries found.", show_alert=True)
