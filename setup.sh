#!/bin/bash
#
# GPU Target Temperature Service - Setup Script
#
# This script:
# - Ensures uv is available
# - Syncs the Python environment (.venv) from pyproject.toml
# - Sets up or reconfigures the systemd service
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
SERVICE_NAME="gpu-target-temp"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_FILE="$SCRIPT_DIR/config.json"
PYTHON_SCRIPT="$SCRIPT_DIR/gpu_temp_service.py"

echo "=========================================="
echo "  GPU Target Temperature Service Setup"
echo "=========================================="
echo ""

# Check if running as root for systemd operations
check_sudo() {
    if ! sudo -n true 2>/dev/null; then
        echo "This script requires sudo access for systemd operations."
        echo "You may be prompted for your password."
        echo ""
    fi
}

# Locate uv, installing it for the current user if missing
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"
        return
    fi

    if [ -x "$HOME/.local/bin/uv" ]; then
        UV_BIN="$HOME/.local/bin/uv"
        return
    fi

    echo "      uv not found, installing to ~/.local/bin..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_BIN="$HOME/.local/bin/uv"

    if [ ! -x "$UV_BIN" ]; then
        echo "Error: uv installation failed. Install it manually from https://docs.astral.sh/uv/" >&2
        exit 1
    fi
}

# Sync the project environment using uv
setup_env() {
    echo "[1/3] Syncing Python environment with uv..."
    ensure_uv
    # Pin the venv to ./.venv so the systemd unit has a stable path,
    # regardless of any user-level UV_PROJECT_ENVIRONMENT override.
    (cd "$SCRIPT_DIR" && UV_PROJECT_ENVIRONMENT="$VENV_DIR" "$UV_BIN" sync --quiet)
    echo "      Environment ready at $VENV_DIR"
}

# Prompt for target temperature
prompt_target_temp() {
    local current_target="$1"
    local prompt_msg

    if [ -n "$current_target" ]; then
        prompt_msg="Enter target temperature in °C (current: ${current_target}, press Enter to keep): "
    else
        prompt_msg="Enter target temperature in °C (e.g., 80): "
    fi

    while true; do
        read -p "$prompt_msg" input_temp

        # If empty and we have a current value, keep it
        if [ -z "$input_temp" ] && [ -n "$current_target" ]; then
            echo "$current_target"
            return 0
        fi

        # Validate input is a number up to 95
        if [[ "$input_temp" =~ ^[0-9]+$ ]] && [ "$input_temp" -ge 1 ] && [ "$input_temp" -le 95 ]; then
            echo "$input_temp"
            return 0
        else
            echo "      Please enter a valid temperature between 1 and 95°C."
        fi
    done
}

# Default fan curve: [temperature, fan_speed] pairs
DEFAULT_FAN_CURVE='[[35, 30], [90, 100]]'

# Create or update config file
update_config() {
    local target_temp="$1"

    # Preserve existing fan_curve if present, otherwise use default
    if [ -f "$CONFIG_FILE" ]; then
        existing_curve=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(json.dumps(c.get('fan_curve', $DEFAULT_FAN_CURVE)))" 2>/dev/null || echo "$DEFAULT_FAN_CURVE")
    else
        existing_curve="$DEFAULT_FAN_CURVE"
    fi

    echo "{\"target_temp\": $target_temp, \"fan_curve\": $existing_curve}" > "$CONFIG_FILE"
    echo "      Configuration saved: target_temp = ${target_temp}°C"
}

# Create systemd service file
create_service_file() {
    local service_content="[Unit]
Description=GPU Target Temperature Service
After=network.target nvidia-persistenced.service
Wants=nvidia-persistenced.service

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/python3 $PYTHON_SCRIPT
WorkingDirectory=$SCRIPT_DIR
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Reload config on SIGHUP
ExecReload=/bin/kill -HUP \$MAINPID

[Install]
WantedBy=multi-user.target"

    echo "$service_content" | sudo tee "$SERVICE_FILE" > /dev/null
}

# Main setup logic
main() {
    check_sudo
    setup_env

    # Check if service already exists and is active
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        # Service exists and is running
        echo "[2/3] Service is currently running."

        # Get current target temp
        if [ -f "$CONFIG_FILE" ]; then
            current_target=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['target_temp'])" 2>/dev/null || echo "")
        fi

        echo ""
        new_target=$(prompt_target_temp "$current_target")

        update_config "$new_target"
        echo "[3/3] Reloading service configuration..."
        sudo systemctl reload "$SERVICE_NAME"
        echo "      Service reloaded."

    elif systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
        # Service exists but is not running
        echo "[2/3] Service exists but is not running."

        # Get current target temp if config exists
        current_target=""
        if [ -f "$CONFIG_FILE" ]; then
            current_target=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['target_temp'])" 2>/dev/null || echo "")
        fi

        echo ""
        new_target=$(prompt_target_temp "$current_target")
        update_config "$new_target"

        echo "[3/3] Starting service..."
        sudo systemctl start "$SERVICE_NAME"
        echo "      Service started."

    else
        # Service doesn't exist - fresh install
        echo "[2/3] Setting up new service..."
        echo ""

        target_temp=$(prompt_target_temp "")
        update_config "$target_temp"

        echo "[3/3] Installing systemd service..."
        create_service_file

        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"
        sudo systemctl start "$SERVICE_NAME"

        echo "      Service installed, enabled, and started."
    fi

    echo ""
    echo "=========================================="
    echo "  Setup Complete!"
    echo "=========================================="
    echo ""
    echo "Useful commands:"
    echo "  View logs:      journalctl -u $SERVICE_NAME -f"
    echo "  Check status:   systemctl status $SERVICE_NAME"
    echo "  Restart:        sudo systemctl restart $SERVICE_NAME"
    echo "  Stop:           sudo systemctl stop $SERVICE_NAME"
    echo "  Reconfigure:    ./setup.sh"
    echo ""
}

main
