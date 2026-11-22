# langgraph_enterprise_assistant 开发计划

> 执行入口：仓库根 `CLAUDE.md`；设计基准：`docs/architecture.md`；本文回答**做什么、按什么顺序、何时提交推送**。
> 流程：**远端建仓（需求方）→ 本地关联 → M1…M4 逐 feature commit → 每个 Gate 全绿后打 tag 并推送一次**。
> 顺序固定 M1 → M2 → M3 → M4；**上一里程碑 Gate 未过不得进入下一里程碑**；任一 Gate 失败先修复。

---

## 0. Git 工作流（需求方已定，不得更改）

### 0.1 远端与本地关联（开工第一步）

远端空仓库由**需求方**在 GitHub 预先创建（public，不初始化 README），仓库名 **`langgraph_enterprise_assistant`**（若需求方另定名以其为准）。执行终端拿到 URL 后：

```bash
# 本地目录已由需求方放入：CLAUDE.md、docs/、seed_docs/（三个子文件夹共 12 份）
git init -b main
git remote add origin <需求方提供的 URL>
git config user.name <...> && git config user.email <...>   # 若全局未配置；不要伪造身份，缺就问
uv sync && uv run python --version                          # 确认 3.12，生成 uv.lock
find seed_docs -type f | wc -l                              # 必须 = 12
```

拿不到 URL → **停下询问**，不要自行建仓。

### 0.2 提交与推送规则

- **commit 粒度 = 下文每条 feature 条目**（一条 feature 一个 commit；确需拆分/合并时保持语义不变并在报告说明）
- message 格式：`feat: 中文描述`（前缀按 feat/fix/test/docs/ci/chore），**每条末尾加**：
  ```
  Co-Authored-By: Claude Code <noreply@anthropic.com>
  ```
- 每个 commit 前：`uv run ruff check .` 0 error + 相关 `uv run pytest` 通过
- **每个 Gate 全绿 → 打 annotated tag → 一次性 push（全部 commit + tag）**：

  | Gate | tag | push 命令 |
  |---|---|---|
  | Gate-M1 | `m1` | `git push -u origin main m1`（首次，带 -u） |
  | Gate-M2 | `m2` | `git push origin main m2` |
  | Gate-M3 | `m3` | `git push origin main m3` |
  | Gate-M4 | `m4` | `git push origin main m4` |

- Gate 失败 → 修复并 commit → 重跑 Gate → 全绿前**不打 tag 不 push**；Gate 之外不 push；禁止 force push
- 永不提交：`.env`、`uploads/`、`chroma_data/`、`.venv/`、`__pycache__/`

### 0.3 提交历史预期形态

```
* chore: 初始化仓库（uv 工程骨架与项目文档）      ← m1 之前
* feat: ...（M1）
* tag: m1
* feat: ...（M2 图与真流式）
* tag: m2
* feat: ...（M3 SSE 全链路与评估）
* tag: m3
* feat: ...（M4 前端与工程化）
* tag: m4
```

---

## M1 — 后端骨架（认证 + CRUD + 权限 + 迁移 + 种子 + 双通道配置）

**目标**：可运行的 FastAPI 骨架；认证与全部 CRUD 带权限；PostgreSQL 迁移 + 种子数据就位；LLM/Embed 双通道工厂与配置校验完成（默认本地 Ollama，API 分支可单测）。

### Feature commits

1. **`chore: 初始化仓库（uv 工程骨架与项目文档）`**
   - `.python-version`(3.12)、`pyproject.toml`（name=`langgraph_enterprise_assistant`，requires-python=`>=3.11,<3.13`；deps：fastapi、uvicorn、sqlalchemy、psycopg2-binary、alembic、pydantic-settings、pyjwt、bcrypt、python-multipart、pypdf、python-docx、chromadb、ollama、openai、**anthropic**、httpx、**langgraph**、**langgraph-checkpoint-postgres**（若暂用 SQLite 回退则注明并保持接口）；`[dependency-groups]` dev：pytest、ruff；ruff 行宽 100；pytest 指向 `tests/`）、`.gitignore`（勿忽略 uv.lock）、`LICENSE`(MIT)、`uv.lock`
   - 本条 commit 时 CLAUDE.md 与 docs/ 已在工作区，一并提交

2. **`feat: FastAPI 应用工厂、RequestID 中间件与健康检查`**
   - `app/core/config.py`（Pydantic Settings：双通道 + 缺 key 校验；`SECRET_KEY` 固定开发默认值；`OLLAMA_THINK=true`、`OLLAMA_NUM_CTX=8192`）、`app/middleware.py`、`app/db.py`、`app/main.py`（create_app 工厂、`GET /health`、`/docs`）

3. **`feat: PostgreSQL compose 服务与测试库初始化`**
   - `docker-compose.yml`（仅 db：postgres:16、5432、volume、healthcheck、挂载 `docker/initdb/init.sql`）、`docker/initdb/init.sql`（建 `langgraph_enterprise_test`）

4. **`feat: SQLAlchemy 数据模型与 Alembic 初始迁移`**
   - `app/models/`：users、knowledge_bases、kb_members、documents、chat_sessions、chat_messages、**chat_feedback**、**embed_index_meta**（字段见 architecture §7）
   - `alembic.ini` + `alembic/` 首次迁移；本机 `uv run alembic upgrade head` 通过

5. **`feat: bcrypt 密码与 JWT 认证依赖`**
   - `app/core/security.py`：bcrypt(12)、JWT 签发/校验、`login_required`/`admin_required`；**login_required 内校验 user.status，禁用即 401**

6. **`feat: 登录与用户管理接口`**
   - `app/api/routes/auth.py`（POST `/api/auth/login`、GET `/api/auth/me`；status=0 拒绝登录）
   - `app/api/routes/users.py`（admin：分页列表/创建/改密/禁用）
   - 对应 `app/schemas/`

7. **`feat: 知识库 CRUD 与成员授权接口`**
   - `app/api/routes/knowledge_bases.py`：GET 列表（admin 全部 / user 仅成员）、POST/PUT/DELETE（admin；**删除实现 DB 级级联：documents 记录、uploads 物理文件、sessions、messages；Chroma 与 checkpoint 清理留接口 try/except 容忍不存在，M2/M3 接通**）、members 子路由（GET/POST/DELETE）

8. **`feat: 文档上传、列表与删除（暂不向量化）`**
   - `app/api/routes/documents.py`：multipart 上传（类型白名单 txt/pdf/md/docx、50MB 限制、uuid stored_name 落盘）、列表（含 status 供轮询）、GET/DELETE；**M1 阶段 status 恒为 pending，不接向量化**

9. **`feat: 管理端统计接口`**
   - `app/api/routes/stats.py`：GET `/api/stats/dashboard` → `{users,kbs,documents,messages, trend:[{date,count}]}` 近 7 天（admin）

10. **`feat: LLM/Embed 双通道 Protocol 与工厂`**
    - `app/services/llm/base.py`：`ChatStreamer` / `Embedder` Protocol + `create_chat_streamer()` / `create_embedder()` 工厂
    - 实现：`ollama_chat.py`、`ollama_embed.py`、`openai_chat.py`、`openai_embed.py`、**`anthropic_chat.py`**
    - 按 `LLM_PROVIDER` / `EMBED_PROVIDER` 分支；**缺 key 显式抛业务/配置错误**，禁止静默降级；`fingerprint` 属性
    - `.env.example` 全量变量（默认本地 Ollama 两模型）

11. **`test: 认证权限与 Provider 工厂单测`**
    - 禁用 401；权限矩阵骨架；三 LLM 两 embed 分支 mock；缺 key 失败；ruff + pytest 全绿

12. **`feat: 种子脚本（双账号、按文件夹三库、12 份文档）`**
    - `scripts/seed.py`（幂等：同 kb 同 filename 跳过）：`admin/admin123`、`user/user123`；按 `seed_docs/` 一级子文件夹各建一个知识库；两用户均入全部库成员；12 份文档入库（M1 状态 pending）

### Gate-M1

```bash
uv sync && uv run python --version          # 输出 3.12.x
uv run ruff check .                         # 0 error
uv run pytest -q                            # 全绿
docker compose up -d db
uv run alembic upgrade head
uv run python scripts/seed.py
find seed_docs -type f | wc -l              # 必须 = 12
uv run uvicorn app.main:app --reload
# 用 admin token：GET /api/knowledge-bases → 200；POST 上传一个文档 → 201
# 配置 LLM_PROVIDER=anthropic 且 ANTHROPIC_API_KEY 为空 → 启动或调用显式失败（非静默 ollama）
```

**Git 动作**：全绿 → `git tag -a m1 -m "Gate-M1 通过：认证+CRUD+权限+迁移+双通道+种子"` → `git push -u origin main m1`

---

## M2 — Adaptive RAG 图 + Checkpointer + 模型桥（以单测为主）

**目标**：LangGraph 图可编译、节点可单测；checkpointer 绑定 thread；ChatStreamer 桥接完成；**generate 真流式回调**用 Scripted 模型验证。

### Feature commits

1. **`feat: Adaptive RAG State 与基础节点`**
   - `app/services/adaptive_rag/state.py`（TypedDict，见 architecture §5.1）
   - nodes：`normalize`、`classify`、`abstain`
   - `builder.py` 骨架（先接无 LLM 节点）

2. **`feat: retrieve/grade 节点（对接向量阈值检索）`**
   - 工厂注入 retriever；State 携带 `kb_id`；grade 默认分数阈值规则；`GRADE_WITH_LLM` 预留（失败回退规则）

3. **`feat: rewrite/generate/cite/validate 节点`**
   - rewrite：LLM + 确定性 fallback，拒绝空/过长
   - generate：**stream + on_token**（见 architecture §6.2）
   - cite：仅来自 relevant_chunks；validate：丢非法引用、产出 confidence/reasoning_summary、空答案降级

4. **`feat: 图条件边、有界循环与 compile(checkpointer)`**
   - architecture §5.2 全边逻辑；`MAX_REWRITE_ATTEMPTS`（默认 2，上限 5）；`build_graph(...)`

5. **`feat: checkpointer 工厂与 session 绑定约定`**
   - `app/services/checkpoint.py`：PG 优先 / SQLite 回退；`thread_id = str(chat_session.id)` 写入文档与类型注释；预留级联删除接口

6. **`feat: Ollama/OpenAI/Anthropic 流式桥与 stream_bridge`**
   - 统一 `("thinking"|"delta", text)`；Ollama 强制 `think` + `num_ctx=8192`；generate **禁止 invoke 后切片**

7. **`test: 图节点与终止条件单测`**
   - 条件边路由；rewrite 达上限必停；空答案→abstain；非法 citation 丢弃；ScriptedChatModel **分块 yield** 断言回调收到多段

8. **`test: checkpointer 与 embed 指纹单测`**
   - thread 隔离；InMemorySaver；指纹不匹配抛错；DeterministicFakeEmbeddings 可复现

9. **`docs: 同步实现与 architecture 的偏差（如有）`**
   - 仅当实现必须改设计时本条；否则并入其他 docs commit

### Gate-M2

```bash
uv run ruff check .
uv run pytest -q
# 必须全绿且不依赖外网/Ollama：
uv run pytest tests/test_graph_nodes.py tests/test_chat_stream.py tests/test_checkpoint.py tests/test_providers.py -q
```

**Git 动作**：全绿 → `git tag -a m2 -m "Gate-M2 通过：Adaptive RAG+checkpointer+真流式节点"` → `git push origin main m2`

---

## M3 — 问答全链路（权限 SSE + 图 + 落库 + 反馈 + 检索调试 + 评估）

**目标**：`POST /api/chat/ask` 端到端真流式；权限前置；消息落库；feedback 与检索调试可用；eval 报告达标。

### Feature commits

1. **`feat: chat/ask SSE 接入 LangGraph`**
   - 权限前置（进 SSE 前 JSON 401/403/404）；ensure session；装配 history；`graph.stream` + on_token
   - 事件序：可选 `node` → `sources` → `thinking`×N → `delta`×N → `done` / `error`
   - **禁止伪流式**；零命中 `sources: []` + 兜底文案

2. **`feat: 会话与消息接口（含 checkpoint 级联）`**
   - sessions CRUD、messages、history；删除会话同步清 checkpoint

3. **`feat: chat_feedback 与 retrieval/search 调试接口`**
   - 👍/👎 落库；检索调试返回 chunks + score

4. **`feat: 向量入库接通 embed 指纹与 reindex 接口`**
   - ingest 写 `embed_index_meta`；`POST /knowledge-bases/{id}/reindex`；检索前指纹校验（不匹配 409/502）

5. **`feat: 知识库级联删除接通 Chroma 与 checkpoint`**
   - 替换 M1 占位 try/except

6. **`test: SSE 事件顺序与真流式（多段 delta）`**
   - Scripted 模型分块；断言 sources 先于 delta；delta 段数 > 1；零命中兜底；非成员 403 且不进 SSE；消息落库字段正确

7. **`test: 反馈、reindex、指纹不匹配、会话级联`**

8. **`feat: RAG 检索评估脚本`**
   - `scripts/eval_rag.py`：15 条 golden（seed_docs 三主题）→ `eval_report.md`；Hit@1/Hit@4/MRR/延迟；**Hit@4 ≥ 0.8**；本地连 Ollama，不进 CI

### Gate-M3

```bash
uv run ruff check . && uv run pytest -q
uv run python scripts/seed.py    # 向量化（本地 OLLAMA_BASE_URL=http://localhost:11434）
# user token SSE：
curl -N -X POST localhost:8000/api/chat/ask \
  -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"question":"员工请假需要提前几天申请？","kb_id":1}'
# 确认：sources → thinking×N（启用思考时）→ delta×N（分段到达）→ done
# sources 含真实文件名与 score；非成员 403；零命中兜底文案
uv run python scripts/eval_rag.py   # Hit@4 ≥ 0.8
```

**Git 动作**：全绿 → `git tag -a m3 -m "Gate-M3 通过：真流式 Adaptive RAG 全链路+评估"` → `git push origin main m3`

---

## M4 — 前端（纯静态 hash SPA）+ 工程化收尾

**目标**：SPA 全功能可走查；Docker/CI/README/截图齐；可选 node 进度与 feedback UI。

### Feature commits

1. **`feat: 单页骨架、hash 路由与主题样式`**
   - `static/index.html`、`css/style.css`、`js/router.js`；未登录跳 login；非 admin 访问 `#/admin/*` 弹回 `#/chat`

2. **`feat: fetch 封装与 SSE 流解析器`**
   - `js/api.js`：自动 token、401 跳登录、统一 toast；**fetch + ReadableStream** 解析 `event:`/`data:` 帧；读流前检查 HTTP 状态

3. **`feat: 登录页`**

4. **`feat: 对话页（会话、流式、引用卡、思考框、node 进度、feedback）`**
   - 会话栏 CRUD；kb 选择；引用卡片；思考框（限高折叠、不落库）；delta 打字机（rAF 批量刷新）；可选 node 进度；confidence；👍/👎

5. **`feat: 对话历史页`**（分页；admin 多用户过滤）

6. **`feat: 管理看板与 SVG 七日趋势`**（无图表库）

7. **`feat: 管理端知识库与成员管理页`**（含 reindex 入口；删除二次确认）

8. **`feat: 管理端文档与用户管理页`**（上传、2s 轮询、error_msg 重传）

9. **`feat: FastAPI 挂载静态资源`**（`GET /` → index.html）

10. **`feat: Docker 镜像与完整 compose 编排`**

11. **`ci: GitHub Actions（ruff + pytest + postgres service）`**

12. **`docs: README（架构图、双通道配置表、快速开始、截图、评估摘要）`**

13. **`docs: 补齐交付截图与 eval 摘要`**（`docs/screenshots/` 四张真实截图入库）

14. **`fix: Gate-M4 修复项`（如有）**

### Gate-M4（浏览器人工走查，逐条记录）

```text
# http://localhost:8000/ 人工走查：
[ ] 登录 admin → 看板数字与近7天 SVG 正确
[ ] 上传文档 → 列表 pending → completed
[ ] user 提问 → 流式打字机 + 引用卡片 + 思考框独立分框
[ ] （ENABLE_NODE_SSE）可见检索中/生成中等 node 进度
[ ] 👍/👎 可提交（接口 200；消息关联正确）
[ ] 新建/重命名/删除会话；删除后无 checkpoint 残留报错
[ ] admin 授权/移除成员后，user 端列表即时变化
[ ] user 改 URL 访问 #/admin/* → 弹回 #/chat
[ ] 401（删 token）后任意操作 → 跳回登录页
[ ] README 含 LLM/Embed 双通道与 reindex 说明
[ ] docs/screenshots/ 四张截图已入库
uv run ruff check . && uv run pytest -q   # 仍全绿
```

**Git 动作**：全绿 → `git tag -a m4 -m "Gate-M4 通过：纯静态前端+工程化交付"` → `git push origin main m4`

---

## 附 A：范围外清单（执行时勿擅自扩大）

| 不做 | 说明 |
|---|---|
| BM25 / RRF 混合检索 | 可选后续里程碑，不进 M1–M4 |
| rerank | 不做 |
| WebSocket | 不做；保持 SSE |
| K8s / 前端框架 / npm 构建 | 不做 |
| Anthropic Embeddings | 协议不存在；Embed 仅 `ollama` \| `openai` |
| 静默降级到本地模型 | API 缺 key 必须失败 |
| 伪流式 generate | Gate-M2/M3 一票否决 |
| 与会话脱钩的随机 thread_id | checkpointer 必须 `session.id` |
| 独立多轮改写服务 | 仅 checkpointer + 有限 history |

---

## 附 B：里程碑验收命令速查（Git Bash）

```bash
# 每次 commit 前
uv run ruff check . && uv run pytest -q

# Gate-M1
uv sync && uv run python --version && uv run alembic upgrade head \
  && uv run python scripts/seed.py && find seed_docs -type f | wc -l

# Gate-M2
uv run pytest tests/test_graph_nodes.py tests/test_chat_stream.py \
  tests/test_checkpoint.py tests/test_providers.py -q

# Gate-M3
uv run pytest -q && uv run python scripts/eval_rag.py
# + curl -N SSE 断言事件序与分段 delta

# Gate-M4
uv run ruff check . && uv run pytest -q
# + 浏览器走查清单
```
