from ua_accounting.accounting.documents import TradeDocument


class UASupplierInvoice(TradeDocument):
    """Рахунок постачальника. Does not post: the debt appears with the receipt."""

    doc_code = "SIN"
    doc_title = "Рахунок постачальника"
    posts = False
