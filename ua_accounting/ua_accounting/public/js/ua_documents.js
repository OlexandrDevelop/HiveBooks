// Client side of the accounting documents.
// Shared: VAT totals of the tables, "Результат проведення", "Створити на підставі".
frappe.provide("ua_accounting.docs");

ua_accounting.docs.VAT_NONE = "Без ПДВ";
ua_accounting.docs.VAT_INCLUDED = "ПДВ у сумі";
ua_accounting.docs.TRADE = ["UA Customer Order", "UA Sales Invoice", "UA Supplier Order", "UA Purchase Receipt"];
ua_accounting.docs.CASH = ["UA Cash Receipt", "UA Cash Payment"];
ua_accounting.docs.POSTING = [
	"UA Sales Invoice",
	"UA Purchase Receipt",
	"UA Cash Receipt",
	"UA Cash Payment",
	"UA Journal Operation",
];
const BASIS = {
	"UA Customer Order": [["Реалізація товарів та послуг", "ua_accounting.ua_documents.doctype.ua_customer_order.ua_customer_order.make_sales_invoice"]],
	"UA Supplier Order": [["Надходження товарів та послуг", "ua_accounting.ua_documents.doctype.ua_supplier_order.ua_supplier_order.make_purchase_receipt"]],
	"UA Sales Invoice": [["Надходження коштів", "ua_accounting.ua_documents.doctype.ua_sales_invoice.ua_sales_invoice.make_cash_receipt"]],
	"UA Purchase Receipt": [["Витрата коштів", "ua_accounting.ua_documents.doctype.ua_purchase_receipt.ua_purchase_receipt.make_cash_payment"]],
};

// ---------------------------------------------------------------- VAT rates and totals

ua_accounting.docs.get_rates = function () {
	if (ua_accounting.docs._rates) {
		return Promise.resolve(ua_accounting.docs._rates);
	}
	return frappe.db
		.get_list("UA VAT Rate", { fields: ["name", "rate", "is_taxable"], limit: 0 })
		.then((rows) => {
			ua_accounting.docs._rates = {};
			rows.forEach((r) => (ua_accounting.docs._rates[r.name] = r));
			return ua_accounting.docs._rates;
		});
};

// Same formulas as calc_line() in accounting/documents.py.
ua_accounting.docs.calc_line = function (row, percent, mode) {
	const amount = flt(flt(row.quantity) * flt(row.price), 2);
	if (mode === ua_accounting.docs.VAT_NONE || !percent) {
		return [amount, 0, amount];
	}
	if (mode === ua_accounting.docs.VAT_INCLUDED) {
		return [amount, flt((amount * percent) / (100 + percent), 2), amount];
	}
	const vat = flt((amount * percent) / 100, 2);
	return [amount, vat, flt(amount + vat, 2)];
};

ua_accounting.docs.recalc = function (frm) {
	return ua_accounting.docs.get_rates().then((rates) => {
		let net = 0;
		let vat = 0;
		let total = 0;
		["goods", "services"].forEach((table) => {
			(frm.doc[table] || []).forEach((row) => {
				const rate = rates[row.vat_rate];
				const percent = rate && rate.is_taxable ? flt(rate.rate) : 0;
				const [amount, vat_amount, row_total] = ua_accounting.docs.calc_line(row, percent, frm.doc.vat_mode);
				row.amount = amount;
				row.vat_amount = vat_amount;
				row.total = row_total;
				net += row_total - vat_amount;
				vat += vat_amount;
				total += row_total;
			});
			frm.refresh_field(table);
		});
		frm.set_value("total_net", flt(net, 2));
		frm.set_value("vat_total", flt(vat, 2));
		frm.set_value("total_amount", flt(total, 2));
		frm.set_value("base_total", flt(total * (flt(frm.doc.exchange_rate) || 1), 2));
	});
};

ua_accounting.docs.set_rate = function (frm) {
	if (!frm.doc.currency || !frm.doc.posting_date) {
		return;
	}
	frappe.call({
		method: "ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency.get_rate",
		args: { currency: frm.doc.currency, date: frm.doc.posting_date },
		callback: (r) => {
			frm.set_value("exchange_rate", r.message || 0);
			if (frm.doc.goods !== undefined) {
				ua_accounting.docs.recalc(frm);
			}
		},
	});
};

// ---------------------------------------------------------------- common form parts

ua_accounting.docs.default_organization = function (frm) {
	if (!frm.is_new() || frm.doc.organization) {
		return;
	}
	frappe.db.get_list("UA Organization", { fields: ["name"], limit: 2 }).then((rows) => {
		if (rows.length === 1) {
			frm.set_value("organization", rows[0].name);
		}
	});
};

ua_accounting.docs.contract_query = function (frm) {
	frm.set_query("contract", () => ({
		filters: { counterparty: frm.doc.counterparty || "", organization: frm.doc.organization || "" },
	}));
};

ua_accounting.docs.on_contract = function (frm) {
	if (!frm.doc.contract) {
		return;
	}
	frappe.db.get_value("UA Counterparty Contract", frm.doc.contract, "currency").then((r) => {
		const currency = r.message && r.message.currency;
		if (currency && currency !== frm.doc.currency) {
			frm.set_value("currency", currency);
		}
	});
};

ua_accounting.docs.add_basis_buttons = function (frm) {
	if (frm.doc.docstatus !== 1) {
		return;
	}
	(BASIS[frm.doctype] || []).forEach(([label, method]) => {
		frm.add_custom_button(
			__(label),
			() => frappe.model.open_mapped_doc({ method: method, frm: frm }),
			__("Створити на підставі")
		);
	});
};

ua_accounting.docs.add_entries_button = function (frm) {
	if (frm.doc.docstatus === 0 || frm.is_new()) {
		return;
	}
	if (!ua_accounting.docs.POSTING.includes(frm.doctype)) {
		return;
	}
	frm.add_custom_button(__("Результат проведення"), () => ua_accounting.docs.show_entries(frm));
};

// ---------------------------------------------------------------- "Результат проведення"

ua_accounting.docs.show_entries = function (frm) {
	frappe.call({
		method: "ua_accounting.accounting.documents.get_posting_result",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => {
			const d = new frappe.ui.Dialog({
				title: __("Результат проведення") + ": " + frm.doc.name,
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "body" }],
			});
			d.fields_dict.body.$wrapper.html(ua_accounting.docs.render_result(r.message || {}));
			d.show();
		},
	});
};

ua_accounting.docs.render_result = function (result) {
	const esc = frappe.utils.escape_html;
	const money = (v) => format_currency(v, frappe.defaults.get_default("currency") || "UAH");
	const subs = (list) => (list || []).map((s) => `<div class="text-muted">${esc(s)}</div>`).join("");
	const entries = result.entries || [];
	let html = "";
	if (!entries.length) {
		html += `<p class="text-muted">${__("Проводок немає")}</p>`;
	} else {
		html += `<table class="table table-bordered table-sm ua-entries"><thead><tr>
			<th>№</th><th>${__("Дебет")}</th><th>${__("Кредит")}</th><th class="text-right">${__("Сума")}</th><th>${__("Зміст")}</th>
		</tr></thead><tbody>`;
		entries.forEach((e) => {
			const qty = [];
			if (e.quantity_dr) qty.push(`${__("К-сть Дт")}: ${e.quantity_dr}`);
			if (e.quantity_cr) qty.push(`${__("К-сть Кт")}: ${e.quantity_cr}`);
			if (e.currency_dr && e.currency_amount_dr) qty.push(`${esc(e.currency_dr)} ${e.currency_amount_dr}`);
			if (e.currency_cr && e.currency_amount_cr) qty.push(`${esc(e.currency_cr)} ${e.currency_amount_cr}`);
			html += `<tr>
				<td>${e.line_no}</td>
				<td><b>${esc(e.account_dr)}</b>${subs(e.subconto_dr)}</td>
				<td><b>${esc(e.account_cr)}</b>${subs(e.subconto_cr)}</td>
				<td class="text-right">${money(e.amount)}<div class="text-muted">${qty.join("<br>")}</div></td>
				<td>${esc(e.content)}</td>
			</tr>`;
		});
		html += "</tbody></table>";
	}
	const vat = result.vat || {};
	[
		["liability", __("ПДВ нараховане")],
		["credit", __("ПДВ кредит")],
	].forEach(([key, title]) => {
		const rows = vat[key] || [];
		if (!rows.length) return;
		html += `<h6>${title}</h6><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Контрагент")}</th><th>${__("Ставка")}</th><th>${__("Подія")}</th>
			<th class="text-right">${__("База")}</th><th class="text-right">${__("ПДВ")}</th>
		</tr></thead><tbody>`;
		rows.forEach((v) => {
			html += `<tr><td>${esc(v.counterparty)}</td><td>${esc(v.vat_rate)}</td><td>${esc(v.event)}</td>
				<td class="text-right">${money(v.base_amount)}</td><td class="text-right">${money(v.vat_amount)}</td></tr>`;
		});
		html += "</tbody></table>";
	});
	return html;
};

// ---------------------------------------------------------------- trade documents

ua_accounting.docs.TRADE.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			ua_accounting.docs.contract_query(frm);
			frm.set_query("item", "goods", () => ({
				filters: { is_group: 0, item_type: ["in", ["Товар", "Матеріал", "Продукція"]] },
			}));
			frm.set_query("item", "services", () => ({ filters: { is_group: 0, item_type: "Послуга" } }));
			frm.set_query("account", "goods", ua_accounting.ui.leaf_account_query);
			frm.set_query("account", "services", ua_accounting.ui.leaf_account_query);
		},
		onload(frm) {
			ua_accounting.docs.default_organization(frm);
		},
		refresh(frm) {
			ua_accounting.docs.add_entries_button(frm);
			ua_accounting.docs.add_basis_buttons(frm);
		},
		counterparty(frm) {
			frm.set_value("contract", "");
		},
		contract(frm) {
			ua_accounting.docs.on_contract(frm);
		},
		currency(frm) {
			ua_accounting.docs.set_rate(frm);
		},
		posting_date(frm) {
			ua_accounting.docs.set_rate(frm);
		},
		exchange_rate(frm) {
			ua_accounting.docs.recalc(frm);
		},
		vat_mode(frm) {
			ua_accounting.docs.recalc(frm);
		},
		goods_remove: (frm) => ua_accounting.docs.recalc(frm),
		services_remove: (frm) => ua_accounting.docs.recalc(frm),
		warehouse(frm) {
			(frm.doc.goods || []).forEach((row) => {
				if (!row.warehouse) row.warehouse = frm.doc.warehouse;
			});
			frm.refresh_field("goods");
		},
	});
});

["UA Goods Line", "UA Service Line"].forEach((child) => {
	frappe.ui.form.on(child, {
		item(frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			if (!row.item) return;
			frappe.db.get_value("UA Item", row.item, ["item_name", "uom", "vat_rate"]).then((r) => {
				const v = r.message || {};
				row.item_name = v.item_name;
				row.uom = v.uom;
				row.vat_rate = v.vat_rate;
				if (cdt === "UA Goods Line" && !row.warehouse) row.warehouse = frm.doc.warehouse;
				ua_accounting.docs.recalc(frm);
			});
		},
		quantity: (frm) => ua_accounting.docs.recalc(frm),
		price: (frm) => ua_accounting.docs.recalc(frm),
		vat_rate: (frm) => ua_accounting.docs.recalc(frm),
	});
});

// ---------------------------------------------------------------- cash documents

ua_accounting.docs.CASH.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			ua_accounting.docs.contract_query(frm);
			frm.set_query("bank_account", () => ({
				filters: { organization: frm.doc.organization || "" },
			}));
			frm.set_query("cash_desk", () => ({ filters: { organization: frm.doc.organization || "" } }));
			frm.set_query("other_account", ua_accounting.ui.leaf_account_query);
		},
		onload(frm) {
			ua_accounting.docs.default_organization(frm);
		},
		refresh(frm) {
			ua_accounting.docs.add_entries_button(frm);
		},
		counterparty(frm) {
			frm.set_value("contract", "");
		},
		contract(frm) {
			ua_accounting.docs.on_contract(frm);
		},
		currency(frm) {
			ua_accounting.docs.set_rate(frm);
		},
		posting_date(frm) {
			ua_accounting.docs.set_rate(frm);
		},
		vat_rate: (frm) => ua_accounting.docs.cash_vat(frm),
		amount: (frm) => ua_accounting.docs.cash_vat(frm),
		settlement_type: (frm) => ua_accounting.docs.cash_vat(frm),
	});
});

ua_accounting.docs.cash_vat = function (frm) {
	if (frm.doc.settlement_type !== "Передоплата (аванс)" || !frm.doc.vat_rate) {
		frm.set_value("vat_amount", 0);
		return;
	}
	ua_accounting.docs.get_rates().then((rates) => {
		const rate = rates[frm.doc.vat_rate];
		const percent = rate && rate.is_taxable ? flt(rate.rate) : 0;
		frm.set_value("vat_amount", flt((flt(frm.doc.amount) * percent) / (100 + percent), 2));
	});
};

// ---------------------------------------------------------------- manual operation

frappe.ui.form.on("UA Journal Operation", {
	setup(frm) {
		frm.set_query("account_dr", "entries", ua_accounting.ui.leaf_account_query);
		frm.set_query("account_cr", "entries", ua_accounting.ui.leaf_account_query);
	},
	onload(frm) {
		ua_accounting.docs.default_organization(frm);
	},
	refresh(frm) {
		ua_accounting.docs.add_entries_button(frm);
	},
});

ua_accounting.docs.fill_subconto_types = function (cdt, cdn, side) {
	const row = locals[cdt][cdn];
	const account = row["account_" + side];
	const clear = () => [1, 2, 3].forEach((i) => frappe.model.set_value(cdt, cdn, `subconto_${side}${i}_type`, null));
	if (!account) {
		clear();
		return;
	}
	frappe.call({
		method: "ua_accounting.accounting.documents.get_account_subconto",
		args: { account: account },
		callback: (r) => {
			const types = r.message || [];
			[1, 2, 3].forEach((i) => {
				const t = types[i - 1];
				frappe.model.set_value(cdt, cdn, `subconto_${side}${i}`, null);
				frappe.model.set_value(cdt, cdn, `subconto_${side}${i}_type`, t && !t.is_dynamic ? t.reference_doctype : null);
			});
		},
	});
};

frappe.ui.form.on("UA Operation Entry", {
	account_dr: (frm, cdt, cdn) => ua_accounting.docs.fill_subconto_types(cdt, cdn, "dr"),
	account_cr: (frm, cdt, cdn) => ua_accounting.docs.fill_subconto_types(cdt, cdn, "cr"),
});
