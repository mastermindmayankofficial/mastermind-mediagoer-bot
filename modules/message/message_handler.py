from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.editscript.handlers import handle_customize_input
from modules.indexing.book_index import handle_index_wizard_message
from modules.request.handlers import handle_manual_request_message
from modules.search.handlers import perform_search


async def handle_normal_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if await handle_customize_input(update, context):
        return
    if await handle_index_wizard_message(update, context):
        return
    if await handle_manual_request_message(update, context):
        return

    if update.effective_chat and update.effective_chat.type == "private" and update.message.text:
        q = update.message.text.strip()
        if len(q) >= 2 and not q.startswith("/"):
            await perform_search(update, context, q, 1)
            return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search All", callback_data="search_menu"), InlineKeyboardButton("📖 Help Menu", callback_data="help_button")],
        [InlineKeyboardButton("🎬 Movie Search", callback_data="movie_search_menu"), InlineKeyboardButton("⛩️ Anime Search", callback_data="anime_search_menu")],
        [InlineKeyboardButton("🛡️ Support", callback_data="support_start_quiz")],
    ])
    await update.message.reply_text(
        "🤖 Use <code>/search &lt;title&gt;</code>, <code>/moviesearch &lt;title&gt;</code>, <code>/animesearch &lt;title&gt;</code>, <code>/info &lt;title&gt;</code>, <code>/series &lt;name&gt;</code>, or <code>/request &lt;title&gt;</code>.",
        parse_mode="HTML",
        reply_markup=kb,
    )
