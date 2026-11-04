import datetime

from tap_pinterest_ads.streams import ads_to_request

WINDOW_START = datetime.date(2026, 10, 1)
BEFORE = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc).timestamp()
DURING = datetime.datetime(2026, 10, 2, tzinfo=datetime.timezone.utc).timestamp()

ADS = [
    {"id": 1, "status": "ACTIVE", "updated_time": BEFORE},
    {"id": 2, "status": "PAUSED", "updated_time": BEFORE},
    {"id": 3, "status": "PAUSED", "updated_time": DURING},
    {"id": 4, "status": "ARCHIVED", "updated_time": None},
]


def test_every_ad_is_pulled_before_backfill():
    assert ads_to_request(ADS, WINDOW_START, skip_inactive=False) == ["1", "2", "3", "4"]


def test_inactive_ads_unchanged_since_the_window_started_are_skipped():
    assert ads_to_request(ADS, WINDOW_START, skip_inactive=True) == ["1", "3"]


def test_an_ad_paused_on_the_first_day_of_the_window_is_pulled():
    midnight = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc).timestamp()
    ads = [{"id": 5, "status": "PAUSED", "updated_time": midnight}]
    assert ads_to_request(ads, WINDOW_START, skip_inactive=True) == ["5"]
