import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.allowance.allowance import can_user_request
from modules.request.handlers import _submit_final_request
from mediagoer import Mediagoer

logger = logging.getLogger(__name__)
_MG = Mediagoer(provider="imdb")


def fetch_movie_request_options(query: str) -> list:
    """
    Queries IMDb and Letterboxd via Mediagoer for Movie & TV Series request options.
    """
    results = []
    for prov in ("imdb", "letterboxd"):
        try:
            items = _MG.search(query, provider=prov, results=3)
            for item in items:
                if item.mediaID and (not item.get("directors") or not item.get("rating")):
                    try:
                        full = _MG.get(item.mediaID, provider=prov)
                        if full and full.get("title"):
                            item = full
                    except Exception:
                        pass
                directors = ", ".join(str(d) for d in (item.get("directors") or []) if str(d)) or "N/A"
                year = str(item.get("year") or "N/A")
                rating = item.get("rating")
                scale = item.default_rating_scale()
                rating_str = f"{rating}/{scale}" if rating not in (None, "") else "N/A"
                series_str = item.get("full series") or item.get("series") or ""
                results.append({
                    "title": item.get("title") or query,
                    "author": directors,
                    "series": series_str,
                    "year": year,
                    "rating": rating_str,
                    "url": item.get("url") or "",
                    "source": "IMDb" if prov == "imdb" else "Letterboxd",
                    "format": "1080p / 720p Movie/Series",
                    "request_type": "Movie/Series",
                })
                if len(results) >= 4:
                    return results
        except Exception as e:
            logger.debug(f"Mediagoer movie request lookup ({prov}) warning: {e}")
    return results


async def show_movie_request_options(target_msg, user, query: str, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = False):
    if not can_user_request(user.id):
        txt = "⚠️ <b>Daily request quota reached!</b> Use <code>/refer</code> to earn +10 bonus quota or wait for daily reset."
        if is_edit:
            await target_msg.edit_text(txt, parse_mode="HTML")
        else:
            await target_msg.reply_text(txt, parse_mode="HTML")
        return

    options = await asyncio.to_thread(fetch_movie_request_options, query)
    context.user_data["mreq_candidates"] = options
    context.user_data["mreq_raw_query"] = query

    kb = []
    if options:
        lines = ["🎬 <b>Matching Movie / TV Series options found on IMDb & Letterboxd:</b>\n"]
        for i, opt in enumerate(options, start=1):
            t_esc = html.escape(opt["title"])
            d_esc = html.escape(opt["author"])
            y_esc = html.escape(opt.get("year") or "N/A")
            r_esc = html.escape(opt.get("rating") or "N/A")
            u_esc = html.escape(opt.get("url") or "https://www.imdb.com")
            src = html.escape(opt.get("source") or "IMDb")
            lines.append(
                f"{i}. <b>{t_esc}</b> ({y_esc}) — ⭐️ {r_esc}\n"
                f"   Director: {d_esc} · <a href=\"{u_esc}\">{src}</a>\n"
            )
            btn_lbl = f"🎬 {i}. {opt['title'][:26]} ({opt.get('year', 'N/A')})"
            kb.append([InlineKeyboardButton(btn_lbl, callback_data=f"mreq_pick_opt_{i-1}")])
        lines.append('Select a movie/series to submit your request, or choose "<b>None of these</b>" below:')
        text = "\n".join(lines)
    else:
        text = f"🎬 <b>Request Movie / TV Series:</b> <i>{html.escape(query)}</i>\n\nNo automatic IMDb/Letterboxd matches found. Choose how to submit:"

    kb.append([InlineKeyboardButton("📋 None of these — Send original movie request", callback_data="mreq_send_original")])
    kb.append([InlineKeyboardButton("✍️ Enter Manual Movie Details (Title/Year/Quality)", callback_data="mreq_start_manual")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="req_cancel")])

    if is_edit:
        await target_msg.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
    else:
        await target_msg.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)


async def requestmovie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/requestmovie <title> or /reqmovie <title> — Request a Movie or TV Series."""
    msg = update.effective_message
    if not msg:
        return
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await msg.reply_text(
            "🎬 <b>How to Request a Movie / TV Series:</b>\n"
            "• <code>/requestmovie &lt;movie title&gt; [year]</code>\n"
            "• Or tap <b>✍️ Manual Movie Request</b> below:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Start Manual Movie Request", callback_data="mreq_start_manual")]]),
        )
        return
    await show_movie_request_options(msg, update.effective_user, query, context, is_edit=False)


async def handle_manual_movie_request_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    wiz = context.user_data.get("manual_mreq_wizard")
    if not wiz or not update.message or not update.message.text:
        return False
    txt = update.message.text.strip()
    step = wiz.get("step")

    if step == "title":
        wiz["title"] = txt
        wiz["step"] = "director"
        await update.message.reply_text("🎬 <b>Step 2/4:</b> Enter the <b>Release Year or Director</b> (or <code>Unknown</code>):", parse_mode="HTML")
        return True
    if step == "director":
        wiz["director"] = txt
        wiz["step"] = "quality"
        await update.message.reply_text("🎞 <b>Step 3/4:</b> Enter preferred <b>Resolution / Language</b> (e.g. <code>1080p Dual Audio</code>, <code>720p English</code>):", parse_mode="HTML")
        return True
    if step == "quality":
        wiz["quality"] = txt
        wiz["step"] = "collection"
        await update.message.reply_text("📚 <b>Step 4/4:</b> Enter <b>Franchise / Season</b> (or <code>None</code> if standalone):", parse_mode="HTML")
        return True
    if step == "collection":
        context.user_data.pop("manual_mreq_wizard", None)
        series_val = "" if txt.lower() == "none" else txt
        status_msg = await update.message.reply_text("⏳ Submitting your manual movie request...")
        await _submit_final_request(
            context.bot, update.effective_user, status_msg,
            wiz.get("title", "Unknown Movie"), wiz.get("director", "Unknown"),
            series=series_val, fmt=wiz.get("quality", "1080p"), source="Manual Movie", request_type="Movie/Series",
        )
        return True
    return False


async def movie_request_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    d = q.data
    user = q.from_user

    if d.startswith("mreq_from_search_"):
        await q.answer()
        query = d.replace("mreq_from_search_", "", 1)
        await show_movie_request_options(q.message, user, query, context, is_edit=True)
    elif d.startswith("mreq_pick_opt_"):
        await q.answer("Submitting selected movie...")
        idx = int(d.replace("mreq_pick_opt_", ""))
        opts = context.user_data.get("mreq_candidates", [])
        if 0 <= idx < len(opts):
            o = opts[idx]
            await _submit_final_request(
                context.bot, user, q.message, o["title"], o["author"],
                o.get("series", ""), o.get("format", "1080p"), o.get("source", "IMDb"), o.get("url", ""),
                request_type="Movie/Series",
            )
    elif d == "mreq_send_original":
        await q.answer("Submitting original movie request...")
        raw_q = context.user_data.get("mreq_raw_query") or "Movie Request"
        await _submit_final_request(context.bot, user, q.message, raw_q, "As Requested", "", "Any", "Original Query", "", request_type="Movie/Series")
    elif d == "mreq_start_manual":
        await q.answer()
        context.user_data["manual_mreq_wizard"] = {"step": "title"}
        await q.message.edit_text("🎬 <b>Manual Movie Request — Step 1/4:</b>\nPlease reply with the <b>Movie or TV Series Title</b>:", parse_mode="HTML")
