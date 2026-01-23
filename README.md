# GpuTargetTempService

A systemd service that maintains NVIDIA GPUs at a target temperature using a PI controller with automatic fan speed adjustment.

## Why

I recently purchased a RTX Pro 6000 Blackwell MaxQ, and noticed it would target 86c regardless of ambient temperature. When the ambient temperature was lower, the GPU temp would climb to 86c and maintain low fan speeds, and when ambient temperatures increased, it would also climb to 86c, but maintain higher fan speeds. This seemed a little high to me, and after reading [this](https://www.reddit.com/r/buildapc/comments/1lqzdjj/cooling_the_nvidia_rtx_pro_6000_blackwell_how_can/) thread, I thought it would be better to maintain a GPU temperature below 85c, since I don't think these cards are that loud anyways. I'm using the MaxQ (blower fan) and even at 75% fan speed (the fan speed it's currently running at to maintain 80c) the sound level is perfectly acceptable for me.

This service lets you set a lower target temperature (e.g., 80C) and automatically adjusts fan speeds to maintain it, regardless of ambient temperature or workload.

## Requirements

- Linux with systemd
- NVIDIA GPU (tested with driver 580.95, which I installed as `nvidia-driver-580-open`)
- Python 3.8+

## Quick Start

```bash
git clone https://github.com/yourusername/GpuTargetTempService.git
cd GpuTargetTempService
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Create a Python virtual environment
2. Install nvidia-ml-py
3. Prompt for your target temperature (50-95C)
4. Install and start the systemd service

## Changing Target Temperature

Run the setup script again:

```bash
./setup.sh
```

Enter a new temperature when prompted. The service will reload without restart.

## Useful Commands

```bash
# View live logs
journalctl -u gpu-target-temp -f

# Check service status
systemctl status gpu-target-temp

# Restart service
sudo systemctl restart gpu-target-temp

# Stop service
sudo systemctl stop gpu-target-temp

# Disable service (won't start on boot)
sudo systemctl disable gpu-target-temp
```

## Extra info

The service uses a PI (Proportional-Integral) controller:

1. **Baseline fan curve**: Fans ramp gradually with temperature (30% at 40C to 95% at 90C), preventing sudden jumps from idle
2. **PI adjustment**: Fine-tunes fan speed to hit the exact target temperature
3. **EMA smoothing**: Smooths temperature readings over ~40 seconds to avoid reacting to brief spikes
4. **Integral term**: Adapts to ambient temperature changes over time

Samples temperature every 3 seconds. Supports multiple GPUs (each controlled independently with shared target temperature).

## Configuration

Config is stored in `config.json`:

```json
{"target_temp": 80}
```

## Files

- `setup.sh` - Installation and configuration script
- `gpu_temp_service.py` - The service itself
- `config.json` - Target temperature (created by setup.sh)

## Tested Hardware

- NVIDIA RTX PRO 6000 Blackwell Max-Q (driver 580.95, Ubuntu 24.04 VM, on my Proxmox VE 9.1.4 homelab)

## License

MIT
