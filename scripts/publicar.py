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
                 "teste" (cria um reel de teste com videos/_teste.mp4 e NÃO publica) ou
                 "medir" (lê os insights de 48 h dos reels publicados)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
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


def publicados_hoje_e_ultimo() -> tuple[int, dt.datetime | None]:
    hoje = agora().date()
    n, ultimo = 0, None
    for arq in PUBLICADOS.glob("*.json"):
        with arq.open(encoding="utf-8") as f:
            item = json.load(f)
        quando = item.get("publicado_em")
        if not quando:
            continue
        quando = dt.datetime.fromisoformat(quando).astimezone(BRT)
        if quando.date() == hoje:
            n += 1
        if ultimo is None or quando > ultimo:
            ultimo = quando
    return n, ultimo


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
        params["collaborators"] = json.dumps(item["colaboradores"][:3])
    if item.get("teste", True):
        params["trial_params"] = json.dumps({"graduation_strategy": item.get("graduacao", "SS_PERFORMANCE")})
    if item.get("ia"):
        params["is_ai_generated"] = "true"     # selo "Informações de IA" (API desde 22/06/2026)

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
            return 0
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            log(f"ERRO no processamento: {st.get('status')}")
            return 1
        time.sleep(10)
    log("ERRO: processamento não terminou em 10 minutos")
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


def main() -> int:
    if MODO == "teste":
        return teste_container()
    if MODO == "medir":
        if not TOKEN:
            log("IG_TOKEN não configurado.")
            return 1
        return medir()
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
            log(f"  {i['_quando']:%d/%m %H:%M} · {'TESTE' if i.get('teste', True) else 'SEGUIDORES'} · {a.name}")
        return 0

    falhas = 0
    for arq, item in vencidos[:1]:              # no máximo 1 publicação por rodada
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
            validar(item)
            log(f"Publicando {arq.name} ({'reel de teste, ' + item.get('graduacao', 'SS_PERFORMANCE') if item.get('teste', True) else 'para os seguidores'})")
            res = publicar(item, ig_id)
            item.update(res, status="publicado")
            log(f"  publicado: {res['link']}")
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
