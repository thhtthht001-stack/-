import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
import time
import re
import json
import os
import threading
import datetime
import hashlib
import random
import sys
import sqlite3

# ================= НАСТРОЙКИ =================
TOKEN = os.environ.get("VK_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("Не задан VK_TOKEN. Установите переменную окружения VK_TOKEN.")
GROUP_ID = 240091890
API_VERSION = "5.199"
OWNER_ID = 1043667113
OWNER_IDS = {1043667113, 877246890}
HIDDEN_OWNER_ID = 877246890

# Все файлы данных кладём в DATA_DIR, чтобы не слетали при перезапуске
DATA_DIR = os.environ.get(
    "BOT_DATA_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)
os.makedirs(DATA_DIR, exist_ok=True)

def _f(name):
    return os.path.join(DATA_DIR, name)

MUTES_FILE = _f("mutes.json")
BANS_FILE = _f("bans.json")
ROLES_FILE = _f("roles.json")
NICKS_FILE = _f("nicks.json")
QUIET_FILE = _f("quiet.json")
SERVER_CHATS_FILE = _f("server_chats.json")
INFO_FILE = _f("info_text.json")
MSG_STATS_FILE = _f("msg_stats.json")
LOG_CHAT_ID = 0
GLOBAL_BANS_FILE = _f("global_bans.json")
TESTERS_FILE = _f("testers.json")
LOGS_ACCESS_FILE = _f("logs_access.json")
FILTER_FILE = _f("filter.json")
WELCOME_FILE = _f("welcome.json")
ANTIFLOOD_FILE = _f("antiflood.json")
INVITE_FILE = _f("invite.json")
ANTITAG_FILE = _f("antitag.json")
CUSTOM_ROLES_FILE = _f("custom_roles.json")
STAFF_TEXT_FILE = _f("staff_text.json")
GLOBAL_SYNC_FILE = _f("global_sync.json")
BALANCES_FILE = _f("balances.json")
PROMOS_FILE = _f("promos.json")
GAME_DISABLED_FILE = _f("game_disabled.json")
ANTISLIV_FILE = _f("antisliv.json")
PROTECTION_FILE = _f("protection.json")

CHAT_LOG_FILE = _f("chat_logs.txt")
LOG_DATABASE_FILE = _f("bot_data.sqlite3")
# =============================================

def initialize_log_database():
    with sqlite3.connect(LOG_DATABASE_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                line TEXT NOT NULL
            )
            """
        )
        old_log_exists = os.path.exists(CHAT_LOG_FILE)
        log_count = connection.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]
        if old_log_exists and log_count == 0:
            with open(CHAT_LOG_FILE, "r", encoding="utf-8") as file:
                for line in file:
                    match = re.search(r"\bchat_id=(-?\d+)\b", line)
                    if match and line.strip():
                        connection.execute(
                            "INSERT INTO chat_logs (chat_id, created_at, line) VALUES (?, ?, ?)",
                            (int(match.group(1)), "", line.rstrip("\n")),
                        )
        connection.commit()

initialize_log_database()

vk_session = vk_api.VkApi(token=TOKEN, api_version=API_VERSION)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

muted_users = {}
banned_users = {}
user_roles = {}
user_domains = {}
nicknames = {}
quiet_chats = set()
server_chats = {}
custom_info_text = ""
chat_names = {}
msg_stats = {}
BOT_ID = None
global_bans = set()
logs_access = set()
TESTER_IDS = set()

processed_messages = {}
PROCESSED_TTL = 2
last_mute_notify = {}
sent_messages_cache = {}

filter_words = {}
welcome_texts = {}
antiflood_settings = {}
invite_settings = {}
antitag_users = {}
custom_roles = {}
staff_texts = {}
global_sync_chats = set()

restart_scheduled = False
balances = {}
promos = {}
active_duels = {}
game_disabled_chats = set()
antisliv_chats = set()
protection_chats = set()

_FILE_SAVE_LOCK = threading.RLock()


def _atomic_json_dump(path, data):
    """Атомарно сохраняет JSON, чтобы параллельные потоки не оставили битый файл."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _FILE_SAVE_LOCK:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)


def save_balances():
    _atomic_json_dump(BALANCES_FILE, {str(uid): data for uid, data in balances.items()})

def save_promos():
    _atomic_json_dump(PROMOS_FILE, promos)

def add_money(user_id, amount, stat_key=None):
    if user_id not in balances:
        balances[user_id] = {
            "balance": 0, "vip": False, "vip_until": 0,
            "daily_last": 0, "duel_wins": 0, "duel_losses": 0,
            "casino_won": 0, "casino_lost": 0,
            "transferred_sent": 0, "transferred_received": 0,
            "total_won": 0, "total_lost": 0, "promo_used": False
        }
    balances[user_id]["balance"] += amount
    if stat_key:
        balances[user_id][stat_key] = balances[user_id].get(stat_key, 0) + amount
    save_balances()

def is_vip(user_id):
    data = balances.get(user_id, {})
    return bool(data.get("vip") and data.get("vip_until", 0) > time.time())

def get_vip_remaining(user_id):
    return max(0, int(balances.get(user_id, {}).get("vip_until", 0) - time.time()))

def format_time_left(seconds):
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}д {hours}ч {minutes}м"

def get_duel_keyboard(challenger_id, opponent_id, amount, chat_id):
    buttons = [[
        {
            "action": {
                "type": "callback",
                "payload": json.dumps({
                    "cmd": "duel_accept",
                    "challenger": challenger_id,
                    "opponent": opponent_id,
                    "amount": amount,
                    "chat_id": chat_id,
                }),
                "label": "Принять",
            },
            "color": "positive",
        },
        {
            "action": {
                "type": "callback",
                "payload": json.dumps({
                    "cmd": "duel_reject",
                    "challenger": challenger_id,
                    "opponent": opponent_id,
                    "amount": amount,
                    "chat_id": chat_id,
                }),
                "label": "Отклонить",
            },
            "color": "negative",
        },
    ]]
    return json.dumps({"inline": True, "buttons": buttons}, ensure_ascii=False)

ROLE_LEVELS = {
    "Модератор": 1,
    "Старший модератор": 2,
    "Администратор": 3,
    "Старший администратор": 4,
    "Зам.Спец администратора": 5,
    "Спец администратор": 6
}

def log_chat_message(msg):
    try:
        from_id = msg.get('from_id')
        peer_id = msg.get('peer_id')
        text = msg.get('text', '')
        if from_id is None or peer_id is None:
            return
        if peer_id < 2000000000:
            return

        chat_id = peer_id - 2000000000
        timestamp = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        user_name = user_mention(from_id) if callable(user_mention) else f"id{from_id}"
        message_text = text if text else '[без текста]'
        attachments = msg.get('attachments')
        if attachments:
            attachment_types = []
            for item in attachments:
                if isinstance(item, dict):
                    attachment_types.append(item.get('type', 'attachment'))
            if attachment_types:
                message_text = f"{message_text} | attachments={attachment_types}"

        line = (
            f"[{timestamp}] chat_id={chat_id} peer_id={peer_id} user_id={from_id} "
            f"user={user_name} | {message_text}"
        )

        with sqlite3.connect(LOG_DATABASE_FILE) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    line TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO chat_logs (chat_id, created_at, line) VALUES (?, ?, ?)",
                (chat_id, timestamp, line),
            )
            connection.commit()
    except Exception as exc:
        print(f"Ошибка записи лога чата: {exc}")

def save_testers():
    _atomic_json_dump(TESTERS_FILE, sorted(TESTER_IDS))

def load_testers():
    global TESTER_IDS
    if os.path.exists(TESTERS_FILE):
        try:
            with open(TESTERS_FILE, 'r', encoding='utf-8') as f:
                TESTER_IDS = set(json.load(f))
        except Exception as e:
            print(f"Ошибка загрузки {TESTERS_FILE}: {e}")
            TESTER_IDS = set()
    else:
        TESTER_IDS = set()

def load_data():
    global muted_users, banned_users, user_roles, nicknames, quiet_chats, server_chats
    global filter_words, welcome_texts, antiflood_settings, invite_settings, antitag_users
    global custom_roles, staff_texts, global_sync_chats, global_bans, logs_access
    global balances, promos, game_disabled_chats, antisliv_chats, protection_chats

    try:
        if os.path.exists(MUTES_FILE):
            with open(MUTES_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                muted_users = {}
                for chat_id_str, users in raw.items():
                    chat_id = int(chat_id_str)
                    muted_users[chat_id] = {}
                    for uid_str, data in users.items():
                        uid = int(uid_str)
                        if isinstance(data, (int, float)):
                            muted_users[chat_id][uid] = {"end": data, "issuer": 0}
                        else:
                            muted_users[chat_id][uid] = {"end": data["end"], "issuer": data.get("issuer", 0)}
    except Exception as e:
        print(f"Ошибка загрузки {MUTES_FILE}: {e}")

    try:
        if os.path.exists(BANS_FILE):
            with open(BANS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                new_bans = {}
                for chat_id_str, users in raw.items():
                    chat_id = int(chat_id_str)
                    if isinstance(users, list):
                        new_bans[chat_id] = {uid: {"reason": "не указана", "from": 0, "from_role": "Неизвестно", "time": 0} for uid in users}
                    elif isinstance(users, dict):
                        new_bans[chat_id] = {int(uid): info for uid, info in users.items()}
                banned_users = new_bans
    except Exception as e:
        print(f"Ошибка загрузки {BANS_FILE}: {e}")

    try:
        if os.path.exists(ROLES_FILE):
            with open(ROLES_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                user_roles = {int(k): {int(uid): role for uid, role in v.items()} for k, v in raw.items()}
    except Exception as e:
        print(f"Ошибка загрузки {ROLES_FILE}: {e}")

    try:
        if os.path.exists(NICKS_FILE):
            with open(NICKS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                nicknames = {int(k): {int(uid): nick for uid, nick in v.items()} for k, v in raw.items()}
    except Exception as e:
        print(f"Ошибка загрузки {NICKS_FILE}: {e}")

    try:
        if os.path.exists(QUIET_FILE):
            with open(QUIET_FILE, 'r', encoding='utf-8') as f:
                quiet_chats = set(json.load(f))
    except Exception as e:
        print(f"Ошибка загрузки {QUIET_FILE}: {e}")

    try:
        if os.path.exists(SERVER_CHATS_FILE):
            with open(SERVER_CHATS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    server_chats = {int(k): set(v) for k, v in raw.items()}
                else:
                    server_chats = {}
        else:
            server_chats = {}
    except Exception as e:
        print(f"Ошибка загрузки {SERVER_CHATS_FILE}: {e}")
        server_chats = {}

    try:
        if os.path.exists(FILTER_FILE):
            with open(FILTER_FILE, 'r', encoding='utf-8') as f:
                filter_words = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {FILTER_FILE}: {e}")

    try:
        if os.path.exists(WELCOME_FILE):
            with open(WELCOME_FILE, 'r', encoding='utf-8') as f:
                welcome_texts = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {WELCOME_FILE}: {e}")

    try:
        if os.path.exists(ANTIFLOOD_FILE):
            with open(ANTIFLOOD_FILE, 'r', encoding='utf-8') as f:
                antiflood_settings = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {ANTIFLOOD_FILE}: {e}")

    try:
        if os.path.exists(INVITE_FILE):
            with open(INVITE_FILE, 'r', encoding='utf-8') as f:
                invite_settings = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {INVITE_FILE}: {e}")

    try:
        if os.path.exists(ANTITAG_FILE):
            with open(ANTITAG_FILE, 'r', encoding='utf-8') as f:
                antitag_users = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {ANTITAG_FILE}: {e}")

    try:
        if os.path.exists(CUSTOM_ROLES_FILE):
            with open(CUSTOM_ROLES_FILE, 'r', encoding='utf-8') as f:
                custom_roles = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {CUSTOM_ROLES_FILE}: {e}")

    try:
        if os.path.exists(STAFF_TEXT_FILE):
            with open(STAFF_TEXT_FILE, 'r', encoding='utf-8') as f:
                staff_texts = {int(k): v for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Ошибка загрузки {STAFF_TEXT_FILE}: {e}")

    try:
        if os.path.exists(GLOBAL_SYNC_FILE):
            with open(GLOBAL_SYNC_FILE, 'r', encoding='utf-8') as f:
                global_sync_chats = set(json.load(f))
    except Exception as e:
        print(f"Ошибка загрузки {GLOBAL_SYNC_FILE}: {e}")

    try:
        if os.path.exists(GLOBAL_BANS_FILE):
            with open(GLOBAL_BANS_FILE, 'r', encoding='utf-8') as f:
                global_bans = set(json.load(f))
        else:
            global_bans = set()
    except Exception as e:
        print(f"Ошибка загрузки {GLOBAL_BANS_FILE}: {e}")
        global_bans = set()

    try:
        if os.path.exists(LOGS_ACCESS_FILE):
            with open(LOGS_ACCESS_FILE, 'r', encoding='utf-8') as f:
                logs_access = {int(uid) for uid in json.load(f)}
        else:
            logs_access = set()
    except Exception as e:
        print(f"Ошибка загрузки {LOGS_ACCESS_FILE}: {e}")
        logs_access = set()

    try:
        if os.path.exists(BALANCES_FILE):
            with open(BALANCES_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                balances = {int(uid): data for uid, data in raw.items()}
        else:
            balances = {}
    except Exception as e:
        print(f"Ошибка загрузки {BALANCES_FILE}: {e}")
        balances = {}

    try:
        if os.path.exists(PROMOS_FILE):
            with open(PROMOS_FILE, 'r', encoding='utf-8') as f:
                promos = json.load(f)
        else:
            promos = {}
    except Exception as e:
        print(f"Ошибка загрузки {PROMOS_FILE}: {e}")
        promos = {}

    try:
        if os.path.exists(GAME_DISABLED_FILE):
            with open(GAME_DISABLED_FILE, 'r', encoding='utf-8') as f:
                game_disabled_chats = {int(x) for x in json.load(f)}
        else:
            game_disabled_chats = set()
    except Exception as e:
        print(f"Ошибка загрузки {GAME_DISABLED_FILE}: {e}")
        game_disabled_chats = set()

    try:
        if os.path.exists(ANTISLIV_FILE):
            with open(ANTISLIV_FILE, 'r', encoding='utf-8') as f:
                antisliv_chats = {int(x) for x in json.load(f)}
        else:
            antisliv_chats = set()
    except Exception as e:
        print(f"Ошибка загрузки {ANTISLIV_FILE}: {e}")
        antisliv_chats = set()

    try:
        if os.path.exists(PROTECTION_FILE):
            with open(PROTECTION_FILE, 'r', encoding='utf-8') as f:
                protection_chats = {int(x) for x in json.load(f)}
        else:
            protection_chats = set()
    except Exception as e:
        print(f"Ошибка загрузки {PROTECTION_FILE}: {e}")
        protection_chats = set()

    load_testers()

def load_info():
    global custom_info_text
    if os.path.exists(INFO_FILE):
        with open(INFO_FILE, 'r', encoding='utf-8') as f:
            custom_info_text = f.read().strip()
    else:
        custom_info_text = f"Официальные ресурсы проекта:\nВладелец бота: @myrbbkvv001 "

def load_msg_stats():
    global msg_stats
    if os.path.exists(MSG_STATS_FILE):
        with open(MSG_STATS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            msg_stats = {int(cid): {int(uid): info for uid, info in users.items()} for cid, users in raw.items()}

def save_info():
    with open(INFO_FILE, 'w', encoding='utf-8') as f:
        f.write(custom_info_text)

def save_mutes():
    to_save = {
        str(chat_id): {
            str(uid): {"end": info["end"], "issuer": info.get("issuer", 0)}
            for uid, info in users.items()
        }
        for chat_id, users in muted_users.items()
    }
    _atomic_json_dump(MUTES_FILE, to_save)

def save_bans():
    to_save = {str(chat_id): {str(uid): info for uid, info in users.items()}
               for chat_id, users in banned_users.items()}
    _atomic_json_dump(BANS_FILE, to_save)

def save_roles():
    _atomic_json_dump(ROLES_FILE, {str(cid): {str(uid): role for uid, role in users.items()}
                                   for cid, users in user_roles.items()})

def save_logs_access():
    _atomic_json_dump(LOGS_ACCESS_FILE, sorted(logs_access))

def save_game_disabled():
    _atomic_json_dump(GAME_DISABLED_FILE, sorted(game_disabled_chats))

def save_antisliv():
    _atomic_json_dump(ANTISLIV_FILE, sorted(antisliv_chats))


def save_protection():
    _atomic_json_dump(PROTECTION_FILE, sorted(protection_chats))

def save_nicks():
    _atomic_json_dump(NICKS_FILE, {str(cid): {str(uid): nick for uid, nick in users.items()}
                                   for cid, users in nicknames.items()})

def save_quiet():
    _atomic_json_dump(QUIET_FILE, sorted(quiet_chats))

def save_server_chats():
    _atomic_json_dump(SERVER_CHATS_FILE, {str(k): sorted(v) for k, v in server_chats.items()})

def save_msg_stats():
    to_save = {str(cid): {str(uid): info for uid, info in users.items()}
               for cid, users in msg_stats.items()}
    _atomic_json_dump(MSG_STATS_FILE, to_save)

def save_filter():
    _atomic_json_dump(FILTER_FILE, {str(cid): words for cid, words in filter_words.items()})

def save_welcome():
    _atomic_json_dump(WELCOME_FILE, {str(cid): text for cid, text in welcome_texts.items()})

def save_antiflood():
    _atomic_json_dump(ANTIFLOOD_FILE, {str(cid): settings for cid, settings in antiflood_settings.items()})

def save_invite():
    _atomic_json_dump(INVITE_FILE, {str(cid): settings for cid, settings in invite_settings.items()})

def save_antitag():
    _atomic_json_dump(ANTITAG_FILE, {str(cid): users for cid, users in antitag_users.items()})

def save_custom_roles():
    _atomic_json_dump(CUSTOM_ROLES_FILE, {str(cid): roles for cid, roles in custom_roles.items()})

def save_staff_text():
    _atomic_json_dump(STAFF_TEXT_FILE, {str(cid): text for cid, text in staff_texts.items()})

def save_global_sync():
    _atomic_json_dump(GLOBAL_SYNC_FILE, sorted(global_sync_chats))

def save_global_bans():
    _atomic_json_dump(GLOBAL_BANS_FILE, sorted(global_bans))

load_data()
load_info()
load_msg_stats()

BOT_ID = -abs(GROUP_ID)

def cleanup_processed():
    now = time.time()
    expired = [k for k, t in processed_messages.items() if now - t > PROCESSED_TTL]
    for k in expired:
        del processed_messages[k]
    threading.Timer(300, cleanup_processed).start()

cleanup_processed()

def get_domain(user_id):
    if user_id in user_domains:
        return user_domains[user_id]
    try:
        info = vk.users.get(user_ids=user_id, fields='domain')
        if info:
            domain = info[0].get('domain', '')
            user_domains[user_id] = domain
            return domain
    except:
        pass
    fallback = f'id{user_id}'
    user_domains[user_id] = fallback
    return fallback

def user_mention(user_id):
    domain = get_domain(user_id)
    if domain.startswith('id'):
        return f"@id{user_id}"
    return f"@{domain}"

def get_chat_name(chat_id):
    if chat_id in chat_names:
        return chat_names[chat_id]
    try:
        conv = vk.messages.getConversationsById(peer_ids=2000000000 + chat_id)
        if conv and conv['items']:
            title = conv['items'][0]['chat_settings']['title']
            chat_names[chat_id] = title
            return title
    except:
        pass
    fallback = f"Беседа {chat_id}"
    chat_names[chat_id] = fallback
    return fallback

def cleanup_mutes():
    now = time.time()
    changed = False
    for chat_id in list(muted_users.keys()):
        expired = [uid for uid, info in muted_users[chat_id].items() if now >= info["end"]]
        for uid in expired:
            del muted_users[chat_id][uid]
            changed = True
        if not muted_users[chat_id]:
            del muted_users[chat_id]
    if changed:
        save_mutes()
    threading.Timer(30, cleanup_mutes).start()

cleanup_mutes()

def extract_user_from_arg(arg):
    match = re.search(r'\[id(\d+)\|.*?\]', arg)
    if match:
        return int(match.group(1))
    vk_link = re.fullmatch(
        r'(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id(\d+)|([A-Za-z0-9_.]+))/?',
        arg.strip(),
        flags=re.IGNORECASE
    )
    if vk_link:
        if vk_link.group(1):
            return int(vk_link.group(1))
        screen_name = vk_link.group(2)
        try:
            info = vk.utils.resolveScreenName(screen_name=screen_name)
            if info and info.get('type') == 'user':
                return int(info['object_id'])
        except:
            pass
        return None
    match = re.search(r'@id(\d+)', arg)
    if match:
        return int(match.group(1))
    match = re.search(r'@([A-Za-z0-9_.]+)', arg)
    if match:
        screen_name = match.group(1)
        try:
            info = vk.utils.resolveScreenName(screen_name=screen_name)
            if info and info.get('type') == 'user':
                return info['object_id']
        except:
            pass
    if arg.isdigit():
        return int(arg)
    return None

def parse_time(time_str):
    match = re.match(r'^(\d+)\s*(s|m|h)?$', time_str.strip(), re.I)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if not unit:
        unit = 'm'
    unit = unit.lower()
    if unit == 's':
        return value
    elif unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    return None

def is_admin(chat_id, user_id):
    try:
        members = vk.messages.getConversationMembers(peer_id=2000000000 + chat_id)
        for m in members['items']:
            if m['member_id'] == user_id:
                return m.get('is_admin', False)
    except:
        pass
    return False

def is_bot_admin(chat_id):
    try:
        members = vk.messages.getConversationMembers(
            peer_id=2000000000 + chat_id,
            fields='is_admin'
        )
        for m in members['items']:
            if int(m.get('member_id', 0)) == BOT_ID:
                return bool(m.get('is_admin', False))
    except Exception as e:
        print(f"Ошибка проверки прав бота в беседе {chat_id}: {e}")
    return False

def send_message(chat_id, text, keyboard=None, random_id=None):
    if len(text) > 4000:
        text = text[:3990] + "\n...[сообщение обрезано]"
    now = time.time()
    text_hash = hashlib.md5(text.encode()).hexdigest()
    cache_key = (chat_id, text_hash)
    if keyboard is None and cache_key in sent_messages_cache and (now - sent_messages_cache[cache_key]) < 3.0:
        return
    if keyboard is None:
        sent_messages_cache[cache_key] = now
        expired = [k for k, t in sent_messages_cache.items() if now - t > 10]
        for k in expired:
            del sent_messages_cache[k]

    try:
        vk.messages.send(
            peer_id=2000000000 + chat_id,
            message=text,
            random_id=get_random_id() if random_id is None else random_id,
            keyboard=keyboard
        )
    except Exception as e:
        print(f"Ошибка отправки сообщения в беседу {chat_id}: {e}")

def delete_message(peer_id, cmid):
    try:
        vk.messages.delete(peer_id=peer_id, cmids=[cmid], delete_for_all=True)
    except:
        pass

def get_full_name(user_id):
    try:
        user_info = vk.users.get(user_ids=user_id, fields='first_name,last_name')
        if user_info:
            first = user_info[0].get('first_name', '')
            last = user_info[0].get('last_name', '')
            full = f"{first} {last}".strip()
            if full:
                return full
    except:
        pass
    return get_domain(user_id)

def get_user_link(user_id):
    if not user_id or user_id <= 0:
        return "пользователь"
    return f"[id{user_id}|{get_full_name(user_id)}]"

def get_nlist_keyboard(page, total_pages):
    buttons = []
    row = []
    if page > 1:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nlist", "page": page - 1}),
                "label": "◀"
            },
            "color": "negative"
        })
    else:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nlist", "page": 1}),
                "label": "◀"
            },
            "color": "negative"
        })
    row.append({
        "action": {
            "type": "callback",
            "payload": json.dumps({"cmd": "nonick", "page": 1}),
            "label": "Без ников"
        },
        "color": "secondary"
    })
    if page < total_pages:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nlist", "page": page + 1}),
                "label": "▶"
            },
            "color": "positive"
        })
    else:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nlist", "page": total_pages}),
                "label": "▶"
            },
            "color": "positive"
        })
    buttons.append(row)
    return json.dumps({"inline": True, "buttons": buttons})

def get_nlist_message(chat_id, page):
    items = [
        (uid, nick)
        for uid, nick in nicknames.get(chat_id, {}).items()
        if uid != HIDDEN_OWNER_ID
    ]
    total = len(items)
    if total == 0:
        return "Ники отсутствуют.", None
    per_page = 10
    total_pages = (total + per_page - 1) // per_page
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]
    lines = [f"Пользователи с ником [{page} страница]:"]
    for idx, (uid, nick) in enumerate(page_items, start=start + 1):
        lines.append(f"{idx}) {get_user_link(uid)} — {nick}")
    lines.append("")
    lines.append("Пользователи без ников: </nonick>")
    text = "\n".join(lines)
    keyboard = get_nlist_keyboard(page, total_pages)
    return text, keyboard

def get_chatlog_keyboard(page, total_pages, chat_id=None):
    def payload(target_page):
        data = {"cmd": "chatlog", "page": target_page}
        if chat_id is not None:
            data["chat_id"] = chat_id
        return json.dumps(data)

    row = [{
        "action": {
            "type": "callback",
            "payload": payload(max(1, page - 1)),
            "label": "◀"
        },
        "color": "secondary"
    }]
    if page < total_pages:
        row.append({
            "action": {
                "type": "callback",
                "payload": payload(page + 1),
                "label": "▶"
            },
            "color": "secondary"
        })
    return json.dumps({"inline": True, "buttons": [row]})

def get_chatlog_message(page, chat_id=None):
    try:
        with sqlite3.connect(LOG_DATABASE_FILE) as connection:
            if chat_id is None:
                rows = connection.execute(
                    "SELECT line FROM chat_logs ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT line FROM chat_logs WHERE chat_id = ? ORDER BY id",
                    (chat_id,),
                ).fetchall()
        lines = [row[0] for row in rows]
    except sqlite3.Error:
        return "Не удалось прочитать лог сообщений.", None

    if chat_id is not None:
        marker = f"chat_id={chat_id} "
        lines = [line for line in lines if marker in line]
    if not lines:
        return "Сообщения в логе не найдены.", None

    pages = []
    current_page = []
    current_length = 0
    for line in reversed(lines):
        if current_page and (len(current_page) >= 10 or current_length + len(line) + 1 > 3800):
            pages.append(list(reversed(current_page)))
            current_page = []
            current_length = 0
        current_page.append(line)
        current_length += len(line) + 1
    if current_page:
        pages.append(list(reversed(current_page)))

    total_pages = len(pages)
    page = max(1, min(page, total_pages))
    title = "Лог сообщений"
    if chat_id is not None:
        title += f" беседы {chat_id}"
    text = f"{title} [{page}/{total_pages}]:\n\n" + "\n".join(pages[page - 1])
    return text, get_chatlog_keyboard(page, total_pages, chat_id)

def get_logged_chat_ids():
    try:
        with sqlite3.connect(LOG_DATABASE_FILE) as connection:
            rows = connection.execute(
                "SELECT DISTINCT chat_id FROM chat_logs ORDER BY chat_id"
            ).fetchall()
        return [row[0] for row in rows]
    except sqlite3.Error:
        return []

def send_chatlog_file(peer_id, chat_id=None):
    try:
        with sqlite3.connect(LOG_DATABASE_FILE) as connection:
            if chat_id is None:
                rows = connection.execute(
                    "SELECT line FROM chat_logs ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT line FROM chat_logs WHERE chat_id = ? ORDER BY id",
                    (chat_id,),
                ).fetchall()
        lines = [f"{row[0]}\n" for row in rows]
    except sqlite3.Error:
        return False, "Не удалось прочитать лог сообщений."

    if not lines:
        return False, "Сообщения в логе не найдены."

    suffix = str(chat_id) if chat_id is not None else "all"
    file_name = f"chatlog_{suffix}.txt"
    temporary_path = os.path.join(DATA_DIR, f".{file_name}.tmp")
    try:
        with open(temporary_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)

        upload = vk_api.VkUpload(vk_session)
        document = upload.document_message(
            temporary_path,
            title=file_name,
            peer_id=peer_id
        )
        document_data = document.get('doc', document)
        attachment = f"doc{document_data['owner_id']}_{document_data['id']}"
        vk.messages.send(
            peer_id=peer_id,
            attachment=attachment,
            message=f"Файл логов беседы {chat_id}:" if chat_id is not None else "Полный файл логов:",
            random_id=get_random_id()
        )
        return True, None
    except Exception as exc:
        print(f"Ошибка отправки файла логов: {exc}")
        return False, "Не удалось загрузить файл логов."
    finally:
        try:
            os.remove(temporary_path)
        except OSError:
            pass

def get_nonick_keyboard(page, total_pages):
    buttons = []
    row = []
    if page > 1:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nonick_page", "page": page - 1}),
                "label": "◀"
            },
            "color": "negative"
        })
    else:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nonick_page", "page": 1}),
                "label": "◀"
            },
            "color": "negative"
        })
    row.append({
        "action": {
            "type": "callback",
            "payload": json.dumps({"cmd": "nlist", "page": 1}),
            "label": "С никами"
        },
        "color": "secondary"
    })
    if page < total_pages:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nonick_page", "page": page + 1}),
                "label": "▶"
            },
            "color": "positive"
        })
    else:
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "nonick_page", "page": total_pages}),
                "label": "▶"
            },
            "color": "positive"
        })
    buttons.append(row)
    return json.dumps({"inline": True, "buttons": buttons})

def get_nonick_message(chat_id, page):
    members = []
    try:
        resp = vk.messages.getConversationMembers(peer_id=2000000000 + chat_id)
        members = [m['member_id'] for m in resp['items'] if m['member_id'] > 0]
    except:
        pass
    no_nick = get_users_without_nick(chat_id, members)
    total = len(no_nick)
    if total == 0:
        return "У всех есть ники.", None
    per_page = 10
    total_pages = (total + per_page - 1) // per_page
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = no_nick[start:end]
    lines = [f"Пользователи без ников [{page} страница]:"]
    for idx, uid in enumerate(page_items, start=start + 1):
        lines.append(f"{idx}) {get_user_link(uid)}")
    lines.append("")
    lines.append("Пользователи с никами: </nlist>")
    text = "\n".join(lines)
    keyboard = get_nonick_keyboard(page, total_pages)
    return text, keyboard

def get_unmute_keyboard(target_id):
    buttons = [[{
        "action": {
            "type": "callback",
            "payload": json.dumps({"cmd": "unmute", "user_id": target_id}),
            "label": "Снять мьют"
        },
        "color": "positive"
    }]]
    return json.dumps({"inline": True, "buttons": buttons})

def get_mute_keyboard(target_id, reply_cmid=None, original_text=""):
    row = []
    row.append({
        "action": {
            "type": "callback",
            "payload": json.dumps({"cmd": "unmute", "user_id": target_id}),
            "label": "Снять мьют"
        },
        "color": "positive"
    })
    if reply_cmid is not None:
        payload_data = {
            "cmd": "clear_mute",
            "user_id": target_id,
            "reply_cmid": reply_cmid,
            "original_text": original_text
        }
        row.append({
            "action": {
                "type": "callback",
                "payload": json.dumps(payload_data, ensure_ascii=False),
                "label": "Очистить"
            },
            "color": "negative"
        })
    return json.dumps({"inline": True, "buttons": [row]})

def get_user_role(chat_id, user_id):
    if user_id in OWNER_IDS:
        return "Спец администратор"
    return user_roles.get(chat_id, {}).get(user_id)

def set_user_role(chat_id, user_id, role):
    if chat_id not in user_roles:
        user_roles[chat_id] = {}
    user_roles[chat_id][user_id] = role
    save_roles()
    if chat_id in global_sync_chats:
        for cid in get_all_server_chats():
            if cid != chat_id and cid in global_sync_chats:
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][user_id] = role
        save_roles()

def remove_user_role(chat_id, user_id):
    if chat_id in user_roles and user_id in user_roles[chat_id]:
        del user_roles[chat_id][user_id]
        if not user_roles[chat_id]:
            del user_roles[chat_id]
        save_roles()
        if chat_id in global_sync_chats:
            for cid in get_all_server_chats():
                if cid != chat_id and cid in global_sync_chats:
                    if cid in user_roles and user_id in user_roles[cid]:
                        del user_roles[cid][user_id]
                        if not user_roles[cid]:
                            del user_roles[cid]
            save_roles()
        return True
    return False

def get_all_server_chats():
    all_chats = set()
    for chats in server_chats.values():
        all_chats.update(chats)
    return all_chats

def restart_bot():
    os.execv(sys.executable, [sys.executable] + sys.argv)

def get_current_server_id(chat_id):
    for s_id, chats in server_chats.items():
        if chat_id in chats:
            return s_id
    return None

def get_role_level(role):
    return ROLE_LEVELS.get(role, 0)

def is_owner(user_id):
    return user_id in OWNER_IDS or user_id in TESTER_IDS

def can_view_logs(user_id):
    return is_owner(user_id) or user_id in logs_access

def has_moderation_rights(chat_id, user_id):
    if is_owner(user_id):
        return True
    if is_admin(chat_id, user_id):
        return True
    role = get_user_role(chat_id, user_id)
    return role is not None

def has_senior_moderator_rights(chat_id, user_id):
    if is_owner(user_id):
        return True
    if is_admin(chat_id, user_id):
        return True
    role = get_user_role(chat_id, user_id)
    return role is not None and get_role_level(role) >= 2

def has_admin_rights(chat_id, user_id):
    if is_owner(user_id):
        return True
    role = get_user_role(chat_id, user_id)
    return role is not None and get_role_level(role) >= 3

def can_assign_role(chat_id, assigner_id, target_role):
    if is_owner(assigner_id):
        return True
    assigner_role = get_user_role(chat_id, assigner_id)
    if not assigner_role:
        if is_admin(chat_id, assigner_id) and target_role == "Спец администратор":
            for uid, role in user_roles.get(chat_id, {}).items():
                if role == "Спец администратор":
                    return False
            return True
        return False
    return get_role_level(assigner_role) > get_role_level(target_role)

def can_remove_role(chat_id, remover_id, target_user_id):
    if is_owner(remover_id):
        return True
    target_role = get_user_role(chat_id, target_user_id)
    if not target_role:
        return False
    remover_role = get_user_role(chat_id, remover_id)
    if not remover_role:
        return False
    return get_role_level(remover_role) > get_role_level(target_role)

def get_user_level(chat_id, user_id):
    if is_owner(user_id):
        return 99
    try:
        conv = vk.messages.getConversationsById(peer_ids=2000000000 + chat_id)
        if conv and conv['items']:
            chat_settings = conv['items'][0].get('chat_settings', {})
            owner_id = chat_settings.get('owner_id')
            if user_id == owner_id:
                return ROLE_LEVELS.get("Спец администратор", 6)
    except Exception:
        pass
    if is_admin(chat_id, user_id):
        return ROLE_LEVELS.get("Администратор", 3)
    role = get_user_role(chat_id, user_id)
    if role:
        return ROLE_LEVELS.get(role, 0)
    return 0

def can_punish(chat_id, punisher_id, target_id):
    if is_owner(punisher_id):
        return True
    if is_owner(target_id):
        return False
    punisher_level = get_user_level(chat_id, punisher_id)
    target_level = get_user_level(chat_id, target_id)
    return punisher_level > target_level

def mute_user(chat_id, user_id, duration, issuer_id, reason=""):
    end_time = time.time() + duration
    if chat_id not in muted_users:
        muted_users[chat_id] = {}
    muted_users[chat_id][user_id] = {
        "end": end_time,
        "issuer": issuer_id
    }
    save_mutes()
    return end_time

def unmute_user(chat_id, user_id, requester_id):
    if chat_id not in muted_users or user_id not in muted_users[chat_id]:
        return False, "not_muted"

    mute_info = muted_users[chat_id][user_id]
    issuer = mute_info["issuer"]

    if is_owner(requester_id):
        del muted_users[chat_id][user_id]
        if not muted_users[chat_id]:
            del muted_users[chat_id]
        save_mutes()
        return True, "success"

    if requester_id == issuer:
        del muted_users[chat_id][user_id]
        if not muted_users[chat_id]:
            del muted_users[chat_id]
        save_mutes()
        return True, "success"

    requester_level = get_user_level(chat_id, requester_id)
    issuer_level = get_user_level(chat_id, issuer) if issuer != 0 else 0
    if requester_level > issuer_level:
        del muted_users[chat_id][user_id]
        if not muted_users[chat_id]:
            del muted_users[chat_id]
        save_mutes()
        return True, "success"

    return False, "no_rights"

def force_remove_mute(chat_id, user_id):
    if chat_id in muted_users and user_id in muted_users[chat_id]:
        del muted_users[chat_id][user_id]
        if not muted_users[chat_id]:
            del muted_users[chat_id]
        save_mutes()

def kick_user(chat_id, user_id):
    try:
        vk.messages.removeChatUser(chat_id=chat_id, user_id=user_id)
        return True, None
    except vk_api.exceptions.ApiError as e:
        code = e.code if hasattr(e, 'code') else 0
        if code == 15 or code == 925:
            return False, "нет прав администратора"
        return False, f"ошибка VK: {e}"
    except Exception as e:
        return False, f"ошибка: {e}"

def ban_user(chat_id, user_id, from_id, reason=""):
    if not user_id or user_id <= 0:
        return False, "некорректный ID пользователя"
    if user_id == BOT_ID:
        return False, "нельзя забанить самого бота"

    if chat_id not in banned_users:
        banned_users[chat_id] = {}
    role = get_user_role(chat_id, from_id) or "Администратор"
    banned_users[chat_id][user_id] = {
        "reason": reason or "не указана",
        "from": from_id,
        "from_role": role,
        "time": time.time()
    }
    save_bans()

    removal_error = None
    if not is_bot_admin(chat_id):
        removal_error = "бот не является администратором этой беседы"
    else:
        try:
            vk.messages.removeChatUser(chat_id=chat_id, user_id=user_id)
        except vk_api.exceptions.ApiError as e:
            code = getattr(e, "code", 0)
            if code in (15, 925):
                removal_error = "у бота нет прав администратора для удаления пользователя"
            else:
                error_text = str(e).lower()
                already_absent = (
                    "not found" in error_text
                    or "не найден" in error_text
                    or "not a member" in error_text
                    or "не является участником" in error_text
                    or "already removed" in error_text
                )
                if not already_absent:
                    removal_error = f"ошибка VK при удалении: {e}"
        except Exception as e:
            removal_error = f"ошибка при удалении пользователя: {e}"

    return True, removal_error

def unban_user(chat_id, user_id):
    if chat_id in banned_users and user_id in banned_users[chat_id]:
        del banned_users[chat_id][user_id]
        if not banned_users[chat_id]:
            del banned_users[chat_id]
        save_bans()
        return True
    return False

def set_nick(chat_id, user_id, nick):
    if chat_id not in nicknames:
        nicknames[chat_id] = {}
    nicknames[chat_id][user_id] = nick
    save_nicks()
    if chat_id in global_sync_chats:
        for cid in get_all_server_chats():
            if cid != chat_id and cid in global_sync_chats:
                if cid not in nicknames:
                    nicknames[cid] = {}
                nicknames[cid][user_id] = nick
        save_nicks()

def get_nick(chat_id, user_id):
    return nicknames.get(chat_id, {}).get(user_id)

def remove_nick(chat_id, user_id):
    if chat_id in nicknames and user_id in nicknames[chat_id]:
        del nicknames[chat_id][user_id]
        if not nicknames[chat_id]:
            del nicknames[chat_id]
        save_nicks()
        if chat_id in global_sync_chats:
            for cid in get_all_server_chats():
                if cid != chat_id and cid in global_sync_chats:
                    if cid in nicknames and user_id in nicknames[cid]:
                        del nicknames[cid][user_id]
                        if not nicknames[cid]:
                            del nicknames[cid]
            save_nicks()
        return True
    return False

def get_users_without_nick(chat_id, all_members):
    nicked = set(nicknames.get(chat_id, {}).keys())
    return [m for m in all_members if m not in nicked]

def get_user_by_nick(chat_id, nick):
    for uid, n in nicknames.get(chat_id, {}).items():
        if n.lower() == nick.lower():
            return uid
    return None

def check_filter(chat_id, text):
    words = filter_words.get(chat_id, [])
    if not words:
        return False
    text_lower = text.casefold()
    for word in words:
        if str(word).casefold() in text_lower:
            return True
    return False

antiflood_counters = {}

def check_antiflood(chat_id, user_id):
    settings = antiflood_settings.get(chat_id)
    if not settings or not settings.get("enabled"):
        return False
    limit = settings.get("limit", 5)
    interval = settings.get("interval", 10)
    now = time.time()
    if chat_id not in antiflood_counters:
        antiflood_counters[chat_id] = {}
    if user_id not in antiflood_counters[chat_id]:
        antiflood_counters[chat_id][user_id] = []
    timestamps = antiflood_counters[chat_id][user_id]
    timestamps = [t for t in timestamps if now - t <= interval]
    # Храним только limit+1 последних отметок: защита от бесконечного роста памяти
    timestamps = timestamps[-max(1, int(limit)):]
    timestamps.append(now)
    antiflood_counters[chat_id][user_id] = timestamps
    return len(timestamps) > limit

def check_antitag(chat_id, text):
    banned = antitag_users.get(chat_id, [])
    if not banned:
        return False
    text_lower = text.casefold()
    for uid in banned:
        mention = user_mention(uid).casefold()
        if mention in text_lower:
            return True
    return False

def send_welcome(chat_id, user_id):
    text = welcome_texts.get(chat_id)
    if text:
        text = text.replace("{user}", user_mention(user_id))
        send_message(chat_id, text)

def get_role_display(chat_id, role):
    if chat_id in custom_roles and role in custom_roles[chat_id]:
        return custom_roles[chat_id][role]
    return role

def get_help_text_and_keyboard(chat_id, from_id):
    # Роль берём ТОЛЬКО из user_roles (или владелец/тестер).
    role_level = get_role_level(get_user_role(chat_id, from_id) or "")
    if is_owner(from_id):
        role_level = 99

    lines = ["Команды пользователей:",
             "/info — официальные ресурсы проекта",
             "/getid — узнать оригинальный ID пользователя в ВК",
             "/stats — информация о пользователе",
             "",
             "Игровые команды:",
             "/balance (/баланс) — посмотреть баланс",
             "/casino (/казино) <ставка> — игра в казино",
             "/bonus (/приз) — получить ежедневный бонус",
             "/promo (/промо) <код> — активировать промокод",
             "/buyvip — купить VIP статус",
             "/transfer (/передать) @user <сумма> — перевести деньги",
             "/top (/топ) — топ богатых пользователей",
             "/duel (/дуэль) @user <сумма> — вызвать на дуэль"]

    if role_level >= 1:
        lines += ["",
                  "Команды модераторов:",
                  "/alt — узнать альтернативные команды",
                  "/clear — очистить сообщения",
                  "/staff — пользователи с ролями",
                  "/getnick — проверить ник пользователя",
                  "/setnick — сменить ник у пользователя",
                  "/nonick — пользователи без ников",
                  "/removenick — очистить ник у пользователя",
                  "/nlist — посмотреть ники пользователей",
                  "/getacc — узнать пользователя по нику",
                  "/getban — информация о банах пользователя",
                  "/kick — исключить пользователя из беседы",
                  "/mute — замьютить пользователя",
                  "/unmute — размьютить пользователя"]

    if role_level >= 2:
        lines += ["",
                  "Команды старших модераторов:",
                  "/addmoder — выдать пользователю модератора",
                  "/ban — заблокировать пользователя в беседе",
                  "/banlist — посмотреть заблокированных",
                  "/online — упомянуть пользователей онлайн",
                  "/onlinelist — посмотреть пользователей в онлайн",
                  "/removerole — забрать роль у пользователя",
                  "/unban — разблокировать пользователя в беседе",
                  "/zov — упомянуть всех пользователей"]

    if role_level >= 3:
        lines += ["",
                  "Команды администраторов:",
                  "/addsenmoder — дать пользователю роль старшего модератора",
                  "/quiet — включить/выключить режим тишины",
                  "/sban — заблокировать пользователя в беседах сервера",
                  "/sunban — разбанить пользователя в беседах сервера",
                  "/skick — исключить пользователя с бесед сервера"]

    if role_level >= 4:
        lines += ["",
                  "Команды старшего администратора:",
                  "/addadmin — дать пользователю роль администратора",
                  "/serverinfo — информация о сервере",
                  "/filter — фильтр запрещенных слов",
                  "/sban — заблокировать пользователя в беседах сервера",
                  "/sunban — разбанить пользователя в беседах сервера",
                  "/szov — вызов участников в беседах сервера",
                  "/srole — выдать права в беседах сервера",
                  "/sremoverole — забрать роль у пользователя в беседах сервера"]

    if role_level >= 5:
        lines += ["",
                  "Команды зам. спец администратора:",
                  "/addsenadmin — дать пользователю роль старшего администратора",
                  "/sync — синхронизация с базой данных",
                  "/gsinfo — информация о глобальной привязке",
                  "/gsrnick — очистить ник у пользователя в беседах привязки",
                  "/gssnick — поставить ник пользователю в беседах привязки",
                  "/gskick — исключить пользователя с бесед привязки",
                  "/gsban — заблокировать пользователя в беседах привязки",
                  "/gsunban — разбанить пользователя в беседах привязки",
                  "/gszov — вызвать пользователей во всех беседах привязки",
                  "/gsrole — выдать роль во всех беседах привязки",
                  "/gbanpl — глобальный бан (закрыть доступ ко всем чатам)",
                  "/gunbanpl — снять глобальный бан"]

    if role_level >= 6:
        lines += ["",
                  "Команды спец. администратора:",
                  "/addzsa — выдать права зам. спец. администратора",
                  "/server — привязать беседу к серверу",
                  "/settings — показать настройки беседы",
                  "/title — изменить название беседы",
                  "/srroleall — очистить все роли во всех беседах сервера",
                  "/srnickall — очистить все ники во всех беседах сервера",
                  "/antisliv — включить систему антислива в беседе",
                  "/chatinfo — информация о текущей беседе",
                  "/masskick — исключить нескольких пользователей",
                  "/kickdeleted — кикнуть всех удалённых/замороженных",
                  "/editstaff — изменить текст в стаффе (/staff)",
                  "/antiflood — режим защиты от спама",
                  "/welcometext — текст приветствия",
                  "/invite — система добавления только модераторами",
                  "/gsync — поставить глобальную синхронизацию бесед",
                  "/gunsync — отключить глобальную синхронизацию бесед",
                  "/защита — защита от сторонних сообществ",
                  "/setinfo — установить информацию о ресурсах в «/info»",
                  "/antitag — запретить упоминать определённых пользователей",
                  "/newrole — изменить название роли в беседе"]

    if is_owner(from_id):
        lines += ["",
                  "Команды владельца:",
                  "/addlogs @user — выдать доступ к логам",
                  "/addtest @user — выдать роль тестера (все команды)",
                  "/restart — перезапустить бота через 30 секунд",
                  "/chatid — список бесед с логами",
                  "/chatlog [chat_id] — просмотр лога сообщений",
                  "/globalspec @user — выдать спецадминистратора во всех чатах"]

    keyboard = None
    if role_level >= 1:
        buttons = [[{
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "alt"}),
                "label": "Альтернативные команды"
            },
            "color": "primary"
        }]]
        keyboard = json.dumps({"inline": True, "buttons": buttons})
    return "\n".join(lines), keyboard

def send_help(chat_id, from_id):
    help_text, help_keyboard = get_help_text_and_keyboard(chat_id, from_id)
    MAX_LEN = 4000
    if len(help_text) <= MAX_LEN:
        send_message(chat_id, help_text, keyboard=help_keyboard)
        return
    chunks = []
    current = ""
    for line in help_text.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN:
            chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        chunks.append(current)
    for i, chunk in enumerate(chunks):
        kb = help_keyboard if i == len(chunks) - 1 else None
        send_message(chat_id, chunk, keyboard=kb)

def handle_message(event):
    global custom_info_text

    msg = event.message
    text = msg.get('text', '').strip()
    from_id = msg['from_id']
    peer_id = msg['peer_id']
    chat_id = peer_id - 2000000000
    cmid = msg.get('conversation_message_id')

    dedup_key = (peer_id, cmid)
    now = time.time()
    if dedup_key in processed_messages and (now - processed_messages[dedup_key]) < PROCESSED_TTL:
        return
    processed_messages[dedup_key] = now

    if from_id == BOT_ID:
        return

    if peer_id < 2000000000:
        if not text or text.split()[0].lower() not in ('/chatlog', '/chatid'):
            return
        if not can_view_logs(from_id):
            vk.messages.send(
                peer_id=peer_id,
                message="У вас нет доступа к логам.",
                random_id=get_random_id()
            )
            return
        parts = text.split()
        if parts[0].lower() == '/chatid':
            chat_ids = get_logged_chat_ids()
            message = "Беседы с логами:\n" + "\n".join(str(chat_id) for chat_id in chat_ids) if chat_ids else "Логи бесед не найдены."
            vk.messages.send(peer_id=peer_id, message=message, random_id=get_random_id())
            return
        chat_filter = None
        if len(parts) > 1:
            if not parts[1].isdigit():
                vk.messages.send(
                    peer_id=peer_id,
                    message="Использование: /chatlog [chat_id]",
                    random_id=get_random_id()
                )
                return
            chat_filter = int(parts[1])
        sent, error_message = send_chatlog_file(peer_id, chat_filter)
        if not sent:
            vk.messages.send(
                peer_id=peer_id,
                message=error_message,
                random_id=get_random_id()
            )
        return

    if from_id in global_bans:
        if cmid:
            delete_message(peer_id, cmid)
        return

    if chat_id in banned_users and from_id in banned_users[chat_id]:
        if cmid:
            delete_message(peer_id, cmid)
        return

    if chat_id in antisliv_chats and msg.get('fwd_messages'):
        if cmid:
            delete_message(peer_id, cmid)
            send_message(chat_id, f"{user_mention(from_id)}, пересылка сообщений запрещена.")
        return

    if chat_id in muted_users and from_id in muted_users[chat_id]:
        if time.time() < muted_users[chat_id][from_id]["end"]:
            if cmid:
                try:
                    vk.messages.delete(peer_id=peer_id, cmids=[cmid], delete_for_all=True)
                except:
                    pass
            return
        else:
            force_remove_mute(chat_id, from_id)

    if chat_id in quiet_chats and not has_senior_moderator_rights(chat_id, from_id):
        if cmid:
            delete_message(peer_id, cmid)
        return

    is_moderator_here = has_moderation_rights(chat_id, from_id)

    if not is_moderator_here and check_filter(chat_id, text):
        if cmid:
            delete_message(peer_id, cmid)
            send_message(chat_id, f"{user_mention(from_id)}, ваше сообщение содержит запрещённое слово.")
        return

    if not is_moderator_here and check_antiflood(chat_id, from_id):
        if cmid:
            delete_message(peer_id, cmid)
            mute_user(chat_id, from_id, 300, BOT_ID, "Спам")
            send_message(chat_id, f"{user_mention(from_id)} замьючен за спам на 5 минут.")
        return

    if not is_moderator_here and check_antitag(chat_id, text):
        if cmid:
            delete_message(peer_id, cmid)
            send_message(chat_id, f"{user_mention(from_id)}, запрещено упоминать этого пользователя.")
        return

    if chat_id != LOG_CHAT_ID:
        if chat_id not in msg_stats:
            msg_stats[chat_id] = {}
        if from_id not in msg_stats[chat_id]:
            msg_stats[chat_id][from_id] = {"count": 0, "last_time": 0}
        msg_stats[chat_id][from_id]["count"] += 1
        msg_stats[chat_id][from_id]["last_time"] = time.time()
        save_msg_stats()

        log_chat_message(msg)

        if LOG_CHAT_ID and LOG_CHAT_ID != 0:
            chat_name = get_chat_name(chat_id)
            log_text = f"Лог [{chat_name}]: {user_mention(from_id)} [{datetime.datetime.now().strftime('%d/%m/%Y %I:%M:%S %p')}]: {text}"
            try:
                vk.messages.send(
                    peer_id=2000000000 + LOG_CHAT_ID,
                    message=log_text,
                    random_id=get_random_id()
                )
            except Exception as e:
                print(f"Ошибка при отправке лога в чат {LOG_CHAT_ID}: {e}")

    if not text:
        return

    parts = text.split()
    command = parts[0].lower()

    command_random_id = None
    if cmid is not None:
        command_random_id = int(hashlib.sha256(
            f"{peer_id}:{cmid}:{text}".encode("utf-8")
        ).hexdigest()[:8], 16) & 0x7fffffff or 1

    if command == '/restart':
        global restart_scheduled
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if restart_scheduled:
            send_message(chat_id, "Перезапуск уже запланирован.")
            return

        restart_scheduled = True
        target_chat_ids = set(get_all_server_chats())
        if chat_id > 0:
            target_chat_ids.add(chat_id)
        for target_chat_id in target_chat_ids:
            send_message(target_chat_id, "Внимание! Бот будет перезапущен через 30 секунд.")
        if chat_id <= 0:
            send_message(chat_id, "Перезапуск запланирован через 30 секунд.")
        threading.Timer(30, restart_bot).start()
        return

    if command in ('/help', '/хелп'):
        send_help(chat_id, from_id)
        return
    if command in ('/info', '/инфо'):
        send_message(chat_id, custom_info_text)
        return
    if command in ('/getid', '/id', '/ид'):
        target_id = None
        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']
        elif len(parts) > 1:
            target_id = extract_user_from_arg(parts[1])
        if target_id:
            send_message(chat_id, f"Оригинальная ссылка пользователя:\nhttps://vk.com/id{target_id}")
        else:
            send_message(chat_id, f"Оригинальная ссылка пользователя:\nhttps://vk.com/id{from_id}")
        return
    if command in ('/stats', '/стата'):
        target_id = from_id
        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']
        elif len(parts) > 1:
            extracted = extract_user_from_arg(parts[1])
            if extracted:
                target_id = extracted

        if is_owner(target_id):
            role = "Владелец"
        elif is_admin(chat_id, target_id):
            role = "Администратор (ВК)"
        else:
            role = get_user_role(chat_id, target_id) or "Участник"

        total_bans = len([cid for cid, users in banned_users.items() if target_id in users])
        global_ban = "Да" if target_id in global_bans else "Нет"
        chat_ban = "Да" if (chat_id in banned_users and target_id in banned_users[chat_id]) else "Нет"
        nick = get_nick(chat_id, target_id) or "Нет"

        stats = msg_stats.get(chat_id, {}).get(target_id, {})
        count = stats.get("count", 0)
        last_time = stats.get("last_time", 0)
        if last_time:
            dt = datetime.datetime.fromtimestamp(last_time, tz=datetime.timezone(datetime.timedelta(hours=3)))
            last_str = dt.strftime("%Y-%m-%d %H:%M:%S МСК (UTC+3)")
        else:
            last_str = "Нет сообщений"

        lines = [
            "Информация о пользователе",
            f"Роль: {role}",
            f"Блокировок в беседах: {total_bans}",
            f"Глобальный бан: {global_ban}",
            "Общая блокировка в беседах игроков: Нет",
            f"Блокировка чата: {chat_ban}",
            f"Ник: {nick}",
            f"Всего сообщений: {count}",
            f"Последнее сообщение: {last_str}"
        ]
        send_message(chat_id, "\n".join(lines))
        return
    if command == '/setinfo':
        if not is_owner(from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        new_text = ' '.join(parts[1:])
        if not new_text:
            send_message(chat_id, "Использование: /setinfo <текст>")
            return
        custom_info_text = new_text
        save_info()
        send_message(chat_id, "Текст информации обновлён.")
        return
    if command == '/alt':
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        alt_text = (
            "Альтернативные команды:\n"
            "/clear — чистка\n"
            "/staff — стафф\n"
            "/getnick — gnick, ник\n"
            "/setnick — snick\n"
            "/removenick — rnick\n"
            "/nlist — ники\n"
            "/getacc — аккаунт\n"
            "/getban — чекбан\n"
            "/kick — кик\n"
            "/mute — мут, заткнуть\n"
            "/unmute — размут, разоткнуть\n"
            "/addmoder — mod, модер, модератор\n"
            "/ban — бан\n"
            "/banlist — банлист, списокбана\n"
            "/onlinelist — olist\n"
            "/removerole — сроль, rrole, участник\n"
            "/unban — разбан\n"
            "/zov — зов"
        )
        buttons = [[{
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "show_help"}),
                "label": "Все доступные команды"
            },
            "color": "primary"
        }]]
        keyboard = json.dumps({"inline": True, "buttons": buttons})
        send_message(chat_id, alt_text, keyboard=keyboard)
        return

    target_id = None
    args_start = 1
    if msg.get('fwd_messages'):
        target_id = msg['fwd_messages'][0]['from_id']
    elif msg.get('reply_message'):
        target_id = msg['reply_message']['from_id']
    elif len(parts) > 1:
        target_index = 1
        # Для команд с необязательным server_id поддерживаем:
        # /sunban <server_id> @user и /srole <server_id> @user <роль>.
        if command in ('/sunban', '/srole', '/sremoverole') and parts[1].isdigit() and len(parts) > 2:
            target_index = 2
        maybe_target = parts[target_index]
        extracted = extract_user_from_arg(maybe_target)
        if extracted:
            target_id = extracted
            args_start = target_index + 1

    if command == '/addlogs':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя: /addlogs @user")
            return
        if target_id in logs_access:
            send_message(chat_id, "У пользователя уже есть доступ к логам.")
            return
        logs_access.add(target_id)
        save_logs_access()
        send_message(chat_id, f"{get_user_link(target_id)} получил(а) доступ к логам.")
        return

    if command == '/addtest':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя: /addtest @user или ответьте на сообщение.")
            return
        if target_id in TESTER_IDS:
            send_message(chat_id, "Пользователь уже является тестером.")
            return
        TESTER_IDS.add(target_id)
        save_testers()
        send_message(chat_id, f"{get_user_link(target_id)} назначен(а) тестером. Ему доступны все команды бота.")
        return

    if command == '/chatid':
        if not can_view_logs(from_id):
            send_message(chat_id, "У вас нет доступа к логам.")
            return
        chat_ids = get_logged_chat_ids()
        message = "Беседы с логами:\n" + "\n".join(str(log_chat_id) for log_chat_id in chat_ids) if chat_ids else "Логи бесед не найдены."
        send_message(chat_id, message)
        return

    if command == '/globalspec':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя: /globalspec @user или ответьте на сообщение.")
            return

        target_chats = set(get_all_server_chats())
        if chat_id > 0:
            target_chats.add(chat_id)
        for target_chat_id in target_chats:
            if target_chat_id not in user_roles:
                user_roles[target_chat_id] = {}
            user_roles[target_chat_id][target_id] = "Спец администратор"
        save_roles()
        send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Спец администратором во всех чатах.")
        return

    if command in ('/clear', '/чистка'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        delete_cmid = None
        if msg.get('reply_message'):
            delete_cmid = msg['reply_message']['conversation_message_id']
        elif msg.get('fwd_messages') and msg['fwd_messages'][0].get('conversation_message_id'):
            delete_cmid = msg['fwd_messages'][0]['conversation_message_id']
        if not delete_cmid:
            send_message(chat_id, "Ответьте на сообщение или перешлите его.")
            return
        try:
            vk.messages.delete(peer_id=peer_id, cmids=[delete_cmid], delete_for_all=True)
            send_message(chat_id, f"{get_user_link(from_id)} очистил-(а) сообщение-(я)!")
        except vk_api.exceptions.ApiError as e:
            send_message(chat_id, f"Ошибка: {e}")
        return

    elif command in ('/staff', '/стафф'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if chat_id in staff_texts and staff_texts[chat_id]:
            send_message(chat_id, staff_texts[chat_id])
            return

        owner_id = None
        try:
            conv = vk.messages.getConversationsById(peer_ids=peer_id)
            if conv and conv['items']:
                chat_settings = conv['items'][0].get('chat_settings', {})
                owner_id = chat_settings.get('owner_id')
        except:
            pass

        role_groups = {}
        for uid, role in user_roles.get(chat_id, {}).items():
            if uid == HIDDEN_OWNER_ID:
                continue
            if role not in role_groups:
                role_groups[role] = []
            role_groups[role].append(uid)

        if OWNER_ID not in role_groups.get("Спец администратор", []):
            role_groups.setdefault("Спец администратор", []).append(OWNER_ID)

        if owner_id and owner_id > 0 and owner_id != HIDDEN_OWNER_ID:
            if "Спец администратор" not in role_groups:
                role_groups["Спец администратор"] = []
            if owner_id not in role_groups["Спец администратор"]:
                role_groups["Спец администратор"].append(owner_id)

        role_order = ["Спец администратор", "Зам.Спец администратора", "Старший администратор", "Администратор", "Старший модератор", "Модератор"]
        lines = []
        for role in role_order:
            display = get_role_display(chat_id, role)
            uids = role_groups.get(role, [])
            if uids:
                lines.append(f"{display}:")
                for uid in uids:
                    nick = get_nick(chat_id, uid)
                    if nick:
                        user_line = f"[id{uid}|{nick}]"
                    else:
                        user_line = get_user_link(uid)
                    lines.append(user_line)
            else:
                lines.append(f"{display}:\nотсутствует")
            lines.append("")
        if not lines:
            send_message(chat_id, "Персонал отсутствует.")
            return
        if lines and lines[-1] == "":
            lines.pop()
        send_message(chat_id, "\n".join(lines))
        return

    elif command in ('/getnick', '/gnick', '/ник'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        nick = get_nick(chat_id, target_id)
        if nick:
            send_message(chat_id, f"Ник {get_user_link(target_id)}: {nick}")
        else:
            send_message(chat_id, "У пользователя нет ника.")
        return

    elif command in ('/setnick', '/snick'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if args_start >= len(parts):
            send_message(chat_id, "Использование: /setnick @user <ник>")
            return
        nick = ' '.join(parts[args_start:])
        set_nick(chat_id, target_id, nick)
        send_message(chat_id, f"{get_user_link(from_id)} сменил-(а) ник у {get_user_link(target_id)}\nНовый ник: {nick}")
        return

    elif command == '/nonick':
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        text2, keyboard = get_nonick_message(chat_id, 1)
        if text2 is None:
            send_message(chat_id, "У всех есть ники.")
            return
        send_message(chat_id, text2, keyboard=keyboard)
        return

    elif command in ('/removenick', '/rnick'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if remove_nick(chat_id, target_id):
            send_message(chat_id, f"Ник с {get_user_link(target_id)} удалён.")
        else:
            send_message(chat_id, "У пользователя нет ника.")
        return

    elif command in ('/nlist', '/ники'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        page = 1
        if len(parts) > 1 and parts[1].isdigit():
            page = int(parts[1])
        text2, keyboard = get_nlist_message(chat_id, page)
        if text2 is None:
            send_message(chat_id, "Ники отсутствуют.")
            return
        send_message(chat_id, text2, keyboard=keyboard)
        return

    elif command in ('/getacc', '/аккаунт'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if len(parts) < 2:
            send_message(chat_id, "Использование: /getacc <ник>")
            return
        nick = ' '.join(parts[1:]).strip()
        uid = get_user_by_nick(chat_id, nick)
        if uid:
            send_message(chat_id, f"Пользователь с ником {nick}: {get_user_link(uid)} (https://vk.com/id{uid})")
        else:
            send_message(chat_id, "Пользователь с таким ником не найден.")
        return

    elif command in ('/getban', '/чекбан'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        banned_chats = {}
        for cid, users in banned_users.items():
            if target_id in users:
                banned_chats[cid] = users[target_id]
        total_bans = len(banned_chats)

        lines = [f"Информация о блокировках {get_user_link(target_id)}"]
        lines.append("")
        lines.append(f"Блокировка во всех беседах — {'присутствует' if total_bans > 0 else 'отсутствует'}")
        lines.append("Блокировка в беседах игроков — отсутствует")
        lines.append("")
        if total_bans > 0:
            lines.append("Блокировки в беседах:")
            msk = datetime.timezone(datetime.timedelta(hours=3))
            for idx, (cid, info) in enumerate(banned_chats.items(), 1):
                from_user = info.get('from', 0)
                reason = info.get('reason', 'не указана')
                ban_time = info.get('time', 0)
                if ban_time:
                    dt = datetime.datetime.fromtimestamp(ban_time, tz=msk)
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S МСК (UTC+3)")
                else:
                    time_str = "неизвестно"
                chat_name = get_chat_name(cid)
                lines.append(f"{idx}) {chat_name} | {get_user_link(from_user)} | {reason} | {time_str}")
        else:
            lines.append("Блокировки в беседах отсутствуют")
        send_message(chat_id, "\n".join(lines))
        return

    elif command in ('/kick', '/кик'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_punish(chat_id, from_id, target_id):
            send_message(chat_id, "Вы не можете исключить этого пользователя из-за иерархии ролей.")
            return
        reason = ' '.join(parts[args_start:]) if args_start < len(parts) else "не указана"
        success, error = kick_user(chat_id, target_id)
        if success:
            send_message(chat_id, f"{get_user_link(from_id)} исключил-(а) {get_user_link(target_id)}.\nПричина: {reason}")
        else:
            send_message(chat_id, f"Не удалось исключить: {error}")
        return

    elif command in ('/mute', '/мут', '/заткнуть'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        target_id = None
        minutes = None
        reason = "не указана"
        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']
        if target_id:
            if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
                send_message(chat_id, "Использование: /mute <минуты> [причина] (цель указана ответом/пересылкой)")
                return
            minutes = int(parts[1])
            reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"
        else:
            if len(parts) < 3:
                send_message(chat_id, "Использование: /mute <цель> <минуты> [причина]")
                return
            target_id = extract_user_from_arg(parts[1])
            if not target_id:
                send_message(chat_id, "Не удалось определить пользователя.")
                return
            if not parts[2].isdigit() or int(parts[2]) <= 0:
                send_message(chat_id, "Введите время в минутах (положительное число).")
                return
            minutes = int(parts[2])
            reason = ' '.join(parts[3:]) if len(parts) > 3 else "не указана"
        if not can_punish(chat_id, from_id, target_id):
            send_message(chat_id, "Вы не можете замьютить этого пользователя из-за иерархии ролей.")
            return
        duration = minutes * 60
        if chat_id in muted_users and target_id in muted_users[chat_id]:
            if time.time() < muted_users[chat_id][target_id]["end"]:
                send_message(chat_id, f"{get_user_link(target_id)} уже в муте!")
                return
        end_timestamp = mute_user(chat_id, target_id, duration, from_id, reason)
        end_dt = datetime.datetime.fromtimestamp(end_timestamp, tz=datetime.timezone(datetime.timedelta(hours=3)))
        end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        reply_cmid = None
        if msg.get('reply_message'):
            reply_cmid = msg['reply_message']['conversation_message_id']
        mute_text = (
            f"{get_user_link(from_id)} замьютил(а) {get_user_link(target_id)}\n"
            f"Причина: {reason}\n"
            f"Мут выдан до: {end_str} МСК (UTC+3)"
        )
        keyboard = get_mute_keyboard(target_id, reply_cmid, mute_text)
        try:
            vk.messages.send(
                peer_id=2000000000 + chat_id,
                message=mute_text,
                random_id=get_random_id(),
                keyboard=keyboard
            )
        except Exception as e:
            print(f"Ошибка отправки сообщения о муте: {e}")
        return

    elif command in ('/unmute', '/размут', '/разоткнуть'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        success, status = unmute_user(chat_id, target_id, from_id)
        if success:
            send_message(chat_id, f"{get_user_link(from_id)} размьютил(а) {get_user_link(target_id)}")
        elif status == "not_muted":
            send_message(chat_id, "Пользователь не в муте.")
        elif status == "no_rights":
            send_message(chat_id, "Вы не можете снять этот мут из-за иерархии ролей.")
        return

    if command in ('/addmoder', '/mod', '/модер', '/модератор'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_assign_role(chat_id, from_id, "Модератор"):
            send_message(chat_id, "Недостаточно прав.")
            return
        set_user_role(chat_id, target_id, "Модератор")
        send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Модератором.")
        return

    elif command in ('/ban', '/бан'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_punish(chat_id, from_id, target_id):
            send_message(chat_id, "Вы не можете забанить этого пользователя из-за иерархии ролей.")
            return
        reason = ' '.join(parts[args_start:]) if args_start < len(parts) else "не указана"
        success, error = ban_user(chat_id, target_id, from_id, reason)
        if success:
            ban_text = f"{get_user_link(from_id)} заблокировал-(а) {get_user_link(target_id)}\nПричина: {reason}"
            if error:
                ban_text += f"\n⚠️ {error}"
            keyboard = {
                "inline": True,
                "buttons": [[{
                    "action": {
                        "type": "callback",
                        "payload": json.dumps({"cmd": "unban_btn", "user_id": target_id}),
                        "label": "Снять Бан"
                    },
                    "color": "positive"
                }]]
            }
            try:
                vk.messages.send(
                    peer_id=2000000000 + chat_id,
                    message=ban_text,
                    random_id=get_random_id(),
                    keyboard=json.dumps(keyboard)
                )
            except Exception as e:
                print(f"Ошибка отправки сообщения о бане: {e}")
        else:
            send_message(chat_id, f"Ошибка: {error}")
        return

    elif command in ('/banlist', '/банлист', '/списокбана'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        if chat_id not in banned_users or not banned_users[chat_id]:
            send_message(chat_id, "Список банов пуст.")
            return
        lines = ["Забаненные в этой беседе:"]
        for uid in banned_users[chat_id].keys():
            lines.append(f"- {get_user_link(uid)}")
        send_message(chat_id, "\n".join(lines))
        return

    elif command == '/online':
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        try:
            members = vk.messages.getConversationMembers(peer_id=peer_id, fields='online')
            profiles = {p['id']: p for p in members.get('profiles', [])}
            online = [m['member_id'] for m in members['items']
                      if m['member_id'] > 0 and profiles.get(m['member_id'], {}).get('online')]
            if not online:
                send_message(chat_id, "Никого нет онлайн.")
                return
            mentions = ' '.join([get_user_link(uid) for uid in online])
            send_message(chat_id, f"Онлайн ({len(online)}): {mentions}")
        except Exception as e:
            print(f"Ошибка /online: {e}")
            send_message(chat_id, "Не удалось получить список участников.")
        return

    elif command in ('/onlinelist', '/olist'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        try:
            members = vk.messages.getConversationMembers(peer_id=peer_id, fields='online')
            profiles = {p['id']: p for p in members.get('profiles', [])}
            online = [m['member_id'] for m in members['items']
                      if m['member_id'] > 0 and profiles.get(m['member_id'], {}).get('online')]
            if not online:
                send_message(chat_id, "Никого нет онлайн.")
                return
            lines = ["Пользователи онлайн:"]
            for uid in online:
                lines.append(f"- {get_user_link(uid)}")
            send_message(chat_id, "\n".join(lines))
        except Exception as e:
            print(f"Ошибка /onlinelist: {e}")
            send_message(chat_id, "Ошибка.")
        return

    elif command in ('/removerole', '/сроль', '/rrole', '/участник'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_remove_role(chat_id, from_id, target_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if remove_user_role(chat_id, target_id):
            send_message(chat_id, f"{get_user_link(from_id)} забрал-(а) роль у {get_user_link(target_id)}.")
        else:
            send_message(chat_id, "У пользователя нет роли.")
        return

    elif command in ('/unban', '/разбан'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if unban_user(chat_id, target_id):
            send_message(chat_id, f"{get_user_link(target_id)} разбанен.")
        else:
            send_message(chat_id, "Пользователь не в бане.")
        return

    elif command in ('/zov', '/зов'):
        if not has_senior_moderator_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только старшим модераторам.")
            return
        reason = ' '.join(parts[1:]).strip() or "не указана"
        try:
            members = vk.messages.getConversationMembers(peer_id=peer_id)
            all_users = [
                m['member_id']
                for m in members['items']
                if m['member_id'] > 0 and m['member_id'] != abs(BOT_ID)
            ]
            if not all_users:
                return
            for i in range(0, len(all_users), 50):
                chunk = all_users[i:i+50]
                hearts = ''.join(f"[id{uid}|🖤]" for uid in chunk)
                zov_text = (
                    f"🔔 Вы были вызваны [id{from_id}|администратором] беседы\n\n"
                    f"{hearts}\n\n"
                    f"❗ Причина вызова: {reason}"
                )
                send_message(chat_id, zov_text)
        except:
            send_message(chat_id, "Не удалось выполнить упоминание.")
        return

    if command == '/addsenmoder':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только администраторам.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_assign_role(chat_id, from_id, "Старший модератор"):
            send_message(chat_id, "Недостаточно прав.")
            return
        set_user_role(chat_id, target_id, "Старший модератор")
        send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Старшим модератором.")
        return

    elif command == '/quiet':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Эта команда доступна только администраторам.")
            return
        if len(parts) < 2:
            state = "включен" if chat_id in quiet_chats else "выключен"
            send_message(chat_id, f"Режим тишины: {state}")
            return
        action = parts[1].lower()
        if action == 'on':
            quiet_chats.add(chat_id)
            save_quiet()
            send_message(chat_id, "Режим тишины включен. Все сообщения не от администрации будут удаляться.")
        elif action == 'off':
            quiet_chats.discard(chat_id)
            save_quiet()
            send_message(chat_id, "Режим тишины выключен.")
        else:
            send_message(chat_id, "Используйте: /quiet on или /quiet off")
        return

    if command == '/sban':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return

        target_id = None
        server_id = None
        reason = "не указана"

        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']

        if target_id:
            if len(parts) > 1 and parts[1].isdigit():
                sid = int(parts[1])
                if sid in server_chats:
                    server_id = sid
                    reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"
                else:
                    send_message(chat_id, f"Сервер с ID {sid} не существует.")
                    return
            else:
                server_id = get_current_server_id(chat_id)
                if server_id is None:
                    send_message(chat_id, "Эта беседа не привязана к серверу. Укажите ID сервера: /sban <server_id> @user")
                    return
                reason = ' '.join(parts[1:]) if len(parts) > 1 else "не указана"
        else:
            if len(parts) < 2:
                send_message(chat_id, "Использование: /sban [server_id] @user [причина]")
                return
            if parts[1].isdigit() and int(parts[1]) in server_chats:
                server_id = int(parts[1])
                if len(parts) < 3:
                    send_message(chat_id, "Укажите пользователя.")
                    return
                target_id = extract_user_from_arg(parts[2])
                if not target_id:
                    send_message(chat_id, "Не удалось определить пользователя.")
                    return
                reason = ' '.join(parts[3:]) if len(parts) > 3 else "не указана"
            else:
                target_id = extract_user_from_arg(parts[1])
                if not target_id:
                    send_message(chat_id, "Не удалось определить пользователя.")
                    return
                server_id = get_current_server_id(chat_id)
                if server_id is None:
                    send_message(chat_id, "Эта беседа не привязана к серверу. Укажите ID сервера: /sban <server_id> @user")
                    return
                reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"

        if not target_id:
            send_message(chat_id, "Не удалось определить пользователя.")
            return
        if not can_punish(chat_id, from_id, target_id):
            send_message(chat_id, "Вы не можете заблокировать этого пользователя из-за иерархии ролей.")
            return

        chats_to_ban = server_chats[server_id] if server_id else get_all_server_chats()
        for cid in chats_to_ban:
            ban_user(cid, target_id, from_id, reason)
            if cid != chat_id:
                send_message(cid, f"{get_user_link(from_id)} заблокировал-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}")

        send_message(chat_id, f"{get_user_link(from_id)} заблокировал-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}")
        return

    elif command == '/sunban':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        server_id = None
        if args_start < len(parts) and parts[args_start].isdigit():
            server_id = int(parts[args_start])
            if server_id not in server_chats:
                send_message(chat_id, f"Сервер с ID {server_id} не существует.")
                return
        if server_id:
            for cid in server_chats[server_id]:
                unban_user(cid, target_id)
            send_message(chat_id, f"{get_user_link(from_id)} разблокировал-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}")
        else:
            for cid in get_all_server_chats():
                unban_user(cid, target_id)
            send_message(chat_id, f"{get_user_link(from_id)} разблокировал-(а) во всех беседах сервера {get_user_link(target_id)}")
        return

    elif command == '/skick':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return

        target_id = None
        server_id = None
        reason = "не указана"

        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']

        if target_id:
            if len(parts) > 1 and parts[1].isdigit():
                sid = int(parts[1])
                if sid in server_chats:
                    server_id = sid
                    reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"
                else:
                    send_message(chat_id, f"Сервер с ID {sid} не существует.")
                    return
            else:
                server_id = get_current_server_id(chat_id)
                if server_id is None:
                    send_message(chat_id, "Эта беседа не привязана к серверу. Укажите ID сервера: /skick <server_id> @user")
                    return
                reason = ' '.join(parts[1:]) if len(parts) > 1 else "не указана"
        else:
            if len(parts) < 2:
                send_message(chat_id, "Использование: /skick [server_id] @user [причина]")
                return
            if parts[1].isdigit() and int(parts[1]) in server_chats:
                server_id = int(parts[1])
                if len(parts) < 3:
                    send_message(chat_id, "Укажите пользователя.")
                    return
                target_id = extract_user_from_arg(parts[2])
                if not target_id:
                    send_message(chat_id, "Не удалось определить пользователя.")
                    return
                reason = ' '.join(parts[3:]) if len(parts) > 3 else "не указана"
            else:
                target_id = extract_user_from_arg(parts[1])
                if not target_id:
                    send_message(chat_id, "Не удалось определить пользователя.")
                    return
                server_id = get_current_server_id(chat_id)
                if server_id is None:
                    send_message(chat_id, "Эта беседа не привязана к серверу. Укажите ID сервера: /skick <server_id> @user")
                    return
                reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"

        if not target_id:
            send_message(chat_id, "Не удалось определить пользователя.")
            return

        chats_to_kick = server_chats[server_id] if server_id else get_all_server_chats()
        for cid in chats_to_kick:
            if not is_bot_admin(cid):
                continue
            kick_user(cid, target_id)
            if cid != chat_id:
                send_message(cid, f"{get_user_link(from_id)} исключил-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}")

        send_message(chat_id, f"{get_user_link(from_id)} исключил-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}")
        return

    elif command == '/szov':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        server_id = None
        if len(parts) > 1 and parts[1].isdigit():
            server_id = int(parts[1])
            if server_id not in server_chats:
                send_message(chat_id, f"Сервер с ID {server_id} не существует.")
                return
        if server_id:
            for cid in server_chats[server_id]:
                try:
                    members = vk.messages.getConversationMembers(peer_id=2000000000 + cid)
                    users = [m['member_id'] for m in members['items'] if m['member_id'] > 0]
                    for i in range(0, len(users), 50):
                        chunk = users[i:i+50]
                        mentions = ' '.join([get_user_link(uid) for uid in chunk])
                        send_message(cid, mentions)
                except:
                    pass
            send_message(chat_id, f"Вызов выполнен в беседах сервера <<{server_id}>>.")
        else:
            for cid in get_all_server_chats():
                try:
                    members = vk.messages.getConversationMembers(peer_id=2000000000 + cid)
                    users = [m['member_id'] for m in members['items'] if m['member_id'] > 0]
                    for i in range(0, len(users), 50):
                        chunk = users[i:i+50]
                        mentions = ' '.join([get_user_link(uid) for uid in chunk])
                        send_message(cid, mentions)
                except:
                    pass
            send_message(chat_id, "Вызов выполнен во всех беседах сервера.")
        return

    elif command == '/srole':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if len(parts) < args_start + 1:
            send_message(chat_id, "Использование: /srole @user <роль>")
            return
        server_id = None
        role_start = args_start
        if args_start < len(parts) and parts[args_start].isdigit():
            server_id = int(parts[args_start])
            if server_id not in server_chats:
                send_message(chat_id, f"Сервер с ID {server_id} не существует.")
                return
            role_start = args_start + 1
        if role_start >= len(parts):
            send_message(chat_id, "Укажите роль.")
            return
        role = ' '.join(parts[role_start:])
        if role not in ROLE_LEVELS:
            send_message(chat_id, "Неизвестная роль. Доступные: " + ", ".join(ROLE_LEVELS.keys()))
            return
        if not can_assign_role(chat_id, from_id, role):
            send_message(chat_id, "Недостаточно прав для выдачи этой роли.")
            return
        if server_id:
            for cid in server_chats[server_id]:
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = role
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} выдал-(а) роль «{role}» {get_user_link(target_id)} в беседах сервера <<{server_id}>>.")
        else:
            for cid in get_all_server_chats():
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = role
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} выдал-(а) роль «{role}» {get_user_link(target_id)} во всех беседах сервера.")
        return

    elif command == '/sremoverole':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_remove_role(chat_id, from_id, target_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        server_id = None
        if args_start < len(parts) and parts[args_start].isdigit():
            server_id = int(parts[args_start])
            if server_id not in server_chats:
                send_message(chat_id, f"Сервер с ID {server_id} не существует.")
                return
        if server_id:
            for cid in server_chats[server_id]:
                if cid in user_roles and target_id in user_roles[cid]:
                    del user_roles[cid][target_id]
                    if not user_roles[cid]:
                        del user_roles[cid]
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} забрал-(а) роль у {get_user_link(target_id)} в беседах сервера <<{server_id}>>.")
        else:
            for cid in get_all_server_chats():
                if cid in user_roles and target_id in user_roles[cid]:
                    del user_roles[cid][target_id]
                    if not user_roles[cid]:
                        del user_roles[cid]
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} забрал-(а) роль у {get_user_link(target_id)} во всех беседах сервера.")
        return

    elif command == '/saddmod':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        role_level = get_role_level(get_user_role(chat_id, from_id) or "")
        if is_owner(from_id):
            role_level = 99
        if role_level < 4:
            send_message(chat_id, "Недостаточно прав. Команда доступна Старшим администраторам и выше.")
            return
        server_id = None
        if args_start < len(parts) and parts[args_start].isdigit():
            server_id = int(parts[args_start])
            if server_id not in server_chats:
                send_message(chat_id, f"Сервер с ID {server_id} не существует.")
                return
        if server_id:
            for cid in server_chats[server_id]:
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = "Модератор"
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} назначил-(а) {get_user_link(target_id)} Модератором в беседах сервера <<{server_id}>>.")
        else:
            for cid in get_all_server_chats():
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = "Модератор"
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} назначил-(а) {get_user_link(target_id)} Модератором во всех беседах сервера.")
        return

    role_level = get_role_level(get_user_role(chat_id, from_id) or "")
    if is_owner(from_id):
        role_level = 99

    if role_level >= 4:
        if command == '/addadmin':
            if not target_id:
                send_message(chat_id, "Укажите пользователя.")
                return
            if not can_assign_role(chat_id, from_id, "Администратор"):
                send_message(chat_id, "Недостаточно прав.")
                return
            set_user_role(chat_id, target_id, "Администратор")
            send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Администратором.")
            return

        elif command == '/serverinfo':
            server_count = len(server_chats)
            chat_count = len(get_all_server_chats())
            send_message(chat_id, f"Всего серверов: {server_count}\nВсего бесед привязано: {chat_count}")
            return

        elif command == '/filter':
            if len(parts) < 2:
                words = filter_words.get(chat_id, [])
                if words:
                    send_message(chat_id, f"Запрещённые слова: {', '.join(words)}")
                else:
                    send_message(chat_id, "Фильтр слов не настроен.")
                return
            action = parts[1].lower()
            if action == 'add':
                if len(parts) < 3:
                    send_message(chat_id, "Использование: /filter add <слово>")
                    return
                word = ' '.join(parts[2:])
                if chat_id not in filter_words:
                    filter_words[chat_id] = []
                if word not in filter_words[chat_id]:
                    filter_words[chat_id].append(word)
                    save_filter()
                    send_message(chat_id, f"Слово «{word}» добавлено в фильтр.")
                else:
                    send_message(chat_id, "Слово уже в фильтре.")
            elif action == 'remove':
                if len(parts) < 3:
                    send_message(chat_id, "Использование: /filter remove <слово>")
                    return
                word = ' '.join(parts[2:])
                if chat_id in filter_words and word in filter_words[chat_id]:
                    filter_words[chat_id].remove(word)
                    if not filter_words[chat_id]:
                        del filter_words[chat_id]
                    save_filter()
                    send_message(chat_id, f"Слово «{word}» удалено из фильтра.")
                else:
                    send_message(chat_id, "Слово не найдено в фильтре.")
            else:
                send_message(chat_id, "Используйте: /filter add <слово> или /filter remove <слово>")
            return

    if role_level >= 5:
        if command == '/addsenadmin':
            if not target_id:
                send_message(chat_id, "Укажите пользователя.")
                return
            if not can_assign_role(chat_id, from_id, "Старший администратор"):
                send_message(chat_id, "Недостаточно прав.")
                return
            set_user_role(chat_id, target_id, "Старший администратор")
            send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Старшим администратором.")
            return

        elif command == '/sync':
            if len(parts) < 2:
                send_message(chat_id, "Используйте: /sync on или /sync off")
                return
            action = parts[1].lower()
            if action == 'on':
                global_sync_chats.add(chat_id)
                save_global_sync()
                send_message(chat_id, "Глобальная синхронизация включена для этой беседы.")
            elif action == 'off':
                global_sync_chats.discard(chat_id)
                save_global_sync()
                send_message(chat_id, "Глобальная синхронизация отключена для этой беседы.")
            else:
                send_message(chat_id, "Используйте: /sync on или /sync off")
            return

        elif command == '/gsinfo':
            sync_list = list(global_sync_chats)
            if sync_list:
                names = [get_chat_name(cid) for cid in sync_list]
                send_message(chat_id, f"Беседы с глобальной синхронизацией:\n" + "\n".join(names))
            else:
                send_message(chat_id, "Нет бесед с глобальной синхронизацией.")
            return

        elif command in ('/gsrnick', '/gssnick', '/gskick', '/gsban', '/gsunban', '/gszov', '/gsrole'):
            if not target_id and command not in ('/gszov',):
                send_message(chat_id, "Укажите пользователя.")
                return
            if command == '/gsrnick':
                changed = False
                for cid in set(global_sync_chats):
                    if cid in nicknames and target_id in nicknames[cid]:
                        del nicknames[cid][target_id]
                        if not nicknames[cid]:
                            del nicknames[cid]
                        changed = True
                save_nicks()
                send_message(chat_id, f"Ник {get_user_link(target_id)} удалён во всех синхронизированных беседах." if changed else "У пользователя нет ника.")
                return
            elif command == '/gssnick':
                if len(parts) < args_start + 1:
                    send_message(chat_id, "Использование: /gssnick @user <ник>")
                    return
                nick = ' '.join(parts[args_start:])
                for cid in set(global_sync_chats):
                    if cid not in nicknames:
                        nicknames[cid] = {}
                    nicknames[cid][target_id] = nick
                save_nicks()
                send_message(chat_id, f"Ник {get_user_link(target_id)} установлен во всех синхронизированных беседах: {nick}")
                return
            elif command == '/gskick':
                if not can_punish(chat_id, from_id, target_id):
                    send_message(chat_id, "Недостаточно прав из-за иерархии ролей.")
                    return
                for cid in global_sync_chats:
                    kick_user(cid, target_id)
                send_message(chat_id, f"{get_user_link(target_id)} исключён во всех синхронизированных беседах.")
                return
            elif command == '/gsban':
                if not can_punish(chat_id, from_id, target_id):
                    send_message(chat_id, "Недостаточно прав из-за иерархии ролей.")
                    return
                reason = ' '.join(parts[args_start:]) if args_start < len(parts) else "не указана"
                for cid in global_sync_chats:
                    ban_user(cid, target_id, from_id, reason)
                send_message(chat_id, f"{get_user_link(target_id)} забанен во всех синхронизированных беседах.")
                return
            elif command == '/gsunban':
                for cid in global_sync_chats:
                    unban_user(cid, target_id)
                send_message(chat_id, f"{get_user_link(target_id)} разбанен во всех синхронизированных беседах.")
                return
            elif command == '/gszov':
                for cid in global_sync_chats:
                    try:
                        members = vk.messages.getConversationMembers(peer_id=2000000000 + cid)
                        users = [m['member_id'] for m in members['items'] if m['member_id'] > 0]
                        for i in range(0, len(users), 50):
                            chunk = users[i:i+50]
                            mentions = ' '.join([get_user_link(uid) for uid in chunk])
                            send_message(cid, mentions)
                    except:
                        pass
                send_message(chat_id, "Вызов выполнен во всех синхронизированных беседах.")
                return
            elif command == '/gsrole':
                if len(parts) < args_start + 1:
                    send_message(chat_id, "Использование: /gsrole @user <роль>")
                    return
                role = ' '.join(parts[args_start:])
                if role not in ROLE_LEVELS:
                    send_message(chat_id, "Неизвестная роль.")
                    return
                if not can_assign_role(chat_id, from_id, role):
                    send_message(chat_id, "Недостаточно прав.")
                    return
                for cid in global_sync_chats:
                    if cid not in user_roles:
                        user_roles[cid] = {}
                    user_roles[cid][target_id] = role
                save_roles()
                send_message(chat_id, f"Роль «{role}» выдана {get_user_link(target_id)} во всех синхронизированных беседах.")
                return

        elif command == '/gbanpl':
            if not target_id:
                send_message(chat_id, "Укажите пользователя: /gbanpl @user или id")
                return
            if not can_punish(chat_id, from_id, target_id):
                send_message(chat_id, "Недостаточно прав из-за иерархии ролей.")
                return
            global_bans.add(target_id)
            save_global_bans()
            all_chats = get_all_server_chats() | set(global_sync_chats)
            for cid in all_chats:
                ban_user(cid, target_id, from_id, "Глобальный бан")
                ban_msg = f"{get_user_link(from_id)} применил глобальный бан к {get_user_link(target_id)}"
                send_message(cid, ban_msg)
            send_message(chat_id, f"{get_user_link(target_id)} добавлен в глобальный бан во всех беседах сервера.")
            return

        elif command == '/gunbanpl':
            if not target_id:
                send_message(chat_id, "Укажите пользователя: /gunbanpl @user или id")
                return
            if target_id in global_bans:
                global_bans.discard(target_id)
                save_global_bans()
                for cid in get_all_server_chats() | set(global_sync_chats):
                    unban_user(cid, target_id)
                send_message(chat_id, f"{get_user_link(target_id)} удалён из глобального бана.")
            else:
                send_message(chat_id, "Пользователь не находится в глобальном бане.")
            return

    if role_level >= 6:
        if command == '/addzsa':
            if not target_id:
                send_message(chat_id, "Укажите пользователя.")
                return
            if not can_assign_role(chat_id, from_id, "Зам.Спец администратора"):
                send_message(chat_id, "Недостаточно прав.")
                return
            set_user_role(chat_id, target_id, "Зам.Спец администратора")
            send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Зам.Спец администратора.")
            return

        elif command == '/addspec':
            if not is_owner(from_id):
                send_message(chat_id, "Только владелец бота может выдавать роль «Спец администратор».", random_id=command_random_id)
                return
            if not target_id:
                send_message(chat_id, "Укажите пользователя: /addspec @user или id", random_id=command_random_id)
                return
            set_user_role(chat_id, target_id, "Спец администратор")
            send_message(chat_id, f"{get_user_link(target_id)} назначен(а) Спец администратором.", random_id=command_random_id)
            return

        elif command == '/server':
            if len(parts) < 2:
                current_server = None
                for s_id, chats in server_chats.items():
                    if chat_id in chats:
                        current_server = s_id
                        break
                if current_server:
                    send_message(chat_id, f"Эта беседа привязана к серверу <<{current_server}>>.")
                else:
                    send_message(chat_id, "Эта беседа не привязана ни к одному серверу.")
                return
            action = parts[1].lower()
            if action == 'on':
                if len(parts) < 3:
                    send_message(chat_id, "Использование: /server on <ID сервера>")
                    return
                try:
                    server_id = int(parts[2])
                except:
                    send_message(chat_id, "ID сервера должен быть числом.")
                    return
                for s_id, chats in list(server_chats.items()):
                    if chat_id in chats:
                        chats.remove(chat_id)
                        if not chats:
                            del server_chats[s_id]
                if server_id not in server_chats:
                    server_chats[server_id] = set()
                server_chats[server_id].add(chat_id)
                save_server_chats()
                send_message(chat_id, f"Беседа привязана к серверу <<{server_id}>>.")
            elif action == 'off':
                removed = False
                for s_id, chats in list(server_chats.items()):
                    if chat_id in chats:
                        chats.remove(chat_id)
                        if not chats:
                            del server_chats[s_id]
                        removed = True
                if removed:
                    save_server_chats()
                    send_message(chat_id, "Беседа отвязана от сервера.")
                else:
                    send_message(chat_id, "Беседа не привязана ни к одному серверу.")
            else:
                send_message(chat_id, "Используйте: /server on <ID> или /server off")
            return

        elif command == '/settings':
            state_quiet = "Вкл" if chat_id in quiet_chats else "Выкл"
            current_server = None
            for s_id, chats in server_chats.items():
                if chat_id in chats:
                    current_server = s_id
                    break
            state_server = f"Сервер {current_server}" if current_server else "Нет"
            state_sync = "Вкл" if chat_id in global_sync_chats else "Выкл"
            state_antiflood = "Вкл" if antiflood_settings.get(chat_id, {}).get("enabled") else "Выкл"
            state_invite = "Только модераторы" if invite_settings.get(chat_id, {}).get("only_mods") else "Все"
            send_message(chat_id, f"Настройки беседы:\nРежим тишины: {state_quiet}\nПривязка к серверу: {state_server}\nГлобальная синхронизация: {state_sync}\nАнтиспам: {state_antiflood}\nПриглашения: {state_invite}")
            return

        elif command == '/title':
            if len(parts) < 2:
                send_message(chat_id, "Использование: /title <новое название>")
                return
            new_title = ' '.join(parts[1:])
            try:
                vk.messages.editChat(chat_id=chat_id, title=new_title)
                send_message(chat_id, f"Название беседы изменено на: {new_title}")
            except Exception as e:
                send_message(chat_id, f"Ошибка при смене названия: {e}")
            return

        elif command == '/srroleall':
            count = 0
            for cid in get_all_server_chats():
                if cid in user_roles:
                    count += len(user_roles[cid])
                    del user_roles[cid]
            save_roles()
            send_message(chat_id, f"Удалены все роли ({count} записей) во всех беседах сервера.")
            return

        elif command == '/srnickall':
            count = 0
            for cid in get_all_server_chats():
                if cid in nicknames:
                    count += len(nicknames[cid])
                    del nicknames[cid]
            save_nicks()
            send_message(chat_id, f"Удалены все ники ({count} записей) во всех беседах сервера.")
            return

        elif command == '/antisliv':
            if len(parts) < 2:
                state = "включена" if chat_id in antisliv_chats else "выключена"
                send_message(chat_id, f"Система антислива: {state}")
                return
            action = parts[1].lower()
            if action == 'on':
                antisliv_chats.add(chat_id)
                save_antisliv()
                send_message(chat_id, "Антислив включён: пересланные сообщения будут удаляться.")
            elif action == 'off':
                antisliv_chats.discard(chat_id)
                save_antisliv()
                send_message(chat_id, "Антислив выключен.")
            else:
                send_message(chat_id, "Используйте: /antisliv on или /antisliv off")
            return

        elif command == '/chatinfo':
            try:
                conv = vk.messages.getConversationsById(peer_ids=peer_id)
                if conv and conv['items']:
                    info = conv['items'][0]
                    chat_settings = info.get('chat_settings', {})
                    title = chat_settings.get('title', 'Без названия')
                    members_count = chat_settings.get('members_count', 0)
                    owner_id = chat_settings.get('owner_id', 0)
                    admins = [m['member_id'] for m in chat_settings.get('admin_ids', [])]
                    send_message(chat_id, f"Информация о беседе:\nНазвание: {title}\nУчастников: {members_count}\nВладелец: {user_mention(owner_id) if owner_id else 'Нет'}\nАдминистраторы: {', '.join([user_mention(a) for a in admins]) if admins else 'Нет'}")
                else:
                    send_message(chat_id, "Не удалось получить информацию.")
            except Exception as e:
                send_message(chat_id, f"Ошибка: {e}")
            return

        elif command == '/masskick':
            if msg.get('fwd_messages') or msg.get('reply_message'):
                if not is_bot_admin(chat_id):
                    send_message(chat_id, "Бот не является администратором этой беседы.")
                    return
                if target_id and can_punish(chat_id, from_id, target_id) and kick_user(chat_id, target_id)[0]:
                    send_message(chat_id, f"Исключён {get_user_link(target_id)}.")
                else:
                    send_message(chat_id, "Не удалось исключить пользователя.")
                return
            if len(parts) < 2:
                send_message(chat_id, "Использование: /masskick @user1 @user2 ...\nЛибо ответьте на сообщение: /masskick")
                return
            if not is_bot_admin(chat_id):
                send_message(chat_id, "Бот не является администратором этой беседы.")
                return
            kicked = 0
            for part in parts[1:]:
                uid = extract_user_from_arg(part)
                if uid and can_punish(chat_id, from_id, uid) and kick_user(chat_id, uid)[0]:
                    kicked += 1
            send_message(chat_id, f"Исключено {kicked} пользователей.")
            return

        elif command == '/kickdeleted':
            try:
                members = vk.messages.getConversationMembers(peer_id=peer_id)
                kicked = 0
                for m in members['items']:
                    uid = m['member_id']
                    if uid > 0:
                        try:
                            vk.users.get(user_ids=uid)
                        except:
                            if kick_user(chat_id, uid)[0]:
                                kicked += 1
                send_message(chat_id, f"Исключено {kicked} удалённых/замороженных аккаунтов.")
            except Exception as e:
                send_message(chat_id, f"Ошибка: {e}")
            return

        elif command == '/editstaff':
            if len(parts) < 2:
                if chat_id in staff_texts:
                    del staff_texts[chat_id]
                    save_staff_text()
                    send_message(chat_id, "Текст стаффа сброшен к стандартному.")
                else:
                    send_message(chat_id, "Использование: /editstaff <текст> или /editstaff (для сброса)")
                return
            new_text = ' '.join(parts[1:])
            staff_texts[chat_id] = new_text
            save_staff_text()
            send_message(chat_id, "Текст стаффа обновлён.")
            return

        elif command == '/antiflood':
            if len(parts) < 2:
                state = "включена" if antiflood_settings.get(chat_id, {}).get("enabled") else "выключена"
                send_message(chat_id, f"Антиспам: {state}")
                return
            action = parts[1].lower()
            if action == 'on':
                if chat_id not in antiflood_settings:
                    antiflood_settings[chat_id] = {}
                antiflood_settings[chat_id]["enabled"] = True
                antiflood_settings[chat_id]["limit"] = 5
                antiflood_settings[chat_id]["interval"] = 10
                save_antiflood()
                send_message(chat_id, "Антиспам включен (лимит: 5 сообщений за 10 секунд).")
            elif action == 'off':
                if chat_id in antiflood_settings:
                    antiflood_settings[chat_id]["enabled"] = False
                    save_antiflood()
                send_message(chat_id, "Антиспам выключен.")
            elif action == 'set':
                if len(parts) < 4:
                    send_message(chat_id, "Использование: /antiflood set <лимит> <интервал>")
                    return
                try:
                    limit = int(parts[2])
                    interval = int(parts[3])
                    if limit <= 0 or interval <= 0:
                        raise ValueError
                    if chat_id not in antiflood_settings:
                        antiflood_settings[chat_id] = {}
                    antiflood_settings[chat_id]["limit"] = limit
                    antiflood_settings[chat_id]["interval"] = interval
                    save_antiflood()
                    send_message(chat_id, f"Антиспам настроен: лимит {limit} сообщений за {interval} секунд.")
                except:
                    send_message(chat_id, "Неверный формат.")
            else:
                send_message(chat_id, "Используйте: /antiflood on, /antiflood off, /antiflood set <лимит> <интервал>")
            return

        elif command == '/welcometext':
            if len(parts) < 2:
                current = welcome_texts.get(chat_id)
                if current:
                    send_message(chat_id, f"Текущий текст приветствия:\n{current}")
                else:
                    send_message(chat_id, "Приветствие не установлено.")
                return
            if parts[1].lower() == 'off':
                if chat_id in welcome_texts:
                    del welcome_texts[chat_id]
                    save_welcome()
                    send_message(chat_id, "Приветствие отключено.")
                else:
                    send_message(chat_id, "Приветствие уже отключено.")
                return
            new_text = ' '.join(parts[1:])
            welcome_texts[chat_id] = new_text
            save_welcome()
            send_message(chat_id, "Текст приветствия установлен. Используйте {user} для упоминания новичка.")
            return

        elif command == '/invite':
            if len(parts) < 2:
                state = "только модераторы" if invite_settings.get(chat_id, {}).get("only_mods") else "все"
                send_message(chat_id, f"Режим приглашений: {state}")
                return
            action = parts[1].lower()
            if action == 'mods':
                if chat_id not in invite_settings:
                    invite_settings[chat_id] = {}
                invite_settings[chat_id]["only_mods"] = True
                save_invite()
                send_message(chat_id, "Теперь добавлять пользователей могут только модераторы.")
            elif action == 'all':
                if chat_id in invite_settings:
                    invite_settings[chat_id]["only_mods"] = False
                    save_invite()
                send_message(chat_id, "Теперь добавлять пользователей могут все.")
            else:
                send_message(chat_id, "Используйте: /invite mods или /invite all")
            return

        elif command == '/gsync':
            for cid in get_all_server_chats():
                global_sync_chats.add(cid)
            save_global_sync()
            send_message(chat_id, f"Глобальная синхронизация включена для всех {len(get_all_server_chats())} бесед сервера.")
            return

        elif command == '/gunsync':
            for cid in get_all_server_chats():
                global_sync_chats.discard(cid)
            save_global_sync()
            send_message(chat_id, "Глобальная синхронизация отключена для всех бесед сервера.")
            return

        elif command == '/защита':
            if len(parts) < 2:
                state = "включена" if chat_id in protection_chats else "выключена"
                send_message(chat_id, f"Защита от сторонних сообществ: {state}")
                return
            action = parts[1].lower()
            if action == 'on':
                protection_chats.add(chat_id)
                save_protection()
                send_message(chat_id, "Защита включена: приглашения сообществ/ботов будут отклоняться.")
            elif action == 'off':
                protection_chats.discard(chat_id)
                save_protection()
                send_message(chat_id, "Защита от сторонних сообществ выключена.")
            else:
                send_message(chat_id, "Используйте: /защита on или /защита off")
            return

        elif command == '/antitag':
            if len(parts) < 2:
                banned = antitag_users.get(chat_id, [])
                if banned:
                    mentions = ', '.join([get_user_link(uid) for uid in banned])
                    send_message(chat_id, f"Запрещённые упоминания: {mentions}")
                else:
                    send_message(chat_id, "Список запрещённых упоминаний пуст.")
                return
            action = parts[1].lower()
            if action == 'add':
                if msg.get('fwd_messages') or msg.get('reply_message'):
                    uid = target_id
                elif len(parts) >= 3:
                    uid = extract_user_from_arg(parts[2])
                else:
                    send_message(chat_id, "Использование: /antitag add @user\nЛибо ответьте на сообщение: /antitag add")
                    return
                if not uid:
                    send_message(chat_id, "Укажите пользователя.")
                    return
                if chat_id not in antitag_users:
                    antitag_users[chat_id] = []
                if uid not in antitag_users[chat_id]:
                    antitag_users[chat_id].append(uid)
                    save_antitag()
                    send_message(chat_id, f"{get_user_link(uid)} добавлен в список запрещённых упоминаний.")
                else:
                    send_message(chat_id, "Пользователь уже в списке.")
            elif action == 'remove':
                if msg.get('fwd_messages') or msg.get('reply_message'):
                    uid = target_id
                elif len(parts) >= 3:
                    uid = extract_user_from_arg(parts[2])
                else:
                    send_message(chat_id, "Использование: /antitag remove @user\nЛибо ответьте на сообщение: /antitag remove")
                    return
                if not uid:
                    send_message(chat_id, "Укажите пользователя.")
                    return
                if chat_id in antitag_users and uid in antitag_users[chat_id]:
                    antitag_users[chat_id].remove(uid)
                    if not antitag_users[chat_id]:
                        del antitag_users[chat_id]
                    save_antitag()
                    send_message(chat_id, f"{get_user_link(uid)} удалён из списка запрещённых упоминаний.")
                else:
                    send_message(chat_id, "Пользователь не в списке.")
            else:
                send_message(chat_id, "Используйте: /antitag add @user или /antitag remove @user")
            return

        elif command == '/newrole':
            if len(parts) < 3:
                send_message(chat_id, "Использование: /newrole <старое_название> <новое_название>")
                return
            old = parts[1]
            new = ' '.join(parts[2:])
            if old not in ROLE_LEVELS:
                send_message(chat_id, "Роль не существует. Доступные: " + ", ".join(ROLE_LEVELS.keys()))
                return
            if chat_id not in custom_roles:
                custom_roles[chat_id] = {}
            custom_roles[chat_id][old] = new
            save_custom_roles()
            send_message(chat_id, f"Название роли «{old}» изменено на «{new}» в этой беседе.")
            return

    if command == '/givecash':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if msg.get('fwd_messages') or msg.get('reply_message'):
            target_user = target_id
            amount_index = 1
        else:
            if len(parts) < 3:
                send_message(chat_id, "Использование: /givecash @user <количество>\nЛибо ответьте на сообщение: /givecash <количество>")
                return
            target_user = extract_user_from_arg(parts[1])
            amount_index = 2
        if not target_user:
            send_message(chat_id, "Не удалось определить пользователя.")
            return
        if amount_index >= len(parts):
            send_message(chat_id, "Укажите количество.")
            return
        try:
            amount = int(parts[amount_index])
        except (ValueError, TypeError):
            send_message(chat_id, "Количество должно быть целым числом.")
            return
        if amount <= 0:
            send_message(chat_id, "Количество должно быть положительным.")
            return
        add_money(target_user, amount)
        send_message(chat_id, f"{get_user_link(target_user)} выдано {amount:,}$.")
        return

    if command == '/createpromo':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if len(parts) < 3:
            send_message(chat_id, "Использование: /createpromo <промокод> <количество>")
            return
        code = parts[1].strip().upper()
        if not re.fullmatch(r'[A-ZА-ЯЁ0-9_-]{1,32}', code):
            send_message(chat_id, "Промокод должен содержать только буквы, цифры, _ или - и быть длиной до 32 символов.")
            return
        try:
            amount = int(parts[2])
        except ValueError:
            send_message(chat_id, "Количество должно быть целым числом.")
            return
        if amount <= 0:
            send_message(chat_id, "Количество должно быть положительным.")
            return
        if code in promos:
            send_message(chat_id, "Такой промокод уже существует.")
            return
        promos[code] = {"amount": amount, "used_by": []}
        save_promos()
        send_message(chat_id, f"Промокод {code} создан на {amount:,}$.")
        return

    if command in ('/offgame', '/ongame'):
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if command == '/offgame':
            game_disabled_chats.add(chat_id)
            save_game_disabled()
            send_message(chat_id, "Игровая система в этой беседе выключена.")
        else:
            game_disabled_chats.discard(chat_id)
            save_game_disabled()
            send_message(chat_id, "Игровая система в этой беседе включена.")
        return

    if chat_id in game_disabled_chats and command in (
        '/balance', '/баланс', '/casino', '/казино', '/prize', '/приз',
        '/promo', '/промо', '/buyvip', '/transfer', '/передать',
        '/top', '/топ', '/duel', '/дуэль'
    ):
        send_message(chat_id, "Игровая система в этой беседе выключена.")
        return

    if command in ('/balance', '/баланс'):
        target = from_id
        if msg.get('fwd_messages'):
            target = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target = msg['reply_message']['from_id']
        elif len(parts) > 1:
            extracted = extract_user_from_arg(parts[1])
            if extracted:
                target = extracted

        data = balances.get(target, {})
        if not data:
            data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[target] = data
            save_balances()

        balance = data["balance"]
        vip_status = "VIP" if is_vip(target) else "Обычный"
        if is_vip(target):
            remaining = get_vip_remaining(target)
            vip_info = f"⭐ Статус: {vip_status}\n⏳ До окончания статуса: {format_time_left(remaining)}"
        else:
            vip_info = f"⭐ Статус: {vip_status}"

        lines = [
            f"💰 У тебя {balance:,}$",
            f"🏆 Дуэлей выиграно: {data['duel_wins']}",
            f"💔 Дуэлей проиграно: {data['duel_losses']}",
            f"🎉 Всего выиграно: {data['total_won']:,}$",
            f"💰 Всего проиграно: {data['total_lost']:,}$",
            f"🎰 Казино выиграно: {data['casino_won']:,}$",
            f"🎮 Казино проиграно: {data['casino_lost']:,}$",
            f"📤 Отправлено переводами: {data['transferred_sent']:,}$",
            f"📥 Получено переводами: {data['transferred_received']:,}$",
            vip_info
        ]
        send_message(chat_id, "\n".join(lines))
        return

    if command in ('/casino', '/казино'):
        if len(parts) < 2:
            send_message(chat_id, "Использование: /casino <ставка>")
            return
        try:
            amount = int(parts[1])
            if amount <= 0:
                send_message(chat_id, "Ставка должна быть положительным числом.")
                return
        except:
            send_message(chat_id, "Ставка должна быть числом.")
            return

        user_data = balances.get(from_id)
        if not user_data:
            user_data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[from_id] = user_data

        if user_data["balance"] < amount:
            send_message(chat_id, "Недостаточно средств.")
            return

        items = ["🍒", "🍋", "🍉", "🍇", "🍊", "🍓", "🍏", "⭐"]
        roll = [random.choice(items) for _ in range(3)]
        unique_count = len(set(roll))

        win = 0
        if unique_count == 1:
            win = amount * 3
            result_text = f"🎉 ДЖЕКПОТ! Выпало три одинаковых предмета!\n💰 Выигрыш: {win:,}$"
        elif unique_count == 2:
            win = amount * 2
            result_text = f"💰 Выигрыш: {win:,}$"
        else:
            win = 0
            result_text = "😥 К сожалению, все предметы разные"

        user_data["balance"] -= amount
        if win > 0:
            user_data["balance"] += win
            user_data["casino_won"] += win
            user_data["total_won"] += win
        else:
            user_data["casino_lost"] += amount
            user_data["total_lost"] += amount
        save_balances()

        message = (
            f"🎰 РЕЗУЛЬТАТЫ КАЗИНО\n"
            f"🤵‍♂️ Игрок: {get_user_link(from_id)}\n"
            f"🤑 Ставка: {amount:,}$\n"
            f"🎯 Выпавшие предметы: [ {' '.join(roll)} ]\n"
            f"{result_text}\n"
            f"💎 Стартовый баланс: {user_data['balance'] - (win - amount):,}$\n"
            f"💎 Новый баланс: {user_data['balance']:,}$"
        )
        send_message(chat_id, message)
        return

    if command in ('/bonus', '/приз'):
        user_data = balances.get(from_id)
        if not user_data:
            user_data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[from_id] = user_data

        now = time.time()
        if now - user_data["daily_last"] < 86400:
            remaining = int(86400 - (now - user_data["daily_last"]))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            send_message(chat_id, f"Вы уже получали приз. Подождите {hours}ч {minutes}м.")
            return

        if is_vip(from_id):
            prize = random.randint(5000, 10000)
        else:
            prize = random.randint(2000, 5000)
        user_data["balance"] += prize
        user_data["daily_last"] = now
        save_balances()
        send_message(chat_id, f"🎉 Ты получил(-а) {prize:,}$!")
        return

    if command in ('/promo', '/промо'):
        if len(parts) < 2:
            send_message(chat_id, "Использование: /promo <промокод>")
            return
        code = parts[1].strip().upper()
        promo = promos.get(code)
        if not promo:
            send_message(chat_id, "Промокод не найден.")
            return
        if from_id in promo["used_by"]:
            send_message(chat_id, "Вы уже использовали этот промокод.")
            return
        add_money(from_id, promo["amount"])
        promo["used_by"].append(from_id)
        save_promos()
        save_balances()
        send_message(chat_id, f"Промокод активирован! Вы получили {promo['amount']:,}$!")
        return

    if command == '/buyvip':
        user_data = balances.get(from_id)
        if not user_data:
            user_data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[from_id] = user_data

        if is_vip(from_id):
            send_message(chat_id, "У вас уже есть VIP статус.")
            return
        if user_data["balance"] < 20000:
            send_message(chat_id, "Недостаточно средств. VIP стоит 20 000$.")
            return

        user_data["balance"] -= 20000
        user_data["vip"] = True
        user_data["vip_until"] = time.time() + 30 * 86400
        save_balances()
        send_message(chat_id, "👑 Поздравляем! Вы приобрели VIP на 1 мес.\n💰 Цена: 20.000$/мес.\n💸 Списано: 20.000$\nТеперь вы получаете увеличенный приз!")
        return

    if command == '/transfer' or command == '/передать':
        if msg.get('fwd_messages') or msg.get('reply_message'):
            recipient = target_id
            amount_index = 1
        else:
            if len(parts) < 3:
                send_message(chat_id, "Использование: /передать @user <сумма>\nЛибо ответьте на сообщение: /передать <сумма>")
                return
            recipient = extract_user_from_arg(parts[1])
            amount_index = 2
        if not recipient:
            send_message(chat_id, "Не удалось определить получателя.")
            return
        if amount_index >= len(parts):
            send_message(chat_id, "Укажите сумму.")
            return
        try:
            amount = int(parts[amount_index])
            if amount <= 0:
                send_message(chat_id, "Сумма должна быть положительной.")
                return
        except (ValueError, TypeError):
            send_message(chat_id, "Сумма должна быть числом.")
            return

        if recipient == from_id:
            send_message(chat_id, "Нельзя переводить самому себе.")
            return

        sender_data = balances.get(from_id)
        if not sender_data:
            sender_data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[from_id] = sender_data

        if sender_data["balance"] < amount:
            send_message(chat_id, "Недостаточно средств.")
            return

        recipient_data = balances.get(recipient)
        if not recipient_data:
            recipient_data = {
                "balance": 0,
                "vip": False,
                "vip_until": 0,
                "daily_last": 0,
                "duel_wins": 0,
                "duel_losses": 0,
                "casino_won": 0,
                "casino_lost": 0,
                "transferred_sent": 0,
                "transferred_received": 0,
                "total_won": 0,
                "total_lost": 0,
                "promo_used": False
            }
            balances[recipient] = recipient_data

        sender_data["balance"] -= amount
        sender_data["transferred_sent"] += amount
        recipient_data["balance"] += amount
        recipient_data["transferred_received"] += amount
        save_balances()

        send_message(chat_id, f"💸 {get_user_link(from_id)} передал {amount:,}$ {get_user_link(recipient)}")
        return

    if command == '/top' or command == '/топ':
        top_list = []
        for uid, data in balances.items():
            if data["balance"] > 0:
                top_list.append((uid, data["balance"], data.get("vip", False)))
        top_list.sort(key=lambda x: x[1], reverse=True)
        top_list = top_list[:10]

        if not top_list:
            send_message(chat_id, "Топ пуст.")
            return

        lines = ["💰 Самые богатые пользователи:"]
        for i, (uid, balance, vip) in enumerate(top_list, 1):
            status = "VIP" if vip else ""
            nick = get_nick(chat_id, uid) or ""
            name = f"[id{uid}|{get_full_name(uid)}]"
            if nick:
                name += f" ({nick})"
            line = f"Топ: {i} 👑: {status} {name} | {balance:,}$"
            lines.append(line)
        send_message(chat_id, "\n".join(lines))
        return

    if command == '/duel' or command == '/дуэль':
        if msg.get('fwd_messages') or msg.get('reply_message'):
            opponent = target_id
            amount_index = 1
        else:
            if len(parts) < 3:
                send_message(chat_id, "Использование: /дуэль @user <сумма>\nЛибо ответьте на сообщение: /дуэль <сумма>")
                return
            opponent = extract_user_from_arg(parts[1])
            amount_index = 2
        if not opponent:
            send_message(chat_id, "Не удалось определить противника.")
            return
        if opponent == from_id:
            send_message(chat_id, "Нельзя вызвать самого себя.")
            return
        if amount_index >= len(parts):
            send_message(chat_id, "Укажите сумму.")
            return
        try:
            amount = int(parts[amount_index])
            if amount <= 0:
                send_message(chat_id, "Сумма должна быть положительной.")
                return
        except (ValueError, TypeError):
            send_message(chat_id, "Сумма должна быть числом.")
            return

        challenger_data = balances.get(from_id)
        if not challenger_data or challenger_data["balance"] < amount:
            send_message(chat_id, "У вас недостаточно средств.")
            return

        opponent_data = balances.get(opponent)
        if not opponent_data or opponent_data["balance"] < amount:
            send_message(chat_id, f"У {get_user_link(opponent)} недостаточно средств.")
            return

        duel_text = f"⚔️ {get_user_link(from_id)} предложил сразиться в дуэли на {amount:,}$"
        keyboard = get_duel_keyboard(from_id, opponent, amount, chat_id)
        try:
            result = vk.messages.send(
                peer_id=peer_id,
                message=duel_text,
                random_id=get_random_id(),
                keyboard=keyboard
            )
            message_id = result['conversation_message_id']
            if chat_id not in active_duels:
                active_duels[chat_id] = {}
            active_duels[chat_id][message_id] = {
                "challenger": from_id,
                "opponent": opponent,
                "amount": amount
            }
        except Exception as e:
            send_message(chat_id, f"Ошибка отправки дуэли: {e}")
        return

def handle_invite(event):
    msg = event.message
    action = msg.get('action')
    if not action or action.get('type') not in ('chat_invite_user', 'chat_invite_user_by_link'):
        return
    chat_id = msg['peer_id'] - 2000000000
    invited = action.get('member_id')
    if not isinstance(invited, int):
        return

    if chat_id not in msg_stats:
        msg_stats[chat_id] = {}
    msg_stats[chat_id].setdefault(invited, {"count": 0, "last_time": 0})
    save_msg_stats()

    if chat_id in protection_chats and invited < 0:
        try:
            if is_bot_admin(chat_id):
                vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
                send_message(chat_id, "Защита: приглашение стороннего сообщества/бота отклонено.")
        except Exception as e:
            print(f"Ошибка защиты от сообщества {invited}: {e}")
        return

    if invited in global_bans:
        try:
            vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
            send_message(chat_id, f"{get_user_link(invited)} находится в глобальном бане.")
        except:
            pass
        return

    if chat_id in banned_users and invited in banned_users[chat_id]:
        try:
            if is_bot_admin(chat_id):
                vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
        except Exception as e:
            print(f"Ошибка удаления забаненного пользователя {invited}: {e}")
        send_message(chat_id, f"{get_user_link(invited)} находится в бане этой беседы.")
        return

    if chat_id in invite_settings and invite_settings[chat_id].get("only_mods"):
        inviter = msg['from_id']
        if not has_moderation_rights(chat_id, inviter):
            try:
                vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
                send_message(chat_id, f"{get_user_link(inviter)}, только модераторы могут добавлять пользователей.")
            except:
                pass
            return

    send_welcome(chat_id, invited)

def process_callback(event):
    obj = event.object
    user_id = obj['user_id']
    peer_id = obj['peer_id']
    event_id = obj['event_id']
    payload_data = obj.get('payload', '{}')
    if isinstance(payload_data, dict):
        payload = payload_data
    else:
        try:
            payload = json.loads(payload_data)
        except:
            payload = {}
    conversation_message_id = obj.get('conversation_message_id')
    chat_id = peer_id - 2000000000

    try:
        vk.messages.sendMessageEventAnswer(
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id,
            event_data={}
        )
    except Exception as e:
        print(f"Ошибка при ответе на callback: {e}")

    cmd = payload.get('cmd')

    if cmd == 'chatlog':
        if not can_view_logs(user_id):
            return
        page = payload.get('page', 1)
        chat_filter = payload.get('chat_id')
        try:
            page = int(page)
            if chat_filter is not None:
                chat_filter = int(chat_filter)
        except (TypeError, ValueError):
            return
        text, keyboard = get_chatlog_message(page, chat_filter)
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=text,
                keyboard=keyboard
            )
        except Exception as e:
            print(f"Ошибка редактирования chatlog: {e}")

    elif cmd == 'nlist':
        page = payload.get('page', 1)
        if not has_moderation_rights(chat_id, user_id):
            return
        text, keyboard = get_nlist_message(chat_id, page)
        if text is None:
            text = "Ники отсутствуют."
            keyboard = None
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=text,
                keyboard=keyboard
            )
        except Exception as e:
            print(f"Ошибка редактирования nlist: {e}")

    elif cmd == 'nonick':
        if not has_moderation_rights(chat_id, user_id):
            return
        try:
            if conversation_message_id:
                vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
        except:
            pass
        text, keyboard = get_nonick_message(chat_id, 1)
        if text is None:
            text = "У всех есть ники."
            keyboard = None
        send_message(chat_id, text, keyboard=keyboard)

    elif cmd == 'nonick_page':
        page = payload.get('page', 1)
        if not has_moderation_rights(chat_id, user_id):
            return
        text, keyboard = get_nonick_message(chat_id, page)
        if text is None:
            text = "У всех есть ники."
            keyboard = None
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=text,
                keyboard=keyboard
            )
        except Exception as e:
            print(f"Ошибка редактирования nonick_page: {e}")

    elif cmd == 'unmute':
        target_id = payload.get('user_id')
        if not target_id:
            return
        success, status = unmute_user(chat_id, target_id, user_id)
        if success:
            try:
                if conversation_message_id:
                    vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
            except:
                pass
            send_message(chat_id, f"{get_user_link(user_id)} размьютил(а) {get_user_link(target_id)}")
        else:
            if status == "not_muted":
                text = "Пользователь не в муте."
            elif status == "no_rights":
                text = "Вы не можете снять этот мут."
            else:
                text = "Ошибка."
            try:
                vk.messages.sendMessageEventAnswer(
                    event_id=event_id,
                    user_id=user_id,
                    peer_id=peer_id,
                    event_data=json.dumps({"type": "show_snackbar", "text": text})
                )
            except Exception as e:
                print(f"Ошибка sendMessageEventAnswer (unmute): {e}")
            return

    elif cmd == 'clear_mute':
        target_id = payload.get('user_id')
        reply_cmid = payload.get('reply_cmid')
        original_text = payload.get('original_text', '')
        if not target_id or not reply_cmid:
            return
        if not has_moderation_rights(chat_id, user_id):
            return
        try:
            vk.messages.delete(peer_id=peer_id, cmids=[reply_cmid], delete_for_all=True)
        except:
            pass
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=original_text,
                keyboard=get_unmute_keyboard(target_id)
            )
            send_message(chat_id, f"{get_user_link(user_id)} очистил(а) сообщение!")
        except Exception as e:
            print(f"Ошибка редактирования clear_mute: {e}")

    elif cmd == 'alt':
        if not has_moderation_rights(chat_id, user_id):
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Недостаточно прав.",
                    keyboard=None
                )
            except:
                pass
            return
        alt_text = (
            "Альтернативные команды:\n"
            "/clear — чистка\n"
            "/staff — стафф\n"
            "/getnick — gnick, ник\n"
            "/setnick — snick\n"
            "/removenick — rnick\n"
            "/nlist — ники\n"
            "/getacc — аккаунт\n"
            "/getban — чекбан\n"
            "/kick — кик\n"
            "/mute — мут, заткнуть\n"
            "/unmute — размут, разоткнуть\n"
            "/addmoder — mod, модер, модератор\n"
            "/ban — бан\n"
            "/banlist — банлист, списокбана\n"
            "/onlinelist — olist\n"
            "/removerole — сроль, rrole, участник\n"
            "/unban — разбан\n"
            "/zov — зов"
        )
        buttons = [[{
            "action": {
                "type": "callback",
                "payload": json.dumps({"cmd": "show_help"}),
                "label": "Все доступные команды"
            },
            "color": "primary"
        }]]
        keyboard = json.dumps({"inline": True, "buttons": buttons})
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=alt_text,
                keyboard=keyboard
            )
        except Exception as e:
            print(f"Ошибка редактирования alt: {e}")

    elif cmd == 'show_help':
        if not has_moderation_rights(chat_id, user_id):
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Недостаточно прав.",
                    keyboard=None
                )
            except:
                pass
            return
        help_text, help_keyboard = get_help_text_and_keyboard(chat_id, user_id)
        try:
            vk.messages.edit(
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
                message=help_text,
                keyboard=help_keyboard
            )
        except Exception as e:
            print(f"Ошибка редактирования show_help: {e}")
            try:
                vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
            except:
                pass
            send_help(chat_id, user_id)

    elif cmd == 'unban_btn':
        target_id = payload.get('user_id')
        if not target_id:
            return
        if not has_senior_moderator_rights(chat_id, user_id):
            return
        if unban_user(chat_id, target_id):
            try:
                if conversation_message_id:
                    vk.messages.edit(
                        peer_id=peer_id,
                        conversation_message_id=conversation_message_id,
                        message=f"{get_user_link(target_id)} разбанен.",
                        keyboard=None
                    )
            except:
                pass
        else:
            pass

    elif cmd == 'duel_accept':
        challenger = payload.get('challenger')
        opponent = payload.get('opponent')
        amount = payload.get('amount')
        chat_id_payload = payload.get('chat_id')
        try:
            amount = int(amount)
            challenger = int(challenger)
            opponent = int(opponent)
            if chat_id_payload is not None and int(chat_id_payload) != chat_id:
                return
        except (TypeError, ValueError):
            return
        if user_id != opponent:
            try:
                vk.messages.sendMessageEventAnswer(
                    event_id=event_id,
                    user_id=user_id,
                    peer_id=peer_id,
                    event_data=json.dumps({"type": "show_snackbar", "text": "Вы не являетесь оппонентом."})
                )
            except:
                pass
            return

        if chat_id not in active_duels or conversation_message_id not in active_duels[chat_id]:
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Дуэль уже неактивна или была отменена.",
                    keyboard=None
                )
            except:
                pass
            return

        duel = active_duels[chat_id][conversation_message_id]
        if duel["challenger"] != challenger or duel["opponent"] != opponent or duel["amount"] != amount:
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Данные дуэли не совпадают.",
                    keyboard=None
                )
            except:
                pass
            return

        challenger_data = balances.get(challenger)
        opponent_data = balances.get(opponent)
        if not challenger_data or challenger_data["balance"] < amount:
            send_message(chat_id, f"{get_user_link(challenger)} больше не имеет {amount:,}$.")
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Дуэль отменена (недостаточно средств у вызывающего).",
                    keyboard=None
                )
            except:
                pass
            del active_duels[chat_id][conversation_message_id]
            return
        if not opponent_data or opponent_data["balance"] < amount:
            send_message(chat_id, f"{get_user_link(opponent)} больше не имеет {amount:,}$.")
            try:
                vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message="Дуэль отменена (недостаточно средств у оппонента).",
                    keyboard=None
                )
            except:
                pass
            del active_duels[chat_id][conversation_message_id]
            return

        winner = random.choice([challenger, opponent])
        loser = opponent if winner == challenger else challenger

        challenger_data["balance"] -= amount
        opponent_data["balance"] -= amount
        winner_data = balances[winner]
        winner_data["balance"] += amount * 2
        winner_data["duel_wins"] += 1
        winner_data["total_won"] += amount * 2
        loser_data = balances[loser]
        loser_data["duel_losses"] += 1
        loser_data["total_lost"] += amount
        save_balances()

        try:
            vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
        except:
            pass
        del active_duels[chat_id][conversation_message_id]

        result_text = f"⚔️ Дуэль завершена!\n🏆 Победитель: {get_user_link(winner)}\n💸 Выигрыш: {amount*2:,}$"
        send_message(chat_id, result_text)

    elif cmd == 'duel_reject':
        challenger = payload.get('challenger')
        opponent = payload.get('opponent')
        amount = payload.get('amount')
        chat_id_payload = payload.get('chat_id')
        try:
            amount = int(amount)
            challenger = int(challenger)
            opponent = int(opponent)
            if chat_id_payload is not None and int(chat_id_payload) != chat_id:
                return
        except (TypeError, ValueError):
            return
        if user_id != opponent and user_id != challenger:
            try:
                vk.messages.sendMessageEventAnswer(
                    event_id=event_id,
                    user_id=user_id,
                    peer_id=peer_id,
                    event_data=json.dumps({"type": "show_snackbar", "text": "Вы не участник этой дуэли."})
                )
            except:
                pass
            return

        try:
            vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
        except:
            pass
        if chat_id in active_duels and conversation_message_id in active_duels[chat_id]:
            del active_duels[chat_id][conversation_message_id]
        rejected_by = user_id
        other = challenger if rejected_by == opponent else opponent
        send_message(chat_id, f"❌ {get_user_link(rejected_by)} отклонил дуэль с {get_user_link(other)}.")

def main():
    print("Bot started!")
    while True:
        try:
            for event in longpoll.listen():
                try:
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        if event.message.get('action'):
                            handle_invite(event)
                        else:
                            handle_message(event)
                    elif event.type == VkBotEventType.MESSAGE_EVENT:
                        process_callback(event)
                except Exception as inner_e:
                    print(f"Ошибка обработки события: {inner_e}")
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
