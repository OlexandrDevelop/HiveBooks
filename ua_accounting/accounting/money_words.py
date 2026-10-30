"""Ukrainian words for hryvnia amounts on primary document forms."""

from frappe.utils import flt

ONES = ("", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять")
TEENS = ("десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять")
TENS = ("", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят", "вісімдесят", "дев'яносто")
HUNDREDS = ("", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот", "дев'ятсот")


def _form(value, forms):
    if value % 100 in range(11, 15):
        return forms[2]
    return forms[{1: 0, 2: 1, 3: 1, 4: 1}.get(value % 10, 2)]


def _group(value, feminine=False):
    parts = []
    if value // 100:
        parts.append(HUNDREDS[value // 100])
    rest = value % 100
    if 10 <= rest < 20:
        parts.append(TEENS[rest - 10])
    else:
        if rest // 10:
            parts.append(TENS[rest // 10])
        one = rest % 10
        if one:
            parts.append(ONES[one] if feminine else ("один" if one == 1 else "два" if one == 2 else ONES[one]))
    return parts


def ua_money_words(amount):
    cents = round(flt(amount) * 100)
    whole, coins = divmod(cents, 100)
    parts = []
    if whole >= 1000:
        thousands = whole // 1000
        parts += _group(thousands, True)
        parts.append(_form(thousands, ("тисяча", "тисячі", "тисяч")))
    parts += _group(whole % 1000, True) if whole else ["нуль"]
    parts.append(_form(whole, ("гривня", "гривні", "гривень")))
    parts += [f"{coins:02d}", _form(coins, ("копійка", "копійки", "копійок"))]
    return " ".join(parts)
