// fetch 封装（自动 token、401 跳登录、统一 toast）+ SSE 流解析器
const TOKEN_KEY = "lga_token";
const USER_KEY = "lga_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}
export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function toast(msg, type = "") {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = `toast ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 2600);
}

function on401() {
  clearAuth();
  location.hash = "#/login";
}

/** 统一 JSON 请求。非 2xx 抛 Error（含后端 detail）。 */
export async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body });
  if (res.status === 401) {
    on401();
    throw new Error("登录已失效");
  }
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

/**
 * SSE POST（fetch + ReadableStream）。
 * 读流前先检查 HTTP 状态：非 2xx 时按 JSON 错误抛出，不进入流解析。
 * handlers: { onNode, onSources, onThinking, onDelta, onDone, onError }
 */
export async function sseAsk(question, kbId, sessionId, handlers = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const body = { question, kb_id: kbId };
  if (sessionId) body.session_id = sessionId;

  const res = await fetch("/api/chat/ask", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    on401();
    throw new Error("登录已失效");
  }
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) detail = data.detail;
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  // 真流式：逐块读 body，增量解析 event/data 帧
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  const emit = (event, data) => {
    const map = {
      node: handlers.onNode,
      sources: handlers.onSources,
      thinking: handlers.onThinking,
      delta: handlers.onDelta,
      done: handlers.onDone,
      error: handlers.onError,
    };
    map[event]?.(data);
  };

  const parseBlock = (block) => {
    let event = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!event || !data) return;
    try {
      emit(event, JSON.parse(data));
    } catch (e) {
      console.error("SSE 解析失败", e, data);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (block.trim()) parseBlock(block);
    }
  }
  if (buf.trim()) parseBlock(buf);
}
