"""Inputs, drafts and editor revisions for one saved application."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


QuestionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
QuestionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ConfirmedFact = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class AnswerQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: QuestionId
    text: QuestionText
    max_characters: int | None = Field(default=None, gt=0, le=8000)
    max_words: int | None = Field(default=None, gt=0, le=1500)
    notes: str = Field(default="", max_length=2000)
    confirmed_facts: tuple[ConfirmedFact, ...] = Field(default=(), max_length=12, strict=False)
    manual_only: bool = False


class PublicAnswerSource(BaseModel):
    """Manually supplied public company material. No URL fetch is implied."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    url: str = Field(min_length=1, max_length=2048)
    snippet: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(character.isspace() for character in value)):
            raise ValueError("Enter a public HTTP or HTTPS page URL without credentials.")
        return value


class AnswerEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    question_id: QuestionId
    text: str = Field(max_length=8000)


class AnswerSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    job_id: str
    revision: str | None = None
    questions: list[AnswerQuestion] = Field(default_factory=list, max_length=12)
    edits: list[AnswerEdit] = Field(default_factory=list, max_length=12)
    public_sources: list[PublicAnswerSource] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scoped_edits(self):
        question_ids = {question.id for question in self.questions}
        if len(question_ids) != len(self.questions):
            raise ValueError("Question IDs must be unique.")
        edit_ids = {edit.question_id for edit in self.edits}
        if len(edit_ids) != len(self.edits) or edit_ids - question_ids:
            raise ValueError("Each answer edit must match a distinct question in this revision.")
        return self


class AnswerEvidence(BaseModel):
    id: str
    source: Literal["saved_profile", "current_profile", "posting", "confirmed_fact", "company_public"]
    text: str
    question_id: str | None = None
    url: str | None = None
    used_in: tuple[Literal["cv", "cover_letter"], ...] = ()


class ProviderAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    question_id: QuestionId
    text: str = Field(max_length=8000)
    evidence_ids: list[str] = Field(max_length=16)
    missing_facts: list[ConfirmedFact] = Field(max_length=12)


class AnswerDraft(BaseModel):
    question_id: str
    status: Literal["drafted", "needs_facts", "over_limit", "manual", "invalid", "unavailable"]
    text: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    characters: int = 0
    words: int = 0
    limits_met: bool | None = None
    message: str = ""


class AnswerUsage(BaseModel):
    provider: str
    requested_model: str
    reported_model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_source: Literal["reported", "estimated"]


class AnswerBatch(BaseModel):
    profile_id: str
    job_id: str
    drafts: list[AnswerDraft]
    evidence: list[AnswerEvidence]
    warnings: list[str]
    usage: AnswerUsage | None = None


# Close the response objects for strict models. Gemini's dialect conversion removes
# the closure keyword. Validate each answer independently against ProviderAnswer.
_STRING = {"type": "string"}
_ANSWER_PROPERTIES = {
    "question_id": _STRING,
    "text": _STRING,
    "evidence_ids": {"type": "array", "items": _STRING},
    "missing_facts": {"type": "array", "items": _STRING},
}
ANSWER_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": _ANSWER_PROPERTIES,
                "required": list(_ANSWER_PROPERTIES),
                "additionalProperties": False,
            },
        },
    },
    "required": ["answers"],
    "additionalProperties": False,
}
