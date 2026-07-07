#!/usr/bin/env python3
"""Run MinerU on the staged question-linked PDF folder.

This is a thin, auditable wrapper around:
`01-projects/UniDoc-RL/tools/mineru_parse_folder.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_MINERU_SCRIPT = "/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_parse_folder.py"
DEFAULT_ENV = "/public/home/zhangfanjin/zhangnianhao/.env"


def env_has_key(path: Path, key: str) -> bool:
    if os.environ.get(key):
        return True
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key and value.strip().strip('"').strip("'"):
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-folder", default="processed_data/mineru_input/group_a_question_pdfs")
    parser.add_argument("--env", default=DEFAULT_ENV)
    parser.add_argument("--mineru-script", default=DEFAULT_MINERU_SCRIPT)
    parser.add_argument("--chunk-size", type=int, default=10)
    parser.add_argument("--language", default="ch")
    parser.add_argument("--ocr", action="store_true", help="Enable MinerU OCR.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--clean-split-work", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print command and pending count without calling MinerU.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_folder = Path(args.pdf_folder).expanduser().resolve()
    env_path = Path(args.env).expanduser().resolve()
    mineru_script = Path(args.mineru_script).expanduser().resolve()
    if not pdf_folder.is_dir():
        print(f"not a directory: {pdf_folder}", file=sys.stderr)
        return 2
    pdfs = sorted(path for path in pdf_folder.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
    if not mineru_script.exists():
        print(f"missing MinerU wrapper: {mineru_script}", file=sys.stderr)
        return 2

    out_root = pdf_folder.parent / "mineru"
    pending = []
    for pdf in pdfs:
        result_json = out_root / pdf.stem / "result.json"
        full_md = out_root / pdf.stem / "full.md"
        if args.force or not (result_json.exists() and full_md.exists()):
            pending.append(pdf.name)

    cmd = [
        sys.executable,
        str(mineru_script),
        str(pdf_folder),
        "--env",
        str(env_path),
        "--chunk-size",
        str(args.chunk_size),
        "--language",
        args.language,
        "--interval",
        str(args.interval),
        "--timeout",
        str(args.timeout),
    ]
    if args.ocr:
        cmd.append("--ocr")
    if args.force:
        cmd.append("--force")
    if args.clean_split_work:
        cmd.append("--clean-split-work")

    summary = {
        "pdf_folder": str(pdf_folder),
        "mineru_output_root": str(out_root),
        "pdf_count": len(pdfs),
        "pending_count": len(pending),
        "env_path": str(env_path),
        "mineru_api_key_present": env_has_key(env_path, "MINERU_API_KEY"),
        "command": cmd,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    if not summary["mineru_api_key_present"]:
        print("MINERU_API_KEY is missing in environment/.env; not calling MinerU.", file=sys.stderr)
        return 2
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
