from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, UploadFile
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.agents.contracts import contract_from_agent_response
from app.agents.orchestrator import AgentContext, OralAgentOrchestrator, max_risk
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.entities import (
    AgentRun,
    AuditLog,
    Consultation,
    DataAccessRequest,
    DataRetentionPolicy,
    DoctorReview,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    FollowUpReminder,
    HealthPlan,
    KnowledgeDocument,
    KnowledgeChangeLog,
    KnowledgeVersion,
    LLMCallLog,
    MedicationCheck,
    Notification,
    PatientConsent,
    PatientProfile,
    PrivacyImpactAssessment,
    RetrievalHit,
    TreatmentComparison,
    TreatmentRecord,
    ToothRecord,
    TriageReport,
    UploadedFile,
    User,
)
from app.rag.store import KnowledgeDocument as StoreKnowledgeDocument
from app.rag.store import KnowledgeStore
from app.schemas.dto import (
    AgentResponse,
    ConsultationHistoryItem,
    ConsultationRequest,
    ConsentInput,
    DataAccessRequestInput,
    DataRetentionPolicyInput,
    KnowledgeDocumentInput,
    LoginRequest,
    LoginResponse,
    PatientProfileInput,
    PrivacyImpactAssessmentInput,
    RegisterRequest,
    ReminderInput,
    ReviewUpdate,
    SourceDTO,
    TreatmentRecordInput,
    ToothRecordInput,
    template_for_agent,
)
from app.schemas.contracts import (
    AuditConsultationItem,
    ConsultationDetailResponse,
    ConsultationTraceItem,
    PendingReviewItem,
    ReviewUpdateResponse,
)
from app.services.audit import write_audit_log
from app.services.auth import CurrentUser, authenticate_user, create_access_token, hash_password, require_role
from app.services.security import DISCLAIMER, assess_message, mask_sensitive_data

# Contract & traceability serialization moved to app/services/traceability.py
# (phase-1 contract consolidation). Re-imported here so existing call sites and
# tests that reference routes._json_loads etc. keep working unchanged.
from app.services.traceability import (
    _enrich_response_archive,
    _sync_review_to_consultation_result,
    _persisted_archive_summary_payload,
    _persisted_traceability_payload,
    _agent_run_payload,
    _retrieval_hit_payload,
    _doctor_review_payload,
    _llm_log_payload,
    _collect_llm_metas,
    _collect_retrieval_sources,
    _dedupe_strings,
    _json_loads,
)


import app.api._shared as _shared
from app.api._shared import router
from app.api._shared import orchestrator, store  # noqa: F401  re-export for tests

# Relocated to app.services.evaluation (phase-4). Re-exported for call sites/tests.
from app.services.evaluation import (
    _ensure_default_evaluation_cases,
    _default_evaluation_case_specs,
    _evaluate_case,
    _evaluate_rag_case,
    _evaluation_summary,
    _evaluation_readiness,
    _evaluation_case_payload,
    _evaluation_run_payload,
    _evaluation_result_payload,
)

# Relocated to app.services.knowledge_sync (phase-4). Re-exported for call sites/tests.
from app.services.knowledge_sync import (
    _upsert_knowledge_version,
    _upsert_knowledge_documents,
    _sync_runtime_knowledge_from_db,
    _is_runtime_test_knowledge,
)

# Relocated to app.services.privacy (phase-4). Re-exported for call sites/tests.
from app.services.privacy import (
    _generate_data_export,
    _process_data_deletion,
    _ensure_default_privacy_records,
    _data_export_summary,
)

# Relocated to app.api.serializers (phase-4). Re-exported for call sites/tests.
from app.api.serializers import (
    _patient_profile_payload,
    _treatment_record_payload,
    _tooth_record_payload,
    _reminder_payload,
    _notification_payload,
)

# Relocated to app.services.alerts (phase-4). Re-exported for call sites/tests.
from app.services.alerts import (
    _admin_alerts_payload,
)

# Relocated to app.services.notifications (phase-4). Re-exported for call sites/tests.
from app.services.notifications import (
    _create_education_notifications,
    _create_notification,
    _generate_due_notifications,
    _run_due_notifications_for_all,
)

# Relocated to app.services.consultation_archive (phase-4). Re-exported for call sites/tests.
from app.services.consultation_archive import (
    _persist_consultation,
    _save_upload,
    _persist_uploaded_file,
    _consultation_detail_payload,
)

_notification_task: asyncio.Task | None = None


def initialize_runtime_services() -> dict[str, Any]:
    db = SessionLocal()
    try:
        sync_result = _sync_runtime_knowledge_from_db(db)
        _shared.orchestrator.load_workflow_from_db(db)
        privacy_seed = _ensure_default_privacy_records(db)
        created = _run_due_notifications_for_all(db)
        if created:
            write_audit_log(
                db,
                actor_external_id="system",
                actor_role="system",
                action="notifications.startup_scan",
                resource_type="notification",
                resource_id=None,
                risk_level="low",
                detail={"created_count": len(created)},
            )
        return {
            "knowledge_sync": sync_result,
            "workflow_config_loaded": True,
            "privacy_seed": privacy_seed,
            "due_notifications_created": len(created),
        }
    finally:
        db.close()


def start_due_notification_scheduler() -> None:
    global _notification_task
    if settings.notification_scan_interval_seconds <= 0:
        return
    if _notification_task is not None and not _notification_task.done():
        return
    _notification_task = asyncio.create_task(_notification_scan_loop())


async def stop_due_notification_scheduler() -> None:
    global _notification_task
    if _notification_task is None:
        return
    _notification_task.cancel()
    try:
        await _notification_task
    except asyncio.CancelledError:
        pass
    _notification_task = None


async def _notification_scan_loop() -> None:
    interval = max(settings.notification_scan_interval_seconds, 60)
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            created = _run_due_notifications_for_all(db)
            if created:
                write_audit_log(
                    db,
                    actor_external_id="system",
                    actor_role="system",
                    action="notifications.auto_scan",
                    resource_type="notification",
                    resource_id=None,
                    risk_level="low",
                    detail={"created_count": len(created)},
                )
        finally:
            db.close()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@router.get("/demo/scenarios")
def demo_scenarios() -> list[dict[str, str]]:
    return [
        {"title": "牙痛预问诊", "agent": "triage", "message": "右下后牙夜间疼痛，冷热刺激痛 3 天，想知道需要看什么科。"},
        {"title": "根管治疗方案解读", "agent": "treatment", "message": "医生建议根管治疗，我想了解治疗步骤、复诊次数、费用影响因素和风险。"},
        {"title": "抗生素用药审查", "agent": "medication", "message": "阿莫西林和甲硝唑能不能一起用？我有青霉素过敏史。"},
        {"title": "全景片报告解读", "agent": "imaging", "message": "全景片提示左下阻生智齿近中倾斜，邻牙远中龋坏，想通俗理解报告。"},
        {"title": "儿童口腔健康管理", "agent": "health", "message": "8 岁儿童需要窝沟封闭吗？请给换牙期刷牙、涂氟和复诊计划。"},
    ]


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = authenticate_user(db, payload.external_id, payload.password)
    return LoginResponse(
        access_token=create_access_token(user),
        external_id=user.external_id,
        role=user.role,  # type: ignore[arg-type]
        display_name=user.display_name,
    )


@router.post("/auth/register", response_model=LoginResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> LoginResponse:
    if payload.role != "patient":
        raise HTTPException(status_code=403, detail="Only patient self-registration is allowed in internal beta")
    existing = db.query(User).filter(User.external_id == payload.external_id).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already exists")
    user_row = User(
        external_id=payload.external_id,
        role=payload.role,
        display_name=payload.display_name or f"患者-{payload.external_id}",
        password_hash=hash_password(payload.password),
        active=True,
    )
    db.add(user_row)
    db.commit()
    db.refresh(user_row)
    user = CurrentUser(
        id=user_row.id,
        external_id=user_row.external_id,
        role=user_row.role,
        display_name=user_row.display_name,
    )
    return LoginResponse(
        access_token=create_access_token(user),
        external_id=user.external_id,
        role=user.role,  # type: ignore[arg-type]
        display_name=user.display_name,
    )


@router.get("/auth/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "id": user.id,
        "external_id": user.external_id,
        "role": user.role,
        "display_name": user.display_name,
    }


@router.post("/consultations", response_model=AgentResponse)
def create_consultation(
    payload: ConsultationRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AgentResponse:
    if payload.patient_profile is not None and user.role == "patient":
        _upsert_patient_profile(db, user, payload.patient_profile)

    response = _shared.orchestrator.run(
        AgentContext(
            message=payload.message,
            requested_agent=payload.requested_agent,
            patient_profile=payload.patient_profile,
        )
    )
    consultation = _persist_consultation(db, user, payload.message, response)
    response.consultation_id = consultation.id

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="consultation.create",
        resource_type="consultation",
        resource_id=str(consultation.id),
        risk_level=response.risk_level,
        detail={"agent_type": response.agent_type, "flags": response.safety_flags},
    )
    return response


@router.post("/consultations/workflow")
def create_workflow_consultation(
    payload: ConsultationRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run consultation through dynamic multi-agent workflow with handoffs."""
    if payload.patient_profile is not None and user.role == "patient":
        _upsert_patient_profile(db, user, payload.patient_profile)

    context = AgentContext(
        message=payload.message,
        requested_agent=payload.requested_agent,
        patient_profile=payload.patient_profile,
    )
    result = _shared.orchestrator.run_workflow(context)
    response = _workflow_result_to_agent_response(payload, context, result)
    consultation = _persist_consultation(db, user, payload.message, response)
    response.consultation_id = consultation.id
    result["consultation_id"] = consultation.id
    result["agent_response"] = response.model_dump()

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="consultation.workflow",
        resource_type="consultation",
        resource_id=str(consultation.id),
        risk_level=response.risk_level,
        detail={"visited_agents": result.get("visited_agents", []), "requires_review": result.get("requires_review")},
    )
    return result


def _workflow_result_to_agent_response(
    payload: ConsultationRequest,
    context: AgentContext,
    result: dict[str, Any],
) -> AgentResponse:
    requested_or_first = payload.requested_agent or (result.get("visited_agents") or [_shared.orchestrator.route(payload.message)])[0]
    agent_type = requested_or_first if requested_or_first in {"triage", "treatment", "medication", "imaging", "health"} else "health"
    safety = assess_message(payload.message, agent_type=agent_type, has_image=context.has_image)
    results = result.get("results", []) or []
    summary_parts = [
        f"{item.get('agent_name', item.get('agent_id', '智能体'))}：{item.get('content', item.get('error', ''))}"
        for item in results
    ]
    summary = "\n".join(summary_parts) or "动态多智能体 workflow 未生成有效结果。"
    sources = []
    for raw_source in result.get("sources", []) or []:
        try:
            sources.append(SourceDTO(**raw_source))
        except Exception:
            continue
    risk_level = max_risk("medium" if result.get("requires_review") else "low", safety.risk_level)
    if any(item.get("error") for item in results):
        risk_level = max_risk(risk_level, "medium")
    response = AgentResponse(
        agent_type=agent_type,
        agent_name="动态多智能体协作 workflow",
        summary=summary,
        evidence=[source.excerpt for source in sources[:3]],
        risk_tips=["动态 workflow 输出仍为 AI 辅助参考，不替代执业医师诊断、处方或治疗决策。"],
        next_steps=["查看各 Agent 来源引用和执行轨迹", "如标记需复核，请由医生确认后再采取医疗行动"],
        doctor_review_required=bool(result.get("requires_review")) or safety.doctor_review_required,
        risk_level=risk_level,
        refusal=bool(result.get("error")),
        disclaimer=DISCLAIMER,
        sources=sources,
        agent_trace=[str(item) for item in result.get("trace", [])],
        safety_flags=sorted(set(safety.flags + (["workflow_error"] if any(item.get("error") for item in results) else []))),
        structured_data={"workflow": result},
    )
    response.structured_data = response.structured_data or {}
    _shared.orchestrator.safety_guard.apply(
        response,
        message=payload.message,
        agent_type=agent_type,
        has_image=context.has_image,
        safety_flags=safety.flags,
        agent_plan=result.get("agent_plan"),
    )
    response.structured_data["agent_contract"] = contract_from_agent_response(response)
    return response


@router.post("/consultations/workflow/raw")
def create_raw_workflow_consultation(
    payload: ConsultationRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run workflow without persistence; kept for debugging."""
    if payload.patient_profile is not None and user.role == "patient":
        _upsert_patient_profile(db, user, payload.patient_profile)

    result = _shared.orchestrator.run_workflow(
        AgentContext(
            message=payload.message,
            requested_agent=payload.requested_agent,
            patient_profile=payload.patient_profile,
        )
    )

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="consultation.workflow",
        resource_type="consultation",
        risk_level="low",
        detail={"workflow_result": result},
    )
    return result


@router.get("/admin/workflow/graph")
def get_workflow_graph(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Get the workflow visualization in DOT format."""
    require_role(user, {"admin"})
    return {"graph": _shared.orchestrator.get_workflow_graph()}


@router.put("/admin/workflow/graph")
def update_workflow_graph(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update the workflow graph structure dynamically and persist to database."""
    require_role(user, {"admin"})
    _shared.orchestrator.update_workflow_graph(
        nodes=payload.get("nodes", []),
        edges=payload.get("edges", []),
    )
    _shared.orchestrator.workflow.save_graph_to_db(db)
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="workflow.update",
        resource_type="workflow_config",
        resource_id="default",
        risk_level="low",
        detail={"nodes_count": len(payload.get("nodes", [])), "edges_count": len(payload.get("edges", []))},
    )
    return {"ok": True, "message": "Workflow graph updated and saved successfully"}


@router.get("/admin/workflow/configs")
def list_workflow_configs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all workflow configurations."""
    require_role(user, {"admin"})
    from app.models.entities import WorkflowConfig, WorkflowNode, WorkflowEdge
    
    configs = db.query(WorkflowConfig).order_by(desc(WorkflowConfig.updated_at)).all()
    result = []
    for config in configs:
        nodes = db.query(WorkflowNode).filter(WorkflowNode.config_id == config.id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.config_id == config.id).all()
        result.append({
            "id": config.id,
            "config_id": config.config_id,
            "name": config.name,
            "description": config.description,
            "active": config.active,
            "nodes_count": len(nodes),
            "edges_count": len(edges),
            "created_at": config.created_at.isoformat(),
            "updated_at": config.updated_at.isoformat(),
        })
    return result


@router.post("/admin/workflow/configs")
def create_workflow_config(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new workflow configuration."""
    require_role(user, {"admin"})
    from app.models.entities import WorkflowConfig
    from datetime import datetime
    
    config = WorkflowConfig(
        config_id=payload["config_id"],
        name=payload.get("name", payload["config_id"]),
        description=payload.get("description"),
        active=payload.get("active", True),
        created_at=datetime.utcnow(),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="workflow.create",
        resource_type="workflow_config",
        resource_id=config.config_id,
        risk_level="low",
        detail={"name": config.name},
    )
    return {"ok": True, "config_id": config.config_id}


@router.get("/admin/workflow/configs/{config_id}")
def get_workflow_config(
    config_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get detailed workflow configuration including nodes and edges."""
    require_role(user, {"admin"})
    from app.models.entities import WorkflowConfig, WorkflowNode, WorkflowEdge
    
    config = db.query(WorkflowConfig).filter(WorkflowConfig.config_id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Workflow config not found")
    
    nodes = db.query(WorkflowNode).filter(WorkflowNode.config_id == config.id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.config_id == config.id).all()
    
    return {
        "id": config.id,
        "config_id": config.config_id,
        "name": config.name,
        "description": config.description,
        "active": config.active,
        "nodes": [
            {
                "node_id": node.node_id,
                "agent_id": node.agent_id,
                "label": node.label,
                "type": node.type,
                "position_x": node.position_x,
                "position_y": node.position_y,
            }
            for node in nodes
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition,
                "label": edge.label,
            }
            for edge in edges
        ],
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
    }


@router.delete("/admin/workflow/configs/{config_id}")
def delete_workflow_config(
    config_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a workflow configuration."""
    require_role(user, {"admin"})
    from app.models.entities import WorkflowConfig
    
    if config_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default workflow config")
    
    config = db.query(WorkflowConfig).filter(WorkflowConfig.config_id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Workflow config not found")
    
    db.delete(config)
    db.commit()
    
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="workflow.delete",
        resource_type="workflow_config",
        resource_id=config_id,
        risk_level="low",
        detail={},
    )
    return {"ok": True, "message": f"Workflow config {config_id} deleted"}


@router.post("/imaging/analyze", response_model=AgentResponse)
async def analyze_imaging(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> AgentResponse:
    report_text, image = await _read_imaging_request(request)
    uploaded_meta = _save_upload(image) if image is not None else None
    saved_path = uploaded_meta["stored_path"] if uploaded_meta is not None else None
    message = report_text.strip() or "用户上传了口腔影像图片，但未提供报告文本。"
    response = _shared.orchestrator.run(
        AgentContext(message=message, requested_agent="imaging", has_image=image is not None)
    )
    consultation = _persist_consultation(db, user, message, response, image_path=saved_path)
    if uploaded_meta is not None:
        _persist_uploaded_file(db, user, consultation.id, uploaded_meta)
    response.consultation_id = consultation.id

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="imaging.analyze_text",
        resource_type="consultation",
        resource_id=str(consultation.id),
        risk_level=response.risk_level,
        detail={"image_uploaded": image is not None, "image_path": saved_path},
    )
    return response


@router.get("/consultations/history", response_model=list[ConsultationHistoryItem])
def consultation_history(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[ConsultationHistoryItem]:
    query = db.query(Consultation)
    if user.role == "patient":
        query = query.filter(Consultation.patient_external_id == user.external_id)
    rows = query.order_by(desc(Consultation.created_at)).limit(100).all()
    return [
        ConsultationHistoryItem(
            id=row.id,
            agent_type=row.agent_type,
            summary=row.summary,
            risk_level=row.risk_level,
            doctor_review_required=row.doctor_review_required,
            status=row.status,
            created_at=row.created_at.isoformat(),
            sources=json.loads(row.sources_json),
        )
        for row in rows
    ]


@router.get("/consultations/{consultation_id}", response_model=ConsultationDetailResponse)
def consultation_detail(
    consultation_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if consultation is None:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if user.role == "patient" and consultation.patient_external_id != user.external_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's consultation")
    return _consultation_detail_payload(db, consultation, include_llm=user.role in {"doctor", "admin"})


@router.get("/patient/profile")
def patient_profile(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient", "doctor", "admin"})
    row = db.query(PatientProfile).filter(PatientProfile.user_external_id == user.external_id).first()
    return _patient_profile_payload(row) or {
        "name": user.display_name,
        "age": None,
        "sex": None,
        "pregnancy_status": None,
        "allergies": None,
        "conditions": None,
        "oral_history": None,
        "updated_at": None,
    }


@router.put("/patient/profile")
def update_patient_profile(
    payload: PatientProfileInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient"})
    _upsert_patient_profile(db, user, payload)
    row = db.query(PatientProfile).filter(PatientProfile.user_external_id == user.external_id).first()
    return {"ok": True, "profile": _patient_profile_payload(row)}


@router.get("/patient/treatment-records")
def list_treatment_records(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    query = db.query(TreatmentRecord)
    if user.role == "patient":
        query = query.filter(TreatmentRecord.user_external_id == user.external_id)
    rows = query.order_by(desc(TreatmentRecord.created_at)).limit(100).all()
    return [_treatment_record_payload(row) for row in rows]


@router.post("/patient/treatment-records")
def create_treatment_record(
    payload: TreatmentRecordInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient", "doctor", "admin"})
    target_external_id = user.external_id if user.role == "patient" else "patient-demo"
    target_user = db.query(User).filter(User.external_id == target_external_id).first()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Patient user not found")
    row = TreatmentRecord(
        user_id=target_user.id,
        user_external_id=target_user.external_id,
        consultation_id=payload.consultation_id,
        tooth_position=payload.tooth_position,
        diagnosis_text=payload.diagnosis_text,
        treatment_name=payload.treatment_name,
        treatment_date=_parse_datetime(payload.treatment_date),
        doctor_name=payload.doctor_name,
        institution=payload.institution,
        cost_amount=payload.cost_amount,
        next_visit_at=_parse_datetime(payload.next_visit_at),
        note=payload.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if row.next_visit_at is not None:
        _create_notification(
            db,
            user_external_id=row.user_external_id,
            title="复诊提醒",
            content=f"{row.treatment_name} 建议复诊：{row.next_visit_at.strftime('%Y-%m-%d %H:%M')}",
            scheduled_at=row.next_visit_at,
        )
    return {"ok": True, "record": _treatment_record_payload(row)}


@router.get("/patient/tooth-records")
def list_tooth_records(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    query = db.query(ToothRecord)
    if user.role == "patient":
        query = query.filter(ToothRecord.user_external_id == user.external_id)
    rows = query.order_by(ToothRecord.tooth_position).limit(200).all()
    return [_tooth_record_payload(row) for row in rows]


@router.post("/patient/tooth-records")
def upsert_tooth_record(
    payload: ToothRecordInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient", "doctor", "admin"})
    target_external_id = user.external_id if user.role == "patient" else "patient-demo"
    target_user = db.query(User).filter(User.external_id == target_external_id).first()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Patient user not found")
    row = (
        db.query(ToothRecord)
        .filter(ToothRecord.user_external_id == target_user.external_id)
        .filter(ToothRecord.tooth_position == payload.tooth_position)
        .first()
    )
    if row is None:
        row = ToothRecord(
            user_id=target_user.id,
            user_external_id=target_user.external_id,
            tooth_position=payload.tooth_position,
        )
        db.add(row)
    row.status = payload.status
    row.diagnosis_text = payload.diagnosis_text
    row.treatment_summary = payload.treatment_summary
    row.maintenance_cycle_days = payload.maintenance_cycle_days
    row.next_check_at = _parse_datetime(payload.next_check_at) or _default_next_check(payload.maintenance_cycle_days)
    row.note = payload.note
    db.commit()
    db.refresh(row)
    if row.next_check_at is not None:
        _create_notification(
            db,
            user_external_id=row.user_external_id,
            title="牙位维护提醒",
            content=f"{row.tooth_position} 牙位建议在 {row.next_check_at.strftime('%Y-%m-%d')} 前复查或维护。",
            scheduled_at=row.next_check_at,
        )
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="tooth_record.upsert",
        resource_type="tooth_record",
        resource_id=str(row.id),
        risk_level=_tooth_record_risk(row),
        detail={
            "target_external_id": row.user_external_id,
            "tooth_position": row.tooth_position,
            "status": row.status,
            "next_check_at": row.next_check_at.isoformat() if row.next_check_at else None,
        },
    )
    return {"ok": True, "tooth_record": _tooth_record_payload(row), "maintenance_plan": _tooth_maintenance_plan(row)}


@router.get("/patient/maintenance-plan")
def patient_maintenance_plan(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    tooth_rows = db.query(ToothRecord).filter(ToothRecord.user_external_id == user.external_id).all()
    treatment_rows = (
        db.query(TreatmentRecord)
        .filter(TreatmentRecord.user_external_id == user.external_id)
        .order_by(desc(TreatmentRecord.created_at))
        .limit(20)
        .all()
    )
    plans = [_tooth_maintenance_plan(row) for row in tooth_rows]
    general = [
        "每日刷牙至少2次，并使用牙线或邻间刷清洁邻面。",
        "如有正畸、种植或牙周治疗史，按医生要求缩短维护周期。",
        "出现疼痛、肿胀、出血、松动或修复体脱落时不等待定期复诊，及时就诊。",
    ]
    return {
        "tooth_plans": plans,
        "recent_treatments": [_treatment_record_payload(row) for row in treatment_rows],
        "general_recommendations": general,
    }


@router.get("/patient/education-feed")
def patient_education_feed(
    limit: int = 8,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient"})
    return _education_feed_payload(db, user, limit=max(1, min(limit, 12)))


@router.post("/patient/education-feed/push")
def push_patient_education_feed(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient"})
    limit = 5
    if payload and isinstance(payload.get("limit"), int):
        limit = max(1, min(int(payload["limit"]), 8))
    feed = _education_feed_payload(db, user, limit=limit)
    created = _create_education_notifications(db, user.external_id, feed["items"])
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="education_feed.push",
        resource_type="notification",
        resource_id=None,
        risk_level="low",
        detail={"created_count": len(created), "focus_terms": feed.get("focus_terms", [])},
    )
    return {
        "ok": True,
        "created_count": len(created),
        "feed": feed,
        "notifications": [_notification_payload(row) for row in created],
    }


@router.get("/patient/tooth-chart")
def patient_tooth_chart(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient", "doctor", "admin"})
    query = db.query(ToothRecord)
    if user.role == "patient":
        query = query.filter(ToothRecord.user_external_id == user.external_id)
    rows = query.order_by(ToothRecord.tooth_position).limit(200).all()
    return _tooth_chart_payload(rows)


@router.get("/patient/reminders")
def list_reminders(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    query = db.query(FollowUpReminder)
    if user.role == "patient":
        query = query.filter(FollowUpReminder.user_external_id == user.external_id)
    rows = query.order_by(desc(FollowUpReminder.created_at)).limit(100).all()
    return [_reminder_payload(row) for row in rows]


@router.post("/patient/reminders")
def create_reminder(
    payload: ReminderInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient"})
    due_at = _parse_datetime(payload.due_at)
    row = FollowUpReminder(
        consultation_id=payload.consultation_id,
        user_external_id=user.external_id,
        reminder_type=payload.reminder_type,
        due_at=due_at,
        status="pending",
        note=payload.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _create_notification(
        db,
        user_external_id=user.external_id,
        title="口腔健康提醒",
        content=payload.note,
        scheduled_at=due_at,
    )
    return {"ok": True, "reminder": _reminder_payload(row)}


@router.put("/patient/reminders/{reminder_id}")
def update_reminder_status(
    reminder_id: int,
    payload: dict[str, str],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.query(FollowUpReminder).filter(FollowUpReminder.id == reminder_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if user.role == "patient" and row.user_external_id != user.external_id:
        raise HTTPException(status_code=403, detail="Cannot update another patient's reminder")
    row.status = payload.get("status", row.status)
    db.commit()
    return {"ok": True, "reminder": _reminder_payload(row)}


@router.get("/patient/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    rows = (
        db.query(Notification)
        .filter(Notification.user_external_id == user.external_id)
        .order_by(desc(Notification.created_at))
        .limit(100)
        .all()
    )
    return [_notification_payload(row) for row in rows]


@router.post("/patient/notifications/due")
def generate_due_notifications(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    rows = _generate_due_notifications(db, user.external_id)
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="notifications.patient_run_due",
        resource_type="notification",
        resource_id=None,
        risk_level="low",
        detail={"sent_or_created_count": len(rows)},
    )
    return {
        "ok": True,
        "created_count": len(rows),
        "sent_or_created_count": len(rows),
        "notifications": [_notification_payload(row) for row in rows],
    }


@router.put("/patient/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.query(Notification).filter(Notification.id == notification_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.user_external_id != user.external_id:
        raise HTTPException(status_code=403, detail="Cannot update another user's notification")
    row.status = "read"
    row.sent_at = row.sent_at or datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.get("/doctor/reviews", response_model=list[PendingReviewItem])
def pending_reviews(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"doctor", "admin"})
    rows = (
        db.query(DoctorReview)
        .join(Consultation)
        .order_by(desc(DoctorReview.created_at))
        .limit(100)
        .all()
    )
    return [
        {
            "review_id": row.id,
            "consultation_id": row.consultation_id,
            "status": row.status,
            "note": row.note,
            "created_at": row.created_at.isoformat(),
            "agent_type": row.consultation.agent_type,
            "risk_level": row.consultation.risk_level,
            "summary": row.consultation.summary,
        }
        for row in rows
    ]


@router.put("/doctor/reviews/{review_id}", response_model=ReviewUpdateResponse)
def update_review(
    review_id: int,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"doctor", "admin"})
    review = db.query(DoctorReview).filter(DoctorReview.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    review.status = payload.status
    review.note = payload.note
    review.reviewed_by = user.external_id
    review.reviewed_at = datetime.utcnow()
    if payload.review_template:
        review.review_template = payload.review_template
    if payload.risk_assessment:
        review.risk_assessment = payload.risk_assessment
    if payload.treatment_decision:
        review.treatment_decision = payload.treatment_decision
    if payload.signature:
        review.signature = payload.signature
    if payload.signature_title:
        review.signature_title = payload.signature_title
    if payload.followup_instruction:
        review.followup_needed = True
        review.followup_instruction = payload.followup_instruction
    if payload.escalation_note:
        review.escalation_note = payload.escalation_note
    if payload.structured_opinion:
        review.structured_opinion_json = json.dumps(payload.structured_opinion, ensure_ascii=False)
    if payload.status in {"approved", "rejected"}:
        review.closed_at = datetime.utcnow()
    review.consultation.status = f"review_{payload.status}"
    _sync_review_to_consultation_result(review.consultation, review)
    db.commit()

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="doctor_review.update",
        resource_type="doctor_review",
        resource_id=str(review.id),
        risk_level=review.consultation.risk_level,
        detail={
            "status": payload.status,
            "template": payload.review_template,
            "treatment_decision": payload.treatment_decision,
            "followup_needed": review.followup_needed,
            "round": review.review_round,
        },
    )
    return {"ok": True, "review_id": review.id, "status": review.status}


@router.get("/doctor/review-templates")
def list_review_templates(user: CurrentUser = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Return available review templates for different agent types."""
    require_role(user, {"doctor", "admin"})
    from app.schemas.dto import REVIEW_TEMPLATES
    return [tpl.model_dump() for tpl in REVIEW_TEMPLATES]


@router.post("/doctor/reviews/{review_id}/escalate")
def escalate_review(
    review_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Escalate review to higher priority or second-level review."""
    require_role(user, {"doctor", "admin"})
    review = db.query(DoctorReview).filter(DoctorReview.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    review.review_round = (review.review_round or 1) + 1
    review.escalation_note = payload.get("reason", "二审/升级复核")
    review.assigned_role = payload.get("to_role", "admin")
    review.status = "escalated"
    review.consultation.status = "review_escalated"
    _sync_review_to_consultation_result(review.consultation, review)
    db.commit()
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="doctor_review.escalate",
        resource_type="doctor_review",
        resource_id=str(review.id),
        risk_level=review.consultation.risk_level,
        detail={"round": review.review_round, "to_role": review.assigned_role},
    )
    return {"ok": True, "review_id": review.id, "round": review.review_round, "status": review.status}


@router.get("/doctor/consultations/{consultation_id}/report", response_model=ConsultationDetailResponse)
def doctor_consultation_report(
    consultation_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"doctor", "admin"})
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if consultation is None:
        raise HTTPException(status_code=404, detail="Consultation not found")
    payload = _consultation_detail_payload(db, consultation, include_llm=True)
    payload["disclaimer"] = "AI 辅助参考，不替代执业医师诊断、处方或治疗决策；本报告供医生复核与内测演示使用。"
    return payload


@router.get("/admin/knowledge")
def knowledge_status(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    metrics = _shared.store.quality_metrics()
    _upsert_knowledge_version(db, metrics)
    return metrics


@router.get("/admin/knowledge/documents")
def admin_knowledge_documents(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(KnowledgeDocument).order_by(desc(KnowledgeDocument.created_at)).limit(200).all()
    return [_knowledge_document_payload(row) for row in rows]


@router.post("/admin/knowledge/documents")
def admin_create_knowledge_document(
    payload: KnowledgeDocumentInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    metrics = _shared.store.quality_metrics()
    _upsert_knowledge_version(db, metrics)
    version = db.query(KnowledgeVersion).filter(KnowledgeVersion.version == str(metrics["version"])).first()
    row = KnowledgeDocument(
        knowledge_version_id=version.id if version else None,
        doc_uid=f"admin-{uuid4().hex[:12]}",
        title=payload.title,
        category=payload.category,
        source=payload.source,
        tags_json=json.dumps(payload.tags, ensure_ascii=False),
        content=payload.content,
        active=payload.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _log_knowledge_change(db, user, row, "create", None, _knowledge_document_payload(row), "管理员新增知识库文档")
    sync_result = _sync_runtime_knowledge_from_db(db)
    return {"ok": True, "document": _knowledge_document_payload(row), "runtime_sync": sync_result}


@router.put("/admin/knowledge/documents/{document_id}")
def admin_update_knowledge_document(
    document_id: int,
    payload: KnowledgeDocumentInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    row = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    before = _knowledge_document_payload(row)
    row.title = payload.title
    row.category = payload.category
    row.source = payload.source
    row.tags_json = json.dumps(payload.tags, ensure_ascii=False)
    row.content = payload.content
    row.active = payload.active
    db.commit()
    db.refresh(row)
    after = _knowledge_document_payload(row)
    _log_knowledge_change(db, user, row, "update", before, after, "管理员编辑知识库文档")
    sync_result = _sync_runtime_knowledge_from_db(db)
    return {"ok": True, "document": after, "runtime_sync": sync_result}


@router.delete("/admin/knowledge/documents/{document_id}")
def admin_deactivate_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    row = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    before = _knowledge_document_payload(row)
    row.active = False
    db.commit()
    db.refresh(row)
    after = _knowledge_document_payload(row)
    _log_knowledge_change(db, user, row, "deactivate", before, after, "管理员下线知识库文档")
    sync_result = _sync_runtime_knowledge_from_db(db)
    return {"ok": True, "document": after, "runtime_sync": sync_result}


@router.get("/admin/knowledge/changes")
def admin_knowledge_changes(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(KnowledgeChangeLog).order_by(desc(KnowledgeChangeLog.created_at)).limit(100).all()
    return [
        {
            "id": row.id,
            "knowledge_document_id": row.knowledge_document_id,
            "actor_external_id": row.actor_external_id,
            "action": row.action,
            "before": _json_loads(row.before_json, None),
            "after": _json_loads(row.after_json, None),
            "note": row.note,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/admin/chroma/rebuild")
def rebuild_chroma(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    _shared.store = KnowledgeStore()
    _sync_runtime_knowledge_from_db(db)
    metrics = _shared.store.quality_metrics()
    _upsert_knowledge_version(db, metrics)
    return {"ok": True, "metrics": metrics, "recall": _shared.store.evaluate_recall()}


@router.get("/admin/rag/evaluation")
def rag_evaluation(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    return _shared.store.evaluate_recall()


@router.get("/admin/evaluation/cases")
def admin_evaluation_cases(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    _ensure_default_evaluation_cases(db)
    rows = db.query(EvaluationCase).order_by(EvaluationCase.evaluation_type, EvaluationCase.case_id).all()
    return [_evaluation_case_payload(row) for row in rows]


@router.post("/admin/evaluation/runs")
def create_evaluation_run(
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    _ensure_default_evaluation_cases(db)
    payload = payload or {}
    case_types = set(str(item) for item in payload.get("case_types", []) or [])
    query = db.query(EvaluationCase).filter(EvaluationCase.active.is_(True))
    if case_types:
        query = query.filter(EvaluationCase.evaluation_type.in_(sorted(case_types)))
    cases = query.order_by(EvaluationCase.evaluation_type, EvaluationCase.case_id).all()

    run = EvaluationRun(
        run_id=f"eval-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        name=str(payload.get("name") or "生产级内测验收评测"),
        status="running",
        triggered_by=user.external_id,
        total_cases=len(cases),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    results = []
    for case in cases:
        result_payload = _evaluate_case(case)
        result_row = EvaluationResult(
            run_db_id=run.id,
            case_db_id=case.id,
            case_id=case.case_id,
            title=case.title,
            evaluation_type=case.evaluation_type,
            agent_type=case.agent_type,
            passed=bool(result_payload["passed"]),
            score=float(result_payload["score"]),
            metrics_json=json.dumps(result_payload["metrics"], ensure_ascii=False),
            failures_json=json.dumps(result_payload["failures"], ensure_ascii=False),
            response_json=json.dumps(result_payload["response"], ensure_ascii=False),
        )
        db.add(result_row)
        results.append(result_payload)

    summary = _evaluation_summary(results, _shared.store.evaluate_recall())
    run.status = "completed"
    run.total_cases = int(summary["total_cases"])
    run.passed_cases = int(summary["passed_cases"])
    run.failed_cases = int(summary["failed_cases"])
    run.pass_rate = float(summary["pass_rate"])
    run.rag_hit_rate = float(summary["rag_hit_rate"])
    run.safety_pass_rate = float(summary["safety_pass_rate"])
    run.agent_quality_rate = float(summary["agent_quality_rate"])
    run.avg_latency_ms = int(summary["avg_latency_ms"])
    run.estimated_cost = float(summary["estimated_cost"])
    run.summary_json = json.dumps(summary, ensure_ascii=False)
    run.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(run)

    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="evaluation.run",
        resource_type="evaluation_run",
        resource_id=str(run.id),
        risk_level="medium" if run.failed_cases else "low",
        detail={"run_id": run.run_id, "pass_rate": run.pass_rate, "failed_cases": run.failed_cases},
    )
    return _evaluation_run_payload(run, include_results=True)


@router.get("/admin/evaluation/runs")
def list_evaluation_runs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(EvaluationRun).order_by(desc(EvaluationRun.created_at)).limit(50).all()
    return [_evaluation_run_payload(row, include_results=False) for row in rows]


@router.get("/admin/evaluation/runs/{run_id}")
def get_evaluation_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    row = db.query(EvaluationRun).filter(EvaluationRun.run_id == run_id).first()
    if row is None and run_id.isdigit():
        row = db.query(EvaluationRun).filter(EvaluationRun.id == int(run_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return _evaluation_run_payload(row, include_results=True)


@router.get("/admin/evaluation/report")
def admin_evaluation_report(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    _ensure_default_evaluation_cases(db)
    latest = db.query(EvaluationRun).order_by(desc(EvaluationRun.created_at)).first()
    cases = db.query(EvaluationCase).filter(EvaluationCase.active.is_(True)).all()
    rag_report = _shared.store.evaluate_recall()
    latest_payload = _evaluation_run_payload(latest, include_results=True) if latest else None
    readiness = _evaluation_readiness(latest_payload, rag_report, len(cases))
    return {
        "module": "production-beta-evaluation",
        "case_count": len(cases),
        "latest_run": latest_payload,
        "rag_evaluation": rag_report,
        "readiness": readiness,
        "acceptance_scenarios": [case for case in _default_evaluation_case_specs() if case["evaluation_type"] == "demo"],
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/admin/audit")
def audit_logs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(200).all()
    return [
        {
            "id": row.id,
            "actor_external_id": row.actor_external_id,
            "actor_role": row.actor_role,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "risk_level": row.risk_level,
            "detail": _json_loads(row.detail_json, {}),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/admin/audit/consultations", response_model=list[AuditConsultationItem])
def audit_consultation_overview(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(Consultation).order_by(desc(Consultation.created_at)).limit(20).all()
    return [
        {
            "consultation_id": row.id,
            "agent_type": row.agent_type,
            "risk_level": row.risk_level,
            "doctor_review_required": row.doctor_review_required,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "sources": json.loads(row.sources_json),
        }
        for row in rows
    ]


@router.get("/admin/consultation-trace", response_model=list[ConsultationTraceItem])
def admin_consultation_trace(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(Consultation).order_by(desc(Consultation.created_at)).limit(50).all()
    payload = []
    for row in rows:
        agent_run = db.query(AgentRun).filter(AgentRun.consultation_id == row.id).first()
        llm_logs = (
            db.query(LLMCallLog)
            .filter(LLMCallLog.consultation_id == row.id)
            .order_by(desc(LLMCallLog.created_at))
            .all()
        )
        hits = (
            db.query(RetrievalHit)
            .filter(RetrievalHit.consultation_id == row.id)
            .order_by(RetrievalHit.rank)
            .all()
        )
        result_data = _json_loads(row.result_json, {})
        payload.append(
            {
                "consultation_id": row.id,
                "patient_external_id": row.patient_external_id,
                "agent_type": row.agent_type,
                "risk_level": row.risk_level,
                "status": row.status,
                "doctor_review_required": row.doctor_review_required,
                "summary": row.summary,
                "created_at": row.created_at.isoformat(),
                "archive_summary": _persisted_archive_summary_payload(row, result_data, hits, llm_logs),
                "traceability": _persisted_traceability_payload(row, result_data, agent_run, hits, llm_logs),
                "agent_run": _agent_run_payload(agent_run),
                "retrieval_hits": [_retrieval_hit_payload(hit) for hit in hits[:5]],
                "llm_call": _llm_log_payload(llm_logs[0]) if llm_logs else None,
                "llm_calls": [_llm_log_payload(log) for log in llm_logs],
                "review": _doctor_review_payload(row.review),
            }
        )
    return payload


@router.get("/admin/alerts")
def admin_alerts(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    return _admin_alerts_payload(db)


@router.get("/admin/llm/metrics")
def llm_metrics(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    rows = db.query(LLMCallLog).order_by(desc(LLMCallLog.created_at)).limit(100).all()
    total_calls = len(rows)
    success_calls = sum(1 for row in rows if row.status == "success")
    total_tokens = sum(row.total_tokens for row in rows)
    total_cost = round(sum(row.estimated_cost for row in rows), 8)
    avg_latency = int(sum(row.latency_ms for row in rows) / total_calls) if total_calls else 0
    return {
        "total_calls": total_calls,
        "success_calls": success_calls,
        "fallback_calls": total_calls - success_calls,
        "total_tokens": total_tokens,
        "estimated_cost": total_cost,
        "avg_latency_ms": avg_latency,
        "recent": [
            {
                "id": row.id,
                "consultation_id": row.consultation_id,
                "model_name": row.model_name,
                "status": row.status,
                "latency_ms": row.latency_ms,
                "total_tokens": row.total_tokens,
                "estimated_cost": row.estimated_cost,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows[:20]
        ],
    }


@router.post("/admin/notifications/run-due")
def admin_run_due_notifications(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    created = _run_due_notifications_for_all(db)
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="notifications.run_due",
        resource_type="notification",
        resource_id=None,
        risk_level="low",
        detail={"sent_or_created_count": len(created)},
    )
    return {"ok": True, "created_count": len(created), "sent_or_created_count": len(created)}


@router.get("/patient/consents")
def list_patient_consents(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"patient", "doctor", "admin"})
    query = db.query(PatientConsent)
    if user.role == "patient":
        query = query.filter(PatientConsent.user_external_id == user.external_id)
    rows = query.order_by(desc(PatientConsent.created_at)).all()
    return [
        {
            "id": row.id,
            "consent_type": row.consent_type,
            "consent_version": row.consent_version,
            "scope": row.scope,
            "consented": row.consented,
            "signature": row.signature,
            "signed_at": row.signed_at.isoformat() if row.signed_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/patient/consents")
def create_consent(
    payload: ConsentInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient", "admin"})
    from datetime import datetime as dt
    expires_at = _parse_datetime(payload.expires_at) if payload.expires_at else None
    row = PatientConsent(
        user_external_id=user.external_id,
        consent_type=payload.consent_type,
        consent_version=payload.consent_version,
        scope=payload.scope,
        consented=True,
        consent_text=payload.consent_text,
        signature=payload.signature or user.display_name,
        signed_at=dt.utcnow(),
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="consent.create",
        resource_type="patient_consent",
        resource_id=str(row.id),
        risk_level="low",
        detail={"consent_type": payload.consent_type},
    )
    return {"ok": True, "consent_id": row.id}


@router.post("/patient/data-request")
def create_data_request(
    payload: DataAccessRequestInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"patient"})
    row = DataAccessRequest(
        user_external_id=user.external_id,
        request_type=payload.request_type,
        status="pending",
        data_scope=payload.data_scope,
        reason=payload.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="data_request.create",
        resource_type="data_access_request",
        resource_id=str(row.id),
        risk_level="medium",
        detail={"request_type": payload.request_type},
    )
    return {"ok": True, "request_id": row.id}


@router.get("/patient/data-requests")
def list_patient_data_requests(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"patient"})
    rows = (
        db.query(DataAccessRequest)
        .filter(DataAccessRequest.user_external_id == user.external_id)
        .order_by(desc(DataAccessRequest.created_at))
        .limit(50)
        .all()
    )
    return [_data_access_request_payload(row, include_result=True) for row in rows]


@router.get("/admin/data-requests")
def list_data_requests(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(DataAccessRequest).order_by(desc(DataAccessRequest.created_at)).all()
    return [_data_access_request_payload(row, include_result=True) for row in rows]


@router.put("/admin/data-requests/{request_id}")
def process_data_request(
    request_id: int,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    request = db.query(DataAccessRequest).filter(DataAccessRequest.id == request_id).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    request.status = payload.get("status", request.status)
    request.processed_by = user.external_id
    request.processed_at = datetime.utcnow()
    request.note = payload.get("note")
    if request.request_type == "export" and request.status == "approved":
        request.result_data = _generate_data_export(db, request.user_external_id, request.data_scope)
    elif request.request_type == "delete" and request.status == "approved":
        _process_data_deletion(db, request.user_external_id, request.data_scope)
    db.commit()
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action="data_request.process",
        resource_type="data_access_request",
        resource_id=str(request.id),
        risk_level="medium",
        detail={"status": request.status},
    )
    return {
        "ok": True,
        "request_id": request.id,
        "status": request.status,
        "request": _data_access_request_payload(request, include_result=True),
    }


@router.get("/admin/privacy/assessments")
def list_privacy_assessments(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(PrivacyImpactAssessment).order_by(desc(PrivacyImpactAssessment.created_at)).all()
    return [
        {
            "id": row.id,
            "assessment_id": row.assessment_id,
            "title": row.title,
            "description": row.description,
            "data_types": row.data_types,
            "risk_level": row.risk_level,
            "compliance_status": row.compliance_status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/admin/privacy/assessments")
def create_privacy_assessment(
    payload: PrivacyImpactAssessmentInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    row = PrivacyImpactAssessment(
        assessment_id=payload.assessment_id,
        title=payload.title,
        description=payload.description,
        data_types=payload.data_types,
        risk_level=payload.risk_level,
        mitigation_measures=payload.mitigation_measures,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "assessment_id": row.assessment_id}


@router.get("/admin/privacy/retention-policies")
def list_retention_policies(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_role(user, {"admin"})
    rows = db.query(DataRetentionPolicy).order_by(DataRetentionPolicy.data_category).all()
    return [
        {
            "id": row.id,
            "data_category": row.data_category,
            "retention_days": row.retention_days,
            "description": row.description,
            "auto_delete": row.auto_delete,
            "archived": row.archived,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/admin/privacy/retention-policies")
def create_retention_policy(
    payload: DataRetentionPolicyInput,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    require_role(user, {"admin"})
    row = DataRetentionPolicy(
        data_category=payload.data_category,
        retention_days=payload.retention_days,
        description=payload.description,
        auto_delete=payload.auto_delete,
        archived=payload.archived,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "policy_id": row.id}


def _upsert_patient_profile(db: Session, user: CurrentUser, profile: PatientProfileInput) -> None:
    row = db.query(PatientProfile).filter(PatientProfile.user_external_id == user.external_id).first()
    if row is None:
        row = PatientProfile(user_external_id=user.external_id)
        db.add(row)

    if profile.name:
        row.name = profile.name
    if profile.age is not None:
        row.age = profile.age
    if profile.sex:
        row.sex = profile.sex
    if profile.pregnancy_status is not None:
        row.pregnancy_status = profile.pregnancy_status
    if profile.allergies is not None:
        row.allergies = profile.allergies
    if profile.conditions is not None:
        row.conditions = profile.conditions
    if profile.oral_history is not None:
        row.oral_history = profile.oral_history

    db.commit()


async def _read_imaging_request(request: Request) -> tuple[str, UploadFile | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await request.json()
        return str(payload.get("report_text", "")), None

    try:
        form = await request.form()
    except AssertionError as exc:
        raise HTTPException(
            status_code=400,
            detail="影像上传需要安装 python-multipart；也可以用 JSON 方式提交 report_text。",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail="影像上传需要安装 python-multipart；也可以用 JSON 方式提交 report_text。",
        ) from exc

    report_text = str(form.get("report_text") or "")
    image_value = form.get("image")
    image = image_value if isinstance(image_value, UploadFile) else None
    return report_text, image


def _data_access_request_payload(row: DataAccessRequest, include_result: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "user_external_id": row.user_external_id,
        "request_type": row.request_type,
        "status": row.status,
        "data_scope": row.data_scope,
        "reason": row.reason,
        "processed_by": row.processed_by,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }
    if include_result:
        result = _json_loads(row.result_data, None)
        payload["result_data"] = result
        payload["result_summary"] = _data_export_summary(result) if isinstance(result, dict) else None
    return payload


def _knowledge_document_payload(row: KnowledgeDocument) -> dict[str, Any]:
    return {
        "id": row.id,
        "knowledge_version_id": row.knowledge_version_id,
        "doc_uid": row.doc_uid,
        "title": row.title,
        "category": row.category,
        "source": row.source,
        "tags": _json_loads(row.tags_json, []),
        "content": row.content,
        "active": row.active,
        "created_at": row.created_at.isoformat(),
    }


def _log_knowledge_change(
    db: Session,
    user: CurrentUser,
    document: KnowledgeDocument,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    note: str,
) -> None:
    db.add(
        KnowledgeChangeLog(
            knowledge_document_id=document.id,
            actor_external_id=user.external_id,
            action=action,
            before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
            after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
            note=note,
        )
    )
    write_audit_log(
        db,
        actor_external_id=user.external_id,
        actor_role=user.role,
        action=f"knowledge_document.{action}",
        resource_type="knowledge_document",
        resource_id=str(document.id),
        risk_level="medium",
        detail={"doc_uid": document.doc_uid, "title": document.title},
    )


def _education_feed_payload(db: Session, user: CurrentUser, limit: int = 8) -> dict[str, Any]:
    profile = db.query(PatientProfile).filter(PatientProfile.user_external_id == user.external_id).first()
    tooth_rows = db.query(ToothRecord).filter(ToothRecord.user_external_id == user.external_id).all()
    treatment_rows = (
        db.query(TreatmentRecord)
        .filter(TreatmentRecord.user_external_id == user.external_id)
        .order_by(desc(TreatmentRecord.created_at))
        .limit(20)
        .all()
    )
    consultation_rows = (
        db.query(Consultation)
        .filter(Consultation.patient_external_id == user.external_id)
        .order_by(desc(Consultation.created_at))
        .limit(20)
        .all()
    )
    focus_terms = _education_focus_terms(profile, tooth_rows, treatment_rows, consultation_rows)
    query = " ".join(focus_terms) or "口腔健康 刷牙 牙线 复诊 科普"
    hits = _shared.store.retrieve(query, categories=["health", "safety", "mucosa", "guide"], top_k=max(limit * 2, 8))
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for hit in hits:
        if hit.document.id in seen:
            continue
        seen.add(hit.document.id)
        items.append(_education_item_payload(hit, focus_terms))
        if len(items) >= limit:
            break
    if len(items) < min(limit, 5):
        fallback_docs = [
            doc for doc in _shared.store.documents
            if doc.category in {"health", "safety", "mucosa", "guide"} and doc.id not in seen
        ]
        fallback_docs.sort(key=lambda doc: (doc.category != "health", doc.title))
        for doc in fallback_docs:
            items.append(
                _education_item_payload(
                    type("EducationHit", (), {"document": doc, "score": 0.35, "excerpt": _short_excerpt(doc.content)})(),
                    focus_terms,
                )
            )
            if len(items) >= limit:
                break
    return {
        "user_external_id": user.external_id,
        "generated_at": datetime.utcnow().isoformat(),
        "focus_terms": focus_terms,
        "basis": {
            "age": profile.age if profile else None,
            "pregnancy_status": profile.pregnancy_status if profile else None,
            "conditions": profile.conditions if profile else None,
            "allergies": profile.allergies if profile else None,
            "tooth_record_count": len(tooth_rows),
            "recent_treatment_count": len(treatment_rows),
            "recent_consultation_count": len(consultation_rows),
        },
        "items": items,
        "disclaimer": DISCLAIMER,
    }


def _education_focus_terms(
    profile: PatientProfile | None,
    tooth_rows: list[ToothRecord],
    treatment_rows: list[TreatmentRecord],
    consultation_rows: list[Consultation],
) -> list[str]:
    terms: list[str] = ["口腔健康", "刷牙", "牙线", "复诊"]
    if profile is not None:
        if profile.age is not None:
            if profile.age <= 12:
                terms.extend(["儿童", "窝沟封闭", "涂氟", "换牙期"])
            elif profile.age >= 60:
                terms.extend(["老年", "义齿", "牙周维护"])
            else:
                terms.extend(["成人", "洁牙", "龋风险"])
        profile_text = f"{profile.pregnancy_status or ''} {profile.conditions or ''} {profile.allergies or ''} {profile.oral_history or ''}"
        if "妊娠" in profile_text or "孕" in profile_text:
            terms.extend(["妊娠期", "用药安全", "牙龈炎"])
        if "糖尿病" in profile_text:
            terms.extend(["糖尿病", "牙周病", "血糖控制"])
        if "青霉素" in profile_text or "过敏" in profile_text:
            terms.extend(["过敏", "用药安全", "医生复核"])
    combined = " ".join(
        [
            " ".join(str(value or "") for value in [row.status, row.diagnosis_text, row.treatment_summary, row.note])
            for row in tooth_rows
        ]
        + [
            " ".join(str(value or "") for value in [row.tooth_position, row.diagnosis_text, row.treatment_name, row.note])
            for row in treatment_rows
        ]
        + [
            " ".join(str(value or "") for value in [row.agent_type, row.input_text, row.summary])
            for row in consultation_rows
        ]
    )
    keyword_terms = [
        ("种植", ["种植体维护", "咬硬物", "复查"]),
        ("正畸", ["正畸复诊", "托槽清洁", "保持器"]),
        ("牙周", ["牙周维护", "龈下清洁", "出血"]),
        ("根管", ["根管后修复", "冠修复", "根尖复查"]),
        ("龋", ["龋病预防", "含氟牙膏", "邻面清洁"]),
        ("阻生", ["智齿", "冠周炎", "拔牙术后护理"]),
        ("溃疡", ["口腔黏膜", "两周不愈", "医生复核"]),
        ("拔牙", ["拔牙术后护理", "出血", "肿胀"]),
    ]
    for keyword, additions in keyword_terms:
        if keyword in combined:
            terms.extend(additions)
    unique_terms: list[str] = []
    for term in terms:
        if term and term not in unique_terms:
            unique_terms.append(term)
    return unique_terms[:18]


def _education_item_payload(hit: Any, focus_terms: list[str]) -> dict[str, Any]:
    doc = hit.document
    matched_terms = [term for term in focus_terms if term and (term in doc.title or term in doc.content or term in " ".join(doc.tags))]
    return {
        "id": doc.id,
        "title": doc.title,
        "category": doc.category,
        "source": doc.source,
        "score": round(float(hit.score), 3),
        "excerpt": hit.excerpt or _short_excerpt(doc.content),
        "tags": doc.tags,
        "matched_terms": matched_terms[:6],
        "recommendation_reason": _education_reason(doc, matched_terms),
    }


def _education_reason(doc: StoreKnowledgeDocument, matched_terms: list[str]) -> str:
    if matched_terms:
        return f"匹配您的档案关注点：{'、'.join(matched_terms[:4])}。"
    if doc.category == "health":
        return "适合作为日常口腔健康管理科普。"
    if doc.category == "safety":
        return "用于强化AI辅助边界、就医复核和医疗安全意识。"
    if doc.category == "mucosa":
        return "用于了解口腔黏膜异常的观察与就医提示。"
    return "与口腔规范化诊疗和居家维护相关。"


def _short_excerpt(content: str, length: int = 120) -> str:
    text = " ".join(content.split())
    return text[:length] + ("..." if len(text) > length else "")


FDI_TOOTH_POSITIONS = [
    "18", "17", "16", "15", "14", "13", "12", "11",
    "21", "22", "23", "24", "25", "26", "27", "28",
    "48", "47", "46", "45", "44", "43", "42", "41",
    "31", "32", "33", "34", "35", "36", "37", "38",
]


def _tooth_chart_payload(rows: list[ToothRecord]) -> dict[str, Any]:
    by_position: dict[str, ToothRecord] = {}
    for row in rows:
        normalized = _normalize_tooth_position(row.tooth_position)
        by_position[normalized] = row
    teeth = []
    risk_counts = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
    overdue_count = 0
    for position in FDI_TOOTH_POSITIONS:
        row = by_position.get(position)
        if row is None:
            risk = "unknown"
            overdue = False
            payload = None
        else:
            plan = _tooth_maintenance_plan(row)
            risk = str(plan["risk_level"])
            overdue = bool(plan["overdue"])
            payload = _tooth_record_payload(row)
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        if overdue:
            overdue_count += 1
        teeth.append(
            {
                "position": position,
                "label": _tooth_display_label(position),
                "quadrant": position[0],
                "has_record": row is not None,
                "risk_level": risk,
                "overdue": overdue,
                "record": payload,
                "plan": _tooth_maintenance_plan(row) if row is not None else None,
            }
        )
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "teeth": teeth,
        "summary": {
            "record_count": len(rows),
            "risk_counts": risk_counts,
            "overdue_count": overdue_count,
        },
        "legend": {
            "unknown": "无档案",
            "low": "常规维护",
            "medium": "需按计划复查",
            "high": "高风险/建议医生复核",
        },
    }


def _normalize_tooth_position(value: str) -> str:
    import re

    raw = str(value or "").strip()
    direct = re.search(r"\b([1-4][1-8])\b", raw)
    if direct and direct.group(1) in FDI_TOOTH_POSITIONS:
        return direct.group(1)
    cn_map = {
        "右上": "1",
        "左上": "2",
        "左下": "3",
        "右下": "4",
    }
    for prefix, quadrant in cn_map.items():
        match = re.search(prefix + r"\s*([1-8])", raw)
        if match:
            return f"{quadrant}{match.group(1)}"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 2 and digits[:2] in FDI_TOOTH_POSITIONS:
        return digits[:2]
    return raw


def _tooth_display_label(position: str) -> str:
    quadrant_labels = {"1": "右上", "2": "左上", "3": "左下", "4": "右下"}
    return f"{quadrant_labels.get(position[0], '')}{position[1]}"


def _tooth_maintenance_plan(row: ToothRecord) -> dict[str, Any]:
    focus = []
    status_text = f"{row.status} {row.diagnosis_text or ''} {row.treatment_summary or ''}"
    if "种植" in status_text:
        focus.extend(["种植体周围清洁", "避免咬硬物", "按3-6个月维护复查"])
    if "正畸" in status_text:
        focus.extend(["托槽/附件周围清洁", "按正畸医嘱复诊", "关注牙龈炎和脱矿"])
    if "牙周" in status_text or "松动" in status_text:
        focus.extend(["牙周维护", "龈下清洁复查", "控制菌斑和出血"])
    if "根管" in status_text or "牙髓" in status_text:
        focus.extend(["观察咬合痛和根尖症状", "评估冠修复或充填体完整性"])
    if not focus:
        focus.extend(["维持刷牙和牙线清洁", "按周期复查牙体和牙周状态"])
    overdue = row.next_check_at is not None and row.next_check_at <= datetime.utcnow()
    risk_level = _tooth_record_risk(row)
    if overdue:
        next_action = "维护或复查时间已到期，建议尽快预约口腔医生复核。"
    elif risk_level == "high":
        next_action = "存在高维护风险线索，建议缩短复查周期并由医生确认维护方案。"
    elif risk_level == "medium":
        next_action = "按维护周期复查，并记录疼痛、出血、松动或修复体异常。"
    else:
        next_action = "维持日常清洁，按计划复查。"
    return {
        "tooth_position": row.tooth_position,
        "status": row.status,
        "risk_level": risk_level,
        "overdue": overdue,
        "next_check_at": row.next_check_at.isoformat() if row.next_check_at else None,
        "maintenance_cycle_days": row.maintenance_cycle_days,
        "focus": focus,
        "next_action": next_action,
    }


def _tooth_record_risk(row: ToothRecord) -> str:
    status_text = f"{row.status} {row.diagnosis_text or ''} {row.treatment_summary or ''}"
    if any(keyword in status_text for keyword in ["种植", "松动", "牙周", "根尖", "脓", "疼", "肿"]):
        return "high"
    if any(keyword in status_text for keyword in ["根管", "正畸", "冠", "嵌体", "修复", "龋"]):
        return "medium"
    return "low"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


def _default_next_check(cycle_days: int) -> datetime:
    from datetime import timedelta

    return datetime.utcnow() + timedelta(days=cycle_days)


