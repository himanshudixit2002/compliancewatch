"""Composition root for the notification service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from notification import __version__
from notification.api.router import router
from py_common.app import create_app

SERVICE_NAME = "notification"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("notification.main:app", host="127.0.0.1", port=8006, reload=True)
