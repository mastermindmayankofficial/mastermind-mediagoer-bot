from telegram import Update
from telegram.ext import ContextTypes

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    
    if not message or not chat:
        return

    reply_to = message.reply_to_message
    args = context.args

    if args:
        target_username = args[0].lstrip("@")
        await message.reply_text(
            f"ℹ️ <b>Username Lookup</b>\n• <b>Target Username:</b> @{target_username}",
            parse_mode="HTML"
        )
        return

    if reply_to and reply_to.from_user:
        replied_user = reply_to.from_user
        response_text = (
            f"👤 <b>Replied User Details</b>\n"
            f"• <b>Name:</b> {replied_user.full_name}\n"
            f"• <b>User ID:</b> <code>{replied_user.id}</code>\n"
            f"• <b>Chat ID:</b> <code>{chat.id}</code>"
        )
        await message.reply_text(response_text, parse_mode="HTML")
        return

    user_id_str = f"<code>{user.id}</code>" if user else "<i>Channel Post</i>"
    response_text = (
        f"📊 <b>Identification</b>\n\n"
        f"👤 <b>User ID:</b> {user_id_str}\n"
        f"💬 <b>Chat ID:</b> <code>{chat.id}</code>\n"
        f"🏷️ <b>Chat Type:</b> {chat.type.capitalize()}"
    )

    try:
        await message.reply_text(response_text, parse_mode="HTML")
    except Exception:
        await context.bot.send_message(chat_id=chat.id, text=response_text, parse_mode="HTML")
