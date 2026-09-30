"""Typed exceptions for the database layer, so routers can distinguish
'not found' from a real database/connection error and map each to the
correct HTTP status code instead of collapsing both into a 500.
"""


class NotFoundError(Exception):
    """Raised when a lookup/delete target does not exist."""
