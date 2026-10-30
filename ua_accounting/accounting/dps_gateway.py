"""Подання до ДПС: транспорт (Електронний кабінет), пісочниця ДПС для тестового сайту, розбір квитанцій №1 і №2.

A transport takes the signed document and returns the raw receipts (each one signed by ДПС). The parsing of a
receipt is separate and always checks the signature, the certificate chain and that the signer is ДПС.

!! The HTTP protocol below follows the public description of the Електронний кабінет API ("JSON з вкладеним
base64 XML, Authorization = ЄДРПОУ, підписаний внутрішнім підписом, з сертифікатом"). The official page
cabinet.tax.gov.ua/help/api.html could not be opened when this was written, so the paths and the JSON fields
(SEND_PATH, RECEIPTS_PATH, "documents", "receipts") are the first thing to confirm with a real key (phase 2).
They are constants in this file on purpose.

Sources: наказ Мінфіну від 14.07.2017 №637 (Електронний кабінет), наказ Мінфіну №13 (квитанції №1 і №2).
"""

import base64
import hashlib
import os
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from ua_accounting.accounting import eusign

ENV_WORKING, ENV_TEST, ENV_SANDBOX = "Робоче", "Тестове", "Пісочниця (імітація ДПС)"
WORKING_URL = "https://cabinet.tax.gov.ua"
SEND_PATH = "/ws/public_api/exchange/send"  # to confirm with a real key
RECEIPTS_PATH = "/ws/public_api/exchange/receipts"  # to confirm with a real key
DPS_EDRPOU = "43005393"  # ЄДРПОУ of the State Tax Service, the signer of the receipts
ALLOWED_HOST_SUFFIXES = (".gov.ua",)
MAX_RESPONSE = 5 * 1024 * 1024
TIMEOUT = 60

SANDBOX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox")
SANDBOX_CA_NAME = "Test CA UA Accounting"
SANDBOX_KEY_PASSWORD = "test1234"  # of the bundled TEST key of the "ДПС server"; the key is trusted by the test CA only


# ---------------------------------------------------------------- addresses


def allowed_host(host):
    """The gateway must be a host of a state domain (or one named in site config ua_dps_allowed_hosts)."""
    extra = frappe.conf.get("ua_dps_allowed_hosts") or []
    host = (host or "").lower()
    return host in extra or any(host.endswith(suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def base_url(setting):
    if setting.dps_environment == ENV_WORKING:
        return WORKING_URL
    url = (setting.api_url or "").strip().rstrip("/")
    if not url:
        frappe.throw(_("Вкажіть адресу API ДПС для тестового середовища"))
    return url


def check_url(url):
    parts = urlparse(url)
    if parts.scheme != "https" or not allowed_host(parts.hostname):
        frappe.throw(_("Адреса API ДПС має бути https-адресою сервера державного домену (.gov.ua)"))


# ---------------------------------------------------------------- the receipts


def receipt_xml(kind, result, text, xml_hash, reg_number=""):
    from xml.sax.saxutils import escape

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<DECLAR><RECEIPT KIND="{escape(kind)}">'
        f"<RESULT>{escape(result)}</RESULT><TEXT>{escape(text)}</TEXT><HASH>{xml_hash}</HASH>"
        f"<REGNUM>{reg_number}</REGNUM></RECEIPT></DECLAR>"
    )


def parse_receipt_xml(data):
    """kind, result, text, hash, reg_number of the receipt XML (the format of this release, see CONTRACT)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        frappe.throw(_("Квитанція не є правильним XML"))
    node = root if root.tag == "RECEIPT" else root.find("RECEIPT")
    if node is None:
        frappe.throw(_("У квитанції немає елемента RECEIPT"))
    get = lambda tag: (node.findtext(tag) or "").strip()
    return {"kind": node.get("KIND") or "", "result": get("RESULT"), "text": get("TEXT"), "hash": get("HASH"),
            "reg_number": get("REGNUM")}


def read_receipt(raw, xml_hash, trusted):
    """A receipt from ДПС (CAdES with the XML inside) as a dict ready for the archive record.
    Checks: the signature and the chain of the certificate, the signer is ДПС, the receipt is for this document.
    `trusted(issuer_cn)` tells if the CA of the signer is accepted. Raises frappe.ValidationError on any failure."""
    try:
        data, signer = eusign.verify(raw)
    except eusign.EUSignError as exc:
        frappe.throw(_("Підпис квитанції недійсний: {0}").format(exc))
    if not trusted(signer["issuer_cn"]):
        frappe.throw(_("ЦСК підписувача квитанції не входить до довірених: {0}").format(signer["issuer_cn"]))
    if signer["edrpou"] != DPS_EDRPOU:
        frappe.throw(_("Квитанцію підписано не ДПС (ЄДРПОУ підписувача {0})").format(signer["edrpou"] or "—"))
    parsed = parse_receipt_xml(data)
    if parsed["hash"] != xml_hash:
        frappe.throw(_("Квитанція стосується іншого документа"))
    if parsed["kind"] not in ("Квитанція №1", "Квитанція №2") or parsed["result"] not in ("Прийнято", "Відхилено"):
        frappe.throw(_("Невідомий вид або результат квитанції"))
    out = {
        "kind": parsed["kind"], "result": parsed["result"], "text": parsed["text"],
        "xml": data.decode("utf-8", "replace"), "received_at": now_datetime(), "signed_by": signer["subject_cn"],
        "chain_ok": 1, "signature": base64.b64encode(raw).decode("ascii"),
    }
    if parsed["reg_number"]:
        out.update(erpn_reg_number=parsed["reg_number"], erpn_reg_date=today())
    return out


# ---------------------------------------------------------------- transport to the real gateway


class HttpTransport:
    """The Електронний кабінет gateway of ДПС (робоче або тестове середовище)."""

    def __init__(self, setting, key):
        self.setting, self.key = setting, key
        self.url = base_url(setting)
        check_url(self.url)

    def _headers(self, edrpou):
        auth = base64.b64encode(eusign.sign(self.key, edrpou.encode("ascii"))).decode("ascii")
        headers = {"Authorization": auth, "Content-Type": "application/json", "Accept": "application/json"}
        api_key = self.setting.get_password("api_key", raise_exception=False)
        if api_key:
            headers["X-Api-Key"] = api_key
        return headers

    def _call(self, method, path, edrpou, **kw):
        import requests

        try:
            res = requests.request(method, self.url + path, headers=self._headers(edrpou), timeout=TIMEOUT,
                                   allow_redirects=False, stream=True, **kw)
            body = res.raw.read(MAX_RESPONSE + 1, decode_content=True)
        except requests.RequestException as exc:
            frappe.throw(_("Немає зв'язку з ДПС: {0}").format(type(exc).__name__))
        if len(body) > MAX_RESPONSE:
            frappe.throw(_("Відповідь ДПС завелика"))
        if res.status_code != 200:
            frappe.throw(_("ДПС не прийняв запит (код {0})").format(res.status_code))
        try:
            return frappe.parse_json(body.decode("utf-8"))
        except Exception:
            frappe.throw(_("Відповідь ДПС не є правильним JSON"))

    @staticmethod
    def _receipts(answer):
        return [base64.b64decode(item["data"]) for item in (answer or {}).get("receipts", [])]

    def send(self, edrpou, filename, payload):
        answer = self._call("POST", SEND_PATH, edrpou,
                            json={"documents": [{"name": filename, "data": base64.b64encode(payload).decode("ascii")}]})
        return self._receipts(answer)

    def fetch(self, edrpou, xml_hash):
        return self._receipts(self._call("GET", RECEIPTS_PATH, edrpou, params={"hash": xml_hash}))


# ---------------------------------------------------------------- the sandbox of ДПС (test site only)


def sandbox_ca_certificate():
    with open(os.path.join(SANDBOX_DIR, "test_ca.cer"), "rb") as fh:
        return fh.read()


class SandboxTransport:
    """In-process imitation of the ДПС gateway. It checks the document like the real one (signature, chain,
    content) and answers with receipts SIGNED by a bundled test key of "ДПС". It lets the whole chain
    (КЕП → подання → квитанції → перевірка) run on a test site without any real key."""

    def __init__(self, setting, key, test_provider):
        self.setting, self.key, self.test_provider = setting, key, test_provider

    def _answer(self, row):
        from ua_accounting.accounting import e_reporting as er

        if row.xml_hash != hashlib.sha256(er.xml_bytes(row.xml_content)).hexdigest():
            frappe.throw(_("ДПС не прийняв запит: вміст документа змінено"))
        out = []
        with open(os.path.join(SANDBOX_DIR, "dps_key.p12"), "rb") as fh:
            blob = fh.read()
        leaf = eusign.pkcs12_leaf_certificate(blob, SANDBOX_KEY_PASSWORD)
        eusign.save_signer_certificate(leaf)
        with eusign.open_key(blob, SANDBOX_KEY_PASSWORD) as dps_key:
            for receipt in self.test_provider._answer(self.setting, row):
                xml = receipt_xml(receipt["kind"], receipt["result"], receipt["text"], row.xml_hash,
                                  receipt.get("erpn_reg_number") or "")
                out.append(eusign.sign(dps_key, xml.encode("utf-8")))
        return out

    def send(self, row, payload):
        # the document is checked the way the real gateway does: the signature and the chain
        data, _signer = eusign.verify(payload)
        if hashlib.sha256(data).hexdigest() != row.xml_hash:
            frappe.throw(_("ДПС не прийняв запит: підписаний вміст не збігається з документом"))
        return self._answer(row)

    def fetch(self, row):
        return self._answer(row)
