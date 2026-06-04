# Lamp Store Bot

Python backend for the lamp store chatbot.

The project is prepared for a future Grok API key, but it can run without AI. In the safe default mode it uses demo products and returns catalog-based fallback replies.

## Architecture

```text
site chat widget
  -> FastAPI backend
  -> product repository
  -> Microsoft SQL Server or demo products
  -> AI provider
  -> Grok API or fallback provider
  -> response back to the site
```

## Main Parts

- `app/main.py` - FastAPI application.
- `app/api/routes/chat.py` - chat API endpoints.
- `app/api/routes/products.py` - product API endpoints.
- `app/services/chat_service.py` - main chat flow.
- `app/services/ai_provider.py` - Grok integration point and no-AI fallback.
- `app/repositories/product_repository.py` - product lookup from memory or Microsoft SQL Server.
- `database/schema.sql` - Microsoft SQL Server schema for products and future chat history.

## Environment

Copy `.env.example` to `.env` and fill only what you need.

Default safe mode:

```env
PRODUCT_DB_MODE=memory
AI_PROVIDER=none
```

Microsoft SQL Server mode:

```env
PRODUCT_DB_MODE=mssql
SQL_SERVER_CONNECTION_STRING=DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=DiplomaStore;Trusted_Connection=yes;TrustServerCertificate=yes;
```

Future Grok mode:

```env
AI_PROVIDER=grok
GROK_API_KEY=your_xai_api_key_here
GROK_MODEL=grok-4-1-fast
```

Do not write the Grok API key directly in source code.

## Run

```powershell
cd D:\Диплом\Bot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API documentation after startup:

```text
http://127.0.0.1:8000/docs
```

## API

- `GET /health`
- `GET /api/v1/products`
- `GET /api/v1/products/{product_id}`
- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`
- `POST /api/v1/chat/messages`

Example chat request:

```json
{
  "session_id": null,
  "language": "ru",
  "text": "Посоветуй лампу для спальни до 50 PLN",
  "metadata": {
    "source": "site-widget"
  }
}
```

## How Grok Will Be Connected

The site sends a message to `POST /api/v1/chat/messages`.

The backend searches matching products in the database and sends only those products to Grok. Grok receives the user's question and real product data, then returns a consultant-style answer.

This is cheaper and safer than sending the whole catalog to AI on every message.
