"""Browser action risk classification — pure pattern tests."""

from backend.tools.browser_guard import classify_click, classify_field


def test_password_field_refused():
    assert classify_field({"type": "password"}) is not None


def test_payment_autocomplete_refused():
    assert classify_field({"autocomplete": "cc-number"}) is not None
    assert classify_field({"autocomplete": "current-password"}) is not None
    assert classify_field({"autocomplete": "one-time-code"}) is not None


def test_sensitive_names_refused():
    assert classify_field({"name": "card_number"}) is not None
    assert classify_field({"id": "cvv"}) is not None
    assert classify_field({"placeholder": "Enter your PIN"}) is not None
    assert classify_field({"label": "Social Security Number"}) is not None


def test_ordinary_fields_allowed():
    assert classify_field({"type": "text", "name": "q", "placeholder": "Search"}) is None
    assert classify_field({"type": "email", "name": "newsletter_email"}) is None
    # "pin" only matches as a whole word — pinned/shopping are fine
    assert classify_field({"name": "pinned_items"}) is None


def test_purchase_clicks_need_confirmation():
    assert classify_click("Buy Now") is not None
    assert classify_click("Place your order") is not None
    assert classify_click("Proceed to checkout") is not None
    assert classify_click("Pay now") is not None


def test_ordinary_clicks_allowed():
    assert classify_click("Add to Cart") is None  # reversible — cart isn't a purchase
    assert classify_click("Next page") is None
    assert classify_click("Customer reviews") is None
    assert classify_click("") is None
