import sqlite3
from modules.database.config_db import get_config


def get_support_chat_id():
    val = get_config("support_chat_id", fallback_env="SUPPORT_CHAT_ID")
    try:
        return int(val) if val else None
    except ValueError:
        return None


def set_ban_db(target_id: int, ban_type: str, reason: str):
    conn = sqlite3.connect("mastermind_users.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS bans (target_id INTEGER PRIMARY KEY, ban_type TEXT, reason TEXT)")
    c.execute("INSERT OR REPLACE INTO bans (target_id, ban_type, reason) VALUES (?, ?, ?)", (int(target_id), ban_type, reason))
    c.execute("UPDATE users SET ban_status = ?, role = 'Banned' WHERE user_id = ?", (ban_type, int(target_id)))
    conn.commit()
    conn.close()


def remove_ban_db(target_id: int):
    conn = sqlite3.connect("mastermind_users.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS bans (target_id INTEGER PRIMARY KEY, ban_type TEXT, reason TEXT)")
    c.execute("DELETE FROM bans WHERE target_id = ?", (int(target_id),))
    c.execute("UPDATE users SET ban_status = 'none', role = CASE WHEN role = 'Banned' THEN 'Normal User' ELSE role END WHERE user_id = ?", (int(target_id),))
    conn.commit()
    conn.close()


def get_ban_status(target_id: int):
    try:
        conn = sqlite3.connect("mastermind_users.db")
        row = conn.execute("SELECT ban_type, reason FROM bans WHERE target_id = ?", (int(target_id),)).fetchone()
        conn.close()
        if row:
            return {"is_banned": True, "ban_type": row[0], "reason": row[1]}
    except Exception:
        pass
    return {"is_banned": False, "ban_type": "none", "reason": None}


def check_access(user_id: int, chat_id: int, chat_type: str):
    support_id = get_support_chat_id()
    chat_status = get_ban_status(chat_id)
    if chat_status["is_banned"]:
        return False, f"🚫 This chat is banned from using the bot.\nReason: {chat_status['reason']}"
    user_status = get_ban_status(user_id)
    if not user_status["is_banned"]:
        return True, None
    btype, reason = user_status["ban_type"], user_status["reason"]
    if btype == "all":
        return False, f"🚫 You are banned from using this bot.\n📝 Reason: {reason}"
    if btype == "pm" and chat_type == "private":
        return False, f"🚫 You are restricted from using this bot in PM.\n📝 Reason: {reason}"
    if btype == "support" and (not support_id or chat_id != support_id):
        return False, f"🚫 You are restricted to support chat only.\n📝 Reason: {reason}"
    return True, None


check_user_access = check_access
