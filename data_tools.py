import json
import os
import time
import logging
import html
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

# ====== КОНФИГУРАЦИЯ ======
# ВАЖНО: Используйте переменные окружения! Не храните ключи в коде!
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PRODUCTS_FILE = "products.json"
DB_FILE = "db.json"
YOOKASSA_PAYMENTS_FILE = "yookassa_payments.json"

# ID администраторов через переменные окружения
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "7784754900")
ADMIN_IDS = set(map(int, ADMIN_IDS_STR.split(",")))

# Ограничения на размер данных
MAX_ID_LENGTH = 50
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 2000
MAX_DELIVER_TEXT_LENGTH = 5000
MAX_DELIVER_URL_LENGTH = 500
MAX_PRICE_STARS = 1000000
MIN_PRICE_STARS = 1
MAX_PRICE_RUB = 10000000
MIN_PRICE_RUB = 1

# Настройки ЮКассы из переменных окружения
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_WEBHOOK_SECRET = os.getenv("YOOKASSA_WEBHOOK_SECRET", "")

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен. Установите переменную окружения BOT_TOKEN")
if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
    logger.warning("Ключи ЮКассы не установлены. Оплата через ЮКассу не будет работать")

# Глобальные состояния
WAITING_PROMO: Dict[int, bool] = {}
ADMIN_STATE: Dict[int, Dict[str, Any]] = {}
LAST_INVOICE: Dict[int, Tuple[int, int]] = {}
# Rate limiting
RATE_LIMIT: Dict[int, Dict[str, Any]] = {}


@dataclass
class Product:
    id: str
    title: str
    description: str
    price_stars: int
    deliver_text: str
    deliver_url: str
    price_rub: Optional[int] = None
    
    def __post_init__(self):
        if self.price_rub is None:
            self.price_rub = self.price_stars * 10
        elif self.price_rub == 0:
            self.price_rub = self.price_stars * 10


@dataclass
class YookassaPayment:
    payment_id: str
    user_id: int
    product_id: str
    amount: float
    status: str
    created_at: int
    payment_url: str
    message_id: Optional[int] = None
    description: Optional[str] = None


# ---------- РАБОТА С ТОВАРАМИ ----------
def load_products() -> List[Product]:
    if not os.path.exists(PRODUCTS_FILE):
        return []
    try:
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Ограничение размера файла
        if len(json.dumps(raw)) > 10 * 1024 * 1024:  # 10MB
            logger.error("Файл товаров слишком большой")
            return []
            
        products = []
        for p in raw:
            if "price_rub" not in p:
                p["price_rub"] = p.get("price_stars", 0) * 10
            products.append(Product(**p))
        return products
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Ошибка загрузки товаров: {e}")
        return []


def save_products(products: List[Product]) -> None:
    try:
        tmp = PRODUCTS_FILE + ".tmp"
        raw = [p.__dict__ for p in products]
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PRODUCTS_FILE)
    except Exception as e:
        logger.error(f"Ошибка сохранения товаров: {e}")


def get_product(products: List[Product], product_id: str) -> Optional[Product]:
    for p in products:
        if p.id == product_id:
            return p
    return None


# ---------- БАЗА ДАННЫХ (DB) ----------
def _default_db() -> Dict[str, Any]:
    return {"payments_processed": [], "purchases": {}}


def load_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return _default_db()
    try:
        # Проверка размера файла перед загрузкой
        file_size = os.path.getsize(DB_FILE)
        if file_size > 50 * 1024 * 1024:  # 50MB
            logger.error(f"Файл БД слишком большой: {file_size} байт")
            return _default_db()
            
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_db()
        data.setdefault("payments_processed", [])
        data.setdefault("purchases", {})
        return data
    except Exception as e:
        logger.error(f"Ошибка загрузки БД: {e}")
        return _default_db()


def save_db(data: Dict[str, Any]) -> None:
    try:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_FILE)
    except Exception as e:
        logger.error(f"Ошибка сохранения БД: {e}")


def reset_db() -> None:
    save_db(_default_db())


def mark_payment_processed(charge_id: str) -> bool:
    db = load_db()
    processed = db.get("payments_processed", [])
    if charge_id in processed:
        return False
    processed.append(charge_id)
    db["payments_processed"] = processed
    save_db(db)
    return True


def add_purchase(user_id: int, product: Product, payment_method: str = "stars", yookassa_id: str = None) -> None:
    db = load_db()
    purchases = db.get("purchases", {})
    uid = str(user_id)
    purchases.setdefault(uid, [])
    
    purchase_data = {
        "product_id": product.id,
        "title": product.title,
        "stars": int(product.price_stars),
        "rub": int(product.price_rub),
        "payment_method": payment_method,
        "ts": int(time.time()),
    }
    
    if yookassa_id:
        purchase_data["yookassa_id"] = yookassa_id
    
    purchases[uid].append(purchase_data)
    db["purchases"] = purchases
    save_db(db)


def get_all_purchases_flat() -> List[Tuple[str, Dict[str, Any]]]:
    db = load_db()
    out: List[Tuple[str, Dict[str, Any]]] = []
    purchases = db.get("purchases", {})
    if isinstance(purchases, dict):
        for uid, items in purchases.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        out.append((uid, it))
    out.sort(key=lambda x: int(x[1].get("ts", 0)))
    return out


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def fmt_dt(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return str(ts)


def validate_text_length(text: str, field_name: str, max_length: int) -> Optional[str]:
    if len(text) > max_length:
        return f"❌ Слишком длинный {field_name}. Максимум {max_length} символов."
    return None


def calculate_stars_from_rub(rub: int) -> int:
    stars = rub / 10
    return int(stars) if stars.is_integer() else int(stars) + 1


def calculate_rub_from_stars(stars: int) -> int:
    return stars * 10


# ---------- RATE LIMITING ----------
def check_rate_limit(user_id: int, action: str, limit: int = 5, window: int = 60) -> bool:
    """Проверяет rate limit для пользователя"""
    current_time = time.time()
    
    if user_id not in RATE_LIMIT:
        RATE_LIMIT[user_id] = {}
    
    if action not in RATE_LIMIT[user_id]:
        RATE_LIMIT[user_id][action] = {"count": 1, "first_time": current_time}
        return True
    
    user_actions = RATE_LIMIT[user_id][action]
    
    # Сброс если прошло больше window секунд
    if current_time - user_actions["first_time"] > window:
        user_actions["count"] = 1
        user_actions["first_time"] = current_time
        return True
    
    # Проверка лимита
    if user_actions["count"] >= limit:
        return False
    
    user_actions["count"] += 1
    return True