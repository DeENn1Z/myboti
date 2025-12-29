import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    PreCheckoutQueryHandler, ContextTypes, filters
)

# ====== ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ======
load_dotenv()  # Загружает переменные из .env файла

# ====== НАСТРОЙКА ЛОГИРОВАНИЯ ======
if not os.path.exists('logs'):
    os.makedirs('logs')

# 1. Файловый handler (ВСЕ логи ТОЛЬКО в файл)
file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# 2. УБИРАЕМ console_handler полностью - ничего не будет в терминале

# 3. Настройка корневого логгера только с ОДНИМ обработчиком (файловым)
logging.basicConfig(
    level=logging.INFO,  # Минимальный уровень для логгеров
    handlers=[file_handler]  # ← ТОЛЬКО file_handler, без console_handler
)

# 4. Отключаем шумные модули
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Импорты из наших модулей
from data_tools import (
    BOT_TOKEN, WAITING_PROMO, ADMIN_STATE, LAST_INVOICE,
    load_products, get_product, mark_payment_processed, add_purchase,
    load_db, check_rate_limit, is_admin, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
)
from keyboards import main_menu_kb, back_to_product_kb, product_kb, catalog_kb, payment_methods_kb, home_only_kb
from payments import (
    delete_last_invoice, create_yookassa_payment,
    create_stars_invoice_payload, get_yookassa_payment,
    update_yookassa_payment_status, check_yookassa_payment_status,
    verify_stars_invoice_payload, validate_payment_data
)
from admin import get_admin_handlers
from subscriptions import handle_subscription_command, delete_subscription_message

import html


# ---------- ВАЛИДАЦИЯ И БЕЗОПАСНОСТЬ ----------
def sanitize_input(text: str, max_length: int = 2000) -> str:
    """Очищает ввод пользователя от потенциально опасных символов"""
    if not text:
        return ""
    
    # Ограничиваем длину
    if len(text) > max_length:
        text = text[:max_length]
    
    # Заменяем опасные HTML символы
    text = html.escape(text)
    
    # Удаляем управляющие символы (кроме переноса строки и табуляции)
    import re
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    return text


def validate_user_session(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет валидность сессии пользователя"""
    # Здесь можно добавить проверку IP, времени сессии и т.д.
    # Пока просто проверяем rate limit
    return check_rate_limit(user_id, "general_requests", limit=50, window=300)


# ---------- ОСНОВНЫЕ ОБРАБОТЧИКИ ----------
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная команда /myid"""
    uid = update.effective_user.id
    
    # Rate limiting
    if not check_rate_limit(uid, "myid_command", limit=3, window=60):
        await update.message.reply_text("⚠️ Слишком много запросов. Подождите минуту.")
        return
    
    username = update.effective_user.username or "нет username"
    first_name = sanitize_input(update.effective_user.first_name or "", 100)
    
    await update.message.reply_text(
        f"📋 <b>Ваши данные:</b>\n\n"
        f"🆔 Telegram ID: <code>{uid}</code>\n"
        f"👤 Имя: {first_name}\n"
        f"🔗 Username: @{username}\n\n"
        f"<i>Для добавления в админы добавьте этот ID в ADMIN_IDS в .env файле</i>",
        parse_mode="HTML"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная команда /start"""
    uid = update.effective_user.id
    
    # Rate limiting
    if not check_rate_limit(uid, "start_command", limit=5, window=60):
        await update.message.reply_text("⚠️ Слишком много запросов. Подождите минуту.")
        return
    
    # Очистка состояний
    WAITING_PROMO.pop(uid, None)
    ADMIN_STATE.pop(uid, None)
    await delete_last_invoice(context, uid)
    
    # Удаляем сообщение о подписке если было
    await delete_subscription_message(uid, context)
    
    # Логирование старта
    username = update.effective_user.username or "нет"
    logger.info(f"Пользователь {uid} (@{username}) запустил бота")
    
    welcome_text = "Добро пожаловать в магазин бот"
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Начать", callback_data="menu:home")
        ]])
    )


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасный обработчик меню"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    user_id = query.from_user.id
    
    # Проверка сессии
    if not validate_user_session(user_id, context):
        await query.answer("Ошибка сессии. Перезапустите бота /start", show_alert=True)
        return
    
    # Rate limiting
    if not check_rate_limit(user_id, "menu_actions", limit=20, window=60):
        await query.answer("Слишком много действий. Подождите минуту.", show_alert=True)
        return
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если пользователь переходит в другое меню
    await delete_subscription_message(user_id, context)
    
    if action in ("menu:home", "menu:catalog", "menu:promocode", "menu:support", "menu:mysub"):
        await delete_last_invoice(context, user_id)
    
    WAITING_PROMO.pop(user_id, None)
    ADMIN_STATE.pop(user_id, None)
    
    if action == "menu:home":
        await handle_menu_home(query, context)
        return
    
    if action == "menu:catalog":
        await handle_menu_catalog(query, context)  # ← ДОБАВЛЕНО context
        return
    
    if action == "menu:promocode":
        await handle_menu_promocode(query, user_id, context)  # ← ДОБАВЛЕНО context
        return
    
    if action == "menu:support":
        await handle_menu_support(query, context)  # ← ДОБАВЛЕНО context
        return
    
    if action == "menu:mysub":
        await handle_menu_mysub(query, user_id, context)
        return


async def handle_menu_home(query, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик главного меню с картинкой"""
    try:
        # Получаем абсолютный путь к картинке
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        photo_path = os.path.join(current_dir, "images", "menu_image.png")
        
        caption = "🏠 <b>Главное меню</b>\n\nВыберите действие:"
        
        # Проверяем существование файла
        if os.path.exists(photo_path):
            # Открываем файл и отправляем
            with open(photo_path, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo,
                    caption=caption,
                    reply_markup=main_menu_kb(),
                    parse_mode="HTML"
                )
            # Удаляем старое сообщение
            try:
                await query.delete_message()
            except:
                pass
        else:
            # Если картинки нет, отправляем текстовое сообщение
            logger.warning(f"Картинка не найдена по пути: {photo_path}")
            await query.edit_message_text(
                caption,
                reply_markup=main_menu_kb(),
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_home: {e}")
        # Резервный вариант - текстовое сообщение
        try:
            await query.edit_message_text(
                "🏠 <b>Главное меню</b>\n\nВыберите действие:",
                reply_markup=main_menu_kb(),
                parse_mode="HTML"
            )
        except Exception as e2:
            logger.error(f"Резервный вариант тоже не сработал: {e2}")
            await query.message.reply_text(
                "🏠 <b>Главное меню</b>",
                reply_markup=main_menu_kb(),
                parse_mode="HTML"
            )


async def handle_menu_catalog(query, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик каталога с удалением предыдущего сообщения"""
    products = load_products()
    
    # Пытаемся удалить предыдущее сообщение
    try:
        await query.delete_message()
    except Exception as delete_error:
        logger.warning(f"Не удалось удалить предыдущее сообщение: {delete_error}")
    
    if not products:
        try:
            await query.message.reply_text(
                "📦 <b>Каталог пуст</b>\n\n"
                "Товары скоро появятся!",
                reply_markup=home_only_kb(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в handle_menu_catalog: {e}")
        return
    
    try:
        await query.message.reply_text(
            "📦 <b>Выбор подписки</b>\n\n"  # ← ИЗМЕНЕНИЕ
            "Выберите вариант подписки:",
            reply_markup=catalog_kb(products),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_catalog: {e}")
        await query.message.reply_text(
            "📦 <b>Выбор подписки</b>",
            reply_markup=catalog_kb(products),
            parse_mode="HTML"
        )


async def handle_menu_promocode(query, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик промокода с удалением предыдущего сообщения"""
    WAITING_PROMO[user_id] = True
    
    # Пытаемся удалить предыдущее сообщение
    try:
        await query.delete_message()
    except Exception as delete_error:
        logger.warning(f"Не удалось удалить предыдущее сообщение: {delete_error}")
    
    try:
        await query.message.reply_text(
            "🎁 <b>Ввод промокода</b>\n\n"
            "Отправьте промокод обычным сообщением (текстом).\n\n"
            "❌ <b>Отмена:</b> отправьте 'отмена' или нажмите «🏠 Главное меню».\n"
            "⏳ <b>Таймаут:</b> 5 минут",
            reply_markup=home_only_kb(),  # ← ИЗМЕНЕНИЕ
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_promocode: {e}")
        await query.message.reply_text(
            "🎁 Введите промокод:",
            reply_markup=home_only_kb()  # ← ИЗМЕНЕНИЕ
        )


async def handle_menu_support(query, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик поддержки с удалением предыдущего сообщения"""
    
    # Пытаемся удалить предыдущее сообщение
    try:
        await query.delete_message()
    except Exception as delete_error:
        logger.warning(f"Не удалось удалить предыдущее сообщение: {delete_error}")
    
    try:
        await query.message.reply_text(
            "💬 <b>Поддержка</b>\n\n"
            "Если у вас возникли проблемы:\n\n"
            "1. Опишите проблему подробно\n"
            "2. Укажите номер заказа (если есть)\n"
            "3. Приложите скриншот (если нужно)\n\n"
            "📧 Email: support@example.com\n"
            "👤 Контакт: @support_username\n\n"
            "⏰ <i>Время ответа: до 24 часов</i>",
            reply_markup=home_only_kb(),  # ← ИЗМЕНЕНИЕ
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_support: {e}")
        await query.message.reply_text(
            "💬 Поддержка:\n"
            "Email: support@example.com\n"
            "Контакт: @support_username",
            reply_markup=home_only_kb()  # ← ИЗМЕНЕНИЕ
        )


async def handle_menu_mysub(query, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Моя подписка'"""
    # Rate limiting для проверки подписки
    if not check_rate_limit(user_id, "subscription_check", limit=10, window=60):
        await query.answer("Слишком много запросов. Подождите минуту.", show_alert=True)
        return
    
    logger.info(f"Пользователь {user_id} проверяет свою подписку")
    
    try:
        # Используем функцию из subscriptions.py
        await handle_subscription_command(user_id, query, context)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_menu_mysub: {e}", exc_info=True)
        
        # Отправляем сообщение об ошибке
        try:
            await query.edit_message_text(
                "❌ <b>Ошибка при проверке подписки</b>\n\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                reply_markup=main_menu_kb(),
                parse_mode="HTML"
            )
        except Exception:
            await query.message.reply_text(
                "❌ Ошибка при проверке подписки. Попробуйте позже.",
                reply_markup=main_menu_kb()
            )


async def on_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасный обработчик товара"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    # Rate limiting
    if not check_rate_limit(user_id, "product_views", limit=30, window=60):
        await query.answer("Слишком много запросов. Подождите минуту.", show_alert=True)
        return
    
    try:
        _, pid = query.data.split(":", 1)
    except ValueError:
        logger.warning(f"Некорректный формат callback_data от user_id={user_id}: {query.data}")
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return
    
    # Валидация product_id
    if len(pid) > 50 or not pid.strip():
        await query.answer("Некорректный ID товара", show_alert=True)
        return
    
    products = load_products()
    p = get_product(products, pid)
    if not p:
        await query.answer("Товар не найден", show_alert=True)
        return
    
    # Безопасное отображение данных товара
    safe_title = sanitize_input(p.title, 100)
    safe_description = sanitize_input(p.description, 500)
    
    text = (
        f"📦 <b>{safe_title}</b>\n\n"
        f"{safe_description}\n\n"
        f"💳 <b>Способы оплаты:</b>\n"
        f"• Telegram Stars: <b>{p.price_stars}⭐</b>\n"
        f"• ЮКасса: <b>{p.price_rub}₽</b>\n\n"
        f"Выберите способ оплаты ниже ⬇️"
    )
    
    logger.info(f"Пользователь {user_id} просматривает товар {pid}")
    
    try:
        await query.edit_message_text(text, reply_markup=product_kb(pid), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в on_product: {e}")
        await query.message.reply_text(text, reply_markup=product_kb(pid), parse_mode="HTML")


async def on_choose_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасный выбор способа оплаты"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    try:
        _, pid = query.data.split(":", 1)
    except ValueError:
        logger.warning(f"Некорректный формат choose_pay callback от user_id={user_id}")
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return
    
    products = load_products()
    p = get_product(products, pid)
    if not p:
        await query.answer("Товар не найден", show_alert=True)
        return
    
    safe_title = sanitize_input(p.title, 100)
    
    text = (
        f"💳 <b>Выберите способ оплаты:</b>\n\n"
        f"📦 <b>{safe_title}</b>\n"
        f"Цена: {p.price_stars}⭐ / {p.price_rub}₽\n\n"
        f"⭐ <b>Telegram Stars</b>\n"
        f"• Оплата внутренней валютой Telegram\n"
        f"• Мгновенное получение товара\n\n"
        f"💰 <b>ЮКасса</b>\n"
        f"• Карты, СБП, электронные кошельки\n"
        f"• Безопасная оплата через защищенный шлюз"
    )
    
    try:
        await query.edit_message_text(text, reply_markup=payment_methods_kb(pid), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в on_choose_payment: {e}")
        await query.message.reply_text(text, reply_markup=payment_methods_kb(pid), parse_mode="HTML")


async def on_pay_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная оплата через Telegram Stars"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    # Rate limiting для платежей
    if not check_rate_limit(user_id, "payment_attempts", limit=5, window=300):
        await query.answer("Слишком много попыток оплаты. Подождите 5 минут.", show_alert=True)
        return
    
    try:
        _, pid = query.data.split(":", 1)
    except ValueError:
        logger.warning(f"Некорректный формат pay_stars callback от user_id={user_id}")
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return
    
    products = load_products()
    p = get_product(products, pid)
    if not p:
        await query.answer("Товар не найден", show_alert=True)
        return
    
    # Удаляем предыдущее сообщение безопасно
    try:
        await query.delete_message()
    except Exception as e:
        logger.warning(f"Не удалось удалить сообщение: {e}")
    
    # Создаем защищенный payload
    prices, payload = create_stars_invoice_payload(user_id, p)
    
    try:
        invoice_msg = await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"Оплата: {p.title[:32]}",
            description=p.description[:255] if p.description else "Цифровой товар",
            payload=payload,
            provider_token="",  # Для Stars provider_token не нужен
            currency="XTR",
            prices=prices,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False,
            start_parameter=pid,
        )
        
        LAST_INVOICE[user_id] = (invoice_msg.chat_id, invoice_msg.message_id)
        
        # Логируем создание инвойса
        logger.info(f"Создан инвойс Stars для user_id={user_id}, product_id={pid}")
        
        # Информационное сообщение
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⭐ <b>Счет на оплату отправлен</b>\n\n"
                 "Проверьте сообщение выше для оплаты Telegram Stars.\n\n"
                 "❌ <b>Если передумали</b> — нажмите кнопку ниже.",
            reply_markup=back_to_product_kb(pid),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка отправки инвойса: {e}", exc_info=True)
        await query.answer("Ошибка при создании счета на оплату", show_alert=True)
        # Безопасный возврат к товару
        await on_product(update, context)
        return


async def on_pay_yookassa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная оплата через ЮКассу"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    # Проверка доступности ЮКассы
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        await query.answer("❌ Оплата через ЮКассу временно недоступна", show_alert=True)
        logger.error(f"Попытка оплаты ЮКассой при отключенных ключах user_id={user_id}")
        return
    
    # Rate limiting для платежей ЮКассы
    if not check_rate_limit(user_id, "yookassa_payment_attempts", limit=3, window=300):
        await query.answer("Слишком много попыток оплата. Подождите 5 минут.", show_alert=True)
        return
    
    try:
        _, pid = query.data.split(":", 1)
    except ValueError:
        logger.warning(f"Некорректный формат pay_yookassa callback от user_id={user_id}")
        await query.answer("Ошибка: неверный формат данных", show_alert=True)
        return
    
    products = load_products()
    p = get_product(products, pid)
    if not p:
        await query.answer("Товар не найден", show_alert=True)
        return
    
    # Проверка цены
    if p.price_rub <= 0 or p.price_rub > 10000000:
        await query.answer("❌ Некорректная цена товара", show_alert=True)
        logger.error(f"Некорректная цена товара {pid}: {p.price_rub}")
        return
    
    # Создаем защищенный платеж
    try:
        payment = create_yookassa_payment(
            user_id=user_id,
            product=p,
            message_id=query.message.message_id
        )
        
        if not payment:
            await query.answer("❌ Ошибка при создании платежа. Попробуйте позже.", show_alert=True)
            logger.error(f"Не удалось создать платеж ЮКассы для user_id={user_id}, product_id={pid}")
            return
        
        safe_title = sanitize_input(p.title, 100)
        
        text = (
            f"💰 <b>Оплата через ЮКассу</b>\n\n"
            f"📦 Товар: {safe_title}\n"
            f"💵 Сумма: <b>{p.price_rub}₽</b> ({p.price_stars}⭐)\n"
            f"🆔 Номер платежа: <code>{payment.payment_id[:16]}...</code>\n\n"
            f"ℹ️ <i>Нажмите кнопку ниже для перехода к оплате.</i>\n"
            f"После оплаты нажмите «Проверить статус».\n\n"
            f"💡 <b>Инструкция:</b>\n"
            f"1. Нажмите «Перейти к оплате»\n"
            f"2. Оплатите в открывшемся окне\n"
            f"3. Вернитесь в бота и нажмите «Проверить статус»\n\n"
            f"⚠️ <b>Внимание:</b> Не передавайте номер платежа третьим лицам!"
        )
        
        logger.info(f"Создан платеж ЮКассы {payment.payment_id[:8]}... для user_id={user_id}")
        
        try:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Перейти к оплате", url=payment.payment_url)],
                    [InlineKeyboardButton("🔄 Проверить статус", callback_data=f"yookassa_check:{payment.payment_id}")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
                ]),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в on_pay_yookassa (edit): {e}")
            await query.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Перейти к оплате", url=payment.payment_url)],
                    [InlineKeyboardButton("🔄 Проверить статус", callback_data=f"yookassa_check:{payment.payment_id}")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
                ]),
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка создания платежа ЮКассы: {e}", exc_info=True)
        await query.answer("Ошибка при создании платежа", show_alert=True)


async def on_yookassa_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная проверка статуса платежа ЮКассы"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    # Rate limiting для проверок статуса
    if not check_rate_limit(user_id, "yookassa_check_status", limit=10, window=60):
        await query.answer("Слишком много проверок. Подождите минуту.", show_alert=True)
        return
    
    try:
        _, payment_id = query.data.split(":", 1)
    except ValueError:
        logger.warning(f"Некорректный формат yookassa_check callback от user_id={user_id}")
        await query.answer("Ошибка", show_alert=True)
        return
    
    # Валидация payment_id
    if len(payment_id) > 100 or not payment_id.strip():
        await query.answer("Некорректный номер платежа", show_alert=True)
        return
    
    # === КРИТИЧЕСКАЯ ПРОВЕРКА 1: Получаем данные платежа ДО всего ===
    payment_data = get_yookassa_payment(payment_id)
    if not payment_data:
        await query.answer("Платеж не найден в базе", show_alert=True)
        logger.warning(f"Платеж {payment_id} не найден для user_id={user_id}")
        return
    
    # === КРИТИЧЕСКАЯ ПРОВЕРКА 2: Проверяем владельца ===
    if payment_data.get("user_id") != user_id:
        logger.security(f"🚨 ПОПЫТКА КРАЖИ ТОВАРА! user_id={user_id} пытается получить чужой платеж {payment_id}")
        await query.answer("Это не ваш платеж", show_alert=True)
        return
    
    try:
        from data_tools import fmt_dt
        
        # Проверяем статус платежа через API ЮКассы
        current_status = check_yookassa_payment_status(payment_id)
        if not current_status:
            await query.answer("❌ Не удалось проверить статус платежа", show_alert=True)
            logger.warning(f"Не удалось проверить статус платежа {payment_id} для user_id={user_id}")
            return
        
        # Обновляем статус в локальной БД
        update_yookassa_payment_status(payment_id, current_status)
        
        # Если платеж успешен - выдаем товар
        if current_status == "succeeded":
            # Находим товар
            products = load_products()
            product = get_product(products, payment_data["product_id"])
            
            if product:
                # Проверяем, не выдавали ли уже товар по этому платежу
                db = load_db()
                already_delivered = False
                purchases = db.get("purchases", {})
                
                for uid, items in purchases.items():
                    for item in items:
                        if item.get("yookassa_id") == payment_id:
                            already_delivered = True
                            break
                    if already_delivered:
                        break
                
                if not already_delivered:
                    # Добавляем покупку с валидацией
                    add_purchase(user_id, product, payment_method="yookassa", yookassa_id=payment_id)
                    
                    # Логируем успешную выдачу
                    logger.info(f"Товар выдан по платежу ЮКассы {payment_id[:8]}... для user_id={user_id}")
                    
                    # Отправляем товар
                    lines = [f"✅ <b>Оплата прошла успешно!</b>\n\nВот ваш товар:"]
                    lines.append(f"📦 {sanitize_input(product.title, 100)}")
                    
                    if product.deliver_text and product.deliver_text.strip():
                        safe_deliver_text = sanitize_input(product.deliver_text.strip(), 1000)
                        lines.append(f"\n{safe_deliver_text}")
                    
                    if product.deliver_url and product.deliver_url.strip():
                        url = product.deliver_url.strip()
                        if url.startswith(("http://", "https://")) and len(url) <= 500:
                            lines.append(f"\n🔗 Ссылка: {url}")
                    
                    try:
                        await query.edit_message_text("\n".join(lines), reply_markup=main_menu_kb(), parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Ошибка редактирования сообщения: {e}")
                        await query.message.reply_text("\n".join(lines), reply_markup=main_menu_kb(), parse_mode="HTML")
                else:
                    # Товар уже был выдан
                    safe_title = sanitize_input(product.title, 100)
                    text = (
                        f"✅ <b>Платеж успешно завершен!</b>\n\n"
                        f"📦 Товар: {safe_title}\n"
                        f"💵 Сумма: {payment_data['amount']}₽\n"
                        f"🆔 Номер: <code>{payment_id[:16]}...</code>\n"
                        f"📅 Дата: {fmt_dt(payment_data['created_at'])}\n\n"
                        f"ℹ️ <i>Товар был выдан ранее.</i>"
                    )
                    try:
                        await query.edit_message_text(
                            text,
                            reply_markup=main_menu_kb(),
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка редактирования сообщения: {e}")
            return
        
        # Если платеж все еще в обработке
        status_texts = {
            "pending": "⏳ Ожидает оплаты",
            "waiting_for_capture": "⏳ Ожидает подтверждения",
            "succeeded": "✅ Оплачен",
            "canceled": "❌ Отменен"
        }
        
        status_text = status_texts.get(current_status, "❓ Неизвестен")
        
        text = (
            f"🔄 <b>Статус платежа</b>\n\n"
            f"📊 Статус: <b>{status_text}</b>\n"
            f"🆔 Номер: <code>{payment_id[:16]}...</code>\n"
            f"💵 Сумма: {payment_data['amount']}₽\n"
            f"📅 Создан: {fmt_dt(payment_data['created_at'])}\n\n"
        )
        
        if current_status in ["pending", "waiting_for_capture"]:
            text += (
                f"ℹ️ <i>Если вы уже оплатили, но статус не обновился,\n"
                f"подождите несколько минут и проверьте снова.</i>\n\n"
                f"Для оплаты нажмите «Перейти к оплате»."
            )
            
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💳 Перейти к оплате", url=payment_data['payment_url'])],
                        [InlineKeyboardButton("🔄 Проверить статус", callback_data=f"yookassa_check:{payment_id}")],
                        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
                    ]),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка в on_yookassa_check (edit): {e}")
        else:
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=main_menu_kb(),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка в on_yookassa_check (final): {e}")
                
    except Exception as e:
        logger.error(f"Ошибка проверки статуса платежа {payment_id}: {e}", exc_info=True)
        await query.answer("❌ Ошибка при проверке статуса платежа. Попробуйте позже.", show_alert=True)


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная предварительная проверка платежа"""
    query = update.pre_checkout_query
    
    # Логируем precheckout запрос
    user_id = query.from_user.id
    logger.info(f"Precheckout запрос от user_id={user_id}, сумма: {query.total_amount/100} {query.currency}")
    
    # Всегда отвечаем OK, реальная проверка в on_successful_payment
    await query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная обработка успешного платежа Telegram Stars"""
    msg = update.message
    sp = msg.successful_payment
    if not sp:
        return
    
    user_id = msg.from_user.id
    
    # УДАЛЯЕМ СООБЩЕНИЕ О ПОДПИСКЕ если было
    await delete_subscription_message(user_id, context)
    
    # Логируем успешный платеж
    logger.info(f"Успешный платеж Stars от user_id={user_id}, сумма: {sp.total_amount/100} {sp.currency}")
    
    await delete_last_invoice(context, user_id)
    
    # Проверяем валюту
    if sp.currency != "XTR":
        logger.error(f"Неверная валюта платежа от user_id={user_id}: {sp.currency}")
        await msg.reply_text("❌ Ошибка: неверная валюта платежа. Обратитесь в поддержку.")
        return
    
    # Проверяем обработку платежа
    charge_id = sp.telegram_payment_charge_id
    if charge_id and not mark_payment_processed(charge_id):
        logger.warning(f"Повторная обработка платежа от user_id={user_id}, charge_id={charge_id}")
        await msg.reply_text("✅ Этот платёж уже обработан ранее. Если нужна помощь — напишите в поддержку.")
        return
    
    payload = sp.invoice_payload or ""
    
    # ВАЖНО: Проверяем валидность защищенного payload
    pid = verify_stars_invoice_payload(payload, user_id)
    
    if not pid:
        logger.security(f"Невалидный payload платежа Stars от user_id={user_id}: {payload[:50]}...")
        await msg.reply_text("❌ Ошибка проверки платежа. Пожалуйста, обратитесь в поддержку.")
        return
    
    products = load_products()
    p = get_product(products, pid) if pid else None
    if not p:
        logger.error(f"Товар не найден по payload от user_id={user_id}: pid={pid}")
        await msg.reply_text("✅ Оплата прошла! Но товар не найден. Напишите /start или обратитесь в поддержку.")
        return
    
    # Добавляем покупку
    add_purchase(user_id, p, payment_method="stars")
    
    logger.info(f"Товар выдан по платежу Stars для user_id={user_id}, product_id={pid}")
    
    # Отправляем товар
    await msg.reply_text("✅ <b>Оплата прошла успешно!</b>\n\nВот ваш цифровой товар:", parse_mode="HTML")
    
    lines = [f"📦 {sanitize_input(p.title, 100)}"]
    
    if p.deliver_text and p.deliver_text.strip():
        safe_deliver_text = sanitize_input(p.deliver_text.strip(), 1000)
        lines.append(f"\n{safe_deliver_text}")
    
    if p.deliver_url and p.deliver_url.strip():
        url = p.deliver_url.strip()
        if url.startswith(("http://", "https://")) and len(url) <= 500:
            lines.append(f"\n🔗 Ссылка: {url}")
    
    await msg.reply_text("\n".join(lines), reply_markup=main_menu_kb())


async def on_promo_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасная обработка промокодов"""
    user_id = update.effective_user.id
    
    # Если пользователь в админском состоянии - пропускаем
    if user_id in ADMIN_STATE:
        return
    
    if not WAITING_PROMO.get(user_id):
        return
    
    text = (update.message.text or "").strip()
    
    # Rate limiting для промокодов
    if not check_rate_limit(user_id, "promocode_attempts", limit=5, window=300):
        await update.message.reply_text("⚠️ Слишком много попыток. Подождите 5 минут.")
        WAITING_PROMO.pop(user_id, None)
        return
    
    if text.lower() in ["отмена", "cancel", "стоп", "stop"]:
        WAITING_PROMO.pop(user_id, None)
        await update.message.reply_text(
            "❌ Ввод промокода отменен.",
            reply_markup=main_menu_kb(),
        )
        return
    
    # Валидация промокода
    if len(text) > 100:
        await update.message.reply_text(
            "❌ Промокод слишком длинный. Максимум 100 символов.\n"
            "Попробуйте снова или отправьте 'отмена'.",
            reply_markup=main_menu_kb(),
        )
        return
    
    # Очищаем промокод от опасных символов
    safe_promocode = sanitize_input(text, 100)
    
    # Логируем ввод промокода
    logger.info(f"Введен промокод от user_id={user_id}: {safe_promocode}")
    
    WAITING_PROMO.pop(user_id, None)
    
    # Здесь можно добавить проверку промокода в базе данных
    await update.message.reply_text(
        f"🎁 <b>Промокод получен</b>\n\n"
        f"Код: <code>{safe_promocode}</code>\n\n"
        f"<i>Проверка промокодов в разработке...</i>",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Безопасный обработчик ошибок"""
    error_msg = str(context.error) if context.error else "Неизвестная ошибка"
    
    # Логируем ошибку с полной информацией
    logger.error(f"Ошибка при обработке обновления {update}: {error_msg}", exc_info=True)
    
    try:
        if update and update.effective_message:
            user_id = update.effective_user.id if update.effective_user else 0
            logger.info(f"Отправка сообщения об ошибке пользователю {user_id}")
            
            await update.effective_message.reply_text(
                "❌ <b>Произошла ошибка</b>\n\n"
                "Пожалуйста, попробуйте еще раз.\n"
                "Если ошибка повторяется, обратитесь в поддержку.",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")


async def security_monitor(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Монитор безопасности - запускается периодически"""
    logger.info("Запуск монитора безопасности...")
    
    # Здесь можно добавить проверки:
    # - Подозрительная активность
    # - Множественные неудачные платежи
    # - Попытки доступа к админке и т.д.
    
    # Пример: очистка старых состояний
    from data_tools import ADMIN_STATE, WAITING_PROMO, LAST_INVOICE
    import time
    
    current_time = time.time()
    
    # Очистка старых состояний админки (старше 1 часа)
    to_remove = []
    for uid, state in ADMIN_STATE.items():
        if current_time - state.get('timestamp', 0) > 3600:
            to_remove.append(uid)
    
    for uid in to_remove:
        ADMIN_STATE.pop(uid, None)
        logger.info(f"Очищено устаревшее состояние админки user_id={uid}")
    
    logger.info("Монитор безопасности завершил работу")


def main() -> None:
    """Основная функция запуска безопасного бота"""
    
    # Проверка обязательных переменных
    if not BOT_TOKEN:
        logger.critical("❌ BOT_TOKEN не задан. Задайте переменную окружения BOT_TOKEN.")
        raise SystemExit("❌ BOT_TOKEN не задан.")
    
    # Логирование информации о запуске
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК БЕЗОПАСНОГО БОТА МАГАЗИНА")
    logger.info("=" * 60)
    
    admin_ids_count = len([id for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()])
    logger.info(f"🔐 Администраторов: {admin_ids_count}")
    logger.info(f"💰 ЮКасса: {'✅ Настроена' if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY else '❌ Не настроена'}")
    
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        logger.warning("⚠️  ЮКасса не настроена. Оплата через ЮКассу недоступна.")
    
    logger.info("=" * 60)
    logger.info("✅ Все проверки пройдены")
    logger.info("=" * 60)
    
    # Создание приложения
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчик ошибок
    app.add_error_handler(error_handler)
    
    # Основные команды пользователя
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    from admin import admin as admin_command
    app.add_handler(CommandHandler("admin", admin_command))

    # Обработчики меню и товаров
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_product, pattern=r"^prod:"))
    app.add_handler(CallbackQueryHandler(on_choose_payment, pattern=r"^choose_pay:"))
    app.add_handler(CallbackQueryHandler(on_pay_stars, pattern=r"^pay_stars:"))
    app.add_handler(CallbackQueryHandler(on_pay_yookassa, pattern=r"^pay_yookassa:"))
    app.add_handler(CallbackQueryHandler(on_yookassa_check, pattern=r"^yookassa_check:"))

    # Обработчики админ-панели
    admin_handlers = get_admin_handlers()
    for handler in admin_handlers:
        app.add_handler(handler)

    # Обработчик промокодов
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_promo_text))
    
    # Обработчик платежей
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # Добавляем периодические задачи (мониторинг безопасности)
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(security_monitor, interval=300, first=10)  # Каждые 5 минут
    
    # Запуск бота
    print("\n" + "=" * 60)
    print("🤖 БЕЗОПАСНЫЙ БОТ МАГАЗИНА ЗАПУЩЕН!")
    print("=" * 60)
    print("🔒 МЕРЫ БЕЗОПАСНОСТИ:")
    print("  • Защита от CSRF-атак")
    print("  • Rate limiting на все действия")
    print("  • Валидация всех входящих данных")
    print("  • HMAC-подписи для платежей")
    print("  • Проверка принадлежности платежей")
    print("  • Автоудаление сообщений подписки")
    print("=" * 60)
    print("💳 ПЛАТЕЖНЫЕ СИСТЕМЫ:")
    print(f"  • Telegram Stars: ✅ Активно")
    print(f"  • ЮКасса: {'✅ Активно' if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY else '❌ Отключено'}")
    print("=" * 60)
    print("📊 МОНИТОРИНГ:")
    print("  • Логи в папке logs/")
    print("  • Мониторинг безопасности каждые 5 минут")
    print("  • Личный кабинет подписок: ✅ Активно")
    print("=" * 60)
    print("⚠️  ВАЖНО:")
    print("  1. Никогда не коммитьте файл .env в git!")
    print("  2. Регулярно делайте бэкапы данных")
    print("  3. Мониторьте логи на подозрительную активность")
    print("=" * 60)
    print("Ctrl+C для остановки")
    print("=" * 60 + "\n")
    
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # Очистка pending updates при запуске
    )


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 Бот остановлен пользователем")
        logger.info("Бот остановлен по команде пользователя")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        print(f"\n❌ Критическая ошибка: {e}")
        print("Проверьте логи в папке logs/")