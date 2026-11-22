// 应用入口：侧栏、路由表与守卫
import { api, clearAuth, getToken, getUser, setAuth, toast } from "./api.js";
import { navigate, route, setGuard, startRouter } from "./router.js";
import { renderLogin } from "./login.js";
import { renderChat } from "./chat.js";
import { renderHistory } from "./history.js";
import { renderAdmin } from "./admin.js";
import { renderAdminKb } from "./admin_kb.js";
import { renderAdminDocs } from "./admin_docs.js";
import { renderAdminUsers } from "./admin_users.js";

function buildSidebar() {
  const user = getUser();
  const sb = document.getElementById("sidebar");
  if (!user) {
    sb.classList.add("hidden");
    return;
  }
  sb.classList.remove("hidden");
  const adminLinks =
    user.role === "admin"
      ? `<a href="#/admin">数据看板</a>
         <a href="#/admin/kb">知识库管理</a>
         <a href="#/admin/docs">文档管理</a>
         <a href="#/admin/users">用户管理</a>`
      : "";
  sb.innerHTML = `
    <div class="brand">📚 企业知识库问答</div>
    <nav class="nav">
      <a href="#/chat">智能问答</a>
      <a href="#/history">对话历史</a>
      ${adminLinks}
    </nav>
    <div class="spacer"></div>
    <div class="who"></div>`;
  const who = sb.querySelector(".who");
  who.innerHTML = `当前用户：<b>${user.username}</b>（${user.role === "admin" ? "管理员" : "普通用户"}）
    <br><a href="#" id="logout-link" style="color:#93c5fd">退出登录</a>`;
  document.getElementById("logout-link").addEventListener("click", (e) => {
    e.preventDefault();
    clearAuth();
    navigate("#/login");
  });
}

// 路由守卫（已在目标页时返回 null，避免原地重定向导致不渲染）
setGuard((path) => {
  const user = getUser();
  if (!user) return path === "#/login" ? null : "#/login";
  if (path.startsWith("#/admin") && user.role !== "admin") return "#/chat";
  return null;
});

route("#/login", renderLogin);
route("#/chat", renderChat);
route("#/history", renderHistory);
route("#/admin", renderAdmin);
route("#/admin/kb", renderAdminKb);
route("#/admin/docs", renderAdminDocs);
route("#/admin/users", renderAdminUsers);

// 登录成功回调（login.js 使用）
window.__onLogin = (token, user) => {
  setAuth(token, user);
  buildSidebar();
  navigate(user.role === "admin" ? "#/admin" : "#/chat");
};

window.addEventListener("hashchange", buildSidebar);

// 启动：带 token 时拉一次 /auth/me 校验有效性
(async function boot() {
  if (getToken()) {
    try {
      const me = await api("/api/auth/me");
      const u = getUser() || {};
      setAuth(getToken(), { ...u, ...me });
    } catch {
      /* 401 已在 api 内处理 */
    }
  }
  buildSidebar();
  if (!location.hash) location.hash = getToken() ? "#/chat" : "#/login";
  startRouter();
})();

export { toast };
