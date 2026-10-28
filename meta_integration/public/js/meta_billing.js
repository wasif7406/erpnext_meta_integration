// Meta Billing: post one card / wallet charge.
//  Already paid  -> Journal Entry  (Dr Ad Expense / Cr card|wallet)
//  On credit     -> Purchase Invoice (Creditors), settled later by a Payment Entry
frappe.ui.form.on("Meta Billing", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Open Journal Entry"), () => {
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry);
			});
			return;
		}
		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(__("Open Purchase Invoice"), () => {
				frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice);
			});
			return;
		}

		const on_credit = (frm.doc.payment_mode || "").startsWith("On credit");
		const label = on_credit ? __("Create Purchase Invoice") : __("Post Journal Entry");
		frm.add_custom_button(label, () => {
			frappe.confirm(
				on_credit
					? __("Bill {0} to {1}? Settle it later with a Payment Entry.", [
							format_currency(frm.doc.base_amount),
							frm.doc.supplier || __("the supplier"),
					  ])
					: __("Post {0} as {1} / {2}?", [
							format_currency(frm.doc.base_amount),
							__("Dr") + " " + (frm.doc.expense_account || ""),
							__("Cr") + " " + (frm.doc.paid_from || __("Paid From")),
					  ]),
				() => {
					frappe.call({
						method: "meta_integration.api.post_billing",
						args: { billing: frm.doc.name },
						freeze: true,
						freeze_message: __("Posting…"),
						callback: (r) => {
							const res = r.message || {};
							const voucher = res.journal_entry || res.purchase_invoice;
							if (voucher) {
								frappe.show_alert({
									message: __("Posted {0}", [voucher]),
									indicator: "green",
								});
								frm.reload_doc();
							} else if (res.reason) {
								frappe.msgprint(res.reason);
							}
						},
					});
				}
			);
		});
	},
});
