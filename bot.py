import asyncio
import os
import re
import sqlite3
from aiohttp import web
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "9211572979:AAEI73Lq3e1FbtcmiYpQSmYlYjzMMh3QKvg")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8524854849"))
SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "@ZORO_BROTHER")
DB_PATH = os.getenv("DB_PATH", "store_v9.db")
PORT = int(os.getenv("PORT", "8080"))

DEFAULT_BKASH = "01862849299"
DEFAULT_NAGAD = "01778879676"

DEFAULT_PLANS = []

CATEGORIES = [
    ("ALL", "🌐 ALL"),
    ("ROOT", "🛡 Root"),
    ("NON_ROOT", "🔓 Non Root"),
    ("IOS", "📱 iOS"),
    ("PC_LAPTOP", "💻 PC/Laptop"),
]

# আপনার কাস্টম প্রাইস স্ল্যাব (সাইট প্রাইস -> আপনার ব্র্যান্ড প্রাইস)
PRICE_SLABS = [
    (25.0, 20.0),
    (30.0, 25.0),
    (50.0, 40.0),
    (70.0, 60.0),
    (100.0, 80.0),
    (160.0, 140.0),
    (200.0, 180.0),
    (500.0, 450.0),
    (800.0, 740.0),
]

# বাদ দেওয়া প্রোডাক্ট (আগের DB থেকেও অটো ডিলিট হবে)
REMOVED_PRODUCTS = [
    "Br Mod Apk Mod",
    "ANGRY MOOD",
    "DELTA MODZ",
]


def round_to_0_or_5(amount: float) -> float:
    if amount <= 0:
        return 0.0
    snapped = round(float(amount) / 5.0) * 5.0
    return float(max(5.0, snapped))


def calc_brand_price(site_price: float) -> float:
    sp = float(site_price)
    if sp <= 0:
        return 0.0

    if sp <= PRICE_SLABS[0][0]:
        ratio = PRICE_SLABS[0][1] / PRICE_SLABS[0][0]
        raw = sp * ratio
    elif sp >= PRICE_SLABS[-1][0]:
        raw = sp * 0.90
    else:
        raw = sp * 0.85
        for i in range(len(PRICE_SLABS) - 1):
            x1, y1 = PRICE_SLABS[i]
            x2, y2 = PRICE_SLABS[i + 1]
            if x1 <= sp <= x2:
                if x2 == x1:
                    raw = y1
                else:
                    t = (sp - x1) / (x2 - x1)
                    raw = y1 + t * (y2 - y1)
                break

    # 45% কম কস্ট প্রাইস (0.55x) + নিরাপদ লাভের মার্জিন, সবসময় 0 বা 5-এ শেষ হবে
    min_safe_price = (sp * 0.55) * 1.15
    final_price = round_to_0_or_5(max(raw, min_safe_price))
    return final_price


# (product_name, category_key, [(duration, site_price, stock, bonus), ...])
RAW_SITE_CATALOG = [
    (
        "DRIP CLIENT NON ROOT",
        "NON_ROOT",
        [
            ("1 Days", 60.0, 20, ""),
            ("3 Days", 100.0, 20, ""),
            ("7 Days", 150.0, 15, ""),
            ("15 Days", 290.0, 15, ""),
            ("30 Days", 500.0, 10, ""),
        ],
    ),
    (
        "ANGRY MOD - ROOT",
        "ROOT",
        [
            ("1 Days", 70.0, 20, ""),
            ("7 Days", 300.0, 20, ""),
            ("15 Days", 500.0, 15, ""),
            ("30 Days", 800.0, 10, ""),
        ],
    ),
    (
        "DELTA MOD - ROOT",
        "ROOT",
        [
            ("1 Days", 60.0, 20, ""),
            ("7 Days", 300.0, 20, ""),
            ("15 Days", 480.0, 15, ""),
            ("30 Days", 700.0, 10, ""),
        ],
    ),
    (
        "BR MOD NON ROOT",
        "NON_ROOT",
        [
            ("1 Days", 50.0, 25, ""),
            ("10 Days", 400.0, 15, ""),
            ("30 Days", 800.0, 10, ""),
        ],
    ),
    (
        "BR MODS - ROOT",
        "ROOT",
        [
            ("1 Days", 40.0, 25, ""),
            ("7 Days", 200.0, 20, ""),
            ("15 Days", 400.0, 15, ""),
            ("30 Days", 500.0, 10, ""),
        ],
    ),
    (
        "REZZX MODZ IOS",
        "IOS",
        [
            ("1 HOURS", 12.0, 30, ""),
            ("2 HOURS", 20.0, 30, ""),
            ("3 HOURS", 35.0, 30, ""),
            ("6 HOURS", 70.0, 25, ""),
            ("12 HOURS", 90.0, 25, ""),
            ("1 Days", 120.0, 20, ""),
            ("3 Days", 280.0, 20, ""),
            ("7 Days", 380.0, 15, ""),
        ],
    ),
    (
        "ZYTRON PRO - ROOT",
        "ROOT",
        [
            ("1 Days", 70.0, 20, ""),
            ("7 Days", 300.0, 20, ""),
            ("15 Days", 500.0, 15, ""),
            ("31 Days", 700.0, 10, ""),
        ],
    ),
    (
        "DRIP WIRE EXTERNAL",
        "NON_ROOT",
        [
            ("3 HOURS", 25.0, 30, ""),
            ("6 HOURS", 40.0, 30, ""),
            ("12 HOURS", 70.0, 25, ""),
            ("24 HOURS", 100.0, 25, ""),
            ("7 Days", 350.0, 15, ""),
            ("30 Days", 700.0, 10, ""),
        ],
    ),
]

CATALOG_PRODUCTS = [
    (
        pname,
        cat_key,
        [
            (dur, calc_brand_price(site_p), stk, bon)
            for dur, site_p, stk, bon in plist
        ],
    )
    for pname, cat_key, plist in RAW_SITE_CATALOG
]

admin_states = {}
user_states = {}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_valid_bd_mobile(text: str) -> bool:
    cleaned = re.sub(r"[\s\-\+]", "", text or "")
    if cleaned.startswith("880"):
        cleaned = "0" + cleaned[3:]
    return bool(re.fullmatch(r"01[3-9]\d{8}", cleaned))


def is_valid_trx_or_proof_text(text: str) -> tuple[bool, str]:
    raw = (text or "").strip()
    if not raw:
        return False, ""

    if is_valid_bd_mobile(raw):
        cleaned = re.sub(r"[\s\-\+]", "", raw)
        if cleaned.startswith("880"):
            cleaned = "0" + cleaned[3:]
        return True, cleaned

    trx = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if len(trx) < 8 or len(trx) > 16:
        return False, trx

    has_digit = any(ch.isdigit() for ch in trx)
    has_alpha = any(ch.isalpha() for ch in trx)
    if not (has_digit and has_alpha):
        return False, trx

    if re.search(r"(.)\1{3,}", trx):
        return False, trx

    if re.fullmatch(r"([A-Z0-9]{2,3})\1{1,5}", trx):
        return False, trx

    junk_tokens = ("QWERTY", "ASDF", "ZXCV", "TEST", "FAKE", "DEMO", "XXXX", "ABCD")
    if any(tok in trx for tok in junk_tokens):
        return False, trx

    return True, trx


def is_duplicate_proof(proof_val: str) -> bool:
    val = (proof_val or "").strip().upper()
    if not val or val == "BALANCE_KEY_REQ":
        return False

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS cnt FROM orders
        WHERE UPPER(TRIM(trx_id)) = ? AND status IN ('pending', 'approved')
        """,
        (val,),
    )
    o_cnt = cur.fetchone()["cnt"]

    cur.execute(
        """
        SELECT COUNT(*) AS cnt FROM balance_requests
        WHERE UPPER(TRIM(proof_text)) = ? AND status IN ('pending', 'approved')
        """,
        (val,),
    )
    b_cnt = cur.fetchone()["cnt"]
    conn.close()
    return (o_cnt + b_cnt) > 0


def sync_catalog_prices(cur: sqlite3.Cursor):
    for rem_name in REMOVED_PRODUCTS:
        cur.execute("SELECT id FROM products WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (rem_name,))
        for r_row in cur.fetchall():
            cur.execute("DELETE FROM plans WHERE product_id = ?", (r_row["id"],))
            cur.execute("DELETE FROM products WHERE id = ?", (r_row["id"],))

    for pname, cat_key, plist in CATALOG_PRODUCTS:
        cur.execute("SELECT id, category FROM products WHERE name = ?", (pname,))
        prow = cur.fetchone()
        if not prow:
            cur.execute(
                "INSERT INTO products (name, category) VALUES (?, ?)",
                (pname, cat_key),
            )
            pid = cur.lastrowid
            cur.executemany(
                "INSERT INTO plans (product_id, duration, price, stock, bonus) VALUES (?, ?, ?, ?, ?)",
                [(pid, dur, pr, st, bon) for dur, pr, st, bon in plist],
            )
        else:
            pid = prow["id"]
            if prow["category"] != cat_key:
                cur.execute("UPDATE products SET category = ? WHERE id = ?", (cat_key, pid))
            for dur, pr, st, bon in plist:
                cur.execute(
                    "SELECT id FROM plans WHERE product_id = ? AND duration = ?",
                    (pid, dur),
                )
                pl_row = cur.fetchone()
                if pl_row:
                    cur.execute(
                        "UPDATE plans SET price = ? WHERE id = ?",
                        (pr, pl_row["id"]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO plans (product_id, duration, price, stock, bonus) VALUES (?, ?, ?, ?, ?)",
                        (pid, dur, pr, st, bon),
                    )


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            lang TEXT DEFAULT 'bn',
            balance REAL DEFAULT 0.0,
            joined_at TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'ALL'
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            duration TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 10,
            bonus TEXT DEFAULT '',
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            sender_number TEXT DEFAULT '',
            trx_id TEXT DEFAULT '',
            proof_photo_id TEXT DEFAULT '',
            delivered_key TEXT DEFAULT '',
            status TEXT DEFAULT 'pending_payment',
            created_at TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS balance_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            requested_amount REAL DEFAULT 0.0,
            proof_text TEXT DEFAULT '',
            proof_photo_id TEXT DEFAULT '',
            status TEXT DEFAULT 'pending_payment',
            created_at TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bkash TEXT DEFAULT '',
            nagad TEXT DEFAULT ''
        )
        """
    )

    cur.execute("PRAGMA table_info(orders)")
    o_cols = [c["name"] for c in cur.fetchall()]
    if "proof_photo_id" not in o_cols:
        cur.execute("ALTER TABLE orders ADD COLUMN proof_photo_id TEXT DEFAULT ''")

    cur.execute("PRAGMA table_info(products)")
    p_cols = [c["name"] for c in cur.fetchall()]
    if "category" not in p_cols:
        cur.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'ALL'")

    cur.execute("SELECT COUNT(*) AS cnt FROM payment_settings WHERE id = 1")
    if cur.fetchone()["cnt"] == 0:
        cur.execute(
            "INSERT INTO payment_settings (id, bkash, nagad) VALUES (1, ?, ?)",
            (DEFAULT_BKASH, DEFAULT_NAGAD),
        )

    sync_catalog_prices(cur)

    conn.commit()
    conn.close()


def get_payment_numbers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT bkash, nagad FROM payment_settings WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return DEFAULT_BKASH, DEFAULT_NAGAD
    return row["bkash"] or "N/A", row["nagad"] or "N/A"


def update_payment_number(method: str, number: str):
    conn = get_conn()
    cur = conn.cursor()
    if method == "bkash":
        cur.execute("UPDATE payment_settings SET bkash = ? WHERE id = 1", (number,))
    elif method == "nagad":
        cur.execute("UPDATE payment_settings SET nagad = ? WHERE id = 1", (number,))
    conn.commit()
    conn.close()


def register_or_update_user(message: Message):
    uid = message.from_user.id
    full_name = message.from_user.full_name or "User"
    username = f"@{message.from_user.username}" if message.from_user.username else "N/A"
    joined = now_str()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT lang, balance FROM users WHERE user_id = ?", (uid,))
    existing = cur.fetchone()
    is_new = existing is None

    if is_new:
        cur.execute(
            """
            INSERT INTO users (user_id, full_name, username, lang, balance, joined_at)
            VALUES (?, ?, ?, 'bn', 0.0, ?)
            """,
            (uid, full_name, username, joined),
        )
        lang = "bn"
        bal = 0.0
    else:
        lang = existing["lang"] or "bn"
        bal = float(existing["balance"] or 0.0)
        cur.execute(
            """
            UPDATE users SET full_name = ?, username = ?
            WHERE user_id = ?
            """,
            (full_name, username, uid),
        )

    cur.execute("SELECT COUNT(*) AS cnt FROM users")
    total_users = cur.fetchone()["cnt"]
    conn.commit()
    conn.close()

    return is_new, lang, bal, total_users, full_name, username, joined


def set_lang(user_id: int, lang: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, full_name, username, lang, balance, joined_at)
        VALUES (?, 'User', 'N/A', ?, 0.0, ?)
        ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
        """,
        (user_id, lang, now_str()),
    )
    conn.commit()
    conn.close()


def get_user_info(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT full_name, username, lang, balance FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return "User", "N/A", "bn", 0.0
    return (
        row["full_name"] or "User",
        row["username"] or "N/A",
        row["lang"] or "bn",
        float(row["balance"] or 0.0),
    )


def format_bonus_bracket(bonus: str) -> str:
    b = (bonus or "").strip()
    if not b:
        return ""
    if b.startswith("(") and b.endswith(")"):
        return f" {b}"
    return f" ({b})"


def status_label(status: str, lang: str) -> str:
    bn_map = {
        "pending_payment": "পেমেন্ট বাকি",
        "pending": "ভেরিফিকেশন চলছে",
        "approved": "এপ্রুভড",
        "rejected": "রিজেক্টেড",
    }
    en_map = {
        "pending_payment": "Awaiting Proof",
        "pending": "Pending Review",
        "approved": "Approved",
        "rejected": "Rejected",
    }
    return (bn_map if lang == "bn" else en_map).get(status, status)


def category_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📱 iOS", callback_data="cat_IOS"),
                InlineKeyboardButton(text="💻 PC/Laptop", callback_data="cat_PC_LAPTOP"),
            ],
            [
                InlineKeyboardButton(text="🔓 Non Root", callback_data="cat_NON_ROOT"),
                InlineKeyboardButton(text="🛡 Root", callback_data="cat_ROOT"),
            ],
            [
                InlineKeyboardButton(text="🌐 ALL (সব প্রোডাক্ট)", callback_data="cat_ALL"),
            ],
        ]
    )


def main_menu(user_id: int, lang: str) -> ReplyKeyboardMarkup:
    if lang == "en":
        rows = [
            [KeyboardButton(text="🛒 Buy Keys"), KeyboardButton(text="➕ Add Balance")],
            [KeyboardButton(text="💰 Balance"), KeyboardButton(text="📦 My Orders")],
            [KeyboardButton(text="🌐 Change Language"), KeyboardButton(text="📞 Support")],
        ]
    else:
        rows = [
            [KeyboardButton(text="🛒 কি কিনুন"), KeyboardButton(text="➕ ব্যালেন্স যোগ")],
            [KeyboardButton(text="💰 ব্যালেন্স"), KeyboardButton(text="📦 আমার অর্ডার")],
            [KeyboardButton(text="🌐 ভাষা পরিবর্তন"), KeyboardButton(text="📞 সাপোর্ট")],
        ]
    if user_id == ADMIN_ID:
        rows.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇧🇩 বাংলা", callback_data="setlang_bn"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en"),
            ]
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Add Product", callback_data="adm_addprod"),
                InlineKeyboardButton(text="🗑 Del Product", callback_data="adm_delprod"),
            ],
            [
                InlineKeyboardButton(text="⏱ Add Plan", callback_data="adm_addplan"),
                InlineKeyboardButton(text="🗑 Del Plan", callback_data="adm_delplan"),
            ],
            [
                InlineKeyboardButton(text="✏️ Edit Plan", callback_data="adm_editplan"),
                InlineKeyboardButton(text="🎁 Set Offer", callback_data="adm_setoffer"),
            ],
            [
                InlineKeyboardButton(text="📋 Pending Orders", callback_data="adm_orders"),
                InlineKeyboardButton(text="💳 Pending Bal Reqs", callback_data="adm_balreqs"),
            ],
            [
                InlineKeyboardButton(text="➕ Balance (+)", callback_data="adm_bal_plus"),
                InlineKeyboardButton(text="➖ Balance (-)", callback_data="adm_bal_minus"),
            ],
            [
                InlineKeyboardButton(text="💳 Payment Numbers", callback_data="adm_paynums"),
                InlineKeyboardButton(text="🔎 User Lookup", callback_data="adm_lookup"),
            ],
            [
                InlineKeyboardButton(text="📊 Sales Report", callback_data="adm_report"),
                InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast"),
            ],
            [
                InlineKeyboardButton(text="👥 Users & Stats", callback_data="adm_users"),
            ],
        ]
    )


def payment_numbers_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📱 Set bKash", callback_data="setpay_bkash"),
                InlineKeyboardButton(text="📱 Set Nagad", callback_data="setpay_nagad"),
            ]
        ]
    )


def order_approve_start_kb(oid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔑 Enter Key & Approve", callback_data=f"reqapp_{oid}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rej_{oid}"),
            ]
        ]
    )


def bal_req_kb(bid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Add Balance (/balance)", callback_data=f"reqbal_{bid}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"rejbal_{bid}"),
            ]
        ]
    )


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    admin_states.pop(uid, None)
    user_states.pop(uid, None)

    is_new, lang, bal, total_users, full_name, username, joined = register_or_update_user(message)

    if is_new and message.from_user.id != ADMIN_ID:
        new_user_alert = (
            f"🎉 New User Joined!\n\n"
            f"👤 Name: {full_name}\n"
            f"🆔 Username: {username}\n"
            f"💬 Chat ID: {message.from_user.id}\n"
            f"💰 Balance: ৳{bal:.2f}\n"
            f"🕒 Time: {joined}\n"
            f"👥 Total Users: {total_users}"
        )
        try:
            await bot.send_message(ADMIN_ID, new_user_alert)
        except Exception:
            pass

    await message.answer(
        "ভাষা বেছে নিন / Choose your language:",
        reply_markup=lang_kb(),
    )
    await message.answer(
        f"⚡ ZORO 404 OFFICIAL\n💰 ব্যালেন্স: ৳{bal:.2f}"
        if lang == "bn"
        else f"⚡ ZORO 404 OFFICIAL\n💰 Balance: ৳{bal:.2f}",
        reply_markup=main_menu(message.from_user.id, lang),
    )


@dp.callback_query(F.data.startswith("setlang_"))
async def cb_setlang(callback: CallbackQuery):
    lang = callback.data.split("_", 1)[1]
    set_lang(callback.from_user.id, lang)
    _, _, _, bal = get_user_info(callback.from_user.id)
    await callback.message.edit_text(
        "✅ বাংলা সেট করা হয়েছে।" if lang == "bn" else "✅ English set."
    )
    await callback.message.answer(
        f"মেইন মেনু | 💰 ব্যালেন্স: ৳{bal:.2f}"
        if lang == "bn"
        else f"Main Menu | 💰 Balance: ৳{bal:.2f}",
        reply_markup=main_menu(callback.from_user.id, lang),
    )
    await callback.answer()


@dp.message(F.text.in_(["💰 ব্যালেন্স", "💰 Balance"]))
async def btn_balance(message: Message):
    admin_states.pop(message.from_user.id, None)
    full_name, username, lang, bal = get_user_info(message.from_user.id)
    if lang == "bn":
        await message.answer(
            f"👤 নাম: {full_name}\n"
            f"🆔 ইউজারনেম: {username}\n"
            f"💬 আইডি: {message.from_user.id}\n"
            f"💰 বর্তমান ব্যালেন্স: ৳{bal:.2f}"
        )
    else:
        await message.answer(
            f"👤 Name: {full_name}\n"
            f"🆔 Username: {username}\n"
            f"💬 ID: {message.from_user.id}\n"
            f"💰 Current Balance: ৳{bal:.2f}"
        )


@dp.message(F.text.in_(["➕ ব্যালেন্স যোগ", "➕ Add Balance"]))
async def btn_add_balance(message: Message):
    uid = message.from_user.id
    admin_states.pop(uid, None)
    _, _, lang, bal = get_user_info(uid)
    user_states[uid] = {"step": "wait_bal_amount"}
    if lang == "bn":
        await message.answer(
            f"💰 বর্তমান ব্যালেন্স: ৳{bal:.2f}\n\n"
            f"কত টাকা ব্যালেন্স যোগ করতে চান সেই সংখ্যাটি লিখে পাঠান:\n"
            f"উদাহরণ: 200"
        )
    else:
        await message.answer(
            f"💰 Current Balance: ৳{bal:.2f}\n\n"
            f"Type and send how much balance you want to add:\n"
            f"Example: 200"
        )


@dp.message(F.text.in_(["🌐 ভাষা পরিবর্তন", "🌐 Change Language"]))
async def btn_change_lang(message: Message):
    admin_states.pop(message.from_user.id, None)
    await message.answer("ভাষা বেছে নিন / Choose language:", reply_markup=lang_kb())


@dp.message(F.text.in_(["🛒 কি কিনুন", "🛒 Buy Keys"]))
async def btn_buy_keys(message: Message):
    admin_states.pop(message.from_user.id, None)
    _, _, lang, bal = get_user_info(message.from_user.id)
    header = (
        f"💰 ব্যালেন্স: ৳{bal:.2f}\nআগে ক্যাটাগরি সিলেক্ট করুন (অথবা ALL দিন):"
        if lang == "bn"
        else f"💰 Balance: ৳{bal:.2f}\nSelect a category first (or choose ALL):"
    )
    await message.answer(header, reply_markup=category_kb())


@dp.callback_query(F.data.startswith("cat_"))
async def cb_select_category(callback: CallbackQuery):
    cat_key = callback.data.split("_", 1)[1]
    _, _, lang, _ = get_user_info(callback.from_user.id)

    conn = get_conn()
    cur = conn.cursor()
    if cat_key == "ALL":
        cur.execute("SELECT id, name FROM products ORDER BY id")
        cat_title = "🌐 ALL"
    else:
        cur.execute(
            "SELECT id, name FROM products WHERE category = ? ORDER BY id",
            (cat_key,),
        )
        cat_label_map = {
            "IOS": "📱 iOS",
            "PC_LAPTOP": "💻 PC/Laptop",
            "NON_ROOT": "🔓 Non Root",
            "ROOT": "🛡 Root",
        }
        cat_title = cat_label_map.get(cat_key, cat_key)

    prods = cur.fetchall()
    conn.close()

    if not prods:
        await callback.answer(
            "এই ক্যাটাগরিতে এখনো কোনো প্রোডাক্ট নেই।"
            if lang == "bn"
            else "No products in this category yet.",
            show_alert=True,
        )
        return

    rows = [
        [InlineKeyboardButton(text=f"🔹 {row['name']}", callback_data=f"prod_{row['id']}")]
        for row in prods
    ]
    rows.append([InlineKeyboardButton(text="⬅️ ক্যাটাগরি পরিবর্তন", callback_data="back_cats")])

    header = (
        f"ক্যাটাগরি: {cat_title}\nপ্রোডাক্ট সিলেক্ট করুন:"
        if lang == "bn"
        else f"Category: {cat_title}\nSelect a product:"
    )
    await callback.message.edit_text(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data == "back_cats")
async def cb_back_cats(callback: CallbackQuery):
    _, _, lang, _ = get_user_info(callback.from_user.id)
    await callback.message.edit_text(
        "ক্যাটাগরি সিলেক্ট করুন (অথবা ALL দিন):" if lang == "bn" else "Select a category (or ALL):",
        reply_markup=category_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("prod_"))
async def cb_select_product(callback: CallbackQuery):
    pid = int(callback.data.split("_", 1)[1])
    _, _, lang, _ = get_user_info(callback.from_user.id)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name, category FROM products WHERE id = ?", (pid,))
    p_row = cur.fetchone()
    cur.execute(
        "SELECT id, duration, price, bonus FROM plans WHERE product_id = ? ORDER BY id",
        (pid,),
    )
    plans = cur.fetchall()
    conn.close()

    if not p_row:
        await callback.answer("Product not found", show_alert=True)
        return

    if not plans:
        await callback.answer(
            "এই প্রোডাক্টে এখনো কোনো প্ল্যান/দিন যোগ করা হয়নি।"
            if lang == "bn"
            else "No plans added for this product yet.",
            show_alert=True,
        )
        return

    pname = p_row["name"]
    cat_back = p_row["category"] or "ALL"
    buttons = []
    for pl in plans:
        label = f"{pl['duration']} - ৳{float(pl['price']):.0f}{format_bonus_bracket(pl['bonus'])}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"plan_{pl['id']}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"cat_{cat_back}")])

    title = (
        f"প্রোডাক্ট: {pname}\nকতদিন নিবেন সিলেক্ট করুন:"
        if lang == "bn"
        else f"Product: {pname}\nSelect duration:"
    )
    await callback.message.edit_text(
        title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("plan_"))
async def cb_select_plan(callback: CallbackQuery):
    plid = int(callback.data.split("_", 1)[1])
    uid = callback.from_user.id
    _, _, lang, bal = get_user_info(uid)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.name, pl.duration, pl.price, pl.bonus
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        WHERE pl.id = ?
        """,
        (plid,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        await callback.answer("Plan not found", show_alert=True)
        return

    pname = row["name"]
    duration = row["duration"]
    price = float(row["price"])
    bonus = row["bonus"] or ""
    bkash_num, nagad_num = get_payment_numbers()
    created = now_str()

    cur.execute(
        """
        INSERT INTO orders (user_id, plan_id, status, created_at)
        VALUES (?, ?, 'pending_payment', ?)
        """,
        (uid, plid, created),
    )
    oid = cur.lastrowid
    conn.commit()
    conn.close()

    user_states[uid] = {
        "step": "wait_proof",
        "order_id": oid,
        "plan_id": plid,
        "pname": pname,
        "duration": duration,
        "price": price,
        "bonus": bonus,
        "created_at": created,
    }

    bonus_line = f"\n🎁 অফার: {bonus}" if bonus else ""
    pay_bal_text = (
        f"💰 ব্যালেন্সের টাকা দিয়ে কি কিনুন (৳{price:.0f})"
        if lang == "bn"
        else f"💰 Buy Key with Balance (৳{price:.0f})"
    )
    kb_rows = [[InlineKeyboardButton(text=pay_bal_text, callback_data=f"paybal_{oid}")]]

    if lang == "bn":
        msg = (
            f"🛒 অর্ডার #{oid}\n"
            f"📦 {pname} ({duration}){bonus_line}\n"
            f"💵 মোট টাকা: ৳{price:.0f} (Send Money)\n"
            f"💰 আপনার ব্যালেন্স: ৳{bal:.2f}\n\n"
            f"📲 পেমেন্ট নম্বর:\n"
            f"• বিকাশ: {bkash_num}\n"
            f"• নগদ: {nagad_num}\n\n"
            f"টাকা পাঠানোর পর যেকোনো ১টা দিন:\n"
            f"📸 পেমেন্টের স্ক্রিনশট পাঠান\n"
            f"অথবা\n"
            f"✍️ সঠিক TrxID / মোবাইল নম্বর লিখে পাঠান"
        )
    else:
        msg = (
            f"🛒 Order #{oid}\n"
            f"📦 {pname} ({duration}){bonus_line}\n"
            f"💵 Amount: ৳{price:.0f} (Send Money)\n"
            f"💰 Your Balance: ৳{bal:.2f}\n\n"
            f"📲 Payment Numbers:\n"
            f"• bKash: {bkash_num}\n"
            f"• Nagad: {nagad_num}\n\n"
            f"After sending money, send any ONE:\n"
            f"📸 Payment screenshot\n"
            f"OR\n"
            f"✍️ Valid TrxID / mobile number"
        )

    await callback.message.edit_text(
        msg,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("paybal_"))
async def cb_pay_with_balance(callback: CallbackQuery):
    oid = int(callback.data.split("_", 1)[1])
    uid = callback.from_user.id
    full_name, username, lang, bal = get_user_info(uid)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.user_id, o.status, o.created_at, p.name, pl.duration, pl.price, pl.bonus
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        WHERE o.id = ? AND o.user_id = ?
        """,
        (oid, uid),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        await callback.answer("Order not found", show_alert=True)
        return

    if row["status"] != "pending_payment":
        conn.close()
        await callback.answer("Already processed", show_alert=True)
        return

    price = float(row["price"])
    if bal < price:
        conn.close()
        await callback.answer(
            f"আপনার ব্যালেন্সে পর্যাপ্ত টাকা নেই (প্রয়োজন ৳{price:.0f}, আছে ৳{bal:.2f})।"
            if lang == "bn"
            else f"Insufficient balance (Need ৳{price:.0f}, you have ৳{bal:.2f}).",
            show_alert=True,
        )
        return

    new_bal = bal - price
    cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, uid))
    cur.execute(
        "UPDATE orders SET trx_id = 'BALANCE_KEY_REQ', status = 'pending' WHERE id = ?",
        (oid,),
    )
    conn.commit()
    conn.close()

    user_states.pop(uid, None)

    await callback.message.edit_text(
        f"✅ ব্যালেন্স কি রিকোয়েস্ট #{oid} পাঠানো হয়েছে!\n"
        f"📦 প্রোডাক্ট: {row['name']} ({row['duration']})\n"
        f"💸 ব্যালেন্স থেকে কাটা হয়েছে: ৳{price:.0f} | বাকি ব্যালেন্স: ৳{new_bal:.2f}\n"
        f"অ্যাডমিন /key কমান্ড দিয়ে কি/পাসওয়ার্ড পাঠাবেন।"
        if lang == "bn"
        else f"✅ Balance Key Request #{oid} sent!\n"
        f"📦 Product: {row['name']} ({row['duration']})\n"
        f"💸 Deducted: ৳{price:.0f} | Remaining Balance: ৳{new_bal:.2f}\n"
        f"Admin will send your key/password using /key."
    )

    offer_line = f"\n🎁 Offer: {row['bonus']}" if row["bonus"] else ""
    admin_alert = (
        f"💰🔑 [ব্যালেন্স টাকায় কি রিকোয়েস্ট] Order #{oid}\n"
        f"🕒 Time: {row['created_at']}\n"
        f"👤 User: {full_name} ({username}) | ID: {uid}\n"
        f"📦 প্যানেল / প্রোডাক্ট: {row['name']} ({row['duration']})\n"
        f"💵 কাটা টাকা: ৳{price:.0f} | বাকি ব্যালেন্স: ৳{new_bal:.2f}{offer_line}\n\n"
        f"কি / পাসওয়ার্ড দিতে লিখুন:\n"
        f"/key XXXXXXXXXXXXX"
    )
    try:
        await bot.send_message(
            ADMIN_ID,
            admin_alert,
            reply_markup=order_approve_start_kb(oid),
        )
    except Exception:
        pass
    await callback.answer()


@dp.message(F.text.in_(["📦 আমার অর্ডার", "📦 My Orders"]))
async def btn_my_orders(message: Message):
    admin_states.pop(message.from_user.id, None)
    _, _, lang, _ = get_user_info(message.from_user.id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.id, p.name, pl.duration, pl.price, o.sender_number, o.trx_id,
               o.proof_photo_id, o.delivered_key, o.status, o.created_at
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        WHERE o.user_id = ?
        ORDER BY o.id DESC LIMIT 10
        """,
        (message.from_user.id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("আপনার কোনো অর্ডার নেই।" if lang == "bn" else "No orders yet.")
        return

    lines = []
    for r in rows:
        proof_txt = r["trx_id"] or r["sender_number"] or ("Screenshot sent" if r["proof_photo_id"] else "-")
        key_txt = f"\n   🔑 Key/Pass: {r['delivered_key']}" if r["delivered_key"] else ""
        st_txt = status_label(r["status"], lang)
        lines.append(
            f"#{r['id']} | {r['name']} ({r['duration']}) - ৳{float(r['price']):.0f} [{st_txt}]\n"
            f"   🕒 {r['created_at']} | Proof: {proof_txt}{key_txt}"
        )
    await message.answer("\n\n".join(lines))


@dp.message(F.text.in_(["📞 সাপোর্ট", "📞 Support"]))
async def btn_support(message: Message):
    admin_states.pop(message.from_user.id, None)
    _, _, lang, _ = get_user_info(message.from_user.id)
    bkash_num, nagad_num = get_payment_numbers()
    msg = (
        f"সাপোর্টের জন্য যোগাযোগ করুন: {SUPPORT_HANDLE}\n"
        f"বিকাশ: {bkash_num} | নগদ: {nagad_num}"
        if lang == "bn"
        else f"Contact for support: {SUPPORT_HANDLE}\n"
        f"bKash: {bkash_num} | Nagad: {nagad_num}"
    )
    await message.answer(msg)


@dp.message(Command("key"))
async def cmd_admin_key(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("ব্যবহার: /key XXXXXXXXXXXXX")
        return

    key_val = parts[1].strip()
    target_oid = admin_states.get(ADMIN_ID, {}).get("order_id")

    conn = get_conn()
    cur = conn.cursor()
    if target_oid:
        cur.execute(
            "SELECT id, user_id, plan_id, status FROM orders WHERE id = ?",
            (target_oid,),
        )
    else:
        cur.execute(
            "SELECT id, user_id, plan_id, status FROM orders WHERE status = 'pending' ORDER BY id DESC LIMIT 1"
        )
    row = cur.fetchone()
    if not row:
        conn.close()
        await message.answer("কোনো Pending পাসওয়ার্ড/কি রিকোয়েস্ট পাওয়া যায়নি।")
        return

    oid = row["id"]
    target_uid = row["user_id"]
    plid = row["plan_id"]

    cur.execute(
        "UPDATE orders SET delivered_key = ?, status = 'approved' WHERE id = ?",
        (key_val, oid),
    )
    cur.execute(
        "UPDATE plans SET stock = CASE WHEN stock > 0 THEN stock - 1 ELSE 0 END WHERE id = ?",
        (plid,),
    )
    conn.commit()
    conn.close()

    if admin_states.get(ADMIN_ID, {}).get("order_id") == oid:
        admin_states.pop(ADMIN_ID, None)

    try:
        await bot.send_message(
            target_uid,
            f"✅ আপনার অর্ডার #{oid} এপ্রুভ হয়েছে!\n🔑 Key / Password: {key_val}",
        )
    except Exception:
        pass

    await message.answer(f"✅ Order #{oid} APPROVED!\n🔑 Sent Key/Password: {key_val}")


@dp.message(Command("balance"))
async def cmd_admin_balance(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer("ব্যবহার: /balance 200")
        return

    try:
        amt = float(parts[1])
        if amt <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("সঠিক সংখ্যা লিখুন। উদাহরণ: /balance 200")
        return

    target_bid = admin_states.get(ADMIN_ID, {}).get("bal_req_id")

    conn = get_conn()
    cur = conn.cursor()
    if target_bid:
        cur.execute(
            "SELECT id, user_id, status FROM balance_requests WHERE id = ?",
            (target_bid,),
        )
    else:
        cur.execute(
            "SELECT id, user_id, status FROM balance_requests WHERE status = 'pending' ORDER BY id DESC LIMIT 1"
        )
    row = cur.fetchone()
    if not row:
        conn.close()
        await message.answer("কোনো Pending ব্যালেন্স রিকোয়েস্ট পাওয়া যায়নি।")
        return

    bid = row["id"]
    target_uid = row["user_id"]

    cur.execute("SELECT balance FROM users WHERE user_id = ?", (target_uid,))
    urow = cur.fetchone()
    if not urow:
        conn.close()
        await message.answer("ইউজার পাওয়া যায়নি।")
        return

    new_bal = float(urow["balance"] or 0.0) + amt
    cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_uid))
    cur.execute("UPDATE balance_requests SET status = 'approved' WHERE id = ?", (bid,))
    conn.commit()
    conn.close()

    if admin_states.get(ADMIN_ID, {}).get("bal_req_id") == bid:
        admin_states.pop(ADMIN_ID, None)

    try:
        await bot.send_message(
            target_uid,
            f"✅ আপনার ব্যালেন্স রিকোয়েস্ট #{bid} এপ্রুভ হয়েছে!\n"
            f"💰 যোগ হয়েছে: ৳{amt:.2f}\n"
            f"💵 নতুন ব্যালেন্স: ৳{new_bal:.2f}",
        )
    except Exception:
        pass

    await message.answer(
        f"✅ Balance Request #{bid} APPROVED!\n"
        f"👤 User: {target_uid} | +৳{amt:.2f}\n"
        f"💰 New Balance: ৳{new_bal:.2f}"
    )


@dp.message(F.text == "🛠 Admin Panel")
async def btn_admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    admin_states.pop(ADMIN_ID, None)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM users")
    u_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM products")
    p_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'pending'")
    o_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM balance_requests WHERE status = 'pending'")
    b_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COALESCE(SUM(balance), 0) AS tot FROM users")
    tot_bal = float(cur.fetchone()["tot"] or 0.0)
    conn.close()

    await message.answer(
        f"🛠 Admin Control ({SUPPORT_HANDLE})\n"
        f"👥 Users: {u_cnt} | 📦 Products: {p_cnt}\n"
        f"⏳ Pending Orders: {o_cnt} | 💳 Bal Reqs: {b_cnt}\n"
        f"💰 Total User Bal: ৳{tot_bal:.2f}",
        reply_markup=admin_panel_kb(),
    )


@dp.callback_query(F.data == "adm_report")
async def cb_adm_report(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*) AS cnt, COALESCE(SUM(pl.price), 0) AS amt
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        WHERE o.status = 'approved'
        """
    )
    app_ord = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*) AS cnt, COALESCE(SUM(pl.price), 0) AS amt
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        WHERE o.status = 'approved' AND o.trx_id = 'BALANCE_KEY_REQ'
        """
    )
    bal_ord = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'pending'")
    pend_ord = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'rejected'")
    rej_ord = cur.fetchone()["cnt"]

    cur.execute(
        """
        SELECT COUNT(*) AS cnt, COALESCE(SUM(requested_amount), 0) AS amt
        FROM balance_requests
        WHERE status = 'approved'
        """
    )
    app_bal_req = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS cnt FROM balance_requests WHERE status = 'pending'")
    pend_bal_req = cur.fetchone()["cnt"]

    conn.close()

    total_approved_sales = float(app_ord["amt"] or 0.0)
    bal_key_sales = float(bal_ord["amt"] or 0.0)
    direct_key_sales = max(0.0, total_approved_sales - bal_key_sales)
    total_added_bal = float(app_bal_req["amt"] or 0.0)

    report_txt = (
        f"📊 সেলস ও ব্যালেন্স রিপোর্ট\n\n"
        f"🛒 কি / অর্ডার:\n"
        f"• এপ্রুভড অর্ডার: {app_ord['cnt']} টি (৳{total_approved_sales:.0f})\n"
        f"  — ডাইরেক্ট পেমেন্টে কি: ৳{direct_key_sales:.0f}\n"
        f"  — ব্যালেন্স টাকায় কি: {bal_ord['cnt']} টি (৳{bal_key_sales:.0f})\n"
        f"• পেন্ডিং অর্ডার: {pend_ord} টি\n"
        f"• রিজেক্টেড অর্ডার: {rej_ord} টি\n\n"
        f"💳 ব্যালেন্স রিকোয়েস্ট:\n"
        f"• এপ্রুভড ব্যালেন্স যোগ: {app_bal_req['cnt']} টি (৳{total_added_bal:.0f})\n"
        f"• পেন্ডিং ব্যালেন্স রিকোয়েস্ট: {pend_bal_req} টি"
    )
    await callback.message.answer(report_txt)
    await callback.answer()


@dp.callback_query(F.data == "adm_paynums")
async def cb_adm_paynums(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    bkash_num, nagad_num = get_payment_numbers()
    await callback.message.answer(
        f"💳 বর্তমান পেমেন্ট নম্বর:\n"
        f"• বিকাশ: {bkash_num}\n"
        f"• নগদ: {nagad_num}\n\n"
        f"যে নম্বরটি বদলাতে চান নিচের বাটনে চাপুন:",
        reply_markup=payment_numbers_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.in_(["setpay_bkash", "setpay_nagad"]))
async def cb_setpay_method(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    method = "bkash" if callback.data == "setpay_bkash" else "nagad"
    label = "বিকাশ" if method == "bkash" else "নগদ"
    admin_states[callback.from_user.id] = {"step": "set_pay_num", "method": method}
    await callback.message.answer(f"নতুন {label} নম্বরটি লিখে পাঠান:")
    await callback.answer()


@dp.callback_query(F.data == "adm_lookup")
async def cb_adm_lookup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    admin_states[callback.from_user.id] = {"step": "user_lookup"}
    await callback.message.answer("যেকোনো ইউজারের UserID লিখে পাঠান (উদাহরণ: 5882761122):")
    await callback.answer()


@dp.callback_query(F.data == "adm_balreqs")
async def cb_adm_balreqs(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.user_id, b.requested_amount, b.proof_text, b.proof_photo_id, b.created_at,
               u.full_name, u.username, u.balance
        FROM balance_requests b
        LEFT JOIN users u ON b.user_id = u.user_id
        WHERE b.status = 'pending'
        ORDER BY b.id DESC LIMIT 10
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("কোনো Pending ব্যালেন্স রিকোয়েস্ট নেই।")
        await callback.answer()
        return

    for r in rows:
        uname = r["username"] or "N/A"
        fname = r["full_name"] or "User"
        cur_bal = float(r["balance"] or 0.0)
        info_line = f"\n🧾 Info: {r['proof_text']}" if r["proof_text"] else ""
        caption_txt = (
            f"💳 [PENDING BALANCE REQ] #{r['id']}\n"
            f"🕒 Time: {r['created_at']}\n"
            f"👤 User: {fname} ({uname}) | ID: {r['user_id']}\n"
            f"💰 Current Bal: ৳{cur_bal:.2f} | Requested: ৳{float(r['requested_amount']):.0f}{info_line}\n\n"
            f"লিখুন: /balance {float(r['requested_amount']):.0f}"
        )
        if r["proof_photo_id"]:
            await callback.message.answer_photo(
                photo=r["proof_photo_id"],
                caption=caption_txt,
                reply_markup=bal_req_kb(r["id"]),
            )
        else:
            await callback.message.answer(
                caption_txt,
                reply_markup=bal_req_kb(r["id"]),
            )
    await callback.answer()


@dp.callback_query(F.data == "adm_users")
async def cb_adm_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, full_name, username, balance, joined_at FROM users ORDER BY user_id DESC LIMIT 15"
    )
    rows = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS cnt FROM users")
    total = cur.fetchone()["cnt"]
    conn.close()

    if not rows:
        await callback.message.answer("কোনো ইউজার নেই।")
        await callback.answer()
        return

    lines = [f"📊 Total Users: {total}\n"]
    for r in rows:
        lines.append(
            f"• {r['user_id']} | {r['full_name']} ({r['username']}) | "
            f"💰 ৳{float(r['balance'] or 0):.2f} | 🕒 {r['joined_at']}"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    admin_states[callback.from_user.id] = {"step": "broadcast"}
    await callback.message.answer("সব ইউজারকে পাঠানোর মেসেজটি লিখুন:")
    await callback.answer()


@dp.callback_query(F.data.in_(["adm_bal_plus", "adm_bal_minus"]))
async def cb_adm_balance_mode(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    mode = "plus" if callback.data == "adm_bal_plus" else "minus"
    admin_states[callback.from_user.id] = {"step": "edit_balance", "mode": mode}
    sign = "+" if mode == "plus" else "-"
    await callback.message.answer(
        f"ব্যালেন্স ({sign}) করতে লিখুন:\n"
        f"UserID | Amount\n"
        f"উদাহরণ: 5882761122 | 250"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_addprod")
async def cb_adm_addprod(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    admin_states[callback.from_user.id] = {"step": "add_prod"}
    await callback.message.answer(
        "নতুন প্রোডাক্ট যোগ করতে লিখুন:\n"
        "ProductName | Category (ROOT / NON_ROOT / IOS / PC_LAPTOP / ALL)\n"
        "উদাহরণ: SHARK PANEL | ROOT"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_delprod")
async def cb_adm_delprod(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, category FROM products ORDER BY id")
    prods = cur.fetchall()
    conn.close()

    if not prods:
        await callback.answer("কোনো প্রোডাক্ট নেই।", show_alert=True)
        return

    plist = "\n".join([f"ProductID {r['id']}: {r['name']} [{r['category']}]" for r in prods])
    admin_states[callback.from_user.id] = {"step": "del_prod"}
    await callback.message.answer(
        f"প্রোডাক্ট লিস্ট:\n{plist}\n\n"
        f"যে প্রোডাক্ট রিমুভ করতে চান তার ProductID লিখে পাঠান:\n"
        f"উদাহরণ: 2"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_addplan")
async def cb_adm_addplan(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, category FROM products ORDER BY id")
    prods = cur.fetchall()
    conn.close()

    if not prods:
        await callback.answer("আগে একটি প্রোডাক্ট যোগ করুন।", show_alert=True)
        return

    plist = "\n".join([f"{r['id']} = {r['name']} [{r['category']}]" for r in prods])
    admin_states[callback.from_user.id] = {"step": "add_plan_loop"}
    await callback.message.answer(
        f"প্রোডাক্ট লিস্ট:\n{plist}\n\n"
        f"সিরিয়াল বাই সিরিয়াল প্ল্যান/দিন যোগ করতে লিখুন:\n"
        f"ProductID | Duration | SitePrice | Offer(ঐচ্ছিক)\n"
        f"উদাহরণ:\n"
        f"2 | 1 Hour | 50\n"
        f"2 | 2 Days | 160\n"
        f"2 | 3 Days | 200 | (1 Day 1 Key Free)\n\n"
        f"যতক্ষণ না /start দিবেন বা অন্য বাটন চাপবেন, ততক্ষণ একটার পর একটা লিখে পাঠাতে পারবেন।"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_delplan")
async def cb_adm_delplan(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pl.id, p.name, pl.duration, pl.price, pl.bonus
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
        return

    plan_lines = "\n".join(
        [
            f"PlanID {r['id']}: {r['name']} - {r['duration']} (৳{float(r['price']):.0f}) "
            f"{format_bonus_bracket(r['bonus'])}"
            for r in rows
        ]
    )
    admin_states[callback.from_user.id] = {"step": "del_plan_loop"}
    await callback.message.answer(
        f"সব প্ল্যান লিস্ট:\n{plan_lines}\n\n"
        f"যে প্ল্যান রিমুভ করতে চান তার PlanID লিখে পাঠান (সিরিয়াল বাই সিরিয়ালও দিতে পারবেন):\n"
        f"উদাহরণ: 5"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_editplan")
async def cb_adm_editplan(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pl.id, p.name, pl.duration, pl.price, pl.stock
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
        return

    plan_lines = "\n".join(
        [
            f"PlanID {r['id']}: {r['name']} - {r['duration']} | ৳{float(r['price']):.0f} | Stock: {r['stock']}"
            for r in rows
        ]
    )
    admin_states[callback.from_user.id] = {"step": "edit_plan"}
    await callback.message.answer(
        f"প্ল্যান লিস্ট:\n{plan_lines}\n\n"
        f"দাম বা স্টক বদলাতে লিখুন:\n"
        f"PlanID | BrandPrice | NewStock(ঐচ্ছিক)\n"
        f"উদাহরণ: 3 | 120 | 25"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_setoffer")
async def cb_adm_setoffer(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pl.id, p.name, pl.duration, pl.price, pl.bonus
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
        return

    plan_lines = "\n".join(
        [
            f"PlanID {r['id']}: {r['name']} - {r['duration']} (৳{float(r['price']):.0f}) "
            f"{format_bonus_bracket(r['bonus'])}"
            for r in rows
        ]
    )
    admin_states[callback.from_user.id] = {"step": "set_offer"}
    await callback.message.answer(
        f"প্ল্যান আইডি গুলো:\n{plan_lines}\n\n"
        f"অফার সেট করতে লিখুন:\n"
        f"PlanID | Offer Text (মুছতে চাইলে PlanID | -)\n"
        f"উদাহরণ: 3 | (1 Day 1 Key Free)"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm_orders")
async def cb_adm_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.id, o.user_id, p.name, pl.duration, pl.price, o.sender_number,
               o.trx_id, o.proof_photo_id, pl.bonus, o.created_at
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        WHERE o.status = 'pending'
        ORDER BY o.id DESC LIMIT 10
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("কোনো Pending পাসওয়ার্ড অর্ডার নেই।")
        await callback.answer()
        return

    for r in rows:
        offer_txt = f"\n🎁 Offer: {r['bonus']}" if r["bonus"] else ""
        proof_val = r["trx_id"] or r["sender_number"]
        if proof_val == "BALANCE_KEY_REQ":
            proof_line = "\n💰 সোর্স: ব্যালেন্স টাকায় কি রিকোয়েস্ট"
        elif proof_val:
            proof_line = f"\n🧾 Info: {proof_val}"
        else:
            proof_line = "\n📸 Proof: Screenshot"

        caption_txt = (
            f"🔑 [PASSWORD REQUEST] Order #{r['id']} | User: {r['user_id']}\n"
            f"🕒 Time: {r['created_at']}\n"
            f"📦 প্যানেল / প্রোডাক্ট: {r['name']} ({r['duration']}) - ৳{float(r['price']):.0f}{offer_txt}{proof_line}\n\n"
            f"লিখুন: /key XXXXXXXXXXXXX"
        )
        if r["proof_photo_id"]:
            await callback.message.answer_photo(
                photo=r["proof_photo_id"],
                caption=caption_txt,
                reply_markup=order_approve_start_kb(r["id"]),
            )
        else:
            await callback.message.answer(
                caption_txt,
                reply_markup=order_approve_start_kb(r["id"]),
            )
    await callback.answer()


@dp.callback_query(F.data.startswith("reqapp_"))
async def cb_req_approve_with_key(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    oid = int(callback.data.split("_", 1)[1])
    admin_states[callback.from_user.id] = {
        "step": "wait_approve_key",
        "order_id": oid,
    }
    await callback.message.answer(
        f"🔑 Order #{oid} এপ্রুভ করতে লিখুন:\n"
        f"/key XXXXXXXXXXXXX\n"
        f"(অথবা শুধু পাসওয়ার্ড/কি লিখেও পাঠাতে পারেন)"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rej_"))
async def cb_order_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    oid = int(callback.data.split("_", 1)[1])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.user_id, o.trx_id, o.status, pl.price
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        WHERE o.id = ?
        """,
        (oid,),
    )
    row = cur.fetchone()
    refund_msg = ""
    if row and row["status"] != "rejected":
        uid = row["user_id"]
        price = float(row["price"] or 0.0)
        is_bal_order = (row["trx_id"] or "") == "BALANCE_KEY_REQ"

        cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        if is_bal_order and price > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (price, uid))
            refund_msg = f"\n💰 ব্যালেন্স থেকে কাটা ৳{price:.0f} ফেরত দেওয়া হয়েছে।"
        conn.commit()
        try:
            await bot.send_message(
                uid,
                f"❌ আপনার অর্ডার #{oid} রিজেক্ট করা হয়েছে।{refund_msg}",
            )
        except Exception:
            pass
    conn.close()

    try:
        await callback.message.edit_text(f"❌ Order #{oid} marked as REJECTED.{refund_msg}")
    except Exception:
        await callback.message.answer(f"❌ Order #{oid} marked as REJECTED.{refund_msg}")
    await callback.answer()


@dp.callback_query(F.data.startswith("reqbal_"))
async def cb_req_balance_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    bid = int(callback.data.split("_", 1)[1])
    admin_states[callback.from_user.id] = {
        "step": "wait_bal_approve_amt",
        "bal_req_id": bid,
    }
    await callback.message.answer(
        f"💰 Balance Request #{bid} এপ্রুভ করতে লিখুন:\n"
        f"/balance 200\n"
        f"(অথবা শুধু সংখ্যা লিখেও পাঠাতে পারেন)"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rejbal_"))
async def cb_rej_balance(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    bid = int(callback.data.split("_", 1)[1])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM balance_requests WHERE id = ?", (bid,))
    row = cur.fetchone()
    if row:
        uid = row["user_id"]
        cur.execute("UPDATE balance_requests SET status = 'rejected' WHERE id = ?", (bid,))
        conn.commit()
        try:
            await bot.send_message(uid, f"❌ আপনার ব্যালেন্স রিকোয়েস্ট #{bid} রিজেক্ট করা হয়েছে।")
        except Exception:
            pass
    conn.close()

    try:
        await callback.message.edit_text(f"❌ Balance Request #{bid} REJECTED.")
    except Exception:
        await callback.message.answer(f"❌ Balance Request #{bid} REJECTED.")
    await callback.answer()


@dp.message()
async def handle_messages(message: Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()

    if uid == ADMIN_ID and uid in admin_states:
        state = admin_states[uid]
        step = state.get("step")

        if step == "set_pay_num":
            if len(txt) < 4:
                await message.answer("সঠিক নম্বর বা স্ট্যাটাস লিখুন:")
                return
            method = state.get("method", "bkash")
            update_payment_number(method, txt)
            admin_states.pop(uid, None)
            label = "বিকাশ" if method == "bkash" else "নগদ"
            await message.answer(f"✅ {label} নম্বর আপডেট হয়েছে: {txt}")
            return

        elif step == "user_lookup":
            try:
                target_uid = int(txt)
            except ValueError:
                await message.answer("সঠিক সংখ্যায় UserID লিখুন:")
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT full_name, username, balance, joined_at FROM users WHERE user_id = ?",
                (target_uid,),
            )
            urow = cur.fetchone()
            if not urow:
                conn.close()
                await message.answer("এই UserID ডেটাবেসে পাওয়া যায়নি।")
                return

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status = 'approved'",
                (target_uid,),
            )
            app_o = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status = 'pending'",
                (target_uid,),
            )
            pend_o = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM balance_requests WHERE user_id = ? AND status = 'approved'",
                (target_uid,),
            )
            app_b = cur.fetchone()["cnt"]
            conn.close()
            admin_states.pop(uid, None)

            await message.answer(
                f"🔎 ইউজার তথ্য:\n"
                f"• ID: {target_uid}\n"
                f"• নাম: {urow['full_name']} ({urow['username']})\n"
                f"• ব্যালেন্স: ৳{float(urow['balance'] or 0):.2f}\n"
                f"• জয়েন: {urow['joined_at']}\n"
                f"• এপ্রুভড অর্ডার: {app_o} | পেন্ডিং অর্ডার: {pend_o}\n"
                f"• এপ্রুভড ব্যালেন্স যোগ: {app_b}"
            )
            return

        elif step == "wait_approve_key":
            if not txt:
                await message.answer("দয়া করে Key / Password লিখুন:")
                return
            key_val = txt.split(maxsplit=1)[1].strip() if txt.lower().startswith("/key ") else txt
            oid = state["order_id"]
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id, plan_id FROM orders WHERE id = ?", (oid,))
            row = cur.fetchone()
            if not row:
                conn.close()
                admin_states.pop(uid, None)
                await message.answer("অর্ডার পাওয়া যায়নি।")
                return

            target_uid = row["user_id"]
            plid = row["plan_id"]
            cur.execute(
                "UPDATE orders SET delivered_key = ?, status = 'approved' WHERE id = ?",
                (key_val, oid),
            )
            cur.execute(
                "UPDATE plans SET stock = CASE WHEN stock > 0 THEN stock - 1 ELSE 0 END WHERE id = ?",
                (plid,),
            )
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)

            try:
                await bot.send_message(
                    target_uid,
                    f"✅ আপনার অর্ডার #{oid} এপ্রুভ হয়েছে!\n🔑 Key / Password: {key_val}",
                )
            except Exception:
                pass

            await message.answer(f"✅ Order #{oid} APPROVED!\n🔑 Sent Key/Password: {key_val}")
            return

        elif step == "wait_bal_approve_amt":
            raw_amt = txt.split(maxsplit=1)[1].strip() if txt.lower().startswith("/balance ") else txt
            try:
                amt = float(raw_amt)
                if amt <= 0:
                    raise ValueError()
            except ValueError:
                await message.answer("সঠিক সংখ্যা লিখুন। উদাহরণ: /balance 200")
                return

            bid = state["bal_req_id"]
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM balance_requests WHERE id = ?", (bid,))
            row = cur.fetchone()
            if not row:
                conn.close()
                admin_states.pop(uid, None)
                await message.answer("ব্যালেন্স রিকোয়েস্ট পাওয়া যায়নি।")
                return

            target_uid = row["user_id"]
            cur.execute("SELECT balance FROM users WHERE user_id = ?", (target_uid,))
            urow = cur.fetchone()
            if not urow:
                conn.close()
                admin_states.pop(uid, None)
                await message.answer("ইউজার পাওয়া যায়নি।")
                return

            new_bal = float(urow["balance"] or 0.0) + amt
            cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_uid))
            cur.execute("UPDATE balance_requests SET status = 'approved' WHERE id = ?", (bid,))
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)

            try:
                await bot.send_message(
                    target_uid,
                    f"✅ আপনার ব্যালেন্স রিকোয়েস্ট #{bid} এপ্রুভ হয়েছে!\n"
                    f"💰 যোগ হয়েছে: ৳{amt:.2f}\n"
                    f"💵 নতুন ব্যালেন্স: ৳{new_bal:.2f}",
                )
            except Exception:
                pass

            await message.answer(
                f"✅ Balance Request #{bid} APPROVED!\n"
                f"👤 User: {target_uid} | +৳{amt:.2f}\n"
                f"💰 New Balance: ৳{new_bal:.2f}"
            )
            return

        elif step == "edit_balance":
            mode = state.get("mode", "plus")
            if "|" not in txt:
                await message.answer("ফরম্যাট: UserID | Amount")
                return
            u_str, amt_str = [x.strip() for x in txt.split("|", 1)]
            try:
                target_uid = int(u_str)
                amt = float(amt_str)
                if amt <= 0:
                    raise ValueError()
            except ValueError:
                await message.answer("সঠিক UserID এবং ধনাত্মক Amount দিন।")
                return

            delta = amt if mode == "plus" else -amt
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT balance FROM users WHERE user_id = ?", (target_uid,))
            urow = cur.fetchone()
            if not urow:
                conn.close()
                await message.answer("এই UserID ডেটাবেসে পাওয়া যায়নি।")
                return
            new_bal = max(0.0, float(urow["balance"] or 0.0) + delta)
            cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_uid))
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)

            try:
                sign_txt = f"+৳{amt:.2f}" if mode == "plus" else f"-৳{amt:.2f}"
                await bot.send_message(
                    target_uid,
                    f"💰 ব্যালেন্স আপডেট ({sign_txt})\nনতুন ব্যালেন্স: ৳{new_bal:.2f}",
                )
            except Exception:
                pass

            await message.answer(
                f"✅ User {target_uid} ব্যালেন্স আপডেট হয়েছে: ৳{new_bal:.2f}"
            )
            return

        elif step == "broadcast":
            if not txt:
                await message.answer("মেসেজ খালি রাখা যাবে না।")
                return
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users")
            all_users = [r["user_id"] for r in cur.fetchall()]
            conn.close()
            admin_states.pop(uid, None)

            sent = 0
            for u_id in all_users:
                try:
                    await bot.send_message(u_id, f"📢 {txt}")
                    sent += 1
                except Exception:
                    pass
            await message.answer(f"✅ Broadcast পাঠানো হয়েছে {sent}/{len(all_users)} জন ইউজারকে।")
            return

        elif step == "add_prod":
            parts = [x.strip() for x in txt.split("|", 1)]
            pname = parts[0]
            cat_raw = parts[1].upper() if len(parts) > 1 else "ALL"
            valid_cats = {"ROOT", "NON_ROOT", "IOS", "PC_LAPTOP", "ALL"}
            cat_val = cat_raw if cat_raw in valid_cats else "ALL"
            if not pname:
                await message.answer("সঠিক নাম দিন।")
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO products (name, category) VALUES (?, ?)",
                (pname, cat_val),
            )
            pid = cur.lastrowid
            if DEFAULT_PLANS:
                cur.executemany(
                    "INSERT INTO plans (product_id, duration, price, stock, bonus) VALUES (?, ?, ?, ?, ?)",
                    [(pid, dur, pr, st, bon) for dur, pr, st, bon in DEFAULT_PLANS],
                )
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)
            await message.answer(
                f"✅ প্রোডাক্ট '{pname}' (ID: {pid}) [{cat_val}] যোগ হয়েছে।\n"
                f"এখন ⏱ Add Plan চেপে এর দিন/মেয়াদ যোগ করতে পারবেন।"
            )
            return

        elif step == "del_prod":
            try:
                pid = int(txt)
            except ValueError:
                await message.answer("সঠিক ProductID সংখ্যা লিখুন:")
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT name FROM products WHERE id = ?", (pid,))
            prow = cur.fetchone()
            if not prow:
                conn.close()
                await message.answer("এই ProductID পাওয়া যায়নি।")
                return

            cur.execute("DELETE FROM plans WHERE product_id = ?", (pid,))
            cur.execute("DELETE FROM products WHERE id = ?", (pid,))
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)
            await message.answer(f"🗑 প্রোডাক্ট '{prow['name']}' (ID: {pid}) এবং এর প্ল্যানগুলো রিমুভ হয়েছে।")
            return

        elif step == "add_plan_loop":
            parts = [x.strip() for x in txt.split("|")]
            if len(parts) < 3:
                await message.answer(
                    "ফরম্যাট ভুল! লিখুন:\n"
                    "ProductID | Duration | SitePrice | Offer(ঐচ্ছিক)\n"
                    "উদাহরণ: 2 | 1 Hour | 50"
                )
                return
            try:
                pid = int(parts[0])
                dur = parts[1]
                site_price = float(parts[2])
                bonus = parts[3] if len(parts) >= 4 else ""
                if not dur or site_price <= 0:
                    raise ValueError()
            except ValueError:
                await message.answer("ProductID এবং SitePrice সঠিক সংখ্যা হতে হবে (যেমন: 2 | 2 Days | 160)।")
                return

            brand_price = calc_brand_price(site_price)

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT name FROM products WHERE id = ?", (pid,))
            prow = cur.fetchone()
            if not prow:
                conn.close()
                await message.answer("এই ProductID পাওয়া যায়নি। আবার সঠিক ProductID দিয়ে লিখুন:")
                return
            cur.execute(
                "INSERT INTO plans (product_id, duration, price, stock, bonus) VALUES (?, ?, ?, 20, ?)",
                (pid, dur, brand_price, bonus),
            )
            conn.commit()
            conn.close()

            await message.answer(
                f"✅ '{prow['name']}'-এ '{dur}' যোগ হয়েছে!\n"
                f"• সাইট দাম: ৳{site_price:.0f} → আপনার ব্র্যান্ড দাম: ৳{brand_price:.0f}{format_bonus_bracket(bonus)}\n"
                f"পরের প্ল্যানটাও একইভাবে লিখুন (অথবা বের হতে /start দিন):"
            )
            return

        elif step == "del_plan_loop":
            try:
                plid = int(txt)
            except ValueError:
                await message.answer("সঠিক PlanID সংখ্যা লিখুন (উদাহরণ: 5):")
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT pl.duration, pl.price, p.name
                FROM plans pl
                JOIN products p ON pl.product_id = p.id
                WHERE pl.id = ?
                """,
                (plid,),
            )
            prow = cur.fetchone()
            if not prow:
                conn.close()
                await message.answer("এই PlanID পাওয়া যায়নি। অন্য PlanID লিখুন:")
                return

            cur.execute("DELETE FROM plans WHERE id = ?", (plid,))
            conn.commit()
            conn.close()
            await message.answer(
                f"🗑 Plan #{plid} ({prow['name']} - {prow['duration']} - ৳{float(prow['price']):.0f}) রিমুভ হয়েছে।\n"
                f"আরও প্ল্যান রিমুভ করতে চাইলে PlanID লিখুন (অথবা বের হতে /start দিন):"
            )
            return

        elif step == "edit_plan":
            parts = [x.strip() for x in txt.split("|")]
            if len(parts) < 2:
                await message.answer("ফরম্যাট: PlanID | BrandPrice | NewStock(ঐচ্ছিক)")
                return
            try:
                plid = int(parts[0])
                new_price = round_to_0_or_5(float(parts[1]))
                new_stock = int(parts[2]) if len(parts) >= 3 and parts[2] else None
                if new_price <= 0 or (new_stock is not None and new_stock < 0):
                    raise ValueError()
            except ValueError:
                await message.answer("সঠিক সংখ্যা লিখুন (যেমন: 3 | 120 | 25):")
                return

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, duration FROM plans WHERE id = ?", (plid,))
            prow = cur.fetchone()
            if not prow:
                conn.close()
                await message.answer("এই PlanID পাওয়া যায়নি।")
                return

            if new_stock is not None:
                cur.execute(
                    "UPDATE plans SET price = ?, stock = ? WHERE id = ?",
                    (new_price, new_stock, plid),
                )
            else:
                cur.execute(
                    "UPDATE plans SET price = ? WHERE id = ?",
                    (new_price, plid),
                )
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)
            stock_txt = f" | Stock: {new_stock}" if new_stock is not None else ""
            await message.answer(f"✅ Plan #{plid} ({prow['duration']}) আপডেট হয়েছে: ৳{new_price:.0f}{stock_txt}")
            return

        elif step == "set_offer":
            if "|" not in txt:
                await message.answer("ফরম্যাট: PlanID | Offer Text")
                return
            pl_str, offer_txt = [x.strip() for x in txt.split("|", 1)]
            try:
                plid = int(pl_str)
            except ValueError:
                await message.answer("PlanID অবশ্যই সংখ্যা হতে হবে।")
                return
            final_offer = "" if offer_txt == "-" else offer_txt
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE plans SET bonus = ? WHERE id = ?", (final_offer, plid))
            updated = cur.rowcount
            conn.commit()
            conn.close()
            admin_states.pop(uid, None)
            await message.answer(
                f"✅ Plan #{plid} অফার আপডেট হয়েছে: {final_offer or 'Removed'}"
                if updated
                else "এই PlanID পাওয়া যায়নি।"
            )
            return

    if uid in user_states:
        ustate = user_states[uid]
        _, _, lang, _ = get_user_info(uid)
        step = ustate.get("step")

        if step == "wait_bal_amount":
            try:
                amt = float(txt)
                if amt <= 0:
                    raise ValueError()
            except ValueError:
                await message.answer(
                    "সঠিক টাকার পরিমাণ লিখুন (উদাহরণ: 200):"
                    if lang == "bn"
                    else "Enter a valid amount (Example: 200):"
                )
                return

            bkash_num, nagad_num = get_payment_numbers()
            created = now_str()
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO balance_requests (user_id, requested_amount, status, created_at)
                VALUES (?, ?, 'pending_payment', ?)
                """,
                (uid, amt, created),
            )
            bid = cur.lastrowid
            conn.commit()
            conn.close()

            user_states[uid] = {
                "step": "wait_bal_proof",
                "bal_req_id": bid,
                "amount": amt,
                "created_at": created,
            }

            if lang == "bn":
                msg = (
                    f"💳 ব্যালেন্স রিকোয়েস্ট #{bid}\n"
                    f"💵 পরিমাণ: ৳{amt:.0f} (Send Money)\n\n"
                    f"📲 পেমেন্ট নম্বর:\n"
                    f"• বিকাশ: {bkash_num}\n"
                    f"• নগদ: {nagad_num}\n\n"
                    f"টাকা পাঠানোর পর যেকোনো ১টা দিন:\n"
                    f"📸 পেমেন্টের স্ক্রিনশট পাঠান\n"
                    f"অথবা\n"
                    f"✍️ সঠিক TrxID / মোবাইল নম্বর লিখে পাঠান"
                )
            else:
                msg = (
                    f"💳 Balance Request #{bid}\n"
                    f"💵 Amount: ৳{amt:.0f} (Send Money)\n\n"
                    f"📲 Payment Numbers:\n"
                    f"• bKash: {bkash_num}\n"
                    f"• Nagad: {nagad_num}\n\n"
                    f"After sending money, send any ONE:\n"
                    f"📸 Payment screenshot\n"
                    f"OR\n"
                    f"✍️ Valid TrxID / mobile number"
                )
            await message.answer(msg)
            return

        elif step == "wait_bal_proof":
            has_photo = bool(message.photo)
            valid_txt, cleaned_proof = is_valid_trx_or_proof_text(txt)

            if not has_photo and not valid_txt:
                bid = ustate["bal_req_id"]
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE balance_requests SET status = 'rejected' WHERE id = ?",
                    (bid,),
                )
                conn.commit()
                conn.close()
                user_states.pop(uid, None)
                await message.answer(
                    f"❌ অটো-রিজেক্ট! ব্যালেন্স রিকোয়েস্ট #{bid} বাতিল করা হয়েছে।\n"
                    f"সঠিক TrxID (যেমন: DKG8KD5RIA / 76CLUSN8), ১১ ডিজিটের মোবাইল নম্বর অথবা স্ক্রিনশট দিন।"
                    if lang == "bn"
                    else f"❌ Auto-Rejected! Balance request #{bid} was cancelled.\n"
                    f"Provide a valid TrxID (e.g. DKG8KD5RIA / 76CLUSN8), 11-digit mobile number, or screenshot."
                )
                return

            if valid_txt and is_duplicate_proof(cleaned_proof):
                bid = ustate["bal_req_id"]
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE balance_requests SET status = 'rejected' WHERE id = ?",
                    (bid,),
                )
                conn.commit()
                conn.close()
                user_states.pop(uid, None)
                await message.answer(
                    f"❌ ডুপ্লিকেট প্রুফ! ব্যালেন্স রিকোয়েস্ট #{bid} অটো-রিজেক্ট করা হয়েছে।\n"
                    f"এই TrxID বা নম্বরটি আগে ব্যবহার করা হয়েছে।"
                    if lang == "bn"
                    else f"❌ Duplicate proof! Balance request #{bid} was auto-rejected.\n"
                    f"This TrxID or number has already been used."
                )
                return

            bid = ustate["bal_req_id"]
            amt = ustate["amount"]
            created = ustate["created_at"]
            photo_id = message.photo[-1].file_id if has_photo else ""
            proof_text = cleaned_proof if valid_txt else ""

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE balance_requests
                SET proof_text = ?, proof_photo_id = ?, status = 'pending'
                WHERE id = ? AND user_id = ?
                """,
                (proof_text, photo_id, bid, uid),
            )
            conn.commit()
            conn.close()

            user_states.pop(uid, None)

            await message.answer(
                f"✅ ব্যালেন্স রিকোয়েস্ট #{bid} জমা হয়েছে!\nঅ্যাডমিন চেক করে ব্যালেন্স যোগ করে দেবেন।"
                if lang == "bn"
                else f"✅ Balance request #{bid} submitted!\nAdmin will review and add your balance."
            )

            full_name, username, _, bal = get_user_info(uid)
            info_line = f"\n🧾 Info: {proof_text}" if proof_text else ""
            photo_line = "\n📸 Proof: Screenshot attached" if photo_id else ""

            admin_alert = (
                f"💳 [BALANCE REQUEST] #{bid}\n"
                f"🕒 Time: {created}\n"
                f"👤 User: {full_name} ({username}) | ID: {uid}\n"
                f"💰 Current Balance: ৳{bal:.2f}\n"
                f"💵 Requested Amount: ৳{amt:.0f}{info_line}{photo_line}\n\n"
                f"ব্যালেন্স দিতে লিখুন:\n"
                f"/balance {amt:.0f}"
            )

            try:
                if photo_id:
                    await bot.send_photo(
                        ADMIN_ID,
                        photo=photo_id,
                        caption=admin_alert,
                        reply_markup=bal_req_kb(bid),
                    )
                else:
                    await bot.send_message(
                        ADMIN_ID,
                        admin_alert,
                        reply_markup=bal_req_kb(bid),
                    )
            except Exception:
                pass
            return

        elif step == "wait_proof":
            has_photo = bool(message.photo)
            valid_txt, cleaned_proof = is_valid_trx_or_proof_text(txt)

            if not has_photo and not valid_txt:
                oid = ustate["order_id"]
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE orders SET status = 'rejected' WHERE id = ?",
                    (oid,),
                )
                conn.commit()
                conn.close()
                user_states.pop(uid, None)
                await message.answer(
                    f"❌ অটো-রিজেক্ট! অর্ডার #{oid} বাতিল করা হয়েছে।\n"
                    f"ভুয়া বা অসম্পূর্ণ তথ্য গ্রহণযোগ্য নয়—সঠিক TrxID (যেমন: DKG8KD5RIA / 76CLUSN8), ১১ ডিজিটের মোবাইল নম্বর অথবা স্ক্রিনশট দিন।"
                    if lang == "bn"
                    else f"❌ Auto-Rejected! Order #{oid} was cancelled.\n"
                    f"Invalid proof—send a valid TrxID (e.g. DKG8KD5RIA / 76CLUSN8), 11-digit mobile number, or screenshot."
                )
                return

            if valid_txt and is_duplicate_proof(cleaned_proof):
                oid = ustate["order_id"]
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE orders SET status = 'rejected' WHERE id = ?",
                    (oid,),
                )
                conn.commit()
                conn.close()
                user_states.pop(uid, None)
                await message.answer(
                    f"❌ ডুপ্লিকেট প্রুফ! অর্ডার #{oid} অটো-রিজেক্ট করা হয়েছে।\n"
                    f"এই TrxID বা নম্বরটি আগে ব্যবহার করা হয়েছে।"
                    if lang == "bn"
                    else f"❌ Duplicate proof! Order #{oid} was auto-rejected.\n"
                    f"This TrxID or number has already been used."
                )
                return

            oid = ustate["order_id"]
            pname = ustate["pname"]
            duration = ustate["duration"]
            price = ustate["price"]
            bonus = ustate.get("bonus", "")
            created = ustate.get("created_at", now_str())

            photo_id = message.photo[-1].file_id if has_photo else ""
            proof_text = cleaned_proof if valid_txt else ""

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE orders
                SET trx_id = ?, proof_photo_id = ?, status = 'pending'
                WHERE id = ? AND user_id = ?
                """,
                (proof_text, photo_id, oid, uid),
            )
            conn.commit()
            conn.close()

            user_states.pop(uid, None)

            await message.answer(
                f"✅ অর্ডার #{oid} জমা হয়েছে!\nঅ্যাডমিন চেক করে Key / Password পাঠাবেন।"
                if lang == "bn"
                else f"✅ Order #{oid} submitted!\nAdmin will check and send your Key / Password."
            )

            full_name, username, _, bal = get_user_info(uid)
            offer_line = f"\n🎁 Offer: {bonus}" if bonus else ""
            info_line = f"\n🧾 Info: {proof_text}" if proof_text else ""
            photo_line = "\n📸 Proof: Screenshot attached" if photo_id else ""

            admin_alert = (
                f"🔑 [PASSWORD REQUEST] Order #{oid}\n"
                f"🕒 Time: {created}\n"
                f"👤 User: {full_name} ({username}) | ID: {uid}\n"
                f"💰 Balance: ৳{bal:.2f}\n"
                f"📦 প্যানেল / প্রোডাক্ট: {pname} ({duration}) - ৳{price:.0f}{offer_line}{info_line}{photo_line}\n\n"
                f"পাসওয়ার্ড দিতে লিখুন:\n"
                f"/key XXXXXXXXXXXXX"
            )

            try:
                if photo_id:
                    await bot.send_photo(
                        ADMIN_ID,
                        photo=photo_id,
                        caption=admin_alert,
                        reply_markup=order_approve_start_kb(oid),
                    )
                else:
                    await bot.send_message(
                        ADMIN_ID,
                        admin_alert,
                        reply_markup=order_approve_start_kb(oid),
                    )
            except Exception:
                pass
            return


async def health_handler(request: web.Request):
    return web.Response(text="OK")


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()


async def main():
    init_db()
    await start_health_server()
    print(f"Bot is running on port {PORT}...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())