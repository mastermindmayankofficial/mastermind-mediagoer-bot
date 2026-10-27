import os
import logging
from datetime import datetime
from modules.database.config_db import get_config, get_config_int, get_template, format_template_string
from modules.database.user_db import get_owner_ids

logger = logging.getLogger(__name__)


async def send_log_with_fallback(bot, text: str, target_chat_key: str = "admin_log_group_id", topic_key: str = None, reply_markup=None):
    """Routes logs to specific group/topic -> falls back to general log + Owner PM -> falls back to Owner PM."""
    primary_chat = get_config(target_chat_key, fallback_env=target_chat_key.upper()) or get_config("general_log_group_id", fallback_env="LOGGER_GROUP_ID")
    topic_id = get_config_int(topic_key, 0, fallback_env=topic_key.upper()) if topic_key else 0

    if primary_chat:
        try:
            kwargs = {"chat_id": int(primary_chat), "text": text, "parse_mode": "HTML"}
            if topic_id > 0:
                kwargs["message_thread_id"] = topic_id
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            return await bot.send_message(**kwargs)
        except Exception as e:
            fallback_err = f"⚠️ <b>Log Destination Issue:</b> Failed to send to <code>{target_chat_key}</code> (topic: <code>{topic_id}</code>): <code>{e}</code>"
            await _notify_owners(bot, fallback_err)

    general_chat = get_config("general_log_group_id", fallback_env="LOGGER_GROUP_ID") or get_config("storage_channel_id", fallback_env="STORAGE_GROUP_ID")
    gen_topic = get_config_int("general_topic_id", 0, fallback_env="GENERAL_TOPIC_ID")
    if general_chat:
        try:
            kwargs = {"chat_id": int(general_chat), "text": f"⚠️ <i>[Fallback General Log]</i>\n\n{text}", "parse_mode": "HTML"}
            if gen_topic > 0:
                kwargs["message_thread_id"] = gen_topic
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            return await bot.send_message(**kwargs)
        except Exception as e2:
            await _notify_owners(bot, f"❌ <b>Critical Log Failure:</b> General log <code>{general_chat}</code> also failed: <code>{e2}</code>\n\n{text}")
            return None

    await _notify_owners(bot, f"⚠️ <b>No Log Destination Configured!</b>\n\n{text}")
    return None


async def _notify_owners(bot, text: str):
    for oid in get_owner_ids():
        try:
            await bot.send_message(chat_id=int(oid), text=text, parse_mode="HTML")
        except Exception:
            pass


async def send_startup_notification(application):
    try:
        bot_info = await application.bot.get_me()
        tpl = get_template("startup_log")
        raw = tpl.get("text") or "🔄 <b>Bot Restarted Successfully</b>\n🤖 <b>{bot_title}</b> (@{bot_username}) is online at {date} {time}"
        startup_text = format_template_string(raw, {"bot_title": bot_info.first_name or "Mastermind", "bot_username": bot_info.username or "Bot"})
        await send_log_with_fallback(application.bot, startup_text, "general_log_group_id", "general_topic_id")
    except Exception as e:
        print(f"[STARTUP LOG WARNING]: {e}")
