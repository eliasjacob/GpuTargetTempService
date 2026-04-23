# GpuTargetTempService

A systemd service that maintains NVIDIA GPUs at a target temperature using a PI controller with automatic fan speed adjustment.

## Why

I recently purchased a RTX Pro 6000 Blackwell Max-Q, and noticed it would target 86°C no matter the ambient temperature. I found [this](https://www.reddit.com/r/buildapc/comments/1lqzdjj/cooling_the_nvidia_rtx_pro_6000_blackwell_how_can/) thread where someone mentioned NVIDIA recommended to keep the temperature below 85°C, so I created this tool to be able to set a new target temperature.

## Requirements

- Linux (I'm personally using this on my Proxmox VE 9.1.4 homelab, inside an Ubuntu 24.04 Server VM, minimal install)
- Compatible driver (I've tested both `nvidia-driver-580-open` and `nvidia-driver-590-open`)
- [uv](https://docs.astral.sh/uv/) (the setup script will install it for the current user if missing)

## Quick Start

```bash
git clone https://github.com/eliasjacob/GpuTargetTempService.git
cd GpuTargetTempService
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Ensure `uv` is installed
2. Sync the Python environment (`.venv`) from `pyproject.toml`
3. Prompt for your target temperature
4. Install and start the systemd service

To manage dependencies manually:

```bash
uv sync              # install/update dependencies into .venv
uv add <package>     # add a new dependency
uv run gpu_temp_service.py   # run the service against the synced env
```

## Changing Target Temperature

Run the setup script again:

```bash
./setup.sh
```

Enter a new temperature when prompted. The service will reload without restart.

## Configuration

Config is stored in `config.json`. The same `target_temp` and `fan_curve` are applied to **every** NVIDIA GPU detected on the system (each GPU runs its own independent PI controller against the shared target).

```json
{
  "target_temp": 80,
  "fan_curve": [[35, 30], [90, 100]]
}
```

### Target Temperature

The temperature (in °C) that the service will try to maintain. Valid range: 1-95°C.

### Fan Curve (Optional)

The baseline fan curve as `[temperature, fan_speed]` pairs. The service interpolates between these points to determine the minimum fan speed at any given temperature. The PI controller adjusts on top of this baseline.

The example above ramps from 30% fan at 35°C to 100% fan at 90°C — an aggressive curve that gives the controller plenty of headroom to hold the target temperature. This is also the built-in default used when `fan_curve` is omitted from `config.json`.

Changes to the config file are applied when you run `./setup.sh` again, or simply reload the service:
```bash
sudo systemctl reload gpu-target-temp
```

## Credits

This is a fork of [m0nsky/GpuTargetTempService](https://github.com/m0nsky/GpuTargetTempService) — all credit for the original PI controller, fan-curve design, and systemd packaging goes to [@m0nsky](https://github.com/m0nsky). This fork adds:

- `uv`-based dependency management (`pyproject.toml` + `uv.lock`) in place of the original `venv` + `pip` setup
- A more aggressive default fan curve (`[[35, 30], [90, 100]]`)

The "Why" section above is preserved from the upstream README.

## License

MIT (inherited from the upstream project)
