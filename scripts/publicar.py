#!/usr/bin/env python3
"""Publica os reels agendados do @vendas.okl pela API oficial do Instagram.

Roda no GitHub Actions a cada 30 minutos. Para cada arquivo em fila/*.json cujo
horário já chegou, cria o reel (como reel de teste quando "teste": true), espera o
Instagram processar, publica e move o JSON para publicados/ com o link do post.

Variáveis de ambiente:
  IG_TOKEN       chave de acesso do Instagram (segredo do repositório)  [obrigatória]
  IG_API_VERSION versão da Graph API (padrão v23.0)
  BASE_URL_VIDEO endereço público onde os vídeos ficam (padrão: GitHub Pages do repositório)
  MODO           "publicar" (padrão), "conferir" (só a chave e a fila),
                 "teste" (cria um reel de teste com videos/_teste.mp4 e NÃO publica),
                 "medir" (lê os insights de 48 h dos reels publicados e confere os collabs) ou
                 "colab" (diagnóstico de colaboradores na API + conferência dos collabs)

Collab automático (24/10/2026): todo reel que vai para os seguidores (teste: false) sai com
o bonde de bonde.json convidado (fixas + 1 da rotação, até 3, limite da API). Criação com
colaborador testada em 24/10 (contêiner aceito, formato json).
A conferência diária de aceites (placar, saída automática após 2 convites seguidos
pendentes e aviso por issue) está pronta, mas DORMENTE: com a chave atual (login do
Instagram) a API responde "nonexisting field (collaborators)"; a Meta só libera a leitura
com login do Facebook. O modo 'colab' testa de novo.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import random
import sys
import time

import requests

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FILA = RAIZ / "fila"
PUBLICADOS = RAIZ / "publicados"
BRT = dt.timezone(dt.timedelta(hours=-3))

API = f"https://graph.instagram.com/{os.environ.get('IG_API_VERSION', 'v23.0')}"
TOKEN = os.environ.get("IG_TOKEN", "").strip()
MODO = os.environ.get("MODO", "publicar").strip() or "publicar"
DRY_RUN = MODO == "conferir"

# Travas de segurança (espelham o vault, "Análise de Reels - Remix e Teste" de 22/10/2026):
# base normal 07h pela API + camada de teste 09h30 · 14h · 19h30 (mínimo de 2 h entre testes).
# Os remixes das 11h e 17h saem pelo app e não passam por aqui.
MAX_API_POR_DIA = 4
MIN_HORAS_ENTRE_API = 2
MAX_ATRASO_HORAS = 3           # passou disso, não publica: marca como atrasado
GRADUACOES = {"SS_PERFORMANCE", "MANUAL"}

# Stories (24/10/2026): vitrine de peças à venda, imagem JPEG 1080x1920 em videos/stories/.
# Não contam no teto dos reels. Saem todos os stories vencidos na mesma rodada, em ordem de
# nome do arquivo, com pausa irregular entre um e outro (ritmo humano, OKL/AGENTS.md).
MAX_STORIES_POR_DIA = 15
MAX_STORIES_POR_RODADA = 10
PAUSA_STORY_S = (8, 20)

BONDE = RAIZ / "bonde.json"
RELATORIO_COLAB = RAIZ / "relatorios" / "collab.md"
MAX_COLAB_API = 3              # a API aceita até 3 colaboradores na criação (no app são 5)
TITULO_AVISO = "Collab: convite pendente para trocar no app"

resumo: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    resumo.append(msg)


def agora() -> dt.datetime:
    return dt.datetime.now(BRT)


def base_url_video() -> str:
    if os.environ.get("BASE_URL_VIDEO"):
        return os.environ["BASE_URL_VIDEO"].rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        raise SystemExit("Defina BASE_URL_VIDEO ou rode dentro do GitHub Actions.")
    dono, nome = repo.split("/", 1)
    return f"https://{dono.lower()}.github.io/{nome}"


def api(metodo: str, caminho: str, **params) -> dict:
    params["access_token"] = TOKEN
    url = f"{API}/{caminho.lstrip('/')}"
    for tentativa in range(3):
        r = requests.request(metodo, url, data=params if metodo == "POST" else None,
                             params=params if metodo == "GET" else None, timeout=60)
        if r.status_code in (429, 500, 502, 503) and tentativa < 2:
            time.sleep(20 * (tentativa + 1))
            continue
        try:
            corpo = r.json()
        except ValueError:
            corpo = {"erro_bruto": r.text[:300]}
        if r.status_code >= 400 or "error" in corpo:
            erro = corpo.get("error", corpo)
            raise RuntimeError(f"{metodo} {caminho} -> HTTP {r.status_code}: {json.dumps(erro, ensure_ascii=False)[:400]}")
        return corpo
    raise RuntimeError(f"{metodo} {caminho}: sem resposta")


def ler_fila() -> list[tuple[pathlib.Path, dict]]:
    itens = []
    for arq in sorted(FILA.glob("*.json")):
        with arq.open(encoding="utf-8") as f:
            item = json.load(f)
        item["_quando"] = dt.datetime.fromisoformat(item["publicar_em"]).astimezone(BRT)
        itens.append((arq, item))
    return sorted(itens, key=lambda x: x[1]["_quando"])


def eh_story(item: dict) -> bool:
    return str(item.get("tipo", "")).lower() == "story"


def publicados_hoje_e_ultimo(stories: bool = False) -> tuple[int, dt.datetime | None]:
    """Conta o que saiu hoje pela API. Reels e stories têm contas separadas."""
    hoje = agora().date()
    n, ultimo = 0, None
    for arq in PUBLICADOS.glob("*.json"):
        with arq.open(encoding="utf-8") as f:
            item = json.load(f)
        if eh_story(item) != stories:
            continue
        quando = item.get("publicado_em")
        if not quando:
            continue
        quando = dt.datetime.fromisoformat(quando).astimezone(BRT)
        if quando.date() == hoje:
            n += 1
        if ultimo is None or quando > ultimo:
            ultimo = quando
    return n, ultimo


def _norm(usuario: str) -> str:
    return str(usuario).strip().lstrip("@").lower()


def ler_bonde() -> dict:
    if not BONDE.is_file():
        return {}
    with BONDE.open(encoding="utf-8") as f:
        return json.load(f)


def gravar_bonde(b: dict) -> None:
    b["atualizado_em"] = agora().isoformat(timespec="seconds")
    with BONDE.open("w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=2)
        f.write("\n")


def escolher_bonde(b: dict) -> tuple[list[str], int]:
    """Fixas + próximas da rotação até MAX_COLAB_API. Devolve (lista, próximo índice da rotação)."""
    fora = {_norm(u) for u in b.get("nunca_convidar", {})} | {_norm(u) for u in b.get("fora_automatico", {})}
    fora |= {_norm(u) for u in b.get("so_com_conversa", {})}
    fixas = [_norm(u) for u in b.get("fixas", []) if _norm(u) not in fora][:MAX_COLAB_API]
    rot = [_norm(u) for u in b.get("rotacao", []) if _norm(u) not in fora and _norm(u) not in fixas]
    i = int(b.get("proxima_rotacao", 0))
    vagas = MAX_COLAB_API - len(fixas)
    extra = [rot[(i + k) % len(rot)] for k in range(min(vagas, len(rot)))] if rot else []
    proximo = (i + len(extra)) % len(rot) if rot else 0
    return fixas + extra, proximo


def aplicar_bonde(item: dict, b: dict) -> int | None:
    """Preenche/filtra item['colaboradores']. Devolve o próximo índice da rotação se usou o bonde."""
    if not b or item.get("teste", True):
        return None
    proximo = None
    if not item.get("colaboradores") and item.get("bonde", True):
        item["colaboradores"], proximo = escolher_bonde(b)
        item["colaboradores_origem"] = "bonde.json"
    if item.get("colaboradores"):
        proibidas = {_norm(u) for u in b.get("nunca_convidar", {})}
        tirar = [u for u in item["colaboradores"] if _norm(u) in proibidas]
        if tirar:
            log(f"  tirados da lista (nunca_convidar): {', '.join(tirar)}")
        item["colaboradores"] = [_norm(u) for u in item["colaboradores"] if _norm(u) not in proibidas][:MAX_COLAB_API]
        if item["colaboradores"]:
            log(f"  colaboradores convidados: {', '.join(item['colaboradores'])}")
    return proximo


def validar_story(item: dict) -> None:
    for campo in ("publicar_em", "imagem"):
        if not item.get(campo):
            raise ValueError(f"campo obrigatório vazio: {campo}")
    if not item["imagem"].lower().endswith((".jpg", ".jpeg")):
        raise ValueError("story precisa de imagem JPEG (.jpg)")
    if not (RAIZ / item["imagem"]).is_file():
        raise ValueError(f"imagem não encontrada no repositório: {item['imagem']}")


def validar(item: dict) -> None:
    for campo in ("publicar_em", "video", "legenda"):
        if not item.get(campo):
            raise ValueError(f"campo obrigatório vazio: {campo}")
    if not (RAIZ / item["video"]).is_file():
        raise ValueError(f"vídeo não encontrado no repositório: {item['video']}")
    if item.get("teste", True) and item.get("graduacao", "SS_PERFORMANCE") not in GRADUACOES:
        raise ValueError("graduacao deve ser SS_PERFORMANCE ou MANUAL")
    if len(item["legenda"]) > 2200:
        raise ValueError("legenda passa de 2.200 caracteres")
    if item.get("teste", True) and item.get("colaboradores"):
        raise ValueError("collab sai sempre normal: não pode ser reel de teste")


def esperar_video_publico(url: str) -> None:
    # O GitHub Pages leva alguns minutos para servir um arquivo recém-enviado.
    for _ in range(12):
        try:
            r = requests.head(url, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(15)
    raise RuntimeError(f"o vídeo não está acessível em {url} (GitHub Pages ainda não publicou?)")


def publicar(item: dict, ig_id: str) -> dict:
    url = f"{base_url_video()}/{item['video']}"
    esperar_video_publico(url)
    params = {
        "media_type": "REELS",
        "video_url": url,
        "caption": item["legenda"],
        "share_to_feed": "true" if item.get("no_feed", True) else "false",
    }
    if item.get("capa_ms") is not None:
        params["thumb_offset"] = str(int(item["capa_ms"]))
    if item.get("colaboradores"):
        lista = [_norm(u) for u in item["colaboradores"]][:MAX_COLAB_API]
        if ler_bonde().get("formato_colaboradores") == "virgula":
            params["collaborators"] = ",".join(lista)
        else:
            params["collaborators"] = json.dumps(lista)
    if item.get("teste", True):
        params["trial_params"] = json.dumps({"graduation_strategy": item.get("graduacao", "SS_PERFORMANCE")})
    if item.get("ia"):
        params["is_ai_generated"] = "true"     # selo "Informações de IA" (API desde 22/06/2026)
    if item.get("marcar"):                    # marcar o criador na mídia (reel aceita só o username)
        params["user_tags"] = json.dumps([{"username": _norm(u)} for u in item["marcar"]])

    try:
        container = api("POST", f"{ig_id}/media", **params)["id"]
    except RuntimeError as e:
        if "user_tags" not in params:
            raise
        log(f"  a API recusou a marcação na mídia ({e}); publicando só com o @ na legenda")
        params.pop("user_tags")
        container = api("POST", f"{ig_id}/media", **params)["id"]
    log(f"  contêiner criado, aguardando o Instagram processar o vídeo")
    for _ in range(60):                       # até 10 minutos
        st = api("GET", container, fields="status_code,status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram recusou o vídeo: {st.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("o Instagram não terminou de processar o vídeo em 10 minutos")

    media_id = api("POST", f"{ig_id}/media_publish", creation_id=container)["id"]
    info = api("GET", media_id, fields="permalink,timestamp")
    return {"media_id": media_id, "link": info.get("permalink"), "publicado_em": agora().isoformat(timespec="seconds")}


def publicar_story(item: dict, ig_id: str) -> dict:
    url = f"{base_url_video()}/{item['imagem']}"
    esperar_video_publico(url)
    container = api("POST", f"{ig_id}/media", media_type="STORIES", image_url=url)["id"]
    for _ in range(30):                       # imagem costuma ficar pronta em segundos
        st = api("GET", container, fields="status_code,status")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram recusou a imagem do story: {st.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("o Instagram não terminou de processar a imagem do story em 2,5 minutos")
    media_id = api("POST", f"{ig_id}/media_publish", creation_id=container)["id"]
    try:
        link = api("GET", media_id, fields="permalink").get("permalink")
    except RuntimeError:
        link = None
    return {"media_id": media_id, "link": link, "publicado_em": agora().isoformat(timespec="seconds")}


def rodar_stories(stories: list[tuple[pathlib.Path, dict]], ig_id: str) -> int:
    """Publica os stories vencidos, em ordem. Se um falhar, os seguintes do lote ficam cancelados
    (não sai sequência pela metade sem a capa ou com peça fora de ordem)."""
    falhas, feitos = 0, 0
    n_hoje, _ = publicados_hoje_e_ultimo(stories=True)
    parar = None
    for arq, item in stories:
        destino = PUBLICADOS / arq.name
        try:
            if parar:
                raise RuntimeError(parar)
            if n_hoje >= MAX_STORIES_POR_DIA:
                log(f"Story {arq.name} fica para amanhã: já saíram {n_hoje} stories hoje (teto {MAX_STORIES_POR_DIA}).")
                break
            if feitos >= MAX_STORIES_POR_RODADA:
                log(f"Story {arq.name} fica para a próxima rodada (teto de {MAX_STORIES_POR_RODADA} por rodada).")
                break
            if agora() - item["_quando"] > dt.timedelta(hours=MAX_ATRASO_HORAS):
                raise RuntimeError(f"atrasado mais de {MAX_ATRASO_HORAS} h; story não publicado")
            if feitos:
                time.sleep(random.uniform(*PAUSA_STORY_S))
            log(f"Publicando story {arq.name}")
            validar_story(item)
            res = publicar_story(item, ig_id)
            item.update(res, status="publicado")
            feitos += 1
            n_hoje += 1
            log(f"  story publicado: {res.get('link') or res['media_id']}")
            img = RAIZ / item["imagem"]
            if img.exists():
                img.unlink()                    # tira a imagem do site público depois de publicada
        except Exception as e:                  # noqa: BLE001
            falhas += 1
            if not parar:
                parar = f"cancelado: o story anterior ({arq.name}) falhou"
                item.update(status="erro", erro=str(e)[:500])
                log(f"  ERRO no story: {e}")
            else:
                item.update(status="cancelado", erro=parar)
            item["tentativa_em"] = agora().isoformat(timespec="seconds")
        item.pop("_quando", None)
        with destino.open("w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        arq.unlink()
    return falhas


def teste_container() -> int:
    """Valida chave, permissão, link do vídeo e trial_params sem publicar nada."""
    eu = api("GET", "me", fields="user_id,username")
    ig_id = eu.get("user_id") or eu.get("id")
    log(f"Conta: @{eu.get('username')}")
    try:
        lim = api("GET", f"{ig_id}/content_publishing_limit", fields="quota_usage,config")
        log(f"Cota de publicação: {json.dumps(lim.get('data', lim), ensure_ascii=False)[:200]}")
    except RuntimeError as e:
        log(f"Cota de publicação não lida: {e}")
    url = f"{base_url_video()}/videos/_teste.mp4"
    esperar_video_publico(url)
    container = api("POST", f"{ig_id}/media", media_type="REELS", video_url=url,
                    caption="teste técnico (não publicado)", share_to_feed="false",
                    trial_params=json.dumps({"graduation_strategy": "MANUAL"}))["id"]
    log("Contêiner de reel de teste criado; aguardando processamento")
    for _ in range(60):
        st = api("GET", container, fields="status_code,status")
        if st.get("status_code") == "FINISHED":
            log("OK: o Instagram aceitou o vídeo como reel de teste. Nada foi publicado; o contêiner expira em 24 h.")
            return teste_story(ig_id)
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            log(f"ERRO no processamento: {st.get('status')}")
            return 1
        time.sleep(10)
    log("ERRO: processamento não terminou em 10 minutos")
    return 1


def teste_story(ig_id: str) -> int:
    """Se existir videos/_teste_story.jpg, cria um contêiner de story e NÃO publica."""
    if not (RAIZ / "videos" / "_teste_story.jpg").is_file():
        return 0
    url = f"{base_url_video()}/videos/_teste_story.jpg"
    esperar_video_publico(url)
    try:
        c = api("POST", f"{ig_id}/media", media_type="STORIES", image_url=url)["id"]
    except RuntimeError as e:
        log(f"ERRO: a chave não aceitou criar story: {e}")
        return 1
    for _ in range(30):
        st = api("GET", c, fields="status_code,status")
        if st.get("status_code") == "FINISHED":
            log("OK: o Instagram aceitou a imagem como story. Nada foi publicado; o contêiner expira em 24 h.")
            return 0
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            log(f"ERRO no story de teste: {st.get('status')}")
            return 1
        time.sleep(5)
    log("ERRO: story de teste não ficou pronto em 2,5 minutos")
    return 1


METRICAS = ["views", "reach", "shares", "saved", "likes", "comments"]


def medir() -> int:
    """Lê os insights dos reels publicados há 48 h ou mais e grava no JSON de cada um."""
    lidos = 0
    for arq in sorted(PUBLICADOS.glob("*.json")):
        with arq.open(encoding="utf-8") as f:
            item = json.load(f)
        if item.get("status") != "publicado" or item.get("insights_48h") or not item.get("media_id"):
            continue
        if eh_story(item):
            continue                            # story some em 24 h; insights de story ficam fora daqui
        quando = dt.datetime.fromisoformat(item["publicado_em"]).astimezone(BRT)
        if agora() - quando < dt.timedelta(hours=48):
            continue
        valores, faltou = {}, []
        for m in METRICAS:
            try:
                r = api("GET", f"{item['media_id']}/insights", metric=m)
                valores[m] = r["data"][0]["values"][0]["value"]
            except (RuntimeError, KeyError, IndexError):
                faltou.append(m)
        item["insights_48h"] = valores
        item["insights_lidos_em"] = agora().isoformat(timespec="seconds")
        if faltou:
            item["insights_nao_lidos"] = faltou
        with arq.open("w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        lidos += 1
        log(f"{arq.name}: {valores}")
    log(f"Insights lidos: {lidos}")
    return 0


def _gh(metodo: str, caminho: str, **corpo) -> dict | list | None:
    """Chamada à API do GitHub com o GITHUB_TOKEN do próprio workflow (para o aviso por issue)."""
    tok, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not tok or not repo:
        return None
    r = requests.request(metodo, f"https://api.github.com/repos/{repo}/{caminho.lstrip('/')}",
                         headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
                         json=corpo or None, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub {metodo} {caminho} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


def _bonde_disponivel(b: dict) -> list[str]:
    fora = {_norm(u) for u in b.get("nunca_convidar", {})} | {_norm(u) for u in b.get("fora_automatico", {})}
    fora |= {_norm(u) for u in b.get("so_com_conversa", {})}
    vistos, saida = set(), []
    for u in [*b.get("fixas", []), *b.get("rotacao", [])]:
        u = _norm(u)
        if u not in fora and u not in vistos:
            vistos.add(u)
            saida.append(u)
    return saida


def avisar_trocas(trocas: list[dict], b: dict) -> None:
    """Abre/comenta uma issue quando um post de ontem tem convite pendente; fecha quando não há."""
    try:
        abertas = [i for i in (_gh("GET", "issues?state=open&per_page=50") or [])
                   if i.get("title") == TITULO_AVISO and "pull_request" not in i]
        if not trocas:
            for i in abertas:
                _gh("PATCH", f"issues/{i['number']}", state="closed")
            return
        linhas = ["Convites de collab que ainda não foram aceitos 24 h depois do post. "
                  "Se quiser, edite o post no app e troque pelas sugeridas (regra do Mapa de Collabs).", ""]
        for t in trocas:
            sugestao = [u for u in _bonde_disponivel(b) if u not in t["no_post"]][:len(t["pendentes"])]
            linhas.append(f"- **Post de {t['quando']:%d/%m %H:%M}** ({t['link']}): ainda não aceitaram "
                          f"{', '.join('@' + u for u in t['pendentes'])}."
                          + (f" Trocar por: {', '.join('@' + u for u in sugestao)}." if sugestao else ""))
        corpo = "\n".join(linhas)
        if abertas:
            _gh("POST", f"issues/{abertas[0]['number']}/comments", body=corpo)
        else:
            _gh("POST", "issues", title=TITULO_AVISO, body=corpo)
        log(f"Aviso de troca enviado ({len(trocas)} post(s)).")
    except RuntimeError as e:
        log(f"Aviso de troca não enviado: {e}")


def escrever_relatorio_colab(b: dict, conferidos: list[str], trocas: list[dict]) -> None:
    RELATORIO_COLAB.parent.mkdir(exist_ok=True)
    fixas = {_norm(u) for u in b.get("fixas", [])}
    rot = {_norm(u) for u in b.get("rotacao", [])}
    fora = {_norm(u) for u in b.get("fora_automatico", {})} | {_norm(u) for u in b.get("nunca_convidar", {})}
    conversa = {_norm(u) for u in b.get("so_com_conversa", {})}

    def papel(u: str) -> str:
        return ("fixa" if u in fixas else "rotação" if u in rot else "fora" if u in fora
                else "só com conversa" if u in conversa else "fora do bonde")

    placar = sorted(b.get("placar", {}).items(), key=lambda kv: (-kv[1].get("aceitos", 0), kv[0]))
    ls = [f"# Collab · placar do bonde (atualizado {agora():%d/%m/%Y %H:%M})", "",
          "Gerado pelo robô. Conta só posts conferidos a partir de 24/10/2026, 24 h depois de publicados.", "",
          "| Página | Papel | Convites | Aceitos | Pendentes seguidos | Último post | Último status |",
          "|---|---|---:|---:|---:|---|---|"]
    for u, p in placar:
        ls.append(f"| @{u} | {papel(u)} | {p.get('convites', 0)} | {p.get('aceitos', 0)} | "
                  f"{p.get('pendentes_seguidos', 0)} | {p.get('ultimo_post', '')} | {p.get('ultimo_status', '')} |")
    ls += ["", "## Conferidos nesta rodada", ""] + ([f"- {c}" for c in conferidos] or ["- nenhum post novo com 24 h ou mais"])
    ls += ["", "## Trocar no app hoje", ""]
    ls += [f"- {t['quando']:%d/%m %H:%M} · {t['link']} · pendentes: {', '.join('@' + u for u in t['pendentes'])}"
           for t in trocas] or ["- nada"]
    if b.get("fora_automatico"):
        ls += ["", "## Saíram do bonde sozinhas", ""] + [f"- @{u}: {m}" for u, m in b["fora_automatico"].items()]
    with RELATORIO_COLAB.open("w", encoding="utf-8") as f:
        f.write("\n".join(ls) + "\n")


def conferir_colab(ig_id: str | None = None) -> int:
    """Lê quem aceitou os convites nos posts de 1 a 7 dias e atualiza bonde.json e o relatório."""
    b = ler_bonde()
    if not b:
        log("bonde.json não existe: conferência de collab pulada.")
        return 0
    if str(b.get("leitura_colaboradores", "")).startswith("indisponível") and MODO != "colab":
        # A chave atual (login do Instagram) não lê /collaborators: a Meta só libera com login do Facebook.
        # Rodar o modo 'colab' testa de novo (por exemplo, depois de trocar a chave).
        log("Conferência de collab pulada: a chave atual não lê colaboradores (rode o modo 'colab' para testar de novo).")
        return 0
    if ig_id is None:
        eu = api("GET", "me", fields="user_id,username")
        ig_id = eu.get("user_id") or eu.get("id")
    midias = api("GET", f"{ig_id}/media", fields="id,timestamp,permalink", limit=30).get("data", [])
    placar = b.setdefault("placar", {})
    vistos = list(b.get("posts_conferidos", []))
    conferidos, trocas, erros, lidos = [], [], [], 0
    for m in sorted(midias, key=lambda x: x.get("timestamp", "")):
        quando = dt.datetime.fromisoformat(m["timestamp"]).astimezone(BRT)
        idade = agora() - quando
        if idade < dt.timedelta(hours=24) or idade > dt.timedelta(days=7):
            continue
        try:
            colabs = api("GET", f"{m['id']}/collaborators").get("data", [])
            lidos += 1
        except RuntimeError as e:
            erros.append(str(e))
            continue
        if not colabs:
            continue
        pend = [_norm(c.get("username", "")) for c in colabs
                if not str(c.get("invite_status", "")).strip().lower().startswith("ac")]
        no_post = [_norm(c.get("username", "")) for c in colabs]
        if pend and idade <= dt.timedelta(hours=48):
            trocas.append({"quando": quando, "link": m.get("permalink", ""), "pendentes": pend, "no_post": no_post})
        if m["id"] in vistos:
            continue
        vistos.append(m["id"])
        aceitos_post = []
        for c in colabs:
            u = _norm(c.get("username", ""))
            aceitou = str(c.get("invite_status", "")).strip().lower().startswith("ac")
            p = placar.setdefault(u, {"convites": 0, "aceitos": 0, "pendentes_seguidos": 0})
            p["convites"] += 1
            if aceitou:
                p["aceitos"] += 1
                p["pendentes_seguidos"] = 0
                aceitos_post.append(u)
            else:
                p["pendentes_seguidos"] += 1
            p["ultimo_post"] = f"{quando:%d/%m}"
            p["ultimo_status"] = "aceitou" if aceitou else "pendente"
        conferidos.append(f"{quando:%d/%m %H:%M} · {m.get('permalink', '')} · aceitaram: "
                          f"{', '.join(aceitos_post) or 'ninguém'} · pendentes: {', '.join(pend) or 'ninguém'}")
    if erros and not lidos:
        log(f"Leitura de colaboradores indisponível com esta chave: {erros[0][:300]}")
        b["leitura_colaboradores"] = f"indisponível ({agora():%d/%m %H:%M})"
        gravar_bonde(b)
        return 0
    b["leitura_colaboradores"] = f"ok ({agora():%d/%m %H:%M})"

    lim = int(b.get("limite_pendentes_seguidos", 2))
    for u, p in placar.items():
        if p.get("pendentes_seguidos", 0) < lim:
            continue
        if u in {_norm(x) for x in b.get("fixas", [])} | {_norm(x) for x in b.get("rotacao", [])}:
            b["fixas"] = [x for x in b.get("fixas", []) if _norm(x) != u]
            b["rotacao"] = [x for x in b.get("rotacao", []) if _norm(x) != u]
            b.setdefault("fora_automatico", {})[u] = f"{lim} convites seguidos pendentes (conferido em {agora():%d/%m})"
            log(f"@{u} saiu do bonde: {lim} convites seguidos pendentes.")
    while len(b.get("fixas", [])) < int(b.get("n_fixas", 2)) and b.get("rotacao"):
        promovida = b["rotacao"].pop(0)
        b["fixas"].append(promovida)
        log(f"@{promovida} subiu para fixa.")
    if b.get("rotacao"):
        b["proxima_rotacao"] = int(b.get("proxima_rotacao", 0)) % len(b["rotacao"])
    b["posts_conferidos"] = vistos[-300:]
    gravar_bonde(b)
    escrever_relatorio_colab(b, conferidos, trocas)
    for c in conferidos:
        log(f"Collab {c}")
    log(f"Collab: {lidos} post(s) lido(s), {len(conferidos)} novo(s) no placar, {len(trocas)} para trocar.")
    avisar_trocas(trocas, b)
    return 0


def diagnostico_colab() -> int:
    """Testa, sem publicar, se a chave lê colaboradores e se aceita o campo collaborators."""
    eu = api("GET", "me", fields="user_id,username")
    ig_id = eu.get("user_id") or eu.get("id")
    log(f"Conta: @{eu.get('username')}")
    midias = api("GET", f"{ig_id}/media", fields="id,timestamp", limit=8).get("data", [])
    for m in midias:
        try:
            colabs = api("GET", f"{m['id']}/collaborators").get("data", [])
            log(f"Leitura OK {m['timestamp'][:10]}: " + (", ".join(f"{c.get('username')}={c.get('invite_status')}"
                                                            for c in colabs) or "sem colaborador"))
        except RuntimeError as e:
            log(f"Leitura FALHOU {m['timestamp'][:10]}: {e}")
    url = f"{base_url_video()}/videos/_teste.mp4"
    esperar_video_publico(url)
    alvo = (escolher_bonde(ler_bonde())[0] or ["bdo_019_"])[:1]
    for formato, valor in (("json", json.dumps(alvo)), ("virgula", ",".join(alvo))):
        try:
            c = api("POST", f"{ig_id}/media", media_type="REELS", video_url=url, share_to_feed="false",
                    caption="teste técnico (não publicado)", collaborators=valor)["id"]
            log(f"Criação OK: contêiner aceito com collaborators no formato '{formato}' ({alvo[0]}). "
                f"Nada foi publicado; o contêiner expira em 24 h. Contêiner {c}")
            if formato == "virgula":
                b = ler_bonde()
                b["formato_colaboradores"] = "virgula"
                gravar_bonde(b)
            return 0
        except RuntimeError as e:
            log(f"Criação com collaborators no formato '{formato}' FALHOU: {e}")
    return 1


def main() -> int:
    if MODO == "teste":
        return teste_container()
    if MODO in ("medir", "colab"):
        if not TOKEN:
            log("IG_TOKEN não configurado.")
            return 1
        codigo = medir() if MODO == "medir" else diagnostico_colab()
        try:
            conferir_colab()
        except Exception as e:  # noqa: BLE001  (a conferência de collab nunca derruba a medição)
            log(f"Conferência de collab falhou: {e}")
        return codigo
    fila = ler_fila()
    vencidos = [(a, i) for a, i in fila if i["_quando"] <= agora()]
    if not vencidos and not DRY_RUN:
        print(f"Nada vencido agora ({len(fila)} na fila).")
        return 0
    if not TOKEN:
        log("IG_TOKEN não configurado (Settings → Secrets and variables → Actions).")
        return 1
    eu = api("GET", "me", fields="user_id,username")
    ig_id = eu.get("user_id") or eu.get("id")
    log(f"Conta: @{eu.get('username')}")
    log(f"Fila: {len(fila)} agendado(s), {len(vencidos)} com horário vencido")
    if DRY_RUN:
        for a, i in fila:
            tipo = 'STORY' if eh_story(i) else ('TESTE' if i.get('teste', True) else 'SEGUIDORES')
            log(f"  {i['_quando']:%d/%m %H:%M} · {tipo} · {a.name}")
        return 0

    stories_vencidos = [(a, i) for a, i in vencidos if eh_story(i)]
    reels_vencidos = [(a, i) for a, i in vencidos if not eh_story(i)]
    falhas = rodar_stories(stories_vencidos, ig_id) if stories_vencidos else 0
    for arq, item in reels_vencidos[:1]:        # no máximo 1 reel por rodada
        n_hoje, ultimo = publicados_hoje_e_ultimo()
        if n_hoje >= MAX_API_POR_DIA:
            log(f"Pulado {arq.name}: já saíram {n_hoje} pela API hoje (teto {MAX_API_POR_DIA}).")
            break
        if ultimo and agora() - ultimo < dt.timedelta(hours=MIN_HORAS_ENTRE_API):
            log(f"Aguardando {arq.name}: a última publicação foi às {ultimo:%H:%M} (mínimo de {MIN_HORAS_ENTRE_API} h).")
            break
        destino = PUBLICADOS / arq.name
        try:
            if agora() - item["_quando"] > dt.timedelta(hours=MAX_ATRASO_HORAS):
                raise RuntimeError(f"atrasado mais de {MAX_ATRASO_HORAS} h; não publicado para não furar a cadência")
            log(f"Publicando {arq.name} ({'reel de teste, ' + item.get('graduacao', 'SS_PERFORMANCE') if item.get('teste', True) else 'para os seguidores'})")
            bonde = ler_bonde()
            proxima_rotacao = aplicar_bonde(item, bonde)
            validar(item)
            res = publicar(item, ig_id)
            item.update(res, status="publicado")
            log(f"  publicado: {res['link']}")
            if proxima_rotacao is not None:
                bonde = ler_bonde()
                bonde["proxima_rotacao"] = proxima_rotacao
                gravar_bonde(bonde)
            video = RAIZ / item["video"]
            if video.exists():
                video.unlink()                  # tira o arquivo do site público depois de publicado
        except Exception as e:                  # noqa: BLE001
            falhas += 1
            item.update(status="erro", erro=str(e)[:500], tentativa_em=agora().isoformat(timespec="seconds"))
            log(f"  ERRO: {e}")
        item.pop("_quando", None)
        with destino.open("w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        arq.unlink()

    return 1 if falhas else 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception as e:  # noqa: BLE001
        log(f"ERRO geral: {e}")
        codigo = 1
    resumo_arq = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo_arq:
        with open(resumo_arq, "a", encoding="utf-8") as f:
            f.write("\n".join(f"- {l}" for l in resumo) + "\n")
    sys.exit(codigo)
