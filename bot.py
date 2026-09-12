import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import io

# লগিং
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভ্যারিয়েবল
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HF_API_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"

# এরর চেক
if not HF_API_TOKEN or not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ HF_API_TOKEN বা TELEGRAM_BOT_TOKEN সেট করো")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """স্টার্ট কমান্ড"""
    await update.message.reply_text(
        "🎨 **ফ্রি AI ইমেজ জেনারেটর বট**\n\n"
        "কিভাবে ব্যবহার করবে:\n"
        "যেকোনো ডিসক্রিপশন লিখো, আমি ইমেজ বানাব।\n\n"
        "**উদাহরণ:**\n"
        "• একটি নীল আকাশ পাহাড়ের উপর\n"
        "• ডিজিটাল আর্ট, মহাকাশ, স্টার\n"
        "• একটি বিড়াল, ফটোগ্রাফি, HD\n\n"
        "⏳ প্রতিটি ইমেজ ১০-৩০ সেকেন্ড\n"
        "📊 ফ্রি: ৩০০ ইমেজ/মাস\n\n"
        "/help - আরো তথ্য",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাহায্য"""
    await update.message.reply_text(
        "**কমান্ড:**\n"
        "/start - শুরু\n"
        "/help - এই মেসেজ\n"
        "/status - বট স্ট্যাটাস\n\n"
        "**টিপস:**\n"
        "• ডিটেইল ডিসক্রিপশন লিখো\n"
        "• স্টাইল মেনশন করো (photography, digital art, etc)\n"
        "• কোয়ালিটি কোয়ার্ড ব্যবহার করো (HD, 4K, high quality)",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """স্ট্যাটাস"""
    await update.message.reply_text(
        "✅ বট **অনলাইন** এবং কাজ করছে\n"
        "📡 Render এ হোস্টেড\n"
        "🎨 Flux.1-schnell মডেল\n"
        "🔗 Hugging Face API",
        parse_mode="Markdown"
    )

async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ইমেজ জেনারেশন"""
    user_prompt = update.message.text
    user_id = update.message.from_user.id
    
    logger.info(f"ইউজার {user_id}: {user_prompt}")
    
    # লোডিং মেসেজ
    loading_msg = await update.message.reply_text(
        "⏳ জেনারেট করছি...\n\n"
        f"প্রম্পট: _{user_prompt}_",
        parse_mode="Markdown"
    )
    
    try:
        # Hugging Face API
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        payload = {"inputs": user_prompt}
        
        response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=120)
        
        # এরর হ্যান্ডলিং
        if response.status_code != 200:
            error_text = response.text[:200] if response.text else "Unknown error"
            await loading_msg.edit_text(
                f"❌ **API এরর {response.status_code}**\n\n"
                f"সম্ভাব্য কারণ:\n"
                f"• টোকেন ইনভ্যালিড\n"
                f"• মাসিক কোটা শেষ\n"
                f"• নেটওয়ার্ক ইস্যু\n\n"
                f"বিস্তারিত: `{error_text}`",
                parse_mode="Markdown"
            )
            logger.error(f"API এরর: {error_text}")
            return
        
        # ইমেজ পাঠাও
        image_bytes = io.BytesIO(response.content)
        await loading_msg.delete()
        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"✅ জেনারেট করা হয়েছে\n\n_'{user_prompt}'_",
            parse_mode="Markdown"
        )
        logger.info(f"ইমেজ সফল (ইউজার {user_id})")
        
    except requests.exceptions.Timeout:
        await loading_msg.edit_text("⏱️ **টাইমআউট** — আবার চেষ্টা করো")
    except Exception as e:
        logger.error(f"এরর: {e}")
        await loading_msg.edit_text(
            f"❌ **এরর**\n\n`{str(e)[:100]}`",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাধারণ মেসেজ হ্যান্ডল"""
    await generate_image(update, context)

def main():
    """মেইন লুপ"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # হ্যান্ডলার
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 বট শুরু হচ্ছে...")
    app.run_polling()

if __name__ == '__main__':
    main()
