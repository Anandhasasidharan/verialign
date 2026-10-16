# VeriAlign Deployment Guide

## Quick Start (Local Development)

```bash
# Clone and setup
cd verialign
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialize database (if not using demo's auto-create)
alembic upgrade head

# Run in demo mode (no API keys needed)
uvicorn verialign.proxy.main:app --reload

# In another terminal, run dashboard
streamlit run verialign/dashboard/app.py
```

Visit:
- Proxy: http://127.0.0.1:8000
- Dashboard: http://127.0.0.1:8501
- API Docs: http://127.0.0.1:8000/docs

## Database Migrations

Alembic manages the database schema. Run migrations after every update:

```bash
# Apply pending migrations
alembic upgrade head

# Check current version
alembic current

# View migration history
alembic history

# Rollback one step (if needed)
alembic downgrade -1
```

The first time you start VeriAlign, the schema is auto-created for demo/dev. In production, always run `alembic upgrade head` explicitly before starting services.

## Docker Compose (Recommended for Production)

```bash
# Copy and edit environment
cp .env.example .env
# Edit .env with your API keys

# Start all services
docker compose -f verialign/deploy/docker-compose.yml up -d

# View logs
docker compose -f verialign/deploy/docker-compose.yml logs -f
```

Services:
- Proxy: http://localhost:8000
- Dashboard: http://localhost:8501
- Metrics: http://localhost:8000/metrics

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VERIALIGN_UPSTREAM_BASE_URL` | No* | OpenAI-compatible API endpoint |
| `VERIALIGN_UPSTREAM_API_KEY` | No* | API key for upstream provider |
| `VERIALIGN_ANTHROPIC_API_KEY` | No | Anthropic API key |
| `VERIALIGN_LOCAL_BASE_URL` | No | Local Ollama endpoint |
| `VERIALIGN_PROXY_API_KEY` | No | VeriAlign's own API key |
| `VERIALIGN_REQUIRE_PROXY_AUTH` | No | Enable auth (true/false) |
| `VERIALIGN_RATE_LIMIT_RPM` | No | Requests/minute per client |
| `VERIALIGN_RATE_LIMIT_TPM` | No | Tokens/minute per client |
| `VERIALIGN_REDACT_TRACES` | No | Redact secrets (true/false) |
| `VERIALIGN_DB_PATH` | No | SQLite path (default: ./verialign.sqlite3) |
| `VERIALIGN_DATABASE_URL` | No | Database URL for async engines (e.g. `postgresql+asyncpg://user:pass@host/db`). Defaults to SQLite. |
| `VERIALIGN_CORS_ALLOWED_ORIGINS` | No | CORS origins as a JSON list (default `[]` — no cross-origin requests allowed; opt in explicitly) |
| `VERIALIGN_MAX_REQUEST_BODY_SIZE` | No | Max request body in bytes (default 10MB) |
| `VERIALIGN_PROXY_TIMEOUT_SECONDS` | No | Proxy-side request timeout (default 120s) |

*Required for real provider mode. Demo mode works without them.

## Fly.io Deployment

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
flyctl auth login

# Launch (creates fly.toml)
flyctl launch --name verialign --region ord --no-deploy

# Set secrets
flyctl secrets set VERIALIGN_UPSTREAM_BASE_URL=https://api.openai.com/v1
flyctl secrets set VERIALIGN_UPSTREAM_API_KEY=sk-...
flyctl secrets set VERIALIGN_PROXY_API_KEY=your-proxy-key
flyctl secrets set VERIALIGN_REQUIRE_PROXY_AUTH=true

# Deploy
flyctl deploy
```

## Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Set variables in Railway dashboard or CLI
railway variables set VERIALIGN_UPSTREAM_BASE_URL=https://api.openai.com/v1
railway variables set VERIALIGN_UPSTREAM_API_KEY=sk-...
railway variables set VERIALIGN_PROXY_API_KEY=your-proxy-key
railway variables set VERIALIGN_REQUIRE_PROXY_AUTH=true

# Deploy
railway up
```

## VPS Deployment (systemd)

```bash
# On your server
sudo apt update && sudo apt install -y python3.12 python3.12-venv nginx certbot python3-certbot-nginx

# Clone and setup
git clone <your-repo> /opt/verialign
cd /opt/verialign
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Create .env
cp .env.example .env
# Edit .env with production values

# Create systemd service
sudo tee /etc/systemd/system/verialign.service <<EOF
[Unit]
Description=VeriAlign Proxy
After=network.target

[Service]
Type=exec
User=www-data
WorkingDirectory=/opt/verialign
Environment=PATH=/opt/verialign/.venv/bin
ExecStart=/opt/verialign/.venv/bin/uvicorn verialign.proxy.main:app --host 127.0.0.1 --port 8000 --workers ${VERIALIGN_WORKERS:-4}
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# Create dashboard service
sudo tee /etc/systemd/system/verialign-dashboard.service <<EOF
[Unit]
Description=VeriAlign Dashboard
After=network.target

[Service]
Type=exec
User=www-data
WorkingDirectory=/opt/verialign
Environment=PATH=/opt/verialign/.venv/bin
ExecStart=/opt/verialign/.venv/bin/streamlit run verialign/dashboard/app.py --server.port=8501 --server.address=127.0.0.1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now verialign verialign-dashboard

# Configure nginx reverse proxy with HTTPS
sudo tee /etc/nginx/sites-available/verialign <<EOF
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # TLS — managed by certbot
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Request body size limit (should match VERIALIGN_MAX_REQUEST_BODY_SIZE)
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /dashboard/ {
        proxy_pass http://127.0.0.1:8501/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/verialign /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Obtain TLS certificate
sudo certbot --nginx -d your-domain.com
```

> **TLS Termination**: VeriAlign itself does not handle TLS. Always front it with a reverse proxy (nginx, Caddy, Traefik) or use your cloud provider's load balancer TLS termination. The nginx config above includes HTTPS setup with security headers.

## Health Checks

```bash
# Proxy health (deep check: probes DB and upstream config)
curl http://localhost:8000/health
# {"status":"ok","database":"ok","upstream_configured":false}

# Prometheus metrics
curl http://localhost:8000/metrics

# Dashboard health
curl http://localhost:8501/_stcore/health
# ok
```

## Database Management

### SQLite (Default)
```bash
# View recent traces
sqlite3 verialign.sqlite3 "SELECT id, created_at, model FROM traces ORDER BY id DESC LIMIT 10;"

# Export traces
sqlite3 verialign.sqlite3 ".mode json" ".output traces.json" "SELECT * FROM traces;"

# Backup
cp verialign.sqlite3 verialign.sqlite3.backup
```

### PostgreSQL (Production)

For higher concurrency, configure a PostgreSQL backend:

```bash
# Install async dependencies
pip install -e ".[async]"

# Set the database URL
export VERIALIGN_DATABASE_URL="postgresql+asyncpg://user:password@host:5432/verialign"

# Initialize schema (auto-created on first startup when using AsyncTraceStore)
# Run migrations
alembic upgrade head
```

The async store uses a connection pool (size=10, overflow=20) and supports the same trace/health/query operations as the SQLite store.

> **Note:** If `VERIALIGN_DATABASE_URL` starts with `postgresql`, `mysql`, or `asyncpg`, the async trace store is used automatically. Otherwise, the default SQLite store is used.

## Monitoring

- **Logs**: Structured JSON logs via stdout with correlation IDs (configure log aggregation like Loki, Datadog)
- **Metrics**: Prometheus endpoint at `/metrics` — request count, latency histograms, upstream latency per provider
- **Dashboard**: Built-in Streamlit dashboard at port 8501
- **Alerts**: Set up alerts on error rate, latency p99 > 10s, or verification failure rates

## Security Checklist

- [ ] Set `VERIALIGN_PROXY_API_KEY` and enable `VERIALIGN_REQUIRE_PROXY_AUTH=true`
- [ ] Use HTTPS in production (nginx + certbot or cloud provider TLS) — VeriAlign does not handle TLS internally
- [ ] Restrict dashboard access (VPN, IP allowlist, or auth proxy)
- [ ] Enable `VERIALIGN_REDACT_TRACES=true`
- [ ] Set appropriate rate limits
- [ ] Regular database backups
- [ ] Monitor for unusual patterns in verification results
- [ ] Use a secrets vault for API keys (HashiCorp Vault, AWS Secrets Manager, 1Password CLI) instead of plaintext env vars
- [ ] Rotate API keys regularly
- [ ] Set `VERIALIGN_CORS_ALLOWED_ORIGINS` to a JSON list of specific origins, e.g. `["https://your.domain"]`
- [ ] Set `VERIALIGN_MAX_REQUEST_BODY_SIZE` to an appropriate limit for your use case
- [ ] Use `--workers N` where N equals your CPU core count for production

## Secrets Management

For production, avoid storing API keys directly in `.env` files. Use a secrets vault:

**HashiCorp Vault:**
```bash
# Fetch secrets at startup via vault-agent or envconsul
export VERIALIGN_UPSTREAM_API_KEY=$(vault kv get -field=key secret/verialign/upstream)
export VERIALIGN_PROXY_API_KEY=$(vault kv get -field=key secret/verialign/proxy)
```

**AWS Secrets Manager:**
```bash
export VERIALIGN_UPSTREAM_API_KEY=$(aws secretsmanager get-secret-value --secret-id verialign/upstream --query SecretString --output text)
```

**Docker Secrets:**
```yaml
# docker-compose.yml
services:
  proxy:
    image: verialign-proxy
    secrets:
      - upstream_api_key
    environment:
      VERIALIGN_UPSTREAM_API_KEY_FILE: /run/secrets/upstream_api_key

secrets:
  upstream_api_key:
    file: ./secrets/upstream_api_key.txt
```

> **Note:** VeriAlign does not directly integrate with any secrets vault. Use your infrastructure's secrets injection mechanism to set environment variables at runtime.