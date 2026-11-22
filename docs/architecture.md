# langgraph_enterprise_assistant 架构设计

> 本文是项目的**设计基准**：做什么、做成长什么样以本文为准；执行顺序与提交节奏见 `docs/plan.md`。
> 文档自包含，不依赖任何外部仓库或历史项目。

---

## 1. 系统总览

企业级知识库问答系统：知识库管理 → 文档异步入库 → 带权限的向量检索 → **LangGraph Adaptive RAG**（分类 / 评分 / 有限改写 / 拒答 / 引用校验）→ **SSE 真流式问答** → 多会话 + checkpointer → 管理端看板。

```mermaid
flowchart LR
    B[浏览器 static/ 纯静态 SPA] -->|HTTP / SSE| F[FastAPI app/]
    F --> PG[(PostgreSQL<br/>业务数据 + LangGraph checkpoint)]
    F --> CH[(Chroma 内嵌<br/>kb_id 独立 collection cosine)]
    F --> G[LangGraph Adaptive RAG]
    G --> CS[ChatStreamer Protocol]
    G --> EM[Embedder Protocol]
    CS -. 默认 .-> O1[Ollama qwen3:4b]
    CS -. openai .-> A1[OpenAI 兼容 API]
    CS -. anthropic .-> A2[Anthropic Claude API]
    EM -. 默认 .-> O2[Ollama qwen3-embedding:4b]
    EM -. openai .-> A3[OpenAI 兼容 embeddings]
```

---

## 2. 技术定稿（已确认，不得擅自更改）

| 维度 | 决策 |
|---|---|
| 执行环境 | Windows 11 + Git Bash；Python 固定 **3.12**；环境管理**只用 uv**；禁用 `python3`/裸 `python`/conda |
| 前端 | 纯静态 HTML/JS/CSS，hash 路由 + ES Modules，手写 CSS；**无构建、无 CDN、无 npm** |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic + Alembic |
| 关系库 | **PostgreSQL 16**（docker-compose；测试库 `langgraph_enterprise_test`） |
| 向量库 | Chroma 内嵌；每库 `kb_{id}`；**必须 `metadata={"hnsw:space":"cosine"}`** |
| 编排 | **LangGraph** `StateGraph` + 条件边 + 有界 rewrite 循环 + **checkpointer** |
| LLM 通道 | `LLM_PROVIDER = ollama \| openai \| anthropic`（独立于 embedding） |
| Embedding 通道 | `EMBED_PROVIDER = ollama \| openai`（**无 anthropic**） |
| 本地默认 | LLM=`qwen3:4b`，Embed=`qwen3-embedding:4b`（需求方指定，**不得降级**） |
| 真流式 | 图内 generate **stream + 回调**；SSE `sources → thinking×N → delta×N → done` |
| Checkpointer | **启用**；`thread_id = str(chat_session.id)`；优先 PG saver |
| 权限 | JWT + admin/user + kb 成员级授权；禁用用户立即 401 |
| 密码 | bcrypt（work factor 12） |
| 测试 | pytest（接口/权限/图节点/SSE 顺序/四格式）+ 本地 eval（不进 CI） |
| 部署 | Docker Compose（postgres + api）+ GitHub Actions（ruff + pytest） |
| 交付 | GitHub 公开仓库 + 4 张真实截图 + `eval_report.md` |

### 明确不做（防蔓延）

WebSocket、前端构建、前端测试框架、Kubernetes、rerank、BM25 混合检索（可作后续可选增强，**不进 M1–M4**）、LangSmith 云端（仅预留 env 开关）、跨会话独立的多轮改写服务（跨轮仅通过 checkpointer 装配有限 history）。

---

## 3. 目录结构

```
langgraph_enterprise_assistant/
├── CLAUDE.md
├── docs/
│   ├── plan.md
│   ├── architecture.md          # 本文
│   └── screenshots/
├── README.md
├── LICENSE
├── .gitignore
├── .python-version              # 3.12
├── uv.lock
├── .env.example
├── pyproject.toml
├── docker-compose.yml
├── docker/initdb/init.sql
├── Dockerfile
├── .github/workflows/ci.yml
├── alembic.ini / alembic/
├── eval_report.md
├── seed_docs/                   # 12 份，三子目录，勿改
├── app/
│   ├── main.py                  # create_app：路由、静态、CORS、lifespan（死状态清理）
│   ├── core/
│   │   ├── config.py            # Pydantic Settings（双通道）
│   │   └── security.py          # bcrypt、JWT、login_required / admin_required
│   ├── db.py
│   ├── models/                  # users, knowledge_bases, kb_members, documents,
│   │                            # chat_sessions, chat_messages, chat_feedback, embed_index_meta
│   ├── schemas/
│   ├── api/routes/              # auth, users, knowledge_bases, documents,
│   │                            # chat, stats, retrieval(调试), feedback
│   ├── middleware.py            # Request-ID
│   ├── services/
│   │   ├── llm/
│   │   │   ├── base.py          # ChatStreamer / Embedder Protocol + 工厂
│   │   │   ├── ollama_chat.py / ollama_embed.py
│   │   │   ├── openai_chat.py / openai_embed.py
│   │   │   └── anthropic_chat.py
│   │   ├── adaptive_rag/        # LangGraph（不依赖 FastAPI）
│   │   │   ├── state.py
│   │   │   ├── builder.py       # 条件边 + 有界循环 + compile(checkpointer)
│   │   │   ├── nodes/           # normalize classify retrieve grade rewrite
│   │   │   │                    # generate cite validate abstain
│   │   │   ├── prompts/
│   │   │   └── stream_bridge.py # generate 内 token → SSE 回调
│   │   ├── vector.py            # Chroma cosine + 指纹校验
│   │   ├── parser.py / chunker.py / ingest.py
│   │   └── checkpoint.py        # get_checkpointer（PG 优先，SQLite 回退）
│   └── logging_setup.py         # Json/Text formatter（可选）
├── static/                      # 零依赖 SPA
├── scripts/
│   ├── seed.py
│   └── eval_rag.py              # 15 条 golden → eval_report.md
└── tests/
    ├── conftest.py              # 测试库、工厂、ScriptedChatModel、InMemorySaver
    ├── test_auth.py / test_knowledge_base.py / test_documents.py
    ├── test_parser.py / test_chat_sse.py / test_stats.py
    ├── test_graph_nodes.py      # 条件边、rewrite 上限、拒答、引用校验
    ├── test_chat_stream.py      # 真流式：多段 delta，禁止切片实现
    ├── test_providers.py        # 双通道工厂、缺 key 失败、embed 指纹
    └── test_checkpoint.py       # thread 绑定与级联清理
```

---

## 4. 配置与环境变量（`app/core/config.py`，`.env.example` 全量）

### 4.1 安全与数据库

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key-change-me` | 生产必换；随机值会导致重启全员掉线 |
| `JWT_EXPIRE_HOURS` | `24` | |
| `DATABASE_URL` | `postgresql+psycopg2://rag:rag123@localhost:5432/langgraph_enterprise` | 测试库 `langgraph_enterprise_test` |

### 4.2 LLM 通道（生成 / 改写 / 评分）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `openai` \| `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | compose 内 `http://host.docker.internal:11434` |
| `OLLAMA_LLM_MODEL` | `qwen3:4b` | **不得降级** |
| `OLLAMA_THINK` | `true` | thinking 以 SSE `thinking` 转发；false 更省时 |
| `OLLAMA_NUM_CTX` | `8192` | **必须限制**，防 16GB 显存挤爆 |
| `OPENAI_API_KEY` | 空 | `LLM_PROVIDER=openai` 时必填；**绝不提交真实 key** |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 可指任意 OpenAI 兼容端点 |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `ANTHROPIC_API_KEY` | 空 | `LLM_PROVIDER=anthropic` 时必填 |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | 按需求方所选模型名填写 |
| `ANTHROPIC_MAX_TOKENS` | `4096` | API 硬性要求 |
| `ANTHROPIC_BASE_URL` | 空 | 可选，默认官方 |
| `LLM_TIMEOUT_SECONDS` | `30` | 三 Provider 统一 |
| `LLM_MAX_RETRIES` | `3` | 三 Provider 统一 |

**校验**：`LLM_PROVIDER` 指向 API 且对应 key 为空 → **启动或首次调用显式失败**，禁止静默回退 Ollama。

### 4.3 Embedding 通道（入库 / 检索）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `EMBED_PROVIDER` | `ollama` | `ollama` \| `openai`（**无 anthropic**） |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:4b` | **不得降级**；`num_ctx` 固定 4096 |
| `EMBED_API_KEY` | 空 | `EMBED_PROVIDER=openai` 时必填；可与 LLM key 不同 |
| `EMBED_BASE_URL` | 空则回退 `OPENAI_BASE_URL` | 双网关时独立填写 |
| `EMBED_MODEL` | 空则回退 `text-embedding-3-small` | |

### 4.4 检索 / 分块 / 存储 / 图

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RETRIEVAL_TOP_K` | `4` | |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.3` | cosine：`relevance = 1 - distance`，低于阈值丢弃 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `500` / `50` | |
| `CHROMA_PERSIST_DIR` | `chroma_data` | gitignore |
| `UPLOAD_DIR` | `uploads` | gitignore |
| `UPLOAD_MAX_MB` | `50` | |
| `MAX_REWRITE_ATTEMPTS` | `2` | 图内有界循环，配置上限 5 |
| `GRADE_WITH_LLM` | `false` | true 时 grade 可用 LLM，失败回退分数规则 |
| `ENABLE_NODE_SSE` | `true` | SSE 可选 `node` 进度事件 |
| `CHECKPOINT_ENABLED` | `true` | 关闭仅用于单测提速 |
| `CHECKPOINT_TABLE` | `langgraph_checkpoints` | PG 表名（若用 PG saver） |

---

## 5. LangGraph Adaptive RAG

### 5.1 State（`TypedDict`，可序列化）

```text
# 输入
question, normalized_question, top_k, history: list[dict]  # 近 N 轮摘要，可选
# 检索
active_query, chunks, relevant_chunks, retrieval_attempts, rewrite_count, max_rewrite_attempts
# 判定
route: knowledge|clarification, is_sufficient, grade_reason, refusal_reason
# 生成
answer, citations, confidence, reasoning_summary, status: answered|insufficient_evidence
# 可观测
errors: list[str]
```

约束：不存 API Key、不存隐藏思维链；`rewrite_count` 保证可终止。

### 5.2 边逻辑

```text
START → normalize → classify
  clarification → abstain
  knowledge → retrieve → grade
    sufficient → generate → cite → validate → END
    not & rewrite_count < MAX → rewrite → retrieve     # 有界循环
    not & rewrite_count ≥ MAX → abstain → cite → validate → END
generate 空答案 → abstain → cite → validate → END
```

节点职责：

| 节点 | 职责 |
|---|---|
| `normalize` | 清洗问题；可选结合 `history` 做指代消解 |
| `classify` | 轻量路由 `knowledge` / `clarification`（空问题或超长 → clarification） |
| `retrieve` | 按 `active_query` + **当前 kb_id** 调 `vector.search` |
| `grade` | 默认分数阈值规则；`GRADE_WITH_LLM=true` 时可 LLM 评分，失败必须回退规则 |
| `rewrite` | LLM 改写失败 → 确定性 fallback 后缀；拒绝空/过长输出；递增 `rewrite_count` |
| `generate` | **流式**生成 grounded answer；经 `on_token` 吐 thinking/delta |
| `cite` | **仅从 relevant_chunks 构建引用**，模型不得发明 id |
| `validate` | 丢弃无法映射回检索结果的 citation；空答案降级拒答；产出 confidence / reasoning_summary |
| `abstain` | 固定拒答文案 + `status=insufficient_evidence` |

约束：nodes **不 import FastAPI**；retriever、chat_model、on_token 均工厂注入；检索材料在 prompt 中视为**不可信数据**。

### 5.3 Checkpointer

| 项 | 决策 |
|---|---|
| 默认 | **开启** |
| `thread_id` | `str(chat_session.id)`（PG 会话主键），禁止与会话脱钩的随机 uuid |
| 存储 | 优先 `langgraph-checkpoint-postgres` 写入同一 PG；依赖不可用时回退 SQLite 文件（路径 gitignore），并文档注明回退条件 |
| 测试 | 单测 `InMemorySaver` 或 `CHECKPOINT_ENABLED=false` |
| 级联 | `DELETE /knowledge-bases/{id}`、删除会话时 **同步删除该 thread 的 checkpoint 行** |
| 与消息表关系 | `chat_messages` = 展示与审计真源；checkpoint 只服务图执行与跨轮 history |

### 5.4 跨轮上下文（有限）

- `normalize` 可读 `state.history`（路由层从本会话最近 N 条 `chat_messages` 装配，截断 token 预算）做指代消解写入 `normalized_question`
- **不做**独立的多轮改写服务；每轮以当前问题 + 有限 history 为输入
- history 只进 prompt 辅助理解；检索 query 以图内 rewrite 结果为准

---

## 6. 真流式协议（关键路径）

### 6.1 内部接口

```python
class ChatStreamer(Protocol):
    def stream(
        self, *, system: str, messages: list[dict]
    ) -> Iterator[tuple[str, str]]:
        """yield ("thinking" | "delta", text)；禁止整段返回后由调用方切片。"""

class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def fingerprint(self) -> str:
        """如 'ollama/qwen3-embedding:4b' 或 'openai/text-embedding-3-small'，用于索引校验。"""
```

| Provider | thinking 来源 | 流式方式 |
|---|---|---|
| ollama | `message.thinking`（`OLLAMA_THINK=true`） | 官方 SDK `stream=True` |
| openai 兼容 | `reasoning_content`（若有） | `stream=True` |
| anthropic | thinking content block（若启用） | `messages.stream` |

三 Provider 统一超时与重试（`LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES`）；Ollama 路径**强制** `num_ctx=8192`，不得被库默认值冲掉。

### 6.2 generate 节点（禁止伪流式）

```text
工厂签名: make_generate_node(chat_model, on_token: Callable[[str, str], None] | None)
实现:
  1. chat_model.stream(...) 逐块累加 answer
  2. 每块: on_token("thinking"|"delta", chunk)   # 无 on_token 时仅累加（单测）
  3. 结束写入 state["answer"]
禁止: invoke 整段 → 再按固定长度切片 yield
```

### 6.3 SSE 事件序

```
event: node          # 可选，ENABLE_NODE_SSE=true：{"node":"retrieve"|"grade"|...}
event: sources       # 检索完成后、generate 前；零命中为 []
event: thinking      # ×N，可选，不落库
event: delta         # ×N，逐段到达
event: done          # 落库成功后：{session_id, message_id, status, confidence?}
event: error         # {message}；进 SSE 前的权限失败仍是 JSON 401/403
```

- 前端 fetch + ReadableStream 解析（EventSource 不支持 POST）
- **Gate 验收**：`curl -N` 观察 delta **多次到达**；sources 先于 delta；禁止一次性大块
- 零命中：`sources: []` + 兜底文案「未找到相关内容，请换个问法」，不算错误

---

## 7. 数据模型

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | id, username(uniq), password_hash, nickname, role(`admin`/`user`), status(1/0), created_at | bcrypt |
| `knowledge_bases` | id, name, description, created_by→users, status, created_at, updated_at | |
| `kb_members` | id, kb_id, user_id, created_at；UNIQUE(kb_id,user_id) | 可见/可问某 KB ⇔ admin 或在表中 |
| `documents` | id, kb_id, filename, stored_name(uuid), file_type, file_size, status(`pending`/`processing`/`completed`/`failed`), error_msg, chunk_count, created_by, timestamps | 路径 `uploads/{stored_name}` |
| `chat_sessions` | id, user_id, kb_id, title, created_at, updated_at | **id 字符串化即 graph thread_id**；title 默认首问前 20 字 |
| `chat_messages` | id, session_id, user_id, kb_id, question, answer, sources(JSON), confidence, status, created_at | sources：file_name/chunk_index/score/snippet；thinking 不落库 |
| `chat_feedback` | id, message_id, user_id, score(+1/-1), comment, created_at | UNIQUE(message_id, user_id) |
| `embed_index_meta` | kb_id PK, embed_fingerprint, dimension, updated_at | 与 Chroma collection metadata 双写 |

### 权限规则（必须有测试覆盖）

- `admin`：全部资源；管理成员、上传/删文档、看全部对话历史与反馈
- `user`：只能列出/问答「自己是成员」的知识库；只能看自己的会话与消息
- 所有涉及 kb 的读写接口**后端强校验**，不能只靠前端隐藏菜单
- **禁用用户（status=0）**：`login_required` 每次查库校验 status，存量 JWT 立即 401

### 删除级联（定稿）

- `DELETE /knowledge-bases/{id}` = **级联物理删除**：documents → uploads 物理文件 → Chroma `kb_{id}` collection → 全部 chat_sessions / chat_messages → **该库全部 thread 的 checkpoint** → embed_index_meta；任一步失败整体回滚
- `DELETE /documents/{id}`：记录 + 物理文件 + Chroma 分块
- `DELETE /chat/sessions/{id}`：messages + 对应 checkpoint
- `DELETE /users/{id}` = 禁用（status=0），不物理删

### Embedding 指纹与 reindex

1. 入库与建 collection 时写入 `embed_fingerprint` + `dimension`
2. 检索前校验：当前 `Embedder.fingerprint` ≠ 索引指纹 → **409/502 明确错误**（`embedding_mismatch`），禁止静默用错向量
3. `POST /knowledge-bases/{id}/reindex`：清空该库向量后全量重建（换 Embed 模型后唯一合法路径）
4. **同一 kb 生命周期内默认固定一种 embedding**；切换必须 reindex

### 迁移与测试库

- Alembic 管理全部表；相关 Gate 执行 `alembic upgrade head`
- `docker/initdb/init.sql` 首次启动建 `langgraph_enterprise_test`；`conftest.py` 在测试库跑迁移

---

## 8. API 设计（前缀 `/api`；除登录外全部 `Authorization: Bearer <token>`）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | 公开 | `{username,password}` → `{token,user}`；status=0 拒绝 |
| GET | `/auth/me` | 登录 | 当前用户（校验 status） |
| GET/POST | `/users` | admin | 列表(分页)/创建 |
| PUT/DELETE | `/users/{id}` | admin | 修改(含重置密码)/禁用 |
| GET | `/knowledge-bases` | 登录 | admin 全部；user 仅成员可见 |
| POST/PUT/DELETE | `/knowledge-bases[/{id}]` | admin | CRUD；删除级联见 §7 |
| GET/POST/DELETE | `/knowledge-bases/{id}/members[/{user_id}]` | admin | 成员授权 |
| POST | `/knowledge-bases/{id}/reindex` | admin | 换 embed 后重建向量 |
| GET/POST/DELETE | `/documents…` | 按 kb 权限 | 列表含 status；multipart 上传；删除同步清 Chroma+文件 |
| POST | `/chat/ask` | 按 kb 权限 | **SSE**；body `{question,kb_id,session_id?}`；无 session 自动创建 |
| GET/POST/PATCH/DELETE | `/chat/sessions…` | 归属/admin | 会话列表/新建/重命名/删除（级联消息+checkpoint） |
| GET | `/chat/sessions/{id}/messages` | 归属/admin | 消息升序 |
| GET | `/chat/history?page=&user_id=` | 登录 | 分页；admin 可按用户过滤 |
| POST | `/chat/feedback` | 登录 | `{message_id, score(+1/-1), comment?}` |
| POST | `/retrieval/search` | 登录/admin | 调试：`{query,kb_id?,top_k?}` → chunks+score |
| GET | `/stats/dashboard` | admin | `{users,kbs,documents,messages, trend:[{date,count}]}` 近 7 天 |

### 问答调用链（`POST /chat/ask`）

```text
login_required → kb 存在 → 成员校验（失败 JSON 403/404，不进 SSE）
→ ensure session（PG）→ 装配 history（近 N 条）→ 初始 State
→ graph.stream(..., config={thread_id: str(session.id)})
    on_token → SSE thinking/delta
    retrieve/grade 完成 → SSE sources（及可选 node）
→ validate 后落库 chat_messages（answer + sources + confidence + status）
→ SSE done
异常 → SSE error（进图前故障可 502）
```

---

## 9. RAG 管线

1. **parser.py**：txt/md（utf-8）、pdf（pypdf）、docx（python-docx）；解析为空抛业务异常
2. **chunker.py**：递归分隔符（`\n\n` → `\n` → `。` → 字符滑窗），500/50，产出 `chunk_index`
3. **vector.py**（Chroma 封装）：
   - `add_chunks` / `delete_doc` / `delete_collection` / `search`
   - **建 collection 必须 `metadata={"hnsw:space":"cosine"}`**——否则 `1-distance` 阈值语义失效
   - 分块 id：`doc_{doc_id}_chunk_{i}`；metadata：doc_id / file_name / chunk_index
   - 写入时校验并更新 `embed_index_meta`
4. **ingest.py**：BackgroundTasks 触发；`pending → processing → completed|failed`；失败写 `error_msg`；Ollama/API 不可达给可读错误；lifespan startup 清理遗留 `pending`/`processing` 为 `failed`
5. **chat/ask**：见 §6、§8；**禁止先整段生成再切片伪装流式**

---

## 10. 前端架构（纯静态 hash SPA）

| 路由 | 页面 | 要点 |
|---|---|---|
| `#/login` | login.js | 登录表单 |
| `#/chat` | chat.js（核心） | 左：会话栏 CRUD；中：提问 → 引用卡片 → **思考框**（限高 180px、可折叠）→ delta 打字机 → done；可选 **node 进度**；confidence 徽章；👍/👎 feedback；顶：kb 选择器 |
| `#/history` | history.js | 分页历史；admin 多用户过滤 |
| `#/admin` | admin.js | 统计卡 + **手写 SVG 柱状图**（近 7 天） |
| `#/admin/kb` | admin_kb.js | KB CRUD（删除二次确认级联范围）+ 成员 + **reindex 按钮** |
| `#/admin/docs` | admin_docs.js | 上传/列表/**2s 轮询**；failed 显示 error_msg 可重传 |
| `#/admin/users` | admin_users.js | 用户 CRUD、角色、重置密码 |

- `router.js`：手写 hash 路由；未登录跳 login；**非 admin 访问 admin 路由弹回 `#/chat`**
- `api.js`：fetch 封装（自动带 token、401 跳登录、统一 toast）+ **SSE 解析器**；读流前先检查 HTTP 状态
- 流式渲染：thinking/delta 按 **rAF 批量刷新**；思考框贴底跟随仅在用户距底 48px 内生效
- 思考过程**仅流式展示不落库**
- `style.css`：CSS 变量主题；≥900px 双栏，以下单栏
- FastAPI 挂 `static/`：`GET /` 返回 index.html；`/docs` 仍可用

---

## 11. 测试与评估

- **conftest.py**：独立测试库 `langgraph_enterprise_test`（alembic 建表）、应用工厂、`ScriptedChatModel`（按块 yield）、`DeterministicFakeEmbeddings`、`InMemorySaver`
- **必须覆盖**：
  - 登录/过期/错误密码/禁用 401；**权限矩阵**（非成员 403/404、admin 全通过）
  - 上传/类型/超限/删除；**四格式解析**（fixture 用 seed_docs 真实文件）
  - 图：条件边路由、rewrite 达上限必停、空答案→abstain、非法 citation 丢弃
  - SSE：sources → thinking → delta **多段** → done；零命中兜底；**无「整段切片」**；非成员不进 SSE
  - Provider 工厂：缺 key 显式失败；三 LLM、两 embed 分支
  - embed 指纹不匹配拒绝检索；reindex 路径
  - checkpoint：thread=session.id；删除级联清理
  - stats
- CI **不依赖** Ollama / 真 API（RAG 全 mock）
- **eval**：15 条 golden 问答对（按 seed_docs 三主题域出题）→ `eval_report.md`；指标 Hit@1、Hit@4、MRR、平均检索延迟；**Hit@4 ≥ 0.8**；`scripts/eval_rag.py` 本地跑，不进 CI

---

## 12. 部署与 CI

- **Dockerfile**：`python:3.12-slim` + uv（先拷 `pyproject.toml`/`uv.lock` → `uv sync --frozen --no-dev` 利用层缓存），非 root，`uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **compose**：db（postgres:16 + healthcheck + volume + initdb）+ api（depends_on db healthy，挂 `chroma_data`/`uploads` volume，`.env` 注入，`extra_hosts: host.docker.internal:host-gateway`）；`down` 不删数据，`down -v` 才清
- **CI**（`.github/workflows/ci.yml`）：push/PR → `astral-sh/setup-uv` → `uv sync --frozen` → `uv run ruff check .` → `uv run pytest`（postgres:16 service）
- 永不提交：`.env`、`uploads/`、`chroma_data/`、`.venv/`、`__pycache__/`、checkpoint 文件（若 SQLite 回退）
- `uv.lock`、`seed_docs/`、`docs/screenshots/`、`eval_report.md` **入库**

---

## 13. 质量红线汇总（与 CLAUDE.md 一致）

1. 权限后端强校验；禁用用户 401  
2. bcrypt；Chroma 显式 cosine  
3. **真流式**；图内 generate 不得伪流式  
4. 入库异步状态机 + 死状态清理  
5. 前端零 npm/CDN；SVG 手写图表  
6. 默认本地 Ollama 两模型；API 为显式切换；缺 key 显式失败  
7. Embed 指纹 + 强制 reindex  
8. checkpointer 开启且绑定 session、级联清理  
9. 引用只来自检索；检索内容视为不可信数据  
10. 不做 rerank / WebSocket / K8s / 前端构建  
