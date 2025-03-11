#!/bin/bash

set -e  # Exit if any command fails

SERVICE_NAME="greenhouse-sensor"
INSTALL_DIR="/opt/$SERVICE_NAME"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

echo "🚀 Installing Greenhouse Sensor Monitoring Service..."

# Ensure running as root
if [[ $EUID -ne 0 ]]; then
    echo "❌ Please run as root (or use sudo)."
    exit 1
fi

# Check if service already exists and remove it
if systemctl list-units --full --all | grep -q "$SERVICE_NAME.service"; then
    echo "🛑 Stopping and disabling existing service..."
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" || true
    rm -f "$SERVICE_FILE"
fi

# Remove previous installation if exists
if [[ -d "$INSTALL_DIR" ]]; then
    echo "🧹 Removing old installation..."
    rm -rf "$INSTALL_DIR"
fi

# Create install directory
echo "📂 Creating $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy script and requirements file
echo "📄 Copying files..."
cp sensor_monitor.py requirements.txt "$INSTALL_DIR"

# Set correct permissions
chown -R plant:plant "$INSTALL_DIR"  # Change user if necessary
chmod +x "$INSTALL_DIR/sensor_monitor.py"

# Create Python virtual environment
echo "🐍 Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

# Deactivate virtualenv
deactivate

# Create systemd service file
echo "⚙️ Creating systemd service..."
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Greenhouse Sensor Monitoring
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/sensor_monitor.py
WorkingDirectory=$INSTALL_DIR
Restart=always
User=plant
Group=plant
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable and start the service
echo "🔄 Reloading systemd..."
systemctl daemon-reload
echo "✅ Enabling $SERVICE_NAME service..."
systemctl enable "$SERVICE_NAME"
echo "▶️ Starting $SERVICE_NAME service..."
systemctl start "$SERVICE_NAME"

echo "🎉 Installation complete! Service is now running."
echo "📋 Check logs with: journalctl -u $SERVICE_NAME -f"
