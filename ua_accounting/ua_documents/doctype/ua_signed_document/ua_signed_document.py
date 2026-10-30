import frappe
from frappe import _
from frappe.model.document import Document


class UASignedDocument(Document):
    """Архів поданих документів. Created and changed only by the system (e_reporting); never deleted:
    tax documents are kept 1095 days (ПКУ ст. 44.3)."""

    def validate(self):
        if self.flags.get("ua_system"):
            return
        if self.is_new():
            frappe.throw(_("Підписаний документ створюється лише підписанням"))
        old = self.get_doc_before_save()
        for field in self.meta.fields:
            if field.fieldtype in ("Table", "Section Break", "Column Break"):
                continue
            if str(old.get(field.fieldname) or "") != str(self.get(field.fieldname) or ""):
                frappe.throw(_("Підписаний документ не змінюють: поле «{0}»").format(_(field.label)))
        keys = ("kind", "received_at", "result", "text", "erpn_reg_number", "erpn_reg_date", "xml", "signed_by", "chain_ok", "signature")
        rows = lambda doc: [tuple(str(r.get(k) or "") for k in keys) for r in doc.receipts]
        if rows(old) != rows(self):
            frappe.throw(_("Квитанції не змінюють"))

    def on_trash(self):
        frappe.throw(_("Архів поданих документів не видаляють: документи зберігають 1095 днів"))
