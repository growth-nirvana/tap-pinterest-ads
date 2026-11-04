"""Tests for production config parsing and analytics windows."""

import datetime

from tap_pinterest_ads.streams import (
    AdAnalyticsStream,
    AccountAnalyticsStream,
    attribution_params,
    clamp_analytics_window,
    configured_account_ids,
    parse_start_date,
)


def test_us_start_date_parses_as_july():
    parsed = parse_start_date("07/01/2026")
    assert parsed.date().isoformat() == "2026-07-01"
    assert parsed.tzinfo is not None


def test_iso_dates_parse():
    assert parse_start_date("2026-07-01").date().isoformat() == "2026-07-01"
    assert parse_start_date("2019-10-17T00:00:00Z").year == 2019


def test_july_start_is_clamped_to_the_synchronous_window():
    now = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
    start_day, end_day, clamped = clamp_analytics_window(
        parse_start_date("07/01/2026"),
        now=now,
    )
    assert clamped is True
    assert start_day.isoformat() == "2026-08-06"
    assert end_day.isoformat() == "2026-11-03"
    assert (end_day - start_day).days <= 89


def test_recent_start_is_not_clamped():
    now = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)
    start_day, end_day, clamped = clamp_analytics_window(
        parse_start_date("2026-10-01"),
        now=now,
    )
    assert clamped is False
    assert start_day.isoformat() == "2026-10-01"
    assert end_day.isoformat() == "2026-11-03"


def test_account_ids_and_attribution_windows():
    assert configured_account_ids({"account_ids": "549770689219"}) == {"549770689219"}
    assert configured_account_ids({"account_ids": "1, 2"}) == {"1", "2"}
    assert configured_account_ids({}) == set()
    assert attribution_params(
        {
            "click_window_days": 30,
            "engagement_window_days": 30,
            "view_window_days": 1,
        }
    ) == {
        "click_window_days": 30,
        "engagement_window_days": 30,
        "view_window_days": 1,
    }


def test_identifier_columns_stay_strings():
    for stream_cls, field in (
        (AdAnalyticsStream, "AD_ID"),
        (AdAnalyticsStream, "PIN_ID"),
        (AccountAnalyticsStream, "AD_ACCOUNT_ID"),
        (AccountAnalyticsStream, "CAMPAIGN_NAME"),
    ):
        property_schema = stream_cls.schema["properties"][field]
        assert "string" in property_schema["type"]

    spend = AdAnalyticsStream.schema["properties"]["SPEND_IN_DOLLAR"]
    assert "number" in spend["type"]
