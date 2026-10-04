"""The composition root (ADR-013): every service in one deployable.

``cw-mvp serve`` runs the app process, one FastAPI app per service behind one ASGI dispatcher,
answering on a public and an internal listener. ``cw-mvp worker`` runs the worker process, every
service's worker components in one event loop.
"""

__version__ = "0.1.0"
