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
MOVIE_PROVIDERS = ("imdb", "letterboxd")


async def perform_movie_search(update: Update, context: ContextTypes.DEFAULT_TYPE, search_term: str, page: int = 1):
    """Searches indexed Movie & TV Series files in the database."""
    await perform_search(
        update,
        context,
        search_term,
        page=page,
        category="movie",
        req_callback_prefix="mreq_from_search_",
        card_callback_prefix="mcard_lookup_",
        page_callback_prefix="msearch_page_",
    )


async def moviesearch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/moviesearch <query> — Dedicated Movie & TV Series search command."""
    msg = update.effective_message
    if not msg:
        return
    if context.args:
        await perform_movie_search(update, context, " ".join(context.args).strip(), 1)
        return
    if msg.reply_to_message and msg.reply_to_message.text:
        await perform_movie_search(update, context, msg.reply_to_message.text.strip(), 1)
        return

    txt = (
        "🎬 <b>Movie & TV Series Search Engine</b>\n\n"
        "• <code>/moviesearch &lt;title&gt;</code> — Search indexed Movies & TV Shows in the library\n"
        "• <code>/movieinfo &lt;title or IMDb/Letterboxd URL&gt;</code> — Get live Movie Unicode card from IMDb or Letterboxd\n"
        "• <code>/movieseries &lt;collection or TV series&gt;</code> — List all movies in a Letterboxd collection or episodes in an IMDb series\n"
        "• <code>/requestmovie &lt;title&gt;</code> — Request a missing Movie or TV Show"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("≼ Back to Search Menu", callback_data="search_menu")]])
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        await update.callback_query.answer()
    else:
        await msg.reply_text(txt, parse_mode="HTML", reply_markup=kb)


async def movieinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/movieinfo <query_or_url> — Fetches a Movie/TV Unicode card from IMDb or Letterboxd via Mediagoer."""
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        await msg.reply_text(
            "🎬 <b>Movie Metadata Card (<code>/movieinfo</code>)</b>\n\n"
            "• <code>/movieinfo The Scandal</code>\n"
            "• <code>/movieinfo imdb: tt1375666</code>\n"
            "• <code>/movieinfo letterboxd: parasite-2019</code>",
            parse_mode="HTML",
        )
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    if prov not in MOVIE_PROVIDERS:
        prov = None
    wait_msg = await msg.reply_text(f"🎬 Fetching movie metadata card for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    item, card_text = await asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov, MOVIE_PROVIDERS)
    if not item or not card_text:
        await wait_msg.edit_text(f"❌ Could not find movie metadata on IMDb/Letterboxd for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    kb = []
    if item.get("url"):
        kb.append([InlineKeyboardButton(f"🌐 View on {(item.accessSystem or 'IMDb').upper()}", url=item["url"])])
    if item.get("seriesID") or item.get("series") or item.get("kind") == "tv series":
        s_id = item.get("seriesID") or item.mediaID
        kb.append([InlineKeyboardButton("🎬 View Collection / Episodes", callback_data=f"mseries_lookup_{item.accessSystem}:{s_id}"[:60])])
    kb.append([InlineKeyboardButton("🔍 Search Movie in Database", callback_data=f"msearch_page_{(item.get('title') or clean_q)[:25]}_1")])

    await wait_msg.edit_text(
        html.escape(card_text),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb),
        disable_web_page_preview=True,
    )


async def movieseries_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/movieseries <query_or_id> — Fetches film collection (Letterboxd) or TV episodes (IMDb) via Mediagoer."""
    msg = update.effective_message
    if not msg:
        return
    raw_q = " ".join(context.args).strip() if context.args else ""
    if not raw_q and msg.reply_to_message and msg.reply_to_message.text:
        raw_q = msg.reply_to_message.text.strip()

    if not raw_q:
        await msg.reply_text(
            "🎬 <b>Movie Collection & TV Series Lookup (<code>/movieseries</code>)</b>\n\n"
            "• <code>/movieseries letterboxd: the-dark-knight-collection</code>\n"
            "• <code>/movieseries imdb: tt0903747</code>",
            parse_mode="HTML",
        )
        return

    prov, clean_q = _parse_provider_prefix(raw_q)
    if prov not in MOVIE_PROVIDERS:
        prov = None
    wait_msg = await msg.reply_text(f"🎬 Fetching movie collection / episodes for <b>{html.escape(clean_q)}</b>...", parse_mode="HTML")

    series_text = await asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov, ("letterboxd", "imdb"))
    if not series_text:
        await wait_msg.edit_text(f"❌ No movie collection or episode list found for <b>{html.escape(clean_q)}</b>.", parse_mode="HTML")
        return

    await wait_msg.edit_text(html.escape(series_text[:4000]), parse_mode="HTML", disable_web_page_preview=True)


async def movie_search_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data

    if d == "movie_search_menu":
        await moviesearch_command(update, context)
    elif d.startswith("msearch_page_"):
        parts = d.replace("msearch_page_", "", 1).rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            await perform_movie_search(update, context, parts[0], int(parts[1]))
    elif d.startswith("mcard_lookup_"):
        query = d.replace("mcard_lookup_", "", 1)
        await q.answer("Fetching IMDb/Letterboxd card...")
        prov, clean_q = _parse_provider_prefix(query)
        item, card_text = await asyncio.to_thread(_lookup_mediagoer_card_sync, clean_q, prov, MOVIE_PROVIDERS)
        if item and card_text:
            kb = [[InlineKeyboardButton("≼ Back to Movie Search", callback_data=f"msearch_page_{clean_q[:25]}_1")]]
            await q.message.edit_text(html.escape(card_text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No movie metadata found.", show_alert=True)
    elif d.startswith("mseries_lookup_"):
        query = d.replace("mseries_lookup_", "", 1)
        await q.answer("Fetching collection/episodes...")
        prov, clean_q = _parse_provider_prefix(query)
        series_text = await asyncio.to_thread(_lookup_mediagoer_series_sync, clean_q, prov, ("letterboxd", "imdb"))
        if series_text:
            kb = [[InlineKeyboardButton("≼ Back to Movie Search", callback_data=f"msearch_page_{clean_q[:25]}_1")]]
            await q.message.edit_text(html.escape(series_text[:4000]), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.answer("No collection/episode entries found.", show_alert=True)
