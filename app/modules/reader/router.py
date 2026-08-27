"""Re-export of reader router for unified module access."""
from app.reader.router import (
    pair_device_handler,
    refresh_token_handler,
    revoke_device_handler,
    register_reader_routes
)

__all__ = [
    "pair_device_handler",
    "refresh_token_handler",
    "revoke_device_handler",
    "register_reader_routes",
]
