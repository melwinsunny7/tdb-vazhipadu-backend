import os
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(
    os.environ.get(
        "APP_DATABASE_PATH",
        Path(__file__).resolve().parent.parent / "data" / "app.db",
    )
)


def get_connection(database_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: str | Path = DATABASE_PATH) -> None:
    connection = get_connection(database_path)
    try:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS offerings (
                    offering_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    price_paise INTEGER NOT NULL CHECK (price_paise > 0),
                    active INTEGER NOT NULL CHECK (active IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    devotee_name TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    birth_star TEXT NOT NULL,
                    booking_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_paise INTEGER NOT NULL CHECK (total_paise >= 0)
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    offering_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise > 0),
                    FOREIGN KEY (order_id) REFERENCES orders(order_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (offering_id) REFERENCES offerings(offering_id)
                );
                """
            )
        _apply_migrations(connection)
    finally:
        connection.close()


def _apply_migrations(connection: sqlite3.Connection) -> None:
    migrations = {
        1: (
            "CREATE INDEX IF NOT EXISTS idx_orders_booking_date_order_id "
            "ON orders (booking_date, order_id DESC)",
            "CREATE INDEX IF NOT EXISTS idx_orders_status_order_id "
            "ON orders (status, order_id DESC)",
            "CREATE INDEX IF NOT EXISTS idx_orders_phone_number_order_id "
            "ON orders (phone_number, order_id DESC)",
        ),
    }

    with connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version INTEGER PRIMARY KEY,
                   applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        applied_versions = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for version, statements in migrations.items():
            if version in applied_versions:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )