// Meta Billing: turn one card charge into a Purchase Invoice.
frappe.ui.form.on("Meta Billing", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(__("Open Purchase Invoice"), () => {
				frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice);
			});
			return;
		}
		frm.add_custom_button(__("Create Purchase Invoice"), () => {
			frappe.confirm(
				__("Post {0} as a Purchase Invoice for {1}?", [
					format_currency(frm.doc.base_amount, frappe.defaults.get_default("currency")),
					frm.doc.supplier || __("the supplier"),
				]),
				() => {
					frappe.call({
						method: "meta_integration.api.post_billing_purchase_invoice",
						args: { billing: frm.doc.name },
						freeze: true,
						freeze_message: __("Posting Purchase Invoice..."),
						callback: (r) => {
							const res = r.message || {};
							if (res.purchase_invoice) {
								frappe.show_alert({
									message: __("Invoice {0} posted", [res.purchase_invoice]),
									indicator: "green",
								});
								frm.reload_doc();
							}
						},
					});
				}
			);
		});
	},
});
