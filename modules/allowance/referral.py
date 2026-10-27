from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.database.config_db import get_config_int
from modules.database.user_db import record_referral_db, add_quota_limits_db, get_referred_users_db, user_exists_db


def process_referral(referrer_id: int, new_user_id: int, is_first_time: bool = True):
    if not is_first_time:
        return False, "⚠️ Referral bonuses are only valid for first-time registrations."
    ok, msg = record_referral_db(referrer_id, new_user_id, f"ref_{referrer_id}")
    if not ok:
        return False, msg
    s_bon = get_config_int("referral_bonus_search", 10)
    r_bon = get_config_int("referral_bonus_request", 10)
    add_quota_limits_db(referrer_id, search_bonus=s_bon, request_bonus=r_bon)
    add_quota_limits_db(new_user_id, search_bonus=s_bon, request_bonus=r_bon)
    return True, f"Referral bonus applied: +{s_bon} search quota, +{r_bon} request quota"


def get_user_referral_stats(user_id: int):
    rows = get_referred_users_db(user_id)
    return {"total_invites": len(rows), "referred_list": rows}


async def process_referral_with_notification(context, referrer_id: int, new_user_id: int, new_user_name: str = "User", is_first_time: bool = True):
    ok, msg = process_referral(referrer_id, new_user_id, is_first_time=is_first_time)
    if not ok:
        return False, msg
    notice = "🎁 <b>Referral bonus applied: +10 search quota, +10 request quota</b>"
    if context and hasattr(context, "bot"):
        for uid, txt in [
            (referrer_id, f"👤 <b>New Referral Joined!</b> ({new_user_name})\n{notice}"),
            (new_user_id, f"🎉 <b>Welcome!</b>\n{notice}"),
        ]:
            try:
                await context.bot.send_message(chat_id=int(uid), text=txt, parse_mode="HTML")
            except Exception:
                pass
    return True, msg
