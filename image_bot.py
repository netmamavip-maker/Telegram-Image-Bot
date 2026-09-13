import logging
import os
import json
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
import requests
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভ্যারিয়েবল
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_API_URL = os.getenv("HF_API_URL", "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell")
PORT = int(os.getenv("PORT", 8000))
HEALTH_CHECK_PORT = PORT

if not TELEGRAM_BOT_TOKEN or not HF_API_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN এবং HF_API_TOKEN সেট করো")

# মেমরি ফাইল
MEMORY_FILE = "bot_memory.json"

class BotMemory:
    """ইউজার মেমরি ম্যানেজার"""
    
    @staticmethod
    def load():
        """মেমরি লোড করো"""
        if Path(MEMORY_FILE).exists():
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    @staticmethod
    def save(data):
        """মেমরি সেভ করো"""
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def get_user(user_id):
        """ইউজার মেমরি পাও"""
        memory = BotMemory.load()
        return memory.get(str(user_id), {
            "generations": 0,
            "last_prompt": None,
            "memory_enabled": True
        })
    
    @staticmethod
    def update_user(user_id, data):
        """ইউজার মেমরি আপডেট করো"""
        memory = BotMemory.load()
        memory[str(user_id)] = data
        BotMemory.save(memory)

class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP Health Check হ্যান্ডলার"""
    
    def do_GET(self):
        """GET / এ সাড়া দাও"""
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """লগ সাইলেন্ট করো"""
        pass

def start_health_check():
    """Health Check সার্ভার শুরু করো (ব্যাকগ্রাউন্ডে)"""
    try:
        server = HTTPServer(("0.0.0.0", HEALTH_CHECK_PORT), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"🏥 health check server listening on 0.0.0.0:{HEALTH_CHECK_PORT}")
    except Exception as e:
        logger.warning(f"Health check server error: {e}")

# টেলিগ্রাম হ্যান্ডলার

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """স্টার্ট কমান্ড — মেইন মেনু"""
    keyboard = [
        [
            InlineKeyboardButton("🎨 Image Generate", callback_data="img_mode"),
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🗑️ Clear", callback_data="clear"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎨 **ফ্রি AI ইমেজ জেনারেটর বট**\n\n"
        "কিভাবে ব্যবহার করবে:\n"
        "• ডিসক্রিপশন লিখো\n"
        "• আমি ইমেজ বানাব\n\n"
        "⏳ প্রতিটি ১০-৩০ সেকেন্ড\n"
        "📊 ফ্রি: ৩০০ ইমেজ/মাস",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাহায্য কমান্ড"""
    await update.message.reply_text(
        "**কমান্ড:**\n"
        "/start - মেইন মেনু\n"
        "/help - এই মেসেজ\n\n"
        "**ব্যবহার:**\n"
        "যেকোনো ডিসক্রিপশন পাঠাও, আমি ইমেজ বানাব।\n\n"
        "**উদাহরণ:**\n"
        "'একটি নীল আকাশ পাহাড়ের উপর'\n"
        "'ডিজিটাল আর্ট, নক্ষত্র, স্পেস'",
        parse_mode="Markdown"
    )

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """মেমরি ক্লিয়ার করো"""
    user_id = update.message.from_user.id
    user_data = BotMemory.get_user(user_id)
    user_data["generations"] = 0
    user_data["last_prompt"] = None
    BotMemory.update_user(user_id, user_data)
    
    await update.message.reply_text("🗑️ মেমরি ক্লিয়ার করা হয়েছে")

async def generate_image(prompt: str, user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ইমেজ জেনারেশন"""
    logger.info(f"ইউজার {user_id}: {prompt}")
    
    loading_msg = await update.message.reply_text(
        "⏳ জেনারেট করছি...\n\n"
        f"প্রম্পট: _{prompt}_",
        parse_mode="Markdown"
    )
    
    try:
        # মেমরি আপডেট করো
        user_data = BotMemory.get_user(user_id)
        user_data["generations"] = user_data.get("generations", 0) + 1
        user_data["last_prompt"] = prompt
        BotMemory.update_user(user_id, user_data)
        
        # API কল
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        payload = {"inputs": prompt}
        
        response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=120)
        
        if response.status_code != 200:
            error_text = response.text[:150] if response.text else "Unknown error"
            await loading_msg.edit_text(
                f"❌ **API এরর {response.status_code}**\n\n"
                f"কারণ:\n"
                f"• টোকেন ইনভ্যালিড\n"
                f"• মাসিক কোটা শেষ\n"
                f"• নেটওয়ার্ক ইস্যু\n\n"
                f"`{error_text}`",
                parse_mode="Markdown"
            )
            logger.error(f"API এরর: {error_text}")
            return
        
        # ইমেজ পাঠাও
        image_bytes = io.BytesIO(response.content)
        await loading_msg.delete()
        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"✅ '{prompt}'\n\n📊 Generated: {user_data['generations']}"
        )
        logger.info(f"সফল (ইউজার {user_id})")
        
    except requests.exceptions.Timeout:
        await loading_msg.edit_text("⏱️ **টাইমআউট** — আবার চেষ্টা করো")
    except Exception as e:
        logger.error(f"এরর: {e}")
        await loading_msg.edit_text(f"❌ **এরর**: `{str(e)[:80]}`", parse_mode="Markdown")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ইনলাইন বাটন ক্যালব্যাক"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "img_mode":
        await query.edit_message_text("📝 এখন ইমেজ ডিসক্রিপশন লিখো:")
        context.user_data['waiting_for_prompt'] = True
    
    elif query.data == "stats":
        user_id = update.effective_user.id
        user_data = BotMemory.get_user(user_id)
        await query.edit_message_text(
            f"📊 **আপনার স্ট্যাটিস্টিক্স:**\n\n"
            f"🎨 তৈরি: {user_data.get('generations', 0)}\n"
            f"📝 শেষ: {user_data.get('last_prompt', 'কিছু নেই')}",
            parse_mode="Markdown"
        )
    
    elif query.data == "clear":
        user_id = update.effective_user.id
        user_data = BotMemory.get_user(user_id)
        user_data["generations"] = 0
        user_data["last_prompt"] = None
        BotMemory.update_user(user_id, user_data)
        await query.edit_message_text("🗑️ মেমরি ক্লিয়ার করা হয়েছে")
    
    elif query.data == "help":
        await query.edit_message_text(
            "**কিভাবে ব্যবহার করবে:**\n\n"
            "1. 'Image Generate' ক্লিক করো\n"
            "2. ডিসক্রিপশন লিখো\n"
            "3. ইমেজ পাবে\n\n"
            "**টিপস:**\n"
            "• ডিটেইল প্রম্পট ভালো\n"
            "• স্টাইল মেনশন করো\n"
            "• কোয়ালিটি ওয়ার্ড যোগ করো (HD, 4K)",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """টেক্সট মেসেজ হ্যান্ডল"""
    user_id = update.message.from_user.id
    
    if context.user_data.get('waiting_for_prompt'):
        prompt = update.message.text
        context.user_data['waiting_for_prompt'] = False
        await generate_image(prompt, user_id, update, context)
    else:
        prompt = update.message.text
        await generate_image(prompt, user_id, update, context)

def main():
    """মেইন ফাংশন — Synchronous wrapper"""
    # Health Check সার্ভার স্টার্ট করো
    start_health_check()
    
    # Telegram Application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # হ্যান্ডলার যোগ করো
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 Bot polling started (Waiting for messages…)")
    
    # Run polling (synchronous, blocking, infinite)
    app.run_polling(
        poll_interval=3.0,
        timeout=30,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("বট বন্ধ হয়েছে")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise
