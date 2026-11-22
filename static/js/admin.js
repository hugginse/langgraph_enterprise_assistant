// 管理看板：统计卡 + 手写 SVG 七日柱状图（无图表库）
import { api, toast } from "./api.js";

export async function renderAdmin() {
  const view = document.getElementById("view");
  view.innerHTML = `
    <div class="topbar"><h1>数据看板</h1></div>
    <div class="page">
      <div class="cards" id="stat-cards"></div>
      <div class="chart-wrap">
        <h3>近 7 天消息量</h3>
        <div id="chart"></div>
      </div>
    </div>`;

  try {
    const d = await api("/api/stats/dashboard");
    document.getElementById("stat-cards").innerHTML = [
      ["用户数", d.users],
      ["知识库", d.kbs],
      ["文档数", d.documents],
      ["消息数", d.messages],
    ]
      .map(
        ([lbl, num]) => `<div class="card"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`
      )
      .join("");
    document.getElementById("chart").innerHTML = renderBarChart(d.trend || []);
  } catch (e) {
    toast(e.message, "error");
  }
}

/** 手写 SVG 柱状图 */
export function renderBarChart(trend) {
  const W = 640;
  const H = 240;
  const padL = 36;
  const padR = 12;
  const padT = 14;
  const padB = 34;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const max = Math.max(1, ...trend.map((t) => t.count));
  const n = Math.max(trend.length, 1);
  const slot = innerW / n;
  const barW = Math.min(slot * 0.55, 46);

  const niceMax = max <= 5 ? 5 : Math.ceil(max / 5) * 5;
  const ticks = 5;

  let grid = "";
  for (let i = 0; i <= ticks; i++) {
    const v = Math.round((niceMax / ticks) * i);
    const y = padT + innerH - (v / niceMax) * innerH;
    grid += `<line class="gridline" x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}"/>
      <text x="${padL - 6}" y="${y + 3}" text-anchor="end">${v}</text>`;
  }

  let bars = "";
  trend.forEach((t, i) => {
    const h = (t.count / niceMax) * innerH;
    const x = padL + slot * i + (slot - barW) / 2;
    const y = padT + innerH - h;
    const label = (t.date || "").slice(5); // MM-DD
    bars += `
      <rect class="bar" x="${x}" y="${y}" width="${barW}" height="${h}" rx="4">
        <title>${t.date}: ${t.count}</title>
      </rect>
      <text x="${x + barW / 2}" y="${padT + innerH + 16}" text-anchor="middle">${label}</text>
      ${t.count > 0 ? `<text x="${x + barW / 2}" y="${y - 4}" text-anchor="middle" fill="#2563eb">${t.count}</text>` : ""}`;
  });

  return `
    <svg class="bar-chart" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="近7天消息趋势">
      ${grid}
      <line x1="${padL}" y1="${padT + innerH}" x2="${W - padR}" y2="${padT + innerH}" stroke="#cbd5e1"/>
      ${bars}
    </svg>`;
}
