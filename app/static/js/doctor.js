import { request } from "./shared/api.js";
import { getCurrentUser } from "./shared/state.js";
import { logout, requireRole } from "./shared/auth.js";
import { showToast, openModal, closeModal, flushPendingToast } from "./shared/components.js";
import { escapeHtml, riskLabel, agentLabel, agentRoleLabel } from "./shared/format.js";
import {
  renderStructuredData,
  renderObjectList,
  renderTrace,
  renderLlmCalls,
} from "./shared/result.js";
import { normalizeDoctorReport } from "./shared/normalizers.js";
import {
  initNav,
  setPageTitle,
  showSkeleton,
  setError,
} from "./shared/view.js";

const SECTION_TITLES = {
  dashboard: "首页概览",
  reviews: "待复核队列",
  highRisk: "高风险咨询",
  history: "复核历史",
};
const PENDING_STATES = ["pending", "returned_for_info", "escalated"];
const els = {};
let allReviews = [];
let currentReviewId = null;
let currentReviewStatus = null;
let currentModalOverlay = null;

function cacheEls() {
  [
    "currentUserText", "logoutBtn", "dashboardBox",
    "reviewList", "refreshReviewBtn", "reportPanel",
    "highRiskList", "refreshHighRiskBtn", "highRiskReportPanel",
    "historyList", "refreshHistoryBtn",
  ].forEach((id) => { els[id] = document.querySelector(`#${id}`); });
}

function renderCurrentUser() {
  const user = getCurrentUser();
  els.currentUserText.textContent = user
    ? `${user.display_name} · ${agentRoleLabel(user.role)}`
    : "未登录";
}

// ===== Fetch once, filter per section =====
async function fetchReviews(force = false) {
  if (allReviews.length && !force) return allReviews;
  allReviews = await request("/api/doctor/reviews");
  return allReviews;
}

function reviewRow(row, { actions = true } = {}) {
  const pending = PENDING_STATES.includes(row.status);
  const resolved = row.status === "approved" || row.status === "rejected" || row.status === "needs_followup";
  const cls = [
    "review-item",
    row.status === "approved" ? "approved" : row.status === "rejected" ? "rejected" : "",
    row.risk_level === "high" ? "high-risk" : "",
    resolved ? "resolved" : "",
  ].filter(Boolean).join(" ");
  return `
    <div class="${cls}">
      <strong>复核 #${row.review_id} · 咨询 #${row.consultation_id}</strong>
      <div class="review-meta">
        <span>状态: ${escapeHtml(row.status)}</span>
        <span class="risk-flag risk-${row.risk_level}">${riskLabel(row.risk_level)}风险</span>
        <span>${agentLabel(row.agent_type)}</span>
      </div>
      <div>${escapeHtml(row.summary.slice(0, 100))}${row.summary.length > 100 ? "..." : ""}</div>
      <div class="review-actions">
        <button data-report="${row.consultation_id}" class="small">查看报告</button>
        ${actions && pending ? `
        <button data-review="${row.review_id}" data-status="approved" class="small primary">通过</button>
        <button data-review="${row.review_id}" data-status="needs_followup" class="small">需随访</button>
        <button data-review="${row.review_id}" data-status="returned_for_info" class="small">退回补充</button>
        <button data-review="${row.review_id}" data-status="rejected" class="small">拒绝</button>
        <button data-escalate="${row.review_id}" class="small">升级复核</button>
        ` : ""}
      </div>
    </div>
  `;
}

function bindRowActions(container, reportPanel) {
  container.querySelectorAll("[data-review]").forEach((button) => {
    button.addEventListener("click", () => openReviewModal(button.dataset.review, button.dataset.status));
  });
  container.querySelectorAll("[data-report]").forEach((button) => {
    button.addEventListener("click", () => loadDoctorReport(button.dataset.report, reportPanel));
  });
  container.querySelectorAll("[data-escalate]").forEach((button) => {
    button.addEventListener("click", () => confirmEscalate(button.dataset.escalate));
  });
}

async function loadReviews(force = false) {
  showSkeleton(els.reviewList, 4);
  try {
    const rows = await fetchReviews(force);
    const pending = rows.filter((r) => PENDING_STATES.includes(r.status));
    els.reviewList.innerHTML = pending.length
      ? pending.map((r) => reviewRow(r)).join("")
      : "<div class='empty-state'><p>暂无待复核记录</p></div>";
    bindRowActions(els.reviewList, els.reportPanel);
  } catch (error) {
    setError(els.reviewList, `加载失败: ${error.message}`, () => loadReviews(true));
  }
}

async function loadHighRisk(force = false) {
  showSkeleton(els.highRiskList, 4);
  try {
    const rows = await fetchReviews(force);
    const high = rows.filter((r) => r.risk_level === "high");
    els.highRiskList.innerHTML = high.length
      ? high.map((r) => reviewRow(r)).join("")
      : "<div class='empty-state'><p>暂无高风险咨询</p></div>";
    bindRowActions(els.highRiskList, els.highRiskReportPanel);
  } catch (error) {
    setError(els.highRiskList, `加载失败: ${error.message}`, () => loadHighRisk(true));
  }
}

async function loadHistory(force = false) {
  showSkeleton(els.historyList, 4);
  try {
    const rows = await fetchReviews(force);
    const done = rows.filter((r) => !PENDING_STATES.includes(r.status));
    els.historyList.innerHTML = done.length
      ? done.map((r) => reviewRow(r, { actions: false })).join("")
      : "<div class='empty-state'><p>暂无复核历史</p></div>";
    bindRowActions(els.historyList, null);
  } catch (error) {
    setError(els.historyList, `加载失败: ${error.message}`, () => loadHistory(true));
  }
}

async function loadDashboard() {
  showSkeleton(els.dashboardBox, 4);
  try {
    const rows = await fetchReviews(true);
    const pending = rows.filter((r) => PENDING_STATES.includes(r.status)).length;
    const high = rows.filter((r) => r.risk_level === "high").length;
    const done = rows.filter((r) => !PENDING_STATES.includes(r.status)).length;
    els.dashboardBox.innerHTML = `
      <div class="dashboard-card accent">
        <span class="dash-label">待复核</span>
        <span class="dash-value">${pending}</span>
      </div>
      <div class="dashboard-card risk-high">
        <span class="dash-label">高风险</span>
        <span class="dash-value">${high}</span>
      </div>
      <div class="dashboard-card">
        <span class="dash-label">已处理</span>
        <span class="dash-value">${done}</span>
      </div>
      <div class="dashboard-card">
        <span class="dash-label">总计</span>
        <span class="dash-value">${rows.length}</span>
      </div>
    `;
  } catch (error) {
    setError(els.dashboardBox, `加载失败: ${error.message}`, loadDashboard);
  }
}

// ===== Three-column report =====
async function loadDoctorReport(consultationId, panel) {
  const target = panel || els.reportPanel;
  target.innerHTML = '<div class="loading-spinner">正在加载报告...</div>';
  try {
    const raw = await request(`/api/doctor/consultations/${consultationId}/report`);
    const d = normalizeDoctorReport(raw);
    const c = d.consultation;

    const patientCol = `
      <div class="report-col patient-col">
        <h3>患者信息</h3>
        <div class="result-metrics compact">
          <div class="metric-card"><span>智能体</span><strong>${agentLabel(c.agent_type)}</strong></div>
          <div class="metric-card risk-${c.risk_level}"><span>风险</span><strong>${riskLabel(c.risk_level)}</strong></div>
          <div class="metric-card"><span>状态</span><strong>${escapeHtml(c.status)}</strong></div>
        </div>
        <div class="result-section">
          <h4>主诉/摘要</h4>
          <p>${escapeHtml(c.summary || "")}</p>
        </div>
      </div>
    `;

    let aiInner = renderStructuredData(d.structured, "doctor");
    aiInner += renderObjectList("检索来源", d.retrievalHits, "title", "excerpt");
    aiInner += `<div class="result-section"><h4>LLM 调用详情</h4>${renderLlmCalls(d.llmCalls, d.llmCall)}</div>`;
    if (d.trace && d.trace.length) aiInner += renderTrace(d.trace);
    const aiCol = `<div class="report-col ai-col"><h3>AI 结果与证据</h3>${aiInner}</div>`;

    const reviewCol = `
      <div class="report-col review-col">
        <h3>复核操作</h3>
        <p class="muted">从待复核队列对该咨询执行通过/退回/升级等操作。</p>
        <div class="result-section">
          <h4>免责声明</h4>
          <p>${escapeHtml(d.disclaimer)}</p>
        </div>
      </div>
    `;

    target.innerHTML = `<div class="doctor-report">${patientCol}${aiCol}${reviewCol}</div>`;
    showToast("报告已加载");
  } catch (error) {
    setError(target, `报告加载失败: ${error.message}`, () => loadDoctorReport(consultationId, panel));
  }
}

// ===== Review modal =====
async function openReviewModal(reviewId, status) {
  currentReviewId = reviewId;
  currentReviewStatus = status;
  const templates = await request("/api/doctor/review-templates");
  const statusLabels = {
    approved: "通过",
    needs_followup: "需随访",
    returned_for_info: "退回补充",
    rejected: "拒绝",
  };

  const { overlay } = openModal(`
    <div class="modal-header">
      <h3>${statusLabels[status]}复核 #${reviewId}</h3>
      <button class="modal-close" data-modal-close>&times;</button>
    </div>
    <div class="modal-body">
      <div style="display: grid; gap: 12px;">
        <div>
          <label>复核模板</label>
          <select id="reviewTemplateSelect">
            <option value="">选择模板（可选）</option>
            ${templates.map((t) => `<option value="${t.template_id}">${t.name}</option>`).join("")}
          </select>
        </div>
        <div id="templateFieldsBox" class="template-fields"></div>
        <div>
          <label>风险评估</label>
          <textarea id="riskAssessmentInput" rows="3" placeholder="请输入风险评估意见..."></textarea>
        </div>
        <div>
          <label>治疗决策</label>
          <select id="treatmentDecisionSelect">
            <option value="">请选择治疗决策</option>
            <option value="refer_to_clinic">建议面诊</option>
            <option value="medication">药物治疗</option>
            <option value="procedure">手术治疗</option>
            <option value="observation">观察随访</option>
            <option value="further_test">进一步检查</option>
          </select>
        </div>
        <div>
          <label>医生签名</label>
          <input type="text" id="signatureInput" placeholder="输入姓名">
        </div>
        <div>
          <label>职称</label>
          <input type="text" id="signatureTitleInput" placeholder="例如：主治医师">
        </div>
        <div>
          <label>随访说明（如需随访）</label>
          <textarea id="followupInstructionInput" rows="3" placeholder="请输入随访要求..."></textarea>
        </div>
        <div>
          <label>备注说明</label>
          <textarea id="reviewNoteInput" rows="3" placeholder="请输入备注说明..."></textarea>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button id="submitReviewBtn" class="primary">确认${statusLabels[status]}</button>
      <button data-modal-close>取消</button>
    </div>
  `);
  currentModalOverlay = overlay;

  overlay.querySelector("#reviewTemplateSelect").addEventListener("change", (event) => {
    renderReviewTemplateFields(overlay, templates.find((item) => item.template_id === event.target.value));
  });
  overlay.querySelector("#submitReviewBtn").addEventListener("click", () => submitReview().catch((e) => showToast(e.message, "error")));
}

function renderReviewTemplateFields(overlay, template) {
  const box = overlay.querySelector("#templateFieldsBox");
  if (!box) return;
  if (!template) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <div class="template-field-grid">
      ${template.fields.map((field) => `
        <label>
          ${escapeHtml(field.label)}
          ${field.type === "select" ? `
            <select data-template-field="${escapeHtml(field.key)}">
              ${(field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join("")}
            </select>
          ` : `<input data-template-field="${escapeHtml(field.key)}" placeholder="${escapeHtml(field.label)}" />`}
        </label>
      `).join("")}
    </div>
  `;
}

function collectStructuredOpinion(overlay) {
  const opinion = {};
  overlay.querySelectorAll("[data-template-field]").forEach((input) => {
    opinion[input.dataset.templateField] = input.value;
  });
  return Object.keys(opinion).length ? opinion : null;
}

async function submitReview() {
  const overlay = currentModalOverlay;
  const payload = {
    status: currentReviewStatus,
    review_template: overlay.querySelector("#reviewTemplateSelect").value || null,
    risk_assessment: overlay.querySelector("#riskAssessmentInput").value || null,
    treatment_decision: overlay.querySelector("#treatmentDecisionSelect").value || null,
    signature: overlay.querySelector("#signatureInput").value || null,
    signature_title: overlay.querySelector("#signatureTitleInput").value || null,
    followup_instruction: overlay.querySelector("#followupInstructionInput").value || null,
    note: overlay.querySelector("#reviewNoteInput").value || null,
    structured_opinion: collectStructuredOpinion(overlay),
  };
  await request(`/api/doctor/reviews/${currentReviewId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  closeModal(overlay);
  currentModalOverlay = null;
  await refreshAll();
  showToast("复核已提交");
}

// ===== Escalate with secondary confirm =====
function confirmEscalate(reviewId) {
  const { overlay } = openModal(`
    <div class="modal-header">
      <h3>升级为二级复核</h3>
      <button class="modal-close" data-modal-close>&times;</button>
    </div>
    <div class="modal-body">
      <p>确认将复核 #${escapeHtml(reviewId)} 升级为二级（管理员）复核？此操作会通知上级。</p>
    </div>
    <div class="modal-footer">
      <button id="confirmEscalateBtn" class="primary">确认升级</button>
      <button data-modal-close>取消</button>
    </div>
  `);
  overlay.querySelector("#confirmEscalateBtn").addEventListener("click", async () => {
    try {
      await escalateReview(reviewId);
      closeModal(overlay);
    } catch (error) {
      showToast(error.message, "error");
    }
  });
}

async function escalateReview(reviewId) {
  await request(`/api/doctor/reviews/${reviewId}/escalate`, {
    method: "POST",
    body: JSON.stringify({ reason: "医生发起二级复核", to_role: "admin" }),
  });
  await refreshAll();
  showToast("已升级为二级复核");
}

async function refreshAll() {
  await fetchReviews(true);
  await Promise.all([loadReviews(), loadHighRisk(), loadHistory(), loadDashboard()]);
}

function onSection(section) {
  setPageTitle(SECTION_TITLES[section] || "");
  if (section === "dashboard") loadDashboard();
  else if (section === "reviews") loadReviews();
  else if (section === "highRisk") loadHighRisk();
  else if (section === "history") loadHistory();
}

function bindDoctorEvents() {
  els.logoutBtn.addEventListener("click", logout);
  els.refreshReviewBtn.addEventListener("click", () => loadReviews(true));
  els.refreshHighRiskBtn.addEventListener("click", () => loadHighRisk(true));
  els.refreshHistoryBtn.addEventListener("click", () => loadHistory(true));
}

async function initDoctorApp() {
  cacheEls();
  const user = await requireRole("doctor");
  if (!user) return;
  renderCurrentUser();
  flushPendingToast();
  bindDoctorEvents();
  initNav("dashboard", onSection);
}

initDoctorApp();
