"""
Telegram Bot integration for LocalForge.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import AsyncIterator

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from backend.agent.loop import run_agent
from backend.config import get_config
from backend.db.store import (
    add_message,
    create_conversation,
    get_messages,
)
from backend.models.registry import get_adapter

logger = logging.getLogger(__name__)

# Module-level state
_chat_conv_map: dict[int, str] = {}  # telegram chat_id → conv_id
_pending_confirmations: dict[str, tuple[asyncio.Event, dict]] = {}  # tool_use_id → (event, result_dict)

# Global application instance
_app: Application | None = None


def _is_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot."""
    cfg = get_config()
    if not cfg.telegram.enabled:
        return False
    if not cfg.telegram.allowed_user_ids:
        return True  # Empty list = allow all
    return user_id in cfg.telegram.allowed_user_ids


async def _get_or_create_conv(chat_id: int) -> str:
    """Get existing conversation or create new one for this chat."""
    if chat_id in _chat_conv_map:
        return _chat_conv_map[chat_id]
    
    cfg = get_config()
    model = cfg.telegram.default_model or cfg.default_model
    conv = await create_conversation(model=model, title="Telegram")
    _chat_conv_map[chat_id] = conv["id"]
    return conv["id"]


def _to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram HTML format."""
    # Escape HTML first
    text = html.escape(text)
    
    # Code blocks: ```lang\ncode\n``` → <pre><code>code</code></pre>
    text = re.sub(
        r'```(\w+)?\n(.*?)```',
        lambda m: f'<pre><code>{m.group(2)}</code></pre>',
        text,
        flags=re.DOTALL
    )
    
    # Inline code: `code` → <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # Bold: **text** → <b>text</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    # Italic: *text* → <i>text</i>
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
    
    return text


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split long messages into chunks."""
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    lines = text.split('\n')
    current = ""
    
    for line in lines:
        if len(current) + len(line) + 1 <= max_len:
            current += line + '\n'
        else:
            if current:
                chunks.append(current.rstrip())
            current = line + '\n'
    
    if current:
        chunks.append(current.rstrip())
    
    return chunks


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    chat_id = update.effective_chat.id
    
    if not _is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return
    
    # Clear conversation mapping
    if chat_id in _chat_conv_map:
        del _chat_conv_map[chat_id]
    
    await update.message.reply_text(
        "🤖 <b>LocalForge Bot</b>\n\n"
        "I'm your local AI assistant with access to files, terminal, and web search.\n\n"
        "Just send me a message and I'll help you!\n\n"
        "Commands:\n"
        "/start - Reset and show this message\n"
        "/new - Start a new conversation",
        parse_mode=ParseMode.HTML
    )


async def _handle_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new command."""
    chat_id = update.effective_chat.id
    
    if not _is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return
    
    # Clear conversation mapping
    if chat_id in _chat_conv_map:
        del _chat_conv_map[chat_id]
    
    await update.message.reply_text("🔄 Started new conversation!")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    user = update.effective_user
    if not user or not _is_authorized(user.id):
        return
    
    text = update.message.text
    if not text:
        return
    
    chat_id = update.effective_chat.id
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Get or create conversation
    conv_id = await _get_or_create_conv(chat_id)
    
    # Add user message to conversation
    await add_message(conv_id, "user", text)
    
    # Get conversation history
    stored = await get_messages(conv_id)
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in stored
        if m["role"] in ("user", "assistant")
    ]
    
    # Get model adapter
    cfg = get_config()
    model = cfg.telegram.default_model or cfg.default_model
    adapter = get_adapter(model)
    
    # Send placeholder message
    sent_message = await update.message.reply_text("⏳ Thinking…")
    
    # Run agent and stream response
    full_text = ""
    last_edit = 0
    edit_interval = 1.5  # seconds
    
    try:
        async for event in run_agent(messages, adapter):
            if event.type == "text_delta":
                full_text += event.data["text"]
                
                # Throttle edits
                current_time = asyncio.get_event_loop().time()
                if current_time - last_edit >= edit_interval:
                    truncated = full_text[:4000]
                    if len(full_text) > 4000:
                        truncated += " ⏳"
                    try:
                        await sent_message.edit_text(
                            _to_telegram_html(truncated),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception:
                        pass  # Ignore edit errors
                    last_edit = current_time
            
            elif event.type == "tool_confirmation_needed":
                # Show confirmation inline keyboard
                data = event.data
                tool_use_id = data["tool_use_id"]
                tool_name = data["name"]
                
                # Create event for waiting
                event_obj = asyncio.Event()
                _pending_confirmations[tool_use_id] = (event_obj, {"approved": False})
                
                # Send confirmation message
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Execute", callback_data=f"approve:{conv_id}:{tool_use_id}"),
                        InlineKeyboardButton("❌ Cancel", callback_data=f"reject:{conv_id}:{tool_use_id}"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ <b>Confirmation Required</b>\n\nRunning <code>{tool_name}</code>...",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                
                # Wait for user response (max 30 seconds)
                try:
                    await asyncio.wait_for(event_obj.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass
                
                # Check result
                _, result = _pending_confirmations.pop(tool_use_id, (None, {}))
                approved = result.get("approved", False)
                
                if not approved:
                    await context.bot.send_message(chat_id=chat_id, text="❌ Operation cancelled.")
                    return
        
        # Save assistant message
        if full_text:
            await add_message(
                conv_id,
                "assistant",
                full_text,
                metadata={}
            )
        
        # Send final response
        final_text = full_text[:4096]
        if len(full_text) > 4096:
            final_text += "\n\n<i>(response truncated)</i>"
        
        await sent_message.edit_text(
            _to_telegram_html(final_text),
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.exception("Error handling message")
        await sent_message.edit_text(f"❌ Error: {str(e)}")


async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data:
        return
    
    parts = data.split(":")
    if len(parts) != 3:
        return
    
    action, conv_id, tool_use_id = parts
    
    if tool_use_id in _pending_confirmations:
        event_obj, result = _pending_confirmations[tool_use_id]
        result["approved"] = (action == "approve")
        event_obj.set()
        
        # Update message to show result
        if action == "approve":
            await query.edit_message_text(
                "✅ <b>Approved</b> - Executing…",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                "❌ <b>Cancelled</b>",
                parse_mode=ParseMode.HTML
            )


async def start_telegram_bot():
    """Start the Telegram bot."""
    global _app
    
    cfg = get_config()
    if not cfg.telegram.enabled:
        logger.info("Telegram bot is disabled")
        return
    
    if not cfg.telegram.bot_token:
        logger.warning("Telegram bot token not configured")
        return
    
    logger.info("Starting Telegram bot...")
    
    _app = Application.builder().token(cfg.telegram.bot_token).build()
    
    # Register handlers
    _app.add_handler(CommandHandler("start", _handle_start))
    _app.add_handler(CommandHandler("new", _handle_new))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    _app.add_handler(CallbackQueryHandler(_handle_callback))
    
    await _app.run_polling(drop_pending_updates=True)
    logger.info("Telegram bot started")


async def stop_telegram_bot():
    """Stop the Telegram bot."""
    global _app
    
    if _app:
        logger.info("Stopping Telegram bot...")
        await _app.stop()
        _app = None
        logger.info("Telegram bot stopped")
