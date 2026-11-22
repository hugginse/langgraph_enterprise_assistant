// 手写 hash 路由：未登录跳 login；非 admin 访问 #/admin/* 弹回 #/chat
import { getToken, getUser, clearAuth } from "./api.js";

const routes = {}; // '#/path' -> async (params) => void
let guard = null; // (path) => redirect path | null

export function route(path, handler) {
  routes[path] = handler;
}

export function setGuard(fn) {
  guard = fn;
}

export function navigate(path) {
  if (location.hash === path) {
    dispatch();
  } else {
    location.hash = path;
  }
}

export function currentPath() {
  const h = location.hash || "#/chat";
  return h.split("?")[0];
}

export function queryParams() {
  const h = location.hash || "";
  const q = h.split("?")[1] || "";
  return Object.fromEntries(new URLSearchParams(q));
}

async function dispatch() {
  let path = currentPath();

  // 未登录一律去 login
  if (!getToken() && path !== "#/login") {
    location.hash = "#/login";
    return;
  }
  if (getToken() && path === "#/login") {
    location.hash = "#/chat";
    return;
  }

  // 非 admin 禁入 admin 路由
  if (guard) {
    const redirect = guard(path);
    if (redirect) {
      location.hash = redirect;
      return;
    }
  }

  const handler = routes[path];
  const view = document.getElementById("view");
  if (!handler) {
    view.innerHTML = `<div class="empty-hint"><h2>404</h2><p>页面不存在：<code>${path}</code></p></div>`;
    return;
  }
  // 侧栏高亮
  document.querySelectorAll(".sidebar .nav a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === path);
  });
  try {
    await handler(queryParams());
  } catch (err) {
    console.error(err);
  }
}

export function startRouter() {
  window.addEventListener("hashchange", dispatch);
  dispatch();
}

export function refreshSidebarAuth() {
  const user = getUser();
  const who = document.querySelector(".sidebar .who");
  if (who && user) {
    who.innerHTML = `当前用户：<b>${user.username}</b>（${user.role === "admin" ? "管理员" : "普通用户"}）
      <br><a href="#" id="logout-link" style="color:#93c5fd">退出登录</a>`;
    document.getElementById("logout-link")?.addEventListener("click", (e) => {
      e.preventDefault();
      clearAuth();
      navigate("#/login");
    });
  }
}
