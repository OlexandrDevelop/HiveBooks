import frappe

from ua_accounting.accounting.documents import TradeDocument, new_from_basis


class UASupplierOrder(TradeDocument):
    """Замовлення постачальнику. No accounting entries. It is the basis for a receipt."""

    doc_code = "SO"
    doc_title = "Замовлення постачальнику"
    posts = False

    def validate(self):
        super().validate()
        if not self.status:
            self.status = "Відкрито"


@frappe.whitelist()
def make_purchase_receipt(source_name, target_doc=None):
    order = frappe.get_doc("UA Supplier Order", source_name)
    order.check_permission("read")
    return new_from_basis(order, "UA Purchase Receipt", "supplier_order")
