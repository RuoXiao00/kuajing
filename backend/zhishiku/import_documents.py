"""递归批量导入知识目录。

示例：
  python -m backend.zhishiku.import_documents "亚马逊知识大纲" --dry-run
  python -m backend.zhishiku.import_documents "亚马逊知识大纲"

正式模式会先完整预扫描，再只导入唯一且可解析的正文；单文件失败不会终止
整个任务。报告默认写到 runtime/import-report-时间.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent import knowledge_base_service
from .config_data import RUNTIME_DIR
from .document_loader import SUPPORTED_SUFFIXES, content_hash, parse_document
from .vector_stories import knowledge_store


def _report_path(value: str | None) -> Path:
    """生成报告路径；报告是审计文件，不参与 Chroma 去重。"""

    if value:
        return Path(value).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return RUNTIME_DIR / f"import-report-{stamp}.json"


def scan_directory(source: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """递归解析全部支持文件，标记 unique/duplicate/error 并打印进度。"""

    # 预扫描只读文件，不写 Chroma。先确定可解析性和源目录内重复，正式阶段
    # 才产生 Embedding 成本；--dry-run 也只执行这一类只读工作。
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    seen_hashes: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    print(f"预扫描：共发现 {len(files)} 个支持的文件")
    for index, path in enumerate(files, 1):
        relative = path.relative_to(source)
        # 完整导入“亚马逊知识大纲”时，relative 的第一段就是分类目录；
        # 断点续传时也允许把某个分类目录直接作为 source，此时文件会直接位于
        # source 下，应该沿用 source 目录名，而不是错误地标成“未分类”。
        category = relative.parts[0] if len(relative.parts) > 1 else source.name
        try:
            parsed = parse_document(path.read_bytes(), path.name)
            digest = content_hash(parsed.text)
            duplicate_of = seen_hashes.get(digest)
            if duplicate_of:
                record = {
                    "path": str(relative),
                    "category": category,
                    "status": "duplicate",
                    "duplicate_of": duplicate_of,
                }
            else:
                seen_hashes[digest] = str(relative)
                record = {
                    "path": str(relative),
                    "category": category,
                    "status": "unique",
                    "content_hash": digest,
                    # ParsedDocument 只在当前进程内使用，写 JSON 前会移除。
                    "_parsed": parsed,
                    "_absolute_path": path,
                }
        except Exception as error:
            record = {
                "path": str(relative),
                "category": category,
                "status": "error",
                "message": str(error),
            }
        records.append(record)
        print(f"[预扫描 {index:>3}/{len(files)}] {record['status']:<9} {relative}")

    summary = {
        "scanned": len(files),
        "unique": sum(item["status"] == "unique" for item in records),
        "duplicate": sum(item["status"] == "duplicate" for item in records),
        "error": sum(item["status"] == "error" for item in records),
    }
    return records, summary


def import_directory(source: Path, dry_run: bool = False) -> dict[str, Any]:
    """预扫描并导入唯一正文，返回可 JSON 序列化的完整报告。"""

    # 这是可供其他 Python 代码复用的业务入口，只返回 dict，不决定报告路径。
    # 写 JSON 和设置命令行退出码属于 main 的职责。
    if not source.is_dir():
        raise ValueError(f"导入目录不存在：{source}")

    started_at = datetime.now().astimezone().isoformat()
    records, scan_summary = scan_directory(source)
    import_results: list[dict[str, Any]] = []
    unique_records = [item for item in records if item["status"] == "unique"]

    if not dry_run:
        for index, record in enumerate(unique_records, 1):
            parsed = record["_parsed"]
            try:
                # 预扫描已经解析过正文，这里从“已解析文档入口”执行入库图，
                # 不再越过业务层直接写存储。图内复用解析对象，存储仍批量 Embedding。
                result = knowledge_base_service.ingest_document(
                    parsed, record["category"]
                )
            except Exception as error:
                result = {
                    "status": "error",
                    "filename": parsed.filename,
                    "category": record["category"],
                    "chunk_count": 0,
                    "message": str(error),
                }
            import_results.append({"path": record["path"], **result})
            print(
                f"[入库 {index:>3}/{len(unique_records)}] "
                f"{result['status']:<9} {record['path']} "
                f"({result.get('chunk_count', 0)} 块)"
            )

    public_records = [
        {key: value for key, value in record.items() if not key.startswith("_")}
        for record in records
    ]
    stats: dict[str, Any] | None = None
    if not dry_run:
        try:
            stats = knowledge_store.stats()
        except Exception as error:
            stats = {"error": str(error)}

    # 本轮实际新增块数适合观察断点续传过程；Chroma 中的总块数才适合最终
    # 验收。两者必须分开，否则重跑一个全部命中去重的目录会得到 0，容易让
    # 使用者误以为已有向量数据丢失。
    chunks_written_this_run = sum(
        int(item.get("chunk_count", 0))
        for item in import_results
        if item["status"] == "indexed"
    )
    total_chunks = (
        int(stats.get("chunk_count", 0))
        if stats is not None and "error" not in stats
        else chunks_written_this_run
    )

    return {
        "source": str(source),
        "dry_run": dry_run,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "scan": scan_summary,
        "import": {
            "indexed": sum(item["status"] == "indexed" for item in import_results),
            "duplicate": sum(item["status"] == "duplicate" for item in import_results),
            "error": sum(item["status"] == "error" for item in import_results),
            # 最终验收字段始终与同一时刻 Chroma 的实际知识块数一致。
            "chunks_written": total_chunks,
            "chunks_written_this_run": chunks_written_this_run,
        },
        "chroma": stats,
        "files": public_records,
        "import_results": import_results,
    }


def main() -> int:
    # argparse 把命令行字符串转换为有类型的参数。main 返回退出码而不直接
    # 结束进程，便于测试；最末尾的 SystemExit 才把它交给操作系统。
    parser = argparse.ArgumentParser(description="递归导入 DOCX/PDF/TXT 到跨境电商知识库")
    parser.add_argument("source", type=Path, help="要递归扫描的资料目录")
    parser.add_argument("--dry-run", action="store_true", help="只预扫描，不调用 Embedding、不写 Chroma")
    parser.add_argument("--report", help="指定 JSON 报告路径")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    report_path = _report_path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = import_directory(source, dry_run=args.dry_run)
    except Exception as error:
        print(f"导入任务无法开始：{error}", file=sys.stderr)
        return 2
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{report_path}")
    print(json.dumps({"scan": report["scan"], "import": report["import"], "chroma": report["chroma"]}, ensure_ascii=False, indent=2))
    return 0 if report["import"]["error"] == 0 else 1


if __name__ == "__main__":
    # 用 python -m 执行本模块时条件成立；被 FastAPI import 时不成立，
    # 所以启动网站不会意外扫描目录或写导入报告。
    raise SystemExit(main())
