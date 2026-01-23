#!/usr/bin/env python3
"""
GPU Target Temperature Service

Uses a smoothed PI controller with a baseline fan curve to maintain
a target GPU temperature regardless of ambient conditions.

Supports multiple GPUs - each GPU maintains independent PI state
while sharing the same target temperature.

Configuration is read from config.json in the same directory.
"""

import json
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from pynvml import (
    nvmlInit,
    nvmlShutdown,
    nvmlDeviceGetHandleByIndex,
    nvmlDeviceGetCount,
    nvmlDeviceGetTemperature,
    nvmlDeviceGetNumFans,
    nvmlDeviceSetFanSpeed_v2,
    nvmlDeviceGetName,
    nvmlSystemGetDriverVersion,
    NVML_TEMPERATURE_GPU,
)

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.json"

# Timing
INTERVAL = 3  # seconds between samples
EMA_ALPHA = 0.15  # smoothing factor (~40 second effective window)

# PI Controller gains
Kp = 2.0  # Proportional gain: how aggressively to respond to current error
Ki = 0.1  # Integral gain: how quickly to adapt to ambient conditions

# Integral windup limits (prevents runaway accumulation)
INTEGRAL_MIN = -20
INTEGRAL_MAX = 20

# Fan speed limits (percentage)
MIN_FAN_SPEED = 30
MAX_FAN_SPEED = 100

# Baseline fan curve: (temperature °C, fan speed %)
# This provides gradual ramping regardless of target temperature
BASELINE_CURVE = [
    (40, 30),
    (50, 35),
    (60, 40),
    (70, 50),
    (75, 60),
    (80, 70),
    (85, 80),
    (90, 95),
]


def get_baseline_fan_speed(temp: float) -> float:
    """
    Interpolate baseline fan speed from the curve.
    Temperatures below/above the curve are clamped to the endpoints.
    """
    if temp <= BASELINE_CURVE[0][0]:
        return BASELINE_CURVE[0][1]
    if temp >= BASELINE_CURVE[-1][0]:
        return BASELINE_CURVE[-1][1]

    # Find the two points to interpolate between
    for i in range(len(BASELINE_CURVE) - 1):
        t1, f1 = BASELINE_CURVE[i]
        t2, f2 = BASELINE_CURVE[i + 1]
        if t1 <= temp <= t2:
            # Linear interpolation
            ratio = (temp - t1) / (t2 - t1)
            return f1 + ratio * (f2 - f1)

    return BASELINE_CURVE[-1][1]


def load_config() -> dict:
    """Load configuration from JSON file."""
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))


@dataclass
class GpuState:
    """Per-GPU state for the PI controller."""
    index: int
    handle: object
    name: str
    num_fans: int
    smoothed_temp: float = None
    integral: float = 0.0
    last_fan_speed: int = 0


class GpuTempController:
    def __init__(self, target_temp: float):
        self.target_temp = target_temp
        self.gpus: list[GpuState] = []
        self.running = True

    def initialize(self):
        """Initialize NVML and discover all GPUs."""
        nvmlInit()

        driver_version = nvmlSystemGetDriverVersion()
        gpu_count = nvmlDeviceGetCount()

        print(f"GPU Target Temperature Service started", flush=True)
        print(f"Driver: {driver_version}", flush=True)
        print(f"GPUs detected: {gpu_count}", flush=True)
        print(f"Target temperature: {self.target_temp}°C", flush=True)
        print(f"Sample interval: {INTERVAL}s, EMA alpha: {EMA_ALPHA}", flush=True)
        print("-" * 60, flush=True)

        # Initialize state for each GPU
        for i in range(gpu_count):
            handle = nvmlDeviceGetHandleByIndex(i)
            name = nvmlDeviceGetName(handle)
            num_fans = nvmlDeviceGetNumFans(handle)

            gpu = GpuState(
                index=i,
                handle=handle,
                name=name,
                num_fans=num_fans,
            )
            self.gpus.append(gpu)

            print(f"  GPU {i}: {name} ({num_fans} fan{'s' if num_fans != 1 else ''})", flush=True)

        print("-" * 60, flush=True)

    def shutdown(self):
        """Clean shutdown of NVML."""
        self.running = False
        print("Shutting down GPU temperature service...", flush=True)
        nvmlShutdown()

    def update_target(self, new_target: float):
        """Update target temperature (for config reload)."""
        self.target_temp = new_target
        print(f"Target temperature updated to {new_target}°C", flush=True)

    def set_fan_speed(self, gpu: GpuState, speed: int):
        """Set fan speed for all fans on a GPU."""
        for fan_idx in range(gpu.num_fans):
            try:
                nvmlDeviceSetFanSpeed_v2(gpu.handle, fan_idx, speed)
            except Exception as e:
                print(f"Warning: GPU {gpu.index} fan {fan_idx} control failed: {e}", flush=True)

    def step_gpu(self, gpu: GpuState) -> dict:
        """
        Perform one control loop iteration for a single GPU.
        Returns a dict with current state for logging.
        """
        # Read current temperature
        current_temp = nvmlDeviceGetTemperature(gpu.handle, NVML_TEMPERATURE_GPU)

        # Apply EMA smoothing
        if gpu.smoothed_temp is None:
            gpu.smoothed_temp = float(current_temp)
        else:
            gpu.smoothed_temp = (
                EMA_ALPHA * current_temp + (1 - EMA_ALPHA) * gpu.smoothed_temp
            )

        # Get baseline fan speed from curve
        baseline = get_baseline_fan_speed(gpu.smoothed_temp)

        # Calculate error (positive = too hot, negative = too cold)
        error = gpu.smoothed_temp - self.target_temp

        # PI controller
        p_term = Kp * error
        gpu.integral += Ki * error * INTERVAL
        gpu.integral = clamp(gpu.integral, INTEGRAL_MIN, INTEGRAL_MAX)

        # Calculate final fan speed
        fan_speed = baseline + p_term + gpu.integral
        fan_speed = clamp(fan_speed, MIN_FAN_SPEED, MAX_FAN_SPEED)
        fan_speed_int = int(round(fan_speed))

        # Apply fan speed
        self.set_fan_speed(gpu, fan_speed_int)
        gpu.last_fan_speed = fan_speed_int

        return {
            "gpu_index": gpu.index,
            "current_temp": current_temp,
            "smoothed_temp": round(gpu.smoothed_temp, 1),
            "target_temp": self.target_temp,
            "error": round(error, 1),
            "baseline": round(baseline, 1),
            "p_term": round(p_term, 1),
            "integral": round(gpu.integral, 1),
            "fan_speed": fan_speed_int,
        }

    def step(self) -> list[dict]:
        """
        Perform one control loop iteration for all GPUs.
        Returns a list of state dicts for logging.
        """
        results = []
        for gpu in self.gpus:
            try:
                state = self.step_gpu(gpu)
                results.append(state)
            except Exception as e:
                print(f"Error controlling GPU {gpu.index}: {e}", flush=True)
        return results

    def run(self):
        """Main control loop."""
        while self.running:
            states = self.step()

            # Log all GPU states
            for state in states:
                print(
                    f"GPU {state['gpu_index']}: "
                    f"Temp: {state['current_temp']}°C (smoothed: {state['smoothed_temp']}°C) | "
                    f"Target: {state['target_temp']}°C | "
                    f"Error: {state['error']:+.1f}°C | "
                    f"Fan: {state['fan_speed']}% (base: {state['baseline']:.0f}%, "
                    f"P: {state['p_term']:+.1f}, I: {state['integral']:+.1f})",
                    flush=True,
                )

            time.sleep(INTERVAL)


def main():
    # Load configuration
    try:
        config = load_config()
        target_temp = float(config["target_temp"])
    except FileNotFoundError:
        print(f"Error: Config file not found at {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"Error: Invalid config file: {e}", file=sys.stderr)
        sys.exit(1)

    # Create controller
    controller = GpuTempController(target_temp)

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}", flush=True)
        controller.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Set up SIGHUP handler for config reload
    def reload_handler(signum, frame):
        print("Received SIGHUP, reloading config...", flush=True)
        try:
            config = load_config()
            controller.update_target(float(config["target_temp"]))
        except Exception as e:
            print(f"Error reloading config: {e}", flush=True)

    signal.signal(signal.SIGHUP, reload_handler)

    # Initialize and run
    try:
        controller.initialize()
        controller.run()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            nvmlShutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
