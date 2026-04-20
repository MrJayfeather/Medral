#!/usr/bin/env bash
# Medral VPS setup script — Ubuntu 22.04 / Debian 12
# Run as root or with sudo:  bash deploy/setup_vps.sh
set -e

REPO_URL="https://github.com/MrJayfeather/Medral.git"
APP_DIR="/opt/medral"
SERVICE_USER="medral"

echo "=== Medral VPS Setup ==="

# ---- system packages ----
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git ffmpeg

echo "[ok] System packages installed"

# ---- create service user ----
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "[ok] User '$SERVICE_USER' created"
fi

# ---- clone / update repo ----
if [ -d "$APP_DIR/.git" ]; then
    echo "[info] Repo exists, pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
    echo "[ok] Repo cloned to $APP_DIR"
fi

# ---- virtualenv ----
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --pre -q -r "$APP_DIR/requirements.txt"
echo "[ok] Python venv ready"

# ---- .env ----
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/.env.example" ]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        echo ""
        echo "!!! IMPORTANT: edit $APP_DIR/.env and set DISCORD_TOKEN !!!"
        echo ""
    else
        echo "DISCORD_TOKEN=" > "$APP_DIR/.env"
        echo "[warn] Created empty .env — set DISCORD_TOKEN before starting"
    fi
fi

# ---- permissions ----
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# ---- install systemd service ----
cp "$APP_DIR/deploy/medral.service" /etc/systemd/system/medral.service
systemctl daemon-reload
systemctl enable medral.service
echo "[ok] systemd service installed and enabled"

echo ""
echo "=== Setup complete ==="
echo "1. Edit $APP_DIR/.env — set DISCORD_TOKEN"
echo "2. systemctl start medral"
echo "3. systemctl status medral"
echo "4. journalctl -u medral -f   (follow logs)"
