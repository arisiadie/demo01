"""Admin alerts aggregation service.

Relocated from app/api/routes.py during the phase-4 service extraction. Builds
the operational alert payload (overdue doctor reviews, pending privacy requests,
etc.) consumed by GET /admin/alerts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

import app.api._shared as _shared
from app.models.entities import Consultation, DataAccessRequest, DoctorReview, LLMCallLog


def _admin_alerts_payload(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    alerts: list[dict[str, Any]] = []
    overdue_reviews = (
        db.query(DoctorReview)
        .filter(DoctorReview.status.in_(["pending", "returned_for_info", "escalated"]))
        .filter(DoctorReview.due_by.is_not(None))
        .filter(DoctorReview.due_by < now)
        .order_by(DoctorReview.due_by)
        .limit(20)
        .all()
    )
    for review in overdue_reviews:
        alerts.append(
            {
                "type": "doctor_review_overdue",
                "severity": "high",
                "title": "医生复核逾期",
                "message": f"复核 #{review.id} 已超过截止时间，咨询 #{review.consultation_id} 仍为 {review.status}。",
                "resource_type": "doctor_review",
                "resource_id": review.id,
                "created_at": now.isoformat(),
            }
        )

    high_risk_pending = (
        db.query(Consultation)
        .filter(Consultation.risk_level == "high")
        .filter(Consultation.doctor_review_required.is_(True))
        .filter(Consultation.status.notin_(["review_approved", "review_rejected"]))
        .order_by(desc(Consultation.created_at))
        .limit(20)
        .all()
    )
    for row in high_risk_pending:
        alerts.append(
            {
                "type": "high_risk_consultation",
                "severity": "high",
                "title": "高风险咨询待闭环",
                "message": f"咨询 #{row.id} 为高风险且需要医生复核，当前状态 {row.status}。",
                "resource_type": "consultation",
                "resource_id": row.id,
                "created_at": row.created_at.isoformat(),
            }
        )

    failed_llm = (
        db.query(LLMCallLog)
        .filter(LLMCallLog.status != "success")
        .order_by(desc(LLMCallLog.created_at))
        .limit(10)
        .all()
    )
    for row in failed_llm:
        alerts.append(
            {
                "type": "llm_fallback",
                "severity": "medium",
                "title": "模型调用异常/降级",
                "message": f"咨询 #{row.consultation_id or '-'} 模型状态 {row.status}：{row.error_message or '已使用本地安全兜底'}。",
                "resource_type": "llm_call_log",
                "resource_id": row.id,
                "created_at": row.created_at.isoformat(),
            }
        )

    slow_llm = (
        db.query(LLMCallLog)
        .filter(LLMCallLog.latency_ms >= 15000)
        .order_by(desc(LLMCallLog.created_at))
        .limit(10)
        .all()
    )
    for row in slow_llm:
        alerts.append(
            {
                "type": "llm_high_latency",
                "severity": "medium",
                "title": "模型延迟过高",
                "message": f"咨询 #{row.consultation_id or '-'} 延迟 {row.latency_ms}ms，建议检查 DeepSeek 接口或网络。",
                "resource_type": "llm_call_log",
                "resource_id": row.id,
                "created_at": row.created_at.isoformat(),
            }
        )

    pending_data_requests = (
        db.query(DataAccessRequest)
        .filter(DataAccessRequest.status == "pending")
        .order_by(DataAccessRequest.created_at)
        .limit(20)
        .all()
    )
    for row in pending_data_requests:
        age_hours = (now - row.created_at).total_seconds() / 3600
        alerts.append(
            {
                "type": "privacy_request_pending",
                "severity": "medium" if age_hours >= 24 else "low",
                "title": "隐私数据请求待处理",
                "message": f"用户 {row.user_external_id} 的 {row.request_type} 请求待处理，范围：{row.data_scope}。",
                "resource_type": "data_access_request",
                "resource_id": row.id,
                "created_at": row.created_at.isoformat(),
            }
        )

    retrieval_evaluation = _shared.store.evaluate_recall()
    if float(retrieval_evaluation.get("hit_rate") or 0.0) < 0.8:
        alerts.append(
            {
                "type": "rag_recall_low",
                "severity": "high",
                "title": "RAG 召回率低于阈值",
                "message": f"当前命中率 {retrieval_evaluation.get('hit_rate')}，请检查 Chroma 入库和知识库版本。",
                "resource_type": "rag_evaluation",
                "resource_id": None,
                "created_at": now.isoformat(),
            }
        )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda item: (severity_rank.get(str(item["severity"]), 9), str(item["created_at"])), reverse=False)
    return {
        "generated_at": now.isoformat(),
        "counts": {
            "total": len(alerts),
            "high": sum(1 for item in alerts if item["severity"] == "high"),
            "medium": sum(1 for item in alerts if item["severity"] == "medium"),
            "low": sum(1 for item in alerts if item["severity"] == "low"),
        },
        "rag_evaluation": retrieval_evaluation,
        "alerts": alerts[:50],
    }
