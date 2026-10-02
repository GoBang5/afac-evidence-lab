from __future__ import annotations
import argparse
import json
from pathlib import Path
from agent.schema import AgentConfig
from .budget import Budget
from .data import adapt
from .runner import run
from .api_config import DEFAULT_CONFIG
from .numeric import NumericConfig


def main():
    parser = argparse.ArgumentParser(description='AFAC Evidence Lab')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='Adapt existing page extraction, excluding labels')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('run', help='Resumable pipeline, no API by default')
    p.add_argument('--data', type=Path, default=Path('examples/lab'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--max-prompt-chars', type=int, default=12000)
    p.add_argument('--limit', type=int)
    p.add_argument('--judge-mode', choices=['none', 'qwen', 'openai_compatible'], default='none')
    p.add_argument('--allow-qwen', action='store_true')
    p.add_argument('--llm-model')
    p.add_argument('--llm-base-url')
    p.add_argument('--llm-api-key-env', default='OPENAI_API_KEY')
    p.add_argument('--api-config', type=Path, help='Read API_BASE_URL/API_MODEL/API_KEY as data; numeric model mode requires this')
    p.add_argument('--use-local-api', action='store_true', help='Use api-config.local.env in the project parent')
    p.add_argument('--max-repair-rounds', type=int, default=1)
    p.add_argument('--max-requests', type=int, default=100)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = adapt(args.source, args.out)
    else:
        config = AgentConfig(judge_mode=args.judge_mode, allow_qwen=args.allow_qwen,
                             llm_model=args.llm_model, llm_base_url=args.llm_base_url,
                             llm_api_key_env=args.llm_api_key_env, max_repair_rounds=args.max_repair_rounds)
        result = run(args.data, args.out, Budget(max_prompt_chars=args.max_prompt_chars), config, args.limit,
                     api_config=args.api_config or (DEFAULT_CONFIG if args.use_local_api else None),
                     numeric=NumericConfig(max_repair_rounds=args.max_repair_rounds), max_requests=args.max_requests)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('failures'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
