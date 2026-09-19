from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


SectionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=200)
    evidence_ids: list[str] = Field(min_length=1, max_length=4)
    kind: Literal["observation", "hypothesis"]

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim text must not be blank")
        return value.strip()

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence IDs must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique within a claim")
        return value


class AnalysisOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=400)
    claims: list[Claim] = Field(max_length=4)
    uncertainties: list[SectionText] = Field(max_length=3)
    next_steps: list[SectionText] = Field(max_length=3)

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value.strip()

    @field_validator("uncertainties", "next_steps")
    @classmethod
    def list_items_must_not_be_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("list items must not be blank")
        return [item.strip() for item in value]


class ModelInfo(StrictModel):
    id: str
    runtime_version: str | None = None
    text_supported: bool = True
    vision_supported: bool | None = None


class Completion(StrictModel):
    text: str
    finish_reason: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    first_token_ms: float | None = None
    elapsed_ms: float | None = None


def analysis_output_schema() -> dict:
    """Return a llama.cpp-friendly schema without external references."""
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1, "maxLength": 400},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 200},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                            "maxItems": 4,
                        },
                        "kind": {
                            "type": "string",
                            "enum": ["observation", "hypothesis"],
                        },
                    },
                    "required": ["text", "evidence_ids", "kind"],
                    "additionalProperties": False,
                },
                "maxItems": 4,
            },
            "uncertainties": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
                "maxItems": 3,
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
                "maxItems": 3,
            },
        },
        "required": ["summary", "claims", "uncertainties", "next_steps"],
        "additionalProperties": False,
    }
