"""Тонка обгортка над бібліотекою ІІТ EUSignCP (euscp.so) через ctypes.

The library is optional: nothing here runs at import time. `available()` tells if the .so is installed;
every other call raises EUSignError with a clear text when it is not. Only the "context" API of the
library is used, so a key read for one request never leaks to another one.

Where the files are (see ua_accounting/scripts/install_eusign.sh and docs/regulatory-update-process.md):
    <home>/lib/euscp.so (+ the other .so files of the SDK)   the library
    <home>/ca/CACertificates.p7b, CAs.json                    certificates and addresses of accredited CAs (КНЕДП)
    <home>/data/                                              settings (osplm.ini) and the certificate store, written by us
<home> is the environment variable UA_EUSIGN_HOME or the site config key ua_eusign_home
(default /home/frappe/data/eusign).

Sources: Закон «Про електронні довірчі послуги» (КЕП), ДСТУ ETSI TS 101 733 (CAdES), документація ІІТ
«Бібліотека підпису (ОС Linux/UNIX, інтерфейс програмування - C++)».
"""

import ctypes as C
import hashlib
import json
import os
import shutil
import threading

DEFAULT_HOME = "/home/frappe/data/eusign"
LIB_NAME = "euscp.so"
LANG_UK = 1

# dwSignAlgo of the context API
SIGN_DSTU4145 = 1
SIGN_RSA = 2
SIGN_ECDSA = 3

# EU_SIGN_TYPE_*: the level of the CAdES signature
CADES_BES, CADES_T, CADES_C, CADES_X_LONG = 1, 4, 8, 16
SIGN_LEVELS = {"CAdES-BES": CADES_BES, "CAdES-T": CADES_T, "CAdES-X Long": CADES_X_LONG}

_LOCK = threading.RLock()
_STATE = {"lib": None, "home": None}


class EUSignError(Exception):
    """An error of the library or of its installation. `code` is the code of the library (0 = not the library)."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- structures of the library (Linux x64)


class SYSTEMTIME(C.Structure):
    _fields_ = [(n, C.c_ushort) for n in ("year", "month", "dow", "day", "hour", "minute", "second", "ms")]

    def iso(self):
        if not self.year:
            return None
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}:{self.second:02d}"


_SUBJECT_FIELDS = [
    "Issuer", "IssuerCN", "Serial", "Subject", "SubjCN", "SubjOrg", "SubjOrgUnit", "SubjTitle", "SubjState",
    "SubjLocality", "SubjFullName", "SubjAddress", "SubjPhone", "SubjEMail", "SubjDNS", "SubjEDRPOUCode", "SubjDRFOCode",
]


class OwnerInfo(C.Structure):  # EU_CERT_OWNER_INFO
    _pack_ = 4  # the library packs its structures by 4 bytes
    _fields_ = [("bFilled", C.c_int)] + [("psz" + n, C.c_char_p) for n in _SUBJECT_FIELDS]


class SignInfo(C.Structure):  # EU_SIGN_INFO
    _pack_ = 4
    _fields_ = OwnerInfo._fields_ + [("bTimeAvail", C.c_int), ("bTimeStamp", C.c_int), ("Time", SYSTEMTIME)]


class CertInfoEx(C.Structure):  # EU_CERT_INFO_EX
    _pack_ = 4
    _fields_ = (
        [("bFilled", C.c_int), ("dwVersion", C.c_ulong)]
        + [("psz" + n, C.c_char_p) for n in _SUBJECT_FIELDS]
        + [("pszSubjNBUCode", C.c_char_p), ("pszSubjSPFMCode", C.c_char_p), ("pszSubjOCode", C.c_char_p),
           ("pszSubjOUCode", C.c_char_p), ("pszSubjUserCode", C.c_char_p),
           ("stCertBeginTime", SYSTEMTIME), ("stCertEndTime", SYSTEMTIME), ("bPrivKeyTimes", C.c_int),
           ("stPrivKeyBeginTime", SYSTEMTIME), ("stPrivKeyEndTime", SYSTEMTIME), ("dwPublicKeyBits", C.c_ulong),
           ("pszPublicKey", C.c_char_p), ("pszPublicKeyID", C.c_char_p), ("pszIssuerPublicKeyID", C.c_char_p),
           ("pszKeyUsage", C.c_char_p), ("pszExtKeyUsages", C.c_char_p), ("pszPolicies", C.c_char_p),
           ("pszCRLDistribPoint1", C.c_char_p), ("pszCRLDistribPoint2", C.c_char_p), ("bPowerCert", C.c_int),
           ("bSubjType", C.c_int), ("bSubjCA", C.c_int), ("iChainLength", C.c_int), ("pszUPN", C.c_char_p),
           ("dwPublicKeyType", C.c_ulong), ("dwKeyUsage", C.c_ulong), ("pszRSAModul", C.c_char_p),
           ("pszRSAExponent", C.c_char_p), ("pszOCSPAccessInfo", C.c_char_p), ("pszIssuerAccessInfo", C.c_char_p),
           ("pszTSPAccessInfo", C.c_char_p), ("bLimitValueAvailable", C.c_int), ("dwLimitValue", C.c_ulong),
           ("pszLimitValueCurrency", C.c_char_p), ("dwSubjType", C.c_ulong), ("dwSubjSubType", C.c_ulong),
           ("pszSubjUNZR", C.c_char_p), ("pszSubjCountry", C.c_char_p), ("pszFingerprint", C.c_char_p)]
    )


# ---------------------------------------------------------------- installation


def home_dir():
    if _STATE["home"]:
        return _STATE["home"]
    path = os.environ.get("UA_EUSIGN_HOME")
    if not path:
        try:
            import frappe

            path = frappe.conf.get("ua_eusign_home")
        except Exception:
            path = None
    return path or DEFAULT_HOME


def library_path():
    return os.path.join(home_dir(), "lib", LIB_NAME)


def available():
    return os.path.isfile(library_path())


def version_info():
    """What is installed (for the settings form and the docs). Never raises."""
    info = {"available": available(), "home": home_dir()}
    marker = os.path.join(home_dir(), "VERSION")
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8") as fh:
            info["version"] = fh.read().strip()
    return info


def accredited_cas():
    """CAs.json of the SDK: accredited CAs (КНЕДП) with the addresses of their OCSP / TSP / CMP servers."""
    path = os.path.join(home_dir(), "ca", "CAs.json")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def accredited_issuer_names():
    names = set()
    for ca in accredited_cas():
        names.update(ca.get("issuerCNs") or [])
    return names


def _lib():
    """The loaded and initialized library (once per process)."""
    with _LOCK:
        if _STATE["lib"] is not None:
            return _STATE["lib"]
        path = library_path()
        if not os.path.isfile(path):
            raise EUSignError(
                "Бібліотеку ІІТ EUSignCP не встановлено (файл {0}). Виконайте scripts/install_eusign.sh, "
                "див. docs/regulatory-update-process.md".format(path)
            )
        data_dir = os.path.join(home_dir(), "data")
        _prepare_data_dir(data_dir)
        lib = C.CDLL(path)
        lib.EUGetErrorLangDesc.restype = C.c_char_p
        lib.EUGetErrorLangDesc.argtypes = [C.c_ulong, C.c_ulong]
        for name in ("EUCtxCreate",):
            getattr(lib, name).argtypes = [C.POINTER(C.c_void_p)]
        lib.EUCtxFree.argtypes = [C.c_void_p]
        lib.EUCtxFreePrivateKey.argtypes = [C.c_void_p]
        lib.EUCtxFreeMemory.argtypes = [C.c_void_p, C.c_void_p]
        lib.EUSetUIMode(0)
        _check(lib, lib.EUSetSettingsFilePath(data_dir.encode()))
        _check(lib, lib.EUInitialize())
        _STATE["lib"] = lib
        _load_accredited_cas(lib)
        return lib


def _prepare_data_dir(data_dir):
    certs = os.path.join(data_dir, "certs")
    os.makedirs(certs, exist_ok=True)
    template = os.path.join(home_dir(), "lib", "osplm.ini")
    target = os.path.join(data_dir, "osplm.ini")
    if os.path.isfile(template) and not os.path.isfile(target):
        with open(template, encoding="utf-8") as fh:
            text = fh.read()
        with open(target, "w", encoding="utf-8") as fh:
            text = text.replace("Path=/data/certificates", "Path=" + certs)
            # only the certificates we save ourselves are trusted: the ones met in keys and signatures are not stored
            text = text.replace("SaveLoadedCerts=1", "SaveLoadedCerts=0")
            fh.write(text)
    os.chmod(data_dir, 0o700)


def _load_accredited_cas(lib):
    """Put the certificates of the accredited CAs into the store once (the file is large; a marker keeps its hash)."""
    p7b = os.path.join(home_dir(), "ca", "CACertificates.p7b")
    if not os.path.isfile(p7b):
        return
    with open(p7b, "rb") as fh:
        blob = fh.read()
    marker = os.path.join(home_dir(), "data", "cas.sha256")
    digest = hashlib.sha256(blob).hexdigest()
    if os.path.isfile(marker) and open(marker).read().strip() == digest:
        return
    _check(lib, lib.EUSaveCertificates(blob, len(blob)))
    with open(marker, "w") as fh:
        fh.write(digest)


def _check(lib, code):
    if code:
        text = lib.EUGetErrorLangDesc(code, LANG_UK)
        raise EUSignError((text or b"").decode("cp1251", "replace") or f"Помилка бібліотеки ІІТ {code}", code)


# ---------------------------------------------------------------- helpers


def _text(value):
    return value.decode("cp1251", "replace") if value else ""


def _owner_dict(info):
    return {
        "issuer": _text(info.pszIssuer), "issuer_cn": _text(info.pszIssuerCN), "serial": _text(info.pszSerial),
        "subject": _text(info.pszSubject), "subject_cn": _text(info.pszSubjCN), "org": _text(info.pszSubjOrg),
        "full_name": _text(info.pszSubjFullName), "edrpou": _text(info.pszSubjEDRPOUCode),
        "drfo": _text(info.pszSubjDRFOCode), "title": _text(info.pszSubjTitle),
    }


def _cert_dict(info):
    out = _owner_dict(info)
    out.update(
        valid_from=info.stCertBeginTime.iso(), valid_to=info.stCertEndTime.iso(),
        key_usage=_text(info.pszKeyUsage), fingerprint=_text(info.pszFingerprint),
        public_key_type=int(info.dwPublicKeyType), is_ca=bool(info.bSubjCA),
    )
    return out


def sign_algo_of(public_key_type):
    # EU_CERT_KEY_TYPE_*: 1 = DSTU 4145, 2 = RSA; other types (ECDSA) use the algorithm of the key itself
    return {1: SIGN_DSTU4145, 2: SIGN_RSA}.get(int(public_key_type), SIGN_ECDSA)


def _certificates_of(blob):
    """(list of x509 certificates) from DER, PEM or P7B bytes."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs7

    for loader in (x509.load_pem_x509_certificates, pkcs7.load_der_pkcs7_certificates, pkcs7.load_pem_pkcs7_certificates):
        try:
            return list(loader(blob))
        except Exception:
            continue
    try:
        return [x509.load_der_x509_certificate(blob)]
    except Exception:
        raise EUSignError("Файл не містить сертифіката (потрібен DER, PEM або P7B)")


def _is_ca(cert):
    from cryptography import x509

    try:
        return bool(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
    except Exception:
        return False


def _save(certs):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    blob = pkcs7.serialize_certificates(certs, serialization.Encoding.DER)
    lib = _lib()
    _check(lib, lib.EUSaveCertificates(blob, len(blob)))


def save_signer_certificate(blob):
    """Put the certificate of a signer (not of a CA) into the store. Certificates of CAs are refused here:
    trusted CAs come only from the SDK list or from add_test_ca()."""
    with _LOCK:
        certs = _certificates_of(blob)
        if any(_is_ca(c) for c in certs):
            raise EUSignError("Це сертифікат ЦСК, а потрібен сертифікат підписувача")
        _save(certs)


def add_test_ca(blob):
    """Trust a test CA (for a test site only). Returns its common name."""
    from cryptography.x509.oid import NameOID

    with _LOCK:
        certs = _certificates_of(blob)
        if not certs or not all(_is_ca(c) for c in certs):
            raise EUSignError("Потрібен сертифікат ЦСК")
        _save(certs)
        return [c.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value for c in certs]


def pkcs12_leaf_certificate(blob, password):
    """DER of the signer certificate inside a PKCS#12 file, or None when the file is not PKCS#12."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    try:
        _key, cert, _more = pkcs12.load_key_and_certificates(blob, (password or "").encode("utf-8"))
    except Exception:
        return None
    return cert.public_bytes(serialization.Encoding.DER) if cert is not None else None


def ca_of_issuer(issuer_cn):
    """The entry of CAs.json for an issuer name, or None."""
    for ca in accredited_cas():
        if issuer_cn in (ca.get("issuerCNs") or []):
            return ca
    return None


def configure(issuer_cn, offline):
    """Set how the library talks to the servers of the CA of the signer.
    Online: OCSP (status of the certificate) and TSP (time stamp) of this CA from CAs.json.
    Offline: no requests at all; only for a test CA that has no servers."""
    with _LOCK:
        lib = _lib()
        if not offline and not issuer_cn:
            _check(lib, lib.EUSetModeSettings(0))
            return
        if offline:
            _check(lib, lib.EUSetModeSettings(1))
            _check(lib, lib.EUSetTSPSettings(0, b"", b""))
            _check(lib, lib.EUSetOCSPSettings(0, 0, b"", b""))
            return
        ca = ca_of_issuer(issuer_cn)
        if not ca:
            raise EUSignError("ЦСК «{0}» немає в списку акредитованих ЦСК (CAs.json)".format(issuer_cn))
        _check(lib, lib.EUSetModeSettings(0))
        _check(lib, lib.EUSetOCSPSettings(1, 0, ca["ocspAccessPointAddress"].encode(), str(ca.get("ocspAccessPointPort", "80")).encode()))
        _check(lib, lib.EUSetTSPSettings(1, ca["tspAddress"].encode(), str(ca.get("tspAddressPort", "80")).encode()))


def _runtime_param(lib, name, value):
    raw = C.c_int(value)
    _check(lib, lib.EUSetRuntimeParameter(name.encode(), C.byref(raw), 4))


class Key:
    """A private key read into a context. Use as a context manager; the memory is freed on exit."""

    def __init__(self, lib, ctx, pk, owner, cert, cert_der):
        self._lib, self.ctx, self.pk = lib, ctx, pk
        self.owner, self.cert, self.cert_der = owner, cert, cert_der

    def close(self):
        if self.pk:
            self._lib.EUCtxFreePrivateKey(self.pk)
            self.pk = None
        if self.ctx:
            self._lib.EUCtxFree(self.ctx)
            self.ctx = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_key(key_bytes, password):
    """Read a key file (Key-6.dat, .pfx, .p12, .jks, .pk8) with its password. Returns a Key."""
    with _LOCK:
        lib = _lib()
        ctx = C.c_void_p()
        _check(lib, lib.EUCtxCreate(C.byref(ctx)))
        pk = C.c_void_p()
        owner = OwnerInfo()
        try:
            _check(lib, lib.EUCtxReadPrivateKeyBinary(ctx, key_bytes, len(key_bytes), (password or "").encode("utf-8"),
                                                      C.byref(pk), C.byref(owner)))
            owner_d = _owner_dict(owner)
            lib.EUCtxFreeCertOwnerInfo(ctx, C.byref(owner))
            info = C.POINTER(CertInfoEx)()
            der = C.POINTER(C.c_ubyte)()
            size = C.c_ulong()
            _check(lib, lib.EUCtxGetOwnCertificate(pk, 0, 1, C.byref(info), C.byref(der), C.byref(size)))
            cert_d = _cert_dict(info.contents)
            cert_der = bytes(der[: size.value])
            lib.EUCtxFreeCertificateInfoEx(ctx, info)
            lib.EUCtxFreeMemory(ctx, der)
        except Exception:
            if pk:
                lib.EUCtxFreePrivateKey(pk)
            lib.EUCtxFree(ctx)
            raise
        return Key(lib, ctx, pk, owner_d, cert_d, cert_der)


# ---------------------------------------------------------------- sign and verify


def sign(key, data, level="CAdES-BES", timestamp=False):
    """CAdES signature with the data inside (the form ДПС accepts) and the certificate of the signer. Bytes."""
    with _LOCK:
        lib = key._lib
        _runtime_param(lib, "SignType", SIGN_LEVELS.get(level, CADES_BES))
        _runtime_param(lib, "SignIncludeContentTimeStamp", 1 if timestamp else 0)
        out = C.POINTER(C.c_ubyte)()
        size = C.c_ulong()
        algo = sign_algo_of(key.cert.get("public_key_type"))
        _check(lib, lib.EUCtxSignData(key.pk, algo, data, len(data), 0, 1, C.byref(out), C.byref(size)))
        result = bytes(out[: size.value])
        lib.EUCtxFreeMemory(key.ctx, out)
        return result


def verify(signature):
    """Verify a signature with the data inside and the chain of the signer certificate.
    Returns (data, signer dict). Raises EUSignError when the signature or the chain is not valid."""
    with _LOCK:
        lib = _lib()
        ctx = C.c_void_p()
        _check(lib, lib.EUCtxCreate(C.byref(ctx)))
        try:
            info = SignInfo()
            out = C.POINTER(C.c_ubyte)()
            size = C.c_ulong()
            _check(lib, lib.EUCtxVerifyDataInternal(ctx, 0, signature, len(signature), C.byref(out), C.byref(size), C.byref(info)))
            data = bytes(out[: size.value])
            lib.EUCtxFreeMemory(ctx, out)
            signer = _owner_dict(info)
            signer["time"] = info.Time.iso() if info.bTimeAvail else None
            lib.EUCtxFreeSignInfo(ctx, C.byref(info))
            return data, signer
        finally:
            lib.EUCtxFree(ctx)


def envelop(key, recipient_certificate_der, data, sign=True):
    """Encrypt data to the certificate of the recipient (the ДПС certificate), signed by our key. Bytes.
    Uses the documented EUCtxEnvelopData (DSTU 28147 + key agreement), so the recipient needs a DSTU 4145 certificate."""
    with _LOCK:
        lib = key._lib
        buf = C.create_string_buffer(recipient_certificate_der, len(recipient_certificate_der))
        certs = (C.POINTER(C.c_ubyte) * 1)(C.cast(buf, C.POINTER(C.c_ubyte)))
        lengths = (C.c_ulong * 1)(len(recipient_certificate_der))
        out = C.POINTER(C.c_ubyte)()
        size = C.c_ulong()
        _check(lib, lib.EUCtxEnvelopData(key.pk, 1, certs, lengths, 1, 1 if sign else 0, 1, data, len(data),
                                         C.byref(out), C.byref(size)))
        result = bytes(out[: size.value])
        lib.EUCtxFreeMemory(key.ctx, out)
        return result


def develop(key, enveloped, sender_certificate_der):
    """Decrypt data that were encrypted to our key. Returns the data."""
    with _LOCK:
        lib = key._lib
        out = C.POINTER(C.c_ubyte)()
        size = C.c_ulong()
        info = C.create_string_buffer(4096)
        _check(lib, lib.EUCtxDevelopData(key.pk, None, enveloped, len(enveloped), sender_certificate_der,
                                         len(sender_certificate_der), C.byref(out), C.byref(size), info))
        result = bytes(out[: size.value])
        lib.EUCtxFreeMemory(key.ctx, out)
        return result


def signer_certificate(signature):
    """Certificate data of the first signer without checking the signature."""
    with _LOCK:
        lib = _lib()
        ctx = C.c_void_p()
        _check(lib, lib.EUCtxCreate(C.byref(ctx)))
        try:
            info = C.POINTER(CertInfoEx)()
            der = C.POINTER(C.c_ubyte)()
            size = C.c_ulong()
            _check(lib, lib.EUCtxGetSignerInfo(ctx, 0, signature, len(signature), C.byref(info), C.byref(der), C.byref(size)))
            out = _cert_dict(info.contents)
            lib.EUCtxFreeCertificateInfoEx(ctx, info)
            lib.EUCtxFreeMemory(ctx, der)
            return out
        finally:
            lib.EUCtxFree(ctx)


def reset_for_tests():
    """Forget the loaded library (a next call loads it again)."""
    with _LOCK:
        lib = _STATE["lib"]
        if lib is not None:
            lib.EUFinalize()
        _STATE["lib"] = None


def wipe_store():
    """Delete the certificate store written by us (not the SDK files)."""
    with _LOCK:
        reset_for_tests()
        shutil.rmtree(os.path.join(home_dir(), "data"), ignore_errors=True)
