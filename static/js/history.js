// 对话历史页：分页；admin 可按用户过滤
import { api, toast } from "./api.js";

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const S = { page: 1, pageSize: 20, total: 0, userId: "", users: [] };

export async function renderHistory() {
  const user = JSON.parse(localStorage.getItem("lga_user") || "{}");
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="topbar"><h1>对话历史</h1></div>
    <div class="page">
      <div class="toolbar">
        ${user.role === "admin" ? `<select id="user-filter"><option value="">全部用户</option></select>` : ""}
        <span class="grow"></span>
        <button id="refresh" class="ghost">刷新</button>
      </div>
      <div id="hist-table"></div>
      <div class="pager">
        <button id="prev" class="ghost">上一页</button>
        <span class="info" id="pager-info"></span>
        <button id="next" class="ghost">下一页</button>
      </div>
    </div>`;

  if (user.role === "admin") {
    try {
      S.users = (await api("/api/users?page_size=100")).items;
      const sel = document.getElementById("user-filter");
      sel.innerHTML =
        `<option value="">全部用户</option>` +
        S.users.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("");
      sel.addEventListener("change", () => {
        S.userId = sel.value;
        S.page = 1;
        load();
      });
    } catch (e) {
      toast(e.message, "error");
    }
  }

  document.getElementById("refresh").addEventListener("click", load);
  document.getElementById("prev").addEventListener("click", () => {
    if (S.page > 1) {
      S.page--;
      load();
    }
  });
  document.getElementById("next").addEventListener("click", () => {
    if (S.page * S.pageSize < S.total) {
      S.page++;
      load();
    }
  });
  await load();
}

async function load() {
  try {
    const qs = new URLSearchParams({ page: S.page, page_size: S.pageSize });
    if (S.userId) qs.set("user_id", S.userId);
    const data = await api(`/api/chat/history?${qs}`);
    S.total = data.total;
    const host = document.getElementById("hist-table");
    if (!data.items.length) {
      host.innerHTML = `<div class="empty-hint"><p>暂无历史消息</p></div>`;
    } else {
      host.innerHTML = `
        <table class="grid">
          <thead><tr><th style="width:70px">ID</th><th>问题</th><th>回答</th><th style="width:90px">状态</th><th style="width:150px">时间</th></tr></thead>
          <tbody>
            ${data.items
              .map(
                (m) => `<tr>
                  <td>${m.id}</td>
                  <td>${esc(m.question)}</td>
                  <td>${esc((m.answer || "").slice(0, 80))}${(m.answer || "").length > 80 ? "…" : ""}</td>
                  <td>${m.status === "answered" ? "✅ 已答" : "⚠️ 证据不足"}</td>
                  <td>${(m.created_at || "").replace("T", " ").slice(0, 19)}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>`;
    }
    document.getElementById("pager-info").textContent =
      `第 ${S.page} 页 · 共 ${S.total} 条`;
    document.getElementById("prev").disabled = S.page <= 1;
    document.getElementById("next").disabled = S.page * S.pageSize >= S.total;
  } catch (e) {
    toast(e.message, "error");
  }
}
