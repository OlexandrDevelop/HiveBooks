from frappe.utils.nestedset import NestedSet


class UACounterparty(NestedSet):
    nsm_parent_field = "parent_ua_counterparty"
