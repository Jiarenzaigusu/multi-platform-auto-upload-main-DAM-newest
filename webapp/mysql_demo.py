from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, replace
from threading import RLock
from typing import Any, Callable, Sequence


_REQUIRED_ENVIRONMENT_VARIABLES = (
    "MPAU_MYSQL_HOST",
    "MPAU_MYSQL_DATABASE",
    "MPAU_MYSQL_USER",
    "MPAU_MYSQL_PASSWORD",
)


class MySQLDemoError(RuntimeError):
    """Raised when the optional MySQL connectivity check cannot complete."""


class MySQLDatabase:
    """Small process-level MySQL client that new features can reuse."""

    def __init__(self, settings: "MySQLSettings") -> None:
        self.settings = settings
        self._connection: Any | None = None
        self._lock = RLock()

    @property
    def configured(self) -> bool:
        return self.settings.configured

    def _connect(self) -> Any:
        try:
            import pymysql
        except ImportError as exc:
            raise MySQLDemoError(
                "缺少 PyMySQL，请安装 requirements-mysql-demo.txt"
            ) from exc
        try:
            return pymysql.connect(
                host=self.settings.host,
                port=self.settings.port,
                user=self.settings.user,
                password=self.settings.password,
                database=self.settings.database,
                charset="utf8mb4",
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.connect_timeout,
                write_timeout=self.settings.connect_timeout,
                autocommit=True,
            )
        except Exception as exc:
            raise _connection_error(self.settings, exc) from exc

    def _ensure_connection(self) -> Any:
        missing = self.settings.missing_environment_variables
        if missing:
            raise MySQLDemoError(f"MySQL 尚未配置：缺少 {', '.join(missing)}")
        if self._connection is None:
            self._connection = self._connect()
        else:
            try:
                self._connection.ping(reconnect=True)
            except Exception:
                self._close_connection()
                self._connection = self._connect()
        return self._connection

    def execute(
        self,
        query: str,
        parameters: Sequence[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Execute a query and return rows; intended for future repositories."""
        with self._lock:
            connection = self._ensure_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(query, parameters or ())
                    rows = cursor.fetchall() if cursor.description else ()
                return [tuple(row) for row in rows]
            except Exception as exc:
                raise _connection_error(self.settings, exc) from exc

    def check(self) -> dict[str, Any]:
        rows = self.execute("SELECT VERSION(), DATABASE()")
        if not rows:
            raise MySQLDemoError("MySQL 已连接，但连通性查询没有返回结果")
        row = rows[0]
        return {
            "configured": True,
            "connected": True,
            "host": self.settings.host,
            "port": self.settings.port,
            "database": str(row[1] or self.settings.database),
            "server_version": str(row[0]),
        }

    def _close_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def close(self) -> None:
        with self._lock:
            self._close_connection()


@dataclass(frozen=True, slots=True)
class MySQLSettings:
    """Connection settings for new MySQL-backed features."""

    host: str = ""
    port: int = 3306
    database: str = ""
    user: str = ""
    password: str = ""
    connect_timeout: int = 5

    @classmethod
    def from_environment(cls) -> "MySQLSettings":
        return cls(
            host=os.getenv("MPAU_MYSQL_HOST", "").strip(),
            port=_positive_int("MPAU_MYSQL_PORT", 3306, maximum=65535),
            database=os.getenv("MPAU_MYSQL_DATABASE", "").strip(),
            user=os.getenv("MPAU_MYSQL_USER", "").strip(),
            password=os.getenv("MPAU_MYSQL_PASSWORD", ""),
            connect_timeout=_positive_int("MPAU_MYSQL_CONNECT_TIMEOUT", 5),
        )

    @property
    def missing_environment_variables(self) -> tuple[str, ...]:
        values = (self.host, self.database, self.user, self.password)
        return tuple(
            name
            for name, value in zip(_REQUIRED_ENVIRONMENT_VARIABLES, values)
            if not value
        )

    @property
    def configured(self) -> bool:
        return not self.missing_environment_variables


def prompt_for_mysql_password(settings: MySQLSettings) -> MySQLSettings:
    """Fill only the missing password through a hidden terminal prompt."""
    missing_without_password = tuple(
        name
        for name in settings.missing_environment_variables
        if name != "MPAU_MYSQL_PASSWORD"
    )
    if missing_without_password:
        raise MySQLDemoError(
            f"MySQL 尚未配置：缺少 {', '.join(missing_without_password)}"
        )
    if settings.password:
        return settings
    password = getpass.getpass("请输入 MySQL 密码: ")
    if not password:
        raise MySQLDemoError("MySQL 密码不能为空")
    return replace(settings, password=password)


def _positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value < 1 or (maximum is not None and value > maximum):
        suffix = f"且不能大于 {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} 必须是正整数{suffix}")
    return value


def _connection_error(settings: "MySQLSettings", exc: Exception) -> MySQLDemoError:
    detail = str(exc)
    if settings.password:
        detail = detail.replace(settings.password, "***")
    return MySQLDemoError(f"MySQL 连接失败：{detail}")


def check_mysql_connection(
    settings: MySQLSettings,
    *,
    connect: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run a read-only query and return non-secret server information."""
    missing = settings.missing_environment_variables
    if missing:
        raise MySQLDemoError(f"MySQL 尚未配置：缺少 {', '.join(missing)}")

    if connect is None:
        return _check_with_database(MySQLDatabase(settings))

    connection = None
    try:
        connection = connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
            charset="utf8mb4",
            connect_timeout=settings.connect_timeout,
            read_timeout=settings.connect_timeout,
            write_timeout=settings.connect_timeout,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), DATABASE()")
            row = cursor.fetchone()
        if not row:
            raise MySQLDemoError("MySQL 已连接，但连通性查询没有返回结果")
        return {
            "configured": True,
            "connected": True,
            "host": settings.host,
            "port": settings.port,
            "database": str(row[1] or settings.database),
            "server_version": str(row[0]),
        }
    except MySQLDemoError:
        raise
    except Exception as exc:
        raise _connection_error(settings, exc) from exc
    finally:
        if connection is not None:
            connection.close()


def _check_with_database(database: MySQLDatabase) -> dict[str, Any]:
    try:
        return database.check()
    finally:
        database.close()


def main() -> int:
    """Allow an operator to test the configured connection from a terminal."""
    try:
        settings = prompt_for_mysql_password(MySQLSettings.from_environment())
        result = check_mysql_connection(settings)
    except (MySQLDemoError, ValueError) as exc:
        print(exc)
        return 1
    print(
        "MySQL 连接成功："
        f"{result['host']}:{result['port']}/{result['database']} "
        f"(server {result['server_version']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
