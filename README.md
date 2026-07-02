# Bot sklepu z lampami

Backend Python dla chatbota sklepu z lampami.

Projekt jest przygotowany pod klucz API Grok, ale może działać bez AI. W trybie zapasowym bot wyszukuje produkty w katalogu i zwraca prostą odpowiedź bez zewnętrznego modelu.

## Architektura

```text
widget czatu na stronie
  -> backend FastAPI
  -> repozytorium produktów
  -> Microsoft SQL Server LocalDB
  -> Grok API albo odpowiedź zapasowa
  -> odpowiedź do strony
```

## Główne elementy

- `app/main.py` - aplikacja FastAPI.
- `app/api/routes/chat.py` - endpointy API czatu.
- `app/api/routes/products.py` - endpointy API produktów.
- `app/services/chat_service.py` - główny przepływ rozmowy.
- `app/services/ai_provider.py` - integracja Grok i odpowiedź zapasowa bez AI.
- `app/repositories/product_repository.py` - wyszukiwanie produktów w Microsoft SQL Server albo w pamięci.
- `database/schema.sql` - odwołanie do głównego schematu z `DataBace/02_init_schema.sql`.

## Baza danych

Główna baza projektu:

```text
DiplomaStore
```

Domyślne połączenie:

```env
SQL_SERVER_CONNECTION_STRING=DRIVER={ODBC Driver 18 for SQL Server};SERVER=(localdb)\MSSQLLocalDB;DATABASE=DiplomaStore;Trusted_Connection=yes;TrustServerCertificate=yes;
```

Główny schemat znajduje się w:

```text
DataBace/02_init_schema.sql
```

## Środowisko

Skopiuj `.env.example` do `.env` i uzupełnij tylko potrzebne wartości.

Tryb Microsoft SQL Server:

```env
PRODUCT_DB_MODE=mssql
SQL_SERVER_CONNECTION_STRING=DRIVER={ODBC Driver 18 for SQL Server};SERVER=(localdb)\MSSQLLocalDB;DATABASE=DiplomaStore;Trusted_Connection=yes;TrustServerCertificate=yes;
```

Tryb Grok:

```env
AI_PROVIDER=grok
GROK_API_KEY=your_xai_api_key_here
GROK_MODEL=grok-4-1-fast
```

Nie wpisuj klucza API Grok bezpośrednio w kodzie źródłowym.

## Uruchomienie

```powershell
cd D:\Diploma\Bot
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Dokumentacja API po uruchomieniu:

```text
http://127.0.0.1:8001/docs
```

## API

- `GET /health`
- `GET /api/v1/products`
- `GET /api/v1/products/{product_id}`
- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}`
- `POST /api/v1/chat/messages`

Przykładowe zapytanie do czatu:

```json
{
  "session_id": null,
  "language": "pl",
  "text": "Doradź lampę do sypialni do 50 PLN",
  "metadata": {
    "source": "site-widget"
  }
}
```
