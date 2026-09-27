"""Composition root for the qa service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from py_common.app import create_app
from qa import __version__
from qa.api.router import router

SERVICE_NAME = "qa"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("qa.main:app", host="127.0.0.1", port=8007, reload=True)
