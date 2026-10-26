from app.database import get_connection, initialize_database


def test_initialize_database_creates_directory_and_database(tmp_path) -> None:
    database_path = tmp_path / "data" / "test.db"

    initialize_database(database_path)

    assert database_path.is_file()

    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()