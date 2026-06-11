"""Tests for the activity feed and DB-path persistence resolution."""

import os
import tempfile
from unittest import mock

from goldscanner.activity import ActivityLog
from goldscanner.config import db_is_persistent, resolve_db_path


def test_activity_log_since_and_levels():
    log = ActivityLog(maxlen=5)
    log.add("first")
    log.add("second", "success")
    out = log.since(after=0)
    assert [e["message"] for e in out["events"]] == ["first", "second"]
    assert out["events"][1]["level"] == "success"
    assert out["last_id"] == 2

    # since(after=id) returns only newer entries
    log.add("third")
    out2 = log.since(after=out["last_id"])
    assert [e["message"] for e in out2["events"]] == ["third"]


def test_activity_log_ring_buffer_caps():
    log = ActivityLog(maxlen=3)
    for i in range(6):
        log.add(f"m{i}")
    out = log.since(after=0)
    # only the last 3 are kept, but ids keep climbing
    assert [e["message"] for e in out["events"]] == ["m3", "m4", "m5"]
    assert out["last_id"] == 6


def test_resolve_db_path_prefers_volume():
    with tempfile.TemporaryDirectory() as d:
        # Pretend `d` is the mounted volume.
        with mock.patch("goldscanner.config._VOLUME_DIRS", (d,)):
            resolved = resolve_db_path("goldscanner.db")
            assert resolved == os.path.join(d, "goldscanner.db")
            assert db_is_persistent(resolved)
            # Even a relative path with dirs is placed on the volume by basename.
            assert resolve_db_path("state/app.db") == os.path.join(d, "app.db")


def test_resolve_db_path_respects_absolute():
    assert resolve_db_path("/srv/custom.db") == "/srv/custom.db"


def test_resolve_db_path_no_volume_keeps_relative():
    with mock.patch("goldscanner.config._VOLUME_DIRS", ("/nonexistent-vol-xyz",)):
        assert resolve_db_path("goldscanner.db") == "goldscanner.db"
        assert not db_is_persistent("goldscanner.db")
