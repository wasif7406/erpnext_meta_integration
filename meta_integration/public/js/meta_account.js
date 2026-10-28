// Meta Account: read-only mirror of one ad account.
//  * sync campaigns / ad sets / ads / daily spend (nothing is posted)
//  * jump to the Spend vs Ledger control report
frappe.ui.form.on("Meta Account", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Sync now"), () => sync_now(frm));

		frm.add_custom_button(__("Spend vs Ledger"), () => {
			frappe.set_route("query-report", "Meta Spend vs Ledger", {
				meta_account: frm.doc.name,
			});
		});
	},
});

function sync_now(frm) {
	frappe.call({
		method: "meta_integration.api.sync_now",
		args: { account: frm.doc.name },
		freeze: true,
		freeze_message: __("Fetching campaigns and spend…"),
		callback: (r) => {
			const result = (r.message || {})[frm.doc.name] || {};
			frappe.msgprint({
				title: __("Sync result"),
				message: frappe.utils.escape_html(
					result.summary || result.reason || JSON.stringify(result)
				),
				wide: true,
			});
			frm.reload_doc();
		},
	});
}
