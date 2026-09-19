from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from belgu.analysis.service import AnalysisError, analyze_evidence, get_model_status


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            rows.append(row)
    return rows


def _completed_keys(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    keys = set()
    for row in load_cases(path):
        case_id, repeat = row.get("case_id"), row.get("repeat")
        if isinstance(case_id, str) and isinstance(repeat, int):
            keys.add((case_id, repeat))
    return keys


def run(args: argparse.Namespace) -> int:
    os.environ["BELGU_MODEL_URL"] = args.base_url.rstrip("/")
    if args.model:
        os.environ["BELGU_MODEL_ID"] = args.model
    else:
        os.environ.pop("BELGU_MODEL_ID", None)

    status = get_model_status()
    if status["status"] != "ready":
        raise SystemExit(f"model unavailable: {status['message']}")
    verified_model = status["model_id"]
    if args.model and verified_model != args.model:
        raise SystemExit(
            f"requested model {args.model!r} does not match endpoint model {verified_model!r}"
        )
    os.environ["BELGU_MODEL_ID"] = verified_model

    cases = load_cases(args.cases)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed = _completed_keys(args.output) if args.resume else set()
    mode = "a" if args.resume else "w"
    with args.output.open(mode, encoding="utf-8", buffering=1) as handle:
        for repeat in range(1, args.repeats + 1):
            for case in cases:
                key = (case["id"], repeat)
                if key in completed:
                    continue
                record = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "repeat": repeat,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "model_id": verified_model,
                    "expected_observations": case["expected_observations"],
                    "forbidden_claims": case["forbidden_claims"],
                    "required_uncertainties": case["required_uncertainties"],
                }
                started = perf_counter()
                try:
                    output = analyze_evidence(
                        case["evidence"],
                        {**(case.get("context") or {}), "evaluation_case": case["id"], "category": case["category"]},
                    )
                    record.update(
                        {
                            "status": "ok",
                            "first_pass_valid": not output["metrics"]["repair_attempted"],
                            "output": output,
                            "error_code": None,
                            "error": None,
                        }
                    )
                except AnalysisError as exc:
                    record.update(
                        {
                            "status": "error",
                            "first_pass_valid": False,
                            "output": None,
                            "error_code": exc.code,
                            "error": str(exc)[:800],
                        }
                    )
                except Exception as exc:  # Preserve results and continue with later cases.
                    record.update(
                        {
                            "status": "error",
                            "first_pass_valid": False,
                            "output": None,
                            "error_code": "runner_error",
                            "error": f"{type(exc).__name__}: {exc}"[:800],
                        }
                    )
                record["elapsed_ms"] = (perf_counter() - started) * 1000
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                print(
                    f"{case['id']} repeat={repeat} status={record['status']} "
                    f"elapsed_ms={record['elapsed_ms']:.1f}",
                    flush=True,
                )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Belgü local text-model evaluation")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", help="Exact ID reported by GET /models; discovered when omitted")
    parser.add_argument(
        "--cases", type=Path, default=Path("evals/fixtures/text-cases.jsonl")
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path(".local/evals/text.jsonl"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
