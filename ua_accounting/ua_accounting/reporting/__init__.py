"""Accounting reports (OSV, OSV by account, account card).

Layers:
    filters.py   parse and check the filters (one format for all reports)
    chart.py     chart of accounts in memory (hierarchy, subconto per account)
    query.py     the shared query layer: totals table + entries of partial months
    titles.py    titles of linked values (subconto values, organizations)
    model.py     the table model sent to the browser, printed and exported
    balance.py   rows of the "opening / turnover / closing" reports
    osv.py, osv_account.py, account_card.py   the reports
    export.py    Excel export of the table model
    api.py       whitelisted methods

A new report is a function build(raw_filters) -> table model. Add it to
api.REPORTS. A new filter is added in filters.py (parse) and query.py (SQL).
"""
