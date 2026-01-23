#!/usr/bin/env python3
"""
GPU Target Temperature Service

Uses a smoothed PI controller with a baseline fan curve to maintain
a target GPU temperature regardless of ambient conditions.

Configuration is read from config.json in the same directory.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path

from pynvml import (
    nvmlInit,
    nvmlShutdown,
    nvmlDeviceGetHandleByIndex,
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


class GpuTempController:
    def __init__(self, target_temp: float):
        self.target_temp = target_temp
        self.smoothed_temp = None
        self.integral = 0.0
        self.handle = None
        self.num_fans = 0
        self.running = True

    def initialize(self):
        """Initialize NVML and get GPU handle."""
        nvmlInit()
        self.handle = nvmlDeviceGetHandleByIndex(0)
        self.num_fans = nvmlDeviceGetNumFans(self.handle)

        gpu_name = nvmlDeviceGetName(self.handle)
        driver_version = nvmlSystemGetDriverVersion()

        print(f"GPU Target Temperature Service started", flush=True)
        print(f"Driver: {driver_version}", flush=True)
        print(f"GPU: {gpu_name}", flush=True)
        print(f"Fans detected: {self.num_fans}", flush=True)
        print(f"Target temperature: {self.target_temp}°C", flush=True)
        print(f"Sample interval: {INTERVAL}s, EMA alpha: {EMA_ALPHA}", flush=True)

    def shutdown(self):
        """Clean shutdown of NVML."""
        self.running = False
        print("Shutting down GPU temperature service...", flush=True)
        nvmlShutdown()

    def update_target(self, new_target: float):
        """Update target temperature (for config reload)."""
        self.target_temp = new_target
        print(f"Target temperature updated to {new_target}°C", flush=True)

    def set_fan_speed(self, speed: int):
        """Set fan speed for all fans."""
        for fan_idx in range(self.num_fans):
            try:
                nvmlDeviceSetFanSpeed_v2(self.handle, fan_idx, speed)
            except Exception as e:
                print(f"Warning: Failed to set fan {fan_idx} speed: {e}", flush=True)

    def step(self) -> dict:
        """
        Perform one control loop iteration.
        Returns a dict with current state for logging.
        """
        # Read current temperature
        current_temp = nvmlDeviceGetTemperature(self.handle, NVML_TEMPERATURE_GPU)

        # Apply EMA smoothing
        if self.smoothed_temp is None:
            self.smoothed_temp = float(current_temp)
        else:
            self.smoothed_temp = (
                EMA_ALPHA * current_temp + (1 - EMA_ALPHA) * self.smoothed_temp
            )

        # Get baseline fan speed from curve
        baseline = get_baseline_fan_speed(self.smoothed_temp)

        # Calculate error (positive = too hot, negative = too cold)
        error = self.smoothed_temp - self.target_temp

        # PI controller
        p_term = Kp * error
        self.integral += Ki * error * INTERVAL
        self.integral = clamp(self.integral, INTEGRAL_MIN, INTEGRAL_MAX)

        # Calculate final fan speed
        fan_speed = baseline + p_term + self.integral
        fan_speed = clamp(fan_speed, MIN_FAN_SPEED, MAX_FAN_SPEED)
        fan_speed_int = int(round(fan_speed))

        # Apply fan speed
        self.set_fan_speed(fan_speed_int)

        return {
            "current_temp": current_temp,
            "smoothed_temp": round(self.smoothed_temp, 1),
            "target_temp": self.target_temp,
            "error": round(error, 1),
            "baseline": round(baseline, 1),
            "p_term": round(p_term, 1),
            "integral": round(self.integral, 1),
            "fan_speed": fan_speed_int,
        }

    def run(self):
        """Main control loop."""
        while self.running:
            try:
                state = self.step()
                print(
                    f"Temp: {state['current_temp']}°C (smoothed: {state['smoothed_temp']}°C) | "
                    f"Target: {state['target_temp']}°C | "
                    f"Error: {state['error']:+.1f}°C | "
                    f"Fan: {state['fan_speed']}% (base: {state['baseline']:.0f}%, "
                    f"P: {state['p_term']:+.1f}, I: {state['integral']:+.1f})",
                    flush=True,
                )
            except Exception as e:
                print(f"Error in control loop: {e}", flush=True)

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
