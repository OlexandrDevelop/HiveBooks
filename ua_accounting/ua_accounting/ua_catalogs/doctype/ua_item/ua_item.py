from frappe.utils.nestedset import NestedSet


class UAItem(NestedSet):
    nsm_parent_field = "parent_ua_item"
