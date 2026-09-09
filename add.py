# ============================================================
#  📦 VIDEO VAULT BOT  —  SINGLE FILE, JSON DATA EDITION
#
#  ✔️ Sab kuch ek hi file me (config + database + bot)
#  ✔️ DATA JSON files me save hota hai → readable + persistent
#       - packs_data.json  (packs + videos)
#       - users_data.json  (users)
#     Bot off/restart ho jaye to bhi data 100% safe rehta hai.
#  ✔️ Owner ka EXACT caption video ke saath deliver hota hai
#  ✔️ STICKER support (upload + delivery)
#  ✔️ Owner-only export/backup commands
#  ✔️ Version-safe (kisi bhi python-telegram-bot version par chalta hai)
#
#  Bas ye 2 cheezein set karo, phir:
#      pip install --upgrade python-telegram-bot
#      python3 add2.py
# ============================================================

# ---------- ⚙️ SETTINGS (yahan edit karo) ----------
BOT_TOKEN = "8726448384:AAFlnrGl2lJYK1yHFocoQkuJpn5BMvC832E"   # @BotFather ka token (123456:ABC...)
OWNER_ID  = 8348667414                 # aapka numeric Telegram user ID
BOT_NAME  = "📦 Video Vault Bot"
CREATOR_NAME = "@kesav86"
SUPPORT_LINK = "https://t.me/@kesav82"

# Data storage files — JSON (alag-alag, persistent, readable)
PACKS_DB = "packs_data.json"        # packs + videos ka data
USERS_DB = "users_data.json"        # users ka data
# ----------------------------------------------------

import json
import os
import uuid
import threading
import logging
import io
import csv
from datetime import datetime
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from telegram.ext.filters import MessageFilter

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.CRITICAL,   # ⬅️ print BILKUL band — kuch bhi print nahi hoga
)
log = logging.getLogger(__name__)
# third-party (telegram / httpx) ke noisy logs bhi band — terminal bilkul clean
logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

_now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ============================================================
#  JSON DATABASE (readable + persistent, atomic writes)
# ============================================================
_lock = threading.Lock()


def _load(db_file, default):
    if os.path.exists(db_file):
        try:
            with open(db_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _write(db_file, data):
    """Atomic save: pehle temp file, phir replace — data kabi corrupt nahi hoga."""
    tmp = db_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, db_file)


def init_db():
    with _lock:
        if not os.path.exists(PACKS_DB):
            _write(PACKS_DB, {"packs": {}})
        if not os.path.exists(USERS_DB):
            _write(USERS_DB, {"users": {}})


# ------------- PACKS + VIDEOS -------------
def create_pack(title="My Videos"):
    token = uuid.uuid4().hex[:10]
    with _lock:
        data = _load(PACKS_DB, {"packs": {}})
        data["packs"][token] = {
            "title": title,
            "created_at": _now(),
            "videos": [],
        }
        _write(PACKS_DB, data)
    return token


def get_pack(token):
    data = _load(PACKS_DB, {"packs": {}})
    p = data["packs"].get(token)
    if not p:
        return None
    return {"token": token, "title": p["title"], "created_at": p["created_at"]}


def list_packs():
    data = _load(PACKS_DB, {"packs": {}})
    packs = []
    for token, p in data["packs"].items():
        packs.append({
            "token": token,
            "title": p["title"],
            "created_at": p["created_at"],
            "video_count": len(p["videos"]),
        })
    packs.sort(key=lambda x: x["created_at"], reverse=True)
    return packs


def delete_pack(token):
    with _lock:
        data = _load(PACKS_DB, {"packs": {}})
        data["packs"].pop(token, None)
        _write(PACKS_DB, data)


def add_video(token, file_id, file_type, filename="", caption="", order=0):
    with _lock:
        data = _load(PACKS_DB, {"packs": {}})
        p = data["packs"].get(token)
        if p is not None:
            p["videos"].append({
                "file_id": file_id,
                "file_type": file_type,
                "filename": filename,
                "caption": caption,
                "order": order,
            })
            _write(PACKS_DB, data)


def get_videos(token):
    data = _load(PACKS_DB, {"packs": {}})
    p = data["packs"].get(token)
    if not p:
        return []
    return sorted(p["videos"], key=lambda v: v["order"])


def get_video_count(token):
    data = _load(PACKS_DB, {"packs": {}})
    p = data["packs"].get(token)
    return len(p["videos"]) if p else 0


def all_video_count():
    data = _load(PACKS_DB, {"packs": {}})
    return sum(len(p["videos"]) for p in data["packs"].values())


# ------------- USERS -------------
def save_user(user, pack_token=None):
    with _lock:
        data = _load(USERS_DB, {"users": {}})
        uid = str(user.id)
        u = data["users"].get(uid)
        if u:
            u["first_name"] = user.first_name or ""
            u["username"] = user.username or ""
            if pack_token:
                u["packs_opened"] = u.get("packs_opened", 0) + 1
            u["last_active"] = _now()
        else:
            data["users"][uid] = {
                "user_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or "",
                "first_seen": _now(),
                "packs_opened": 1 if pack_token else 0,
                "last_active": _now(),
            }
        _write(USERS_DB, data)


def get_all_users():
    data = _load(USERS_DB, {"users": {}})
    users = list(data["users"].values())
    users.sort(key=lambda u: u.get("first_seen", ""), reverse=True)
    return users


def user_count():
    data = _load(USERS_DB, {"users": {}})
    return len(data["users"])


# ============================================================
#  HELPERS / FILTERS
# ============================================================
def is_owner(update):
    return update.effective_user.id == OWNER_ID


# Version-proof media filter — video/document/photo/audio/sticker/animation
# har library version par kaam karta hai.
class MediaFilter(MessageFilter):
    def filter(self, message):
        return bool(
            getattr(message, "video", None)
            or getattr(message, "document", None)
            or getattr(message, "photo", None)
            or getattr(message, "audio", None)
            or getattr(message, "sticker", None)
            or getattr(message, "animation", None)
        )


MEDIA_FILTER = MediaFilter()


def bold(t): return f"<b>{t}</b>"
def code(t): return f"<code>{t}</code>"


# --- 🌟 BULLETPROOF INLINE KEYBOARD HELPER ---
# Ye error ("text buttons are not allowed") tab aata hai jab kisi inline button
# me koi ACTION field nahi hota (na url, na callback_data). Ye helper har button
# ko check karta hai aur bina-action waale button ko hata deta hai, taaki
# Telegram kabhi bhi ye error na de. "Contact Us" jaisa url button bhi safe hai.
def _has_action(btn):
    return bool(
        btn.url
        or btn.callback_data
        or btn.switch_inline_query
        or btn.switch_inline_query_current_chat
        or btn.login_url
        or btn.web_app
        or btn.callback_game
        or btn.pay
    )


def make_kb(rows):
    """Rows = [[InlineKeyboardButton, ...], ...] -> safe InlineKeyboardMarkup.
    Bina action waale button (ye error dene wale) filter ho jaate hain."""
    clean = [[b for b in row if _has_action(b)] for row in rows]
    clean = [row for row in clean if row]           # khaali rows bhi hatao
    return InlineKeyboardMarkup(clean)

pending_upload = {}   # {token, title, count}


# ============================================================
#  USER FLOW
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user = update.effective_user
    if user:
        save_user(user)

    if args:
        if args[0] == "admin" and is_owner(update):
            return await show_owner_panel(update, context)
        return await deliver_pack(update, context, args[0])

    text = (
        f"👋 <b>Namaste {escape(user.first_name or 'friend')}!</b>\n\n"
        f"Welcome to {bold(BOT_NAME)} 🎥\n"
        f"Yahan premium videos milengi — bilkul free!\n\n"
        f"📌 <i>Neeche button se videos open karein.</i>"
    )
    kb = [[InlineKeyboardButton("🎬 Open Videos", callback_data="open_videos")]]
    if is_owner(update):
        kb.append([InlineKeyboardButton("👑 Owner Panel", callback_data="owner_panel")])
    kb.append([InlineKeyboardButton("📞 Contact Us", url=SUPPORT_LINK)])
    try:
        await update.message.reply_text(text, reply_markup=make_kb(kb), parse_mode=ParseMode.HTML)
    except Exception:
        # Safety: agar keyboard me koi dikkat ho to message BINA keyboard ke bhej do
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def deliver_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    pack = get_pack(token)
    if not pack:
        return await update.message.reply_text(
            "❌ <b>Invalid link!</b>\nYe link ab kaam nahi kar raha ya delete ho chuka hai.",
            parse_mode=ParseMode.HTML)
    videos = get_videos(token)
    if not videos:
        return await update.message.reply_text(
            "📭 Ye pack abhi khaali hai. Jald hi videos add honge.", parse_mode=ParseMode.HTML)

    if update.effective_user:
        save_user(update.effective_user, pack_token=token)

    title = pack["title"]; total = len(videos)
    await update.message.reply_text(
        f"🎬 <b>{escape(title)}</b>\n📦 Kull <b>{total}</b> item milenge.\n⏳ <i>Load ho rahe hain...</i>",
        parse_mode=ParseMode.HTML)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

    sent = 0
    for i, v in enumerate(videos, start=1):
        try:
            ftype = v.get("file_type", "video")
            f_id = v["file_id"]
            cap = v.get("caption", "") or None        # <-- EXACT caption owner ka
            if ftype == "document":
                await context.bot.send_document(update.effective_chat.id, f_id, caption=cap)
            elif ftype == "photo":
                await context.bot.send_photo(update.effective_chat.id, f_id, caption=cap)
            elif ftype == "sticker":
                await context.bot.send_sticker(update.effective_chat.id, f_id)
            elif ftype == "audio":
                await context.bot.send_audio(update.effective_chat.id, f_id, caption=cap)
            else:  # video
                await context.bot.send_video(update.effective_chat.id, f_id, caption=cap)
            sent += 1
        except Exception as e:
            log.warning("send fail %s", e)

    await context.bot.send_message(
        update.effective_chat.id,
        f"✅ <b>Sab ho gaya!</b>\n\n<b>📊 Summary</b>\n📦 Delivered: <b>{sent}/{total}</b>\n"
        f"📦 Pack: {escape(title)}\n\n💜 {escape(BOT_NAME)} • {escape(CREATOR_NAME)}",
        parse_mode=ParseMode.HTML)


async def open_videos_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🎬 <b>Videos</b>\n\nBhai! Videos sirf <b>Start Link</b> se deliver hoti hain.\n\n"
        "👉 Apne dost se <b>Start Link</b> manga lo, ya niche button use karo.",
        parse_mode=ParseMode.HTML)


# ============================================================
#  OWNER PANEL
# ============================================================
async def show_owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    packs = list_packs()
    total_videos = all_video_count()
    users = user_count()
    text = (
        f"👑 <b>OWNER PANEL</b>\n\n"
        f"📊 <b>Stats</b>\n🛠 Packs: <b>{len(packs)}</b>\n🎥 Items: <b>{total_videos}</b>\n"
        f"👤 Users: <b>{users}</b>\n\n"
        f"─── <i>Commands</i> ───\n"
        f"{code('/add')} │ naya pack + upload mode\n"
        f"{code('/mylinks')} │ saare start-links\n"
        f"{code('/deletelink')} │ link delete\n"
        f"{code('/stats')} │ poori info\n"
        f"{code('/exportdata')} │ ⬇️ data file nikaalo\n"
        f"{code('/exportusers')} │ 👥 users file nikaalo\n"
        f"{code('/backup')} │ 💾 full backup (dono files)\n"
        f"{code('/broadcast')} │ sab users ko msg\n"
        f"{code('/cancel')} │ upload mode band"
    )
    kb = [[InlineKeyboardButton("➕ New Pack", callback_data="owner_add")],
          [InlineKeyboardButton("🔗 My Links", callback_data="owner_links")],
          [InlineKeyboardButton("📊 Stats", callback_data="owner_stats")],
          [InlineKeyboardButton("⬇️ Export Data", callback_data="owner_export")],
          [InlineKeyboardButton("💾 Backup", callback_data="owner_backup")],
          [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast")]]
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=make_kb(kb), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=make_kb(kb), parse_mode=ParseMode.HTML)


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    title = " ".join(context.args) if context.args else "My Videos"
    token = create_pack(title)
    pending_upload["token"] = token
    pending_upload["title"] = title
    pending_upload["count"] = 0
    await update.message.reply_text(
        f"🎥 <b>Upload Mode started!</b>\n\nAb items bhejo (video / file / photo / sticker / audio).\n"
        f"📦 Pack: {code(title)}\n🔑 Token: {code(token)}\n\n"
        f"<i>Jitne chaho bhejo — /done karne par start link ban jaayega.</i>\n{code('/cancel')} to cancel.",
        parse_mode=ParseMode.HTML)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    if "token" not in pending_upload:
        return await update.message.reply_text("⚠️ Pehle /add se upload mode kholo.", parse_mode=ParseMode.HTML)
    token = pending_upload.pop("token")
    title = pending_upload.get("title", "My Videos")
    counts = get_video_count(token)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={token}"
    pending_upload.clear()
    await update.message.reply_text(
        f"🎉 <b>Pack Ready!</b>\n\n📦 Title: {bold(title)}\n🎥 Items: <b>{counts}</b>\n\n"
        f"<b>Yeh raha aapka START LINK 👇</b>\n{code(link)}\n\n"
        f"✉️ Ye link kisi ko bhi bhejo — link tap karte hi saari items milengi.\n🡅 /mylinks dekho.",
        parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    pending_upload.clear()
    await update.message.reply_text("✖️ Upload mode cancel.", parse_mode=ParseMode.HTML)


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update) or "token" not in pending_upload:
        return
    token = pending_upload["token"]
    msg = update.message
    caption = msg.caption or ""            # <-- exact owner caption save hota hai
    order = pending_upload.get("count", 0) + 1
    pending_upload["count"] = order

    if getattr(msg, "video", None):
        add_video(token, msg.video.file_id, "video", caption=caption, order=order); fn = "🎥 Video"
    elif getattr(msg, "document", None):
        add_video(token, msg.document.file_id, "document", msg.document.file_name or "", caption, order); fn = "📄 File"
    elif getattr(msg, "photo", None):
        add_video(token, msg.photo[-1].file_id, "photo", caption=caption, order=order); fn = "🖼 Photo"
    elif getattr(msg, "sticker", None):
        add_video(token, msg.sticker.file_id, "sticker", caption="", order=order); fn = "😀 Sticker"
    elif getattr(msg, "audio", None):
        add_video(token, msg.audio.file_id, "audio", caption=caption, order=order); fn = "🎵 Audio"
    else:
        return await msg.reply_text("❌ Sirf video / file / photo / sticker / audio bhejo.", parse_mode=ParseMode.HTML)

    extra = f" • caption: {code(caption)}" if caption else ""
    await msg.reply_text(
        f"{fn} <b>#{order}</b> saved ✅{extra}\nAur bhejo, ya {code('/done')} dabao.", parse_mode=ParseMode.HTML)


async def cmd_mylinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    packs = list_packs()
    if not packs:
        return await update.message.reply_text("📭 Abhi koi pack nahi hai.", parse_mode=ParseMode.HTML)
    me = await context.bot.get_me()
    lines = [f"👑 <b>Your Start Links</b>\n"]
    for i, p in enumerate(packs, 1):
        link = f"https://t.me/{me.username}?start={p['token']}"
        lines.append(f"{i}. <b>{escape(p['title'])}</b>\n    🔗 {code(link)}")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
    kb = [[InlineKeyboardButton(f"🗑 {p['title'][:20]}", callback_data=f"del_{p['token']}")] for p in packs[:20]]
    if kb:
        await update.message.reply_text("🔽 Delete karne ke liye tap karo:",
                                        reply_markup=make_kb(kb), parse_mode=ParseMode.HTML)


async def cmd_deletelink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    if not context.args:
        return await update.message.reply_text("Usage: /deletelink <token>", parse_mode=ParseMode.HTML)
    if not get_pack(context.args[0]):
        return await update.message.reply_text("❌ Ye pack nahi mila.", parse_mode=ParseMode.HTML)
    delete_pack(context.args[0])
    await update.message.reply_text("🗑️ Pack delete ho gaya.", parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    packs = list_packs()
    total = all_video_count()
    users = user_count()
    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} — Stats</b>\n\n🛠 Packs: <b>{len(packs)}</b>\n🎥 Items: <b>{total}</b>\n"
        f"👤 Users: <b>{users}</b>\n👤 Owner: <code>{OWNER_ID}</code>\n\n"
        f"💾 Data files: {code(PACKS_DB)} + {code(USERS_DB)}", parse_mode=ParseMode.HTML)


# ============================================================
#  ⬇️ OWNER EXPORT / BACKUP COMMANDS
# ============================================================
async def cmd_exportdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    await update.message.reply_text("⬇️ Data file nikaal rahi hain...", parse_mode=ParseMode.HTML)
    try:
        with open(PACKS_DB, "rb") as f:
            await update.message.reply_document(
                document=f, filename=PACKS_DB,
                caption=f"💾 <b>Data backup</b>\n📦 Packs+Videos ({PACKS_DB})\nBot off hone par bhi safe.",
                parse_mode=ParseMode.HTML)
    except FileNotFoundError:
        await update.message.reply_text("❌ Data file nahi mili.", parse_mode=ParseMode.HTML)


async def cmd_exportusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    users = get_all_users()
    if not users:
        return await update.message.reply_text("👥 Abhi koi user nahi aaya.", parse_mode=ParseMode.HTML)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["User ID", "First Name", "Username", "First Seen", "Packs Opened", "Last Active"])
    for u in users:
        w.writerow([u["user_id"], u["first_name"], u["username"], u["first_seen"],
                    u["packs_opened"], u["last_active"]])
    data = buf.getvalue().encode("utf-8")
    await update.message.reply_text(f"👥 <b>{len(users)}</b> users mil rahe hain. CSV bhej raha hoon...",
                                    parse_mode=ParseMode.HTML)
    await update.message.reply_document(
        document=io.BytesIO(data), filename="users_list.csv",
        caption=f"👥 <b>USERS LIST</b>\nKull {len(users)} users\n\nData file: {USERS_DB}",
        parse_mode=ParseMode.HTML)


async def cmd_exportusersdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    try:
        with open(USERS_DB, "rb") as f:
            await update.message.reply_document(
                document=f, filename=USERS_DB,
                caption=f"👥 <b>Users file</b> ({USERS_DB})", parse_mode=ParseMode.HTML)
    except FileNotFoundError:
        await update.message.reply_text("❌ Users file nahi mili.", parse_mode=ParseMode.HTML)


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    await update.message.reply_text("💾 <b>Full backup</b> bana raha hoon... (dono files)",
                                    parse_mode=ParseMode.HTML)
    for fname in (PACKS_DB, USERS_DB):
        try:
            with open(fname, "rb") as f:
                await update.message.reply_document(
                    document=f, filename=fname, caption=f"💾 Backup: {fname}", parse_mode=ParseMode.HTML)
        except FileNotFoundError:
            pass
    await update.message.reply_text(
        "✅ <b>Backup complete!</b>\n\n🔹 <i>Packs + videos</i> → packs_data.json\n"
        "🔹 <i>Users</i> → users_data.json\n\n"
        "⚠️ Ye files folder me hain. Kisi safe jagah copy kar lo. Jab wapas chahiye to bot chalao "
        "aur ye files usi folder me rakho.", parse_mode=ParseMode.HTML)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return await no_perm(update)
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Usage: /broadcast <message>", parse_mode=ParseMode.HTML)
    users = get_all_users()
    if not users:
        return await update.message.reply_text("📭 Abhi koi user nahi aaya.", parse_mode=ParseMode.HTML)
    n = 0
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], text, parse_mode=ParseMode.HTML); n += 1
        except Exception:
            pass
    await update.message.reply_text(f"📢 Broadcast: <b>{n}</b> users ko mila.", parse_mode=ParseMode.HTML)


async def no_perm(update: Update):
    await update.message.reply_text(
        "🔒 <b>Access Denied!</b>\nYe command sirf bot owner ke liye hai.", parse_mode=ParseMode.HTML)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    if data == "open_videos":
        await open_videos_cb(update, context)
        return
    if not is_owner(update):
        return await q.answer("Owner only!", show_alert=True)
    await q.answer()
    if data == "owner_panel":
        await show_owner_panel(update, context, edit=True)
    elif data == "owner_add":
        await q.edit_message_text("➕ New Pack — <b>/add</b> likh ke bhejo, ya title ke saath:\n\n" + code("/add My Cool Videos"), parse_mode=ParseMode.HTML)
    elif data == "owner_links":
        await q.edit_message_text("🔗 <b>My Links</b>\n\n" + code("/mylinks") + " command bhalein.", parse_mode=ParseMode.HTML)
    elif data == "owner_stats":
        await q.edit_message_text("📊 <b>Stats</b>\n\n" + code("/stats") + " command bhalein.", parse_mode=ParseMode.HTML)
    elif data == "owner_export":
        await q.edit_message_text(
            "⬇️ <b>Export / Backup</b>\n\n"
            f"{code('/exportdata')} ➜ packs+videos file download\n"
            f"{code('/exportusers')} ➜ users list (CSV) download\n"
            f"{code('/exportusersdb')} ➜ users file download\n"
            f"{code('/backup')} 🡅 dono files ek saath",
            parse_mode=ParseMode.HTML)
    elif data == "owner_backup":
        await cmd_backup(update, context)
    elif data == "owner_broadcast":
        await q.edit_message_text("📢 <b>Broadcast</b>\n\n" + code("/broadcast Your message here"), parse_mode=ParseMode.HTML)
    elif data.startswith("del_"):
        delete_pack(data[4:])
        await q.answer("🗑️ Deleted.", show_alert=True)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.error("error: %s", context.error)


# ============================================================
#  MAIN
# ============================================================
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or OWNER_ID == 123456789:
        log.error("⚠️   TOKEN aur OWNER_ID file ke top par set karo (BOT_TOKEN / OWNER_ID)!")
        raise SystemExit
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("mylinks", cmd_mylinks))
    app.add_handler(CommandHandler("deletelink", cmd_deletelink))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("exportdata", cmd_exportdata))
    app.add_handler(CommandHandler("exportusers", cmd_exportusers))
    app.add_handler(CommandHandler("exportusersdb", cmd_exportusersdb))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(MessageHandler(MEDIA_FILTER, handle_media))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(error_handler)
    log.info("🤖 %s running... (data files: %s , %s)", BOT_NAME, PACKS_DB, USERS_DB)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
