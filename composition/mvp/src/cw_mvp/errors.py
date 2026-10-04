"""The problems the composition root answers itself, before any service sees the request."""

from domain_kernel.errors import DomainError


class RouteNotFoundError(DomainError, LookupError):
    """No route by that method and path is served on this listener: it does not exist, or it is
    served only on the internal listener, or only to admins while ``CW_AUTH_MODE=token``. The
    public listener says the same in every case, so it does not reveal which routes exist."""

    type_slug = "route-not-found"
    title = "Route not found"
