# Pareamento: conectar um navegador ao Eeze

🇺🇸 [English](../PAIRING.md)

O painel do Eeze roda em `http://127.0.0.1:8765` e pode aprovar ações no seu computador
(mover arquivos, gastar com IA, enviar e-mail). Por isso o navegador precisa ser **conectado**
(pareado) antes de ver ou fazer qualquer coisa. No uso normal isso é automático.

## O jeito automático (normal)

| Quando | O que acontece |
| --- | --- |
| Na instalação | O `install.cmd` termina abrindo o Eeze **já conectado** na página de configuração. |
| Depois, sempre | Dois cliques no atalho **Eeze Agent** (Área de Trabalho ou menu Iniciar). |

Por trás, o atalho roda `eeze open`, que:

1. liga o serviço do Eeze se ele estiver parado;
2. cria um **código de uso único** aleatório (só o hash SHA-256 é guardado, em
   `~/.eeze/pair-codes.json`);
3. abre `http://127.0.0.1:8765/pair#code=…` — a página troca o código por um cookie de acesso
   e apaga o código da barra de endereço na hora.

O código vale **uma vez**, por **dois minutos**, e só neste computador. Depois o navegador
fica conectado por **30 dias**.

No terminal: `eeze open` (painel), `eeze open /setup` (uma página específica),
`eeze open --print-only` (mostra o link em vez de abrir — útil para um segundo navegador no
mesmo PC).

## O jeito manual (alternativa)

Use se o atalho não existir ou para conectar outro navegador:

1. Abra `%USERPROFILE%\.eeze\api.token` no Bloco de Notas (macOS/Linux: `~/.eeze/api.token`).
2. Copie todo o conteúdo.
3. Na página **Conecte este navegador**, clique em *"Sem o atalho? Conecte com a sua chave de
   acesso"*, cole e clique em **Conectar**.

## Modelo de segurança

- O serviço escuta **só no próprio computador** (`127.0.0.1`) e recusa pedidos de outras
  máquinas, proxies e sites de fora.
- `~/.eeze/api.token` é a **chave de acesso**. Quem lê esse arquivo controla o Eeze, então:
  nunca compartilhe, nunca cole em chat, site ou na demo pública, nunca coloque no Git.
- O cookie de acesso é `HttpOnly`, `SameSite=Strict` e assinado com a chave; a chave em si
  nunca fica guardada no navegador.
- O código de uso único só facilita, sem abrir acesso novo: quem consegue rodar `eeze open`
  na sua conta já conseguiria ler a chave.

## Desconectar tudo

```bash
eeze unpair
```

Troca a chave de acesso, o que **desconecta todos os navegadores de uma vez** (e invalida
scripts que usavam a chave antiga). Use se achar que a chave vazou ou num PC compartilhado.
Depois abra o Eeze pelo atalho para conectar de novo.

## Configuração

| Variável (no `.env`) | Padrão | Significado |
| --- | --- | --- |
| `EEZE_SESSION_DAYS` | `30` | Por quantos dias o navegador fica conectado (1–365). |

## Problemas comuns

| Sintoma | Solução |
| --- | --- |
| "Este link já foi usado ou expirou" | Dois cliques no atalho Eeze Agent de novo (o código dura dois minutos e vale uma vez). |
| "Não foi possível falar com o Eeze" | Dois cliques no atalho — ele liga o serviço. Se continuar, rode o `install.cmd`; os logs ficam em `%USERPROFILE%\.eeze\api.log`. |
| Pede para conectar toda hora | Os cookies de `127.0.0.1` estão sendo apagados (janela anônima, extensão de limpeza). Use uma janela normal ou libere cookies para `127.0.0.1`. |
| Conectado em `localhost:8765` mas não em `127.0.0.1:8765` | Para o navegador são sites diferentes. Use `http://127.0.0.1:8765` (o que o atalho abre). |
| Chave recusada | Copie o arquivo inteiro, sem espaços extras. Se você rodou `eeze unpair`, a chave mudou. |
