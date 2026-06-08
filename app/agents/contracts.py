from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RiskLevel = Literal["low", "medium", "high"]
AGENT_OUTPUT_PROTOCOL_VERSION = "agent-output-v1"
REQUIRED_AGENT_CONTRACT_KEYS = {
    "protocol_version",
    "agent_id",
    "agent_name",
    "summary",
    "evidence",
    "risk_tips",
    "next_steps",
    "doctor_review_required",
    "risk_level",
    "refusal",
    "sources",
    "agent_trace",
    "safety_flags",
    "structured_data",
}


@dataclass(frozen=True)
class AgentPlan:
    intent: str
    primary_agent: str
    secondary_agents: list[str] = field(default_factory=list)
    risk_signals: list[str] = field(default_factory=list)
    retrieval_queries: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    doctor_review_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentContract:
    agent_id: str
    agent_name: str
    summary: str
    evidence: list[str]
    risk_tips: list[str]
    next_steps: list[str]
    doctor_review_required: bool
    risk_level: RiskLevel
    refusal: bool
    sources: list[dict[str, Any]]
    agent_trace: list[str]
    safety_flags: list[str]
    structured_data: dict[str, Any]
    llm_meta: dict[str, Any] | None = None
    protocol_version: str = AGENT_OUTPUT_PROTOCOL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "summary": self.summary,
            "evidence": self.evidence,
            "risk_tips": self.risk_tips,
            "next_steps": self.next_steps,
            "doctor_review_required": self.doctor_review_required,
            "risk_level": self.risk_level,
            "refusal": self.refusal,
            "sources": self.sources,
            "agent_trace": self.agent_trace,
            "safety_flags": self.safety_flags,
            "structured_data": self.structured_data,
            "llm_meta": self.llm_meta,
        }


def build_agent_contract(
    *,
    agent_id: str,
    agent_name: str,
    summary: str,
    evidence: list[str] | None = None,
    risk_tips: list[str] | None = None,
    next_steps: list[str] | None = None,
    doctor_review_required: bool = False,
    risk_level: str = "low",
    refusal: bool = False,
    sources: list[Any] | None = None,
    agent_trace: list[str] | None = None,
    safety_flags: list[str] | None = None,
    structured_data: dict[str, Any] | None = None,
    llm_meta: dict[str, Any] | None = None,
) -> AgentContract:
    return AgentContract(
        agent_id=str(agent_id),
        agent_name=str(agent_name),
        summary=str(summary or ""),
        evidence=_dedupe_text(evidence or []),
        risk_tips=_dedupe_text(risk_tips or []),
        next_steps=_dedupe_text(next_steps or []),
        doctor_review_required=bool(doctor_review_required),
        risk_level=normalize_risk_level(risk_level),
        refusal=bool(refusal),
        sources=normalize_sources(sources or []),
        agent_trace=_dedupe_text(agent_trace or []),
        safety_flags=_dedupe_text(safety_flags or []),
        structured_data=structured_data or {},
        llm_meta=llm_meta,
    )


def contract_from_agent_response(response: Any) -> dict[str, Any]:
    structured_data = dict(getattr(response, "structured_data", None) or {})
    structured_data.pop("agent_contract", None)
    return build_agent_contract(
        agent_id=getattr(response, "agent_type", ""),
        agent_name=getattr(response, "agent_name", ""),
        summary=getattr(response, "summary", ""),
        evidence=list(getattr(response, "evidence", []) or []),
        risk_tips=list(getattr(response, "risk_tips", []) or []),
        next_steps=list(getattr(response, "next_steps", []) or []),
        doctor_review_required=bool(getattr(response, "doctor_review_required", False)),
        risk_level=str(getattr(response, "risk_level", "low")),
        refusal=bool(getattr(response, "refusal", False)),
        sources=list(getattr(response, "sources", []) or []),
        agent_trace=list(getattr(response, "agent_trace", []) or []),
        safety_flags=list(getattr(response, "safety_flags", []) or []),
        structured_data=structured_data,
        llm_meta=getattr(response, "llm_meta", None),
    ).as_dict()


def normalize_risk_level(value: str, default: RiskLevel = "low") -> RiskLevel:
    normalized = str(value or default).lower().strip()
    if normalized in {"low", "medium", "high"}:
        return normalized  # type: ignore[return-value]
    if normalized in {"中", "中等", "moderate"}:
        return "medium"
    if normalized in {"高", "urgent", "critical"}:
        return "high"
    return default


def normalize_sources(sources: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sources:
        source = _source_to_dict(item)
        source_id = str(source.get("id") or source.get("document_uid") or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        normalized.append(
            {
                "id": source_id,
                "title": str(source.get("title") or ""),
                "category": str(source.get("category") or ""),
                "source": str(source.get("source") or ""),
                "score": _float_or_zero(source.get("score")),
                "excerpt": str(source.get("excerpt") or ""),
            }
        )
    return normalized


def validate_contract(contract: dict[str, Any]) -> list[str]:
    missing = sorted(REQUIRED_AGENT_CONTRACT_KEYS - set(contract))
    invalid = []
    if contract.get("risk_level") not in {"low", "medium", "high"}:
        invalid.append("risk_level")
    if not isinstance(contract.get("sources"), list):
        invalid.append("sources")
    if not isinstance(contract.get("agent_trace"), list):
        invalid.append("agent_trace")
    return missing + invalid


def _source_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    result = {}
    for key in ("id", "document_uid", "title", "category", "source", "score", "excerpt"):
        if hasattr(item, key):
            result[key] = getattr(item, key)
    return result


def _dedupe_text(items: list[Any]) -> list[str]:
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
