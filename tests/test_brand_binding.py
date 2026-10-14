from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi import HTTPException

from webapp.api.brand_data import match_data_brand, resolve_data_brand
from webapp.auth.brands import normalize_brand_name
from webapp.auth.service import AuthService
from webapp.auth.store import AuthStore
from webapp.mysql_demo import MySQLDemoError


class BrandBindingTests(unittest.TestCase):
    def test_saved_brand_id_wins_over_account_name_without_writes(self):
        database = Mock(configured=True)
        database.execute.return_value = [(1, "星巴克新名称")]
        user = Mock(id="existing-user", brand_name="其他品牌")
        self.assertEqual(resolve_data_brand(database, user), {"id": 1, "name": "星巴克新名称"})
        database.execute.assert_called_once()
        self.assertEqual(database.execute.call_args.args[1], ("existing-user",))
        self.assertTrue(database.execute.call_args.args[0].startswith("SELECT"))

    def test_deleted_saved_brand_does_not_fall_back_to_account_name(self):
        database = Mock(configured=True)
        database.execute.return_value = [(9, None)]
        with self.assertRaises(HTTPException) as raised:
            resolve_data_brand(database, Mock(id="existing-user", brand_name="星巴克"))
        self.assertEqual(raised.exception.status_code, 403)
        database.execute.assert_called_once()

    def test_initial_binding_does_not_overwrite_a_concurrent_saved_binding(self):
        database = Mock(configured=True)
        database.execute.side_effect = [[], [(1, "星巴克")], [], [(2, "其他品牌")]]
        self.assertEqual(resolve_data_brand(database, Mock(id="new-user", brand_name="星巴克")), {"id": 2, "name": "其他品牌"})
        query, values = database.execute.call_args_list[2].args
        self.assertIn("INSERT IGNORE", query)
        self.assertEqual(values, ("new-user", 1))

    def test_data_brand_match_normalizes_names_without_fuzzy_matching(self):
        brands = [{"id": 1, "name": "Nike Air"}, {"id": 2, "name": "Nike"}]
        self.assertEqual(match_data_brand("  ＮＩＫＥ　 air ", brands), brands[0])
        self.assertIsNone(match_data_brand("Nike Ai", brands))
        self.assertIsNone(match_data_brand("", brands))

    def test_duplicate_normalized_data_brands_are_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            match_data_brand("Nike", [{"id": 1, "name": "Nike"}, {"id": 2, "name": "ＮＩＫＥ"}])
        self.assertEqual(raised.exception.status_code, 409)

    def test_missing_brand_and_database_failures_do_not_grant_access(self):
        database = Mock(configured=True)
        database.execute.side_effect = [[], [(2, "其他品牌")]]
        user = Mock(id="missing-user", brand_name="星巴克")
        with self.assertRaises(HTTPException) as raised:
            resolve_data_brand(database, user)
        self.assertEqual(raised.exception.status_code, 403)
        database.execute.side_effect = MySQLDemoError("测试连接失败")
        with self.assertRaises(HTTPException) as raised:
            resolve_data_brand(database, user)
        self.assertEqual(raised.exception.status_code, 503)
        database.configured = False
        with self.assertRaises(HTTPException) as raised:
            resolve_data_brand(database, user)
        self.assertEqual(raised.exception.status_code, 503)

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
