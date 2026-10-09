# THLPro Backend (Fase 2)

Backend do sistema THLPro em FastAPI + PostgreSQL com autenticação JWT, regras de strike/tolerância, anti-rollback, sincronização de séries da B3, WebSocket e suíte de testes.

## Requisitos

- Python 3.12 (no ambiente desta execução, validado com Python 3.11)
- PostgreSQL local ativo

## Configuração rápida

```bash
cd /home/ubuntu/thlpro/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Banco de dados local

```bash
sudo -u postgres createdb thlpro
sudo -u postgres createdb thlpro_test
```

Se necessário, definir senha do usuário postgres para ambiente local:

```bash
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
```

## Migrações + seed

```bash
cd /home/ubuntu/thlpro/backend
source .venv/bin/activate
alembic upgrade head
PYTHONPATH=/home/ubuntu/thlpro/backend python -m scripts.seed
```

## Executar API

```bash
cd /home/ubuntu/thlpro/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Endpoints principais:
- `GET /health`
- `GET /docs`

> Observação: `localhost` acima é da VM do agente Abacus, não do seu computador local.

## Testes

```bash
cd /home/ubuntu/thlpro/backend
source .venv/bin/activate
PYTHONPATH=/home/ubuntu/thlpro/backend pytest -q
```

## Sincronização de séries

- Endpoint admin: `POST /options/synchronize` com `source="b3"` (download) ou `source="upload"` (fixture/arquivo local).
- Se a URL pública da B3 estiver indisponível no ambiente, use o caminho manual e consulte os logs administrativos.

## Modo simulação

- Controle por `system_settings.simulation_mode`.
- Somente quando ativo, é permitido gerar dados simulados (`source="SIMULATED"`).

Script auxiliar de séries simuladas (somente testes):

```bash
cd /home/ubuntu/thlpro/backend
source .venv/bin/activate
PYTHONPATH=/home/ubuntu/thlpro/backend python -m scripts.load_simulation_fixture
```

## Estrutura

- `app/`: API, modelos, schemas, serviços e segurança
- `alembic/`: migrações versionadas
- `scripts/`: criação/seed/simulações
- `tests/`: suíte pytest completa
