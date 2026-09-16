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
    def test_maps_daily_and_weekly_metrics_to_dashboard_payload(self):
        database = MagicMock()
        database.settings.database = "movado_data"
        daily_row = (
            "2026-09-07", 122, 151, 13, 40, 1, 1, 2, 2, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0,
        )
        weekly_row = (
            "2026-W35", "第35周", "光合数据总览", 957, 11, 246, 0, 0,
            133, 47, 1407, 20, 426, 0, 6, 6, 4104, 343, 0.0835,
        )
        report_period = ("2026-08-31", "2026-09-06")

        def execute(query, parameters=None):
            if "MAX(metric_date)" in query:
                return [("2026-09-07",)]
            if "CONCAT(YEAR(week_start)" in query:
                return [(
                    "2026-W35", "2026-08-31 — 2026-09-06", "光合数据", 798,
                    0, 160, 0, 12000, 155, 155, 0, 160, 0, 0, 0, 0, 0, None,
                )]
            if "FROM guanghe_metrics" in query and "channel = '光合数据总览'" in query:
                return [weekly_row]
            if "GROUP BY week_start, week_end" in query:
                return [report_period]
            if "FROM subscription_daily_metrics" in query:
                return [daily_row]
            if "FROM weekly_report_summary" in query and "content_viewers" in query:
                return [("光合数据", 798, 155, 12000, 160)]
            if "FROM weekly_report_notes" in query:
                return [("本周图文发布7条",)]
            return []

        database.execute.side_effect = execute
        payload = DashboardRepository(database).load("week")

        self.assertEqual(payload["source"]["database"], "movado_data")
        self.assertEqual(payload["summary"]["current"]["content_viewers"], 798)
        self.assertEqual(payload["trend"][0]["content_viewers"], 13)
        self.assertEqual(payload["channels"][0]["name"], "光合数据")
        self.assertEqual(payload["notes"][0]["text"], "本周图文发布7条")

    def test_rejects_unknown_period(self):
        database = MagicMock()
        with self.assertRaises(ValueError):
            DashboardRepository(database).load("month")


if __name__ == "__main__":
    unittest.main()
