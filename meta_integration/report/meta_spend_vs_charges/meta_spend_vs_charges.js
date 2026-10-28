frappe.query_reports["Meta Spend vs Charges"] = {
	filters: [
		{
			fieldname: "from_date",
			fieldtype: "Date",
			label: __("From Date"),
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -6),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			fieldtype: "Date",
			label: __("To Date"),
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			fieldtype: "Link",
			label: __("Company"),
			options: "Company",
		},
		{
			fieldname: "meta_account",
			fieldtype: "Link",
			label: __("Meta Account"),
			options: "Meta Account",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname !== "status") {
			return default_formatter(value, row, column, data);
		}
		const colour =
			{
				OK: "green",
				"Spend not charged": "orange",
				"Charged > spend": "red",
				"Charge without spend": "red",
				"Draft entries": "blue",
			}[value] || "gray";
		return `<span class="indicator-pill ${colour}">${frappe.utils.escape_html(
			value || ""
		)}</span>`;
	},
};
