from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agents import domain_rules
from app.agents.config import AgentConfig
from app.agents.contracts import build_agent_contract
from app.rag.store import KnowledgeStore, RetrievalHit
from app.services.llm import LLMClient, LLMResult


@dataclass
class AgentMemory:
    history: List[Dict[str, Any]] = field(default_factory=list)
    max_history: int = 10

    def add(self, entry: Dict[str, Any]) -> None:
        self.history.append(entry)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def get_relevant(self, query: str, threshold: float = 0.7) -> List[Dict[str, Any]]:
        return self.history

    def clear(self) -> None:
        self.history.clear()


@dataclass
class AgentTask:
    task_id: str
    agent_id: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None


@dataclass
class AgentOutput:
    content: str
    agent_id: str
    agent_name: str
    confidence: float = 0.0
    requires_review: bool = False
    references: List[Dict[str, Any]] = field(default_factory=list)
    llm_meta: Dict[str, Any] | None = None
    next_actions: List[Dict[str, Any]] = field(default_factory=list)
    task_handoffs: List[AgentTask] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)
    agent_contract: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig, store: KnowledgeStore, llm: LLMClient):
        self.config = config
        self.store = store
        self.llm = llm
        self.memory = AgentMemory(max_history=config.memory_config.max_history)

    @abstractmethod
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        pass

    def retrieve_knowledge(self, query: str, top_k: int = 5) -> List[RetrievalHit]:
        return self.store.retrieve(query, categories=self.config.categories, top_k=top_k)

    def format_prompt(self, message: str, context: Dict[str, Any]) -> str:
        patient_profile = context.get("patient_profile", {})
        return self.config.prompt_config.user_prompt_template.format(
            message=message,
            patient_profile=str(patient_profile)
        )

    def call_llm(self, message: str, context: Dict[str, Any], hits: List[RetrievalHit] | None = None) -> LLMResult:
        system_prompt = self.config.prompt_config.system_prompt
        user_prompt = self.format_prompt(message, context)
        if hits:
            evidence_text = "\n".join(
                f"- {hit.document.title}（{hit.document.source}，score={hit.score:.3f}）：{hit.excerpt}"
                for hit in hits[:5]
            )
            user_prompt = f"{user_prompt}\n\n检索依据：\n{evidence_text}"
        
        return self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self.config.prompt_config.temperature,
            max_tokens=self.config.prompt_config.max_tokens,
        )

    def update_memory(self, message: str, response: str) -> None:
        if self.config.memory_config.enabled:
            self.memory.add({
                "message": message,
                "response": response,
                "timestamp": self._get_timestamp(),
            })

    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.utcnow().isoformat()

    def _sources_from_hits(self, hits: List[RetrievalHit]) -> List[Dict[str, Any]]:
        return [hit.as_source() for hit in hits]

    def _trace_for_hits(self, message: str, hits: List[RetrievalHit]) -> List[str]:
        return [
            f"{self.config.name}：接收任务",
            f"{self.config.name}：按分类 {','.join(self.config.categories) or '全部'} 检索，命中 {len(hits)} 条",
            f"{self.config.name}：生成回答并给出下一步动作",
        ]

    def _contract_for_output(
        self,
        *,
        message: str,
        content: str,
        hits: List[RetrievalHit],
        requires_review: bool,
        llm_meta: Dict[str, Any] | None,
        next_actions: List[Dict[str, Any]] | None = None,
        risk_level: str | None = None,
        risk_tips: List[str] | None = None,
        next_steps: List[str] | None = None,
        safety_flags: List[str] | None = None,
        structured_data: Dict[str, Any] | None = None,
        refusal: bool = False,
    ) -> Dict[str, Any]:
        action_steps = [
            str(action.get("reason") or action.get("action") or "")
            for action in (next_actions or [])
            if action.get("reason") or action.get("action")
        ]
        default_risk_tips = ["AI 输出仅作口腔医疗辅助参考，需结合医生面诊和检查结果。"]
        if not hits:
            default_risk_tips.append("未命中可引用知识来源时，应转医生复核或补充信息。")
            safety_flags = list(safety_flags or []) + ["low_retrieval_confidence"]
            requires_review = True
        structured_payload = {
            "rag_plan": _rag_plan_for_hits(
                agent_id=self.config.agent_id,
                categories=self.config.categories,
                hits=hits,
                query=message,
            )
        }
        structured_payload.update(structured_data or {})
        return build_agent_contract(
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            summary=content,
            evidence=[hit.excerpt for hit in hits[:3]],
            risk_tips=risk_tips or default_risk_tips,
            next_steps=next_steps or action_steps or ["查看来源依据，并在必要时交由医生复核。"],
            doctor_review_required=requires_review,
            risk_level=risk_level or ("medium" if requires_review else "low"),
            refusal=refusal,
            sources=self._sources_from_hits(hits),
            agent_trace=self._trace_for_hits("", hits),
            safety_flags=safety_flags or [],
            structured_data=structured_payload,
            llm_meta=llm_meta,
        ).as_dict()


class TriageAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        domain_payload = domain_rules.structured_output_for_agent(
            "triage",
            message,
            context.get("patient_profile"),
        )
        triage_report = domain_payload.get("triage_report", {})
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        requires_review = self.config.requires_review or bool(triage_report.get("doctor_review_required"))
        
        next_actions = []
        if triage_report.get("urgency_level") in {"urgent", "soon"} or "紧急" in llm_result.content or "尽快" in llm_result.content:
            next_actions.append({
                "action": "handoff",
                "target_agent": "treatment",
                "reason": "评估为紧急情况，建议进一步诊疗方案分析"
            })
        risk_level = {"urgent": "high", "soon": "medium", "routine": "low"}.get(
            str(triage_report.get("urgency_level") or "routine"),
            "low",
        )
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.85,
            requires_review=requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            next_actions=next_actions,
            trace=self._trace_for_hits(message, hits),
            agent_contract=self._contract_for_output(
                message=message,
                content=llm_result.content,
                hits=hits,
                requires_review=requires_review,
                llm_meta=llm_result.meta.__dict__,
                next_actions=next_actions,
                risk_level=risk_level,
                risk_tips=["预问诊结果不能替代面诊诊断；急性肿胀、发热、吞咽或呼吸异常需线下急诊。"],
                next_steps=["补充牙位、持续时间、诱因和伴随症状", "根据风险等级预约对应口腔专科或医生复核"],
                safety_flags=["triage_red_flags"] if triage_report.get("red_flags") else [],
                structured_data=domain_payload,
            ),
        )


class TreatmentAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        domain_payload = domain_rules.structured_output_for_agent(
            "treatment",
            message,
            context.get("patient_profile"),
        )
        comparison = domain_payload.get("treatment_comparison", {})
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        next_actions = [
            {
                "action": "handoff",
                "target_agent": "health",
                "reason": "治疗方案需要同步健康管理计划"
            }
        ]
        requires_review = self.config.requires_review or bool(comparison.get("doctor_review_required"))

        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.88,
            requires_review=requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            next_actions=next_actions,
            trace=self._trace_for_hits(message, hits),
            agent_contract=self._contract_for_output(
                message=message,
                content=llm_result.content,
                hits=hits,
                requires_review=requires_review,
                llm_meta=llm_result.meta.__dict__,
                next_actions=next_actions,
                risk_level=str(comparison.get("risk_level") or "low"),
                risk_tips=["治疗方案需结合临床检查、影像资料、牙周状况和医生面诊判断。"],
                next_steps=["向医生确认治疗目标、复诊次数、费用构成、替代方案和术后维护计划"],
                safety_flags=["complex_treatment_plan"] if comparison.get("complexity_flags") else [],
                structured_data=domain_payload,
            ),
        )


class MedicationAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        domain_payload = domain_rules.structured_output_for_agent(
            "medication",
            message,
            context.get("patient_profile"),
        )
        medication_check = domain_payload.get("medication_check", {})
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        next_actions = []
        if medication_check.get("contraindications") or medication_check.get("interactions") or medication_check.get("boundary_violations") or "禁忌" in llm_result.content or "风险" in llm_result.content:
            next_actions.append({
                "action": "review",
                "target_agent": "doctor",
                "reason": "发现用药风险，需要医生复核"
            })
        safety_flags = ["medication_review_required"]
        if medication_check.get("contraindications"):
            safety_flags.append("medication_contraindication")
        if medication_check.get("interactions"):
            safety_flags.append("drug_interaction_risk")
        if any(alert.get("type") == "allergy" for alert in medication_check.get("patient_specific_alerts", [])):
            safety_flags.append("allergy_risk")
        risk_level = "high" if medication_check.get("contraindications") else "medium"
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.92,
            requires_review=self.config.requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            next_actions=next_actions,
            trace=self._trace_for_hits(message, hits),
            agent_contract=self._contract_for_output(
                message=message,
                content=llm_result.content,
                hits=hits,
                requires_review=self.config.requires_review,
                llm_meta=llm_result.meta.__dict__,
                next_actions=next_actions,
                risk_level=risk_level,
                risk_tips=["用药问题必须核查年龄、孕期、过敏史、基础病、剂量和相互作用；平台不自动开具处方。"],
                next_steps=["补充完整用药上下文", "由医生或药师复核后再调整药物或剂量"],
                safety_flags=safety_flags,
                structured_data=domain_payload,
            ),
        )


class ImagingAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        domain_payload = domain_rules.structured_output_for_agent(
            "imaging",
            message,
            context.get("patient_profile"),
            has_image=bool(context.get("has_image")),
        )
        analysis = domain_payload.get("imaging_report_analysis", {})
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        next_actions = [
            {
                "action": "handoff",
                "target_agent": "treatment",
                "reason": "影像结果需要结合诊疗方案分析"
            },
            {
                "action": "review",
                "target_agent": "doctor",
                "reason": "影像解读需要医生确认"
            }
        ]
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.80,
            requires_review=self.config.requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            next_actions=next_actions,
            trace=self._trace_for_hits(message, hits),
            agent_contract=self._contract_for_output(
                message=message,
                content=llm_result.content,
                hits=hits,
                requires_review=self.config.requires_review,
                llm_meta=llm_result.meta.__dict__,
                next_actions=next_actions,
                risk_level=str(analysis.get("risk_level") or "medium"),
                risk_tips=["仅解读影像报告文本；上传图片只做预览/归档，不输出真实图像诊断。"],
                next_steps=["携带原始影像和报告到口腔医生处复核", "结合口内检查后确定治疗方案"],
                safety_flags=["visual_diagnosis_disabled"],
                structured_data=domain_payload,
            ),
        )


class HealthAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        domain_payload = domain_rules.structured_output_for_agent(
            "health",
            message,
            context.get("patient_profile"),
        )
        health_plan = domain_payload.get("health_plan", {})
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.85,
            requires_review=self.config.requires_review or bool(health_plan.get("doctor_review_required")),
            references=references,
            llm_meta=llm_result.meta.__dict__,
            trace=self._trace_for_hits(message, hits),
            agent_contract=self._contract_for_output(
                message=message,
                content=llm_result.content,
                hits=hits,
                requires_review=self.config.requires_review or bool(health_plan.get("doctor_review_required")),
                llm_meta=llm_result.meta.__dict__,
                risk_level=str(health_plan.get("risk_level") or "low"),
                risk_tips=["健康管理建议需随龋风险、牙周状态、治疗记录和医生复查结果动态调整。"],
                next_steps=["建立复诊提醒", "记录刷牙、牙线、涂氟、洁牙和治疗维护情况"],
                safety_flags=["health_plan_review_required"] if health_plan.get("doctor_review_required") else [],
                structured_data=domain_payload,
            ),
        )


class AgentFactory:
    _agent_classes: Dict[str, type] = {
        "triage": TriageAgent,
        "treatment": TreatmentAgent,
        "medication": MedicationAgent,
        "imaging": ImagingAgent,
        "health": HealthAgent,
    }

    @classmethod
    def create(cls, agent_id: str, store: KnowledgeStore, llm: LLMClient) -> BaseAgent:
        from app.agents.config import AgentConfigRegistry
        
        config = AgentConfigRegistry.get(agent_id)
        if not config:
            raise ValueError(f"Unknown agent: {agent_id}")
        
        agent_class = cls._agent_classes.get(agent_id)
        if not agent_class:
            raise ValueError(f"No implementation for agent: {agent_id}")
        
        return agent_class(config, store, llm)

    @classmethod
    def register_agent_class(cls, agent_id: str, agent_class: type) -> None:
        cls._agent_classes[agent_id] = agent_class


def _rag_plan_for_hits(agent_id: str, categories: List[str], hits: List[RetrievalHit], query: str = "") -> Dict[str, Any]:
    source_ids = [hit.document.id for hit in hits]
    hit_categories = sorted({hit.document.category for hit in hits})
    confidence = 0.0 if not hits else min(round((min(len(hits), 5) / 5 * 0.7) + 0.3, 3), 1.0)
    return {
        "agent_type": agent_id,
        "sub_questions": [],
        "retrieval_categories": categories,
        "round_count": 1,
        "steps": [
            {
                "name": "workflow_agent_retrieve",
                "query": query,
                "categories": categories,
                "hit_count": len(hits),
                "hits": [hit.as_source() for hit in hits],
            }
        ],
        "merged_source_ids": source_ids,
        "confidence_score": confidence,
        "source_coverage": {
            "round_count": 1,
            "covered_round_count": 1 if hits else 0,
            "source_count": len(hits),
            "retrieved_categories": hit_categories,
            "requested_categories": categories,
        },
    }
