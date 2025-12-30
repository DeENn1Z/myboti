from database_adapter import add_user_to_db

# Ваш Telegram ID
YOUR_ID = 7784754900

# Тест 1: Добавляем нового пользователя
result = add_user_to_db(YOUR_ID, "test_user", "Тестовый Пользователь")
if result:
    print(f"✅ Пользователь {YOUR_ID} добавлен в базу")
else:
    print(f"❌ Ошибка при добавлении пользователя")

# Тест 2: Пробуем добавить того же пользователя снова (не должно быть ошибки)
result2 = add_user_to_db(YOUR_ID, "another_name", "Другое Имя")
if result2:
    print(f"✅ Повторное добавление пользователя {YOUR_ID} прошло успешно")
else:
    print(f"❌ Ошибка при повторном добавлении")