# THLPro — Manual do Usuário

Sistema de análise de opções em tempo real para operação no mercado financeiro. Este manual explica a tela principal, os indicadores e as telas administrativas.

---

## 1. Acesso

1. Abra o endereço do sistema no navegador.
2. Informe **e-mail** e **senha** fornecidos pelo administrador.
3. Após o login, você cai na **tela principal**.

O cabeçalho mostra: nome do sistema (**THLPro**), **usuário conectado**, **status do servidor** (verde = conectado), **status do Profit/RTD**, **horário da última atualização** e botões de **configurações**, **atualizar** e **sair**.

---

## 2. Tela principal — filtros

| Controle | O que faz |
|---|---|
| **Carteira/Ativo** | Seleciona o ativo-base (BOVA11, ABEV3; outros podem ser cadastrados pelo admin). |
| **Strike** | Abre a **grade de strikes** com TODOS os strikes dentro da faixa calculada (default ±10% do preço atual) — inclusive strikes "quebrados" como 182, 183, 187, 193. A faixa é recalculada com o preço atual. |
| **Vencimentos** | Quantidade de vencimentos exibidos (default 6, ajustável 1–12). |
| **CALL/PUT** | Mostra somente CALL, somente PUT, ou ambos. |
| **Auto** | Liga/desliga a atualização automática e escolhe o intervalo de atualização (em segundos). |

Ao **trocar o strike**, todas as tabelas e gráficos são recalculados instantaneamente. Ao trocar o ativo, a grade de strikes é recarregada.

---

## 3. Painel do ativo

Exibe para o ativo selecionado: **código**, **último preço**, **variação em pontos e percentual**, **máxima**, **mínima**, **horário da atualização** e a **faixa de strikes** calculada (ex.: 171,00–209,00).

> Se ainda não houver cotação do ativo (nenhum cliente enviando dados), o sistema mostra "Aguardando dados do Profit…" — nunca um preço inventado.

---

## 4. Tabelas CALL e PUT

Lado a lado, uma coluna por vencimento (do mais próximo ao mais distante):

| Coluna | Conteúdo |
|---|---|
| Vencimento | Ex.: `Out/26`, `Nov/26` |
| Código | Código da opção (automatizado via sincronização B3) |
| Strike | Strike da série; se a série for **próxima** ao strike solicitado (dentro da tolerância, ex. 0,50), aparece uma nota "strike próximo: 184,50" |
| Prêmio | Último preço negociado |
| BID / ASK | Melhores ofertas de compra/venda |
| Último preço | Último valor recebido |
| Atualização | Horário (America/São_Paulo) da última atualização |

**Indicadores visuais:**

- 🟢 Verde: dado atualizado (dentro do tempo máximo de validade).
- 🟡 Amarelo: dado **atrasado** (acima do tempo máximo configurado).
- 🔴 Vermelho (cabeçalho): servidor ou Profit desconectado.
- **N/D**: não existe dado para aquela célula (nunca um "0" falso).
- **"— sem opção —"**: não existe opção para o strike/vencimento (mesmo com tolerância).
- **"dados simulados de teste"**: badge visível quando o sistema opera em modo simulação (somente para testes).

---

## 5. Gráficos

- **Prêmio por vencimento:** linha para CALL e linha para PUT; tooltip com nome da opção, strike, vencimento, BID e ASK.
- **BID × ASK × Último por vencimento:** compara as pontas e o último preço ao longo dos vencimentos.
- **Prêmio/BID/ASK por strike:** análise para um vencimento selecionado, CALL e PUT separados.

Todos os gráficos respondem às mudanças de ativo, strike, vencimento e tipo — e atualizam automaticamente quando chegam novos dados via WebSocket.

---

## 6. Temas e preferências

- Botão **configurações** no cabeçalho: escolha o tema (**claro/escuro**) e ajuste as preferências.
- Suas preferências (ativo, strike, quantidade de vencimentos, CALL/PUT, auto-refresh, intervalo, tema) são **salvas por usuário** no servidor — ao entrar de outro computador, elas são restauradas.

---

## 7. Telas administrativas (perfil admin)

- **Usuários:** criar, editar, desativar e definir perfil (admin/user).
- **Ativos:** cadastrar novos ativos (código, nome, tipo, mercado, tick mínimo, intervalo de strikes, percentuais da faixa, habilitado/desabilitado) — ex.: PETR4, VALE3, ITUB4, BBDC4.
- **Clientes / Diagnóstico:** clientes conectados/desconectados, último heartbeat, última atualização, quantidade de ativos e opções monitorados, erros de RTD/comunicação, tempo desde a última atualização; forçar **desconexão/reconexão**.
- **Logs:** consulta de login, logout, erros de cliente, erros de RTD, dados recebidos/rejeitados, com usuário/cliente responsável e horário.
- **Sincronização:** executa a rotina de sincronização das séries da B3 (botão "Sincronizar"), com resultado `{criadas, atualizadas, desativadas, erros}`; permite **upload manual** do arquivo da B3 quando o download direto não estiver disponível.
- **Configurações do sistema:** tolerância de strike (default 0,50), tempo máximo de validade do dado (default 60 s), modo simulação.

---

## 8. Fluxo de operação típico

1. Abra o THLPro e faça login.
2. Selecione **BOVA11** → confira o preço atual e a faixa de strikes calculada.
3. Selecione um strike na grade (por exemplo **187**).
4. Confira CALL e PUT nos 6 próximos vencimentos — código, prêmio, BID, ASK e horário.
5. Acompanhe os gráficos enquanto o cliente local envia dados em tempo real do Profit.

*Dúvidas técnicas sobre a integração com o Profit/RTD: ver `docs/MANUAL_PROFIT_RTD.md`.*
