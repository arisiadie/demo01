"""Response models for the unified traceability / archive contract.

Phase-1 of the backend governance refactor: these Pydantic models give the
patient / doctor / admin APIs a single typed contract for the traceability,
archive_summary and review_context structures that were previously returned as
bare dicts.

Design choices:
- Every model sets ``extra="allow"`` so declaring a ``response_model`` documents
  the contract floor (the fields below) WITHOUT silently dropping any extra keys
  the live or persisted builders may attach. This keeps the OpenAPI schema useful
  for the upcoming frontend integration table while guaranteeing zero field loss.
- Most fields are Optional because the live builder (from an in-memory
  AgentResponse) and the persisted builder (rebuilt from DB rows) populate
  overlapping-but-different subsets. The models are the UNION (superset) of both.
- ``execution_timeline`` step ``detail`` is intentionally ``dict[str, Any]``:
  each stage carries a heterogeneous detail payload that is not worth modelling.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReviewContextDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    review_id: int | None = None
    status: str | None = None
    assigned_role: str | None = None
    review_template: str | None = None
    due_by: str | None = None
    review_round: int | None = None
    followup_needed: bool | None = None
    closed_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None


class ArchiveSummaryDTO(BaseModel):
    """Superset of the live and persisted archive_summary payloads."""

    model_config = ConfigDict(extra="allow")

    consultation_id: int | None = None
    archive_version: str | None = None
    patient_external_id: str | None = None
    agent_type: str | None = None
    risk_level: str | None = None
    status: str | None = None
    doctor_review_required: bool | None = None
    doctor_review_id: int | None = None
    review_status: str | None = None
    review_round: int | None = None
    closed_at: str | None = None
    source_count: int | None = None
    retrieval_hit_count: int | None = None
    llm_call_count: int | None = None
    workflow_agent_count: int | None = None
    visited_agents: list[str] = Field(default_factory=list)
    safety_flag_count: int | None = None
    refusal: bool | None = None
    has_image: bool | None = None
    created_at: str | None = None


class TraceabilityWorkflowDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    visited_agents: list[str] = Field(default_factory=list)
    requires_review: bool | None = None
    result_count: int | None = None
    workflow_graph: Any | None = None


class TraceabilityRagDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_count: int | None = None
    source_ids: list[str] = Field(default_factory=list)
    top_sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_categories: list[str] = Field(default_factory=list)
    round_count: int | None = None
    confidence_score: float | None = None
    source_coverage: dict[str, Any] = Field(default_factory=dict)
    source_bindings: list[dict[str, Any]] = Field(default_factory=list)
    # persisted-side additions
    persisted_hit_count: int | None = None
    persisted_top_sources: list[dict[str, Any]] = Field(default_factory=list)
    persisted_source_ids: list[str] = Field(default_factory=list)


class TraceabilityLlmDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_count: int | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    avg_latency_ms: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    calls: list[dict[str, Any]] = Field(default_factory=list)
    # persisted-side additions
    persisted_call_count: int | None = None
    persisted_status_counts: dict[str, int] = Field(default_factory=dict)
    persisted_avg_latency_ms: int | None = None
    persisted_total_tokens: int | None = None
    persisted_estimated_cost: float | None = None


class TraceabilitySafetyDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    risk_level: str | None = None
    refusal: bool | None = None
    safety_flags: list[str] = Field(default_factory=list)
    guard_status: str | None = None
    findings: list[Any] = Field(default_factory=list)
    doctor_review_required: bool | None = None


class TraceabilityPersistenceDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    consultation_table: str | None = None
    agent_run_table: str | None = None
    retrieval_hit_table: str | None = None
    llm_call_table: str | None = None
    doctor_review_table: str | None = None
    structured_output_tables: list[str] = Field(default_factory=list)


class TraceabilityDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    consultation_id: int | None = None
    archive_version: str | None = None
    agent_plan: dict[str, Any] = Field(default_factory=dict)
    workflow: TraceabilityWorkflowDTO | None = None
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)
    # heterogeneous per-step detail -> kept as raw dicts on purpose
    execution_timeline: list[dict[str, Any]] = Field(default_factory=list)
    rag: TraceabilityRagDTO | None = None
    llm: TraceabilityLlmDTO | None = None
    safety: TraceabilitySafetyDTO | None = None
    review: ReviewContextDTO | None = None
    persistence: TraceabilityPersistenceDTO | None = None


class DoctorReviewDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    status: str | None = None
    review_template: str | None = None
    structured_opinion: dict[str, Any] = Field(default_factory=dict)
    risk_assessment: str | None = None
    treatment_decision: str | None = None
    signature: str | None = None
    signature_title: str | None = None
    due_by: str | None = None
    review_round: int | None = None
    followup_needed: bool | None = None
    followup_instruction: str | None = None
    escalation_note: str | None = None
    closed_at: str | None = None
    note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None


class AgentRunDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_type: str | None = None
    agent_name: str | None = None
    risk_level: str | None = None
    refusal: bool | None = None
    safety_flags: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None


class RetrievalHitDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_uid: str | None = None
    title: str | None = None
    category: str | None = None
    source: str | None = None
    score: float | None = None
    rank: int | None = None
    excerpt: str | None = None


class ConsultationCoreDTO(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    patient_external_id: str | None = None
    agent_type: str | None = None
    input_text: str | None = None
    sanitized_input: str | None = None
    summary: str | None = None
    risk_level: str | None = None
    status: str | None = None
    doctor_review_required: bool | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    image_path: str | None = None
    created_at: str | None = None


class ConsultationDetailResponse(BaseModel):
    """Full consultation detail returned by GET /consultations/{id} and the
    doctor consultation report endpoint."""

    model_config = ConfigDict(extra="allow")

    consultation: ConsultationCoreDTO
    patient_profile: dict[str, Any] | None = None
    agent_response: dict[str, Any] = Field(default_factory=dict)
    structured_outputs: dict[str, Any] = Field(default_factory=dict)
    archive_summary: ArchiveSummaryDTO | None = None
    traceability: TraceabilityDTO | None = None
    review_context: ReviewContextDTO | None = None
    review: DoctorReviewDTO | None = None
    agent_run: AgentRunDTO | None = None
    retrieval_hits: list[RetrievalHitDTO] = Field(default_factory=list)
    llm_call: dict[str, Any] | None = None
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    uploads: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str | None = None


class ConsultationTraceItem(BaseModel):
    """One row of GET /admin/consultation-trace."""

    model_config = ConfigDict(extra="allow")

    consultation_id: int | None = None
    patient_external_id: str | None = None
    agent_type: str | None = None
    risk_level: str | None = None
    status: str | None = None
    doctor_review_required: bool | None = None
    summary: str | None = None
    created_at: str | None = None
    archive_summary: ArchiveSummaryDTO | None = None
    traceability: TraceabilityDTO | None = None
    agent_run: AgentRunDTO | None = None
    retrieval_hits: list[RetrievalHitDTO] = Field(default_factory=list)
    llm_call: dict[str, Any] | None = None
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    review: DoctorReviewDTO | None = None


class AuditConsultationItem(BaseModel):
    """One row of GET /admin/audit/consultations."""

    model_config = ConfigDict(extra="allow")

    consultation_id: int | None = None
    agent_type: str | None = None
    risk_level: str | None = None
    doctor_review_required: bool | None = None
    status: str | None = None
    created_at: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class PendingReviewItem(BaseModel):
    """One row of GET /doctor/reviews."""

    model_config = ConfigDict(extra="allow")

    review_id: int | None = None
    consultation_id: int | None = None
    status: str | None = None
    note: str | None = None
    created_at: str | None = None
    agent_type: str | None = None
    risk_level: str | None = None
    summary: str | None = None


class ReviewUpdateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    review_id: int
    status: str
