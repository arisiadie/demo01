from __future__ import annotations

from dataclasses import dataclass

from langchain_core.runnables import RunnableLambda, RunnableSequence

from app.rag.store import KnowledgeStore, RetrievalHit


@dataclass(frozen=True)
class RetrievalStep:
    name: str
    query: str
    categories: list[str]
    hits: list[RetrievalHit]


@dataclass(frozen=True)
class AgenticPlan:
    agent_type: str
    sub_questions: list[str]
    steps: list[RetrievalStep]
    merged_hits: list[RetrievalHit]
    trace: list[str]


class AgenticRAGFlow:
    """LangChain Runnable-based planner for multi-step retrieval."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store
        self.chain: RunnableSequence = (
            RunnableLambda(self._decompose)
            | RunnableLambda(self._multi_retrieve)
            | RunnableLambda(self._merge)
        )

    def run(self, *, message: str, agent_type: str, categories: list[str], top_k: int = 5) -> AgenticPlan:
        return self.chain.invoke(
            {
                "message": message,
                "agent_type": agent_type,
                "categories": categories,
                "top_k": top_k,
            }
        )

    def _decompose(self, payload: dict) -> dict:
        message = str(payload["message"])
        agent_type = str(payload["agent_type"])
        sub_questions = _sub_questions(message, agent_type)
        return {**payload, "sub_questions": sub_questions}

    def _multi_retrieve(self, payload: dict) -> dict:
        steps: list[RetrievalStep] = []
        categories = list(payload["categories"])
        top_k = int(payload["top_k"])
        for index, query in enumerate(payload["sub_questions"], start=1):
            hits = self.store.retrieve(query, categories=categories, top_k=top_k)
            steps.append(RetrievalStep(name=f"round_{index}", query=query, categories=categories, hits=hits))
        return {**payload, "steps": steps}

    def _merge(self, payload: dict) -> AgenticPlan:
        seen: set[str] = set()
        merged: list[RetrievalHit] = []
        for step in payload["steps"]:
            for hit in step.hits:
                if hit.document.id in seen:
                    continue
                seen.add(hit.document.id)
                merged.append(hit)
        merged.sort(key=lambda hit: hit.score, reverse=True)
        trace = [
            "LangChain Runnable 编排：问题拆解 -> 多轮检索 -> 结果合并",
            f"问题拆解：{' | '.join(payload['sub_questions'])}",
        ]
        for step in payload["steps"]:
            trace.append(f"{step.name} 检索：{step.query}，命中 {len(step.hits)} 条")
        return AgenticPlan(
            agent_type=str(payload["agent_type"]),
            sub_questions=list(payload["sub_questions"]),
            steps=list(payload["steps"]),
            merged_hits=merged[: int(payload["top_k"])],
            trace=trace,
        )


def _sub_questions(message: str, agent_type: str) -> list[str]:
    if agent_type == "triage":
        return [
            message,
            f"{message} 牙位 持续时间 伴随症状 紧急程度",
            f"{message} 龋病 牙髓炎 牙周炎 冠周炎 黏膜病 鉴别",
        ]
    if agent_type == "medication":
        return [
            message,
            f"{message} 年龄 妊娠 基础疾病 过敏史 禁忌",
            f"{message} 剂量 相互作用 儿童 老人 用药安全",
        ]
    if agent_type == "imaging":
        return [
            message,
            f"{message} 全景片 根尖片 CBCT 报告术语 解读",
            f"{message} 阻生齿 根尖周 骨吸收 种植位点",
        ]
    if agent_type == "treatment":
        return [
            message,
            f"{message} 治疗步骤 疗程 复诊 费用构成",
            f"{message} 优劣对比 替代方案 风险 医生复核",
        ]
    return [
        message,
        f"{message} 年龄阶段 刷牙 牙线 冲牙器 洁牙",
        f"{message} 窝沟封闭 涂氟 正畸复诊 种植维护",
    ]

