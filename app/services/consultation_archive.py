"""Consultation archival service (write + read).

Relocated from app/api/routes.py during the phase-4 service extraction. Owns the
full persistence of a consultation (the consultation row, doctor-review task,
agent run, LLM call logs, retrieval hits, structured + health outputs, uploads)
and the rebuild of the consultation detail payload for the patient/doctor views.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import (
    AgentRun,
    Consultation,
    DoctorReview,
    FollowUpReminder,
    HealthPlan,
    KnowledgeDocument,
    LLMCallLog,
    MedicationCheck,
    PatientProfile,
    RetrievalHit,
    TreatmentComparison,
    TriageReport,
    UploadedFile,
)
from app.schemas.dto import AgentResponse, template_for_agent
from app.api.serializers import _patient_profile_payload
from app.services.auth import CurrentUser
from app.services.security import assess_message, mask_sensitive_data
from app.services.traceability import (
    _agent_run_payload,
    _collect_llm_metas,
    _collect_retrieval_sources,
    _doctor_review_payload,
    _dedupe_strings,
    _enrich_response_archive,
    _json_loads,
    _llm_log_payload,
    _persisted_archive_summary_payload,
    _persisted_traceability_payload,
    _retrieval_hit_payload,
)


def _persist_consultation(
    db: Session,
    user: CurrentUser,
    message: str,
    response: AgentResponse,
    image_path: str | None = None,
) -> Consultation:
    safety = assess_message(message, response.agent_type, has_image=bool(image_path))
    consultation = Consultation(
        user_id=user.id,
        patient_external_id=user.external_id if user.role == "patient" else "patient-demo",
        agent_type=response.agent_type,
        input_text=message,
        sanitized_input=safety.sanitized_text,
        summary=mask_sensitive_data(response.summary),
        risk_level=response.risk_level,
        sources_json=json.dumps([source.model_dump() for source in response.sources], ensure_ascii=False),
        result_json=response.model_dump_json(),
        doctor_review_required=response.doctor_review_required,
        status="review_pending" if response.doctor_review_required else "completed",
        image_path=image_path,
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    response.consultation_id = consultation.id

    review: DoctorReview | None = None
    if response.doctor_review_required:
        template = template_for_agent(response.agent_type)
        due_hours = 4 if response.risk_level == "high" else 24 if response.risk_level == "medium" else 72
        review = DoctorReview(
            consultation_id=consultation.id,
            review_template=template.template_id if template else None,
            due_by=datetime.utcnow() + timedelta(hours=due_hours),
        )
        db.add(review)
        db.commit()
        db.refresh(review)

    _enrich_response_archive(response, consultation, review)
    consultation.result_json = response.model_dump_json()
    db.commit()

    _persist_agent_run(db, consultation.id, response)
    _persist_llm_call_logs(db, consultation.id, response)
    _persist_retrieval_hits(db, consultation.id, response)
    _persist_health_outputs(db, user, consultation.id, response)
    _persist_structured_outputs(db, consultation.id, response)

    return consultation


def _save_upload(image: UploadFile | None) -> dict[str, Any] | None:
    if image is None:
        return None
    settings.resolved_upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".pdf"}:
        suffix = ".upload"
    filename = f"{uuid4().hex}{suffix}"
    target = settings.resolved_upload_dir / filename
    with target.open("wb") as handle:
        content = image.file.read()
        handle.write(content)
    return {
        "original_name": image.filename or filename,
        "stored_path": str(target),
        "mime_type": image.content_type,
        "file_size": len(content),
    }


def _persist_uploaded_file(
    db: Session,
    user: CurrentUser,
    consultation_id: int,
    upload: dict[str, Any],
) -> None:
    db.add(
        UploadedFile(
            consultation_id=consultation_id,
            user_id=user.id,
            original_name=str(upload["original_name"]),
            stored_path=str(upload["stored_path"]),
            mime_type=upload.get("mime_type"),
            file_size=int(upload.get("file_size") or 0),
            purpose="imaging",
        )
    )
    db.commit()


def _persist_agent_run(db: Session, consultation_id: int, response: AgentResponse) -> None:
    trace_lines = _agent_run_trace_lines(response)
    db.add(
        AgentRun(
            consultation_id=consultation_id,
            agent_type=response.agent_type,
            agent_name=response.agent_name,
            risk_level=response.risk_level,
            refusal=response.refusal,
            safety_flags_json=json.dumps(response.safety_flags, ensure_ascii=False),
            trace_json=json.dumps(trace_lines, ensure_ascii=False),
        )
    )
    db.commit()


def _agent_run_trace_lines(response: AgentResponse) -> list[str]:
    trace = _dedupe_strings([str(item) for item in response.agent_trace])
    structured = response.structured_data or {}
    archive_summary = structured.get("archive_summary") or {}
    traceability = structured.get("traceability") or {}
    if archive_summary:
        trace.append(
            "历史归档："
            f"来源 {archive_summary.get('retrieval_hit_count', archive_summary.get('source_count', 0))} 条，"
            f"模型调用 {archive_summary.get('llm_call_count', 0)} 次，"
            f"复核状态 {archive_summary.get('review_status') or '无'}。"
        )
    if isinstance(traceability, dict):
        timeline = traceability.get("execution_timeline") or []
        if timeline:
            stages = " -> ".join(str(item.get("stage")) for item in timeline if isinstance(item, dict) and item.get("stage"))
            trace.append(f"链路追踪：{stages}")
    return _dedupe_strings(trace)


def _persist_llm_call_logs(db: Session, consultation_id: int, response: AgentResponse) -> None:
    metas = _collect_llm_metas(response)
    if not metas:
        return

    for scope, meta in metas:
        db.add(_llm_call_log_from_meta(consultation_id, scope, meta))
    db.commit()


def _llm_call_log_from_meta(consultation_id: int, scope: str, meta: dict[str, Any]) -> LLMCallLog:
    request_preview = str(meta.get("request_preview") or "")
    if not request_preview.startswith("["):
        request_preview = f"[{scope}] {request_preview}"
    return LLMCallLog(
        consultation_id=consultation_id,
        provider=str(meta.get("provider") or "deepseek"),
        model_name=str(meta.get("model_name") or ""),
        status=str(meta.get("status") or "unknown"),
        latency_ms=int(meta.get("latency_ms") or 0),
        prompt_tokens=int(meta.get("prompt_tokens") or 0),
        completion_tokens=int(meta.get("completion_tokens") or 0),
        total_tokens=int(meta.get("total_tokens") or 0),
        estimated_cost=float(meta.get("estimated_cost") or 0.0),
        request_preview=request_preview,
        response_preview=meta.get("response_preview"),
        error_message=meta.get("error_message"),
    )


def _persist_retrieval_hits(db: Session, consultation_id: int, response: AgentResponse) -> None:
    for rank, source in enumerate(_collect_retrieval_sources(response), start=1):
        source_id = str(source.get("id") or source.get("document_uid") or "")
        knowledge_document = db.query(KnowledgeDocument).filter(KnowledgeDocument.doc_uid == source_id).first()
        db.add(
            RetrievalHit(
                consultation_id=consultation_id,
                knowledge_document_id=knowledge_document.id if knowledge_document else None,
                document_uid=source_id,
                title=str(source.get("title") or ""),
                category=str(source.get("category") or ""),
                source=str(source.get("source") or ""),
                score=float(source.get("score") or 0.0),
                rank=rank,
                excerpt=str(source.get("excerpt") or ""),
            )
        )
    db.commit()


def _persist_health_outputs(db: Session, user: CurrentUser, consultation_id: int, response: AgentResponse) -> None:
    if response.agent_type == "health":
        db.add(
            HealthPlan(
                consultation_id=consultation_id,
                user_external_id=user.external_id,
                plan_type="oral_health",
                plan_json=json.dumps(
                    {
                        "summary": response.summary,
                        "next_steps": response.next_steps,
                        "risk_tips": response.risk_tips,
                    },
                    ensure_ascii=False,
                ),
            )
        )
    if response.agent_type in {"triage", "treatment", "imaging", "health"}:
        db.add(
            FollowUpReminder(
                consultation_id=consultation_id,
                user_external_id=user.external_id,
                reminder_type="doctor_review" if response.doctor_review_required else "routine_follow_up",
                due_at=None,
                status="pending",
                note="；".join(response.next_steps[:2]) or "建议按需复诊或维护口腔健康档案。",
            )
        )
    db.commit()


def _persist_structured_outputs(db: Session, consultation_id: int, response: AgentResponse) -> None:
    if not response.structured_data:
        return
    if "triage_report" in response.structured_data:
        report = response.structured_data["triage_report"]
        row = db.query(TriageReport).filter(TriageReport.consultation_id == consultation_id).first()
        if row is None:
            row = TriageReport(consultation_id=consultation_id)
            db.add(row)
        row.tooth_position = report.get("tooth_position")
        row.duration_text = report.get("duration_text")
        row.pain_character = report.get("pain_character")
        row.triggers_json = json.dumps(report.get("triggers", []), ensure_ascii=False)
        row.accompanying_symptoms_json = json.dumps(report.get("accompanying_symptoms", []), ensure_ascii=False)
        row.suspected_conditions_json = json.dumps(report.get("suspected_conditions", []), ensure_ascii=False)
        row.urgency_level = str(report.get("urgency_level") or "routine")
        row.recommended_department = str(report.get("recommended_department") or "口腔科")
        row.report_json = json.dumps(report, ensure_ascii=False)
    if "medication_check" in response.structured_data:
        check = response.structured_data["medication_check"]
        row = db.query(MedicationCheck).filter(MedicationCheck.consultation_id == consultation_id).first()
        if row is None:
            row = MedicationCheck(consultation_id=consultation_id)
            db.add(row)
        row.checked_drugs_json = json.dumps(check.get("checked_drugs", []), ensure_ascii=False)
        row.risk_points_json = json.dumps(check.get("risk_points", []), ensure_ascii=False)
        row.contraindications_json = json.dumps(check.get("contraindications", []), ensure_ascii=False)
        row.interactions_json = json.dumps(check.get("interactions", []), ensure_ascii=False)
        row.compliance_summary = str(check.get("compliance_summary") or "")
        row.review_required = bool(check.get("review_required", True))
        row.report_json = json.dumps(check, ensure_ascii=False)
    if "treatment_comparison" in response.structured_data:
        comparison = response.structured_data["treatment_comparison"]
        row = db.query(TreatmentComparison).filter(TreatmentComparison.consultation_id == consultation_id).first()
        if row is None:
            row = TreatmentComparison(consultation_id=consultation_id)
            db.add(row)
        row.matched_options_json = json.dumps(comparison.get("matched_options", []), ensure_ascii=False)
        row.comparison_json = json.dumps(comparison.get("comparison", []), ensure_ascii=False)
        row.recommendation_note = str(comparison.get("recommendation_note") or "")
        row.report_json = json.dumps(comparison, ensure_ascii=False)
    db.commit()


def _structured_outputs_payload(db: Session, consultation_id: int) -> dict[str, Any]:
    triage = db.query(TriageReport).filter(TriageReport.consultation_id == consultation_id).first()
    medication = db.query(MedicationCheck).filter(MedicationCheck.consultation_id == consultation_id).first()
    treatment = db.query(TreatmentComparison).filter(TreatmentComparison.consultation_id == consultation_id).first()
    payload: dict[str, Any] = {}
    if triage is not None:
        payload["triage_report"] = _json_loads(triage.report_json, {})
    if medication is not None:
        payload["medication_check"] = _json_loads(medication.report_json, {})
    if treatment is not None:
        payload["treatment_comparison"] = _json_loads(treatment.report_json, {})
    return payload


def _consultation_detail_payload(
    db: Session,
    consultation: Consultation,
    include_llm: bool = False,
) -> dict[str, Any]:
    profile = (
        db.query(PatientProfile)
        .filter(PatientProfile.user_external_id == consultation.patient_external_id)
        .first()
    )
    agent_run = db.query(AgentRun).filter(AgentRun.consultation_id == consultation.id).first()
    llm_logs = (
        db.query(LLMCallLog)
        .filter(LLMCallLog.consultation_id == consultation.id)
        .order_by(desc(LLMCallLog.created_at))
        .all()
    )
    hits = (
        db.query(RetrievalHit)
        .filter(RetrievalHit.consultation_id == consultation.id)
        .order_by(RetrievalHit.rank)
        .all()
    )
    uploads = db.query(UploadedFile).filter(UploadedFile.consultation_id == consultation.id).all()
    result_data = _json_loads(consultation.result_json, {})
    traceability = _persisted_traceability_payload(consultation, result_data, agent_run, hits, llm_logs)
    archive_summary = _persisted_archive_summary_payload(consultation, result_data, hits, llm_logs)
    return {
        "consultation": {
            "id": consultation.id,
            "patient_external_id": consultation.patient_external_id,
            "agent_type": consultation.agent_type,
            "input_text": consultation.input_text,
            "sanitized_input": consultation.sanitized_input,
            "summary": consultation.summary,
            "risk_level": consultation.risk_level,
            "status": consultation.status,
            "doctor_review_required": consultation.doctor_review_required,
            "sources": _json_loads(consultation.sources_json, []),
            "image_path": consultation.image_path,
            "created_at": consultation.created_at.isoformat(),
        },
        "patient_profile": _patient_profile_payload(profile),
        "agent_response": result_data,
        "structured_outputs": _structured_outputs_payload(db, consultation.id),
        "archive_summary": archive_summary,
        "traceability": traceability,
        "review_context": traceability.get("review"),
        "review": _doctor_review_payload(consultation.review),
        "agent_run": _agent_run_payload(agent_run),
        "retrieval_hits": [_retrieval_hit_payload(row) for row in hits],
        "llm_call": _llm_log_payload(llm_logs[0]) if include_llm and llm_logs else None,
        "llm_calls": [_llm_log_payload(row) for row in llm_logs] if include_llm else [],
        "uploads": [
            {
                "id": row.id,
                "original_name": row.original_name,
                "mime_type": row.mime_type,
                "file_size": row.file_size,
                "purpose": row.purpose,
                "created_at": row.created_at.isoformat(),
            }
            for row in uploads
        ],
        "disclaimer": "AI 辅助参考，不替代执业医师诊断、处方或治疗决策；历史归档用于复盘来源、轨迹和医生复核状态。",
    }
