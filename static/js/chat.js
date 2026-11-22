// 对话页（核心）：会话栏 CRUD、kb 选择、SSE 流式、引用卡、思考框、node 进度、feedback
import { api, sseAsk, toast } from "./api.js";
import { navigate } from "./router.js";

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
    S.sessionId = S.sessions[0].id;
  }
  renderSessionList();
  if (S.sessionId) await loadMessages(S.sessionId);
  else showEmpty();
}

function showEmpty() {
  document.getElementById("chat-msgs").innerHTML = `
    <div class="empty-hint">
      <h2>开始提问</h2>
      <p>选择知识库后输入问题，回答将带引用与思考过程实时流出。</p>
    </div>`;
}

async function loadKbs() {
  S.kbs = await api("/api/knowledge-bases");
  if (!S.kbId && S.kbs.length) S.kbId = S.kbs[0].id;
  for (const id of ["kb-select", "kb-select-2"]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.innerHTML = S.kbs
      .map((k) => `<option value="${k.id}" ${k.id === S.kbId ? "selected" : ""}>${esc(k.name)}</option>`)
      .join("");
  }
}

async function loadSessions() {
  S.sessions = await api("/api/chat/sessions");
}

function renderSessionList() {
  const el = document.getElementById("session-list");
  if (!el) return;
  if (!S.sessions.length) {
    el.innerHTML = `<div style="padding:16px;color:#94a3b8;font-size:13px">暂无会话，点右上 ＋ 新建</div>`;
    return;
  }
  el.innerHTML = S.sessions
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
      } catch (err) {
        toast(err.message, "error");
      }
    });
    item.querySelector(".del").addEventListener("click", async () => {
      if (!confirm("删除该会话及其全部消息？")) return;
      try {
        await api(`/api/chat/sessions/${id}`, { method: "DELETE" });
        S.sessions = S.sessions.filter((x) => x.id !== id);
        if (S.sessionId === id) {
          S.sessionId = S.sessions[0]?.id || null;
          if (S.sessionId) await loadMessages(S.sessionId);
          else showEmpty();
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
  for (const id of ["kb-select", "kb-select-2"]) {
    document.getElementById(id)?.addEventListener("change", (e) => {
      S.kbId = Number(e.target.value);
      for (const other of ["kb-select", "kb-select-2"]) {
        const el = document.getElementById(other);
        if (el) el.value = String(S.kbId);
      }
    });
  }
  document.getElementById("new-session")?.addEventListener("click", async () => {
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
  const cites = (m.sources || [])
    .map(
      (c) => `
    <div class="cite-card">
      <div class="fname">${esc(c.file_name)}</div>
      <div class="meta">#${c.chunk_index} · score ${Number(c.score).toFixed(3)}</div>
      <div class="snip">${esc(c.snippet || "")}</div>
    </div>`
    )
    .join("");
  return `
    <div class="msg user"><div class="role">我</div><div class="bubble">${esc(m.question)}</div></div>
    <div class="msg assistant">
      <div class="role">助手
        ${m.confidence != null ? `<span class="badge ${m.status === "answered" ? "ok" : "warn"}">confidence ${Number(m.confidence).toFixed(2)}</span>` : ""}
        <span class="badge">${m.status === "answered" ? "已回答" : "证据不足"}</span>
      </div>
      <div class="bubble">${esc(m.answer)}
        ${cites ? `<div class="cite-cards">${cites}</div>` : ""}
      </div>
      <div class="fb-row" data-msg="${m.id}">
        <button class="fb-up" title="有用">👍</button>
        <button class="fb-down" title="没用">👎</button>
        <span class="fb-tip" style="font-size:12px;color:#94a3b8"></span>
      </div>
    </div>`;
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
  S.streaming = true;
  document.getElementById("send-btn").disabled = true;

  const box = document.getElementById("chat-msgs");
  if (box.querySelector(".empty-hint")) box.innerHTML = "";

  // 用户消息
  box.insertAdjacentHTML(
    "beforeend",
    `<div class="msg user"><div class="role">我</div><div class="bubble">${esc(question)}</div></div>`
  );

  // 助手骨架
  const aid = `a-${Date.now()}`;
  box.insertAdjacentHTML(
    "beforeend",
    `<div class="msg assistant" id="${aid}">
      <div class="role">助手</div>
      <div class="node-progress"></div>
      <div class="thinking-box hidden">
        <div class="th-head"><span>🤔 思考过程</span><span class="th-toggle">收起 ▲</span></div>
        <div class="th-body"></div>
      </div>
      <div class="bubble"><span class="answer-text"></span><span class="caret">▍</span>
        <div class="cite-cards"></div>
      </div>
      <div class="fb-row hidden"></div>
    </div>`
  );
  const root = document.getElementById(aid);
  const nodeEl = root.querySelector(".node-progress");
  const thBox = root.querySelector(".thinking-box");
  const thBody = root.querySelector(".th-body");
  const ansEl = root.querySelector(".answer-text");
  const caret = root.querySelector(".caret");
  const citeWrap = root.querySelector(".cite-cards");
  const fbRow = root.querySelector(".fb-row");

  root.querySelector(".th-head").addEventListener("click", () => {
    thBox.classList.toggle("collapsed");
    root.querySelector(".th-toggle").textContent = thBox.classList.contains("collapsed")
      ? "展开 ▼"
      : "收起 ▲";
  });

  // rAF 批量刷新打字机
  let pending = [];
  let rafId = 0;
  const flush = () => {
    rafId = 0;
    if (pending.length) {
      ansEl.textContent += pending.join("");
      pending = [];
      box.scrollTop = box.scrollHeight;
    }
  };
  const pushDelta = (t) => {
    pending.push(t);
    if (!rafId) rafId = requestAnimationFrame(flush);
  };

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

  try {
    await sseAsk(question, S.kbId, S.sessionId, {
      onNode: (d) => {
        nodeEl.innerHTML = `<span>${NODE_CN[d.node] || d.node}</span>`;
      },
      onSources: (d) => {
        const chunks = d.sources || [];
        if (!chunks.length) {
          citeWrap.innerHTML = `<div class="cite-card"><div class="fname">未检索到相关内容</div></div>`;
        } else {
          citeWrap.innerHTML = chunks
            .map(
              (c) => `
            <div class="cite-card">
              <div class="fname">${esc(c.file_name)}</div>
              <div class="meta">#${c.chunk_index} · score ${Number(c.score).toFixed(3)}</div>
              <div class="snip">${esc(c.snippet || "")}</div>
            </div>`
            )
            .join("");
        }
        box.scrollTop = box.scrollHeight;
      },
      onThinking: (d) => {
        thBox.classList.remove("hidden");
        thBody.textContent += d.text;
        box.scrollTop = box.scrollHeight;
      },
      onDelta: (d) => pushDelta(d.text),
      onDone: (d) => {
        if (rafId) cancelAnimationFrame(rafId), flush();
        caret.remove();
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
        if (!S.sessionId) {
          S.sessionId = d.session_id;
          loadSessions().then(renderSessionList);
        }
        // 更新会话列表标题
        const cur = S.sessions.find((x) => x.id === (S.sessionId || d.session_id));
        if (cur && !cur.title) {
          cur.title = question.slice(0, 20);
          renderSessionList();
        }
      },
      onError: (d) => {
        ansEl.textContent += `\n⚠️ ${d.message}`;
        caret.remove();
        toast(d.message, "error");
      },
    });
  } catch (e) {
    ansEl.textContent += ansEl.textContent ? "" : `⚠️ ${e.message}`;
    if (!ansEl.textContent) ansEl.textContent = `⚠️ ${e.message}`;
    caret.remove();
    toast(e.message, "error");
  } finally {
    S.streaming = false;
    document.getElementById("send-btn").disabled = false;
    box.scrollTop = box.scrollHeight;
  }
}
