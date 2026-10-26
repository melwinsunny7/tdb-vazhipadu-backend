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

## Temple-Based Bookings

Create a temple with `POST /temples`, list temples with `GET /temples`, and map a shared offering with `POST /temples/{temple_id}/offerings`. Get a temple's offerings, shared prices, availability, and configured limits with `GET /temples/{temple_id}/offerings`. The offering catalog and its price remain shared across temples.

Each temple-offering mapping has its own active flag and optional `daily_limit`; `null` means unlimited and `0` rejects all positive-quantity bookings. Set or clear the value with `PATCH /temples/{temple_id}/offerings/{offering_id}` and a body such as `{"daily_limit": 12}`, `{"daily_limit": 0}`, or `{"daily_limit": null}`. Capacity counts item quantities for the selected temple and requested booking date. All existing orders consume capacity because cancellation is not implemented. Booking checks and inserts use a SQLite write transaction; transient database contention returns a retryable `503` response. Daily-limit reporting is not implemented.

Order creation requires `temple_id` alongside the existing devotee, date, and item fields. Each offering must be active in the shared catalog and actively mapped to that temple. Order items preserve the shared offering price at booking time.

## Explicit Development Database Reset

Ordinary application startup does not delete data. The temple schema is incompatible with the previous order schema, so startup detects an existing legacy database and stops with reset instructions instead of silently discarding records.

The explicit reset deletes and recreates only these application tables and their data: `order_items`, `orders`, `temple_offerings`, `offerings`, `temples`, and `schema_migrations`. Other tables and files are left untouched. Back up any data you need before resetting.

To reset the configured development database (`APP_DATABASE_PATH`, or `data/app.db` by default), run:

```bash
python -m app.database --reset --confirm-reset
```

Both flags are required. Tests use temporary database paths and must not run this command against the development database.

## Test

```bash
pytest
```
