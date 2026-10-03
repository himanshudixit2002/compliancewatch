"""Request-scoped dependencies: the caller and the wiring.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. Eval runs are platform
data, so no route takes a tenant. With a token, ``Admin`` (starting a run, which spends compute
and, under the nightly profile, model budget) is a user with the admin role, and ``Operator``
(reading runs) a user with a regulatory role: analyst, reviewer or admin. Anyone else is a 403
``auth-forbidden``. Without a token (``header`` mode, or ``dual`` mode without one) every route
works as before tokens existed.
"""

from typing import Annotated

from fastapi import Depends, Request

from domain_kernel.access import REGULATORY_ROLES, Principal, Role
from eval_service.wiring import Wiring
from py_common.auth.fastapi import require_roles


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Wired = Annotated[Wiring, Depends(wiring)]
Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]
Operator = Annotated[Principal, Depends(require_roles(REGULATORY_ROLES))]
