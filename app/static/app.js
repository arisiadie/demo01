const state = {
  role: "patient",
  scenarios: [],
  token: localStorage.getItem("oralcare_token") || "",
  currentUser: JSON.parse(localStorage.getItem("oralcare_user") || "null"),
};

const els = {
  status: document.querySelector("#statusText"),
  roles: document.querySelectorAll(".role"),
  loginUserInput: document.querySelector("#loginUserInput"),
  loginPasswordInput: document.querySelector("#loginPasswordInput"),
  loginBtn: document.querySelector("#loginBtn"),
  logoutBtn: document.querySelector("#logoutBtn"),
  currentUserText: document.querySelector("#currentUserText"),
  scenarioList: document.querySelector("#scenarioList"),
  agentSelect: document.querySelector("#agentSelect"),
  messageInput: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  clearBtn: document.querySelector("#clearBtn"),
  reportInput: document.querySelector("#reportInput"),
  imageInput: document.querySelector("#imageInput"),
  imagingBtn: document.querySelector("#imagingBtn"),
  resultPanel: document.querySelector("#resultPanel"),
  historyList: document.querySelector("#historyList"),
  refreshHistoryBtn: document.querySelector("#refreshHistoryBtn"),
  refreshReviewBtn: document.querySelector("#refreshReviewBtn"),
  reviewList: document.querySelector("#reviewList"),
  ragEvalBtn: document.querySelector("#ragEvalBtn"),
  llmMetricsBtn: document.querySelector("#llmMetricsBtn"),
  adminAlertsBtn: document.querySelector("#adminAlertsBtn"),
  rebuildChromaBtn: document.querySelector("#rebuildChromaBtn"),
  knowledgeBox: document.querySelector("#knowledgeBox"),
  profileNameInput: document.querySelector("#profileNameInput"),
  ageInput: document.querySelector("#ageInput"),
  sexInput: document.querySelector("#sexInput"),
  pregnancyInput: document.querySelector("#pregnancyInput"),
  allergyInput: document.querySelector("#allergyInput"),
  conditionInput: document.querySelector("#conditionInput"),
  oralHistoryInput: document.querySelector("#oralHistoryInput"),
  saveProfileBtn: document.querySelector("#saveProfileBtn"),
  loadCareBtn: document.querySelector("#loadCareBtn"),
  careBox: document.querySelector("#careBox"),
  recordTreatmentInput: document.querySelector("#recordTreatmentInput"),
  recordDiagnosisInput: document.querySelector("#recordDiagnosisInput"),
  recordNextVisitInput: document.querySelector("#recordNextVisitInput"),
  addRecordBtn: document.querySelector("#addRecordBtn"),
  reminderNoteInput: document.querySelector("#reminderNoteInput"),
  addReminderBtn: document.querySelector("#addReminderBtn"),
  toothPositionInput: document.querySelector("#toothPositionInput"),
  toothStatusInput: document.querySelector("#toothStatusInput"),
  toothCycleInput: document.querySelector("#toothCycleInput"),
  addToothRecordBtn: document.querySelector("#addToothRecordBtn"),
  loadToothChartBtn: document.querySelector("#loadToothChartBtn"),
  loadMaintenanceBtn: document.querySelector("#loadMaintenanceBtn"),
  loadEducationFeedBtn: document.querySelector("#loadEducationFeedBtn"),
  pushEducationFeedBtn: document.querySelector("#pushEducationFeedBtn"),
  runDueNotificationsBtn: document.querySelector("#runDueNotificationsBtn"),
  signConsentBtn: document.querySelector("#signConsentBtn"),
  loadConsentsBtn: document.querySelector("#loadConsentsBtn"),
  requestExportBtn: document.querySelector("#requestExportBtn"),
  requestDeleteBtn: document.querySelector("#requestDeleteBtn"),
  loadPatientDataRequestsBtn: document.querySelector("#loadPatientDataRequestsBtn"),
  adminRunDueBtn: document.querySelector("#adminRunDueBtn"),
  loadKnowledgeDocsBtn: document.querySelector("#loadKnowledgeDocsBtn"),
  loadKnowledgeChangesBtn: document.querySelector("#loadKnowledgeChangesBtn"),
  loadWorkflowBtn: document.querySelector("#loadWorkflowBtn"),
  saveWorkflowBtn: document.querySelector("#saveWorkflowBtn"),
  loadConsultationTraceBtn: document.querySelector("#loadConsultationTraceBtn"),
  loadDataRequestsBtn: document.querySelector("#loadDataRequestsBtn"),
  loadAuditBtn: document.querySelector("#loadAuditBtn"),
  loadPrivacyBtn: document.querySelector("#loadPrivacyBtn"),
  knowledgeTitleInput: document.querySelector("#knowledgeTitleInput"),
  knowledgeCategoryInput: document.querySelector("#knowledgeCategoryInput"),
  knowledgeSourceInput: document.querySelector("#knowledgeSourceInput"),
  knowledgeContentInput: document.querySelector("#knowledgeContentInput"),
  workflowJsonInput: document.querySelector("#workflowJsonInput"),
  createKnowledgeDocBtn: document.querySelector("#createKnowledgeDocBtn"),
};

function headers(json = true) {
  const headers = {
    "X-User-Id": `${state.role}-demo`,
    "X-Role": state.role,
  };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

function setStatus(text) {
  els.status.textContent = text;
}

function showToast(message, type = "success", duration = 3000) {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${type === "success" ? "✓" : type === "error" ? "✕" : "!"}</span>
    <div class="toast-content">
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = "slideOut 0.3s ease forwards";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
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

async function login() {
  const data = await request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      external_id: els.loginUserInput.value.trim(),
      password: els.loginPasswordInput.value,
    }),
  });
  state.token = data.access_token;
  state.currentUser = data;
  localStorage.setItem("oralcare_token", state.token);
  localStorage.setItem("oralcare_user", JSON.stringify(data));
  setRole(data.role);
  renderCurrentUser();
  showToast("登录成功");
}

function logout() {
  state.token = "";
  state.currentUser = null;
  localStorage.removeItem("oralcare_token");
  localStorage.removeItem("oralcare_user");
  renderCurrentUser();
  showToast("已安全退出");
}

function renderCurrentUser() {
  if (!state.currentUser) {
    els.currentUserText.textContent = "未登录";
    return;
  }
  els.currentUserText.textContent = `${state.currentUser.display_name} · ${agentRoleLabel(state.currentUser.role)}`;
}

async function loadScenarios() {
  state.scenarios = await request("/api/demo/scenarios");
  els.scenarioList.innerHTML = state.scenarios
    .map((item, index) => `
      <button class="scenario" data-index="${index}">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.message)}</span>
      </button>
    `)
    .join("");
  document.querySelectorAll(".scenario").forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.scenarios[Number(button.dataset.index)];
      els.agentSelect.value = item.agent;
      els.messageInput.value = item.message;
      showToast(`已加载场景: ${item.title}`);
    });
  });
}

async function saveProfile() {
  const data = await request("/api/patient/profile", {
    method: "PUT",
    headers: headers(true),
    body: JSON.stringify(profilePayload()),
  });
  if (data.ok) {
    showToast("资料保存成功");
  } else {
    showToast("保存失败", "error");
  }
}

async function loadProfile() {
  try {
    const data = await request("/api/patient/profile", { headers: headers(false) });
    els.profileNameInput.value = data.name || "";
    els.ageInput.value = data.age ?? "";
    els.sexInput.value = data.sex || "";
    els.pregnancyInput.value = data.pregnancy_status || "";
    els.allergyInput.value = data.allergies || "";
    els.conditionInput.value = data.conditions || "";
    els.oralHistoryInput.value = data.oral_history || "";
  } catch {
    // Profile loading is best effort; current form values can still be used for consultation.
  }
}

async function loadCare() {
  if (state.role !== "patient") return;
  try {
    const [records, reminders, notifications, toothRecords] = await Promise.all([
      request("/api/patient/treatment-records", { headers: headers(false) }),
      request("/api/patient/reminders", { headers: headers(false) }),
      request("/api/patient/notifications", { headers: headers(false) }),
      request("/api/patient/tooth-records", { headers: headers(false) }),
    ]);
    
    let html = "";
    
    if (records.length > 0) {
      html += `<div class="history-item"><strong>治疗记录</strong>`;
      records.forEach(item => {
        html += `<div>${escapeHtml(item.treatment_name)} · ${escapeHtml(item.diagnosis_text || '')}</div>`;
      });
      html += `</div>`;
    }
    
    if (reminders.length > 0) {
      html += `<div class="history-item"><strong>复诊提醒</strong>`;
      reminders.forEach(item => {
        html += `<div>${escapeHtml(item.note)} · ${item.due_at ? formatDate(item.due_at) : ''} · ${escapeHtml(item.status)}</div>`;
      });
      html += `</div>`;
    }
    
    if (toothRecords.length > 0) {
      html += `<div class="history-item"><strong>牙位档案</strong>`;
      toothRecords.slice(0, 8).forEach(item => {
        html += `<div>${escapeHtml(item.tooth_position)} · ${escapeHtml(item.status)} · ${item.next_check_at ? formatDate(item.next_check_at) : "未设复查"}</div>`;
      });
      html += `</div>`;
    }

    if (notifications.length > 0) {
      html += `<div class="history-item pending"><strong>站内通知</strong>`;
      notifications.forEach(item => {
        html += `<div>${escapeHtml(item.title)} · ${escapeHtml(item.status)}${item.content ? ` · ${escapeHtml(item.content.slice(0, 48))}` : ""}</div>`;
      });
      html += `</div>`;
    }
    
    els.careBox.innerHTML = html || "<div class='history-item'>暂无记录</div>";
  } catch (error) {
    els.careBox.innerHTML = `<div class='history-item'>加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

function formatDate(dateStr) {
  try {
    return new Date(dateStr).toLocaleDateString("zh-CN");
  } catch {
    return dateStr;
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
    headers: headers(true),
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
    headers: headers(true),
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
    headers: headers(true),
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
  const data = await request("/api/patient/maintenance-plan", { headers: headers(false) });
  els.careBox.innerHTML = renderMaintenancePlan(data);
  showToast("维护计划已加载");
}

async function loadToothChart() {
  const data = await request("/api/patient/tooth-chart", { headers: headers(false) });
  els.careBox.innerHTML = renderToothChart(data);
  showToast("牙位图已加载");
}

async function loadEducationFeed() {
  const data = await request("/api/patient/education-feed", { headers: headers(false) });
  els.careBox.innerHTML = renderEducationFeed(data);
  showToast("科普推送已加载");
}

async function pushEducationFeed() {
  const data = await request("/api/patient/education-feed/push", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ limit: 5 }),
  });
  els.careBox.innerHTML = renderEducationFeed(data.feed, data.notifications, data.created_count);
  await loadCare();
  showToast(`已生成 ${data.created_count} 条站内科普`);
}

async function runDueNotifications() {
  const data = await request("/api/patient/notifications/due", {
    method: "POST",
    headers: headers(false),
  });
  els.careBox.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  showToast("到期提醒已扫描");
}

async function signConsent() {
  const data = await request("/api/patient/consents", {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({
      consent_type: "ai_medical_assist",
      consent_version: "v1.0",
      scope: "AI辅助咨询、RAG检索、医生复核、历史归档",
      consent_text: "我知晓本平台输出仅为AI辅助参考，不替代执业医师诊断、处方或治疗决策；我同意在内测范围内保存咨询、检索来源和医生复核记录。",
      signature: state.currentUser?.display_name || "patient-demo",
    }),
  });
  els.careBox.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  showToast("同意记录已签署");
}

async function loadConsents() {
  const data = await request("/api/patient/consents", { headers: headers(false) });
  els.careBox.innerHTML = renderSimpleTable("同意记录", data, ["consent_type", "consent_version", "scope", "signed_at"]);
  showToast("同意记录已加载");
}

async function createDataRequest(type) {
  const data = await request("/api/patient/data-request", {
    method: "POST",
    headers: headers(true),
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
  const data = await request("/api/patient/data-requests", { headers: headers(false) });
  els.careBox.innerHTML = renderDataRequests("我的数据申请", data, false);
  showToast("数据申请记录已加载");
}

async function adminRunDueNotifications() {
  const data = await request("/api/admin/notifications/run-due", {
    method: "POST",
    headers: headers(false),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("管理员扫描完成");
}

async function loadWorkflowConfig() {
  const data = await request("/api/admin/workflow/configs/default", { headers: headers(false) });
  const payload = { nodes: data.nodes || [], edges: data.edges || [] };
  els.workflowJsonInput.value = JSON.stringify(payload, null, 2);
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
    headers: headers(true),
    body: JSON.stringify(payload),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("工作流配置已保存");
}

async function loadDataRequests() {
  const data = await request("/api/admin/data-requests", { headers: headers(false) });
  els.knowledgeBox.innerHTML = renderDataRequests("数据导出/删除请求", data, true);
  document.querySelectorAll("[data-data-request]").forEach((button) => {
    button.addEventListener("click", () => processDataRequest(button.dataset.dataRequest, button.dataset.action));
  });
  showToast("数据请求已加载");
}

async function loadConsultationTrace() {
  const data = await request("/api/admin/consultation-trace", { headers: headers(false) });
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

async function processDataRequest(requestId, status) {
  const data = await request(`/api/admin/data-requests/${requestId}`, {
    method: "PUT",
    headers: headers(true),
    body: JSON.stringify({ status, note: status === "approved" ? "管理员已按内测流程处理" : "管理员拒绝本次申请" }),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("数据请求已处理");
  await loadDataRequests();
}

async function loadPrivacyCompliance() {
  const [assessments, policies] = await Promise.all([
    request("/api/admin/privacy/assessments", { headers: headers(false) }),
    request("/api/admin/privacy/retention-policies", { headers: headers(false) }),
  ]);
  els.knowledgeBox.innerHTML = `
    <h3>隐私合规记录</h3>
    ${renderSimpleTable("隐私影响评估", assessments, ["assessment_id", "title", "risk_level", "compliance_status"])}
    ${renderSimpleTable("数据保留策略", policies, ["data_category", "retention_days", "auto_delete", "archived"])}
  `;
  showToast("隐私合规记录已加载");
}

async function loadAuditLogs() {
  const data = await request("/api/admin/audit", { headers: headers(false) });
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
    const payload = {
      message,
      requested_agent: els.agentSelect.value || null,
      patient_profile: profilePayload(),
    };
    const data = await request("/api/consultations", {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify(payload),
    });
    renderResult(data);
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
    const data = await request("/api/imaging/analyze", {
      method: "POST",
      headers: headers(false),
      body: form,
    });
    renderResult(data);
    await loadHistory();
    showToast("影像解读完成");
  } catch (error) {
    showError(error);
  } finally {
    els.imagingBtn.disabled = false;
    setStatus("就绪");
  }
}

function renderResult(data) {
  els.resultPanel.classList.remove("empty", "loading");
  
  let html = `
    <div class="result-header">
      <div class="result-title">
        <h3>${escapeHtml(data.agent_name)}</h3>
        <span class="agent-badge">${agentLabel(data.agent_type)}</span>
      </div>
    </div>
    
    <div class="result-metrics">
      <div class="metric-card"><span>咨询编号</span><strong>${data.consultation_id ?? "-"}</strong></div>
      <div class="metric-card risk-${data.risk_level}"><span>风险等级</span><strong>${riskLabel(data.risk_level)}</strong></div>
      <div class="metric-card"><span>医生复核</span><strong>${data.doctor_review_required ? "需要" : "暂不需要"}</strong></div>
    </div>
    
    <div class="result-content">
      <p>${escapeHtml(data.summary)}</p>
    </div>
  `;

  html += renderList("依据摘要", data.evidence);
  html += renderStructuredData(data.structured_data);
  html += renderList("风险提示", data.risk_tips);
  html += renderList("建议下一步", data.next_steps);
  html += renderSources(data.sources);
  html += renderList("安全标记", data.safety_flags);
  html += renderTrace(data.agent_trace);
  
  html += `
    <div class="result-section">
      <h4>免责声明</h4>
      <p>${escapeHtml(data.disclaimer)}</p>
    </div>
  `;
  
  els.resultPanel.innerHTML = html;
}

function renderStructuredData(structured) {
  if (!structured) return "";
  return `
    ${structured.workflow ? renderWorkflow(structured.workflow) : ""}
    ${structured.triage_report ? renderTriageReport(structured.triage_report) : ""}
    ${structured.medication_check ? renderMedicationCheck(structured.medication_check) : ""}
    ${structured.treatment_comparison ? renderTreatmentComparison(structured.treatment_comparison) : ""}
  `;
}

function renderWorkflow(workflow) {
  const results = workflow.results || [];
  return `
    <div class="result-section">
      <h4>多智能体协作流程</h4>
      <div class="result-metrics">
        <div class="metric-card"><span>执行链</span><strong>${(workflow.visited_agents || []).join(" → ") || "-"}</strong></div>
        <div class="metric-card"><span>医生复核</span><strong>${workflow.requires_review ? "需要" : "暂不需要"}</strong></div>
        <div class="metric-card"><span>来源数量</span><strong>${(workflow.sources || []).length}</strong></div>
      </div>
      <div class="comparison-list">
        ${results
          .map(
            (item) => `
              <div class="comparison-item">
                <div class="option-name">${escapeHtml(item.agent_name || item.agent_id)}</div>
                <p>${escapeHtml(item.content || item.error || "")}</p>
                ${renderSources(item.sources || item.references || [])}
                ${renderTrace(item.trace || [])}
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderTriageReport(report) {
  return `
    <div class="result-section">
      <h4>预问诊报告</h4>
      <div class="result-metrics">
        <div class="metric-card"><span>牙位/区域</span><strong>${escapeHtml(report.tooth_position || "-")}</strong></div>
        <div class="metric-card"><span>持续时间</span><strong>${escapeHtml(report.duration_text || "-")}</strong></div>
        <div class="metric-card"><span>疼痛性质</span><strong>${escapeHtml(report.pain_character || "-")}</strong></div>
        <div class="metric-card"><span>紧急程度</span><strong>${escapeHtml(report.urgency_label || report.urgency_level || "-")}</strong></div>
        <div class="metric-card"><span>建议科室</span><strong>${escapeHtml(report.recommended_department || "-")}</strong></div>
        <div class="metric-card"><span>医生复核</span><strong>${report.doctor_review_required ? "建议" : "按需"}</strong></div>
      </div>
      ${renderList("诱因", report.triggers)}
      ${renderList("伴随症状", report.accompanying_symptoms)}
      ${renderObjectList("疑似问题", report.suspected_conditions, "name", "basis")}
    </div>
  `;
}

function renderMedicationCheck(check) {
  return `
    <div class="result-section">
      <h4>用药审查</h4>
      <p>${escapeHtml(check.compliance_summary)}</p>
      ${renderDrugBlocks(check.checked_drugs)}
      ${renderList("禁忌/高风险", check.contraindications)}
      ${renderList("相互作用提示", check.interactions)}
      ${renderList("需补充核查", check.required_context)}
    </div>
  `;
}

function renderTreatmentComparison(comparison) {
  return `
    <div class="result-section">
      <h4>方案对比</h4>
      <p>${escapeHtml(comparison.recommendation_note)}</p>
      <div class="comparison-list">
        ${(comparison.comparison || [])
          .map(
            (item) => `
              <div class="comparison-item">
                <div class="option-name">${escapeHtml(item.option_name)} · ${escapeHtml(item.category)}</div>
                <div class="option-stats">
                  <span>疗程: ${escapeHtml(item.duration_note)}</span>
                </div>
                ${renderList("步骤", item.main_steps)}
                <div class="option-pros">优势: ${(item.advantages || []).join(", ")}</div>
                <div class="option-cons">局限: ${(item.disadvantages || []).join(", ")}</div>
                ${renderList("替代方案", item.alternatives)}
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderDrugBlocks(drugs) {
  if (!drugs || !drugs.length) return "";
  return `
    <div class="drug-list">
      ${drugs
        .map(
          (drug) => `
            <div class="drug-item">
              <div class="drug-name">${escapeHtml(drug.drug_name)} · ${escapeHtml(drug.category)}</div>
              <div>${escapeHtml(drug.dose_note)}</div>
              ${drug.alcohol_warning ? `<div class="drug-risk">${escapeHtml(drug.alcohol_warning)}</div>` : ''}
              ${drug.safety_status === 'safe' ? `<div class="drug-safe">用药安全</div>` : ''}
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderObjectList(title, items, titleKey, bodyKey) {
  if (!items || !items.length) return "";
  return `
    <div class="result-section">
      <h4>${title}</h4>
      <div class="source-list">
        ${items
          .map(
            (item) => `
              <div class="source-item">
                <div class="source-title">${escapeHtml(item[titleKey])}</div>
                <div class="source-excerpt">${escapeHtml(item[bodyKey])}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderList(title, items) {
  if (!items || !items.length) return "";
  return `
    <div class="result-section">
      <h4>${title}</h4>
      <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderSources(sources) {
  if (!sources || !sources.length) return "";
  return `
    <div class="result-section">
      <h4>来源引用</h4>
      <div class="source-list">
        ${sources
          .map(
            (source) => `
              <div class="source-item">
                <div class="source-title">${escapeHtml(source.title)}</div>
                <div class="source-meta">
                  <span>${escapeHtml(source.source)}</span>
                  <span>命中分: ${source.score}</span>
                </div>
                <div class="source-excerpt">${escapeHtml(source.excerpt)}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderTrace(trace) {
  if (!trace || !trace.length) return "";
  return `
    <div class="result-section">
      <h4>执行轨迹</h4>
      <div class="trace-list">
        ${trace.map((item, i) => `<div class="trace-item">${i + 1}. ${escapeHtml(item)}</div>`).join("")}
      </div>
    </div>
  `;
}

function renderLlmCallSection(title, calls, fallbackCall = null) {
  const html = renderLlmCalls(calls, fallbackCall);
  if (!html) return "";
  return `
    <div class="result-section">
      <h4>${escapeHtml(title)}</h4>
      ${html}
    </div>
  `;
}

function renderLlmCalls(calls, fallbackCall = null) {
  const rows = calls && calls.length ? calls : fallbackCall ? [fallbackCall] : [];
  if (!rows.length) return "<p>暂无模型调用记录</p>";
  return `
    <div class="llm-call-list">
      ${rows
        .map((call, index) => `
          <div class="llm-call-item">
            <div class="source-title">调用 ${index + 1} · ${escapeHtml(call.status || "-")} · ${escapeHtml(call.model_name || "-")}</div>
            <div class="source-meta">
              <span>${escapeHtml(call.provider || "deepseek")}</span>
              <span>延迟 ${escapeHtml(call.latency_ms ?? "-")}ms</span>
              <span>Token ${escapeHtml(call.total_tokens ?? 0)}</span>
              <span>费用 ${escapeHtml(call.estimated_cost ?? 0)}</span>
            </div>
            ${call.error_message ? `<div class="drug-risk">${escapeHtml(call.error_message)}</div>` : ""}
            ${call.response_preview ? `<p>${escapeHtml(call.response_preview)}</p>` : ""}
            <details class="export-details">
              <summary>请求/响应预览</summary>
              <pre>${escapeHtml(JSON.stringify(call, null, 2))}</pre>
            </details>
          </div>
        `)
        .join("")}
    </div>
  `;
}

async function loadHistory() {
  try {
    const rows = await request("/api/consultations/history", { headers: headers(false) });
    els.historyList.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
              <div class="history-item" data-history="${row.id}">
                <strong>#${row.id} · ${agentLabel(row.agent_type)}</strong>
                <div class="history-meta">
                  <span class="risk-${row.risk_level}">${riskLabel(row.risk_level)}</span>
                  ${row.doctor_review_required ? '<span>需复核</span>' : ''}
                  <span>${formatDate(row.created_at)}</span>
                </div>
                <div>${escapeHtml(row.summary.slice(0, 100))}${row.summary.length > 100 ? "..." : ""}</div>
              </div>
            `,
          )
          .join("")
      : "<div class='history-item'>暂无历史记录</div>";
    document.querySelectorAll("[data-history]").forEach((item) => {
      item.addEventListener("click", () => loadConsultationDetail(item.dataset.history));
    });
  } catch (error) {
    els.historyList.innerHTML = `<div class="history-item">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function loadConsultationDetail(consultationId) {
  try {
    const data = await request(`/api/consultations/${consultationId}`, { headers: headers(false) });
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
  html += renderStructuredData(data.structured_outputs || response.structured_data);
  html += renderObjectList("检索来源", data.retrieval_hits || consultation.sources || [], "title", "excerpt");
  html += renderLlmCallSection("LLM 调用归档", data.llm_calls || [], data.llm_call);
  html += renderTrace(data.agent_run?.trace || response.agent_trace || []);
  if (data.review) {
    html += renderReviewArchive(data.review);
  }
  if (data.uploads && data.uploads.length) {
    html += renderSimpleTable("上传归档", data.uploads, ["original_name", "mime_type", "file_size", "created_at"]);
  }
  html += `
    <div class="result-section">
      <h4>免责声明</h4>
      <p>${escapeHtml(data.disclaimer || response.disclaimer || "")}</p>
    </div>
  `;
  els.resultPanel.classList.remove("empty");
  els.resultPanel.innerHTML = html;
}

function renderReviewArchive(review) {
  return `
    <div class="result-section">
      <h4>医生复核状态</h4>
      <div class="result-metrics compact">
        <div class="metric-card"><span>状态</span><strong>${escapeHtml(review.status)}</strong></div>
        <div class="metric-card"><span>轮次</span><strong>${escapeHtml(review.review_round || "-")}</strong></div>
        <div class="metric-card"><span>模板</span><strong>${escapeHtml(review.review_template || "-")}</strong></div>
      </div>
      ${review.risk_assessment ? `<p>风险评估：${escapeHtml(review.risk_assessment)}</p>` : ""}
      ${review.treatment_decision ? `<p>治疗决策：${escapeHtml(review.treatment_decision)}</p>` : ""}
      ${review.followup_instruction ? `<p>随访说明：${escapeHtml(review.followup_instruction)}</p>` : ""}
      ${review.note ? `<p>备注：${escapeHtml(review.note)}</p>` : ""}
    </div>
  `;
}

async function loadReviews() {
  if (state.role === "patient") return;
  try {
    const rows = await request("/api/doctor/reviews", { headers: headers(false) });
    els.reviewList.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
              <div class="review-item ${row.status === 'approved' ? 'approved' : row.status === 'rejected' ? 'rejected' : ''}">
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
    
    document.querySelectorAll("[data-review]").forEach((button) => {
      button.addEventListener("click", () => openReviewModal(button.dataset.review, button.dataset.status));
    });
    
    document.querySelectorAll("[data-report]").forEach((button) => {
      button.addEventListener("click", () => loadDoctorReport(button.dataset.report));
    });

    document.querySelectorAll("[data-escalate]").forEach((button) => {
      button.addEventListener("click", () => escalateReview(button.dataset.escalate));
    });
  } catch (error) {
    els.reviewList.innerHTML = `<div class="review-item">加载失败: ${escapeHtml(error.message)}</div>`;
  }
}

async function loadDoctorReport(consultationId) {
  try {
    const data = await request(`/api/doctor/consultations/${consultationId}/report`, { headers: headers(false) });
    
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
    
    html += renderStructuredData(data.structured_outputs);
    html += renderObjectList("检索来源", data.retrieval_hits, "title", "excerpt");
    
    html += `
      <div class="result-section">
        <h4>LLM 调用详情</h4>
        ${renderLlmCalls(data.llm_calls || [], data.llm_call)}
      </div>
    `;
    
    if (data.agent_run) {
      html += renderTrace(data.agent_run.trace);
    }
    
    html += `
      <div class="result-section">
        <h4>免责声明</h4>
        <p>${escapeHtml(data.disclaimer)}</p>
      </div>
    `;
    
    els.resultPanel.innerHTML = html;
    showToast("报告已加载");
  } catch (error) {
    showError(error);
  }
}

let currentReviewId = null;
let currentReviewStatus = null;

async function openReviewModal(reviewId, status) {
  currentReviewId = reviewId;
  currentReviewStatus = status;
  
  const templates = await request("/api/doctor/review-templates", { headers: headers(false) });
  const statusLabels = {
    "approved": "通过",
    "needs_followup": "需随访",
    "returned_for_info": "退回补充",
    "rejected": "拒绝"
  };
  
  const modal = document.createElement("div");
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal">
      <div class="modal-header">
        <h3>${statusLabels[status]}复核 #${reviewId}</h3>
        <button class="modal-close" onclick="this.parentElement.parentElement.parentElement.remove()">&times;</button>
      </div>
      <div class="modal-body">
        <div style="display: grid; gap: 12px;">
          <div>
            <label>复核模板</label>
            <select id="reviewTemplateSelect">
              <option value="">选择模板（可选）</option>
              ${templates.map(t => `<option value="${t.template_id}">${t.name}</option>`).join("")}
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
        <button onclick="this.parentElement.parentElement.parentElement.remove()">取消</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  document.getElementById("reviewTemplateSelect").addEventListener("change", (event) => {
    renderReviewTemplateFields(templates.find((item) => item.template_id === event.target.value));
  });
  document.getElementById("submitReviewBtn").addEventListener("click", submitReview);
}

function renderReviewTemplateFields(template) {
  const box = document.getElementById("templateFieldsBox");
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

function collectStructuredOpinion() {
  const opinion = {};
  document.querySelectorAll("[data-template-field]").forEach((input) => {
    opinion[input.dataset.templateField] = input.value;
  });
  return Object.keys(opinion).length ? opinion : null;
}

async function submitReview() {
  const payload = {
    status: currentReviewStatus,
    review_template: document.getElementById("reviewTemplateSelect").value || null,
    risk_assessment: document.getElementById("riskAssessmentInput").value || null,
    treatment_decision: document.getElementById("treatmentDecisionSelect").value || null,
    signature: document.getElementById("signatureInput").value || null,
    signature_title: document.getElementById("signatureTitleInput").value || null,
    followup_instruction: document.getElementById("followupInstructionInput").value || null,
    note: document.getElementById("reviewNoteInput").value || null,
    structured_opinion: collectStructuredOpinion(),
  };
  
  await request(`/api/doctor/reviews/${currentReviewId}`, {
    method: "PUT",
    headers: headers(true),
    body: JSON.stringify(payload),
  });
  
  document.querySelector(".modal-overlay").remove();
  els.resultPanel.innerHTML = '<div class="empty">请选择一个操作</div>';
  await loadReviews();
  await loadHistory();
  showToast("复核已提交");
}

async function escalateReview(reviewId) {
  const data = await request(`/api/doctor/reviews/${reviewId}/escalate`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({ reason: "医生发起二级复核", to_role: "admin" }),
  });
  els.resultPanel.innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  await loadReviews();
  showToast("已升级为二级复核");
}

async function loadKnowledgeDocs() {
  const data = await request("/api/admin/knowledge/documents", { headers: headers(false) });
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
    headers: headers(true),
    body: JSON.stringify(payload),
  });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("文档已新增");
}

async function loadKnowledgeChanges() {
  const data = await request("/api/admin/knowledge/changes", { headers: headers(false) });
  els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
  showToast("变更记录已刷新");
}

async function loadRagEvaluation() {
  try {
    const data = await request("/api/admin/rag/evaluation", { headers: headers(false) });
    
    let html = `<h3>RAG 召回评测报告</h3>`;
    
    html += `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; margin: 16px 0;">`;
    html += `<div class="metric-card"><span>后端</span><strong>${escapeHtml(data.backend || 'N/A')}</strong></div>`;
    html += `<div class="metric-card"><span>测试用例</span><strong>${data.case_count || 0}</strong></div>`;
    html += `<div class="metric-card"><span>命中率</span><strong>${(data.hit_rate || 0).toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>MRR</span><strong>${(data.mrr || 0).toFixed(2)}</strong></div>`;
    html += `<div class="metric-card"><span>失败数</span><strong>${data.failure_count || 0}</strong></div>`;
    html += `</div>`;
    
    if (data.difficulty_analysis) {
      html += `<h4>难度分布分析</h4>`;
      html += `<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">`;
      for (const [diff, stats] of Object.entries(data.difficulty_analysis)) {
        const color = diff === 'easy' ? 'risk-low' : diff === 'medium' ? 'risk-medium' : 'risk-high';
        html += `<div class="metric-card ${color}">`;
        html += `<span>${diff === 'easy' ? '简单' : diff === 'medium' ? '中等' : '困难'}</span>`;
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
        const color = recall >= 0.8 ? 'risk-low' : recall >= 0.5 ? 'risk-medium' : 'risk-high';
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
          const percent = (count / (data.failure_count || 1) * 100);
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
    els.knowledgeBox.textContent = error.message;
    showToast("加载失败", "error");
  }
}

function getCategoryName(cat) {
  const names = {
    'triage': '分诊',
    'treatment': '治疗',
    'medication': '用药',
    'imaging': '影像',
    'health': '健康',
    'mucosa': '黏膜',
    'case': '病例',
    'emergency': '紧急',
    'guide': '指南',
    'safety': '安全'
  };
  return names[cat] || cat;
}

function getFailureTypeName(type) {
  const names = {
    'semantic_mismatch': '语义不匹配',
    'keyword_missing': '关键词缺失',
    'category_confusion': '类别混淆',
    'ambiguous_query': '查询歧义',
    'document_not_found': '文档缺失',
    'other': '其他'
  };
  return names[type] || type;
}

function renderSimpleTable(title, rows, columns) {
  return `
    <div class="result-section">
      <h4>${escapeHtml(title)}</h4>
      ${rows && rows.length ? `
        <div class="data-table">
          <div class="data-table-head">${columns.map((column) => `<span>${escapeHtml(column)}</span>`).join("")}</div>
          ${rows.map((row) => `
            <div class="data-table-row">
              ${columns.map((column) => `<span>${escapeHtml(row[column])}</span>`).join("")}
            </div>
          `).join("")}
        </div>
      ` : "<p>暂无记录</p>"}
    </div>
  `;
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

function renderDataRequests(title, rows, adminMode) {
  return `
    <h3>${escapeHtml(title)}</h3>
    ${rows && rows.length ? rows.map((item) => `
      <div class="admin-row">
        <strong>#${item.id} · ${escapeHtml(dataRequestTypeLabel(item.request_type))} · ${escapeHtml(dataRequestStatusLabel(item.status))}</strong>
        <p>${escapeHtml(item.user_external_id)} · ${escapeHtml(item.data_scope)} · ${escapeHtml(item.reason || "")}</p>
        ${item.processed_at ? `<p>处理人：${escapeHtml(item.processed_by || "-")} · ${formatDate(item.processed_at)} · ${escapeHtml(item.note || "")}</p>` : ""}
        ${item.result_summary ? renderDataExportSummary(item.result_summary) : ""}
        ${item.result_data ? `<details class="export-details"><summary>查看导出数据预览</summary><pre>${escapeHtml(JSON.stringify(item.result_data, null, 2))}</pre></details>` : ""}
        ${adminMode && item.status === "pending" ? `
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

function dataRequestTypeLabel(type) {
  return { export: "导出", delete: "删除" }[type] || type;
}

function dataRequestStatusLabel(status) {
  return { pending: "待处理", approved: "已批准", rejected: "已拒绝" }[status] || status;
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

async function loadLlmMetrics() {
  try {
    const data = await request("/api/admin/llm/metrics", { headers: headers(false) });
    els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
    showToast("LLM 指标已刷新");
  } catch (error) {
    els.knowledgeBox.textContent = error.message;
    showToast("加载失败", "error");
  }
}

async function loadAdminAlerts() {
  try {
    const data = await request("/api/admin/alerts", { headers: headers(false) });
    els.knowledgeBox.innerHTML = renderAdminAlerts(data);
    showToast("异常告警已刷新");
  } catch (error) {
    els.knowledgeBox.textContent = error.message;
    showToast("加载失败", "error");
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
    const data = await request("/api/admin/chroma/rebuild", {
      method: "POST",
      headers: headers(false),
    });
    els.knowledgeBox.textContent = JSON.stringify(data, null, 2);
    showToast("向量库重建完成");
  } catch (error) {
    els.knowledgeBox.textContent = error.message;
    showToast("重建失败", "error");
  } finally {
    setStatus("就绪");
  }
}

function setRole(role) {
  state.role = role;
  els.roles.forEach((button) => button.classList.toggle("active", button.dataset.role === role));
  document.querySelectorAll(".patient-only").forEach((item) => item.classList.toggle("hidden", role !== "patient"));
  document.querySelectorAll(".doctor-only").forEach((item) => item.classList.toggle("hidden", role === "patient"));
  document.querySelectorAll(".admin-only").forEach((item) => item.classList.toggle("hidden", role !== "admin"));
  loadProfile();
  loadHistory();
  loadReviews();
  loadCare();
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

function riskLabel(risk) {
  return { low: "低", medium: "中", high: "高" }[risk] || risk;
}

function agentLabel(agent) {
  return {
    triage: "预问诊",
    treatment: "方案",
    medication: "用药",
    imaging: "影像",
    health: "健康",
  }[agent] || agent;
}

function agentRoleLabel(role) {
  return { patient: "患者", doctor: "医生", admin: "管理员" }[role] || role;
}

function toIsoOrNull(value) {
  return value ? new Date(value).toISOString() : null;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.loginBtn.addEventListener("click", () => login().catch(showError));
els.logoutBtn.addEventListener("click", logout);
els.roles.forEach((button) => button.addEventListener("click", () => setRole(button.dataset.role)));
els.sendBtn.addEventListener("click", sendConsultation);
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
els.clearBtn.addEventListener("click", () => {
  els.messageInput.value = "";
  els.agentSelect.value = "";
});
els.imagingBtn.addEventListener("click", sendImaging);
els.refreshHistoryBtn.addEventListener("click", loadHistory);
els.refreshReviewBtn.addEventListener("click", loadReviews);
els.loadKnowledgeDocsBtn.addEventListener("click", () => loadKnowledgeDocs().catch(showError));
els.createKnowledgeDocBtn.addEventListener("click", () => createKnowledgeDoc().catch(showError));
els.loadKnowledgeChangesBtn.addEventListener("click", () => loadKnowledgeChanges().catch(showError));
els.loadWorkflowBtn.addEventListener("click", () => loadWorkflowConfig().catch(showError));
els.saveWorkflowBtn.addEventListener("click", () => saveWorkflowConfig().catch(showError));
els.loadConsultationTraceBtn.addEventListener("click", () => loadConsultationTrace().catch(showError));
els.loadDataRequestsBtn.addEventListener("click", () => loadDataRequests().catch(showError));
els.loadAuditBtn.addEventListener("click", () => loadAuditLogs().catch(showError));
els.loadPrivacyBtn.addEventListener("click", () => loadPrivacyCompliance().catch(showError));
els.ragEvalBtn.addEventListener("click", loadRagEvaluation);
els.llmMetricsBtn.addEventListener("click", loadLlmMetrics);
els.adminAlertsBtn.addEventListener("click", loadAdminAlerts);
els.rebuildChromaBtn.addEventListener("click", rebuildChroma);
els.adminRunDueBtn.addEventListener("click", () => adminRunDueNotifications().catch(showError));

loadScenarios();
renderCurrentUser();
setRole(state.currentUser?.role || "patient");
