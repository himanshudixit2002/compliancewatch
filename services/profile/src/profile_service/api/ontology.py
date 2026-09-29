"""``GET /v1/ontology``: the attributes a profile holds, worded for people, and the operators a
rule may use on each type. Part of the public API (tag ``public``).

The ontology and its wording are the same for every tenant and change only with a release, so
the answer carries an ``ETag`` (the SHA-256 of the body) and may be cached for an hour; a client
that sends the ETag back in ``If-None-Match`` gets a 304 without a body. The wording is a draft
until an analyst has reviewed it, which ``review_status`` says.
"""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel, Field

from domain_kernel.ontology import ALLOWED_OPERATORS, AttributeDefinition, Ontology, OntologyWording
from domain_kernel.operators import Operator
from profile_service.api.business_schemas import OptionOut, bound, options_of
from profile_service.api.deps import PUBLIC_ROUTE, Wired
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/ontology", tags=["public", "ontology"])

CACHE_CONTROL: Final = "max-age=3600"
NOT_MODIFIED: Final[dict[int | str, dict[str, Any]]] = {
    304: {"description": "Not Modified: the ETag in If-None-Match is still current; no body"}
}


class OntologyAttributeOut(BaseModel):
    key: str
    type: str
    level: str = Field(description="entity, registration or location: the node holding the value")
    source: str = Field(description="gstin_lookup, user_input or derived")
    per_financial_year: bool
    definition: str = Field(description="What the attribute means; the ontology's own words")
    question: str = Field(description="How onboarding asks for it; empty for a derived one")
    help: str
    values: list[OptionOut] = Field(description="Allowed values with their labels, in order")
    min: int | float | None = None
    max: int | float | None = None
    example: Any = None

    @classmethod
    def of(
        cls, definition: AttributeDefinition, wording: OntologyWording
    ) -> "OntologyAttributeOut":
        worded = wording.for_key(definition.key)
        return cls(
            key=definition.key,
            type=definition.type.value,
            level=definition.level.value,
            source=definition.source.value,
            per_financial_year=definition.per_financial_year,
            definition=definition.definition,
            question="" if worded is None else worded.question,
            help="" if worded is None else worded.help,
            values=options_of(definition, wording),
            min=bound(definition.minimum),
            max=bound(definition.maximum),
            example=_plain(definition.example),
        )


class OntologyOut(BaseModel):
    version: str = Field(description="The attribute set's version, which rules are written against")
    wording_version: str
    language: str
    review_status: str = Field(description="needs_review until an analyst has read the wording")
    operators_by_type: dict[str, list[str]] = Field(
        description="The operators a rule predicate may use on each attribute type"
    )
    attributes: list[OntologyAttributeOut]

    @classmethod
    def of(cls, ontology: Ontology, wording: OntologyWording) -> "OntologyOut":
        return cls(
            version=ontology.version,
            wording_version=wording.version,
            language=wording.language,
            review_status=wording.review_status.value,
            operators_by_type={
                kind.value: [operator.value for operator in Operator if operator in allowed]
                for kind, allowed in ALLOWED_OPERATORS.items()
            },
            attributes=[OntologyAttributeOut.of(definition, wording) for definition in ontology],
        )


def _plain(value: object) -> object:
    """An example in canonical form as JSON carries it: sets sorted, dates and decimals text."""
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, date | Decimal):
        return str(value)
    return value


def _matches(if_none_match: str | None, etag: str) -> bool:
    if if_none_match is None:
        return False
    tags = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return etag in tags or "*" in tags


@router.get(
    "",
    summary="The profile attributes with their questions, labelled values and rule operators",
    response_model=OntologyOut,
    responses={**NOT_MODIFIED, **problem_responses(500)},
    openapi_extra=PUBLIC_ROUTE,
)
def read_ontology(
    wired: Wired,
    if_none_match: Annotated[
        str | None,
        Header(max_length=1024, description="The ETag of a copy the client holds"),
    ] = None,
) -> Response:
    content = OntologyOut.of(wired.ontology, wired.wording).model_dump_json().encode("utf-8")
    etag = f'"{hashlib.sha256(content).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content, media_type="application/json", headers=headers)
