frappe.ui.form.on("UA Counterparty Contract", {
	setup(frm) {
		frm.set_query("counterparty", () => ({ filters: { is_group: 0 } }));
	},
});
