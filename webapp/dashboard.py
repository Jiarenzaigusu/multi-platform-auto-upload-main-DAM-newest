from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from webapp.mysql_demo import MySQLDatabase


class DashboardRepository:
    """Read and normalize the Movado tables used by the dashboard."""

    _DAILY_COLUMNS = (
        "content_impression_users",
        "content_impressions",
        "content_viewers",
        "content_views",
        "product_click_users",
        "product_clicks",
        "store_visit_users",
        "store_visits",
        "add_to_cart_users",
        "add_to_cart_items",
        "subscription_guided_revenue",
        "subscription_direct_revenue",
        "coupon_redemption_guided_revenue",
        "live_content_guided_revenue",
        "direct_conversion_users",
        "direct_conversion_orders",
        "subscription_content_driven_revenue",
        "subscription_content_driven_buyers",
    )

    def __init__(self, database: MySQLDatabase) -> None:
        self.database = database

    def load(self, period: str = "week") -> dict[str, Any]:
        if period not in {"week", "previous_week", "30d"}:
            raise ValueError("period 必须是 week、previous_week 或 30d")

        latest_daily = self._scalar(
            "SELECT MAX(metric_date) FROM subscription_daily_metrics"
        )
        report_periods = self._weekly_summary_dates()
        weekly = self._weekly_report_overview_rows() if report_periods else []
        weekly = weekly or self._weekly_overview_rows()
        if latest_daily is None and not weekly:
            return {
                "configured": True,
                "connected": True,
                "empty": True,
                "source": {"tables": []},
                "periods": [],
                "selected_period": period,
                "summary": None,
                "comparisons": {},
                "trend": [],
                "comparison_trend": [],
                "year_comparison_trend": [],
                "channels": [],
                "notes": [],
            }

        periods = self._period_options(weekly, report_periods, latest_daily)
        selected_week_index = 0 if period == "week" else 1
        if period == "30d":
            selected = self._load_daily_period(latest_daily)
        else:
            selected = self._load_week_period(weekly, selected_week_index)
            if len(report_periods) > selected_week_index:
                end_date = _as_date(report_periods[selected_week_index][1])
                daily_window = self._load_daily_range(
                    end_date - timedelta(days=6), end_date
                )
                selected["trend"] = daily_window["trend"]
                selected["comparison_trend"] = daily_window["comparison_trend"]

        selected_week = report_periods[selected_week_index] if len(report_periods) > selected_week_index else None
        channel_period_start = selected_week[0] if selected_week else None
        channels = self._load_channels(channel_period_start)
        notes = self._load_notes(selected_week_index)

        return {
            "configured": True,
            "connected": True,
            "empty": False,
            "source": {
                "database": self.database.settings.database,
                "tables": [
                    "guanghe_metrics",
                    "subscription_daily_metrics",
                    "weekly_report_summary",
                    "weekly_report_notes",
                ],
                "latest_daily_date": str(latest_daily) if latest_daily else None,
                "latest_week": str(report_periods[0][0]) if report_periods else None,
            },
            "periods": periods,
            "selected_period": period,
            "summary": selected["summary"],
            "comparisons": selected.get("comparisons", {}),
            "trend": selected["trend"],
            "comparison_trend": selected["comparison_trend"],
            "year_comparison_trend": selected.get("year_comparison_trend", []),
            "channels": channels,
            "notes": notes,
        }

    def _load_week_period(
        self, weekly: list[tuple[Any, ...]], selected_index: int
    ) -> dict[str, Any]:
        if len(weekly) <= selected_index:
            return {"summary": None, "trend": [], "comparison_trend": [], "year_comparison_trend": []}

        selected = self._metric_from_weekly_row(weekly[selected_index])
        previous = (
            self._metric_from_weekly_row(weekly[selected_index + 1])
            if len(weekly) > selected_index + 1
            else None
        )
        same_period_last_year = (
            self._metric_from_weekly_row(weekly[selected_index + 52])
            if len(weekly) > selected_index + 52
            else None
        )
        trend_rows = weekly[selected_index : selected_index + 7]
        comparison_rows = weekly[selected_index + 1 : selected_index + 8]
        year_comparison_rows = weekly[selected_index + 52 : selected_index + 59]
        return {
            "summary": self._summary(selected, previous),
            "comparisons": self._comparisons(selected, previous, same_period_last_year),
            "trend": [self._metric_from_weekly_row(row) for row in reversed(trend_rows)],
            "comparison_trend": [
                self._metric_from_weekly_row(row) for row in reversed(comparison_rows)
            ],
            "year_comparison_trend": [
                self._metric_from_weekly_row(row) for row in reversed(year_comparison_rows)
            ],
        }

    def _load_daily_period(self, latest_daily: Any) -> dict[str, Any]:
        if latest_daily is None:
            return {"summary": None, "trend": [], "comparison_trend": [], "year_comparison_trend": []}

        end_date = _as_date(latest_daily)
        start_date = end_date - timedelta(days=29)
        previous_end = start_date - timedelta(days=1)
        previous_start = previous_end - timedelta(days=29)
        year_ago_start = start_date - timedelta(days=364)
        year_ago_end = end_date - timedelta(days=364)
        result = self._load_daily_range(start_date, end_date, previous_start, previous_end)
        year_ago_rows = self._daily_rows(year_ago_start, year_ago_end)
        result["comparisons"] = self._comparisons(
            result["summary"]["current"] if result["summary"] else {},
            result["summary"]["previous"] if result["summary"] else None,
            self._aggregate_daily(year_ago_rows) if year_ago_rows else None,
        )
        result["year_comparison_trend"] = [
            self._metric_from_daily_row(row) for row in year_ago_rows
        ]
        return result

    def _load_daily_range(
        self,
        start_date: date,
        end_date: date,
        previous_start: date | None = None,
        previous_end: date | None = None,
    ) -> dict[str, Any]:
        if previous_start is None or previous_end is None:
            previous_end = start_date - timedelta(days=1)
            previous_start = previous_end - (end_date - start_date)
        current_rows = self._daily_rows(start_date, end_date)
        previous_rows = self._daily_rows(previous_start, previous_end)
        current = self._aggregate_daily(current_rows)
        previous = self._aggregate_daily(previous_rows) if previous_rows else None
        return {
            "summary": self._summary(current, previous),
            "comparisons": self._comparisons(current, previous, None),
            "trend": [self._metric_from_daily_row(row) for row in current_rows],
            "comparison_trend": [
                self._metric_from_daily_row(row) for row in previous_rows
            ],
            "year_comparison_trend": [],
        }

    def _weekly_overview_rows(self) -> list[tuple[Any, ...]]:
        return self.database.execute(
            """
            SELECT period_key, period_label, channel, content_viewers,
                   content_engagers, product_guided_click_users,
                   content_driven_buyers, content_driven_revenue,
                   viewed_content_count, content_views, content_engagements,
                   product_click_users, product_clicks, add_to_cart_users,
                   add_to_cart_items, impression_users, click_users,
                   impression_uv_ctr
            FROM guanghe_metrics
            WHERE granularity = 'week' AND channel = '光合数据总览'
            ORDER BY period_key DESC
            LIMIT 80
            """
        )

    def _weekly_report_overview_rows(self) -> list[tuple[Any, ...]]:
        """Use the report's aggregate channel as the weekly dashboard series."""
        return self.database.execute(
            """
            SELECT CONCAT(YEAR(week_start), '-W', LPAD(WEEK(week_start, 1), 2, '0')),
                   CONCAT(DATE_FORMAT(week_start, '%%Y-%%m-%%d'), ' — ',
                          DATE_FORMAT(week_end, '%%Y-%%m-%%d')),
                   channel, content_viewers, 0, product_click_users, 0,
                   content_driven_revenue, viewed_content_count,
                   viewed_content_count, 0, product_click_users, 0, 0, 0,
                   0, 0, NULL
            FROM weekly_report_summary
            WHERE channel = '光合数据'
            ORDER BY week_start DESC
            LIMIT 80
            """
        )

    def _weekly_summary_dates(self) -> list[tuple[Any, ...]]:
        return self.database.execute(
            """
            SELECT week_start, week_end
            FROM weekly_report_summary
            GROUP BY week_start, week_end
            ORDER BY week_start DESC
            LIMIT 80
            """
        )

    def _daily_rows(self, start_date: date, end_date: date) -> list[tuple[Any, ...]]:
        columns = ", ".join(self._DAILY_COLUMNS)
        return self.database.execute(
            f"""
            SELECT metric_date, {columns}
            FROM subscription_daily_metrics
            WHERE metric_date BETWEEN %s AND %s
            ORDER BY metric_date
            """,
            (start_date, end_date),
        )

    def _load_channels(self, week_start: Any | None) -> list[dict[str, Any]]:
        if not week_start:
            return []
        rows = self.database.execute(
            """
            SELECT channel, content_viewers, viewed_content_count,
                   content_driven_revenue, product_click_users
            FROM weekly_report_summary
            WHERE week_start = %s
            ORDER BY content_viewers DESC, channel
            """,
            (week_start,),
        )
        previous_dates = self.database.execute(
            """
            SELECT week_start
            FROM weekly_report_summary
            WHERE week_start < %s
            GROUP BY week_start
            ORDER BY week_start DESC
            LIMIT 1
            """,
            (week_start,),
        )
        previous_start = previous_dates[0][0] if previous_dates else None
        previous_rows = self.database.execute(
            """
            SELECT channel, content_viewers
            FROM weekly_report_summary
            WHERE week_start = %s
            """,
            (previous_start,),
        ) if previous_start else []
        previous = {str(row[0]): _number(row[1]) for row in previous_rows}

        result = []
        for row in rows:
            viewers = _number(row[1])
            previous_viewers = previous.get(str(row[0]))
            result.append(
                {
                    "name": str(row[0]),
                    "viewers": viewers,
                    "views": _number(row[2]),
                    "revenue": _number(row[3]),
                    "product_click_users": _number(row[4]),
                    "impression_users": 0,
                    "click_users": _number(row[4]),
                    "uv_rate": 0,
                    "delta": _change(viewers, previous_viewers),
                }
            )
        return result

    def _load_notes(self, selected_week_index: int) -> list[dict[str, Any]]:
        dates = self._weekly_summary_dates()
        if len(dates) <= selected_week_index:
            return []
        week_start, week_end = dates[selected_week_index]
        rows = self.database.execute(
            """
            SELECT report_note
            FROM weekly_report_notes
            WHERE week_start = %s AND week_end = %s
            """,
            (week_start, week_end),
        )
        return [
            {"week_start": str(week_start), "week_end": str(week_end), "text": str(row[0])}
            for row in rows
            if row[0]
        ]

    def _period_options(
        self,
        weekly: list[tuple[Any, ...]],
        report_periods: list[tuple[Any, ...]],
        latest_daily: Any,
    ) -> list[dict[str, Any]]:
        options = []
        if report_periods:
            end_date = _as_date(report_periods[0][1])
            options.extend(
                [
                    {
                        "key": "week",
                        "label": "本周",
                        "date_label": f"{end_date - timedelta(days=6)} — {end_date}",
                    },
                    {
                        "key": "previous_week",
                        "label": "上周",
                        "date_label": f"{end_date - timedelta(days=13)} — {end_date - timedelta(days=7)}",
                    },
                ]
            )
        elif latest_daily is not None:
            end_date = _as_date(latest_daily)
            options.extend(
                [
                    {
                        "key": "week",
                        "label": "本周",
                        "date_label": f"{end_date - timedelta(days=6)} — {end_date}",
                    },
                    {
                        "key": "previous_week",
                        "label": "上周",
                        "date_label": f"{end_date - timedelta(days=13)} — {end_date - timedelta(days=7)}",
                    },
                ]
            )
        if latest_daily is not None:
            end_date = _as_date(latest_daily)
            options.append(
                {
                    "key": "30d",
                    "label": "近30天",
                    "date_label": f"{end_date - timedelta(days=29)} — {end_date}",
                }
            )
        return options

    @staticmethod
    def _metric_from_weekly_row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "period_key": str(row[0]),
            "label": str(row[1]),
            "date_label": str(row[0]),
            "content_viewers": _number(row[3]),
            "content_engagers": _number(row[4]),
            "product_guided_click_users": _number(row[5]),
            "content_driven_buyers": _number(row[6]),
            "revenue": _number(row[7]),
            "viewed_content_count": _number(row[8]),
            "content_views": _number(row[9]),
            "content_engagements": _number(row[10]),
            "product_click_users": _number(row[11]),
            "product_clicks": _number(row[12]),
            "add_to_cart_users": _number(row[13]),
            "add_to_cart_items": _number(row[14]),
            "impression_users": _number(row[15]),
            "click_users": _number(row[16]),
            "uv_rate": _number(row[17]) if row[15] else None,
        }

    @staticmethod
    def _metric_from_daily_row(row: tuple[Any, ...]) -> dict[str, Any]:
        values = dict(zip(("date",) + DashboardRepository._DAILY_COLUMNS, row))
        return {
            "period_key": str(values["date"]),
            "label": str(values["date"]),
            "date_label": str(values["date"]),
            "content_viewers": _number(values["content_viewers"]),
            "content_engagers": 0,
            "product_guided_click_users": _number(values["product_click_users"]),
            "content_driven_buyers": _number(values["subscription_content_driven_buyers"]),
            "revenue": _number(values["subscription_guided_revenue"]),
            "viewed_content_count": 0,
            "content_views": _number(values["content_views"]),
            "content_engagements": 0,
            "product_click_users": _number(values["product_click_users"]),
            "product_clicks": _number(values["product_clicks"]),
            "add_to_cart_users": _number(values["add_to_cart_users"]),
            "add_to_cart_items": _number(values["add_to_cart_items"]),
            "impression_users": _number(values["content_impression_users"]),
            "click_users": _number(values["product_click_users"]),
            "uv_rate": _ratio(
                values["product_click_users"], values["content_impression_users"]
            ),
        }

    @staticmethod
    def _aggregate_daily(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
        if not rows:
            return {}
        metrics = [DashboardRepository._metric_from_daily_row(row) for row in rows]
        sum_keys = (
            "content_viewers",
            "content_engagers",
            "product_guided_click_users",
            "content_driven_buyers",
            "revenue",
            "viewed_content_count",
            "content_views",
            "content_engagements",
            "product_click_users",
            "product_clicks",
            "add_to_cart_users",
            "add_to_cart_items",
            "impression_users",
            "click_users",
        )
        result = {key: sum(metric[key] or 0 for metric in metrics) for key in sum_keys}
        result.update(
            {
                "period_key": f"{metrics[0]['period_key']}..{metrics[-1]['period_key']}",
                "label": "近30天",
                "date_label": f"{metrics[0]['date_label']} — {metrics[-1]['date_label']}",
                "add_to_cart_users": result["add_to_cart_users"],
                "add_to_cart_items": result["add_to_cart_items"],
                "uv_rate": _ratio(result["click_users"], result["impression_users"]),
            }
        )
        return result

    @staticmethod
    def _summary(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
        if not current:
            return None
        return {
            "current": current,
            "previous": previous,
            "deltas": {
                key: _change(current.get(key), previous.get(key) if previous else None)
                for key in (
                    "content_viewers",
                    "content_views",
                    "revenue",
                    "product_click_users",
                    "impression_users",
                    "click_users",
                    "add_to_cart_items",
                )
            },
        }

    @staticmethod
    def _comparisons(
        current: dict[str, Any],
        previous: dict[str, Any] | None,
        same_period_last_year: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Expose comparison values and deltas for the dashboard's trend card."""
        metrics = (
            "content_viewers",
            "content_views",
            "revenue",
            "product_click_users",
        )

        def comparison(label: str, reference: dict[str, Any] | None) -> dict[str, Any]:
            return {
                "label": label,
                "available": bool(reference),
                "values": {key: reference.get(key) for key in metrics} if reference else {},
                "deltas": {
                    key: _change(current.get(key), reference.get(key))
                    for key in metrics
                } if reference else {},
            }

        return {
            "previous_week": comparison("较上周", previous),
            "same_period_last_year": comparison("较去年同期", same_period_last_year),
        }

    def _scalar(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        rows = self.database.execute(query, parameters)
        return rows[0][0] if rows else None


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _number(value: Any) -> int | float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _ratio(numerator: Any, denominator: Any) -> float:
    numerator = float(numerator or 0)
    denominator = float(denominator or 0)
    return numerator / denominator if denominator else 0


def _change(current: Any, previous: Any) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / float(previous)


def _week_label(row: tuple[Any, ...]) -> str:
    return str(row[1])
