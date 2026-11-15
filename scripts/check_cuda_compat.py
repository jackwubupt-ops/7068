"""Check that the NVIDIA driver can run the CUDA runtime PyTorch was built with.

`nvidia-smi`'s "CUDA Version" is the highest CUDA the DRIVER supports. It is
NOT the runtime PyTorch uses; that is torch.version.cuda. This script compares
the two and runs a real GPU kernel, so a broken stack fails here instead of
deep inside vLLM's engine-core startup.

Exit code 0 = compatible and a GPU matmul succeeded. Non-zero = do not start vLLM.
"""
from __future__ import annotations

import ctypes
import json
import sys

# CUDA 12.x minor-version compatibility needs at least this Linux driver.
MIN_DRIVER_FOR_CUDA12 = (525, 60, 13)


def driver_cuda_version() -> tuple[int, int] | None:
    """CUDA version supported by the installed driver (cuDriverGetVersion)."""
    for name in ("libcuda.so.1", "libcuda.so"):
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        value = ctypes.c_int(0)
        if lib.cuDriverGetVersion(ctypes.byref(value)) == 0 and value.value:
            return value.value // 1000, (value.value % 1000) // 10
    return None


def driver_version() -> str | None:
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = out.stdout.strip().splitlines()
    return lines[0].strip() if out.returncode == 0 and lines else None


def main() -> int:
    report: dict = {"python": sys.executable}
    problems: list[str] = []

    drv = driver_version()
    drv_cuda = driver_cuda_version()
    report["nvidia_driver"] = drv
    report["driver_max_cuda"] = f"{drv_cuda[0]}.{drv_cuda[1]}" if drv_cuda else None
    if drv_cuda is None:
        problems.append("libcuda not found: no NVIDIA driver visible in this container")

    try:
        import torch
    except ImportError:
        problems.append("torch is not installed in this interpreter")
        torch = None

    if torch is not None:
        report["torch"] = torch.__version__
        report["torch_cuda_runtime"] = torch.version.cuda
        if not torch.version.cuda:
            problems.append("torch is a CPU-only build")
        elif drv_cuda:
            rt_major = int(torch.version.cuda.split(".")[0])
            if rt_major > drv_cuda[0]:
                problems.append(
                    f"torch was built for CUDA {torch.version.cuda} but the driver only "
                    f"supports CUDA {report['driver_max_cuda']}. Reinstall with "
                    "requirements-qwen-server.txt (CUDA 12 build); do not upgrade the "
                    "driver inside the container."
                )
            if rt_major == 12 and drv:
                parts = tuple(int(p) for p in drv.split(".") if p.isdigit())
                if parts and parts < MIN_DRIVER_FOR_CUDA12:
                    problems.append("driver is older than 525.60.13; CUDA 12 runtimes will not load")
        if not problems:
            report["cuda_available"] = torch.cuda.is_available()
            if report["cuda_available"]:
                report["gpu"] = torch.cuda.get_device_name(0)
                report["compute_capability"] = ".".join(map(str, torch.cuda.get_device_capability(0)))
                a = torch.randn(256, 256, device="cuda", dtype=torch.bfloat16)
                report["matmul_ok"] = bool(torch.isfinite((a @ a).float()).all().item())
                if not report["matmul_ok"]:
                    problems.append("GPU matmul returned non-finite values")
            else:
                problems.append("torch.cuda.is_available() is False")

    try:
        import vllm
        report["vllm"] = vllm.__version__
    except Exception as exc:  # report but don't hide torch problems
        report["vllm"] = f"import failed: {type(exc).__name__}: {exc}"

    report["problems"] = problems
    report["compatible"] = not problems
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
