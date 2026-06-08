from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agents.config import AgentConfig
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


class TriageAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        requires_review = self.config.requires_review
        
        next_actions = []
        if "紧急" in llm_result.content or "尽快" in llm_result.content:
            next_actions.append({
                "action": "handoff",
                "target_agent": "treatment",
                "reason": "评估为紧急情况，建议进一步诊疗方案分析"
            })
        
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
        )


class TreatmentAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        next_actions = [
            {
                "action": "handoff",
                "target_agent": "health",
                "reason": "治疗方案需要同步健康管理计划"
            }
        ]
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.88,
            requires_review=self.config.requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            next_actions=next_actions,
            trace=self._trace_for_hits(message, hits),
        )


class MedicationAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        next_actions = []
        if "禁忌" in llm_result.content or "风险" in llm_result.content:
            next_actions.append({
                "action": "review",
                "target_agent": "doctor",
                "reason": "发现用药风险，需要医生复核"
            })
        
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
        )


class ImagingAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        
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
        )


class HealthAgent(BaseAgent):
    def run(self, message: str, context: Dict[str, Any]) -> AgentOutput:
        hits = self.retrieve_knowledge(message)
        references = self._sources_from_hits(hits)
        
        llm_result = self.call_llm(message, context, hits)
        
        self.update_memory(message, llm_result.content)
        
        return AgentOutput(
            content=llm_result.content,
            agent_id=self.config.agent_id,
            agent_name=self.config.name,
            confidence=0.85,
            requires_review=self.config.requires_review,
            references=references,
            llm_meta=llm_result.meta.__dict__,
            trace=self._trace_for_hits(message, hits),
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
