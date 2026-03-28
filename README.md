# Lamp Store Bot

Базовый Python-сервис для кнопки-робота на сайте интернет-магазина.

Сейчас внутри нет искусственного интеллекта и нет подключения к внешнему API. Вместо этого уже есть правильная база:

- HTTP API для чата
- сессии и история сообщений
- rule-based ответы без ИИ
- репозиторий товаров
- готовая точка расширения под будущую БД и Grok

## Структура

- `app/main.py` - запуск FastAPI
- `app/api/routes/chat.py` - API чата
- `app/api/routes/products.py` - API товаров
- `app/services/chat_service.py` - логика сессий и ответов
- `app/repositories/product_repository.py` - работа с товарами
- `database/schema.sql` - схема будущей SQLite БД

## Что уже умеет бот

- создавать чат-сессию
- принимать сообщение от пользователя
- сохранять историю диалога
- искать товар по названию и ключевым словам
- отвечать по цене, наличию, доставке, возврату
- делать простую подборку товаров без ИИ

## Что потом можно подключить без ломки архитектуры

- Grok API или другой AI-провайдер
- реальную БД товаров
- базу пользователей
- оформление заказа
- FAQ, логистику и CRM

## Быстрый запуск

```powershell
cd D:\Диплом\Bot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Документация FastAPI после запуска:

- `http://127.0.0.1:8000/docs`

## Основные маршруты

- `GET /health`
- `GET /api/v1/products`
- `GET /api/v1/products/{product_id}`
- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`
- `POST /api/v1/chat/messages`

## Пример запроса на отправку сообщения

```json
{
  "session_id": null,
  "language": "ru",
  "text": "Подбери лампу для спальни",
  "metadata": {
    "source": "site-widget"
  }
}
```

## Как подключить к сайту позже

На стороне фронтенда кнопка робота должна:

1. Открывать окно чата.
2. Отправлять `fetch` на `POST /api/v1/chat/messages`.
3. Сохранять `session.id` в `localStorage` или `sessionStorage`.
4. Добавлять в окно чата и сообщение пользователя, и ответ бота.

Минимальный пример:

```js
const response = await fetch("http://127.0.0.1:8000/api/v1/chat/messages", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    session_id: sessionId,
    language: "ru",
    text: userText,
    metadata: { source: "site-widget" }
  })
});

const data = await response.json();
sessionId = data.session.id;
```

## Подключение к будущей БД товаров

Сейчас по умолчанию используется память и тестовые товары.

Когда появится SQLite база:

1. Создай файл БД по схеме из `database/schema.sql`.
2. Укажи в `.env`:

```env
PRODUCT_DB_MODE=sqlite
SQLITE_DB_PATH=database/products.db
```

Если база недоступна или пуста, сервис автоматически вернется к встроенным товарам, поэтому запуск не упадет.
