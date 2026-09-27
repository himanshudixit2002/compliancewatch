"""Composition root for the obligation service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from obligation import __version__
from obligation.api.router import router
from py_common.app import create_app

SERVICE_NAME = "obligation"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("obligation.main:app", host="127.0.0.1", port=8005, reload=True)
