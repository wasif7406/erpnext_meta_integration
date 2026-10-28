"""Constants that are Meta-wide (not company-specific)."""

# Bumped whenever we need to prove which code a site is actually running; call
# `meta_integration.api.health` after a deploy and compare.
BUILD = "2026-10-29.2"

BASE_URL = "https://graph.facebook.com"

# Marketing API v25.0 (released 2026-02-18); v24.0 expires 2026-10-06.
DEFAULT_API_VERSION = "v25.0"

# ---------------------------------------------------------------------------
# Mapping roles
# ---------------------------------------------------------------------------
ROLE_EXPENSE = "Advertising Expense"
ROLE_PAYABLE = "Payable"
ROLE_COST_CENTER = "Cost Center"

ROLES = (ROLE_EXPENSE, ROLE_PAYABLE, ROLE_COST_CENTER)
REQUIRED_ROLES = (ROLE_EXPENSE, ROLE_PAYABLE)

# role -> (allowed root_types, allowed account_types, allow blank account_type)
ACCOUNT_RULES = {
	ROLE_EXPENSE: (("Expense",), (), True),
	ROLE_PAYABLE: (("Liability",), ("Payable",), False),
}

# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
# How the expense reaches the ledger.
#   billing  : Purchase Invoice from the card/statement charge, settled by Payment Entry
#   accrual  : daily spend booked against a payable (Journal Entry)
RECOGNITION_BILLING = "Billing (Purchase Invoice)"
RECOGNITION_ACCRUAL = "Accrual (spend)"

BOOKING_JOURNAL_ENTRY = "Journal Entry"
BOOKING_PURCHASE_INVOICE = "Purchase Invoice"
BOOKING_MODES = (BOOKING_JOURNAL_ENTRY, BOOKING_PURCHASE_INVOICE)

STATUS_DRAFT = "Draft"
STATUS_BOOKED = "Booked"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped"

# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------
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

# Safety caps so a bad token or a huge account cannot hang a worker.
PAGE_SIZE = 200
MAX_PAGES = 100
MAX_INSIGHT_DAYS = 400

# Daily spend is re-fetched for this many days by default: Meta keeps
# restating spend for a few days after the fact.
DEFAULT_SYNC_DAYS = 7
