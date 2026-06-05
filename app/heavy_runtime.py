from __future__ import annotations

import asyncio
import functools
import os
import shutil
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, TypeVar

from telegram.ext import Application, ContextTypes


T = TypeVar("T")

HEAVY_POOL_KEY = "kbdna_heavy_process_pool"


def heavy_max_workers() -> int:
    value = os.getenv("KBDNA_HEAVY_MAX_WORKERS", "3")
    try:
        configured = int(value)
    except (TypeError, ValueError):
        configured = 3
    cpu_count = os.cpu_count() or 1
    return max(1, min(configured, cpu_count))


def heavy_cpu_affinity_spec() -> str:
    configured = os.getenv("KBDNA_HEAVY_CPU_AFFINITY", "").strip()
    if configured:
        return configured

    cpu_count = os.cpu_count() or 1
    if cpu_count <= 1:
        return "0"

    cpus = list(range(1, min(cpu_count, heavy_max_workers() + 1)))
    return ",".join(str(cpu) for cpu in cpus) or "0"


def heavy_command(args: list[str]) -> list[str]:
    if os.name != "posix":
        return args
    taskset = shutil.which("taskset")
    if not taskset:
        return args
    spec = heavy_cpu_affinity_spec()
    if not spec:
        return args
    return [taskset, "-c", spec, *args]


def get_heavy_executor(application: Application) -> ProcessPoolExecutor:
    executor = application.bot_data.get(HEAVY_POOL_KEY)
    if isinstance(executor, ProcessPoolExecutor):
        return executor

    executor = ProcessPoolExecutor(max_workers=heavy_max_workers(), initializer=_pin_current_process_to_heavy_cpus)
    application.bot_data[HEAVY_POOL_KEY] = executor
    return executor


async def run_in_heavy_pool(context: ContextTypes.DEFAULT_TYPE, func: Callable[..., T], *args: Any) -> T:
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args)
    return await loop.run_in_executor(get_heavy_executor(context.application), call)


def _pin_current_process_to_heavy_cpus() -> None:
    if not hasattr(os, "sched_setaffinity"):
        return
    cpus = _parse_cpu_spec(heavy_cpu_affinity_spec())
    if not cpus:
        return
    try:
        os.sched_setaffinity(0, cpus)
    except OSError:
        return


def _parse_cpu_spec(value: str) -> set[int]:
    cpus: set[int] = set()
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            left, _, right = chunk.partition("-")
            try:
                start = int(left)
                end = int(right)
            except ValueError:
                continue
            cpus.update(range(min(start, end), max(start, end) + 1))
            continue
        try:
            cpus.add(int(chunk))
        except ValueError:
            continue
    return cpus
