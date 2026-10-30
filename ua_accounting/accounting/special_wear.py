"""Special tools and workwear (МШП, account 22) in use.

Documents: issue to use, monthly write-off, return to the warehouse, write-off from use.
The items in use are kept in lots. A lot is one row of a submitted issue. The state of a lot
is built from the submitted documents (no extra register):
  quantity left = issued - quantity of the allocations of returns and write-offs
  cost left     = cost of the row - cost of the allocations
  expensed left = expensed part of the row + monthly parts - expensed part of the allocations
Returns and write-offs take lots of the person (or department) in the order of issue.
Items in use are also kept off the balance on МЦ.04 (item, person or department).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.stock import take_cost
from ua_accounting.accounting.utils import title_of

OFF_BALANCE_ACCOUNT = "МЦ.04"
STOCK = "22"
IN_USE_WAREHOUSE = "Спецодяг в експлуатації"

AT_ONCE = "100% при передачі"
HALF = "50% + 50%"
EVEN = "Рівномірно за строк корисного використання"

TO_PERSON = "Працівник"
TO_DEPARTMENT = "Підрозділ"

# 91 is a group: the posting goes to its subaccount of variable overhead
# 91 is a group: the ledger refuses it like in every other document, 911-913 are posted
EXPENSE_ACCOUNTS = ("23", "91", "911", "912", "913", "92", "93")

ISSUE = "UA Special Wear Issue"
LINE = "tabUA Special Wear Line"
LINE_DT = "UA Special Wear Line"
ALLOC = "tabUA Special Wear Allocation"
MONTHLY = "tabUA Special Wear Monthly Line"


# ---------------------------------------------------------------- lots


def _child_rows(table, parent, columns, lines, date, exclude=None):
    """Sums of a child table of submitted documents of one type, by the issue row, up to `date`."""
    sql = f"""select {columns} from `{table}` a join `tab{parent}` p on p.name = a.parent
        where p.docstatus = 1 and p.posting_date <= %s and a.issue_line in %s"""
    values = [getdate(date), lines]
    if exclude and exclude[0] == parent:
        sql += " and p.name != %s"
        values.append(exclude[1])
    return frappe.db.sql(sql + " group by a.issue_line", values, as_dict=True)


USERS = (
    (ALLOC, "UA Special Wear Return"),
    (ALLOC, "UA Special Wear Writeoff"),
    (MONTHLY, "UA Special Wear Monthly Writeoff"),
)


def later_usage(lines, date, same_day=False, exclude=None):
    """Issue rows used by a submitted return, write-off or monthly write-off that is later than `date`
    (with `same_day`: also on that date)."""
    found = set()
    for table, parent in USERS:
        # on cancel (`same_day`) any other document of the same date counts: the submit order is not the creation order
        sql = f"""select distinct a.issue_line from `{table}` a join `tab{parent}` p on p.name = a.parent
            where p.docstatus = 1 and a.issue_line in %s and p.posting_date {'>=' if same_day else '>'} %s"""
        values = [lines, getdate(date)]
        if exclude and exclude[0] == parent:
            sql += " and p.name != %s"
            values.append(exclude[1])
        found.update(frappe.db.sql_list(sql, values))
    return found


def check_no_later(doc):
    """A document cannot be cancelled while later documents use the same issue rows."""
    lines = {r.issue_line for r in doc.get("allocations") or doc.get("lines") or [] if r.issue_line}
    if lines and later_usage(list(lines), doc.posting_date, True, (doc.doctype, doc.name)):
        frappe.throw(_("Документ не можна скасувати: за цими передачами вже є пізніші документи. Спочатку скасуйте їх"))


def lots(organization, date, holder=None, item=None, exclude=None):
    """Lots in use on the end of `date`, oldest first.

    `holder` is ("person" | "department", name). `exclude` is (doctype, name) of the document that is built now.
    """
    sql = f"""select l.name as line, l.parent as issue, l.item, l.quantity, l.cost, l.expensed,
        p.posting_date, p.writeoff_method, p.useful_life_months, p.expense_account, p.expense_item,
        p.warehouse, p.person, p.department
        from `{LINE}` l join `tabUA Special Wear Issue` p on p.name = l.parent
        where p.docstatus = 1 and p.organization = %s and p.posting_date <= %s"""
    values = [organization, getdate(date)]
    if holder:
        sql += f" and p.`{holder[0]}` = %s"
        values.append(holder[1])
    if item:
        sql += " and l.item = %s"
        values.append(item)
    sql += " order by p.posting_date, p.creation, l.idx"
    rows = frappe.db.sql(sql, values, as_dict=True)
    if not rows:
        return []
    names = [r.line for r in rows]
    taken, parts, months = {}, {}, {}
    for parent in ("UA Special Wear Return", "UA Special Wear Writeoff"):
        for a in _child_rows(ALLOC, parent, "a.issue_line, sum(a.quantity) as quantity, sum(a.cost) as cost, "
                             "sum(a.expensed) as expensed", names, date, exclude):
            t = taken.setdefault(a.issue_line, frappe._dict(quantity=0, cost=0, expensed=0))
            for key in ("quantity", "cost", "expensed"):
                t[key] += flt(a[key])
    for m in _child_rows(MONTHLY, "UA Special Wear Monthly Writeoff", "a.issue_line, sum(a.amount) as amount, "
                         "max(a.months_done) as months_done", names, date, exclude):
        parts[m.issue_line] = flt(m.amount, 2)
        months[m.issue_line] = int(m.months_done or 0)
    later = later_usage(names, date, False, exclude)
    out = []
    for r in rows:
        r.later = r.line in later
        t = taken.get(r.line)
        r.qty_left = flt(flt(r.quantity) - flt(t.quantity if t else 0), 3)
        r.cost_left = flt(flt(r.cost) - flt(t.cost if t else 0), 2)
        r.expensed_left = flt(flt(r.expensed) + parts.get(r.line, 0) - flt(t.expensed if t else 0), 2)
        r.months_done = months.get(r.line, 0)
        if r.qty_left > 0:
            out.append(r)
    return out


def take_from_lots(organization, date, holder, item, quantity, exclude, idx, pending):
    """Allocations (list of dict) for `quantity` of `item` of the holder. Throws when there is not enough."""
    left = flt(quantity, 3)
    result = []
    for lot in lots(organization, date, holder, item, exclude):
        # rows of this document that took the lot before
        used = pending.setdefault(lot.line, frappe._dict(quantity=0, cost=0, expensed=0))
        lot.qty_left = flt(lot.qty_left - used.quantity, 3)
        lot.cost_left = flt(lot.cost_left - used.cost, 2)
        lot.expensed_left = flt(lot.expensed_left - used.expensed, 2)
        if left <= 0 or lot.qty_left <= 0:
            continue
        if lot.later:
            frappe.throw(
                _("Рядок {0}: за передачею {1} вже є пізніші документи. Проведіть документ пізнішою датою").format(
                    idx, lot.issue
                )
            )
        qty = min(left, lot.qty_left)
        if qty == lot.qty_left:
            cost, expensed = lot.cost_left, lot.expensed_left
        else:
            cost = flt(lot.cost_left * qty / lot.qty_left, 2)
            expensed = flt(lot.expensed_left * qty / lot.qty_left, 2)
        used.quantity += qty
        used.cost += cost
        used.expensed += expensed
        result.append(
            {
                "issue": lot.issue, "issue_line": lot.line, "item": item, "warehouse": lot.warehouse,
                "quantity": qty, "cost": cost, "expensed": expensed,
                "expense_account": lot.expense_account, "expense_item": lot.expense_item,
                "method": lot.writeoff_method,
            }
        )
        left = flt(left - qty, 3)
    if left > 0:
        frappe.throw(
            _("Рядок {0}: в експлуатації немає стільки {1}, не вистачає {2}").format(
                idx, title_of("UA Item", item), frappe.format(left, {"fieldtype": "Float", "precision": 3})
            )
        )
    return result


def in_use_warehouse(organization):
    """Warehouse that holds the cost of the items in use that are written off evenly (like 1C: they stay on 22)."""
    name = frappe.db.get_value("UA Warehouse", {"organization": organization, "warehouse_name": IN_USE_WAREHOUSE})
    if name:
        return name
    doc = frappe.get_doc({"doctype": "UA Warehouse", "warehouse_name": IN_USE_WAREHOUSE, "organization": organization})
    doc.insert(ignore_permissions=True)
    return doc.name


def expense_sub(expense_item, department=None):
    return {"ExpenseItem": expense_item, "Department": department}


# ---------------------------------------------------------------- base


class SpecialWearDocument(AccountingDocument):
    """Common checks: holder (person or department), rows with item and quantity."""

    rows_table = "items"
    holder_required = True

    def validate(self):
        super().validate()
        self.check_rows()

    def check_rows(self):
        rows = self.get(self.rows_table) or []
        if not rows:
            frappe.throw(_("Заповніть табличну частину «Спецодяг і спецоснащення»"))
        for row in rows:
            info = frappe.db.get_value("UA Item", row.item, ["is_group", "item_type"], as_dict=True)
            if not info:
                frappe.throw(_("Рядок {0}: номенклатуру {1} не знайдено").format(row.idx, row.item))
            if info.is_group:
                frappe.throw(_("Рядок {0}: {1} є групою номенклатури").format(row.idx, title_of("UA Item", row.item)))
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))

    def check_warehouse(self, warehouse):
        if not warehouse:
            frappe.throw(_("Вкажіть склад"))
        org = frappe.db.get_value("UA Warehouse", warehouse, "organization")
        if org is None and not frappe.db.exists("UA Warehouse", warehouse):
            frappe.throw(_("Склад {0} не знайдено").format(warehouse))
        if org != self.organization:
            frappe.throw(_("Склад {0} належить іншій організації").format(title_of("UA Warehouse", warehouse)))

    def holder(self):
        """("person" | "department", name) of the document."""
        if self.get("person"):
            return "person", self.person
        return "department", self.department

    def holder_sub(self, item):
        sub = {"Item": item}
        field, value = self.holder()
        sub["Person" if field == "person" else "Department"] = value
        return sub

    def check_holder(self):
        if bool(self.get("person")) == bool(self.get("department")):
            frappe.throw(_("Вкажіть працівника або підрозділ"))

    def off_entry(self, side, item, qty, cost):
        sub = self.holder_sub(item)
        if side == "dr":
            return self.entry(OFF_BALANCE_ACCOUNT, "", cost, sub, None, quantity_dr=flt(qty, 3))
        return self.entry("", OFF_BALANCE_ACCOUNT, cost, None, sub, quantity_cr=flt(qty, 3))

    def has_allocations(self):
        """True when a submitted return, write-off or monthly write-off uses a row of this issue."""
        lines = frappe.get_all(LINE_DT, filters={"parent": self.name}, pluck="name", parent_doctype=ISSUE)
        if not lines:
            return False
        for table, parent in ((ALLOC, "UA Special Wear Return"), (ALLOC, "UA Special Wear Writeoff"),
                              (MONTHLY, "UA Special Wear Monthly Writeoff")):
            if _child_rows(table, parent, "a.issue_line", lines, "9999-12-31"):
                return True
        return False


# ---------------------------------------------------------------- issue


class UASpecialWearIssue(SpecialWearDocument):
    """Передача в експлуатацію.

    100 %: Дт 92 Кт 22 at once. 50 % + 50 %: Дт 92 Кт 22 half. Evenly: no expense, the cost moves
    to the in-use warehouse and is written off monthly. Off the balance: Дт МЦ.04.
    """

    doc_code = "SWI"
    doc_title = "Передача в експлуатацію спецодягу і спецоснащення"

    def validate(self):
        super().validate()
        self.check_warehouse(self.warehouse)
        if self.recipient_type == TO_DEPARTMENT:
            if not self.department:
                frappe.throw(_("Вкажіть підрозділ"))
            self.person = None
        else:
            self.recipient_type = TO_PERSON
            if not self.person:
                frappe.throw(_("Вкажіть працівника"))
            self.department = None
        account = self.expense_account or "92"
        if account not in EXPENSE_ACCOUNTS:
            frappe.throw(_("Рахунок витрат {0} не підходить для цього документа").format(account))
        if not self.writeoff_method:
            self.writeoff_method = AT_ONCE
        if self.writeoff_method == EVEN:
            if int(self.useful_life_months or 0) <= 0:
                frappe.throw(_("Вкажіть строк корисного використання в місяцях"))
        else:
            self.useful_life_months = 0

    def before_submit(self):
        """Fix the cost of the rows: moving average (or FIFO) cost of the warehouse."""
        self._ctx = {}
        used = {}
        for row in self.items:
            cost = take_cost(self, row, STOCK, row.item, self.warehouse, row.quantity, used)
            row.cost = cost
            if self.writeoff_method == AT_ONCE:
                row.expensed = cost
            elif self.writeoff_method == HALF:
                row.expensed = flt(cost / 2, 2)
            else:
                row.expensed = 0

    def before_cancel(self):
        super().before_cancel()
        if self.has_allocations():
            frappe.throw(
                _("Документ не можна скасувати: за ним вже є повернення, списання або списання вартості за місяць")
            )

    def build(self):
        entries = []
        in_use = None
        for row in self.items:
            qty = flt(row.quantity, 3)
            cost, expensed = flt(row.cost, 2), flt(row.expensed, 2)
            stock_sub = {"Item": row.item, "Warehouse": self.warehouse}
            exp_sub = expense_sub(self.expense_item, self.department)
            if self.writeoff_method == EVEN:
                in_use = in_use or in_use_warehouse(self.organization)
                entries.append(
                    self.entry(STOCK, STOCK, cost, {"Item": row.item, "Warehouse": in_use}, stock_sub,
                               quantity_dr=qty, quantity_cr=qty)
                )
            else:
                entries.append(self.entry(self.expense_account, STOCK, expensed, exp_sub, stock_sub, quantity_cr=qty))
            entries.append(self.off_entry("dr", row.item, qty, cost))
        return entries, [], []


# ---------------------------------------------------------------- monthly write-off


class UASpecialWearMonthlyWriteoff(AccountingDocument):
    """Списання вартості за місяць: Дт 92 Кт 22 for items issued with the even method.

    The part is the unwritten cost divided by the months left. The first month is the month after the issue.
    """

    doc_code = "SWM"
    doc_title = "Списання вартості спецодягу за місяць"

    def before_submit(self):
        self.set("lines", [])
        date = getdate(self.posting_date)
        for lot in lots(self.organization, date, exclude=(self.doctype, self.name)):
            if lot.writeoff_method != EVEN:
                continue
            if lot.later:
                frappe.throw(
                    _("За передачею {0} вже є пізніші документи. Проведіть документ пізнішою датою").format(lot.issue)
                )
            life = int(lot.useful_life_months or 0)
            start = getdate(lot.posting_date)
            k = min((date.year - start.year) * 12 + date.month - start.month, life)
            if k <= lot.months_done:
                continue
            rest = flt(lot.cost_left - lot.expensed_left, 2)
            amount = rest if k >= life else flt(rest * (k - lot.months_done) / (life - lot.months_done), 2)
            self.append(
                "lines",
                {"issue": lot.issue, "issue_line": lot.line, "item": lot.item, "quantity": lot.qty_left,
                 "months_done": k, "amount": amount},
            )

    def before_cancel(self):
        super().before_cancel()
        check_no_later(self)

    def build(self):
        self._ctx = {}
        entries = []
        in_use = in_use_warehouse(self.organization)
        for line in self.lines:
            issue = frappe.db.get_value(
                ISSUE, line.issue, ["expense_account", "expense_item", "department"], as_dict=True
            )
            entries.append(
                self.entry(
                    issue.expense_account, STOCK, line.amount,
                    expense_sub(issue.expense_item, issue.department),
                    {"Item": line.item, "Warehouse": in_use},
                )
            )
        return entries, [], []


# ---------------------------------------------------------------- return


class UASpecialWearReturn(SpecialWearDocument):
    """Повернення на склад: off-balance Кт; the expensed cost comes back Дт 22 Кт 92.

    With the even method the unwritten cost moves from the in-use warehouse back (22 total is the same).
    """

    doc_code = "SWR"
    doc_title = "Повернення спецодягу на склад"

    def validate(self):
        super().validate()
        self.check_holder()
        self.check_warehouse(self.warehouse)

    def before_cancel(self):
        super().before_cancel()
        check_no_later(self)

    def before_submit(self):
        self.set("allocations", [])
        pending = {}
        for row in self.items:
            for alloc in take_from_lots(
                self.organization, self.posting_date, self.holder(), row.item, row.quantity,
                (self.doctype, self.name), row.idx, pending,
            ):
                self.append("allocations", alloc)

    def build(self):
        self._ctx = {}
        entries = []
        in_use = None
        for a in self.allocations:
            qty = flt(a.quantity, 3)
            stock_sub = {"Item": a.item, "Warehouse": self.warehouse}
            if a.method == EVEN:
                in_use = in_use or in_use_warehouse(self.organization)
                entries.append(
                    self.entry(STOCK, STOCK, flt(a.cost - a.expensed, 2), stock_sub, {"Item": a.item, "Warehouse": in_use},
                               quantity_dr=qty, quantity_cr=qty)
                )
            else:
                department = frappe.db.get_value(ISSUE, a.issue, "department")
                entries.append(
                    self.entry(STOCK, a.expense_account, a.expensed, stock_sub,
                               expense_sub(a.expense_item, department), quantity_dr=qty)
                )
            entries.append(self.off_entry("cr", a.item, qty, a.cost))
        return entries, [], []


# ---------------------------------------------------------------- write-off from use


class UASpecialWearWriteoff(SpecialWearDocument):
    """Списання з експлуатації: off-balance Кт; the unwritten rest of the cost Дт 92 Кт 22."""

    doc_code = "SWW"
    doc_title = "Списання спецодягу з експлуатації"

    def validate(self):
        super().validate()
        self.check_holder()

    def before_cancel(self):
        super().before_cancel()
        check_no_later(self)

    def before_submit(self):
        self.set("allocations", [])
        pending = {}
        for row in self.items:
            for alloc in take_from_lots(
                self.organization, self.posting_date, self.holder(), row.item, row.quantity,
                (self.doctype, self.name), row.idx, pending,
            ):
                self.append("allocations", alloc)

    def build(self):
        self._ctx = {}
        entries = []
        in_use = None
        for a in self.allocations:
            qty = flt(a.quantity, 3)
            rest = flt(a.cost - a.expensed, 2)
            department = frappe.db.get_value(ISSUE, a.issue, "department")
            if a.method == EVEN:
                in_use = in_use or in_use_warehouse(self.organization)
                # the items leave the in-use warehouse: quantity goes out even when the rest is nil
                entries.append(
                    self.entry(a.expense_account, STOCK, rest, expense_sub(a.expense_item, department),
                               {"Item": a.item, "Warehouse": in_use}, quantity_cr=qty)
                )
            elif rest:
                entries.append(
                    self.entry(a.expense_account, STOCK, rest, expense_sub(a.expense_item, department),
                               {"Item": a.item, "Warehouse": a.warehouse})
                )
            entries.append(self.off_entry("cr", a.item, qty, a.cost))
        return entries, [], []


# ---------------------------------------------------------------- report


def in_use_rows(organization, date_to, person=None, department=None):
    """Rows of the in-use statement: one per lot left."""
    holder = None
    if person:
        holder = ("person", person)
    elif department:
        holder = ("department", department)
    rows = []
    for lot in lots(organization, date_to, holder):
        # the lot quantity left and cost left; written off = expensed part of the cost left
        rows.append(
            {
                "person": lot.person,
                "department": lot.department,
                "item": lot.item,
                "quantity": lot.qty_left,
                "cost": lot.cost_left,
                "issue_date": str(lot.posting_date),
                "written_off": lot.expensed_left,
                "remaining": flt(lot.cost_left - lot.expensed_left, 2),
                "issue": lot.issue,
            }
        )
    return rows
