"""Composition root for the llm-gateway service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from llm_gateway import __version__
from llm_gateway.api.router import router
from py_common.app import create_app

SERVICE_NAME = "llm-gateway"

app = create_app(service_name=SERVICE_NAME, version=__version__, routers=[router])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("llm_gateway.main:app", host="127.0.0.1", port=8008, reload=True)
