// 对话页（核心）：会话栏 CRUD、kb 选择、SSE 流式、引用卡、思考框、node 进度、feedback
// 交互参照根目录 chat.js（预建会话、kb 过滤会话、details 折叠、48px 贴底、富文本），
// 但保持本项目 API 契约（裸数组、data.text、lga_* 存储）与全局侧栏结构。
import { api, sseAsk, toast } from "./api.js";

const S = {
  kbs: [],
  sessions: [],
  sessionId: null,
  kbId: null,
  streaming: false,
};

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

export async function renderChat() {
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="chat-layout">
      <div class="session-pane">
        <div class="head">
          <select id="kb-select" title="选择知识库"></select>
          <button id="new-session" class="sm" title="新建会话">＋</button>
        </div>
        <div class="session-list" id="session-list"></div>
      </div>
      <div class="chat-main">
        <div class="chat-msgs" id="chat-msgs"></div>
        <div class="composer">
          <select id="kb-select-2" class="kb-select" title="选择知识库"></select>
          <textarea id="question" placeholder="输入问题，Enter 发送，Shift+Enter 换行"></textarea>
          <button id="send-btn">发送</button>
        </div>
      </div>
    </div>`;

  await loadKbs();
  await loadSessions();
  wireEvents();
  if (S.sessions.length && !S.sessionId) {
    const first = visibleSessions()[0];
    if (first) S.sessionId = first.id;
  }
  renderSessionList();
  if (S.sessionId) await loadMessages(S.sessionId);
  else showEmpty();
}

function showEmpty() {
  document.getElementById("chat-msgs").innerHTML = `
    <div class="empty-hint">
      <h2>选择或新建会话，开始提问吧 👋</h2>
      <p>选择知识库后输入问题，回答将带引用与思考过程实时流出。</p>
    </div>`;
}

/** 会话列表只展示当前知识库的会话（前端过滤，避免 kb/会话错配）。 */
function visibleSessions() {
  return S.sessions.filter((s) => s.kb_id === S.kbId);
}

async function loadKbs() {
  S.kbs = await api("/api/knowledge-bases"); // 后端返回裸数组
  if (!S.kbId && S.kbs.length) S.kbId = S.kbs[0].id;
  syncKbSelects();
}

function syncKbSelects() {
  for (const id of ["kb-select", "kb-select-2"]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.innerHTML = S.kbs
      .map(
        (k) =>
          `<option value="${k.id}" ${k.id === S.kbId ? "selected" : ""}>${esc(k.name)}</option>`
      )
      .join("");
    if (S.kbId) el.value = String(S.kbId);
  }
}

async function loadSessions() {
  S.sessions = await api("/api/chat/sessions"); // 后端返回裸数组
}

function renderSessionList() {
  const el = document.getElementById("session-list");
  if (!el) return;
  const list = visibleSessions();
  if (!list.length) {
    el.innerHTML = `<div style="padding:16px;color:#94a3b8;font-size:13px">该知识库暂无会话，点右上 ＋ 新建</div>`;
    return;
  }
  el.innerHTML = list
    .map(
      (s) => `
    <div class="session-item ${s.id === S.sessionId ? "active" : ""}" data-id="${s.id}">
      <span class="title">${esc(s.title || "未命名会话")}</span>
      <span class="ops">
        <button class="sm ghost ren" title="重命名">✎</button>
        <button class="sm ghost del" title="删除">✕</button>
      </span>
    </div>`
    )
    .join("");

  el.querySelectorAll(".session-item").forEach((item) => {
    const id = Number(item.dataset.id);
    item.addEventListener("click", async (e) => {
      if (e.target.closest(".ren") || e.target.closest(".del")) return;
      S.sessionId = id;
      renderSessionList();
      await loadMessages(id);
    });
    item.querySelector(".ren").addEventListener("click", async () => {
      const s = S.sessions.find((x) => x.id === id);
      const title = prompt("重命名会话", s.title || "");
      if (!title) return;
      try {
        await api(`/api/chat/sessions/${id}`, { method: "PATCH", body: { title } });
        s.title = title;
        renderSessionList();
        toast("已重命名", "ok");
      } catch (err) {
        toast(err.message, "error");
      }
    });
    item.querySelector(".del").addEventListener("click", async () => {
      if (!confirm("删除该会话？消息记录将一并删除。")) return;
      try {
        await api(`/api/chat/sessions/${id}`, { method: "DELETE" });
        S.sessions = S.sessions.filter((x) => x.id !== id);
        if (S.sessionId === id) {
          S.sessionId = null;
          showEmpty();
        }
        renderSessionList();
        toast("会话已删除", "ok");
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });
}

function wireEvents() {
  const onKbChange = (value) => {
    S.kbId = Number(value);
    syncKbSelects();
    // 切换知识库 → 退出当前会话并清空消息（会话列表已按 kb 过滤）
    S.sessionId = null;
    renderSessionList();
    showEmpty();
  };
  document.getElementById("kb-select")?.addEventListener("change", (e) =>
    onKbChange(e.target.value)
  );
  document.getElementById("kb-select-2")?.addEventListener("change", (e) =>
    onKbChange(e.target.value)
  );

  document.getElementById("new-session")?.addEventListener("click", async () => {
    if (!S.kbId) {
      toast("请先选择知识库", "error");
      return;
    }
    try {
      const s = await api("/api/chat/sessions", {
        method: "POST",
        body: { title: "", kb_id: S.kbId },
      });
      S.sessions.unshift(s);
      S.sessionId = s.id;
      renderSessionList();
      showEmpty();
      document.getElementById("question").focus();
    } catch (err) {
      toast(err.message, "error");
    }
  });

  const ta = document.getElementById("question");
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.getElementById("send-btn").addEventListener("click", send);
}

async function loadMessages(sessionId) {
  const msgs = await api(`/api/chat/sessions/${sessionId}/messages`);
  const box = document.getElementById("chat-msgs");
  if (!msgs.length) {
    showEmpty();
    return;
  }
  box.innerHTML = msgs.map(renderHistoryMsg).join("");
  box.scrollTop = box.scrollHeight;
  bindFeedback(box);
}

function renderHistoryMsg(m) {
  return `
    <div class="msg user"><div class="role">我</div><div class="bubble">${esc(m.question)}</div></div>
    <div class="msg assistant">
      <div class="role">助手
        ${m.confidence != null ? `<span class="badge ${m.status === "answered" ? "ok" : "warn"}">confidence ${Number(m.confidence).toFixed(2)}</span>` : ""}
        <span class="badge">${m.status === "answered" ? "已回答" : "证据不足"}</span>
      </div>
      <div class="bubble">${formatAnswer(m.answer)}
        ${renderSources(m.sources || [])}
      </div>
      <div class="fb-row" data-msg="${m.id}">
        <button class="fb-up" title="有用">👍</button>
        <button class="fb-down" title="没用">👎</button>
        <span class="fb-tip" style="font-size:12px;color:#94a3b8"></span>
      </div>
    </div>`;
}

function renderSources(sources) {
  if (!sources || !sources.length) return "";
  return `
    <div class="cite-cards">
      <div class="cite-title">📎 引用来源（${sources.length}）</div>
      ${sources
        .map(
          (c) => `
        <details class="cite-card">
          <summary>
            <span class="fname">${esc(c.file_name || "未知文件")}</span>
            <span class="meta">#${c.chunk_index ?? 0} · ${((c.score || 0) * 100).toFixed(1)}%</span>
          </summary>
          <div class="snip">${esc(c.snippet || "")}</div>
        </details>`
        )
        .join("")}
    </div>`;
}

function renderThinking(text) {
  return `
    <details class="thinking-box" open>
      <summary>🤔 思考过程</summary>
      <div class="thinking-body">${esc(text)}</div>
    </details>`;
}

function bindFeedback(root) {
  root.querySelectorAll(".fb-row").forEach((row) => {
    const id = row.dataset.msg;
    row.querySelector(".fb-up")?.addEventListener("click", () => submitFb(row, id, 1));
    row.querySelector(".fb-down")?.addEventListener("click", () => submitFb(row, id, -1));
  });
}

async function submitFb(row, messageId, score) {
  try {
    await api("/api/chat/feedback", {
      method: "POST",
      body: { message_id: Number(messageId), score },
    });
    row.querySelector(".fb-up")?.classList.toggle("on-ok", score === 1);
    row.querySelector(".fb-down")?.classList.toggle("on-no", score === -1);
    row.querySelector(".fb-tip").textContent = score === 1 ? "感谢反馈！" : "已收到，我们会改进";
    toast("反馈已提交", "ok");
  } catch (e) {
    toast(e.message, "error");
  }
}

const NODE_CN = {
  normalize: "预处理",
  classify: "意图分类",
  retrieve: "检索中",
  grade: "相关性评分",
  rewrite: "查询改写",
  generate: "生成中",
  cite: "引用整理",
  validate: "校验中",
  abstain: "证据不足",
};

async function send() {
  if (S.streaming) return;
  const ta = document.getElementById("question");
  const question = ta.value.trim();
  if (!question) return;
  if (!S.kbId) {
    toast("请先选择知识库", "error");
    return;
  }
  ta.value = "";

  // 发送前预建会话（带标题），保证 session_id 与 kb 一致
  if (!S.sessionId) {
    try {
      // 标题留空：首次回答落库时后端按问题精简版自动命名（交互完成后刷新可见）
      const s = await api("/api/chat/sessions", {
        method: "POST",
        body: { title: "", kb_id: S.kbId },
      });
      S.sessions.unshift(s);
      S.sessionId = s.id;
      renderSessionList();
    } catch (err) {
      toast(err.message, "error");
      return;
    }
  }

  S.streaming = true;
  document.getElementById("send-btn").disabled = true;

  const box = document.getElementById("chat-msgs");
  if (box.querySelector(".empty-hint")) box.innerHTML = "";

  box.insertAdjacentHTML(
    "beforeend",
    `<div class="msg user"><div class="role">我</div><div class="bubble">${esc(question)}</div></div>`
  );

  const aid = `a-${Date.now()}`;
  box.insertAdjacentHTML(
    "beforeend",
    `<div class="msg assistant" id="${aid}">
      <div class="role">助手</div>
      <div class="node-progress"></div>
      <div class="cite-cards" id="${aid}-cites"></div>
      <div class="bubble">
        <details class="thinking-box" id="${aid}-think" open hidden>
          <summary>🤔 思考过程</summary>
          <div class="thinking-body"></div>
        </details>
        <span class="answer-text"></span><span class="cursor">▍</span>
      </div>
      <div class="fb-row hidden"></div>
    </div>`
  );
  const root = document.getElementById(aid);
  const nodeEl = root.querySelector(".node-progress");
  const thinkBox = root.querySelector(`#${aid}-think`);
  const thBody = thinkBox.querySelector(".thinking-body");
  const ansEl = root.querySelector(".answer-text");
  const cursor = root.querySelector(".cursor");
  const citeWrap = root.querySelector(`#${aid}-cites`);
  const fbRow = root.querySelector(".fb-row");

  // 距底 48px 内才跟随滚动（architecture §10）
  const stickToBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 48;

  let fullAnswer = ""; // 累计全文（rAF 批量重渲染，避免只渲染增量段）
  let deltaDirty = false;
  let pendingThinking = "";
  let rafId = 0;
  const flush = () => {
    rafId = 0;
    if (pendingThinking) {
      thinkBox.hidden = false;
      const stick = stickToBottom(thBody);
      thBody.textContent += pendingThinking;
      pendingThinking = "";
      if (stick) thBody.scrollTop = thBody.scrollHeight;
    }
    if (deltaDirty) {
      ansEl.innerHTML = formatAnswer(fullAnswer) + `<span class="cursor">▍</span>`;
      deltaDirty = false;
      if (stickToBottom(box)) box.scrollTop = box.scrollHeight;
    }
  };
  const schedule = () => {
    if (!rafId) rafId = requestAnimationFrame(flush);
  };

  let gotDone = false;
  try {
    await sseAsk(question, S.kbId, S.sessionId, {
      onNode: (d) => {
        nodeEl.innerHTML = `<span>${NODE_CN[d.node] || d.node}</span>`;
      },
      onSources: (d) => {
        citeWrap.innerHTML = renderSources(d.sources || []);
        if (stickToBottom(box)) box.scrollTop = box.scrollHeight;
      },
      onThinking: (d) => {
        pendingThinking += d.text;
        schedule();
      },
      onDelta: (d) => {
        fullAnswer += d.text;
        deltaDirty = true;
        schedule();
      },
      onDone: (d) => {
        gotDone = true;
        if (rafId) {
          cancelAnimationFrame(rafId);
          flush();
        }
        cursor?.remove();
        nodeEl.innerHTML = "";
        const badge =
          d.status === "answered"
            ? `<span class="badge ok">已回答</span>`
            : `<span class="badge warn">证据不足</span>`;
        const conf =
          d.confidence != null
            ? `<span class="badge">confidence ${Number(d.confidence).toFixed(2)}</span>`
            : "";
        root.querySelector(".role").innerHTML = `助手 ${conf}${badge}`;
        fbRow.classList.remove("hidden");
        fbRow.dataset.msg = d.message_id;
        fbRow.innerHTML = `
          <button class="fb-up">👍</button>
          <button class="fb-down">👎</button>
          <span class="fb-tip" style="font-size:12px;color:#94a3b8"></span>`;
        bindFeedback(root);
        loadSessions()
          .then(renderSessionList)
          .catch(() => {});
      },
      onError: (d) => {
        ansEl.innerHTML = `<span class="error-text">⚠️ ${esc(d.message)}</span>`;
        cursor?.remove();
        toast(d.message, "error");
      },
    });
    // 流结束兜底：冲刷残留帧并去掉光标（无 done 时保留已生成内容）
    if (rafId) {
      cancelAnimationFrame(rafId);
      flush();
    }
    root.querySelector(".cursor")?.remove();
    void gotDone;
  } catch (e) {
    ansEl.innerHTML = `<span class="error-text">⚠️ ${esc(e.message)}</span>`;
    root.querySelector(".cursor")?.remove();
    toast(e.message, "error");
  } finally {
    S.streaming = false;
    document.getElementById("send-btn").disabled = false;
    box.scrollTop = box.scrollHeight;
  }
}

/* ---------- 文本格式化（先转义，再轻量 Markdown） ---------- */
function formatAnswer(text) {
  let html = esc(text);
  const codes = [];
  html = html.replace(/```([\s\S]*?)```/g, (_, c) => {
    codes.push(c.trim());
    return `\u0000CODE${codes.length - 1}\u0000`;
  });
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // 依据引用：[文件名.ext] 或 [文件名.ext #3] → 醒目徽章
  html = html.replace(
    /\[([^\[\]]+?\.(?:md|txt|pdf|docx))(?:\s*#\s*(\d+))?\]/gi,
    (_, file, n) =>
      `<span class="cite-ref" title="回答依据来源">📎 ${file}${n ? ` #${n}` : ""}</span>`
  );
  html = html.replace(/\n/g, "<br>");
  html = html.replace(/\u0000CODE(\d+)\u0000/g, (_, i) => `<pre>${codes[Number(i)]}</pre>`);
  return html;
}
