"""Risk classification for Elara's browser actions.

Same philosophy as shell_guard: defence in depth, not a sandbox. Two tiers —
typing into credential/payment fields is HARD-refused (the user does that part
themselves, always), while purchase-shaped clicks are held for a spoken
confirmation like risky PowerShell is.
"""

from __future__ import annotations

import re

# Field attributes that mean "never type here". Matched against the joined
# name/id/placeholder/label blob of the target element.
_SENSITIVE_FIELD = re.compile(
    r"password|passwd|cvv|cvc|card.?number|cardnum|expir|ssn|"
    r"social.?security|otp|one.?time|passcode|\bpin\b|secret|routing|iban",
    re.I,
)

# Accessible names of controls that commit money or an order.
_PURCHASE = re.compile(
    r"buy now|place (your )?order|confirm (purchase|order|payment)|submit order|"
    r"pay now|order now|complete (purchase|order|payment)|proceed to checkout|checkout",
    re.I,
)


def classify_field(attrs: dict) -> str | None:
    """A reason to refuse typing into this element, or None if it's ordinary.

    `attrs` holds whatever we could read off the element: type, autocomplete,
    name, id, placeholder, label.
    """
    if str(attrs.get("type", "")).lower() == "password":
        return "a password field"
    autocomplete = str(attrs.get("autocomplete", "")).lower()
    if autocomplete.startswith("cc-") or autocomplete in (
        "current-password",
        "new-password",
        "one-time-code",
    ):
        return "a credential or payment field"
    blob = " ".join(
        str(attrs.get(k, "")) for k in ("name", "id", "placeholder", "label")
    )
    if _SENSITIVE_FIELD.search(blob):
        return "a sensitive field (credentials or payment details)"
    return None


def classify_click(label: str) -> str | None:
    """A reason this click needs confirmation first, or None."""
    if label and _PURCHASE.search(label):
        return "looks like a purchase or checkout action"
    return None
