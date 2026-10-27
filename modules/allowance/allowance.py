from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.user_db import (
    get_user_role_db,
    get_quota_record_db,
    update_quota_counts_db,
    increment_search_used_db,
    increment_request_used_db,
    add_quota_limits_db,
)
from modules.database.config_db import get_template, format_template_string
from modules.allowance.referral import get_user_referral_stats
from modules.log.startup_log import send_log_with_fallback


def check_and_reset_quota(user_id: int):
    today_str = datetime.now().strftime("%Y-%m-%d")
    row = get_quota_record_db(user_id)
    if row and row[4] != today_str:
        update_quota_counts_db(user_id, 0, 0, today_str)


def can_user_search(user_id: int) -> bool:
    role = get_user_role_db(user_id)
    if role == "Banned":
        return False
    if role in ("Admin", "Owner"):
        return True
    check_and_reset_quota(user_id)
    row = get_quota_record_db(user_id)
    return True if not row else (row[0] < row[1])


def can_user_request(user_id: int) -> bool:
    role = get_user_role_db(user_id)
    if role == "Banned":
        return False
    if role in ("Admin", "Owner"):
        return True
    check_and_reset_quota(user_id)
    row = get_quota_record_db(user_id)
    return True if not row else (row[2] < row[3])


def deduct_search_quota(user_id: int):
    """Deducted ONLY when a searched file is successfully delivered to the user."""
    if get_user_role_db(user_id) not in ("Admin", "Owner"):
        increment_search_used_db(user_id)


def deduct_request_quota(user_id: int):
    """Deducted ONLY when a request is successfully posted to the request log."""
    if get_user_role_db(user_id) not in ("Admin", "Owner"):
        increment_request_used_db(user_id)


def get_user_quota_summary(user_id: int):
    check_and_reset_quota(user_id)
    role = get_user_role_db(user_id)
    row = get_quota_record_db(user_id)
    if role in ("Admin", "Owner"):
        return {"role": role, "unlimited": True, "searches_left": "Unlimited", "searches_limit": "Unlimited", "requests_left": "Unlimited", "requests_limit": "Unlimited"}
    if row:
        s_used, s_lim, r_used, r_lim, _ = row
        return {"role": role, "unlimited": False, "searches_left": max(0, s_lim - s_used), "searches_limit": s_lim, "requests_left": max(0, r_lim - r_used), "requests_limit": r_lim}
    return {"role": role, "unlimited": False, "searches_left": 10, "searches_limit": 10, "requests_left": 10, "requests_limit": 10}


def gift_quota(admin_user_id: int, target_user_id: int, search_bonus: int = 0, request_bonus: int = 0):
    if get_user_role_db(admin_user_id) not in ("Admin", "Owner"):
        return False, "⛔ Access denied. Only Admins and Owners can use /gift."
    add_quota_limits_db(target_user_id, search_bonus, request_bonus)
    return True, f"🎁 Added <b>+{search_bonus} search quota</b> and <b>+{request_bonus} request quota</b> to user <code>{target_user_id}</code>."


async def quota_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = update.effective_user.id
    s = get_user_quota_summary(user_id)
    tpl = get_template("quota_status")
    text = format_template_string(tpl.get("text"), s)
    await msg.reply_text(text, parse_mode="HTML")


async def gift_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text("⚠️ <b>Usage:</b> <code>/gift &lt;user_id&gt; &lt;search_bonus&gt; [request_bonus]</code>", parse_mode="HTML")
        return
    try:
        target_id = int(args[0])
        s_bonus = int(args[1])
        r_bonus = int(args[2]) if len(args) > 2 else s_bonus
    except ValueError:
        await update.effective_message.reply_text("⚠️ Invalid numbers. Usage: <code>/gift &lt;user_id&gt; &lt;search_bonus&gt; [request_bonus]</code>", parse_mode="HTML")
        return
    ok, reply = gift_quota(admin_id, target_id, s_bonus, r_bonus)
    await update.effective_message.reply_text(reply, parse_mode="HTML")
    if ok:
        await send_log_with_fallback(context.bot, f"🎁 <b>Quota Gifted</b>\n👮 By: <code>{admin_id}</code>\n👤 To: <code>{target_id}</code> (+{s_bonus}S / +{r_bonus}R)", "admin_log_group_id", "user_log_topic_id")


async def refer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_uname = context.bot.username or "Bot"
    ref_link = f"https://t.me/{bot_uname}?start=ref_{user.id}"
    stats = get_user_referral_stats(user.id)
    total = stats["total_invites"]
    text = (
        f"🔗 <b>Your Referral Dashboard</b>\n\n"
        f"📌 <b>Your Referral Link:</b>\n<code>{ref_link}</code>\n"
        f"💡 Or command: <code>/ref {user.id}</code>\n\n"
        f"📊 <b>Total Friends Invited:</b> <code>{total}</code>\n"
        f"🎁 <b>Total Bonus Earned:</b> <code>+{total * 10}</code> Searches & Requests\n\n"
        f"<i>When a new first-time user joins via your link, both of you receive +10 search quota and +10 request quota!</i>"
    )
    share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20and%20get%20%2B10%20bonus%20quota"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Share Referral Link", url=share_url)]])
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb)
