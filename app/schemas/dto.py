from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Role = Literal["patient", "doctor", "admin"]
AgentType = Literal["triage", "treatment", "medication", "imaging", "health"]


class LoginRequest(BaseModel):
    external_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    external_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)
    role: Role = "patient"
    display_name: str | None = Field(default=None, max_length=80)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    external_id: str
    role: Role
    display_name: str


class PatientProfileInput(BaseModel):
    name: str | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str | None = None
    pregnancy_status: str | None = None
    allergies: str | None = None
    conditions: str | None = None
    oral_history: str | None = None


class ConsultationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    requested_agent: AgentType | None = None
    patient_profile: PatientProfileInput | None = None


class SourceDTO(BaseModel):
    id: str
    title: str
    category: str
    source: str
    score: float
    excerpt: str


class AgentResponse(BaseModel):
    consultation_id: int | None = None
    agent_type: AgentType
    agent_name: str
    summary: str
    evidence: list[str]
    risk_tips: list[str]
    next_steps: list[str]
    doctor_review_required: bool
    risk_level: Literal["low", "medium", "high"]
    refusal: bool = False
    disclaimer: str
    sources: list[SourceDTO]
    agent_trace: list[str]
    safety_flags: list[str]
    llm_meta: dict[str, Any] | None = None
    structured_data: dict[str, Any] | None = None


class ConsultationHistoryItem(BaseModel):
    id: int
    agent_type: str
    summary: str
    risk_level: str
    doctor_review_required: bool
    status: str
    created_at: str
    sources: list[dict[str, Any]]


class ReviewUpdate(BaseModel):
    status: Literal["approved", "needs_followup", "rejected", "returned_for_info"]
    note: str = Field(default="", max_length=1200)
    review_template: str | None = Field(default=None, max_length=80)
    risk_assessment: str | None = Field(default=None, max_length=1200)
    treatment_decision: str | None = Field(default=None, max_length=80)
    signature: str | None = Field(default=None, max_length=80)
    signature_title: str | None = Field(default=None, max_length=120)
    followup_instruction: str | None = Field(default=None, max_length=1200)
    escalation_note: str | None = Field(default=None, max_length=1200)
    structured_opinion: dict[str, Any] | None = None


class ReviewTemplateItem(BaseModel):
    template_id: str
    name: str
    applicable_agents: list[str]
    fields: list[dict[str, Any]]


REVIEW_TEMPLATES: list[ReviewTemplateItem] = [
    ReviewTemplateItem(
        template_id="triage_acute",
        name="急性症状预问诊复核",
        applicable_agents=["triage"],
        fields=[
            {"key": "symptom_severity", "label": "症状严重程度", "type": "select", "options": ["紧急", "尽快", "常规"]},
            {"key": "department_match", "label": "科室匹配度", "type": "select", "options": ["匹配", "基本匹配", "需调整"]},
            {"key": "additional_checks", "label": "建议补充检查", "type": "text"},
        ],
    ),
    ReviewTemplateItem(
        template_id="medication_audit",
        name="用药合规复核",
        applicable_agents=["medication"],
        fields=[
            {"key": "allergy_confirmed", "label": "过敏史确认", "type": "select", "options": ["已确认", "待确认", "无过敏"]},
            {"key": "dose_approved", "label": "剂量合规", "type": "select", "options": ["合规", "需调整", "禁忌"]},
            {"key": "interactions_clear", "label": "相互作用排查", "type": "select", "options": ["无风险", "需关注", "禁忌联用"]},
        ],
    ),
    ReviewTemplateItem(
        template_id="treatment_plan",
        name="治疗方案复核",
        applicable_agents=["treatment"],
        fields=[
            {"key": "indication", "label": "适应证评估", "type": "select", "options": ["明确", "基本明确", "需进一步检查"]},
            {"key": "risk_benefit", "label": "风险收益比", "type": "select", "options": ["收益大风险小", "收益风险相当", "风险大于收益"]},
            {"key": "alternative_offered", "label": "替代方案是否充分", "type": "select", "options": ["充分", "基本充分", "需补充"]},
        ],
    ),
    ReviewTemplateItem(
        template_id="imaging_interpret",
        name="影像解读复核",
        applicable_agents=["imaging"],
        fields=[
            {"key": "report_complete", "label": "报告完整性", "type": "select", "options": ["完整", "基本完整", "需补充影像原片"]},
            {"key": "interpret_accuracy", "label": "解读准确性", "type": "select", "options": ["准确", "基本准确", "需修正"]},
        ],
    ),
]


def template_for_agent(agent_type: str) -> ReviewTemplateItem | None:
    for tpl in REVIEW_TEMPLATES:
        if agent_type in tpl.applicable_agents:
            return tpl
    return None


class KnowledgeDocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=160)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1, max_length=12000)
    active: bool = True


class TreatmentRecordInput(BaseModel):
    consultation_id: int | None = None
    tooth_position: str | None = Field(default=None, max_length=80)
    diagnosis_text: str = Field(min_length=1, max_length=2000)
    treatment_name: str = Field(min_length=1, max_length=120)
    treatment_date: str | None = None
    doctor_name: str | None = Field(default=None, max_length=80)
    institution: str | None = Field(default=None, max_length=160)
    cost_amount: float | None = Field(default=None, ge=0)
    next_visit_at: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ReminderInput(BaseModel):
    consultation_id: int | None = None
    reminder_type: str = Field(default="routine_follow_up", max_length=40)
    due_at: str | None = None
    note: str = Field(min_length=1, max_length=1200)


class ToothRecordInput(BaseModel):
    tooth_position: str = Field(min_length=1, max_length=40)
    status: str = Field(default="观察", max_length=80)
    diagnosis_text: str | None = Field(default=None, max_length=2000)
    treatment_summary: str | None = Field(default=None, max_length=2000)
    maintenance_cycle_days: int = Field(default=180, ge=30, le=720)
    next_check_at: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ConsentInput(BaseModel):
    consent_type: str = Field(default="ai_medical_assist", max_length=40)
    consent_version: str = Field(default="v1.0", max_length=40)
    scope: str = Field(default="AI辅助咨询、RAG检索、医生复核、历史归档", max_length=160)
    consent_text: str = Field(min_length=1, max_length=4000)
    signature: str | None = Field(default=None, max_length=80)
    expires_at: str | None = None


class DataAccessRequestInput(BaseModel):
    request_type: Literal["export", "delete"] = "export"
    data_scope: str = Field(default="profile,consultations,consents", max_length=200)
    reason: str | None = Field(default=None, max_length=1200)


class PrivacyImpactAssessmentInput(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    data_types: str = Field(min_length=1, max_length=2000)
    risk_level: Literal["low", "medium", "high"] = "medium"
    mitigation_measures: str = Field(min_length=1, max_length=4000)


class DataRetentionPolicyInput(BaseModel):
    data_category: str = Field(min_length=1, max_length=80)
    retention_days: int = Field(ge=1, le=36500)
    description: str | None = Field(default=None, max_length=2000)
    auto_delete: bool = True
    archived: bool = False
