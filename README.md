# GpuTargetTempService

A systemd service that maintains NVIDIA GPUs at a target temperature using a PI controller with automatic fan speed adjustment.

## Why

I recently purchased a RTX Pro 6000 Blackwell Max-Q, and noticed it would target 86°C no matter the ambient temperature. I found [this](https://www.reddit.com/r/buildapc/comments/1lqzdjj/cooling_the_nvidia_rtx_pro_6000_blackwell_how_can/) thread where someone mentioned NVIDIA recommended to keep the temperature below 85°C, so I created this tool to be able to set a new target temperature.

## Requirements

- Linux (I'm personally using this on my Proxmox VE 9.1.4 homelab, inside an Ubuntu 24.04 Server VM, minimal install)
- Compatible driver (I've tested both `nvidia-driver-580-open` and `nvidia-driver-590-open`)

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
3. Prompt for your target temperature
4. Install and start the systemd service

## Changing Target Temperature

Run the setup script again:

```bash
./setup.sh
```

Enter a new temperature when prompted. The service will reload without restart.

## Configuration

Config is stored in `config.json`:

```json
{"target_temp": 80}
```

## License

MIT
