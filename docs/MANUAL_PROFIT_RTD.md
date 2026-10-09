# THLPro — Manual de Configuração Profit/RTD

Este manual descreve como o cliente local THLPro lê dados do **Profit Pro (Nelogica)** via **RTD** e como configurar o ambiente.

> Detalhes operacionais do código do cliente: ver `client/README.md` e `client/CONFIGURACAO_PROFIT_RTD.md`.

---

## 1. Conceito: o que é o RTD

O Profit expõe cotações em tempo real por um servidor COM chamado **`rtdtrading.rtdserver`** (o mesmo mecanismo que a planilha THLPro utiliza nas fórmulas `RTD("rtdtrading.rtdserver", ...)`). O servidor RTD entrega valores sob demanda por **tópico**, identificado pelo papél + código da série.

### Tópico padrão usado pelo sistema

```
<ATIVO><CÓDIGO>_B_0
```

Exemplos (mesmos da planilha original):

| Série | Tópico RTD |
|---|---|
| BOVA11 CALL strike 200 venc. out | `BOVAJ40_B_0` |
| BOVA11 PUT strike 185 venc. out | `BOVAV37_B_0` |

### Campos lidos por tópico

| Campo RTD | Significado | Uso no THLPro |
|---|---|---|
| `ULT` | Último preço negociado | `last_price` / prêmio |
| `OCP` | Melhor oferta de compra | `bid` |
| `OVD` | Melhor oferta de venda | `ask` |
| `VEN` | Data de vencimento | `expiration_date` |
| `PEX` | Preço de exercício (strike) | `strike` |

---

## 2. Requisitos na máquina de operação

- **Windows 10/11 64-bit**.
- **Profit Pro** instalado, logado e com cotações sendo recebidas normalmente.
- O servidor RTD **`rtdtrading.rtdserver`** disponível (é registrado pelo próprio Profit — verifique se a planilha original atualiza neste computador; se atualiza, o RTD está OK).
- **Python 3.12 (64-bit)** apenas para gerar o .exe (a instalação final não exige Python).
- Permissão para o executável THLProClient.exe rodar em segundo plano (antivírus/firewall liberados para HTTP/HTTPS e WebSocket para o servidor THLPro).

---

## 3. Como o THLPro acessa o RTD

O cliente usa duas camadas:

1. **`ComRTDClient`** — acesso direto ao servidor COM `rtdtrading.rtdserver` (mesmo provedor da planilha). Assina os tópicos das séries ativas recebidas do servidor (`GET /clients/config`) e consome `ULT/OCP/OVD/VEN/PEX`. A leitura é por eventos quando suportada, com fallback de polling curto (500 ms–1 s) por tópico — comportamento idêntico ao observado na planilha, sem travamentos no Profit.
2. **`ProfitApiRtdClient`** — stub documentado para integração via API/plugin oficial da Nelogica, caso você prefira liberar o acesso programático explícito do Profit (a API oficial da Nelogica é licenciada/contratada separadamente; se você tiver acesso, seguimos as instruções do stub).

> Se o **acesso COM direto** não funcionar no seu ambiente (variação de produto/versão), o fallback da planilha continua válido: uma instância do **Excel em modo oculto** assinando fórmulas RTD e publicando os valores para o cliente. Essa alternativa está documentada no código (`client/CONFIGURACAO_PROFIT_RTD.md`), mas só será necessária em ambientes onde o COM direto for bloqueado.

---

## 4. Configuração do cliente

1. Instale o **THLProClient.exe** (instalador Inno Setup) na máquina do Profit.
2. Abra o cliente pela bandeja do Windows (ícone THLPro) → **Configurações**.
3. Preencha:
   - **URL do servidor**: endereço do backend THLPro (ex.: `https://thlpro.suaempresa.com`).
   - **E-mail/Senha**: usuário com permissão no sistema.
   - **Nome do cliente** e **computador**: identificação da máquina (aparece no diagnóstico).
4. Clique em **Salvar** — o cliente faz login, se registra (`/clients/register`), recebe a API key e baixa a configuração de séries ativas.
5. Com o Profit aberto, clique em **Iniciar captura**.

### Modo simulação (somente testes)

Para testar sem o Profit, rode com `SIMULATE=1` (ou `--simulate`): o cliente gera cotações sintéticas com origem **`SIMULATED`** — elas aparecem com o badge "dados simulados de teste" nas telas. **Nunca use em produção.**

---

## 5. Status e diagnóstico

Na bandeja, o menu mostra:

- **Profit:** conectado/desconectado (indicador verde/vermelho).
- **Servidor:** conectado/desconectado + última atualização recebida.
- **Captura:** ativa/parada; quantidade de ativos e opções monitorados.
- **Erros recentes** de RTD e de comunicação.

A tela administrativa (web) em **Clientes/Diagnóstico** mostra os mesmos estados por cliente, com último heartbeat e tempo desde a última atualização.

**Tratamento de falhas:** Profit fechado ou RTD indisponível → status vermelho, captura pausada, heartbeat mantido; internet/servidor indisponível → dados ficam na **fila local** (SQLite) e são reenviados ao reconectar, sem duplicação; o cliente **reinicia automaticamente** workers que falharem (watchdog) e nunca trava o Profit.

---

## 6. Verificação rápida

1. Profit aberto mostrando cotações de BOVA11.
2. THLProClient com captura **iniciada** e status verde.
3. Web → tela principal → BOVA11: tabelas CALL/PUT preenchendo com vencimentos, prêmio, BID, ASK e **horários de atualização** atuais.
4. Parar o Profit: em até ~60 s as telas marcam os dados como **atrasados** (indicador amarelo).

---

*THLPro — manual de configuração Profit/RTD. Detalhes técnicos adicionais: `client/CONFIGURACAO_PROFIT_RTD.md`.*
