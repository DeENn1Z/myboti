# init_database.py - Исправленная версия

import sqlite3
import json
import os

def init_database():
    """Создаёт базу данных с правильной структурой"""
    
    if os.path.exists('bot_database.db'):
        os.remove('bot_database.db')
        print("[INFO] Удалена старая база данных")
    
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            subscription_end TEXT,
            is_admin INTEGER DEFAULT 0,
            reg_date TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ТАБЛИЦА ТОВАРОВ - КАК В ВАШЕМ products.json
    cursor.execute('''
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            price_stars INTEGER,
            deliver_text TEXT,
            deliver_url TEXT,
            price_rub INTEGER,
            days INTEGER  -- Добавляем поле для дней подписки
        )
    ''')
    
    # Таблица платежей
    cursor.execute('''
        CREATE TABLE payments (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            product_id TEXT,
            amount REAL,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    print("[SUCCESS] Таблицы созданы успешно!")
    
    # Загружаем товары из products.json
    try:
        with open('products.json', 'r', encoding='utf-8') as f:
            products_data = json.load(f)
        
        # Ваш products.json - это список товаров
        if isinstance(products_data, list):
            products = products_data
        else:
            products = []
        
        loaded_count = 0
        for product in products:
            # Преобразуем title в name для совместимости
            title = product.get('title', 'Без названия')
            
            # Извлекаем количество дней из названия
            days = 0
            title_lower = title.lower()
            if '2 дня' in title_lower or '2 дня' in title_lower:
                days = 2
            elif '1 месяц' in title_lower or '1 месяц' in title_lower:
                days = 30
            elif '2 месяца' in title_lower or '2 месяца' in title_lower:
                days = 60
            elif '3 месяца' in title_lower or '3 месяца' in title_lower:
                days = 90
            elif '6 месяцев' in title_lower or '6 месяцев' in title_lower:
                days = 180
            elif '1 год' in title_lower or '1 год' in title_lower:
                days = 365
            
            # Вставляем товар с правильной структурой
            cursor.execute('''
                INSERT OR REPLACE INTO products 
                (id, title, description, price_stars, deliver_text, deliver_url, price_rub, days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(product.get('id', '')),
                title,
                str(product.get('description', '')),
                int(product.get('price_stars', 0)),
                str(product.get('deliver_text', '')),
                str(product.get('deliver_url', '')),
                int(product.get('price_rub', 0)),
                days
            ))
            loaded_count += 1
        
        conn.commit()
        print(f"[SUCCESS] Загружено {loaded_count} товаров")
        
        # Показать загруженные товары для проверки
        cursor.execute("SELECT id, title, price_rub, days FROM products")
        products = cursor.fetchall()
        print("\n=== ЗАГРУЖЕННЫЕ ТОВАРЫ ===")
        for product in products:
            print(f"ID: {product[0]}, Название: {product[1]}, Цена: {product[2]} руб., Дней: {product[3]}")
        
    except Exception as e:
        print(f"[ERROR] Ошибка загрузки товаров: {e}")
        import traceback
        traceback.print_exc()
    
    # Закрываем соединение
    conn.close()
    print("\n[SUCCESS] База данных готова к работе!")
    return True

if __name__ == "__main__":
    print("=== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ===")
    init_database()
    print("\nТеперь запустите бота: python bot.py")