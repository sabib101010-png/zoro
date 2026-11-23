import asyncio
from datetime import datetime
import html
import io
import json
import logging
import os
import re
import sqlite3
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("zoro404_bot")

BOT_TOKEN = os.getenv(
    "BOT_TOKEN", "9211572979:AAEI73Lq3e1FbtcmiYpQSmYlYjzMMh3QKvg"
)
ADMIN_ID = int(os.getenv("ADMIN_ID", "8524854849"))
SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "@ZORO_BROTHER")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "01778878676")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/zoro404ofc")
DB_PATH = os.getenv("DB_PATH", "store_v9.db")
PORT = int(os.getenv("PORT", "8080"))

# Dolphin Reseller API Config
DOLPHIN_BASE_URL = os.getenv(
    "DOLPHIN_BASE_URL", "https://dolphinbot.catchmeifyoucan.org"
).rstrip("/")
DOLPHIN_RESELLER_KEY = os.getenv(
    "DOLPHIN_RESELLER_KEY", "dres_c7c78682ab970b56ee9821f4a991495979765395"
)
DOLPHIN_USER_AGENT = os.getenv("DOLPHIN_USER_AGENT", "paymentdolphin0234432")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

DEFAULT_BKASH = "01862849299"
DEFAULT_NAGAD = "01778879676"

DEFAULT_PLANS = []

CATEGORIES = [
    ("ALL", "🌐 ALL"),
    ("ROOT", "🛡 ROOT"),
    ("NON_ROOT", "🔓 NON ROOT"),
    ("IOS", "📱 IOS"),
    ("PC_LAPTOP", "💻 PC / LAPTOP"),
]

REMOVED_PRODUCTS = [
    "Br Mod Apk Mod",
    "ANGRY MOOD",
    "DELTA MODZ",
    "ANGRY MOD - ROOT",
    "DELTA MOD - ROOT",
    "ZYTRON PRO - ROOT",
    "DRIP WIRE EXTERNAL",
    "BR MOD NON ROOT",
]


def canon_name(name: str) -> str:
  s = re.sub(r"\s+", " ", (name or "").strip()).upper()
  return s


def canon_duration(dur: str) -> str:
  s = re.sub(r"\s+", " ", (dur or "").strip())
  m = re.fullmatch(r"(\d+)\s*(hours?|hrs?|ঘণ্টা|ঘন্টা|h)", s, flags=re.I)
  if m:
    n = int(m.group(1))
    return f"{n} HOUR" if n == 1 else f"{n} HOURS"
  m = re.fullmatch(r"(\d+)\s*(days?|দিন|d)", s, flags=re.I)
  if m:
    n = int(m.group(1))
    return f"{n} DAY" if n == 1 else f"{n} DAYS"
  return s.upper()


def format_unit_duration(num_val: int, unit_type: str) -> str:
  n = max(1, int(num_val))
  if unit_type == "HOURS":
    return f"{n} HOUR" if n == 1 else f"{n} HOURS"
  return f"{n} DAY" if n == 1 else f"{n} DAYS"


def parse_multi_int_values(raw_text: str) -> list[int]:
  items = re.findall(r"\d+", raw_text or "")
  result: list[int] = []
  for tok in items:
    val = int(tok)
    if val > 0:
      result.append(val)
  return result


def parse_multi_price_values(raw_text: str) -> list[float]:
  items = re.findall(r"\d+(?:\.\d+)?", raw_text or "")
  result: list[float] = []
  for tok in items:
    try:
      val = float(tok)
      if val > 0:
        result.append(val)
    except ValueError:
      pass
  return result


def parse_clean_price(raw_val: str) -> float:
  s = re.sub(r"[^\d.]", "", (raw_val or "").strip())
  if not s:
    return 0.0
  try:
    return float(s)
  except ValueError:
    return 0.0


def round_to_zero(amount: float) -> float:
  if amount <= 0:
    return 0.0
  snapped = round(float(amount) / 10.0) * 10.0
  return float(max(10.0, snapped))


def round_to_0_or_5(amount: float) -> float:
  if amount <= 0:
    return 0.0
  snapped = round(float(amount) / 5.0) * 5.0
  return float(max(5.0, snapped))


def is_dolphin_product(pname: str) -> bool:
  return "dolphin" in (pname or "").strip().lower()


def is_angry_product(pname: str) -> bool:
  return "angry" in (pname or "").strip().lower()


def parse_days_count(duration: str) -> int:
  s = (duration or "").strip().lower()
  if "hour" in s or "hr" in s:
    return 0
  m = re.search(r"(\d+)\s*day", s)
  if not m:
    return 0
  return int(m.group(1))


def calc_brand_price(
    site_price: float, pname: str = "", duration: str = ""
) -> float:
  sp = float(site_price)
  if sp <= 0:
    return 0.0

  if is_dolphin_product(pname):
    return round_to_0_or_5(sp)

  days = parse_days_count(duration)
  if days == 0:
    cut = 0.0 if sp <= 25 else 10.0
  elif days <= 1:
    if abs(sp - 60.0) < 1e-6:
      cut = 10.0
    elif sp >= 100:
      cut = 20.0
    else:
      cut = 10.0
  elif days <= 3:
    cut = 20.0
  elif days <= 10:
    cut = 30.0 if sp >= 250 else 20.0
  elif days <= 15:
    cut = 40.0 if sp >= 300 else 30.0
  else:
    cut = 60.0 if sp >= 500 else 40.0

  if is_angry_product(pname):
    if days <= 1:
      cut += 10.0
    elif days <= 7:
      cut = max(cut, 60.0)
    elif days <= 15:
      cut = 20.0
    else:
      cut = 60.0

  price = round_to_zero(max(10.0, sp - cut))
  return price


def get_vip_discount_pct(total_spent: float) -> float:
  spent = float(total_spent or 0.0)
  if spent >= 5000.0:
    return 30.0
  if spent >= 2000.0:
    return 20.0
  return 0.0


def calc_vip_price_details(
    pname: str, base_price: float, total_spent: float
) -> tuple[float, float, float]:
  price = round_to_zero(float(base_price))
  if price <= 0 or is_dolphin_product(pname):
    return 0.0, 0.0, price

  pct = get_vip_discount_pct(total_spent)
  if pct <= 0:
    return 0.0, 0.0, price

  raw_after = price * (1.0 - (pct / 100.0))
  final_price = round_to_zero(raw_after)
  if final_price >= price:
    return 0.0, 0.0, price

  disc_amt = round(price - final_price, 2)
  return pct, disc_amt, final_price


def calc_discount_details(
    pname: str,
    duration: str,
    base_price: float,
    user_disc_pct: float = 0.0,
    total_spent: float = 0.0,
) -> tuple[float, float, float]:
  return calc_vip_price_details(pname, base_price, total_spent)


RAW_CATALOG = [
    (
        "DOLPHIN PLUSH - ROOT",
        "ROOT",
        [
            ("7 DAYS", 500.0, 15, "", True),
            ("15 DAYS", 900.0, 10, "", True),
            ("30 DAYS", 1500.0, 10, "", True),
        ],
    ),
    (
        "DELTA MODS - ROOT",
        "ROOT",
        [
            ("1 DAY", 50.0, 25, "", False),
            ("7 DAYS", 300.0, 20, "", False),
            ("15 DAYS", 480.0, 15, "", False),
            ("30 DAYS", 700.0, 10, "", False),
        ],
    ),
    (
        "BR MODS - ROOT",
        "ROOT",
        [
            ("1 DAY", 40.0, 25, "", False),
            ("10 DAYS", 380.0, 15, "", False),
            ("30 DAYS", 680.0, 10, "", False),
        ],
    ),
    (
        "TITAN MODS - ROOT",
        "ROOT",
        [
            ("1 DAY", 40.0, 25, "", False),
            ("7 DAYS", 260.0, 20, "", False),
            ("15 DAYS", 450.0, 15, "", False),
            ("30 DAYS", 700.0, 10, "", False),
        ],
    ),
    (
        "DRIP WIRE - NON ROOT",
        "NON_ROOT",
        [
            ("3 HOURS", 20.0, 30, "", False),
            ("6 HOURS", 30.0, 30, "", False),
            ("12 HOURS", 60.0, 25, "", False),
            ("1 DAY", 80.0, 20, "", False),
            ("7 DAYS", 350.0, 15, "", False),
            ("30 DAYS", 700.0, 10, "", False),
        ],
    ),
    (
        "ANGRY MODS - ROOT",
        "ROOT",
        [
            ("1 DAY", 50.0, 20, "", False),
            ("7 DAYS", 200.0, 20, "", False),
            ("15 DAYS", 480.0, 15, "", False),
            ("30 DAYS", 740.0, 10, "", False),
        ],
    ),
    (
        "DRIP APKMOD - NON ROOT",
        "NON_ROOT",
        [
            ("1 DAY", 50.0, 25, "", False),
            ("3 DAYS", 80.0, 20, "", False),
            ("7 DAYS", 170.0, 20, "", False),
            ("15 DAYS", 290.0, 15, "", False),
            ("30 DAYS", 500.0, 10, "", False),
        ],
    ),
    (
        "BR MOD PC",
        "PC_LAPTOP",
        [
            ("1 DAY", 80.0, 20, "", False),
            ("10 DAYS", 290.0, 15, "", False),
            ("30 DAYS", 480.0, 10, "", False),
        ],
    ),
]

CATALOG_PRODUCTS = [
    (
        pname,
        cat_key,
        [
            (
                canon_duration(dur),
                round_to_0_or_5(pr) if fixed_off else round_to_zero(pr),
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
  db_dir = os.path.dirname(os.path.abspath(DB_PATH))
  if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)
  conn = sqlite3.connect(DB_PATH, timeout=30.0)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA journal_mode=WAL;")
  conn.execute("PRAGMA synchronous=NORMAL;")
  return conn


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def update_channel_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(inline_keyboard=[[
      InlineKeyboardButton(text="JOIN UPDATE CHANNEL 🗣️", url=CHANNEL_URL),
  ]])


async def safe_delete_message(chat_id: int, message_id: int | None):
  if not message_id:
    return
  try:
    await bot.delete_message(chat_id=chat_id, message_id=message_id)
  except Exception:
    pass


async def safe_delete_messages(chat_id: int, message_ids: list[int | None]):
  for mid in message_ids:
    await safe_delete_message(chat_id, mid)


def detect_payment_method_label(
    sender_number: str = "", trx_id: str = "", proof_photo_id: str = ""
) -> str:
  num = normalize_bd_mobile(sender_number or "") or (sender_number or "").strip()
  trx = (trx_id or "").strip().upper()
  has_photo = bool((proof_photo_id or "").strip())

  if trx:
    if trx.startswith("BK") or "BKASH" in trx:
      return f"বিকাশ (TrxID: {trx})"
    if trx.startswith("NG") or "NAGAD" in trx:
      return f"নগদ (TrxID: {trx})"
    return f"TrxID ({trx})"

  if num:
    if re.fullmatch(r"01[3-9]\d{8}", num):
      prefix3 = num[:3]
      if prefix3 in ("017", "013"):
        return f"বিকাশ / নগদ নম্বর ({num})"
      if prefix3 in ("018", "019", "016", "014", "015"):
        return f"মোবাইল নম্বর ({num})"
    return f"মোবাইল নম্বর ({num})"

  if has_photo:
    return "স্ক্রিনশট (বিকাশ / নগদ)"
  return "উল্লেখ নেই"


# ==========================================
# HIGH-RELIABILITY BACKUP & RESTORE ENGINE
# ==========================================
def export_full_backup_payload() -> dict:
  conn = get_conn()
  try:
    cur = conn.cursor()

    cur.execute("SELECT * FROM users ORDER BY user_id")
    users = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM products ORDER BY id")
    products = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM plans ORDER BY id")
    plans = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM orders ORDER BY id")
    orders = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM payment_settings WHERE id = 1")
    pay_row = cur.fetchone()
    payment_settings = [dict(pay_row)] if pay_row else []

    cur.execute("SELECT * FROM key_ownership ORDER BY id")
    key_ownership = [dict(r) for r in cur.fetchall()]

    return {
        "version": "zoro404_backup_v3_pro",
        "exported_at": now_str(),
        "counts": {
            "users": len(users),
            "products": len(products),
            "plans": len(plans),
            "orders": len(orders),
            "key_ownership": len(key_ownership),
        },
        "tables": {
            "users": users,
            "products": products,
            "plans": plans,
            "orders": orders,
            "payment_settings": payment_settings,
            "key_ownership": key_ownership,
        },
    }
  finally:
    conn.close()


def import_full_backup_payload(payload: dict) -> dict[str, int]:
  if not isinstance(payload, dict) or not isinstance(
      payload.get("tables"), dict
  ):
    raise ValueError("Invalid backup format")

  tables = payload["tables"]
  conn = get_conn()
  cur = conn.cursor()

  restored = {
      "users": 0,
      "products": 0,
      "plans": 0,
      "orders": 0,
      "key_ownership": 0,
  }

  try:
    cur.execute("BEGIN IMMEDIATE")

    prod_id_map: dict[int, int] = {}
    for p in tables.get("products", []):
      pname = (p.get("name") or "").strip()
      if not pname:
        continue
      cat = (p.get("category") or "ALL").strip().upper()
      old_pid = p.get("id")
      if old_pid is not None:
        cur.execute(
            """
                    INSERT INTO products (id, name, category)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        category = excluded.category
                    """,
            (int(old_pid), pname, cat),
        )
        prod_id_map[int(old_pid)] = int(old_pid)
      else:
        cur.execute(
            "INSERT INTO products (name, category) VALUES (?, ?)",
            (pname, cat),
        )
      restored["products"] += 1

    plan_id_map: dict[int, int] = {}
    for pl in tables.get("plans", []):
      raw_pid = pl.get("product_id")
      dur = canon_duration(pl.get("duration") or "")
      if raw_pid is None or not dur:
        continue
      mapped_pid = prod_id_map.get(int(raw_pid), int(raw_pid))
      cur.execute("SELECT id FROM products WHERE id = ?", (mapped_pid,))
      if not cur.fetchone():
        continue

      price = float(pl.get("price") or 0.0)
      stock = int(pl.get("stock") or 0)
      bonus = pl.get("bonus") or ""
      old_plid = pl.get("id")

      if old_plid is not None:
        cur.execute(
            """
                    INSERT INTO plans (id, product_id, duration, price, stock, bonus)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        product_id = excluded.product_id,
                        duration = excluded.duration,
                        price = excluded.price,
                        stock = excluded.stock,
                        bonus = excluded.bonus
                    """,
            (int(old_plid), mapped_pid, dur, price, stock, bonus),
        )
        plan_id_map[int(old_plid)] = int(old_plid)
      else:
        cur.execute(
            """
                    INSERT INTO plans (product_id, duration, price, stock, bonus)
                    VALUES (?, ?, ?, ?, ?)
                    """,
            (mapped_pid, dur, price, stock, bonus),
        )
        plan_id_map[int(cur.lastrowid)] = int(cur.lastrowid)
      restored["plans"] += 1

    for u in tables.get("users", []):
      if u.get("user_id") is None:
        continue
      uid = int(u["user_id"])
      cur.execute(
          """
                INSERT INTO users (
                    user_id, full_name, username, lang, balance,
                    total_spent, discount_pct, referral_count, referred_by, joined_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = COALESCE(NULLIF(excluded.full_name, ''), users.full_name),
                    username = COALESCE(NULLIF(excluded.username, ''), users.username),
                    lang = COALESCE(NULLIF(excluded.lang, ''), users.lang),
                    balance = MAX(users.balance, excluded.balance),
                    total_spent = MAX(users.total_spent, excluded.total_spent),
                    discount_pct = MAX(users.discount_pct, excluded.discount_pct),
                    referral_count = MAX(users.referral_count, excluded.referral_count),
                    referred_by = CASE
                        WHEN users.referred_by = 0 THEN excluded.referred_by
                        ELSE users.referred_by
                    END,
                    joined_at = COALESCE(NULLIF(users.joined_at, ''), excluded.joined_at)
                """,
          (
              uid,
              u.get("full_name") or "User",
              u.get("username") or "N/A",
              u.get("lang") or "bn",
              float(u.get("balance") or 0.0),
              float(u.get("total_spent") or 0.0),
              float(u.get("discount_pct") or 0.0),
              int(u.get("referral_count") or 0),
              int(u.get("referred_by") or 0),
              u.get("joined_at") or now_str(),
          ),
      )
      restored["users"] += 1

    for o in tables.get("orders", []):
      if o.get("user_id") is None or o.get("plan_id") is None:
        continue
      mapped_plid = plan_id_map.get(int(o["plan_id"]), int(o["plan_id"]))
      cur.execute("SELECT id FROM plans WHERE id = ?", (mapped_plid,))
      if not cur.fetchone():
        continue

      old_oid = o.get("id")
      if old_oid is not None:
        cur.execute(
            """
                    INSERT INTO orders (
                        id, user_id, plan_id, sender_number, trx_id, proof_photo_id,
                        delivered_key, discount_used_pct, final_amount, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        sender_number = COALESCE(NULLIF(excluded.sender_number, ''), orders.sender_number),
                        trx_id = COALESCE(NULLIF(excluded.trx_id, ''), orders.trx_id),
                        proof_photo_id = COALESCE(NULLIF(excluded.proof_photo_id, ''), orders.proof_photo_id),
                        delivered_key = COALESCE(NULLIF(excluded.delivered_key, ''), orders.delivered_key),
                        discount_used_pct = excluded.discount_used_pct,
                        final_amount = CASE
                            WHEN excluded.final_amount > 0 THEN excluded.final_amount
                            ELSE orders.final_amount
                        END,
                        status = CASE
                            WHEN orders.status = 'approved' THEN 'approved'
                            ELSE excluded.status
                        END
                    """,
            (
                int(old_oid),
                int(o["user_id"]),
                mapped_plid,
                o.get("sender_number") or "",
                o.get("trx_id") or "",
                o.get("proof_photo_id") or "",
                o.get("delivered_key") or "",
                float(o.get("discount_used_pct") or 0.0),
                float(o.get("final_amount") or 0.0),
                o.get("status") or "pending_payment",
                o.get("created_at") or now_str(),
            ),
        )
      else:
        cur.execute(
            """
                    INSERT INTO orders (
                        user_id, plan_id, sender_number, trx_id, proof_photo_id,
                        delivered_key, discount_used_pct, final_amount, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
            (
                int(o["user_id"]),
                mapped_plid,
                o.get("sender_number") or "",
                o.get("trx_id") or "",
                o.get("proof_photo_id") or "",
                o.get("delivered_key") or "",
                float(o.get("discount_used_pct") or 0.0),
                float(o.get("final_amount") or 0.0),
                o.get("status") or "pending_payment",
                o.get("created_at") or now_str(),
            ),
        )
      restored["orders"] += 1

    for ps in tables.get("payment_settings", []):
      bk = (ps.get("bkash") or DEFAULT_BKASH).strip()
      ng = (ps.get("nagad") or DEFAULT_NAGAD).strip()
      cur.execute(
          """
                INSERT INTO payment_settings (id, bkash, nagad)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    bkash = excluded.bkash,
                    nagad = excluded.nagad
                """,
          (bk, ng),
      )

    for ko in tables.get("key_ownership", []):
      kval = (ko.get("key_value") or "").strip()
      if not kval:
        continue
      cur.execute(
          """
                INSERT INTO key_ownership (key_value, owner_user_id, product_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key_value) DO UPDATE SET
                    owner_user_id = CASE
                        WHEN key_ownership.owner_user_id = 0 THEN excluded.owner_user_id
                        ELSE key_ownership.owner_user_id
                    END,
                    product_name = excluded.product_name
                """,
          (
              kval,
              int(ko.get("owner_user_id") or 0),
              ko.get("product_name") or "DOLPHIN",
              ko.get("created_at") or now_str(),
          ),
      )
      restored["key_ownership"] += 1

    cur.execute("""
            UPDATE users
            SET total_spent = MAX(
                COALESCE(total_spent, 0.0),
                COALESCE((
                    SELECT SUM(COALESCE(NULLIF(o.final_amount, 0), pl.price))
                    FROM orders o
                    JOIN plans pl ON o.plan_id = pl.id
                    WHERE o.user_id = users.user_id AND o.status = 'approved'
                ), 0.0)
            )
            """)

    conn.commit()
    try:
      conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
      pass
    return restored
  except Exception:
    try:
      conn.rollback()
    except Exception:
      pass
    raise
  finally:
    conn.close()


async def send_backup_file_to_admin(
    chat_id: int, title_prefix: str = "DATABASE BACKUP READY!"
):
  payload = export_full_backup_payload()
  raw_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode(
      "utf-8"
  )
  stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  filename = f"zoro404_backup_{stamp}.json"
  counts = payload["counts"]

  caption = (
      f"💾 <b>{html.escape(title_prefix)}</b>\n"
      f"🕒 TIME: <code>{html.escape(payload['exported_at'])}</code>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"• 👥 <b>USERS:</b> <b>{counts['users']}</b>\n"
      f"• 📦 <b>PRODUCTS:</b> <b>{counts['products']}</b>\n"
      f"• ⏱ <b>PLANS:</b> <b>{counts['plans']}</b>\n"
      f"• 🧾 <b>ORDERS:</b> <b>{counts['orders']}</b>\n"
      f"• 🔐 <b>KEY LOCKS:</b> <b>{counts['key_ownership']}</b>\n\n"
      f"<b>রিস্টোর করতে /restore বা Restore DB দিয়ে এই ফাইলটি পাঠান।</b>"
  )
  doc = BufferedInputFile(raw_bytes, filename=filename)
  await bot.send_document(
      chat_id=chat_id,
      document=doc,
      caption=caption,
      parse_mode="HTML",
  )


# ==========================================
# DOLPHIN OWNERSHIP LOCK & API CLIENT
# ==========================================
def clean_reset_key_value(raw_text: str) -> str:
  cleaned = (raw_text or "").strip()
  if not cleaned:
    return ""
  m = re.search(
      r"(?:PASS|PASSWORD|PW)\s*[:=\-]?\s*(.+)$",
      cleaned,
      flags=re.I,
  )
  if m:
    val = m.group(1).strip()
    if val:
      return val
  val_after_prefix = re.sub(
      r"^(?:USER|PASS|PASSWORD|PW|KEY)\s*[:=\-]?\s*",
      "",
      cleaned,
      flags=re.I,
  ).strip()
  return val_after_prefix or cleaned


def extract_key_tokens(raw_text: str) -> list[str]:
  cleaned = (raw_text or "").strip()
  if not cleaned:
    return []

  tokens = [cleaned]
  m = re.search(
      r"USER\s*[:=\-]?\s*(.+?)\s+(?:PASS|PASSWORD|PW)\s*[:=\-]?\s*(.+)$",
      cleaned,
      flags=re.I,
  )
  if m:
    u_val = m.group(1).strip()
    p_val = m.group(2).strip()
    if u_val:
      tokens.append(u_val)
    if p_val:
      tokens.append(p_val)

  val_after_prefix = re.sub(
      r"^(?:USER|PASS|PASSWORD|PW|KEY)\s*[:=\-]?\s*",
      "",
      cleaned,
      flags=re.I,
  ).strip()
  if val_after_prefix and val_after_prefix not in tokens:
    tokens.append(val_after_prefix)

  return tokens


def assign_key_ownership(
    raw_key_text: str, owner_user_id: int, product_name: str = "DOLPHIN"
):
  tokens = extract_key_tokens(raw_key_text)
  if not tokens or not owner_user_id:
    return

  conn = get_conn()
  cur = conn.cursor()
  ts = now_str()
  for tok in tokens:
    cur.execute(
        """
            INSERT INTO key_ownership (key_value, owner_user_id, product_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key_value) DO UPDATE SET
                owner_user_id = CASE
                    WHEN key_ownership.owner_user_id = 0 THEN excluded.owner_user_id
                    ELSE key_ownership.owner_user_id
                END,
                product_name = excluded.product_name
            """,
        (tok, int(owner_user_id), product_name, ts),
    )
  conn.commit()
  conn.close()


def verify_key_ownership(
    submitted_key: str, requester_user_id: int, lang: str = "bn"
) -> tuple[bool, str]:
  clean_k = clean_reset_key_value(submitted_key)
  if not clean_k:
    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )

  if int(requester_user_id) == ADMIN_ID:
    return True, "OK"

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT owner_user_id FROM key_ownership
        WHERE key_value = ? OR LOWER(key_value) = LOWER(?)
        ORDER BY id DESC LIMIT 1
        """,
      (clean_k, clean_k),
  )
  row = cur.fetchone()
  conn.close()

  if not row:
    return True, "OK"

  owner_id = int(row["owner_user_id"] or 0)
  if owner_id != 0 and owner_id != int(requester_user_id):
    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )

  return True, "OK"


def get_dolphin_headers() -> dict[str, str]:
  return {
      "User-Agent": DOLPHIN_USER_AGENT,
      "X-Reseller-Key": DOLPHIN_RESELLER_KEY,
      "Authorization": f"Bearer {DOLPHIN_RESELLER_KEY}",
      "Content-Type": "application/json",
      "Accept": "application/json",
  }


def _is_reset_success_response(status: int, data: dict | list | str) -> bool:
  if not (200 <= status < 300):
    return False
  if isinstance(data, dict):
    for k in ("success", "ok", "status"):
      if k in data:
        val = data[k]
        if isinstance(val, bool):
          return val
        if isinstance(val, str):
          low = val.strip().lower()
          if low in ("false", "error", "failed", "fail", "invalid", "not_found"):
            return False
          if low in ("true", "ok", "success", "reset"):
            return True
    err_msg = str(data.get("error") or data.get("message") or "").lower()
    if any(
        w in err_msg
        for w in (
            "invalid",
            "not found",
            "wrong",
            "incorrect",
            "fail",
            "error",
            "expired",
        )
    ):
      return False
    return True
  if isinstance(data, str):
    low = data.strip().lower()
    if any(
        w in low
        for w in ("invalid", "not found", "wrong", "incorrect", "fail", "error")
    ):
      return False
    return bool(low)
  return True


async def dolphin_reset_hwid_api(
    key_val: str, lang: str = "bn"
) -> tuple[bool, str]:
  clean_key = clean_reset_key_value(key_val)
  if not clean_key:
    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )

  endpoints = [
      f"{DOLPHIN_BASE_URL}/api/v1/reseller/reset-hwid",
      f"{DOLPHIN_BASE_URL}/api/reseller/reset-hwid",
      f"{DOLPHIN_BASE_URL}/api/v1/reset-hwid",
  ]
  payload = {"key": clean_key, "password": clean_key}
  timeout = aiohttp.ClientTimeout(total=12)

  try:
    async with aiohttp.ClientSession(timeout=timeout) as session:
      for url in endpoints:
        try:
          async with session.post(
              url, headers=get_dolphin_headers(), json=payload
          ) as resp:
            if resp.status == 404:
              continue
            raw_txt = await resp.text()
            try:
              parsed: dict | list | str = await resp.json()
            except Exception:
              parsed = raw_txt

            if _is_reset_success_response(resp.status, parsed):
              return (
                  True,
                  "✅ পাসওয়ার্ড রিসেট সফল হয়েছে।"
                  if lang == "bn"
                  else "✅ Password reset successful.",
              )
            return (
                False,
                "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
                if lang == "bn"
                else "❌ Password is incorrect or not found. Try again with a valid password.",
            )
        except aiohttp.ClientError:
          continue

    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )

  except asyncio.TimeoutError:
    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )
  except Exception as exc:
    logger.warning("Dolphin reset API error: %s", exc)
    return (
        False,
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else "❌ Password is incorrect or not found. Try again with a valid password.",
    )


async def dolphin_claim_key_api(
    key_val: str, customer_chat_id: int
) -> tuple[bool, str]:
  clean_key = clean_reset_key_value(key_val)
  url = f"{DOLPHIN_BASE_URL}/api/v1/reseller/claim-key"
  payload = {
      "key": clean_key,
      "customer_chat_id": int(customer_chat_id),
  }
  timeout = aiohttp.ClientTimeout(total=12)

  try:
    async with aiohttp.ClientSession(timeout=timeout) as session:
      async with session.post(
          url, headers=get_dolphin_headers(), json=payload
      ) as resp:
        try:
          data = await resp.json()
        except Exception:
          data = {}

        if 200 <= resp.status < 300:
          msg = (
              data.get("message") or "কি সফলভাবে ক্লেইম করা হয়েছে।"
              if isinstance(data, dict)
              else "কি সফলভাবে ক্লেইম করা হয়েছে।"
          )
          return True, str(msg)

        return False, "পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি।"
  except Exception as exc:
    logger.warning("Dolphin claim API error: %s", exc)
    return False, "পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি।"


def build_approved_order_message(
    oid: int, pname: str, duration: str, key_val: str, lang: str = "bn"
) -> str:
  raw = (key_val or "").strip()
  safe_prod = html.escape((pname or "PANEL").upper())
  safe_dur = html.escape((duration or "").upper())
  dur_part = f" ({safe_dur})" if safe_dur else ""

  m = re.search(
      r"USER\s*[:=\-]?\s*(.+?)\s+(?:PASS|PASSWORD|PW)\s*[:=\-]?\s*(.+)$",
      raw,
      flags=re.I,
  )
  if m:
    user_only = html.escape(m.group(1).strip())
    pass_only = html.escape(m.group(2).strip())
    if lang == "en":
      cred_section = (
          f"👤 <b>USERNAME:</b>\n<code>{user_only}</code>\n\n"
          f"🔐 <b>PASSWORD:</b>\n<code>{pass_only}</code>"
      )
    else:
      cred_section = (
          f"👤 <b>ইউজারনেম:</b>\n<code>{user_only}</code>\n\n"
          f"🔐 <b>পাসওয়ার্ড:</b>\n<code>{pass_only}</code>"
      )
  else:
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 2:
      u_clean = html.escape(
          re.sub(r"^USER\s*[:=\-]?\s*", "", lines[0], flags=re.I).strip()
      )
      p_clean = html.escape(
          re.sub(
              r"^(?:PASS|PASSWORD|PW)\s*[:=\-]?\s*", "", lines[1], flags=re.I
          ).strip()
      )
      if lang == "en":
        cred_section = (
            f"👤 <b>USERNAME:</b>\n<code>{u_clean}</code>\n\n"
            f"🔐 <b>PASSWORD:</b>\n<code>{p_clean}</code>"
        )
      else:
        cred_section = (
            f"👤 <b>ইউজারনেম:</b>\n<code>{u_clean}</code>\n\n"
            f"🔐 <b>পাসওয়ার্ড:</b>\n<code>{p_clean}</code>"
        )
    else:
      single_clean = html.escape(
          re.sub(
              r"^(?:USER|PASS|PASSWORD|PW|KEY)\s*[:=\-]?\s*",
              "",
              raw,
              flags=re.I,
          ).strip()
          or raw
      )
      if lang == "en":
        cred_section = f"🔑 <b>KEY / PASSWORD:</b>\n<code>{single_clean}</code>"
      else:
        cred_section = f"🔑 <b>কি / পাসওয়ার্ড:</b>\n<code>{single_clean}</code>"

  if lang == "en":
    return (
        f"✅ <b>Order #{oid} Approved!</b>\n"
        f"📦 <b>Panel:</b> <b>{safe_prod}{dur_part}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"{cred_section}\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👉 <i>Tap only the value box to copy.</i>"
    )

  return (
      f"✅ <b>অর্ডার #{oid} এপ্রুভ হয়েছে!</b>\n"
      f"📦 <b>প্যানেল:</b> <b>{safe_prod}{dur_part}</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"{cred_section}\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"👉 <i>শুধু লেখার বক্সে চাপ দিন, ইউজার বা পাসওয়ার্ড কপি হয়ে যাবে।</i>"
  )


def normalize_bd_mobile(text: str) -> str | None:
  cleaned = re.sub(r"[\s\-\+]", "", text or "")
  if cleaned.startswith("880"):
    cleaned = "0" + cleaned[3:]
  if re.fullmatch(r"01[3-9]\d{8}", cleaned):
    return cleaned
  return None


def is_valid_bd_mobile(text: str) -> bool:
  return normalize_bd_mobile(text) is not None


def is_valid_trx_or_proof_text(text: str) -> tuple[bool, str, bool]:
  raw = (text or "").strip()
  if not raw:
    return False, "", False

  mob = normalize_bd_mobile(raw)
  if mob:
    return True, mob, True

  trx = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
  if len(trx) < 8 or len(trx) > 16:
    return False, trx, False

  has_digit = any(ch.isdigit() for ch in trx)
  has_alpha = any(ch.isalpha() for ch in trx)
  if not (has_digit and has_alpha):
    return False, trx, False

  if re.search(r"(.)\1{3,}", trx):
    return False, trx, False

  if re.fullmatch(r"([A-Z0-9]{2,3})\1{1,5}", trx):
    return False, trx, False

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
    return False, trx, False

  return True, trx, False


def is_duplicate_proof(proof_val: str, is_mobile: bool = False) -> bool:
  if is_mobile:
    return False

  val = (proof_val or "").strip().upper()
  if not val:
    return False

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT COUNT(*) AS cnt FROM orders
        WHERE UPPER(TRIM(trx_id)) = ? AND status IN ('pending_payment', 'pending', 'approved')
        """,
      (val,),
  )
  o_cnt = cur.fetchone()["cnt"]
  conn.close()
  return o_cnt > 0


def sync_catalog_prices(cur: sqlite3.Cursor):
  removed_canon = {canon_name(x) for x in REMOVED_PRODUCTS}
  catalog_map = {
      canon_name(pname): (pname, cat_key, plist)
      for pname, cat_key, plist in CATALOG_PRODUCTS
  }

  cur.execute("SELECT id, name, category FROM products ORDER BY id")
  all_prods = cur.fetchall()

  kept_by_canon = {}
  for prow in all_prods:
    pid = prow["id"]
    cname = canon_name(prow["name"])
    if cname in removed_canon:
      cur.execute("DELETE FROM plans WHERE product_id = ?", (pid,))
      cur.execute("DELETE FROM products WHERE id = ?", (pid,))
      continue

    if cname in catalog_map:
      target_pname, target_cat, _ = catalog_map[cname]
      if cname not in kept_by_canon:
        kept_by_canon[cname] = pid
        if prow["name"] != target_pname or prow["category"] != target_cat:
          cur.execute(
              "UPDATE products SET name = ?, category = ? WHERE id = ?",
              (target_pname, target_cat, pid),
          )
      else:
        primary_pid = kept_by_canon[cname]
        cur.execute(
            "UPDATE orders SET plan_id = (SELECT id FROM plans WHERE product_id"
            " = ? LIMIT 1) WHERE plan_id IN (SELECT id FROM plans WHERE"
            " product_id = ?)",
            (primary_pid, pid),
        )
        cur.execute("DELETE FROM plans WHERE product_id = ?", (pid,))
        cur.execute("DELETE FROM products WHERE id = ?", (pid,))

  for cname, (pname, cat_key, plist) in catalog_map.items():
    if cname not in kept_by_canon:
      cur.execute(
          "INSERT INTO products (name, category) VALUES (?, ?)",
          (pname, cat_key),
      )
      pid = cur.lastrowid
      kept_by_canon[cname] = pid
    else:
      pid = kept_by_canon[cname]

    allowed_durs = [canon_duration(dur) for dur, _, _, _ in plist]
    cur.execute(
        "SELECT id, duration, bonus FROM plans WHERE product_id = ? ORDER BY id",
        (pid,),
    )
    existing_plans = cur.fetchall()

    seen_durs = set()
    for pl in existing_plans:
      cdur = canon_duration(pl["duration"])
      if cdur not in allowed_durs or cdur in seen_durs:
        cur.execute("DELETE FROM plans WHERE id = ?", (pl["id"],))
      else:
        seen_durs.add(cdur)
        if pl["duration"] != cdur:
          cur.execute(
              "UPDATE plans SET duration = ? WHERE id = ?", (cdur, pl["id"])
          )

    for dur, pr, st, bon in plist:
      cdur = canon_duration(dur)
      cur.execute(
          "SELECT id FROM plans WHERE product_id = ? AND duration = ? ORDER BY"
          " id LIMIT 1",
          (pid, cdur),
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
            (pid, cdur, pr, st, bon),
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
            total_spent REAL DEFAULT 0.0,
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
  cur.execute("""
        CREATE TABLE IF NOT EXISTS key_ownership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_value TEXT UNIQUE NOT NULL,
            owner_user_id INTEGER NOT NULL,
            product_name TEXT DEFAULT 'DOLPHIN',
            created_at TEXT DEFAULT ''
        )
        """)

  cur.execute("PRAGMA table_info(users)")
  u_cols = [c["name"] for c in cur.fetchall()]
  if "total_spent" not in u_cols:
    cur.execute("ALTER TABLE users ADD COLUMN total_spent REAL DEFAULT 0.0")
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

  cur.execute("""
        SELECT o.user_id, o.delivered_key, p.name
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        WHERE o.status = 'approved' AND TRIM(COALESCE(o.delivered_key, '')) != ''
        """)
  for old_ord in cur.fetchall():
    ts = now_str()
    for tok in extract_key_tokens(old_ord["delivered_key"]):
      cur.execute(
          """
                INSERT OR IGNORE INTO key_ownership (key_value, owner_user_id, product_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
          (tok, int(old_ord["user_id"]), old_ord["name"] or "DOLPHIN", ts),
      )

  cur.execute("""
        UPDATE users
        SET total_spent = MAX(
            COALESCE(total_spent, 0.0),
            COALESCE((
                SELECT SUM(COALESCE(NULLIF(o.final_amount, 0), pl.price))
                FROM orders o
                JOIN plans pl ON o.plan_id = pl.id
                WHERE o.user_id = users.user_id AND o.status = 'approved'
            ), 0.0)
        )
        """)

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
  _ = referrer_id
  uid = message.from_user.id
  full_name = message.from_user.full_name or "User"
  username = (
      f"@{message.from_user.username}" if message.from_user.username else "N/A"
  )
  joined = now_str()

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT lang, total_spent, discount_pct, referral_count FROM users WHERE"
      " user_id = ?",
      (uid,),
  )
  existing = cur.fetchone()
  is_new = existing is None
  ref_awarded_to = 0

  if is_new:
    cur.execute(
        """
            INSERT INTO users (
                user_id, full_name, username, lang, balance,
                total_spent, discount_pct, referral_count, referred_by, joined_at
            )
            VALUES (?, ?, ?, 'bn', 0.0, 0.0, 0.0, 0, 0, ?)
            """,
        (uid, full_name, username, joined),
    )
    lang = "bn"
    total_spent = 0.0
    disc_pct = 0.0
    ref_cnt = 0
  else:
    lang = existing["lang"] or "bn"
    total_spent = float(existing["total_spent"] or 0.0)
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
      total_spent,
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
        INSERT INTO users (
            user_id, full_name, username, lang, balance,
            total_spent, discount_pct, referral_count, referred_by, joined_at
        )
        VALUES (?, 'User', 'N/A', ?, 0.0, 0.0, 0.0, 0, 0, ?)
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
      "SELECT full_name, username, lang, total_spent, discount_pct,"
      " referral_count FROM users WHERE user_id = ?",
      (user_id,),
  )
  row = cur.fetchone()
  conn.close()
  if not row:
    return "User", "N/A", "bn", 0.0, 0.0, 0
  return (
      row["full_name"] or "User",
      row["username"] or "N/A",
      row["lang"] or "bn",
      float(row["total_spent"] or 0.0),
      float(row["discount_pct"] or 0.0),
      int(row["referral_count"] or 0),
  )


def build_welcome_message(full_name: str, lang: str) -> str:
  safe_name = html.escape(full_name)
  safe_sup = f"<code>{html.escape(SUPPORT_HANDLE)}</code>"
  ch_link = f'<a href="{html.escape(CHANNEL_URL)}">CLICK HERE</a>'
  if lang == "bn":
    return (
        f"👋 <b>স্বাগতম, {safe_name}!</b>\n"
        f"✨ <b>ZORO 404 OFFICIAL</b> বটে আপনাকে স্বাগতম।\n\n"
        f"এখান থেকে সহজে আপনার পছন্দের প্ল্যান বেছে নিয়ে অর্ডার করতে পারবেন।\n"
        f"📢 আপডেট চ্যানেল: {ch_link}\n"
        f"💬 সাপোর্ট: {safe_sup}\n\n"
        f"🛒 শুরু করতে নিচের <b>পাসওয়ার্ড কিনুন</b> বাটনে চাপুন।"
    )
  return (
      f"👋 <b>Welcome, {safe_name}!</b>\n"
      f"✨ Welcome to <b>ZORO 404 OFFICIAL</b>.\n\n"
      f"Choose your plan easily to place an order.\n"
      f"📢 Update Channel: {ch_link}\n"
      f"💬 Support: {safe_sup}\n\n"
      f"🛒 Tap <b>Buy Keys</b> below to get started."
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


def cancel_order_kb(oid: int, lang: str = "bn") -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(inline_keyboard=[[
      InlineKeyboardButton(
          text="❌ অর্ডার বাতিল করুন" if lang == "bn" else "❌ CANCEL ORDER",
          callback_data=f"cancelord_{oid}",
      )
  ]])


def reset_menu_kb(lang: str = "bn") -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🐬 DOLPHIN RESET", callback_data="reset_dolphin"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="❌ বন্ধ করুন" if lang == "bn" else "❌ CLOSE",
                  callback_data="reset_close",
              ),
          ],
      ]
  )


def back_to_reset_kb(lang: str = "bn") -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="⬅️ রিসেট মেনু" if lang == "bn" else "⬅️ RESET MENU",
                  callback_data="open_reset_menu",
              ),
          ],
          [
              InlineKeyboardButton(
                  text="❌ বন্ধ করুন" if lang == "bn" else "❌ CLOSE",
                  callback_data="reset_close",
              ),
          ],
      ]
  )


def category_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(text="🛡 ROOT", callback_data="cat_ROOT"),
              InlineKeyboardButton(
                  text="🔓 NON ROOT", callback_data="cat_NON_ROOT"
              ),
          ],
          [
              InlineKeyboardButton(text="📱 IOS", callback_data="cat_IOS"),
              InlineKeyboardButton(
                  text="💻 PC / LAPTOP", callback_data="cat_PC_LAPTOP"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="🌐 ALL PRODUCTS", callback_data="cat_ALL"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="JOIN UPDATE CHANNEL 🗣️", url=CHANNEL_URL
              ),
          ],
      ]
  )


def main_menu(user_id: int, lang: str) -> ReplyKeyboardMarkup:
  if lang == "en":
    rows = [
        [
            KeyboardButton(text="🛒 Buy Keys"),
            KeyboardButton(text="🔄 Reset System"),
        ],
        [
            KeyboardButton(text="📦 My Orders"),
            KeyboardButton(text="🌐 Change Language"),
        ],
        [
            KeyboardButton(text="📞 Support"),
        ],
    ]
  else:
    rows = [
        [
            KeyboardButton(text="🛒 পাসওয়ার্ড কিনুন"),
            KeyboardButton(text="🔄 রিসেট সিস্টেম"),
        ],
        [
            KeyboardButton(text="📦 আমার অর্ডার"),
            KeyboardButton(text="🌐 ভাষা পরিবর্তন"),
        ],
        [
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
          [
              InlineKeyboardButton(
                  text="💾 Backup DB", callback_data="adm_backup"
              ),
              InlineKeyboardButton(
                  text="♻️ Restore DB", callback_data="adm_restore"
              ),
          ],
      ]
  )


def easy_category_pick_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🛡 ROOT", callback_data="pickprodcat_ROOT"
              ),
              InlineKeyboardButton(
                  text="🔓 NON ROOT", callback_data="pickprodcat_NON_ROOT"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="📱 IOS", callback_data="pickprodcat_IOS"
              ),
              InlineKeyboardButton(
                  text="💻 PC / LAPTOP", callback_data="pickprodcat_PC_LAPTOP"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="🌐 ALL", callback_data="pickprodcat_ALL"
              ),
          ],
      ]
  )


def duration_unit_pick_kb() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="🕒 ঘণ্টা (HOURS)", callback_data="pickunit_HOURS"
              ),
              InlineKeyboardButton(
                  text="📅 দিন (DAYS)", callback_data="pickunit_DAYS"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="⬅️ অন্য প্রোডাক্ট বাছুন", callback_data="adm_addplan"
              ),
          ],
      ]
  )


def after_plan_added_kb(pid: int) -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="➕ এই প্রোডাক্টে আরেকটি প্ল্যান যোগ করুন",
                  callback_data=f"easyplanprod_{pid}",
              ),
          ],
          [
              InlineKeyboardButton(
                  text="📦 অন্য প্রোডাক্ট বাছুন", callback_data="adm_addplan"
              ),
              InlineKeyboardButton(
                  text="🛠 Admin Panel", callback_data="back_adm_panel"
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


async def setup_bot_commands():
  user_commands = [
      BotCommand(command="start", description="বট শুরু / মেনু খুলুন"),
      BotCommand(command="buy", description="পাসওয়ার্ড / কি কিনুন"),
      BotCommand(command="reset", description="নিজের কি রিসেট করুন"),
      BotCommand(command="orders", description="আমার অর্ডার দেখুন"),
      BotCommand(command="support", description="সাপোর্ট ও যোগাযোগ"),
  ]
  admin_commands = user_commands + [
      BotCommand(command="admin", description="অ্যাডমিন কন্ট্রোল প্যানেল"),
      BotCommand(command="key", description="অর্ডার এপ্রুভ ও Key পাঠান"),
      BotCommand(command="assign", description="কাস্টমার আইডিতে কি লক করুন"),
      BotCommand(command="report", description="সেলস রিপোর্ট দেখুন"),
      BotCommand(command="backup", description="ব্যাকআপ ফাইল নিন"),
      BotCommand(command="restore", description="ব্যাকআপ ফাইল রিস্টোর করুন"),
  ]
  try:
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(
        admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID)
    )
  except Exception as exc:
    logger.warning("Failed to set bot commands: %s", exc)


async def open_reset_menu(message: Message):
  uid = message.from_user.id
  prev_usr = user_states.get(uid) or {}
  await safe_delete_message(uid, prev_usr.get("reset_prompt_msg_id"))
  user_states.pop(uid, None)

  _, _, lang, _, _, _ = get_user_info(uid)
  txt = (
      "🔄 <b>রিসেট সিস্টেম</b>\n"
      "পাসওয়ার্ড রিসেট করতে নিচের বাটনে চাপুন:"
      if lang == "bn"
      else "🔄 <b>RESET SYSTEM</b>\n"
      "Tap below to reset your password:"
  )
  sent = await message.answer(
      txt, parse_mode="HTML", reply_markup=reset_menu_kb(lang)
  )
  user_states[uid] = {
      "step": "reset_menu",
      "reset_prompt_msg_id": sent.message_id,
  }


async def send_admin_panel_to_chat(chat_id: int):
  prev = admin_states.pop(ADMIN_ID, None)
  if prev:
    await safe_delete_messages(
        ADMIN_ID,
        [prev.get("prompt_msg_id"), prev.get("list_msg_id")],
    )

  conn = get_conn()
  cur = conn.cursor()
  cur.execute("SELECT COUNT(*) AS cnt FROM users")
  u_cnt = cur.fetchone()["cnt"]
  cur.execute("SELECT COUNT(*) AS cnt FROM products")
  p_cnt = cur.fetchone()["cnt"]
  cur.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'pending'")
  o_cnt = cur.fetchone()["cnt"]
  conn.close()

  await bot.send_message(
      chat_id=chat_id,
      text=(
          f"🛠 <b>ADMIN CONTROL</b> ({html.escape(SUPPORT_HANDLE)})\n"
          f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
          f"👥 <b>Total Users:</b> {u_cnt}\n"
          f"📦 <b>Total Products:</b> {p_cnt}\n"
          f"⏳ <b>Pending Orders:</b> {o_cnt}\n\n"
          f"👉 <i>নিচের বাটনে চাপলেই সহজ ধাপে কাজ করতে পারবেন।</i>"
      ),
      parse_mode="HTML",
      reply_markup=admin_panel_kb(),
  )


async def open_admin_panel(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  await send_admin_panel_to_chat(message.chat.id)


async def send_support_message(message: Message):
  uid = message.from_user.id
  prev_adm = admin_states.pop(uid, None)
  if prev_adm and uid == ADMIN_ID:
    await safe_delete_messages(
        uid, [prev_adm.get("prompt_msg_id"), prev_adm.get("list_msg_id")]
    )

  _, _, lang, _, _, _ = get_user_info(uid)
  ch_link = f'<a href="{html.escape(CHANNEL_URL)}">CLICK HERE</a>'
  safe_sup = f"<code>{html.escape(SUPPORT_HANDLE)}</code>"
  safe_wa = f"<code>{html.escape(WHATSAPP_NUMBER)}</code>"

  if lang == "bn":
    msg = (
        f"📞 <b>সাপোর্ট ও যোগাযোগ</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🔹 <b>টেলিগ্রাম সাপোর্ট:</b> {safe_sup}\n"
        f"🔹 <b>হোয়াটসঅ্যাপ:</b> {safe_wa}\n"
        f"🔹 <b>আপডেট চ্যানেল:</b> {ch_link}"
    )
  else:
    msg = (
        f"📞 <b>SUPPORT & CONTACT</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🔹 <b>Telegram Support:</b> {safe_sup}\n"
        f"🔹 <b>WhatsApp:</b> {safe_wa}\n"
        f"🔹 <b>Update Channel:</b> {ch_link}"
    )
  await message.answer(
      msg,
      parse_mode="HTML",
      link_preview_options=NO_PREVIEW,
      reply_markup=update_channel_kb(),
  )


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  await open_admin_panel(message)


@dp.message(Command("backup"))
async def cmd_backup(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  await send_backup_file_to_admin(ADMIN_ID)


@dp.message(Command("restore"))
async def cmd_restore(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  prompt = await message.answer(
      "♻️ <b>PRO RESTORE DATABASE</b>\n"
      "<b>রিস্টোর করার আগে অটো-ব্যাকআপ নেওয়া হবে। .json ফাইলটি পাঠান:</b>",
      parse_mode="HTML",
  )
  admin_states[ADMIN_ID] = {
      "step": "wait_restore_file",
      "prompt_msg_id": prompt.message_id,
  }


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
  await open_reset_menu(message)


@dp.message(Command("assign"))
async def cmd_assign_key(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  parts = (message.text or "").strip().split(maxsplit=2)
  if len(parts) < 3:
    await message.answer(
        "ব্যবহার: <code>/assign user_id key_value</code>", parse_mode="HTML"
    )
    return
  try:
    target_uid = int(parts[1].strip())
  except ValueError:
    await message.answer("❌ সঠিক সংখ্যাযুক্ত User ID দিন।")
    return
  key_val = parts[2].strip()
  assign_key_ownership(key_val, target_uid, product_name="DOLPHIN")
  await safe_delete_message(ADMIN_ID, message.message_id)
  done = await message.answer(
      f"✅ কি সফলভাবে ইউজার <code>{target_uid}</code>-এর সাথে লক হয়েছে।",
      parse_mode="HTML",
  )
  await asyncio.sleep(3)
  await safe_delete_message(ADMIN_ID, done.message_id)


@dp.message(Command("claim"))
async def cmd_claim_key(message: Message):
  uid = message.from_user.id
  _, _, lang, _, _, _ = get_user_info(uid)
  parts = (message.text or "").strip().split(maxsplit=1)
  await safe_delete_message(uid, message.message_id)

  if uid == ADMIN_ID:
    await message.answer("⚠️ অ্যাডমিন অ্যাকাউন্ট দিয়ে ক্লেইম লাগে না।")
    return

  if len(parts) < 2 or not parts[1].strip():
    await message.answer(
        "ব্যবহার: <code>/claim পাসওয়ার্ড</code>"
        if lang == "bn"
        else "Usage: <code>/claim password</code>",
        parse_mode="HTML",
    )
    return

  key_val = parts[1].strip()
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT owner_user_id FROM key_ownership WHERE key_value = ? ORDER BY id"
      " DESC LIMIT 1",
      (key_val,),
  )
  row = cur.fetchone()
  conn.close()

  if row and int(row["owner_user_id"] or 0) not in (0, uid):
    await message.answer(
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else (
            "❌ Password is incorrect or not found. Try again with a valid"
            " password."
        )
    )
    return

  ok, _ = await dolphin_claim_key_api(key_val, uid)
  if not ok:
    await message.answer(
        "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
        if lang == "bn"
        else (
            "❌ Password is incorrect or not found. Try again with a valid"
            " password."
        )
    )
    return

  assign_key_ownership(key_val, uid, product_name="DOLPHIN")
  await message.answer(
      "✅ পাসওয়ার্ড আপনার অ্যাকাউন্টে যুক্ত হয়েছে।"
      if lang == "bn"
      else "✅ Password linked to your account."
  )


@dp.message(CommandStart())
async def cmd_start(message: Message):
  uid = message.from_user.id
  prev_adm = admin_states.pop(uid, None)
  if prev_adm:
    await safe_delete_messages(
        uid, [prev_adm.get("prompt_msg_id"), prev_adm.get("list_msg_id")]
    )

  prev_usr = user_states.pop(uid, None)
  if prev_usr:
    await safe_delete_messages(
        uid,
        [
            prev_usr.get("order_msg_id"),
            prev_usr.get("submitted_msg_id"),
            prev_usr.get("reset_prompt_msg_id"),
        ],
    )

  (
      is_new,
      _,
      _,
      _,
      _,
      total_users,
      full_name,
      username,
      joined,
      _,
  ) = register_or_update_user(message, referrer_id=0)

  if is_new and message.from_user.id != ADMIN_ID:
    new_user_alert = (
        f"🎉 New User Joined!\n\n"
        f"👤 Name: {full_name}\n"
        f"🆔 Username: {username}\n"
        f"💬 Chat ID: {message.from_user.id}\n"
        f"🕒 Time: {joined}\n"
        f"👥 Total Users: {total_users}"
    )
    try:
      await bot.send_message(ADMIN_ID, new_user_alert)
    except Exception:
      pass

  await message.answer(
      "<b>ভাষা বেছে নিন / Choose Language:</b>",
      parse_mode="HTML",
      reply_markup=lang_kb(),
  )


@dp.callback_query(F.data.startswith("setlang_"))
async def cb_setlang(callback: CallbackQuery):
  lang = callback.data.split("_", 1)[1]
  uid = callback.from_user.id
  set_lang(uid, lang)
  full_name, _, _, _, _, _ = get_user_info(uid)

  await safe_delete_message(uid, callback.message.message_id)

  welcome_txt = build_welcome_message(full_name, lang)
  await bot.send_message(
      uid,
      welcome_txt,
      parse_mode="HTML",
      link_preview_options=NO_PREVIEW,
      reply_markup=main_menu(uid, lang),
  )
  await callback.answer()


@dp.message(F.text.in_(["🌐 ভাষা পরিবর্তন", "🌐 Change Language"]))
async def btn_change_lang(message: Message):
  uid = message.from_user.id
  prev_adm = admin_states.pop(uid, None)
  if prev_adm:
    await safe_delete_messages(
        uid, [prev_adm.get("prompt_msg_id"), prev_adm.get("list_msg_id")]
    )
  await message.answer(
      "<b>ভাষা বেছে নিন / Choose Language:</b>",
      parse_mode="HTML",
      reply_markup=lang_kb(),
  )


@dp.message(F.text.in_(["🔄 রিসেট সিস্টেম", "🔄 Reset System", "Reset System"]))
async def btn_reset_system(message: Message):
  await open_reset_menu(message)


@dp.callback_query(F.data == "open_reset_menu")
async def cb_open_reset_menu(callback: CallbackQuery):
  uid = callback.from_user.id
  _, _, lang, _, _, _ = get_user_info(uid)
  user_states[uid] = {
      "step": "reset_menu",
      "reset_prompt_msg_id": callback.message.message_id,
  }
  txt = (
      "🔄 <b>রিসেট সিস্টেম</b>\n"
      "পাসওয়ার্ড রিসেট করতে নিচের বাটনে চাপুন:"
      if lang == "bn"
      else "🔄 <b>RESET SYSTEM</b>\n"
      "Tap below to reset your password:"
  )
  await callback.message.edit_text(
      txt, parse_mode="HTML", reply_markup=reset_menu_kb(lang)
  )
  await callback.answer()


@dp.callback_query(F.data == "reset_dolphin")
async def cb_reset_dolphin(callback: CallbackQuery):
  uid = callback.from_user.id
  _, _, lang, _, _, _ = get_user_info(uid)

  user_states[uid] = {
      "step": "wait_dolphin_reset_key",
      "reset_prompt_msg_id": callback.message.message_id,
  }

  txt = (
      "🐬 <b>DOLPHIN RESET</b>\n"
      "আপনার পাসওয়ার্ডটি লিখে পাঠান:"
      if lang == "bn"
      else "🐬 <b>DOLPHIN RESET</b>\n"
      "Send your password:"
  )
  await callback.message.edit_text(
      txt, parse_mode="HTML", reply_markup=back_to_reset_kb(lang)
  )
  await callback.answer()


@dp.callback_query(F.data == "reset_close")
async def cb_reset_close(callback: CallbackQuery):
  uid = callback.from_user.id
  if user_states.get(uid, {}).get("step") in (
      "reset_menu",
      "wait_dolphin_reset_key",
  ):
    user_states.pop(uid, None)
  await safe_delete_message(uid, callback.message.message_id)
  await callback.answer()


@dp.message(
    F.text.in_(["🛒 পাসওয়ার্ড কিনুন", "🛒 কি কিনুন", "🛒 Buy Keys"])
    | F.text.startswith("/buy")
)
async def btn_buy_keys(message: Message):
  uid = message.from_user.id
  prev_adm = admin_states.pop(uid, None)
  if prev_adm:
    await safe_delete_messages(
        uid, [prev_adm.get("prompt_msg_id"), prev_adm.get("list_msg_id")]
    )
  _, _, lang, _, _, _ = get_user_info(uid)
  header = (
      "🛒 <b>ক্যাটাগরি সিলেক্ট করুন:</b>"
      if lang == "bn"
      else "🛒 <b>SELECT CATEGORY:</b>"
  )
  await message.answer(header, parse_mode="HTML", reply_markup=category_kb())


@dp.callback_query(F.data.startswith("cat_"))
async def cb_select_category(callback: CallbackQuery):
  cat_key = callback.data.split("_", 1)[1]
  _, _, lang, _, _, _ = get_user_info(callback.from_user.id)

  conn = get_conn()
  cur = conn.cursor()
  if cat_key == "ALL":
    cur.execute("SELECT id, name FROM products ORDER BY id")
    cat_title = "🌐 ALL PRODUCTS"
  else:
    cur.execute(
        "SELECT id, name FROM products WHERE category = ? ORDER BY id",
        (cat_key,),
    )
    cat_label_map = {
        "IOS": "📱 IOS",
        "PC_LAPTOP": "💻 PC / LAPTOP",
        "NON_ROOT": "🔓 NON ROOT",
        "ROOT": "🛡 ROOT",
    }
    cat_title = cat_label_map.get(cat_key, cat_key.upper())

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
              text=f"🔹 {row['name'].upper()}",
              callback_data=f"prod_{row['id']}",
          )
      ]
      for row in prods
  ]
  rows.append([
      InlineKeyboardButton(
          text="⬅️ ক্যাটাগরি পরিবর্তন" if lang == "bn" else "⬅️ CHANGE CATEGORY",
          callback_data="back_cats",
      )
  ])

  header = (
      f"📂 <b>ক্যাটাগরি: {cat_title}</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"<b>প্রোডাক্ট সিলেক্ট করুন:</b>"
      if lang == "bn"
      else f"📂 <b>CATEGORY: {cat_title}</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"<b>SELECT A PRODUCT:</b>"
  )
  await callback.message.edit_text(
      header,
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
  )
  await callback.answer()


@dp.callback_query(F.data == "back_cats")
async def cb_back_cats(callback: CallbackQuery):
  _, _, lang, _, _, _ = get_user_info(callback.from_user.id)
  await callback.message.edit_text(
      "🛒 <b>ক্যাটাগরি সিলেক্ট করুন:</b>"
      if lang == "bn"
      else "🛒 <b>SELECT CATEGORY:</b>",
      parse_mode="HTML",
      reply_markup=category_kb(),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("prod_"))
async def cb_select_product(callback: CallbackQuery):
  pid = int(callback.data.split("_", 1)[1])
  _, _, lang, total_spent, _, _ = get_user_info(callback.from_user.id)

  conn = get_conn()
  cur = conn.cursor()
  cur.execute("SELECT name, category FROM products WHERE id = ?", (pid,))
  p_row = cur.fetchone()
  cur.execute(
      "SELECT id, duration, price, stock, bonus FROM plans WHERE product_id ="
      " ? ORDER BY id",
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

  pname = p_row["name"].upper()
  cat_back = p_row["category"] or "ALL"
  buttons = []
  for pl in plans:
    base_p = float(pl["price"])
    stk = int(pl["stock"] or 0)
    app_pct, _, final_p = calc_discount_details(
        pname, pl["duration"], base_p, 0.0, total_spent
    )
    shown_price = final_p if app_pct > 0 else base_p
    out_tag = " [STOCK OUT]" if stk <= 0 else ""
    dur_upper = (pl["duration"] or "").upper()
    label = (
        f"⏱ {dur_upper}  |  ৳{shown_price:.0f}{format_bonus_bracket(pl['bonus'])}{out_tag}"
    )
    buttons.append(
        [InlineKeyboardButton(text=label, callback_data=f"plan_{pl['id']}")]
    )

  buttons.append([
      InlineKeyboardButton(
          text="⬅️ ব্যাক" if lang == "bn" else "⬅️ BACK",
          callback_data=f"cat_{cat_back}",
      )
  ])

  title = (
      f"📦 <b>প্রোডাক্ট: {pname}</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"<b>মেয়াদ ও দাম সিলেক্ট করুন:</b>"
      if lang == "bn"
      else f"📦 <b>PRODUCT: {pname}</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"<b>SELECT DURATION & PRICE:</b>"
  )
  await callback.message.edit_text(
      title,
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("plan_"))
async def cb_select_plan(callback: CallbackQuery):
  plid = int(callback.data.split("_", 1)[1])
  uid = callback.from_user.id
  _, _, lang, total_spent, _, _ = get_user_info(uid)

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT p.name, pl.duration, pl.price, pl.stock, pl.bonus
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

  if int(row["stock"] or 0) <= 0:
    conn.close()
    await callback.answer(
        "এই প্ল্যানের স্টক বর্তমানে শেষ।"
        if lang == "bn"
        else "This plan is currently out of stock.",
        show_alert=True,
    )
    return

  pname = row["name"].upper()
  duration = (row["duration"] or "").upper()
  base_price = (
      round_to_0_or_5(float(row["price"]))
      if is_dolphin_product(pname)
      else round_to_zero(float(row["price"]))
  )
  bonus = row["bonus"] or ""
  app_pct, disc_amt, final_price = calc_discount_details(
      pname, duration, base_price, 0.0, total_spent
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

  bonus_line = f"\n🎁 <b>অফার:</b> {html.escape(bonus)}" if bonus else ""
  if lang == "bn":
    msg = (
        f"🛒 <b>অর্ডার #{oid}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📦 <b>প্রোডাক্ট:</b> {html.escape(pname)}\n"
        f"⏱ <b>সময় / মেয়াদ:</b> {html.escape(duration)}{bonus_line}\n"
        f"💵 <b>মোট টাকা:</b> <b>৳{final_price:.0f}</b> (Send Money)\n\n"
        f"📲 <b>পেমেন্ট নম্বর (ক্লিক করে কপি করুন):</b>\n"
        f"• <b>বিকাশ:</b> <code>{html.escape(bkash_num)}</code>\n"
        f"• <b>নগদ:</b> <code>{html.escape(nagad_num)}</code>\n\n"
        f"টাকা পাঠানোর পর যেকোনো ১টি দিন:\n"
        f"📸 <b>পেমেন্টের স্ক্রিনশট</b>\n"
        f"অথবা\n"
        f"✍️ <b>সঠিক TrxID / ১১ ডিজিটের মোবাইল নম্বর</b>"
    )
  else:
    msg = (
        f"🛒 <b>ORDER #{oid}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📦 <b>PRODUCT:</b> {html.escape(pname)}\n"
        f"⏱ <b>DURATION:</b> {html.escape(duration)}{bonus_line}\n"
        f"💵 <b>TOTAL AMOUNT:</b> <b>৳{final_price:.0f}</b> (Send Money)\n\n"
        f"📲 <b>PAYMENT NUMBERS (Tap to copy):</b>\n"
        f"• <b>bKash:</b> <code>{html.escape(bkash_num)}</code>\n"
        f"• <b>Nagad:</b> <code>{html.escape(nagad_num)}</code>\n\n"
        f"After sending money, send any ONE:\n"
        f"📸 <b>Payment screenshot</b>\n"
        f"OR\n"
        f"✍️ <b>Valid TrxID / 11-digit mobile number</b>"
    )

  await callback.message.edit_text(
      msg, parse_mode="HTML", reply_markup=cancel_order_kb(oid, lang)
  )

  user_states[uid] = {
      "step": "wait_proof",
      "order_id": oid,
      "order_msg_id": callback.message.message_id,
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
  await callback.answer()


@dp.callback_query(F.data.startswith("cancelord_"))
async def cb_user_cancel_order(callback: CallbackQuery):
  oid = int(callback.data.split("_", 1)[1])
  uid = callback.from_user.id

  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT status FROM orders WHERE id = ? AND user_id = ?", (oid, uid)
  )
  row = cur.fetchone()
  if row and row["status"] == "pending_payment":
    cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
    conn.commit()
  conn.close()

  if user_states.get(uid, {}).get("order_id") == oid:
    user_states.pop(uid, None)

  await safe_delete_message(uid, callback.message.message_id)
  await callback.answer()


@dp.message(
    F.text.in_(["📦 আমার অর্ডার", "📦 My Orders"]) | F.text.startswith("/orders")
)
async def btn_my_orders(message: Message):
  uid = message.from_user.id
  prev_adm = admin_states.pop(uid, None)
  if prev_adm:
    await safe_delete_messages(
        uid, [prev_adm.get("prompt_msg_id"), prev_adm.get("list_msg_id")]
    )

  _, _, lang, _, _, _ = get_user_info(uid)
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
      (uid,),
  )
  rows = cur.fetchall()
  conn.close()

  if not rows:
    await message.answer(
        "<b>আপনার কোনো অর্ডার নেই।</b>" if lang == "bn" else "<b>No orders yet.</b>",
        parse_mode="HTML",
    )
    return

  lines = []
  for r in rows:
    proof_txt = (
        r["trx_id"]
        or r["sender_number"]
        or ("Screenshot sent" if r["proof_photo_id"] else "-")
    )
    key_txt = (
        f"\n   🔑 <b>Key/Pass:</b> <code>{html.escape(r['delivered_key'])}</code>"
        if r["delivered_key"]
        else ""
    )
    st_txt = status_label(r["status"], lang).upper()
    paid_amt = float(r["final_amount"] or r["price"] or 0.0)
    lines.append(
        f"<b>#{r['id']}</b> | <b>{html.escape(r['name'].upper())}</b>"
        f" ({html.escape((r['duration'] or '').upper())}) —"
        f" <b>৳{paid_amt:.0f}</b> [{html.escape(st_txt)}]\n"
        f"   🕒 {html.escape(r['created_at'])} | Proof:"
        f" {html.escape(proof_txt)}{key_txt}"
    )
  await message.answer(
      "\n\n".join(lines),
      parse_mode="HTML",
      link_preview_options=NO_PREVIEW,
      reply_markup=update_channel_kb(),
  )


@dp.message(
    F.text.in_(["📞 সাপোর্ট", "📞 Support", "সাপোর্ট", "support", "Support"])
    | F.text.startswith("/support")
)
async def btn_support(message: Message):
  await send_support_message(message)


def finalize_order_approval(oid: int, key_val: str):
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT o.id, o.user_id, o.plan_id, o.final_amount, o.discount_used_pct,
               o.status, pl.price, pl.duration, p.name AS prod_name, u.lang AS user_lang
        FROM orders o
        JOIN plans pl ON o.plan_id = pl.id
        JOIN products p ON pl.product_id = p.id
        LEFT JOIN users u ON o.user_id = u.user_id
        WHERE o.id = ?
        """,
      (oid,),
  )
  row = cur.fetchone()
  if not row:
    conn.close()
    return None, "", "", "bn"

  target_uid = row["user_id"]
  plid = row["plan_id"]
  paid_amt = float(row["final_amount"] or row["price"] or 0.0)
  already_approved = row["status"] == "approved"
  prod_name = row["prod_name"] or ""
  duration = row["duration"] or ""
  user_lang = row["user_lang"] or "bn"

  cur.execute(
      "SELECT total_spent FROM users WHERE user_id = ?",
      (target_uid,),
  )
  urow = cur.fetchone()
  old_spent = float(urow["total_spent"] or 0.0) if urow else 0.0

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
    new_spent = round(old_spent + paid_amt, 2)
    cur.execute(
        "UPDATE users SET total_spent = ? WHERE user_id = ?",
        (new_spent, target_uid),
    )

  conn.commit()
  conn.close()

  assign_key_ownership(key_val, target_uid, product_name=prod_name or "DOLPHIN")

  return target_uid, prod_name, duration, user_lang


async def deliver_approved_key_message(
    target_uid: int,
    oid: int,
    pname: str,
    duration: str,
    key_val: str,
    lang: str = "bn",
):
  msg_txt = build_approved_order_message(oid, pname, duration, key_val, lang)
  await bot.send_message(
      target_uid,
      msg_txt,
      parse_mode="HTML",
      link_preview_options=NO_PREVIEW,
      reply_markup=update_channel_kb(),
  )


@dp.message(Command("key"))
async def cmd_admin_key(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  parts = (message.text or "").strip().split(maxsplit=1)
  if len(parts) < 2 or not parts[1].strip():
    await safe_delete_message(ADMIN_ID, message.message_id)
    warn = await message.answer("ব্যবহার: /key USER: abc PASS: 123")
    await asyncio.sleep(3)
    await safe_delete_message(ADMIN_ID, warn.message_id)
    return

  key_val = parts[1].strip()
  prev_state = admin_states.pop(ADMIN_ID, None) or {}
  target_oid = prev_state.get("order_id")

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
    await safe_delete_message(ADMIN_ID, message.message_id)
    return

  oid = row["id"]
  target_uid, pname, duration, user_lang = finalize_order_approval(oid, key_val)
  if not target_uid:
    return

  await safe_delete_messages(
      ADMIN_ID,
      [
          message.message_id,
          prev_state.get("prompt_msg_id"),
          prev_state.get("alert_msg_id"),
      ],
  )

  try:
    await deliver_approved_key_message(
        target_uid, oid, pname, duration, key_val, user_lang
    )
  except Exception:
    pass


@dp.message(Command("report"))
async def cmd_admin_report(message: Message):
  if message.from_user.id != ADMIN_ID:
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
  await message.answer(
      f"📊 <b>সেলস রিপোর্ট</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"• <b>এপ্রুভড অর্ডার:</b> {app_ord['cnt']} টি (<b>৳{total_sales:.0f}</b>)\n"
      f"• <b>পেন্ডিং অর্ডার:</b> {pend_ord} টি\n"
      f"• <b>রিজেক্টেড অর্ডার:</b> {rej_ord} টি",
      parse_mode="HTML",
  )


@dp.message(F.text == "🛠 Admin Panel")
async def btn_admin_panel(message: Message):
  if message.from_user.id != ADMIN_ID:
    return
  await open_admin_panel(message)


@dp.callback_query(F.data == "back_adm_panel")
async def cb_back_adm_panel(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  await safe_delete_message(callback.message.chat.id, callback.message.message_id)
  await send_admin_panel_to_chat(callback.message.chat.id)
  await callback.answer()


@dp.callback_query(F.data == "adm_backup")
async def cb_adm_backup(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  await callback.answer("ব্যাকআপ তৈরি হচ্ছে...")
  await send_backup_file_to_admin(ADMIN_ID)


@dp.callback_query(F.data == "adm_restore")
async def cb_adm_restore(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  prompt = await callback.message.answer(
      "♻️ <b>PRO RESTORE DATABASE</b>\n"
      "<b>রিস্টোর করার আগে অটো-ব্যাকআপ নেওয়া হবে। .json ফাইলটি পাঠান:</b>",
      parse_mode="HTML",
  )
  admin_states[ADMIN_ID] = {
      "step": "wait_restore_file",
      "prompt_msg_id": prompt.message_id,
  }
  await callback.answer()


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
      f"📊 <b>সেলস রিপোর্ট</b>\n"
      f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
      f"• <b>এপ্রুভড অর্ডার:</b> {app_ord['cnt']} টি (<b>৳{total_sales:.0f}</b>)\n"
      f"• <b>পেন্ডিং অর্ডার:</b> {pend_ord} টি\n"
      f"• <b>রিজেক্টেড অর্ডার:</b> {rej_ord} টি"
  )
  await callback.message.answer(report_txt, parse_mode="HTML")
  await callback.answer()


@dp.callback_query(F.data == "adm_paynums")
async def cb_adm_paynums(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  bkash_num, nagad_num = get_payment_numbers()
  await callback.message.answer(
      f"💳 <b>বর্তমান পেমেন্ট নম্বর:</b>\n"
      f"• <b>বিকাশ:</b> <code>{html.escape(bkash_num)}</code>\n"
      f"• <b>নগদ:</b> <code>{html.escape(nagad_num)}</code>\n\n"
      f"যে নম্বরটি বদলাতে চান নিচের বাটনে চাপুন:",
      parse_mode="HTML",
      reply_markup=payment_numbers_kb(),
  )
  await callback.answer()


@dp.callback_query(F.data.in_(["setpay_bkash", "setpay_nagad"]))
async def cb_setpay_method(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  method = "bkash" if callback.data == "setpay_bkash" else "nagad"
  label = "বিকাশ" if method == "bkash" else "নগদ"
  prompt = await callback.message.answer(f"নতুন {label} নম্বরটি লিখে পাঠান:")
  admin_states[callback.from_user.id] = {
      "step": "set_pay_num",
      "method": method,
      "prompt_msg_id": prompt.message_id,
  }
  await callback.answer()


@dp.callback_query(F.data == "adm_lookup")
async def cb_adm_lookup(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  prompt = await callback.message.answer(
      "যেকোনো ইউজারের UserID লিখে পাঠান (উদাহরণ: 5882761122):"
  )
  admin_states[callback.from_user.id] = {
      "step": "user_lookup",
      "prompt_msg_id": prompt.message_id,
  }
  await callback.answer()


@dp.callback_query(F.data == "adm_users")
async def cb_adm_users(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      "SELECT user_id, full_name, username, total_spent, joined_at FROM users"
      " ORDER BY user_id DESC LIMIT 15"
  )
  rows = cur.fetchall()
  cur.execute("SELECT COUNT(*) AS cnt FROM users")
  total = cur.fetchone()["cnt"]
  conn.close()

  if not rows:
    await callback.message.answer("কোনো ইউজার নেই।")
    await callback.answer()
    return

  lines = [f"📊 <b>Total Users:</b> {total}\n"]
  for r in rows:
    sp = float(r["total_spent"] or 0.0)
    vp = get_vip_discount_pct(sp)
    lines.append(
        f"• <code>{r['user_id']}</code> | <b>{html.escape(r['full_name'])}</b>"
        f" ({html.escape(r['username'])}) | Spent: <b>৳{sp:.0f}</b> (VIP"
        f" {vp:.0f}%) | 🕒 {html.escape(r['joined_at'])}"
    )
  await callback.message.answer("\n".join(lines), parse_mode="HTML")
  await callback.answer()


@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  prompt = await callback.message.answer("সব ইউজারকে পাঠানোর মেসেজটি লিখুন:")
  admin_states[callback.from_user.id] = {
      "step": "broadcast",
      "prompt_msg_id": prompt.message_id,
  }
  await callback.answer()


# ==========================================
# EASY PRODUCT & PLAN ADMIN WORKFLOWS
# ==========================================
@dp.callback_query(F.data == "adm_addprod")
async def cb_adm_addprod(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  prompt = await callback.message.answer(
      "➕ <b>নতুন প্রোডাক্ট যোগ করুন</b>\n"
      "শুধু প্রোডাক্টের <b>নাম</b> লিখে পাঠান (যেমন: <code>SHARK PANEL</code>):",
      parse_mode="HTML",
  )
  admin_states[callback.from_user.id] = {
      "step": "easy_addprod_name",
      "prompt_msg_id": prompt.message_id,
  }
  await callback.answer()


@dp.callback_query(F.data.startswith("pickprodcat_"))
async def cb_easy_pick_prod_cat(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  cat_val = callback.data.split("_", 1)[1]
  state = admin_states.get(ADMIN_ID) or {}
  pname = (state.get("new_prod_name") or "").strip()
  if not pname:
    await callback.answer("আগে প্রোডাক্টের নাম দিন।", show_alert=True)
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

  admin_states.pop(ADMIN_ID, None)
  await safe_delete_message(ADMIN_ID, callback.message.message_id)
  await callback.message.answer(
      f"✅ প্রোডাক্ট <b>{html.escape(pname)}</b> [{html.escape(cat_val)}] যোগ হয়েছে!\n"
      f"এখন এই প্রোডাক্টে প্ল্যান যোগ করতে নিচের বাটনে চাপুন:",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(
          inline_keyboard=[[
              InlineKeyboardButton(
                  text="⏱ এই প্রোডাক্টে প্ল্যান যোগ করুন",
                  callback_data=f"easyplanprod_{pid}",
              )
          ]]
      ),
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

  rows = [
      [
          InlineKeyboardButton(
              text=f"🗑 {r['name']} [{r['category']}]",
              callback_data=f"easydelprod_{r['id']}",
          )
      ]
      for r in prods
  ]
  await callback.message.answer(
      "🗑 <b>যে প্রোডাক্ট ডিলিট করতে চান তাতে চাপুন:</b>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("easydelprod_"))
async def cb_easy_delprod(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  pid = int(callback.data.split("_", 1)[1])
  conn = get_conn()
  cur = conn.cursor()
  cur.execute("SELECT name FROM products WHERE id = ?", (pid,))
  prow = cur.fetchone()
  if prow:
    cur.execute("DELETE FROM plans WHERE product_id = ?", (pid,))
    cur.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
  conn.close()
  await safe_delete_message(ADMIN_ID, callback.message.message_id)
  if prow:
    done = await callback.message.answer(
        f"🗑 প্রোডাক্ট <b>{html.escape(prow['name'])}</b> ডিলিট হয়েছে।",
        parse_mode="HTML",
    )
    await asyncio.sleep(3)
    await safe_delete_message(ADMIN_ID, done.message_id)
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

  rows = [
      [
          InlineKeyboardButton(
              text=f"📦 {r['name']} [{r['category']}]",
              callback_data=f"easyplanprod_{r['id']}",
          )
      ]
      for r in prods
  ]
  await callback.message.edit_text(
      "⏱ <b>কোন প্রোডাক্টে প্ল্যান যোগ করবেন? বাটনে চাপুন:</b>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("easyplanprod_"))
async def cb_easy_plan_prod(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  pid = int(callback.data.split("_", 1)[1])
  conn = get_conn()
  cur = conn.cursor()
  cur.execute("SELECT name FROM products WHERE id = ?", (pid,))
  prow = cur.fetchone()
  conn.close()

  if not prow:
    await callback.answer("প্রোডাক্ট পাওয়া যায়নি।", show_alert=True)
    return

  admin_states[ADMIN_ID] = {
      "step": "easy_plan_pick_unit",
      "plan_pid": pid,
      "plan_pname": prow["name"],
      "prompt_msg_id": callback.message.message_id,
  }
  await callback.message.edit_text(
      f"📦 প্রোডাক্ট: <b>{html.escape(prow['name'])}</b>\n"
      f"⏱ <b>মেয়াদ কিসে দেবেন? ঘণ্টা নাকি দিন সিলেক্ট করুন:</b>",
      parse_mode="HTML",
      reply_markup=duration_unit_pick_kb(),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("pickunit_"))
async def cb_pick_duration_unit(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  unit_type = callback.data.split("_", 1)[1]
  state = admin_states.get(ADMIN_ID) or {}
  pid = state.get("plan_pid")
  pname = state.get("plan_pname") or ""
  if not pid:
    await callback.answer("আবার Add Plan চাপুন।", show_alert=True)
    return

  admin_states[ADMIN_ID] = {
      "step": "easy_plan_wait_num",
      "plan_pid": pid,
      "plan_pname": pname,
      "plan_unit": unit_type,
      "prompt_msg_id": callback.message.message_id,
  }
  if unit_type == "HOURS":
    prompt_txt = (
        f"📦 প্রোডাক্ট: <b>{html.escape(pname)}</b>\n"
        f"🕒 ইউনিট: <b>ঘণ্টা (HOURS)</b>\n"
        f"✍️ <b>কত ঘণ্টা অ্যাড করতে চান? সংখ্যা লিখুন</b> (একটি বা একাধিক: <code>1 2 6</code>):"
    )
  else:
    prompt_txt = (
        f"📦 প্রোডাক্ট: <b>{html.escape(pname)}</b>\n"
        f"📅 ইউনিট: <b>দিন (DAYS)</b>\n"
        f"✍️ <b>কত দিন অ্যাড করতে চান? সংখ্যা লিখুন</b> (একটি বা একাধিক: <code>1 10 20</code>):"
    )
  await callback.message.edit_text(prompt_txt, parse_mode="HTML")
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

  kb_rows = [
      [
          InlineKeyboardButton(
              text=(
                  f"🗑 {r['name']} — {r['duration']} (৳{float(r['price']):.0f})"
              ),
              callback_data=f"easydelplan_{r['id']}",
          )
      ]
      for r in rows
  ]
  await callback.message.answer(
      "🗑 <b>যে প্ল্যান ডিলিট করতে চান তাতে চাপুন:</b>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("easydelplan_"))
async def cb_easy_delplan(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  plid = int(callback.data.split("_", 1)[1])
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT pl.duration, p.name
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        WHERE pl.id = ?
        """,
      (plid,),
    )
  prow = cur.fetchone()
  if prow:
    cur.execute("DELETE FROM plans WHERE id = ?", (plid,))
    conn.commit()
  conn.close()
  await safe_delete_message(ADMIN_ID, callback.message.message_id)
  if prow:
    done = await callback.message.answer(
        f"🗑 প্ল্যান <b>{html.escape(prow['name'])} — {html.escape(prow['duration'])}</b> ডিলিট হয়েছে।",
        parse_mode="HTML",
    )
    await asyncio.sleep(3)
    await safe_delete_message(ADMIN_ID, done.message_id)
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

  kb_rows = [
      [
          InlineKeyboardButton(
              text=(
                  f"✏️ {r['name']} — {r['duration']} (৳{float(r['price']):.0f})"
              ),
              callback_data=f"easyeditplan_{r['id']}",
          )
      ]
      for r in rows
  ]
  await callback.message.answer(
      "✏️ <b>কোন প্ল্যানের দাম বদলাতে চান? চাপুন:</b>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("easyeditplan_"))
async def cb_easy_editplan_pick(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  plid = int(callback.data.split("_", 1)[1])
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
  conn.close()
  if not prow:
    await callback.answer("প্ল্যান পাওয়া যায়নি।", show_alert=True)
    return

  admin_states[ADMIN_ID] = {
      "step": "easy_edit_wait_price",
      "edit_plid": plid,
      "prompt_msg_id": callback.message.message_id,
  }
  await callback.message.edit_text(
      f"✏️ <b>{html.escape(prow['name'])} — {html.escape(prow['duration'])}</b>\n"
      f"বর্তমান দাম: <b>৳{float(prow['price']):.0f}</b>\n"
      f"নতুন দাম কত? শুধু সংখ্যা লিখুন:",
      parse_mode="HTML",
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

  kb_rows = [
      [
          InlineKeyboardButton(
              text=(
                  f"🎁 {r['name']} — {r['duration']} {format_bonus_bracket(r['bonus'])}"
              ),
              callback_data=f"easyofferplan_{r['id']}",
          )
      ]
      for r in rows
  ]
  await callback.message.answer(
      "🎁 <b>কোন প্ল্যানে অফার সেট বা রিমুভ করবেন? চাপুন:</b>",
      parse_mode="HTML",
      reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
  )
  await callback.answer()


@dp.callback_query(F.data.startswith("easyofferplan_"))
async def cb_easy_offer_pick(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  plid = int(callback.data.split("_", 1)[1])
  conn = get_conn()
  cur = conn.cursor()
  cur.execute(
      """
        SELECT pl.id, pl.duration, pl.bonus, p.name
        FROM plans pl
        JOIN products p ON pl.product_id = p.id
        WHERE pl.id = ?
        """,
      (plid,),
    )
  prow = cur.fetchone()
  conn.close()
  if not prow:
    await callback.answer("প্ল্যান পাওয়া যায়নি।", show_alert=True)
    return

  admin_states[ADMIN_ID] = {
      "step": "easy_offer_wait_text",
      "offer_plid": plid,
      "prompt_msg_id": callback.message.message_id,
  }
  await callback.message.edit_text(
      f"🎁 <b>{html.escape(prow['name'])} — {html.escape(prow['duration'])}</b>\n"
      f"অফার টেক্সট লিখুন (যেমন: <code>1 Day Free</code>)\n"
      f"অথবা অফার মুছে ফেলতে লিখুন: <code>-</code>",
      parse_mode="HTML",
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
    await callback.answer("কোনো Pending অর্ডার নেই।", show_alert=True)
    return

  for r in rows:
    offer_txt = f"\n🎁 Offer: {r['bonus']}" if r["bonus"] else ""
    proof_val = r["trx_id"] or r["sender_number"]
    proof_line = (
        f"\n🧾 Info: {proof_val}" if proof_val else "\n📸 Proof: Screenshot"
    )
    paid_amt = float(r["final_amount"] or r["price"] or 0.0)
    pay_method = detect_payment_method_label(
        r["sender_number"], r["trx_id"], r["proof_photo_id"]
    )

    caption_txt = (
        f"📥 <b>NEW ORDER REQUEST #{r['id']}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 <b>User ID:</b> <code>{r['user_id']}</code>\n"
        f"📦 <b>Panel:</b> <b>{html.escape(r['name'])}</b> ({html.escape(r['duration'])})\n"
        f"💰 <b>Amount:</b> <b>৳{paid_amt:.0f}</b>\n"
        f"💳 <b>Method:</b> {html.escape(pay_method)}\n"
        f"🕒 <b>Time:</b> <code>{html.escape(r['created_at'])}</code>"
        f"{offer_txt}{proof_line}"
    )
    if r["proof_photo_id"]:
      await callback.message.answer_photo(
          photo=r["proof_photo_id"],
          caption=caption_txt,
          parse_mode="HTML",
          reply_markup=order_approve_start_kb(r["id"]),
      )
    else:
      await callback.message.answer(
          caption_txt,
          parse_mode="HTML",
          reply_markup=order_approve_start_kb(r["id"]),
      )
  await callback.answer()


@dp.callback_query(F.data.startswith("reqapp_"))
async def cb_req_approve_with_key(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    return
  oid = int(callback.data.split("_", 1)[1])
  prompt = await callback.message.answer(
      f"🔑 Order #{oid} এর ইউজার ও পাসওয়ার্ড লিখুন:"
  )
  admin_states[callback.from_user.id] = {
      "step": "wait_approve_key",
      "order_id": oid,
      "prompt_msg_id": prompt.message_id,
      "alert_msg_id": callback.message.message_id,
  }
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

  await safe_delete_message(ADMIN_ID, callback.message.message_id)
  await callback.answer("Rejected")


@dp.message()
async def handle_messages(message: Message):
  uid = message.from_user.id
  txt = (message.text or "").strip()

  if uid == ADMIN_ID and uid in admin_states:
    state = admin_states[uid]
    step = state.get("step")
    prompt_id = state.get("prompt_msg_id")

    if step == "wait_restore_file":
      if not message.document:
        await message.answer(
            "❌ অনুগ্রহ করে ব্যাকআপ <code>.json</code> ফাইলটি ডকুমেন্ট হিসেবে পাঠান।",
            parse_mode="HTML",
        )
        return
      buf = io.BytesIO()
      try:
        await send_backup_file_to_admin(
            uid, title_prefix="PRE-RESTORE SAFETY BACKUP"
        )
        await bot.download(message.document, destination=buf)
        raw_text = buf.getvalue().decode("utf-8")
        data = json.loads(raw_text)
        restored = import_full_backup_payload(data)
        admin_states.pop(uid, None)
        await safe_delete_messages(uid, [message.message_id, prompt_id])

        await message.answer(
            f"✅ <b>PRO RESTORE COMPLETED SUCCESSFULLY!</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"• 👥 <b>USERS RESTORED:</b> <b>{restored['users']}</b>\n"
            f"• 📦 <b>PRODUCTS RESTORED:</b> <b>{restored['products']}</b>\n"
            f"• ⏱ <b>PLANS RESTORED:</b> <b>{restored['plans']}</b>\n"
            f"• 🧾 <b>ORDERS RESTORED:</b> <b>{restored['orders']}</b>\n"
            f"• 🔐 <b>KEY LOCKS RESTORED:</b> <b>{restored['key_ownership']}</b>",
            parse_mode="HTML",
        )
      except Exception as exc:
        logger.warning("Restore failed: %s", exc)
        await message.answer(
            "❌ <b>ব্যাকআপ ফাইলটি সঠিকভাবে রিস্টোর করা যায়নি। সেফটি ব্যাকআপ ও বর্তমান ডেটা অক্ষত আছে।</b>",
            parse_mode="HTML",
        )
      return

    if step == "easy_addprod_name":
      if not txt:
        return
      admin_states[uid] = {
          "step": "easy_addprod_cat",
          "new_prod_name": txt,
          "prompt_msg_id": prompt_id,
      }
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      sent = await message.answer(
          f"📦 প্রোডাক্ট: <b>{html.escape(txt)}</b>\n"
          f"<b>ক্যাটাগরি বাটনে চাপুন:</b>",
          parse_mode="HTML",
          reply_markup=easy_category_pick_kb(),
      )
      admin_states[uid]["prompt_msg_id"] = sent.message_id
      return

    if step == "easy_plan_wait_num":
      vals = parse_multi_int_values(txt)
      if not vals:
        warn = await message.answer(
            "❌ সঠিক সংখ্যা লিখুন (যেমন: 1 বা 1 2 6 বা 1, 10, 20)"
        )
        await asyncio.sleep(2)
        await safe_delete_message(uid, warn.message_id)
        return
      unit_type = state.get("plan_unit") or "DAYS"
      durs = [format_unit_duration(v, unit_type) for v in vals]
      pid = state.get("plan_pid")
      pname = state.get("plan_pname") or ""
      admin_states[uid] = {
          "step": "easy_plan_wait_price",
          "plan_pid": pid,
          "plan_pname": pname,
          "plan_durs": durs,
          "prompt_msg_id": prompt_id,
      }
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      dur_preview = ", ".join(f"<code>{html.escape(d)}</code>" for d in durs)
      if len(durs) == 1:
        price_hint = (
            f"💵 <b>{dur_preview}</b>-এর দাম কত? শুধু সংখ্যা লিখুন (যেমন:"
            f" <code>300</code>):"
        )
      else:
        price_hint = (
            f"💵 <b>{len(durs)}টি</b> প্ল্যান ({dur_preview})-এর দাম একসাথে"
            f" লিখুন (যেমন: <code>50 90 150</code>):"
        )
      sent = await message.answer(
          f"📦 প্রোডাক্ট: <b>{html.escape(pname)}</b>\n"
          f"⏱ মেয়াদসমূহ: {dur_preview}\n"
          f"{price_hint}",
          parse_mode="HTML",
      )
      admin_states[uid]["prompt_msg_id"] = sent.message_id
      return

    if step == "easy_plan_wait_price":
      durs = state.get("plan_durs") or ["1 DAY"]
      raw_prices = parse_multi_price_values(txt)
      if not raw_prices:
        warn = await message.answer("❌ সঠিক দাম লিখুন (যেমন: 300 বা 50 90 150)")
        await asyncio.sleep(2)
        await safe_delete_message(uid, warn.message_id)
        return

      if len(durs) > 1 and len(raw_prices) == 1:
        raw_prices = raw_prices * len(durs)
      elif len(durs) > 1 and len(raw_prices) != len(durs):
        warn = await message.answer(
            f"❌ মেয়াদ আছে {len(durs)}টি, তাই {len(durs)}টি দাম লিখুন (বা ১টি দাম"
            " লিখলে সবগুলোতে সমান বসবে)।"
        )
        await asyncio.sleep(3)
        await safe_delete_message(uid, warn.message_id)
        return

      pid = state.get("plan_pid")
      pname = state.get("plan_pname") or ""
      admin_states[uid] = {
          "step": "easy_plan_wait_offer",
          "plan_pid": pid,
          "plan_pname": pname,
          "plan_durs": durs,
          "plan_raw_prices": raw_prices[: len(durs)],
          "prompt_msg_id": prompt_id,
      }
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      pairs_txt = "\n".join(
          f"• <b>{html.escape(d)}</b> — ৳{p:.0f}"
          for d, p in zip(durs, raw_prices[: len(durs)])
      )
      sent = await message.answer(
          f"📦 প্রোডাক্ট: <b>{html.escape(pname)}</b>\n"
          f"{pairs_txt}\n\n"
          f"🎁 কোনো অফার থাকলে লিখুন, না থাকলে <code>skip</code> বা <code>-</code> লিখুন:",
          parse_mode="HTML",
      )
      admin_states[uid]["prompt_msg_id"] = sent.message_id
      return

    if step == "easy_plan_wait_offer":
      pid = state.get("plan_pid")
      pname = state.get("plan_pname") or ""
      durs = state.get("plan_durs") or ["1 DAY"]
      raw_prices = state.get("plan_raw_prices") or [0.0] * len(durs)
      bonus = "" if txt.lower() in ("-", "skip", "no", "none", "0") else txt

      added_summary = []
      conn = get_conn()
      cur = conn.cursor()
      for dur, raw_p in zip(durs, raw_prices):
        brand_price = calc_brand_price(float(raw_p), pname, dur)
        cur.execute(
            "INSERT INTO plans (product_id, duration, price, stock, bonus)"
            " VALUES (?, ?, ?, 20, ?)",
            (pid, dur, brand_price, bonus),
        )
        added_summary.append(
            f"• <b>{html.escape(dur)}</b> — <b>৳{brand_price:.0f}</b>{html.escape(format_bonus_bracket(bonus))}"
        )
      conn.commit()
      conn.close()

      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      await message.answer(
          f"✅ <b>{len(added_summary)}টি প্ল্যান যোগ হয়েছে!</b>\n"
          f"📦 প্রোডাক্ট: <b>{html.escape(pname)}</b>\n"
          + "\n".join(added_summary),
          parse_mode="HTML",
          reply_markup=after_plan_added_kb(int(pid)),
      )
      return

    if step == "easy_edit_wait_price":
      raw_p = parse_clean_price(txt)
      if raw_p <= 0:
        return
      plid = state.get("edit_plid")
      conn = get_conn()
      cur = conn.cursor()
      cur.execute(
          """
                SELECT pl.id, p.name
                FROM plans pl
                JOIN products p ON pl.product_id = p.id
                WHERE pl.id = ?
                """,
          (plid,),
      )
      prow = cur.fetchone()
      new_price = 0.0
      if prow:
        new_price = (
            round_to_0_or_5(raw_p)
            if is_dolphin_product(prow["name"])
            else round_to_zero(raw_p)
        )
        cur.execute(
            "UPDATE plans SET price = ? WHERE id = ?",
            (new_price, plid),
        )
        conn.commit()
      conn.close()
      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      if prow:
        done = await message.answer(
            f"✅ নতুন দাম সেট হয়েছে: <b>৳{new_price:.0f}</b>",
            parse_mode="HTML",
        )
        await asyncio.sleep(3)
        await safe_delete_message(uid, done.message_id)
      return

    if step == "easy_offer_wait_text":
      if not txt:
        return
      plid = state.get("offer_plid")
      final_offer = "" if txt == "-" or txt.lower() == "skip" else txt
      conn = get_conn()
      cur = conn.cursor()
      cur.execute("UPDATE plans SET bonus = ? WHERE id = ?", (final_offer, plid))
      conn.commit()
      conn.close()
      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      done = await message.answer(
          f"✅ অফার আপডেট হয়েছে: <b>{html.escape(final_offer or 'Removed')}</b>",
          parse_mode="HTML",
      )
      await asyncio.sleep(3)
      await safe_delete_message(uid, done.message_id)
      return

    if step == "set_pay_num":
      if len(txt) < 4:
        return
      method = state.get("method", "bkash")
      update_payment_number(method, txt)
      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])
      label = "বিকাশ" if method == "bkash" else "নগদ"
      done = await message.answer(f"✅ {label} নম্বর আপডেট হয়েছে: {txt}")
      await asyncio.sleep(3)
      await safe_delete_message(uid, done.message_id)
      return

    elif step == "user_lookup":
      try:
        target_uid = int(txt)
      except ValueError:
        return

      conn = get_conn()
      cur = conn.cursor()
      cur.execute(
          "SELECT full_name, username, total_spent, joined_at FROM users WHERE"
          " user_id = ?",
          (target_uid,),
      )
      urow = cur.fetchone()
      if not urow:
        conn.close()
        await message.answer(
            "❌ এই User ID-এর কোনো ইউজার পাওয়া যায়নি।", parse_mode="HTML"
        )
        return

      cur.execute(
          """
                SELECT o.id, p.name AS pname, pl.duration, pl.price,
                       o.final_amount, o.sender_number, o.trx_id,
                       o.proof_photo_id, o.delivered_key, o.status, o.created_at
                FROM orders o
                JOIN plans pl ON o.plan_id = pl.id
                JOIN products p ON pl.product_id = p.id
                WHERE o.user_id = ?
                ORDER BY o.id DESC
                """,
          (target_uid,),
      )
      all_ords = cur.fetchall()
      conn.close()

      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])

      approved_ords = [o for o in all_ords if o["status"] == "approved"]
      pending_ords = [o for o in all_ords if o["status"] == "pending"]
      rejected_ords = [o for o in all_ords if o["status"] == "rejected"]

      calc_spent = sum(
          float(o["final_amount"] or o["price"] or 0.0) for o in approved_ords
      )
      sp = max(float(urow["total_spent"] or 0.0), calc_spent)
      vp = get_vip_discount_pct(sp)

      order_cards = []
      for o in all_ords[:10]:
        amt = float(o["final_amount"] or o["price"] or 0.0)
        method_lbl = detect_payment_method_label(
            o["sender_number"], o["trx_id"], o["proof_photo_id"]
        )
        st_bn = status_label(o["status"], "bn")
        key_line = (
            f"\n     🔑 <b>Key:</b> <code>{html.escape(o['delivered_key'])}</code>"
            if o["delivered_key"]
            else ""
        )
        order_cards.append(
            f"  • <b>#{o['id']}</b> | <b>{html.escape(o['pname'])}</b>"
            f" ({html.escape(o['duration'])}) — <b>৳{amt:.0f}</b>"
            f" [<b>{html.escape(st_bn)}</b>]\n"
            f"     💳 <b>মাধ্যম:</b> {html.escape(method_lbl)}\n"
            f"     🕒 <b>সময়:</b> <code>{html.escape(o['created_at'])}</code>{key_line}"
        )

      orders_section = (
          "\n\n".join(order_cards)
          if order_cards
          else "  • কোনো অর্ডার হিস্ট্রি নেই।"
      )

      await message.answer(
          f"🔎 <b>ইউজার প্রোফাইল ও ক্রয় হিস্ট্রি</b>\n"
          f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
          f"👤 <b>নাম:</b> <b>{html.escape(urow['full_name'])}</b>\n"
          f"🔹 <b>ইউজারনেম:</b> <code>{html.escape(urow['username'])}</code>\n"
          f"🆔 <b>User ID:</b> <code>{target_uid}</code>\n"
          f"📅 <b>জয়েন:</b> <code>{html.escape(urow['joined_at'])}</code>\n"
          f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
          f"🔑 <b>মোট কেনা পাসওয়ার্ড/অর্ডার:</b> <b>{len(approved_ords)} টি</b> (মোট রিকোয়েস্ট: {len(all_ords)} টি)\n"
          f"💰 <b>মোট খরচ:</b> <b>৳{sp:.0f}</b> | 👑 <b>VIP:</b> {vp:.0f}%\n"
          f"⏳ <b>পেন্ডিং:</b> {len(pending_ords)} | ❌ <b>রিজেক্টেড:</b> {len(rejected_ords)}\n"
          f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
          f"🧾 <b>অর্ডার ডিটেইলস:</b>\n{orders_section}",
          parse_mode="HTML",
      )
      return

    elif step == "wait_approve_key":
      if not txt:
        return
      key_val = (
          txt.split(maxsplit=1)[1].strip()
          if txt.lower().startswith("/key ")
          else txt
      )
      oid = state["order_id"]
      target_uid, pname, duration, user_lang = finalize_order_approval(
          oid, key_val
      )
      admin_states.pop(uid, None)

      await safe_delete_messages(
          uid, [message.message_id, prompt_id, state.get("alert_msg_id")]
      )

      if not target_uid:
        return

      try:
        await deliver_approved_key_message(
            target_uid, oid, pname, duration, key_val, user_lang
        )
      except Exception:
        pass
      return

    elif step == "broadcast":
      if not txt:
        return
      conn = get_conn()
      cur = conn.cursor()
      cur.execute("SELECT user_id FROM users")
      all_users = [r["user_id"] for r in cur.fetchall()]
      conn.close()
      admin_states.pop(uid, None)
      await safe_delete_messages(uid, [message.message_id, prompt_id])

      sent = 0
      for u_id in all_users:
        try:
          await bot.send_message(
              u_id,
              f"📢 <b>{html.escape(txt)}</b>",
              parse_mode="HTML",
              link_preview_options=NO_PREVIEW,
              reply_markup=update_channel_kb(),
          )
          sent += 1
        except Exception:
          pass
      done = await message.answer(
          f"✅ Broadcast পাঠানো হয়েছে {sent}/{len(all_users)} জন ইউজারকে।"
      )
      await asyncio.sleep(3)
      await safe_delete_message(uid, done.message_id)
      return

  if uid in user_states:
    ustate = user_states[uid]
    _, _, lang, _, _, _ = get_user_info(uid)
    step = ustate.get("step")

    if step == "wait_dolphin_reset_key":
      if not txt:
        return
      reset_prompt_id = ustate.get("reset_prompt_msg_id")
      user_states.pop(uid, None)

      await safe_delete_messages(uid, [message.message_id, reset_prompt_id])

      processing_msg = await message.answer(
          "⏳ রিসেট হচ্ছে..." if lang == "bn" else "⏳ Resetting..."
      )

      final_msg = (
          "❌ পাসওয়ার্ডটি ভুল বা খুঁজে পাওয়া যায়নি। সঠিক পাসওয়ার্ড দিয়ে আবার চেষ্টা করুন।"
          if lang == "bn"
          else (
              "❌ Password is incorrect or not found. Try again with a valid"
              " password."
          )
      )
      try:
        allowed, lock_msg = verify_key_ownership(txt, uid, lang)
        if not allowed:
          final_msg = lock_msg
        else:
          _, api_msg = await dolphin_reset_hwid_api(txt, lang)
          final_msg = api_msg
      finally:
        await safe_delete_message(uid, processing_msg.message_id)

      await message.answer(
          final_msg,
          reply_markup=back_to_reset_kb(lang),
      )
      return

    if step == "wait_proof":
      has_photo = bool(message.photo)
      valid_txt, cleaned_proof, is_mobile = is_valid_trx_or_proof_text(txt)
      order_msg_id = ustate.get("order_msg_id")

      if not has_photo and not valid_txt:
        oid = ustate["order_id"]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        user_states.pop(uid, None)
        await safe_delete_messages(uid, [message.message_id, order_msg_id])
        warn = await message.answer(
            f"❌ <b>অর্ডার #{oid} বাতিল হয়েছে।</b> সঠিক TrxID, ১১ ডিজিটের"
            f" নম্বর বা স্ক্রিনশট দিন।"
            if lang == "bn"
            else f"❌ <b>Order #{oid} cancelled.</b> Send a valid TrxID,"
            f" 11-digit number, or screenshot.",
            parse_mode="HTML",
        )
        await asyncio.sleep(4)
        await safe_delete_message(uid, warn.message_id)
        return

      if valid_txt and is_duplicate_proof(cleaned_proof, is_mobile=is_mobile):
        oid = ustate["order_id"]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        user_states.pop(uid, None)
        await safe_delete_messages(uid, [message.message_id, order_msg_id])
        warn = await message.answer(
            f"❌ <b>ডুপ্লিকেট TrxID!</b> অর্ডার #{oid} বাতিল করা হয়েছে।"
            if lang == "bn"
            else f"❌ <b>Duplicate TrxID!</b> Order #{oid} cancelled.",
            parse_mode="HTML",
        )
        await asyncio.sleep(4)
        await safe_delete_message(uid, warn.message_id)
        return

      oid = ustate["order_id"]
      pname = ustate["pname"]
      duration = ustate["duration"]
      final_price = float(ustate.get("final_price", ustate.get("price", 0.0)))
      disc_pct = float(ustate.get("discount_pct", 0.0))
      bonus = ustate.get("bonus", "")
      created = ustate.get("created_at", now_str())

      photo_id = message.photo[-1].file_id if has_photo else ""
      sender_num_val = cleaned_proof if (valid_txt and is_mobile) else ""
      trx_val = cleaned_proof if (valid_txt and not is_mobile) else ""

      conn = get_conn()
      cur = conn.cursor()
      cur.execute(
          """
                UPDATE orders
                SET sender_number = ?, trx_id = ?, proof_photo_id = ?, status = 'pending'
                WHERE id = ? AND user_id = ?
                """,
          (sender_num_val, trx_val, photo_id, oid, uid),
      )
      conn.commit()
      conn.close()

      user_states.pop(uid, None)

      await safe_delete_message(uid, order_msg_id)
      sub_msg = await message.answer(
          f"⏳ <b>অর্ডার #{oid}</b> — ভেরিফিকেশন চলছে..."
          if lang == "bn"
          else f"⏳ <b>Order #{oid}</b> — Verifying payment...",
          parse_mode="HTML",
      )

      full_name, username, _, total_spent, _, _ = get_user_info(uid)
      pay_method_lbl = detect_payment_method_label(
          sender_num_val, trx_val, photo_id
      )
      offer_line = (
          f"\n🎁 <b>অফার:</b> {html.escape(bonus)}" if bonus else ""
      )
      disc_line = (
          f"\n👑 <b>VIP ডিসকাউন্ট:</b> {disc_pct:.0f}% (Spent:"
          f" ৳{total_spent:.0f})"
          if disc_pct > 0
          else ""
      )
      shown_proof = sender_num_val or trx_val
      info_line = (
          f"\n🧾 <b>প্রুফ কোড/নম্বর:</b> <code>{html.escape(shown_proof)}</code>"
          if shown_proof
          else ""
      )
      photo_line = (
          "\n📸 <b>স্ক্রিনশট:</b> যুক্ত করা হয়েছে" if photo_id else ""
      )

      admin_alert = (
          f"⚡ <b>নতুন অর্ডার রিকোয়েস্ট — #{oid}</b>\n"
          f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
          f"👤 <b>কাস্টমার:</b> <b>{html.escape(full_name)}</b>"
          f" (<code>{html.escape(username)}</code>)\n"
          f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
          f"📦 <b>প্যানেল:</b> <b>{html.escape(pname)}</b>"
          f" (<code>{html.escape(duration)}</code>)\n"
          f"💵 <b>টাকার পরিমাণ:</b> <b>৳{final_price:.0f}</b>\n"
          f"💳 <b>পেমেন্ট মাধ্যম:</b> <b>{html.escape(pay_method_lbl)}</b>\n"
          f"🕒 <b>সময়:</b> <code>{html.escape(created)}</code>"
          f"{disc_line}{offer_line}{info_line}{photo_line}"
      )

      try:
        if photo_id:
          sent_adm = await bot.send_photo(
              ADMIN_ID,
              photo=photo_id,
              caption=admin_alert,
              parse_mode="HTML",
              reply_markup=order_approve_start_kb(oid),
          )
        else:
          sent_adm = await bot.send_message(
              ADMIN_ID,
              admin_alert,
              parse_mode="HTML",
              reply_markup=order_approve_start_kb(oid),
          )
        admin_states[ADMIN_ID] = {
            "step": "wait_approve_key",
            "order_id": oid,
            "alert_msg_id": sent_adm.message_id,
            "user_sub_msg_id": sub_msg.message_id,
        }
      except Exception as exc:
        logger.warning("Failed to send order alert to admin: %s", exc)
      return


@dp.errors()
async def on_error(event, exception):
  logger.exception("Unhandled error in dispatcher: %s", exception)
  return True


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
  await setup_bot_commands()
  logger.info("Bot is running on port %s...", PORT)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
