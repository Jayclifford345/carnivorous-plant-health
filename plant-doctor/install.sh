#!/bin/bash

set -e  # Exit if any command fails

SERVICE_NAME="plant-doctor"
INSTALL_DIR="/opt/$SERVICE_NAME"
VENV_DIR="$INSTALL_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
ENV_FILE="$INSTALL_DIR/.env"

echo "🌱 Installing Plant Doctor Service..."

# Ensure running as root
if [[ $EUID -ne 0 ]]; then
    echo "❌ Please run as root (or use sudo)."
    exit 1
fi

# Check for OpenAI API token in AI_TOKEN environment variable
if [ -n "$AI_TOKEN" ]; then
    echo "✅ Found OpenAI API token in AI_TOKEN environment variable"
    OPENAI_API_KEY="$AI_TOKEN"
elif [ -n "$OPENAI_API_KEY" ]; then
    echo "✅ Found OpenAI API key in OPENAI_API_KEY environment variable"
    # Keep using OPENAI_API_KEY as is
else
    echo "⚠️ No OpenAI API token found in environment variables."
    echo "Please set your OpenAI API token with: export AI_TOKEN=your_token_here"
    echo "Or: export OPENAI_API_KEY=your_token_here"
    echo "Then run this script again."
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
mkdir -p "$INSTALL_DIR/images"
mkdir -p "$INSTALL_DIR/templates"

# Copy application files
echo "📄 Copying files..."
cp main.py requirements.txt "$INSTALL_DIR"
cp -r templates/* "$INSTALL_DIR/templates/"

# Store the OpenAI API token securely
echo "🔐 Storing OpenAI API token securely..."
echo "OPENAI_API_KEY=$OPENAI_API_KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"  # Only readable by owner

# Clear the environment variables for security
echo "🧹 Clearing API tokens from environment for security..."
if [ -n "$AI_TOKEN" ]; then
    unset AI_TOKEN
fi
if [ -n "$OPENAI_API_KEY" ]; then
    unset OPENAI_API_KEY
fi

# Set correct permissions
echo "🔒 Setting file permissions..."
chown -R plant:plant "$INSTALL_DIR"  # Change user if necessary
chmod +x "$INSTALL_DIR/main.py"

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
Description=Plant Doctor - AI Plant Health Analysis
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/main.py
WorkingDirectory=$INSTALL_DIR
Restart=always
User=plant
Group=plant
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=$ENV_FILE

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
echo "🌐 Access the web interface at: http://$(hostname):5000"
echo ""
echo "⚠️  IMPORTANT: For security, your OpenAI API token has been stored in $ENV_FILE"
echo "   and removed from environment variables." 