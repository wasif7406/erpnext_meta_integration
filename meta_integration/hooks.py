app_name = "meta_integration"
app_title = "Meta Integration"
app_publisher = "Aqreno Nova"
app_description = "Meta (Facebook/Instagram) ad spend analytics for ERPNext — read-only"
app_email = "dev@aqrenonova.com"
app_license = "mit"
app_version = "0.2.0"

required_apps = ["erpnext"]

# Read-only by design: no journal entries, invoices or payments are ever created
# here. Spend is synced for analytics and compared against the ledger.
doctype_js = {
	"Meta Account": "public/js/meta_account.js",
	"Meta Campaign": "public/js/meta_reporting.js",
	"Meta Ad Set": "public/js/meta_reporting.js",
	"Meta Ad": "public/js/meta_reporting.js",
}

before_install = "meta_integration.install.before_install"
after_install = "meta_integration.install.after_install"
after_migrate = "meta_integration.install.after_migrate"

# Spend is restated for a few days, so the sync runs daily and re-reads a window.
scheduler_events = {
	"cron": {
		"0 2 * * *": ["meta_integration.tasks.sync_all_accounts"],
	},
	"weekly": ["meta_integration.tasks.prune_logs"],
}

fixtures = []
