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
import { renderSources, renderLlmCalls } from "./shared/result.js";

const els = {};

function cacheEls() {
  const ids = [
    "currentUserText", "logoutBtn", "knowledgeBox", "workflowJsonInput",
    "knowledgeTitleInput", "knowledgeCategoryInput", "knowledgeSourceInput", "knowledgeContentInput",
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

function showError(error) {
  els.knowledgeBox.textContent = error.message;
  showToast(error.message, "error");
}

async function loadKnowledgeDocs() {
  const data = await request("/api/admin/knowledge/documents");
  els.knowledgeBox.textContent = JSON.stringify(data.slice(0, 30), null, 2);
  showToast("知识库文档已加载");
}

async function createKnowledgeDoc() {
  const payload = {
    title: els.knowledgeTitleInput.value.trim(),
    category: els.knowledgeCategoryInput.value.trim() || "health",
    source: els.knowledgeSourceInput.value.trim() || "管理员内测录入",
    tags: [],
    content: els.knowledgeContentInput.value.trim(),
    active: true,
  };
  if (!payload.title || !payload.content) {
    showToast("请填写标题和内容", "warning");
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

async function loadRagEvaluation() {
  try {
    const data = await request("/api/admin/rag/evaluation");
    let html = `<h3>RAG 召回评测报告</h3>`;
    html += `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; margin: 16px 0;">`;
    html += `<div class="metric-card"><span>后端</span><strong>${escapeHtml(data.backend || "N/A")}</strong></div>`;
    html += `<div class="metric-card"><span>测试用例</span><strong>${data.case_count || 0}</strong></div>`;
    html += `<div class="metric-card"><span>命中率</span><strong>${(data.hit_rate || 0).toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>MRR</span><strong>${(data.mrr || 0).toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>失败数</span><strong>${data.failure_count || 0}</strong></div>`;
    html += `</div>`;

    if (data.difficulty_analysis) {
      html += `<h4>难度分布分析</h4>`;
      html += `<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">`;
      for (const [diff, stats] of Object.entries(data.difficulty_analysis)) {
        const color = diff === "easy" ? "risk-low" : diff === "medium" ? "risk-medium" : "risk-high";
        html += `<div class="metric-card ${color}">`;
        html += `<span>${diff === "easy" ? "简单" : diff === "medium" ? "中等" : "困难"}</span>`;
        html += `<strong>${(stats.recall * 100).toFixed(1)}%</strong>`;
        html += `<div style="font-size: 12px; color: var(--text-secondary);">${stats.hits}/${stats.total}</div>`;
        html += `</div>`;
      }
      html += `</div>`;
    }

    if (data.category_recall) {
      html += `<h4>类别召回率</h4>`;
      html += `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px;">`;
      for (const [cat, recall] of Object.entries(data.category_recall)) {
        const color = recall >= 0.8 ? "risk-low" : recall >= 0.5 ? "risk-medium" : "risk-high";
        html += `<div class="metric-card ${color}" style="padding: 8px;">`;
        html += `<span style="font-size: 11px;">${getCategoryName(cat)}</span>`;
        html += `<strong>${(recall * 100).toFixed(0)}%</strong>`;
        html += `</div>`;
      }
      html += `</div>`;
    }

    if (data.failure_analysis) {
      html += `<h4>失败原因分析</h4>`;
      html += `<div style="display: flex; flex-direction: column; gap: 6px;">`;
      for (const [type, count] of Object.entries(data.failure_analysis)) {
        if (count > 0) {
          const percent = (count / (data.failure_count || 1)) * 100;
          html += `<div style="display: flex; align-items: center; gap: 8px;">`;
          html += `<span style="width: 100px; font-size: 13px;">${getFailureTypeName(type)}</span>`;
          html += `<div style="flex: 1; height: 20px; background: var(--bg-tertiary); border-radius: 4px; overflow: hidden;">`;
          html += `<div style="height: 100%; background: var(--danger); width: ${percent}%;"></div>`;
          html += `</div>`;
          html += `<span style="width: 30px; text-align: right;">${count}</span>`;
          html += `</div>`;
        }
      }
      html += `</div>`;
    }

    els.knowledgeBox.innerHTML = html;
    showToast("RAG 评测已刷新");
  } catch (error) {
    showError(error);
  }
}

async function loadWorkflowConfig() {
  const data = await request("/api/admin/workflow/configs/default");
  els.workflowJsonInput.value = JSON.stringify({ nodes: data.nodes || [], edges: data.edges || [] }, null, 2);
  els.knowledgeBox.innerHTML = renderWorkflowAdmin(data);
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
  const data = await request("/api/admin/workflow/graph", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("工作流配置已保存");
}

function renderWorkflowAdmin(config) {
  return `
    <h3>工作流配置：${escapeHtml(config.name || config.config_id || "default")}</h3>
    <div class="result-metrics">
      <div class="metric-card"><span>节点</span><strong>${(config.nodes || []).length}</strong></div>
      <div class="metric-card"><span>连线</span><strong>${(config.edges || []).length}</strong></div>
      <div class="metric-card"><span>状态</span><strong>${config.active ? "启用" : "停用"}</strong></div>
    </div>
    ${renderSimpleTable("节点", config.nodes || [], ["node_id", "agent_id", "label"])}
    ${renderSimpleTable("连线", config.edges || [], ["source", "target", "label", "condition"])}
  `;
}

async function loadConsultationTrace() {
  const data = await request("/api/admin/consultation-trace");
  els.knowledgeBox.innerHTML = `
    <h3>咨询追踪</h3>
    ${data.length ? data.map((item) => `
      <div class="admin-row risk-border-${escapeHtml(item.risk_level)}">
        <strong>#${item.consultation_id} · ${agentLabel(item.agent_type)} · ${escapeHtml(item.status)}</strong>
        <p>${escapeHtml(item.patient_external_id)} · ${riskLabel(item.risk_level)}风险 · ${item.doctor_review_required ? "需复核" : "无需复核"} · ${formatDate(item.created_at)}</p>
        <p>${escapeHtml((item.summary || "").slice(0, 140))}${(item.summary || "").length > 140 ? "..." : ""}</p>
        <div class="export-summary">
          <span>LLM: ${escapeHtml(item.llm_call?.status || "-")}</span>
          <span>延迟: ${escapeHtml(item.llm_call?.latency_ms ?? "-")}ms</span>
          <span>费用: ${escapeHtml(item.llm_call?.estimated_cost ?? "-")}</span>
          <span>调用: ${(item.llm_calls || []).length || (item.llm_call ? 1 : 0)}</span>
          <span>复核: ${escapeHtml(item.review?.status || "-")}</span>
          <span>命中: ${(item.retrieval_hits || []).length}</span>
        </div>
        <details class="export-details"><summary>检索命中</summary>${renderSources(item.retrieval_hits || [])}</details>
        <details class="export-details"><summary>模型调用</summary>${renderLlmCalls(item.llm_calls || [], item.llm_call)}</details>
        <details class="export-details"><summary>复核状态</summary><pre>${escapeHtml(JSON.stringify(item.review || {}, null, 2))}</pre></details>
      </div>
    `).join("") : "<div class='admin-row'>暂无咨询追踪记录</div>"}
  `;
  showToast("咨询追踪已加载");
}

async function loadDataRequests() {
  const data = await request("/api/admin/data-requests");
  els.knowledgeBox.innerHTML = renderDataRequests("数据导出/删除请求", data);
  els.knowledgeBox.querySelectorAll("[data-data-request]").forEach((button) => {
    button.addEventListener("click", () => processDataRequest(button.dataset.dataRequest, button.dataset.action).catch(showError));
  });
  showToast("数据请求已加载");
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
    `).join("") : "<div class='admin-row'>暂无数据请求</div>"}
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
  const data = await request(`/api/admin/data-requests/${requestId}`, {
    method: "PUT",
    body: JSON.stringify({ status, note: status === "approved" ? "管理员已按内测流程处理" : "管理员拒绝本次申请" }),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("数据请求已处理");
  await loadDataRequests();
}

async function loadAuditLogs() {
  const data = await request("/api/admin/audit");
  els.knowledgeBox.innerHTML = `
    <h3>审计日志</h3>
    ${data.length ? data.map((item) => `
      <div class="admin-row risk-border-${escapeHtml(item.risk_level)}">
        <strong>#${item.id} · ${escapeHtml(item.action)} · ${escapeHtml(item.risk_level)}</strong>
        <p>${escapeHtml(item.actor_external_id)} / ${escapeHtml(item.actor_role)} · ${escapeHtml(item.resource_type)} #${escapeHtml(item.resource_id || "-")} · ${formatDate(item.created_at)}</p>
        <details class="export-details"><summary>详情</summary><pre>${escapeHtml(JSON.stringify(item.detail || {}, null, 2))}</pre></details>
      </div>
    `).join("") : "<div class='admin-row'>暂无审计日志</div>"}
  `;
  showToast("审计日志已加载");
}

async function loadPrivacyCompliance() {
  const [assessments, policies] = await Promise.all([
    request("/api/admin/privacy/assessments"),
    request("/api/admin/privacy/retention-policies"),
  ]);
  els.knowledgeBox.innerHTML = `
    <h3>隐私合规记录</h3>
    ${renderSimpleTable("隐私影响评估", assessments, ["assessment_id", "title", "risk_level", "compliance_status"])}
    ${renderSimpleTable("数据保留策略", policies, ["data_category", "retention_days", "auto_delete", "archived"])}
  `;
  showToast("隐私合规记录已加载");
}

async function loadLlmMetrics() {
  try {
    const data = await request("/api/admin/llm/metrics");
    els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
    showToast("LLM 指标已刷新");
  } catch (error) {
    showError(error);
  }
}

async function loadAdminAlerts() {
  try {
    const data = await request("/api/admin/alerts");
    els.knowledgeBox.innerHTML = renderAdminAlerts(data);
    showToast("异常告警已刷新");
  } catch (error) {
    showError(error);
  }
}

function renderAdminAlerts(data) {
  const alerts = data.alerts || [];
  return `
    <h3>异常告警</h3>
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
    `).join("") : "<div class='admin-row'>暂无异常告警</div>"}
  `;
}

async function rebuildChroma() {
  try {
    setStatus("重建向量库中...");
    const data = await request("/api/admin/chroma/rebuild", { method: "POST" });
    els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
    showToast("向量库重建完成");
  } catch (error) {
    showError(error);
  } finally {
    setStatus("就绪");
  }
}

async function adminRunDueNotifications() {
  const data = await request("/api/admin/notifications/run-due", { method: "POST" });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("管理员扫描完成");
}

function bindAdminEvents() {
  els.logoutBtn.addEventListener("click", logout);
  els.ragEvalBtn.addEventListener("click", loadRagEvaluation);
  els.llmMetricsBtn.addEventListener("click", loadLlmMetrics);
  els.adminAlertsBtn.addEventListener("click", loadAdminAlerts);
  els.rebuildChromaBtn.addEventListener("click", rebuildChroma);
  els.adminRunDueBtn.addEventListener("click", () => adminRunDueNotifications().catch(showError));
  els.loadKnowledgeDocsBtn.addEventListener("click", () => loadKnowledgeDocs().catch(showError));
  els.createKnowledgeDocBtn.addEventListener("click", () => createKnowledgeDoc().catch(showError));
  els.loadKnowledgeChangesBtn.addEventListener("click", () => loadKnowledgeChanges().catch(showError));
  els.loadWorkflowBtn.addEventListener("click", () => loadWorkflowConfig().catch(showError));
  els.saveWorkflowBtn.addEventListener("click", () => saveWorkflowConfig().catch(showError));
  els.loadConsultationTraceBtn.addEventListener("click", () => loadConsultationTrace().catch(showError));
  els.loadDataRequestsBtn.addEventListener("click", () => loadDataRequests().catch(showError));
  els.loadAuditBtn.addEventListener("click", () => loadAuditLogs().catch(showError));
  els.loadPrivacyBtn.addEventListener("click", () => loadPrivacyCompliance().catch(showError));
}

async function initAdminApp() {
  cacheEls();
  const user = await requireRole("admin");
  if (!user) return;
  renderCurrentUser();
  flushPendingToast();
  bindAdminEvents();
}

initAdminApp();
