"""pinterest tap class."""

from typing import List

from singer_sdk import Tap, Stream
from singer_sdk import typing as th  # JSON schema typing helpers

from tap_pinterest_ads.streams import (
    AdAccountStream,
    CampaignStream,
    AdGroupStream,
    AdStream,
    AdAnalyticsStream,
    AccountAnalyticsStream,
)
STREAM_TYPES = [
    AdAccountStream,
    CampaignStream,
    AdGroupStream,
    AdStream,
    AdAnalyticsStream,
    AccountAnalyticsStream,
]


class TapPinterestAds(Tap):
    """pinterest tap class."""
    name = "tap-pinterest-ads"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "client_id",
            th.StringType,
            required=True,
            description="App ID"
        ),
        th.Property(
            "client_secret",
            th.StringType,
            required=True,
            description="App secret key"
        ),
        th.Property(
            "refresh_token",
            th.StringType,
            required=True,
            description="Refresh token obtained from the OAuth user flow"
        ),
        th.Property(
            "start_date",
            th.StringType,
            default="2019-10-17T00:00:00Z",
            description=(
                "Date to start collecting analytics from. Accepts YYYY-MM-DD, "
                "ISO-8601, or MM/DD/YYYY. Synchronous Pinterest analytics only "
                "return the last 90 days, so older dates are moved forward."
            ),
        ),
        th.Property(
            "account_ids",
            th.StringType,
            required=False,
            description=(
                "Optional comma-separated ad account IDs. When omitted, every "
                "account the token can access is synced."
            ),
        ),
        th.Property(
            "click_window_days",
            th.IntegerType,
            default=30,
            description="Conversion attribution window in days for a pin click",
        ),
        th.Property(
            "engagement_window_days",
            th.IntegerType,
            default=30,
            description="Conversion attribution window in days for an engagement",
        ),
        th.Property(
            "view_window_days",
            th.IntegerType,
            default=1,
            description="Conversion attribution window in days for a view",
        ),
        th.Property(
            "is_backfilled",
            th.BooleanType,
            default=False,
            description="Set to True once backfilled in order to reduce API calls per day"
        ),
        th.Property(
            "conversion_report_time",
            th.StringType,
            required=False,
            default="TIME_OF_AD_ACTION",
            description="The date by which the conversion metrics will be reported. Can be either TIME_OF_AD_ACTION or TIME_OF_CONVERSION."
        ),
    ).to_dict()

    def discover_streams(self) -> List[Stream]:
        """Return a list of discovered streams."""
        return [stream_class(tap=self) for stream_class in STREAM_TYPES]
