"""Native Windows path importer for the bundled batch publishing templates."""
from __future__ import annotations

import tempfile
import shutil
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".webm"}
CELL_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"
ROW_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"
# Inline-string cells use t="inlineStr", but their value container is <is>.
INLINE_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is"
TEXT_TAG = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"


def _install_staged_output(staged_output: Path, output: Path) -> None:
    """Install a generated workbook even when temp and output are on different drives."""
    try:
        staged_output.replace(output)
    except OSError as exc:
        # Windows raises WinError 17 for cross-volume rename (C: temp -> D: output).
        # A move cannot be atomic across volumes, so copy the completed ZIP instead.
        if getattr(exc, "winerror", None) != 17 and getattr(exc, "errno", None) != 18:
            raise
        shutil.copy2(staged_output, output)


def _stem(path: Path) -> str:
    return unicodedata.normalize("NFKC", path.stem.strip()).casefold()


def _set_cell(root: ET.Element, reference: str, value: str) -> None:
    row_number = "".join(char for char in reference if char.isdigit())
    row = next((item for item in root.iter(ROW_TAG) if item.get("r") == row_number), None)
    if row is None:
        raise RuntimeError(f"模板缺少第 {row_number} 行")
    cell = next((item for item in row.iter(CELL_TAG) if item.get("r") == reference), None)
    if cell is None:
        cell = ET.Element(CELL_TAG, {"r": reference})
        columns = "".join(char for char in reference if char.isalpha())
        insert_at = len(row)
        for index, existing in enumerate(row):
            existing_ref = existing.get("r", "")
            existing_column = "".join(char for char in existing_ref if char.isalpha())
            if existing_column > columns:
                insert_at = index
                break
        row.insert(insert_at, cell)
    cell[:] = []
    cell.attrib.pop("t", None)
    if not value:
        return
    cell.set("t", "inlineStr")
    inline = ET.SubElement(cell, INLINE_TAG)
    text = ET.SubElement(inline, TEXT_TAG)
    text.text = value


def import_workbook(template: Path, source: Path, output: Path, cover: Path | None) -> tuple[str, int, int]:
    """Fill a selected template and return (content_type, count, missing_covers)."""
    with zipfile.ZipFile(template) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
        root = ET.fromstring(sheet_xml)
        headers = " ".join(item.text or "" for item in root.iter(TEXT_TAG))
        is_article = "图片文件夹路径" in headers
        is_video = "视频路径" in headers
        if not is_article and not is_video:
            raise RuntimeError("无法识别模板：缺少“视频路径”或“图片文件夹路径”表头")
        platform = "京东" if "自主原创" in headers else "天猫"
        content = "图文" if is_article else "视频"

        files = (
            sorted((item for item in source.iterdir() if item.is_dir()), key=lambda item: item.name.casefold())
            if is_article
            else sorted(
                (item for item in source.rglob("*") if item.is_file() and item.suffix.casefold() in VIDEO_EXTENSIONS),
                key=lambda item: str(item).casefold(),
            )
        )
        if not files:
            raise RuntimeError("没有找到支持的文件")
        if len(files) > 200:
            raise RuntimeError("模板最多支持 200 行")

        cover_map = {}
        if cover:
            for item in cover.rglob("*"):
                if item.is_file():
                    cover_map.setdefault(_stem(item), item.resolve())

        columns = "ABCDEFGHIJK"
        for row in range(2, 202):
            for column in columns:
                _set_cell(root, f"{column}{row}", "")
        missing = 0
        for index, item in enumerate(files, start=2):
            _set_cell(root, f"A{index}", str(item.resolve()))
            if cover:
                matched = cover_map.get(_stem(item))
                if matched:
                    _set_cell(root, f"B{index}", str(matched))
                else:
                    missing += 1

        with tempfile.TemporaryDirectory(prefix="mpau-path-import-") as temporary:
            staged_output = Path(temporary) / "imported.xlsx"
            replacement = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(staged_output, "w", zipfile.ZIP_DEFLATED) as result:
                for info in archive.infolist():
                    content_bytes = (
                        replacement
                        if info.filename == "xl/worksheets/sheet1.xml"
                        else archive.read(info.filename)
                    )
                    result.writestr(info, content_bytes)
            output.parent.mkdir(parents=True, exist_ok=True)
            _install_staged_output(staged_output, output)
    return f"{platform}{content}", len(files), missing


def run_path_import(asset_directory: Path, parent=None) -> None:
    """Run the native picker UI; all user-facing errors are shown as dialogs."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = parent or tk.Tk()
    owns_root = parent is None
    if owns_root:
        root.withdraw()
    try:
        template_name = filedialog.askopenfilename(
            title="第 1 步：选择天猫或京东的视频/图文模板",
            initialdir=str(asset_directory),
            parent=root,
            filetypes=[("Excel 工作簿", "*.xlsx")],
        )
        if not template_name:
            return
        template = Path(template_name)
        source_name = filedialog.askdirectory(title="第 2 步：选择视频文件夹或图文总文件夹", parent=root)
        if not source_name:
            return
        cover = None
        with zipfile.ZipFile(template) as template_archive:
            is_video = "视频路径" in template_archive.read("xl/worksheets/sheet1.xml").decode("utf-8", "ignore")
        if is_video:
            if messagebox.askyesno("可选封面", "是否按同名文件导入封面？", parent=root):
                cover_name = filedialog.askdirectory(title="第 3 步：选择封面文件夹", parent=root)
                if not cover_name:
                    return
                cover = Path(cover_name)
        output_name = filedialog.asksaveasfilename(
            title="选择输出工作簿",
            initialdir=str(template.parent),
            initialfile="已导入批量发布.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            parent=root,
        )
        if not output_name:
            return
        output = Path(output_name)
        if output.resolve() == template.resolve():
            raise RuntimeError("输出文件不能覆盖模板")
        content, count, missing = import_workbook(template, Path(source_name), output, cover)
        suffix = f"\n已匹配封面：{count - missing}\n未匹配视频：{missing}" if cover else ""
        messagebox.showinfo("批量发布路径导入", f"完成（{content}模板）\n文件数量：{count}{suffix}\n\n输出文件：{output}", parent=root)
    except Exception as exc:
        messagebox.showerror("导入失败", str(exc), parent=root)
    finally:
        if owns_root:
            root.destroy()
