frappe.query_reports["UA Appendix 4DF"] = {
	filters: [{fieldname:'organization',label:'Організація',fieldtype:'Link',options:'UA Organization',reqd:1},{fieldname:'year',label:'Рік',fieldtype:'Int',reqd:1,default:new Date().getFullYear()},{fieldname:'quarter',label:'Квартал',fieldtype:'Select',options:'1\n2\n3\n4',reqd:1,default:'1'}],
	onload(report) {
		report.page.add_inner_button(__("Експорт XML"), () => {
			const f = report.get_values();
			frappe.call({
				method: "ua_accounting.reporting.payroll.export_4df_xml",
				type: "GET",
				args: {organization: f.organization, year: f.year, quarter: f.quarter},
				callback: (r) => {
					const blob = new Blob([r.message], {type: "application/xml;charset=utf-8"});
					const a = document.createElement("a");
					a.href = URL.createObjectURL(blob);
					a.download = `4DF_${f.year}_${f.quarter}.xml`;
					a.click();
				},
			});
		});
	},
};
