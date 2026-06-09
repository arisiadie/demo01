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
  dataRequestTypeLabel,
  dataRequestStatusLabel,
  toIsoOrNull,
} from "./shared/format.js";
import {
  renderAgentResult,
  renderStructuredData,
  renderObjectList,
  renderList,
  renderReviewStatus,
} from "./shared/result.js";

const DEPTH = { depth: "patient" };
const els = {};

function cacheEls() {
  const ids = [
    "currentUserText", "logoutBtn", "scenarioList", "agentSelect", "messageInput",
    "sendBtn", "clearBtn", "reportInput", "imageInput", "imagingBtn", "resultPanel",
    "historyList", "refreshHistoryBtn", "profileNameInput", "ageInput", "sexInput",
    "pregnancyInput", "allergyInput", "conditionInput", "oralHistoryInput",
    "saveProfileBtn", "loadCareBtn", "careBox", "recordTreatmentInput",
    "recordDiagnosisInput", "recordNextVisitInput", "addRecordBtn", "reminderNoteInput",
    "addReminderBtn", "toothPositionInput", "toothStatusInput", "toothCycleInput",
    "addToothRecordBtn", "loadToothChartBtn", "loadMaintenanceBtn", "loadEducationFeedBtn",
    "pushEducationFeedBtn", "runDueNotificationsBtn", "signConsentBtn", "loadConsentsBtn",
    "requestExportBtn", "requestDeleteBtn", "loadPatientDataRequestsBtn",
  ];
  ids.forEach((id) => { els[id] = document.querySelector(`#${id}`); });
}

function renderCurrentUser() {
  const user = getCurrentUser();
  els.currentUserText.textContent = user
    ? `${user.display_name} · ${agentRoleLabel(user.role)}`
    : "未登录";
}

function profilePayload() {
  const age = Number.parseInt(els.ageInput.value, 10);
  return {
    name: els.profileNameInput.value.trim() || null,
    age: Number.isFinite(age) ? age : null,
    sex: els.sexInput.value.trim() || null,
    pregnancy_status: els.pregnancyInput.value.trim() || null,
    allergies: els.allergyInput.value.trim() || null,
    conditions: els.conditionInput.value.trim() || null,
    oral_history: els.oralHistoryInput.value.trim() || null,
  };
}

async function loadScenarios() {
  const scenarios = await request("/api/demo/scenarios");
  els.scenarioList.innerHTML = scenarios
    .map((item, index) => `
      <button class="scenario" data-index="${index}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.message)}</span>
      </button>
    `)
    .join("");
  els.scenarioList.querySelectorAll(".scenario").forEach((button) => {
    button.addEventListener("click", () => {
      const item = scenarios[Number(button.dataset.index)];
      els.agentSelect.value = item.agent;
      els.messageInput.value = item.message;
      showToast(`已加载场景: ${item.title}`);
    });
  });
}

async function saveProfile() {
  const data = await request("/api/patient/profile", {
    method: "PUT",
    body: JSON.stringify(profilePayload()),
  });
  showToast(data.ok ? "资料保存成功" : "保存失败", data.ok ? "success" : "error");
}

async function loadProfile() {
  try {
    const data = await request("/api/patient/profile");
    els.profileNameInput.value = data.name || "";
    els.ageInput.value = data.age ?? "";
    els.sexInput.value = data.sex || "";
    els.pregnancyInput.value = data.pregnancy_status || "";
    els.allergyInput.value = data.allergies || "";
    els.conditionInput.value = data.conditions || "";
    els.oralHistoryInput.value = data.oral_history || "";
  } catch {
    // best effort
  }
}

async function loadCare() {
  try {
    const [records, reminders, notifications, toothRecords] = await Promise.all([
      request("/api/patient/treatment-records"),
      request("/api/patient/reminders"),
      request("/api/patient/notifications"),
      request("/api/patient/tooth-records"),
    ]);

    let html = "";
    if (records.length > 0) {
      html += `<div class="history-item"><strong>治疗记录</strong>`;
      records.forEach((item) => {
        html += `<div>${escapeHtml(item.treatment_name)} · ${escapeHtml(item.diagnosis_text || "")}</div>`;
      });
      html += `</div>`;
    }
    if (reminders.length > 0) {
      html += `<div class="history-item"><strong>复诊提醒</strong>`;
      reminders.forEach((item) => {
        html += `<div>${escapeHtml(item.note)} · ${item.due_at ? formatDate(item.due_at) : ""} · ${escapeHtml(item.status)}</div>`;
      });
      html += `</div>`;
    }
    if (toothRecords.length > 0) {
      html += `<div class="history-item"><strong>牙位档案</strong>`;
      toothRecords.slice(0, 8).forEach((item) => {
        html += `<div>${escapeHtml(item.tooth_position)} · ${escapeHtml(item.status)} · ${item.next_check_at ? formatDate(item.next_check_at) : "未设复查"}</div>`;
      });
      html += `</div>`;
    }
    if (notifications.length > 0) {
      html += `<div class="history-item pending"><strong>站内通知</strong>`;
      notifications.forEach((item) => {
        html += `<div>${escapeHtml(item.title)} · ${escapeHtml(item.status)}${item.content ? ` · ${escapeHtml(item.content.slice(0, 48))}` : ""}</div>`;
      });
      html += `</div>`;
    }
    els.careBox.innerHTML = html || "<div class='history-item'>暂无记录</div>";
  } catch (error) {
    els.careBox.innerHTML = `<div class='history-item'>加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function addTreatmentRecord() {
  const treatmentName = els.recordTreatmentInput.value.trim();
  const diagnosisText = els.recordDiagnosisInput.value.trim();
  if (!treatmentName || !diagnosisText) {
    showToast("请填写治疗名称和诊断", "warning");
    return;
  }
  await request("/api/patient/treatment-records", {
    method: "POST",
    body: JSON.stringify({
      treatment_name: treatmentName,
      diagnosis_text: diagnosisText,
      next_visit_at: toIsoOrNull(els.recordNextVisitInput.value),
    }),
  });
  els.recordTreatmentInput.value = "";
  els.recordDiagnosisInput.value = "";
  await loadCare();
  showToast("治疗记录已添加");
}

async function addReminder() {
  const note = els.reminderNoteInput.value.trim();
  if (!note) {
    showToast("请填写提醒内容", "warning");
    return;
  }
  await request("/api/patient/reminders", {
    method: "POST",
    body: JSON.stringify({ note, due_at: toIsoOrNull(els.recordNextVisitInput.value) }),
  });
  els.reminderNoteInput.value = "";
  await loadCare();
  showToast("提醒已添加");
}

async function addToothRecord() {
  const toothPosition = els.toothPositionInput.value.trim();
  if (!toothPosition) {
    showToast("请填写牙位", "warning");
    return;
  }
  const cycleDays = Number.parseInt(els.toothCycleInput.value, 10);
  const data = await request("/api/patient/tooth-records", {
    method: "POST",
    body: JSON.stringify({
      tooth_position: toothPosition,
      status: els.toothStatusInput.value.trim() || "观察",
      diagnosis_text: els.recordDiagnosisInput.value.trim() || null,
      treatment_summary: els.recordTreatmentInput.value.trim() || null,
      maintenance_cycle_days: Number.isFinite(cycleDays) ? cycleDays : 180,
    }),
  });
  els.careBox.innerHTML = renderToothRecordResult(data);
  showToast("牙位档案已保存");
}

async function loadMaintenancePlan() {
  const data = await request("/api/patient/maintenance-plan");
  els.careBox.innerHTML = renderMaintenancePlan(data);
  showToast("维护计划已加载");
}

async function loadToothChart() {
  const data = await request("/api/patient/tooth-chart");
  els.careBox.innerHTML = renderToothChart(data);
  showToast("牙位图已加载");
}

async function loadEducationFeed() {
  const data = await request("/api/patient/education-feed");
  els.careBox.innerHTML = renderEducationFeed(data);
  showToast("科普推送已加载");
}

async function pushEducationFeed() {
  const data = await request("/api/patient/education-feed/push", {
    method: "POST",
    body: JSON.stringify({ limit: 5 }),
  });
  els.careBox.innerHTML = renderEducationFeed(data.feed, data.notifications, data.created_count);
  await loadCare();
  showToast(`已生成 ${data.created_count} 条站内科普`);
}

async function runDueNotifications() {
  const data = await request("/api/patient/notifications/due", { method: "POST" });
  els.careBox.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  showToast("到期提醒已扫描");
}

async function signConsent() {
  const user = getCurrentUser();
  const data = await request("/api/patient/consents", {
    method: "POST",
    body: JSON.stringify({
      consent_type: "ai_medical_assist",
      consent_version: "v1.0",
      scope: "AI辅助咨询、RAG检索、医生复核、历史归档",
      consent_text: "我知晓本平台输出仅为AI辅助参考，不替代执业医师诊断、处方或治疗决策；我同意在内测范围内保存咨询、检索来源和医生复核记录。",
      signature: user?.display_name || "patient-demo",
    }),
  });
  els.careBox.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  showToast("同意记录已签署");
}

async function loadConsents() {
  const data = await request("/api/patient/consents");
  els.careBox.innerHTML = renderSimpleTable("同意记录", data, ["consent_type", "consent_version", "scope", "signed_at"]);
  showToast("同意记录已加载");
}

async function createDataRequest(type) {
  const data = await request("/api/patient/data-request", {
    method: "POST",
    body: JSON.stringify({
      request_type: type,
      data_scope: type === "export" ? "profile,consultations,consents" : "profile,consultations",
      reason: type === "export" ? "患者申请导出内测数据" : "患者申请删除内测数据",
    }),
  });
  els.careBox.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  showToast(type === "export" ? "导出申请已提交" : "删除申请已提交");
}

async function loadPatientDataRequests() {
  const data = await request("/api/patient/data-requests");
  els.careBox.innerHTML = renderDataRequests("我的数据申请", data);
  showToast("数据申请记录已加载");
}

async function sendConsultation() {
  const message = els.messageInput.value.trim();
  if (!message) {
    showToast("请输入咨询内容", "warning");
    return;
  }
  setStatus("智能体处理中...");
  els.sendBtn.disabled = true;
  els.resultPanel.classList.remove("empty");
  els.resultPanel.innerHTML = '<div class="loading-spinner">正在分析您的问题...</div>';
  try {
    const data = await request("/api/consultations", {
      method: "POST",
      body: JSON.stringify({
        message,
        requested_agent: els.agentSelect.value || null,
        patient_profile: profilePayload(),
      }),
    });
    els.resultPanel.classList.remove("empty", "loading");
    els.resultPanel.innerHTML = renderAgentResult(data, DEPTH);
    await loadHistory();
    showToast("咨询完成");
  } catch (error) {
    showError(error);
  } finally {
    els.sendBtn.disabled = false;
    setStatus("就绪");
  }
}

async function sendImaging() {
  setStatus("上传解读中...");
  els.imagingBtn.disabled = true;
  els.resultPanel.classList.remove("empty");
  els.resultPanel.innerHTML = '<div class="loading-spinner">正在分析影像报告...</div>';
  try {
    const form = new FormData();
    form.append("report_text", els.reportInput.value.trim());
    if (els.imageInput.files[0]) form.append("image", els.imageInput.files[0]);
    const data = await request("/api/imaging/analyze", { method: "POST", body: form });
    els.resultPanel.classList.remove("empty", "loading");
    els.resultPanel.innerHTML = renderAgentResult(data, DEPTH);
    await loadHistory();
    showToast("影像解读完成");
  } catch (error) {
    showError(error);
  } finally {
    els.imagingBtn.disabled = false;
    setStatus("就绪");
  }
}

async function loadHistory() {
  try {
    const rows = await request("/api/consultations/history");
    els.historyList.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
              <div class="history-item" data-history="${row.id}">
                <strong>#${row.id} · ${agentLabel(row.agent_type)}</strong>
                <div class="history-meta">
                  <span class="risk-${row.risk_level}">${riskLabel(row.risk_level)}</span>
                  ${row.doctor_review_required ? "<span>需复核</span>" : ""}
                  <span>${formatDate(row.created_at)}</span>
                </div>
                <div>${escapeHtml(row.summary.slice(0, 100))}${row.summary.length > 100 ? "..." : ""}</div>
              </div>
            `,
          )
          .join("")
      : "<div class='history-item'>暂无历史记录</div>";
    els.historyList.querySelectorAll("[data-history]").forEach((item) => {
      item.addEventListener("click", () => loadConsultationDetail(item.dataset.history));
    });
  } catch (error) {
    els.historyList.innerHTML = `<div class="history-item">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function loadConsultationDetail(consultationId) {
  try {
    const data = await request(`/api/consultations/${consultationId}`);
    renderConsultationArchive(data);
    showToast("历史归档已加载");
  } catch (error) {
    showError(error);
  }
}

function renderConsultationArchive(data) {
  const consultation = data.consultation || {};
  const response = data.agent_response || {};
  let html = `
    <div class="result-header">
      <div class="result-title">
        <h3>历史归档 #${escapeHtml(consultation.id)}</h3>
        <span class="agent-badge">${agentLabel(consultation.agent_type)}</span>
      </div>
    </div>
    <div class="result-metrics">
      <div class="metric-card risk-${consultation.risk_level}"><span>风险等级</span><strong>${riskLabel(consultation.risk_level)}</strong></div>
      <div class="metric-card"><span>状态</span><strong>${escapeHtml(consultation.status)}</strong></div>
      <div class="metric-card"><span>医生复核</span><strong>${consultation.doctor_review_required ? "需要" : "暂不需要"}</strong></div>
      <div class="metric-card"><span>来源</span><strong>${(data.retrieval_hits || []).length}</strong></div>
    </div>
    <div class="result-section">
      <h4>用户输入</h4>
      <p>${escapeHtml(consultation.sanitized_input || consultation.input_text || "")}</p>
    </div>
    <div class="result-section">
      <h4>归档摘要</h4>
      <p>${escapeHtml(consultation.summary || response.summary || "")}</p>
    </div>
  `;
  html += renderStructuredData(data.structured_outputs || response.structured_data, "patient");
  html += renderObjectList("检索来源", data.retrieval_hits || consultation.sources || [], "title", "excerpt");
  if (data.review) html += renderReviewStatus(data.review);
  html += `
    <div class="result-section">
      <h4>免责声明</h4>
      <p>${escapeHtml(data.disclaimer || response.disclaimer || "")}</p>
    </div>
  `;
  els.resultPanel.classList.remove("empty");
  els.resultPanel.innerHTML = html;
}

function renderToothRecordResult(data) {
  const record = data.tooth_record || {};
  const plan = data.maintenance_plan || {};
  return `
    <div class="care-card">
      <h3>${escapeHtml(record.tooth_position || "-")} 牙位档案</h3>
      <div class="result-metrics compact">
        <div class="metric-card risk-${plan.risk_level || "low"}"><span>风险</span><strong>${riskLabel(plan.risk_level)}</strong></div>
        <div class="metric-card"><span>维护周期</span><strong>${escapeHtml(record.maintenance_cycle_days || "-")}天</strong></div>
        <div class="metric-card"><span>下次复查</span><strong>${plan.next_check_at ? formatDate(plan.next_check_at) : "-"}</strong></div>
      </div>
      <p>${escapeHtml(plan.next_action || "")}</p>
      ${renderList("维护重点", plan.focus || [])}
    </div>
  `;
}

function renderMaintenancePlan(data) {
  const toothPlans = data.tooth_plans || [];
  return `
    <div class="care-card">
      <h3>个性化维护计划</h3>
      ${renderList("通用建议", data.general_recommendations || [])}
      <div class="care-grid">
        ${toothPlans.length ? toothPlans.map((plan) => `
          <div class="care-item risk-border-${plan.risk_level}">
            <strong>${escapeHtml(plan.tooth_position)} · ${riskLabel(plan.risk_level)}</strong>
            <p>${escapeHtml(plan.next_action)}</p>
            <span>${plan.next_check_at ? formatDate(plan.next_check_at) : "未设置复查时间"}</span>
          </div>
        `).join("") : "<p>暂无牙位维护计划</p>"}
      </div>
    </div>
  `;
}

function renderToothChart(data) {
  const teeth = data.teeth || [];
  const summary = data.summary || {};
  const upper = teeth.slice(0, 16);
  const lower = teeth.slice(16);
  const toothButton = (tooth) => `
    <button class="tooth-cell risk-${tooth.risk_level}${tooth.overdue ? " overdue" : ""}" title="${escapeHtml(tooth.label)} ${escapeHtml(tooth.record?.status || "无档案")}">
      <span>${escapeHtml(tooth.position)}</span>
      <small>${escapeHtml(tooth.record?.status || "无")}</small>
    </button>
  `;
  const recordCards = teeth
    .filter((tooth) => tooth.has_record)
    .map((tooth) => `
      <div class="care-item risk-border-${tooth.risk_level}">
        <strong>${escapeHtml(tooth.label)} / ${escapeHtml(tooth.position)}</strong>
        <p>${escapeHtml(tooth.record.status)}${tooth.overdue ? " · 已到期" : ""}</p>
        <span>${escapeHtml(tooth.plan?.next_action || "")}</span>
      </div>
    `)
    .join("");
  return `
    <div class="care-card">
      <h3>牙位图</h3>
      <div class="result-metrics compact">
        <div class="metric-card"><span>已建档</span><strong>${summary.record_count || 0}</strong></div>
        <div class="metric-card risk-high"><span>高风险</span><strong>${summary.risk_counts?.high || 0}</strong></div>
        <div class="metric-card risk-medium"><span>中风险</span><strong>${summary.risk_counts?.medium || 0}</strong></div>
        <div class="metric-card"><span>到期</span><strong>${summary.overdue_count || 0}</strong></div>
      </div>
      <div class="tooth-chart">
        <div class="tooth-row upper">${upper.map(toothButton).join("")}</div>
        <div class="tooth-midline"></div>
        <div class="tooth-row lower">${lower.map(toothButton).join("")}</div>
      </div>
      <div class="tooth-legend">
        <span class="legend-dot risk-unknown"></span>无档案
        <span class="legend-dot risk-low"></span>低风险
        <span class="legend-dot risk-medium"></span>中风险
        <span class="legend-dot risk-high"></span>高风险
      </div>
      <div class="care-grid">${recordCards || "<p>暂无牙位档案，请先保存牙位记录。</p>"}</div>
    </div>
  `;
}

function renderEducationFeed(feed, notifications = [], createdCount = null) {
  const items = feed?.items || [];
  return `
    <div class="care-card">
      <h3>个性化科普推送</h3>
      ${createdCount !== null ? `<p>本次新增站内科普通知 ${createdCount} 条。</p>` : ""}
      <div class="tag-list">${(feed?.focus_terms || []).map((term) => `<span>${escapeHtml(term)}</span>`).join("")}</div>
      <div class="education-list">
        ${items.length ? items.map((item) => `
          <article class="education-item">
            <div class="education-title">${escapeHtml(item.title)}</div>
            <div class="source-meta">
              <span>${escapeHtml(getCategoryName(item.category))}</span>
              <span>${escapeHtml(item.source)}</span>
              <span>命中分: ${escapeHtml(item.score)}</span>
            </div>
            <p>${escapeHtml(item.excerpt)}</p>
            <div class="education-reason">${escapeHtml(item.recommendation_reason)}</div>
            <div class="tag-list">${(item.matched_terms || []).map((term) => `<span>${escapeHtml(term)}</span>`).join("")}</div>
          </article>
        `).join("") : "<p>暂无科普推荐</p>"}
      </div>
      ${notifications.length ? renderSimpleTable("已生成通知", notifications, ["title", "status", "sent_at"]) : ""}
      <p class="muted">${escapeHtml(feed?.disclaimer || "")}</p>
    </div>
  `;
}

function renderDataRequests(title, rows) {
  return `
    <h3>${escapeHtml(title)}</h3>
    ${rows && rows.length ? rows.map((item) => `
      <div class="admin-row">
        <strong>#${item.id} · ${escapeHtml(dataRequestTypeLabel(item.request_type))} · ${escapeHtml(dataRequestStatusLabel(item.status))}</strong>
        <p>${escapeHtml(item.user_external_id)} · ${escapeHtml(item.data_scope)} · ${escapeHtml(item.reason || "")}</p>
        ${item.processed_at ? `<p>处理人：${escapeHtml(item.processed_by || "-")} · ${formatDate(item.processed_at)} · ${escapeHtml(item.note || "")}</p>` : ""}
        ${item.result_data ? `<details class="export-details"><summary>查看导出数据预览</summary><pre>${escapeHtml(JSON.stringify(item.result_data, null, 2))}</pre></details>` : ""}
      </div>
    `).join("") : "<div class='admin-row'>暂无数据请求</div>"}
  `;
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

function bindPatientEvents() {
  els.logoutBtn.addEventListener("click", logout);
  els.sendBtn.addEventListener("click", sendConsultation);
  els.imagingBtn.addEventListener("click", sendImaging);
  els.clearBtn.addEventListener("click", () => {
    els.messageInput.value = "";
    els.agentSelect.value = "";
  });
  els.saveProfileBtn.addEventListener("click", () => saveProfile().catch(showError));
  els.loadCareBtn.addEventListener("click", () => loadCare().catch(showError));
  els.addRecordBtn.addEventListener("click", () => addTreatmentRecord().catch(showError));
  els.addReminderBtn.addEventListener("click", () => addReminder().catch(showError));
  els.addToothRecordBtn.addEventListener("click", () => addToothRecord().catch(showError));
  els.loadToothChartBtn.addEventListener("click", () => loadToothChart().catch(showError));
  els.loadMaintenanceBtn.addEventListener("click", () => loadMaintenancePlan().catch(showError));
  els.loadEducationFeedBtn.addEventListener("click", () => loadEducationFeed().catch(showError));
  els.pushEducationFeedBtn.addEventListener("click", () => pushEducationFeed().catch(showError));
  els.runDueNotificationsBtn.addEventListener("click", () => runDueNotifications().catch(showError));
  els.signConsentBtn.addEventListener("click", () => signConsent().catch(showError));
  els.loadConsentsBtn.addEventListener("click", () => loadConsents().catch(showError));
  els.requestExportBtn.addEventListener("click", () => createDataRequest("export").catch(showError));
  els.requestDeleteBtn.addEventListener("click", () => createDataRequest("delete").catch(showError));
  els.loadPatientDataRequestsBtn.addEventListener("click", () => loadPatientDataRequests().catch(showError));
  els.refreshHistoryBtn.addEventListener("click", loadHistory);
}

async function initPatientApp() {
  cacheEls();
  const user = await requireRole("patient");
  if (!user) return;
  renderCurrentUser();
  flushPendingToast();
  bindPatientEvents();
  loadScenarios().catch(showError);
  loadProfile();
  loadHistory();
  loadCare();
}

initPatientApp();
