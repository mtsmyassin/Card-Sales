"""Type-safe accessors for Supabase API responses."""
from __future__ import annotations
from typing import Any


def rows(response: Any) -> list[dict[str, Any]]:
    """Extract row list from a Supabase APIResponse, with type narrowing.

    Returns empty list if response.data is None or not a list.
    """
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data  # type: ignore[return-value]
    return []


def row0(response: Any) -> dict[str, Any]:
    """Extract the first row from a Supabase APIResponse.

    Handles both .single() responses (data is a dict) and list responses.
    Returns empty dict if no data found.
    """
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data  # type: ignore[return-value]
    if isinstance(data, list) and data:
        return data[0]  # type: ignore[return-value]
    return {}
