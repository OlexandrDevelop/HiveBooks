from frappe.utils.nestedset import NestedSet


class UADepartment(NestedSet):
    nsm_parent_field = "parent_ua_department"
