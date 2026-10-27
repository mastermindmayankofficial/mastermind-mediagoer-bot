import os
import sqlite3
from datetime import datetime

DB_PATH = "database/files.db"


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_file_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_unique_id TEXT UNIQUE,
            file_id TEXT,
            storage_message_id INTEGER,
            file_name TEXT,
            file_size INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 0,
            user_title TEXT DEFAULT '',
            caption TEXT DEFAULT '',
            extension TEXT DEFAULT '',
            file_type TEXT DEFAULT '',
            category TEXT DEFAULT 'book',
            title TEXT DEFAULT '',
            author TEXT DEFAULT '',
            narrator TEXT DEFAULT '',
            series TEXT DEFAULT '',
            publisher TEXT DEFAULT '',
            release_date TEXT DEFAULT '',
            length_str TEXT DEFAULT '',
            description TEXT DEFAULT '',
            keywords TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("PRAGMA table_info(indexed_files)")
    fcols = {r["name"] for r in c.fetchall()}
    for col in ["title", "author", "narrator", "series", "publisher", "release_date", "length_str", "description", "keywords"]:
        if col not in fcols:
            c.execute(f"ALTER TABLE indexed_files ADD COLUMN {col} TEXT DEFAULT ''")

    c.execute("""
        CREATE TABLE IF NOT EXISTS indexing_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_unique_id TEXT,
            file_name TEXT,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT '',
            caption TEXT DEFAULT '',
            channel_id INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 0,
            user_title TEXT DEFAULT '',
            source TEXT DEFAULT 'upload',
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'queued',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def _init_extra_file_tables():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            request_type TEXT DEFAULT 'Book/Audiobook',
            title TEXT,
            author TEXT DEFAULT '',
            series TEXT DEFAULT '',
            format TEXT DEFAULT 'Any',
            source TEXT DEFAULT 'Manual',
            audible_url TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            log_chat_id INTEGER DEFAULT 0,
            log_message_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS delivery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_name TEXT,
            sender_bot TEXT,
            receiver_id INTEGER,
            channel_link TEXT,
            message_link TEXT,
            posting_message_id INTEGER DEFAULT 0,
            delivery_status TEXT DEFAULT 'delivered',
            deleted_at TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_file_by_unique_id_db(file_unique_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM indexed_files WHERE file_unique_id = ?", (file_unique_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_file_by_id_db(row_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM indexed_files WHERE id = ?", (int(row_id),)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_indexed_file_db(
    file_unique_id, file_id, storage_message_id, file_name, file_size, duration,
    user_id, user_title, caption, extension, file_type, category,
    title="", author="", narrator="", series="", publisher="", release_date="", length_str="", description="", keywords=""
):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO indexed_files (
            file_unique_id, file_id, storage_message_id, file_name, file_size,
            duration, user_id, user_title, caption, extension, file_type, category,
            title, author, narrator, series, publisher, release_date, length_str, description, keywords
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_unique_id, file_id, storage_message_id, file_name, file_size,
        duration, user_id, user_title, caption, extension, file_type, category,
        title, author, narrator, series, publisher, release_date, length_str, description, keywords
    ))
    conn.commit()
    conn.close()


def search_indexed_files_db(keyword: str, limit: int = 50) -> list:
    conn = get_connection()
    q = f"%{keyword.strip()}%"
    rows = conn.execute("""
        SELECT * FROM indexed_files
        WHERE file_name LIKE ? OR caption LIKE ? OR title LIKE ? OR author LIKE ?
           OR narrator LIKE ? OR series LIKE ? OR category LIKE ? OR description LIKE ? OR keywords LIKE ?
        ORDER BY id DESC LIMIT ?
    """, (q, q, q, q, q, q, q, q, q, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_file_delivery_db(file_id, file_name, sender_bot, receiver_id, channel_link, message_link, posting_msg_id, status="delivered"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO delivery_logs (file_id, file_name, sender_bot, receiver_id, channel_link, message_link, posting_message_id, delivery_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (file_id, file_name, sender_bot, receiver_id, channel_link, message_link, posting_msg_id, status))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def mark_delivery_deleted_db(log_id: int):
    conn = get_connection()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE delivery_logs SET deleted_at = ?, delivery_status = 'auto_deleted' WHERE id = ?", (now_str, int(log_id)))
    conn.commit()
    conn.close()
    return now_str


def reset_file_db():
    conn = get_connection()
    for t in ["indexed_files", "indexing_queue", "requests_queue", "delivery_logs"]:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()


init_file_db()
_init_extra_file_tables()
