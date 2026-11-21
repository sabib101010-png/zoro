import asyncio
from datetime import datetime
import os
import re
import sqlite3
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN", "9211572979:AAEI73Lq3e1FbtcmiYpQSmYlYjzMMh3QKvg"
)
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

# কাস্টম প্রাইস স্ল্যাব (সাইট প্রাইস -> ব্র্যান্ড প্রাইস)
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


def is_dolphin_product(pname: str) -> bool:
  return "dolphin" in (pname or "").strip().lower()


def is_three_days_or_more(duration: str) -> bool:
  s = (duration or "").strip().lower()
  if "hour" in s or "hr" in s:
    return False
  m = re.search(r"(\d+)\s*day", s)
  if not m:
    return False
  return int(m.group(1)) >= 3


def calc_brand_price(site_price: float, pname: str = "") -> float:
  sp = float(site_price)
  if sp <= 0:
    return 0.0

  if is_dolphin_product(pname):
    return round_to_0_or_5(sp)

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

  # কেনা দাম বিক্রয়মূল্যের চেয়ে ~30% কম (0.70x) ধরে নিরাপদ ফ্লোর
  cost_est = sp * 0.70
  min_safe_price = cost_est * 1.12
  return round_to_0_or_5(max(raw, min_safe_price))


def calc_discount_details(
    pname: str, duration: str, base_price: float, user_disc_pct: float
) -> tuple[float, float, float]:
  """
    রিটার্ন করে: (applied_pct, discount_amount, final_price)
    - Dolphin প্যানেলে ডিসকাউন্ট 0%
    - 3 দিনের নিচের প্ল্যানে ডিসকাউন্ট 0%
    - প্রতি রেফারে 2% জমে; সাধারণ প্রোডাক্টে সর্বোচ্চ 5%, আর 600 টাকার ওপরে সর্বোচ্চ 30%
    - কেনা দাম (প্রায় 70% of base_price) ও ন্যূনতম লাভের নিচে দাম নামতে দেবে না
    """
  price = float(base_price)
  if price <= 0 or is_dolphin_product(pname) or not is_three_days_or_more(duration):
    return 0.0, 0.0, round_to_0_or_5(price)

  avail_pct = max(0.0, float(user_disc_pct or 0.0))
  if avail_pct <= 0:
    return 0.0, 0.0, round_to_0_or_5(price)

  max_cap_pct = 30.0 if price > 600.0 else 5.0
  applied_pct = min(avail_pct, max_cap_pct)

  raw_after = price * (1.0 - (applied_pct / 100.0))
  # কেনা দাম (~0.70x) + সামান্য লাভের সুরক্ষা যেন ডিসকাউন্টে লস না হয়
  cost_floor = price * 0.70
  profit_guard = price * 0.75
  safe_floor = max(cost_floor, profit_guard)

  if raw_after < safe_floor:
    max_safe_disc_amt = max(0.0, price - safe_floor)
    applied_pct = round((max_safe_disc_amt / price) * 100.0, 2)
    final_price = round_to_0_or_5(safe_floor)
  else:
    final_price = round_to_0_or_5(raw_after)

  disc_amt = max(0.0, round(price - final_price, 2))
  if disc_amt <= 0 or applied_pct <= 0:
    return 0.0, 0.0, round_to_0_or_5(price)

  return applied_pct, disc_amt, final_price


# (product_name, category_key, [(duration, price_or_site_price, stock, bonus, is_fixed_official), ...])
RAW_CATALOG = [
    (
        "DOLPHIN PLUSH - ROOT",
        "ROOT",
        [
            ("7 Days", 500.0, 15, "", True),
            ("15 Days", 900.0, 10, "", True),
            ("30 Days", 1500.0, 10, "", True),
        ],
    ),
    (
        "DELTA MODS - ROOT",
        "ROOT",
        [
            ("1 Day", 50.0, 25, "", False),
            ("7 Day", 280.0, 20, "", False),
            ("15 Day", 480.0, 15, "", False),
            ("30 Day", 700.0, 10, "", False),
        ],
    ),
    (
        "BR MODS - ROOT",
        "ROOT",
        [
            ("1 Day", 50.0, 25, "", False),
            ("10 Day", 380.0, 15, "", False),
            ("30 Day", 680.0, 10, "", False),
        ],
    ),
    (
        "TITAN MODS - ROOT",
        "ROOT",
        [
            ("1 Day", 50.0, 25, "", False),
            ("7 Day", 250.0, 20, "", False),
            ("15 Day", 450.0, 15, "", False),
            ("30 Day", 700.0, 10, "", False),
        ],
    ),
    (
        "DRIP WIRE - NON ROOT",
        "NON_ROOT",
        [
            ("3 Hour", 25.0, 30, "", False),
            ("6 Hour", 50.0, 30, "", False),
            ("12 Hour", 80.0, 25, "", False),
            ("1 Day", 120.0, 20, "", False),
            ("7 Day", 480.0, 15, "", False),
            ("30 Day", 850.0, 10, "", False),
        ],
    ),
    (
        "ANGRY MODS - ROOT",
        "ROOT",
        [
            ("1 Day", 70.0, 20, "", False),
            ("7 Day", 300.0, 20, "", False),
            ("15 Day", 500.0, 15, "", False),
            ("30 Day", 800.0, 10, "", False),
        ],
    ),
    (
        "DRIP APKMOD - NON ROOT",
        "NON_ROOT",
        [
            ("1 Day", 50.0, 25, "", False),
            ("3 Day", 100.0, 20, "", False),
            ("7 Day", 200.0, 20, "", False),
            ("15 Day", 350.0, 15, "", False),
            ("30 Day", 580.0, 10, "", False),
        ],
    ),
    (
        "BR MOD PC",
        "PC_LAPTOP",
        [
            ("1 Day", 90.0, 20, "", False),
            ("10 Day", 280.0, 15, "", False),
            ("30 Day", 480.0, 10, "", False),
        ],
    ),
]

CATALOG_PRODUCTS = [
    (
        pname,
        cat_key,
        [
            (
                dur,
                round_to_0_or_5(pr)
                if fixed_off
                else calc_brand_price(pr, pname),
                stk,
                bon,
            )
            for dur, pr, stk, bon, fixed_off in plist
        ],
    )
    for pname, cat_key, plist in RAW_CATALOG
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

  junk_tokens = (
      "QWERTY",
      "ASDF",
      "ZXCV",
      "TEST",
      "FAKE",
      "DEMO",
      "XXXX",
      "ABCD",
  )
  if any(tok in trx for tok in junk_tokens):
    return False, trx

  return True, trx


def is_duplicate_proof(proof_val: str) -> bool:
  val = (proof_val or "").strip().upper()
  if not val:
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
  conn.close()
  return o_cnt > 0


def sync_catalog_prices(cur: sqlite3.Cursor):
  for rem_name in REMOVED_PRODUCTS:
    cur.execute(
        "SELECT id FROM products WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
        (rem_name,),
    )
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
          "INSERT INTO plans (product_id, duration, price, stock, bonus)"
          " VALUES (?, ?, ?, ?, ?)",
          [(pid, dur, pr, st, bon) for dur, pr, st, bon in plist],
      )
    else:
      pid = prow["id"]
      if prow["category"] != cat_key:
        cur.execute(
            "UPDATE products SET category = ? WHERE id = ?", (cat_key, pid)
        )
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
              "INSERT INTO plans (product_id, duration, price, stock, bonus)"
              " VALUES (?, ?, ?, ?, ?)",
              (pid, dur, pr, st, bon),
          )


def init_db():
  conn = get_conn()
  cur = conn.cursor()

  cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            lang TEXT DEFAULT 'bn',
            balance REAL DEFAULT 0.0,
            discount_pct REAL DEFAULT 0.0,
            referral_count INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT ''
        )
        """)
  cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'ALL'
        )
        """)
  cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            duration TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 10,
            bonus TEXT DEFAULT '',
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
        """)
  cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            sender_number TEXT DEFAULT '',
            trx_id TEXT DEFAULT '',
            proof_photo_id TEXT DEFAULT '',
            delivered_key TEXT DEFAULT '',
            discount_used_pct REAL DEFAULT 0.0,
            final_amount REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending_payment',
            created_at TEXT DEFAULT ''
        )
        """)
  cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bkash TEXT DEFAULT '',
            nagad TEXT DEFAULT ''
        )
        """)

  cur.execute("PRAGMA table_info(users)")
  u_cols = [c["name"] for c in cur.fetchall()]
  if "discount_pct" not in u_cols:
    cur.execute("ALTER TABLE users ADD COLUMN discount_pct REAL DEFAULT 0.0")
  if "referral_count" not in u_cols:
    cur.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
  if "referred_by" not in u_cols:
    cur.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT 0")

  cur.execute("PRAGMA table_info(orders)")
  o_cols = [c["name"] for c in cur.fetchall()]
  if "proof_photo_id" not in o_cols:
    cur.execute("ALTER TABLE orders ADD COLUMN proof_photo_id TEXT DEFAULT ''")
  if "discount_used_pct" not in o_cols:
    cur.execute(
        "ALTER TABLE orders ADD COLUMN discount_used_pct REAL DEFAULT 0.0"
    )
  if "final_amount" not in o_cols:
    cur.execute("ALTER TABLE orders ADD COLUMN final_amount REAL DEFAULT 0.0")

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


def register_or_update_user(message: Message, referrer_id: int = 0):
  uid = message.from_user.id
  full_name = message.from_user.full_name or "User"
  username = (
      f"@{message.from_user.username}" if message.from_user.username else "N/A"
  )
  joined = now_str()

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT lang, discount_pct, referral_count FROM users WHERE user_id = ?",
      (uid,),
  )
  existing = cur.fetchone()
  is_new = existing is None
  ref_awarded_to = 0

  if is_new:
    valid_ref = 0
    if referrer_id and referrer_id != uid:
      cur.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
      if cur.fetchone():
        valid_ref = referrer_id

    cur.execute(
        """
            INSERT INTO users (
                user_id, full_name, username, lang, balance,
                discount_pct, referral_count, referred_by, joined_at
            )
            VALUES (?, ?, ?, 'bn', 0.0, 0.0, 0, ?, ?)
            """,
        (uid, full_name, username, valid_ref, joined),
    )
    if valid_ref:
      # প্রতি বৈধ রেফারে 2% ডিসকাউন্ট যোগ (ম্যাক্স 30% পর্যন্ত জমতে পারবে)
      cur.execute(
          """
                UPDATE users
                SET referral_count = referral_count + 1,
                    discount_pct = MIN(30.0, ROUND(discount_pct + 2.0, 2))
                WHERE user_id = ?
                """,
          (valid_ref,),
      )
      ref_awarded_to = valid_ref

    lang = "bn"
    disc_pct = 0.0
    ref_cnt = 0
  else:
    lang = existing["lang"] or "bn"
    disc_pct = float(existing["discount_pct"] or 0.0)
    ref_cnt = int(existing["referral_count"] or 0)
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

  return (
      is_new,
      lang,
      disc_pct,
      ref_cnt,
      total_users,
      full_name,
      username,
      joined,
      ref_awarded_to,
  )


def set_lang(user_id: int, lang: str):
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        INSERT INTO users (user_id, full_name, username, lang, balance, discount_pct, referral_count, referred_by, joined_at)
        VALUES (?, 'User', 'N/A', ?, 0.0, 0.0, 0, 0, ?)
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
      "SELECT full_name, username, lang, discount_pct, referral_count FROM"
      " users WHERE user_id = ?",
      (user_id,),
  )
  row = cur.fetchone()
  conn.close()
  if not row:
    return "User", "N/A", "bn", 0.0, 0
  return (
      row["full_name"] or "User",
      row["username"] or "N/A",
      row["lang"] or "bn",
      float(row["discount_pct"] or 0.0),
      int(row["referral_count"] or 0),
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
              InlineKeyboardButton(text="🛡 Root", callback_data="cat_ROOT"),
              InlineKeyboardButton(
                  text="🔓 Non Root", callback_data="cat_NON_ROOT"
              ),
          ],
          [
              InlineKeyboardButton(text="📱 iOS", callback_data="cat_IOS"),
              InlineKeyboardButton(
                  text="💻 PC/Laptop", callback_data="cat_PC_LAPTOP"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="🌐 ALL Products", callback_data="cat_ALL"
              ),
          ],
      ]
  )


def main_menu(user_id: int, lang: str) -> ReplyKeyboardMarkup:
  if lang == "en":
    rows = [
        [
            KeyboardButton(text="🛒 Buy Keys"),
            KeyboardButton(text="🎁 My Discount"),
        ],
        [
            KeyboardButton(text="🔗 Refer & Earn"),
            KeyboardButton(text="📦 My Orders"),
        ],
        [
            KeyboardButton(text="🌐 Change Language"),
            KeyboardButton(text="📞 Support"),
        ],
    ]
  else:
    rows = [
        [
            KeyboardButton(text="🛒 কি কিনুন"),
            KeyboardButton(text="🎁 মাই ডিসকাউন্ট"),
        ],
        [
            KeyboardButton(text="🔗 রেফার লিংক"),
            KeyboardButton(text="📦 আমার অর্ডার"),
        ],
        [
            KeyboardButton(text="🌐 ভাষা পরিবর্তন"),
            KeyboardButton(text="📞 সাপোর্ট"),
        ],
    ]
  if user_id == ADMIN_ID:
    rows.append([KeyboardButton(text="🛠 Admin Panel")])
  return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def lang_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(text="🇧🇩 বাংলা", callback_data="setlang_bn"),
          InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en"),
      ]]
  )


def admin_panel_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="➕ Add Product", callback_data="adm_addprod"
              ),
              InlineKeyboardButton(
                  text="🗑 Del Product", callback_data="adm_delprod"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="⏱ Add Plan", callback_data="adm_addplan"
              ),
              InlineKeyboardButton(
                  text="🗑 Del Plan", callback_data="adm_delplan"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="✏️ Edit Plan", callback_data="adm_editplan"
              ),
              InlineKeyboardButton(
                  text="🎁 Set Offer", callback_data="adm_setoffer"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="📋 Pending Orders", callback_data="adm_orders"
              ),
              InlineKeyboardButton(
                  text="💳 Payment Numbers", callback_data="adm_paynums"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="🔎 User Lookup", callback_data="adm_lookup"
              ),
              InlineKeyboardButton(
                  text="📊 Sales Report", callback_data="adm_report"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="📢 Broadcast", callback_data="adm_broadcast"
              ),
              InlineKeyboardButton(
                  text="👥 Users & Stats", callback_data="adm_users"
              ),
          ],
      ]
  )


def payment_numbers_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[[
          InlineKeyboardButton(
              text="📱 Set bKash", callback_data="setpay_bkash"
          ),
          InlineKeyboardButton(
              text="📱 Set Nagad", callback_data="setpay_nagad"
          ),
      ]]
  )


def order_approve_start_kb(oid: int) -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(inline_keyboard=[[
      InlineKeyboardButton(
          text="🔑 Enter Key & Approve", callback_data=f"reqapp_{oid}"
      ),
      InlineKeyboardButton(text="❌ Reject", callback_data=f"rej_{oid}"),
  ]])


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
  uid = message.from_user.id
  admin_states.pop(uid, None)
  user_states.pop(uid, None)

  ref_id = 0
  parts = (message.text or "").strip().split(maxsplit=1)
  if len(parts) == 2 and parts[1].strip().isdigit():
    ref_id = int(parts[1].strip())

  (
      is_new,
      lang,
      disc_pct,
      ref_cnt,
      total_users,
      full_name,
      username,
      joined,
      ref_awarded_to,
  ) = register_or_update_user(message, referrer_id=ref_id)

  if ref_awarded_to:
    try:
      await bot.send_message(
          ref_awarded_to,
          f"🎉 নতুন রেফার সফল হয়েছে! আপনার মাই ডিসকাউন্টে +2% ডিসকাউন্ট যোগ"
          f" হয়েছে।",
      )
    except Exception:
      pass

  if is_new and message.from_user.id != ADMIN_ID:
    new_user_alert = (
        f"🎉 New User Joined!\n\n"
        f"👤 Name: {full_name}\n"
        f"🆔 Username: {username}\n"
        f"💬 Chat ID: {message.from_user.id}\n"
        f"🔗 Referred By: {ref_awarded_to or 'None'}\n"
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
  welcome_txt = (
      f"ZORO 404 OFFICIAL\n"
      f"🎁 জমে থাকা ডিসকাউন্ট: {disc_pct:.0f}% | রেফার: {ref_cnt}"
      if lang == "bn"
      else f"ZORO 404 OFFICIAL\n"
      f"🎁 Saved Discount: {disc_pct:.0f}% | Referrals: {ref_cnt}"
  )
  await message.answer(welcome_txt, reply_markup=main_menu(uid, lang))


@dp.callback_query(F.data.startswith("setlang_"))
async def cb_setlang(callback: CallbackQuery):
  lang = callback.data.split("_", 1)[1]
  set_lang(callback.from_user.id, lang)
  _, _, _, disc_pct, ref_cnt = get_user_info(callback.from_user.id)
  await callback.message.edit_text(
      "✅ বাংলা সেট করা হয়েছে।" if lang == "bn" else "✅ English set."
  )
  await callback.message.answer(
      f"মেইন মেনু | 🎁 ডিসকাউন্ট: {disc_pct:.0f}% (রেফার: {ref_cnt})"
      if lang == "bn"
      else f"Main Menu | 🎁 Discount: {disc_pct:.0f}% (Refs: {ref_cnt})",
      reply_markup=main_menu(callback.from_user.id, lang),
  )
  await callback.answer()


@dp.message(F.text.in_(["🎁 মাই ডিসকাউন্ট", "🎁 My Discount"]))
async def btn_my_discount(message: Message):
  admin_states.pop(message.from_user.id, None)
  full_name, username, lang, disc_pct, ref_cnt = get_user_info(
      message.from_user.id
  )
  if lang == "bn":
    txt = (
        f"🎁 মাই ডিসকাউন্ট\n\n"
        f"• ইউজার: {full_name} ({username})\n"
        f"• মোট সফল রেফার: {ref_cnt} জন\n"
        f"• জমে থাকা ডিসকাউন্ট: {disc_pct:.0f}%\n\n"
        f"নিয়মাবলি:\n"
        f"1. প্রতি সফল রেফারে +2% ডিসকাউন্ট জমা হয়।\n"
        f"2. ৩ দিনের নিচের প্ল্যানে কোনো ডিসকাউন্ট নেই (0%)।\n"
        f"3. ৩ দিন বা তার বেশি দিনের প্ল্যানে সাধারণত সর্বোচ্চ 5% এবং 600"
        f" টাকার ওপরে সর্বোচ্চ 30% পর্যন্ত ডিসকাউন্ট পাওয়া যায়।\n"
        f"4. Dolphin প্যানেলে ডেভেলপারের নিয়ম অনুযায়ী কোনো ডিসকাউন্ট নেই।\n"
        f"5. ডিসকাউন্ট ব্যবহার হলে ব্যবহৃত অংশ কেটে নেওয়া হয় এবং কেনা দামের"
        f" নিচে নামার সুযোগ নেই।"
    )
  else:
    txt = (
        f"🎁 My Discount\n\n"
        f"• User: {full_name} ({username})\n"
        f"• Valid Referrals: {ref_cnt}\n"
        f"• Saved Discount: {disc_pct:.0f}%\n\n"
        f"Rules:\n"
        f"1. +2% discount per valid referral.\n"
        f"2. 0% discount on plans under 3 days.\n"
        f"3. Up to 5% on 3+ day plans, and up to 30% above ৳600 (within"
        f" profit safety).\n"
        f"4. No discount on Dolphin panels.\n"
        f"5. Used discount is deducted after order approval."
    )
  await message.answer(txt)


@dp.message(F.text.in_(["🔗 রেফার লিংক", "🔗 Refer & Earn"]))
async def btn_refer_link(message: Message):
  admin_states.pop(message.from_user.id, None)
  uid = message.from_user.id
  _, _, lang, disc_pct, ref_cnt = get_user_info(uid)
  me = await bot.get_me()
  ref_link = f"https://t.me/{me.username}?start={uid}"
  if lang == "bn":
    txt = (
        f"🔗 রেফার ও ডিসকাউন্ট\n\n"
        f"আপনার রেফার লিংক:\n{ref_link}\n\n"
        f"• সফল রেফার: {ref_cnt} জন\n"
        f"• জমে থাকা ডিসকাউন্ট: {disc_pct:.0f}%\n"
        f"প্রতি রেফারে 2% ডিসকাউন্ট পাবেন।"
    )
  else:
    txt = (
        f"🔗 Refer & Discount\n\n"
        f"Your referral link:\n{ref_link}\n\n"
        f"• Valid Referrals: {ref_cnt}\n"
        f"• Saved Discount: {disc_pct:.0f}%\n"
        f"Earn 2% discount per valid referral."
    )
  await message.answer(txt)


@dp.message(F.text.in_(["🌐 ভাষা পরিবর্তন", "🌐 Change Language"]))
async def btn_change_lang(message: Message):
  admin_states.pop(message.from_user.id, None)
  await message.answer("ভাষা বেছে নিন / Choose language:", reply_markup=lang_kb())


@dp.message(F.text.in_(["🛒 কি কিনুন", "🛒 Buy Keys"]))
async def btn_buy_keys(message: Message):
  admin_states.pop(message.from_user.id, None)
  _, _, lang, disc_pct, _ = get_user_info(message.from_user.id)
  header = (
      f"🎁 জমে থাকা ডিসকাউন্ট: {disc_pct:.0f}%\nক্যাটাগরি সিলেক্ট করুন:"
      if lang == "bn"
      else f"🎁 Saved Discount: {disc_pct:.0f}%\nSelect a category:"
  )
  await message.answer(header, reply_markup=category_kb())


@dp.callback_query(F.data.startswith("cat_"))
async def cb_select_category(callback: CallbackQuery):
  cat_key = callback.data.split("_", 1)[1]
  _, _, lang, _, _ = get_user_info(callback.from_user.id)

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
      [
          InlineKeyboardButton(
              text=f"🔹 {row['name']}", callback_data=f"prod_{row['id']}"
          )
      ]
      for row in prods
  ]
  rows.append([
      InlineKeyboardButton(text="⬅️ ক্যাটাগরি পরিবর্তন", callback_data="back_cats")
  ])

  header = (
      f"ক্যাটাগরি: {cat_title}\nপ্রোডাক্ট সিলেক্ট করুন:"
      if lang == "bn"
      else f"Category: {cat_title}\nSelect a product:"
  )
  await callback.message.edit_text(
      header, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
  )
  await callback.answer()


@dp.callback_query(F.data == "back_cats")
async def cb_back_cats(callback: CallbackQuery):
  _, _, lang, _, _ = get_user_info(callback.from_user.id)
  await callback.message.edit_text(
      "ক্যাটাগরি সিলেক্ট করুন:" if lang == "bn" else "Select a category:",
      reply_markup=category_kb(),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("prod_"))
async def cb_select_product(callback: CallbackQuery):
  pid = int(callback.data.split("_", 1)[1])
  _, _, lang, disc_pct, _ = get_user_info(callback.from_user.id)

  conn = get_conn()
  cur = conn.cursor()
  cur.execute("SELECT name, category FROM products WHERE id = ?", (pid,))
  p_row = cur.fetchone()
  cur.execute(
      "SELECT id, duration, price, bonus FROM plans WHERE product_id = ?"
      " ORDER BY id",
      (pid,),
  )
  plans = cur.fetchall()
  conn.close()

  if not p_row:
    await callback.answer("Product not found", show_alert=True)
    return

  if not plans:
    await callback.answer(
        "এই প্রোডাক্টে এখনো কোনো প্ল্যান যোগ করা হয়নি।"
        if lang == "bn"
        else "No plans added for this product yet.",
        show_alert=True,
    )
    return

  pname = p_row["name"]
  cat_back = p_row["category"] or "ALL"
  buttons = []
  for pl in plans:
    base_p = float(pl["price"])
    app_pct, _, final_p = calc_discount_details(
        pname, pl["duration"], base_p, disc_pct
    )
    disc_tag = f" (-{app_pct:.0f}% → ৳{final_p:.0f})" if app_pct > 0 else ""
    label = (
        f"{pl['duration']} - ৳{base_p:.0f}{disc_tag}{format_bonus_bracket(pl['bonus'])}"
    )
    buttons.append(
        [InlineKeyboardButton(text=label, callback_data=f"plan_{pl['id']}")]
    )

  buttons.append(
      [InlineKeyboardButton(text="⬅️ Back", callback_data=f"cat_{cat_back}")]
  )

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
  _, _, lang, disc_pct, _ = get_user_info(uid)

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
  base_price = float(row["price"])
  bonus = row["bonus"] or ""
  app_pct, disc_amt, final_price = calc_discount_details(
      pname, duration, base_price, disc_pct
  )

  bkash_num, nagad_num = get_payment_numbers()
  created = now_str()

  cur.execute(
      """
        INSERT INTO orders (
            user_id, plan_id, discount_used_pct, final_amount, status, created_at
        )
        VALUES (?, ?, ?, ?, 'pending_payment', ?)
        """,
      (uid, plid, app_pct, final_price, created),
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
      "base_price": base_price,
      "discount_pct": app_pct,
      "discount_amt": disc_amt,
      "final_price": final_price,
      "bonus": bonus,
      "created_at": created,
  }

  bonus_line = f"\n🎁 অফার: {bonus}" if bonus else ""
  if app_pct > 0:
    price_lines = (
        f"💵 মূল দাম: ৳{base_price:.0f}\n"
        f"🎁 ডিসকাউন্ট ({app_pct:.0f}%): -৳{disc_amt:.0f}\n"
        f"✅ পরিশোধযোগ্য: ৳{final_price:.0f} (Send Money)"
    )
  else:
    price_lines = f"💵 মোট টাকা: ৳{final_price:.0f} (Send Money)"

  if lang == "bn":
    msg = (
        f"🛒 অর্ডার #{oid}\n"
        f"📦 {pname} ({duration}){bonus_line}\n"
        f"{price_lines}\n\n"
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
        f"{price_lines}\n\n"
        f"📲 Payment Numbers:\n"
        f"• bKash: {bkash_num}\n"
        f"• Nagad: {nagad_num}\n\n"
        f"After sending money, send any ONE:\n"
        f"📸 Payment screenshot\n"
        f"OR\n"
        f"✍️ Valid TrxID / mobile number"
    )

  await callback.message.edit_text(msg)
  await callback.answer()


@dp.message(F.text.in_(["📦 আমার অর্ডার", "📦 My Orders"]))
async def btn_my_orders(message: Message):
  admin_states.pop(message.from_user.id, None)
  _, _, lang, _, _ = get_user_info(message.from_user.id)
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT o.id, p.name, pl.duration, pl.price, o.final_amount,
               o.discount_used_pct, o.sender_number, o.trx_id,
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
    await message.answer(
        "আপনার কোনো অর্ডার নেই।" if lang == "bn" else "No orders yet."
    )
    return

  lines = []
  for r in rows:
    proof_txt = (
        r["trx_id"]
        or r["sender_number"]
        or ("Screenshot sent" if r["proof_photo_id"] else "-")
    )
    key_txt = f"\n   🔑 Key/Pass: {r['delivered_key']}" if r["delivered_key"] else ""
    st_txt = status_label(r["status"], lang)
    paid_amt = float(r["final_amount"] or r["price"] or 0.0)
    disc_u = float(r["discount_used_pct"] or 0.0)
    disc_txt = f" (-{disc_u:.0f}%)" if disc_u > 0 else ""
    lines.append(
        f"#{r['id']} | {r['name']} ({r['duration']}) -"
        f" ৳{paid_amt:.0f}{disc_txt} [{st_txt}]\n"
        f"   🕒 {r['created_at']} | Proof: {proof_txt}{key_txt}"
    )
  await message.answer("\n\n".join(lines))


@dp.message(F.text.in_(["📞 সাপোর্ট", "📞 Support"]))
async def btn_support(message: Message):
  admin_states.pop(message.from_user.id, None)
  _, _, lang, _, _ = get_user_info(message.from_user.id)
  bkash_num, nagad_num = get_payment_numbers()
  msg = (
      f"সাপোর্টের জন্য যোগাযোগ করুন: {SUPPORT_HANDLE}\n"
      f"বিকাশ: {bkash_num} | নগদ: {nagad_num}"
      if lang == "bn"
      else f"Contact for support: {SUPPORT_HANDLE}\n"
      f"bKash: {bkash_num} | Nagad: {nagad_num}"
  )
  await message.answer(msg)


def finalize_order_approval(oid: int, key_val: str):
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT o.id, o.user_id, o.plan_id, o.discount_used_pct, o.status
        FROM orders o
        WHERE o.id = ?
        """,
      (oid,),
  )
  row = cur.fetchone()
  if not row:
    conn.close()
    return None

  target_uid = row["user_id"]
  plid = row["plan_id"]
  disc_used = float(row["discount_used_pct"] or 0.0)
  already_approved = row["status"] == "approved"

  cur.execute(
      "UPDATE orders SET delivered_key = ?, status = 'approved' WHERE id = ?",
      (key_val, oid),
  )
  if not already_approved:
    cur.execute(
        "UPDATE plans SET stock = CASE WHEN stock > 0 THEN stock - 1 ELSE 0"
        " END WHERE id = ?",
        (plid,),
    )
    if disc_used > 0:
      cur.execute(
          """
                UPDATE users
                SET discount_pct = MAX(0.0, ROUND(discount_pct - ?, 2))
                WHERE user_id = ?
                """,
          (disc_used, target_uid),
      )

  conn.commit()
  conn.close()
  return target_uid


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
    cur.execute("SELECT id FROM orders WHERE id = ?", (target_oid,))
  else:
    cur.execute(
        "SELECT id FROM orders WHERE status = 'pending' ORDER BY id DESC LIMIT"
        " 1"
    )
  row = cur.fetchone()
  conn.close()

  if not row:
    await message.answer("কোনো Pending অর্ডার পাওয়া যায়নি।")
    return

  oid = row["id"]
  target_uid = finalize_order_approval(oid, key_val)
  if not target_uid:
    await message.answer("অর্ডার পাওয়া যায়নি।")
    return

  if admin_states.get(ADMIN_ID, {}).get("order_id") == oid:
    admin_states.pop(ADMIN_ID, None)

  try:
    await bot.send_message(
        target_uid,
        f"✅ আপনার অর্ডার #{oid} এপ্রুভ হয়েছে!\n🔑 Key / Password: {key_val}",
    )
  except Exception:
    pass

  await message.answer(
      f"✅ Order #{oid} APPROVED!\n🔑 Sent Key/Password: {key_val}"
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
  conn.close()

  await message.answer(
      f"🛠 Admin Control ({SUPPORT_HANDLE})\n"
      f"👥 Users: {u_cnt} | 📦 Products: {p_cnt}\n"
      f"⏳ Pending Orders: {o_cnt}",
      reply_markup=admin_panel_kb(),
  )


@dp.callback_query(F.data == "adm_report")
async def cb_adm_report(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return

  conn = get_conn()
  cur = conn.cursor()

  cur.execute("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(COALESCE(NULLIF(o.final_amount, 0), pl.price)), 0) AS amt
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        WHERE o.status = 'approved'
        """)
  app_ord = cur.fetchone()

  cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'pending'")
  pend_ord = cur.fetchone()["cnt"]

  cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'rejected'")
  rej_ord = cur.fetchone()["cnt"]

  conn.close()

  total_sales = float(app_ord["amt"] or 0.0)
  report_txt = (
      f"📊 সেলস রিপোর্ট\n\n"
      f"• এপ্রুভড অর্ডার: {app_ord['cnt']} টি (৳{total_sales:.0f})\n"
      f"• পেন্ডিং অর্ডার: {pend_ord} টি\n"
      f"• রিজেক্টেড অর্ডার: {rej_ord} টি"
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
  await callback.message.answer(
      "যেকোনো ইউজারের UserID লিখে পাঠান (উদাহরণ: 5882761122):"
  )
  await callback.answer()


@dp.callback_query(F.data == "adm_users")
async def cb_adm_users(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT user_id, full_name, username, discount_pct, referral_count,"
      " joined_at FROM users ORDER BY user_id DESC LIMIT 15"
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
        f"🎁 {float(r['discount_pct'] or 0):.0f}% (Refs:"
        f" {int(r['referral_count'] or 0)}) | 🕒 {r['joined_at']}"
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

  plist = "\n".join(
      [f"ProductID {r['id']}: {r['name']} [{r['category']}]" for r in prods]
  )
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

  plist = "\n".join(
      [f"{r['id']} = {r['name']} [{r['category']}]" for r in prods]
  )
  admin_states[callback.from_user.id] = {"step": "add_plan_loop"}
  await callback.message.answer(
      f"প্রোডাক্ট লিস্ট:\n{plist}\n\n"
      f"প্ল্যান যোগ করতে লিখুন:\n"
      f"ProductID | Duration | SitePrice | Offer(ঐচ্ছিক)\n"
      f"উদাহরণ:\n"
      f"2 | 7 Days | 300\n"
      f"2 | 30 Days | 700 | (1 Day Free)\n\n"
      f"বের হতে /start দিন।"
  )
  await callback.answer()


@dp.callback_query(F.data == "adm_delplan")
async def cb_adm_delplan(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  conn = get_conn()
  cur = conn.cursor()
  cur.execute("""
        SELECT pl.id, p.name, pl.duration, pl.price, pl.bonus
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """)
  rows = cur.fetchall()
  conn.close()

  if not rows:
    await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
    return

  plan_lines = "\n".join([
      f"PlanID {r['id']}: {r['name']} - {r['duration']}"
      f" (৳{float(r['price']):.0f}) {format_bonus_bracket(r['bonus'])}"
      for r in rows
  ])
  admin_states[callback.from_user.id] = {"step": "del_plan_loop"}
  await callback.message.answer(
      f"সব প্ল্যান লিস্ট:\n{plan_lines}\n\n"
      f"যে প্ল্যান রিমুভ করতে চান তার PlanID লিখে পাঠান (বের হতে /start দিন):"
  )
  await callback.answer()


@dp.callback_query(F.data == "adm_editplan")
async def cb_adm_editplan(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  conn = get_conn()
  cur = conn.cursor()
  cur.execute("""
        SELECT pl.id, p.name, pl.duration, pl.price, pl.stock
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """)
  rows = cur.fetchall()
  conn.close()

  if not rows:
    await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
    return

  plan_lines = "\n".join([
      f"PlanID {r['id']}: {r['name']} - {r['duration']} |"
      f" ৳{float(r['price']):.0f} | Stock: {r['stock']}"
      for r in rows
  ])
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
  cur.execute("""
        SELECT pl.id, p.name, pl.duration, pl.price, pl.bonus
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        ORDER BY pl.id
        """)
  rows = cur.fetchall()
  conn.close()

  if not rows:
    await callback.answer("কোনো প্ল্যান নেই।", show_alert=True)
    return

  plan_lines = "\n".join([
      f"PlanID {r['id']}: {r['name']} - {r['duration']}"
      f" (৳{float(r['price']):.0f}) {format_bonus_bracket(r['bonus'])}"
      for r in rows
  ])
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
  cur.execute("""
        SELECT o.id, o.user_id, p.name, pl.duration, pl.price, o.final_amount,
               o.discount_used_pct, o.sender_number, o.trx_id, o.proof_photo_id,
               pl.bonus, o.created_at
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        WHERE o.status = 'pending'
        ORDER BY o.id DESC LIMIT 10
        """)
  rows = cur.fetchall()
  conn.close()

  if not rows:
    await callback.message.answer("কোনো Pending অর্ডার নেই।")
    await callback.answer()
    return

  for r in rows:
    offer_txt = f"\n🎁 Offer: {r['bonus']}" if r["bonus"] else ""
    proof_val = r["trx_id"] or r["sender_number"]
    proof_line = (
        f"\n🧾 Info: {proof_val}" if proof_val else "\n📸 Proof: Screenshot"
    )
    paid_amt = float(r["final_amount"] or r["price"] or 0.0)
    disc_u = float(r["discount_used_pct"] or 0.0)
    disc_line = f"\n🎁 Discount Used: {disc_u:.0f}%" if disc_u > 0 else ""

    caption_txt = (
        f"🔑 [PASSWORD REQUEST] Order #{r['id']} | User: {r['user_id']}\n"
        f"🕒 Time: {r['created_at']}\n"
        f"📦 প্যানেল / প্রোডাক্ট: {r['name']} ({r['duration']}) -"
        f" ৳{paid_amt:.0f}{disc_line}{offer_txt}{proof_line}\n\n"
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
  cur.execute("SELECT user_id, status FROM orders WHERE id = ?", (oid,))
  row = cur.fetchone()
  if row and row["status"] != "rejected":
    uid = row["user_id"]
    cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
    conn.commit()
    try:
      await bot.send_message(
          uid,
          f"❌ আপনার অর্ডার #{oid} রিজেক্ট করা হয়েছে।",
      )
    except Exception:
      pass
  conn.close()

  try:
    await callback.message.edit_text(f"❌ Order #{oid} marked as REJECTED.")
  except Exception:
    await callback.message.answer(f"❌ Order #{oid} marked as REJECTED.")
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
          "SELECT full_name, username, discount_pct, referral_count, joined_at"
          " FROM users WHERE user_id = ?",
          (target_uid,),
      )
      urow = cur.fetchone()
      if not urow:
        conn.close()
        await message.answer("এই UserID ডেটাবেসে পাওয়া যায়নি।")
        return

      cur.execute(
          "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status ="
          " 'approved'",
          (target_uid,),
      )
      app_o = cur.fetchone()["cnt"]
      cur.execute(
          "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status ="
          " 'pending'",
          (target_uid,),
      )
      pend_o = cur.fetchone()["cnt"]
      conn.close()
      admin_states.pop(uid, None)

      await message.answer(
          f"🔎 ইউজার তথ্য:\n"
          f"• ID: {target_uid}\n"
          f"• নাম: {urow['full_name']} ({urow['username']})\n"
          f"• রেফার: {int(urow['referral_count'] or 0)} | ডিসকাউন্ট:"
          f" {float(urow['discount_pct'] or 0):.0f}%\n"
          f"• জয়েন: {urow['joined_at']}\n"
          f"• এপ্রুভড অর্ডার: {app_o} | পেন্ডিং অর্ডার: {pend_o}"
      )
      return

    elif step == "wait_approve_key":
      if not txt:
        await message.answer("দয়া করে Key / Password লিখুন:")
        return
      key_val = (
          txt.split(maxsplit=1)[1].strip()
          if txt.lower().startswith("/key ")
          else txt
      )
      oid = state["order_id"]
      target_uid = finalize_order_approval(oid, key_val)
      admin_states.pop(uid, None)

      if not target_uid:
        await message.answer("অর্ডার পাওয়া যায়নি।")
        return

      try:
        await bot.send_message(
            target_uid,
            f"✅ আপনার অর্ডার #{oid} এপ্রুভ হয়েছে!\n🔑 Key / Password: {key_val}",
        )
      except Exception:
        pass

      await message.answer(
          f"✅ Order #{oid} APPROVED!\n🔑 Sent Key/Password: {key_val}"
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
      await message.answer(
          f"✅ Broadcast পাঠানো হয়েছে {sent}/{len(all_users)} জন ইউজারকে।"
      )
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
      await message.answer(
          f"🗑 প্রোডাক্ট '{prow['name']}' (ID: {pid}) এবং এর প্ল্যানগুলো রিমুভ"
          f" হয়েছে।"
      )
      return

    elif step == "add_plan_loop":
      lines = [line.strip() for line in txt.splitlines() if line.strip()]
      if not lines:
        await message.answer(
            "ফরম্যাট ভুল! লিখুন:\n"
            "ProductID | Duration | SitePrice | Offer(ঐচ্ছিক)"
        )
        return

      conn = get_conn()
      cur = conn.cursor()

      added_items = []
      failed_items = []

      for idx, line in enumerate(lines, start=1):
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 3:
          failed_items.append(
              f"লাইন {idx}: `{line}` -> কমপক্ষে ৩টি অংশ লাগবে"
          )
          continue

        try:
          pid = int(parts[0])
          dur = parts[1]
          site_price = float(parts[2])
          bonus = parts[3] if len(parts) >= 4 else ""
          if not dur or site_price <= 0:
            raise ValueError()
        except ValueError:
          failed_items.append(
              f"লাইন {idx}: `{line}` -> ProductID এবং SitePrice সঠিক সংখ্যা হতে"
              " হবে"
          )
          continue

        cur.execute("SELECT name FROM products WHERE id = ?", (pid,))
        prow = cur.fetchone()
        if not prow:
          failed_items.append(
              f"লাইন {idx}: `{line}` -> ProductID {pid} পাওয়া যায়নি"
          )
          continue

        pname = prow["name"]
        brand_price = calc_brand_price(site_price, pname)
        cur.execute(
            "INSERT INTO plans (product_id, duration, price, stock, bonus)"
            " VALUES (?, ?, ?, 20, ?)",
            (pid, dur, brand_price, bonus),
        )
        added_items.append(
            f"• {pname} — {dur} | সাইট ৳{site_price:.0f} → প্রাইস"
            f" ৳{brand_price:.0f}{format_bonus_bracket(bonus)}"
        )

      conn.commit()
      conn.close()

      reply_parts = []
      if added_items:
        reply_parts.append(
            f"✅ মোট {len(added_items)}টি প্ল্যান যোগ হয়েছে:\n"
            + "\n".join(added_items)
        )
      if failed_items:
        reply_parts.append(
            "⚠️ যে লাইনগুলো যোগ হয়নি:\n" + "\n".join(failed_items)
        )

      reply_parts.append("\nআরও প্ল্যান পাঠান অথবা বের হতে /start দিন:")
      await message.answer("\n\n".join(reply_parts), parse_mode=None)
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
          f"🗑 Plan #{plid} ({prow['name']} - {prow['duration']} -"
          f" ৳{float(prow['price']):.0f}) রিমুভ হয়েছে।\n"
          f"আরও PlanID লিখুন অথবা বের হতে /start দিন:"
      )
      return

    elif step == "edit_plan":
      parts = [x.strip() for x in txt.split("|")]
      if len(parts) < 2:
        await message.answer("ফরম্যাট: PlanID | BrandPrice | NewStock(ঐচ্ছিক)")
        return
      try:
        plid = int(parts[0])
        new_stock = int(parts[2]) if len(parts) >= 3 and parts[2] else None
        if new_stock is not None and new_stock < 0:
          raise ValueError()
      except ValueError:
        await message.answer("সঠিক সংখ্যা লিখুন (যেমন: 3 | 120 | 25):")
        return

      conn = get_conn()
      cur = conn.cursor()
      cur.execute(
          """
                SELECT pl.id, pl.duration, pl.price, p.name
                FROM plans pl
                JOIN products p ON pl.product_id = p.id
                WHERE pl.id = ?
                """,
          (plid,),
      )
      prow = cur.fetchone()
      if not prow:
        conn.close()
        await message.answer("এই PlanID পাওয়া যায়নি।")
        return

      try:
        raw_p = float(parts[1])
        if raw_p <= 0:
          raise ValueError()
      except ValueError:
        conn.close()
        await message.answer("সঠিক দাম লিখুন।")
        return

      new_price = (
          round_to_0_or_5(raw_p)
          if is_dolphin_product(prow["name"])
          else round_to_0_or_5(raw_p)
      )

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
      await message.answer(
          f"✅ Plan #{plid} ({prow['duration']}) আপডেট হয়েছে:"
          f" ৳{new_price:.0f}{stock_txt}"
      )
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
    _, _, lang, _, _ = get_user_info(uid)
    step = ustate.get("step")

    if step == "wait_proof":
      has_photo = bool(message.photo)
      valid_txt, cleaned_proof = is_valid_trx_or_proof_text(txt)

      if not has_photo and not valid_txt:
        oid = ustate["order_id"]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        user_states.pop(uid, None)
        await message.answer(
            f"❌ অটো-রিজেক্ট! অর্ডার #{oid} বাতিল করা হয়েছে।\n"
            f"সঠিক TrxID, ১১ ডিজিটের মোবাইল নম্বর অথবা স্ক্রিনশট দিন।"
            if lang == "bn"
            else f"❌ Auto-Rejected! Order #{oid} was cancelled.\n"
            f"Send a valid TrxID, 11-digit mobile number, or screenshot."
        )
        return

      if valid_txt and is_duplicate_proof(cleaned_proof):
        oid = ustate["order_id"]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        user_states.pop(uid, None)
        await message.answer(
            f"❌ ডুপ্লিকেট প্রুফ! অর্ডার #{oid} অটো-রিজেক্ট করা হয়েছে।"
            if lang == "bn"
            else f"❌ Duplicate proof! Order #{oid} was auto-rejected."
        )
        return

      oid = ustate["order_id"]
      pname = ustate["pname"]
      duration = ustate["duration"]
      final_price = float(ustate.get("final_price", ustate.get("price", 0.0)))
      disc_pct = float(ustate.get("discount_pct", 0.0))
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
          else f"✅ Order #{oid} submitted!\nAdmin will check and send your"
          f" Key / Password."
      )

      full_name, username, _, cur_disc, ref_cnt = get_user_info(uid)
      offer_line = f"\n🎁 Offer: {bonus}" if bonus else ""
      disc_line = (
          f"\n🎁 Discount Applied: {disc_pct:.0f}% (Saved Bal:"
          f" {cur_disc:.0f}%, Refs: {ref_cnt})"
          if disc_pct > 0
          else ""
      )
      info_line = f"\n🧾 Info: {proof_text}" if proof_text else ""
      photo_line = "\n📸 Proof: Screenshot attached" if photo_id else ""

      admin_alert = (
          f"🔑 [PASSWORD REQUEST] Order #{oid}\n"
          f"🕒 Time: {created}\n"
          f"👤 User: {full_name} ({username}) | ID: {uid}\n"
          f"📦 প্যানেল / প্রোডাক্ট: {pname} ({duration}) -"
          f" ৳{final_price:.0f}{disc_line}{offer_line}{info_line}{photo_line}\n\n"
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
