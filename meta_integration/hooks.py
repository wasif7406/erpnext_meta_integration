app_name = "meta_integration"
app_title = "Meta Integration"
app_publisher = "Aqreno Nova"
app_description = "Meta (Facebook/Instagram) Ads spend to ERPNext expense and payables"
app_email = "dev@aqrenonova.com"
app_license = "mit"
app_version = "0.1.0"

required_apps = ["erpnext"]

doctype_js = {
	"Meta Account": "public/js/meta_account.js",
	"Meta Campaign": "public/js/meta_reporting.js",
	"Meta Ad Set": "public/js/meta_reporting.js",
	"Meta Ad": "public/js/meta_reporting.js",
}

before_install = "meta_integration.install.before_install"
after_install = "meta_integration.install.after_install"
after_migrate = "meta_integration.install.after_migrate"

# Spend is restated by Meta for a few days, so the sync runs daily and always
# re-reads the last `sync_days` window. Booking is opt-in per account.
scheduler_events = {
	"cron": {
		"0 2 * * *": ["meta_integration.tasks.sync_all_accounts"],
		"0 4 1 * *": ["meta_integration.tasks.book_previous_month"],
	},
	"weekly": ["meta_integration.tasks.prune_logs"],
}

fixtures = []
