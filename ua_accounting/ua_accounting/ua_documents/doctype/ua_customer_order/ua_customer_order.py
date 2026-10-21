import frappe

from ua_accounting.accounting.documents import TradeDocument, new_from_basis


class UACustomerOrder(TradeDocument):
    """Замовлення покупця. No accounting entries. It is the basis for a sale."""

    doc_code = "CO"
    doc_title = "Замовлення покупця"
    posts = False

    def validate(self):
        super().validate()
        if not self.status:
            self.status = "Відкрито"


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
    order = frappe.get_doc("UA Customer Order", source_name)
    order.check_permission("read")
    return new_from_basis(order, "UA Sales Invoice", "customer_order")
