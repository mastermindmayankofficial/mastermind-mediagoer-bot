import os
import re
import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.file_db import get_file_by_unique_id_db, save_indexed_file_db, get_connection as get_file_conn
from modules.database.config_db import get_config
from modules.database.user_db import get_user_role_db
from modules.log.startup_log import send_log_with_fallback
from modules.indexing.book_index import (
    VIDEO_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    _item_to_meta_dict,
    format_index_channel_caption,
    enqueue_file_for_indexing,
    process_global_indexing_queue,
)
from mediagoer import Mediagoer, MediaItem

logger = logging.getLogger(__name__)

SUPPORTED_MOVIE_EXTENSIONS = VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS
_MOVIE_CACHE = {}
_MG = Mediagoer(provider="imdb")


def is_movie_file(file_name: str, mime_type: str = "", caption: str = "") -> bool:
    """
    Returns True if the file is a Movie or TV Series video/subtitle file (and not tagged as Anime/Manga).
    """
    from modules.indexing.anime_index import is_anime_or_manga_file

    if is_anime_or_manga_file(file_name, mime_type, caption):
        return False

    combined = f"{file_name or ''} {caption or ''}"
    if re.search(r"#movie\b|#film\b|#series\b|#tv\b|#imdb\b|#letterboxd\b", combined, re.IGNORECASE):
        return True

    _, ext = os.path.splitext((file_name or "").lower())
    if ext in SUPPORTED_MOVIE_EXTENSIONS:
        return True
    if mime_type and "video" in mime_type.lower():
        return True
    return False


def clean_movie_filename_for_search(file_name: str) -> str:
    """
    Strips video resolution, codecs, release group tags, and episode markers
    to extract a clean Movie or TV Series title for IMDb/Letterboxd search.
    """
    if not file_name:
        return ""
    name = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", file_name)
    name = re.sub(r"\[.*?\]|\(.*?\)|\{.*?\}", " ", name)
    name = re.sub(r"\bS\d{1,2}(?:E\d{1,3})?(?:-\d{1,3})?\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(?:Season|Episode|Ep)\.?\s*\d{1,3}\b", " ", name, flags=re.IGNORECASE)
    noise = (
        r"\b(2160p|1080p|720p|480p|4k|uhd|hdr|hdr10|dv|dolby\s*vision|"
        r"bluray|blu-ray|bdrip|brrip|web-dl|webdl|webrip|hdrip|dvdrip|camrip|hdtv|"
        r"x264|x265|h264|h265|hevc|av1|10bit|8bit|aac|ac3|eac3|ddp5\.1|dts|atmos|truehd|"
        r"dual\s*audio|multi\s*subs|multisub|esub|esubs|hindi|english|korean|"
        r"yts|yify|rarbg|psa|pahe|tigole|qxr|proper|repack|extended|remastered|unrated|directors\s*cut)\b"
    )
    name = re.sub(noise, " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(19\d{2}|20\d{2})\b.*$", " ", name)
    name = re.sub(r"[_\.\-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _default_movie_meta(clean_title: str) -> dict:
    fallback = MediaItem(
        mediaID="",
        data={
            "title": clean_title or "Unknown Movie",
            "kind": "movie",
            "rating_scale": 10,
            "genres": ["Movie"],
        },
        access_system="imdb",
    )
    return _item_to_meta_dict(fallback, default_category="movie")


def _fetch_movie_mediagoer_sync(clean_query: str) -> dict:
    providers = ["imdb", "letterboxd"]
    words = clean_query.split()
    queries = [clean_query] + ([" ".join(words[:5])] if len(words) > 5 else [])

    for q in queries:
        for prov in providers:
            try:
                results = _MG.search(q, provider=prov, results=3)
                if results:
                    top = results[0]
                    if top.mediaID and (not top.get("plot") or not top.get("genres") or not top.get("rating")):
                        try:
                            full_item = _MG.get(top.mediaID, provider=prov)
                            if full_item and full_item.get("title"):
                                top = full_item
                        except Exception:
                            pass
                    return _item_to_meta_dict(top, default_category="movie")
            except Exception as e:
                logger.debug(f"Movie Mediagoer lookup ({prov}) warning: {e}")
    return _default_movie_meta(clean_query)


async def fetch_movie_metadata(file_name: str, caption: str = "") -> dict:
    """
    Asynchronously fetches Movie / TV Series metadata from IMDb & Letterboxd via Mediagoer.
    """
    clean_query = clean_movie_filename_for_search(file_name)
    if not clean_query and caption:
        clean_query = clean_movie_filename_for_search(caption.splitlines()[0])
    if not clean_query:
        return _default_movie_meta(file_name)

    ckey = clean_query.lower()
    if ckey in _MOVIE_CACHE:
        return _MOVIE_CACHE[ckey]

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_fetch_movie_mediagoer_sync, clean_query),
            timeout=15.0,
        )
        _MOVIE_CACHE[ckey] = data
        return data
    except Exception as e:
        logger.warning(f"Mediagoer movie metadata error: {e}")
        return _default_movie_meta(clean_query)


def format_movie_channel_caption(file_name: str, file_size_str: str, extension: str, file_type: str, movie_meta: dict) -> str:
    return format_index_channel_caption(file_name, file_size_str, extension, file_type, movie_meta)


async def _index_single_movie_obj(bot, file_id: str, file_unique_id: str, file_name: str, file_size: int, mime_type: str, user_id: int, user_title: str, orig_caption: str = "") -> str:
    """Indexes a single Movie / TV Series file to the storage channel and database."""
    storage_id = get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
    if not storage_id:
        return "filtered"

    _, ext = os.path.splitext((file_name or "").lower())
    if not ext and mime_type and "video" in mime_type.lower():
        ext = ".mp4"
    if ext not in SUPPORTED_MOVIE_EXTENSIONS:
        return "filtered"

    if get_file_by_unique_id_db(file_unique_id):
        return "duplicate"

    movie_meta = await fetch_movie_metadata(file_name, caption=orig_caption)
    size_mb = (file_size or 0) / (1024 * 1024)
    size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{(file_size or 0) / 1024:.1f} KB"

    caption_html = format_movie_channel_caption(file_name, size_str, ext.lstrip("."), mime_type, movie_meta)

    try:
        if mime_type and mime_type.startswith("video/telegram_video"):
            target_msg = await bot.send_video(chat_id=int(storage_id), video=file_id, caption=caption_html, parse_mode="HTML")
        else:
            target_msg = await bot.send_document(chat_id=int(storage_id), document=file_id, caption=caption_html, parse_mode="HTML")
    except Exception:
        target_msg = await bot.send_video(chat_id=int(storage_id), video=file_id, caption=caption_html, parse_mode="HTML")

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
        category="movie",
        title=movie_meta.get("title", ""),
        author=movie_meta.get("author", ""),
        narrator=movie_meta.get("narrator", ""),
        series=movie_meta.get("series", ""),
        series_id=movie_meta.get("series_id", ""),
        publisher=movie_meta.get("publisher", ""),
        release_date=movie_meta.get("year", ""),
        length_str=movie_meta.get("length_str", ""),
        description=movie_meta.get("storyline", ""),
        keywords=clean_movie_filename_for_search(file_name),
        rating=movie_meta.get("rating", ""),
        language=movie_meta.get("language", ""),
        country=movie_meta.get("country", ""),
        genres=movie_meta.get("book_genres", ""),
        provider=movie_meta.get("provider", "imdb"),
        media_url=movie_meta.get("url", ""),
    )

    log_txt = (
        f"🎬 <b>Movie / Series Indexed Successfully</b>\n\n"
        f"🏷 <b>Title:</b> {html.escape(movie_meta.get('title', file_name))}\n"
        f"🌐 <b>Source:</b> <code>{html.escape(movie_meta.get('provider', 'imdb').upper())}</code>\n"
        f"📂 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
        f"🆔 <b>Unique ID:</b> <code>{file_unique_id}</code>\n"
        f"👤 <b>Indexed By:</b> {html.escape(user_title)} (<code>{user_id}</code>)"
    )
    await send_log_with_fallback(bot, log_txt, "general_log_group_id", "index_log_topic_id")
    return "forwarded"


async def handle_movie_indexing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming Movie / TV Series video or document files.
    """
    msg = update.message or update.channel_post or update.effective_message
    if not msg:
        return
    doc = msg.video or msg.document
    if not doc:
        return

    is_native_video = bool(msg.video and not msg.document)
    file_id = doc.file_id
    file_unique_id = doc.file_unique_id
    default_name = f"movie_{file_unique_id[:8]}.mp4"
    file_name = getattr(doc, "file_name", None) or default_name
    file_size = getattr(doc, "file_size", 0) or 0
    mime_type = getattr(doc, "mime_type", None) or ("video/telegram_video" if is_native_video else "video/mp4")
    if is_native_video and not mime_type.startswith("video/telegram_video"):
        mime_type = f"video/telegram_video;{mime_type}"

    _, ext = os.path.splitext(file_name.lower())
    if not ext:
        ext = ".mp4"
        file_name = f"{file_name}.mp4"

    if ext not in SUPPORTED_MOVIE_EXTENSIONS:
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("❌ Unsupported movie format. Supported: .mkv, .mp4, .avi, .mov, .webm, .m4v, .srt.")
        return

    if get_file_by_unique_id_db(file_unique_id):
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("🎬 This movie/series file is already indexed in the database.")
        return

    user = msg.from_user
    uid = user.id if user else 0
    utitle = (user.full_name or user.username) if user else (msg.chat.title or "Channel")
    role = get_user_role_db(uid) if uid else "Admin"

    if role == "Banned":
        return

    if role in ("Volunteer", "Admin", "Owner"):
        enqueue_file_for_indexing(file_id, file_unique_id, file_name, file_size, mime_type, uid, utitle, msg.caption or "", priority=10, source="direct_movie")
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("🎬 <b>Movie/Series added to Priority Indexing Queue!</b> (Batch cap: 10 files / 10s throttle)", parse_mode="HTML")
        asyncio.create_task(process_global_indexing_queue(context.bot))
    else:
        conn = get_file_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO indexing_queue (file_id, file_unique_id, file_name, file_size, mime_type, caption, user_id, user_title, source, priority, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', 10, 'pending_approval')
        """, (file_id, file_unique_id, file_name, file_size, mime_type, msg.caption or "", uid, utitle))
        qid = cur.lastrowid
        conn.commit()
        conn.close()

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve & Index", callback_data=f"idx_app_yes_{qid}"),
            InlineKeyboardButton("❌ Reject Upload", callback_data=f"idx_app_no_{qid}"),
        ]])
        app_txt = (
            f"🎬 <b>New Movie Upload Pending Approval</b>\n\n"
            f"👤 <b>Uploader:</b> {html.escape(utitle)} (<code>{uid}</code> | <code>{role}</code>)\n"
            f"📁 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
            f"📦 <b>Size:</b> <code>{file_size / (1024*1024):.2f} MB</code>"
        )
        await send_log_with_fallback(context.bot, app_txt, "admin_log_group_id", "index_log_topic_id", reply_markup=kb)
        if update.message:
            await update.message.reply_text("⏳ <b>Movie Upload Received!</b> Sent to Admins for approval before indexing.", parse_mode="HTML")


async def indexmovie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /indexmovie — Replies to a movie file to index it immediately, or opens the channel indexing wizard.
    """
    msg = update.effective_message
    if msg and msg.reply_to_message and (msg.reply_to_message.video or msg.reply_to_message.document):
        update.message = msg.reply_to_message
        await handle_movie_indexing(update, context)
        return
    from modules.indexing.book_index import index_command
    await index_command(update, context)
