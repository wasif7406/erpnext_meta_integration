"""Meta-wide constants (not company-specific)."""

# Bumped whenever we need to prove which code a site is running; call
# `meta_integration.api.health` after a deploy and compare.
BUILD = "2026-10-30.1"

BASE_URL = "https://graph.facebook.com"

# Marketing API v25.0 (released 2026-02-18); v24.0 expired 2026-10-06.
DEFAULT_API_VERSION = "v25.0"

CAMPAIGN_FIELDS = "id,name,status,objective,daily_budget,lifetime_budget,start_time,stop_time,created_time"
AD_SET_FIELDS = (
	"id,name,status,campaign_id,daily_budget,lifetime_budget,"
	"optimization_goal,billing_event,start_time,end_time,created_time"
)
AD_FIELDS = "id,name,status,adset_id,campaign_id,created_time"
INSIGHT_FIELDS = (
	"account_id,account_name,account_currency,"
	"campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
	"spend,impressions,clicks,date_start,date_stop"
)

PAGE_SIZE = 200
MAX_PAGES = 100

# Spend is restated for a few days after the fact, so each sync re-reads a window.
DEFAULT_SYNC_DAYS = 7
