#!/usr/bin/env python3
"""Simulate a bounded human/agent/model delivery calendar with 15-minute slots.

This is a planning model, not historical time tracking. A task uses exactly one
resource class: human decision/review, agent implementation, or local model lane.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "tasks.json"


@dataclass(frozen=True)
class Task:
    id: str
    label: str
    resource: str
    hours: tuple[float, float]
    depends: tuple[str, ...]
    notes: str
    model_workload: dict | None = None


def load_scope(scope: str) -> tuple[dict, list[Task]]:
    raw = json.loads(DATA.read_text())
    task_data = raw["scopes"][scope]["tasks"]
    tasks = [Task(x["id"], x["label"], x["resource"], tuple(x["hours"]), tuple(x["depends"]), x["notes"], x.get("model_workload")) for x in task_data]
    return raw["assumptions"], tasks


def parse_start(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(minute=(parsed.minute // 15) * 15, second=0, microsecond=0)


def windows_for_day(day: datetime, human_hours: int, assumptions: dict) -> list[tuple[datetime, datetime]]:
    key = str(human_hours)
    if key not in assumptions["human_windows_by_daily_hours"]:
        raise ValueError("human_hours must be one of " + ", ".join(assumptions["human_windows_by_daily_hours"]))
    if day.weekday() not in assumptions["calendar_days_available"]:
        return []
    answer = []
    for start, end in assumptions["human_windows_by_daily_hours"][key]:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        answer.append((day.replace(hour=sh, minute=sm), day.replace(hour=eh, minute=em)))
    return answer


def is_human_time(moment: datetime, human_hours: int, assumptions: dict) -> bool:
    return any(start <= moment < end for start, end in windows_for_day(moment, human_hours, assumptions))


def advance_to_human(moment: datetime, human_hours: int, assumptions: dict) -> datetime:
    while not is_human_time(moment, human_hours, assumptions):
        moment += timedelta(minutes=15)
    return moment


def planned_hours(task: Task, estimate: int, slot_minutes: int) -> float:
    """Return declared human/agent time or a derived model-call budget.

    For model tasks, ``hours`` is retained only as a documented hand-calculated
    reference. The scheduler uses the workload fields, so changing cases,
    variants, repeats, per-trial budget, or warmup changes the calendar.
    """
    if task.resource != "model" or not task.model_workload:
        return task.hours[estimate]
    key = "low" if estimate == 0 else "high"
    plan = task.model_workload[key]
    raw_seconds = plan["cases"] * plan["variants"] * plan["repeats"] * plan["seconds_per_trial"] + plan["warmup_seconds"]
    # Scheduling is quantized to slots, so recorded model occupancy is rounded up.
    return (raw_seconds + slot_minutes * 60 - 1) // (slot_minutes * 60) * slot_minutes / 60


def schedule(scope: str, estimate: int, start: datetime, human_hours: int, agent_workers: int, assumptions: dict) -> dict:
    _, tasks = load_scope(scope)
    task_map = {t.id: t for t in tasks}
    if len(task_map) != len(tasks):
        raise ValueError("task IDs must be unique")
    for task in tasks:
        if any(dep not in task_map for dep in task.depends):
            raise ValueError(f"unknown dependency for {task.id}")
    if estimate not in (0, 1):
        raise ValueError("estimate must be 0 (low) or 1 (high)")
    if agent_workers < 1:
        raise ValueError("agent_workers must be positive")

    slot = timedelta(minutes=assumptions["slot_minutes"])
    estimated_hours = {t.id: planned_hours(t, estimate, assumptions["slot_minutes"]) for t in tasks}
    duration = {t.id: int(estimated_hours[t.id] * 60 / assumptions["slot_minutes"]) for t in tasks}
    remaining = duration.copy()
    completed: dict[str, datetime] = {}
    first_slot: dict[str, datetime] = {}
    resource_history: dict[str, list[tuple[datetime, str]]] = {"human": [], "agent": [], "model": []}
    point = start
    guard = 0
    while len(completed) < len(tasks):
        guard += 1
        if guard > 500_000:
            raise RuntimeError("calendar did not converge")
        ready = [t for t in tasks if t.id not in completed and remaining[t.id] and all(dep in completed and completed[dep] <= point for dep in t.depends)]
        if not ready:
            if all(t.id in completed for t in tasks):
                break
            point += slot
            continue
        capacity = {"human": 1 if is_human_time(point, human_hours, assumptions) else 0, "agent": agent_workers, "model": assumptions["local_model_lanes"]}
        # A fixed stable ordering makes the model deterministic. Work within the
        # same resource can use all available workers in one 15-minute slot.
        assigned: list[Task] = []
        for resource in ("human", "agent", "model"):
            for task in ready:
                if task.resource == resource and capacity[resource] > 0:
                    assigned.append(task)
                    capacity[resource] -= 1
        for task in assigned:
            first_slot.setdefault(task.id, point)
            remaining[task.id] -= 1
            resource_history[task.resource].append((point, task.id))
            if remaining[task.id] == 0:
                completed[task.id] = point + slot
        point += slot

    first = min(first_slot.values()) if first_slot else start
    end = max(completed.values()) if completed else start
    totals = {kind: sum(estimated_hours[task.id] for task in tasks if task.resource == kind) for kind in resource_history}
    slot_counts: dict[str, dict[datetime, int]] = {kind: {} for kind in resource_history}
    for kind, entries in resource_history.items():
        for moment, _ in entries:
            slot_counts[kind][moment] = slot_counts[kind].get(moment, 0) + 1
    rows = []
    for task in tasks:
        rows.append({
            "id": task.id, "label": task.label, "resource": task.resource,
            "hours": estimated_hours[task.id],
            "declared_hours_reference": list(task.hours) if task.resource == "model" else None,
            "hours_source": "model_workload_derived" if task.resource == "model" and task.model_workload else "declared_task_hours",
            "depends": list(task.depends),
            "start": first_slot[task.id].isoformat(), "end": completed[task.id].isoformat(),
            "notes": task.notes,
            "model_workload": task.model_workload,
        })
    return {
        "scope": scope, "estimate": "low" if estimate == 0 else "high",
        "configuration": {"start": start.isoformat(), "human_hours_per_day": human_hours, "agent_workers": agent_workers, "model_lanes": assumptions["local_model_lanes"], "slot_minutes": assumptions["slot_minutes"], "calendar_days_available": assumptions["calendar_days_available"]},
        "resource_hours": totals,
        "allocation_audit": {
            "human_slots_outside_windows": sum(
                1 for moment, _ in resource_history["human"] if not is_human_time(moment, human_hours, assumptions)
            ),
            "maximum_parallel_slots": {kind: max(counts.values(), default=0) for kind, counts in slot_counts.items()},
        },
        "calendar": {
            "requested_start": start.isoformat(), "first_task_start": first.isoformat(), "finish": end.isoformat(),
            "wait_before_first_task_hours": round((first - start).total_seconds() / 3600, 2),
            "elapsed_after_first_task_start_hours": round((end - first).total_seconds() / 3600, 2),
            "elapsed_from_requested_start_hours": round((end - start).total_seconds() / 3600, 2),
            "elapsed_from_requested_start_days": round((end - start).total_seconds() / 86400, 2),
        },
        "tasks": rows,
    }


def summary(scope: str, start: datetime, human_hours: int, agent_workers: int) -> dict:
    assumptions, _ = load_scope(scope)
    low = schedule(scope, 0, start, human_hours, agent_workers, assumptions)
    high = schedule(scope, 1, start, human_hours, agent_workers, assumptions)
    return {"scope": scope, "label": json.loads(DATA.read_text())["scopes"][scope]["label"], "low": low, "high": high}


def checks() -> None:
    assumptions, _ = load_scope("interview")
    start = parse_start("2026-11-23T09:00:00")
    baseline = schedule("interview", 0, start, 4, 3, assumptions)
    more_human = schedule("interview", 0, start, 8, 3, assumptions)
    more_agents = schedule("interview", 0, start, 4, 5, assumptions)
    model_task = next(task for task in load_scope("interview")[1] if task.id == "int_model_trial")
    changed_plan = dict(model_task.model_workload or {})
    changed_low = dict(changed_plan["low"])
    changed_low["cases"] *= 2
    changed_plan["low"] = changed_low
    doubled_cases = replace(model_task, model_workload=changed_plan)
    assert planned_hours(doubled_cases, 0, assumptions["slot_minutes"]) > planned_hours(model_task, 0, assumptions["slot_minutes"])
    scheduled_model = next(task for task in baseline["tasks"] if task["id"] == "int_model_trial")
    assert scheduled_model["hours_source"] == "model_workload_derived"
    assert scheduled_model["declared_hours_reference"] == [1, 4.75]
    assert more_human["calendar"]["elapsed_from_requested_start_hours"] <= baseline["calendar"]["elapsed_from_requested_start_hours"]
    assert more_agents["calendar"]["elapsed_from_requested_start_hours"] <= baseline["calendar"]["elapsed_from_requested_start_hours"]
    for result in (baseline, more_human, more_agents):
        assert result["allocation_audit"]["human_slots_outside_windows"] == 0
        assert result["allocation_audit"]["maximum_parallel_slots"]["human"] <= 1
        assert result["allocation_audit"]["maximum_parallel_slots"]["agent"] <= result["configuration"]["agent_workers"]
        assert result["allocation_audit"]["maximum_parallel_slots"]["model"] <= result["configuration"]["model_lanes"]
        for task in result["tasks"]:
            assert datetime.fromisoformat(task["end"]) > datetime.fromisoformat(task["start"])
            for dep in task["depends"]:
                dependency = next(item for item in result["tasks"] if item["id"] == dep)
                assert datetime.fromisoformat(task["start"]) >= datetime.fromisoformat(dependency["end"])
    try:
        schedule("interview", 0, start, 4, 0, assumptions)
    except ValueError as error:
        assert "agent_workers" in str(error)
    else:
        raise AssertionError("agent_workers=0 must fail")
    late = schedule("review", 0, parse_start("2026-11-23T23:45:00"), 2, 3, assumptions)
    assert datetime.fromisoformat(late["calendar"]["first_task_start"]).date() > start.date()
    assert late["calendar"]["wait_before_first_task_hours"] > 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["review", "interview", "complete", "training_addon"])
    parser.add_argument("--start", default=None)
    parser.add_argument("--human-hours", type=int, choices=[2, 4, 8], default=4)
    parser.add_argument("--agent-workers", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.agent_workers < 1:
        parser.error("--agent-workers must be positive")
    if args.self_test:
        checks()
        print("scheduler checks passed")
        return
    raw = json.loads(DATA.read_text())
    start = parse_start(args.start or raw["assumptions"]["default_start"])
    if args.scope:
        result = summary(args.scope, start, args.human_hours, args.agent_workers)
    else:
        result = {scope: summary(scope, start, args.human_hours, args.agent_workers) for scope in ("review", "interview", "complete", "training_addon")}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
