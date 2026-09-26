# Eeze Agent

**Um agente que usa o computador por você, rodando no seu próprio PC Windows.** Você descreve
o trabalho com palavras simples — "corte este vídeo num teaser vertical de 30 segundos",
"renomeie estas 80 fotos para parque001, parque002…", "renderize uma foto de produto no
Blender" — o Eeze planeja, mostra exatamente o que vai fazer, espera a sua aprovação e faz em
segundo plano, com os programas que você já tem.

🇺🇸 [Read in English](README.md)

- **Local.** O serviço e o painel ficam em `127.0.0.1`. Seus arquivos não saem do computador,
  a não ser que um trabalho aprovado por você envie algo ao provedor de IA que você configurou.
- **Você aprova o que é arriscado.** Tudo que altera ou apaga arquivos, gasta dinheiro ou envia
  algo para fora para e pergunta. Mudanças em arquivos vêm com prévia e desfazer em um clique.
- **Proteções embutidas.** Limite diário de gasto com IA paga, aprovações que expiram,
  lembretes e histórico completo de cada execução.

## O que ele faz hoje

| Missão | Resultado |
| --- | --- |
| Vídeo | Cortar, juntar, títulos/logo, versões verticais 9:16 (ffmpeg) |
| Foto | Recortar, redimensionar, quadrado/vertical, edições simples (ffmpeg) |
| Arquivos | Renomear em sequência, organizar por data/tipo, achar duplicados — com prévia e desfazer |
| 3D | Cenas e renders simples no Blender |
| Notas fiscais | Extrair dados de PDFs para uma tabela |
| Rotinas | Qualquer um dos itens acima, agendado |

É um projeto open source em estágio inicial: espere arestas. Veja [docs/CAPABILITIES.md](docs/CAPABILITIES.md).

## Instalação (Windows 10/11 — sem terminal)

1. Baixe este repositório (botão verde **Code** → **Download ZIP**) e descompacte num lugar
   definitivo, por exemplo `C:\Users\<você>\eeze-agent`. Ou use `git clone`.
2. Dê dois cliques no **`install.cmd`**.

O instalador prepara o Python (via [uv](https://docs.astral.sh/uv/)), monta o painel, liga o
serviço em segundo plano, cria atalhos e **abre o Eeze no navegador já conectado**. Depois ele
guia a configuração (escolher um provedor de IA e colar a chave).

Ferramentas opcionais usadas pelas missões: [ffmpeg](https://ffmpeg.org/) (vídeo/foto) e
[Blender](https://www.blender.org/) (3D). Instale se for usar essas missões.

### Uso no dia a dia

| Você quer… | Faça isto |
| --- | --- |
| Abrir o Eeze | Dois cliques em **Eeze Agent** na Área de Trabalho ou no menu Iniciar |
| Instalar uma atualização | Menu Iniciar → **Eeze Agent - Update** (ou dois cliques no `install.cmd`) |
| Desconectar todos os navegadores | `eeze unpair` (veja abaixo) |

O serviço inicia com o Windows para as rotinas rodarem, e um vigia o reinicia se ele parar.

## Conectar o navegador (pareamento)

O painel do Eeze vê suas execuções e aprova ações no seu computador, por isso o navegador
precisa ser **conectado** uma vez antes de usar. Normalmente você nem percebe:

- **O instalador e o atalho "Eeze Agent" conectam o navegador sozinhos.** Eles abrem um link
  com um código que vale uma única vez, por dois minutos, só neste computador.
- Um navegador conectado fica assim por **30 dias** (ajuste com `EEZE_SESSION_DAYS`).

Se um dia você cair na página **"Conecte este navegador"**, é só dar dois cliques no atalho
Eeze Agent. O jeito manual, o modelo de segurança e a solução de problemas estão em
**[docs/pt-BR/PAIRING.md](docs/pt-BR/PAIRING.md)**.

## Para desenvolvedores

Veja a seção *For developers* do [README em inglês](README.md#for-developers).

## Segurança

Relate vulnerabilidades de forma privada — veja [SECURITY.md](SECURITY.md).

## Licença

[Apache License 2.0](LICENSE).
