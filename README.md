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

## Test

```bash
pytest
```
