"""Stream type classes for tap-pinterest."""
import copy
import datetime
from urllib.parse import urlparse
from urllib.parse import parse_qs

import requests
from typing import Any, Callable, Dict, Iterable, Optional

from tap_pinterest_ads.client import PinterestStream

from singer_sdk.typing import (
    ArrayType,
    ObjectType,
    BooleanType,
    Property,
    DateTimeType,
    NumberType,
    PropertiesList,
    StringType,
)

# Base properties that should be included in all streams
BASE_PROPERTIES = [
    Property("run_id", NumberType),
]

# Pinterest returns these as identifiers or names. Several are larger than
# JSON numbers can represent exactly, so they are stored as strings.
STRING_ANALYTICS_FIELDS = {
    "AD_ACCOUNT_ID",
    "AD_GROUP_ID",
    "AD_ID",
    "CAMPAIGN_ID",
    "CAMPAIGN_NAME",
    "PIN_ID",
}

# Synchronous analytics cannot start more than 90 days ago, and a single
# request cannot span more than 90 days.
SYNC_LOOKBACK_DAYS = 90
SYNC_MAX_SPAN_DAYS = 89


def parse_start_date(value: str) -> datetime.datetime:
    """Parse config and bookmark dates, including Hotglue's MM/DD/YYYY values."""
    text = str(value).strip()
    us_date = datetime.datetime.strptime(text, "%m/%d/%Y") if "/" in text else None
    if us_date is not None:
        parsed = us_date
    else:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def clamp_analytics_window(
    start: datetime.datetime,
    now: Optional[datetime.datetime] = None,
) -> tuple:
    """Return (start_day, end_day, clamped) inside the synchronous API limits."""
    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    earliest = (current - datetime.timedelta(days=SYNC_LOOKBACK_DAYS)).date()
    yesterday = (current - datetime.timedelta(days=1)).date()
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    start_day = start.astimezone(datetime.timezone.utc).date()
    clamped = start_day < earliest
    if clamped:
        start_day = earliest
    end_day = min(start_day + datetime.timedelta(days=SYNC_MAX_SPAN_DAYS), yesterday)
    return start_day, end_day, clamped


def configured_account_ids(config: dict) -> set:
    """Return the account IDs named in config, or an empty set for all accounts."""
    raw = config.get("account_ids")
    if raw is None or str(raw).strip() == "":
        return set()
    parts = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return {str(part).strip() for part in parts if str(part).strip()}


def attribution_params(config: dict) -> dict:
    """Map the production attribution settings onto Pinterest query params."""
    params = {}
    defaults = {
        "click_window_days": 30,
        "engagement_window_days": 30,
        "view_window_days": 1,
    }
    for key, default in defaults.items():
        value = config.get(key, default)
        if value is None or value == "":
            continue
        params[key] = int(value)
    report_time = config.get("conversion_report_time")
    if report_time:
        params["conversion_report_time"] = report_time
    return params


def analytics_schema(*leading_properties, columns):
    """Build an analytics schema without turning identifier columns into numbers."""
    properties = [*BASE_PROPERTIES, *leading_properties]
    seen = {prop.name for prop in properties}
    for column in columns:
        if column in seen:
            continue
        column_type = StringType if column in STRING_ANALYTICS_FIELDS else NumberType
        properties.append(Property(column, column_type))
        seen.add(column)
    return PropertiesList(*properties).to_dict()

class AdAccountStream(PinterestStream):
    name = 'ad_accounts'
    path = 'ad_accounts'
    primary_keys = ["id"]
    replication_key = None
    schema = PropertiesList(
        *BASE_PROPERTIES,
        Property("id", StringType),
        Property("name", StringType),
        Property("owner",
            ObjectType(
                Property("username", StringType)
            )
        ),
        Property("country", StringType),
        Property("currency", StringType),
    ).to_dict()

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Dict[str, Any]:
        params = super().get_url_params(context, next_page_token)
        params["include_shared_accounts"] = "true"
        return params

    def get_child_context(self, record: dict, context: Optional[dict]) -> dict:
        """Return a context dictionary for child streams."""
        return {
            "ad_account_id": record["id"],
        }

    def get_records(self, context: Optional[dict] = None) -> Iterable[Dict[str, Any]]:
        """Return a generator of row-type dictionary objects.
        Each row emitted should be a dictionary of property names to their values.
        """
        account_ids_str = self.config.get("account_ids")
        if account_ids_str:
            # Split the comma-separated string and strip whitespace
            account_ids = {id.strip() for id in account_ids_str.split(",") if id.strip()}
            # Track which accounts we've found
            found_accounts = set()

        for record in super().get_records(context):
            if account_ids_str:
                if record["id"] in account_ids:
                    found_accounts.add(record["id"])
                    yield record
            else:
                yield record

        # After processing all records, check if we found all requested accounts
        if account_ids_str and found_accounts != account_ids:
            missing_accounts = account_ids - found_accounts
            self.logger.warning(f"Some requested accounts were not found: {missing_accounts}")


class CampaignStream(PinterestStream):
    name = 'campaigns'
    parent_stream_type = AdAccountStream
    path = "ad_accounts/{ad_account_id}/campaigns"
    ignore_parent_replication_keys = True
    primary_keys = ["id"]
    replication_key = None
    schema = PropertiesList(
        *BASE_PROPERTIES,
        Property("id", StringType),
        Property("ad_account_id", StringType),
        Property("name", StringType),
        Property("status", StringType),
        Property("lifetime_spend_cap", NumberType),
        Property("daily_spend_cap", NumberType),
        Property("order_line_id", StringType),
        Property("tracking_urls",
            ObjectType(
                Property("impression", ArrayType(StringType)),
                Property("click", ArrayType(StringType)),
                Property("engagement", ArrayType(StringType)),
                Property("buyable_button", ArrayType(StringType)),
                Property("audience_verification", ArrayType(StringType)),
            )
        ),
        Property("objective_type", StringType),
        Property("created_time", NumberType),
        Property("updated_time", NumberType),
        Property("type", StringType),
    ).to_dict()


class AdGroupStream(PinterestStream):
    name = 'ad_groups'
    parent_stream_type = AdAccountStream
    path = "ad_accounts/{ad_account_id}/ad_groups"
    ignore_parent_replication_keys = True
    primary_keys = ["id"]
    replication_key = None
    schema = PropertiesList(
        *BASE_PROPERTIES,
        Property("name", StringType),
        Property("status", StringType),
        Property("budget_in_micro_currency", NumberType),
        Property("bid_in_micro_currency", NumberType),
        Property("budget_type", StringType),
        Property("start_time", NumberType),
        Property("end_time", NumberType),
        Property("targeting_spec",  # might need this to not specify dict keys
            ObjectType(
                Property("AGE_BUCKET", ArrayType(StringType)),
                Property("LOCATION", ArrayType(StringType)),
                Property("SHOPPING_RETARGETING", ArrayType(StringType)),
                Property("AUDIENCE_INCLUDE", ArrayType(StringType)),
                Property("TARGETING_STRATEGY", ArrayType(StringType)),
                Property("GENDER", ArrayType(StringType)),
                Property("INTEREST", ArrayType(StringType)),
                Property("LOCALE", ArrayType(StringType)),
                Property("APPTYPE", ArrayType(StringType)),
                Property("AUDIENCE_EXCLUDE", ArrayType(StringType)),
            )
        ),
        Property("lifetime_frequency_cap", NumberType),
        Property("tracking_urls",
             ObjectType(
                 Property("impression", ArrayType(StringType)),
                 Property("click", ArrayType(StringType)),
                 Property("engagement", ArrayType(StringType)),
                 Property("buyable_button", ArrayType(StringType)),
                 Property("audience_verification", ArrayType(StringType)),
             )
        ),
        Property("auto_targeting_enabled", BooleanType),
        Property("placement_group", StringType),
        Property("pacing_delivery_type", StringType),
        Property("conversion_learning_mode_type", StringType),
        Property("summary_status", StringType),
        Property("feed_profile_id", StringType),
        Property("campaign_id", StringType),
        Property("billable_event", StringType),
        Property("id", StringType),
        Property("type", StringType),
        Property("ad_account_id", StringType),
        Property("created_time", NumberType),
        Property("updated_time", NumberType),
    ).to_dict()


class AdStream(PinterestStream):
    name = 'ads'
    parent_stream_type = AdAccountStream
    path = "ad_accounts/{ad_account_id}/ads"
    ignore_parent_replication_keys = True
    primary_keys = ["id"]
    replication_key = None
    schema = PropertiesList(
        *BASE_PROPERTIES,
        Property("ad_group_id", StringType),
        Property("android_deep_link", StringType),
        Property("carousel_android_deep_links", ArrayType(StringType)),
        Property("carousel_destination_urls", ArrayType(StringType)),
        Property("carousel_ios_deep_links", ArrayType(StringType)),
        Property("click_tracking_url", StringType),
        Property("creative_type", StringType),
        Property("destination_url", StringType),
        Property("ios_deep_link", StringType),
        Property("is_pin_deleted", BooleanType),
        Property("is_removable", BooleanType),
        Property("name", StringType),
        Property("pin_id", StringType),
        Property("status", StringType),
        Property("tracking_urls",
             ObjectType(
                 Property("impression", ArrayType(StringType)),
                 Property("click", ArrayType(StringType)),
                 Property("engagement", ArrayType(StringType)),
                 Property("buyable_button", ArrayType(StringType)),
                 Property("audience_verification", ArrayType(StringType)),
             )
        ),
        Property("view_tracking_url", StringType),
        Property("ad_account_id", StringType),
        Property("campaign_id", StringType),
        Property("collection_items_destination_url_template", StringType),
        Property("created_time", NumberType),
        Property("id", StringType),
        Property("rejected_reasons", ArrayType(StringType)),
        Property("rejection_labels", ArrayType(StringType)),
        Property("review_status", StringType),
        Property("type", StringType),
        Property("updated_time", NumberType),
        Property("summary_status", StringType),
    ).to_dict()

    def get_child_context(self, record: dict, context: Optional[dict]) -> dict:
        """Return a context dictionary for child streams."""
        return {
            "ad_account_id": record["ad_account_id"],
            "ad_id": record["id"],
            "ad_status": record["status"]
        }


AD_ANALYTICS_COLUMNS = [
    "AD_ACCOUNT_ID", "AD_GROUP_ENTITY_STATUS", "AD_GROUP_ID",
    "AD_ID", "CAMPAIGN_DAILY_SPEND_CAP", "CAMPAIGN_ENTITY_STATUS",
    "CAMPAIGN_ID", "CAMPAIGN_LIFETIME_SPEND_CAP",
    "CHECKOUT_ROAS", "CLICKTHROUGH_1", "CLICKTHROUGH_1_GROSS",
    "CLICKTHROUGH_2", "CPC_IN_MICRO_DOLLAR", "CPM_IN_DOLLAR",
    "CPM_IN_MICRO_DOLLAR", "CTR", "CTR_2", "ECPCV_IN_DOLLAR",
    "ECPCV_P95_IN_DOLLAR", "ECPC_IN_DOLLAR", "ECPC_IN_MICRO_DOLLAR",
    "ECPE_IN_DOLLAR", "ECPM_IN_MICRO_DOLLAR", "ECPV_IN_DOLLAR",
    "ECTR", "EENGAGEMENT_RATE", "ENGAGEMENT_1", "ENGAGEMENT_2",
    "ENGAGEMENT_RATE", "IDEA_PIN_PRODUCT_TAG_VISIT_1",
    "IDEA_PIN_PRODUCT_TAG_VISIT_2", "IMPRESSION_1", "IMPRESSION_1_GROSS",
    "IMPRESSION_2", "INAPP_CHECKOUT_COST_PER_ACTION", "OUTBOUND_CLICK_1",
    "OUTBOUND_CLICK_2", "PAGE_VISIT_COST_PER_ACTION", "PAGE_VISIT_ROAS",
    "PAID_IMPRESSION", "PIN_ID", "REPIN_1", "REPIN_2", "REPIN_RATE",
    "SPEND_IN_DOLLAR", "SPEND_IN_MICRO_DOLLAR", "TOTAL_CHECKOUT",
    "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_CLICKTHROUGH",
    "TOTAL_CLICK_CHECKOUT", "TOTAL_CLICK_CHECKOUT_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_CLICK_LEAD", "TOTAL_CLICK_SIGNUP", "TOTAL_CLICK_SIGNUP_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_CONVERSIONS", "TOTAL_CUSTOM", "TOTAL_ENGAGEMENT", "TOTAL_ENGAGEMENT_CHECKOUT",
    "TOTAL_ENGAGEMENT_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_ENGAGEMENT_LEAD",
    "TOTAL_ENGAGEMENT_SIGNUP", "TOTAL_ENGAGEMENT_SIGNUP_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_IDEA_PIN_PRODUCT_TAG_VISIT", "TOTAL_IMPRESSION_FREQUENCY",
    "TOTAL_IMPRESSION_USER", "TOTAL_LEAD", "TOTAL_PAGE_VISIT",
    "TOTAL_REPIN_RATE", "TOTAL_SIGNUP", "TOTAL_SIGNUP_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_VIDEO_3SEC_VIEWS", "TOTAL_VIDEO_AVG_WATCHTIME_IN_SECOND",
    "TOTAL_VIDEO_MRC_VIEWS", "TOTAL_VIDEO_P0_COMBINED", "TOTAL_VIDEO_P100_COMPLETE",
    "TOTAL_VIDEO_P25_COMBINED", "TOTAL_VIDEO_P50_COMBINED", "TOTAL_VIDEO_P75_COMBINED",
    "TOTAL_VIDEO_P95_COMBINED", "TOTAL_VIEW_CHECKOUT", "TOTAL_VIEW_CHECKOUT_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_VIEW_LEAD", "TOTAL_VIEW_SIGNUP", "TOTAL_VIEW_SIGNUP_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_WEB_CHECKOUT", "TOTAL_WEB_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_CLICK_CHECKOUT",
    "TOTAL_WEB_CLICK_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_ENGAGEMENT_CHECKOUT",
    "TOTAL_WEB_ENGAGEMENT_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_VIEW_CHECKOUT",
    "TOTAL_WEB_VIEW_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "VIDEO_3SEC_VIEWS_2", "VIDEO_LENGTH",
    "VIDEO_MRC_VIEWS_2", "VIDEO_P0_COMBINED_2", "VIDEO_P100_COMPLETE_2", "VIDEO_P25_COMBINED_2",
    "VIDEO_P50_COMBINED_2", "VIDEO_P75_COMBINED_2", "VIDEO_P95_COMBINED_2",
    "WEB_CHECKOUT_COST_PER_ACTION", "WEB_CHECKOUT_ROAS"
]

class PinterestAnalyticsStream(PinterestStream):
    """Shared date, attribution, and identifier handling for analytics streams."""

    columns: list = []

    def get_starting_timestamp(self, context: Optional[dict]) -> Optional[datetime.datetime]:
        value = self.get_starting_replication_key_value(context)
        if value is None:
            value = self.config.get("start_date")
        if value is None:
            return None
        return parse_start_date(value)

    def _parse_datetime(self, value: str) -> datetime.datetime:
        return parse_start_date(value)

    def analytics_bounds(self, context: Optional[dict], next_page_token: Optional[Any]):
        """Return the request window, or None when it cannot contain rows."""
        if next_page_token:
            start = (
                next_page_token
                if isinstance(next_page_token, datetime.datetime)
                else parse_start_date(str(next_page_token))
            )
        else:
            start = self.get_starting_timestamp(context)
            if start is None:
                start = parse_start_date("2019-10-17T00:00:00Z")
        start_day, end_day, clamped = clamp_analytics_window(start)
        if end_day < start_day:
            return None
        return start_day, end_day, clamped, start

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Optional[dict]:
        bounds = self.analytics_bounds(context, next_page_token)
        if bounds is None:
            self.logger.info(
                "%s has no available dates for the configured start_date",
                self.name,
            )
            return None
        start_day, end_day, clamped, requested = bounds
        if clamped and not getattr(self, "_logged_lookback_clamp", False):
            self._logged_lookback_clamp = True
            self.logger.info(
                "%s start_date %s is outside the last %s days Pinterest allows "
                "for synchronous analytics. Requesting %s through %s.",
                self.name,
                requested.date().isoformat(),
                SYNC_LOOKBACK_DAYS,
                start_day.isoformat(),
                end_day.isoformat(),
            )
        params = {
            "start_date": start_day.strftime("%Y-%m-%d"),
            "end_date": end_day.strftime("%Y-%m-%d"),
            "granularity": "DAY",
            "columns": ",".join(self.columns),
        }
        params.update(attribution_params(self.config))
        self.logger.info(
            "%s requesting %s through %s",
            self.name,
            params["start_date"],
            params["end_date"],
        )
        return params

    def get_records(self, context: Optional[dict] = None) -> Iterable[Dict[str, Any]]:
        if self.analytics_bounds(context, None) is None:
            return []
        return super().get_records(context)

    def post_process(self, row: dict, context: Optional[dict] = None) -> Optional[dict]:
        if row.get("DATE"):
            row["DATE"] = datetime.datetime.strptime(row["DATE"], "%Y-%m-%d").strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        for field in STRING_ANALYTICS_FIELDS:
            if row.get(field) is not None:
                row[field] = str(row[field])
        return row

    def get_next_page_token(
        self, response: requests.Response, previous_token: Optional[Any]
    ) -> Any:
        query = parse_qs(urlparse(response.request.url).query)
        end_date = datetime.datetime.strptime(query["end_date"][0], "%Y-%m-%d")
        yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        if end_date.date() < yesterday.date():
            return end_date + datetime.timedelta(days=1)
        return None


class AdAnalyticsStream(PinterestAnalyticsStream):
    name = 'ad_analytics'
    parent_stream_type = AdStream
    path = "ad_accounts/{ad_account_id}/ads/analytics"
    records_jsonpath = "$[*]"
    ignore_parent_replication_keys = True
    primary_keys = ["AD_ID", "DATE"]
    replication_key = "DATE"
    state_partitioning_keys = ["AD_ID"]
    columns = AD_ANALYTICS_COLUMNS
    schema = analytics_schema(
        Property("AD_ID", StringType),
        Property("DATE", DateTimeType),
        columns=AD_ANALYTICS_COLUMNS,
    )

    def get_url_params(
        self, context: Optional[dict], next_page_token: Optional[Any]
    ) -> Optional[dict]:
        params = super().get_url_params(context, next_page_token)
        if params is None:
            return None
        params["ad_ids"] = context["ad_id"]
        return params

    def get_records(self, context: Optional[dict] = None) -> Iterable[Dict[str, Any]]:
        """Return a generator of row-type dictionary objects.
        Each row emitted should be a dictionary of property names to their values.
        """
        if context["ad_status"] != "ACTIVE" and self.config.get("is_backfilled", False) == True:
            self.logger.info("Skipping inactive ad {ad_id} sync.".format(ad_id=context["ad_id"]))
            return []
        return super().get_records(context)


ACCOUNT_ANALYTICS_COLUMNS = [
    "AD_GROUP_ENTITY_STATUS", "CAMPAIGN_DAILY_SPEND_CAP",
    "CAMPAIGN_ENTITY_STATUS", "CAMPAIGN_ID", "CAMPAIGN_LIFETIME_SPEND_CAP", "CAMPAIGN_NAME",
    "CHECKOUT_ROAS", "CLICKTHROUGH_1", "CLICKTHROUGH_1_GROSS", "CLICKTHROUGH_2",
    "CPC_IN_MICRO_DOLLAR", "CPM_IN_DOLLAR", "CPM_IN_MICRO_DOLLAR", "CTR", "CTR_2",
    "ECPCV_IN_DOLLAR", "ECPCV_P95_IN_DOLLAR", "ECPC_IN_DOLLAR", "ECPC_IN_MICRO_DOLLAR",
    "ECPE_IN_DOLLAR", "ECPM_IN_MICRO_DOLLAR", "ECPV_IN_DOLLAR", "ECTR", "EENGAGEMENT_RATE",
    "ENGAGEMENT_1", "ENGAGEMENT_2", "ENGAGEMENT_RATE", "IDEA_PIN_PRODUCT_TAG_VISIT_1",
    "IDEA_PIN_PRODUCT_TAG_VISIT_2", "IMPRESSION_1", "IMPRESSION_1_GROSS", "IMPRESSION_2",
    "INAPP_CHECKOUT_COST_PER_ACTION", "OUTBOUND_CLICK_1", "OUTBOUND_CLICK_2",
    "PAGE_VISIT_COST_PER_ACTION", "PAGE_VISIT_ROAS", "PAID_IMPRESSION", "PIN_ID", "REPIN_1",
    "REPIN_2", "REPIN_RATE", "SPEND_IN_DOLLAR", "SPEND_IN_MICRO_DOLLAR", "TOTAL_CHECKOUT",
    "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_CLICKTHROUGH", "TOTAL_CLICK_CHECKOUT",
    "TOTAL_CLICK_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_CLICK_SIGNUP",
    "TOTAL_CLICK_SIGNUP_VALUE_IN_MICRO_DOLLAR", "TOTAL_CONVERSIONS", "TOTAL_CUSTOM",
    "TOTAL_ENGAGEMENT", "TOTAL_ENGAGEMENT_CHECKOUT",
    "TOTAL_ENGAGEMENT_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_ENGAGEMENT_SIGNUP",
    "TOTAL_ENGAGEMENT_SIGNUP_VALUE_IN_MICRO_DOLLAR", "TOTAL_IDEA_PIN_PRODUCT_TAG_VISIT",
    "TOTAL_IMPRESSION_FREQUENCY", "TOTAL_IMPRESSION_USER", "TOTAL_LEAD", "TOTAL_PAGE_VISIT",
    "TOTAL_REPIN_RATE", "TOTAL_SIGNUP", "TOTAL_SIGNUP_VALUE_IN_MICRO_DOLLAR",
    "TOTAL_VIDEO_3SEC_VIEWS", "TOTAL_VIDEO_AVG_WATCHTIME_IN_SECOND", "TOTAL_VIDEO_MRC_VIEWS",
    "TOTAL_VIDEO_P0_COMBINED", "TOTAL_VIDEO_P100_COMPLETE", "TOTAL_VIDEO_P25_COMBINED",
    "TOTAL_VIDEO_P50_COMBINED", "TOTAL_VIDEO_P75_COMBINED", "TOTAL_VIDEO_P95_COMBINED",
    "TOTAL_VIEW_CHECKOUT", "TOTAL_VIEW_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_VIEW_SIGNUP",
    "TOTAL_VIEW_SIGNUP_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_CHECKOUT",
    "TOTAL_WEB_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_CLICK_CHECKOUT",
    "TOTAL_WEB_CLICK_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_ENGAGEMENT_CHECKOUT",
    "TOTAL_WEB_ENGAGEMENT_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "TOTAL_WEB_VIEW_CHECKOUT",
    "TOTAL_WEB_VIEW_CHECKOUT_VALUE_IN_MICRO_DOLLAR", "VIDEO_3SEC_VIEWS_2", "VIDEO_LENGTH",
    "VIDEO_MRC_VIEWS_2", "VIDEO_P0_COMBINED_2", "VIDEO_P100_COMPLETE_2", "VIDEO_P25_COMBINED_2",
    "VIDEO_P50_COMBINED_2", "VIDEO_P75_COMBINED_2", "VIDEO_P95_COMBINED_2", "WEB_CHECKOUT_COST_PER_ACTION",
    "WEB_CHECKOUT_ROAS"
]

class AccountAnalyticsStream(PinterestAnalyticsStream):
    name = 'account_analytics'
    parent_stream_type = AdAccountStream
    path = "ad_accounts/{ad_account_id}/analytics"
    records_jsonpath = "$[*]"
    ignore_parent_replication_keys = True
    primary_keys = ["AD_ACCOUNT_ID", "DATE"]
    replication_key = "DATE"
    columns = ACCOUNT_ANALYTICS_COLUMNS
    schema = analytics_schema(
        Property("AD_ACCOUNT_ID", StringType),
        Property("DATE", DateTimeType),
        columns=ACCOUNT_ANALYTICS_COLUMNS,
    )
