// 管理端文档：上传（类型白名单）、列表、2s 轮询状态、failed 显示 error_msg 可重传
import { api, toast } from "./api.js";

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const STATUS_CN = {
  pending: "待处理",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};

const S = { kbs: [], kbId: null, timer: 0 };

export async function renderAdminDocs() {
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="topbar"><h1>文档管理</h1></div>
    <div class="page">
      <div class="toolbar">
        <select id="kb-select"></select>
        <input type="file" id="file-input" accept=".txt,.md,.pdf,.docx" multiple>
        <button id="upload-btn">上传</button>
        <span class="grow"></span>
        <span style="color:#6b7688;font-size:12px">支持 txt / md / pdf / docx，单文件 ≤50MB；每 2 秒自动刷新状态</span>
      </div>
      <div id="doc-table"></div>
    </div>`;

  try {
    S.kbs = await api("/api/knowledge-bases");
    const sel = document.getElementById("kb-select");
    if (!S.kbs.length) {
      sel.innerHTML = `<option value="">暂无知识库</option>`;
    } else {
      S.kbId = S.kbId || S.kbs[0].id;
      sel.innerHTML = S.kbs
        .map((k) => `<option value="${k.id}" ${k.id === S.kbId ? "selected" : ""}>${esc(k.name)}</option>`)
        .join("");
      sel.addEventListener("change", () => {
        S.kbId = Number(sel.value);
        loadDocs();
      });
    }
  } catch (e) {
    toast(e.message, "error");
  }

  document.getElementById("upload-btn").addEventListener("click", upload);
  await loadDocs();
  clearInterval(S.timer);
  S.timer = setInterval(loadDocs, 2000);
}

// 路由离开时清理轮询
window.addEventListener("hashchange", () => {
  if (!location.hash.startsWith("#/admin/docs")) clearInterval(S.timer);
});

async function loadDocs() {
  if (!S.kbId) return;
  try {
    const docs = await api(`/api/knowledge-bases/${S.kbId}/documents`);
    const host = document.getElementById("doc-table");
    if (!host) return clearInterval(S.timer);
    if (!docs.length) {
      host.innerHTML = `<div class="empty-hint"><p>该知识库暂无文档</p></div>`;
      return;
    }
    host.innerHTML = `
      <table class="grid">
        <thead><tr>
          <th>ID</th><th>文件名</th><th>类型</th><th>大小</th>
          <th>状态</th><th>分块数</th><th style="width:80px">操作</th>
        </tr></thead>
        <tbody>
          ${docs
            .map(
              (d) => `<tr>
              <td>${d.id}</td>
              <td>${esc(d.filename)}</td>
              <td>${esc(d.file_type)}</td>
              <td>${fmtSize(d.file_size)}</td>
              <td>
                <span class="status-pill status-${d.status}">${STATUS_CN[d.status] || d.status}</span>
                ${d.error_msg ? `<div class="err-msg">${esc(d.error_msg)}</div>` : ""}
              </td>
              <td>${d.chunk_count}</td>
              <td>
                ${d.status === "failed" ? `<button class="sm ghost retry" data-id="${d.id}">重传</button>` : ""}
                <button class="sm danger del" data-id="${d.id}">删除</button>
              </td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;

    host.querySelectorAll(".del").forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("删除该文档（含向量分块与物理文件）？")) return;
        try {
          await api(`/api/documents/${b.dataset.id}`, { method: "DELETE" });
          toast("已删除", "ok");
          loadDocs();
        } catch (e) {
          toast(e.message, "error");
        }
      })
    );
    host.querySelectorAll(".retry").forEach((b) =>
      b.addEventListener("click", () => {
        toast("请重新选择该文件上传（失败文档请修正后重传）");
        document.getElementById("file-input").click();
      })
    );
  } catch (e) {
    /* 轮询期间容忍瞬时错误 */
  }
}

async function upload() {
  const input = document.getElementById("file-input");
  const files = input.files;
  if (!S.kbId) return toast("请先选择知识库", "error");
  if (!files.length) return toast("请选择文件", "error");
  const fd = new FormData();
  for (const f of files) fd.append("file", f);
  const btn = document.getElementById("upload-btn");
  btn.disabled = true;
  btn.textContent = "上传中…";
  try {
    await api(`/api/knowledge-bases/${S.kbId}/documents`, { method: "POST", body: fd });
    toast(`已上传 ${files.length} 个文件，向量化中…`, "ok");
    input.value = "";
    loadDocs();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "上传";
  }
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
