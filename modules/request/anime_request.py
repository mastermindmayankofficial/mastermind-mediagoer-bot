import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.allowance.allowance import can_user_request
from modules.request.handlers import _submit_final_request
from mediagoer import Mediagoer

logger = logging.getLogger(__name__)
_MG = Mediagoer(provider="anilist")


def fetch_anime_request_options(query: str) -> list:
    """
    Queries AniList, MyAnimeList (Jikan), and Kitsu via Mediagoer for Anime & Manga request options.
    """
    results = []
    for prov in ("anilist", "mal", "kitsu"):
        try:
            items = _MG.search(query, provider=prov, results=3)
            for item in items:
                studios = [str(s) for s in (item.get("studios") or []) if str(s)]
                authors = [str(a) for a in (item.get("authors") or []) if str(a)]
                creator = ", ".join(studios or authors) or "Unknown Studio"
                year = str(item.get("year") or "N/A")
                rating = item.get("rating")
                rating_str = f"{rating}/10" if rating not in (None, "") else "N/A"
                eps = item.get("episodes")
                ep_str = f"{eps} eps" if eps else (item.get("kind") or "Anime").title()
                results.append({
                    "title": item.get("title") or query,
                    "author": creator,
                    "series": item.get("series") or "",
                    "year": year,
                    "rating": rating_str,
                    "episodes": ep_str,
                    "url": item.get("url") or "",
                    "source": prov.upper() if prov == "mal" else prov.title(),
                    "format": f"Anime ({ep_str})",
                    "request_type": "Anime/Manga",
                })
                if len(results) >= 4:
                    return results
        except Exception as e:
            logger.debug(f"Mediagoer anime request lookup ({prov}) warning: {e}")
    return results


async def show_anime_request_options(target_msg, user, query: str, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = False):
    if not can_user_request(user.id):
        txt = "⚠️ <b>Daily request quota reached!</b> Use <code>/refer</code> to earn +10 bonus quota or wait for daily reset."
        if is_edit:
            await target_msg.edit_text(txt, parse_mode="HTML")
        else:
            await target_msg.reply_text(txt, parse_mode="HTML")
        return

    options = await asyncio.to_thread(fetch_anime_request_options, query)
    context.user_data["areq_candidates"] = options
    context.user_data["areq_raw_query"] = query

    kb = []
    if options:
        lines = ["⛩️ <b>Matching Anime / Manga options found on AniList, MAL & Kitsu:</b>\n"]
        for i, opt in enumerate(options, start=1):
            t_esc = html.escape(opt["title"])
            s_esc = html.escape(opt["author"])
            y_esc = html.escape(opt.get("year") or "N/A")
            r_esc = html.escape(opt.get("rating") or "N/A")
            ep_esc = html.escape(opt.get("episodes") or "Anime")
            u_esc = html.escape(opt.get("url") or "https://anilist.co")
            src = html.escape(opt.get("source") or "AniList")
            lines.append(
                f"{i}. <b>{t_esc}</b> ({y_esc}) — ⭐️ {r_esc} · {ep_esc}\n"
                f"   Studio/Creator: {s_esc} · <a href=\"{u_esc}\">{src}</a>\n"
            )
            btn_lbl = f"⛩️ {i}. {opt['title'][:24]} ({opt.get('source', 'MAL')})"
            kb.append([InlineKeyboardButton(btn_lbl, callback_data=f"areq_pick_opt_{i-1}")])
        lines.append('Select an anime/manga to submit your request, or choose "<b>None of these</b>" below:')
        text = "\n".join(lines)
    else:
        text = f"⛩️ <b>Request Anime / Manga:</b> <i>{html.escape(query)}</i>\n\nNo automatic AniList/MAL/Kitsu matches found. Choose how to submit:"

    kb.append([InlineKeyboardButton("📋 None of these — Send original anime request", callback_data="areq_send_original")])
    kb.append([InlineKeyboardButton("✍️ Enter Manual Anime Details (Title/Studio/Sub-Dub/Season)", callback_data="areq_start_manual")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="req_cancel")])

    if is_edit:
        await target_msg.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
    else:
        await target_msg.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)


async def requestanime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/requestanime <title> or /reqanime <title> — Request an Anime, Manga, or Light Novel."""
    msg = update.effective_message
    if not msg:
        return
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await msg.reply_text(
            "⛩️ <b>How to Request an Anime / Manga:</b>\n"
            "• <code>/requestanime &lt;anime or manga title&gt;</code>\n"
            "• Or tap <b>✍️ Manual Anime Request</b> below:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Start Manual Anime Request", callback_data="areq_start_manual")]]),
        )
        return
    await show_anime_request_options(msg, update.effective_user, query, context, is_edit=False)


async def handle_manual_anime_request_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    wiz = context.user_data.get("manual_areq_wizard")
    if not wiz or not update.message or not update.message.text:
        return False
    txt = update.message.text.strip()
    step = wiz.get("step")

    if step == "title":
        wiz["title"] = txt
        wiz["step"] = "studio"
        await update.message.reply_text("⛩️ <b>Step 2/4:</b> Enter the <b>Studio or Author</b> (or <code>Unknown</code>):", parse_mode="HTML")
        return True
    if step == "studio":
        wiz["studio"] = txt
        wiz["step"] = "audio_format"
        await update.message.reply_text("🔊 <b>Step 3/4:</b> Enter preferred <b>Format</b> (e.g. <code>1080p Sub</code>, <code>Dual Audio</code>, or <code>Manga CBZ</code>):", parse_mode="HTML")
        return True
    if step == "audio_format":
        wiz["audio_format"] = txt
        wiz["step"] = "season"
        await update.message.reply_text("📚 <b>Step 4/4:</b> Enter <b>Season / Franchise Name</b> (or <code>None</code>):", parse_mode="HTML")
        return True
    if step == "season":
        context.user_data.pop("manual_areq_wizard", None)
        series_val = "" if txt.lower() == "none" else txt
        status_msg = await update.message.reply_text("⏳ Submitting your manual anime/manga request...")
        await _submit_final_request(
            context.bot, update.effective_user, status_msg,
            wiz.get("title", "Unknown Anime"), wiz.get("studio", "Unknown"),
            series=series_val, fmt=wiz.get("audio_format", "Sub/Dub"), source="Manual Anime", request_type="Anime/Manga",
        )
        return True
    return False


async def anime_request_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data
    user = q.from_user

    if d.startswith("areq_from_search_"):
        await q.answer()
        query = d.replace("areq_from_search_", "", 1)
        await show_anime_request_options(q.message, user, query, context, is_edit=True)
    elif d.startswith("areq_pick_opt_"):
        await q.answer("Submitting selected anime/manga...")
        idx = int(d.replace("areq_pick_opt_", ""))
        opts = context.user_data.get("areq_candidates", [])
        if 0 <= idx < len(opts):
            o = opts[idx]
            await _submit_final_request(
                context.bot, user, q.message, o["title"], o["author"],
                o.get("series", ""), o.get("format", "Anime"), o.get("source", "AniList"), o.get("url", ""),
                request_type="Anime/Manga",
            )
    elif d == "areq_send_original":
        await q.answer("Submitting original anime request...")
        raw_q = context.user_data.get("areq_raw_query") or "Anime Request"
        await _submit_final_request(context.bot, user, q.message, raw_q, "As Requested", "", "Any", "Original Query", "", request_type="Anime/Manga")
    elif d == "areq_start_manual":
        await q.answer()
        context.user_data["manual_areq_wizard"] = {"step": "title"}
        await q.message.edit_text("⛩️ <b>Manual Anime/Manga Request — Step 1/4:</b>\nPlease reply with the <b>Anime or Manga Title</b>:", parse_mode="HTML")
