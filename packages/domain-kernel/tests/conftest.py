"""Hypothesis profiles and the shared test ontology.

``ci`` (the default) is deterministic and skips the example database; ``dev`` runs fewer
examples. Select with ``HYPOTHESIS_PROFILE=dev``. The ontology fixture is session-scoped so
``@given`` tests can use it.
"""

import os
from collections.abc import Mapping

import pytest
from hypothesis import settings

from domain_kernel.ontology import Ontology

settings.register_profile(
    "ci", derandomize=True, database=None, max_examples=200, deadline=None, print_blob=True
)
settings.register_profile("dev", database=None, max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

ONTOLOGY_MAPPING: Mapping[str, object] = {
    "version": "0.0.1",
    "attributes": [
        {
            "key": "registration_type",
            "type": "enum",
            "source": "gstin_lookup",
            "since": "0.0.1",
            "definition": "Kind of GST registration the business holds.",
            "allowed_values": ["regular", "composition", "unregistered"],
            "example": "regular",
        },
        {
            "key": "turnover_band",
            "type": "ordered_enum",
            "source": "user_input",
            "since": "0.0.1",
            "definition": "Aggregate turnover band of the previous financial year.",
            "allowed_values": ["under_20l", "20l_to_1_5cr", "1_5cr_to_5cr", "over_5cr"],
            "example": "20l_to_1_5cr",
        },
        {
            "key": "state_codes",
            "type": "enum_set",
            "source": "gstin_lookup",
            "since": "0.0.1",
            "definition": "States in which the business is registered.",
            "allowed_values": ["KA", "MH", "DL", "TN"],
            "example": ["KA"],
        },
        {
            "key": "e_commerce_supplier",
            "type": "boolean",
            "source": "user_input",
            "since": "0.0.1",
            "definition": "True when the business sells through an e-commerce operator.",
            "example": False,
        },
        {
            "key": "employee_count",
            "type": "integer",
            "source": "user_input",
            "since": "0.0.1",
            "definition": "People on the payroll.",
            "min": 0,
            "example": 12,
        },
        {
            "key": "annual_turnover_inr",
            "type": "decimal",
            "source": "user_input",
            "since": "0.0.1",
            "definition": "Aggregate turnover of the previous financial year in rupees.",
            "min": 0,
            "example": "1500000.50",
        },
        {
            "key": "registered_on",
            "type": "date",
            "source": "gstin_lookup",
            "since": "0.0.1",
            "definition": "Date the registration took effect.",
            "example": "2019-07-01",
        },
        {
            "key": "trade_name",
            "type": "string",
            "source": "gstin_lookup",
            "since": "0.0.1",
            "definition": "Trade name on the registration certificate.",
            "example": "Acme Traders",
        },
    ],
}


@pytest.fixture(scope="session")
def ontology() -> Ontology:
    return Ontology.from_mapping(ONTOLOGY_MAPPING)
