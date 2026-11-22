"""RAG 检索评估：15 条 golden（seed_docs 三主题）→ eval_report.md。

指标：Hit@1 / Hit@4 / MRR / 平均检索延迟；**Hit@4 ≥ 0.8** 为 Gate-M3 阈值。
本地连 Ollama 向量化检索，不进 CI。用法：uv run python scripts/eval_rag.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import KnowledgeBase  # noqa: E402
from app.services.vector import search  # noqa: E402

# 15 条 golden：问题 → 期望命中的知识库与文件（seed_docs 三主题）
GOLDEN: list[dict] = [
    # 公司规章制度
    {
        "question": "员工请假需要提前几天申请？",
        "kb": "公司规章制度",
        "file": "员工请假管理办法.md",
    },
    {
        "question": "年休假天数是怎么规定的？",
        "kb": "公司规章制度",
        "file": "员工请假管理办法.md",
    },
    {
        "question": "公司考勤管理有什么要求？",
        "kb": "公司规章制度",
        "file": "公司考勤管理制度.txt",
    },
    {
        "question": "薪酬福利制度包含哪些内容？",
        "kb": "公司规章制度",
        "file": "公司薪酬福利制度.pdf",
    },
    {
        "question": "员工行为规范有哪些准则？",
        "kb": "公司规章制度",
        "file": "员工行为规范手册.docx",
    },
    # 技术开发规范
    {
        "question": "API 的 URL 设计规范是什么？",
        "kb": "技术开发规范",
        "file": "API接口设计规范.md",
    },
    {
        "question": "Git 分支与版本管理如何规范？",
        "kb": "技术开发规范",
        "file": "Git版本管理规范.docx",
    },
    {
        "question": "Python 编码有哪些风格规范？",
        "kb": "技术开发规范",
        "file": "Python开发编码规范.txt",
    },
    {
        "question": "数据库设计需要遵循什么规范？",
        "kb": "技术开发规范",
        "file": "数据库设计规范.pdf",
    },
    {
        "question": "接口版本号应该怎么命名？",
        "kb": "技术开发规范",
        "file": "API接口设计规范.md",
    },
    # 产品使用指南
    {
        "question": "如何配置企业邮箱客户端？",
        "kb": "产品使用指南",
        "file": "企业邮箱配置说明.pdf",
    },
    {
        "question": "OA 系统有哪些功能、怎么使用？",
        "kb": "产品使用指南",
        "file": "企业OA系统使用手册.txt",
    },
    {
        "question": "新员工入职需要办理什么手续？",
        "kb": "产品使用指南",
        "file": "新员工入职指南.docx",
    },
    {
        "question": "项目管理平台如何立项和操作？",
        "kb": "产品使用指南",
        "file": "项目管理平台操作指南.md",
    },
    {
        "question": "企业邮箱和内部沟通工具有哪些？",
        "kb": "产品使用指南",
        "file": "企业邮箱配置说明.pdf",
    },
]

TOP_K = 4
HIT4_THRESHOLD = 0.8


def main() -> int:
    db = SessionLocal()
    try:
        kb_by_name = {
            kb.name: kb.id for kb in db.scalars(select(KnowledgeBase)).all()
        }
        rows: list[dict] = []
        latencies: list[float] = []
        hit1 = hit4 = rr_sum = 0

        for item in GOLDEN:
            kb_id = kb_by_name.get(item["kb"])
            if kb_id is None:
                print(f"[missing kb] {item['kb']}")
                rows.append({**item, "rank": None, "latency_ms": 0.0, "top": []})
                continue
            t0 = time.perf_counter()
            results = search(item["question"], kb_id=kb_id, top_k=TOP_K, db=db)
            elapsed = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed)
            top_files = [r["file_name"] for r in results]
            rank = None
            if item["file"] in top_files:
                rank = top_files.index(item["file"]) + 1
                rr_sum += 1.0 / rank
                if rank == 1:
                    hit1 += 1
                if rank <= TOP_K:
                    hit4 += 1
            rows.append(
                {**item, "rank": rank, "latency_ms": round(elapsed, 1), "top": top_files}
            )
            mark = "OK " if rank else "MISS"
            print(f"[{mark}] #{len(rows):02d} rank={rank} {item['question'][:30]}")

        n = len(GOLDEN)
        m_hit1 = hit1 / n
        m_hit4 = hit4 / n
        m_rr = rr_sum / n
        m_lat = sum(latencies) / len(latencies) if latencies else 0.0

        report = [
            "# RAG 检索评估报告",
            "",
            "> 由 `scripts/eval_rag.py` 自动生成；本地 Ollama `qwen3-embedding:4b`，top_k=4。",
            "",
            "## 总体指标",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| Hit@1 | {m_hit1:.4f} |",
            f"| Hit@4 | {m_hit4:.4f} |",
            f"| MRR | {m_rr:.4f} |",
            f"| 平均检索延迟 | {m_lat:.1f} ms |",
            f"| 样本数 | {n} |",
            (
                f"| Hit@4 阈值 | ≥ {HIT4_THRESHOLD} → "
                f"{'✅ 通过' if m_hit4 >= HIT4_THRESHOLD else '❌ 未达标'} |"
            ),
            "",
            "## 逐条结果",
            "",
            "| # | 问题 | 知识库 | 期望文件 | Rank | 延迟(ms) | Top 结果 |",
            "|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(rows, 1):
            top = " > ".join(r["top"]) if r["top"] else "（空）"
            report.append(
                f"| {i} | {r['question']} | {r['kb']} | {r['file']} | "
                f"{r['rank'] or '-'} | {r['latency_ms']} | {top} |"
            )
        report.append("")

        out = ROOT / "eval_report.md"
        out.write_text("\n".join(report), encoding="utf-8")
        print(f"\n报告已写入 {out}")
        print(f"Hit@1={m_hit1:.4f} Hit@4={m_hit4:.4f} MRR={m_rr:.4f} 延迟={m_lat:.1f}ms")
        if m_hit4 < HIT4_THRESHOLD:
            print(f"❌ Hit@4 < {HIT4_THRESHOLD}，未达 Gate-M3 阈值")
            return 1
        print("✅ Hit@4 达标")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
