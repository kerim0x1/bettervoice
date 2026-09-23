"""Errors that carry a short, user-facing message for the overlay."""


class SttError(Exception):
    """Recognition failed; `message` is shown to the user (German, short)."""

    def __init__(self, message, detail=None):
        super().__init__(f"{message} ({detail})" if detail else message)
        self.message = message


class MissingKey(SttError):
    pass


class AuthError(SttError):
    """The provider rejected the API key."""
