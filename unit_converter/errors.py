"""Shared exception type for the unit_converter package."""


class ConvertError(ValueError):
    """Raised when a unit or category is unknown to the requested converter."""
