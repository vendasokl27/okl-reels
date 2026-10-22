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
- `colaboradores`: lista de até 3 @ (sem o @) para convite de collab. Opcional.

Vídeo: MP4 (H.264 + AAC), vertical 9:16, 15 a 30 s, até ~50 MB.

## Travas de segurança

Espelham o Vault OKL (teto de 3 reels por dia, ao menos 4 h entre eles):

- no máximo **2 publicações pela API por dia** (os remixes do app completam o dia);
- pelo menos **4 h** entre duas publicações pela API;
- **1 publicação por rodada**;
- passou mais de **12 h** do horário, não publica: marca como atrasado para não furar a cadência.

## Configuração (uma vez)

- **Segredo `IG_TOKEN`**: Settings → Secrets and variables → Actions → New repository secret. É a chave gerada no painel da Meta (app "OKL Reels", produto Instagram, "Generate token" da conta @vendas.okl).
- **GitHub Pages**: Settings → Pages → Deploy from a branch → `main` / root. A API do Instagram busca o vídeo por um link público, e o Pages fornece esse link.
- **Conferir**: Actions → Publicar reels → Run workflow → modo `conferir`. Mostra a conta conectada e a fila.
- **Teste técnico sem publicar**: modo `teste`. Cria um reel de teste com `videos/_teste.mp4`, espera o Instagram aceitar e **não** publica.

## Renovação da chave

A chave do Instagram vale 60 dias. O workflow **Renovar chave do Instagram** roda nos dias 1 e 15 e estende a validade. Se a Meta devolver uma chave diferente, ele avisa por e-mail (ou grava sozinho, se existir o segredo opcional `GH_PAT`).
