# 任务书验收矩阵

本矩阵用于对照《基于Agentic RAG与多智能体协作的口腔医疗智能服务平台》任务书，记录当前实现证据与验证方式。项目定位为生产级内测系统：工程、安全、审计、追踪按生产标准设计；医疗输出仅作 AI 辅助参考，不替代执业医师诊断、处方或真实影像判读。

## 核心架构

| 要求 | 当前实现证据 | 验证方式 |
| --- | --- | --- |
| FastAPI 后端 | `app/main.py`、`app/api/routes.py` | `python -m compileall app tests scripts` |
| MySQL 业务库 | `sql/init_oralcare_agentic_rag.sql`，29 张表 | `python scripts/init_mysql.py`、`python scripts/verify_database.py` |
| Chroma 向量库 | `app/rag/chroma_index.py`、`data/chroma` | `python scripts/rebuild_chroma.py` |
| LangChain Agentic RAG | `app/agents/agentic_flow.py` 使用 `RunnableLambda` / `RunnableSequence` | `tests/test_orchestrator.py` |
| DeepSeek 接入与监控 | `app/services/llm.py`、`llm_call_logs`、`/api/admin/llm/metrics`，主 Agent 与 workflow 子 Agent 均写入调用日志 | `tests/test_extended_features.py`、管理员前端 “LLM 指标/咨询追踪” |
| HTML/CSS/JS 前端 | `app/static/index.html`、`app/static/app.js`、`app/static/styles.css` | `node --check app/static/app.js` |

## 五大智能体

| 智能体 | 当前实现证据 | 输出/归档 |
| --- | --- | --- |
| 症状预问诊 | `OralAgentOrchestrator`、`_build_triage_report` | `triage_reports`、历史归档、医生复核 |
| 诊疗方案解读 | `_build_treatment_comparison` | `treatment_comparisons`、方案步骤/费用/替代方案 |
| 用药合规审查 | `_build_medication_check`、药物规则库 | `medication_checks`、禁忌/相互作用/剂量边界 |
| 影像报告文本解读 | `/api/imaging/analyze` | `uploaded_files` 归档占位，不做真实图像诊断 |
| 健康管理与科普 | `/api/patient/maintenance-plan`、`/api/patient/education-feed` | `health_plans`、复诊提醒、站内通知、科普推送 |

## Agentic RAG 与可溯源

| 要求 | 当前实现证据 | 验证方式 |
| --- | --- | --- |
| 意图识别 | `MultiAgentWorkflow.route`、`OralAgentOrchestrator.route` | 演示场景与单元测试 |
| 复合问题拆解 | `_sub_questions` 按智能体生成多轮检索查询 | `agent_trace` 含 `round_` 检索记录 |
| 多轮检索 | `AgenticRAGFlow._multi_retrieve` | `tests/test_orchestrator.py` |
| Chroma 向量检索 | `KnowledgeStore.retrieve` 优先 Chroma，失败兜底 local hybrid | `scripts/rebuild_chroma.py` |
| 来源引用 | `SourceDTO`、`retrieval_hits`、前端 `renderSources` | 历史归档、医生报告、咨询追踪 |
| 来源相关性排序 | `KnowledgeStore.retrieve` 使用 Chroma 召回 + 领域关键词重排；主 Agent 来源优先于 workflow 补充来源 | 五条 HTTP 演示链路首位来源分别命中对应知识文档 |
| 低置信拒答 | `refusal_for_no_evidence`、`low_retrieval_confidence` | `OralAgentOrchestrator.run` |
| 召回评测 | `KnowledgeStore.evaluate_recall`、`/api/admin/rag/evaluation` | 当前 56 用例，命中率 1.0，MRR 0.988 |

## 业务闭环

| 要求 | 当前实现证据 |
| --- | --- |
| 智能预问诊入口 | 前端主咨询框、演示场景 “牙痛预问诊” |
| 诊疗方案查询与解读 | `requested_agent=treatment`、方案对比结构化展示 |
| 用药安全核查 | `requested_agent=medication`、用药上下文/禁忌/相互作用 |
| 影像报告上传分析 | `/api/imaging/analyze`、图片/PDF 归档、文本报告解读 |
| 口腔健康档案 | 患者资料、治疗记录、牙位档案、牙位图 |
| 科普知识推送 | `/api/patient/education-feed`、`/api/patient/education-feed/push` |
| 就诊记录与复诊提醒 | `treatment_records`、`follow_up_reminders`、`notifications` |
| 历史咨询记录 | `/api/consultations/history`、`/api/consultations/{id}` |
| 医生复核闭环 | `/api/doctor/reviews`、结构化模板、通过/随访/退回/拒绝/升级 |
| 管理员知识库管理 | `/api/admin/knowledge/documents`、变更记录、运行时同步 |
| 管理员咨询追踪 | `/api/admin/consultation-trace` 展示检索命中、主 Agent/workflow 子 Agent LLM 调用、模型回答摘要、复核状态 |

## 安全与合规

| 要求 | 当前实现证据 |
| --- | --- |
| 登录角色 | 患者、医生、管理员；请求头与 token 登录均支持 |
| 免责声明 | 所有 `AgentResponse` 统一包含 `DISCLAIMER` |
| 权限控制 | `require_role` 覆盖患者/医生/管理员接口 |
| 操作审计 | `audit_logs`、`/api/admin/audit`、前端 “审计日志” |
| 请求日志/模型日志 | `llm_call_logs`、`/api/admin/llm/metrics`、`/api/admin/consultation-trace` 的 `llm_calls` |
| 数据脱敏 | `mask_sensitive_data`、咨询 `sanitized_input` |
| 接口限流 | `InMemoryRateLimitMiddleware` |
| 提示词注入防护 | `prompt_injection_attempt` 拦截 |
| 危险医疗建议拦截 | `diagnosis_or_prescription_boundary` 明确拒绝自动确诊/处方/具体剂量 |
| 急症升级 | `emergency_symptom` 升级高风险并提示急诊 |
| 隐私合规记录 | `patient_consents`、`data_access_requests`、`privacy_impact_assessments`、`data_retention_policies` |
| 异常告警 | `/api/admin/alerts` 覆盖复核逾期、高风险未闭环、LLM 异常/高延迟、RAG 召回、隐私请求 |

## 演示链路

| 链路 | 输入示例 | 展示点 |
| --- | --- | --- |
| 牙痛预问诊 | 右下后牙夜间疼痛，冷热刺激痛 3 天 | Agent 路由、预问诊报告、来源、复核 |
| 根管方案解读 | 医生建议根管治疗，我想了解步骤和风险 | 方案对比、费用因素、替代方案 |
| 抗生素用药审查 | 阿莫西林和甲硝唑能不能一起用，我青霉素过敏 | 禁忌、相互作用、剂量边界 |
| 全景片报告解读 | 全景片提示左下阻生智齿近中倾斜 | 报告文本解读、影像安全边界 |
| 儿童健康管理 | 8 岁儿童窝沟封闭和换牙期护理计划 | 健康计划、科普推送、复诊提醒 |

## 最近验证结果

- `python -m compileall app tests scripts`：通过
- `node --check app/static/app.js`：通过
- `pytest -q`：30 passed
- `python scripts/init_mysql.py`：通过
- `python scripts/verify_database.py`：29 张表，workflow 1 套、9 节点、19 边，隐私保留策略 5 条、隐私影响评估 1 条
- `python scripts/rebuild_chroma.py`：Chroma 后端 `chroma-persistent`，知识库 54 条，召回评测 56 用例命中率 1.0、MRR 0.988
- HTTP 烟测：5 条验收演示链路均生成咨询归档、RAG 来源、执行轨迹和医生复核标记；管理员咨询追踪返回 workflow 子 Agent `llm_calls`
