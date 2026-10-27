// Entity forms: jump to the daily spend rows of this campaign / ad set / ad.
// Guarded so the file registering three doctypes cannot bind twice when the
// browser loads it again for another entity form.
(function () {
	if (window.__meta_reporting_js_loaded) return;
	window.__meta_reporting_js_loaded = true;

	frappe.ui.form.on("Meta Campaign", {
		refresh(frm) {
			add_spend_button(frm, { campaign: frm.doc.name });
		},
	});

	frappe.ui.form.on("Meta Ad Set", {
		refresh(frm) {
			add_spend_button(frm, { ad_set: frm.doc.name });
		},
	});

	frappe.ui.form.on("Meta Ad", {
		refresh(frm) {
			add_spend_button(frm, { ad: frm.doc.name });
		},
	});

	function add_spend_button(frm, filters) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Daily Spend"), () => {
			frappe.set_route("List", "Meta Insight", filters);
		});
	}
})();
