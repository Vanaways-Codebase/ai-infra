import os
from typing import Optional

from ringcentral import SDK

from app.core.config import settings


_platform = None


def get_platform():
    """Singleton RingCentral Platform authenticated via JWT."""
    global _platform
    if _platform is not None:
        return _platform

    server_url = os.getenv("RINGCENTRAL_SERVER_URL", "https://platform.ringcentral.com")
    rcsdk = SDK(settings.RINGCENTRAL_CLIENT_ID, settings.RINGCENTRAL_CLIENT_SECRET, server_url)
    platform = rcsdk.platform()
    platform.login(jwt=settings.RINGCENTRAL_JWT)
    _platform = platform
    return _platform

