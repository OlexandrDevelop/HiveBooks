from ua_accounting.accounting.documents import TradeDocument


class UAPaymentInvoice(TradeDocument):
    """Рахунок на оплату покупцю. Does not post and does not touch the stock."""

    doc_code = "PIN"
    doc_title = "Рахунок на оплату покупцю"
    posts = False
