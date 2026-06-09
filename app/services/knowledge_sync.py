"""Knowledge base synchronization service.

Relocated from app/api/routes.py during the phase-4 service extraction. Keeps
the runtime KnowledgeStore / orchestrator in sync with the admin-curated
knowledge_documents rows, and upserts knowledge_versions / knowledge_documents
from the in-memory store.

The orchestrator is rebound on the shared module (app.api._shared) so every
module that reads _shared.orchestrator observes the refreshed instance.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

import app.api._shared as _shared
from app.agents.orchestrator import OralAgentOrchestrator
from app.models.entities import KnowledgeDocument, KnowledgeVersion
from app.rag.store import KnowledgeDocument as StoreKnowledgeDocument
from app.services.traceability import _json_loads


def _upsert_knowledge_version(db: Session, metrics: dict[str, Any]) -> None:
    version = str(metrics["version"])
    row = db.query(KnowledgeVersion).filter(KnowledgeVersion.version == version).first()
    if row is None:
        row = KnowledgeVersion(
            version=version,
            title=str(metrics["title"]),
            document_count=int(metrics["document_count"]),
            retrieval_backend=str(metrics["retrieval_backend"]),
            quality_score=float(metrics["quality_score"]),
        )
        db.add(row)
    else:
        row.document_count = int(metrics["document_count"])
        row.retrieval_backend = str(metrics["retrieval_backend"])
        row.quality_score = float(metrics["quality_score"])
        row.active = True
    db.commit()
    db.refresh(row)
    _upsert_knowledge_documents(db, row.id)


def _upsert_knowledge_documents(db: Session, knowledge_version_id: int) -> None:
    for doc in _shared.store.documents:
        row = db.query(KnowledgeDocument).filter(KnowledgeDocument.doc_uid == doc.id).first()
        if row is None:
            row = KnowledgeDocument(
                knowledge_version_id=knowledge_version_id,
                doc_uid=doc.id,
                title=doc.title,
                category=doc.category,
                source=doc.source,
                tags_json=json.dumps(doc.tags, ensure_ascii=False),
                content=doc.content,
            )
            db.add(row)
        else:
            row.knowledge_version_id = knowledge_version_id
            row.title = doc.title
            row.category = doc.category
            row.source = doc.source
            row.tags_json = json.dumps(doc.tags, ensure_ascii=False)
            row.content = doc.content
            row.active = True
    db.commit()


def _sync_runtime_knowledge_from_db(db: Session) -> dict[str, Any]:
    rows = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.active.is_(True))
        .order_by(KnowledgeDocument.id)
        .all()
    )
    admin_docs = [
        StoreKnowledgeDocument(
            id=row.doc_uid,
            title=row.title,
            category=row.category,
            source=row.source,
            tags=list(_json_loads(row.tags_json, [])),
            content=row.content,
        )
        for row in rows
        if row.doc_uid.startswith("admin-") and not _is_runtime_test_knowledge(row)
    ]
    _shared.store.sync_admin_documents(admin_docs)
    _shared.orchestrator = OralAgentOrchestrator(store=_shared.store)
    _shared.orchestrator.load_workflow_from_db(db)
    metrics = _shared.store.quality_metrics()
    return {
        "ok": True,
        "admin_document_count": len(admin_docs),
        "runtime_document_count": metrics["document_count"],
        "retrieval_backend": metrics["retrieval_backend"],
        "chroma_error": metrics.get("chroma_error"),
    }


def _is_runtime_test_knowledge(row: KnowledgeDocument) -> bool:
    text = f"{row.doc_uid} {row.title} {row.source} {row.tags_json} {row.content}"
    markers = ["ASCII_RAG_TEST", "斑马测试词", "????", "测试词"]
    return any(marker in text for marker in markers)
