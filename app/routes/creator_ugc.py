"""app/routes/creator_ugc.py
Alias / proxy for app.routers.creator_ugc to ensure backwards compatibility.
"""

from app.routers.creator_ugc import (
    router,
    handle_generate_ugc,
    aiohttp_generate_ugc_handler,
    aiohttp_options_ugc_handler,
    register_creator_ugc_routes,
)

__all__ = [
    "router",
    "handle_generate_ugc",
    "aiohttp_generate_ugc_handler",
    "aiohttp_options_ugc_handler",
    "register_creator_ugc_routes",
]