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
    MANGA_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    _item_to_meta_dict,
    format_index_channel_caption,
    enqueue_file_for_indexing,
    process_global_indexing_queue,
)
from mediagoer import Mediagoer, MediaItem

logger = logging.getLogger(__name__)

SUPPORTED_ANIME_EXTENSIONS = VIDEO_EXTENSIONS | MANGA_EXTENSIONS | SUBTITLE_EXTENSIONS
_ANIME_CACHE = {}
_MG = Mediagoer(provider="anilist")

# Release group tags and patterns common in anime files
ANIME_FILENAME_RE = re.compile(
    r"(\[(?:SubsPlease|Erai-raws|HorribleSubs|Judas|Ember|ASW|nyaa|Cleo|Anime\s*Time|DKB|SSA|ToonsHub|Golumpa|GJM|DameDesuYo|Commie|FFF|Chihiro|Yameii)\]"
    r"|\b(?:Dual[\s\._-]*Audio|Multi[\s\._-]*Subs|Anime|Manga|Manhwa|Light[\s\._-]*Novel|BDRip\s+1080p\s+HEVC\s+10bit|OVA|ONA)\b"
    r"|-\s*\d{2,4}\s*(?:\[(?:1080p|720p|480p|2160p)|\())",
    re.IGNORECASE,
)


def is_anime_or_manga_file(file_name: str, mime_type: str = "", caption: str = "") -> bool:
    """
    Returns True if the file is an Anime video or Manga archive (.cbz/.cbr) or tagged as Anime/Manga.
    """
    _, ext = os.path.splitext((file_name or "").lower())
    if ext in MANGA_EXTENSIONS:
        return True
    combined = f"{file_name or ''} {caption or ''}"
    if re.search(r"#anime\b|#manga\b|#manhwa\b|#mal\b|#anilist\b|#kitsu\b", combined, re.IGNORECASE):
        return True
    if (ext in VIDEO_EXTENSIONS or (mime_type and "video" in mime_type.lower())) and ANIME_FILENAME_RE.search(combined):
        return True
    return False


def clean_anime_filename_for_search(file_name: str) -> str:
    """
    Cleans anime fansub/release group brackets, CRC32 hashes, episode numbers,
    and video tags to extract the clean Anime or Manga title.
    """
    if not file_name:
        return ""
    name = re.sub(r"\.[a-zA-Z0-9]{2,5}$", "", file_name)
    # Remove [SubsPlease], [1080p], [A1B2C3D4] CRC hashes, etc.
    name = re.sub(r"\[.*?\]|\(.*?\)|\{.*?\}", " ", name)
    # Remove S01E01 or - 01 or Ep 01 or Vol. 01 Ch. 05
    name = re.sub(r"\bS\d{1,2}(?:E\d{1,4})?(?:-\d{1,4})?\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(?:Episode|Ep|Vol|Volume|Ch|Chapter)\.?\s*\d{1,4}\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\s-\s\d{1,4}(?:v\d)?\b", " ", name)
    noise = (
        r"\b(2160p|1080p|720p|480p|4k|bdrip|bluray|web-dl|webrip|hevc|x264|x265|10bit|8bit|"
        r"aac|flac|opus|dual\s*audio|multi\s*subs|sub|dub|eng|jpn|jap|cbz|cbr|raw)\b"
    )
    name = re.sub(noise, " ", name, flags=re.IGNORECASE)
    name = re.sub(r"[_\.\-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _default_anime_meta(clean_title: str, is_manga: bool = False) -> dict:
    cat = "manga" if is_manga else "anime"
    fallback = MediaItem(
        mediaID="",
        data={
            "title": clean_title or "Unknown Anime",
            "kind": cat,
            "rating_scale": 10,
            "language": "Japanese",
            "country": "Japan",
            "genres": ["Manga" if is_manga else "Anime"],
        },
        access_system="anilist",
    )
    return _item_to_meta_dict(fallback, default_category=cat)


def _fetch_anime_mediagoer_sync(clean_query: str, is_manga: bool = False) -> dict:
    cat = "manga" if is_manga else "anime"
    providers = ["anilist", "mal", "kitsu"]
    words = clean_query.split()
    queries = [clean_query] + ([" ".join(words[:5])] if len(words) > 5 else [])

    for q in queries:
        for prov in providers:
            try:
                mtype = ("MANGA" if is_manga else "ANIME") if prov == "anilist" else ("manga" if is_manga else "anime")
                results = _MG.search(q, provider=prov, results=3, media_type=mtype)
                if results:
                    top = results[0]
                    if top.mediaID and (not top.get("plot") or not top.get("genres")):
                        try:
                            full_item = _MG.get(top.mediaID, provider=prov, media_type=mtype)
                            if full_item and full_item.get("title"):
                                top = full_item
                        except Exception:
                            pass
                    return _item_to_meta_dict(top, default_category=cat)
            except Exception as e:
                logger.debug(f"Anime Mediagoer lookup ({prov}) warning: {e}")
    return _default_anime_meta(clean_query, is_manga=is_manga)


async def fetch_anime_metadata(file_name: str, ext: str = "", caption: str = "") -> dict:
    """
    Asynchronously fetches Anime or Manga metadata from AniList, MyAnimeList, and Kitsu via Mediagoer.
    """
    if not ext and file_name:
        _, ext = os.path.splitext(file_name.lower())
    is_manga = ext.lower() in MANGA_EXTENSIONS or bool(re.search(r"#manga\b", caption or "", re.I))
    clean_query = clean_anime_filename_for_search(file_name)
    if not clean_query and caption:
        clean_query = clean_anime_filename_for_search(caption.splitlines()[0])
    if not clean_query:
        return _default_anime_meta(file_name, is_manga=is_manga)

    ckey = f"{'manga' if is_manga else 'anime'}:{clean_query.lower()}"
    if ckey in _ANIME_CACHE:
        return _ANIME_CACHE[ckey]

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_fetch_anime_mediagoer_sync, clean_query, is_manga),
            timeout=15.0,
        )
        _ANIME_CACHE[ckey] = data
        return data
    except Exception as e:
        logger.warning(f"Mediagoer anime metadata error: {e}")
        return _default_anime_meta(clean_query, is_manga=is_manga)


def format_anime_channel_caption(file_name: str, file_size_str: str, extension: str, file_type: str, anime_meta: dict) -> str:
    return format_index_channel_caption(file_name, file_size_str, extension, file_type, anime_meta)


async def _index_single_anime_obj(bot, file_id: str, file_unique_id: str, file_name: str, file_size: int, mime_type: str, user_id: int, user_title: str, orig_caption: str = "") -> str:
    """Indexes a single Anime or Manga file to the storage channel and database."""
    storage_id = get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
    if not storage_id:
        return "filtered"

    _, ext = os.path.splitext((file_name or "").lower())
    if not ext and mime_type and "video" in mime_type.lower():
        ext = ".mp4"
    if ext not in SUPPORTED_ANIME_EXTENSIONS:
        return "filtered"

    if get_file_by_unique_id_db(file_unique_id):
        return "duplicate"

    anime_meta = await fetch_anime_metadata(file_name, ext=ext, caption=orig_caption)
    size_mb = (file_size or 0) / (1024 * 1024)
    size_str = f"{size_mb:.2f} MB" if size_mb >= 1 else f"{(file_size or 0) / 1024:.1f} KB"

    caption_html = format_anime_channel_caption(file_name, size_str, ext.lstrip("."), mime_type, anime_meta)
    cat = anime_meta.get("category") or ("manga" if ext in MANGA_EXTENSIONS else "anime")

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
        category=cat,
        title=anime_meta.get("title", ""),
        author=anime_meta.get("author", ""),
        narrator=anime_meta.get("narrator", ""),
        series=anime_meta.get("series", ""),
        series_id=anime_meta.get("series_id", ""),
        publisher=anime_meta.get("publisher", ""),
        release_date=anime_meta.get("year", ""),
        length_str=anime_meta.get("length_str", ""),
        description=anime_meta.get("storyline", ""),
        keywords=clean_anime_filename_for_search(file_name),
        rating=anime_meta.get("rating", ""),
        language=anime_meta.get("language", ""),
        country=anime_meta.get("country", ""),
        genres=anime_meta.get("book_genres", ""),
        provider=anime_meta.get("provider", "anilist"),
        media_url=anime_meta.get("url", ""),
    )

    log_txt = (
        f"⛩️ <b>Anime / Manga Indexed Successfully ({cat.upper()})</b>\n\n"
        f"🏷 <b>Title:</b> {html.escape(anime_meta.get('title', file_name))}\n"
        f"🌐 <b>Source:</b> <code>{html.escape(anime_meta.get('provider', 'anilist').upper())}</code>\n"
        f"📂 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
        f"🆔 <b>Unique ID:</b> <code>{file_unique_id}</code>\n"
        f"👤 <b>Indexed By:</b> {html.escape(user_title)} (<code>{user_id}</code>)"
    )
    await send_log_with_fallback(bot, log_txt, "general_log_group_id", "index_log_topic_id")
    return "forwarded"


async def handle_anime_indexing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles incoming Anime or Manga file uploads.
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
    default_name = f"anime_{file_unique_id[:8]}.mp4"
    file_name = getattr(doc, "file_name", None) or default_name
    file_size = getattr(doc, "file_size", 0) or 0
    mime_type = getattr(doc, "mime_type", None) or ("video/telegram_video" if is_native_video else "video/mp4")
    if is_native_video and not mime_type.startswith("video/telegram_video"):
        mime_type = f"video/telegram_video;{mime_type}"

    _, ext = os.path.splitext(file_name.lower())
    if not ext:
        ext = ".mp4"
        file_name = f"{file_name}.mp4"

    if ext not in SUPPORTED_ANIME_EXTENSIONS:
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("❌ Unsupported anime/manga format. Supported: .mkv, .mp4, .avi, .webm, .cbz, .cbr.")
        return

    if get_file_by_unique_id_db(file_unique_id):
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("⛩️ This anime/manga file is already indexed in the database.")
        return

    user = msg.from_user
    uid = user.id if user else 0
    utitle = (user.full_name or user.username) if user else (msg.chat.title or "Channel")
    role = get_user_role_db(uid) if uid else "Admin"

    if role == "Banned":
        return

    caption = msg.caption or ""
    if "#anime" not in caption.lower() and "#manga" not in caption.lower() and ext not in MANGA_EXTENSIONS:
        caption = f"{caption} #anime".strip()

    if role in ("Volunteer", "Admin", "Owner"):
        enqueue_file_for_indexing(file_id, file_unique_id, file_name, file_size, mime_type, uid, utitle, caption, priority=10, source="direct_anime")
        if update.message and update.effective_chat.type == "private":
            await update.message.reply_text("⛩️ <b>Anime/Manga added to Priority Indexing Queue!</b> (Batch cap: 10 files / 10s throttle)", parse_mode="HTML")
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
            f"⛩️ <b>New Anime/Manga Upload Pending Approval</b>\n\n"
            f"👤 <b>Uploader:</b> {html.escape(utitle)} (<code>{uid}</code> | <code>{role}</code>)\n"
            f"📁 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
            f"📦 <b>Size:</b> <code>{file_size / (1024*1024):.2f} MB</code>"
        )
        await send_log_with_fallback(context.bot, app_txt, "admin_log_group_id", "index_log_topic_id", reply_markup=kb)
        if update.message:
            await update.message.reply_text("⏳ <b>Anime/Manga Upload Received!</b> Sent to Admins for approval before indexing.", parse_mode="HTML")


async def indexanime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /indexanime — Replies to an anime/manga file to index it immediately, or opens the channel indexing wizard.
    """
    msg = update.effective_message
    if msg and msg.reply_to_message and (msg.reply_to_message.video or msg.reply_to_message.document):
        update.message = msg.reply_to_message
        await handle_anime_indexing(update, context)
        return
    from modules.indexing.book_index import index_command
    await index_command(update, context)
