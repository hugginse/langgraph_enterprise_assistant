"""交付截图脚本（本地运行，不进 CI）：用本机 Edge 截取 4 张真实界面图。

用法：uv run --with playwright python scripts/take_screenshots.py
（有头模式：窗口会短暂出现在桌面上——本机 headless 截帧不可靠）
前置：uvicorn app.main:app 已在 127.0.0.1:8000 运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8000"
VIEWPORT = {"width": 1440, "height": 900}


def login(page, username: str, password: str) -> None:
    page.goto(f"{BASE}/#/login")
    page.wait_for_selector("#username")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")
    page.wait_for_timeout(800)


def shot(page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    page.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
    page.wait_for_timeout(250)
    page.screenshot(path=str(path))
    print(f"saved {path}")


def main() -> int:
    with sync_playwright() as p:
        # 本机 headless Edge 存在过期合成帧问题，必须有头模式
        browser = p.chromium.launch(channel="msedge", headless=False)
        ctx = browser.new_context(viewport=VIEWPORT, locale="zh-CN")
        page = ctx.new_page()

        # 1) 登录页
        page.goto(f"{BASE}/#/login")
        page.wait_for_selector(".login-card")
        page.wait_for_timeout(300)
        shot(page, "login.png")

        # 2) 管理看板（admin 登录后默认路由）
        login(page, "admin", "admin123")
        page.wait_for_selector(".cards .card", timeout=10000)
        page.wait_for_timeout(600)  # 等 SVG 图渲染
        shot(page, "admin_dashboard.png")

        # 3) 文档管理
        page.goto(f"{BASE}/#/admin/docs")
        page.wait_for_selector("#doc-table table, #doc-table .empty-hint", timeout=10000)
        page.wait_for_timeout(500)
        shot(page, "admin_docs.png")

        # 4) 对话页：user 提问并等待流式完成（整页重载清除 admin 会话）
        page.evaluate("localStorage.clear()")
        page.goto(BASE)
        login(page, "user", "user123")
        page.wait_for_selector("#question", timeout=10000)
        page.wait_for_timeout(600)
        page.fill("#question", "年休假天数是怎么规定的？")
        page.click("#send-btn")
        # 等最后一条助手消息完成（fb-row 取消 hidden）
        page.wait_for_function(
            """() => {
              const rows = document.querySelectorAll('.msg.assistant .fb-row');
              return rows.length > 0 && !rows[rows.length - 1].classList.contains('hidden');
            }""",
            timeout=90000,
        )
        page.wait_for_timeout(400)
        shot(page, "chat.png")

        browser.close()
    print("all screenshots done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
