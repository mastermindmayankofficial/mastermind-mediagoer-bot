from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from modules.ban.ban import get_support_chat_id

# The 10 questions and their correct answers (True = Yes, False = No)
QUIZ_QUESTIONS = [
    ("1. Is casual chatting allowed in the support chat?", False),
    ("2. Can you submit files in this group?", False),
    ("3. Can you request files in this group?", False),
    ("4. Can you search for files in this group?", False),
    ("5. Can you appeal for an unban or check restrictions here?", True),
    ("6. Can you report errors encountered while using the bot?", True),
    ("7. Can you ask for help on how to use the bot?", True),
    ("8. Can you report wrong files here?", True),
    ("9. Can you leave feedback for the bot or owners?", True),
    ("10. Can you submit complaints here?", True),
]

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered when a user clicks 'Contact Support & Appeal' or runs /support.
    Shows the safety disclaimer and button to start the quiz.
    """
    text = (
        "🛡️ **Mastermind Support Center**\n\n"
        "If you need help, you can join our support chat. However, to keep our "
        "support chat safe and protected from unnecessary/irrelevant questions, "
        "spam, chats, and attacks, you must pass a quick verification quiz first."
    )
    
    keyboard = [[InlineKeyboardButton("🚀 Start Verification Quiz", callback_data="support_start_quiz")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def support_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all callback queries related to the support quiz flow."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # Start Quiz
    if data == "support_start_quiz":
        context.user_data["quiz_step"] = 0
        await send_quiz_question(query, context, step=0)

    # Answer handling (format: quiz_ans_yes or quiz_ans_no)
    elif data.startswith("quiz_ans_"):
        user_step = context.user_data.get("quiz_step", 0)
        user_choice = True if data == "quiz_ans_yes" else False
        
        expected_ans = QUIZ_QUESTIONS[user_step][1]
        
        if user_choice == expected_ans:
            # Correct answer! Advance step
            user_step += 1
            context.user_data["quiz_step"] = user_step
            
            if user_step < len(QUIZ_QUESTIONS):
                await send_quiz_question(query, context, step=user_step)
            else:
                # Quiz Completed Successfully! Generate Single-Use Invite Link
                await finalize_quiz_success(query, context)
        else:
            # Wrong answer! Reset quiz immediately
            context.user_data["quiz_step"] = 0
            fail_text = (
                "❌ **Incorrect Answer!**\n\n"
                "You failed one of the screening questions. To protect the support chat, "
                "the quiz has been reset from the beginning.\n\n"
                "Let's try again."
            )
            keyboard = [[InlineKeyboardButton("🔄 Restart Quiz", callback_data="support_start_quiz")]]
            await query.message.edit_text(fail_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def send_quiz_question(query, context, step: int):
    """Sends the current question with Yes/No inline buttons."""
    question_text, _ = QUIZ_QUESTIONS[step]
    text = (
        f"📝 **Support Verification Quiz ({step + 1}/10)**\n\n"
        f"{question_text}"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="quiz_ans_yes"),
            InlineKeyboardButton("❌ No", callback_data="quiz_ans_no")
        ]
    ]
    await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def finalize_quiz_success(query, context):
    """Generates a single-use invite link for the support chat upon passing the quiz."""
    support_chat_id = get_support_chat_id()
    
    if not support_chat_id:
        await query.message.edit_text(
            "✅ **Quiz Passed Successfully!**\n\n"
            "⚠️ Support chat ID is not configured on this bot instance. Please contact the owner.",
            parse_mode="Markdown"
        )
        return

    try:
        # Generate a secure, single-use invite link restricted to 1 member
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=support_chat_id,
            member_limit=1,
            creates_join_request=False
        )
        
        success_text = (
            "🎉 **Congratulations! You passed the verification quiz.**\n\n"
            "Here is your secure, single-use invite link to join the support chat. "
            "Note that this link can only be used once."
        )
        keyboard = [[InlineKeyboardButton("🔗 Join Support Chat", url=invite_link.invite_link)]]
        await query.message.edit_text(success_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    except Exception as e:
        await query.message.edit_text(
            f"✅ **Quiz Passed Successfully!**\n\n"
            f"Could not generate invite link automatically: {e}\n"
            "Please contact the bot administrator directly.",
            parse_mode="Markdown"
        )
