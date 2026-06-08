from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage

from app.agents.base_agent import AgentFactory, AgentOutput, BaseAgent
from app.agents.router import AgentRouter
from app.rag.store import KnowledgeStore
from app.services.llm import LLMClient


def load_workflow_from_db(db, config_id: str = "default") -> Optional["WorkflowGraph"]:
    """Load workflow graph from database."""
    from app.models.entities import WorkflowConfig, WorkflowNode, WorkflowEdge
    
    config = db.query(WorkflowConfig).filter(WorkflowConfig.config_id == config_id).first()
    if not config:
        return None
    
    graph = WorkflowGraph()
    for node in config.nodes:
        graph.add_node(node.node_id, node.agent_id, node.label)
    
    for edge in config.edges:
        graph.add_edge(edge.source, edge.target, edge.condition, edge.label)
    
    return graph


def save_workflow_to_db(db, graph: "WorkflowGraph", config_id: str = "default", name: str = "默认工作流") -> None:
    """Save workflow graph to database."""
    from app.models.entities import WorkflowConfig, WorkflowNode, WorkflowEdge
    from datetime import datetime
    
    config = db.query(WorkflowConfig).filter(WorkflowConfig.config_id == config_id).first()
    if not config:
        config = WorkflowConfig(
            config_id=config_id,
            name=name,
            description="动态多智能体工作流配置",
            active=True,
            created_at=datetime.utcnow(),
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    db.query(WorkflowNode).filter(WorkflowNode.config_id == config.id).delete()
    db.query(WorkflowEdge).filter(WorkflowEdge.config_id == config.id).delete()
    
    for node in graph.nodes:
        db.add(WorkflowNode(
            config_id=config.id,
            node_id=node.node_id,
            agent_id=node.agent_id,
            label=node.label,
            type=node.type,
        ))
    
    for edge in graph.edges:
        db.add(WorkflowEdge(
            config_id=config.id,
            source=edge.source,
            target=edge.target,
            condition=edge.condition,
            label=edge.label,
        ))
    
    config.updated_at = datetime.utcnow()
    db.commit()


@dataclass
class WorkflowState:
    messages: List[BaseMessage] = field(default_factory=list)
    current_agent: str = ""
    outputs: Dict[str, AgentOutput] = field(default_factory=dict)
    handoffs: List[Dict[str, Any]] = field(default_factory=list)
    reviewed: bool = False
    completed: bool = False


@dataclass
class WorkflowNode:
    node_id: str
    agent_id: str
    label: str
    type: str = "agent"


@dataclass
class WorkflowEdge:
    source: str
    target: str
    condition: Optional[str] = None
    label: Optional[str] = None


@dataclass
class WorkflowGraph:
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    
    def add_node(self, node_id: str, agent_id: str, label: str) -> None:
        self.nodes.append(WorkflowNode(node_id=node_id, agent_id=agent_id, label=label))
    
    def add_edge(self, source: str, target: str, condition: Optional[str] = None, label: Optional[str] = None) -> None:
        self.edges.append(WorkflowEdge(source=source, target=target, condition=condition, label=label))
    
    def to_dot(self) -> str:
        lines = ["digraph workflow {"]
        for node in self.nodes:
            lines.append(f'  "{node.node_id}" [label="{node.label}", shape="box"]')
        for edge in self.edges:
            edge_label = f', label="{edge.label}"' if edge.label else ""
            lines.append(f'  "{edge.source}" -> "{edge.target}"{edge_label}')
        lines.append("}")
        return "\n".join(lines)


class MultiAgentWorkflow:
    def __init__(self, store: KnowledgeStore, llm: LLMClient, db=None):
        self.store = store
        self.llm = llm
        self.agents: Dict[str, BaseAgent] = {}
        self.workflow_graph = WorkflowGraph()
        self.router = AgentRouter()
        self._initialize_agents()
        if db is not None:
            self._load_graph_from_db(db)
        else:
            self._build_default_graph()
    
    def _initialize_agents(self) -> None:
        from app.agents.config import AgentConfigRegistry
        
        for agent_id in AgentConfigRegistry.keys():
            self.agents[agent_id] = AgentFactory.create(agent_id, self.store, self.llm)
    
    def _load_graph_from_db(self, db) -> None:
        """Load workflow graph from database, fallback to default if not found."""
        loaded_graph = load_workflow_from_db(db)
        if loaded_graph:
            self.workflow_graph = loaded_graph
        else:
            self._build_default_graph()
            save_workflow_to_db(db, self.workflow_graph)

    def load_graph_from_db(self, db) -> None:
        """Reload workflow graph from persisted configuration."""
        self._load_graph_from_db(db)
    
    def save_graph_to_db(self, db) -> None:
        """Save current workflow graph to database."""
        save_workflow_to_db(db, self.workflow_graph)
    
    def _build_default_graph(self) -> None:
        self.workflow_graph = WorkflowGraph()
        self.workflow_graph.add_node("start", "start", "开始")
        self.workflow_graph.add_node("router", "router", "意图路由")
        
        for agent_id, agent in self.agents.items():
            self.workflow_graph.add_node(agent_id, agent_id, agent.config.name)
        
        self.workflow_graph.add_node("review", "review", "医生复核")
        self.workflow_graph.add_node("end", "end", "结束")
        
        self.workflow_graph.add_edge("start", "router", label="用户请求")
        self.workflow_graph.add_edge("router", "triage", condition="症状相关", label="症状预问诊")
        self.workflow_graph.add_edge("router", "treatment", condition="方案相关", label="方案解读")
        self.workflow_graph.add_edge("router", "medication", condition="用药相关", label="用药审查")
        self.workflow_graph.add_edge("router", "imaging", condition="影像相关", label="影像解读")
        self.workflow_graph.add_edge("router", "health", condition="健康相关", label="健康管理")
        
        self.workflow_graph.add_edge("triage", "treatment", condition="需要方案", label="转诊治疗方案")
        self.workflow_graph.add_edge("triage", "medication", condition="涉及用药", label="用药审查")
        self.workflow_graph.add_edge("triage", "review", condition="紧急情况", label="医生复核")
        self.workflow_graph.add_edge("triage", "end", condition="常规咨询", label="直接结束")
        
        self.workflow_graph.add_edge("treatment", "medication", condition="涉及用药", label="用药审查")
        self.workflow_graph.add_edge("treatment", "health", label="健康管理")
        self.workflow_graph.add_edge("treatment", "review", condition="复杂方案", label="医生复核")
        self.workflow_graph.add_edge("treatment", "end", label="结束")
        
        self.workflow_graph.add_edge("medication", "review", condition="风险", label="医生复核")
        self.workflow_graph.add_edge("medication", "end", condition="安全", label="结束")
        
        self.workflow_graph.add_edge("imaging", "treatment", label="转诊治疗方案")
        self.workflow_graph.add_edge("imaging", "review", label="医生复核")
        
        self.workflow_graph.add_edge("health", "end", label="结束")
        self.workflow_graph.add_edge("review", "end", label="结束")
    
    def route(self, message: str) -> str:
        return self.router.plan(message).primary_agent
    
    def execute_agent(self, agent_id: str, message: str, context: Dict[str, Any]) -> AgentOutput:
        if agent_id not in self.agents:
            raise ValueError(f"Unknown agent: {agent_id}")
        
        agent = self.agents[agent_id]
        return agent.run(message, context)
    
    def run_workflow(self, initial_message: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        context = context or {}
        state = WorkflowState()
        results = []
        trace = [
            "动态多智能体 workflow：启动",
        ]
        
        requested_agent = context.get("requested_agent")
        agent_plan = context.get("agent_plan") or self.router.plan(initial_message, requested_agent=requested_agent).as_dict()
        planned_agents = _planned_agents(agent_plan)
        current_agent_id = requested_agent if requested_agent in self.agents else str(agent_plan.get("primary_agent") or self.route(initial_message))
        state.current_agent = current_agent_id
        trace.append(f"意图路由：{current_agent_id}")
        trace.append(
            "Router 计划："
            f"主智能体={agent_plan.get('primary_agent', current_agent_id)}，"
            f"次级智能体={','.join(agent_plan.get('secondary_agents') or []) or '无'}"
        )
        if agent_plan.get("risk_signals"):
            trace.append(f"Router 风险信号：{','.join(agent_plan.get('risk_signals') or [])}")
        
        visited_agents: List[str] = []
        
        while not state.completed:
            if current_agent_id in visited_agents:
                trace.append(f"循环保护：{current_agent_id} 已执行，停止")
                break
            
            visited_agents.append(current_agent_id)
            
            try:
                trace.append(f"{current_agent_id}：开始执行")
                output = self.execute_agent(current_agent_id, initial_message, context)
                state.outputs[current_agent_id] = output
                results.append({
                    "agent_id": current_agent_id,
                    "agent_name": output.agent_name,
                    "content": output.content,
                    "confidence": output.confidence,
                    "requires_review": output.requires_review,
                    "risk_level": output.agent_contract.get("risk_level", "medium" if output.requires_review else "low"),
                    "references": output.references,
                    "sources": output.references,
                    "llm_meta": output.llm_meta,
                    "next_actions": output.next_actions,
                    "trace": output.trace,
                    "agent_contract": output.agent_contract,
                })
                trace.extend(output.trace)
                
                if output.requires_review:
                    state.reviewed = True
                    trace.append(f"{current_agent_id}：标记需要医生复核")
                
                next_action = self._determine_next_action(current_agent_id, output, set(visited_agents), planned_agents)
                if next_action:
                    trace.append(f"{current_agent_id} -> {next_action}：按 workflow graph/交接动作进入下一智能体")
                    initial_message = f"基于前序结果继续处理：{output.content}"
                    current_agent_id = next_action
                else:
                    state.completed = True
                    trace.append(f"{current_agent_id}：无可执行下一跳，workflow 完成")
                    
            except Exception as e:
                state.completed = True
                trace.append(f"{current_agent_id}：执行异常 {e}")
                results.append({
                    "agent_id": current_agent_id,
                    "error": str(e),
                })
        
        return {
            "results": results,
            "requires_review": state.reviewed,
            "workflow_graph": self.workflow_graph.to_dot(),
            "visited_agents": visited_agents,
            "sources": _merge_sources(results),
            "trace": trace,
            "agent_plan": agent_plan,
        }
    
    def _determine_next_action(
        self,
        current_agent_id: str,
        output: AgentOutput,
        visited: set,
        planned_agents: List[str] | None = None,
    ) -> Optional[str]:
        graph_edges = [edge for edge in self.workflow_graph.edges if edge.source == current_agent_id]
        graph_next = self._next_agent_from_graph(current_agent_id, output, visited, graph_edges, planned_agents or [])
        if graph_next:
            return graph_next
        if graph_edges:
            return None
        for action in output.next_actions:
            if action.get("action") == "handoff":
                target_agent = action.get("target_agent")
                if target_agent and target_agent not in visited and target_agent in self.agents:
                    return target_agent
        return None

    def _next_agent_from_graph(
        self,
        current_agent_id: str,
        output: AgentOutput,
        visited: set,
        edges: List[WorkflowEdge],
        planned_agents: List[str],
    ) -> Optional[str]:
        if not edges:
            return None
        handoff_targets = [
            action.get("target_agent")
            for action in output.next_actions
            if action.get("action") == "handoff" and action.get("target_agent")
        ]
        handoff_targets.extend(agent_id for agent_id in planned_agents if agent_id != current_agent_id)
        if output.requires_review:
            handoff_targets.append("review")
        handoff_targets = _dedupe_agents(handoff_targets)
        if not handoff_targets:
            return None
        for edge in edges:
            node = self._node_by_id(edge.target)
            target_agent = node.agent_id if node else edge.target
            if target_agent in handoff_targets and target_agent in self.agents and target_agent not in visited:
                return target_agent
        return None

    def _node_by_id(self, node_id: str) -> Optional[WorkflowNode]:
        return next((node for node in self.workflow_graph.nodes if node.node_id == node_id), None)
    
    def get_graph_visualization(self) -> str:
        return self.workflow_graph.to_dot()
    
    def update_graph(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
        graph = WorkflowGraph()
        seen_nodes: set[str] = set()

        def add_node(node_id: str, agent_id: str, label: str) -> None:
            if node_id in seen_nodes:
                return
            graph.add_node(node_id=node_id, agent_id=agent_id, label=label)
            seen_nodes.add(node_id)

        required_nodes = [
            ("start", "start", "开始"),
            ("router", "router", "意图路由"),
            ("review", "review", "医生复核"),
            ("end", "end", "结束"),
        ]
        for node_id, agent_id, label in required_nodes:
            add_node(node_id, agent_id, label)

        for agent_id, agent in self.agents.items():
            add_node(agent_id, agent_id, agent.config.name)

        for node in nodes:
            node_id = str(node.get("node_id") or "").strip()
            if not node_id:
                continue
            agent_id = str(node.get("agent_id") or node_id)
            label = str(node.get("label") or node_id)
            add_node(node_id, agent_id, label)

        allowed_nodes = {node.node_id for node in graph.nodes}
        added_edges: set[tuple[str, str, str | None]] = set()

        def add_edge(source: str, target: str, condition: str | None = None, label: str | None = None) -> None:
            if source not in allowed_nodes or target not in allowed_nodes:
                return
            key = (source, target, label)
            if key in added_edges:
                return
            graph.add_edge(source=source, target=target, condition=condition, label=label)
            added_edges.add(key)

        if not edges:
            self.workflow_graph = graph
            self._build_default_edges_for_graph()
            return

        for edge in edges:
            add_edge(
                source=str(edge.get("source") or ""),
                target=str(edge.get("target") or ""),
                condition=edge.get("condition"),
                label=edge.get("label"),
            )
        add_edge("start", "router", label="用户请求")
        for agent_id in self.agents:
            add_edge("router", agent_id, label=f"路由到{self.agents[agent_id].config.name}")
        self.workflow_graph = graph

    def _build_default_edges_for_graph(self) -> None:
        self.workflow_graph.add_edge("start", "router", label="用户请求")
        for agent_id, agent in self.agents.items():
            self.workflow_graph.add_edge("router", agent_id, label=f"路由到{agent.config.name}")
        self.workflow_graph.add_edge("triage", "treatment", condition="需要方案", label="转诊治疗方案")
        self.workflow_graph.add_edge("triage", "medication", condition="涉及用药", label="用药审查")
        self.workflow_graph.add_edge("triage", "review", condition="紧急情况", label="医生复核")
        self.workflow_graph.add_edge("triage", "end", condition="常规咨询", label="直接结束")
        self.workflow_graph.add_edge("treatment", "medication", condition="涉及用药", label="用药审查")
        self.workflow_graph.add_edge("treatment", "health", label="健康管理")
        self.workflow_graph.add_edge("treatment", "review", condition="复杂方案", label="医生复核")
        self.workflow_graph.add_edge("treatment", "end", label="结束")
        self.workflow_graph.add_edge("medication", "review", condition="风险", label="医生复核")
        self.workflow_graph.add_edge("medication", "end", condition="安全", label="结束")
        self.workflow_graph.add_edge("imaging", "treatment", label="转诊治疗方案")
        self.workflow_graph.add_edge("imaging", "review", label="医生复核")
        self.workflow_graph.add_edge("health", "end", label="结束")
        self.workflow_graph.add_edge("review", "end", label="结束")


def _merge_sources(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for result in results:
        for source in result.get("sources", []) or []:
            source_id = str(source.get("id") or source.get("document_uid") or "")
            if not source_id:
                continue
            if source_id not in merged or float(source.get("score") or 0) > float(merged[source_id].get("score") or 0):
                merged[source_id] = source
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0), reverse=True)


def _planned_agents(agent_plan: dict[str, Any]) -> List[str]:
    agents = [str(agent_plan.get("primary_agent") or "")]
    agents.extend(str(agent_id) for agent_id in agent_plan.get("secondary_agents") or [])
    return _dedupe_agents(agents)


def _dedupe_agents(agent_ids: List[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for agent_id in agent_ids:
        if not agent_id or agent_id in {"start", "router", "review", "end"} or agent_id in seen:
            continue
        seen.add(agent_id)
        result.append(agent_id)
    return result
