"""REWE package bootstrap patches for resilient location selection."""
from __future__ import annotations

import re

from . import scraper as _scraper


def _editable_postcode_input(scope):
    """Return only a visible, editable postcode field.

    REWE currently renders a visible readonly postcode summary input before the
    actual location editor opens. Treating that summary as the form field makes
    Playwright wait 30s in Locator.fill(). We deliberately skip readonly/disabled
    fields so the existing location loop can click "Standort ändern" and retry.
    """
    selectors = [
        'input[autocomplete="postal-code"]',
        'input[inputmode="numeric"]',
        'input[placeholder*="Postleitzahl" i]',
        'input[placeholder*="PLZ" i]',
        'input[name*="postal" i]',
        'input[name*="postcode" i]',
        'input[name*="zip" i]',
        'input[id*="postal" i]',
        'input[id*="postcode" i]',
    ]

    candidates = []
    try:
        labelled = scope.get_by_label(re.compile(r"Postleitzahl|PLZ", re.I)).first
        if labelled.count():
            candidates.append(labelled)
    except Exception:
        pass

    for selector in selectors:
        try:
            locator = scope.locator(selector).first
            if locator.count():
                candidates.append(locator)
        except Exception:
            pass

    for locator in candidates:
        try:
            if not locator.is_visible():
                continue
            if locator.get_attribute("readonly") is not None:
                continue
            if locator.get_attribute("disabled") is not None:
                continue
            if not locator.is_editable(timeout=500):
                continue
            return locator
        except Exception:
            continue
    return None


_scraper._visible_postcode_input = _editable_postcode_input
