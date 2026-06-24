# Heimdall — Governança de IA e FinOps Multicloud

> *"Aquele que tudo vigia."* Plataforma de monitoramento de consumo de nuvem e
> de tokens de Inteligência Artificial para IBM Cloud, AWS, Oracle, Google Cloud
> e Microsoft Azure.

Aplicação Flask, totalmente open-source, para rodar em **Ubuntu + Apache (mod_wsgi)**
com banco **MySQL/MariaDB** local.

## Funcionalidades

- **Coleta via API** dos cinco provedores (IBM, AWS, Oracle, Google, Azure), com
  *fallback* para lançamento manual quando a credencial/SDK não estiver disponível.
- **Governança de IA**: cadastro de produtos de IA por conta, monitoramento de
  consumo de tokens e custo, e **estimativa de consumo futuro** (média móvel
  ponderada + regressão linear) com base no histórico do cliente.
- **FinOps Cloud**: visão consolidada da conta com **drill-down de custos** por
  provedor → tipo de recurso → recurso individual.
- **Usuários e permissões**: cada usuário recebe acesso por cliente em nível
  *somente leitura* ou *leitura + gravação*; administradores têm acesso total.
- **Assinaturas**: vigência (início/fim) e créditos restantes por cliente.
- **Dashboard** consolidado e **exportação para Excel**.

## Arquitetura

```
app/
  __init__.py            app-factory, registro de blueprints, filtros
  models.py              User, Client, Subscription, CloudAccount,
                         AIProduct, TokenUsage, BillingRecord, ClientPermission
  crypto.py              criptografia Fernet das credenciais de nuvem
  decorators.py          admin_required, client_read/write_required, audit
  scoping.py             filtragem de clientes por permissão
  blueprints/            auth, dashboard, clients, providers, products,
                         governance, finops, subscriptions, exports, api
  services/
    collectors/          ibm, aws, azure, oracle, google (+ base/factory)
    analytics.py         agregações para dashboard/finops/governança
    estimator.py         estimativa de consumo futuro
    excel.py             geração de planilhas
  templates/, static/    interface (tema claro / fundo branco)
config/settings.py       configuração por ambiente (lê variáveis HEIMDALL_*)
wsgi.py                  ponto de entrada para o mod_wsgi
deploy/                  vhost Apache, schema SQL e script de deploy
```

## Implantação rápida

```bash
sudo bash deploy/deploy.sh
```

O script instala dependências, cria o banco, gera o virtualenv, gera as chaves
(`SECRET_KEY`/`FERNET_KEY`), emite o certificado SSL autoassinado, configura o
Apache e inicializa o banco. Ao final, acesse `https://10.250.128.114/`.

Login inicial: **admin@heimdall.local** / **Heimdall@2025!** (altere no primeiro acesso).

## Ingestão de uso de IA via API

```
POST /api/v1/usage
Authorization: Bearer <HEIMDALL_INGEST_TOKEN>
Content-Type: application/json

{ "product_id": 1, "period": "2026-06",
  "input_tokens": 120000, "output_tokens": 45000, "calls": 1500 }
```

O token é gerado automaticamente no deploy e fica em `/etc/apache2/envvars`.

## Agendamento de coletas

Na tela **Agendamentos** é possível cadastrar coletas periódicas por conta de
nuvem (diária, semanal ou mensal, com hora definida e quantos meses anteriores
recoletar a cada execução). A execução automática é feita por um *systemd timer*
no servidor (não por uma thread no Apache, que seria reciclada):

```bash
sudo cp deploy/heimdall-scheduler.service /etc/systemd/system/
sudo cp deploy/heimdall-scheduler.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now heimdall-scheduler.timer

# acompanhar
systemctl list-timers heimdall-scheduler.timer
journalctl -u heimdall-scheduler.service -n 50
```

O timer roda a cada 15 minutos e dispara cada coleta no horário configurado,
uma única vez por janela (controlado por `last_run`). O botão ▶ na tela executa
a coleta imediatamente. O `deploy.sh` já instala e habilita o timer.

