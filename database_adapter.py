# database_adapter.py - Мост между старым кодом и новой базой данных
import sqlite3
import json
from datetime import datetime, timedelta

class DatabaseAdapter:
    """Адаптер для работы с базой данных SQLite"""
    
    def __init__(self, db_path='bot_database.db'):
        self.db_path = db_path
    
    def _get_connection(self):
        """Создаёт подключение к базе данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ========== ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    def add_user(self, user_id, username="", full_name=""):
        """Добавляет пользователя в базу"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
            """, (user_id, username, full_name))
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB Ошибка] Не удалось добавить пользователя {user_id}: {e}")
            return False
        finally:
            conn.close()
    
    def get_user(self, user_id):
        """Получает информацию о пользователе"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return dict(user)
        return None
    
    def update_subscription(self, user_id, days_to_add):
        """Обновляет подписку пользователя"""
        user = self.get_user(user_id)
        if not user:
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now().date()
        
        # Определяем текущую дату окончания подписки
        if user.get('subscription_end'):
            try:
                current_end = datetime.strptime(user['subscription_end'], '%Y-%m-%d').date()
                if current_end > now:
                    new_end = current_end + timedelta(days=days_to_add)
                else:
                    new_end = now + timedelta(days=days_to_add)
            except:
                new_end = now + timedelta(days=days_to_add)
        else:
            new_end = now + timedelta(days=days_to_add)
        
        # Обновляем в базе
        cursor.execute("""
            UPDATE users 
            SET subscription_end = ? 
            WHERE user_id = ?
        """, (new_end.strftime('%Y-%m-%d'), user_id))
        
        conn.commit()
        conn.close()
        return True
    
    def check_subscription(self, user_id):
        """Проверяет активность подписки"""
        user = self.get_user(user_id)
        if not user or not user.get('subscription_end'):
            return False, 0
        
        now = datetime.now().date()
        try:
            end_date = datetime.strptime(user['subscription_end'], '%Y-%m-%d').date()
        except:
            return False, 0
        
        if end_date > now:
            days_left = (end_date - now).days
            return True, days_left
        return False, 0
    
    # ========== ФУНКЦИИ ДЛЯ ТОВАРОВ ==========
    
    def get_product(self, product_id):
        """Получает товар по ID (адаптирует структуру для старого кода)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
        conn.close()
        
        if product:
            product_dict = dict(product)
            # Преобразуем структуру для совместимости со старым кодом
            return {
                'id': product_dict['id'],
                'name': product_dict['title'],
                'description': product_dict['description'],
                'price': product_dict['price_rub'],  # Основная цена в рублях
                'price_stars': product_dict['price_stars'],  # Цена в звёздах
                'days': product_dict['days'],
                'deliver_text': product_dict['deliver_text'],
                'deliver_url': product_dict['deliver_url'],
                'currency': 'RUB',
                'is_visible': True
            }
        return None
    
    def get_all_products(self):
        """Получает все товары"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM products ORDER BY price_rub")
        products = cursor.fetchall()
        conn.close()
        
        return [dict(product) for product in products]
    
    # ========== ФУНКЦИИ ДЛЯ СОВМЕСТИМОСТИ ==========
    
    def get_products_for_menu(self):
        """Возвращает товары в формате для меню (как старый load_products)"""
        products = self.get_all_products()
        
        # Преобразуем в старый формат
        result = {"products": []}
        for product in products:
            result["products"].append({
                'id': product['id'],
                'name': product['title'],
                'description': product['description'],
                'price': product['price_rub'],
                'price_stars': product['price_stars'],
                'days': product['days'],
                'deliver_text': product['deliver_text'],
                'deliver_url': product['deliver_url']
            })
        
        return result

# Создаём глобальный экземпляр адаптера
db = DatabaseAdapter()

# ========== ФУНКЦИИ-ОБЁРТКИ ДЛЯ ПРОСТОГО ИМПОРТА ==========

def add_user_to_db(user_id, username="", full_name=""):
    return db.add_user(user_id, username, full_name)

def get_user_from_db(user_id):
    return db.get_user(user_id)

def update_subscription_in_db(user_id, days_to_add):
    return db.update_subscription(user_id, days_to_add)

def check_subscription_in_db(user_id):
    return db.check_subscription(user_id)

def get_product_from_db(product_id):
    return db.get_product(product_id)

def get_all_products_from_db():
    return db.get_all_products()

def load_products_from_db():
    """Аналог старой функции load_products() для совместимости"""
    return get_products_for_menu_from_db()

def get_products_for_menu_from_db():
    return db.get_products_for_menu()