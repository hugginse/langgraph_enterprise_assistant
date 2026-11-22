# CLAUDE.md — langgraph_enterprise_assistant 执行指引

## 项目定位

企业级知识库问答系统（**LangGraph Adaptive RAG**），交付物为 **GitHub 公开仓库 `langgraph_enterprise_assistant`**。

系统能力：知识库管理 → 文档异步入库 → 带权限的向量检索 → LangGraph 自适应问答（分类 / 评分 / 有限改写 / 拒答 / 引用校验）→ SSE 真流式输出 → 多会话 + 状态检查点 → 管理端看板。

本文件与 `docs/plan.md`、`docs/architecture.md` **自包含**：仅凭本仓库文档即可完整开工。

## 文档地图（开工前必读，顺序固定）

1. **`docs/plan.md`** — 四个里程碑、逐条 feature commit 清单、每个 Gate 的验收命令与 git 动作 → 回答「做什么、按什么顺序、何时提交推送」
2. **`docs/architecture.md`** — 架构决策、图协议、双通道模型配置、数据模型、API 与 SSE 协议、权限与级联、配置表 → 回答「做成长什么样」

冲突处理：**做什么**以 architecture.md 为准；**顺序 / 提交 / 验收**以 plan.md 为准。

## 环境铁律（Windows 11 / Git Bash）

- 环境管理**只用 uv**：`.python-version` 钉 3.12，`uv sync` 建环境，日常一律 `uv run ...`
- **禁止**：`python3`（本机是损坏的商店别名）、裸 `python`（3.14，chromadb/psycopg2 无 wheel）、conda 环境
- 依赖增改后必须 `uv sync` 并**提交 `uv.lock`**；`.venv/` 不提交
- Ollama 已装 `qwen3:4b` 与 `qwen3-embedding:4b`（127.0.0.1:11434）；Docker 已装；5432 空闲。**本地默认模型是需求方指定，不得降级**
- 本机显卡 **RTX 5060 Ti 16GB**；Ollama **必须限制上下文**（`OLLAMA_NUM_CTX=8192`、嵌入 4096）：否则按模型声明的 262144 满配预分配 KV cache（约 40GB）挤爆显存，模型 CPU/GPU 混跑；限后 100% GPU 驻留、首 token 秒级
- 所有 Gate 命令均为 Git Bash 形式（见 plan.md 各节）

## Git 工作流（需求方已定，不得更改）

- 分支固定 `main`；**远端空仓库由需求方预先在 GitHub 创建**，开工第一步即 `git remote add origin <URL>`；若拿不到 URL，**停下来询问**，不要自行建仓
- 顺序固定 M1 → M2 → M3 → M4；每个里程碑内按 plan.md 的 feature 清单分批 commit
- commit 规范：中文、conventional 前缀（`feat:` / `fix:` / `test:` / `docs:` / `ci:` / `chore:`），**每条末尾加** `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 每个 commit 前：`uv run ruff check .` 0 error + 相关 `uv run pytest` 通过
- **每个 Gate 全绿 → 打 annotated tag（`m1`/`m2`/`m3`/`m4`）→ 一次性 push（全部 commit + tag）**；Gate 失败先修复并 commit、重跑 Gate，全绿前不打 tag 不 push；Gate 之外不 push；禁止 force push
- 永不提交：`.env`、`uploads/`、`chroma_data/`、`.venv/`、`__pycache__/`、checkpoint 数据文件

## 质量红线（细节见 architecture.md）

- 权限一律**后端强校验**（非成员 403/404），不能只靠前端隐藏菜单；禁用用户（status=0）存量 JWT 立即 401；**进 SSE 前完成校验**
- 密码只用 bcrypt；Chroma collection 必须显式 **cosine 空间**（分数阈值语义依赖它）
- SSE 必须**真流式**（逐 token），禁止整段生成后切片伪装；事件顺序固定 `sources → thinking×N（可选） → delta×N → done`（可选 `node` 进度事件，见 architecture）；思考不落库
- **Adaptive RAG 图内 generate 必须流式吐 token**（节点内 `stream` + 回调），不得 `invoke` 整段后再切片
- 文档入库全异步（`pending → processing → completed|failed`），失败写 `error_msg`；应用启动清理遗留死状态
- 前端**零 npm、零 CDN、无构建**；看板图表手写 SVG，不引图表库
- 模型双通道：**LLM ∈ {ollama, openai, anthropic}，Embedding ∈ {ollama, openai}**（Anthropic 无官方 embeddings）；**默认必须是本地 Ollama 两模型**；缺 key 显式失败，禁止静默降级
- Embedding 切换必须校验索引指纹，不一致拒绝检索并要求 reindex
- LangGraph checkpointer **必须启用**，`thread_id = chat_session.id`，删除级联时清理 checkpoint
- 不做范围外功能：rerank、WebSocket、K8s、前端测试框架、前端构建

## seed_docs（需求方已手动放入）

- 结构：`seed_docs/公司规章制度/`、`seed_docs/技术开发规范/`、`seed_docs/产品使用指南/`，共 **12 份**、覆盖 **txt/md/pdf/docx** 四格式
- **勿改内容与文件名**；seed 脚本与上传校验逻辑需**递归扫描**该目录
- 开工校验：`find seed_docs -type f | wc -l` 必须 = 12

## 开工检查（首次运行，逐项确认）

1. `uv --version`、`docker compose version`、`ollama --version`；`curl -s http://localhost:11434/api/tags` 含两个 qwen3 模型
2. `find seed_docs -type f | wc -l` = 12；`CLAUDE.md`、`docs/plan.md`、`docs/architecture.md` 在仓库根
3. `git config user.name` / `user.email` 已配置（仓库级即可）；未配置则**询问需求方**，不要伪造身份
4. `uv sync && uv run python --version` 输出 3.12
5. 读完 plan.md 与 architecture.md，从 **M1 feature commit #1** 开始执行

## 阻塞时的处置

- 环境不满足、远端 URL 缺失、seed_docs 数量不对、需求方决策缺失 → **停下报告，不要绕过、不要静默降级**
- 技术方案疑问 → 查 architecture.md；文档未覆盖的取舍 → 按最小范围实现并在报告中说明，不擅自扩大范围
