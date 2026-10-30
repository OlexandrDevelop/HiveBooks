from frappe.model.document import Document
from ua_accounting.accounting_policy import policy_for


class UAFixedAsset(Document):
    def validate(self):
        if not self.depreciation_method:
            policy = policy_for(self.organization, self.commissioning_date)
            self.depreciation_method = policy.depreciation_method if policy else "Прямолінійний"
