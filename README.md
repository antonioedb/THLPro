# THLPro — Sistema Profissional de Análise de Opções

Sistema completo que substitui a planilha **THLPro.xlsx**: análise de opções em tempo real, multiusuário, com backend Python/FastAPI, frontend web React, cliente Windows (.exe) integrado ao **Profit via RTD** e comunicação WebSocket.

- **Backend:** Python · FastAPI · SQLAlchemy (async) · PostgreSQL · Alembic · Pydantic v2 · JWT
- **Frontend:** React · TypeScript · Vite · Tailwind · Lightweight Charts/Recharts · temas claro/escuro
- **Cliente Windows:** Python · RTD (`rtdtrading.rtdserver`) · bandeja do Windows · PyInstaller + Inno Setup
- **Tempo real:** WebSocket broadcast de cotações para todos os usuários; anti-rollback (dado antigo nunca sobrescreve novo); regra de prioridade entre clientes

## Estrutura

```
thlpro/
├── backend/      # API FastAPI + migrações Alembic + seed + testes pytest
├── frontend/     # Aplicação web React/Vite/TS
├── client/       # Cliente Windows .exe (RTD Profit) + build/instalador
├── docs/         # INSTALACAO.md · API.md · MANUAL_USUARIO.md · MANUAL_PROFIT_RTD.md
├── nginx/        # Configuração de proxy (web → api)
├── docker-compose.yml
└── .env.example
```

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/INSTALACAO.md`](docs/INSTALACAO.md) | Instalação (Docker e manual), HTTPS, backup, atualização |
| [`docs/API.md`](docs/API.md) | Documentação da API (Swagger também em `/docs`) |
| [`docs/MANUAL_USUARIO.md`](docs/MANUAL_USUARIO.md) | Uso da tela principal e telas administrativas |
| [`docs/MANUAL_PROFIT_RTD.md`](docs/MANUAL_PROFIT_RTD.md) | Configuração Profit/RTD do cliente local |
| [`backend/README.md`](backend/README.md) · [`frontend/README.md`](frontend/README.md) · [`client/README.md`](client/README.md) | Detalhes por componente |
| `thlpro_design_validacao.md` | Fase 1 — análise da planilha + design validado |

## Início rápido (Docker)

```bash
cp .env.example .env        # edite senhas e SECRET_KEY
docker compose up -d --build
# Web: http://localhost · API: http://localhost/health · Swagger: http://localhost/docs
```

## Principais recursos

- Ativos iniciais **BOVA11** e **ABEV3**; cadastro extensível (PETR4, VALE3, ITUB4, BBDC4…).
- Faixa de strikes ±10% (configurável por ativo) e **grade com TODOS os strikes** (171, 172, 173… inclusive quebrados).
- Identificação automática das opções via **arquivo oficial da B3** (sem digitação manual de códigos).
- Tolerância de strike configurável (default 0,50) — nunca substituição silenciosa de strike.
- CALL e PUT lado a lado com prêmio, BID, ASK, último preço, horário e status (atualizado/atrasado/N/D).
- Preferências individuais por usuário; dados de mercado compartilhados em tempo real.
- Cliente .exe com fila local, reconexão automática, watchdog, logs e bandeja do Windows.
- Modo **simulação explícito** (apenas testes; badge visível; desligado em produção).

*Todas as cotações exibidas são reais (cliente conectado via Profit RTD) — versão final sem dados fictícios.*
