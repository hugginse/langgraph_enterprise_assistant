// 登录页
import { api, toast } from "./api.js";

export async function renderLogin() {
  const view = document.getElementById("view");
  document.getElementById("sidebar").classList.add("hidden");
  view.innerHTML = `
    <div class="login-wrap">
      <div class="login-card">
        <h1>企业知识库问答</h1>
        <p class="sub">LangGraph Adaptive RAG · 请登录后继续</p>
        <label>用户名</label>
        <input id="username" autocomplete="username" placeholder="admin / user">
        <label>密码</label>
        <input id="password" type="password" autocomplete="current-password" placeholder="••••••">
        <div class="login-err" id="login-err"></div>
        <button id="login-btn">登 录</button>
      </div>
    </div>`;

  const doLogin = async () => {
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const errEl = document.getElementById("login-err");
    errEl.textContent = "";
    if (!username || !password) {
      errEl.textContent = "请输入用户名和密码";
      return;
    }
    const btn = document.getElementById("login-btn");
    btn.disabled = true;
    btn.textContent = "登录中…";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: { username, password },
      });
      toast(`欢迎，${data.user.nickname || data.user.username}`, "ok");
      window.__onLogin(data.token, data.user);
    } catch (e) {
      errEl.textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "登 录";
    }
  };

  document.getElementById("login-btn").addEventListener("click", doLogin);
  document.getElementById("password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
}
