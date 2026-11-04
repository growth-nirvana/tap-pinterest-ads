# tap-pinterest-ads

`tap-pinterest-ads` is a Singer tap for Pinterest Ads.

Built with the [Meltano Tap SDK](https://sdk.meltano.com) for Singer Taps.

**Note:** Ad Analytics are filtered for `ACTIVE` ads only, hence totals may not match that of the account analytics, this is done to reduce the number of requests due to the limits imposed by the API.

## Installation

```bash
pipx install git+https://github.com/gthesheep/tap-pinterest-ads.git
```

## Configuration

### Accepted Config Options

- **client_id**: App ID for your Pinterest App
- **client_secret**: App secret key
- **refresh_token**: Refresh token obtained from the OAuth user flow
- **start_date**: Start date to collect ad analytics from
- **is_backfilled**: Set to True once backfilled. `ad_analytics` then leaves out ads that are not ACTIVE and have not changed since the sync window started, since they cannot have delivered in it
- **click_window_days**: Number of days to use as the conversion attribution window for a pin click action (default: 30)
- **engagement_window_days**: Number of days to use as the conversion attribution window for an engagement action (default: 30)
- **view_window_days**: Number of days to use as the conversion attribution window for a view action (default: 1)
- **conversion_report_time**: The date by which the conversion metrics will be reported. Can be either TIME_OF_AD_ACTION or TIME_OF_CONVERSION (default: TIME_OF_AD_ACTION)

### Ad analytics

`ad_analytics` keeps one bookmark per ad account and pulls every ad in the
account for the same dates, up to 250 ads per request. A load that replaces an
account's date range (for example target-bigquery `filtered_replace` keyed on
`AD_ACCOUNT_ID`) therefore never removes rows it did not pull again. Campaigns,
ad groups and ads include archived entities, which still have analytics for the
days they ran.

A full list of supported settings and capabilities for this
tap is available by running:

```bash
tap-pinterest-ads --about
```

### Source Authentication and Authorization

In order to obtain the ```refresh_token``` for your Pinterest Ads account
please follow the OAuth 2.0 flow described by the source docs, [here](https://developers.pinterest.com/docs/api/v5/#tag/Authentication).
We can look to add support for this process in here in the future.

Beyond obtaining the Trial Access for the API, filling of historical data
may require upgrading to Standard Access, depending on use of the ads service.

## Available Streams

### Advertiser History (ad_accounts)
Contains information about Pinterest ad accounts:
- Basic info: id, name, country, currency
- Account settings: account_permissions, billing_profile_status, billing_type
- Owner info: owner_user_id, owner_username
- Status and timestamps: status, created_time, updated_time
- Merchant info: merchant_id

### Campaign History (campaigns)
Contains campaign-level information:
- Basic info: id, name, status, objective_type
- Budget settings: lifetime_spend_cap, daily_spend_cap, default_ad_group_budget_in_micro_currency
- Campaign settings: campaign_budget_optimization_enabled, is_automated_campaign, is_campaign_budget_optimization, is_flexible_daily_budgets
- Timestamps: created_time, updated_time, start_time, end_time
- Status info: summary_status

### Ad Group History (ad_groups)
Contains ad group-level information:
- Basic info: id, name, status
- Budget and bid settings: budget_in_micro_currency, bid_in_micro_currency, budget_type, bid_strategy_type
- Targeting settings: targeting_spec fields (flattened)
- Status and timestamps: created_time, updated_time, start_time, end_time
- Additional settings: auto_targeting_enabled, placement_group, pacing_delivery_type, conversion_learning_mode_type

### Ad Group Report (ad_analytics)
Contains detailed analytics for ad groups including:
- Basic metrics: impressions, clicks, spend
- Conversion metrics: checkouts, leads, signups
- Cross-device conversion metrics (desktop/mobile/tablet)
- Web-specific metrics
- Cost per action metrics
- ROAS metrics
- Video metrics
- All metrics are available with attribution window settings

### Campaign Report (account_analytics)
Contains the same metrics as Ad Group Report but at the campaign level.

## Usage

You can easily run `tap-pinterest-ads` by itself or in a pipeline using [Meltano](https://meltano.com/).

### Executing the Tap Directly

```bash
tap-pinterest-ads --version
tap-pinterest-ads --help
tap-pinterest-ads --config CONFIG --discover > ./catalog.json
```

### Initialize your Development Environment

```bash
pipx install poetry
poetry install
```

### Create and Run Tests

Create tests within the `tap_pinterest_ads/tests` sub-folder and
  then run:

```bash
poetry run pytest
```

You can also test the `tap-pinterest-ads` CLI interface directly using `poetry run`:

```bash
poetry run tap-pinterest-ads --help
```
