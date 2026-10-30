"""The provider «ІІТ» (iit_eusign) on the signature contract of the core (frappe.beeone.providers.signature).

The EUSign library stays in the app (eusign.py). This class only maps the contract to it. A key is a
ProviderKey (file and password: read for one call, never logged) or a key that is already open.
"""

from frappe.beeone.providers import log_call
from frappe.beeone.providers.signature import ProviderKey, SignatureError, SignatureProvider

from ua_accounting.accounting import eusign

PROVIDER_NAME = "iit_eusign"


class EUSignSignature(SignatureProvider):
    name = PROVIDER_NAME

    def sign(self, key, data, level=None):
        log_call(self.name, "sign", key=key, level=level, size=len(data))
        try:
            if isinstance(key, ProviderKey):
                with eusign.open_key(key.data, key.password) as opened:
                    return eusign.sign(opened, data, level or "CAdES-BES")
            return eusign.sign(key, data, level or "CAdES-BES")
        except eusign.EUSignError as exc:
            raise SignatureError(str(exc)) from exc

    def verify(self, signature):
        log_call(self.name, "verify", size=len(signature))
        try:
            data, signer = eusign.verify(signature)
        except eusign.EUSignError as exc:
            raise SignatureError(str(exc)) from exc
        return data, {**signer, "subject": signer["subject_cn"]}

    def signer_info(self, signature):
        try:
            cert = eusign.signer_certificate(signature)
        except eusign.EUSignError as exc:
            raise SignatureError(str(exc)) from exc
        return {**cert, "subject": cert["subject_cn"]}
