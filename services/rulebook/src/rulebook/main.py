"""Composition root for the rulebook service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from py_common.app import create_app
from rulebook import __version__
from rulebook.api.router import router

SERVICE_NAME = "rulebook"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("rulebook.main:app", host="127.0.0.1", port=8003, reload=True)
