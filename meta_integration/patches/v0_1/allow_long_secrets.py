import frappe

# Password fields are not stored in the doctype's table (they live encrypted in
# `__Auth`), but the desk input is capped at `df.length or 140`. A Meta system
# user token is ~230 characters, so the cap has to be raised or the token cannot
# be pasted at all.
FIELDS = {
	"Meta Account": ("access_token", "app_secret"),
}
LENGTH = 1000


def execute():
	try:
		for doctype, fields in FIELDS.items():
			for fieldname in fields:
				name = frappe.db.get_value(
					"DocField", {"parent": doctype, "fieldname": fieldname}, "name"
				)
				if name:
					frappe.db.set_value("DocField", name, "length", LENGTH, update_modified=False)
		frappe.db.commit()
		frappe.clear_cache()
	except Exception:
		frappe.log_error(
			title="Meta: could not raise password field length",
			message=frappe.get_traceback(),
		)
