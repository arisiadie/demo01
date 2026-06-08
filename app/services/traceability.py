"""Contract & traceability serialization (single source of truth).

Relocated from app/api/routes.py during the backend governance refactor
(phase 1: contract consolidation). These builders turn agent responses and
persisted rows into the unified traceability / archive_summary / review_context
payloads consumed by the patient, doctor and admin APIs.

Two entry families are intentionally kept:
- live builders (from in-memory AgentResponse, at consultation creation time)
- persisted builders (rebuilt from DB rows, reusing archived data when present)
They share the low-level row serializers and dedupe/normalize helpers below.
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.contracts import contract_from_agent_response
from app.models.entities import (
    AgentRun,
    Consultation,
    DoctorReview,
    LLMCallLog,
    RetrievalHit,
)
from app.schemas.dto import AgentResponse


def _enrich_response_archive(
    response: AgentResponse,
    consultation: Consultation,
    review: DoctorReview | None,
) -> None:
    if response.structured_data is None:
        response.structured_data = {}
    llm_metas = _collect_llm_metas(response)
    retrieval_sources = _collect_retrieval_sources(response)
    response.structured_data["archive_summary"] = _archive_summary_from_response(
        response=response,
        consultation=consultation,
        review=review,
        retrieval_source_count=len(retrieval_sources),
        llm_call_count=len(llm_metas),
    )
    response.structured_data["review_context"] = _review_context_payload(review)
    response.structured_data["traceability"] = _traceability_from_response(
        response=response,
        consultation=consultation,
        review=review,
        retrieval_sources=retrieval_sources,
        llm_metas=llm_metas,
    )
    response.structured_data["agent_contract"] = contract_from_agent_response(response)


def _sync_review_to_consultation_result(consultation: Consultation, review: DoctorReview) -> None:
    result_data = _json_loads(consultation.result_json, {})
    if not isinstance(result_data, dict):
        result_data = {}
    structured = result_data.setdefault("structured_data", {})
    if not isinstance(structured, dict):
        structured = {}
        result_data["structured_data"] = structured

    review_context = _review_context_payload(review)
    structured["review_context"] = review_context
    archive_summary = structured.get("archive_summary")
    if isinstance(archive_summary, dict):
        archive_summary["status"] = consultation.status
        archive_summary["review_status"] = review.status
        archive_summary["review_round"] = review.review_round
        archive_summary["closed_at"] = review.closed_at.isoformat() if review.closed_at else None
    traceability = structured.get("traceability")
    if isinstance(traceability, dict):
        traceability["review"] = review_context
        persistence = traceability.setdefault("persistence", {})
        if isinstance(persistence, dict):
            persistence["doctor_review_table"] = "doctor_reviews"
        timeline = traceability.setdefault("execution_timeline", [])
        if isinstance(timeline, list):
            timeline.append(
                {
                    "step": len(timeline) + 1,
                    "stage": "doctor_review",
                    "label": "医生复核状态更新",
                    "status": review.status,
                    "detail": {
                        "review_id": review.id,
                        "reviewed_by": review.reviewed_by,
                        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
                        "followup_needed": review.followup_needed,
                    },
                }
            )
    consultation.result_json = json.dumps(result_data, ensure_ascii=False)


def _archive_summary_from_response(
    *,
    response: AgentResponse,
    consultation: Consultation,
    review: DoctorReview | None,
    retrieval_source_count: int,
    llm_call_count: int,
) -> dict[str, Any]:
    workflow = (response.structured_data or {}).get("workflow") if response.structured_data else None
    visited_agents = workflow.get("visited_agents", []) if isinstance(workflow, dict) else []
    return {
        "consultation_id": consultation.id,
        "patient_external_id": consultation.patient_external_id,
        "agent_type": response.agent_type,
        "risk_level": response.risk_level,
        "status": consultation.status,
        "doctor_review_required": response.doctor_review_required,
        "doctor_review_id": review.id if review else None,
        "review_status": review.status if review else None,
        "source_count": len(response.sources),
        "retrieval_hit_count": retrieval_source_count,
        "llm_call_count": llm_call_count,
        "workflow_agent_count": len(visited_agents),
        "visited_agents": visited_agents,
        "safety_flag_count": len(response.safety_flags),
        "refusal": response.refusal,
        "has_image": bool(consultation.image_path),
        "created_at": consultation.created_at.isoformat(),
        "archive_version": "traceability-v1",
    }


def _traceability_from_response(
    *,
    response: AgentResponse,
    consultation: Consultation,
    review: DoctorReview | None,
    retrieval_sources: list[dict[str, Any]],
    llm_metas: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    structured = response.structured_data or {}
    agent_plan = structured.get("agent_plan") or {}
    rag_plan = structured.get("rag_plan") or {}
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    safety_guard = structured.get("safety_guard") or {}
    return {
        "consultation_id": consultation.id,
        "archive_version": "traceability-v1",
        "agent_plan": agent_plan,
        "workflow": {
            "visited_agents": workflow.get("visited_agents", []),
            "requires_review": workflow.get("requires_review"),
            "result_count": len(workflow.get("results", []) or []),
            "workflow_graph": workflow.get("workflow_graph"),
        },
        "agent_runs": _agent_runs_from_response(response),
        "execution_timeline": _execution_timeline_from_response(response),
        "rag": _rag_trace_from_response(response, retrieval_sources, rag_plan),
        "llm": _llm_trace_from_metas(llm_metas),
        "safety": {
            "risk_level": response.risk_level,
            "refusal": response.refusal,
            "safety_flags": response.safety_flags,
            "guard_status": safety_guard.get("status"),
            "findings": safety_guard.get("findings", []),
        },
        "review": _review_context_payload(review),
        "persistence": {
            "consultation_table": "consultations",
            "agent_run_table": "agent_runs",
            "retrieval_hit_table": "retrieval_hits",
            "llm_call_table": "llm_call_logs",
            "doctor_review_table": "doctor_reviews" if review else None,
            "structured_output_tables": _structured_output_table_names(response.structured_data or {}),
        },
    }


def _agent_runs_from_response(response: AgentResponse) -> list[dict[str, Any]]:
    runs = [
        {
            "scope": "main",
            "agent_id": response.agent_type,
            "agent_name": response.agent_name,
            "risk_level": response.risk_level,
            "requires_review": response.doctor_review_required,
            "refusal": response.refusal,
            "trace_count": len(response.agent_trace),
            "source_count": len(response.sources),
            "safety_flags": response.safety_flags,
            "llm_status": (response.llm_meta or {}).get("status"),
        }
    ]
    workflow = (response.structured_data or {}).get("workflow") if response.structured_data else None
    if isinstance(workflow, dict):
        for item in workflow.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            contract = item.get("agent_contract") if isinstance(item.get("agent_contract"), dict) else {}
            runs.append(
                {
                    "scope": "workflow",
                    "agent_id": item.get("agent_id"),
                    "agent_name": item.get("agent_name"),
                    "risk_level": item.get("risk_level") or contract.get("risk_level"),
                    "requires_review": item.get("requires_review") or contract.get("doctor_review_required"),
                    "refusal": contract.get("refusal", False),
                    "trace_count": len(item.get("trace") or []),
                    "source_count": len(item.get("sources") or item.get("references") or []),
                    "safety_flags": contract.get("safety_flags", []),
                    "llm_status": (item.get("llm_meta") or {}).get("status") if isinstance(item.get("llm_meta"), dict) else None,
                }
            )
    return runs


def _execution_timeline_from_response(response: AgentResponse) -> list[dict[str, Any]]:
    structured = response.structured_data or {}
    timeline: list[dict[str, Any]] = []

    def add(stage: str, label: str, detail: Any = None, status: str = "completed") -> None:
        timeline.append(
            {
                "step": len(timeline) + 1,
                "stage": stage,
                "label": label,
                "status": status,
                "detail": detail,
            }
        )

    plan = structured.get("agent_plan") or {}
    if plan:
        add(
            "router",
            "Agent 路由与问题拆解",
            {
                "primary_agent": plan.get("primary_agent"),
                "secondary_agents": plan.get("secondary_agents", []),
                "risk_signals": plan.get("risk_signals", []),
            },
        )
    rag_plan = structured.get("rag_plan") or {}
    if rag_plan:
        add(
            "rag",
            "Agentic RAG 多轮检索",
            {
                "round_count": rag_plan.get("round_count"),
                "confidence_score": rag_plan.get("confidence_score"),
                "source_count": (rag_plan.get("source_coverage") or {}).get("source_count"),
            },
        )
    workflow = structured.get("workflow") if isinstance(structured.get("workflow"), dict) else {}
    if workflow:
        for item in workflow.get("results", []) or []:
            add(
                "workflow_agent",
                f"{item.get('agent_id', 'unknown')} 子智能体执行",
                {
                    "agent_name": item.get("agent_name"),
                    "requires_review": item.get("requires_review"),
                    "source_count": len(item.get("sources") or item.get("references") or []),
                    "llm_status": (item.get("llm_meta") or {}).get("status") if isinstance(item.get("llm_meta"), dict) else None,
                },
            )
    add(
        "safety",
        "医疗安全校验",
        {
            "risk_level": response.risk_level,
            "refusal": response.refusal,
            "safety_flags": response.safety_flags,
            "guard_status": (structured.get("safety_guard") or {}).get("status"),
        },
    )
    if response.doctor_review_required:
        add("doctor_review", "创建医生复核任务", {"risk_level": response.risk_level, "status": "pending"})
    add("archive", "历史归档", {"source_count": len(response.sources), "trace_count": len(response.agent_trace)})
    return timeline


def _rag_trace_from_response(
    response: AgentResponse,
    retrieval_sources: list[dict[str, Any]],
    rag_plan: dict[str, Any],
) -> dict[str, Any]:
    source_ids = [str(source.get("id") or source.get("document_uid")) for source in retrieval_sources]
    return {
        "source_count": len(retrieval_sources),
        "source_ids": source_ids,
        "top_sources": retrieval_sources[:5],
        "retrieval_categories": rag_plan.get("retrieval_categories", []),
        "round_count": rag_plan.get("round_count"),
        "confidence_score": rag_plan.get("confidence_score"),
        "source_coverage": rag_plan.get("source_coverage", {}),
        "source_bindings": (response.structured_data or {}).get("source_bindings", []),
    }


def _llm_trace_from_metas(metas: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    total_latency = 0
    total_tokens = 0
    total_cost = 0.0
    calls = []
    for scope, meta in metas:
        status = str(meta.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        latency = int(meta.get("latency_ms") or 0)
        tokens = int(meta.get("total_tokens") or 0)
        cost = float(meta.get("estimated_cost") or 0.0)
        total_latency += latency
        total_tokens += tokens
        total_cost += cost
        calls.append(
            {
                "scope": scope,
                "provider": meta.get("provider") or "deepseek",
                "model_name": meta.get("model_name"),
                "status": status,
                "latency_ms": latency,
                "total_tokens": tokens,
                "estimated_cost": cost,
            }
        )
    return {
        "call_count": len(metas),
        "status_counts": status_counts,
        "avg_latency_ms": int(total_latency / len(metas)) if metas else 0,
        "total_tokens": total_tokens,
        "estimated_cost": round(total_cost, 8),
        "calls": calls,
    }


def _review_context_payload(review: DoctorReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "review_id": review.id,
        "status": review.status,
        "assigned_role": review.assigned_role,
        "review_template": review.review_template,
        "due_by": review.due_by.isoformat() if review.due_by else None,
        "review_round": review.review_round,
        "followup_needed": review.followup_needed,
        "closed_at": review.closed_at.isoformat() if review.closed_at else None,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
    }


def _structured_output_table_names(structured_data: dict[str, Any]) -> list[str]:
    tables = []
    if "triage_report" in structured_data:
        tables.append("triage_reports")
    if "medication_check" in structured_data:
        tables.append("medication_checks")
    if "treatment_comparison" in structured_data:
        tables.append("treatment_comparisons")
    if "health_plan" in structured_data:
        tables.append("health_plans")
    return tables


def _collect_llm_metas(response: AgentResponse) -> list[tuple[str, dict[str, Any]]]:
    metas: list[tuple[str, dict[str, Any]]] = []
    if response.llm_meta:
        metas.append((f"main_agent:{response.agent_type}", response.llm_meta))

    workflow = (response.structured_data or {}).get("workflow") if response.structured_data else None
    if isinstance(workflow, dict):
        for item in workflow.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            meta = item.get("llm_meta")
            agent_id = str(item.get("agent_id") or "unknown")
            if isinstance(meta, dict):
                metas.append((f"workflow_agent:{agent_id}", meta))
    return metas


def _collect_retrieval_sources(response: AgentResponse) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    def add_source(raw: Any, scope: str) -> None:
        source = _normalize_source_dict(raw)
        if source is None:
            return
        source["scopes"] = _dedupe_strings([*source.get("scopes", []), scope])
        sources.append(source)

    for source in response.sources:
        add_source(source, "main_response")

    workflow = (response.structured_data or {}).get("workflow") if response.structured_data else None
    if isinstance(workflow, dict):
        for raw_source in workflow.get("sources", []) or []:
            add_source(raw_source, "workflow")
        for item in workflow.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or "unknown")
            for raw_source in item.get("sources", []) or item.get("references", []) or []:
                add_source(raw_source, f"workflow_agent:{agent_id}")
            contract = item.get("agent_contract") if isinstance(item.get("agent_contract"), dict) else {}
            for raw_source in contract.get("sources", []) or []:
                add_source(raw_source, f"workflow_contract:{agent_id}")

    return _dedupe_sources(sources)


def _normalize_source_dict(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        item = raw.model_dump()
    elif hasattr(raw, "dict"):
        item = raw.dict()
    elif isinstance(raw, dict):
        item = dict(raw)
    else:
        item = {}
        for key in ("id", "document_uid", "title", "category", "source", "score", "excerpt"):
            if hasattr(raw, key):
                item[key] = getattr(raw, key)
    source_id = str(item.get("id") or item.get("document_uid") or "").strip()
    if not source_id:
        return None
    return {
        "id": source_id,
        "title": str(item.get("title") or ""),
        "category": str(item.get("category") or ""),
        "source": str(item.get("source") or ""),
        "score": _float_or_zero(item.get("score")),
        "excerpt": str(item.get("excerpt") or ""),
        "scopes": list(item.get("scopes") or []),
    }


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = str(source.get("id") or "")
        existing = merged.get(source_id)
        if existing is None:
            merged[source_id] = source
            continue
        existing["scopes"] = _dedupe_strings([*existing.get("scopes", []), *source.get("scopes", [])])
        if float(source.get("score") or 0) > float(existing.get("score") or 0):
            existing.update({key: source[key] for key in ("title", "category", "source", "score", "excerpt")})
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0), reverse=True)


def _dedupe_strings(items: list[Any]) -> list[str]:
    result = []
    seen = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _doctor_review_payload(review: DoctorReview | None) -> dict[str, Any] | None:
    import json as _json
    if review is None:
        return None
    try:
        structured_opinion = _json.loads(review.structured_opinion_json)
    except Exception:
        structured_opinion = {}
    return {
        "id": review.id,
        "status": review.status,
        "review_template": review.review_template,
        "structured_opinion": structured_opinion,
        "risk_assessment": review.risk_assessment,
        "treatment_decision": review.treatment_decision,
        "signature": review.signature,
        "signature_title": review.signature_title,
        "due_by": review.due_by.isoformat() if review.due_by else None,
        "review_round": review.review_round,
        "followup_needed": review.followup_needed,
        "followup_instruction": review.followup_instruction,
        "escalation_note": review.escalation_note,
        "closed_at": review.closed_at.isoformat() if review.closed_at else None,
        "note": review.note,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "created_at": review.created_at.isoformat(),
    }


def _persisted_archive_summary_payload(
    consultation: Consultation,
    result_data: Any,
    hits: list[RetrievalHit],
    llm_logs: list[LLMCallLog],
) -> dict[str, Any]:
    structured = result_data.get("structured_data", {}) if isinstance(result_data, dict) else {}
    archived = structured.get("archive_summary") if isinstance(structured, dict) else None
    if isinstance(archived, dict):
        payload = dict(archived)
    else:
        payload = {
            "consultation_id": consultation.id,
            "archive_version": "traceability-v1",
            "patient_external_id": consultation.patient_external_id,
            "agent_type": consultation.agent_type,
        }
    payload.update(
        {
            "consultation_id": consultation.id,
            "status": consultation.status,
            "risk_level": consultation.risk_level,
            "doctor_review_required": consultation.doctor_review_required,
            "review_status": consultation.review.status if consultation.review else None,
            "retrieval_hit_count": len(hits),
            "llm_call_count": len(llm_logs),
            "source_count": len(_json_loads(consultation.sources_json, [])),
            "created_at": consultation.created_at.isoformat(),
        }
    )
    return payload


def _persisted_traceability_payload(
    consultation: Consultation,
    result_data: Any,
    agent_run: AgentRun | None,
    hits: list[RetrievalHit],
    llm_logs: list[LLMCallLog],
) -> dict[str, Any]:
    structured = result_data.get("structured_data", {}) if isinstance(result_data, dict) else {}
    archived = structured.get("traceability") if isinstance(structured, dict) else None
    if isinstance(archived, dict):
        traceability = dict(archived)
    else:
        traceability = {
            "consultation_id": consultation.id,
            "archive_version": "traceability-v1",
            "agent_plan": structured.get("agent_plan", {}) if isinstance(structured, dict) else {},
            "workflow": _workflow_trace_from_result(result_data),
            "agent_runs": [_agent_run_payload(agent_run)] if agent_run else [],
            "execution_timeline": _timeline_from_persisted_rows(consultation, agent_run, hits, llm_logs),
            "rag": {},
            "llm": {},
            "safety": {},
            "review": None,
            "persistence": {},
        }

    traceability["consultation_id"] = consultation.id
    traceability["review"] = _doctor_review_payload(consultation.review)
    traceability["rag"] = _persisted_rag_trace(traceability.get("rag"), hits)
    traceability["llm"] = _persisted_llm_trace(traceability.get("llm"), llm_logs)
    traceability["safety"] = _persisted_safety_trace(traceability.get("safety"), consultation, agent_run)
    traceability["persistence"] = _persisted_tables_trace(traceability.get("persistence"), consultation)
    if not traceability.get("execution_timeline"):
        traceability["execution_timeline"] = _timeline_from_persisted_rows(consultation, agent_run, hits, llm_logs)
    return traceability


def _workflow_trace_from_result(result_data: Any) -> dict[str, Any]:
    structured = result_data.get("structured_data", {}) if isinstance(result_data, dict) else {}
    workflow = structured.get("workflow") if isinstance(structured, dict) and isinstance(structured.get("workflow"), dict) else {}
    return {
        "visited_agents": workflow.get("visited_agents", []),
        "requires_review": workflow.get("requires_review"),
        "result_count": len(workflow.get("results", []) or []),
        "workflow_graph": workflow.get("workflow_graph"),
    }


def _timeline_from_persisted_rows(
    consultation: Consultation,
    agent_run: AgentRun | None,
    hits: list[RetrievalHit],
    llm_logs: list[LLMCallLog],
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []

    def add(stage: str, label: str, detail: dict[str, Any] | None = None, status: str = "completed") -> None:
        timeline.append({"step": len(timeline) + 1, "stage": stage, "label": label, "status": status, "detail": detail or {}})

    add("consultation", "咨询归档创建", {"consultation_id": consultation.id, "agent_type": consultation.agent_type})
    if agent_run:
        add("agent", "主 Agent 执行归档", {"agent_type": agent_run.agent_type, "risk_level": agent_run.risk_level})
    if hits:
        add("rag", "RAG 来源命中归档", {"hit_count": len(hits), "top_document_uid": hits[0].document_uid})
    if llm_logs:
        add("llm", "模型调用日志归档", {"call_count": len(llm_logs), "statuses": _llm_status_counts(llm_logs)})
    add(
        "safety",
        "安全与复核状态归档",
        {
            "risk_level": consultation.risk_level,
            "doctor_review_required": consultation.doctor_review_required,
            "review_status": consultation.review.status if consultation.review else None,
        },
    )
    return timeline


def _persisted_rag_trace(existing: Any, hits: list[RetrievalHit]) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(
        {
            "persisted_hit_count": len(hits),
            "source_count": payload.get("source_count", len(hits)),
            "persisted_top_sources": [_retrieval_hit_payload(row) for row in hits[:5]],
            "persisted_source_ids": [row.document_uid for row in hits],
        }
    )
    return payload


def _persisted_llm_trace(existing: Any, llm_logs: list[LLMCallLog]) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(
        {
            "persisted_call_count": len(llm_logs),
            "persisted_status_counts": _llm_status_counts(llm_logs),
            "persisted_avg_latency_ms": int(sum(row.latency_ms for row in llm_logs) / len(llm_logs)) if llm_logs else 0,
            "persisted_total_tokens": sum(row.total_tokens for row in llm_logs),
            "persisted_estimated_cost": round(sum(row.estimated_cost for row in llm_logs), 8),
        }
    )
    return payload


def _persisted_safety_trace(existing: Any, consultation: Consultation, agent_run: AgentRun | None) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(
        {
            "risk_level": consultation.risk_level,
            "refusal": bool(agent_run.refusal) if agent_run else payload.get("refusal", False),
            "safety_flags": _json_loads(agent_run.safety_flags_json, []) if agent_run else payload.get("safety_flags", []),
            "doctor_review_required": consultation.doctor_review_required,
        }
    )
    return payload


def _persisted_tables_trace(existing: Any, consultation: Consultation) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(
        {
            "consultation_table": "consultations",
            "agent_run_table": "agent_runs",
            "retrieval_hit_table": "retrieval_hits",
            "llm_call_table": "llm_call_logs",
            "doctor_review_table": "doctor_reviews" if consultation.review else None,
        }
    )
    return payload


def _llm_status_counts(llm_logs: list[LLMCallLog]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in llm_logs:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def _agent_run_payload(agent_run: AgentRun | None) -> dict[str, Any] | None:
    if agent_run is None:
        return None
    return {
        "agent_type": agent_run.agent_type,
        "agent_name": agent_run.agent_name,
        "risk_level": agent_run.risk_level,
        "refusal": agent_run.refusal,
        "safety_flags": _json_loads(agent_run.safety_flags_json, []),
        "trace": _json_loads(agent_run.trace_json, []),
        "started_at": agent_run.started_at.isoformat(),
        "completed_at": agent_run.completed_at.isoformat(),
    }


def _retrieval_hit_payload(row: RetrievalHit) -> dict[str, Any]:
    return {
        "document_uid": row.document_uid,
        "title": row.title,
        "category": row.category,
        "source": row.source,
        "score": row.score,
        "rank": row.rank,
        "excerpt": row.excerpt,
    }


def _llm_log_payload(row: LLMCallLog | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "provider": row.provider,
        "model_name": row.model_name,
        "status": row.status,
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost": row.estimated_cost,
        "request_preview": row.request_preview,
        "response_preview": row.response_preview,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat(),
    }


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback
