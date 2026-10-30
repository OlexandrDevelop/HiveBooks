from ua_accounting.accounting.asset_documents import AssetDocument

LOSS_ACCOUNT = "973"


class UAAssetWriteoff(AssetDocument):
    """Списання ОЗ.

    Dt 13x Ct 10x   accumulated wear
    Dt 973 Ct 10x   residual cost
    A low-value asset with 50 % + 50 % first gets the other half: Dt 92 Ct 132.
    """

    doc_code = "SP"
    doc_title = "Списання ОЗ"

    def validate(self):
        super().validate()
        self.check_not_depreciated_later()
        self.residual_value = self.residual_after_disposal()

    def build(self):
        return self.disposal_entries(LOSS_ACCOUNT), [], []
