# tdb-vazhipadu-backend

vazhipadu (temple offering) booking service for a temple board.

## Requirements

- Python 3.12

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. The health endpoint is `GET /health`.
SQLite creates its local database at `data/app.db` when the application starts.

## Order Search

`GET /orders` returns an `orders` array and pagination metadata:

```json
{
  "orders": [],
  "page": 1,
  "page_size": 20,
  "total": 0,
  "total_pages": 0
}
```

Optional query parameters are `booking_date` (`YYYY-MM-DD`), `status`, `phone_number`, `page` (starts at 1), and `page_size` (defaults to 20, maximum 100). Filters combine with AND. Phone search is an exact match; phone values are stored and searched as supplied, including an optional leading `+`.

Results are ordered by descending order ID for deterministic page boundaries. Pagination uses SQL `LIMIT` and `OFFSET`; very deep pages can become slower because SQLite must walk past earlier matching rows. Search indexes are installed through a repeatable versioned migration when the application initializes its database.

## Test

```bash
pytest
```
