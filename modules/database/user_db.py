import os
import sqlite3
from datetime import datetime
from modules.database.config_db import get_config_int

DB_FILE = "mastermind_users.db"
OWNER_IDS = {7261537212}


def get_owner_ids() -> set:
    ids = set(OWNER_IDS)
    env_admins = os.getenv("ADMIN_IDS", "")
    for part in env_admins.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def get_role_base_quota(role: str) -> tuple:
    role_map = {
        "Banned": (0, 0),
        "Normal User": (get_config_int("search_quota_default", 10), get_config_int("request_quota_default", 10)),
        "Promoter": (get_config_int("promoter_quota_default", 20), get_config_int("promoter_quota_default", 20)),
        "Volunteer": (get_config_int("volunteer_quota_default", 30), get_config_int("volunteer_quota_default", 30)),
        "Moderator": (get_config_int("moderator_quota_default", 40), get_config_int("moderator_quota_default", 40)),
        "Admin": (999999, 999999),
        "Owner": (999999, 999999),
    }
    return role_map.get(role, (10, 10))


def init_user_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            role TEXT DEFAULT 'Normal User',
            ban_status TEXT DEFAULT 'none',
            helper_started INTEGER DEFAULT 0,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA table_info(users)")
    ucols = {r[1] for r in cursor.fetchall()}
    if "helper_started" not in ucols:
        cursor.execute("ALTER TABLE users ADD COLUMN helper_started INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quotas (
            user_id INTEGER PRIMARY KEY,
            searches_used INTEGER DEFAULT 0,
            searches_limit INTEGER DEFAULT 10,
            requests_used INTEGER DEFAULT 0,
            requests_limit INTEGER DEFAULT 10,
            bonus_searches INTEGER DEFAULT 0,
            bonus_requests INTEGER DEFAULT 0,
            last_reset_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    cursor.execute("PRAGMA table_info(quotas)")
    qcols = {r[1] for r in cursor.fetchall()}
    if "bonus_searches" not in qcols:
        cursor.execute("ALTER TABLE quotas ADD COLUMN bonus_searches INTEGER DEFAULT 0")
    if "bonus_requests" not in qcols:
        cursor.execute("ALTER TABLE quotas ADD COLUMN bonus_requests INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referred_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            referral_code TEXT DEFAULT '',
            status TEXT DEFAULT 'used',
            bonus_applied INTEGER DEFAULT 1,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TEXT DEFAULT ''
        )
    """)
    cursor.execute("PRAGMA table_info(referrals)")
    rcols = {r[1] for r in cursor.fetchall()}
    for col, cdef in [("referral_code", "TEXT DEFAULT ''"), ("status", "TEXT DEFAULT 'used'"), ("bonus_applied", "INTEGER DEFAULT 1"), ("used_at", "TEXT DEFAULT ''")]:
        if col not in rcols:
            cursor.execute(f"ALTER TABLE referrals ADD COLUMN {col} {cdef}")

    conn.commit()
    conn.close()


def user_exists_db(user_id: int) -> bool:
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (int(user_id),)).fetchone()
    conn.close()
    return row is not None


def add_or_update_user_db(user_id, username, full_name, today_str, helper_started=None) -> bool:
    """Returns True if this is a brand-new user registration, False if existing."""
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, role FROM users WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()
    is_new = existing is None

    if is_new:
        role = "Owner" if user_id in get_owner_ids() else "Normal User"
        s_limit, r_limit = get_role_base_quota(role)
        h_flag = 1 if helper_started else 0
        cursor.execute(
            "INSERT INTO users (user_id, username, full_name, role, ban_status, helper_started) VALUES (?, ?, ?, ?, 'none', ?)",
            (user_id, username, full_name, role, h_flag),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO quotas (user_id, searches_used, searches_limit, requests_used, requests_limit, bonus_searches, bonus_requests, last_reset_date) VALUES (?, 0, ?, 0, ?, 0, 0, ?)",
            (user_id, s_limit, r_limit, today_str),
        )
    else:
        if helper_started is not None:
            cursor.execute("UPDATE users SET username=?, full_name=?, helper_started=? WHERE user_id=?", (username, full_name, int(bool(helper_started)), user_id))
        else:
            cursor.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?", (username, full_name, user_id))

    conn.commit()
    conn.close()
    return is_new


def set_helper_started_db(user_id: int, started: bool = True):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET helper_started = ? WHERE user_id = ?", (1 if started else 0, int(user_id)))
    conn.commit()
    conn.close()


def has_started_helper_bot_db(user_id: int) -> bool:
    init_user_db()
    if int(user_id) in get_owner_ids():
        return True
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT helper_started FROM users WHERE user_id = ?", (int(user_id),)).fetchone()
    conn.close()
    return bool(row and row[0])


def get_user_role_db(user_id: int) -> str:
    init_user_db()
    if int(user_id) in get_owner_ids():
        return "Owner"
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT role, ban_status FROM users WHERE user_id = ?", (int(user_id),)).fetchone()
    conn.close()
    if row:
        if row[1] and row[1] != "none":
            return "Banned"
        if row[0]:
            return row[0]
    return "Normal User"


def set_user_role_db(user_id: int, new_role: str) -> tuple:
    """Updates role and adjusts base quota limits while preserving referral/gift bonus quota."""
    init_user_db()
    s_base, r_base = get_role_base_quota(new_role)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (int(user_id),))
    if not cursor.fetchone():
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("INSERT INTO users (user_id, username, full_name, role, ban_status) VALUES (?, '', '', ?, 'none')", (int(user_id), new_role))
        cursor.execute("INSERT INTO quotas (user_id, searches_used, searches_limit, requests_used, requests_limit, bonus_searches, bonus_requests, last_reset_date) VALUES (?, 0, ?, 0, ?, 0, 0, ?)", (int(user_id), s_base, r_base, today_str))
    else:
        cursor.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, int(user_id)))
        qrow = cursor.execute("SELECT bonus_searches, bonus_requests FROM quotas WHERE user_id = ?", (int(user_id),)).fetchone()
        b_s = qrow[0] if qrow and qrow[0] else 0
        b_r = qrow[1] if qrow and qrow[1] else 0
        cursor.execute("UPDATE quotas SET searches_limit = ?, requests_limit = ? WHERE user_id = ?", (s_base + b_s, r_base + b_r, int(user_id)))
    conn.commit()
    conn.close()
    return s_base, r_base


def get_quota_record_db(user_id: int):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT searches_used, searches_limit, requests_used, requests_limit, last_reset_date FROM quotas WHERE user_id = ?", (int(user_id),)).fetchone()
    conn.close()
    return row


def update_quota_counts_db(user_id: int, searches_used: int, requests_used: int, reset_date: str):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE quotas SET searches_used = ?, requests_used = ?, last_reset_date = ? WHERE user_id = ?", (searches_used, requests_used, reset_date, int(user_id)))
    conn.commit()
    conn.close()


def increment_search_used_db(user_id: int):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE quotas SET searches_used = searches_used + 1 WHERE user_id = ?", (int(user_id),))
    conn.commit()
    conn.close()


def increment_request_used_db(user_id: int):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE quotas SET requests_used = requests_used + 1 WHERE user_id = ?", (int(user_id),))
    conn.commit()
    conn.close()


def add_quota_limits_db(target_user_id: int, search_bonus: int = 0, request_bonus: int = 0):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        UPDATE quotas
        SET searches_limit = searches_limit + ?,
            requests_limit = requests_limit + ?,
            bonus_searches = COALESCE(bonus_searches, 0) + ?,
            bonus_requests = COALESCE(bonus_requests, 0) + ?
        WHERE user_id = ?
    """, (search_bonus, request_bonus, search_bonus, request_bonus, int(target_user_id)))
    conn.commit()
    conn.close()


def record_referral_db(referrer_id: int, referred_id: int, referral_code: str = "") -> tuple:
    """Validates anti-abuse rules and records referral."""
    init_user_db()
    if int(referrer_id) == int(referred_id):
        return False, "⚠️ You cannot refer yourself."
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    ref_row = cursor.execute("SELECT role, ban_status FROM users WHERE user_id = ?", (int(referrer_id),)).fetchone()
    if not ref_row:
        conn.close()
        return False, "⚠️ Invalid referrer account."
    if ref_row[0] == "Banned" or (ref_row[1] and ref_row[1] != "none"):
        conn.close()
        return False, "⚠️ Referrals from restricted/banned users are not eligible."
    if cursor.execute("SELECT referred_id FROM referrals WHERE referred_id = ?", (int(referred_id),)).fetchone():
        conn.close()
        return False, "⚠️ You have already claimed a referral bonus."

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    code = referral_code or f"ref_{referrer_id}"
    cursor.execute(
        "INSERT INTO referrals (referred_id, referrer_id, referral_code, status, bonus_applied, used_at) VALUES (?, ?, ?, 'used', 1, ?)",
        (int(referred_id), int(referrer_id), code, now_str),
    )
    conn.commit()
    conn.close()
    return True, "Success"


def get_referred_users_db(referrer_id: int):
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT u.user_id, u.full_name, u.username, r.timestamp
        FROM referrals r
        JOIN users u ON r.referred_id = u.user_id
        WHERE r.referrer_id = ?
        ORDER BY r.timestamp DESC
    """, (int(referrer_id),)).fetchall()
    conn.close()
    return rows


def get_all_users_db(role_filter: str = None) -> list:
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    if role_filter and role_filter.lower() != "everyone":
        rows = conn.execute("SELECT user_id, username, full_name, role FROM users WHERE LOWER(role) = LOWER(?)", (role_filter,)).fetchall()
    else:
        rows = conn.execute("SELECT user_id, username, full_name, role FROM users").fetchall()
    conn.close()
    return rows


def reset_user_db():
    init_user_db()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM referrals")
    conn.execute("DELETE FROM quotas")
    conn.execute("DELETE FROM users")
    conn.execute("DROP TABLE IF EXISTS bans")
    conn.commit()
    conn.close()


init_user_db()
