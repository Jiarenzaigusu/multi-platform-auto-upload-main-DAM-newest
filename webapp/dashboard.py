from __future__ import annotations

from decimal import Decimal
from typing import Any

from webapp.mysql_demo import MySQLDatabase


class DashboardRepository:
    """Build the existing dashboard from one brand's monthly content snapshots."""

    def __init__(self, database: MySQLDatabase) -> None:
        self.database = database

    def load(self, brand_id: int, brand_name: str, period: str = "latest") -> dict[str, Any]:
        rows = self.database.execute(
            """
            SELECT `年份`, `下载周期`, COUNT(*), SUM(`查看人数`),
                   SUM(`曝光次数`), SUM(`种草成交金额`), SUM(`商品点击人数`),
                   SUM(`曝光人数`), SUM(`互动次数`), SUM(`商品点击次数`)
            FROM content_performance
            WHERE brand_id = %s
            GROUP BY `年份`, `下载周期`
            """,
            (brand_id,),
        )
        monthly = sorted((self._month_metric(row) for row in rows), key=lambda item: item["period_key"], reverse=True)
        base = {
            "configured": True,
            "connected": True,
            "brand": {"id": brand_id, "name": brand_name},
            "source": {"database": self.database.settings.database, "tables": ["content_performance"], "latest_period": monthly[0]["period_key"] if monthly else None},
            "periods": [{"key": item["period_key"], "label": item["label"], "date_label": f"{item['label']}下载周期"} for item in monthly],
        }
        if not monthly:
            return {**base, "empty": True, "selected_period": None, "summary": None, "comparisons": {}, "trend": [], "comparison_trend": [], "year_comparison_trend": [], "channels": [], "tags": {"image": [], "video": []}, "notes": []}

        selected_key = monthly[0]["period_key"] if period in ("", "latest") else period
        selected_index = next((index for index, item in enumerate(monthly) if item["period_key"] == selected_key), None)
        if selected_index is None:
            raise ValueError("所选下载周期不存在")
        current = monthly[selected_index]
        previous = monthly[selected_index + 1] if selected_index + 1 < len(monthly) else None
        last_year = next((item for item in monthly if item["period_key"] == f"{int(selected_key[:4]) - 1}{selected_key[4:]}"), None)
        trend = list(reversed(monthly[selected_index:selected_index + 12]))
        comparison_trend = list(reversed(monthly[selected_index + 1:selected_index + 13]))
        by_key = {item["period_key"]: item for item in monthly}
        year_trend = [by_key[f"{int(item['period_key'][:4]) - 1}{item['period_key'][4:]}"] for item in trend if f"{int(item['period_key'][:4]) - 1}{item['period_key'][4:]}" in by_key]
        categories = self._categories(brand_id, selected_key, previous["period_key"] if previous else None, list(reversed(monthly[selected_index:selected_index + 6])))
        return {
            **base,
            "empty": False,
            "selected_period": selected_key,
            "summary": {"current": current, "previous": previous, "deltas": {key: _change(current[key], previous[key] if previous else None) for key in ("content_viewers", "impressions", "revenue", "product_click_users")}},
            "comparisons": {
                "previous_week": self._comparison(current, previous),
                "same_period_last_year": self._comparison(current, last_year),
            },
            "trend": trend,
            "comparison_trend": comparison_trend,
            "year_comparison_trend": year_trend,
            "channels": categories["channels"],
            "tags": categories["tags"],
            "notes": [],
        }

    @staticmethod
    def _month_key(year: Any, cycle: Any) -> str:
        month = int(str(cycle).strip().removesuffix("月"))
        if not 1 <= month <= 12:
            raise ValueError("下载周期必须为 1月 至 12月")
        return f"{int(year):04d}-{month:02d}"

    @classmethod
    def _month_metric(cls, row: tuple[Any, ...]) -> dict[str, Any]:
        key = cls._month_key(row[0], row[1])
        return {
            "period_key": key,
            "label": f"{key[:4]}年{int(key[5:])}月",
            "date_label": key,
            "content_count": _number(row[2]),
            "content_viewers": _number(row[3]),
            "impressions": _number(row[4]),
            "revenue": _number(row[5]),
            "product_click_users": _number(row[6]),
            "impression_users": _number(row[7]),
            "interactions": _number(row[8]),
            "product_clicks": _number(row[9]),
        }

    @staticmethod
    def _comparison(current: dict[str, Any], reference: dict[str, Any] | None) -> dict[str, Any]:
        keys = ("content_viewers", "impressions", "revenue", "product_click_users")
        return {
            "available": bool(reference),
            "values": {key: reference[key] for key in keys} if reference else {},
            "deltas": {key: _change(current[key], reference[key]) for key in keys} if reference else {},
        }

    def _categories(self, brand_id: int, selected_key: str, previous_key: str | None, trend_months: list[dict[str, Any]]) -> dict[str, Any]:
        rows = self.database.execute(
            """
            SELECT `年份`, `下载周期`, `汇总分类`, `二级分类`, COUNT(*),
                   SUM(`曝光人数`), SUM(`曝光次数`), SUM(`互动次数`),
                   SUM(`种草成交金额`), SUM(`商品点击人数`), SUM(`点击次数`),
                   SUM(CASE WHEN TRIM(`是否爆文`) = '是' THEN 1 ELSE 0 END)
            FROM content_performance
            WHERE brand_id = %s
            GROUP BY `年份`, `下载周期`, `汇总分类`, `二级分类`
            """,
            (brand_id,),
        )
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            month_key = self._month_key(row[0], row[1])
            category = str(row[2] or "未分类").strip()
            subcategory = str(row[3] or "").strip()
            label = f"{category} · {subcategory}" if subcategory else category
            kind = "image" if category == "图文" else "video"
            groups[(month_key, kind, label)] = {
                "category": category, "subcategory": subcategory,
                "contentCount": _number(row[4]), "exposure": _number(row[5]),
                "views": _number(row[6]), "interactions": _number(row[7]),
                "revenue": _number(row[8]), "product_click_users": _number(row[9]),
                "clicks": _number(row[10]), "viralCount": _number(row[11]),
            }
        sample_rows = self.database.execute(
            """
            SELECT `汇总分类`, `二级分类`, `内容ID`, `内容名称`, `内容发布时间`,
                   `曝光人数`, `种草成交金额`, `商品点击人数`, `点击次数`, `是否爆文`
            FROM content_performance
            WHERE brand_id = %s AND `年份` = %s AND `下载周期` = %s
            ORDER BY `曝光人数` DESC
            """,
            (brand_id, int(selected_key[:4]), f"{int(selected_key[5:])}月"),
        )
        samples: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for category, subcategory, content_id, title, published_at, exposure, revenue, product_click_users, clicks, is_viral in sample_rows:
            name = str(category or "未分类").strip()
            sub = str(subcategory or "").strip()
            label = f"{name} · {sub}" if sub else name
            kind = "image" if name == "图文" else "video"
            bucket = samples.setdefault((kind, label), [])
            published = str(published_at)[:10] if published_at else "未知"
            bucket.append({
                "content_id": str(content_id),
                "viralCount": int(str(is_viral or "").strip() == "是"),
                "title": str(title or content_id).replace("\\u200d", "\u200d"),
                "exposure": _number(exposure), "clicks": _number(clicks), "revenue": _number(revenue),
                "product_click_users": _number(product_click_users),
                "meta": f"发布于 {published}",
                "metric": f"商品点击人数 {_number(product_click_users):,}",
            })
        palette = ("#5f7ca4", "#76955e", "#b27a58", "#9b6a85", "#a18d55", "#758cad")
        tags: dict[str, list[dict[str, Any]]] = {"image": [], "video": []}
        channels = []
        for kind in ("image", "video"):
            labels = {label for month, group_kind, label in groups if month == selected_key and group_kind == kind}
            for index, label in enumerate(sorted(labels)):
                item = groups[(selected_key, kind, label)]
                previous = groups.get((previous_key, kind, label)) if previous_key else None
                tags[kind].append({
                    "id": label, "label": label, "description": "当前下载周期",
                    "color": palette[index % len(palette)],
                    **item, "delta": _change(item["exposure"], previous["exposure"] if previous else None),
                    "trend": [groups.get((month["period_key"], kind, label), {}).get("exposure", 0) for month in trend_months],
                    "trends": {metric: [groups.get((month["period_key"], kind, label), {}).get(metric, 0) for month in trend_months] for metric in ("contentCount", "viralCount", "exposure", "clicks", "revenue")},
                    "trendLabels": [month["label"] for month in trend_months],
                    "samples": samples.get((kind, label), []),
                })
                channels.append({"name": label, "revenue": item["revenue"], "product_click_users": item["product_click_users"]})
        return {"tags": tags, "channels": channels}


def _number(value: Any) -> int | float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _change(current: Any, previous: Any) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / float(previous)
