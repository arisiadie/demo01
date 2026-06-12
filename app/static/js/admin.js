import { request } from "./shared/api.js";
import { getCurrentUser } from "./shared/state.js";
import { logout, requireRole } from "./shared/auth.js";
import { showToast, setStatus, renderSimpleTable, flushPendingToast } from "./shared/components.js";
import {
  escapeHtml,
  formatDate,
  riskLabel,
  agentLabel,
  agentRoleLabel,
  getCategoryName,
  getFailureTypeName,
  dataRequestTypeLabel,
  dataRequestStatusLabel,
} from "./shared/format.js";
import { renderSources, renderLlmCalls, renderReviewStatus } from "./shared/result.js";
import { normalizeRagEvaluation } from "./shared/normalizers.js";
import { initNav, setPageTitle, showSkeleton, setError } from "./shared/view.js";
import { cachedRequest, invalidateCache } from "./shared/cache.js";
import { validateKnowledgeDocument, validateWorkflowGraph } from "./shared/validators.js";
import { clearFormErrors, applyErrors } from "./shared/form.js";

const SECTION_TITLES = {
  dashboard: "首页概览",
  knowledge: "知识库管理",
  rag: "RAG 评测",
  workflow: "Workflow 配置",
  llm: "模型调用监控",
  trace: "咨询链路追踪",
  audit: "审计日志",
  privacy: "隐私合规",
  alerts: "异常告警",
};
const els = {};

function cacheEls() {
  const ids = [
    "currentUserText", "logoutBtn", "metricGrid", "dashboardExtra",
    "knowledgeBox", "workflowJsonInput", "workflowPreview",
    "knowledgeTitleInput", "knowledgeCategoryInput", "knowledgeSourceInput", "knowledgeContentInput",
    "ragBox", "llmBox", "traceBox", "auditBox", "privacyBox", "alertsBox",
    "ragEvalBtn", "llmMetricsBtn", "adminAlertsBtn", "rebuildChromaBtn", "adminRunDueBtn",
    "loadKnowledgeDocsBtn", "createKnowledgeDocBtn", "loadKnowledgeChangesBtn",
    "loadWorkflowBtn", "saveWorkflowBtn", "loadConsultationTraceBtn", "loadDataRequestsBtn",
    "loadAuditBtn", "loadPrivacyBtn",
  ];
  ids.forEach((id) => { els[id] = document.querySelector(`#${id}`); });
}

function renderCurrentUser() {
  const user = getCurrentUser();
  els.currentUserText.textContent = user
    ? `${user.display_name} · ${agentRoleLabel(user.role)}`
    : "未登录";
}

function toastError(error) {
  showToast(error.message, "error");
}

// ===== Dashboard metric grid =====
async function loadDashboard() {
  showSkeleton(els.metricGrid, 4);
  try {
    const [alerts, llm] = await Promise.all([
      cachedRequest("admin:alerts", () => request("/api/admin/alerts")).catch(() => ({})),
      cachedRequest("admin:llm", () => request("/api/admin/llm/metrics")).catch(() => ({})),
    ]);
    const rag = alerts.rag_evaluation || {};
    els.metricGrid.innerHTML = `
      <div class="admin-metric-card accent">
        <span class="metric-label">RAG 命中率</span>
        <span class="metric-value">${rag.hit_rate ?? "—"}</span>
      </div>
      <div class="admin-metric-card">
        <span class="metric-label">RAG MRR</span>
        <span class="metric-value">${rag.mrr ?? "—"}</span>
      </div>
      <div class="admin-metric-card">
        <span class="metric-label">告警总数</span>
        <span class="metric-value">${alerts.counts?.total ?? 0}</span>
      </div>
      <div class="admin-metric-card">
        <span class="metric-label">高危告警</span>
        <span class="metric-value">${alerts.counts?.high ?? 0}</span>
      </div>
      <div class="admin-metric-card">
        <span class="metric-label">LLM 调用</span>
        <span class="metric-value">${llm.total_calls ?? llm.count ?? "—"}</span>
      </div>
    `;
    els.dashboardExtra.innerHTML = "";
  } catch (error) {
    setError(els.metricGrid, `加载失败: ${error.message}`, loadDashboard);
  }
}

// ===== Knowledge =====
async function loadKnowledgeDocs() {
  const data = await request("/api/admin/knowledge/documents");
  els.knowledgeBox.textContent = JSON.stringify(data.slice(0, 30), null, 2);
  showToast("知识库文档已加载");
}

async function createKnowledgeDoc() {
  const container = document.querySelector('[data-section="knowledge"]');
  clearFormErrors(container);
  const payload = {
    title: els.knowledgeTitleInput.value.trim(),
    category: els.knowledgeCategoryInput.value.trim(),
    source: els.knowledgeSourceInput.value.trim(),
    tags: [],
    content: els.knowledgeContentInput.value.trim(),
    active: true,
  };
  const check = validateKnowledgeDocument(payload);
  if (!check.ok) {
    applyErrors(container, check.fieldErrors);
    return;
  }
  const data = await request("/api/admin/knowledge/documents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("文档已新增");
}

async function loadKnowledgeChanges() {
  const data = await request("/api/admin/knowledge/changes");
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("变更记录已刷新");
}

async function rebuildChroma() {
  try {
    setStatus("重建向量库中...");
    const data = await request("/api/admin/chroma/rebuild", { method: "POST" });
    invalidateCache("admin:rag"); // rebuild changes retrieval quality
    els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
    showToast("向量库重建完成");
  } catch (error) {
    els.knowledgeBox.textContent = error.message;
    toastError(error);
  } finally {
    setStatus("就绪");
  }
}

// ===== RAG evaluation =====
async function loadRagEvaluation() {
  showSkeleton(els.ragBox, 3);
  try {
    const data = normalizeRagEvaluation(await cachedRequest("admin:rag", () => request("/api/admin/rag/evaluation")));
    let html = `<div class="result-metrics">`;
    html += `<div class="metric-card"><span>后端</span><strong>${escapeHtml(data.backend)}</strong></div>`;
    html += `<div class="metric-card"><span>测试用例</span><strong>${data.caseCount}</strong></div>`;
    html += `<div class="metric-card"><span>命中率</span><strong>${data.hitRate.toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>MRR</span><strong>${data.mrr.toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>失败数</span><strong>${data.failureCount}</strong></div>`;
    html += `</div>`;

    if (data.difficultyAnalysis) {
      html += `<div class="result-section"><h4>难度分布分析</h4><div class="result-metrics">`;
      for (const [diff, stats] of Object.entries(data.difficultyAnalysis)) {
        const color = diff === "easy" ? "risk-low" : diff === "medium" ? "risk-medium" : "risk-high";
        html += `<div class="metric-card ${color}"><span>${diff === "easy" ? "简单" : diff === "medium" ? "中等" : "困难"}</span><strong>${(stats.recall * 100).toFixed(1)}%</strong></div>`;
      }
      html += `</div></div>`;
    }

    if (data.categoryRecall) {
      html += `<div class="result-section"><h4>类别召回率</h4><div class="result-metrics compact">`;
      for (const [cat, recall] of Object.entries(data.categoryRecall)) {
        const color = recall >= 0.8 ? "risk-low" : recall >= 0.5 ? "risk-medium" : "risk-high";
        html += `<div class="metric-card ${color}"><span>${getCategoryName(cat)}</span><strong>${(recall * 100).toFixed(0)}%</strong></div>`;
      }
      html += `</div></div>`;
    }

    if (data.failureAnalysis) {
      html += `<div class="result-section"><h4>失败原因分析</h4><div style="display:flex;flex-direction:column;gap:6px;">`;
      for (const [type, count] of Object.entries(data.failureAnalysis)) {
        if (count > 0) {
          const percent = (count / (data.failureCount || 1)) * 100;
          html += `<div style="display:flex;align-items:center;gap:8px;">
            <span style="width:100px;font-size:13px;">${getFailureTypeName(type)}</span>
            <div style="flex:1;height:20px;background:var(--bg-tertiary);border-radius:4px;overflow:hidden;">
              <div style="height:100%;background:var(--danger);width:${percent}%;"></div>
            </div>
            <span style="width:30px;text-align:right;">${count}</span>
          </div>`;
        }
      }
      html += `</div></div>`;
    }

    els.ragBox.innerHTML = html;
    showToast("RAG 评测已刷新");
  } catch (error) {
    setError(els.ragBox, `加载失败: ${error.message}`, loadRagEvaluation);
  }
}

// ===== Workflow =====
async function loadWorkflowConfig() {
  const data = await request("/api/admin/workflow/configs/default");
  els.workflowJsonInput.value = JSON.stringify({ nodes: data.nodes || [], edges: data.edges || [] }, null, 2);
  els.workflowPreview.innerHTML = renderWorkflowGraph(data);
  showToast("工作流配置已加载");
}

async function saveWorkflowConfig() {
  let payload;
  try {
    payload = JSON.parse(els.workflowJsonInput.value || "{}");
  } catch {
    showToast("工作流 JSON 格式不正确", "error");
    return;
  }
  const check = validateWorkflowGraph(payload);
  if (!check.ok) {
    els.workflowPreview.innerHTML = `<div class="error-state"><p>保存被拦截，请修正：</p><ul>${check.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul></div>`;
    showToast(check.errors[0], "error");
    return;
  }
  const data = await request("/api/admin/workflow/graph", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  els.workflowPreview.innerHTML = renderWorkflowGraph(data.config || payload);
  showToast("工作流配置已保存");
}

// Visual read-only preview: entry/risk nodes highlighted, edges as source→target
// with condition labels. visited_agents (if present) marks the executed path.
function renderWorkflowGraph(config) {
  const nodes = config.nodes || [];
  const edges = config.edges || [];
  const visited = new Set(config.visited_agents || []);
  // Entry nodes = never a target of any edge.
  const targets = new Set(edges.map((e) => e.target));
  const isEntry = (n) => !targets.has(n.node_id);
  const isRisk = (n) => /risk|safety|guard|escalat/i.test(`${n.agent_id} ${n.node_id} ${n.label || ""}`);

  const nodeCards = nodes.length ? nodes.map((n) => {
    const flags = [];
    if (isEntry(n)) flags.push('<span class="wf-tag entry">入口</span>');
    if (isRisk(n)) flags.push('<span class="wf-tag risk">风险</span>');
    if (visited.has(n.agent_id) || visited.has(n.node_id)) flags.push('<span class="wf-tag visited">已执行</span>');
    const cls = `wf-node${visited.has(n.agent_id) || visited.has(n.node_id) ? " visited" : ""}${isEntry(n) ? " entry" : ""}`;
    return `
      <div class="${cls}">
        <div class="wf-node-head">
          <strong>${escapeHtml(n.label || n.node_id)}</strong>
          <span class="wf-node-id">${escapeHtml(n.node_id)}</span>
        </div>
        <div class="wf-node-agent">agent: ${escapeHtml(n.agent_id || "-")}</div>
        <div class="wf-flags">${flags.join("")}</div>
      </div>
    `;
  }).join("") : "<p>暂无节点</p>";

  const edgeRows = edges.length ? edges.map((e) => `
    <div class="wf-edge">
      <span class="wf-edge-src">${escapeHtml(e.source)}</span>
      <span class="wf-edge-arrow">→</span>
      <span class="wf-edge-dst">${escapeHtml(e.target)}</span>
      ${e.condition ? `<span class="wf-edge-cond">${escapeHtml(e.condition)}</span>` : ""}
      ${e.label ? `<span class="wf-edge-label">${escapeHtml(e.label)}</span>` : ""}
    </div>
  `).join("") : "<p>暂无连线</p>";

  return `
    <h3>工作流配置：${escapeHtml(config.name || config.config_id || "default")}</h3>
    <div class="result-metrics compact">
      <div class="metric-card"><span>节点</span><strong>${nodes.length}</strong></div>
      <div class="metric-card"><span>连线</span><strong>${edges.length}</strong></div>
      <div class="metric-card"><span>状态</span><strong>${config.active ? "启用" : "停用"}</strong></div>
    </div>
    <div class="result-section"><h4>节点</h4><div class="wf-node-grid">${nodeCards}</div></div>
    <div class="result-section"><h4>连线</h4><div class="wf-edge-list">${edgeRows}</div></div>
  `;
}

// ===== LLM metrics =====
function renderLlmMetrics(data) {
  if (!data || typeof data !== "object") {
    return "<div class='empty-state'><p>暂无数据</p></div>";
  }
  
  const successRate = data.total_calls > 0 
    ? Math.round((data.success_calls / data.total_calls) * 100) 
    : 0;
  const fallbackRate = data.total_calls > 0 
    ? Math.round((data.fallback_calls / data.total_calls) * 100) 
    : 0;

  let html = `
    <div class="llm-metrics-grid">
      <div class="llm-metric-card">
        <div class="llm-metric-icon">📊</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">${data.total_calls || 0}</div>
          <div class="llm-metric-label">总调用次数</div>
        </div>
      </div>
      <div class="llm-metric-card">
        <div class="llm-metric-icon">✅</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">${successRate}%</div>
          <div class="llm-metric-label">成功率</div>
        </div>
      </div>
      <div class="llm-metric-card">
        <div class="llm-metric-icon">🔄</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">${fallbackRate}%</div>
          <div class="llm-metric-label">降级率</div>
        </div>
      </div>
      <div class="llm-metric-card">
        <div class="llm-metric-icon">⏱️</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">${(data.avg_latency_ms || 0).toLocaleString()}ms</div>
          <div class="llm-metric-label">平均延迟</div>
        </div>
      </div>
      <div class="llm-metric-card">
        <div class="llm-metric-icon">📝</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">${(data.total_tokens || 0).toLocaleString()}</div>
          <div class="llm-metric-label">总令牌数</div>
        </div>
      </div>
      <div class="llm-metric-card">
        <div class="llm-metric-icon">💰</div>
        <div class="llm-metric-info">
          <div class="llm-metric-value">$${(data.estimated_cost || 0).toFixed(4)}</div>
          <div class="llm-metric-label">预估费用</div>
        </div>
      </div>
    </div>
  `;

  if (data.recent && data.recent.length > 0) {
    html += `
      <div class="llm-recent-section">
        <h3>最近调用记录</h3>
        <div class="llm-recent-list">
          ${data.recent.slice(0, 10).map((item) => renderLlmCallItem(item)).join("")}
        </div>
      </div>
    `;
  }
  
  return html;
}

function renderLlmCallItem(item) {
  const statusClass = item.status === "success" ? "status-success" : 
                      item.status === "failed" ? "status-failed" : "status-pending";
  const statusLabel = item.status === "success" ? "成功" : 
                      item.status === "failed" ? "失败" : "进行中";
  
  return `
    <div class="llm-call-item">
      <div class="llm-call-header">
        <span class="llm-call-id">#${item.id}</span>
        <span class="llm-model-name">${escapeHtml(item.model_name || "-")}</span>
        <span class="llm-status ${statusClass}">${statusLabel}</span>
      </div>
      <div class="llm-call-info">
        <span>咨询ID: ${item.consultation_id || "-"}</span>
        <span>延迟: ${(item.latency_ms || 0).toLocaleString()}ms</span>
        <span>令牌: ${(item.total_tokens || 0).toLocaleString()}</span>
        <span>费用: $${(item.estimated_cost || 0).toFixed(4)}</span>
      </div>
      <div class="llm-call-time">${formatDate(item.created_at)}</div>
      ${item.error_message ? `<div class="llm-error-message">错误: ${escapeHtml(item.error_message)}</div>` : ""}
    </div>
  `;
}

async function loadLlmMetrics() {
  showSkeleton(els.llmBox, 2);
  try {
    const data = await cachedRequest("admin:llm", () => request("/api/admin/llm/metrics"));
    els.llmBox.innerHTML = renderLlmMetrics(data);
    showToast("LLM 指标已刷新");
  } catch (error) {
    setError(els.llmBox, `加载失败: ${error.message}`, loadLlmMetrics);
  }
}

// ===== Consultation trace =====
function renderConsultationTrace(data) {
  if (!data || !data.length) {
    return "<div class='empty-state'><p>暂无咨询追踪记录</p></div>";
  }
  
  return data.map((item) => {
    const llmCallCount = (item.llm_calls || []).length || (item.llm_call ? 1 : 0);
    const hitCount = (item.retrieval_hits || []).length;
    const reviewStatus = item.review?.status || "未复核";
    
    return `
      <div class="trace-card risk-border-${escapeHtml(item.risk_level)}">
        <div class="trace-header">
          <div class="trace-id">#${item.consultation_id}</div>
          <div class="trace-agent">${agentLabel(item.agent_type)}</div>
          <div class="trace-status ${getTraceStatusClass(item.status)}">${getTraceStatusLabel(item.status)}</div>
          <div class="trace-risk risk-${escapeHtml(item.risk_level)}">${riskLabel(item.risk_level)}风险</div>
        </div>
        
        <div class="trace-meta">
          <span class="trace-patient">患者: ${escapeHtml(item.patient_external_id)}</span>
          <span class="trace-divider">·</span>
          <span class="trace-review ${item.doctor_review_required ? "review-required" : ""}">
            ${item.doctor_review_required ? "需复核" : "无需复核"}
          </span>
          <span class="trace-divider">·</span>
          <span class="trace-date">${formatDate(item.created_at)}</span>
        </div>
        
        ${item.summary ? `
          <div class="trace-summary">
            <div class="trace-summary-label">咨询摘要</div>
            <p>${escapeHtml(item.summary.slice(0, 200))}${item.summary.length > 200 ? "..." : ""}</p>
          </div>
        ` : ""}
        
        <div class="trace-metrics">
          <div class="trace-metric">
            <span class="trace-metric-value">${llmCallCount}</span>
            <span class="trace-metric-label">LLM调用</span>
          </div>
          <div class="trace-metric">
            <span class="trace-metric-value">${item.llm_call?.latency_ms || "-"}</span>
            <span class="trace-metric-label">延迟(ms)</span>
          </div>
          <div class="trace-metric">
            <span class="trace-metric-value">${item.llm_call?.total_tokens || "-"}</span>
            <span class="trace-metric-label">Token数</span>
          </div>
          <div class="trace-metric">
            <span class="trace-metric-value">${hitCount}</span>
            <span class="trace-metric-label">检索命中</span>
          </div>
          <div class="trace-metric">
            <span class="trace-metric-value review-status">${reviewStatus}</span>
            <span class="trace-metric-label">复核状态</span>
          </div>
        </div>
        
        <div class="trace-details">
          <details class="trace-detail-section">
            <summary>📚 检索命中 (${hitCount})</summary>
            <div class="trace-detail-content">
              ${hitCount > 0 ? renderSources(item.retrieval_hits || []) : "<div class='empty-detail'>暂无检索命中记录</div>"}
            </div>
          </details>
          
          <details class="trace-detail-section">
            <summary>🤖 模型调用 (${llmCallCount})</summary>
            <div class="trace-detail-content">
              ${llmCallCount > 0 ? renderLlmCalls(item.llm_calls || [], item.llm_call) : "<div class='empty-detail'>暂无模型调用记录</div>"}
            </div>
          </details>
          
          <details class="trace-detail-section">
            <summary>👩⚕️ 复核状态</summary>
            <div class="trace-detail-content">
              ${item.review ? renderReviewStatus(item.review) : "<div class='empty-detail'>暂无复核信息</div>"}
            </div>
          </details>
        </div>
      </div>
    `;
  }).join("");
}

function getTraceStatusClass(status) {
  const statusMap = {
    completed: "status-completed",
    pending: "status-pending",
    failed: "status-failed",
    in_progress: "status-progress",
  };
  return statusMap[status] || "status-unknown";
}

function getTraceStatusLabel(status) {
  const labelMap = {
    completed: "已完成",
    pending: "处理中",
    failed: "失败",
    in_progress: "进行中",
  };
  return labelMap[status] || status;
}

async function loadConsultationTrace() {
  showSkeleton(els.traceBox, 4);
  try {
    const data = await cachedRequest("admin:trace", () => request("/api/admin/consultation-trace"));
    els.traceBox.innerHTML = renderConsultationTrace(data);
    showToast("咨询追踪已加载");
  } catch (error) {
    setError(els.traceBox, `加载失败: ${error.message}`, loadConsultationTrace);
  }
}

// ===== Audit =====
function formatAuditAction(action) {
  const actionMap = {
    "data_request.process": "数据请求处理",
    "data_request.create": "创建数据请求",
    "knowledge.create": "创建知识库文档",
    "knowledge.update": "更新知识库文档",
    "knowledge.delete": "删除知识库文档",
    "workflow.update": "更新工作流配置",
    "system.login": "系统登录",
    "system.logout": "系统登出",
    "admin.action": "管理员操作",
  };
  return actionMap[action] || action.replace(/\./g, " / ").replace(/_/g, " ");
}

function formatResourceType(type) {
  const typeMap = {
    "data_access_request": "数据访问请求",
    "knowledge_document": "知识库文档",
    "workflow_config": "工作流配置",
    "user_account": "用户账户",
    "system_setting": "系统设置",
  };
  return typeMap[type] || type.replace(/_/g, " ");
}

function renderDetail(detail) {
  if (!detail || typeof detail !== "object") {
    return "<div class='detail-empty'>暂无详情信息</div>";
  }
  const rows = [];
  for (const [key, value] of Object.entries(detail)) {
    const displayKey = formatDetailKey(key);
    const displayValue = formatDetailValue(value);
    rows.push(`<div class="detail-row"><span class="detail-key">${displayKey}</span><span class="detail-value">${displayValue}</span></div>`);
  }
  return rows.length ? rows.join("") : "<div class='detail-empty'>暂无详情信息</div>";
}

function formatDetailKey(key) {
  const keyMap = {
    status: "状态",
    note: "备注",
    reason: "原因",
    old_value: "原值",
    new_value: "新值",
    request_id: "请求ID",
    user_id: "用户ID",
    action_type: "操作类型",
    data_scope: "数据范围",
    processed_by: "处理人",
    processed_at: "处理时间",
    actor_id: "操作人ID",
    actor_name: "操作人姓名",
    target_id: "目标ID",
    target_name: "目标名称",
    ip_address: "IP地址",
    user_agent: "客户端",
    changes: "变更内容",
    result: "操作结果",
    error_message: "错误信息",
  };
  return keyMap[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDetailValue(value) {
  if (value === null || value === undefined) {
    return "<span class='detail-null'>-</span>";
  }
  if (typeof value === "object") {
    return `<div class='detail-object'><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></div>`;
  }
  if (typeof value === "boolean") {
    return value ? "<span class='detail-badge detail-badge-success'>是</span>" : "<span class='detail-badge detail-badge-danger'>否</span>";
  }
  const statusMap = {
    rejected: { label: "已拒绝", class: "detail-badge-danger" },
    approved: { label: "已批准", class: "detail-badge-success" },
    pending: { label: "待处理", class: "detail-badge-warning" },
    success: { label: "成功", class: "detail-badge-success" },
    failed: { label: "失败", class: "detail-badge-danger" },
    active: { label: "启用", class: "detail-badge-success" },
    inactive: { label: "停用", class: "detail-badge-muted" },
  };
  if (statusMap[value]) {
    const status = statusMap[value];
    return `<span class='detail-badge ${status.class}'>${status.label}</span>`;
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) {
    return `<span class='detail-date'>${formatDate(value)}</span>`;
  }
  return escapeHtml(String(value));
}

async function loadAuditLogs() {
  showSkeleton(els.auditBox, 4);
  try {
    const data = await cachedRequest("admin:audit", () => request("/api/admin/audit"));
    els.auditBox.innerHTML = data.length ? data.map((item) => `
      <div class="audit-item risk-border-${escapeHtml(item.risk_level)}">
        <div class="audit-header">
          <div class="audit-id">#${item.id}</div>
          <div class="audit-action">${formatAuditAction(item.action)}</div>
          <div class="audit-risk risk-${escapeHtml(item.risk_level)}">${riskLabel(item.risk_level)}风险</div>
        </div>
        <div class="audit-info">
          <span class="audit-actor">${escapeHtml(item.actor_external_id)} · ${agentRoleLabel(item.actor_role)}</span>
          <span class="audit-divider">·</span>
          <span class="audit-resource">${formatResourceType(item.resource_type)} #${item.resource_id || "-"}</span>
          <span class="audit-divider">·</span>
          <span class="audit-date">${formatDate(item.created_at)}</span>
        </div>
        <details class="audit-details">
          <summary>查看详情</summary>
          <div class="audit-detail-content">${renderDetail(item.detail)}</div>
        </details>
      </div>
    `).join("") : "<div class='empty-state'><p>暂无审计日志</p></div>";
    showToast("审计日志已加载");
  } catch (error) {
    setError(els.auditBox, `加载失败: ${error.message}`, loadAuditLogs);
  }
}

// ===== Privacy =====
async function loadPrivacyCompliance() {
  showSkeleton(els.privacyBox, 3);
  try {
    const [assessments, policies] = await Promise.all([
      request("/api/admin/privacy/assessments"),
      request("/api/admin/privacy/retention-policies"),
    ]);
    els.privacyBox.innerHTML = `
      ${renderSimpleTable("隐私影响评估", assessments, ["assessment_id", "title", "risk_level", "compliance_status"])}
      ${renderSimpleTable("数据保留策略", policies, ["data_category", "retention_days", "auto_delete", "archived"])}
    `;
    showToast("隐私合规记录已加载");
  } catch (error) {
    setError(els.privacyBox, `加载失败: ${error.message}`, loadPrivacyCompliance);
  }
}

async function loadDataRequests() {
  showSkeleton(els.privacyBox, 3);
  try {
    const data = await request("/api/admin/data-requests");
    els.privacyBox.innerHTML = renderDataRequests("数据导出/删除请求", data);
    els.privacyBox.querySelectorAll("[data-data-request]").forEach((button) => {
      button.addEventListener("click", () => processDataRequest(button.dataset.dataRequest, button.dataset.action).catch(toastError));
    });
    showToast("数据请求已加载");
  } catch (error) {
    setError(els.privacyBox, `加载失败: ${error.message}`, loadDataRequests);
  }
}

function renderDataRequests(title, rows) {
  return `
    <h3>${escapeHtml(title)}</h3>
    ${rows && rows.length ? rows.map((item) => `
      <div class="admin-row">
        <strong>#${item.id} · ${escapeHtml(dataRequestTypeLabel(item.request_type))} · ${escapeHtml(dataRequestStatusLabel(item.status))}</strong>
        <p>${escapeHtml(item.user_external_id)} · ${escapeHtml(item.data_scope)} · ${escapeHtml(item.reason || "")}</p>
        ${item.processed_at ? `<p>处理人：${escapeHtml(item.processed_by || "-")} · ${formatDate(item.processed_at)} · ${escapeHtml(item.note || "")}</p>` : ""}
        ${item.result_summary ? renderDataExportSummary(item.result_summary) : ""}
        ${item.result_data ? `<details class="export-details"><summary>查看导出数据预览</summary><pre>${escapeHtml(JSON.stringify(item.result_data, null, 2))}</pre></details>` : ""}
        ${item.status === "pending" ? `
          <button class="small primary" data-data-request="${item.id}" data-action="approved">批准</button>
          <button class="small" data-data-request="${item.id}" data-action="rejected">拒绝</button>
        ` : ""}
      </div>
    `).join("") : "<div class='empty-state'><p>暂无数据请求</p></div>"}
  `;
}

function renderDataExportSummary(summary) {
  return `
    <div class="export-summary">
      <span>咨询 ${summary.consultation_count || 0}</span>
      <span>同意 ${summary.consent_count || 0}</span>
      <span>治疗 ${summary.treatment_record_count || 0}</span>
      <span>牙位 ${summary.tooth_record_count || 0}</span>
      <span>提醒 ${summary.reminder_count || 0}</span>
    </div>
  `;
}

async function processDataRequest(requestId, status) {
  await request(`/api/admin/data-requests/${requestId}`, {
    method: "PUT",
    body: JSON.stringify({ status, note: status === "approved" ? "管理员已按内测流程处理" : "管理员拒绝本次申请" }),
  });
  showToast("数据请求已处理");
  await loadDataRequests();
}

// ===== Alerts =====
async function loadAdminAlerts() {
  showSkeleton(els.alertsBox, 3);
  try {
    const data = await cachedRequest("admin:alerts", () => request("/api/admin/alerts"));
    els.alertsBox.innerHTML = renderAdminAlerts(data);
    showToast("异常告警已刷新");
  } catch (error) {
    setError(els.alertsBox, `加载失败: ${error.message}`, loadAdminAlerts);
  }
}

function renderAdminAlerts(data) {
  const alerts = data.alerts || [];
  return `
    <div class="result-metrics compact">
      <div class="metric-card"><span>总数</span><strong>${data.counts?.total || 0}</strong></div>
      <div class="metric-card risk-high"><span>高</span><strong>${data.counts?.high || 0}</strong></div>
      <div class="metric-card risk-medium"><span>中</span><strong>${data.counts?.medium || 0}</strong></div>
      <div class="metric-card risk-low"><span>低</span><strong>${data.counts?.low || 0}</strong></div>
    </div>
    <div class="admin-row">
      <strong>RAG 质量</strong>
      <p>命中率 ${escapeHtml(data.rag_evaluation?.hit_rate ?? "-")} · MRR ${escapeHtml(data.rag_evaluation?.mrr ?? "-")} · 用例 ${escapeHtml(data.rag_evaluation?.case_count ?? "-")}</p>
    </div>
    ${alerts.length ? alerts.map((alert) => `
      <div class="admin-row alert-${escapeHtml(alert.severity)}">
        <strong>${escapeHtml(alert.title)} · ${escapeHtml(alert.severity)}</strong>
        <p>${escapeHtml(alert.message)}</p>
        <p>${escapeHtml(alert.resource_type || "-")} #${escapeHtml(alert.resource_id || "-")} · ${formatDate(alert.created_at)}</p>
      </div>
    `).join("") : "<div class='empty-state'><p>暂无异常告警</p></div>"}
  `;
}

async function adminRunDueNotifications() {
  setStatus("扫描到期提醒中...");
  try {
    await request("/api/admin/notifications/run-due", { method: "POST" });
    invalidateCache("admin:alerts");
    await loadAdminAlerts();
    showToast("扫描到期提醒完成");
  } finally {
    setStatus("就绪");
  }
}

// ===== Section lazy-load =====
function onSection(section) {
  setPageTitle(SECTION_TITLES[section] || "");
  if (section === "dashboard") loadDashboard();
  else if (section === "rag") loadRagEvaluation();
  else if (section === "workflow") loadWorkflowConfig().catch(toastError);
  else if (section === "llm") loadLlmMetrics();
  else if (section === "trace") loadConsultationTrace();
  else if (section === "audit") loadAuditLogs();
  else if (section === "privacy") loadPrivacyCompliance();
  else if (section === "alerts") loadAdminAlerts();
}

function bindAdminEvents() {
  els.logoutBtn.addEventListener("click", logout);
  els.ragEvalBtn.addEventListener("click", () => { invalidateCache("admin:rag"); loadRagEvaluation(); });
  els.llmMetricsBtn.addEventListener("click", () => { invalidateCache("admin:llm"); loadLlmMetrics(); });
  els.adminAlertsBtn.addEventListener("click", () => { invalidateCache("admin:alerts"); loadAdminAlerts(); });
  els.rebuildChromaBtn.addEventListener("click", rebuildChroma);
  els.adminRunDueBtn.addEventListener("click", () => adminRunDueNotifications().catch(toastError));
  els.loadKnowledgeDocsBtn.addEventListener("click", () => loadKnowledgeDocs().catch(toastError));
  els.createKnowledgeDocBtn.addEventListener("click", () => createKnowledgeDoc().catch(toastError));
  els.loadKnowledgeChangesBtn.addEventListener("click", () => loadKnowledgeChanges().catch(toastError));
  els.loadWorkflowBtn.addEventListener("click", () => loadWorkflowConfig().catch(toastError));
  els.saveWorkflowBtn.addEventListener("click", () => saveWorkflowConfig().catch(toastError));
  els.loadConsultationTraceBtn.addEventListener("click", () => { invalidateCache("admin:trace"); loadConsultationTrace().catch(toastError); });
  els.loadDataRequestsBtn.addEventListener("click", () => loadDataRequests().catch(toastError));
  els.loadAuditBtn.addEventListener("click", () => { invalidateCache("admin:audit"); loadAuditLogs().catch(toastError); });
  els.loadPrivacyBtn.addEventListener("click", () => loadPrivacyCompliance().catch(toastError));
}

async function initAdminApp() {
  cacheEls();
  const user = await requireRole("admin");
  if (!user) return;
  renderCurrentUser();
  flushPendingToast();
  bindAdminEvents();
  initNav("dashboard", onSection);
}

initAdminApp();
