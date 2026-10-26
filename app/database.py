import os
import sqlite3
import argparse
from pathlib import Path


DATABASE_PATH = Path(
    os.environ.get(
        "APP_DATABASE_PATH",
        Path(__file__).resolve().parent.parent / "data" / "app.db",
    )
)

APPLICATION_TABLES = (
    "order_items",
    "orders",
    "temple_offerings",
    "offerings",
    "temples",
    "schema_migrations",
)

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS temples (
        temple_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS offerings (
        offering_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price_paise INTEGER NOT NULL CHECK (price_paise > 0),
        active INTEGER NOT NULL CHECK (active IN (0, 1))
    )""",
    """CREATE TABLE IF NOT EXISTS temple_offerings (
        temple_id INTEGER NOT NULL,
        offering_id INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        daily_limit INTEGER CHECK (daily_limit IS NULL OR daily_limit >= 0),
        PRIMARY KEY (temple_id, offering_id),
        FOREIGN KEY (temple_id) REFERENCES temples(temple_id),
        FOREIGN KEY (offering_id) REFERENCES offerings(offering_id)
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        temple_id INTEGER NOT NULL,
        devotee_name TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        birth_star TEXT NOT NULL,
        booking_date TEXT NOT NULL,
        status TEXT NOT NULL,
        total_paise INTEGER NOT NULL CHECK (total_paise >= 0),
        UNIQUE (order_id, temple_id),
        FOREIGN KEY (temple_id) REFERENCES temples(temple_id)
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        temple_id INTEGER NOT NULL,
        offering_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise > 0),
        FOREIGN KEY (order_id, temple_id)
            REFERENCES orders(order_id, temple_id) ON DELETE CASCADE,
        FOREIGN KEY (temple_id, offering_id)
            REFERENCES temple_offerings(temple_id, offering_id)
    )""",
    """CREATE TRIGGER IF NOT EXISTS trg_order_item_active_temple_offering
    BEFORE INSERT ON order_items
    WHEN NOT EXISTS (
        SELECT 1 FROM temple_offerings AS mapping
        JOIN offerings ON offerings.offering_id = mapping.offering_id
        WHERE mapping.temple_id = NEW.temple_id
          AND mapping.offering_id = NEW.offering_id
          AND mapping.active = 1
          AND offerings.active = 1
    )
    BEGIN
        SELECT RAISE(ABORT, 'offering is not active for this temple');
    END""",
)


def get_connection(database_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: str | Path = DATABASE_PATH) -> None:
    connection = get_connection(database_path)
    try:
        if _has_table(connection, "orders") and not _has_temple_order_schema(connection):
            raise RuntimeError(
                "The database uses the legacy order schema. Run "
                "`python -m app.database --reset --confirm-reset` to reset "
                "application data for the temple-based schema."
            )
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.commit()
        _apply_migrations(connection)
    finally:
        connection.close()


def reset_database(
    database_path: str | Path = DATABASE_PATH, *, confirm: bool = False
) -> None:
    if not confirm:
        raise ValueError("Database reset requires explicit confirmation.")

    connection = get_connection(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table_name in APPLICATION_TABLES:
            connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        _apply_migrations(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _has_temple_order_schema(connection: sqlite3.Connection) -> bool:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(orders)")
    }
    return "temple_id" in columns


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


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
        2: (
            """CREATE TABLE temple_offerings_new (
                temple_id INTEGER NOT NULL,
                offering_id INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                daily_limit INTEGER CHECK (daily_limit IS NULL OR daily_limit >= 0),
                PRIMARY KEY (temple_id, offering_id),
                FOREIGN KEY (temple_id) REFERENCES temples(temple_id),
                FOREIGN KEY (offering_id) REFERENCES offerings(offering_id)
            )""",
            """INSERT INTO temple_offerings_new
               (temple_id, offering_id, active, daily_limit)
               SELECT temple_id, offering_id, active, daily_limit
               FROM temple_offerings""",
            "DROP TRIGGER IF EXISTS trg_order_item_active_temple_offering",
            "DROP TABLE temple_offerings",
            "ALTER TABLE temple_offerings_new RENAME TO temple_offerings",
            """CREATE TRIGGER trg_order_item_active_temple_offering
            BEFORE INSERT ON order_items
            WHEN NOT EXISTS (
                SELECT 1 FROM temple_offerings AS mapping
                JOIN offerings ON offerings.offering_id = mapping.offering_id
                WHERE mapping.temple_id = NEW.temple_id
                  AND mapping.offering_id = NEW.offering_id
                  AND mapping.active = 1
                  AND offerings.active = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'offering is not active for this temple');
            END""",
            "CREATE INDEX IF NOT EXISTS idx_orders_temple_booking_date_order_id "
            "ON orders (temple_id, booking_date, order_id)",
            "CREATE INDEX IF NOT EXISTS idx_order_items_order_offering_quantity "
            "ON order_items (order_id, offering_id, quantity)",
        ),
    }

    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    for version, statements in migrations.items():
        owns_transaction = not connection.in_transaction
        rebuilds_mapping_table = version == 2 and owns_transaction
        if rebuilds_mapping_table:
            connection.execute("PRAGMA foreign_keys = OFF")
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        try:
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone()
            if applied is None:
                migration_statements = (
                    statements if owns_transaction or version != 2 else statements[-2:]
                )
                for statement in migration_statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction:
                connection.rollback()
            raise
        finally:
            if rebuilds_mapping_table:
                connection.execute("PRAGMA foreign_keys = ON")
        if rebuilds_mapping_table:
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    "Foreign key violations found after temple-offering migration."
                )


def _run_reset_cli() -> None:
    parser = argparse.ArgumentParser(description="Reset application database schema and data.")
    parser.add_argument(
        "--reset", action="store_true", help="drop and recreate application tables"
    )
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="confirm deleting all application data in the selected database",
    )
    arguments = parser.parse_args()
    if not arguments.reset or not arguments.confirm_reset:
        parser.error("both --reset and --confirm-reset are required")
    reset_database(confirm=True)
    print(f"Reset application tables in {DATABASE_PATH}")


if __name__ == "__main__":
    _run_reset_cli()