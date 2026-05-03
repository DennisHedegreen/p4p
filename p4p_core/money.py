from __future__ import annotations

import re


CURRENCY_CODE_PATTERN = r"^[A-Z]{3}$"
_CURRENCY_CODE_RE = re.compile(CURRENCY_CODE_PATTERN)

ZERO_DECIMAL_CURRENCIES = {
    "BIF",
    "CLP",
    "DJF",
    "GNF",
    "ISK",
    "JPY",
    "KMF",
    "KRW",
    "PYG",
    "RWF",
    "UGX",
    "VND",
    "VUV",
    "XAF",
    "XOF",
    "XPF",
}

THREE_DECIMAL_CURRENCIES = {
    "BHD",
    "IQD",
    "JOD",
    "KWD",
    "LYD",
    "OMR",
    "TND",
}


def normalize_currency_code(value: str) -> str:
    code = value.strip().upper()
    if not _CURRENCY_CODE_RE.fullmatch(code):
        raise ValueError("currency must be a 3-letter uppercase currency code")
    return code


def is_currency_code(value: str) -> bool:
    try:
        normalize_currency_code(value)
    except ValueError:
        return False
    return True


def currency_fraction_digits(currency: str) -> int:
    code = normalize_currency_code(currency)
    if code in ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def minor_units_to_decimal_string(amount: int, currency: str) -> str:
    digits = currency_fraction_digits(currency)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    if digits == 0:
        return f"{sign}{absolute}"
    factor = 10**digits
    whole = absolute // factor
    fraction = absolute % factor
    return f"{sign}{whole}.{fraction:0{digits}d}"


def format_money_minor(amount: int, currency: str) -> str:
    code = normalize_currency_code(currency)
    return f"{minor_units_to_decimal_string(amount, code)} {code}"
