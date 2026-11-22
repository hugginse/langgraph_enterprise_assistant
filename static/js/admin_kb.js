// 管理端知识库与成员管理：CRUD + 成员授权 + reindex + 删除二次确认
import { api, toast } from "./api.js";

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const S = { kbs: [], current: null, members: [], users: [] };

export async function renderAdminKb() {
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="topbar"><h1>知识库管理</h1></div>
    <div class="page" style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">
      <div style="flex:2;min-width:340px">
        <div class="toolbar">
          <button id="kb-new">＋ 新建知识库</button>
        </div>
        <div id="kb-table"></div>
      </div>
      <div style="flex:1;min-width:300px">
        <div class="card" id="kb-detail"><p style="color:#6b7688">← 选择一个知识库查看成员</p></div>
      </div>
    </div>`;

  document.getElementById("kb-new").addEventListener("click", createKb);
  await load();
}

async function load() {
  try {
    S.kbs = await api("/api/knowledge-bases");
    renderTable();
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderTable() {
  document.getElementById("kb-table").innerHTML = `
    <table class="grid">
      <thead><tr><th>ID</th><th>名称</th><th>描述</th><th style="width:230px">操作</th></tr></thead>
      <tbody>
        ${S.kbs
          .map(
            (k) => `<tr>
            <td>${k.id}</td>
            <td><a href="#" class="kb-open" data-id="${k.id}">${esc(k.name)}</a></td>
            <td>${esc((k.description || "").slice(0, 40))}</td>
            <td>
              <button class="sm ghost kb-ren" data-id="${k.id}">重命名</button>
              <button class="sm ghost kb-reindex" data-id="${k.id}" title="重建向量索引">reindex</button>
              <button class="sm danger kb-del" data-id="${k.id}">删除</button>
            </td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;

  document.querySelectorAll(".kb-open").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      openKb(Number(a.dataset.id));
    })
  );
  document.querySelectorAll(".kb-ren").forEach((b) =>
    b.addEventListener("click", () => renameKb(Number(b.dataset.id)))
  );
  document.querySelectorAll(".kb-reindex").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = Number(b.dataset.id);
      if (!confirm("重建该库全部向量？（更换 Embed 模型后必须执行）")) return;
      try {
        await api(`/api/knowledge-bases/${id}/reindex`, { method: "POST" });
        toast("reindex 已排队执行", "ok");
      } catch (e) {
        toast(e.message, "error");
      }
    })
  );
  document.querySelectorAll(".kb-del").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = Number(b.dataset.id);
      const k = S.kbs.find((x) => x.id === id);
      const sure = confirm(
        `⚠️ 删除「${k?.name}」将级联物理删除：\n· 全部文档记录与上传文件\n· 向量索引（Chroma）\n· 全部会话、消息与 checkpoint\n\n确认删除？`
      );
      if (!sure) return;
      try {
        await api(`/api/knowledge-bases/${id}`, { method: "DELETE" });
        toast("已删除", "ok");
        if (S.current === id) S.current = null;
        await load();
        document.getElementById("kb-detail").innerHTML =
          `<p style="color:#6b7688">← 选择一个知识库查看成员</p>`;
      } catch (e) {
        toast(e.message, "error");
      }
    })
  );
}

async function createKb() {
  const name = prompt("知识库名称：");
  if (!name) return;
  const description = prompt("描述（可空）：") || "";
  try {
    await api("/api/knowledge-bases", { method: "POST", body: { name, description } });
    toast("已创建", "ok");
    await load();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function renameKb(id) {
  const k = S.kbs.find((x) => x.id === id);
  const name = prompt("新名称：", k.name);
  if (!name) return;
  try {
    await api(`/api/knowledge-bases/${id}`, { method: "PUT", body: { name } });
    await load();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function openKb(id) {
  S.current = id;
  const host = document.getElementById("kb-detail");
  host.innerHTML = `<p style="color:#6b7688">加载成员…</p>`;
  try {
    S.members = await api(`/api/knowledge-bases/${id}/members`);
    if (!S.users.length) {
      S.users = (await api("/api/users?page_size=100")).items;
    }
    renderDetail();
  } catch (e) {
    toast(e.message, "error");
    host.innerHTML = `<p style="color:#dc2626">${esc(e.message)}</p>`;
  }
}

function renderDetail() {
  const host = document.getElementById("kb-detail");
  const k = S.kbs.find((x) => x.id === S.current);
  const memberIds = new Set(S.members.map((m) => m.user_id));
  const candidates = S.users.filter((u) => !memberIds.has(u.id));
  host.innerHTML = `
    <h3 style="margin-top:0">成员 · ${esc(k?.name || "")}</h3>
    <div class="toolbar">
      <select id="add-user" style="flex:1">
        ${candidates.map((u) => `<option value="${u.id}">${esc(u.username)}</option>`).join("") || `<option value="">无可用用户</option>`}
      </select>
      <button id="add-member" class="sm">授权</button>
    </div>
    <table class="grid">
      <thead><tr><th>用户名</th><th>昵称</th><th style="width:70px"></th></tr></thead>
      <tbody>
        ${S.members
          .map(
            (m) => `<tr>
              <td>${esc(m.username)}</td>
              <td>${esc(m.nickname || "")}</td>
              <td><button class="sm danger rm" data-uid="${m.user_id}">移除</button></td>
            </tr>`
          )
          .join("") || `<tr><td colspan="3" style="color:#94a3b8">暂无成员</td></tr>`}
      </tbody>
    </table>`;

  document.getElementById("add-member")?.addEventListener("click", async () => {
    const uid = document.getElementById("add-user").value;
    if (!uid) return;
    try {
      await api(`/api/knowledge-bases/${S.current}/members`, {
        method: "POST",
        body: { user_id: Number(uid) },
      });
      toast("已授权", "ok");
      await openKb(S.current);
    } catch (e) {
      toast(e.message, "error");
    }
  });
  host.querySelectorAll(".rm").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api(`/api/knowledge-bases/${S.current}/members/${b.dataset.uid}`, {
          method: "DELETE",
        });
        toast("已移除", "ok");
        await openKb(S.current);
      } catch (e) {
        toast(e.message, "error");
      }
    })
  );
}
