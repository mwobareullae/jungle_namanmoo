#!/usr/bin/env python3
"""Capture host specifications and lightweight host resource samples for benchmarks."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RUNNING = True
HOST_STATS_FIELDS = [
    "timestamp", "cpu_usage_percent", "load1", "load5", "load15",
    "mem_total_mib", "mem_available_mib", "mem_used_mib", "swap_total_mib",
    "swap_free_mib", "disk_root_used_percent", "network_rx_bytes_per_second",
    "network_tx_bytes_per_second",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
    except (FileNotFoundError, ValueError):
        pass
    return values


def read_cpu_counters() -> tuple[int, int] | None:
    try:
        values = [int(value) for value in Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]]
    except (FileNotFoundError, IndexError, ValueError):
        return None
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def read_network_totals() -> tuple[int, int] | None:
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
    except FileNotFoundError:
        return None
    rx_total = tx_total = 0
    for line in lines:
        interface, values = line.split(":", 1)
        if interface.strip() == "lo":
            continue
        counters = values.split()
        if len(counters) >= 9:
            rx_total += int(counters[0])
            tx_total += int(counters[8])
    return rx_total, tx_total


def read_os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    return result


def docker_version() -> str | None:
    if shutil.which("docker") is None:
        return None
    completed = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], check=False, capture_output=True, text=True, timeout=3)
    return completed.stdout.strip() or None


def write_snapshot(output: Path, server_label: str | None) -> None:
    meminfo = read_meminfo()
    disk = shutil.disk_usage("/")
    payload = {
        "captured_at": utc_now(), "server_label": server_label or None,
        "hostname": socket.gethostname(),
        "os_name": read_os_release().get("PRETTY_NAME") or platform.platform(),
        "kernel": platform.release(), "architecture": platform.machine(),
        "logical_vcpu_count": os.cpu_count(),
        "memory_total_mib": round(meminfo.get("MemTotal", 0) / (1024 * 1024), 2) or None,
        "swap_total_mib": round(meminfo.get("SwapTotal", 0) / (1024 * 1024), 2) or None,
        "root_disk_total_gib": round(disk.total / (1024**3), 2),
        "docker_server_version": docker_version(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample(previous_cpu: tuple[int, int] | None, previous_network: tuple[int, int] | None, interval: float) -> tuple[dict[str, Any], tuple[int, int] | None, tuple[int, int] | None]:
    meminfo, cpu, network = read_meminfo(), read_cpu_counters(), read_network_totals()
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    disk = shutil.disk_usage("/")
    cpu_percent = None
    if cpu and previous_cpu:
        total_delta, idle_delta = cpu[0] - previous_cpu[0], cpu[1] - previous_cpu[1]
        if total_delta > 0:
            cpu_percent = round((1 - idle_delta / total_delta) * 100, 2)
    rx_per_second = tx_per_second = None
    if network and previous_network and interval > 0:
        rx_per_second = round(max(network[0] - previous_network[0], 0) / interval, 2)
        tx_per_second = round(max(network[1] - previous_network[1], 0) / interval, 2)
    total, available = meminfo.get("MemTotal", 0), meminfo.get("MemAvailable", 0)
    row = {
        "timestamp": utc_now(), "cpu_usage_percent": cpu_percent,
        "load1": round(load[0], 2) if load[0] is not None else None,
        "load5": round(load[1], 2) if load[1] is not None else None,
        "load15": round(load[2], 2) if load[2] is not None else None,
        "mem_total_mib": round(total / (1024 * 1024), 2) if total else None,
        "mem_available_mib": round(available / (1024 * 1024), 2) if available else None,
        "mem_used_mib": round((total - available) / (1024 * 1024), 2) if total else None,
        "swap_total_mib": round(meminfo.get("SwapTotal", 0) / (1024 * 1024), 2),
        "swap_free_mib": round(meminfo.get("SwapFree", 0) / (1024 * 1024), 2),
        "disk_root_used_percent": round(disk.used / disk.total * 100, 2) if disk.total else None,
        "network_rx_bytes_per_second": rx_per_second,
        "network_tx_bytes_per_second": tx_per_second,
    }
    return row, cpu, network


def monitor(output: Path, interval: float) -> None:
    global RUNNING
    signal.signal(signal.SIGTERM, lambda *_: setattr(__import__(__name__), "RUNNING", False))
    signal.signal(signal.SIGINT, lambda *_: setattr(__import__(__name__), "RUNNING", False))
    output.parent.mkdir(parents=True, exist_ok=True)
    previous_cpu, previous_network = read_cpu_counters(), read_network_totals()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HOST_STATS_FIELDS)
        writer.writeheader()
        while RUNNING:
            started = time.monotonic()
            row, previous_cpu, previous_network = sample(previous_cpu, previous_network, interval)
            writer.writerow(row)
            handle.flush()
            time.sleep(max(interval - (time.monotonic() - started), 0.05))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--output", type=Path, required=True)
    snapshot_parser.add_argument("--server-label")
    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--output", type=Path, required=True)
    monitor_parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.command == "snapshot":
        write_snapshot(args.output, args.server_label)
    else:
        monitor(args.output, max(args.interval, 0.1))


if __name__ == "__main__":
    main()
