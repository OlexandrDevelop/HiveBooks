from frappe.utils.nestedset import NestedSet


class UACashFlowItem(NestedSet):
    nsm_parent_field = "parent_ua_cash_flow_item"
