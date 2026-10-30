"""Електронна звітність: підпис КЕП, подання до ДПС, квитанції, статус ЄРПН.

A source document (ПН, РК, декларація з ПДВ, регламентований або статистичний звіт) is exported to XML,
signed (UA Signed Document keeps the signed bytes) and sent. The provider does the signing and talks to ДПС;
all providers have the same interface (sign / verify / send / fetch_receipts).

Sources: Закон «Про електронні довірчі послуги» (КЕП), ПКУ ст. 201.1 (ПН підписується КЕП), ст. 201.10 (15 днів),
ст. 44.3 (зберігання 1095 днів), наказ Мінфіну №13 (квитанції №1 і №2).
The built-in «Тестовий провайдер» is a sandbox with fake signatures and fake receipts: it works only
on a test site (developer mode) and is refused everywhere else.
The provider «ІІТ» (iit_eusign) signs with the ІІТ EUSignCP library: a real CAdES signature, the check of the
certificate chain, delivery to ДПС (dps_gateway) and receipts that are verified before they are stored.
"""

import base64
import hashlib
import json
import os
from xml.sax.saxutils import escape

import frappe
from frappe import _
from frappe.beeone import providers as core_providers
from frappe.beeone.providers.signature import SignatureError
from frappe.utils import flt, getdate, now_datetime, today
from frappe.utils.password import remove_encrypted_password

from ua_accounting.accounting import dps_gateway, eusign
from ua_accounting.accounting import regulated_report as rr
from ua_accounting.accounting import statistics, tax, tax_xml

SETTING = "UA E-Reporting Setting"
SIGNED = "UA Signed Document"
INBOUND = "UA ERPN Inbound"
RET = "UA VAT Return"
REG = rr.DOCTYPE
STAT = statistics.DOCTYPE
SOURCES = (tax.PN, tax.RK, RET, REG, STAT)

TEST_PROVIDER = "Тестовий провайдер"
IIT = "ІІТ"
PROVIDERS = (TEST_PROVIDER, IIT, "Дія.Підпис", "Інший API")
CA_OFFLINE = "Офлайн (лише тестовий ЦСК)"
LEVEL_T = "CAdES-T"
MAX_KEY_SIZE = 256 * 1024
MAX_VERIFY_SIZE = 20 * 1024 * 1024
MANAGERS = ("UA Accounting Manager", "System Manager")
MODE_ACCEPT, MODE_REJECT, MODE_SILENT = "Приймати", "Відхиляти", "Без відповіді"

SIGNED_OK, SENT, ACCEPTED, REJECTED = "Підписано", "Надіслано", "Прийнято", "Відхилено"
RECEIPT_1, RECEIPT_2 = "Квитанція №1", "Квитанція №2"
REJECT_TEXT = "Тестова відмова: помилка в документі"
ENCODING = "windows-1251"
FIRST_REG_NUMBER = 9300000001  # sandbox numbers: 10 digits

# fields that change when the document is registered or filed; they are not part of the signed content
VOLATILE = {"name", "creation", "modified", "modified_by", "owner", "status", "xsd_version", "erpn_status",
            "erpn_reg_number", "erpn_reg_date", "idx", "parent", "parentfield", "parenttype", "doctype"}


# ---------------------------------------------------------------- access and settings


def check_roles():
    frappe.only_for(rr.READERS)


def sandbox_allowed():
    """The test provider is for a test site only (developer mode)."""
    return bool(frappe.conf.get("developer_mode"))


def get_setting(organization):
    if not frappe.db.exists(SETTING, organization):
        frappe.throw(_("Для організації {0} не налаштовано електронну звітність").format(organization))
    return frappe.get_doc(SETTING, organization)


def check_provider_allowed(setting):
    if setting.provider == TEST_PROVIDER and not sandbox_allowed():
        frappe.throw(_("Тестовий провайдер працює лише на тестовому сайті"), frappe.PermissionError)
    if setting.provider == IIT and uses_test_ca(setting) and not sandbox_allowed():
        frappe.throw(_("Пісочниця ДПС і офлайн-режим працюють лише на тестовому сайті"), frappe.PermissionError)


def validate_iit_setting(setting):
    """Rules of the settings of the provider ІІТ (called when the setting is saved)."""
    if setting.dps_environment == dps_gateway.ENV_TEST:
        dps_gateway.check_url(dps_gateway.base_url(setting))
    if uses_test_ca(setting) and setting.sign_level == LEVEL_T:
        frappe.throw(_("Позначка часу (CAdES-T) потребує серверів ЦСК: для тестового режиму оберіть CAdES-BES"))
    if setting.dps_encrypt and setting.dps_environment != dps_gateway.ENV_SANDBOX and not setting.dps_certificate:
        frappe.throw(_("Для шифрування документа вставте сертифікат ДПС"))


def uses_test_ca(setting):
    """The offline mode and the sandbox of ДПС work with the bundled test CA, never with real ones."""
    return setting.ca_mode == CA_OFFLINE or setting.dps_environment == dps_gateway.ENV_SANDBOX


def certificate_ok(setting, org, on_date):
    """The certificate is valid on the date and belongs to the legal entity of the organization."""
    on_date = getdate(on_date)
    if not setting.certificate_valid_from or not setting.certificate_valid_to:
        return False
    if not getdate(setting.certificate_valid_from) <= on_date <= getdate(setting.certificate_valid_to):
        return False
    return (setting.certificate_edrpou or "") == (org.edrpou or "")


# ---------------------------------------------------------------- providers


class Provider:
    """Interface of a provider."""

    def sign(self, setting, xml_hash, signed_at, xml):
        raise NotImplementedError

    def verify(self, setting, signature, xml_hash, xml):
        """dict: signature_ok (bool), chain_ok (bool or None when the provider has no chain), signer, issuer,
        edrpou, error (text)."""
        raise NotImplementedError

    def certificate_valid(self, setting, org, result, on_date):
        """The certificate of the signer is valid on the date and belongs to the legal entity of the organization."""
        return certificate_ok(setting, org, on_date)

    def send(self, setting, signed):
        """Receipts returned at once (a list of dicts; may be empty)."""
        raise NotImplementedError

    def fetch_receipts(self, setting, signed):
        raise NotImplementedError


class NotConnected(Provider):
    """Дія.Підпис and «Інший API» need an account of the customer; they are not built into this release.
    A real provider must verify the КЕП signature and the certificate chain before it is enabled."""

    def _refuse(self, *args):
        frappe.throw(_("Провайдер КЕП не підключено: оберіть іншого провайдера або підключіть бібліотеку"))

    sign = verify = send = fetch_receipts = _refuse


class TestProvider(Provider):
    """Sandbox: signature = base64 of TESTSIG|<sha256>|<signer>|<time>; ДПС answers by the test mode."""

    def sign(self, setting, xml_hash, signed_at, xml):
        text = f"TESTSIG|{xml_hash}|{setting.certificate_holder}|{signed_at}"
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    def verify(self, setting, signature, xml_hash, xml):
        try:
            parts = base64.b64decode(signature or "", validate=True).decode("utf-8").split("|")
        except Exception:
            parts = []
        ok = len(parts) >= 4 and parts[0] == "TESTSIG" and parts[1] == xml_hash
        return {"signature_ok": ok, "chain_ok": None, "signer": parts[2] if ok else "", "issuer": "", "edrpou": "",
                "error": "" if ok else _("Підпис емулятора недійсний")}

    def send(self, setting, signed):
        return self._answer(setting, signed)

    def fetch_receipts(self, setting, signed):
        return self._answer(setting, signed)

    def _answer(self, setting, signed):
        mode = setting.test_mode or MODE_ACCEPT
        if mode == MODE_SILENT:
            return []
        receipts = [self._receipt(RECEIPT_1, ACCEPTED, "Документ отримано", signed)]
        if mode == MODE_REJECT:
            receipts.append(self._receipt(RECEIPT_2, REJECTED, REJECT_TEXT, signed))
            return receipts
        reg = {}
        if signed.source_doctype in (tax.PN, tax.RK):
            reg = {"erpn_reg_number": next_reg_number(signed.organization), "erpn_reg_date": today()}
        text = "Документ прийнято" + (f", реєстраційний номер {reg['erpn_reg_number']}" if reg else "")
        receipts.append(self._receipt(RECEIPT_2, ACCEPTED, text, signed, **reg))
        return receipts

    def _receipt(self, kind, result, text, signed, **extra):
        reg = extra.get("erpn_reg_number") or ""
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<DECLAR><RECEIPT KIND="{escape(kind)}">'
            f"<RESULT>{escape(result)}</RESULT><TEXT>{escape(text)}</TEXT><HASH>{signed.xml_hash}</HASH>"
            f"<REGNUM>{reg}</REGNUM></RECEIPT></DECLAR>"
        )
        return {"kind": kind, "result": result, "text": text, "xml": xml, "received_at": now_datetime(), **extra}


class IITProvider(Provider):
    """Provider «ІІТ» (iit_eusign): the library ІІТ EUSignCP. The key file and its password are kept in Password
    fields of the setting, are read only here and never returned or logged."""

    def trusted(self, issuer_cn):
        """Only accredited CAs (CAs.json of the SDK); the bundled test CA only on a test site."""
        if eusign.ca_of_issuer(issuer_cn):
            return True
        return sandbox_allowed() and issuer_cn == dps_gateway.SANDBOX_CA_NAME

    def prepare(self, setting, issuer_cn=None):
        if not eusign.available():
            frappe.throw(_("Бібліотеку ІІТ EUSignCP не встановлено на сервері: виконайте scripts/install_eusign.sh "
                           "(див. docs/regulatory-update-process.md) або оберіть емулятор"))
        offline = uses_test_ca(setting) or (sandbox_allowed() and issuer_cn == dps_gateway.SANDBOX_CA_NAME)
        try:
            if sandbox_allowed():
                eusign.add_test_ca(dps_gateway.sandbox_ca_certificate())
            eusign.configure(issuer_cn, offline)
        except eusign.EUSignError as exc:
            frappe.throw(_("Бібліотеку ІІТ не налаштовано: {0}").format(exc))

    def open_key(self, setting):
        data = setting.get_password("key_data", raise_exception=False)
        if not data:
            frappe.throw(_("Особистий ключ не завантажено: відкрийте налаштування електронної звітності і завантажте файл ключа"))
        self.prepare(setting)
        try:
            return eusign.open_key(base64.b64decode(data), setting.get_password("key_password", raise_exception=False))
        except eusign.EUSignError as exc:
            frappe.throw(_("Ключ КЕП не відкрито: {0}").format(exc))

    def signer(self):
        """The signature provider of the core contract (the library stays in this app)."""
        return core_providers.get_signature_provider("iit_eusign")

    def level(self, setting):
        return LEVEL_T if setting.sign_level == LEVEL_T and not uses_test_ca(setting) else "CAdES-BES"

    def sign(self, setting, xml_hash, signed_at, xml):
        with self.open_key(setting) as key:
            issuer = key.cert["issuer_cn"]
            if not self.trusted(issuer):
                frappe.throw(_("ЦСК «{0}» не входить до списку акредитованих ЦСК").format(issuer))
            self.prepare(setting, issuer)
            try:
                signature = self.signer().sign(key, xml_bytes(xml), self.level(setting))
            except SignatureError as exc:
                frappe.throw(_("Підпис не сформовано: {0}").format(exc))
        return base64.b64encode(signature).decode("ascii")

    def verify(self, setting, signature, xml_hash, xml):
        res = {"signature_ok": False, "chain_ok": False, "signer": "", "issuer": "", "edrpou": "", "error": ""}
        try:
            raw = base64.b64decode(signature or "", validate=True)
            cert = self.signer().signer_info(raw)
        except (ValueError, SignatureError) as exc:
            res["error"] = _("Підпис не розпізнано: {0}").format(exc)
            return res
        res["issuer"] = cert["issuer_cn"]
        if not self.trusted(cert["issuer_cn"]):
            res["error"] = _("ЦСК «{0}» не входить до списку акредитованих ЦСК").format(cert["issuer_cn"])
            return res
        self.prepare(setting, cert["issuer_cn"])
        try:
            data, signer = self.signer().verify(raw)
        except SignatureError as exc:
            res["error"] = str(exc)
            return res
        res.update(chain_ok=True, signer=signer["subject_cn"], edrpou=signer["edrpou"] or signer["drfo"])
        if data != xml_bytes(xml):
            res["error"] = _("Підписані дані не збігаються з XML")
            return res
        res["signature_ok"] = True
        return res

    def certificate_valid(self, setting, org, result, on_date):
        return bool(result.get("edrpou")) and result["edrpou"] == (org.edrpou or "")

    # -- delivery and receipts

    def _transport(self, setting, key):
        if setting.dps_environment == dps_gateway.ENV_SANDBOX:
            return dps_gateway.SandboxTransport(setting, key, TestProvider())
        return dps_gateway.HttpTransport(setting, key)

    def _payload(self, setting, key, signed):
        payload = base64.b64decode(signed.signature)
        if setting.dps_encrypt and setting.dps_certificate and setting.dps_environment != dps_gateway.ENV_SANDBOX:
            try:
                cert = eusign._certificates_of(setting.dps_certificate.encode("utf-8"))[0]
                from cryptography.hazmat.primitives import serialization

                payload = eusign.envelop(key, cert.public_bytes(serialization.Encoding.DER), payload)
            except eusign.EUSignError as exc:
                frappe.throw(_("Документ не зашифровано для ДПС: {0}").format(exc))
        return payload

    def read_receipt(self, setting, signed, raw):
        try:
            issuer = eusign.signer_certificate(raw)["issuer_cn"]
        except eusign.EUSignError as exc:
            frappe.throw(_("Квитанцію не розпізнано: {0}").format(exc))
        self.prepare(setting, issuer)
        return dps_gateway.read_receipt(raw, signed.xml_hash, self.trusted)

    def _read_all(self, setting, signed, raws):
        receipts = []
        for raw in raws:
            try:
                receipts.append(self.read_receipt(setting, signed, raw))
            except frappe.ValidationError as exc:
                frappe.get_doc(SIGNED, signed.name).add_comment("Info", _("Квитанцію відхилено: {0}").format(exc))
        return receipts

    def send(self, setting, signed):
        edrpou = frappe.db.get_value("UA Organization", signed.organization, "edrpou") or ""
        with self.open_key(setting) as key:
            self.prepare(setting, key.cert["issuer_cn"])
            transport = self._transport(setting, key)
            if isinstance(transport, dps_gateway.SandboxTransport):
                raws = transport.send(signed, base64.b64decode(signed.signature))
            else:
                raws = transport.send(edrpou, signed.xml_filename, self._payload(setting, key, signed))
        return self._read_all(setting, signed, raws)

    def fetch_receipts(self, setting, signed):
        edrpou = frappe.db.get_value("UA Organization", signed.organization, "edrpou") or ""
        with self.open_key(setting) as key:
            self.prepare(setting, key.cert["issuer_cn"])
            transport = self._transport(setting, key)
            if isinstance(transport, dps_gateway.SandboxTransport):
                raws = transport.fetch(signed)
            else:
                raws = transport.fetch(edrpou, signed.xml_hash)
        return self._read_all(setting, signed, raws)


def provider_of(setting):
    check_provider_allowed(setting)
    if setting.provider == TEST_PROVIDER:
        return TestProvider()
    return IITProvider() if setting.provider == IIT else NotConnected()


def next_reg_number(organization):
    """10 digits, unique per organization among ПН, РК and the archive."""
    best = FIRST_REG_NUMBER - 1
    for doctype in (tax.PN, tax.RK, SIGNED):
        field = "dps_reg_number" if doctype == SIGNED else "erpn_reg_number"
        for (value,) in frappe.db.sql(
            f"select `{field}` from `tab{doctype}` where organization = %s and `{field}` regexp '^[0-9]{{10}}$'",
            organization,
        ):
            best = max(best, int(value))
    return str(best + 1)


# ---------------------------------------------------------------- the source document


def load_source(doctype, name):
    if doctype not in SOURCES:
        frappe.throw(_("Документ типу {0} не підписують КЕП").format(doctype))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return doc


def check_signable(doc):
    if doc.doctype in (tax.PN, tax.RK):
        if doc.docstatus != 1:
            frappe.throw(_("Підписують лише проведені документи"))
        if doc.doctype == tax.PN and doc.direction != tax.ISSUED:
            frappe.throw(_("Отриману податкову накладну реєструє постачальник: ми її не підписуємо і не надсилаємо"))
        if doc.doctype == tax.RK and doc.get("direction") == tax.RECEIVED:
            frappe.throw(_("Отриманий розрахунок коригування не підписують"))
    elif doc.doctype in (REG, STAT) and doc.status == "Чернетка":
        frappe.throw(_("Спочатку заповніть звіт"))


def export_source(doc, fill_date=None):
    """(filename, xml text) exactly as the export of the source document gives it."""
    if doc.doctype in (tax.PN, tax.RK):
        res = tax_xml.export(doc)
    elif doc.doctype == RET:
        res = tax_xml.export_return(doc, fill_date)
    elif doc.doctype == REG:
        res = rr.export_xml(doc, fill_date)
        return res["filename"], res["content"]
    else:
        res = statistics.export_xml(doc, fill_date)
    return res["filename"], res["xml"]


def xml_bytes(text):
    return text.encode(ENCODING, errors="xmlcharrefreplace")


def digest(text):
    return hashlib.sha256(xml_bytes(text)).hexdigest()


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def fingerprint(doc):
    """Hash of the content of the source. It catches changes that are not in the XML (for example the totals)."""
    data = _strip(frappe.get_doc(doc.doctype, doc.name).as_dict(convert_dates_to_str=True))
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- signing


def sign(doctype, name):
    check_roles()
    doc = load_source(doctype, name)
    check_signable(doc)
    org = frappe.get_doc("UA Organization", doc.organization)
    setting = get_setting(doc.organization)
    provider = provider_of(setting)
    if setting.provider == IIT:
        refresh_certificate(setting)
    if not certificate_ok(setting, org, today()):
        frappe.throw(_("Сертифікат КЕП недійсний на дату підпису або виданий іншій юридичній особі (ЄДРПОУ {0})").format(org.edrpou))
    signed_at = now_datetime()
    filename, xml = export_source(doc, getdate(signed_at))
    xml_hash = digest(xml)
    signature = provider.sign(setting, xml_hash, signed_at.isoformat(timespec="seconds"), xml)
    row = frappe.get_doc(
        {
            "doctype": SIGNED,
            "organization": doc.organization,
            "source_doctype": doctype,
            "source_name": name,
            "xml_filename": filename,
            "xml_content": xml,
            "xml_hash": xml_hash,
            "source_fingerprint": fingerprint(doc),
            "signature": signature,
            "signer": setting.certificate_holder,
            "signed_at": signed_at,
            "provider": setting.provider,
            "status": SIGNED_OK,
        }
    )
    row.flags.ua_system = True
    row.insert(ignore_permissions=True)
    if doctype == RET and doc.status != "Подана":
        doc.db_set("status", "Підписана", update_modified=False)
    return row.name


def load_signed(name):
    check_roles()
    if not frappe.db.exists(SIGNED, name):
        frappe.throw(_("Підписаний документ {0} не знайдено").format(name), frappe.DoesNotExistError)
    row = frappe.get_doc(SIGNED, name)
    row.check_permission("read")
    return row


def source_matches(row):
    """The source still gives the signed bytes and has the signed content."""
    if not frappe.db.exists(row.source_doctype, row.source_name):
        return False
    doc = frappe.get_doc(row.source_doctype, row.source_name)
    try:
        check_signable(doc)
        _filename, xml = export_source(doc, getdate(row.signed_at))
    except frappe.ValidationError:
        return False
    return digest(xml) == row.xml_hash and fingerprint(doc) == row.source_fingerprint


def verify_signature(name):
    row = load_signed(name)
    hash_match = source_matches(row)
    setting = frappe.get_doc(SETTING, row.organization) if frappe.db.exists(SETTING, row.organization) else None
    cert = False
    result = {"signature_ok": False, "chain_ok": None, "signer": "", "issuer": "", "error": ""}
    if setting:
        org = frappe.get_doc("UA Organization", row.organization)
        provider = provider_of(setting)
        result = provider.verify(setting, row.signature, row.xml_hash, row.xml_content)
        cert = provider.certificate_valid(setting, org, result, getdate(row.signed_at))
    # the archived bytes are the signed bytes
    sig_ok = bool(result["signature_ok"]) and digest(row.xml_content) == row.xml_hash
    chain_ok = result["chain_ok"] is not False
    return {
        "valid": bool(sig_ok and hash_match and cert and chain_ok),
        "signer": row.signer,
        "signed_at": str(row.signed_at),
        "hash_match": bool(hash_match),
        "certificate_ok": bool(cert),
        "signature_ok": bool(sig_ok),
        "chain_ok": result["chain_ok"],
        "issuer": result.get("issuer") or "",
        "error": result.get("error") or "",
    }


def verify_data(organization, xml, signature):
    """Check any XML and signature (for example a file downloaded earlier) for the organization.
    Nothing is stored. A changed XML or signature, an untrusted CA or a certificate of another entity is invalid."""
    check_roles()
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    if len(xml or "") > MAX_VERIFY_SIZE or len(signature or "") > MAX_VERIFY_SIZE:
        frappe.throw(_("Файл завеликий для перевірки"))
    setting = get_setting(organization)
    provider = provider_of(setting)
    org = frappe.get_doc("UA Organization", organization)
    result = provider.verify(setting, signature, digest(xml), xml)
    cert = provider.certificate_valid(setting, org, result, getdate(today()))
    return {
        "valid": bool(result["signature_ok"] and cert and result["chain_ok"] is not False),
        "signature_ok": bool(result["signature_ok"]),
        "chain_ok": result["chain_ok"],
        "certificate_ok": bool(cert),
        "signer": result.get("signer") or "",
        "issuer": result.get("issuer") or "",
        "error": result.get("error") or "",
    }


def get_signed_xml(name):
    row = load_signed(name)
    return {"xml": row.xml_content, "filename": row.xml_filename, "signature": row.signature}


# ---------------------------------------------------------------- sending and receipts


def send(name):
    row = load_signed(name)
    if row.status != SIGNED_OK:
        frappe.throw(_("Надсилають лише підписаний документ у статусі «{0}»").format(SIGNED_OK))
    doc = load_source(row.source_doctype, row.source_name)
    check_signable(doc)
    if not source_matches(row):
        frappe.throw(_("Документ змінено після підпису: підпишіть його ще раз"))
    if doc.doctype in (tax.PN, tax.RK) and doc.erpn_status == tax.STATUS_REGISTERED:
        frappe.throw(_("Документ уже зареєстровано в ЄРПН"))
    setting = get_setting(row.organization)
    provider = provider_of(setting)
    row.flags.ua_system = True
    row.sent_at = now_datetime()
    row.status = SENT
    row.is_late = int(doc.doctype in (tax.PN, tax.RK) and getdate(today()) > getdate(tax.deadline_of(doc.posting_date)))
    row.save(ignore_permissions=True)
    update_source(row, None)
    apply_receipts(row, provider.send(setting, row))
    return frappe.get_doc(SIGNED, name).as_dict(convert_dates_to_str=True)


def apply_receipts(row, receipts):
    """Store new receipts, set the status of the archive record and of the source document. Returns True if changed."""
    have = {r.kind for r in row.receipts}
    new = [r for r in receipts if r["kind"] not in have]
    if not new:
        return False
    row.flags.ua_system = True
    for r in new:
        row.append("receipts", r)
    final = {r.kind: r.result for r in row.receipts}.get(RECEIPT_2)
    row.status = {ACCEPTED: ACCEPTED, REJECTED: REJECTED}.get(final, SENT)
    reg = next((r for r in row.receipts if r.kind == RECEIPT_2 and r.erpn_reg_number), None)
    if row.status == ACCEPTED and reg:
        row.dps_reg_number = reg.erpn_reg_number
    row.save(ignore_permissions=True)
    update_source(row, reg)
    return True


def update_source(row, reg):
    doctype, name = row.source_doctype, row.source_name
    if doctype in (tax.PN, tax.RK):
        current = frappe.db.get_value(doctype, name, ["erpn_status", "erpn_reg_number"], as_dict=True)
        if current.erpn_status == tax.STATUS_REGISTERED and row.dps_reg_number != current.erpn_reg_number:
            # registered by another archive record: an older receipt must not change it
            frappe.get_doc(doctype, name).add_comment(
                "Info", _("Квитанція запису {0} ({1}) не змінила статус ЄРПН: документ уже зареєстровано").format(row.name, row.status)
            )
            return
        values = {"erpn_status": tax.STATUS_SENT, "erpn_reg_number": "", "erpn_reg_date": None}
        if row.status == ACCEPTED and reg:
            values = {"erpn_status": tax.STATUS_REGISTERED, "erpn_reg_number": reg.erpn_reg_number,
                      "erpn_reg_date": reg.erpn_reg_date}
        elif row.status == REJECTED:
            values["erpn_status"] = tax.STATUS_REJECTED
        frappe.db.set_value(doctype, name, values, update_modified=False)
        frappe.get_doc(doctype, name).add_comment("Info", _("Статус ЄРПН: {0}").format(values["erpn_status"]))
    elif row.status == ACCEPTED:
        frappe.db.set_value(doctype, name, "status", "Подана" if doctype == RET else rr.EXPORTED, update_modified=False)


def sync_receipts(organization):
    check_roles()
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    rows = frappe.get_all(SIGNED, filters={"organization": organization, "status": SENT}, pluck="name", order_by="creation")
    if not rows:
        return {"checked": 0, "updated": 0}
    setting = get_setting(organization)
    provider = provider_of(setting)
    updated = 0
    for name in rows:
        row = frappe.get_doc(SIGNED, name)
        if apply_receipts(row, provider.fetch_receipts(setting, row)):
            updated += 1
    return {"checked": len(rows), "updated": updated}


def ingest_receipt(name, receipt):
    """Store a receipt (base64, signed by ДПС) that was delivered by other means. It is verified like the ones
    that arrive on sending: signature, chain, signer ДПС, and it must be for this document."""
    row = load_signed(name)
    setting = get_setting(row.organization)
    provider = provider_of(setting)
    if not isinstance(provider, IITProvider):
        frappe.throw(_("Перевірку підписаних квитанцій підтримує лише провайдер ІІТ"))
    try:
        raw = base64.b64decode(receipt or "", validate=True)
    except ValueError:
        frappe.throw(_("Квитанція має бути в base64"))
    changed = apply_receipts(row, [provider.read_receipt(setting, row, raw)])
    return {"applied": bool(changed), "status": frappe.db.get_value(SIGNED, name, "status")}


# ---------------------------------------------------------------- the key of the signer (provider ІІТ)


def _iit_setting(organization):
    """The setting of an organization with the provider ІІТ; only managers (the key is a secret)."""
    frappe.only_for(MANAGERS)
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    setting = get_setting(organization)
    if setting.provider != IIT:
        frappe.throw(_("Ключ КЕП завантажують лише для провайдера ІІТ"))
    provider_of(setting)
    return setting


def eusign_status():
    """Is the library installed? (for the settings form)"""
    check_roles()
    info = eusign.version_info()
    return {"available": info["available"], "version": info.get("version") or ""}


def _certificate_summary(provider, key, org_edrpou):
    cert = key.cert
    valid_to = (cert["valid_to"] or "")[:10]
    days = (getdate(valid_to) - getdate(today())).days if valid_to else None
    return {
        "ok": True,
        "owner": cert["subject_cn"],
        "organization": cert["org"],
        "edrpou": cert["edrpou"] or cert["drfo"],
        "issuer": cert["issuer_cn"],
        "serial": cert["serial"],
        "valid_from": (cert["valid_from"] or "")[:10],
        "valid_to": valid_to,
        "days_left": days,
        "algorithm": {1: "ДСТУ 4145-2002", 2: "RSA"}.get(cert["public_key_type"], "ECDSA"),
        "edrpou_match": bool((cert["edrpou"] or cert["drfo"]) and (cert["edrpou"] or cert["drfo"]) == (org_edrpou or "")),
        "trusted_ca": provider.trusted(cert["issuer_cn"]),
    }


def refresh_certificate(setting):
    """Copy the data of the certificate of the stored key into the setting (the signer, ЄДРПОУ, validity)."""
    provider = IITProvider()
    with provider.open_key(setting) as key:
        summary = _certificate_summary(provider, key, "")
    values = {"certificate_holder": summary["owner"], "certificate_edrpou": summary["edrpou"],
              "certificate_valid_from": summary["valid_from"], "certificate_valid_to": summary["valid_to"],
              "certificate_issuer": summary["issuer"]}
    frappe.db.set_value(SETTING, setting.name, values, update_modified=False)
    setting.update(values)
    return summary


def check_key(organization):
    """«Перевірити ключ»: open the stored key and show who owns the certificate and how long it is valid.
    Never returns the key or the password."""
    setting = _iit_setting(organization)
    org_edrpou = frappe.db.get_value("UA Organization", organization, "edrpou")
    try:
        summary = refresh_certificate(setting)
    except frappe.ValidationError as exc:
        return {"ok": False, "error": frappe.as_unicode(exc.args[0]) if exc.args else str(exc)}
    summary["edrpou_match"] = bool(summary["edrpou"] and summary["edrpou"] == (org_edrpou or ""))
    if not summary["trusted_ca"]:
        summary.update(ok=False, error=_("ЦСК «{0}» не входить до списку акредитованих ЦСК").format(summary["issuer"]))
    elif not summary["edrpou_match"]:
        summary.update(ok=False, error=_("Сертифікат виданий іншій особі (код {0}), а організація має ЄДРПОУ {1}").format(
            summary["edrpou"] or "—", org_edrpou or "—"))
    return summary


def upload_key(organization, filename, key, password, certificate=None):
    """Save the key file (base64) and its password. The key is opened first: a wrong password, an expired
    certificate or a CA that is not trusted is refused and nothing is stored."""
    setting = _iit_setting(organization)
    try:
        blob = base64.b64decode(key or "", validate=True)
    except ValueError:
        frappe.throw(_("Файл ключа має бути переданий у base64"))
    if not blob or len(blob) > MAX_KEY_SIZE:
        frappe.throw(_("Файл ключа порожній або завеликий"))
    provider = IITProvider()
    provider.prepare(setting)
    org_edrpou = frappe.db.get_value("UA Organization", organization, "edrpou") or ""
    try:
        leaf = eusign.pkcs12_leaf_certificate(blob, password)
        if not leaf and certificate:
            leaf = base64.b64decode(certificate)
        if leaf:
            eusign.save_signer_certificate(leaf)
        with eusign.open_key(blob, password) as opened:
            summary = _certificate_summary(provider, opened, org_edrpou)
    except (eusign.EUSignError, ValueError) as exc:
        frappe.throw(_("Ключ КЕП не прийнято: {0}").format(exc))
    if not summary["trusted_ca"]:
        frappe.throw(_("ЦСК «{0}» не входить до списку акредитованих ЦСК").format(summary["issuer"]))
    if not summary["edrpou_match"]:
        frappe.throw(_("Ключ належить іншій особі (код {0}), а організація має ЄДРПОУ {1}").format(
            summary["edrpou"] or "—", org_edrpou or "—"))
    setting.key_data = key
    setting.key_password = password
    setting.key_file_name = os.path.basename(filename or "key")[:140]
    setting.save()
    refresh_certificate(frappe.get_doc(SETTING, organization))
    return check_key(organization)


def remove_key(organization):
    setting = _iit_setting(organization)
    for field in ("key_data", "key_password"):
        remove_encrypted_password(SETTING, setting.name, field)
        setting.set(field, "")
    setting.key_file_name = ""
    setting.certificate_holder = ""
    setting.certificate_edrpou = ""
    setting.certificate_issuer = ""
    setting.certificate_valid_from = None
    setting.certificate_valid_to = None
    setting.save()
    return {"removed": True}


# ---------------------------------------------------------------- received ПН


def test_queue_inbound(organization, counterparty, posting_date, base, vat, number):
    """Sandbox only: queue one received ПН for import_received_invoices."""
    check_roles()
    setting = get_setting(organization)
    if setting.provider != TEST_PROVIDER:
        frappe.throw(_("Тестова черга доступна лише для тестового провайдера"))
    check_provider_allowed(setting)
    row = frappe.get_doc(
        {
            "doctype": INBOUND,
            "organization": organization,
            "counterparty": counterparty,
            "posting_date": posting_date,
            "number": str(number),
            "base_amount": flt(base, 2),
            "vat_amount": flt(vat, 2),
        }
    )
    row.insert(ignore_permissions=True)
    return row.name


def import_received_invoices(organization, date_from, date_to):
    """Draft received ПН for the invoices the provider holds for the period. Already imported ones are skipped."""
    check_roles()
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    setting = get_setting(organization)
    provider_of(setting)
    if setting.provider != TEST_PROVIDER:
        frappe.throw(_("Завантаження отриманих ПН для цього провайдера не підключено"))
    created = []
    for name in frappe.get_all(
        INBOUND,
        filters={"organization": organization, "posting_date": ("between", [getdate(date_from), getdate(date_to)]),
                 "imported_as": ("is", "not set")},
        pluck="name",
        order_by="posting_date, creation",
    ):
        inbound = frappe.get_doc(INBOUND, name)
        rate = frappe.db.get_value("UA VAT Rate", {"rate": flt(inbound.vat_amount / inbound.base_amount * 100, 0)
                                                  if inbound.base_amount else 0}, "name")
        pn = frappe.get_doc(
            {
                "doctype": tax.PN,
                "organization": organization,
                "posting_date": inbound.posting_date,
                "direction": tax.RECEIVED,
                "invoice_kind": tax.KIND_ORDINARY,
                "number": inbound.number,
                "counterparty": inbound.counterparty,
                "lines": [{
                    "description": _("Податкова накладна №{0} з ЄРПН").format(inbound.number),
                    "quantity": 1,
                    "price": inbound.base_amount,
                    "vat_rate": rate,
                    "base_amount": inbound.base_amount,
                    "vat_amount": inbound.vat_amount,
                }],
            }
        )
        pn.insert()
        frappe.db.set_value(INBOUND, name, "imported_as", pn.name)
        created.append(pn.name)
    return created
