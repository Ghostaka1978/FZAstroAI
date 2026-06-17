import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .logging_utils import log_debug, log_warning


class GpuMonitorWorker(QThread):
    """Poll hardware telemetry without blocking the UI thread."""

    metrics_ready = Signal(int, int, int, object)
    system_metrics_ready = Signal(object, object, object, object)
    unavailable = Signal(str)

    def __init__(self, interval_ms=1000, parent=None):
        super().__init__(parent)
        self.interval_ms = max(500, int(interval_ms))
        self._stop_requested = False
        self._previous_cpu_times = None

    def stop(self):
        self._stop_requested = True

    def _sleep_interruptibly(self):
        remaining = self.interval_ms

        while remaining > 0 and not self._stop_requested:
            step = min(100, remaining)
            self.msleep(step)
            remaining -= step

    def run(self):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        gpu_unavailable_reported = False
        system_unavailable_reported = False

        while not self._stop_requested:
            try:
                cpu_load = self._read_cpu_percent()
                ram_used_mb, ram_total_mb = self._read_memory_mb()
                cpu_temp_c = self._read_cpu_temperature_c()
                self.system_metrics_ready.emit(
                    cpu_load, ram_used_mb, ram_total_mb, cpu_temp_c
                )
                system_unavailable_reported = False
            except Exception as error:
                clean_error = re.sub(r"\s+", " ", str(error)).strip()

                if not system_unavailable_reported:
                    log_warning(
                        "System telemetry unavailable",
                        clean_error or "CPU/RAM telemetry could not be read",
                    )
                    self.system_metrics_ready.emit(None, None, None, None)
                    system_unavailable_reported = True
                else:
                    log_debug("System telemetry still unavailable", clean_error)

            try:
                gpu_load, memory_used_mb, memory_total_mb, gpu_temp_c = (
                    self._read_nvidia_gpu_metrics(creation_flags)
                )
                self.metrics_ready.emit(
                    gpu_load, memory_used_mb, memory_total_mb, gpu_temp_c
                )
                gpu_unavailable_reported = False

            except Exception as error:
                clean_error = re.sub(r"\s+", " ", str(error)).strip()

                if not gpu_unavailable_reported:
                    log_warning(
                        "NVIDIA GPU telemetry unavailable",
                        clean_error or "nvidia-smi did not return usable metrics",
                    )
                    self.unavailable.emit(
                        clean_error or "NVIDIA GPU telemetry unavailable"
                    )
                    gpu_unavailable_reported = True
                else:
                    log_debug("NVIDIA GPU telemetry still unavailable", clean_error)

            self._sleep_interruptibly()

    def _read_nvidia_gpu_metrics(self, creation_flags):
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
            creationflags=creation_flags,
        )

        first_line = next(
            (line.strip() for line in result.stdout.splitlines() if line.strip()),
            "",
        )
        values = [value.strip() for value in first_line.split(",")]

        if len(values) < 3:
            raise ValueError("Unexpected nvidia-smi output")

        gpu_load = int(float(values[0]))
        memory_used_mb = int(float(values[1]))
        memory_total_mb = int(float(values[2]))
        gpu_temp_c = self._parse_temperature(values[3]) if len(values) >= 4 else None
        return gpu_load, memory_used_mb, memory_total_mb, gpu_temp_c

    def _read_cpu_percent(self):
        current_times = self._read_cpu_times()

        if current_times is None:
            return None

        previous_times = self._previous_cpu_times
        self._previous_cpu_times = current_times

        if previous_times is None:
            return None

        previous_idle, previous_total = previous_times
        current_idle, current_total = current_times
        total_delta = current_total - previous_total
        idle_delta = current_idle - previous_idle

        if total_delta <= 0:
            return None

        busy_percent = 100.0 * (1.0 - (idle_delta / total_delta))
        return round(max(0.0, min(100.0, busy_percent)), 1)

    def _read_cpu_times(self):
        if sys.platform.startswith("win"):
            return self._read_windows_cpu_times()

        stat_path = Path("/proc/stat")
        if stat_path.exists():
            return self._read_proc_stat_cpu_times(stat_path)

        return None

    def _read_windows_cpu_times(self):
        idle_time = _FILETIME()
        kernel_time = _FILETIME()
        user_time = _FILETIME()

        success = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle_time), ctypes.byref(kernel_time), ctypes.byref(user_time)
        )
        if not success:
            return None

        idle = _filetime_to_int(idle_time)
        kernel = _filetime_to_int(kernel_time)
        user = _filetime_to_int(user_time)
        return idle, kernel + user

    def _read_proc_stat_cpu_times(self, stat_path):
        first_line = stat_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines()[0]
        values = [int(value) for value in first_line.split()[1:]]

        if len(values) < 4:
            return None

        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return idle, total

    def _read_memory_mb(self):
        if sys.platform.startswith("win"):
            return self._read_windows_memory_mb()

        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.exists():
            return self._read_proc_meminfo_mb(meminfo_path)

        return None, None

    def _read_windows_memory_mb(self):
        memory_status = _MEMORYSTATUSEX()
        memory_status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)

        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(
            ctypes.byref(memory_status)
        )
        if not success:
            return None, None

        total_mb = int(memory_status.ullTotalPhys / (1024 * 1024))
        available_mb = int(memory_status.ullAvailPhys / (1024 * 1024))
        used_mb = max(0, total_mb - available_mb)
        return used_mb, total_mb

    def _read_proc_meminfo_mb(self, meminfo_path):
        values = {}
        for line in meminfo_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1])

        total_kb = values.get("MemTotal")
        available_kb = values.get("MemAvailable", values.get("MemFree"))

        if total_kb is None or available_kb is None:
            return None, None

        used_kb = max(0, total_kb - available_kb)
        return int(used_kb / 1024), int(total_kb / 1024)

    def _read_cpu_temperature_c(self):
        psutil_temperature = self._read_psutil_cpu_temperature_c()
        if psutil_temperature is not None:
            return psutil_temperature

        thermal_zone_temperature = self._read_linux_thermal_zone_temperature_c()
        if thermal_zone_temperature is not None:
            return thermal_zone_temperature

        return None

    def _read_psutil_cpu_temperature_c(self):
        try:
            import psutil  # type: ignore
        except Exception:
            return None

        try:
            temperatures = psutil.sensors_temperatures(fahrenheit=False)
        except Exception:
            return None

        candidates = []
        preferred_names = ("coretemp", "k10temp", "cpu_thermal", "acpitz")

        for sensor_name, entries in temperatures.items():
            sensor_name_lower = str(sensor_name).lower()
            for entry in entries:
                current = getattr(entry, "current", None)
                if current is None:
                    continue
                try:
                    value = float(current)
                except (TypeError, ValueError):
                    continue
                if not (-50.0 <= value <= 150.0):
                    continue
                priority = (
                    0
                    if any(name in sensor_name_lower for name in preferred_names)
                    else 1
                )
                candidates.append((priority, value))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return round(candidates[0][1], 1)

    def _read_linux_thermal_zone_temperature_c(self):
        thermal_root = Path("/sys/class/thermal")
        if not thermal_root.exists():
            return None

        candidates = []
        for temp_file in thermal_root.glob("thermal_zone*/temp"):
            try:
                raw_value = float(temp_file.read_text(encoding="utf-8").strip())
            except Exception:
                continue

            value = raw_value / 1000.0 if raw_value > 1000 else raw_value
            if 0.0 <= value <= 125.0:
                candidates.append(value)

        if not candidates:
            return None

        return round(max(candidates), 1)

    def _parse_temperature(self, value):
        try:
            temperature = float(value)
        except (TypeError, ValueError):
            return None

        if not (-50.0 <= temperature <= 150.0):
            return None

        return round(temperature, 1)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _filetime_to_int(filetime):
    return (int(filetime.dwHighDateTime) << 32) + int(filetime.dwLowDateTime)
