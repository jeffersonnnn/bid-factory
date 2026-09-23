from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal['eligibility', 'technical', 'management', 'staffing', 'key_personnel',
    'past_performance', 'pricing', 'certification', 'form', 'attachment', 'formatting',
    'page_limit', 'deadline', 'submission', 'amendment', 'signature', 'representation', 'administrative', 'other']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CompanyInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    profile: dict[str, str] = Field(default_factory=dict)


class BidInput(Strict):
    company_id: str
    title: str = Field(min_length=2, max_length=180)


class RequirementInput(Strict):
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=2, max_length=12000)
    text: str = Field(min_length=2, max_length=2000)
    kind: Kind
    scope: Literal['submission', 'performance'] = 'submission'
    mandatory: bool = True
    key: str = Field(min_length=1, max_length=160)
    constraints: dict = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0, le=1)
    evaluation_factor: str = Field(default='', max_length=300)
    component: str = Field(default='technical_volume', max_length=120)
    supersedes: str | None = None
    supersession_reason: str = Field(default='', max_length=1000)


class EvidenceInput(Strict):
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=2, max_length=12000)
    kind: Kind = 'other'
    fact_key: str = Field(default='', max_length=160)


class ReviewInput(Strict):
    reviewer: str = Field(min_length=2, max_length=120)
    reason: str = Field(min_length=8, max_length=4000)
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    expected_revision: int | None = Field(default=None, ge=0)


class EvidenceReview(ReviewInput):
    approved: bool
    expires_at: str | None = None


class MappingInput(ReviewInput):
    evidence_ids: list[str] = Field(max_length=100)
    approved: bool = True


class AnswerInput(Strict):
    requirement_id: str
    text: str = Field(min_length=2, max_length=10000)
    customer_name: str = Field(min_length=2, max_length=120)
    fact_key: str = Field(default='', max_length=160)
    supersedes: str | None = None
    confirmed: Literal[True]
    attachment_document_id: str | None = None


class ControlsInput(ReviewInput):
    deadline: str
    deadline_requirement_id: str
    page_limit: int = Field(ge=1, le=30)
    page_limit_requirement_id: str | None = None
    submission_method: str = Field(min_length=5, max_length=1000)
    submission_requirement_id: str
    scope_confirmed: Literal[True]
    package_complete: Literal[True]

    @field_validator('deadline')
    @classmethod
    def aware_deadline(cls, value):
        from datetime import datetime
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Include a time zone offset in the deadline.')
        return dt.isoformat()


class AuditInput(ReviewInput):
    mode: Literal['human', 'ai'] = 'human'
    independent_review_complete: Literal[True]
    findings: list[str] = Field(default_factory=list, max_length=100)


class ExportInput(Strict):
    final: bool = False
