"""
System resource stats endpoint.
GET /api/stats — CPU %, RAM, GPU/VRAM (NVIDIA via pynvml) and Ollama loaded models.
"""
from __future__ import annotations

import psutil
import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/stats", tags=["stats"])

# Try to initialize NVML once at module load
import logging as _logging
import warnings as _warnings
_nvml_ok = False
_pynvml = None
try:
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")   # suppress FutureWarning from pynvml
        import pynvml as _pynvml
    _pynvml.nvmlInit()
    _nvml_ok = True
except Exception as _e:
    _logging.warning(f"NVML init failed (no GPU stats): {_e}")


def _gpu_info() -> dict | None:
    if not _nvml_ok or _pynvml is None:
        return None
    try:
        handle = _pynvml.nvmlDeviceGetHandleByIndex(0)
        mem    = _pynvml.nvmlDeviceGetMemoryInfo(handle)
        util   = _pynvml.nvmlDeviceGetUtilizationRates(handle)
        name   = _pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode()
        return {
            "name":          name,
            "percent":       util.gpu,
            "vram_used_gb":  round(mem.used  / 1_073_741_824, 1),
            "vram_total_gb": round(mem.total / 1_073_741_824, 1),
        }
    except Exception:
        return None


async def _ollama_models() -> list[dict]:
    """Query Ollama /api/ps for currently loaded models."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:11434/api/ps")
            if not resp.is_success:
                return []
            data = resp.json()
            result = []
            for m in data.get("models", []):
                size      = m.get("size", 0) or 0
                size_vram = m.get("size_vram", 0) or 0
                gpu_pct   = round(size_vram / size * 100) if size > 0 else 0
                details   = m.get("details", {}) or {}
                result.append({
                    "name":        m.get("name", ""),
                    "size_gb":     round(size      / 1_073_741_824, 1),
                    "vram_gb":     round(size_vram / 1_073_741_824, 1),
                    "gpu_percent": gpu_pct,           # 100 = full GPU, 0 = full CPU
                    "params":      details.get("parameter_size", ""),
                    "quant":       details.get("quantization_level", ""),
                })
            return result
    except Exception:
        return []


@router.get("")
async def get_stats():
    ram = psutil.virtual_memory()
    return {
        "cpu_percent":   psutil.cpu_percent(interval=None),
        "ram_used_gb":   round(ram.used  / 1_073_741_824, 1),
        "ram_total_gb":  round(ram.total / 1_073_741_824, 1),
        "ram_percent":   ram.percent,
        "gpu":           _gpu_info(),
        "ollama_models": await _ollama_models(),
    }
