frappe.query_reports["UA Lease Obligations Report"] = {
	filters: [
		{ fieldname: "organization", label: "Організація", fieldtype: "Link", options: "UA Organization", reqd: 1 },
		{ fieldname: "date_to", label: "На дату", fieldtype: "Date", default: frappe.datetime.get_today() },
	],
};
