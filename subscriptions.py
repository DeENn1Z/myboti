# subscriptions.py - с функцией удаления сообщения
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Храним ID сообщений с подписками для каждого пользователя
SUBSCRIPTION_MESSAGES = {}  # {user_id: (chat_id, message_id)}


def get_user_subscription_info(user_id: int) -> Dict[str, Any]:
    """
    ПРОСТАЯ функция проверки подписки.
    Возвращает только то, что нужно показать пользователю.
    """
    try:
        from data_tools import load_db
        
        db = load_db()
        user_id_str = str(user_id)
        
        # Получаем ВСЕ покупки пользователя
        all_purchases = db.get("purchases", {}).get(user_id_str, [])
        
        # Если покупок нет
        if not all_purchases:
            return {
                "has_subscription": False,
                "status": "no_subscription",
                "message": "📭 <b>У вас нет активной подписки</b>\n\n"
                          "Для доступа к VPN приобретите подписку в каталоге.",
                "details": None
            }
        
        # Находим последнюю покупку
        last_purchase = max(all_purchases, key=lambda x: x.get('ts', 0))
        
        # Получаем данные покупки
        purchase_time = last_purchase.get('ts', int(time.time()))
        product_title = last_purchase.get('title', 'VPN подписка')
        
        # VPN подписка на 30 дней
        subscription_days = 30
        
        # Дата покупки
        purchase_date = datetime.fromtimestamp(purchase_time)
        
        # Дата окончания подписки
        end_date = purchase_date + timedelta(days=subscription_days)
        
        # Сегодняшняя дата
        today = datetime.now()
        
        # Проверяем, активна ли подписка
        if today <= end_date:
            # Подписка активна
            days_left = (end_date - today).days
            
            message = (
                f"✅ <b>ВАША ПОДПИСКА АКТИВНА</b>\n\n"
                f"🌐 <b>Тариф:</b> {product_title}\n"
                f"📅 <b>Действует до:</b> <code>{end_date.strftime('%d.%m.%Y')}</code>\n"
                f"⏳ <b>Осталось дней:</b> <b>{days_left}</b>\n\n"
                f"🚀 <b>Доступные сервера:</b>\n"
                f"• США 🇺🇸 (Нью-Йорк, Лос-Анджелес)\n"
                f"• Германия 🇩🇪 (Франкфурт)\n"
                f"• Япония 🇯🇵 (Токио)\n\n"
                f"🔐 <b>Статус:</b> VPN подключен и работает"
            )
            
            return {
                "has_subscription": True,
                "status": "active",
                "message": message,
                "details": {
                    "end_date": end_date,
                    "days_left": days_left,
                    "product_title": product_title
                }
            }
        else:
            # Подписка истекла
            message = (
                f"❌ <b>ВАША ПОДПИСКА ЗАКОНЧИЛАСЬ</b>\n\n"
                f"📅 <b>Закончилась:</b> <code>{end_date.strftime('%d.%m.%Y')}</code>\n"
                f"🌐 <b>Был тариф:</b> {product_title}\n\n"
                f"🔒 <b>Статус:</b> VPN отключен\n\n"
                f"Для возобновления доступа приобретите новую подписку в каталоге."
            )
            
            return {
                "has_subscription": True,
                "status": "expired",
                "message": message,
                "details": {
                    "end_date": end_date,
                    "product_title": product_title
                }
            }
            
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return {
            "has_subscription": False,
            "status": "error",
            "message": "❌ <b>Ошибка при проверке подписки</b>\n\n"
                      "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
            "details": None
        }


async def handle_subscription_command(user_id: int, query, context):
    """
    ПРОСТОЙ обработчик кнопки "Моя подписка".
    Показывает пользователю статус его подписки.
    Сохраняет ID сообщения для последующего удаления.
    """
    try:
        # Получаем информацию
        info = get_user_subscription_info(user_id)
        
        # Импортируем клавиатуру
        from keyboards import home_only_kb
        
        # Сохраняем предыдущее сообщение для удаления
        if user_id in SUBSCRIPTION_MESSAGES:
            try:
                old_chat_id, old_msg_id = SUBSCRIPTION_MESSAGES[user_id]
                await context.bot.delete_message(chat_id=old_chat_id, message_id=old_msg_id)
            except:
                pass  # Игнорируем если не удалось удалить старое сообщение
        
        # Если подписка активна, пытаемся отправить картинку
        if info["status"] == "active":
            # Формируем абсолютный путь к картинке
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            photo_path = os.path.join(current_dir, "images", "black_online.png")
            
            if os.path.exists(photo_path):
                with open(photo_path, 'rb') as photo:
                    sent_message = await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=info["message"],
                        reply_markup=home_only_kb(),
                        parse_mode="HTML"
                    )
            else:
                # Если картинки нет, отправляем текстовое сообщение
                logger.warning(f"Картинка не найдена по пути: {photo_path}")
                sent_message = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=info["message"],
                    reply_markup=home_only_kb(),
                    parse_mode="HTML"
                )
        else:
            # Для неактивной подписки или ошибки отправляем текст
            sent_message = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=info["message"],
                reply_markup=home_only_kb(),
                parse_mode="HTML"
            )
        
        # Сохраняем ID нового сообщения
        SUBSCRIPTION_MESSAGES[user_id] = (sent_message.chat_id, sent_message.message_id)
        
        # Удаляем оригинальное сообщение с кнопкой
        try:
            await query.delete_message()
        except:
            pass  # Игнорируем если не удалось удалить
            
    except Exception as e:
        logger.error(f"Ошибка в handle_subscription_command: {e}")
        
        from keyboards import home_only_kb
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=home_only_kb()
        )


async def delete_subscription_message(user_id: int, context):
    """Удаляет сообщение о подписке пользователя"""
    if user_id in SUBSCRIPTION_MESSAGES:
        try:
            chat_id, message_id = SUBSCRIPTION_MESSAGES[user_id]
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            SUBSCRIPTION_MESSAGES.pop(user_id, None)
            return True
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение подписки: {e}")
            SUBSCRIPTION_MESSAGES.pop(user_id, None)
    return False


def clear_subscription_message(user_id: int):
    """Очищает информацию о сообщении подписки (без удаления из Telegram)"""
    SUBSCRIPTION_MESSAGES.pop(user_id, None)


# Дополнительные простые функции
def check_if_user_has_active_subscription(user_id: int) -> bool:
    """Простая проверка - есть ли активная подписка"""
    info = get_user_subscription_info(user_id)
    return info["status"] == "active"


def get_subscription_end_date_str(user_id: int) -> str:
    """Возвращает дату окончания подписки в виде строки"""
    info = get_user_subscription_info(user_id)
    
    if info["status"] == "active":
        end_date = info["details"]["end_date"]
        return end_date.strftime('%d.%m.%Y')
    elif info["status"] == "expired":
        end_date = info["details"]["end_date"]
        return f"закончилась {end_date.strftime('%d.%m.%Y')}"
    else:
        return "нет подписки"