"""The ways a regulator writes a number or a date, so a validator can find a value in a clause.

Indian notifications write "Rs. 2 crore", "two crore rupees", "2,00,00,000", "twenty-first day
of April, 2026", "21.04.2026" and "21st April, 2026" for the same things. The functions here
produce every spelling of a value the validators accept, and ``normalise`` flattens the clause
text (case, whitespace, spaces around hyphens that PDF extraction inserts) before the search.
"""

import re
from collections.abc import Iterable
from datetime import date

_UNITS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)
_ORDINALS = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
    20: "twentieth",
    30: "thirtieth",
}
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_SPACES = re.compile(r"\s+")
_AROUND_HYPHEN = re.compile(r"\s*-\s*")
_DASHES = re.compile("[\u2010-\u2015]")


def normalise(text: str) -> str:
    """Casefolded, single-spaced, ASCII hyphens with no spaces around them, no commas."""
    text = _DASHES.sub("-", text.casefold())
    text = _AROUND_HYPHEN.sub("-", text)
    return _SPACES.sub(" ", text.replace(",", "")).strip()


def words(number: int) -> str:
    """``21`` as ``twenty-one``; numbers up to 99 only (larger ones use lakh and crore)."""
    if number < 20:
        return _UNITS[number]
    tens, unit = divmod(number, 10)
    return _TENS[tens - 2] + (f"-{_UNITS[unit]}" if unit else "")


def ordinal(day: int) -> str:
    """``21`` as ``twenty-first``."""
    if day in _ORDINALS:
        return _ORDINALS[day]
    tens, unit = divmod(day, 10)
    return f"{_TENS[tens - 2]}-{_ORDINALS[unit]}"


def ordinal_suffix(day: int) -> str:
    if day in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def number_forms(value: int) -> frozenset[str]:
    """Every spelling of a rupee amount the validator accepts, normalised."""
    forms = {str(value), _indian(value), _western(value)}
    for scale, name in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand")):
        if value >= scale and value % (scale // 100) == 0:
            quotient = value / scale
            figure = str(int(quotient)) if quotient.is_integer() else f"{quotient:.2f}".rstrip("0")
            forms.add(f"{figure} {name}")
            if quotient.is_integer() and quotient < 100:
                forms.add(f"{words(int(quotient))} {name}")
    if value < 100:
        forms.add(words(value))
    return frozenset(normalise(form) for form in forms)


def small_number_forms(value: int) -> frozenset[str]:
    """A day count or a day of the month: digits, words, and the ordinal spellings."""
    forms = {str(value), words(value)} if value < 100 else {str(value)}
    if 1 <= value <= 31:
        forms.add(ordinal(value))
        forms.add(f"{value}{ordinal_suffix(value)}")
    return frozenset(normalise(form) for form in forms)


def date_forms(value: date) -> frozenset[str]:
    """Every spelling of a date the validator accepts, normalised."""
    day, month, year = value.day, _MONTHS[value.month - 1], value.year
    suffix = ordinal_suffix(day)
    forms = {
        value.isoformat(),
        f"{day:02d}.{value.month:02d}.{year}",
        f"{day:02d}/{value.month:02d}/{year}",
        f"{day:02d}-{value.month:02d}-{year}",
        f"{day}.{value.month}.{year}",
        f"{day}/{value.month}/{year}",
        f"{day}{suffix} {month} {year}",
        f"{day}{suffix} {month}, {year}",
        f"{day} {month} {year}",
        f"{day} {month}, {year}",
        f"{month} {day}, {year}",
        f"{month} {day}{suffix}, {year}",
        f"{day}{suffix} day of {month} {year}",
        f"{day}{suffix} day of {month}, {year}",
        f"{ordinal(day)} day of {month} {year}",
        f"{ordinal(day)} day of {month}, {year}",
        f"{ordinal(day)} {month} {year}",
        f"{ordinal(day)} {month}, {year}",
    }
    return frozenset(normalise(form) for form in forms)


def text_has(text: str, forms: Iterable[str]) -> bool:
    """True when any of the (already normalised) forms appears in the normalised text."""
    haystack = normalise(text)
    return any(form in haystack for form in forms)


def _indian(value: int) -> str:
    digits = str(value)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def _western(value: int) -> str:
    return f"{value:,}"
