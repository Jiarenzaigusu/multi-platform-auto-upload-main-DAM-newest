"""Exercise deployment guards without invoking Docker or touching live data."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


_SPEC = importlib.util.spec_from_file_location(
    "mpau_upgrade_from_zip",
    Path(__file__).resolve().parents[1] / "deploy/docker/upgrade-from-zip.py",
)
upgrade = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(upgrade)


@pytest.fixture
def mounts():
    return [
        {
            "Type": "bind",
            "Source": "/root/MPAU/apps/deploy/windows/output",
            "Destination": "/var/lib/mpau/releases",
            "Mode": "ro", "RW": False, "Propagation": "rprivate",
        },
        {
            "Type": "volume", "Name": "mpau-data",
            "Source": "/var/lib/docker/volumes/mpau-data/_data",
            "Destination": "/var/lib/mpau/data", "Driver": "local",
            "Mode": "rw", "RW": True, "Propagation": "",
        },
    ]


def test_reordered_mounts_pass_without_mutating_inspect_snapshots(mounts):
    original = deepcopy(mounts)
    current = deepcopy(mounts[::-1])
    upgrade.verify_mounts(current, original)
    assert original == mounts
    assert current == mounts[::-1]


@pytest.mark.parametrize("index,field,value", [
    (0, "Source", "/different/installers"),
    (0, "Destination", "/different/releases"),
    (0, "Type", "volume"),
    (0, "RW", True),
    (0, "Mode", "rw"),
    (0, "Propagation", "rshared"),
    (1, "Name", "different-data"),
    (1, "Source", "/different/data"),
    (1, "Destination", "/different/data"),
    (1, "RW", False),
    (1, "Driver", "different-driver"),
    (1, "Mode", ""),
    (1, "UnexpectedOption", True),
])
def test_mount_field_changes_still_fail(mounts, index, field, value):
    current = deepcopy(mounts)
    current[index][field] = value
    with pytest.raises(upgrade.UpgradeError, match="切换后挂载变化"):
        upgrade.verify_mounts(current[::-1], mounts)


@pytest.mark.parametrize("change", ["missing_mount", "extra_mount", "missing_field", "duplicate_mount"])
def test_mount_structure_changes_still_fail(mounts, change):
    current = deepcopy(mounts)
    if change == "missing_mount":
        current.pop()
    elif change == "extra_mount":
        current.append({"Type": "bind", "Source": "/extra", "Destination": "/extra", "RW": True})
    elif change == "missing_field":
        del current[1]["Driver"]
    else:
        current.append(deepcopy(current[0]))
    with pytest.raises(upgrade.UpgradeError, match="切换后挂载变化"):
        upgrade.verify_mounts(current, mounts)


def cutover_fixture(tmp_path, monkeypatch, mounts, current_mounts):
    operation = upgrade.Upgrade(SimpleNamespace(root=str(tmp_path), timeout=180))
    operation.apps.mkdir()
    (operation.apps / "local_agent").mkdir()
    (operation.apps / "local_agent/__init__.py").write_text('version = "old"')
    operation.backup.mkdir(parents=True)
    next_apps = operation.stage / "next-apps"
    (next_apps / "local_agent").mkdir(parents=True)
    (next_apps / "local_agent/__init__.py").write_text('version = "new"')
    operation.initial_fingerprint = upgrade.fingerprint(operation.apps)
    operation.original = {
        "Id": "original-container", "Image": "old-image",
        "State": {"Running": True}, "Mounts": deepcopy(mounts),
    }
    operation.old_image = "old-image"
    operation.new_image = "new-image"
    operation.config = {}
    operation.inspect = Mock(side_effect=[operation.original, {
        "Image": "new-image", "State": {"Health": {"Status": "healthy"}},
        "Mounts": current_mounts,
    }])
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if "config" in args:
            return json.dumps(operation.config)
        if args[:3] == ["docker", "ps", "-q"]:
            return "running-container"
        return ""

    monkeypatch.setattr(upgrade, "run", run)
    monkeypatch.setattr(upgrade, "compressed_command", Mock())
    operation.helper = Mock(return_value='{"users": 1}')
    operation.dump_mysql = Mock()
    return operation, commands


def test_cutover_accepts_reordering_and_completes_validation(tmp_path, monkeypatch, mounts):
    operation, commands = cutover_fixture(tmp_path, monkeypatch, mounts, mounts[::-1])
    operation.cutover()
    assert operation.stopped is False
    assert (operation.backup / "success.json").is_file()
    assert '"new"' in (operation.apps / "local_agent/__init__.py").read_text()
    assert '"old"' in (operation.backup / "source-before/local_agent/__init__.py").read_text()
    assert ["docker", "stop", "--timeout", "60", "mpau-web"] in commands
    assert any(args[:3] == ["docker", "exec", "mpau-web"] and upgrade.MYSQL_CHECK in args for args in commands)


def test_real_mount_change_stops_cutover_and_allows_rollback(tmp_path, monkeypatch, mounts):
    changed = deepcopy(mounts[::-1])
    changed[0]["Name"] = "wrong-data-volume"
    operation, commands = cutover_fixture(tmp_path, monkeypatch, mounts, changed)
    with pytest.raises(upgrade.UpgradeError, match="切换后挂载变化"):
        operation.cutover()
    assert operation.stopped is True
    assert not (operation.backup / "success.json").exists()
    assert not any(upgrade.MYSQL_CHECK in args for args in commands)
    operation.recover()
    assert operation.stopped is False
    assert '"old"' in (operation.apps / "local_agent/__init__.py").read_text()
    assert commands.count(["docker", "stop", "--timeout", "60", "mpau-web"]) == 2
    assert ["docker", "image", "tag", "old-image", "mpau-web:local"] in commands
