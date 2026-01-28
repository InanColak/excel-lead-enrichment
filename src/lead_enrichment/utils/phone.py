"""Phone number classification utilities.

Maps API-specific phone type values to our German-language column names:
- Handynummer = mobile phone
- Festnetz/Durchwahl = landline / direct dial
"""

from __future__ import annotations

from ..models import ApolloPhoneNumber, LushaPhoneNumber

# Apollo type_cd values that map to mobile
_APOLLO_MOBILE_TYPES = {"mobile"}
# Apollo type_cd values that map to direct dial / landline
_APOLLO_DIRECT_TYPES = {"work_direct", "direct_dial", "work_hq", "other"}

# Apollo confidence ranking (higher is better)
_APOLLO_CONFIDENCE_RANK = {
    "very_high": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def classify_apollo_phones(
    phone_numbers: list[ApolloPhoneNumber],
) -> dict[str, str | None]:
    """Extract the best mobile and direct-dial numbers from Apollo phone data.

    Returns {"mobile": "...", "direct_dial": "..."} with None for missing types.
    """
    mobile: str | None = None
    direct: str | None = None
    best_mobile_conf = -1
    best_direct_conf = -1

    for phone in phone_numbers:
        number = phone.sanitized_number or phone.raw_number
        if not number:
            continue

        conf = _APOLLO_CONFIDENCE_RANK.get(phone.confidence_cd or "", 0)
        type_cd = (phone.type_cd or "").lower()

        if type_cd in _APOLLO_MOBILE_TYPES and conf > best_mobile_conf:
            mobile = number
            best_mobile_conf = conf
        elif type_cd in _APOLLO_DIRECT_TYPES and conf > best_direct_conf:
            direct = number
            best_direct_conf = conf

    return {"mobile": mobile, "direct_dial": direct}


def classify_lusha_phones(
    phone_numbers: list[LushaPhoneNumber],
) -> dict[str, str | None]:
    """Extract mobile and direct-dial numbers from Lusha phone data.

    Respects the doNotCall flag — DNC-flagged numbers are skipped.
    Returns {"mobile": "...", "direct_dial": "..."} with None for missing types.
    """
    mobile: str | None = None
    direct: str | None = None

    for phone in phone_numbers:
        if phone.do_not_call:
            continue
        ptype = (phone.phone_type or "").lower()
        if ptype == "mobile" and not mobile:
            mobile = phone.phone
        elif ptype in ("directdial", "landline") and not direct:
            direct = phone.phone

    return {"mobile": mobile, "direct_dial": direct}
