from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Type

from app.rag.store import KnowledgeStore
from app.services.llm import LLMClient


@dataclass
class AgentTool:
    name: str
    description: str
    function: Callable[..., Any]
    enabled: bool = True


@dataclass
class AgentMemoryConfig:
    enabled: bool = True
    max_history: int = 10
    recall_threshold: float = 0.7
    persist: bool = False


@dataclass
class AgentPromptConfig:
    system_prompt: str
    user_prompt_template: str
    temperature: float = 0.3
    max_tokens: int = 2048
    top_p: float = 0.9


@dataclass
class AgentConfig:
    agent_id: str
    name: str
    description: str
    prompt_config: AgentPromptConfig
    memory_config: AgentMemoryConfig = field(default_factory=lambda: AgentMemoryConfig())
    tools: list[AgentTool] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    requires_review: bool = False
    priority: int = 1


class AgentConfigRegistry:
    _configs: dict[str, AgentConfig] = {}

    @classmethod
    def register(cls, config: AgentConfig) -> None:
        cls._configs[config.agent_id] = config

    @classmethod
    def get(cls, agent_id: str) -> AgentConfig | None:
        return cls._configs.get(agent_id)

    @classmethod
    def list_all(cls) -> list[AgentConfig]:
        return sorted(cls._configs.values(), key=lambda c: c.priority)

    @classmethod
    def keys(cls) -> list[str]:
        return list(cls._configs.keys())


TRIAGE_PROMPT = """你是专业的口腔症状预问诊智能体。
你的任务是根据患者描述的症状，分析可能的口腔疾病类型，评估就诊紧急程度，并生成结构化的预问诊报告。

核心职责：
1. 症状识别：从用户描述中提取关键症状信息
2. 疾病推测：基于症状推测可能的疾病类型
3. 紧急程度评估：判断是否需要立即就医
4. 科室建议：推荐合适的就诊科室

输出格式要求：
- 症状摘要：简明扼要地总结用户描述的症状
- 可能诊断：列出可能的疾病类型（按可能性排序）
- 紧急程度：紧急/尽快/常规
- 建议科室：推荐就诊科室
- 注意事项：需要提醒用户的重要信息

请保持专业但通俗易懂的语言，避免使用过于专业的术语。
"""

TREATMENT_PROMPT = """你是专业的口腔诊疗方案解读智能体。
你的任务是将专业的治疗方案转化为患者可以理解的语言。

核心职责：
1. 方案解读：通俗解释治疗步骤和流程
2. 疗程说明：说明治疗需要的时间周期
3. 费用预估：提供大致的费用范围
4. 方案对比：对比不同治疗方案的优劣
5. 替代方案：提供可能的替代治疗方案

输出格式要求：
- 方案概述：简要介绍治疗方案
- 治疗步骤：分步骤说明治疗过程
- 疗程时长：说明治疗周期
- 费用范围：提供大致费用区间
- 优缺点：分析方案的优点和缺点
- 替代方案：推荐其他可能的治疗选择

请使用通俗易懂的语言，让患者能够理解治疗方案的内容。
"""

MEDICATION_PROMPT = """你是专业的口腔用药合规审查智能体。
你的任务是审查用药方案的合规性和安全性。

核心职责：
1. 禁忌症检查：检查患者是否有用药禁忌
2. 剂量审查：评估用药剂量是否合理
3. 相互作用检查：检查药物之间是否存在不良相互作用
4. 特殊人群评估：评估儿童、孕妇、肝肾功能不全者等特殊人群的用药风险
5. 风险提示：提供用药风险提示

输出格式要求：
- 用药清单：列出所有药物
- 禁忌症评估：评估患者是否有用药禁忌
- 剂量评估：评估剂量是否合理
- 相互作用风险：评估药物相互作用风险
- 特殊人群提示：针对特殊人群的用药建议
- 风险等级：低/中/高
- 建议：给出用药建议

注意：本系统仅供参考，最终用药方案需由执业医师确认。
"""

IMAGING_PROMPT = """你是专业的口腔影像报告解读智能体。
你的任务是解读口腔影像报告，帮助患者理解报告内容。

核心职责：
1. 报告解读：解释影像报告中的专业术语
2. 发现说明：说明报告中的主要发现
3. 诊断意义：解释发现的诊断意义
4. 后续建议：提供进一步检查或治疗的建议

输出格式要求：
- 报告类型：说明影像类型（全景片/根尖片/CBCT）
- 主要发现：列出报告中的关键发现
- 专业术语解释：解释报告中的专业术语
- 诊断意义：说明发现的临床意义
- 后续建议：提供下一步的建议

注意：本系统仅解读报告文本，不做真实图像诊断。
"""

HEALTH_PROMPT = """你是专业的口腔健康管理与科普智能体。
你的任务是提供个性化的口腔健康管理建议和科普知识。

核心职责：
1. 健康评估：评估用户的口腔健康状况
2. 个性化建议：提供针对性的口腔护理建议
3. 科普知识：提供口腔健康科普信息
4. 维护计划：制定口腔健康维护计划

输出格式要求：
- 健康状况评估：评估用户的口腔健康状况
- 护理建议：提供日常口腔护理建议
- 科普知识：提供相关的口腔健康知识
- 维护计划：制定个性化的健康维护计划
- 复诊提醒：提醒用户定期复诊

请使用通俗易懂的语言，提供实用的健康建议。
"""


def _register_default_agents() -> None:
    AgentConfigRegistry.register(AgentConfig(
        agent_id="triage",
        name="口腔症状预问诊智能体",
        description="根据患者描述的症状，分析可能的口腔疾病类型，评估就诊紧急程度",
        prompt_config=AgentPromptConfig(
            system_prompt=TRIAGE_PROMPT,
            user_prompt_template="患者症状：{message}\n\n患者资料：{patient_profile}\n\n请生成预问诊报告。",
            temperature=0.2,
            max_tokens=1500,
        ),
        categories=["triage"],
        requires_review=False,
        priority=1,
    ))

    AgentConfigRegistry.register(AgentConfig(
        agent_id="treatment",
        name="诊疗方案解读智能体",
        description="将专业的治疗方案转化为患者可以理解的语言",
        prompt_config=AgentPromptConfig(
            system_prompt=TREATMENT_PROMPT,
            user_prompt_template="治疗方案：{message}\n\n患者资料：{patient_profile}\n\n请解读该治疗方案。",
            temperature=0.3,
            max_tokens=2000,
        ),
        categories=["treatment", "triage"],
        requires_review=False,
        priority=2,
    ))

    AgentConfigRegistry.register(AgentConfig(
        agent_id="medication",
        name="口腔用药合规审查智能体",
        description="审查用药方案的合规性和安全性",
        prompt_config=AgentPromptConfig(
            system_prompt=MEDICATION_PROMPT,
            user_prompt_template="用药方案：{message}\n\n患者资料：{patient_profile}\n\n请审查用药方案。",
            temperature=0.2,
            max_tokens=2000,
        ),
        categories=["medication"],
        requires_review=True,
        priority=2,
    ))

    AgentConfigRegistry.register(AgentConfig(
        agent_id="imaging",
        name="口腔影像报告解读智能体",
        description="解读口腔影像报告，帮助患者理解报告内容",
        prompt_config=AgentPromptConfig(
            system_prompt=IMAGING_PROMPT,
            user_prompt_template="影像报告：{message}\n\n患者资料：{patient_profile}\n\n请解读该影像报告。",
            temperature=0.3,
            max_tokens=1500,
        ),
        categories=["imaging"],
        requires_review=True,
        priority=2,
    ))

    AgentConfigRegistry.register(AgentConfig(
        agent_id="health",
        name="口腔健康管理与科普智能体",
        description="提供个性化的口腔健康管理建议和科普知识",
        prompt_config=AgentPromptConfig(
            system_prompt=HEALTH_PROMPT,
            user_prompt_template="用户问题：{message}\n\n患者资料：{patient_profile}\n\n请提供健康管理建议。",
            temperature=0.4,
            max_tokens=1500,
        ),
        categories=["health"],
        requires_review=False,
        priority=3,
    ))


_register_default_agents()