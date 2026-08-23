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

# ================= НАСТРОЙКИ =================
TOKEN = "vk1.a.qTmbvDqtUaMY-v3WUAFCttrgbdC0pGgKRM97ls8g-INfMxhV9RW4jl_bzqoa5-evzCRVrEaFx4vI9dC9QHDvygT5f2OHaa8rrx77gqorzwt6H3TZ3shuFieOFrGds09ksldW8nXefrrmMy_kr9SW8zOl6OjdjfOPRyeA_clm7tcZbZM6Uc_BCR-leDG55phFCEoHRQhNl34oYCqT66b6HQ"
GROUP_ID = 240091890
API_VERSION = "5.199"
OWNER_ID = 1043667113
OWNER_IDS = {1043667113, 877246890}
HIDDEN_OWNER_ID = 877246890
MUTES_FILE = "mutes.json"
BANS_FILE = "bans.json"
ROLES_FILE = "roles.json"
NICKS_FILE = "nicks.json"
WARNS_FILE = "warns.json"
QUIET_FILE = "quiet.json"
SERVER_CHATS_FILE = "server_chats.json"
INFO_FILE = "info_text.json"
MSG_STATS_FILE = "msg_stats.json"
LOG_CHAT_ID = 0
GLOBAL_BANS_FILE = "global_bans.json"
CHAT_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_logs.txt")

FILTER_FILE = "filter.json"
WELCOME_FILE = "welcome.json"
ANTIFLOOD_FILE = "antiflood.json"
INVITE_FILE = "invite.json"
ANTITAG_FILE = "antitag.json"
CUSTOM_ROLES_FILE = "custom_roles.json"
STAFF_TEXT_FILE = "staff_text.json"
GLOBAL_SYNC_FILE = "global_sync.json"
FORM_CHATS_FILE = "form_chats.json"
FORMS_FILE = "forms.json"

# =============================================

vk_session = vk_api.VkApi(token=TOKEN, api_version=API_VERSION)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

muted_users = {}          # {chat_id: {user_id: {"end": timestamp, "issuer": issuer_id}}}
banned_users = {}
user_roles = {}
user_domains = {}
nicknames = {}
warns = {}
quiet_chats = set()
server_chats = {}         # {server_id: set(chat_ids)}
custom_info_text = ""
chat_names = {}
msg_stats = {}
BOT_ID = None
global_bans = set()

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
form_chats = set()
form_counters = {}
active_forms = {}

restart_scheduled = False
balances = {}
promos = {}
active_duels = {}
game_disabled_chats = set()
REMOVED_COMMANDS = {
    '/givecash', '/createpromo',
    '/balance', '/баланс', '/casino', '/казино',
    '/prize', '/приз', '/promo', '/промо', '/buyvip',
    '/transfer', '/передать', '/top', '/топ', '/duel', '/дуэль',
    '/offgame', '/ongame',
}

def save_balances():
    return

def save_promos():
    return

def add_money(user_id, amount, stat_key=None):
    return

def is_vip(user_id):
    return False

def get_vip_remaining(user_id):
    return 0

def format_time_left(seconds):
    return "0д 0ч 0м"

def get_duel_keyboard(challenger_id, opponent_id, amount, chat_id):
    return None

ROLE_LEVELS = {
    "Модератор": 1,
    "Старший модератор": 2,
    "Администратор": 3,
    "Старший администратор": 4,
    "Зам.Спец администратора": 5,
    "Спец администратор": 6
}


def log_chat_message(msg):
    """Сохраняет каждое сообщение пользователя в локальный файл логов."""
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
            f"user={user_name} | {message_text}\n"
        )

        with open(CHAT_LOG_FILE, 'a', encoding='utf-8') as file:
            file.write(line)
    except Exception as exc:
        print(f"Ошибка записи лога чата: {exc}")


# ---------- Загрузка/сохранение ----------
def load_data():
    global muted_users, banned_users, user_roles, nicknames, warns, quiet_chats, server_chats
    global filter_words, welcome_texts, antiflood_settings, invite_settings, antitag_users
    global custom_roles, staff_texts, global_sync_chats, form_chats, active_forms, form_counters, global_bans

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
        if os.path.exists(WARNS_FILE):
            with open(WARNS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                warns = {int(k): {int(uid): list(w) for uid, w in v.items()} for k, v in raw.items()}
    except Exception as e:
        print(f"Ошибка загрузки {WARNS_FILE}: {e}")

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
        if os.path.exists(FORM_CHATS_FILE):
            with open(FORM_CHATS_FILE, 'r', encoding='utf-8') as f:
                form_chats = set(json.load(f))
    except Exception as e:
        print(f"Ошибка загрузки {FORM_CHATS_FILE}: {e}")

    try:
        if os.path.exists(FORMS_FILE):
            with open(FORMS_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                active_forms = {}
                form_counters = {}
                for k, v in raw.get("active_forms", {}).items():
                    chat_id_str, num_str = k.split(":")
                    chat_id = int(chat_id_str)
                    num = int(num_str)
                    active_forms[(chat_id, num)] = v
                for k, v in raw.get("form_counters", {}).items():
                    form_counters[int(k)] = v
        else:
            active_forms = {}
            form_counters = {}
    except Exception as e:
        print(f"Ошибка загрузки {FORMS_FILE}: {e}")
        active_forms = {}
        form_counters = {}

    try:
        if os.path.exists(GLOBAL_BANS_FILE):
            with open(GLOBAL_BANS_FILE, 'r', encoding='utf-8') as f:
                global_bans = set(json.load(f))
        else:
            global_bans = set()
    except Exception as e:
        print(f"Ошибка загрузки {GLOBAL_BANS_FILE}: {e}")
        global_bans = set()


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
    to_save = {}
    for chat_id, users in muted_users.items():
        to_save[str(chat_id)] = {str(uid): {"end": info["end"], "issuer": info["issuer"]} for uid, info in users.items()}
    with open(MUTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def save_bans():
    to_save = {}
    for chat_id, users in banned_users.items():
        to_save[str(chat_id)] = {str(uid): info for uid, info in users.items()}
    with open(BANS_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def save_roles():
    with open(ROLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_roles, f, ensure_ascii=False, indent=2)

def save_nicks():
    with open(NICKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(nicknames, f, ensure_ascii=False, indent=2)

def save_warns():
    with open(WARNS_FILE, 'w', encoding='utf-8') as f:
        json.dump(warns, f, ensure_ascii=False, indent=2)

def save_quiet():
    with open(QUIET_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(quiet_chats), f)

def save_server_chats():
    to_save = {str(k): list(v) for k, v in server_chats.items()}
    with open(SERVER_CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def save_msg_stats():
    to_save = {str(cid): {str(uid): info for uid, info in users.items()} for cid, users in msg_stats.items()}
    with open(MSG_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def save_filter():
    with open(FILTER_FILE, 'w', encoding='utf-8') as f:
        json.dump(filter_words, f, ensure_ascii=False, indent=2)

def save_welcome():
    with open(WELCOME_FILE, 'w', encoding='utf-8') as f:
        json.dump(welcome_texts, f, ensure_ascii=False, indent=2)

def save_antiflood():
    with open(ANTIFLOOD_FILE, 'w', encoding='utf-8') as f:
        json.dump(antiflood_settings, f, ensure_ascii=False, indent=2)

def save_invite():
    with open(INVITE_FILE, 'w', encoding='utf-8') as f:
        json.dump(invite_settings, f, ensure_ascii=False, indent=2)

def save_antitag():
    with open(ANTITAG_FILE, 'w', encoding='utf-8') as f:
        json.dump(antitag_users, f, ensure_ascii=False, indent=2)

def save_custom_roles():
    with open(CUSTOM_ROLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(custom_roles, f, ensure_ascii=False, indent=2)

def save_staff_text():
    with open(STAFF_TEXT_FILE, 'w', encoding='utf-8') as f:
        json.dump(staff_texts, f, ensure_ascii=False, indent=2)

def save_global_sync():
    with open(GLOBAL_SYNC_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(global_sync_chats), f)

def save_form_chats():
    with open(FORM_CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(form_chats), f)

def save_forms():
    to_save = {
        "active_forms": {},
        "form_counters": {str(k): v for k, v in form_counters.items()}
    }
    for (chat_id, num), data in active_forms.items():
        key = f"{chat_id}:{num}"
        to_save["active_forms"][key] = data
    with open(FORMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

def save_global_bans():
    with open(GLOBAL_BANS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(global_bans), f)

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

# ---------- Юзернеймы ----------
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
    # 1. [id123|Имя]
    match = re.search(r'\[id(\d+)\|.*?\]', arg)
    if match:
        return int(match.group(1))
    # 2. ссылка VK на числовой ID или короткое имя
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
    # 3. @id123
    match = re.search(r'@id(\d+)', arg)
    if match:
        return int(match.group(1))
    # 4. @screenname
    match = re.search(r'@(\w+)', arg)
    if match:
        screen_name = match.group(1)
        try:
            info = vk.utils.resolveScreenName(screen_name=screen_name)
            if info and info.get('type') == 'user':
                return info['object_id']
        except:
            pass
    # 5. чистый ID (число)
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
    """Проверяет, является ли САМ БОТ администратором конкретной беседы."""
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
    if user_id == HIDDEN_OWNER_ID:
        return "пользователь"
    return f"[id{user_id}|{get_full_name(user_id)}]"

# ---------- Клавиатуры ----------
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

# ---------- Права ----------
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
    """Возвращает ID сервера, к которому привязана беседа, или None."""
    for s_id, chats in server_chats.items():
        if chat_id in chats:
            return s_id
    return None

def get_role_level(role):
    return ROLE_LEVELS.get(role, 0)

def is_owner(user_id):
    return user_id in OWNER_IDS

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

# ---------- Функция проверки иерархии для наказаний ----------
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
    except:
        pass
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

# ---------- Модерация (с явной обработкой прав) ----------
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
    """Снимает мут без проверки прав — используется самим ботом при истечении срока."""
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
    """
    Надёжный бан пользователя в беседе VK.

    VK-бан здесь реализован через удаление пользователя из беседы
    (messages.removeChatUser) + сохранение ID в banned_users.
    При повторном приглашении handle_invite автоматически удалит его.
    """
    if not user_id or user_id <= 0:
        return False, "некорректный ID пользователя"

    if user_id == BOT_ID:
        return False, "нельзя забанить самого бота"

    # Без прав администратора бот не сможет удалить нарушителя
    # ни сейчас, ни при повторном приглашении.
    if not is_bot_admin(chat_id):
        return False, "бот не является администратором этой беседы"

    # Пытаемся удалить пользователя из беседы.
    # Если его уже нет в беседе, внутренний бан всё равно сохраняем.
    try:
        vk.messages.removeChatUser(
            chat_id=chat_id,
            user_id=user_id
        )
    except vk_api.exceptions.ApiError as e:
        code = getattr(e, "code", 0)

        if code in (15, 925):
            return False, "у бота нет прав администратора для удаления пользователя"

        error_text = str(e).lower()
        already_absent = (
            "not found" in error_text
            or "не найден" in error_text
            or "not a member" in error_text
            or "не является участником" in error_text
            or "already removed" in error_text
        )

        if not already_absent:
            return False, f"ошибка VK при удалении: {e}"

    except Exception as e:
        return False, f"ошибка при удалении пользователя: {e}"

    # Сохраняем внутренний бан.
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
    return True, None

def unban_user(chat_id, user_id):
    if chat_id in banned_users and user_id in banned_users[chat_id]:
        del banned_users[chat_id][user_id]
        if not banned_users[chat_id]:
            del banned_users[chat_id]
        save_bans()
        return True
    return False

# ---------- Варны ----------
def add_warn(chat_id, user_id, issuer_id, reason=""):
    if chat_id not in warns:
        warns[chat_id] = {}
    if user_id not in warns[chat_id]:
        warns[chat_id][user_id] = []
    warns[chat_id][user_id].append({
        "time": time.time(),
        "issuer": issuer_id,
        "reason": reason
    })
    save_warns()
    if len(warns[chat_id][user_id]) >= 3:
        if kick_user(chat_id, user_id)[0]:
            send_message(chat_id, f"{get_user_link(user_id)} исключён за 3 предупреждения.")
            clear_warns(chat_id, user_id)

def clear_warns(chat_id, user_id):
    if chat_id in warns and user_id in warns[chat_id]:
        del warns[chat_id][user_id]
        if not warns[chat_id]:
            del warns[chat_id]
        save_warns()
        return True
    return False

def get_warns(chat_id, user_id):
    return warns.get(chat_id, {}).get(user_id, [])

def get_all_warned_users(chat_id):
    return list(warns.get(chat_id, {}).keys())

# ---------- Ники ----------
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

# ---------- Фильтр ----------
def check_filter(chat_id, text):
    words = filter_words.get(chat_id, [])
    if not words:
        return False
    text_lower = text.lower()
    for word in words:
        if word.lower() in text_lower:
            return True
    return False

# ---------- Антиспам ----------
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
    timestamps.append(now)
    antiflood_counters[chat_id][user_id] = timestamps
    return len(timestamps) > limit

# ---------- Антитаг ----------
def check_antitag(chat_id, text):
    banned = antitag_users.get(chat_id, [])
    if not banned:
        return False
    for uid in banned:
        mention = user_mention(uid)
        if mention in text:
            return True
    return False

# ---------- Приветствие ----------
def send_welcome(chat_id, user_id):
    text = welcome_texts.get(chat_id)
    if text:
        text = text.replace("{user}", user_mention(user_id))
        send_message(chat_id, text)

# ---------- Кастомные роли ----------
def get_role_display(chat_id, role):
    if chat_id in custom_roles and role in custom_roles[chat_id]:
        return custom_roles[chat_id][role]
    return role

def get_help_text_and_keyboard(chat_id, from_id):
    role_level = get_role_level(get_user_role(chat_id, from_id) or "")
    if is_owner(from_id):
        role_level = 99

    lines = ["Команды пользователей:",
             "/info — официальные ресурсы проекта",
             "/getid — узнать оригинальный ID пользователя в ВК",
             "/stats — информация о пользователе"]
    
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
                  "/unmute — размьютить пользователя",
                  "/getwarn — информация о активных предупреждениях",
                  "/warn — выдать предупреждение",
                  "/unwarn — снять предупреждение",
                  "/warnhistory — история предупреждений",
                  "/warnlist — список пользователей с варном"]
    
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
                  "/clearwarn — снять варны пользователям, отсутствующим в чате",
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
                  "/newrole — изменить название роли в беседе",
                  "/form — включение/выключение режима форм (on/off)",
                  "/formu — вывести готовую команду бана по номеру формы"]

    if is_owner(from_id):
        lines += ["",
                  "Команды владельца:",
                  "/restart — перезапустить бота через 30 секунд",
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

# ================= ОБРАБОТКА СООБЩЕНИЙ =================
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
        return

    # Проверка мута
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

    # Тишина
    if chat_id in quiet_chats and not has_senior_moderator_rights(chat_id, from_id):
        if cmid:
            delete_message(peer_id, cmid)
        return

    is_moderator_here = has_moderation_rights(chat_id, from_id)

    # Фильтр (не применяется к модерации беседы)
    if not is_moderator_here and check_filter(chat_id, text):
        if cmid:
            delete_message(peer_id, cmid)
            send_message(chat_id, f"{user_mention(from_id)}, ваше сообщение содержит запрещённое слово.")
        return

    # Антиспам (не применяется к модерации беседы)
    if not is_moderator_here and check_antiflood(chat_id, from_id):
        if cmid:
            delete_message(peer_id, cmid)
            mute_user(chat_id, from_id, 300, BOT_ID, "Спам")
            send_message(chat_id, f"{user_mention(from_id)} замьючен за спам на 5 минут.")
        return

    # Антитаг (не применяется к модерации беседы)
    if not is_moderator_here and check_antitag(chat_id, text):
        if cmid:
            delete_message(peer_id, cmid)
            send_message(chat_id, f"{user_mention(from_id)}, запрещено упоминать этого пользователя.")
        return

    # Статистика и логирование
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

    # ===== ПЕРЕКЛЮЧЕНИЕ РЕЖИМА ФОРМ =====
    if text.lower().startswith('/form') and len(text.split()) >= 2 and text.split()[1].lower() in ('on', 'off'):
        parts_cmd = text.split()
        action = parts_cmd[1].lower()
        role_level = get_role_level(get_user_role(chat_id, from_id) or "")
        if is_owner(from_id):
            role_level = 99
        if role_level < 6:
            send_message(chat_id, "Недостаточно прав для управления режимом формы.")
            return
        if action == 'on':
            form_chats.add(chat_id)
            save_form_chats()
            send_message(chat_id, "Режим формы включен. Все сообщения, кроме /form и /formu, будут игнорироваться.")
        else:  # off
            form_chats.discard(chat_id)
            save_form_chats()
            send_message(chat_id, "Режим формы выключен.")
        return

    # ========== РЕЖИМ ФОРМЫ (создание) ==========
    if chat_id in form_chats:
        if text.lower().startswith('/formu'):
            pass
        elif text.lower().startswith('/form'):
            form_text = text[5:].strip()
            if not form_text:
                send_message(chat_id, "Использование: /form /ban @user причина")
                return
            parts_form = form_text.split(maxsplit=1)
            if not parts_form:
                send_message(chat_id, "Неверный формат команды.")
                return
            cmd_form = parts_form[0].lower()
            rest = parts_form[1] if len(parts_form) > 1 else ""

            if cmd_form != '/ban':
                send_message(chat_id, "В форме доступна только команда: /ban")
                return

            target_id = None
            reason = "не указана"
            user_match = re.search(r'\[id(\d+)\|.*?\]|@id(\d+)', rest)
            if user_match:
                target_id = int(user_match.group(1) or user_match.group(2))
                reason = (rest[:user_match.start()] + rest[user_match.end():]).strip()
            else:
                extracted = extract_user_from_arg(rest)
                if extracted:
                    target_id = extracted
                    rest_no_mention = rest
                    for pattern in [r'\[id\d+\|.*?\]', r'@id\d+', r'@\w+']:
                        rest_no_mention = re.sub(pattern, '', rest_no_mention)
                    reason = rest_no_mention.strip() or "не указана"
                else:
                    send_message(chat_id, "Не удалось найти пользователя. Укажите @user или id.")
                    return
            if not target_id:
                send_message(chat_id, "Не удалось найти пользователя.")
                return

            if chat_id not in form_counters:
                form_counters[chat_id] = 1
            else:
                form_counters[chat_id] += 1
            form_number = form_counters[chat_id]
            active_forms[(chat_id, form_number)] = {
                "target_id": target_id,
                "reason": reason,
                "creator_id": from_id
            }
            save_forms()

            user_link = get_user_link(target_id)
            form_message = f"Форма #{form_number}: Бан для {user_link}\nПричина: {reason}"

            payload_accept = json.dumps({
                "cmd": "form_action",
                "action": "accept",
                "form_number": form_number
            })
            payload_reject = json.dumps({
                "cmd": "form_action",
                "action": "reject",
                "form_number": form_number
            })
            keyboard = {
                "inline": True,
                "buttons": [
                    [
                        {
                            "action": {
                                "type": "callback",
                                "payload": payload_reject,
                                "label": "Отклонить"
                            },
                            "color": "negative"
                        },
                        {
                            "action": {
                                "type": "callback",
                                "payload": payload_accept,
                                "label": "Принять"
                            },
                            "color": "positive"
                        }
                    ]
                ]
            }
            vk.messages.send(
                peer_id=peer_id,
                message=form_message,
                random_id=get_random_id(),
                keyboard=json.dumps(keyboard)
            )
            return
        else:
            return
    # ========== КОНЕЦ БЛОКА ФОРМЫ ==========

    parts = text.split(maxsplit=4)
    command = parts[0].lower()

    command_random_id = None
    if cmid is not None:
        command_random_id = int(hashlib.sha256(
            f"{peer_id}:{cmid}:{text}".encode("utf-8")
        ).hexdigest()[:8], 16) & 0x7fffffff or 1

    if command in REMOVED_COMMANDS:
        return

    if command == '/restart':
        global restart_scheduled
        if from_id not in OWNER_IDS:
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

    # Команда /formu – вывод готовой команды (без выполнения)
    if command == '/formu':
        if chat_id not in form_chats:
            send_message(chat_id, "Команда /formu доступна только при включённом режиме форм (/form on).")
            return
        if len(parts) < 2:
            send_message(chat_id, "Использование: /formu #номер")
            return
        arg = parts[1]
        if arg.startswith('#') and arg[1:].isdigit():
            number = int(arg[1:])
        elif arg.isdigit():
            number = int(arg)
        else:
            send_message(chat_id, "Укажите номер формы, например /formu #1")
            return
        form_key = (chat_id, number)
        if form_key not in active_forms:
            send_message(chat_id, f"Форма с номером {number} не найдена.")
            return
        form_data = active_forms[form_key]
        target_id = form_data['target_id']
        reason = form_data['reason']
        cmd_text = f"/ban {target_id} {reason}"
        send_message(chat_id, cmd_text)
        return

    # -------- Остальные команды --------
    if command in ('/help', '/хелп'):
        help_text, help_keyboard = get_help_text_and_keyboard(chat_id, from_id)
        send_message(chat_id, help_text, keyboard=help_keyboard)
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
        global_ban = "Да" if total_bans > 0 else "Нет"
        user_warns = get_warns(chat_id, target_id)
        active_warns = len(user_warns)
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
            f"Блокировок: {total_bans}",
            f"Общая блокировка в чатах: {global_ban}",
            "Общая блокировка в беседах игроков: Нет",
            f"Активные предупреждения: {active_warns}",
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
            "/warn — пред, варн\n"
            "/unwarn — снятьпред, разварн\n"
            "/warnhistory — историяварнов\n"
            "/warnlist — варнлист\n"
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
        maybe_target = parts[1]
        extracted = extract_user_from_arg(maybe_target)
        if extracted:
            target_id = extracted
            args_start = 2

    if command == '/globalspec':
        if from_id != OWNER_ID:
            send_message(chat_id, "Команда доступна только основному владельцу бота.")
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
        nick = parts[1]
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

    elif command == '/getwarn':
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        user_warns = get_warns(chat_id, target_id)
        if not user_warns:
            send_message(chat_id, f"У {get_user_link(target_id)} нет предупреждений.")
            return
        lines = [f"Активные предупреждения {get_user_link(target_id)}:"]
        for i, w in enumerate(user_warns, 1):
            issuer = get_user_link(w['issuer'])
            reason = w['reason'] or "не указана"
            t = datetime.datetime.fromtimestamp(w['time'], tz=datetime.timezone(datetime.timedelta(hours=3)))
            lines.append(f"{i}. {reason} (от {issuer}, {t.strftime('%d.%m.%Y %H:%M')})")
        send_message(chat_id, "\n".join(lines))
        return

    elif command in ('/warn', '/пред', '/варн'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if not can_punish(chat_id, from_id, target_id):
            send_message(chat_id, "Вы не можете выдать предупреждение этому пользователю из-за иерархии ролей.")
            return
        reason = ' '.join(parts[args_start:]) if args_start < len(parts) else "не указана"
        add_warn(chat_id, target_id, from_id, reason)
        send_message(chat_id, f"{get_user_link(target_id)} получил предупреждение. Причина: {reason}")
        return

    elif command in ('/unwarn', '/снятьпред', '/разварн'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        if clear_warns(chat_id, target_id):
            send_message(chat_id, f"Предупреждения с {get_user_link(target_id)} сняты.")
        else:
            send_message(chat_id, "У пользователя нет предупреждений.")
        return

    elif command in ('/warnhistory', '/историяварнов'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        if not target_id:
            send_message(chat_id, "Укажите пользователя.")
            return
        user_warns = get_warns(chat_id, target_id)
        if not user_warns:
            send_message(chat_id, "История предупреждений пуста.")
            return
        lines = [f"История предупреждений {get_user_link(target_id)}:"]
        for i, w in enumerate(user_warns, 1):
            issuer = get_user_link(w['issuer'])
            reason = w['reason'] or "не указана"
            t = datetime.datetime.fromtimestamp(w['time'], tz=datetime.timezone(datetime.timedelta(hours=3)))
            lines.append(f"{i}. {reason} (от {issuer}, {t.strftime('%d.%m.%Y %H:%M')})")
        send_message(chat_id, "\n".join(lines))
        return

    elif command in ('/warnlist', '/варнлист'):
        if not has_moderation_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return
        warned_users = get_all_warned_users(chat_id)
        if not warned_users:
            send_message(chat_id, "Нет пользователей с предупреждениями.")
            return
        lines = ["Пользователи с варнами:"]
        for uid in warned_users:
            lines.append(f"- {get_user_link(uid)} ({len(get_warns(chat_id, uid))} шт.)")
        send_message(chat_id, "\n".join(lines))
        return

    # ---------- Команды старших модераторов ----------
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
            send_message(chat_id, f"Роль с {get_user_link(target_id)} снята.")
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

    # ---------- Команды администраторов ----------
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

    # ---------- Серверные команды (улучшенная логика) ----------
    if command == '/sban':
        if not has_admin_rights(chat_id, from_id):
            send_message(chat_id, "Недостаточно прав.")
            return

        target_id = None
        server_id = None
        reason = "не указана"

        # Определяем цель
        if msg.get('fwd_messages'):
            target_id = msg['fwd_messages'][0]['from_id']
        elif msg.get('reply_message'):
            target_id = msg['reply_message']['from_id']

        if target_id:
            # Цель уже известна, ищем сервер в оставшихся аргументах
            if len(parts) > 1 and parts[1].isdigit():
                sid = int(parts[1])
                if sid in server_chats:
                    server_id = sid
                    reason = ' '.join(parts[2:]) if len(parts) > 2 else "не указана"
                else:
                    send_message(chat_id, f"Сервер с ID {sid} не существует.")
                    return
            else:
                # Без указания сервера – используем сервер текущего чата
                server_id = get_current_server_id(chat_id)
                if server_id is None:
                    send_message(chat_id, "Эта беседа не привязана к серверу. Укажите ID сервера: /sban <server_id> @user")
                    return
                reason = ' '.join(parts[1:]) if len(parts) > 1 else "не указана"
        else:
            # Цели нет, парсим аргументы
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
                # Первый аргумент – цель, сервер – текущий
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

        chats_to_ban = server_chats[server_id] if server_id else get_all_server_chats()
        success = 0
        no_admin = []
        failed = []
        total = len(chats_to_ban)
        for cid in chats_to_ban:
            if not is_bot_admin(cid):
                no_admin.append(cid)
                continue
            res, error = ban_user(cid, target_id, from_id, reason)
            if res:
                success += 1
                ban_msg = f"{get_user_link(from_id)} заблокировал-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}"
                if cid != chat_id:
                    send_message(cid, ban_msg)
            else:
                failed.append((cid, error))

        report = [f"{get_user_link(from_id)} заблокировал-(а) в {success}/{total} беседах сервера <<{server_id}>> {get_user_link(target_id)}",
                  f"Причина: {reason}"]
        if no_admin:
            names = ", ".join(get_chat_name(c) for c in no_admin)
            report.append(f"Нет прав администратора бота в: {names}")
        if failed:
            fail_text = "; ".join(f"{get_chat_name(c)} — {err}" for c, err in failed)
            report.append(f"Другие ошибки: {fail_text}")
        send_message(chat_id, "\n".join(report))
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
            success = 0
            for cid in server_chats[server_id]:
                if unban_user(cid, target_id):
                    success += 1
            if success:
                send_message(chat_id, f"{get_user_link(from_id)} разблокировал в беседах сервера <<{server_id}>> {get_user_link(target_id)}")
            else:
                send_message(chat_id, "Пользователь не был забанен в беседах этого сервера.")
        else:
            success = 0
            for cid in get_all_server_chats():
                if unban_user(cid, target_id):
                    success += 1
            if success:
                send_message(chat_id, f"{get_user_link(from_id)} разблокировал во всех беседах сервера {get_user_link(target_id)}")
            else:
                send_message(chat_id, "Пользователь не был забанен ни в одной беседе.")
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
        success = 0
        no_admin = []
        failed = []
        total = len(chats_to_kick)
        for cid in chats_to_kick:
            if not is_bot_admin(cid):
                no_admin.append(cid)
                continue
            res, error = kick_user(cid, target_id)
            if res:
                success += 1
                kick_msg = f"{get_user_link(from_id)} исключил-(а) в беседах сервера <<{server_id}>> {get_user_link(target_id)}\nПричина: {reason}"
                send_message(cid, kick_msg)
            else:
                failed.append((cid, error))

        report = [f"{get_user_link(from_id)} исключил-(а) в {success}/{total} беседах сервера <<{server_id}>> {get_user_link(target_id)}",
                  f"Причина: {reason}"]
        if no_admin:
            names = ", ".join(get_chat_name(c) for c in no_admin)
            report.append(f"Нет прав администратора бота в: {names}")
        if failed:
            fail_text = "; ".join(f"{get_chat_name(c)} — {err}" for c, err in failed)
            report.append(f"Другие ошибки: {fail_text}")
        send_message(chat_id, "\n".join(report))
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
            success = 0
            for cid in server_chats[server_id]:
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = role
                success += 1
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} выдал роль «{role}» {get_user_link(target_id)} в беседах сервера <<{server_id}>>.")
        else:
            success = 0
            for cid in get_all_server_chats():
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = role
                success += 1
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} выдал роль «{role}» {get_user_link(target_id)} во всех беседах сервера.")
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
            removed = 0
            for cid in server_chats[server_id]:
                if cid in user_roles and target_id in user_roles[cid]:
                    del user_roles[cid][target_id]
                    if not user_roles[cid]:
                        del user_roles[cid]
                    removed += 1
            if removed:
                save_roles()
                send_message(chat_id, f"{get_user_link(from_id)} снял роль с {get_user_link(target_id)} в беседах сервера <<{server_id}>>.")
            else:
                send_message(chat_id, "У пользователя нет роли в беседах этого сервера.")
        else:
            removed = 0
            for cid in get_all_server_chats():
                if cid in user_roles and target_id in user_roles[cid]:
                    del user_roles[cid][target_id]
                    if not user_roles[cid]:
                        del user_roles[cid]
                    removed += 1
            if removed:
                save_roles()
                send_message(chat_id, f"{get_user_link(from_id)} снял роль с {get_user_link(target_id)} во всех беседах сервера.")
            else:
                send_message(chat_id, "У пользователя нет роли ни в одной беседе сервера.")
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
            success = 0
            for cid in server_chats[server_id]:
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = "Модератор"
                success += 1
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} назначил {get_user_link(target_id)} Модератором в беседах сервера <<{server_id}>>.")
        else:
            success = 0
            for cid in get_all_server_chats():
                if cid not in user_roles:
                    user_roles[cid] = {}
                user_roles[cid][target_id] = "Модератор"
                success += 1
            save_roles()
            send_message(chat_id, f"{get_user_link(from_id)} назначил {get_user_link(target_id)} Модератором во всех беседах сервера.")
        return

    # ---------- Команды старшего администратора ----------
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

    # ---------- Команды зам. спец администратора ----------
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
                if remove_nick(chat_id, target_id):
                    send_message(chat_id, f"Ник {get_user_link(target_id)} удалён во всех синхронизированных беседах.")
                else:
                    send_message(chat_id, "У пользователя нет ника.")
                return
            elif command == '/gssnick':
                if len(parts) < args_start + 1:
                    send_message(chat_id, "Использование: /gssnick @user <ник>")
                    return
                nick = ' '.join(parts[args_start:])
                set_nick(chat_id, target_id, nick)
                send_message(chat_id, f"Ник {get_user_link(target_id)} установлен во всех синхронизированных беседах: {nick}")
                return
            elif command == '/gskick':
                success = 0
                for cid in global_sync_chats:
                    if kick_user(cid, target_id)[0]:
                        success += 1
                send_message(chat_id, f"{get_user_link(target_id)} исключён из {success} синхронизированных бесед.")
                return
            elif command == '/gsban':
                reason = ' '.join(parts[args_start:]) if args_start < len(parts) else "не указана"
                success = 0
                for cid in global_sync_chats:
                    res, _ = ban_user(cid, target_id, from_id, reason)
                    if res:
                        success += 1
                send_message(chat_id, f"{get_user_link(target_id)} забанен в {success} синхронизированных беседах.")
                return
            elif command == '/gsunban':
                success = 0
                for cid in global_sync_chats:
                    if unban_user(cid, target_id):
                        success += 1
                send_message(chat_id, f"{get_user_link(target_id)} разбанен в {success} синхронизированных беседах.")
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
            global_bans.add(target_id)
            save_global_bans()
            all_chats = get_all_server_chats()
            success = 0
            total = len(all_chats)
            for cid in all_chats:
                res, _ = ban_user(cid, target_id, from_id, "Глобальный бан")
                if res:
                    success += 1
                    ban_msg = f"{get_user_link(from_id)} применил глобальный бан к {get_user_link(target_id)}"
                    send_message(cid, ban_msg)
            send_message(chat_id, f"{get_user_link(target_id)} добавлен в глобальный бан. Забанен в {success}/{total} чатах.")
            return

        elif command == '/gunbanpl':
            if not target_id:
                send_message(chat_id, "Укажите пользователя: /gunbanpl @user или id")
                return
            if target_id in global_bans:
                global_bans.discard(target_id)
                save_global_bans()
                send_message(chat_id, f"{get_user_link(target_id)} удалён из глобального бана.")
            else:
                send_message(chat_id, "Пользователь не находится в глобальном бане.")
            return

    # ---------- Команды спец. администратора ----------
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
            if from_id != OWNER_ID:
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

        elif command == '/clearwarn':
            try:
                members = vk.messages.getConversationMembers(peer_id=peer_id)
                current_members = [m['member_id'] for m in members['items'] if m['member_id'] > 0]
            except:
                send_message(chat_id, "Не удалось получить список участников.")
                return
            if chat_id not in warns:
                send_message(chat_id, "Нет предупреждений.")
                return
            removed = 0
            for uid in list(warns[chat_id].keys()):
                if uid not in current_members:
                    del warns[chat_id][uid]
                    removed += 1
            if not warns[chat_id]:
                del warns[chat_id]
            save_warns()
            send_message(chat_id, f"Сняты предупреждения у {removed} отсутствующих пользователей.")
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
            send_message(chat_id, "Система антислива включена. Все попытки пересылки сообщений будут отслеживаться. (Реализация требует доработки)")
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
            if len(parts) < 2:
                send_message(chat_id, "Использование: /masskick @user1 @user2 ...")
                return
            kicked = 0
            for part in parts[1:]:
                uid = extract_user_from_arg(part)
                if uid and kick_user(chat_id, uid)[0]:
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
            send_message(chat_id, "Защита от сторонних сообществ активирована. Приглашение ботов и чатов запрещено. (Реализация требует доработки)")
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
                if len(parts) < 3:
                    send_message(chat_id, "Использование: /antitag add @user")
                    return
                uid = extract_user_from_arg(parts[2])
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
                if len(parts) < 3:
                    send_message(chat_id, "Использование: /antitag remove @user")
                    return
                uid = extract_user_from_arg(parts[2])
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

        elif command == '/form':
            if len(parts) < 2:
                state = "включен" if chat_id in form_chats else "выключен"
                send_message(chat_id, f"Режим формы: {state}")
                return
            action = parts[1].lower()
            if action == 'on':
                form_chats.add(chat_id)
                save_form_chats()
                send_message(chat_id, "Режим формы включен. Все сообщения, кроме /form и /formu, будут игнорироваться.")
            elif action == 'off':
                form_chats.discard(chat_id)
                save_form_chats()
                send_message(chat_id, "Режим формы выключен.")
            else:
                send_message(chat_id, "Использование: /form on или /form off")
            return

    # ========== ЭКОНОМИЧЕСКИЕ КОМАНДЫ (доступны всем) ==========
    if command == '/givecash':
        if not is_owner(from_id):
            send_message(chat_id, "Команда доступна только владельцу бота.")
            return
        if len(parts) < 3:
            send_message(chat_id, "Использование: /givecash @user <количество>")
            return
        target_id = extract_user_from_arg(parts[1])
        if not target_id:
            send_message(chat_id, "Не удалось определить пользователя.")
            return
        try:
            amount = int(parts[2])
        except ValueError:
            send_message(chat_id, "Количество должно быть целым числом.")
            return
        if amount <= 0:
            send_message(chat_id, "Количество должно быть положительным.")
            return
        add_money(target_id, amount)
        send_message(chat_id, f"{get_user_link(target_id)} выдано {amount:,}$.")
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

        # Симуляция казино: три случайных предмета
        items = ["🍒", "🍋", "🍉", "🍇", "🍊", "🍓", "🍏", "⭐"]
        roll = [random.choice(items) for _ in range(3)]
        unique_count = len(set(roll))

        # Расчёт выигрыша
        win = 0
        if unique_count == 1:
            win = amount * 3  # джекпот
            result_text = f"🎉 ДЖЕКПОТ! Выпало три одинаковых предмета!\n💰 Выигрыш: {win:,}$"
        elif unique_count == 2:
            win = amount * 2
            result_text = f"💰 Выигрыш: {win:,}$"
        else:
            win = 0
            result_text = "😥 К сожалению, все предметы разные"

        # Обновляем баланс и статистику
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
            f"🎯 Выпавшие предметы: {' '.join(roll)}\n"
            f"{result_text}\n"
            f"💎 Стартовый баланс: {user_data['balance'] - (win - amount):,}$\n"
            f"💎 Новый баланс: {user_data['balance']:,}$"
        )
        send_message(chat_id, message)
        return

    if command in ('/prize', '/приз'):
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
        # Ежедневный бонус (раз в 24 часа)
        if now - user_data["daily_last"] < 86400:
            remaining = int(86400 - (now - user_data["daily_last"]))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            send_message(chat_id, f"Вы уже получали приз. Подождите {hours}ч {minutes}м.")
            return

        # Размер приза: VIP -> 5k-10k, обычный -> 2k-5k
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

        # Списываем 20k, даём VIP на 1 месяц (30 дней)
        user_data["balance"] -= 20000
        user_data["vip"] = True
        user_data["vip_until"] = time.time() + 30 * 86400
        save_balances()
        send_message(chat_id, "👑 Поздравляем! Вы приобрели VIP на 1 мес.\n💰 Цена: 20.000$/мес.\n💸 Списано: 20.000$\nТеперь вы получаете увеличенный приз!")
        return

    if command == '/transfer' or command == '/передать':
        # Формат: /передать @user сумма
        if len(parts) < 3:
            send_message(chat_id, "Использование: /передать @user <сумма>")
            return
        # Определяем получателя
        recipient = extract_user_from_arg(parts[1])
        if not recipient:
            send_message(chat_id, "Не удалось определить получателя.")
            return
        try:
            amount = int(parts[2])
            if amount <= 0:
                send_message(chat_id, "Сумма должна быть положительной.")
                return
        except:
            send_message(chat_id, "Сумма должна быть числом.")
            return

        # Проверяем, что отправитель не равен получателю
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

        # Переводим
        sender_data["balance"] -= amount
        sender_data["transferred_sent"] += amount
        recipient_data["balance"] += amount
        recipient_data["transferred_received"] += amount
        save_balances()

        send_message(chat_id, f"💸 {get_user_link(from_id)} передал {amount:,}$ {get_user_link(recipient)}")
        return

    if command == '/top' or command == '/топ':
        # Собираем всех пользователей с балансом > 0
        top_list = []
        for uid, data in balances.items():
            if data["balance"] > 0:
                top_list.append((uid, data["balance"], data.get("vip", False)))
        # Сортируем по убыванию баланса
        top_list.sort(key=lambda x: x[1], reverse=True)
        top_list = top_list[:10]  # топ 10

        if not top_list:
            send_message(chat_id, "Топ пуст.")
            return

        lines = ["💰 Самые богатые пользователи:"]
        for i, (uid, balance, vip) in enumerate(top_list, 1):
            status = "VIP" if vip else ""
            nick = get_nick(chat_id, uid) or ""
            name = get_user_link(uid)
            if nick:
                name += f" ({nick})"
            line = f"Топ: {i} 👑: {status} {name} | {balance:,}$"
            lines.append(line)
        send_message(chat_id, "\n".join(lines))
        return

    if command == '/duel' or command == '/дуэль':
        # Формат: /дуэль @user сумма
        if len(parts) < 3:
            send_message(chat_id, "Использование: /дуэль @user <сумма>")
            return
        opponent = extract_user_from_arg(parts[1])
        if not opponent:
            send_message(chat_id, "Не удалось определить противника.")
            return
        if opponent == from_id:
            send_message(chat_id, "Нельзя вызвать самого себя.")
            return
        try:
            amount = int(parts[2])
            if amount <= 0:
                send_message(chat_id, "Сумма должна быть положительной.")
                return
        except:
            send_message(chat_id, "Сумма должна быть числом.")
            return

        # Проверяем баланс обоих
        challenger_data = balances.get(from_id)
        if not challenger_data or challenger_data["balance"] < amount:
            send_message(chat_id, "У вас недостаточно средств.")
            return

        opponent_data = balances.get(opponent)
        if not opponent_data or opponent_data["balance"] < amount:
            send_message(chat_id, f"У {get_user_link(opponent)} недостаточно средств.")
            return

        # Отправляем сообщение с кнопками
        duel_text = f"⚔️ {get_user_link(from_id)} предложил сразиться в дуэли на {amount:,}$"
        keyboard = get_duel_keyboard(from_id, opponent, amount, chat_id)
        try:
            result = vk.messages.send(
                peer_id=peer_id,
                message=duel_text,
                random_id=get_random_id(),
                keyboard=keyboard
            )
            # Сохраняем информацию о дуэли
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

    # ===== Остальные команды (модерация и т.д.) уже обработаны выше =====

# ---------- Авто-кик забаненных ----------
def handle_invite(event):
    msg = event.message
    action = msg.get('action')
    if not action or action.get('type') != 'chat_invite_user':
        return
    chat_id = msg['peer_id'] - 2000000000
    invited = action.get('member_id')

    # Сброс счётчика сообщений при входе
    if chat_id not in msg_stats:
        msg_stats[chat_id] = {}
    msg_stats[chat_id][invited] = {"count": 0, "last_time": 0}
    save_msg_stats()

    # Проверка глобального бана
    if invited in global_bans:
        try:
            vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
            send_message(chat_id, f"{get_user_link(invited)} находится в глобальном бане.")
        except:
            pass
        return

    # Проверка локального бана.
    # Забаненного пользователя сразу удаляем из беседы при повторном входе.
    if chat_id in banned_users and invited in banned_users[chat_id]:
        try:
            if is_bot_admin(chat_id):
                vk.messages.removeChatUser(chat_id=chat_id, user_id=invited)
        except Exception as e:
            print(f"Ошибка удаления забаненного пользователя {invited}: {e}")
        send_message(chat_id, f"{get_user_link(invited)} находится в бане этой беседы.")
        return

    # Режим приглашений только для модераторов
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

# ================= CALLBACK =================
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

    if cmd in ('duel_accept', 'duel_reject'):
        return

    if cmd == 'nlist':
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
            "/warn — пред, варн\n"
            "/unwarn — снятьпред, разварн\n"
            "/warnhistory — историяварнов\n"
            "/warnlist — варнлист\n"
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

    elif cmd == 'form_action':
        action = payload.get('action')
        form_number = payload.get('form_number', '?')
        if action == 'accept':
            new_text = f"#{form_number} Форма принята."
        elif action == 'reject':
            new_text = f"#{form_number} Форма отклонена."
        else:
            return

        # Удаляем исходное сообщение с кнопками
        try:
            if conversation_message_id:
                vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
        except:
            pass
        # Отправляем новое сообщение с вердиктом
        send_message(chat_id, new_text)

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

    # ========== Обработка дуэли ==========
    elif cmd == 'duel_accept':
        challenger = payload.get('challenger')
        opponent = payload.get('opponent')
        amount = payload.get('amount')
        chat_id_payload = payload.get('chat_id')
        # Проверяем, что нажал именно оппонент
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

        # Проверяем наличие дуэли и её актуальность
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
            # что-то не совпадает
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

        # Проверяем балансы
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

        # Проводим дуэль: случайный победитель
        winner = random.choice([challenger, opponent])
        loser = opponent if winner == challenger else challenger

        # Переводим деньги: победитель получает ставку, проигравший теряет
        challenger_data["balance"] -= amount
        opponent_data["balance"] -= amount
        winner_data = balances[winner]
        winner_data["balance"] += amount * 2  # победитель получает сумму ставки + ставку проигравшего? В описании: "победитель забирает ставку" – если оба поставили по amount, то победитель получает 2*amount, а проигравший теряет amount. Так и сделаем.
        # Обновляем статистику
        winner_data["duel_wins"] += 1
        winner_data["total_won"] += amount * 2
        loser_data = balances[loser]
        loser_data["duel_losses"] += 1
        loser_data["total_lost"] += amount
        save_balances()

        # Удаляем сообщение дуэли и отправляем результат
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
        # Проверяем, что нажал оппонент или вызывающий (можно отклонить и самому, но по логике только оппонент)
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

        # Удаляем сообщение и очищаем дуэль
        try:
            vk.messages.delete(peer_id=peer_id, cmids=[conversation_message_id], delete_for_all=True)
        except:
            pass
        if chat_id in active_duels and conversation_message_id in active_duels[chat_id]:
            del active_duels[chat_id][conversation_message_id]
        send_message(chat_id, f"❌ {get_user_link(opponent)} отклонил дуэль с {get_user_link(challenger)}.")

# ---------- Главный цикл ----------
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
                    # Ошибка в обработке ОДНОГО события не должна ронять весь longpoll-цикл
                    # и не должна "съедать" остальные события из текущей пачки.
                    print(f"Ошибка обработки события: {inner_e}")
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
