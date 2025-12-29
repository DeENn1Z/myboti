from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Optional
from data_tools import Product

def home_only_kb() -> InlineKeyboardMarkup:
    """Клавиатура только с кнопкой Главное меню"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")]
    ])

def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню пользователя"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Купить подписку", callback_data="menu:catalog")],  # ← ИЗМЕНЕНИЕ
        [InlineKeyboardButton("📅 Моя подписка", callback_data="menu:mysub")],
        [InlineKeyboardButton("🎁 Ввести промокод", callback_data="menu:promocode")],
        [InlineKeyboardButton("💬 Поддержка", callback_data="menu:support")],
    ])


def catalog_kb(products: List[Product]) -> InlineKeyboardMarkup:
    """Клавиатура каталога товаров"""
    rows = []
    for p in products[:50]:  # Ограничение 50 товаров на одной странице
        button_text = f"{p.title[:30]} — {p.price_stars}⭐ / {p.price_rub}₽"
        rows.append([InlineKeyboardButton(button_text, callback_data=f"prod:{p.id}")])
    
    # Заменяем "Назад" на "Главное меню"
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def product_kb(product_id: str) -> InlineKeyboardMarkup:
    """Клавиатура товара"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Выбрать способ оплаты", callback_data=f"choose_pay:{product_id}")],
        [InlineKeyboardButton("⬅️ Назад в подписки", callback_data="menu:catalog")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
    ])


def payment_methods_kb(product_id: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа оплаты"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Оплата Telegram Stars", callback_data=f"pay_stars:{product_id}")],
        [InlineKeyboardButton("💰 Оплата Бансковской Картой", callback_data=f"pay_yookassa:{product_id}")],
        [InlineKeyboardButton("⬅️ Назад к товару", callback_data=f"prod:{product_id}")],
    ])


def back_to_product_kb(product_id: str) -> InlineKeyboardMarkup:
    """Клавиатура возврата к товару"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад к товару", callback_data=f"prod:{product_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
    ])


def admin_menu_kb(csrf_token: Optional[str] = None) -> InlineKeyboardMarkup:
    """Защищенная клавиатура админ-панели"""
    if csrf_token:
        # Добавляем CSRF токен ко всем кнопкам
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Товары", callback_data=f"admin:products:{csrf_token}")],
            [InlineKeyboardButton("➕ Добавить товар", callback_data=f"admin:add_product:{csrf_token}")],
            [InlineKeyboardButton("✏️ Редактировать товар", callback_data=f"admin:edit_product:{csrf_token}")],
            [InlineKeyboardButton("🗑 Удалить товар", callback_data=f"admin:delete_product:{csrf_token}")],
            [InlineKeyboardButton("📊 Статистика", callback_data=f"admin:stats:{csrf_token}")],
            [InlineKeyboardButton("📜 Последние покупки", callback_data=f"admin:last_purchases:{csrf_token}")],
            [InlineKeyboardButton("💳 Платежи ЮКассы", callback_data=f"admin:yookassa_payments:{csrf_token}")],
            [InlineKeyboardButton("🧹 Сбросить статистику", callback_data=f"admin:reset_stats:{csrf_token}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
        ])
    else:
        # Без CSRF токена (для обратной совместимости)
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Товары", callback_data="admin:products")],
            [InlineKeyboardButton("➕ Добавить товар", callback_data="admin:add_product")],
            [InlineKeyboardButton("✏️ Редактировать товар", callback_data="admin:edit_product")],
            [InlineKeyboardButton("🗑 Удалить товар", callback_data="admin:delete_product")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
            [InlineKeyboardButton("📜 Последние покупки", callback_data="admin:last_purchases")],
            [InlineKeyboardButton("💳 Платежи ЮКассы", callback_data="admin:yookassa_payments")],
            [InlineKeyboardButton("🧹 Сбросить статистику", callback_data="admin:reset_stats")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
        ])


def edit_select_product_kb(products: List[Product], csrf_token: Optional[str] = None) -> InlineKeyboardMarkup:
    """Защищенная клавиатура выбора товара для редактирования"""
    rows = []
    for p in products[:30]:  # Ограничение 30 товаров
        button_text = f"{p.title[:25]} ({p.id}) - {p.price_stars}⭐"
        if csrf_token:
            rows.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"edit_select:{p.id}:{csrf_token}"
            )])
        else:
            rows.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"edit_select:{p.id}"
            )])
    
    if csrf_token:
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"admin:back:{csrf_token}")])
    else:
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:back")])
    
    return InlineKeyboardMarkup(rows)