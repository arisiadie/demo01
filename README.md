# 口腔医疗 Agentic RAG 多智能体平台

这是一个生产级内测定位的口腔医疗智能服务平台原型：FastAPI 后端、HTML/CSS/JS 前端、本地示例知识库、Agentic RAG 检索、五智能体调度、审计日志、角色权限和医疗安全边界。

## 快速启动

推荐使用你现有的 Conda 环境 `openai`，当前已确认它是 Python 3.11 环境，并包含 FastAPI、Uvicorn、SQLAlchemy、python-multipart、pytest、Chroma 相关依赖：

```powershell
conda activate openai
python -m pip install -r requirements.txt
```

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。

## PyCharm 配置

1. 打开项目目录 `F:\python\demo01`。
2. 在 `Settings > Project > Python Interpreter` 选择 Conda 环境 `openai`，解释器路径通常是 `G:\Anaconda_envs\envs\openai\python.exe`。
3. 添加 Run Configuration：
   - Module name: `uvicorn`
   - Parameters: `app.main:app --reload --host 127.0.0.1 --port 8000`
   - Working directory: `F:\python\demo01`
4. 运行后访问 `http://127.0.0.1:8000`。

如需确认 PyCharm 使用的是哪个解释器，在 PyCharm 终端运行：

```powershell
python --version
python -c "import sys; print(sys.executable)"
python -m pip list
```

说明：`openai` 环境中的 `FastAPI 0.109.2 / Starlette 0.36.3 / httpx 0.28.1` 组合可能导致 `fastapi.testclient.TestClient` 报版本兼容错误；这不影响 Uvicorn 方式运行项目。核心单元测试已使用 `pytest` 验证。

默认使用 MySQL 业务库 `oralcare_agentic_rag`。初始化脚本在 `sql/init_oralcare_agentic_rag.sql`，当前 `.env` 已配置为：

```text
mysql+pymysql://root:123456@127.0.0.1:3306/oralcare_agentic_rag?charset=utf8mb4
```

数据库设计说明见 `docs/database_design.md`。当前设计包含 29 张表，覆盖用户档案、咨询主流程、RAG 命中、Agent 轨迹、DeepSeek 调用日志、医生复核、影像上传、健康计划、复诊提醒、站内通知、牙位档案、知识库变更记录、动态 workflow 配置、隐私合规记录和审计日志。

如果需要重新初始化数据库，可在已安装 MySQL 且账号密码可用时执行：

```powershell
python scripts/init_mysql.py
python scripts/verify_database.py
```

## 演示账号

前端可直接切换角色。接口使用请求头模拟生产内测登录态：

- `X-User-Id: patient-demo`，`X-Role: patient`
- `X-User-Id: doctor-demo`，`X-Role: doctor`
- `X-User-Id: admin-demo`，`X-Role: admin`

## 已实现能力

- 五智能体：症状预问诊、诊疗方案解读、用药合规审查、影像报告文本解读、健康管理。
- Agentic RAG：LangChain Runnable 编排、问题拆解、多轮检索、Chroma 向量检索、来源引用、低置信度拒答。
- 知识库管理：管理员新增/编辑/下线文档后自动同步运行时 RAG 与 Chroma，服务启动时也会从 MySQL 恢复管理员知识。
- 医疗安全：免责声明、危险症状提示、处方/诊断边界、提示词注入拦截、医生复核标记。
- 生产内测：角色权限、请求限流、真实审计日志、异常告警、数据脱敏、知识库版本、动态 workflow 持久化、隐私同意、数据导出/删除申请、历史归档、到期提醒扫描。
- 健康档案：治疗记录、复诊提醒、站内通知、牙位级档案、牙位图、个性化维护计划和科普知识推送。
- 管理员追踪：咨询追踪一览展示 RAG 检索命中、主 Agent/workflow 子 Agent LLM 调用状态、延迟、费用、模型回答摘要和医生复核状态。
- 影像模块：支持图片上传预览/归档和报告文本解读，不做真实图像诊断。

## 验收链路

1. 牙痛预问诊：输入“右下后牙夜间疼痛，冷热刺激痛 3 天”。
2. 根管治疗方案解读：输入“医生建议根管治疗，我想了解步骤和风险”。
3. 抗生素用药审查：输入“阿莫西林和甲硝唑能不能一起用，我青霉素过敏”。
4. 全景片报告解读：在影像模块输入“全景片提示左下阻生智齿近中倾斜，邻牙远中龋坏”。
5. 儿童健康管理：输入“8 岁儿童窝沟封闭和换牙期护理计划”。

## Chroma 与 RAG 评测

```powershell
python scripts/rebuild_chroma.py
```

管理员接口：

- `POST /api/admin/chroma/rebuild`
- `GET /api/admin/rag/evaluation`

## 重要边界

本系统使用示例知识库，仅用于内部演示和工程验证。输出均为 AI 辅助参考，不替代执业医师诊断、处方或治疗决策。若转为机构试点或商业上线，需要补充真实授权知识库、医生审核流程、隐私影响评估和监管边界评估。
