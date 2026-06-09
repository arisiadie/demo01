import { request } from "./shared/api.js";
import { getCurrentUser } from "./shared/state.js";
import { logout, requireRole } from "./shared/auth.js";
import { showToast, setStatus, openModal, closeModal } from "./shared/components.js";
import { escapeHtml, formatDate, riskLabel, agentLabel, agentRoleLabel } from "./shared/format.js";
import {
  renderStructuredData,
  renderObjectList,
  renderTrace,
  renderLlmCalls,
} from "./shared/result.js";

const els = {};
let currentReviewId = null;
let currentReviewStatus = null;
let currentModalOverlay = null;

function cacheEls() {
  ["currentUserText", "logoutBtn", "resultPanel", "reviewList", "refreshReviewBtn"].forEach((id) => {
    els[id] = document.querySelector(`#${id}`);
  });
}

function renderCurrentUser() {
  const user = getCurrentUser();
  els.currentUserText.textContent = user
    ? `${user.display_name} · ${agentRoleLabel(user.role)}`
    : "未登录";
}

function showError(error) {
  setStatus("发生错误");
  els.resultPanel.classList.remove("empty", "loading");
  els.resultPanel.innerHTML = `
    <div style="text-align: center; padding: 40px;">
      <div style="font-size: 48px; margin-bottom: 16px;">✕</div>
      <h3 style="color: var(--danger);">请求失败</h3>
      <p>${escapeHtml(error.message)}</p>
    </div>
  `;
  showToast(error.message, "error");
}

async function loadReviews() {
  try {
    const rows = await request("/api/doctor/reviews");
    els.reviewList.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
              <div class="review-item ${row.status === "approved" ? "approved" : row.status === "rejected" ? "rejected" : ""}">
                <strong>复核 #${row.review_id} · 咨询 #${row.consultation_id}</strong>
                <div class="review-meta">
                  <span>状态: ${escapeHtml(row.status)}</span>
                  <span class="risk-${row.risk_level}">${riskLabel(row.risk_level)}</span>
                  <span>${agentLabel(row.agent_type)}</span>
                </div>
                <div>${escapeHtml(row.summary.slice(0, 100))}${row.summary.length > 100 ? "..." : ""}</div>
                <button data-report="${row.consultation_id}" class="small">查看报告</button>
                ${row.status === "pending" || row.status === "returned_for_info" || row.status === "escalated" ? `
                <button data-review="${row.review_id}" data-status="approved" class="small primary">通过</button>
                <button data-review="${row.review_id}" data-status="needs_followup" class="small">需随访</button>
                <button data-review="${row.review_id}" data-status="returned_for_info" class="small">退回补充</button>
                <button data-review="${row.review_id}" data-status="rejected" class="small">拒绝</button>
                <button data-escalate="${row.review_id}" class="small">升级复核</button>
                ` : ""}
              </div>
            `,
          )
          .join("")
      : "<div class='review-item'>暂无待复核记录</div>";

    els.reviewList.querySelectorAll("[data-review]").forEach((button) => {
      button.addEventListener("click", () => openReviewModal(button.dataset.review, button.dataset.status));
    });
    els.reviewList.querySelectorAll("[data-report]").forEach((button) => {
      button.addEventListener("click", () => loadDoctorReport(button.dataset.report));
    });
    els.reviewList.querySelectorAll("[data-escalate]").forEach((button) => {
      button.addEventListener("click", () => escalateReview(button.dataset.escalate).catch(showError));
    });
  } catch (error) {
    els.reviewList.innerHTML = `<div class="review-item">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function loadDoctorReport(consultationId) {
  try {
    const data = await request(`/api/doctor/consultations/${consultationId}/report`);
    let html = `
      <div class="result-header">
        <div class="result-title">
          <h3>医生复核报告 #${escapeHtml(data.consultation.id)}</h3>
        </div>
      </div>
      <div class="result-metrics">
        <div class="metric-card"><span>智能体</span><strong>${agentLabel(data.consultation.agent_type)}</strong></div>
        <div class="metric-card risk-${data.consultation.risk_level}"><span>风险等级</span><strong>${riskLabel(data.consultation.risk_level)}</strong></div>
        <div class="metric-card"><span>状态</span><strong>${escapeHtml(data.consultation.status)}</strong></div>
      </div>
      <div class="result-content">
        <p>${escapeHtml(data.consultation.summary)}</p>
      </div>
    `;
    html += renderStructuredData(data.structured_outputs, "doctor");
    html += renderObjectList("检索来源", data.retrieval_hits, "title", "excerpt");
    html += `
      <div class="result-section">
        <h4>LLM 调用详情</h4>
        ${renderLlmCalls(data.llm_calls || [], data.llm_call)}
      </div>
    `;
    if (data.agent_run) html += renderTrace(data.agent_run.trace);
    html += `
      <div class="result-section">
        <h4>免责声明</h4>
        <p>${escapeHtml(data.disclaimer)}</p>
      </div>
    `;
    els.resultPanel.classList.remove("empty");
    els.resultPanel.innerHTML = html;
    showToast("报告已加载");
  } catch (error) {
    showError(error);
  }
}

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
  overlay.querySelector("#submitReviewBtn").addEventListener("click", () => submitReview().catch(showError));
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
  els.resultPanel.innerHTML = '<div class="empty">请选择一个操作</div>';
  await loadReviews();
  showToast("复核已提交");
}

async function escalateReview(reviewId) {
  const data = await request(`/api/doctor/reviews/${reviewId}/escalate`, {
    method: "POST",
    body: JSON.stringify({ reason: "医生发起二级复核", to_role: "admin" }),
  });
  els.resultPanel.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  await loadReviews();
  showToast("已升级为二级复核");
}

function bindDoctorEvents() {
  els.logoutBtn.addEventListener("click", logout);
  els.refreshReviewBtn.addEventListener("click", loadReviews);
}

async function initDoctorApp() {
  cacheEls();
  const user = await requireRole("doctor");
  if (!user) return;
  renderCurrentUser();
  bindDoctorEvents();
  loadReviews();
}

initDoctorApp();
