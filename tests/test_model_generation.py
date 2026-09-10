from datetime import UTC, datetime

from openngs.model import Facet, Specimen

SPECIMEN_ID = "018f5b2a-0000-7000-8000-000000000000"


def test_entity_round_trips() -> None:
    specimen = Specimen(
        internal_id=SPECIMEN_ID,
        name="openngs://acme-genomics/core-lab/specimen/SPEC-001",
        xrefs=["biosample:SAMN12345678"],
        valid_time=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
    )
    dumped = specimen.model_dump_json()
    assert Specimen.model_validate_json(dumped) == specimen


def test_facet_producer_and_schema_url_serialize_with_leading_underscore() -> None:
    # No core facet ships by default - exercise the abstract Facet base
    # directly, since _producer/_schemaURL aliasing is a property of every facet,
    # concrete or not.
    facet = Facet(
        attached_to=SPECIMEN_ID,
        **{
            "_producer": "acme-lims/2.3",
            "_schemaURL": "https://acme.example/schema/facets/custom-facet/v1",
        },
    )
    payload = facet.model_dump(by_alias=True)
    assert payload["_producer"] == "acme-lims/2.3"
    assert payload["_schemaURL"] == "https://acme.example/schema/facets/custom-facet/v1"
    assert Facet.model_validate(payload) == facet
