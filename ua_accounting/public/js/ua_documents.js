// Client side of the accounting documents.
// Shared: VAT totals of the tables, "Результат проведення". The toolbar buttons are in ua_form_toolbar.js.
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
	"UA Tax Invoice",
	"UA Tax Adjustment",
	"UA VAT Allocation",
	"UA Dividend Accrual",
	"UA Tax Payment",
	"UA Loan Drawdown",
	"UA Loan Interest Accrual",
	"UA Loan Repayment",
	"UA Currency Revaluation",
	"UA Opening Balances",
];
// Extra toolbar buttons of a form: [label, icon, handler(frm), show(frm)]
ua_accounting.docs.EXTRA = {};

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

// ---------------------------------------------------------------- "Результат проведення"

// Dialog "Рух документа: Дт/Кт" (design/mockups/form-document.html, ?dialog=dtkt).
// Tabs: Бухгалтерський облік (entries) and Податковий облік (VAT); an empty tab is not shown.
// frm: a form, or {doctype, doc} from a list.
ua_accounting.docs.show_entries = function (frm) {
	frappe.call({
		method: "ua_accounting.accounting.documents.get_posting_result",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => ua_accounting.docs.entries_dialog(frm, r.message || {}),
	});
};

// Fallback movement viewer for accounting documents whose registers are owned by the app
// rather than declared as BeeOne Document Movements metadata.
ua_accounting.docs.show_movements = function (frm) {
	frappe.call({
		method: "ua_accounting.accounting.documents.get_posting_result",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => ua_accounting.docs.entries_dialog(frm, r.message || {}),
	});
};

ua_accounting.docs.entries_dialog = function (frm, result) {
	const esc = frappe.utils.escape_html;
	const ui = ua_accounting.ui;
	const icon = ui.icon;
	const doc = frm.doc;
	const entries = result.entries || [];
	const vat = result.vat || {};
	const vat_rows = []
		.concat((vat.liability || []).map((v) => Object.assign({ kind: __("ПДВ нараховане") }, v)))
		.concat((vat.credit || []).map((v) => Object.assign({ kind: __("ПДВ кредит") }, v)));
	const lines = (list) => (list || []).map((t, i) => (i ? `<span class="ua-sub">${esc(t)}</span>` : esc(t))).join("");
	const qty = (e) => {
		const q = e.quantity_dr || e.quantity_cr;
		return q ? format_number(q, null, 3).replace(/,?0+$/, "") : "";
	};
	const total = entries.reduce((s, e) => s + flt(e.amount), 0);
	// "361 Розрахунки з вітчизняними покупцями" -> chip "361", the name in the tooltip
	const acc = (value, kt) => {
		const text = String(value || "");
		const code = text.split(" ")[0];
		return `<span class="ua-acc${kt ? " ua-acc--kt" : ""}" title="${esc(text)}" data-ua-tip="${esc(text)}">${esc(code)}</span>`;
	};
	const tabs = [];
	if (entries.length) tabs.push(["bu", __("Бухгалтерський облік"), entries.length]);
	if (vat_rows.length) tabs.push(["pu", __("Податковий облік"), vat_rows.length]);

	const bu =
		`<div class="ua-table-wrap ua-dtkt-wrap"><table class="ua-table ua-dtkt-table"><thead><tr>` +
		`<th class="ua-r" style="width:36px">№</th><th style="width:64px">${esc(__("Дт"))}</th><th>${esc(__("Субконто Дт"))}</th>` +
		`<th style="width:64px">${esc(__("Кт"))}</th><th>${esc(__("Субконто Кт"))}</th><th class="ua-r">${esc(__("Кількість"))}</th>` +
		`<th class="ua-r">${esc(__("Сума, ₴"))}</th><th>${esc(__("Зміст"))}</th></tr></thead><tbody>` +
		entries
			.map(
				(e) =>
					`<tr><td class="ua-r ua-subtle">${esc(e.line_no)}</td><td>${acc(e.account_dr)}</td>` +
					`<td>${lines(e.subconto_dr)}</td><td>${acc(e.account_cr, true)}</td>` +
					`<td>${lines(e.subconto_cr)}</td><td class="ua-r ua-num">${esc(qty(e))}</td>` +
					`<td class="ua-r ua-num ua-cell-main">${esc(ui.money(e.amount))}</td><td>${esc(e.content || "")}</td></tr>`
			)
			.join("") +
		`</tbody></table></div><div class="ua-dtkt-sum"><span>${esc(__("Проводок"))}: <b class="ua-num">${entries.length}</b></span>` +
		`<span>${esc(__("Разом"))}: <b class="ua-num">${esc(ui.money(total, { cur: true }))}</b></span></div>`;

	const pu =
		`<div class="ua-table-wrap ua-dtkt-wrap"><table class="ua-table ua-dtkt-table"><thead><tr>` +
		`<th>${esc(__("Запис"))}</th><th>${esc(__("Контрагент"))}</th><th>${esc(__("Ставка"))}</th><th>${esc(__("Подія"))}</th>` +
		`<th class="ua-r">${esc(__("База, ₴"))}</th><th class="ua-r">${esc(__("ПДВ, ₴"))}</th></tr></thead><tbody>` +
		vat_rows
			.map(
				(v) =>
					`<tr><td>${esc(v.kind)}</td><td>${esc(v.counterparty || "")}</td><td>${esc(v.vat_rate || "")}</td><td>${esc(
						v.event || ""
					)}</td><td class="ua-r ua-num">${esc(ui.money(v.base_amount))}</td><td class="ua-r ua-num ua-cell-main">${esc(
						ui.money(v.vat_amount)
					)}</td></tr>`
			)
			.join("") +
		"</tbody></table></div>";

	const date = doc.posting_date ? ` ${__("від")} ${frappe.datetime.str_to_user(doc.posting_date)}` : "";
	const cp_title = doc.counterparty ? frappe.utils.get_link_title("UA Counterparty", doc.counterparty) || "" : "";
	const sub = `${__(frm.doctype)} ${doc.name}${date}${cp_title ? " · " + cp_title : ""}`;
	const body = tabs.length
		? `<div class="ua-tabs ua-dtkt-tabs" role="tablist">${tabs
				.map(
					([key, label, n], i) =>
						`<button class="ua-tab${i ? "" : " is-on"}" role="tab" aria-selected="${!i}" data-tab="${key}">${esc(label)} <span class="ua-count">${n}</span></button>`
				)
				.join("")}</div>` +
		  (entries.length ? `<div data-panel="bu">${bu}</div>` : "") +
		  (vat_rows.length ? `<div data-panel="pu"${entries.length ? " hidden" : ""}>${pu}</div>` : "")
		: ui.empty_html({ title: __("Проводок немає"), text: __("Документ проведено, але він не сформував записів.") });

	const d = ui.dialog({
		title: __("Рух документа: Дт/Кт"),
		wide: true,
		width: 1120,
		html:
			`<div class="ua-dialog-head"><span class="ua-fp-icon">${icon("dtkt")}</span><div>` +
			`<div class="ua-dialog-title">${esc(__("Рух документа: Дт/Кт"))}</div><div class="ua-dialog-sub">${esc(sub)}</div></div>` +
			`<button class="ua-btn ua-btn--ghost ua-btn--icon" data-close aria-label="${esc(__("Закрити"))}">${icon("x")}</button></div>` +
			`<div class="ua-dialog-body">${body}</div>` +
			`<div class="ua-dialog-foot"><span></span><div class="ua-right"><button class="ua-btn" data-act="print">${icon(
				"printer"
			)}${esc(__("Друк"))}</button><button class="ua-btn ua-btn--primary" data-close autofocus>${esc(__("Закрити"))}</button></div></div>`,
	});
	const $box = $(d.box);
	const tabs_el = $box.find(".ua-dtkt-tabs")[0];
	if (tabs_el) setTimeout(() => ui.place_ink(tabs_el), 0);
	$box.on("click", ".ua-tab", function () {
		const key = $(this).attr("data-tab");
		$box.find(".ua-tab").each(function () {
			const on = $(this).attr("data-tab") === key;
			$(this).toggleClass("is-on", on).attr("aria-selected", on);
		});
		$box.find("[data-panel]").each(function () {
			$(this).prop("hidden", $(this).attr("data-panel") !== key);
		});
		ui.place_ink(tabs_el);
	});
	$box.on("click", "[data-act=print]", () => {
		const w = window.open("", "_blank");
		if (!w) return frappe.msgprint(__("Браузер заблокував вікно друку"));
		w.document.write(
			`<html><head><title>${esc(__("Рух документа: Дт/Кт"))}</title><style>${ua_accounting.reports.PRINT_CSS}
			.ua-sub{display:block;color:#555}.ua-acc{font-weight:bold}</style></head><body>` +
				`<h1>${esc(__("Рух документа: Дт/Кт"))}</h1><div>${esc(sub)}</div>` +
				$box.find("[data-panel]:not([hidden]) table").prop("outerHTML").replace(/class="ua-table[^"]*"/, 'class="ua-rpt"') +
				"</body></html>"
		);
		w.document.close();
		w.focus();
		w.print();
	});
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


// ---------------------------------------------------------------- tax invoices, adjustments, VAT return

// windows-1251 bytes of a text (the files of ДПС use this encoding)
ua_accounting.docs.cp1251 = function (text) {
	const special = { 0x401: 0xa8, 0x451: 0xb8, 0x404: 0xaa, 0x454: 0xba, 0x406: 0xb2, 0x456: 0xb3, 0x407: 0xaf, 0x457: 0xbf, 0x490: 0xa5, 0x491: 0xb4, 0xab: 0xab, 0xbb: 0xbb, 0x2116: 0xb9, 0x2013: 0x96, 0x2014: 0x97, 0xa0: 0xa0 };
	const bytes = [];
	for (const ch of text) {
		const c = ch.codePointAt(0);
		if (c < 0x80) bytes.push(c);
		else if (c >= 0x410 && c <= 0x44f) bytes.push(c - 0x410 + 0xc0);
		else bytes.push(special[c] || 0x3f);
	}
	return new Uint8Array(bytes);
};

ua_accounting.docs.export_xml = function (frm) {
	const is_return = frm.doctype === "UA VAT Return";
	frappe.call({
		method: is_return ? "ua_accounting.api.vat_return.export_xml" : "ua_accounting.api.tax_invoice.export_xml",
		args: is_return ? { name: frm.doc.name } : { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => {
			const res = r.message;
			if (!res) return;
			const blob = new Blob([ua_accounting.docs.cp1251(res.xml)], { type: "application/xml" });
			const a = document.createElement("a");
			a.href = URL.createObjectURL(blob);
			a.download = res.filename;
			document.body.appendChild(a);
			a.click();
			a.remove();
			frappe.show_alert({ message: __("Файл {0} вивантажено ({1})", [res.filename, res.schema_version]), indicator: "green" });
		},
	});
};

ua_accounting.docs.export_vat_package = function (frm) {
	frappe.call({
		method: "ua_accounting.api.vat_return.export_package",
		args: { name: frm.doc.name },
		callback: (r) => {
			const res = r.message;
			if (!res) return;
			const binary = atob(res.zip_base64);
			const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
			const blob = new Blob([bytes], { type: "application/zip" });
			const a = document.createElement("a");
			a.href = URL.createObjectURL(blob);
			a.download = res.filename;
			document.body.appendChild(a);
			a.click();
			a.remove();
			frappe.show_alert({ message: __("Пакет {0} вивантажено", [res.filename]), indicator: "green" });
		},
	});
};

ua_accounting.docs.erpn_status_dialog = function (frm) {
	const d = new frappe.ui.Dialog({
		title: __("Статус ЄРПН"),
		fields: [
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Статус ЄРПН"),
				options: ["Не зареєстровано", "Надіслано", "Зареєстровано", "Відхилено"].join("\n"),
				default: frm.doc.erpn_status,
				reqd: 1,
			},
			{ fieldname: "reg_number", fieldtype: "Data", label: __("Номер реєстрації"), default: frm.doc.erpn_reg_number },
			{ fieldname: "reg_date", fieldtype: "Date", label: __("Дата реєстрації"), default: frm.doc.erpn_reg_date },
		],
		primary_action_label: __("Записати"),
		primary_action: (v) => {
			frappe.call({
				method: "ua_accounting.api.tax_invoice.set_erpn_status",
				args: { doctype: frm.doctype, name: frm.doc.name, status: v.status, reg_number: v.reg_number, reg_date: v.reg_date },
				callback: () => {
					d.hide();
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
};

["UA Tax Invoice", "UA Tax Adjustment"].forEach((doctype) => {
	ua_accounting.docs.EXTRA[doctype] = [
		["Вивантажити XML", "arrow-down", (frm) => ua_accounting.docs.export_xml(frm), (frm) => frm.doc.docstatus === 1],
		["Статус ЄРПН", "check-circle", (frm) => ua_accounting.docs.erpn_status_dialog(frm), (frm) => frm.doc.docstatus === 1],
	];
});

ua_accounting.docs.EXTRA["UA VAT Return"] = [
	[
		"Заповнити",
		"refresh",
		(frm) => {
			const run = () =>
				frappe.call({
					method: "ua_accounting.api.vat_return.fill",
					args: { name: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			if (frm.is_dirty()) frm.save().then(run);
			else run();
		},
	],
	["Вивантажити XML", "arrow-down", (frm) => ua_accounting.docs.export_xml(frm)],
	["Вивантажити пакет XML", "archive", (frm) => ua_accounting.docs.export_vat_package(frm)],
];

ua_accounting.docs.EXTRA["UA Regulated Report"] = [
	[
		"Заповнити",
		"refresh",
		(frm) => {
			const run = () =>
				frappe.call({
					method: "ua_accounting.api.fill_report",
					args: { name: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			if (frm.is_dirty()) frm.save().then(run);
			else run();
		},
	],
	[
		"Вивантажити XML",
		"arrow-down",
		(frm) =>
			frappe.call({
				method: "ua_accounting.api.export_report_xml",
				args: { name: frm.doc.name },
				callback: (r) => {
					const res = r.message;
					if (!res) return;
					// the main declaration and each appendix are separate files
					[res].concat(res.appendices || []).forEach((file) => {
						const blob = new Blob([ua_accounting.docs.cp1251(file.content)], { type: "application/xml" });
						const a = document.createElement("a");
						a.href = URL.createObjectURL(blob);
						a.download = file.filename;
						document.body.appendChild(a);
						a.click();
						a.remove();
					});
					frappe.show_alert({ message: __("Файл {0} вивантажено ({1})", [res.filename, res.xsd_version]), indicator: "green" });
					frm.reload_doc();
				},
			}),
	],
];

// ---------------------------------------------------------------- electronic reporting: КЕП, sending to ДПС

ua_accounting.docs.sign_kep = function (frm) {
	const run = () =>
		frappe.call({
			method: "ua_accounting.api.e_reporting.sign",
			args: { doctype: frm.doctype, name: frm.doc.name },
			freeze: true,
			callback: (r) => {
				frappe.show_alert({ message: __("Документ підписано КЕП: {0}", [r.message]), indicator: "green" });
				frm.reload_doc();
			},
		});
	if (frm.is_dirty()) frm.save().then(run);
	else run();
};

ua_accounting.docs.send_to_dps = function (frm) {
	frappe.db
		.get_list("UA Signed Document", {
			filters: { source_doctype: frm.doctype, source_name: frm.doc.name, status: "Підписано" },
			fields: ["name"],
			order_by: "creation desc",
			limit: 1,
		})
		.then((rows) => {
			if (!rows.length) {
				frappe.msgprint(__("Спочатку підпишіть документ КЕП"));
				return;
			}
			frappe.call({
				method: "ua_accounting.api.e_reporting.send",
				args: { name: rows[0].name },
				freeze: true,
				callback: (r) => {
					frappe.show_alert({ message: __("Статус подання: {0}", [r.message.status]), indicator: r.message.status === "Відхилено" ? "red" : "green" });
					frm.reload_doc();
				},
			});
		});
};

// ---------------------------------------------------------------- e-reporting setting: key of the signer (provider ІІТ)

ua_accounting.docs.show_key_check = function (info) {
	const row = (label, value) => `<tr><td class="text-muted" style="padding-right:16px">${frappe.utils.escape_html(label)}</td><td>${frappe.utils.escape_html(value || "—")}</td></tr>`;
	const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
	const rows = [
		row(__("Власник сертифіката"), info.owner),
		row(__("Організація в сертифікаті"), info.organization),
		row(__("Код ЄДРПОУ / РНОКПП"), info.edrpou),
		row(__("ЦСК, що видав сертифікат"), info.issuer),
		row(__("Дійсний з"), date(info.valid_from)),
		row(__("Дійсний по"), date(info.valid_to)),
		row(__("Залишилось днів"), info.days_left === null || info.days_left === undefined ? "" : String(info.days_left)),
		row(__("Алгоритм"), info.algorithm),
	].join("");
	const status = info.ok
		? `<p class="text-success"><b>${__("Ключ придатний до підпису")}</b></p>`
		: `<p class="text-danger"><b>${__("Ключ не придатний")}:</b> ${frappe.utils.escape_html(info.error || "")}</p>`;
	frappe.msgprint({
		title: __("Перевірка ключа КЕП"),
		indicator: info.ok ? "green" : "red",
		message: status + (info.owner ? `<table>${rows}</table>` : ""),
	});
};

ua_accounting.docs.upload_key_dialog = function (frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Завантажити особистий ключ КЕП"),
		fields: [
			{ fieldname: "key_html", fieldtype: "HTML", options: `<div class="form-group"><label class="control-label">${__("Файл ключа (Key-6.dat, .pfx, .p12, .jks)")}</label><input type="file" class="ua-key-file form-control"></div>` },
			{ fieldname: "password", fieldtype: "Password", label: __("Пароль до ключа"), reqd: 1 },
			{ fieldname: "cert_html", fieldtype: "HTML", options: `<div class="form-group"><label class="control-label">${__("Файл сертифіката (.cer), якщо його немає у файлі ключа")}</label><input type="file" class="ua-cert-file form-control"></div>` },
		],
		primary_action_label: __("Завантажити"),
		primary_action(values) {
			const read = (selector) =>
				new Promise((resolve) => {
					const file = dialog.$wrapper.find(selector)[0].files[0];
					if (!file) return resolve(null);
					const reader = new FileReader();
					reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(",")[1] });
					reader.readAsDataURL(file);
				});
			Promise.all([read(".ua-key-file"), read(".ua-cert-file")]).then(([key, cert]) => {
				if (!key) return frappe.msgprint(__("Оберіть файл ключа"));
				frappe.call({
					method: "ua_accounting.api.e_reporting.upload_key",
					args: { organization: frm.doc.organization, filename: key.name, key: key.data, password: values.password, certificate: cert ? cert.data : null },
					freeze: true,
					callback: (r) => {
						dialog.hide();
						ua_accounting.docs.show_key_check(r.message);
						frm.reload_doc();
					},
				});
			});
		},
	});
	dialog.show();
};

ua_accounting.docs.check_key = (frm) =>
	frappe.call({
		method: "ua_accounting.api.e_reporting.check_key",
		args: { organization: frm.doc.organization },
		freeze: true,
		callback: (r) => {
			ua_accounting.docs.show_key_check(r.message);
			frm.reload_doc();
		},
	});

ua_accounting.docs.remove_key = (frm) =>
	frappe.confirm(__("Видалити ключ і пароль із системи?"), () =>
		frappe.call({
			method: "ua_accounting.api.e_reporting.remove_key",
			args: { organization: frm.doc.organization },
			callback: () => frm.reload_doc(),
		})
	);

ua_accounting.docs.is_iit_form = (frm) => !frm.is_new() && frm.doc.provider === "ІІТ";
ua_accounting.docs.EXTRA["UA E-Reporting Setting"] = [
	["Завантажити ключ", "arrow-up", (frm) => ua_accounting.docs.upload_key_dialog(frm), ua_accounting.docs.is_iit_form],
	["Перевірити ключ", "check-circle", (frm) => ua_accounting.docs.check_key(frm), (frm) => ua_accounting.docs.is_iit_form(frm) && !!frm.doc.key_file_name],
	["Видалити ключ", "trash", (frm) => ua_accounting.docs.remove_key(frm), (frm) => ua_accounting.docs.is_iit_form(frm) && !!frm.doc.key_file_name],
];

frappe.ui.form.on("UA E-Reporting Setting", {
	refresh(frm) {
		if (!ua_accounting.docs.is_iit_form(frm)) return;
		frappe.call({
			method: "ua_accounting.api.e_reporting.eusign_status",
			callback: (r) => {
				if (r.message && !r.message.available)
					frm.dashboard.set_headline_alert(__("Бібліотеку ІІТ EUSignCP не встановлено на сервері: підпис КЕП недоступний. Зверніться до адміністратора."), "red");
			},
		});
	},
});

[
	["UA Tax Invoice", (frm) => frm.doc.docstatus === 1 && frm.doc.direction === "Видана"],
	["UA Tax Adjustment", (frm) => frm.doc.docstatus === 1],
	["UA VAT Return", () => true],
	["UA Regulated Report", () => true],
	["UA Statistical Report", () => true],
].forEach(([doctype, when]) => {
	ua_accounting.docs.EXTRA[doctype] = (ua_accounting.docs.EXTRA[doctype] || []).concat([
		["Підписати КЕП", "lock", (frm) => ua_accounting.docs.sign_kep(frm), when],
		["Надіслати до ДПС", "upload", (frm) => ua_accounting.docs.send_to_dps(frm), when],
	]);
});

ua_accounting.docs.EXTRA["UA Statistical Report"].unshift(
	[
		"Заповнити",
		"refresh",
		(frm) => {
			const run = () =>
				frappe.call({
					method: "ua_accounting.api.e_reporting.statistics_fill",
					args: { name: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			if (frm.is_dirty()) frm.save().then(run);
			else run();
		},
	],
	[
		"Вивантажити XML",
		"arrow-down",
		(frm) =>
			frappe.call({
				method: "ua_accounting.api.e_reporting.statistics_export_xml",
				args: { name: frm.doc.name },
				callback: (r) => {
					const res = r.message;
					if (!res) return;
					const blob = new Blob([ua_accounting.docs.cp1251(res.xml)], { type: "application/xml" });
					const a = document.createElement("a");
					a.href = URL.createObjectURL(blob);
					a.download = res.filename;
					document.body.appendChild(a);
					a.click();
					a.remove();
					frappe.show_alert({ message: __("Файл {0} вивантажено ({1})", [res.filename, res.schema_version]), indicator: "green" });
					frm.reload_doc();
				},
			}),
	],
);

frappe.ui.form.on("UA Tax Invoice", {
	setup(frm) {
		ua_accounting.docs.contract_query(frm);
	},
	onload(frm) {
		ua_accounting.docs.default_organization(frm);
	},
	counterparty(frm) {
		frm.set_value("contract", "");
	},
});

frappe.ui.form.on("UA Tax Invoice Line", {
	quantity: (frm, cdt, cdn) => ua_accounting.docs.tax_line(frm, cdt, cdn),
	price: (frm, cdt, cdn) => ua_accounting.docs.tax_line(frm, cdt, cdn),
	vat_rate: (frm, cdt, cdn) => ua_accounting.docs.tax_line(frm, cdt, cdn),
	base_amount: (frm) => ua_accounting.docs.tax_totals(frm),
	vat_amount: (frm) => ua_accounting.docs.tax_totals(frm),
	lines_remove: (frm) => ua_accounting.docs.tax_totals(frm),
});

ua_accounting.docs.tax_line = function (frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	ua_accounting.docs.get_rates().then((rates) => {
		const rate = rates[row.vat_rate];
		const percent = rate && rate.is_taxable ? flt(rate.rate) : 0;
		row.base_amount = flt(flt(row.quantity) * flt(row.price), 2);
		row.vat_amount = flt((row.base_amount * percent) / 100, 2);
		frm.refresh_field("lines");
		ua_accounting.docs.tax_totals(frm);
	});
};

ua_accounting.docs.tax_totals = function (frm) {
	let base = 0;
	let vat = 0;
	(frm.doc.lines || []).forEach((r) => {
		base += flt(r.base_amount);
		vat += flt(r.vat_amount);
	});
	frm.set_value("total_base", flt(base, 2));
	frm.set_value("total_vat", flt(vat, 2));
	frm.set_value("total_amount", flt(base + vat, 2));
};

frappe.ui.form.on("UA Tax Adjustment Line", {
	quantity_after: (frm, cdt, cdn) => ua_accounting.docs.adjust_line(frm, cdt, cdn),
	price_after: (frm, cdt, cdn) => ua_accounting.docs.adjust_line(frm, cdt, cdn),
});

ua_accounting.docs.adjust_line = function (frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	ua_accounting.docs.get_rates().then((rates) => {
		const rate = rates[row.vat_rate];
		const percent = rate && rate.is_taxable ? flt(rate.rate) : 0;
		row.base_after = flt(flt(row.quantity_after) * flt(row.price_after), 2);
		row.vat_after = flt((row.base_after * percent) / 100, 2);
		row.delta_base = flt(row.base_after - flt(row.base_before), 2);
		row.delta_vat = flt(row.vat_after - flt(row.vat_before), 2);
		frm.refresh_field("lines");
		frm.set_value(
			"total_delta_base",
			flt((frm.doc.lines || []).reduce((s, r) => s + flt(r.delta_base), 0), 2)
		);
		frm.set_value(
			"total_delta_vat",
			flt((frm.doc.lines || []).reduce((s, r) => s + flt(r.delta_vat), 0), 2)
		);
	});
};

// ---------------------------------------------------------------- opening balances assistant
// The section of a row limits its accounts; the account sets the subconto types of the row.

ua_accounting.docs.opening_sections = function () {
	if (!ua_accounting.docs._opening) {
		ua_accounting.docs._opening = frappe
			.call({ method: "ua_accounting.accounting.opening.get_sections", type: "GET" })
			.then((r) => r.message || []);
	}
	return ua_accounting.docs._opening;
};

frappe.ui.form.on("UA Opening Balances", {
	setup(frm) {
		frm.set_query("account", "rows", (_doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const codes = ((ua_accounting.docs._opening_codes || {})[row.section] || []);
			return { filters: { name: ["in", codes.length ? codes : [""]] } };
		});
		ua_accounting.docs.opening_sections().then((sections) => {
			ua_accounting.docs._opening_codes = {};
			sections.forEach((s) => (ua_accounting.docs._opening_codes[s.section] = s.accounts.map((a) => a.account)));
		});
	},
});

frappe.ui.form.on("UA Opening Balance Line", {
	section(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "account", "");
	},
	account(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		ua_accounting.docs.opening_sections().then((sections) => {
			const section = sections.find((s) => s.section === row.section);
			const acc = section && section.accounts.find((a) => a.account === row.account);
			[1, 2, 3].forEach((i) => {
				frappe.model.set_value(cdt, cdn, `subconto${i}`, "");
				frappe.model.set_value(cdt, cdn, `subconto${i}_type`, (acc && acc.subconto_doctypes[i - 1]) || "");
			});
		});
	},
});
