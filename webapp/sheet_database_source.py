"""Turn one user's brand-scoped content data into a sheet-fill source workbook."""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook

from webapp.mysql_demo import MySQLDatabase


def list_content_periods(database: MySQLDatabase, brand_id: int) -> list[dict]:
    rows = database.execute(
        "SELECT `年份`, `下载周期`, COUNT(*) FROM content_performance "
        "WHERE brand_id = %s GROUP BY `年份`, `下载周期`",
        (brand_id,),
    )
    return sorted(({
        "key": f"{int(year):04d}-{int(str(cycle).removesuffix('月')):02d}",
        "label": f"{year}年{cycle}",
        "count": count,
    } for year, cycle, count in rows), key=lambda item: item["key"], reverse=True)


def export_content_source(
    database: MySQLDatabase, brand_id: int, brand_name: str, period: str, path: Path,
) -> Path:
    if period != "all" and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError("下载周期格式无效")
    columns = [str(row[0]) for row in database.execute("SHOW COLUMNS FROM content_performance")]
    if "brand_id" not in columns:
        raise ValueError("内容数据表缺少品牌字段")
    columns.remove("brand_id")
    quoted = ", ".join("`" + column.replace("`", "``") + "`" for column in columns)
    query = f"SELECT {quoted} FROM content_performance WHERE brand_id = %s"
    parameters: tuple = (brand_id,)
    if period != "all":
        year, month = period.split("-")
        query += " AND `年份` = %s AND `下载周期` = %s"
        parameters += (int(year), f"{int(month)}月")
    rows = database.execute(query + " LIMIT 20001", parameters)
    if not rows:
        raise ValueError("所选品牌和下载周期没有内容数据")
    if len(rows) > 20000:
        raise ValueError("数据超过 2 万行，请先选择单个下载周期")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "内容表现"
    sheet.append(["品牌", *columns])
    for row in rows:
        sheet.append([brand_name, *row])
    workbook.save(path)
    return path
