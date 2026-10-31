"""Additive migration for authentication columns on existing users tables.

Run once before starting a WSGI deployment:
    python scripts/migrate_auth_schema.py
"""
from sqlalchemy import inspect

from app import app, db


ADDITIVE_USER_COLUMNS = {
    "password_hash": "VARCHAR(255)",
    "password_reset_token_hash": "VARCHAR(64)",
    "password_reset_sent_at": "DATETIME",
}


def migrate_user_auth_columns(engine):
    """Add missing nullable auth columns without modifying existing rows."""
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        raise RuntimeError("Table 'users' does not exist; refusing to create or alter the schema.")

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        for column_name, column_type in ADDITIVE_USER_COLUMNS.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )


if __name__ == "__main__":
    with app.app_context():
        migrate_user_auth_columns(db.engine)
    print("Authentication schema migration completed. Existing user data was preserved.")
