"""Tests for end-time normalization across sources."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from goldscanner.times import end_epoch, with_end_ts


def test_shopgoodwill_naive_is_pacific():
    # 2026-06-16 20:52 PDT == 2026-06-17 03:52 UTC
    ts = end_epoch("2026-06-16T20:52:00", "shopgoodwill")
    expected = datetime(
        2026, 6, 16, 20, 52, tzinfo=ZoneInfo("America/Los_Angeles")
    ).timestamp()
    assert ts == expected
    # Sanity: renders as 11:52 PM in US Eastern (user's example zone).
    eastern = datetime.fromtimestamp(ts, ZoneInfo("America/New_York"))
    assert (eastern.hour, eastern.minute) == (23, 52)


def test_ebay_z_suffix_is_utc():
    ts = end_epoch("2026-06-15T20:00:00.000Z", "ebay")
    assert ts == datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc).timestamp()


def test_missing_or_garbage_end_time():
    assert end_epoch(None, "etsy") is None
    assert end_epoch("", "shopgoodwill") is None
    assert end_epoch("not-a-date", "shopgoodwill") is None


def test_with_end_ts_enriches_dicts():
    items = [
        {"end_time": "2026-06-16T20:52:00", "source": "shopgoodwill"},
        {"end_time": None, "source": "etsy"},
        {"end_time": "2026-06-15T20:00:00Z", "source": "ebay"},
    ]
    out = with_end_ts(items)
    assert out[0]["end_ts"] is not None
    assert out[1]["end_ts"] is None
    assert out[2]["end_ts"] is not None
