# okl-reels

Robô que publica os reels próprios do **@vendas.okl** pela API oficial do Instagram, já como **reel de teste** (só quem não segue vê; se for bem, o Instagram manda pros seguidores sozinho).

Roda no GitHub Actions a cada 30 minutos, com o computador desligado. Os remixes **não** passam por aqui: remix só existe no app.

## Como funciona

1. Toda semana o Claude coloca aqui os vídeos (`videos/`) e um arquivo `.json` por reel (`fila/`).
2. A cada 30 min o robô olha a fila. O que já passou do horário é publicado.
3. Depois de publicado, o `.json` vai para `publicados/` com o link do post, e o vídeo sai da pasta `videos/`.
4. Se der erro, o `.json` vai para `publicados/` com `"status": "erro"` e o GitHub manda e-mail.

## Formato de um reel na fila

`fila/2026-10-26_0700_voce-teria-juliet.json`

```json
{
  "publicar_em": "2026-10-26T07:00:00-03:00",
  "video": "videos/2026-10-26_voce-teria-juliet.mp4",
  "legenda": "Você teria um desse? 🏴‍☠️\n\nJuliet Polished, X-Metal original.\n\n#oakley #viral #reels #viralreels #fyp",
  "teste": true,
  "graduacao": "SS_PERFORMANCE",
  "capa_ms": 1000,
  "no_feed": true
}
```

- `teste`: `true` = reel de teste. `false` = vai direto para os seguidores (reels de venda com preço e de prova social).
- `graduacao`: `SS_PERFORMANCE` = o Instagram compartilha com os seguidores se performar; `MANUAL` = só você, pelo app.
- `capa_ms`: momento do vídeo (em milissegundos) usado como capa. Opcional.
- `marcar`: lista de @ (sem o @) para marcar a pessoa na mídia (`user_tags`). Opcional; vale também para reel de teste. Se a API recusar a marcação, o robô publica do mesmo jeito, só com o @ da legenda, e registra no log.
- `colaboradores`: lista de até 3 @ (sem o @) para convite de collab. Opcional. **Collab sai sempre normal** (`teste: false`).
- `ia`: `true` liga o selo "Informações de IA" (vídeos do Cientista Maluco).

Vídeo: MP4 (H.264 + AAC), vertical 9:16, 15 a 30 s, até ~50 MB.

## Stories (desde 24/10/2026)

Vitrine de peças à venda. Um `.json` por story em `fila/` e a imagem em `videos/stories/`:

```json
{
  "tipo": "story",
  "publicar_em": "2026-10-25T19:00:00-03:00",
  "imagem": "videos/stories/2026-10-25_01_capa.jpg"
}
```

- Imagem **JPEG** 1080x1920 (a API só aceita JPEG). Sem legenda, sem figurinha: o texto vai na própria imagem.
- Stories **não contam** no teto dos reels. Todos os vencidos saem na mesma rodada, na ordem do nome do arquivo, com pausa de 8 a 20 s entre um e outro. Teto: 10 por rodada e 15 por dia.
- Se um story falhar, os seguintes do mesmo lote ficam como `cancelado` em `publicados/` (para não sair sequência pela metade).
- Depois de publicado, a imagem sai de `videos/stories/`.
- O modo `teste` também cria um story de teste com `videos/_teste_story.jpg` e **não** publica.

## Travas de segurança

Espelham o Vault OKL ("Análise de Reels - Remix e Teste", 22/10/2026): base normal às 07h pela API, camada de teste às 09h30, 14h e 19h30; remixes das 11h e 17h pelo app.

- no máximo **4 publicações pela API por dia**;
- pelo menos **2 h** entre duas publicações pela API;
- **1 publicação por rodada**;
- passou mais de **3 h** do horário, não publica: marca como atrasado para não furar a cadência;
- reel de teste com coautor é recusado (collab sai sempre normal).

## Collab automático (bonde)

Desde 24/10/2026 (Vault OKL, "Mapa de Collabs - Posts de IA").

- Todo reel que vai para os seguidores (`teste: false`) sai com o bonde de `bonde.json` convidado: as `fixas` + a próxima da `rotacao`, até **3** (limite da API; no app são 5). Para mandar outra lista, use `colaboradores` no JSON; para sair sem collab, `"bonde": false`.
- `nunca_convidar` é tirado até de lista manual. `so_com_conversa` fica fora da escolha automática.
- Testado em 24/10: a API aceitou criar o reel com colaborador (formato json). O primeiro post normal confirma se o convite chega.
- **Conferência de aceites: pronta, mas parada.** Com a chave atual (login do Instagram) a API não deixa ler quem aceitou ("nonexisting field (collaborators)"); a Meta só libera com login do Facebook. Quando liberar, o robô passa a ler todo dia às 08h23 quem aceitou nos posts de 1 a 7 dias (inclusive os do app), atualizar o `placar` e `relatorios/collab.md`, tirar do bonde quem deixar 2 convites seguidos pendentes e abrir a issue **"Collab: convite pendente para trocar no app"**. Até lá, a conferência é feita pelo Claude no navegador, quando pedida.
- A API não troca colaborador depois de publicado: a troca é no app.
- Diagnóstico: Actions → Publicar reels → Run workflow → modo `colab`. Tenta ler os colaboradores dos últimos posts e cria um contêiner com colaborador **sem publicar**.

## Insights

Todo dia às 08h23 o robô lê views, alcance, compartilhamentos, salvamentos, curtidas e comentários dos reels publicados há 48 h ou mais e grava em `insights_48h` no JSON de cada um, em `publicados/`.

## Configuração (uma vez)

- **Segredo `IG_TOKEN`**: Settings → Secrets and variables → Actions → New repository secret. É a chave gerada no painel da Meta (app "OKL Reels", produto Instagram, "Generate token" da conta @vendas.okl).
- **GitHub Pages**: Settings → Pages → Deploy from a branch → `main` / root. A API do Instagram busca o vídeo por um link público, e o Pages fornece esse link.
- **Conferir**: Actions → Publicar reels → Run workflow → modo `conferir`. Mostra a conta conectada e a fila.
- **Teste técnico sem publicar**: modo `teste`. Cria um reel de teste com `videos/_teste.mp4`, espera o Instagram aceitar e **não** publica.

## Renovação da chave

A chave do Instagram vale 60 dias. O workflow **Renovar chave do Instagram** roda nos dias 1 e 15 e estende a validade. Se a Meta devolver uma chave diferente, ele avisa por e-mail (ou grava sozinho, se existir o segredo opcional `GH_PAT`).

## Respostas automáticas no YouTube (Dr. X)

O workflow **Responder comentários do YouTube** roda a cada 30 min e responde todo comentário novo do canal VENDAS OKL na voz do **Dr. X**, o Cientista Maluco: quem segue é "cobaia", quem compra sai "vacinado contra réplica", assinatura "~Dr. X".

**Regra (Thiago, 24/10/2026): o YouTube não vende.** Lá o laboratório só mostra; a plataforma de vendas é o **Instagram @vendas.okl**. Toda resposta (menos a de hater) manda seguir o Instagram e, para comprar, chamar no Direct de lá. Nada de preço, WhatsApp, Pix, frete ou link. A função `conferir_regra()` trava o robô (sai com erro) se algum texto do banco fugir disso.

A cada rodada, além de responder:
- **Descrições:** troca, vídeo por vídeo (inclusive agendados), o rodapé antigo que mandava para o WhatsApp pelo novo: "🛒 Aqui no YouTube a gente só mostra. Venda é só no Instagram @vendas.okl…". Até 20 por rodada; descrição já certa não é tocada.
- **Comentário de abertura:** todo vídeo público dos últimos 30 dias que ainda não tem comentário do canal ganha um do Dr. X mandando para o Instagram (texto próprio para vídeo de criador). Até 10 por rodada. A API não fixa comentário: fixar é no app.

- Script: `scripts/youtube_respostas.py`. Testar o estilo sem internet: `python scripts/youtube_respostas.py --teste "quanto custa?"`.
- Não guarda estado: um comentário conta como respondido quando o canal já respondeu depois dele na mesma conversa. No máximo 4 respostas do canal por conversa e 40 por rodada.
- Pula spam (link, telefone, "meu canal", cripto) e xingamento pesado. Não põe link na resposta.
- Em vídeo de criador autorizado (título ou descrição com um @ que não é o nosso), não diz que a peça é original nem que está à venda.
- Segredos: `YT_CLIENT_SECRET` e `YT_REFRESH_TOKEN` (o `YT_CLIENT_ID` é público e fica no próprio workflow) (conta vendas.okl27, escopo `youtube.force-ssl`, app "OKL Respostas" no Google Cloud, em produção para a chave não vencer em 7 dias).
- Simular: Actions → Responder comentários do YouTube → Run workflow → `dry_run = 1`.
