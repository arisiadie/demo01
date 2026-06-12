from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# Big JSON / free-text payloads (full LLM result, structured outputs, eval
# responses) can exceed MySQL TEXT's 64KB limit with real model output. Use
# LONGTEXT (4GB) on MySQL and fall back to TEXT elsewhere (e.g. SQLite).
LongText = Text().with_variant(LONGTEXT, "mysql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    consultations: Mapped[list["Consultation"]] = relationship(back_populates="user")
    uploaded_files: Mapped[list["UploadedFile"]] = relationship(back_populates="user")
    profile: Mapped["PatientProfile"] = relationship(back_populates="user", uselist=False)
    treatment_records: Mapped[list["TreatmentRecord"]] = relationship(back_populates="user")
    tooth_records: Mapped[list["ToothRecord"]] = relationship(back_populates="user")


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), ForeignKey("users.external_id"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="内测用户")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pregnancy_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    oral_history: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class Consultation(Base):
    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    patient_external_id: Mapped[str] = mapped_column(String(80), index=True)
    agent_type: Mapped[str] = mapped_column(String(40), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    sanitized_input: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(LongText)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    sources_json: Mapped[str] = mapped_column(LongText, default="[]")
    result_json: Mapped[str] = mapped_column(LongText)
    doctor_review_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", index=True)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="consultations")
    review: Mapped["DoctorReview"] = relationship(back_populates="consultation", uselist=False)
    agent_run: Mapped["AgentRun"] = relationship(back_populates="consultation", uselist=False)
    retrieval_hits: Mapped[list["RetrievalHit"]] = relationship(back_populates="consultation")
    uploaded_files: Mapped[list["UploadedFile"]] = relationship(back_populates="consultation")
    health_plans: Mapped[list["HealthPlan"]] = relationship(back_populates="consultation")
    reminders: Mapped[list["FollowUpReminder"]] = relationship(back_populates="consultation")
    triage_report: Mapped["TriageReport"] = relationship(back_populates="consultation", uselist=False)
    medication_check: Mapped["MedicationCheck"] = relationship(back_populates="consultation", uselist=False)
    treatment_comparison: Mapped["TreatmentComparison"] = relationship(back_populates="consultation", uselist=False)


class DoctorReview(Base):
    __tablename__ = "doctor_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True)
    assigned_role: Mapped[str] = mapped_column(String(20), default="doctor")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    review_template: Mapped[str | None] = mapped_column(String(80), nullable=True)
    structured_opinion_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment_decision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    due_by: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_round: Mapped[int] = mapped_column(Integer, default=1)
    followup_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    consultation: Mapped[Consultation] = relationship(back_populates="review")


class TriageReport(Base):
    __tablename__ = "triage_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    tooth_position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pain_character: Mapped[str | None] = mapped_column(String(160), nullable=True)
    triggers_json: Mapped[str] = mapped_column(Text, default="[]")
    accompanying_symptoms_json: Mapped[str] = mapped_column(Text, default="[]")
    suspected_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    urgency_level: Mapped[str] = mapped_column(String(20), default="routine", index=True)
    recommended_department: Mapped[str] = mapped_column(String(80), default="口腔科", index=True)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consultation: Mapped[Consultation] = relationship(back_populates="triage_report")


class MedicationRule(Base):
    __tablename__ = "medication_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    drug_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    category: Mapped[str] = mapped_column(String(80), index=True)
    contraindications_json: Mapped[str] = mapped_column(Text, default="[]")
    interactions_json: Mapped[str] = mapped_column(Text, default="[]")
    special_populations_json: Mapped[str] = mapped_column(Text, default="{}")
    dose_note: Mapped[str] = mapped_column(Text)
    alcohol_warning: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MedicationCheck(Base):
    __tablename__ = "medication_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    checked_drugs_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_points_json: Mapped[str] = mapped_column(Text, default="[]")
    contraindications_json: Mapped[str] = mapped_column(Text, default="[]")
    interactions_json: Mapped[str] = mapped_column(Text, default="[]")
    compliance_summary: Mapped[str] = mapped_column(Text)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consultation: Mapped[Consultation] = relationship(back_populates="medication_check")


class TreatmentOption(Base):
    __tablename__ = "treatment_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    option_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    duration_note: Mapped[str] = mapped_column(Text)
    cost_factors_json: Mapped[str] = mapped_column(Text, default="[]")
    advantages_json: Mapped[str] = mapped_column(Text, default="[]")
    disadvantages_json: Mapped[str] = mapped_column(Text, default="[]")
    alternatives_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TreatmentComparison(Base):
    __tablename__ = "treatment_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    matched_options_json: Mapped[str] = mapped_column(Text, default="[]")
    comparison_json: Mapped[str] = mapped_column(Text, default="[]")
    recommendation_note: Mapped[str] = mapped_column(Text)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    consultation: Mapped[Consultation] = relationship(back_populates="treatment_comparison")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_external_id: Mapped[str] = mapped_column(String(80), index=True)
    actor_role: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="deepseek", index=True)
    model_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    request_preview: Mapped[str] = mapped_column(Text)
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    version: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    document_count: Mapped[int] = mapped_column(Integer)
    retrieval_backend: Mapped[str] = mapped_column(String(40), default="local-hybrid")
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="knowledge_version")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    knowledge_version_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_versions.id"), nullable=True, index=True)
    doc_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(160))
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    content: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    knowledge_version: Mapped[KnowledgeVersion | None] = relationship(back_populates="documents")
    retrieval_hits: Mapped[list["RetrievalHit"]] = relationship(back_populates="knowledge_document")


class KnowledgeChangeLog(Base):
    __tablename__ = "knowledge_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    knowledge_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=True, index=True)
    actor_external_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PatientConsent(Base):
    __tablename__ = "patient_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), ForeignKey("users.external_id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(40), index=True)
    consent_version: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(160))
    consented: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_text: Mapped[str] = mapped_column(Text)
    signature: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship()


class DataAccessRequest(Base):
    __tablename__ = "data_access_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), ForeignKey("users.external_id"), index=True)
    request_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    data_scope: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship()


class PrivacyImpactAssessment(Base):
    __tablename__ = "privacy_impact_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    data_types: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    mitigation_measures: Mapped[str] = mapped_column(Text)
    compliance_status: Mapped[str] = mapped_column(String(30), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataRetentionPolicy(Base):
    __tablename__ = "data_retention_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    data_category: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    retention_days: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_delete: Mapped[bool] = mapped_column(Boolean, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    agent_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_name: Mapped[str] = mapped_column(String(80))
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    refusal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    safety_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    trace_json: Mapped[str] = mapped_column(LongText, default="[]")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    consultation: Mapped[Consultation] = relationship(back_populates="agent_run")


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), index=True)
    knowledge_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=True, index=True)
    document_uid: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(160))
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    excerpt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    consultation: Mapped[Consultation] = relationship(back_populates="retrieval_hits")
    knowledge_document: Mapped[KnowledgeDocument | None] = relationship(back_populates="retrieval_hits")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str] = mapped_column(String(40), default="imaging")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    consultation: Mapped[Consultation | None] = relationship(back_populates="uploaded_files")
    user: Mapped[User] = relationship(back_populates="uploaded_files")


class TreatmentRecord(Base):
    __tablename__ = "treatment_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), index=True)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    tooth_position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    diagnosis_text: Mapped[str] = mapped_column(Text)
    treatment_name: Mapped[str] = mapped_column(String(120), index=True)
    treatment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    doctor_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cost_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_visit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="treatment_records")


class ToothRecord(Base):
    __tablename__ = "tooth_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), index=True)
    tooth_position: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(80), default="观察", index=True)
    diagnosis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    treatment_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintenance_cycle_days: Mapped[int] = mapped_column(Integer, default=180)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="tooth_records")


class HealthPlan(Base):
    __tablename__ = "health_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), index=True)
    plan_type: Mapped[str] = mapped_column(String(40), default="oral_health", index=True)
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    consultation: Mapped[Consultation] = relationship(back_populates="health_plans")


class FollowUpReminder(Base):
    __tablename__ = "follow_up_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"), nullable=True, index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), index=True)
    reminder_type: Mapped[str] = mapped_column(String(40), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    consultation: Mapped[Consultation | None] = relationship(back_populates="reminders")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_external_id: Mapped[str] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="in_app", index=True)
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="unread", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AlertDismissal(Base):
    """Records an admin "dismiss/acknowledge" of a computed alert.

    Alerts are derived on the fly from underlying data (overdue reviews, failed
    LLM calls, etc.) and have no row of their own. To let admins clear handled
    alerts without touching that data, each dismissal is keyed by a stable
    alert_key ("type:resource_type:resource_id") and filtered out when the alert
    payload is rebuilt.
    """

    __tablename__ = "alert_dismissals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dismissed_by: Mapped[str] = mapped_column(String(80), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkflowConfig(Base):
    __tablename__ = "workflow_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    config_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nodes: Mapped[list["WorkflowNode"]] = relationship(back_populates="config")
    edges: Mapped[list["WorkflowEdge"]] = relationship(back_populates="config")


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("workflow_configs.id"), index=True)
    node_id: Mapped[str] = mapped_column(String(80), index=True)
    agent_id: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40), default="agent")
    position_x: Mapped[int] = mapped_column(Integer, default=0)
    position_y: Mapped[int] = mapped_column(Integer, default=0)

    config: Mapped[WorkflowConfig] = relationship(back_populates="nodes")


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("workflow_configs.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(80), index=True)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    config: Mapped[WorkflowConfig] = relationship(back_populates="edges")


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    evaluation_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)
    requested_agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_doc_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_safety_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_structured_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_review_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expected_refusal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    results: Mapped[list["EvaluationResult"]] = relationship(back_populates="case")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", index=True)
    triggered_by: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    rag_hit_rate: Mapped[float] = mapped_column(Float, default=0.0)
    safety_pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    agent_quality_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    summary_json: Mapped[str] = mapped_column(LongText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["EvaluationResult"]] = relationship(back_populates="run")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_db_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    case_db_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_cases.id"), nullable=True, index=True)
    case_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(160))
    evaluation_type: Mapped[str] = mapped_column(String(40), index=True)
    agent_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    failures_json: Mapped[str] = mapped_column(LongText, default="[]")
    response_json: Mapped[str] = mapped_column(LongText, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")
    case: Mapped[EvaluationCase | None] = relationship(back_populates="results")
