// Meta Account: company-filtered mapping, sync and expense booking.
frappe.ui.form.on("Meta Account", {
	refresh(frm) {
		set_mapping_queries(frm);
		if (frm.is_new()) return;

		frm.add_custom_button(__("Sync now"), () => sync_now(frm));
		frm.add_custom_button(__("Book expenses…"), () => open_booking_dialog(frm));
		frm.add_custom_button(
			__("Book previous month"),
			() => {
				frappe.confirm(
					__("Book the previous month's selected spend on {0}?", [frm.doc.account_name]),
					() => {
						frappe.call({
							method: "meta_integration.api.book_previous_month",
							args: { account: frm.doc.name },
							freeze: true,
							freeze_message: __("Posting expense…"),
							callback: (r) => show_booking_result(r.message),
						});
					}
				);
			},
			__("More")
		);
	},
	company(frm) {
		set_mapping_queries(frm);
	},
});

function set_mapping_queries(frm) {
	if (!frm.fields_dict.mapping) return;
	const filters = () => ({ company: frm.doc.company, is_group: 0 });
	frm.set_query("account", "mapping", filters);
	frm.set_query("cost_center", "mapping", filters);
}

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

function open_booking_dialog(frm) {
	// Default to the previous month: that is the usual booking cadence.
	const last_month = frappe.datetime.add_months(frappe.datetime.get_today(), -1);
	const from_date = frappe.datetime.month_start(last_month);
	const to_date = frappe.datetime.month_end(last_month);

	frappe.prompt(
		[
			{
				fieldname: "from_date",
				fieldtype: "Date",
				label: __("From Date"),
				default: from_date,
				reqd: 1,
			},
			{
				fieldname: "to_date",
				fieldtype: "Date",
				label: __("To Date"),
				default: to_date,
				reqd: 1,
			},
			{
				fieldname: "posting_date",
				fieldtype: "Date",
				label: __("Posting Date"),
				default: to_date,
			},
		],
		(values) => preview_then_book(frm, values),
		__("Book Meta expenses"),
		__("Preview")
	);
}

function preview_then_book(frm, values) {
	frappe.call({
		method: "meta_integration.api.preview_expenses",
		args: {
			account: frm.doc.name,
			from_date: values.from_date,
			to_date: values.to_date,
		},
		freeze: true,
		freeze_message: __("Reading spend…"),
		callback: (r) => {
			const data = r.message || {};
			if (data.error) {
				frappe.msgprint({
					title: __("Cannot book yet"),
					message: frappe.utils.escape_html(data.error),
					indicator: "red",
				});
				return;
			}
			if (data.already_booked) {
				frappe.msgprint({
					title: __("Already booked"),
					message: __("This period is already booked in {0}.", [data.already_booked]),
					indicator: "orange",
				});
				return;
			}
			if (!data.selected_rows) {
				frappe.msgprint({
					title: __("Nothing to book"),
					message: __(
						"No unbooked spend is selected for reporting in this period. Tick 'Report to ERPNext' on the campaigns, ad sets or ads first."
					),
					indicator: "orange",
				});
				return;
			}
			frappe.confirm(preview_html(data), () => book(frm, values));
		},
	});
}

function preview_html(data) {
	const campaigns = (data.campaigns || [])
		.map(
			(row) => `<tr>
				<td>${frappe.utils.escape_html(row.campaign || "-")}</td>
				<td class="text-right">${format_currency(row.spend, data.currency)}</td>
			</tr>`
		)
		.join("");

	const conversion =
		data.currency && data.company_currency && data.currency !== data.company_currency
			? ` → <b>${format_currency(data.base_total, data.company_currency)}</b>
			   @ ${data.exchange_rate}`
			: "";

	return `
		<p>
			${__("Unbooked ad-days")}: <b>${data.unbooked_rows}</b><br>
			${__("Selected for reporting")}: <b>${data.selected_rows}</b><br>
			${__("Amount")}: <b>${format_currency(data.total, data.currency)}</b>${conversion}
		</p>
		${
			campaigns
				? `<table class="table table-condensed">
					<thead><tr>
						<th>${__("Campaign")}</th>
						<th class="text-right">${__("Spend")}</th>
					</tr></thead>
					<tbody>${campaigns}</tbody>
				   </table>`
				: ""
		}
		<p class="text-muted small">
			${__("Booking")}: ${frappe.utils.escape_html(data.booking_mode)} ·
			Dr ${frappe.utils.escape_html(data.expense_account)} ·
			Cr ${frappe.utils.escape_html(data.payable_account)}
			(${frappe.utils.escape_html(data.supplier || "-")})
		</p>
	`;
}

function book(frm, values) {
	frappe.call({
		method: "meta_integration.api.book_expenses",
		args: {
			account: frm.doc.name,
			from_date: values.from_date,
			to_date: values.to_date,
			posting_date: values.posting_date || values.to_date,
		},
		freeze: true,
		freeze_message: __("Posting expense…"),
		callback: (r) => {
			show_booking_result(r.message);
			frm.reload_doc();
		},
	});
}

function show_booking_result(result) {
	result = result || {};
	if (result.status === "Booked") {
		const doctype = result.voucher_doctype || "Journal Entry";
		frappe.msgprint({
			title: __("Expense booked"),
			message: `${__("Entry")}: <a href="/app/meta-expense-entry/${encodeURIComponent(
				result.entry
			)}">${frappe.utils.escape_html(result.entry)}</a><br>
				${__("Voucher")}: <a href="/app/${frappe.scrub(doctype).replace(/_/g, "-")}/${encodeURIComponent(
					result.voucher
				)}">${frappe.utils.escape_html(result.voucher)}</a>`,
			indicator: "green",
		});
		frappe.show_alert({ message: __("Booked {0}", [result.voucher]), indicator: "green" });
		return;
	}
	if (result.status === "Skipped") {
		frappe.msgprint({
			title: __("Nothing booked"),
			message: frappe.utils.escape_html(result.reason || __("Skipped")),
			indicator: "orange",
		});
		return;
	}
	frappe.msgprint({
		title: __("Booking failed"),
		message: frappe.utils.escape_html(result.error || __("Unknown error")),
		indicator: "red",
	});
}
