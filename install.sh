#!/usr/bin/env bash
set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "${BLUE}==>${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}ok${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}warn${NC} %s\n" "$1"; }
die()   { printf "${RED}error${NC} %s\n" "$1"; exit 1; }
step()  { printf "\n${BOLD}%s${NC}\n" "$1"; }

INSTALL_DIR="${WORKBOOK_CLI_DIR:-${HOME}/.local/lib/workbook-cli}"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/workbook-cli"
CONFIG_FILE="${CONFIG_DIR}/.env"
REPO_URL="${WORKBOOK_CLI_REPO:-https://github.com/rossmeyerza/workbook-cli.git}"
FORCE_RECONFIGURE=false

for arg in "$@"; do
  case "$arg" in
    --reconfigure|--reconfig) FORCE_RECONFIGURE=true ;;
  esac
done

printf "\n${BOLD}workbook-cli installer${NC}\n"
printf "Install dir: %s\n\n" "$INSTALL_DIR"

step "Checking prerequisites"
command -v python3 >/dev/null 2>&1 || die "python3 is required."
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
  die "Python 3.12+ is required. Found Python ${PY_VERSION}."
fi
ok "Python ${PY_VERSION}"
command -v git >/dev/null 2>&1 || die "git is required."
ok "git $(git --version | awk '{print $3}')"

mkdir -p "$BIN_DIR" "$(dirname "$INSTALL_DIR")" "$CONFIG_DIR"

step "Fetching workbook-cli"
if [ -d "${INSTALL_DIR}/.git" ]; then
  info "Pulling latest changes..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  info "Cloning repository..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
ok "Source ready"

step "Installing dependencies"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -e "$INSTALL_DIR"
"${INSTALL_DIR}/.venv/bin/python" -m playwright install chromium --quiet 2>/dev/null || \
  "${INSTALL_DIR}/.venv/bin/python" -m playwright install chromium
ok "Python packages and Playwright Chromium installed"

ln -sf "${INSTALL_DIR}/.venv/bin/workbook-cli" "${BIN_DIR}/workbook-cli"
ok "workbook-cli linked to ${BIN_DIR}/workbook-cli"

env_value() {
  local key="$1"
  if [ -f "$CONFIG_FILE" ]; then
    awk -F= -v k="$key" '$1 == k { sub(/^[^=]+=/, ""); print; exit }' "$CONFIG_FILE"
  fi
}

WORKBOOK_URL_CURRENT="$(env_value WORKBOOK_URL || true)"
WORKBOOK_EMAIL_CURRENT="$(env_value WORKBOOK_EMAIL || true)"
WORKBOOK_PASSWORD_CURRENT="$(env_value WORKBOOK_PASSWORD || true)"

NEEDS_CONFIG=false
[ "$FORCE_RECONFIGURE" = true ] && NEEDS_CONFIG=true
[ ! -f "$CONFIG_FILE" ] && NEEDS_CONFIG=true
[ -z "$WORKBOOK_EMAIL_CURRENT" ] && NEEDS_CONFIG=true
[ -z "$WORKBOOK_PASSWORD_CURRENT" ] && NEEDS_CONFIG=true

if [ "$NEEDS_CONFIG" = true ]; then
  step "Configuration"
  printf "workbook-cli needs your Workbook/Okta email and password.\n"
  printf "These are stored only in %s with mode 600.\n\n" "$CONFIG_FILE"
  if ! exec 3</dev/tty; then
    warn "No interactive terminal is available, so configuration was not written."
    warn "Run this later from a terminal:"
    warn "  workbook-cli config init --email you@company.com --password 'your-password'"
    warn "Or rerun: ${INSTALL_DIR}/install.sh --reconfigure"
    NEEDS_CONFIG=false
  else
  printf "WORKBOOK_URL [%s]: " "${WORKBOOK_URL_CURRENT:-https://wunderman.workbook.dk}"
  read -r WORKBOOK_URL <&3
  WORKBOOK_URL="${WORKBOOK_URL:-${WORKBOOK_URL_CURRENT:-https://wunderman.workbook.dk}}"

  while true; do
    if [ -n "$WORKBOOK_EMAIL_CURRENT" ]; then
      printf "WORKBOOK_EMAIL [%s]: " "$WORKBOOK_EMAIL_CURRENT"
      read -r WORKBOOK_EMAIL_INPUT <&3
      WORKBOOK_EMAIL="${WORKBOOK_EMAIL_INPUT:-$WORKBOOK_EMAIL_CURRENT}"
    else
      printf "WORKBOOK_EMAIL: "
      read -r WORKBOOK_EMAIL <&3
    fi
    echo "$WORKBOOK_EMAIL" | grep -qE '^[^@]+@[^@]+\.[^@]+$' && break
    printf "Please enter a valid email address.\n"
  done

  while true; do
    printf "WORKBOOK_PASSWORD (input hidden): "
    stty -echo <&3
    read -r WORKBOOK_PASSWORD <&3
    stty echo <&3
    printf "\n"
    [ -n "$WORKBOOK_PASSWORD" ] && break
    printf "Password cannot be empty.\n"
  done

  exec 3<&-
  cat > "$CONFIG_FILE" << EOF
WORKBOOK_URL=${WORKBOOK_URL}
WORKBOOK_EMAIL=${WORKBOOK_EMAIL}
WORKBOOK_PASSWORD=${WORKBOOK_PASSWORD}
EOF
  chmod 600 "$CONFIG_FILE"
  ok "Config written"
  fi
else
  ok "Config already exists; use --reconfigure to rewrite"
fi

if ! echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
  warn "${BIN_DIR} is not in your PATH."
  warn "Add: export PATH=\"${BIN_DIR}:\$PATH\""
fi

printf "\n${GREEN}${BOLD}workbook-cli installed successfully.${NC}\n"
printf "Run: workbook-cli auth\n\n"
