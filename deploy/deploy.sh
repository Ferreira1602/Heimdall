#!/usr/bin/env bash
# =============================================================================
# Heimdall — script de implantação em Ubuntu + Apache + MariaDB
# Execute como root:  sudo bash deploy/deploy.sh
# Idempotente: pode ser executado novamente sem quebrar instalação existente.
# =============================================================================
set -euo pipefail

APP_DIR="/var/www/heimdall"
SERVER_IP="10.250.128.114"
SSL_DIR="/etc/apache2/ssl"
DB_NAME="heimdall"
DB_USER="heimdall"
DB_PASS="Heimdall@2025!"

echo "==> [1/9] Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
    apache2 libapache2-mod-wsgi-py3 \
    mariadb-server \
    python3 python3-venv python3-dev \
    build-essential default-libmysqlclient-dev pkg-config \
    openssl unzip

echo "==> [2/9] MariaDB ativo"
systemctl enable --now mariadb

echo "==> [3/9] Banco de dados e usuário"
mysql <<SQL
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
CREATE USER IF NOT EXISTS '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

echo "==> [4/9] Copiando aplicação para ${APP_DIR}"
mkdir -p "${APP_DIR}"
# Assume que este script roda de dentro da pasta extraída do projeto:
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rsync -a --exclude 'venv' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude 'smoke_test*.py' "${SRC}/" "${APP_DIR}/"

echo "==> [5/9] Virtualenv + dependências"
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> [6/9] Variáveis de ambiente (gera FERNET_KEY se não existir)"
ENV_FILE="/etc/apache2/envvars"
FERNET_KEY="$("${APP_DIR}/venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
SECRET_KEY="$(openssl rand -hex 32)"
# Remove definições antigas e regrava
sed -i '/HEIMDALL_/d' "${ENV_FILE}"
cat >> "${ENV_FILE}" <<EOF

# ---- Heimdall ----
export HEIMDALL_SECRET_KEY="${SECRET_KEY}"
export HEIMDALL_FERNET_KEY="${FERNET_KEY}"
export HEIMDALL_DB_USER="${DB_USER}"
export HEIMDALL_DB_PASS="${DB_PASS}"
export HEIMDALL_DB_HOST="127.0.0.1"
export HEIMDALL_DB_PORT="3306"
export HEIMDALL_DB_NAME="${DB_NAME}"
export HEIMDALL_ADMIN_EMAIL="admin@heimdall.local"
export HEIMDALL_ADMIN_PASS="Heimdall@2025!"
export HEIMDALL_INGEST_TOKEN="$(openssl rand -hex 24)"
EOF

echo "==> [7/9] Certificado SSL autoassinado (CN=${SERVER_IP})"
mkdir -p "${SSL_DIR}"
if [ ! -f "${SSL_DIR}/heimdall.crt" ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "${SSL_DIR}/heimdall.key" \
    -out    "${SSL_DIR}/heimdall.crt" \
    -subj   "/C=BR/ST=SP/L=Sao Paulo/O=Heimr/OU=Heimdall/CN=${SERVER_IP}" \
    -addext "subjectAltName=IP:${SERVER_IP}"
  chmod 600 "${SSL_DIR}/heimdall.key"
fi

echo "==> [8/9] Apache: módulos, vhost e permissões"
a2enmod ssl wsgi headers rewrite >/dev/null
cp "${APP_DIR}/deploy/apache_vhost.conf" /etc/apache2/sites-available/heimdall.conf
a2dissite 000-default.conf >/dev/null 2>&1 || true
a2ensite heimdall.conf >/dev/null
chown -R www-data:www-data "${APP_DIR}"

echo "==> [9/9] Inicializa o banco e reinicia o Apache"
# Carrega as envvars e cria as tabelas + admin inicial
set -a; . "${ENV_FILE}"; set +a
"${APP_DIR}/venv/bin/python" -c "from app import create_app; create_app('production')"
apache2ctl configtest
systemctl restart apache2

echo "==> [extra] Agendador de coletas (systemd timer)"
cp "${APP_DIR}/deploy/heimdall-scheduler.service" /etc/systemd/system/heimdall-scheduler.service
cp "${APP_DIR}/deploy/heimdall-scheduler.timer"   /etc/systemd/system/heimdall-scheduler.timer
systemctl daemon-reload
systemctl enable --now heimdall-scheduler.timer

echo
echo "============================================================"
echo " Heimdall implantado com sucesso!"
echo " Acesse:  https://${SERVER_IP}/"
echo " Login:   admin@heimdall.local"
echo " Senha:   Heimdall@2025!  (altere após o primeiro acesso)"
echo "============================================================"
