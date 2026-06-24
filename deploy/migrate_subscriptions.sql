-- =============================================================================
-- Heimdall — migração: novas colunas de assinatura (saldo/origem/ref externa)
-- Aplicada automaticamente no boot; este arquivo é para execução manual se
-- preferir: sudo mysql heimdall < deploy/migrate_subscriptions.sql
-- (MariaDB suporta ADD COLUMN IF NOT EXISTS — idempotente.)
-- =============================================================================
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS balance      NUMERIC(14,2) NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS source       VARCHAR(10) DEFAULT 'manual';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS external_ref VARCHAR(160) NULL;
