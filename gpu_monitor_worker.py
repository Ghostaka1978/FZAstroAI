"""Compatibility wrapper for the relocated GPU monitor worker."""

from .workers.gpu_monitor_worker import GpuMonitorWorker

__all__ = ["GpuMonitorWorker"]
