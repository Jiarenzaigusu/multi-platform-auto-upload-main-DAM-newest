from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from webapp.mysql_demo import (
    MySQLDemoError,
    MySQLDatabase,
    MySQLSettings,
    check_mysql_connection,
    main,
    prompt_for_mysql_password,
)
from webapp.dashboard import DashboardRepository


class MySQLSettingsTests(unittest.TestCase):
    def test_password_prompt_fills_only_the_missing_password(self):
        settings = MySQLSettings(
            host="db.internal", database="mpau_business", user="mpau_app"
        )
        with patch(
            "webapp.mysql_demo.getpass.getpass", return_value="secret"
        ) as password_prompt:
            prompted = prompt_for_mysql_password(settings)

        self.assertEqual(prompted.password, "secret")
        password_prompt.assert_called_once_with("请输入 MySQL 密码: ")

    def test_reads_split_environment_variables(self):
        with patch.dict(
            "os.environ",
            {
                "MPAU_MYSQL_HOST": "db.internal",
                "MPAU_MYSQL_PORT": "3307",
                "MPAU_MYSQL_DATABASE": "mpau_business",
                "MPAU_MYSQL_USER": "mpau_app",
                "MPAU_MYSQL_PASSWORD": "secret",
                "MPAU_MYSQL_CONNECT_TIMEOUT": "7",
            },
            clear=True,
        ):
            settings = MySQLSettings.from_environment()

        self.assertTrue(settings.configured)
        self.assertEqual(settings.host, "db.internal")
        self.assertEqual(settings.port, 3307)
        self.assertEqual(settings.connect_timeout, 7)

    def test_reports_missing_required_settings(self):
        settings = MySQLSettings(host="127.0.0.1")

        self.assertFalse(settings.configured)
        self.assertEqual(
            settings.missing_environment_variables,
            (
                "MPAU_MYSQL_DATABASE",
                "MPAU_MYSQL_USER",
                "MPAU_MYSQL_PASSWORD",
            ),
        )


class MySQLConnectionDemoTests(unittest.TestCase):
    def test_database_reuses_connection_for_future_queries(self):
        settings = MySQLSettings(
            host="127.0.0.1",
            database="mpau_business",
            user="mpau_app",
            password="secret",
        )
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.side_effect = [[("8.4.0", "mpau_business")], [("value",)]]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.ping.return_value = None
        connect = MagicMock(return_value=connection)

        with patch("webapp.mysql_demo.pymysql", create=True):
            database = MySQLDatabase(settings)
            with patch.dict("sys.modules", {"pymysql": MagicMock(connect=connect)}):
                self.assertEqual(database.check()["server_version"], "8.4.0")
                self.assertEqual(database.execute("SELECT value"), [("value",)])
            database.close()

        connect.assert_called_once()
        connection.ping.assert_called_once_with(reconnect=True)
        connection.close.assert_called_once_with()

    def test_database_accepts_write_queries_without_a_result_set(self):
        settings = MySQLSettings(
            host="127.0.0.1",
            database="mpau_business",
            user="mpau_app",
            password="secret",
        )
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.description = None
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connect = MagicMock(return_value=connection)

        with patch.dict("sys.modules", {"pymysql": MagicMock(connect=connect)}):
            database = MySQLDatabase(settings)
            self.assertEqual(
                database.execute(
                    "INSERT INTO demo(value) VALUES (%s)", ("value",)
                ),
                [],
            )
            database.close()

        cursor.execute.assert_called_once_with(
            "INSERT INTO demo(value) VALUES (%s)", ("value",)
        )

    def test_runs_read_only_connectivity_query(self):
        settings = MySQLSettings(
            host="127.0.0.1",
            database="mpau_business",
            user="mpau_app",
            password="secret",
        )
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchone.return_value = ("8.4.0", "mpau_business")
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connect = MagicMock(return_value=connection)

        result = check_mysql_connection(settings, connect=connect)

        cursor.execute.assert_called_once_with("SELECT VERSION(), DATABASE()")
        connection.close.assert_called_once_with()
        self.assertEqual(result["server_version"], "8.4.0")
        self.assertTrue(result["connected"])

    def test_never_exposes_password_in_connection_error(self):
        settings = MySQLSettings(
            host="db.example",
            database="mpau_business",
            user="mpau_app",
            password="top-secret",
        )

        with self.assertRaises(MySQLDemoError) as context:
            check_mysql_connection(
                settings,
                connect=MagicMock(side_effect=RuntimeError("bad top-secret")),
            )

        self.assertNotIn("top-secret", str(context.exception))
        self.assertIn("***", str(context.exception))

    def test_cli_prompts_for_password_when_environment_omits_it(self):
        environment = {
            "MPAU_MYSQL_HOST": "db.internal",
            "MPAU_MYSQL_PORT": "3306",
            "MPAU_MYSQL_DATABASE": "mpau_business",
            "MPAU_MYSQL_USER": "mpau_app",
        }
        with patch.dict("os.environ", environment, clear=True), patch(
            "webapp.mysql_demo.getpass.getpass", return_value="secret"
        ) as password_prompt, patch(
            "webapp.mysql_demo.check_mysql_connection",
            return_value={
                "host": "db.internal",
                "port": 3306,
                "database": "mpau_business",
                "server_version": "8.4.0",
            },
        ) as check:
            exit_code = main()

        self.assertEqual(exit_code, 0)
        password_prompt.assert_called_once_with("请输入 MySQL 密码: ")
        self.assertEqual(check.call_args.args[0].password, "secret")


class DashboardRepositoryTests(unittest.TestCase):
    def test_monthly_brand_metrics_and_tags_use_only_bound_brand(self):
        database = MagicMock()
        database.settings.database = "starbucks"

        def execute(query, parameters=None):
            self.assertEqual(parameters[0], 7)
            if "GROUP BY `年份`, `下载周期`, `汇总分类`" in query:
                return [
                    (2026, "8月", "图文", "", 1, 100, 130, 4, 20, 12, 30),
                    (2026, "8月", "往期视频", "", 1, 100, 120, 4, 19.5, 8, 20),
                    (2026, "7月", "图文", "", 1, 90, 120, 3, 10, 9, 15),
                ]
            if "COUNT(*)" in query:
                return [
                    (2026, "8月", 2, 100, 250, 39.5, 20, 200, 8, 30),
                    (2026, "7月", 1, 50, 120, 10, 9, 90, 3, 12),
                ]
            return [
                ("图文", "", "123", "真实作品", "2025-11-29 21:00:00", 100, 20, 12, 30),
                ("图文", "", "456", "另一篇图文", "2026-03-15 20:00:00", 50, 0, 1, 5),
            ]

        database.execute.side_effect = execute
        payload = DashboardRepository(database).load(7, "星巴克")

        self.assertEqual(payload["selected_period"], "2026-08")
        self.assertEqual(payload["brand"], {"id": 7, "name": "星巴克"})
        self.assertEqual(payload["summary"]["current"]["content_viewers"], 100)
        self.assertEqual(payload["summary"]["current"]["impressions"], 250)
        self.assertEqual(payload["comparisons"]["previous_week"]["values"]["content_viewers"], 50)
        self.assertEqual(payload["tags"]["video"][0]["category"], "往期视频")
        self.assertEqual(payload["tags"]["image"][0]["subcategory"], "")
        self.assertEqual(payload["tags"]["image"][0]["samples"][0]["title"], "真实作品")
        self.assertEqual(payload["tags"]["image"][0]["samples"][0]["exposure"], 100)
        self.assertEqual(payload["tags"]["image"][0]["clicks"], 30)
        self.assertEqual(payload["tags"]["image"][0]["trends"]["clicks"], [15, 30])
        self.assertEqual(payload["tags"]["image"][0]["samples"][0]["clicks"], 30)
        self.assertEqual(len(payload["tags"]["image"][0]["samples"]), 2)
        self.assertIn("2025-11-29", payload["tags"]["image"][0]["samples"][0]["meta"])
        self.assertTrue(all(call.args[1][0] == 7 for call in database.execute.call_args_list))

    def test_samples_include_revenue_leader_outside_exposure_top_five(self):
        database = MagicMock()
        database.execute.side_effect = [
            [(2026, "8月", "AI短视频", "", 6, 401, 500, 0, 500, 0, 0)],
            [("AI短视频", "", str(index), f"作品{index}", None, exposure, revenue, 0, 0)
             for index, (exposure, revenue) in enumerate([(100, 0), (90, 0), (80, 0), (70, 0), (60, 0), (1, 500)])],
        ]
        tags = DashboardRepository(database)._categories(7, "2026-08", None, [{"period_key": "2026-08", "label": "2026年8月"}])["tags"]
        self.assertEqual({sample["content_id"] for sample in tags["video"][0]["samples"]}, {"0", "1", "2", "3", "4", "5"})

    def test_rejects_unknown_period(self):
        database = MagicMock()
        database.execute.return_value = [(2026, "8月", 1, 1, 1, 1, 1, 1, 1, 1)]
        with self.assertRaises(ValueError):
            DashboardRepository(database).load(7, "星巴克", "2026-05")


if __name__ == "__main__":
    unittest.main()
