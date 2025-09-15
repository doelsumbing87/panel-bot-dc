# -*- coding: utf-8 -*-
import json
import threading
import time
import os
import random
import re
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import logging
from logging.handlers import RotatingFileHandler

# --- Inisialisasi Awal ---
load_dotenv()
console = Console()

# Flask App Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables
global_config = {}
bot_accounts = {}
channel_handlers = {}
system_logs = []
MAX_LOGS = 1000

# --- Logging Setup ---
def setup_logging():
    """Setup logging for the application."""
    logging.basicConfig(level=logging.INFO)
    handler = RotatingFileHandler('bot.log', maxBytes=10000000, backupCount=5)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s'
    ))
    app.logger.addHandler(handler)

# --- Utility Functions ---
def log_message(title: str, message: str, level: str = "INFO"):
    """Mencetak pesan log ke konsol dan menyimpan untuk web panel."""
    color_map = {
        "SUCCESS": "green", "ERROR": "red", "WARNING": "yellow",
        "WAIT": "cyan", "INFO": "blue"
    }
    color = color_map.get(level.upper(), "white")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    panel_content = f"[b]{timestamp}[/b]\n\n{message}"
    console.print(
        Panel(
            panel_content,
            title=f"[{color}]{title}[/{color}]",
            expand=False,
            border_style=color
        )
    )
    
    log_entry = {
        'timestamp': timestamp, 'title': title, 'message': message,
        'level': level, 'color': color
    }
    system_logs.append(log_entry)
    if len(system_logs) > MAX_LOGS:
        system_logs.pop(0)
    
    socketio.emit('new_log', log_entry)
    
    if level == "ERROR":
        app.logger.error(f"{title}: {message}")
    elif level == "WARNING":
        app.logger.warning(f"{title}: {message}")
    else:
        app.logger.info(f"{title}: {message}")

def clean_discord_mentions(text: str) -> str:
    """Menghapus semua jenis mention dari teks pesan Discord."""
    return re.sub(r'<@!?\d+>|<#\d+>|<@&\d+>|\s+', ' ', text).strip()

def get_api_key(used_keys: set, all_keys: list, cooldown_seconds: int) -> str | None:
    """Mendapatkan Google API key yang tersedia secara acak dan menangani cooldown."""
    available_keys = [key for key in all_keys if key not in used_keys]
    if not available_keys:
        log_message(
            "Cooldown API",
            f"Semua API key sedang dalam masa cooldown. Menunggu {cooldown_seconds // 3600} jam...",
            "WAIT"
        )
        time.sleep(cooldown_seconds)
        used_keys.clear()
        log_message("Cooldown Selesai", "Mencoba kembali dengan semua API key.", "SUCCESS")
        return random.choice(all_keys) if all_keys else None
    return random.choice(available_keys)

def generate_gemini_response(api_key: str, prompt: str) -> str | None:
    """Menghasilkan respons menggunakan Google Gemini Pro."""
    try:
        genai.configure(api_key=api_key)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest", safety_settings=safety_settings)
        response = model.generate_content(prompt)
        
        if response.parts:
            return response.text
        else:
            log_message("Gemini Response", "Respons diblokir oleh filter keamanan atau kosong.", "WARNING")
            return None
            
    except Exception as e:
        log_message("Gemini Error", f"Gagal menghasilkan respons: {str(e)}", "ERROR")
        return None

# --- Bot Logic Classes ---
class LocalMessageManager:
    """Mengelola pesan lokal dengan sistem anti-repeat yang cerdas."""
    def __init__(self, filename: str = "pesan.txt"):
        self.filename = filename
        self.all_messages = self._load_messages()
        self.used_messages = set()
        
    def _load_messages(self) -> list:
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                messages = [line.strip() for line in f if line.strip()]
                if not messages:
                    log_message("Peringatan", f"File {self.filename} kosong.", "WARNING")
                    return []
                log_message("Local Messages", f"Berhasil memuat {len(messages)} pesan dari {self.filename}", "SUCCESS")
                return messages
        except FileNotFoundError:
            log_message("Peringatan", f"File {self.filename} tidak ditemukan.", "WARNING")
            return []
    
    def _calculate_context_similarity(self, message: str, context: str) -> float:
        if not context: return 0.0
        message_words = set(message.lower().split())
        context_words = set(context.lower().split())
        if not message_words or not context_words: return 0.0
        
        intersection = len(message_words.intersection(context_words))
        union = len(message_words.union(context_words))
        jaccard = intersection / union if union > 0 else 0.0
        
        crypto_keywords = {
            'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'defi', 'nft', 
            'trading', 'hodl', 'pump', 'dump', 'moon', 'lambo', 'gem', 'ath', 'dip'
        }
        crypto_bonus = 0.2 if crypto_keywords.intersection(context_words) and crypto_keywords.intersection(message_words) else 0.0
        return min(jaccard + crypto_bonus, 1.0)
    
    def get_smart_message(self, context: str = "") -> str | None:
        if not self.all_messages: return None
        available_messages = [msg for msg in self.all_messages if msg not in self.used_messages]
        
        if not available_messages:
            self.used_messages.clear()
            available_messages = self.all_messages.copy()
        
        if not available_messages: return None
        
        if context:
            scored_messages = sorted(
                [(msg, self._calculate_context_similarity(msg, context)) for msg in available_messages],
                key=lambda x: x[1], reverse=True
            )
            top_messages = scored_messages[:max(1, len(scored_messages) // 3)]
            selected_message = random.choice(top_messages)[0]
        else:
            selected_message = random.choice(available_messages)
        
        self.used_messages.add(selected_message)
        return selected_message
    
    def get_stats(self) -> dict:
        total = len(self.all_messages)
        used = len(self.used_messages)
        return {
            'total_messages': total, 'used_messages': used,
            'available_messages': total - used,
            'usage_rate': used / total if total else 0
        }

class DiscordAccount:
    """Mewakili satu akun Discord (token) dan menangani interaksi API."""
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": self.token, "Content-Type": "application/json"}
        self.status = "offline"
        self.last_activity = None
        self.user_id, self.username = self._get_bot_info()

    def _get_bot_info(self) -> tuple[str, str]:
        try:
            response = requests.get("https://discord.com/api/v9/users/@me", headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            user_id, username = data.get("id", "Unknown"), data.get("username", "Unknown")
            self.status = "online"
            return user_id, username
        except requests.exceptions.RequestException:
            log_message("Auth Gagal", f"Token tidak valid: ...{self.token[-4:]}", "ERROR")
            self.status = "error"
            return "Unknown", "Unknown"

    def send_message(self, channel_id: str, message: str, reply_to_id: str | None = None) -> dict | None:
        if not message: return None
        payload = {'content': message}
        if reply_to_id:
            payload["message_reference"] = {"message_id": reply_to_id}

        try:
            response = requests.post(
                f"https://discord.com/api/v9/channels/{channel_id}/messages",
                json=payload, headers=self.headers, timeout=15
            )
            
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1.0)
                log_message(f"Rate Limited [{self.username}]", f"Menunggu {retry_after:.1f} detik...", "WAIT")
                time.sleep(retry_after)
                return self.send_message(channel_id, message, reply_to_id)
            
            response.raise_for_status()
            self.last_activity = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_message(f"Pesan Terkirim [{self.username}]", f'"{message[:50]}..." ke #{channel_id}', "SUCCESS")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            log_message(f"Gagal Kirim [{self.username}]", f"Error: {str(e)}", "ERROR")
            self.status = "error"
            return None
    
    def delete_message(self, channel_id: str, message_id: str) -> bool:
        """Menghapus sebuah pesan di channel."""
        try:
            response = requests.delete(
                f"https://discord.com/api/v9/channels/{channel_id}/messages/{message_id}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 429: # Rate limit
                retry_after = response.json().get("retry_after", 1.0)
                log_message(f"Rate Limited (Delete) [{self.username}]", f"Menunggu {retry_after:.1f} detik...", "WAIT")
                time.sleep(retry_after)
                return self.delete_message(channel_id, message_id)

            response.raise_for_status()
            log_message(f"Pesan Dihapus [{self.username}]", f"Pesan {message_id} di channel {channel_id} berhasil dihapus.", "INFO")
            return True
        except requests.exceptions.RequestException as e:
            if e.response and e.response.status_code == 404:
                log_message(f"Hapus Pesan Gagal [{self.username}]", f"Pesan {message_id} sudah tidak ada.", "WARNING")
            else:
                log_message(f"Hapus Pesan Gagal [{self.username}]", f"Error: {str(e)}", "ERROR")
            return False

    def get_latest_messages(self, channel_id: str, limit: int = 10) -> list | None:
        try:
            response = requests.get(
                f'https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}',
                headers=self.headers, timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            log_message(f"Gagal Ambil Pesan [{self.username}]", f"Error: {str(e)}", "ERROR")
            return None

    def get_status_info(self) -> dict:
        return {
            'username': self.username, 'user_id': self.user_id,
            'status': self.status, 'last_activity': self.last_activity,
            'token_preview': f"...{self.token[-8:]}" if len(self.token) > 8 else "Invalid"
        }

class ChannelHandler:
    """Mengelola logika untuk satu channel spesifik."""
    def __init__(self, channel_id: str, settings: dict, account: DiscordAccount):
        self.channel_id = channel_id
        self.settings = settings
        self.account = account
        self.processed_ids = set()
        self.message_manager = LocalMessageManager()
        self.is_running = False
        self.thread = None
        # --- LOGIKA BARU UNTUK AUTO-DELETE ---
        self.sent_message_ids = []
        self.auto_delete_enabled = self.settings.get("enable_auto_delete", False)
        self.delete_threshold = self.settings.get("delete_after_messages", 5)

    def start(self):
        if self.is_running: return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        
        if self.settings.get("enable_local_chatter", False):
            self._start_local_chatter()
        
        log_message(f"Handler Started", f"Channel: {self.channel_id} | Account: {self.account.username}", "SUCCESS")

    def stop(self):
        self.is_running = False
        log_message(f"Handler Stopped", f"Channel: {self.channel_id} | Account: {self.account.username}", "WARNING")
    
  
    def _handle_auto_delete(self, sent_message: dict):
        """Menangani logika penghapusan pesan otomatis."""
        if not self.auto_delete_enabled or not sent_message:
            return

        self.sent_message_ids.append(sent_message.get('id'))
        
        if len(self.sent_message_ids) >= self.delete_threshold:
            log_message(f"Auto Delete [{self.account.username}]", f"Batas {self.delete_threshold} pesan tercapai. Menghapus pesan...", "INFO")
            ids_to_delete = self.sent_message_ids.copy()
            self.sent_message_ids.clear()

            for msg_id in ids_to_delete:
                if msg_id:
                    self.account.delete_message(self.channel_id, msg_id)
                    time.sleep(1) 

    def _start_local_chatter(self):
        def chatter_loop():
            while self.is_running:
                try:
                    min_delay = self.settings.get("local_chatter_delay_min", 2700)
                    max_delay = self.settings.get("local_chatter_delay_max", 5400)
                    if min_delay > max_delay: min_delay = max_delay -1
                    delay = random.randint(min_delay, max_delay)
                    
                    for _ in range(delay):
                        if not self.is_running: return
                        time.sleep(1)
                    
                    context_messages = self.account.get_latest_messages(self.channel_id, limit=5)
                    if context_messages:
                        context = " ".join([clean_discord_mentions(m.get('content', '')) for m in context_messages[:3]])
                        message = self.message_manager.get_smart_message(context)
                        if message: 
                            sent_message = self.account.send_message(self.channel_id, message)
                            self._handle_auto_delete(sent_message)
                            
                except Exception as e:
                    log_message(f"Chatter Error [{self.account.username}]", str(e), "ERROR")
                    time.sleep(60)

        threading.Thread(target=chatter_loop, daemon=True).start()

    def _run_loop(self):
        delay_interval = self.settings.get("delay_interval", 15)
        while self.is_running:
            try:
                time.sleep(delay_interval)
                messages = self.account.get_latest_messages(self.channel_id, limit=5)
                if not messages: continue

                last_message = messages[0]
                msg_id, author_id = last_message.get('id'), last_message.get('author', {}).get('id')

                if author_id == self.account.user_id or msg_id in self.processed_ids:
                    continue
                self.processed_ids.add(msg_id)
                
                is_mentioned = any(m['id'] == self.account.user_id for m in last_message.get('mentions', []))
                reply_mode = self.settings.get("reply_mode", "mention")
                
                if not ((reply_mode == "mention" and is_mentioned) or reply_mode == "all"):
                    continue

                content = clean_discord_mentions(last_message.get("content", ""))
                if not content: continue
                self._generate_and_send_reply(messages, last_message, content)
                
            except Exception as e:
                log_message(f"Loop Error [{self.account.username}]", str(e), "ERROR")
                time.sleep(30)

    def _generate_and_send_reply(self, messages, last_message, content):
        api_key = get_api_key(
            global_config.get("used_api_keys", set()),
            global_config.get("google_api_keys", []),
            global_config.get("cooldown_seconds", 86400)
        )
        if not api_key:
            log_message("API Key", "Tidak ada API key yang tersedia.", "WARNING")
            return

        conversation_history = "\n".join(
            [f"- {m.get('author', {}).get('username', 'User')}: {clean_discord_mentions(m.get('content', ''))}" for m in reversed(messages[:3])]
        )
        prompt = f"""
You are a crypto and blockchain influencer, known for being friendly and helpful inside a Discord community.
Your task is to respond to the last message in this conversation.
Answer in English, with a casual and fun Gen-Z style. You never use emoticons.
Emulate the style of the influencer https://x.com/satyaXBT in all aspects.

Here is a brief history of the conversation:
{conversation_history}

Give a relevant response to the last message. Do not repeat the question.
"""
        log_message("Generating Reply", f"Membuat respons untuk: \"{content[:50]}...\"", "INFO")
        ai_response = generate_gemini_response(api_key, prompt)
        
        if ai_response:
            time.sleep(random.randint(2, 5))
            reply_to = last_message.get('id') if self.settings.get("use_reply", True) else None
            sent_message = self.account.send_message(self.channel_id, ai_response, reply_to)
            self._handle_auto_delete(sent_message)
        else:
            log_message("Reply Failed", "Gagal mendapatkan respons dari AI.", "WARNING")

    def get_status_info(self) -> dict:
        return {
            'channel_id': self.channel_id, 'is_running': self.is_running,
            'processed_count': len(self.processed_ids),
            'message_stats': self.message_manager.get_stats()
        }

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    accounts_status = {token: acc.get_status_info() for token, acc in bot_accounts.items()}
    channels_status = {key: h.get_status_info() for key, h in channel_handlers.items()}
    
    return jsonify({
        'accounts': accounts_status, 'channels': channels_status,
        'total_accounts': len(bot_accounts),
        'active_channels': sum(1 for h in channel_handlers.values() if h.is_running),
        'total_logs': len(system_logs)
    })

@app.route('/api/logs')
def get_logs():
    limit = request.args.get('limit', 100, type=int)
    return jsonify(system_logs[-limit:])

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        try:
            with open('config.json', 'w') as f:
                json.dump(request.json, f, indent=4)
            log_message("Config Updated", "Configuration updated via web panel", "INFO")
            return jsonify({'success': True})
        except Exception as e:
            log_message("Config Error", str(e), "ERROR")
            return jsonify({'error': str(e)}), 500
    else: # GET
        try:
            with open('config.json', 'r') as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/messages', methods=['GET', 'POST'])
def handle_messages():
    if request.method == 'POST':
        try:
            messages = request.json.get('messages', [])
            with open('pesan.txt', 'w', encoding='utf-8') as f:
                f.write('\n'.join(m.strip() for m in messages))
            log_message("Messages Updated", f"Updated {len(messages)} messages via web panel", "INFO")
            return jsonify({'success': True})
        except Exception as e:
            log_message("Messages Error", str(e), "ERROR")
            return jsonify({'error': str(e)}), 500
    else: # GET
        try:
            with open('pesan.txt', 'r', encoding='utf-8') as f:
                messages = [line.strip() for line in f if line.strip()]
            return jsonify({'messages': messages})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/add_account', methods=['POST'])
def add_account():
    """Menambahkan akun baru atau channel ke config.json."""
    try:
        data = request.json
        new_token = data.get('token')
        new_channel_id = data.get('channel_id')

        if not new_token or not new_channel_id:
            return jsonify({'error': 'Token and Channel ID are required'}), 400

        with open('config.json', 'r+') as f:
            config = json.load(f)
            
            token_exists = False
            for acc in config.get('accounts', []):
                if acc.get('token') == new_token:
                    if new_channel_id not in acc.get('channels', []):
                        acc['channels'].append(new_channel_id)
                    token_exists = True
                    break
            
            if not token_exists:
                config.setdefault('accounts', []).append({
                    "token": new_token,
                    "channels": [new_channel_id]
                })

            f.seek(0)
            json.dump(config, f, indent=4)
            f.truncate()
        
        log_message("Account Added", "Akun/Channel baru ditambahkan via panel. Merestart bot...", "INFO")
        
        stop_all_handlers()
        time.sleep(1)
        initialize_bot()
        
        return jsonify({'success': True, 'message': 'Account added and bot restarted.'})
        
    except Exception as e:
        log_message("Add Account Error", str(e), "ERROR")
        return jsonify({'error': str(e)}), 500

@app.route('/api/restart')
def restart_bot():
    try:
        stop_all_handlers()
        time.sleep(2)
        initialize_bot()
        return jsonify({'success': True})
    except Exception as e:
        log_message("Restart Error", str(e), "ERROR")
        return jsonify({'error': str(e)}), 500

# --- WebSocket Events ---
@socketio.on('connect')
def handle_connect():
    log_message("Web Client", "New client connected to panel", "INFO")

@socketio.on('disconnect')
def handle_disconnect():
    log_message("Web Client", "Client disconnected from panel", "INFO")

# --- Bot Management Functions ---
def initialize_bot():
    """Initialize bot with current configuration."""
    global global_config, bot_accounts, channel_handlers
    
    google_api_keys = [k.strip() for k in os.getenv('GOOGLE_API_KEYS', '').split(',') if k.strip()]
    if not google_api_keys:
        log_message("Error Kritis", "GOOGLE_API_KEYS tidak ditemukan di .env", "ERROR")
        return False

    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log_message("Config Error", "config.json tidak ditemukan atau rusak. Membuat file default.", "WARNING")
        config = {
            "cooldown_hours": 24,
            "global_settings": {
                "language": "english", "reply_mode": "mention", "use_reply": True,
                "delay_interval": 15, "enable_local_chatter": True,
                "local_chatter_delay_min": 2700, "local_chatter_delay_max": 5400,
                "enable_auto_delete": False, "delete_after_messages": 5
            },
            "accounts": []
        }
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)

    global_config = {
        "google_api_keys": google_api_keys, "used_api_keys": set(),
        "cooldown_seconds": config.get("cooldown_hours", 24) * 3600
    }
    
    bot_accounts.clear()
    stop_all_handlers()
    
    global_settings = config.get("global_settings", {})
    accounts_config = config.get("accounts", [])
    
    for acc_config in accounts_config:
        token = acc_config.get("token")
        channel_ids = acc_config.get("channels", [])
        if not token: continue
            
        account = DiscordAccount(token)
        if account.user_id == "Unknown": continue
        bot_accounts[token] = account
        
        for channel_id in channel_ids:
            if "MASUKKAN" in channel_id or not channel_id.strip(): continue
            handler = ChannelHandler(channel_id, global_settings, account)
            channel_handlers[f"{token}:{channel_id}"] = handler
            handler.start()
            time.sleep(1)

    log_message("Bot Initialized", f"Started {len(bot_accounts)} accounts with {len(channel_handlers)} handlers", "SUCCESS")
    return True

def stop_all_handlers():
    for handler in channel_handlers.values():
        handler.stop()
    channel_handlers.clear()
    log_message("Handlers Stopped", "All channel handlers stopped", "WARNING")

# --- Main Execution ---
if __name__ == "__main__":
    setup_logging()
    log_message("System Starting", "Discord Bot Panel is starting up...", "INFO")
    
    if initialize_bot():
        log_message("System Ready", "Bot and web panel are ready!", "SUCCESS")
    else:
        log_message("System Warning", "Bot initialization failed, but web panel is available", "WARNING")
    
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
