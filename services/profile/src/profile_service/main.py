"""Composition root for the profile service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from profile_service import __version__
from profile_service.api.router import router
from py_common.app import create_app

SERVICE_NAME = "profile"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("profile_service.main:app", host="127.0.0.1", port=8002, reload=True)
