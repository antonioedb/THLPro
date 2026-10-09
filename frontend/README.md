# THLPro Frontend (Fase 3)

Frontend web do THLPro em React + TypeScript + Vite + Tailwind, consumindo o backend FastAPI já existente.

## Requisitos

- Node.js 20+
- Backend THLPro rodando em `http://localhost:8000`

> `localhost` aqui é da VM do agente Abacus.

## Variáveis de ambiente

```bash
cp .env.example .env
```

- `VITE_API_URL`: URL base da API (padrão: `/api`, usando proxy do Vite para o backend local)
- `VITE_WS_URL`: URL do WebSocket de mercado (padrão: `/ws/market-data`, também via proxy)

## Rodar em desenvolvimento

```bash
npm install
npm run dev
```

## Build de produção

```bash
npm run build
```

## Funcionalidades implementadas

- Login com JWT e logout
- Painel principal com:
  - filtros de ativo/strike/vencimentos/lado
  - grade completa de strikes da API (sem filtro 0/5)
  - painel de spot do ativo
  - tabelas CALL e PUT lado a lado com N/D e atraso
  - gráficos de prêmio, BID/ASK/último e fluxo WebSocket em tempo real
- Preferências com fallback localStorage + tentativa de persistência via endpoints de preferência
- Administração (apenas `role=admin`): usuários, ativos, clientes/diagnóstico, logs, sincronização
- Tema claro/escuro
- WebSocket com reconexão automática (backoff)

## Credenciais de seed (backend)

- E-mail: `admin@thlpro.local`
- Senha: definida no `.env` do backend (`ADMIN_PASSWORD`)
