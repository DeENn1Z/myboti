import html
import logging
import os
import time
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton 
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from data_tools import (
    is_admin, ADMIN_STATE, WAITING_PROMO, load_products, save_products, 
    get_product, get_all_purchases_flat, reset_db, fmt_dt, validate_text_length,
    MAX_ID_LENGTH, MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH, MAX_DELIVER_TEXT_LENGTH,
    MAX_DELIVER_URL_LENGTH, MAX_PRICE_STARS, MIN_PRICE_STARS, MAX_PRICE_RUB, MIN_PRICE_RUB,
    Product, YOOKASSA_PAYMENTS_FILE, check_rate_limit, ADMIN_IDS
)
from keyboards import admin_menu_kb, edit_select_product_kb
from payments import load_yookassa_payments, get_yookassa_payment

logger = logging.getLogger(__name__)

# Словарь для защиты от CSRF (простейшая реализация)
ADMIN_CSRF_TOKENS = {}


def generate_csrf_token(user_id: int) -> str:
    """Генерирует CSRF токен для защиты от подделки запросов"""
    import hashlib
    timestamp = int(time.time())
    token = hashlib.sha256(f"{user_id}:{timestamp}:{os.urandom(16).hex()}".encode()).hexdigest()[:32]
    ADMIN_CSRF_TOKENS[user_id] = {"token": token, "timestamp": timestamp}
    return token


def verify_csrf_token(user_id: int, token: str) -> bool:
    """Проверяет CSRF токен"""
    if user_id not in ADMIN_CSRF_TOKENS:
        return False
    
    stored = ADMIN_CSRF_TOKENS[user_id]
    
    # Токен действует 30 минут
    if time.time() - stored["timestamp"] > 1800:
        del ADMIN_CSRF_TOKENS[user_id]
        return False
    
    # Сравниваем токены безопасным способом
    import hmac
    return hmac.compare_digest(token, stored["token"])


def extract_admin_action_and_csrf(data: str) -> tuple:
    """Извлекает действие и CSRF токен из callback_data"""
    if ":" not in data:
        return data, None
    
    parts = data.split(":", 2)
    if len(parts) == 3 and parts[0] == "admin":
        return f"admin:{parts[1]}", parts[2]
    elif len(parts) == 2 and parts[0] == "admin":
        return data, None
    
    return data, None


# ---------- КОМАНДЫ АДМИНИСТРАТОРА ----------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Защищенная команда администратора"""
    uid = update.effective_user.id
    
    # Проверка rate limit
    if not check_rate_limit(uid, "admin_command", limit=5, window=300):
        await update.message.reply_text("⚠️ Слишком много запросов. Подождите 5 минут.")
        return
    
    if not is_admin(uid):
        logger.warning(f"Попытка доступа к админке от неавторизованного user_id={uid}")
        await update.message.reply_text("⛔ Нет доступа.")
        return
    
    # Генерируем CSRF токен
    csrf_token = generate_csrf_token(uid)
    
    # Очищаем состояния
    ADMIN_STATE.pop(uid, None)
    WAITING_PROMO.pop(uid, None)
    
    logger.info(f"Админка открыта user_id={uid}")
    await update.message.reply_text(
        f"🔧 <b>Панель администратора</b>\n\n"
        f"🆔 Ваш ID: <code>{uid}</code>\n"
        f"👥 Админов в системе: {len(ADMIN_IDS)}\n\n"
        f"<i>Токен безопасности: {csrf_token[:8]}...</i>",
        reply_markup=admin_menu_kb(csrf_token),
        parse_mode="HTML"
    )


async def on_admin_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Защищенный обработчик кликов в админке"""
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    
    # Проверка доступа
    if not is_admin(uid):
        logger.warning(f"Попытка доступа к админке от неавторизованного user_id={uid}")
        await query.answer("Нет доступа", show_alert=True)
        return
    
    # Проверка rate limit
    if not check_rate_limit(uid, "admin_actions", limit=20, window=60):
        await query.answer("Слишком много действий. Подождите минуту.", show_alert=True)
        return
    
    action_data = query.data
    
    # Извлекаем действие и CSRF токен
    action, csrf_token = extract_admin_action_and_csrf(action_data)
    
    # Проверяем CSRF токен для важных действий
    if csrf_token and not verify_csrf_token(uid, csrf_token):
        logger.warning(f"Неверный CSRF токен от user_id={uid}")
        await query.answer("Ошибка безопасности. Обновите страницу.", show_alert=True)
        return
    
    WAITING_PROMO.pop(uid, None)
    
    # Обработка действий
    if action == "admin:products":
        await handle_admin_products(query, uid)
        return
        
    if action == "admin:stats":
        await handle_admin_stats(query, uid)
        return
        
    if action == "admin:last_purchases":
        await handle_admin_last_purchases(query, uid)
        return
        
    if action == "admin:yookassa_payments":
        await handle_admin_yookassa_payments(query, uid)
        return
        
    if action == "admin:reset_stats":
        await handle_admin_reset_stats(query, uid)
        return
        
    if action == "admin:add_product":
        await handle_admin_add_product(query, uid)
        return
        
    if action == "admin:delete_product":
        await handle_admin_delete_product(query, uid)
        return
        
    if action == "admin:edit_product":
        await handle_admin_edit_product(query, uid)
        return
        
    if action == "admin:back":
        csrf_token = generate_csrf_token(uid)
        try:
            await query.edit_message_text(
                f"🔧 <b>Панель администратора</b>\n\n"
                f"🆔 Ваш ID: <code>{uid}</code>",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin:back: {e}")
            await query.message.reply_text(
                f"🔧 Панель администратора (ID: {uid})",
                reply_markup=admin_menu_kb(csrf_token)
            )
        return


async def handle_admin_products(query, uid):
    """Обработчик просмотра товаров"""
    products = load_products()
    if not products:
        try:
            await query.edit_message_text(
                "📦 <b>Товаров пока нет</b>\n\n"
                "Используйте «➕ Добавить товар» для создания первого товара.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid)),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin:products: {e}")
            await query.message.reply_text(
                "📦 Товаров пока нет.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid))
            )
        return
    
    lines = ["📦 <b>Список товаров:</b>"]
    for p in products[:50]:  # Ограничение 50 товаров
        lines.append(f"• <code>{html.escape(p.id)}</code> — {html.escape(p.title)} — {p.price_stars}⭐ / {p.price_rub}₽")
    
    if len(products) > 50:
        lines.append(f"\n... и еще {len(products) - 50} товаров")
    
    lines.append(f"\n<b>Всего товаров:</b> {len(products)}")
    
    try:
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:products (edit): {e}")
        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )


async def handle_admin_stats(query, uid):
    """Обработчик статистики"""
    allp = get_all_purchases_flat()
    
    total_orders = len(allp)
    total_stars = sum(int(it.get("stars", 0)) for _, it in allp)
    total_rub = sum(int(it.get("rub", it.get("stars", 0) * 10)) for _, it in allp)
    
    # Статистика по методам оплаты
    payment_methods = {}
    for _, it in allp:
        method = it.get("payment_method", "stars")
        payment_methods[method] = payment_methods.get(method, 0) + 1
    
    payment_stats_lines = []
    for method, count in payment_methods.items():
        method_name = "⭐ Stars" if method == "stars" else "💰 ЮКасса" if method == "yookassa" else method
        payment_stats_lines.append(f"• {method_name}: {count}")
    
    payment_stats = "\n".join(payment_stats_lines) if payment_stats_lines else "• Нет данных"
    
    # Статистика по ЮКассе
    yookassa_payments_data = load_yookassa_payments()
    successful_yookassa = sum(1 for p in yookassa_payments_data.values() if p.get("status") == "succeeded")
    pending_yookassa = sum(1 for p in yookassa_payments_data.values() if p.get("status") in ["pending", "waiting_for_capture"])
    total_yookassa_amount = sum(p.get("amount", 0) for p in yookassa_payments_data.values() if p.get("status") == "succeeded")
    
    text = (
        "📊 <b>Статистика магазина</b>\n\n"
        f"🛒 <b>Покупки:</b>\n"
        f"• Всего покупок: <b>{total_orders}</b>\n"
        f"• Получено звезд: <b>{total_stars}⭐</b>\n"
        f"• Получено рублей: <b>{total_rub}₽</b>\n\n"
        f"💳 <b>Методы оплаты:</b>\n"
        f"{payment_stats}\n\n"
        f"💰 <b>ЮКасса:</b>\n"
        f"• Успешных платежей: <b>{successful_yookassa}</b>\n"
        f"• В ожидании: <b>{pending_yookassa}</b>\n"
        f"• Общая сумма: <b>{total_yookassa_amount:.2f}₽</b>"
    )
    
    try:
        await query.edit_message_text(
            text,
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:stats (edit): {e}")
        await query.message.reply_text(
            text,
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )


async def handle_admin_last_purchases(query, uid):
    """Обработчик последних покупок"""
    allp = get_all_purchases_flat()
    if not allp:
        try:
            await query.edit_message_text(
                "📜 <b>Покупок пока нет</b>\n\n"
                "Здесь будут отображаться последние покупки пользователей.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid)),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin:last_purchases: {e}")
            await query.message.reply_text(
                "📜 Покупок пока нет.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid))
            )
        return
    
    last = allp[-20:]  # Последние 20 покупок
    lines = ["📜 <b>Последние покупки (20):</b>"]
    
    for user_id_str, it in last:
        method = it.get("payment_method", "stars")
        method_icon = "⭐" if method == "stars" else "💰"
        yookassa_id = it.get("yookassa_id", "")
        
        if yookassa_id:
            yookassa_id_short = f" (ID: {yookassa_id[:8]}...)"
        else:
            yookassa_id_short = ""
        
        # Безопасное отображение данных
        title = html.escape(it.get('title', 'Без названия')[:30])
        timestamp = it.get('ts', 0)
        
        lines.append(
            f"• {fmt_dt(timestamp)} | 👤 {user_id_str} | "
            f"{method_icon} {title} — {it.get('stars')}⭐ / {it.get('rub', it.get('stars', 0)*10)}₽{yookassa_id_short}"
        )
    
    lines.append(f"\n<b>Всего покупок в истории:</b> {len(allp)}")
    
    try:
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:last_purchases (edit): {e}")
        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )


async def handle_admin_yookassa_payments(query, uid):
    """Обработчик платежей ЮКассы"""
    payments = load_yookassa_payments()
    if not payments:
        try:
            await query.edit_message_text(
                "💳 <b>Платежей ЮКассы пока нет</b>\n\n"
                "Здесь будут отображаться все платежи через ЮКассу.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid)),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin:yookassa_payments: {e}")
            await query.message.reply_text(
                "💳 Платежей ЮКассы пока нет.",
                reply_markup=admin_menu_kb(generate_csrf_token(uid))
            )
        return
    
    lines = ["💳 <b>Платежи ЮКассы (последние 20):</b>"]
    status_icons = {
        "pending": "⏳",
        "waiting_for_capture": "⏳",
        "succeeded": "✅",
        "canceled": "❌"
    }
    
    # Сортируем по времени создания
    sorted_payments = sorted(payments.items(), key=lambda x: x[1].get('created_at', 0), reverse=True)
    
    for payment_id, p in sorted_payments[:20]:
        status = p.get("status", "unknown")
        icon = status_icons.get(status, "❓")
        
        product = get_product(load_products(), p.get("product_id", ""))
        if product:
            product_title = html.escape(product.title[:20])
        else:
            product_title = html.escape(p.get("product_id", "?")[:20])
        
        user_id = p.get('user_id', '?')
        amount = p.get('amount', 0)
        created_at = fmt_dt(p.get('created_at', 0))
        
        lines.append(
            f"• {icon} {created_at} | 👤 {user_id} | "
            f"{product_title} | {amount}₽ | {status} | ID: {payment_id[:8]}..."
        )
    
    lines.append(f"\n<b>Всего платежей:</b> {len(payments)}")
    
    successful = sum(1 for p in payments.values() if p.get("status") == "succeeded")
    pending = sum(1 for p in payments.values() if p.get("status") in ["pending", "waiting_for_capture"])
    canceled = sum(1 for p in payments.values() if p.get("status") == "canceled")
    
    lines.append(f"✅ <b>Успешных:</b> {successful}")
    lines.append(f"⏳ <b>В ожидании:</b> {pending}")
    lines.append(f"❌ <b>Отменено:</b> {canceled}")
    
    total_amount = sum(p.get("amount", 0) for p in payments.values() if p.get("status") == "succeeded")
    lines.append(f"💰 <b>Общая сумма:</b> {total_amount:.2f}₽")
    
    try:
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:yookassa_payments (edit): {e}")
        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_menu_kb(generate_csrf_token(uid)),
            parse_mode="HTML"
        )


async def handle_admin_reset_stats(query, uid):
    """Обработчик сброса статистики"""
    # Дополнительная проверка для опасных действий
    if not check_rate_limit(uid, "dangerous_admin_actions", limit=1, window=3600):
        await query.answer("Сброс статистики можно делать не чаще раза в час.", show_alert=True)
        return
    
    # Подтверждение сброса
    csrf_token = generate_csrf_token(uid)
    
    try:
        await query.edit_message_text(
            "⚠️ <b>Подтверждение сброса статистики</b>\n\n"
            "Вы уверены, что хотите сбросить всю статистику?\n\n"
            "🗑️ <b>Будут удалены:</b>\n"
            "• Все истории покупок\n"
            "• Статистика платежей\n"
            "• История платежей ЮКассы (создастся резервная копия)\n\n"
            "❌ <b>Это действие необратимо!</b>\n\n"
            "Для подтверждения введите: <code>ПОДТВЕРЖДАЮ СБРОС</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data=f"admin:back:{csrf_token}")],
            ]),
            parse_mode="HTML"
        )
        
        # Устанавливаем состояние подтверждения
        ADMIN_STATE[uid] = {
            "mode": "confirm_reset",
            "csrf_token": csrf_token,
            "attempts": 0
        }
        
    except Exception as e:
        logger.error(f"Ошибка в admin:reset_stats: {e}")
        await query.message.reply_text(
            "⚠️ Подтверждение сброса статистики",
            reply_markup=admin_menu_kb(csrf_token)
        )


async def handle_admin_add_product(query, uid):
    """Обработчик добавления товара"""
    csrf_token = generate_csrf_token(uid)
    
    ADMIN_STATE[uid] = {
        "mode": "add_product", 
        "step": "id", 
        "data": {},
        "csrf_token": csrf_token
    }
    
    text = (
        "➕ <b>Добавление нового товара</b>\n\n"
        f"<b>Шаг 1/7:</b> отправьте <code>ID</code> товара\n\n"
        f"<b>❕ Ограничения:</b>\n"
        f"• Максимум {MAX_ID_LENGTH} символов\n"
        "• Только латинские буквы, цифры и _-\n"
        "• Пример: <code>premium_access</code> или <code>product_001</code>\n\n"
        "❌ <b>Отмена:</b> отправьте 'отмена' в любой момент\n"
        "⏭ <b>Пропустить шаг нельзя</b> — ID обязателен\n\n"
        "<i>Для отмены также можно нажать «🏠 Главное меню».</i>"
    )
    
    try:
        await query.edit_message_text(
            text, 
            reply_markup=admin_menu_kb(csrf_token), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:add_product: {e}")
        await query.message.reply_text(
            text, 
            reply_markup=admin_menu_kb(csrf_token), 
            parse_mode="HTML"
        )


async def handle_admin_delete_product(query, uid):
    """Обработчик удаления товара"""
    csrf_token = generate_csrf_token(uid)
    
    ADMIN_STATE[uid] = {
        "mode": "delete_product", 
        "step": "id", 
        "data": {},
        "csrf_token": csrf_token
    }
    
    text = (
        "🗑 <b>Удаление товара</b>\n\n"
        "Отправьте <code>ID</code> товара, который нужно удалить\n\n"
        "📋 <b>Список товаров:</b>\n"
    )
    
    products = load_products()
    if products:
        for p in products[:10]:  # Показываем первые 10 товаров
            text += f"• <code>{html.escape(p.id)}</code> — {html.escape(p.title[:20])}\n"
        if len(products) > 10:
            text += f"• ... и еще {len(products) - 10} товаров\n"
    else:
        text += "• Товаров пока нет\n"
    
    text += "\n❌ <b>Отмена:</b> отправьте 'отмена'\n\n"
    
    try:
        await query.edit_message_text(
            text, 
            reply_markup=admin_menu_kb(csrf_token), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:delete_product: {e}")
        await query.message.reply_text(
            text, 
            reply_markup=admin_menu_kb(csrf_token), 
            parse_mode="HTML"
        )


async def handle_admin_edit_product(query, uid):
    """Обработчик редактирования товара"""
    products = load_products()
    if not products:
        csrf_token = generate_csrf_token(uid)
        try:
            await query.edit_message_text(
                "📦 <b>Товаров пока нет</b>\n\n"
                "Сначала добавьте товар через «➕ Добавить товар».",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin:edit_product: {e}")
            await query.message.reply_text(
                "📦 Товаров пока нет. Сначала добавьте товар.",
                reply_markup=admin_menu_kb(csrf_token)
            )
        return
    
    csrf_token = generate_csrf_token(uid)
    
    try:
        await query.edit_message_text(
            "✏️ <b>Выберите товар для редактирования:</b>",
            reply_markup=edit_select_product_kb(products, csrf_token),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в admin:edit_product (edit): {e}")
        await query.message.reply_text(
            "✏️ Выберите товар для редактирования:",
            reply_markup=edit_select_product_kb(products, csrf_token)
        )


async def on_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Защищенный обработчик выбора товара для редактирования"""
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    if not is_admin(uid):
        await query.answer("Нет доступа", show_alert=True)
        return
    
    try:
        _, pid, csrf_token = query.data.split(":", 2)
        if not verify_csrf_token(uid, csrf_token):
            await query.answer("Ошибка безопасности", show_alert=True)
            return
    except ValueError:
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return
    
    products = load_products()
    product = get_product(products, pid)
    
    if not product:
        await query.answer("Товар не найден", show_alert=True)
        return
    
    # Генерируем новый CSRF токен для сессии редактирования
    new_csrf_token = generate_csrf_token(uid)
    
    ADMIN_STATE[uid] = {
        "mode": "edit_product",
        "step": "id",
        "data": product.__dict__.copy(),
        "original_id": pid,
        "csrf_token": new_csrf_token
    }
    
    text = (
        f"✏️ <b>Редактирование товара</b>\n\n"
        f"📦 <b>Текущий товар:</b> {html.escape(product.title)}\n"
        f"🆔 <b>Текущий ID:</b> <code>{html.escape(product.id)}</code>\n\n"
        f"<b>Шаг 1/8:</b> отправьте новый <code>ID</code> товара\n"
        f"Для сохранения текущего значения отправьте <code>-</code>\n\n"
        f"<b>❕ Ограничения:</b>\n"
        f"• Максимум {MAX_ID_LENGTH} символов\n"
        "• Только латинские буквы, цифры и _-\n\n"
        f"❌ <b>Отмена:</b> отправьте 'отмена' в любой момент\n\n"
        f"<i>Для отмены также можно нажать «🏠 Главное меню».</i>"
    )
    
    try:
        await query.edit_message_text(
            text, 
            reply_markup=admin_menu_kb(new_csrf_token), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в on_edit_select: {e}")
        await query.message.reply_text(
            text, 
            reply_markup=admin_menu_kb(new_csrf_token), 
            parse_mode="HTML"
        )


async def on_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Защищенный обработчик текста в админке"""
    uid = update.effective_user.id
    if not is_admin(uid):
        logger.warning(f"Попытка отправки текста в админку от неавторизованного user_id={uid}")
        return
    
    # Проверка rate limit
    if not check_rate_limit(uid, "admin_text", limit=30, window=60):
        await update.message.reply_text("⚠️ Слишком много запросов. Подождите минуту.")
        return
    
    text = (update.message.text or "").strip()
    if not text:
        return
    
    if text.lower() in ["отмена", "cancel", "стоп", "stop"]:
        if uid in ADMIN_STATE:
            logger.info(f"Действие отменено администратором user_id={uid}")
            ADMIN_STATE.pop(uid, None)
        if uid in WAITING_PROMO:
            WAITING_PROMO.pop(uid, None)
        
        csrf_token = generate_csrf_token(uid)
            
        await update.message.reply_text(
            "❌ Действие отменено.",
            reply_markup=admin_menu_kb(csrf_token),
        )
        return
    
    st = ADMIN_STATE.get(uid)
    if not st:
        return
    
    # --- CONFIRM RESET MODE ---
    if st.get("mode") == "confirm_reset":
        if text.upper() == "ПОДТВЕРЖДАЮ СБРОС":
            reset_db()
            # Также очищаем платежи ЮКассы с созданием резервной копии
            if os.path.exists(YOOKASSA_PAYMENTS_FILE):
                try:
                    backup_name = f"{YOOKASSA_PAYMENTS_FILE}.backup.{int(time.time())}"
                    os.rename(YOOKASSA_PAYMENTS_FILE, backup_name)
                    logger.info(f"Создана резервная копия платежей: {backup_name}")
                except Exception as e:
                    logger.error(f"Ошибка создания бэкапа платежей: {e}")
            
            logger.warning(f"Статистика сброшена администратором user_id={uid}")
            
            csrf_token = generate_csrf_token(uid)
            ADMIN_STATE.pop(uid, None)
            
            await update.message.reply_text(
                "✅ <b>Статистика успешно сброшена!</b>\n\n"
                "🗑️ <b>Удалено:</b>\n"
                "• Все истории покупок\n"
                "• Статистика платежей\n"
                "• История платежей ЮКассы\n\n"
                "💾 <b>Создана резервная копия файла платежей.</b>",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML"
            )
        else:
            st["attempts"] = st.get("attempts", 0) + 1
            if st["attempts"] >= 3:
                csrf_token = generate_csrf_token(uid)
                ADMIN_STATE.pop(uid, None)
                await update.message.reply_text(
                    "❌ Слишком много неудачных попыток. Действие отменено.",
                    reply_markup=admin_menu_kb(csrf_token)
                )
            else:
                await update.message.reply_text(
                    f"⚠️ <b>Неправильное подтверждение</b>\n\n"
                    f"Для подтверждения сброса статистики введите точно:\n"
                    f"<code>ПОДТВЕРЖДАЮ СБРОС</code>\n\n"
                    f"Попыток: {st['attempts']}/3\n"
                    f"❌ Для отмены отправьте 'отмена'",
                    parse_mode="HTML"
                )
        return
    
    # --- DELETE PRODUCT MODE ---
    if st.get("mode") == "delete_product":
        pid = text
        
        error = validate_text_length(pid, "ID товара", MAX_ID_LENGTH)
        if error:
            await update.message.reply_text(error)
            return
            
        products = load_products()
        before = len(products)
        products = [p for p in products if p.id != pid]
        after = len(products)
        
        ADMIN_STATE.pop(uid, None)
        
        if after == before:
            csrf_token = generate_csrf_token(uid)
            await update.message.reply_text(
                f"❌ Товар с ID <code>{html.escape(pid)}</code> не найден.",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML",
            )
            return
        
        save_products(products)
        logger.info(f"Товар {pid} удален администратором user_id={uid}")
        
        csrf_token = generate_csrf_token(uid)
        await update.message.reply_text(
            f"✅ Товар <code>{html.escape(pid)}</code> успешно удалён.",
            reply_markup=admin_menu_kb(csrf_token),
            parse_mode="HTML",
        )
        return
    
    # --- ADD PRODUCT MODE ---
    if st.get("mode") == "add_product":
        step = st.get("step")
        data = st.setdefault("data", {})
        csrf_token = st.get("csrf_token", generate_csrf_token(uid))
        
        if step == "id":
            error = validate_text_length(text, "ID товара", MAX_ID_LENGTH)
            if error:
                await update.message.reply_text(error)
                return
                
            # Проверка на допустимые символы
            if not re.match(r'^[a-zA-Z0-9_\-]+$', text):
                await update.message.reply_text("❌ ID может содержать только латинские буквы, цифры, _ и -")
                return
                
            products = load_products()
            if get_product(products, text):
                await update.message.reply_text("❌ Такой ID уже существует. Пришлите другой ID.")
                return
                
            data["id"] = text
            st["step"] = "title"
            await update.message.reply_text(
                f"<b>Шаг 2/7:</b> отправьте название товара (title)\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_TITLE_LENGTH} символов\n"
                "• Можно использовать русские и английские буквы, цифры, пробелы и знаки препинания\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "title":
            error = validate_text_length(text, "название товара", MAX_TITLE_LENGTH)
            if error:
                await update.message.reply_text(error)
                return
                
            data["title"] = text
            st["step"] = "description"
            await update.message.reply_text(
                f"<b>Шаг 3/7:</b> отправьте описание товара (description)\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DESCRIPTION_LENGTH} символов\n"
                "• Можно использовать любое форматирование\n"
                "• Поддерживаются переносы строк\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "description":
            error = validate_text_length(text, "описание товара", MAX_DESCRIPTION_LENGTH)
            if error:
                await update.message.reply_text(error)
                return
                
            data["description"] = text
            st["step"] = "price_stars"
            await update.message.reply_text(
                f"<b>Шаг 4/7:</b> отправьте цену в ⭐ (только число)\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Минимум {MIN_PRICE_STARS} звезда\n"
                f"• Максимум {MAX_PRICE_STARS} звезд\n"
                "• Пример: 25, 100, 500\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "price_stars":
            try:
                price = int(text)
                if price < MIN_PRICE_STARS:
                    await update.message.reply_text(f"❌ Цена должна быть не меньше {MIN_PRICE_STARS}. Пример: 25")
                    return
                if price > MAX_PRICE_STARS:
                    await update.message.reply_text(f"❌ Цена слишком большая. Максимум {MAX_PRICE_STARS} звезд.")
                    return
            except ValueError:
                await update.message.reply_text("❌ Цена должна быть целым числом > 0. Пример: 25")
                return
                
            data["price_stars"] = price
            st["step"] = "price_rub"
            await update.message.reply_text(
                f"<b>Шаг 5/7:</b> отправьте цену в ₽ (только число)\n\n"
                f"📊 <b>Авто-расчет:</b> {price}⭐ = {price * 10}₽\n"
                f"Для использования авто-расчета отправьте <code>-</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Минимум {MIN_PRICE_RUB} рубль\n"
                f"• Максимум {MAX_PRICE_RUB} рублей\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "price_rub":
            if text == "-":
                # Используем авто-расчет: 1 звезда = 10 рублей
                data["price_rub"] = data["price_stars"] * 10
            else:
                try:
                    price_rub = int(text)
                    if price_rub < MIN_PRICE_RUB:
                        await update.message.reply_text(f"❌ Цена должна быть не меньше {MIN_PRICE_RUB} рублей.")
                        return
                    if price_rub > MAX_PRICE_RUB:
                        await update.message.reply_text(f"❌ Цена слишком большая. Максимум {MAX_PRICE_RUB} рублей.")
                        return
                    data["price_rub"] = price_rub
                except ValueError:
                    await update.message.reply_text("❌ Цена должна быть целым числом > 0. Пример: 250")
                    return
            
            st["step"] = "deliver_text"
            await update.message.reply_text(
                f"<b>Шаг 6/7:</b> отправьте текст выдачи (deliver_text)\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DELIVER_TEXT_LENGTH} символов\n"
                "• Если не нужен — отправьте просто: -\n"
                "• Это текст, который получит пользователь после оплаты\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "deliver_text":
            if text != "-":
                error = validate_text_length(text, "текст выдачи", MAX_DELIVER_TEXT_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                    
            data["deliver_text"] = "" if text == "-" else text
            st["step"] = "deliver_url"
            await update.message.reply_text(
                f"<b>Шаг 7/7:</b> отправьте ссылку (deliver_url)\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DELIVER_URL_LENGTH} символов\n"
                "• Если не нужна — отправьте просто: -\n"
                "• Должна начинаться с http:// или https://\n"
                "• Это ссылка, которая будет отправлена пользователю после оплаты\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "deliver_url":
            if text != "-":
                error = validate_text_length(text, "ссылка", MAX_DELIVER_URL_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                    
                if not text.startswith(("http://", "https://")):
                    await update.message.reply_text(
                        "❌ Ссылка должна начинаться с http:// или https://"
                    )
                    return

            data["deliver_url"] = "" if text == "-" else text

            try:
                newp = Product(
                    id=str(data["id"]),
                    title=str(data["title"]),
                    description=str(data["description"]),
                    price_stars=int(data["price_stars"]),
                    price_rub=int(data.get("price_rub", data["price_stars"] * 10)),
                    deliver_text=str(data.get("deliver_text", "")),
                    deliver_url=str(data.get("deliver_url", "")),
                )
                products = load_products()
                products.append(newp)
                save_products(products)
                
                logger.info(f"Товар добавлен администратором user_id={uid}: {newp.id} - {newp.title}")
                
            except Exception as e:
                await update.message.reply_text(f"❌ Не удалось сохранить товар: {e}")
                ADMIN_STATE.pop(uid, None)
                return

            ADMIN_STATE.pop(uid, None)
            
            await update.message.reply_text(
                f"✅ <b>Товар успешно добавлен!</b>\n\n"
                f"🆔 <b>ID:</b> <code>{newp.id}</code>\n"
                f"📦 <b>Название:</b> {newp.title}\n"
                f"💰 <b>Цена:</b> {newp.price_stars}⭐ / {newp.price_rub}₽\n"
                f"📝 <b>Описание:</b> {len(newp.description)} символов\n"
                f"🎁 <b>Текст выдачи:</b> {'есть' if newp.deliver_text else 'нет'}\n"
                f"🔗 <b>Ссылка:</b> {'есть' if newp.deliver_url else 'нет'}",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML",
            )
            return

    # --- EDIT PRODUCT MODE ---
    if st.get("mode") == "edit_product":
        step = st.get("step")
        data = st.setdefault("data", {})
        original_id = st.get("original_id")
        csrf_token = st.get("csrf_token", generate_csrf_token(uid))
        
        if step == "id":
            if text == "-":
                data["id"] = original_id
            else:
                error = validate_text_length(text, "ID товара", MAX_ID_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                    
                # Проверка на допустимые символы
                if not re.match(r'^[a-zA-Z0-9_\-]+$', text):
                    await update.message.reply_text("❌ ID может содержать только латинские буквы, цифры, _ и -")
                    return
                    
                products = load_products()
                existing_product = get_product(products, text)
                if existing_product and existing_product.id != original_id:
                    await update.message.reply_text(
                        f"❌ Товар с ID <code>{html.escape(text)}</code> уже существует. Пришлите другой ID."
                    )
                    return
                data["id"] = text
            
            st["step"] = "title"
            await update.message.reply_text(
                f"<b>Шаг 2/8:</b> отправьте новое название товара (title)\n"
                f"📝 <b>Текущее:</b> {html.escape(data.get('title', ''))}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_TITLE_LENGTH} символов\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "title":
            if text == "-":
                pass
            else:
                error = validate_text_length(text, "название товара", MAX_TITLE_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                data["title"] = text
                
            st["step"] = "description"
            await update.message.reply_text(
                f"<b>Шаг 3/8:</b> отправьте новое описание товара (description)\n"
                f"📝 <b>Текущее:</b> {html.escape(data.get('description', ''))}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DESCRIPTION_LENGTH} символов\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "description":
            if text == "-":
                pass
            else:
                error = validate_text_length(text, "описание товара", MAX_DESCRIPTION_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                data["description"] = text
                
            st["step"] = "price_stars"
            await update.message.reply_text(
                f"<b>Шаг 4/8:</b> отправьте новую цену в ⭐ (только число)\n"
                f"💰 <b>Текущая:</b> {data.get('price_stars', '')}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Минимум {MIN_PRICE_STARS} звезда\n"
                f"• Максимум {MAX_PRICE_STARS} звезд\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "price_stars":
            if text == "-":
                if "price_stars" not in data:
                    await update.message.reply_text("❌ Ошибка: цена в звездах не найдена")
                    return
            else:
                try:
                    price = int(text)
                    if price < MIN_PRICE_STARS:
                        await update.message.reply_text(f"❌ Цена должна быть не меньше {MIN_PRICE_STARS}.")
                        return
                    if price > MAX_PRICE_STARS:
                        await update.message.reply_text(f"❌ Цена слишком большая. Максимум {MAX_PRICE_STARS} звезд.")
                        return
                    data["price_stars"] = price
                except ValueError:
                    await update.message.reply_text("❌ Цена должна быть целым числом > 0. Пример: 25")
                    return
            
            st["step"] = "price_rub"
            await update.message.reply_text(
                f"<b>Шаг 5/8:</b> отправьте новую цену в ₽ (только число)\n"
                f"💰 <b>Текущая:</b> {data.get('price_rub', data.get('price_stars', 0) * 10)}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Минимум {MIN_PRICE_RUB} рубль\n"
                f"• Максимум {MAX_PRICE_RUB} рублей\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "price_rub":
            if text == "-":
                if "price_rub" not in data and "price_stars" in data:
                    # Авто-расчет из звезд
                    data["price_rub"] = data["price_stars"] * 10
            else:
                try:
                    price_rub = int(text)
                    if price_rub < MIN_PRICE_RUB:
                        await update.message.reply_text(f"❌ Цена должна быть не меньше {MIN_PRICE_RUB} рублей.")
                        return
                    if price_rub > MAX_PRICE_RUB:
                        await update.message.reply_text(f"❌ Цена слишком большая. Максимум {MAX_PRICE_RUB} рублей.")
                        return
                    data["price_rub"] = price_rub
                except ValueError:
                    await update.message.reply_text("❌ Цена должна быть целым числом > 0. Пример: 250")
                    return
            
            st["step"] = "deliver_text"
            await update.message.reply_text(
                f"<b>Шаг 6/8:</b> отправьте новый текст выдачи (deliver_text)\n"
                f"📝 <b>Текущий:</b> {html.escape(data.get('deliver_text', ''))}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n"
                f"Для очистки отправьте <code>clear</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DELIVER_TEXT_LENGTH} символов\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "deliver_text":
            if text == "-":
                pass
            elif text.lower() == "clear":
                data["deliver_text"] = ""
            else:
                error = validate_text_length(text, "текст выдачи", MAX_DELIVER_TEXT_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                data["deliver_text"] = text
            
            st["step"] = "deliver_url"
            await update.message.reply_text(
                f"<b>Шаг 7/8:</b> отправьте новую ссылку (deliver_url)\n"
                f"🔗 <b>Текущая:</b> {html.escape(data.get('deliver_url', ''))}\n"
                f"Для сохранения текущего значения отправьте <code>-</code>\n"
                f"Для очистки отправьте <code>clear</code>\n\n"
                f"<b>❕ Ограничения:</b>\n"
                f"• Максимум {MAX_DELIVER_URL_LENGTH} символов\n"
                "• Должна начинаться с http:// или https://\n\n"
                f"❌ <b>Отмена:</b> отправьте 'отмена'",
                parse_mode="HTML"
            )
            return

        if step == "deliver_url":
            if text == "-":
                pass
            elif text.lower() == "clear":
                data["deliver_url"] = ""
            else:
                error = validate_text_length(text, "ссылка", MAX_DELIVER_URL_LENGTH)
                if error:
                    await update.message.reply_text(error)
                    return
                    
                if not text.startswith(("http://", "https://")):
                    await update.message.reply_text(
                        "❌ Ссылка должна начинаться с http:// или https://"
                    )
                    return
                    
                data["deliver_url"] = text

            try:
                products = load_products()
                
                new_id = str(data["id"])
                if original_id != new_id:
                    # Удаляем старый товар если ID изменился
                    products = [p for p in products if p.id != original_id]
                
                product_found = False
                for i, p in enumerate(products):
                    if p.id == new_id:
                        products[i] = Product(
                            id=new_id,
                            title=str(data["title"]),
                            description=str(data["description"]),
                            price_stars=int(data["price_stars"]),
                            price_rub=int(data.get("price_rub", data["price_stars"] * 10)),
                            deliver_text=str(data.get("deliver_text", "")),
                            deliver_url=str(data.get("deliver_url", "")),
                        )
                        product_found = True
                        break
                
                if not product_found:
                    products.append(Product(
                        id=new_id,
                        title=str(data["title"]),
                        description=str(data["description"]),
                        price_stars=int(data["price_stars"]),
                        price_rub=int(data.get("price_rub", data["price_stars"] * 10)),
                        deliver_text=str(data.get("deliver_text", "")),
                        deliver_url=str(data.get("deliver_url", "")),
                    ))
                
                save_products(products)
                
                logger.info(f"Товар отредактирован администратором user_id={uid}: {original_id} -> {new_id}")
                
            except Exception as e:
                await update.message.reply_text(f"❌ Не удалось сохранить изменения: {e}")
                ADMIN_STATE.pop(uid, None)
                return

            ADMIN_STATE.pop(uid, None)
            await update.message.reply_text(
                f"✅ <b>Товар успешно обновлен!</b>\n\n"
                f"🆔 <b>ID:</b> {data['id']}\n"
                f"📦 <b>Название:</b> {data['title']}\n"
                f"💰 <b>Цена:</b> {data['price_stars']}⭐ / {data.get('price_rub', data['price_stars'] * 10)}₽\n"
                f"📝 <b>Описание:</b> {len(data['description'])} символов\n"
                f"🎁 <b>Текст выдачи:</b> {'есть' if data.get('deliver_text') else 'нет'}\n"
                f"🔗 <b>Ссылка:</b> {'есть' if data.get('deliver_url') else 'нет'}",
                reply_markup=admin_menu_kb(csrf_token),
                parse_mode="HTML",
            )
            return


# Функции для регистрации обработчиков
def get_admin_handlers():
    """Возвращает защищенные обработчики для админ-панели"""
    return [
        CommandHandler("admin", admin),
        CallbackQueryHandler(on_admin_click, pattern=r"^admin:"),
        CallbackQueryHandler(on_edit_select, pattern=r"^edit_select:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_admin_text),
    ]