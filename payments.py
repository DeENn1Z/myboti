import json
import os
import time
import hashlib
import hmac
import logging
from typing import Dict, Any, Optional, List
from uuid import uuid4

from yookassa import Configuration, Payment
from yookassa.domain.request import PaymentRequest
from telegram import LabeledPrice
from telegram.ext import ContextTypes

from data_tools import (
    YookassaPayment, Product, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY,
    YOOKASSA_PAYMENTS_FILE, YOOKASSA_WEBHOOK_SECRET, load_products, 
    get_product, add_purchase, load_db, LAST_INVOICE, logger,
    check_rate_limit  # ← ТОЛЬКО ЭТО ОСТАВИТЬ
)

# Настройка ЮКассы - только если ключи есть
if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
else:
    logger.warning("Ключи ЮКассы не настроены. Оплата через ЮКассу недоступна.")

# Секретный ключ для хэширования payload инвойсов Telegram Stars
# Используем комбинацию токена бота и специального секрета для большей безопасности
STARS_PAYLOAD_SECRET = os.getenv("STARS_PAYLOAD_SECRET", "")
if not STARS_PAYLOAD_SECRET:
    # Если нет специального секрета, используем токен бота, но это менее безопасно
    from data_tools import BOT_TOKEN
    STARS_PAYLOAD_SECRET = BOT_TOKEN
    logger.warning("STARS_PAYLOAD_SECRET не установлен. Используется BOT_TOKEN.")

    # ИСПРАВЛЕНИЕ: функция для работы со словарями вместо объектов
def get_product_data(product):
    """Получает данные из товара, независимо от формата (объект или словарь)"""
    if isinstance(product, dict):
        return {
            'id': product.get('id'),
            'title': product.get('title', product.get('name', 'Товар')),
            'price_rub': product.get('price_rub', product.get('price', 0)),
            'price_stars': product.get('price_stars', 0),
            'days': product.get('days', 0),
            'description': product.get('description', ''),
            'deliver_text': product.get('deliver_text', ''),
            'deliver_url': product.get('deliver_url', '')
        }
    else:
        # Если это объект (старый формат)
        return {
            'id': getattr(product, 'id', None),
            'title': getattr(product, 'title', getattr(product, 'name', 'Товар')),
            'price_rub': getattr(product, 'price_rub', getattr(product, 'price', 0)),
            'price_stars': getattr(product, 'price_stars', 0),
            'days': getattr(product, 'days', 0),
            'description': getattr(product, 'description', ''),
            'deliver_text': getattr(product, 'deliver_text', ''),
            'deliver_url': getattr(product, 'deliver_url', '')
        }

# ---------- ФУНКЦИИ ЮКАССЫ ----------
def load_yookassa_payments() -> Dict[str, Dict[str, Any]]:
    """Загружает платежи ЮКассы с проверкой целостности данных"""
    if not os.path.exists(YOOKASSA_PAYMENTS_FILE):
        return {}
    
    try:
        # Проверяем размер файла (не более 10MB)
        if os.path.getsize(YOOKASSA_PAYMENTS_FILE) > 10 * 1024 * 1024:
            logger.error(f"Файл платежей ЮКассы слишком большой: {YOOKASSA_PAYMENTS_FILE}")
            return {}
            
        with open(YOOKASSA_PAYMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Проверяем структуру данных
        if not isinstance(data, dict):
            logger.error(f"Некорректный формат файла платежей: {YOOKASSA_PAYMENTS_FILE}")
            return {}
            
        return data
        
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка JSON в файле платежей ЮКассы: {e}")
        # Создаем резервную копию поврежденного файла
        backup_name = f"{YOOKASSA_PAYMENTS_FILE}.backup.{int(time.time())}"
        try:
            os.rename(YOOKASSA_PAYMENTS_FILE, backup_name)
            logger.info(f"Создана резервная копия поврежденного файла: {backup_name}")
        except:
            pass
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки платежей ЮКассы: {e}")
        return {}


def save_yookassa_payments(payments: Dict[str, Dict[str, Any]]) -> None:
    """Сохраняет платежи ЮКассы с атомарной записью"""
    try:
        # Проверяем данные перед сохранением
        if not isinstance(payments, dict):
            logger.error("Попытка сохранить некорректные данные платежей")
            return
            
        # Ограничиваем размер данных (примерно 10000 платежей)
        if len(payments) > 10000:
            logger.warning(f"Слишком много платежей в памяти: {len(payments)}")
            # Оставляем только последние 5000 платежей
            sorted_items = sorted(payments.items(), key=lambda x: x[1].get('created_at', 0))
            payments = dict(sorted_items[-5000:])
        
        tmp = f"{YOOKASSA_PAYMENTS_FILE}.{int(time.time())}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payments, f, ensure_ascii=False, indent=2, default=str)
        
        # Атомарная замена файла
        os.replace(tmp, YOOKASSA_PAYMENTS_FILE)
        
    except Exception as e:
        logger.error(f"Ошибка сохранения платежей ЮКассы: {e}")
        # Пытаемся удалить временный файл
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except:
            pass


def create_yookassa_payment(user_id: int, product: Product, message_id: int = None) -> Optional[YookassaPayment]:
    """Создает защищенный платеж через API ЮКассы"""
    # Проверяем rate limit
    if not check_rate_limit(user_id, "create_yookassa_payment", limit=3, window=60):
        logger.warning(f"Rate limit для создания платежа ЮКассы user_id={user_id}")
        return None
    
    # Проверяем доступность ЮКассы
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        logger.error("Ключи ЮКассы не настроены")
        return None
    
    try:
        # Валидация продукта
        if product.price_rub <= 0 or product.price_rub > 10000000:  # Максимум 10 млн рублей
            logger.error(f"Некорректная цена товара: {product.price_rub}")
            return None
        
        amount_rub = product.price_rub
        
        # Создаем уникальный idempotence_key
        idempotence_key = str(uuid4())
        
        # Описание платежа (обезопасенное)
        description = f"Покупка товара: {product.title[:100]}"
        
        # Создаем защищенный запрос на платеж
        payment_request = PaymentRequest(
            amount={
                "value": f"{amount_rub:.2f}",
                "currency": "RUB"
            },
            capture=True,
            confirmation={
                "type": "redirect",
                "return_url": "https://t.me/"  # Безопасный возврат
            },
            description=description[:128],
            metadata={
                "user_id": str(user_id),
                "product_id": product.id,
                "bot_message_id": str(message_id),
                "timestamp": str(int(time.time())),
                "hash": generate_payment_hash(user_id, product.id, amount_rub)
            }
        )
        
        # Создаем платеж через API ЮКассы
        payment_response = Payment.create(payment_request, idempotence_key)
        
        # Валидируем ответ от ЮКассы
        if not payment_response or not hasattr(payment_response, 'id'):
            logger.error("Некорректный ответ от API ЮКассы")
            return None
        
        # Создаем объект платежа
        payment = YookassaPayment(
            payment_id=payment_response.id,
            user_id=user_id,
            product_id=product.id,
            amount=amount_rub,
            status=payment_response.status,
            created_at=int(time.time()),
            payment_url=payment_response.confirmation.confirmation_url,
            message_id=message_id,
            description=description
        )
        
        # Сохраняем в файл с дополнительной проверкой
        payments = load_yookassa_payments()
        
        # Проверяем, не существует ли уже такой платеж
        if payment.payment_id in payments:
            logger.warning(f"Платеж {payment.payment_id} уже существует")
            # Проверяем, не попытка ли это повторного использования
            existing_payment = payments[payment.payment_id]
            if existing_payment.get('user_id') != user_id:
                logger.error(f"Попытка переиспользования платежа {payment.payment_id} другим пользователем")
                return None
        
        payments[payment.payment_id] = {
            "payment_id": payment.payment_id,
            "user_id": payment.user_id,
            "product_id": payment.product_id,
            "amount": payment.amount,
            "status": payment.status,
            "created_at": payment.created_at,
            "payment_url": payment.payment_url,
            "message_id": payment.message_id,
            "description": payment.description,
            "metadata": {
                "user_id": str(user_id),
                "product_id": product.id,
                "bot_message_id": str(message_id),
                "timestamp": str(int(time.time())),
                "hash": generate_payment_hash(user_id, product.id, amount_rub)
            }
        }
        
        save_yookassa_payments(payments)
        
        logger.info(f"Создан защищенный платеж ЮКассы: {payment.payment_id[:8]}... для user_id: {user_id}")
        return payment
        
    except Exception as e:
        logger.error(f"Ошибка создания защищенного платежа ЮКассы: {e}", exc_info=True)
        return None


def update_yookassa_payment_status(payment_id: str, status: str, metadata: dict = None) -> bool:
    """Обновляет статус платежа ЮКассы с проверками"""
    if not payment_id or len(payment_id) > 100:
        logger.error(f"Некорректный payment_id: {payment_id}")
        return False
    
    try:
        payments = load_yookassa_payments()
        
        if payment_id not in payments:
            logger.error(f"Платеж {payment_id} не найден в локальной БД")
            return False
        
        # Проверяем, что статус допустимый
        valid_statuses = ["pending", "waiting_for_capture", "succeeded", "canceled"]
        if status not in valid_statuses:
            logger.error(f"Некорректный статус платежа: {status}")
            return False
        
        payments[payment_id]["status"] = status
        
        # Обновляем метаданные если они предоставлены
        if metadata:
            # Фильтруем метаданные (только разрешенные ключи)
            allowed_keys = {"user_id", "product_id", "bot_message_id", "timestamp", "hash"}
            filtered_metadata = {k: v for k, v in metadata.items() if k in allowed_keys}
            payments[payment_id].setdefault("metadata", {})
            payments[payment_id]["metadata"].update(filtered_metadata)
        
        save_yookassa_payments(payments)
        
        # Логируем изменение статуса
        logger.info(f"Статус платежа {payment_id[:8]}... обновлен на: {status}")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обновления статуса платежа {payment_id}: {e}")
        return False


def get_yookassa_payment(payment_id: str) -> Optional[Dict[str, Any]]:
    """Получает информацию о платеже ЮКассы с проверкой безопасности"""
    if not payment_id or len(payment_id) > 100:
        logger.error(f"Некорректный payment_id: {payment_id}")
        return None
    
    try:
        # Сначала проверяем локальную БД
        payments = load_yookassa_payments()
        
        if payment_id in payments:
            payment_data = payments[payment_id]
            
            # Проверяем целостность данных
            if not validate_payment_data(payment_data):
                logger.warning(f"Данные платежа {payment_id} повреждены")
                return None
            
            # Проверяем актуальный статус через API (если есть ключи)
            if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
                try:
                    payment_response = Payment.find_one(payment_id)
                    
                    # Обновляем статус если он изменился
                    if payment_data.get("status") != payment_response.status:
                        payment_data["status"] = payment_response.status
                        payments[payment_id] = payment_data
                        save_yookassa_payments(payments)
                        logger.info(f"Обновлен статус платежа {payment_id[:8]}...: {payment_response.status}")
                    
                    # Добавляем данные из API к локальным данным
                    payment_data["api_data"] = {
                        "paid": payment_response.paid,
                        "refundable": payment_response.refundable,
                        "test": payment_response.test,
                        "expires_at": payment_response.expires_at
                    }
                    
                except Exception as api_error:
                    logger.warning(f"Не удалось получить статус платежа {payment_id} из API: {api_error}")
            
            return payment_data
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка получения платежа {payment_id}: {e}")
        return None


def validate_payment_data(payment_data: Dict[str, Any]) -> bool:
    """Проверяет целостность данных платежа"""
    required_fields = ["payment_id", "user_id", "product_id", "amount", "status", "created_at"]
    
    for field in required_fields:
        if field not in payment_data:
            return False
    
    # Проверяем типы данных
    try:
        user_id = payment_data["user_id"]
        if not isinstance(user_id, int) and not str(user_id).isdigit():
            return False
        
        amount = payment_data["amount"]
        if not isinstance(amount, (int, float)) or amount <= 0:
            return False
        
        created_at = payment_data["created_at"]
        if not isinstance(created_at, (int, float)) or created_at <= 0:
            return False
        
        # Проверяем хэш если есть
        metadata = payment_data.get("metadata", {})
        if metadata.get("hash"):
            expected_hash = generate_payment_hash(
                int(user_id),
                str(payment_data["product_id"]),
                float(amount)
            )
            if metadata["hash"] != expected_hash:
                logger.warning(f"Неверный хэш платежа {payment_data.get('payment_id')}")
                return False
                
    except Exception as e:
        logger.error(f"Ошибка валидации данных платежа: {e}")
        return False
    
    return True


def get_user_pending_yookassa_payments(user_id: int) -> List[Dict[str, Any]]:
    """Получает ожидающие платежи пользователя"""
    payments = load_yookassa_payments()
    user_payments = []
    
    for payment_id, payment_data in payments.items():
        # Проверяем принадлежность платежа пользователю
        if payment_data.get("user_id") == user_id and payment_data.get("status") in ["pending", "waiting_for_capture"]:
            # Проверяем целостность данных
            if validate_payment_data(payment_data):
                user_payments.append(payment_data)
    
    return user_payments


def check_yookassa_payment_status(payment_id: str) -> Optional[str]:
    """Проверяет статус платежа через API ЮКассы с защитой"""
    if not payment_id or len(payment_id) > 100:
        logger.error(f"Некорректный payment_id: {payment_id}")
        return None
    
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        logger.error("Ключи ЮКассы не настроены")
        return None
    
    try:
        payment_response = Payment.find_one(payment_id)
        return payment_response.status
    except Exception as e:
        logger.error(f"Ошибка проверки статуса платежа {payment_id}: {e}")
        return None


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОПЛАТЫ ----------
async def delete_last_invoice(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Удаляет последний инвойс с защитой от ошибок"""
    info = LAST_INVOICE.get(user_id)
    if not info:
        return
    
    chat_id, msg_id = info
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        LAST_INVOICE.pop(user_id, None)
    except Exception as e:
        logger.error(f"Ошибка удаления инвойса для user_id={user_id}: {e}")


def generate_payment_hash(user_id: int, product_id: str, amount: float) -> str:
    """Генерирует хэш для проверки целостности платежа"""
    data = f"{user_id}:{product_id}:{amount}:{int(time.time())}"
    return hashlib.sha256(f"{data}:{STARS_PAYLOAD_SECRET}".encode()).hexdigest()[:16]


def create_stars_invoice_payload(user_id: int, product: Product) -> tuple:
    """
    Создает защищенные данные для инвойса Telegram Stars.
    
    Payload формат: v=1&p=PRODUCT_ID&u=USER_ID&t=TIMESTAMP&h=HMAC_SHA256
    """
    prices = [LabeledPrice(label=(product.title[:32] or "Товар"), amount=int(product.price_stars))]
    
    # Генерируем timestamp и nonce для защиты от replay-атак
    timestamp = int(time.time())
    nonce = hashlib.md5(str(uuid4()).encode()).hexdigest()[:8]
    
    # Создаем строку для хэширования
    data_string = f"v=1&p={product.id}&u={user_id}&t={timestamp}&n={nonce}"
    
    # Генерируем HMAC-SHA256 хэш
    hash_obj = hmac.new(
        key=STARS_PAYLOAD_SECRET.encode('utf-8'),
        msg=data_string.encode('utf-8'),
        digestmod=hashlib.sha256
    )
    signature = hash_obj.hexdigest()
    
    # Формируем защищенный payload
    payload = f"{data_string}&h={signature}"
    
    # Логируем создание инвойса (без sensitive данных)
    logger.info(f"Создан защищенный инвойс Stars для user_id={user_id}, product_id={product.id}")
    
    return prices, payload


def verify_stars_invoice_payload(payload: str, user_id: int) -> Optional[str]:
    """
    Проверяет валидность защищенного payload инвойса Telegram Stars.
    Возвращает product_id если проверка пройдена, иначе None.
    """
    if not payload:
        logger.warning("Пустой payload")
        return None
    
    try:
        # Парсим параметры из payload
        params = {}
        for part in payload.split('&'):
            if '=' in part:
                key, value = part.split('=', 1)
                params[key] = value
        
        # Проверяем наличие обязательных полей
        required_fields = ["v", "p", "u", "t", "n", "h"]
        for field in required_fields:
            if field not in params:
                logger.warning(f"Отсутствует обязательное поле {field} в payload")
                return None
        
        # Проверяем версию payload
        if params["v"] != "1":
            logger.warning(f"Неподдерживаемая версия payload: {params['v']}")
            return None
        
        # Проверяем, что payload предназначен этому пользователю
        if int(params["u"]) != user_id:
            logger.warning(f"Несоответствие user_id в payload: ожидалось {user_id}, получено {params['u']}")
            return None
        
        # Проверяем timestamp (не старше 1 часа)
        timestamp = int(params["t"])
        current_time = int(time.time())
        if timestamp < current_time - 3600 or timestamp > current_time + 300:
            logger.warning(f"Просроченный или неверный timestamp: {timestamp}, текущее: {current_time}")
            return None
        
        # Извлекаем подпись
        received_hash = params.pop('h')
        
        # Восстанавливаем исходную строку для проверки (сортировка для консистентности)
        data_parts = []
        for key in sorted(params.keys()):
            if key != 'h':  # Уже извлекли
                data_parts.append(f"{key}={params[key]}")
        data_string = '&'.join(data_parts)
        
        # Генерируем HMAC-SHA256 для проверки
        hash_obj = hmac.new(
            key=STARS_PAYLOAD_SECRET.encode('utf-8'),
            msg=data_string.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        expected_hash = hash_obj.hexdigest()
        
        # Сравниваем хэши безопасным способом
        if hmac.compare_digest(received_hash, expected_hash):
            logger.info(f"Payload успешно проверен для user_id={user_id}, product_id={params['p']}")
            return params['p']
        else:
            logger.warning(f"Неверная подпись payload для user_id={user_id}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка проверки payload: {e}", exc_info=True)
        return None


def verify_yookassa_webhook(body: bytes, signature: str) -> bool:
    """
    Проверяет подпись вебхука от ЮКассы.
    Для использования нужно настроить вебхуки в админке ЮКассы.
    """
    if not YOOKASSA_WEBHOOK_SECRET:
        logger.error("YOOKASSA_WEBHOOK_SECRET не настроен")
        return False
    
    if not signature or not signature.startswith("sha256="):
        logger.error("Неверный формат подписи вебхука")
        return False
    
    try:
        expected_signature = signature[7:]  # Убираем 'sha256='
        
        # Создаем HMAC с секретным ключом
        hmac_obj = hmac.new(
            key=YOOKASSA_WEBHOOK_SECRET.encode('utf-8'),
            msg=body,
            digestmod=hashlib.sha256
        )
        
        calculated_signature = hmac_obj.hexdigest()
        
        # Сравниваем подписи безопасным способом
        return hmac.compare_digest(expected_signature, calculated_signature)
        
    except Exception as e:
        logger.error(f"Ошибка проверки подписи вебхука: {e}")
        return False