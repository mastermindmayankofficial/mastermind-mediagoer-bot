import os
import json
import re
import sqlite3
from datetime import datetime

DB_DIR = "database"
DB_PATH = os.path.join(DB_DIR, "config.db")
_CONFIG_CACHE = {}

DEFAULT_CONFIGS = {
    "bot_title": ("Mastermind Library Bot", "text", "Display title of the bot"),
    "bot_username": ("MastermindBot", "text", "Bot username without @"),
    "helper_bot_username": ("MastermindHelperBot", "text", "Helper bot username without @"),
    "storage_channel_id": ("-1003511375054", "channel", "Permanent file storage channel/group ID"),
    "posting_channel_id": ("-1003936877675", "channel", "Temporary file delivery posting channel ID"),
    "request_log_chat_id": ("-1004447676324", "channel", "Channel/group ID where book requests are posted"),
    "admin_log_group_id": ("-1003936877675", "channel", "Admin & moderation audit log group ID"),
    "general_log_group_id": ("-1003936877675", "channel", "General fallback log group ID"),
    "support_chat_id": ("-1004496093454", "channel", "Support group ID"),
    "general_topic_id": ("1", "int", "General topic thread ID"),
    "index_log_topic_id": ("18", "int", "Indexing & upload approval log topic ID"),
    "group_log_topic_id": ("5", "int", "Group events log topic ID"),
    "channel_log_topic_id": ("8", "int", "Channel events log topic ID"),
    "user_log_topic_id": ("11", "int", "User events log topic ID"),
    "max_index_batch": ("10", "int", "Max files processed per indexing batch"),
    "index_sleep_seconds": ("10", "int", "Cooldown sleep seconds after each 10-file batch"),
    "file_delete_after_seconds": ("120", "int", "Auto-delete timer (seconds) for temporary posting channel files"),
    "auto_delete_enabled": ("true", "bool", "Whether temporary posted files auto-delete"),
    "fsub_enabled": ("false", "bool", "Whether Force Subscribe is globally active"),
    "is_broadcast_enabled": ("true", "bool", "Whether broadcasting is enabled"),
    "require_helper_bot_start": ("true", "bool", "Require user to start helper bot before file delivery"),
    "search_quota_default": ("10", "int", "Default daily search quota for Normal Users"),
    "request_quota_default": ("10", "int", "Default daily request quota for Normal Users"),
    "promoter_quota_default": ("20", "int", "Default daily quota for Promoters"),
    "volunteer_quota_default": ("30", "int", "Default daily quota for Volunteers"),
    "moderator_quota_default": ("40", "int", "Default daily quota for Moderators"),
    "referral_bonus_search": ("10", "int", "Referral bonus added to search quota"),
    "referral_bonus_request": ("10", "int", "Referral bonus added to request quota"),
}

DEFAULT_TEMPLATES = {
    "start": {
        "module": "start",
        "title": "START MESSAGE",
        "description": "WHEN USER GIVE START COMMAND OR START THE BOT THEN BOT REPLY START MESSAGE. IN START MESSAGE BOT OWNER CAN SET START MESSAGE TEXT, PICTURE AND BUTTON.",
        "text": "Hi <b>{user_name}</b>, welcome to <b>{bot_title}</b>! 👋\n\n📚 Search ebooks & audiobooks, request missing titles, and earn bonus quotas by inviting friends.\nTap the buttons below to explore the bot.",
    },
    "about": {
        "module": "start",
        "title": "ABOUT MESSAGE",
        "description": "DISPLAYS BOT INFORMATION, VERSION, AND ARCHITECTURE DETAILS WHEN USER TAPS ABOUT.",
        "text": "🤖 <b>About {bot_title}</b>\n\n• <b>Bot:</b> @{bot_username}\n• <b>Date:</b> {date} | <b>Time:</b> {time}",
    },
    "help": {"module": "help", "title": "USER HELP MESSAGE", "description": "MAIN /help SCREEN FOR ALL USERS.", "text": ""},
    "adminhelp": {"module": "help", "title": "ADMIN HELP MESSAGE", "description": "RESTRICTED /adminhelp SCREEN FOR ADMINS/OWNERS.", "text": ""},
    "search_results": {"module": "search", "title": "SEARCH RESULTS HEADER", "description": "HEADER SHOWN FOR DATABASE MATCHES.", "text": "🔍 <b>Search results from {bot_title}'s database</b>"},
    "delivery_reply": {
        "module": "search",
        "title": "FILE DELIVERY REPLY",
        "description": "MESSAGE SENT WHEN HELPER BOT DELIVERS A FILE.",
        "text": "✅ <b>File Delivered!</b>\n\n📁 <b>File:</b> <code>{file_name}</code>\n📢 <b>Channel:</b> {channel_link}\n🔗 <b>Message:</b> <a href=\"{message_link}\">Open File</a>",
    },
    "helper_not_started": {
        "module": "search",
        "title": "HELPER BOT REQUIRED",
        "description": "SHOWN IF USER HAS NOT STARTED HELPER BOT.",
        "text": "⚠️ Please start the helper bot first to receive the file.",
    },
    "request_received": {
        "module": "request",
        "title": "REQUEST CONFIRMATION",
        "description": "SHOWN WHEN A BOOK REQUEST IS LOGGED.",
        "text": "✅ <b>Request received!</b>\n\n<b>{request_summary}</b>\n\nYour request has been noted. Admins will review it soon!",
    },
    "quota_status": {
        "module": "quota",
        "title": "QUOTA STATUS MESSAGE",
        "description": "DISPLAYS REMAINING DAILY QUOTAS.",
        "text": "👤 <b>Your Role:</b> <code>{role}</code>\n\n🔍 <b>Searches Left:</b> <code>{searches_left} / {searches_limit}</code>\n📥 <b>Requests Left:</b> <code>{requests_left} / {requests_limit}</code>",
    },
    "referral_message": {
        "module": "quota",
        "title": "REFERRAL DASHBOARD",
        "description": "SHOWN ON /refer COMMAND.",
        "text": "🔗 <b>Your Referral Dashboard</b>\n\n📌 <b>Link:</b> <code>{referral_link}</code>\n📊 <b>Invited:</b> <code>{total_invites}</code> | 🎁 <b>Bonus:</b> <code>+{bonus_earned}</code>",
    },
    "index_caption": {"module": "indexing", "title": "STORAGE INDEX CAPTION", "description": "CAPTION FOR INDEXED FILES.", "text": ""},
    "role_updated": {"module": "roles", "title": "ROLE ASSIGNMENT MESSAGE", "description": "SHOWN WHEN ROLE IS UPDATED.", "text": "🎖 <b>Role Updated!</b>\n👤 <b>User:</b> {target_user}\n🛡 <b>New Role:</b> <code>{new_role}</code>\n📊 <b>New Quota:</b> <code>{new_quota}</code>"},
    "startup_log": {"module": "logs", "title": "STARTUP LOG MESSAGE", "description": "BOT STARTUP NOTIFICATION.", "text": "🔄 <b>Bot Restarted Successfully</b>\n🤖 <b>{bot_title}</b> is online."},
    "fsub_message": {
        "module": "fsub",
        "title": "FORCE SUBSCRIBE MESSAGE",
        "description": "SHOWN WHEN USER MUST JOIN FSUB CHANNELS.",
        "text": "📢 <b>Subscription Required!</b>\n\nHello <b>{user_name}</b>, please join our channel(s) below to use <b>{bot_title}</b>, then tap <b>✅ Try Again</b>.",
    },
}


def _ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def get_connection():
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_config_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT,
            type TEXT DEFAULT 'text',
            updated_by INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            description TEXT DEFAULT ''
        )
    """)
    cursor.execute("PRAGMA table_info(config)")
    cols = {row["name"] for row in cursor.fetchall()}
    for col, ctype in [("updated_by", "INTEGER DEFAULT 0"), ("updated_at", "TEXT DEFAULT ''"), ("description", "TEXT DEFAULT ''")]:
        if col not in cols:
            cursor.execute(f"ALTER TABLE config ADD COLUMN {col} {ctype}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            name TEXT PRIMARY KEY,
            module TEXT DEFAULT 'general',
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            text TEXT DEFAULT '',
            media_type TEXT DEFAULT 'none',
            media_id TEXT DEFAULT '',
            buttons_json TEXT DEFAULT '[]',
            updated_by INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fsub_channels (
            channel_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT 'Channel',
            invite_link TEXT DEFAULT '',
            mode TEXT DEFAULT 'normal',
            added_by INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fsub_requests (
            channel_id INTEGER,
            user_id INTEGER,
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, user_id)
        )
    """)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for k, (val, vtype, desc) in DEFAULT_CONFIGS.items():
        env_val = os.getenv(k.upper())
        cursor.execute(
            "INSERT OR IGNORE INTO config (key, value, type, updated_by, updated_at, description) VALUES (?, ?, ?, 0, ?, ?)",
            (k, str(env_val if env_val is not None else val), vtype, now_str, desc),
        )
    for tname, tdata in DEFAULT_TEMPLATES.items():
        cursor.execute(
            "INSERT OR IGNORE INTO templates (name, module, title, description, text, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tname, tdata["module"], tdata["title"], tdata["description"], tdata["text"], now_str),
        )
    conn.commit()
    conn.close()


def reload_config_cache():
    global _CONFIG_CACHE
    init_config_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config")
    _CONFIG_CACHE = {row["key"]: row["value"] for row in cursor.fetchall()}
    conn.close()
    return _CONFIG_CACHE


def get_config(key, default=None, fallback_env=None):
    init_config_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row is not None and row["value"] not in (None, ""):
        return row["value"]
    if fallback_env and os.getenv(fallback_env):
        return os.getenv(fallback_env)
    if os.getenv(key.upper()):
        return os.getenv(key.upper())
    if key in DEFAULT_CONFIGS:
        return DEFAULT_CONFIGS[key][0]
    return default


def get_config_int(key, default=0, fallback_env=None) -> int:
    try:
        return int(get_config(key, default=str(default), fallback_env=fallback_env))
    except (ValueError, TypeError):
        return default


def get_config_bool(key, default=False) -> bool:
    return str(get_config(key, default=str(default))).strip().lower() in ("true", "1", "yes", "on")


def set_config(key, value, value_type="text", updated_by=0, description=""):
    init_config_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not description and key in DEFAULT_CONFIGS:
        description = DEFAULT_CONFIGS[key][2]
        if value_type == "text":
            value_type = DEFAULT_CONFIGS[key][1]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO config (key, value, type, updated_by, updated_at, description)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, type=excluded.type, updated_by=excluded.updated_by, updated_at=excluded.updated_at
    """, (key, str(value), value_type, updated_by, now_str, description))
    conn.commit()
    conn.close()
    _CONFIG_CACHE[key] = str(value)
    return True


def get_all_configs():
    init_config_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, type, value, updated_by, updated_at, description FROM config ORDER BY key ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_template(name: str) -> dict:
    init_config_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM templates WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        try:
            d["buttons"] = json.loads(d.get("buttons_json") or "[]")
        except Exception:
            d["buttons"] = []
        return d
    return {"name": name, "module": "general", "title": name.upper(), "description": "", "text": "", "media_type": "none", "media_id": "", "buttons": []}


def list_templates(module: str = None) -> list:
    init_config_db()
    conn = get_connection()
    cursor = conn.cursor()
    if module:
        cursor.execute("SELECT * FROM templates WHERE module = ? ORDER BY name ASC", (module,))
    else:
        cursor.execute("SELECT * FROM templates ORDER BY module ASC, name ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for d in rows:
        try:
            d["buttons"] = json.loads(d.get("buttons_json") or "[]")
        except Exception:
            d["buttons"] = []
    return rows


def update_template_text(name: str, text: str, updated_by: int = 0):
    init_config_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute("""
        INSERT INTO templates (name, text, updated_by, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET text=excluded.text, updated_by=excluded.updated_by, updated_at=excluded.updated_at
    """, (name, text, updated_by, now_str))
    conn.commit()
    conn.close()


def update_template_media(name: str, media_type: str, media_id: str, updated_by: int = 0):
    init_config_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute("""
        INSERT INTO templates (name, media_type, media_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET media_type=excluded.media_type, media_id=excluded.media_id, updated_by=excluded.updated_by, updated_at=excluded.updated_at
    """, (name, media_type, media_id, updated_by, now_str))
    conn.commit()
    conn.close()


def remove_template_media(name: str, updated_by: int = 0):
    update_template_media(name, "none", "", updated_by)


def add_template_button(name: str, label: str, target: str, updated_by: int = 0):
    tpl = get_template(name)
    buttons = tpl.get("buttons", [])
    btype = "url" if target.startswith(("http://", "https://", "tg://")) else "callback"
    buttons.append({"label": label, "target": target, "type": btype})
    conn = get_connection()
    conn.execute("UPDATE templates SET buttons_json=?, updated_by=?, updated_at=? WHERE name=?", (json.dumps(buttons), updated_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name))
    conn.commit()
    conn.close()


def remove_template_button(name: str, index: int, updated_by: int = 0) -> bool:
    tpl = get_template(name)
    buttons = tpl.get("buttons", [])
    if 0 <= index < len(buttons):
        buttons.pop(index)
        conn = get_connection()
        conn.execute("UPDATE templates SET buttons_json=?, updated_by=?, updated_at=? WHERE name=?", (json.dumps(buttons), updated_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name))
        conn.commit()
        conn.close()
        return True
    return False


def format_template_string(raw_text: str, extra_vars: dict = None) -> str:
    if not raw_text:
        return ""
    now = datetime.now()
    vars_map = {
        "bot_title": get_config("bot_title", "Mastermind Library Bot"),
        "bot_username": get_config("bot_username", "MastermindBot").lstrip("@"),
        "helper_bot_username": get_config("helper_bot_username", "MastermindHelperBot").lstrip("@"),
        "chat_title": "Private Chat",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%I:%M %p"),
        "user_name": "User",
    }
    if extra_vars:
        vars_map.update(extra_vars)
    text = raw_text.replace("\\n", "\n")
    for k, v in vars_map.items():
        text = text.replace(f"{{{k}}}", str(v))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)
    text = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


def add_fsub_channel_db(channel_id: int, title: str, invite_link: str = "", mode: str = "normal", added_by: int = 0):
    init_config_db()
    conn = get_connection()
    conn.execute("""
        INSERT INTO fsub_channels (channel_id, title, invite_link, mode, added_by) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title, invite_link=CASE WHEN excluded.invite_link!='' THEN excluded.invite_link ELSE fsub_channels.invite_link END, mode=excluded.mode
    """, (int(channel_id), title, invite_link, mode, added_by))
    conn.commit()
    conn.close()


def remove_fsub_channel_db(channel_id: int):
    init_config_db()
    conn = get_connection()
    conn.execute("DELETE FROM fsub_channels WHERE channel_id = ?", (int(channel_id),))
    conn.execute("DELETE FROM fsub_requests WHERE channel_id = ?", (int(channel_id),))
    conn.commit()
    conn.close()


def get_fsub_channels_db() -> list:
    init_config_db()
    conn = get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM fsub_channels ORDER BY created_at ASC").fetchall()]
    conn.close()
    return rows


def record_fsub_join_request_db(channel_id: int, user_id: int):
    init_config_db()
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO fsub_requests (channel_id, user_id) VALUES (?, ?)", (int(channel_id), int(user_id)))
    conn.commit()
    conn.close()


def has_fsub_join_request_db(channel_id: int, user_id: int) -> bool:
    init_config_db()
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM fsub_requests WHERE channel_id = ? AND user_id = ?", (int(channel_id), int(user_id))).fetchone()
    conn.close()
    return row is not None


def reset_channels_and_groups_db():
    init_config_db()
    conn = get_connection()
    conn.execute("DELETE FROM fsub_channels")
    conn.execute("DELETE FROM fsub_requests")
    for k, (val, vtype, _) in DEFAULT_CONFIGS.items():
        if vtype == "channel" or "topic_id" in k:
            conn.execute("UPDATE config SET value = ? WHERE key = ?", (str(val), k))
    conn.commit()
    conn.close()
    reload_config_cache()


init_config_db()
