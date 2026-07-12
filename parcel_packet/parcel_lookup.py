from __future__ import annotations

import re


STREET_SUFFIXES = {
    "ALY",
    "ALLEY",
    "AVE",
    "AVENUE",
    "BLVD",
    "BOULEVARD",
    "CIR",
    "CIRCLE",
    "CT",
    "COURT",
    "DR",
    "DRIVE",
    "HWY",
    "HIGHWAY",
    "LN",
    "LANE",
    "PKWY",
    "PARKWAY",
    "PL",
    "PLACE",
    "RD",
    "ROAD",
    "ST",
    "STREET",
    "TER",
    "TERRACE",
    "WAY",
}

ADDRESS_STOP_WORDS = {
    "APT",
    "APARTMENT",
    "BLDG",
    "BUILDING",
    "DE",
    "DELAWARE",
    "FLOOR",
    "STE",
    "SUITE",
    "UNIT",
    "WILMINGTON",
    "NEWARK",
    "MIDDLETOWN",
    "BEAR",
    "NEW",
    "CASTLE",
}


def parcel_key(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())


def split_parcel_inputs(value: str) -> tuple[str, ...]:
    if parse_address(value)[1]:
        return ()
    parts = [part.strip() for part in re.split(r"[,;\s]+", value or "") if part.strip()]
    parcel_parts = [part for part in parts if _looks_like_parcel_part(part)]
    if parts and len(parcel_parts) == len(parts):
        return tuple(dict.fromkeys(parcel_key(part) for part in parts if parcel_key(part)))
    single_key = parcel_key(value or "")
    if _looks_like_parcel_key(single_key):
        return (single_key,)
    return ()


def parcel_where(parcel_search_value: str) -> str:
    escaped = sql_quote(parcel_search_value)
    return " OR ".join(
        (
            f"PARCELNO='{escaped}'",
            f"PRCLID='{escaped}'",
            f"SHORTPRCL='{escaped}'",
        )
    )


def address_where(value: str) -> str | None:
    house_number, street_name = parse_address(value)
    if not house_number or not street_name:
        return None
    house_number = sql_quote(house_number)
    street_name = sql_quote(street_name)
    return f"STNO='{house_number}' AND UPPER(STNAME)='{street_name}'"


def fallback_address_where(value: str) -> str | None:
    house_number, street_name = parse_address(value)
    if not house_number or not street_name:
        return None
    house_number = sql_quote(house_number)
    street_name = sql_quote(street_name)
    return f"STNO='{house_number}' AND UPPER(ADDRESS) LIKE '%{street_name}%'"


def parse_address(value: str) -> tuple[str, str]:
    cleaned = re.sub(r"[^A-Za-z0-9\s#-]", " ", value or "").upper()
    tokens = [token for token in cleaned.split() if token]
    number_index = next((index for index, token in enumerate(tokens) if re.fullmatch(r"\d+[A-Z]?", token)), None)
    if number_index is None:
        return "", ""

    house_number = tokens[number_index]
    street_tokens: list[str] = []
    for token in tokens[number_index + 1 :]:
        if token in STREET_SUFFIXES:
            break
        if token in ADDRESS_STOP_WORDS:
            break
        if token.startswith("#"):
            break
        if re.fullmatch(r"\d{5}(?:-\d{4})?", token):
            break
        street_tokens.append(token)

    while street_tokens and street_tokens[0] in {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}:
        street_tokens.pop(0)
    while street_tokens and street_tokens[-1] in {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}:
        street_tokens.pop()

    street_name = " ".join(street_tokens)
    if not any(ch.isalpha() for ch in street_name):
        return "", ""
    return house_number, street_name


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


def _looks_like_parcel_part(value: str) -> bool:
    key = parcel_key(value)
    return _looks_like_parcel_key(key) and not re.search(r"[A-Za-z]{3,}", value)


def _looks_like_parcel_key(key: str) -> bool:
    return bool(re.fullmatch(r"\d{6,20}", key or ""))
