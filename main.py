import os
import json
import asyncio
import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    filters,
)

from modules.database.config_db import init_config_db, reload_config_cache
from modules.database.user_db import init_user_db
from modules.database.file_db import init_file_db
from modules.log.logger import setup_in_memory_logger
from modules.log.startup_log import send_startup_notification
from modules.log.handlers import log_command, handle_my_chat_member
from modules.ban.handlers import ban_command, ban_pm_command, ban_support_command, unban_command, enforce_ban_middleware
from modules.fsub.handlers import enforce_fsub_middleware, handle_chat_join_request, fsub_verify_callback
from modules.start.start_handler import start_command, menu_callback_router
from modules.help.handlers import help_command, adminhelp_command
from modules.roles.handlers import addvol_command, addprom_command, addmod_command, addadmin_command
from modules.allowance.allowance import quota_command, gift_command, refer_command

# Search Modules (Books/All, Movies, Anime)
from modules.search.handlers import search_command, info_command, series_command, search_callback_handler
from modules.search.movie_search import moviesearch_command, movieinfo_command, movieseries_command, movie_search_callback_handler
from modules.search.anime_search import animesearch_command, animeinfo_command, animeseries_command, anime_search_callback_handler

# Request Modules (Books, Movies, Anime)
from modules.request.handlers import request_command, request_callback_handler
from modules.request.movie_request import requestmovie_command, movie_request_callback_handler
from modules.request.anime_request import requestanime_command, anime_request_callback_handler

# Indexing Modules (Books, Movies, Anime)
from modules.indexing.book_index import handle_book_indexing, index_command, indexing_callback_handler
from modules.indexing.movie_index import indexmovie_command
from modules.indexing.anime_index import indexanime_command

from modules.editscript.handlers import (
    customize_command, editscript_callback, reloadconfig_command,
    setconfig_command, getconfig_command, template_cli_command,
)
from modules.broadcast.handlers import broadcast_command, broadcast_confirm_command, broadcast_callback_handler
from modules.stats.handlers import stats_command
from modules.support.handlers import support_command, support_callback_handler
from modules.id.handlers import id_command
from modules.utility.ping import ping_command
from modules.message.message_handler import handle_normal_text


def _read_env_value(*names):
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def load_env():
    for env_path in ("env.txt", ".env"):
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        os.environ[k.strip()] = v.strip()

    # Primary bot token support.
    primary_token = _read_env_value("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
    if primary_token:
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", primary_token)
        os.environ.setdefault("BOT_TOKEN", primary_token)

    # Helper bot token support (default + category-specific variants).
    helper_aliases = [
        "HELPER_TELEGRAM_BOT_TOKEN",
        "HELPER_BOT_TOKEN",
        "HELPER_BOT",
        "TELEGRAM_HELPER_BOT_TOKEN",
    ]
    default_helper = _read_env_value(*helper_aliases)
    if default_helper:
        os.environ.setdefault("HELPER_BOT_TOKEN", default_helper)
        os.environ.setdefault("HELPER_TELEGRAM_BOT_TOKEN", default_helper)

    category_tokens = {
        "default": default_helper,
        "book": _read_env_value("BOOK_HELPER_BOT_TOKEN", "BOOK_TELEGRAM_BOT_TOKEN", "BOOK_HELPER_TOKEN"),
        "movie": _read_env_value("MOVIE_HELPER_BOT_TOKEN", "MOVIE_TELEGRAM_BOT_TOKEN", "MOVIE_HELPER_TOKEN"),
        "anime": _read_env_value("ANIME_HELPER_BOT_TOKEN", "ANIME_TELEGRAM_BOT_TOKEN", "ANIME_HELPER_TOKEN"),
    }
    category_tokens = {k: v for k, v in category_tokens.items() if v}
    if category_tokens:
        os.environ["HELPER_BOT_TOKENS"] = json.dumps(category_tokens)


def main():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        print("❌ Please set TELEGRAM_BOT_TOKEN in env.txt")
        exit(1)

    helper_tokens = json.loads(os.getenv("HELPER_BOT_TOKENS", "{}")) if os.getenv("HELPER_BOT_TOKENS") else {}
    if not helper_tokens:
        helper_tokens = {
            "default": os.getenv("HELPER_BOT_TOKEN") or os.getenv("HELPER_TELEGRAM_BOT_TOKEN"),
            "book": os.getenv("BOOK_HELPER_BOT_TOKEN") or os.getenv("BOOK_TELEGRAM_BOT_TOKEN"),
            "movie": os.getenv("MOVIE_HELPER_BOT_TOKEN") or os.getenv("MOVIE_TELEGRAM_BOT_TOKEN"),
            "anime": os.getenv("ANIME_HELPER_BOT_TOKEN") or os.getenv("ANIME_TELEGRAM_BOT_TOKEN"),
        }
    helper_tokens = {k: v for k, v in helper_tokens.items() if v}
    if helper_tokens:
        os.environ["HELPER_BOT_TOKENS"] = json.dumps(helper_tokens)

    logging.basicConfig(level=logging.INFO)
    setup_in_memory_logger()
    init_config_db()
    reload_config_cache()
    init_user_db()
    init_file_db()

    app = ApplicationBuilder().token(token).build()

    # Middlewares: Group -2 Ban check, Group -1 Force Subscribe check
    app.add_handler(MessageHandler(filters.ALL, enforce_ban_middleware), group=-2)
    app.add_handler(MessageHandler(filters.ALL, enforce_fsub_middleware), group=-1)
    app.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # User Commands — General & Books
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler(["info", "card", "mediainfo"], info_command))
    app.add_handler(CommandHandler(["series", "seriesinfo"], series_command))
    app.add_handler(CommandHandler(["request", "req", "requestbook"], request_command))

    # User Commands — Movies & TV Series
    app.add_handler(CommandHandler(["moviesearch", "msearch"], moviesearch_command))
    app.add_handler(CommandHandler(["movieinfo", "mcard"], movieinfo_command))
    app.add_handler(CommandHandler(["movieseries", "mseries"], movieseries_command))
    app.add_handler(CommandHandler(["requestmovie", "reqmovie"], requestmovie_command))

    # User Commands — Anime & Manga
    app.add_handler(CommandHandler(["animesearch", "asearch"], animesearch_command))
    app.add_handler(CommandHandler(["animeinfo", "acard"], animeinfo_command))
    app.add_handler(CommandHandler(["animeseries", "aseries"], animeseries_command))
    app.add_handler(CommandHandler(["requestanime", "reqanime"], requestanime_command))

    # Quota, Referral & Utility Commands
    app.add_handler(CommandHandler("quota", quota_command))
    app.add_handler(CommandHandler(["refer", "ref"], refer_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("ping", ping_command))

    # Admin & Role Commands
    app.add_handler(CommandHandler(["adminhelp", "ownerhelp"], adminhelp_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("log", log_command))
    app.add_handler(CommandHandler("gift", gift_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("ban_pm", ban_pm_command))
    app.add_handler(CommandHandler("ban_support", ban_support_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("addvol", addvol_command))
    app.add_handler(CommandHandler("addprom", addprom_command))
    app.add_handler(CommandHandler("addmod", addmod_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler(["index", "Index", "indexbook"], index_command))
    app.add_handler(CommandHandler(["indexmovie", "movieindex"], indexmovie_command))
    app.add_handler(CommandHandler(["indexanime", "animeindex"], indexanime_command))

    # Config, Customize & Broadcast Commands
    app.add_handler(CommandHandler(["customize", "editscript", "config", "showconfig"], customize_command))
    app.add_handler(CommandHandler("reloadconfig", reloadconfig_command))
    app.add_handler(CommandHandler("setconfig", setconfig_command))
    app.add_handler(CommandHandler("getconfig", getconfig_command))
    app.add_handler(CommandHandler(["edittext", "setmedia", "removemedia", "addbutton", "removebutton", "listtemplates", "showtemplate"], template_cli_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("broadcast_confirm", broadcast_confirm_command))

    # Callback Routers
    app.add_handler(CallbackQueryHandler(fsub_verify_callback, pattern=r"^fsub_"))
    app.add_handler(CallbackQueryHandler(menu_callback_router, pattern=r"^(help_button|help_menu|help_open_admin|help_sec_|adm_sec_|search_menu|stats_menu|start_menu|quota|quota_menu|bot_owner)"))
    app.add_handler(CallbackQueryHandler(search_callback_handler, pattern=r"^(file_dl_|search_page_|card_lookup_|series_lookup_|search_cancel|noop)"))
    app.add_handler(CallbackQueryHandler(movie_search_callback_handler, pattern=r"^(movie_search_menu|msearch_page_|mcard_lookup_|mseries_lookup_)"))
    app.add_handler(CallbackQueryHandler(anime_search_callback_handler, pattern=r"^(anime_search_menu|asearch_page_|acard_lookup_|aseries_lookup_)"))
    app.add_handler(CallbackQueryHandler(request_callback_handler, pattern=r"^req_"))
    app.add_handler(CallbackQueryHandler(movie_request_callback_handler, pattern=r"^mreq_"))
    app.add_handler(CallbackQueryHandler(anime_request_callback_handler, pattern=r"^areq_"))
    app.add_handler(CallbackQueryHandler(indexing_callback_handler, pattern=r"^idx_"))
    app.add_handler(CallbackQueryHandler(editscript_callback, pattern=r"^(cust_|es_)"))
    app.add_handler(CallbackQueryHandler(broadcast_callback_handler, pattern=r"^bcast_"))
    app.add_handler(CallbackQueryHandler(support_callback_handler, pattern=r"^support_|^quiz_ans_"))

    # File Upload / Auto-Indexing (Documents, Audio, and Video for Books, Audiobooks, Movies & Anime)
    app.add_handler(MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_book_indexing))
    app.add_handler(MessageHandler(filters.PHOTO | filters.FORWARDED | (filters.TEXT & ~filters.COMMAND), handle_normal_text))

    async def post_init(application):
        await send_startup_notification(application)

    app.post_init = post_init
    print("🤖 Mastermind Multi-Media & Library Bot is online and polling...")
    print(f"✅ Loaded helper bot tokens: {', '.join(helper_tokens.keys()) if helper_tokens else 'none configured'}")
    app.run_polling()


if __name__ == "__main__":
    main()
