-- =============================================================================
-- Heimdall — criação do banco e do usuário no MariaDB/MySQL local
-- Uso: sudo mysql < /var/www/heimdall/deploy/schema.sql
-- As tabelas são criadas automaticamente pela aplicação (db.create_all) no
-- primeiro boot; aqui só preparamos o database, o usuário e as permissões.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS heimdall
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Usuário da aplicação (acesso somente local 127.0.0.1).
-- IMPORTANTE: a senha deve ser idêntica à variável HEIMDALL_DB_PASS do ambiente.
CREATE USER IF NOT EXISTS 'heimdall'@'localhost'  IDENTIFIED BY 'Heimdall@2025!';
CREATE USER IF NOT EXISTS 'heimdall'@'127.0.0.1'  IDENTIFIED BY 'Heimdall@2025!';

GRANT ALL PRIVILEGES ON heimdall.* TO 'heimdall'@'localhost';
GRANT ALL PRIVILEGES ON heimdall.* TO 'heimdall'@'127.0.0.1';

FLUSH PRIVILEGES;
