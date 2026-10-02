from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp.auth.brands import normalize_brand_name
from webapp.auth.service import AuthService
from webapp.auth.store import AuthStore


class BrandBindingTests(unittest.TestCase):
    def test_normalization_ignores_full_width_spacing_and_case(self):
        display_name, brand_key = normalize_brand_name("  Ｎｉｋｅ   Air  ")

        self.assertEqual(display_name, "Nike Air")
        self.assertEqual(brand_key, "nike air")

    def test_existing_user_database_gets_brand_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE users (
                        id TEXT PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        display_name TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_login_at TEXT
                    )
                    """
                )
                connection.commit()

            store = AuthStore(path)
            with sqlite3.connect(path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(users)")
                }
            self.assertTrue({"brand_name", "brand_key"}.issubset(columns))
            self.assertEqual(store.user_count(), 0)

    def test_registered_user_keeps_display_name_and_stable_brand_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuthStore(Path(directory) / "auth.sqlite3")
            service = AuthService(store)
            admin = service.bootstrap_admin(
                username="admin",
                display_name="Administrator",
                password="admin-password-123",
                brand_name="Example Brand",
            )
            operator = service.register_operator(
                username="operator",
                display_name="Operator",
                password="operator-password-123",
                ip_address="127.0.0.1",
                brand_name="  Ｅｘａｍｐｌｅ   BRAND ",
            )

            self.assertEqual(admin.brand_key, "example brand")
            self.assertEqual(operator.brand_name, "Example BRAND")
            self.assertEqual(operator.brand_key, "example brand")


if __name__ == "__main__":
    unittest.main()
