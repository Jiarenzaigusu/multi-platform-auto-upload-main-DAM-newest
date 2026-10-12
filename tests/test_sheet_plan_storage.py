import os
from pathlib import Path

from webapp.api.main import sheet_plan_storage_path


def test_sheet_plan_record_survives_long_workspace_path(tmp_path):
    # A realistic checkout + per-user workspace puts the hashed filename past
    # Windows MAX_PATH even though its parent directory can still be created.
    folder = tmp_path / ("workspace-" + "x" * 100) / "sheet-fill-plans" / ("b" * 16) / "tables"
    storage = sheet_plan_storage_path(folder)
    storage.mkdir(parents=True)
    record = storage / ("e" * 64 + ".json")
    assert len(str(record)) > 260
    record.write_text('{"table_name": "weekly"}', encoding="utf-8")
    assert record.read_text(encoding="utf-8") == '{"table_name": "weekly"}'
    assert record in list(storage.glob("*.json"))
    record.with_suffix(".deleted").touch()
    record.unlink()
    assert record.with_suffix(".deleted").is_file()
    record.with_suffix(".deleted").unlink()
    # Clean up using the same extended path on Windows.
    storage.rmdir()
    storage.parent.rmdir()
    storage.parent.parent.rmdir()
    storage.parent.parent.parent.rmdir()


def test_sheet_plan_storage_path_is_idempotent(tmp_path):
    storage = sheet_plan_storage_path(tmp_path)
    assert sheet_plan_storage_path(storage) == storage
    if os.name != "nt":
        assert storage == tmp_path
