import os
import re
import html
import time
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.file_db import get_file_by_unique_id_db, save_indexed_file_db, get_connection as get_file_conn
from modules.database.config_db import get_config, get_config_int
from modules.database.user_db import get_user_role_db
from modules.log.startup_log import send_log_with_fallback
from mediagoer import Mediagoer, MediaItem

logger = logging.getLogger(__name__)

# Extensions for Books & Audiobooks
BOOK_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw3", ".djvu", ".txt", ".rtf", ".doc", ".docx"}
AUDIOBOOK_EXTENSIONS = {".mp3", ".m4b", ".aax", ".flac", ".ogg", ".opus", ".m4a"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".wmv"}
MANGA_EXTENSIONS = {".cbz", ".cbr"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".vtt"}

SUPPORTED_BOOK_EXTENSIONS = BOOK_EXTENSIONS | AUDIOBOOK_EXTENSIONS
SUPPORTED_EXTENSIONS = (
    BOOK_EXTENSIONS
    | AUDIOBOOK_EXTENSIONS
    | VIDEO_EXTENSIONS
    | MANGA_EXTENSIONS
    | SUBTITLE_EXTENSIONS
)

_BOOK_CACHE = {}
_MG = Mediagoer(provider="goodreads", audible_marketplace="in", storytel_locale="in")

QUEUE_STATE = {
    "running": False,
    "paused": False,
    "cancelled": False,
    "status": "idle",
    "fetched": 0,
    "remaining": 0,
    "forwarded": 0,
    "duplicates": 0,
    "deleted": 0,
    "skipped": 0,
    "filtered": 0,
    "start_time": 0.0,
    "card_chat_id": None,
    "card_msg_id": None,
}


def clean_filename_for_search(file_name: str) -> str:
    if not file_name:
        return ""
    name = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", file_name)
    name = re.sub(r"\[.*?\]|\(.*?\)|\{.*?\}", " ", name)
    noise = (
        r"\b(z-lib\.org|z-library|annas-archive|libgen|epub|pdf|azw3|kfx|mobi|djvu|"
        r"mp3|m4b|aax|audiobook|unabridged|abridged|64kbps|128kbps|320kbps)\b"
    )
    name = re.sub(noise, " ", name, flags=re.IGNORECASE)
    name = re.sub(r"[_\.\-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _item_to_meta_dict(item: MediaItem, default_category: str = "book") -> dict:
    """Converts a Mediagoer MediaItem into a standardized metadata dict."""
    title = item.get("title") or "Unknown Title"
    authors = [str(a) for a in (item.get("authors") or []) if str(a)]
    directors = [str(d) for d in (item.get("directors") or []) if str(d)]
    studios = [str(s) for s in (item.get("studios") or []) if str(s)]
    narrators = [str(n) for n in (item.get("narrators") or []) if str(n)]

    creator_str = ", ".join(authors or directors or studios) or "Unknown Author"
    narrator_str = ", ".join(narrators) if narrators else "N/A"
    series_label = item.get("full series") or item.get("series") or ""
    series_id = str(item.get("seriesID") or "")
    year = str(item.get("year") or "N/A")
    scale = item.default_rating_scale()
    raw_rating = item.get("rating")
    rating_str = f"{raw_rating} / {scale}" if raw_rating not in (None, "") else "N/A"
    votes_str = str(item.get("votes") or "0")
    lang = item.get("language") or "English"
    if isinstance(lang, list):
        lang = ", ".join(str(x) for x in lang if x)
    country = item.get("country") or "N/A"
    if isinstance(country, list):
        country = ", ".join(str(x) for x in country if x)
    genres_list = item.get("genres") or ["Books & Literature"]
    if isinstance(genres_list, str):
        genres_list = [genres_list]
    pages_str = str(item.get("pages") or "N/A")
    runtime_str = str(item.get("runtime") or (f"{pages_str} pages" if pages_str != "N/A" else "N/A"))
    plot_str = item.get("plot") or ""
    url_str = item.get("url") or ""
    card_str = item.format_card()

    return {
        "title": title,
        "book_title": title,
        "author": creator_str,
        "book_author": creator_str,
        "narrator": narrator_str,
        "series": series_label,
        "series_id": series_id,
        "year": year,
        "book_published": year,
        "rating": rating_str,
        "book_rating": str(raw_rating or "N/A"),
        "ratings_count": votes_str,
        "book_ratings_count": votes_str,
        "language": str(lang),
        "country": str(country),
        "genres": genres_list,
        "book_genres": ", ".join(genres_list),
        "pages": pages_str,
        "book_pages": pages_str,
        "length_str": runtime_str,
        "publisher": str(item.get("publisher") or item.accessSystem.title()),
        "storyline": plot_str,
        "url": url_str,
        "book_url": url_str,
        "provider": item.accessSystem,
        "category": default_category,
        "card_text": card_str,
    }


def _default_book_meta(clean_title: str, category: str = "book") -> dict:
    fallback_item = MediaItem(
        mediaID="",
        data={
            "title": clean_title or "Unknown Title",
            "kind": category,
            "language": "English",
            "genres": ["Books" if category == "book" else "Audiobook"],
        },
        access_system="goodreads" if category == "book" else "audible",
    )
    return _item_to_meta_dict(fallback_item, default_category=category)


def _fetch_book_mediagoer_sync(clean_query: str, is_audiobook: bool = False) -> dict:
    cat = "audiobook" if is_audiobook else "book"
    providers = ["audible", "storytel", "goodreads"] if is_audiobook else ["goodreads", "audible", "storytel"]
    words = clean_query.split()
    queries = [clean_query] + ([" ".join(words[:5])] if len(words) > 5 else [])

    for q in queries:
        for prov in providers:
            try:
                results = _MG.search(q, provider=prov, results=3)
                if results:
                    top = results[0]
                    # Enrich with full item page if plot or language is missing
                    if top.mediaID and (not top.get("plot") or not top.get("genres")):
                        try:
                            full_item = _MG.get(top.mediaID, provider=prov)
                            if full_item and full_item.get("title"):
                                top = full_item
                        except Exception:
                            pass
                    return _item_to_meta_dict(top, default_category=cat)
            except Exception as e:
                logger.debug(f"Book Mediagoer lookup ({prov}) warning: {e}")
    return _default_book_meta(clean_query, category=cat)


async def fetch_goodreads_metadata(file_name: str, ext: str = "") -> dict:
    """
    Fetches Book or Audiobook metadata from Goodreads, Audible, and Storytel via Mediagoer.
    """
    if not ext and file_name:
        _, ext = os.path.splitext(file_name.lower())
    is_audio = ext.lower() in AUDIOBOOK_EXTENSIONS
    clean_query = clean_filename_for_search(file_name)
    if not clean_query:
        return _default_book_meta(file_name, category="audiobook" if is_audio else "book")

    ckey = f"{'audio' if is_audio else 'book'}:{clean_query.lower()}"
    if ckey in _BOOK_CACHE:
        return _BOOK_CACHE[ckey]

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_fetch_book_mediagoer_sync, clean_query, is_audio),
            timeout=14.0,
        )
        _BOOK_CACHE[ckey] = data
        return data
    except Exception as e:
        logger.warning(f"Mediagoer book lookup error: {e}")
        return _default_book_meta(clean_query, category="audiobook" if is_audio else "book")


def format_index_channel_caption(file_name: str, file_size_str: str, extension: str, file_type: str, meta: dict) -> str:
    """
    Formats the storage channel caption using the Mediagoer Unicode card layout
    (`🏷 𝖳𝗂𝗍𝗅𝖾`, `📚 𝖲𝖾𝗋𝗂𝖾𝗌`, `🔮 𝖸𝖾𝖺𝗋`, `⭐️ 𝖱𝖺𝗍𝗂𝗇𝗀𝗌`, `🔊 𝖫𝖺𝗇𝗀𝗎𝖺𝗀𝖾`, `🌏 𝖢𝗈𝗎𝗇𝗍𝗋𝗒`,
    `🎭 𝖦𝖾𝗇𝖾𝗋𝗌`, `📜 𝖲𝗍𝗈𝗋𝗒 𝖫𝗂𝗇𝖾`) plus the file info footer.
    """
    card_text = meta.get("card_text") or ""
    if not card_text:
        item = MediaItem(
            mediaID="",
            data={
                "title": meta.get("title") or meta.get("book_title") or file_name,
                "series": meta.get("series") or "",
                "year": meta.get("year") or meta.get("book_published") or "",
                "rating": meta.get("book_rating") if meta.get("book_rating") != "N/A" else None,
                "language": meta.get("language") or "English",
                "country": meta.get("country") or "",
                "genres": meta.get("genres") or ["Books"],
                "plot": meta.get("storyline") or "",
            },
            access_system=meta.get("provider") or "goodreads",
        )
        card_text = item.format_card()

    # Clip card text so footer fits within Telegram's 1024-char caption limit
    if len(card_text) > 760:
        card_text = card_text[:757].rsplit(" ", 1)[0] + "..."

    esc_card = html.escape(card_text)
    url = meta.get("url") or meta.get("book_url") or ""
    title = meta.get("title") or meta.get("book_title") or ""
    if url and title:
        esc_title = html.escape(title)
        esc_card = esc_card.replace(
            f"🏷 𝖳𝗂𝗍𝗅𝖾 : {esc_title}",
            f'🏷 𝖳𝗂𝗍𝗅𝖾 : <a href="{html.escape(url)}">{esc_title}</a>',
            1,
        )

    cat_str = (meta.get("category") or file_type or "BOOK").upper()
    footer = (
        f"\n\n📁 <b>File Name:</b> <code>{html.escape(file_name or 'Unknown')}</code>\n"
        f"📦 <b>Size:</b> <code>{html.escape(file_size_str)}</code> | "
        f"<b>Type:</b> <code>{html.escape(cat_str)} (.{html.escape(extension.lstrip('.'))})</code>"
    )
    return (esc_card + footer)[:1020]


def _calc_eta_and_pct() -> tuple:
    fetched = QUEUE_STATE["fetched"]
    rem = QUEUE_STATE["remaining"]
    total = max(1, fetched + rem)
    pct = int((fetched / total) * 100) if (fetched + rem) > 0 else 100
    elapsed = max(1.0, time.time() - (QUEUE_STATE["start_time"] or time.time()))
    rate = fetched / elapsed if fetched > 0 else 0.5
    eta_sec = int(rem / rate) if rate > 0 else 0
    days, rem_s = divmod(eta_sec, 86400)
    hrs, rem_s = divmod(rem_s, 3600)
    mins, _ = divmod(rem_s, 60)
    eta_str = f"{days}d, {hrs}h, {mins}m" if days > 0 else f"{hrs}h, {mins}m"
    return pct, eta_str


def render_progress_card_text() -> str:
    pct, _ = _calc_eta_and_pct()
    st = QUEUE_STATE
    return (
        "<pre>"
        "╭──────❪ FORWARD STATUS ❫──〇⚙️\n"
        "│╭─────────────────────────➤\n"
        f"│├─»◇ FECHED MESSAGES: {st['fetched']}\n"
        "││\n"
        f"│├─»◇ REMAINING MESSAGES: {st['remaining']}\n"
        "││\n"
        f"│├─»◇ SUCCEFULLY FORWARDED: {st['forwarded']}\n"
        "││\n"
        f"│├─»◇ DUPLICATE MESSAGES: {st['duplicates']}\n"
        "││\n"
        f"│├─»◇ DELETED MESSAGES: {st['deleted']}\n"
        "││\n"
        f"│├─»◇ SKIPPED MESSAGES: {st['skipped']}\n"
        "││\n"
        f"│├─»◇ FILTERED MESSAGES: {st['filtered']}\n"
        "││\n"
        f"│├─»◇ CURRENT STATUS: {st['status']}\n"
        "││\n"
        f"│├─»◇ PERCENTAGE: {pct} %\n"
        "│╰─────────────────────────➤\n"
        "╰─────────❪ PROGRESSING ❫──〇⚙️"
        "</pre>"
    )


def render_progress_card_keyboard() -> InlineKeyboardMarkup:
    pct, _ = _calc_eta_and_pct()
    filled = max(1, min(12, int((pct / 100) * 12)))
    bar = ("▬" * filled) + ("□" * (12 - filled))
    pause_btn = (
        InlineKeyboardButton("• RESUME", callback_data="idx_ctrl_resume")
        if QUEUE_STATE["paused"]
        else InlineKeyboardButton("• PAUSE", callback_data="idx_ctrl_pause")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(bar, callback_data="idx_ctrl_popup")],
        [pause_btn, InlineKeyboardButton("⏳ WAIT / HOLD", callback_data="idx_ctrl_wait")],
        [InlineKeyboardButton("• CANCEL", callback_data="idx_ctrl_cancel")],
    ])


async def _index_single_book_obj(bot, file_id: str, file_unique_id: str, file_name: str, file_size: int, mime_type: str, user_id: int, user_title: str, orig_caption: str = "") -> str:
    """Indexes a single Book or Audiobook file."""
    storage_id = get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
    if not storage_id:
        return "filtered"

    _, ext = os.path.splitext((file_name or "").lower())
    if ext not in SUPPORTED_BOOK_EXTENSIONS:
        return "filtered"

    if get_file_by_unique_id_db(file_unique_id):
        return "duplicate"

    book_meta = await fetch_goodreads_metadata(file_name, ext=ext)
    size_mb = (file_size or 0) / (1024 * 1024)
    size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{(file_size or 0) / 1024:.1f} KB"

    caption_html = format_index_channel_caption(file_name, size_str, ext.lstrip("."), mime_type, book_meta)
    cat = "audiobook" if ext in AUDIOBOOK_EXTENSIONS else "book"
    target_msg = await bot.send_document(chat_id=int(storage_id), document=file_id, caption=caption_html, parse_mode="HTML")

    save_indexed_file_db(
        file_unique_id=file_unique_id,
        file_id=file_id,
        storage_message_id=target_msg.message_id,
        file_name=file_name,
        file_size=file_size or 0,
        duration=0,
        user_id=user_id,
        user_title=user_title,
        caption=orig_caption or caption_html,
        extension=ext,
        file_type=mime_type,
        category=cat,
        title=book_meta.get("title", ""),
        author=book_meta.get("author", ""),
        narrator=book_meta.get("narrator", ""),
        series=book_meta.get("series", ""),
        series_id=book_meta.get("series_id", ""),
        publisher=book_meta.get("publisher", ""),
        release_date=book_meta.get("year", ""),
        length_str=book_meta.get("length_str", ""),
        description=book_meta.get("storyline", ""),
        keywords=clean_filename_for_search(file_name),
        rating=book_meta.get("rating", ""),
        language=book_meta.get("language", ""),
        country=book_meta.get("country", ""),
        genres=book_meta.get("book_genres", ""),
        provider=book_meta.get("provider", ""),
        media_url=book_meta.get("url", ""),
    )

    log_txt = (
        f"📚 <b>Book/Audiobook Indexed Successfully</b>\n\n"
        f"🏷 <b>Title:</b> {html.escape(book_meta.get('title', file_name))}\n"
        f"🌐 <b>Source:</b> <code>{html.escape(book_meta.get('provider', 'goodreads').upper())}</code>\n"
        f"📂 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
        f"🆔 <b>Unique ID:</b> <code>{file_unique_id}</code>\n"
        f"👤 <b>Indexed By:</b> {html.escape(user_title)} (<code>{user_id}</code>)"
    )
    await send_log_with_fallback(bot, log_txt, "general_log_group_id", "index_log_topic_id")
    return "forwarded"


async def _index_single_file_obj(bot, file_id: str, file_unique_id: str, file_name: str, file_size: int, mime_type: str, user_id: int, user_title: str, orig_caption: str = "") -> str:
    """
    Dispatches queued files to the appropriate indexer:
    - Anime / Manga -> `modules.indexing.anime_index._index_single_anime_obj`
    - Movie / TV    -> `modules.indexing.movie_index._index_single_movie_obj`
    - Book / Audio  -> `_index_single_book_obj`
    """
    from modules.indexing.anime_index import is_anime_or_manga_file, _index_single_anime_obj
    from modules.indexing.movie_index import is_movie_file, _index_single_movie_obj

    if is_anime_or_manga_file(file_name, mime_type, orig_caption):
        return await _index_single_anime_obj(bot, file_id, file_unique_id, file_name, file_size, mime_type, user_id, user_title, orig_caption)
    if is_movie_file(file_name, mime_type, orig_caption):
        return await _index_single_movie_obj(bot, file_id, file_unique_id, file_name, file_size, mime_type, user_id, user_title, orig_caption)
    return await _index_single_book_obj(bot, file_id, file_unique_id, file_name, file_size, mime_type, user_id, user_title, orig_caption)


async def _refresh_progress_card(bot):
    cid, mid = QUEUE_STATE["card_chat_id"], QUEUE_STATE["card_msg_id"]
    if not cid or not mid:
        return
    try:
        await bot.edit_message_text(
            chat_id=int(cid),
            message_id=int(mid),
            text=render_progress_card_text(),
            parse_mode="HTML",
            reply_markup=render_progress_card_keyboard(),
        )
    except Exception:
        pass


async def process_global_indexing_queue(bot):
    """Processes global queue in batches of max 10 files with 10s cooldown sleep after each batch."""
    if QUEUE_STATE["running"]:
        return
    QUEUE_STATE["running"] = True
    QUEUE_STATE["cancelled"] = False
    QUEUE_STATE["start_time"] = time.time()

    try:
        while not QUEUE_STATE["cancelled"]:
            while QUEUE_STATE["paused"] and not QUEUE_STATE["cancelled"]:
                QUEUE_STATE["status"] = "paused"
                await _refresh_progress_card(bot)
                await asyncio.sleep(2)

            if QUEUE_STATE["cancelled"]:
                break

            batch_limit = get_config_int("max_index_batch", 10)
            sleep_secs = get_config_int("index_sleep_seconds", 10)

            conn = get_file_conn()
            rows = conn.execute(
                "SELECT * FROM indexing_queue WHERE status = 'queued' ORDER BY priority DESC, id ASC LIMIT ?",
                (batch_limit,),
            ).fetchall()
            rem_row = conn.execute("SELECT COUNT(*) as c FROM indexing_queue WHERE status = 'queued'").fetchone()
            QUEUE_STATE["remaining"] = rem_row["c"] if rem_row else 0
            conn.close()

            if not rows:
                QUEUE_STATE["status"] = "completed"
                await _refresh_progress_card(bot)
                break

            QUEUE_STATE["status"] = "forwarding"
            for r in rows:
                if QUEUE_STATE["cancelled"] or QUEUE_STATE["paused"]:
                    break
                qid = r["id"]
                conn = get_file_conn()
                conn.execute("UPDATE indexing_queue SET status = 'processing' WHERE id = ?", (qid,))
                conn.commit()
                conn.close()

                QUEUE_STATE["fetched"] += 1
                QUEUE_STATE["remaining"] = max(0, QUEUE_STATE["remaining"] - 1)
                try:
                    res = await _index_single_file_obj(
                        bot, r["file_id"], r["file_unique_id"], r["file_name"],
                        r["file_size"], r["mime_type"], r["user_id"], r["user_title"], r["caption"]
                    )
                    if res == "forwarded":
                        QUEUE_STATE["forwarded"] += 1
                    elif res == "duplicate":
                        QUEUE_STATE["duplicates"] += 1
                    else:
                        QUEUE_STATE["filtered"] += 1
                    st_val = "completed"
                except Exception:
                    QUEUE_STATE["filtered"] += 1
                    st_val = "failed"

                conn = get_file_conn()
                conn.execute("UPDATE indexing_queue SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?", (st_val, qid))
                conn.commit()
                conn.close()

            await _refresh_progress_card(bot)

            conn = get_file_conn()
            still_left = conn.execute("SELECT COUNT(*) as c FROM indexing_queue WHERE status = 'queued'").fetchone()["c"]
            conn.close()
            if still_left > 0 and not QUEUE_STATE["cancelled"] and not QUEUE_STATE["paused"]:
                QUEUE_STATE["status"] = f"sleeping ({sleep_secs}s)"
                await _refresh_progress_card(bot)
                await asyncio.sleep(sleep_secs)
    finally:
        QUEUE_STATE["running"] = False


def enqueue_file_for_indexing(file_id, file_unique_id, file_name, file_size, mime_type, user_id, user_title, caption="", priority=10, source="upload"):
    conn = get_file_conn()
    conn.execute("""
        INSERT INTO indexing_queue (file_id, file_unique_id, file_name, file_size, mime_type, caption, user_id, user_title, source, priority, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')
    """, (file_id, file_unique_id, file_name, file_size, mime_type, caption, user_id, user_title, source, priority))
    conn.commit()
    conn.close()


async def handle_book_indexing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for uploaded files: routes Anime/Manga uploads to `handle_anime_indexing`,
    Movie/TV uploads to `handle_movie_indexing`, and handles Book/Audiobook files directly.
    """
    msg = update.message or update.channel_post or update.effective_message
    if not msg:
        return

    if context.user_data.get("index_wizard") and msg.forward_from_chat:
        if await handle_index_wizard_message(update, context):
            return

    doc = msg.document or msg.audio or msg.video
    if not doc:
        return

    is_native_video = bool(msg.video and not msg.document)
    file_unique_id = doc.file_unique_id
    default_name = f"video_{file_unique_id[:8]}.mp4" if is_native_video else "audiobook.m4b"
    file_name = getattr(doc, "file_name", None) or default_name
    mime_type = getattr(doc, "mime_type", None) or ("video/telegram_video" if is_native_video else "document")
    caption = msg.caption or ""

    from modules.indexing.anime_index import is_anime_or_manga_file, handle_anime_indexing
    from modules.indexing.movie_index import is_movie_file, handle_movie_indexing

    if is_anime_or_manga_file(file_name, mime_type, caption):
        await handle_anime_indexing(update, context)
        return
    if is_movie_file(file_name, mime_type, caption):
        await handle_movie_indexing(update, context)
        return

    file_id = doc.file_id
    file_size = getattr(doc, "file_size", 0) or 0
    _, ext = os.path.splitext(file_name.lower())

    if ext not in SUPPORTED_BOOK_EXTENSIONS:
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("❌ Unsupported file format.")
        return

    if get_file_by_unique_id_db(file_unique_id):
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("📚 This book/audiobook is already indexed in the database.")
        return

    user = msg.from_user
    uid = user.id if user else 0
    utitle = (user.full_name or user.username) if user else (msg.chat.title or "Channel")
    role = get_user_role_db(uid) if uid else "Admin"

    if role == "Banned":
        return

    if role in ("Volunteer", "Admin", "Owner"):
        enqueue_file_for_indexing(file_id, file_unique_id, file_name, file_size, mime_type, uid, utitle, caption, priority=10, source="direct_book")
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("📥 <b>Book/Audiobook added to Priority Indexing Queue!</b> (Batch cap: 10 files / 10s throttle)", parse_mode="HTML")
        asyncio.create_task(process_global_indexing_queue(context.bot))
    else:
        conn = get_file_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO indexing_queue (file_id, file_unique_id, file_name, file_size, mime_type, caption, user_id, user_title, source, priority, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', 10, 'pending_approval')
        """, (file_id, file_unique_id, file_name, file_size, mime_type, caption, uid, utitle))
        qid = cur.lastrowid
        conn.commit()
        conn.close()

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve & Index", callback_data=f"idx_app_yes_{qid}"),
            InlineKeyboardButton("❌ Reject Upload", callback_data=f"idx_app_no_{qid}"),
        ]])
        app_txt = (
            f"📤 <b>New Book/Audiobook Upload Pending Approval</b>\n\n"
            f"👤 <b>Uploader:</b> {html.escape(utitle)} (<code>{uid}</code> | <code>{role}</code>)\n"
            f"📁 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
            f"📦 <b>Size:</b> <code>{file_size / (1024*1024):.2f} MB</code>"
        )
        await send_log_with_fallback(context.bot, app_txt, "admin_log_group_id", "index_log_topic_id", reply_markup=kb)
        if update.message:
            await update.message.reply_text("⏳ <b>Book Upload Received!</b> Sent to Admins for approval before indexing.", parse_mode="HTML")


def _parse_tme_link(link_str: str):
    """Parses t.me/c/12345/678 or t.me/channel/678-900."""
    m_priv = re.search(r"t\.me/c/(\d+)(?:/(\d+)(?:-(\d+))?)?", link_str)
    if m_priv:
        cid = int(f"-100{m_priv.group(1)}")
        m1 = int(m_priv.group(2)) if m_priv.group(2) else None
        m2 = int(m_priv.group(3)) if m_priv.group(3) else None
        return cid, m1, m2
    m_pub = re.search(r"t\.me/([A-Za-z0-9_]+)(?:/(\d+)(?:-(\d+))?)?", link_str)
    if m_pub:
        uname = f"@{m_pub.group(1)}"
        m1 = int(m_pub.group(2)) if m_pub.group(2) else None
        m2 = int(m_pub.group(3)) if m_pub.group(3) else None
        return uname, m1, m2
    return None, None, None


async def index_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    role = get_user_role_db(user.id)
    if role not in ("Volunteer", "Admin", "Owner"):
        await update.effective_message.reply_text("⛔ Access denied. Only Volunteers, Admins, and Owners can use /index.")
        return

    raw_args = " ".join(context.args).strip() if context.args else ""
    if not raw_args:
        context.user_data["index_wizard"] = {"step": "await_source"}
        await update.effective_message.reply_text(
            "<b>❪ Set Source Chat ❫</b>\n\nForward the last message or last message link of source chat.",
            parse_mode="HTML",
        )
        return

    links = re.findall(r"(?:https?://)?t\.me/[^\s]+", raw_args)
    chat_ref, start_id, end_id = (None, 1, 500)
    skip_range = None

    if len(links) >= 2:
        chat_ref, m1, _ = _parse_tme_link(links[0])
        _, m2, _ = _parse_tme_link(links[1])
        start_id, end_id = (m1 or 1), (m2 or (m1 or 100))
    elif len(links) == 1:
        chat_ref, m1, m2 = _parse_tme_link(links[0])
        if m1 and m2:
            start_id, end_id = m1, m2
        elif m1:
            start_id, end_id = 1, m1
    else:
        chat_ref = context.args[0]

    m_from = re.search(r"--from\s+(\d+)", raw_args)
    m_to = re.search(r"--to\s+(\d+)", raw_args)
    if m_from:
        start_id = int(m_from.group(1))
    if m_to:
        end_id = int(m_to.group(1))

    m_skip_rng = re.search(r"skip[=\s]+(\d+)-(\d+)", raw_args, re.IGNORECASE)
    m_skip_num = re.search(r"skip[=\s]+(\d+)", raw_args, re.IGNORECASE)
    if m_skip_rng:
        skip_range = (int(m_skip_rng.group(1)), int(m_skip_rng.group(2)))
    elif m_skip_num:
        start_id = int(m_skip_num.group(1)) + 1

    m_lim = re.search(r"limit[=\s]+(\d+)", raw_args, re.IGNORECASE)
    if m_lim:
        end_id = start_id + int(m_lim.group(1)) - 1

    context.user_data["index_wizard"] = {
        "step": "confirm",
        "source_chat": chat_ref,
        "start_id": start_id,
        "end_id": end_id,
        "skip_count": start_id - 1,
        "skip_range": skip_range,
    }
    await _send_double_check_card(update.effective_message, user.first_name, chat_ref, start_id - 1)


async def _send_double_check_card(msg, user_name, source_chat, skip_num):
    target_id = get_config("storage_channel_id", "-1003511375054")
    txt = (
        "<b>ᴅᴏᴜʙʟᴇ ᴄʜᴇᴄᴋɪɴɢ 📋</b>\n\n"
        "ʙᴇꜰᴏʀᴇ ꜰᴏʀᴡᴀʀᴅɪɴɢ ᴛʜᴇ ᴍᴇssᴀɢᴇs ᴄʟɪᴄᴋ ᴛʜᴇ ʏᴇs ʙᴜᴛᴛᴏɴ ᴏɴʟʏ ᴀꜰᴛᴇʀ ᴄʜᴇᴄᴋɪɴɢ ᴛʜᴇ ꜰᴏʟʟᴏᴡɪɴɢ\n\n"
        f"★ <b>ʏᴏᴜʀ userbot/bot:</b> {html.escape(user_name)}\n"
        f"★ <b>sᴏᴜʀᴄᴇ ᴄʜᴀᴛ:</b> <code>{html.escape(str(source_chat))}</code>\n"
        f"★ <b>ᴛᴀʀɢᴇᴛ ᴄʜᴀᴛ:</b> <code>{html.escape(str(target_id))}</code>\n"
        f"★ <b>sᴋɪᴘ ᴍᴇssᴀɢᴇs:</b> <code>{skip_num}</code>\n\n"
        "° Bot ᴍᴜsᴛ ʙᴇ ᴀᴅᴍɪɴ ɪɴ ᴛᴀʀɢᴇᴛ ᴄʜᴀᴛ\n"
        "° ɪꜰ ᴛʜᴇ sᴏᴜʀᴄᴇ ᴄʜᴀᴛ ɪs ᴘʀɪᴠᴀᴛᴇ ʏᴏᴜʀ ʙᴏᴛ ᴍᴜsᴛ ʙᴇ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴇʀᴇ ᴀʟsᴏ\n\n"
        "ɪꜰ ᴛʜᴇ ᴀʙᴏᴠᴇ ɪs ᴄʜᴇᴄᴋᴇᴅ ᴛʜᴇɴ ᴛʜᴇ ʏᴇs ʙᴜᴛᴛᴏɴ ᴄᴀɴ ʙᴇ ᴄʟɪᴄᴋᴇᴅ"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ YES", callback_data="idx_wiz_start_yes"),
        InlineKeyboardButton("❌ CANCEL", callback_data="idx_wiz_cancel"),
    ]])
    await msg.reply_text(txt, parse_mode="HTML", reply_markup=kb)


async def handle_index_wizard_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles conversational steps for /index wizard. Returns True if consumed."""
    wiz = context.user_data.get("index_wizard")
    if not wiz or not update.message:
        return False
    msg = update.message
    step = wiz.get("step")

    if step == "await_source":
        if msg.forward_from_chat:
            wiz["source_chat"] = msg.forward_from_chat.id
            wiz["end_id"] = msg.forward_from_message_id or 500
        elif msg.text and "t.me/" in msg.text:
            cid, m1, m2 = _parse_tme_link(msg.text.strip())
            if not cid:
                await msg.reply_text("⚠️ Invalid message link. Please forward the last message or paste a valid `https://t.me/...` link.")
                return True
            wiz["source_chat"] = cid
            wiz["end_id"] = m2 or m1 or 500
        else:
            return False

        wiz["step"] = "ask_skip"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes", callback_data="idx_wiz_skip_yes"),
            InlineKeyboardButton("❌ No", callback_data="idx_wiz_skip_no"),
        ]])
        await msg.reply_text("<b>Did You Want Skip Any Message's</b>", parse_mode="HTML", reply_markup=kb)
        return True

    if step == "await_skip_num" and msg.text and msg.text.strip().isdigit():
        skip_n = int(msg.text.strip())
        wiz["skip_count"] = skip_n
        wiz["start_id"] = skip_n + 1
        wiz["step"] = "confirm"
        await _send_double_check_card(msg, update.effective_user.first_name, wiz.get("source_chat"), skip_n)
        return True

    return False


async def indexing_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data
    uid = q.from_user.id
    role = get_user_role_db(uid)

    if d == "idx_ctrl_popup":
        pct, eta_str = _calc_eta_and_pct()
        st = QUEUE_STATE
        alert_txt = (
            f"FORWARD BOT\n"
            f"📈 PERCENTAGE: {pct} %\n"
            f"♻️ FECHED: {st['fetched']}\n"
            f"♻️ FORWARDED: {st['forwarded']}\n"
            f"♻️ REMAINING: {st['remaining']}\n"
            f"♻️ STATUS: {st['status']}\n"
            f"⏳ ETA: {eta_str}"
        )
        await q.answer(alert_txt, show_alert=True)
        return

    if role not in ("Volunteer", "Admin", "Owner"):
        await q.answer("⛔ Access denied.", show_alert=True)
        return

    if d == "idx_ctrl_pause":
        QUEUE_STATE["paused"] = True
        QUEUE_STATE["status"] = "paused"
        await q.answer("⏸ Queue paused. Active file will finish safely.")
        await _refresh_progress_card(context.bot)
    elif d == "idx_ctrl_resume":
        QUEUE_STATE["paused"] = False
        QUEUE_STATE["status"] = "forwarding"
        await q.answer("▶️ Queue resumed!")
        await _refresh_progress_card(context.bot)
        asyncio.create_task(process_global_indexing_queue(context.bot))
    elif d == "idx_ctrl_wait":
        await q.answer("⏳ Task held in queue until active batch completes.", show_alert=True)
    elif d == "idx_ctrl_cancel":
        QUEUE_STATE["cancelled"] = True
        QUEUE_STATE["paused"] = False
        QUEUE_STATE["status"] = "cancelled"
        conn = get_file_conn()
        conn.execute("UPDATE indexing_queue SET status = 'cancelled' WHERE status = 'queued'")
        conn.commit()
        conn.close()
        await q.answer("❌ Indexing cancelled and pending queue cleared.")
        await _refresh_progress_card(context.bot)
    elif d.startswith("idx_app_yes_") or d.startswith("idx_app_no_"):
        if role not in ("Admin", "Owner"):
            await q.answer("⛔ Only Admins and Owners can approve/reject uploads.", show_alert=True)
            return
        qid = int(d.split("_")[-1])
        conn = get_file_conn()
        row = conn.execute("SELECT * FROM indexing_queue WHERE id = ?", (qid,)).fetchone()
        if not row:
            conn.close()
            await q.answer("⚠️ Upload entry not found.", show_alert=True)
            return
        if d.startswith("idx_app_yes_"):
            conn.execute("UPDATE indexing_queue SET status = 'queued', priority = 10 WHERE id = ?", (qid,))
            conn.commit()
            conn.close()
            await q.message.edit_text(f"{q.message.text}\n\n✅ <b>Status: Approved & Queued for Indexing</b>", parse_mode="HTML")
            asyncio.create_task(process_global_indexing_queue(context.bot))
        else:
            conn.execute("UPDATE indexing_queue SET status = 'rejected' WHERE id = ?", (qid,))
            conn.commit()
            conn.close()
            await q.message.edit_text(f"{q.message.text}\n\n❌ <b>Status: Rejected</b>", parse_mode="HTML")
    elif d == "idx_wiz_skip_yes":
        wiz = context.user_data.get("index_wizard", {})
        wiz["step"] = "await_skip_num"
        await q.message.edit_text(
            "<b>❪ Set Skip Number ❫</b>\n\nYou can skip a certain number of messages and forward the rest.\n\n"
            "Default skip number is 0\nExample: If you enter 0, no messages will be skipped.\nIf you enter 5, the first 5 messages will be skipped",
            parse_mode="HTML",
        )
    elif d == "idx_wiz_skip_no":
        wiz = context.user_data.get("index_wizard", {})
        wiz["skip_count"] = 0
        wiz["start_id"] = 1
        wiz["step"] = "confirm"
        await q.message.delete()
        await _send_double_check_card(q.message, q.from_user.first_name, wiz.get("source_chat"), 0)
    elif d == "idx_wiz_cancel":
        context.user_data.pop("index_wizard", None)
        await q.message.edit_text("❌ Indexing setup cancelled.")
    elif d == "idx_wiz_start_yes":
        wiz = context.user_data.pop("index_wizard", None)
        if not wiz:
            await q.answer("⚠️ Session expired.", show_alert=True)
            return
        QUEUE_STATE.update({
            "fetched": 0,
            "forwarded": 0,
            "duplicates": 0,
            "deleted": 0,
            "skipped": wiz.get("skip_count", 0),
            "filtered": 0,
            "remaining": max(0, int(wiz.get("end_id", 100)) - int(wiz.get("start_id", 1)) + 1),
            "status": "forwarding",
            "paused": False,
            "cancelled": False,
            "start_time": time.time(),
            "card_chat_id": q.message.chat_id,
            "card_msg_id": q.message.message_id,
        })
        await _refresh_progress_card(context.bot)
        asyncio.create_task(_run_channel_range_scan(context.bot, wiz, q.from_user))


async def _run_channel_range_scan(bot, wiz: dict, user):
    """Scans source channel messages in batches of 10 with 10s sleep."""
    src = wiz.get("source_chat")
    start_id = int(wiz.get("start_id", 1))
    end_id = int(wiz.get("end_id", start_id))
    skip_range = wiz.get("skip_range")
    storage_id = get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
    batch_limit = get_config_int("max_index_batch", 10)
    sleep_secs = get_config_int("index_sleep_seconds", 10)

    processed_in_batch = 0
    for mid in range(start_id, end_id + 1):
        if QUEUE_STATE["cancelled"]:
            break
        while QUEUE_STATE["paused"] and not QUEUE_STATE["cancelled"]:
            QUEUE_STATE["status"] = "paused"
            await _refresh_progress_card(bot)
            await asyncio.sleep(2)

        if skip_range and skip_range[0] <= mid <= skip_range[1]:
            QUEUE_STATE["skipped"] += 1
            QUEUE_STATE["remaining"] = max(0, end_id - mid)
            continue

        QUEUE_STATE["fetched"] += 1
        QUEUE_STATE["remaining"] = max(0, end_id - mid)
        try:
            if storage_id:
                copied = await bot.copy_message(chat_id=int(storage_id), from_chat_id=src, message_id=mid)
                if copied:
                    QUEUE_STATE["forwarded"] += 1
        except Exception:
            QUEUE_STATE["deleted"] += 1

        processed_in_batch += 1
        if processed_in_batch >= batch_limit:
            processed_in_batch = 0
            QUEUE_STATE["status"] = f"sleeping ({sleep_secs}s)"
            await _refresh_progress_card(bot)
            await asyncio.sleep(sleep_secs)
            QUEUE_STATE["status"] = "forwarding"

    if not QUEUE_STATE["cancelled"]:
        QUEUE_STATE["status"] = "completed"
    await _refresh_progress_card(bot)
