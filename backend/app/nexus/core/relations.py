"""Typed ontology relation contracts shared by importer, validator and optimizer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


MultiplicityBound = int | Literal["many", "unknown"]
MinimumBound = Literal[0, 1, "unknown"]


class RelationEnd(BaseModel):
    entity: str
    attributes: list[str]

    @model_validator(mode="before")
    @classmethod
    def normalize_attribute(cls, value: Any):
        if isinstance(value, dict) and "attributes" not in value and "attribute" in value:
            value = dict(value)
            attr = value.pop("attribute")
            value["attributes"] = attr if isinstance(attr, list) else [attr]
        return value


class Multiplicity(BaseModel):
    min: MinimumBound
    max: MultiplicityBound


class RelationMultiplicity(BaseModel):
    from_to: Multiplicity
    to_from: Multiplicity


class RelationIntegrity(BaseModel):
    mode: Literal["ENFORCED", "DECLARED", "INFERRED", "UNKNOWN"]
    source: str | None = None
    constraint_name: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class TemporalRelation(BaseModel):
    fact_time: str
    valid_from: str
    valid_to: str


class RelationContract(BaseModel):
    id: str
    name: str
    from_: RelationEnd = Field(alias="from", serialization_alias="from")
    to: RelationEnd
    multiplicity: RelationMultiplicity
    integrity: RelationIntegrity
    temporal: TemporalRelation | None = None
    semantics: str | None = None
    synonyms: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def cardinality_label(self) -> str:
        left = "1" if self.multiplicity.to_from.max == 1 else "N" if self.multiplicity.to_from.max == "many" else "?"
        right = "1" if self.multiplicity.from_to.max == 1 else "N" if self.multiplicity.from_to.max == "many" else "?"
        return f"{left}:{right}"
