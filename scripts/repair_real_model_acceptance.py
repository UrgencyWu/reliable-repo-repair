"""Run frozen repair samples through the real Repair API and collect evidence."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object")
    return value


def objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return [mapping(item) for item in value]


def required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def save(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def read(path: Path) -> dict[str, object]:
    return mapping(json.loads(path.read_text()))


def trajectory_usage(state: dict[str, object]) -> dict[str, object]:
    messages = objects(mapping(state["values"]).get("messages", []))
    calls = 0
    missing = 0
    tool_calls = 0
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    models: set[str] = set()
    for message in messages:
        if message.get("type") != "ai":
            continue
        calls += 1
        tool_calls += len(objects(message.get("tool_calls", [])))
        metadata = mapping(message.get("response_metadata") or {})
        model = metadata.get("model_name") or metadata.get("model_provider")
        if isinstance(model, str):
            models.add(model)
        raw_usage = message.get("usage_metadata")
        if raw_usage is None:
            raw_usage = mapping(message.get("additional_kwargs") or {}).get("usage_metadata")
        if not isinstance(raw_usage, dict):
            missing += 1
            continue
        usage = mapping(raw_usage)
        for key in totals:
            amount = usage.get(key)
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise ValueError("Model usage metadata has an invalid token count")
            totals[key] += amount
    return {
        "scope": "persisted main-agent AI messages; background title/branch calls excluded",
        "source": "Runtime usage_metadata or serialized additional_kwargs.usage_metadata",
        "ai_messages": calls,
        "messages_without_usage": missing,
        "tool_calls": tool_calls,
        "observed_models": sorted(models),
        "tokens": totals if calls and not missing else None,
        "known_partial_tokens": totals,
        "cost": None,
        "cost_note": "Local endpoint provides token usage, not billing or GPU cost",
    }


async def run_sample(
    client: httpx.AsyncClient,
    sample: dict[str, object],
    root: Path,
    runtime_url: str,
    wait_seconds: float,
) -> dict[str, object]:
    sample_id = required_string(sample["sample_id"])
    folder = root / sample_id
    folder.mkdir(exist_ok=True)
    result_path = folder / "result.json"
    if result_path.exists():
        return read(result_path)
    request_path = folder / "request.json"
    if not request_path.exists():
        save(
            request_path,
            {
                "idempotency_key": f"real-acceptance-{uuid4()}",
                "body": {
                    "fixture_id": sample_id,
                    "target_commit": sample["target_commit"],
                    "failing_command": sample["failing_command"],
                    "constraints": sample.get("constraints", ""),
                },
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
    request = read(request_path)
    started = perf_counter()
    response = await client.post(
        "/api/repair-tasks",
        json=request["body"],
        headers={"Idempotency-Key": required_string(request["idempotency_key"])},
    )
    response.raise_for_status()
    if response.status_code != 202:
        raise ValueError("Repair API did not accept the task asynchronously")
    created = mapping(response.json())
    save(folder / "accepted.json", created)
    task_id = required_string(created["id"])
    print(json.dumps({"sample_id": sample_id, "task_id": task_id, "event": "accepted"}), flush=True)
    last_status: object = None
    while True:
        response = await client.get(f"/api/repair-tasks/{task_id}")
        response.raise_for_status()
        detail = mapping(response.json())
        save(folder / "detail.json", detail)
        task = mapping(detail["task"])
        status = task["status"]
        if status != last_status:
            print(json.dumps({"sample_id": sample_id, "status": status}), flush=True)
            last_status = status
        runs = objects(detail["runs"])
        stops_pending = any(run.get("runtime_stop_pending") for run in runs)
        if status in {"COMPLETED", "FAILED", "TIMEOUT"} and not stops_pending:
            break
        if perf_counter() - started > wait_seconds:
            raise TimeoutError(f"Acceptance observer deadline reached for task {task_id}")
        await asyncio.sleep(2)
    response = await client.get(f"/api/repair-tasks/{task_id}/artifacts")
    response.raise_for_status()
    artifacts = mapping(response.json())
    save(folder / "artifacts.json", artifacts)
    candidate = artifacts.get("candidate")
    patch_matches = False
    if isinstance(candidate, dict):
        response = await client.get(f"/api/repair-tasks/{task_id}/patch")
        response.raise_for_status()
        patch = response.content
        (folder / "candidate.patch").write_bytes(patch)
        patch_matches = hashlib.sha256(patch).hexdigest() == mapping(candidate)["sha256"]
        if not patch_matches:
            raise ValueError("Downloaded patch does not match the persisted candidate hash")
    usage: dict[str, object] | None = None
    history_count: int | None = None
    if len(runs) != 1:
        raise ValueError("Acceptance expected one business repair run")
    run = runs[0]
    if run.get("runtime_run_id"):
        thread = required_string(run["thread_id"])
        async with httpx.AsyncClient(base_url=runtime_url, timeout=30) as runtime:
            response = await runtime.get(f"/threads/{thread}/state")
            response.raise_for_status()
            state = mapping(response.json())
            save(folder / "runtime-state.json", state)
            usage = trajectory_usage(state)
            response = await runtime.get(f"/threads/{thread}/runs", params={"limit": 100})
            response.raise_for_status()
            history = objects(response.json())
            save(folder / "runtime-history.json", history)
            history_count = len(history)
    validations = objects(artifacts["validations"])
    baseline_reproduced = any(
        check.get("name") == "BASELINE" and check.get("exit_code") == 1
        for validation in validations
        for check in objects(validation["checks"])
    )
    passed = any(validation.get("status") == "PASS" for validation in validations)
    if status == "COMPLETED" and not (passed and baseline_reproduced and patch_matches):
        raise ValueError("COMPLETED lacks independent validation or immutable patch evidence")
    result: dict[str, object] = {
        "sample_id": sample_id,
        "task_id": task_id,
        "repair_run_id": run["id"],
        "thread_id": run["thread_id"],
        "runtime_run_id": run["runtime_run_id"],
        "target_commit": sample["target_commit"],
        "started_at": request["started_at"],
        "finished_at": datetime.now(UTC).isoformat(),
        "status": status,
        "failure_reason": task.get("failure_reason"),
        "candidate_produced": candidate is not None,
        "baseline_reproduced": baseline_reproduced,
        "independent_pass": passed,
        "patch_hash_matches": patch_matches,
        "runtime_history_count": history_count,
        "task_created_at": task["created_at"],
        "task_updated_at": task["updated_at"],
        "observer_elapsed_seconds": round(perf_counter() - started, 3),
        "usage": usage,
    }
    save(result_path, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--wait-seconds", type=float, default=720)
    args = parser.parse_args()
    if args.limit <= 0 or args.wait_seconds <= 0:
        raise ValueError("Acceptance limit and observer deadline must be positive")
    session = read(args.session)
    manifest = read(args.manifest)
    samples = objects(manifest["samples"])[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    plan = {
        "kind": "real-model-repair-acceptance",
        "samples": objects(manifest["samples"]),
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "api_url": args.api_url,
        "scope": "trusted synthetic repositories; not independent or real-project benchmark",
    }
    plan_path = args.output / "plan.json"
    if plan_path.exists():
        frozen = read(plan_path)
        if (
            frozen["manifest_sha256"] != plan["manifest_sha256"]
            or frozen["api_url"] != args.api_url
        ):
            raise ValueError("Acceptance inputs differ from the frozen plan")
    else:
        save(plan_path, plan)
    async with httpx.AsyncClient(
        base_url=args.api_url,
        timeout=30,
        headers={"Origin": args.api_url},
        cookies={required_string(session["cookie_name"]): required_string(session["cookie_value"])},
    ) as client:
        for sample in samples:
            await run_sample(client, sample, args.output, args.api_url, args.wait_seconds)
    results = [read(path) for path in sorted(args.output.glob("*/result.json"))]
    save(
        args.output / "summary.json",
        {
            "kind": plan["kind"],
            "started_tasks": len(list(args.output.glob("*/accepted.json"))),
            "completed_observations": len(results),
            "independent_pass": sum(result["independent_pass"] is True for result in results),
            "results": results,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
