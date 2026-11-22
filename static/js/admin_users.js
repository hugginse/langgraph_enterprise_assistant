// 管理端用户管理：列表 / 创建 / 改密 / 禁用启用 / 角色
import { api, toast } from "./api.js";

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const S = { page: 1, pageSize: 20, total: 0 };

export async function renderAdminUsers() {
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="topbar"><h1>用户管理</h1></div>
    <div class="page">
      <div class="toolbar">
        <button id="user-new">＋ 新建用户</button>
        <span class="grow"></span>
      </div>
      <div id="user-table"></div>
      <div class="pager">
        <button id="prev" class="ghost">上一页</button>
        <span class="info" id="pager-info"></span>
        <button id="next" class="ghost">下一页</button>
      </div>
    </div>`;

  document.getElementById("user-new").addEventListener("click", createUser);
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
    const data = await api(`/api/users?page=${S.page}&page_size=${S.pageSize}`);
    S.total = data.total;
    const me = JSON.parse(localStorage.getItem("lga_user") || "{}");
    document.getElementById("user-table").innerHTML = `
      <table class="grid">
        <thead><tr><th>ID</th><th>用户名</th><th>昵称</th><th>角色</th><th>状态</th><th style="width:250px">操作</th></tr></thead>
        <tbody>
          ${data.items
            .map(
              (u) => `<tr>
              <td>${u.id}</td>
              <td>${esc(u.username)}</td>
              <td>${esc(u.nickname || "")}</td>
              <td>${u.role === "admin" ? "管理员" : "用户"}</td>
              <td>${u.status === 1 ? "✅ 启用" : "🚫 禁用"}</td>
              <td>
                <button class="sm ghost pw" data-id="${u.id}">改密</button>
                <button class="sm ghost role" data-id="${u.id}">${u.role === "admin" ? "降为用户" : "升为管理员"}</button>
                ${
                  u.id === me.id
                    ? ""
                    : u.status === 1
                      ? `<button class="sm danger dis" data-id="${u.id}">禁用</button>`
                      : `<button class="sm ghost en" data-id="${u.id}">启用</button>`
                }
              </td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;

    document.getElementById("pager-info").textContent = `第 ${S.page} 页 · 共 ${S.total} 条`;
    document.getElementById("prev").disabled = S.page <= 1;
    document.getElementById("next").disabled = S.page * S.pageSize >= S.total;

    document.querySelectorAll(".pw").forEach((b) =>
      b.addEventListener("click", () => resetPw(Number(b.dataset.id)))
    );
    document.querySelectorAll(".role").forEach((b) =>
      b.addEventListener("click", () => toggleRole(Number(b.dataset.id)))
    );
    document.querySelectorAll(".dis").forEach((b) =>
      b.addEventListener("click", () => setStatus(Number(b.dataset.id), 0))
    );
    document.querySelectorAll(".en").forEach((b) =>
      b.addEventListener("click", () => setStatus(Number(b.dataset.id), 1))
    );
  } catch (e) {
    toast(e.message, "error");
  }
}

async function createUser() {
  const username = prompt("用户名（≥3 字符）：");
  if (!username) return;
  const password = prompt("初始密码（≥6 位）：");
  if (!password) return;
  const role = prompt("角色 admin/user：", "user") || "user";
  try {
    await api("/api/users", {
      method: "POST",
      body: { username, password, role: role === "admin" ? "admin" : "user" },
    });
    toast("已创建", "ok");
    load();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function resetPw(id) {
  const password = prompt("新密码（≥6 位）：");
  if (!password) return;
  try {
    await api(`/api/users/${id}`, { method: "PUT", body: { password } });
    toast("密码已重置", "ok");
  } catch (e) {
    toast(e.message, "error");
  }
}

async function toggleRole(id) {
  try {
    const list = await api(`/api/users?page=1&page_size=100`);
    const u = list.items.find((x) => x.id === id);
    const role = u.role === "admin" ? "user" : "admin";
    await api(`/api/users/${id}`, { method: "PUT", body: { role } });
    toast("角色已更新", "ok");
    load();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function setStatus(id, status) {
  const action = status === 0 ? "禁用" : "启用";
  if (status === 0 && !confirm("禁用后该用户存量登录立即失效，确认？")) return;
  try {
    await api(`/api/users/${id}`, { method: "PUT", body: { status } });
    toast(`已${action}`, "ok");
    load();
  } catch (e) {
    toast(e.message, "error");
  }
}
