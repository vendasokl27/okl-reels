#!/usr/bin/env python3
"""Responde sozinho os comentários do canal VENDAS OKL no YouTube, na voz do Dr. X.

O Dr. X é o Cientista Maluco da logo. Quem segue é "cobaia"; quem compra sai
"vacinado contra réplica". Identidade completa no Vault OKL, nota
"Personagem IA - Cientista Maluco", seção "Identidade nas redes: Dr. X".

Roda no GitHub Actions a cada 30 min. A cada rodada:
1. lê os comentários dos vídeos do canal (últimos DIAS dias);
2. acha o que ainda não tem resposta do canal depois dele;
3. responde no estilo Dr. X (sem link, sem atestar peça que não é nossa);
4. pula spam, golpe de link e xingamento pesado.

Não guarda estado: "já respondido" é conferido no próprio YouTube (resposta do
canal depois do comentário). Uso de cota: 1 unidade por leitura, 50 por resposta,
10.000 por dia.

Segredos: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (conta do canal,
escopo youtube.force-ssl). DRY_RUN=1 mostra o que responderia, sem responder.
Teste local do estilo: python scripts/youtube_respostas.py --teste "quanto custa?"
"""
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/youtube/v3"
DRY = os.environ.get("DRY_RUN", "0").strip() == "1"
MAX_POR_RODADA = int(os.environ.get("MAX_POR_RODADA", "40"))
DIAS = int(os.environ.get("DIAS", "30"))
MAX_DO_ROBO_POR_CONVERSA = 4
ASSINATURA = " ~Dr. X"

# ---------------------------------------------------------------------------
# Estilo Dr. X
# ---------------------------------------------------------------------------

PT = {
    "comprou": [
        "Mais uma cobaia vacinada contra réplica 💉✅",
        "Vacina aplicada com sucesso, cobaia! Agora você é imune a réplica 💉",
        "Experimento concluído: cobaia vacinada contra réplica 💉✅ Bem-vindo ao bunker!",
    ],
    "golpe": [
        "Aqui é só peça original, testada no laboratório e com procedência, cobaia. Chama no WhatsApp do link do canal que o Doutor te mostra tudo 💉",
        "Réplica não entra no bunker, cobaia. Quer conferir? Chama no WhatsApp do link do canal que o Doutor mostra peça por peça 🧪",
    ],
    "original": [
        "Passou pelo laboratório, cobaia. Réplica não entra no bunker ☠️",
        "Testada no laboratório, cobaia. Aqui é 100% original 💉",
        "Original, cobaia. Réplica aqui não passa nem da porta do bunker ☠️",
    ],
    "original_terceiro": [
        "Essa é do acervo do criador do vídeo, cobaia. As do nosso laboratório saem testadas e com procedência 💉",
        "Essa peça é do criador do vídeo, cobaia. As que saem do nosso bunker são testadas no laboratório 🧪",
    ],
    "preco": [
        "Chama no WhatsApp do link do canal que o Doutor te passa a fórmula 💉",
        "A fórmula (e o preço) o Doutor passa no WhatsApp do link do canal, cobaia 💉",
        "Chama no WhatsApp do link do canal ou no Insta @vendas.okl que o Doutor te atende, cobaia 🧪",
    ],
    "preco_terceiro": [
        "Essa é do acervo do criador do vídeo, cobaia. As do nosso laboratório estão no WhatsApp do link do canal 💉",
        "Essa peça é do criador do vídeo. Peças do nosso bunker: chama no WhatsApp do link do canal, cobaia 🧪",
    ],
    "contato": [
        "O WhatsApp do Doutor está no link do canal, cobaia 💉",
        "Tá no link do canal, cobaia: WhatsApp e Insta @vendas.okl 🧪",
    ],
    "modelo_terceiro": [
        "Boa pergunta, cobaia! Quem conhece essa de perto é o criador do vídeo (o @ dele está na descrição) 🧪",
    ],
    "desejo_terceiro": [
        "Peça de respeito, cobaia ⚡ Os experimentos do nosso bunker estão no WhatsApp do link do canal",
    ],
    "raro_terceiro": [
        "Peça de respeito, cobaia ⚡ Raridade de verdade",
        "Coisa de colecionador, cobaia ⚡ O laboratório aprova",
    ],
    "modelo": [
        "Boa pergunta, cobaia! O nome e a ficha completa o Doutor passa no WhatsApp do link do canal 🧪",
        "É peça de laboratório, cobaia ⚡ Chama no WhatsApp do link do canal que o Doutor te passa a ficha",
    ],
    "ia": [
        "O Doutor foi feito em laboratório, cobaia 🧪 As peças é que são 100% reais.",
        "MUAHAHA o Doutor saiu do laboratório, cobaia 🧪 Mas as peças são todas reais e originais.",
    ],
    "caramelo": [
        "O Caramelo agradece. Ele fareja réplica de longe 🐶",
        "O Caramelo mandou um abraço, cobaia 🐶 Assistente oficial do laboratório",
    ],
    "amigo": [
        "Traz ele pro laboratório 🧪",
        "Chama a cobaia pro laboratório que tem vaga 🧪",
        "Mais uma cobaia chegando no bunker ⚡",
    ],
    "desejo": [
        "Então chama no WhatsApp do link do canal antes que outra cobaia leve ⚡",
        "Experimento raro, cobaia. Desse só sai um do bunker ⚡",
        "Quem quer, chama no WhatsApp do link do canal 💉 O Doutor separa pra você",
    ],
    "raro": [
        "Experimento raro. Desse só sai um do bunker ⚡",
        "Peça de laboratório, cobaia. Rara de verdade ⚡",
    ],
    "risada": [
        "MUAHAHA 🧪",
        "MUAHAHAHA tamo junto, cobaia 🧪",
        "MUAHAHA ⚡",
    ],
    "hater": [
        "MUAHAHA 🧪",
        "MUAHAHA o laboratório agradece a visita, cobaia 🧪",
    ],
    "elogio": [
        "Tamo junto, cobaia! 🧪",
        "Valeu demais, cobaia! O laboratório agradece 🧪",
        "Tamo junto, cobaia! Réplica não entra no bunker ☠️",
        "Aprovado no laboratório, cobaia ⚡",
    ],
    "pergunta": [
        "Boa pergunta, cobaia! Chama no WhatsApp do link do canal que o Doutor te responde com calma 🧪",
        "O Doutor responde tudo no WhatsApp do link do canal, cobaia 💉",
    ],
    "padrao": [
        "Tamo junto, cobaia! 🧪",
        "Bem-vindo ao laboratório, cobaia ⚡",
        "Valeu, cobaia! O Doutor agradece 🧪",
        "Tamo junto, cobaia! 💉",
    ],
}

EN = {
    "comprou": ["Another guinea pig vaccinated against replicas 💉✅",
                "Vaccine applied, guinea pig! You are now immune to replicas 💉"],
    "golpe": ["Only original pieces here, lab tested and traceable, guinea pig. DM us on Instagram @vendas.okl and the Doctor shows you everything 💉"],
    "original": ["Lab tested, guinea pig. No replicas get into the bunker ☠️",
                 "100% original, guinea pig. Tested in the lab 💉"],
    "original_terceiro": ["That piece belongs to the creator of the video, guinea pig. Ours leave the lab tested 💉"],
    "preco": ["DM us on Instagram @vendas.okl and the Doctor sends you the formula 💉",
              "The formula (and the price) is on Instagram @vendas.okl, guinea pig 💉"],
    "preco_terceiro": ["That piece belongs to the creator of the video. Ours are on Instagram @vendas.okl, guinea pig 💉"],
    "contato": ["Find us on Instagram @vendas.okl, guinea pig 💉"],
    "modelo_terceiro": ["Good question, guinea pig! The creator of the video knows this one best (handle in the description) 🧪"],
    "desejo_terceiro": ["A serious piece, guinea pig ⚡ Ours are on Instagram @vendas.okl"],
    "raro_terceiro": ["A serious piece, guinea pig ⚡ Real collector stuff"],
    "modelo": ["Good question, guinea pig! DM us on Instagram @vendas.okl for the full spec sheet 🧪"],
    "ia": ["The Doctor was made in a lab, guinea pig 🧪 The pieces are 100% real."],
    "caramelo": ["Caramelo says thanks. He can smell a replica from miles away 🐶"],
    "amigo": ["Bring them to the lab 🧪", "One more guinea pig coming to the bunker ⚡"],
    "desejo": ["Then DM us on Instagram @vendas.okl before another guinea pig takes it ⚡",
               "Rare experiment, guinea pig. Only one of these leaves the bunker ⚡"],
    "raro": ["Rare experiment. Only one of these leaves the bunker ⚡"],
    "risada": ["MUAHAHA 🧪", "MUAHAHAHA cheers, guinea pig 🧪"],
    "hater": ["MUAHAHA 🧪"],
    "elogio": ["Thanks, guinea pig! The lab appreciates it 🧪", "Respect from the lab, guinea pig ⚡",
               "Lab approved, guinea pig 🧪"],
    "pergunta": ["Good question, guinea pig! DM us on Instagram @vendas.okl and the Doctor answers 🧪"],
    "padrao": ["Cheers, guinea pig! 🧪", "Welcome to the lab, guinea pig ⚡", "Thanks, guinea pig! 💉"],
}


def norm(texto):
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def tem(t, termos):
    """Procura cada termo como palavra inteira (ou trecho, se terminar em *)."""
    for termo in termos:
        if termo.endswith("*"):
            if re.search(r"(?<!\w)" + re.escape(termo[:-1]), t):
                return True
        elif re.search(r"(?<!\w)" + re.escape(termo) + r"(?!\w)", t):
            return True
    return False


SPAM = ["http*", "www.*", "t.me*", "telegram", "bit.ly*", "sub4sub", "my channel", "meu canal",
        "check out my", "visit my", "follow me", "me segue", "segue la", "bitcoin", "forex", "cripto*",
        "crypto*", "investimento*", "renda extra", "ganhe dinheiro", "onlyfans", "promo code"]
PESADO = ["vtnc", "fdp", "filho da puta", "vai tomar no", "vai se fuder", "vai se foder", "arrombad*",
          "retardad*", "viado", "puta que te pariu", "fuck you"]
HATER = ["lixo", "horrivel", "feio", "feia", "cringe", "chato", "bosta", "ridicul*", "merda", "pessimo",
         "nojo*", "trash", "ugly", "boring", "sucks", "cafona", "brega"]
GOLPE = ["golpe*", "golpista*", "falsificad*", "pirata", "scam*", "scammer*"]
ORIGINAL = ["original", "originais", "replica*", "fake", "falso", "falsa", "autentic*", "verdadeir*",
            "legit", "real?", "e real", "authentic*", "genuine", "paraguai*", "china", "1:1", "aaa"]
COMPROU = ["comprei", "chegou", "recebi", "ja comprei", "comprei com", "meu chegou", "minha chegou",
           "ja sou cliente", "sou cliente", "bought", "received", "got mine", "arrived"]
PRECO = ["preco", "precos", "quanto", "valor", "vende", "vendem", "vendendo", "venda", "vendas?", "comprar",
         "compro", "onde acho", "onde encontro", "onde compra", "onde compro", "disponivel", "tem ainda",
         "ainda tem", "tem pra", "r$", "pix", "frete", "envia",
         "entrega", "parcela*", "price", "how much", "sell", "selling", "buy", "available", "for sale",
         "cost", "ship", "shipping"]
CONTATO = ["whats", "whatsapp", "zap", "zapzap", "contato", "numero", "telefone", "insta", "instagram"]
MODELO = ["qual modelo", "que modelo", "qual o modelo", "qual e o modelo", "qual oculos", "que oculos",
          "qual o oculos", "nome do", "nome dessa", "nome desse", "qual e esse", "qual e essa", "qual relogio",
          "que relogio", "qual lente", "what model", "which model", "what glasses", "what watch",
          "name of", "what is this", "which one"]
IA = ["inteligencia artificial", "feito com ia", "feito por ia", "gerado por ia", "e ia", "eh ia", "isso e ia",
      "so ia", "ia?", "robo", "cgi", "made with ai", "is this ai", "is it ai", "ai generated"]
NOSSOS_HANDLES = ("@vendas.okl", "@vendasokl")
CARAMELO = ["caramelo", "cachorro", "cachorrinho", "doguinho", "dog", "cao", "pet", "vira-lata", "vira lata",
            "puppy", "doggo"]
DESEJO = ["quero", "queria", "preciso", "desejo", "sonho", "me da", "meu sonho", "want", "need", "dream",
          "grail", "i wish"]
RARO = ["raro", "rara", "raridade", "dificil", "rare", "unicorn", "grail"]
RISADA = ["kkk*", "hahaha*", "haha", "rsrs*", "lol", "lmao", "kakak*", "ksks*"]
RISADA_EMOJI = ["😂", "🤣", "😆", "😹"]
ELOGIO = ["top", "brabo", "braba", "lindo", "linda", "lindos", "foda", "show", "massa", "insano", "insana",
          "monstro", "sensacional", "perfeito", "perfeita", "incrivel", "maravilh*", "nice", "cool", "fire",
          "love", "beautiful", "amazing", "awesome", "clean", "sick", "goat", "daora", "da hora", "zica",
          "absurdo", "absurda", "bonito", "bonita", "bom demais", "melhor", "brabissimo", "pica", "estilo",
          "classe", "elegante", "obra de arte", "icone", "lenda", "legend*", "best", "great", "dope", "wow",
          "uau", "caraca", "nossa", "parabens", "sucesso", "chave", "chavoso", "respeito", "brutal"]
ELOGIO_EMOJI = ["🔥", "😍", "❤", "💯", "👏", "🙌", "🤩", "😎", "👌", "💎", "🚀", "🤘"]

EN_PALAVRAS = {"the", "is", "this", "that", "what", "how", "much", "my", "you", "your", "love", "nice",
               "these", "are", "price", "where", "can", "i", "it", "so", "cool", "awesome", "for", "with"}
PT_PALAVRAS = {"o", "a", "e", "que", "de", "do", "da", "esse", "essa", "isso", "quanto", "muito", "meu",
               "minha", "voce", "vc", "pra", "para", "tem", "nao", "sim", "top", "mano", "irmao", "show"}


def idioma(t):
    palavras = re.findall(r"[a-z]+", t)
    en = sum(p in EN_PALAVRAS for p in palavras)
    pt = sum(p in PT_PALAVRAS for p in palavras)
    return "en" if en > pt and en >= 2 else "pt"


def classificar(texto, terceiro=False, eh_resposta=False):
    """Devolve a categoria da resposta, ou None quando o comentário não deve ser respondido."""
    t = norm(texto).strip()
    if not t:
        return None
    if tem(t, SPAM) or re.search(r"(?<!\d)\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}(?!\d)", t):
        return None
    if tem(t, PESADO):
        return None
    # Em resposta dentro de conversa o YouTube põe "@fulano" no começo: não conta como marcar amigo.
    sem_mencao_inicial = re.sub(r"^\s*@[\w.\-]+\s*", "", t) if eh_resposta else t
    if tem(t, COMPROU):
        return "comprou"
    if tem(t, GOLPE):
        return "golpe" if not terceiro else "original_terceiro"
    if tem(t, ORIGINAL):
        return "original_terceiro" if terceiro else "original"
    if tem(t, PRECO):
        return "preco_terceiro" if terceiro else "preco"
    if tem(t, CONTATO):
        return "contato"
    if tem(t, MODELO):
        return "modelo_terceiro" if terceiro else "modelo"
    if tem(t, IA):
        return "ia"
    if tem(t, CARAMELO):
        return "caramelo"
    if any(h.strip(".") not in NOSSOS_HANDLES for h in re.findall(r"@[\w.\-]+", sem_mencao_inicial)):
        return "amigo"
    if tem(t, DESEJO):
        return "desejo_terceiro" if terceiro else "desejo"
    if tem(t, RARO):
        return "raro_terceiro" if terceiro else "raro"
    if tem(t, HATER):
        return "hater"
    if tem(t, RISADA) or any(e in texto for e in RISADA_EMOJI):
        return "risada"
    if tem(t, ELOGIO) or any(e in texto for e in ELOGIO_EMOJI):
        return "elogio"
    if "?" in t:
        return "pergunta"
    return "padrao"


def escrever(texto, comentario_id, terceiro=False, eh_resposta=False, autor=""):
    """Monta a resposta do Dr. X. Devolve (categoria, texto) ou (None, None)."""
    cat = classificar(texto, terceiro, eh_resposta)
    if cat is None:
        return None, None
    banco = EN if idioma(norm(texto)) == "en" else PT
    opcoes = banco.get(cat) or banco["padrao"]
    i = int(hashlib.sha1(comentario_id.encode()).hexdigest(), 16) % len(opcoes)
    resposta = opcoes[i] + ASSINATURA
    if eh_resposta and autor.startswith("@"):
        resposta = f"{autor} {resposta}"
    return cat, resposta


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

class ErroAPI(Exception):
    def __init__(self, status, motivo, corpo):
        super().__init__(f"HTTP {status} {motivo}: {corpo[:300]}")
        self.status, self.motivo = status, motivo


def http(metodo, url, dados=None, token=None, form=False):
    cab = {"Accept": "application/json"}
    corpo = None
    if dados is not None:
        if form:
            corpo = urllib.parse.urlencode(dados).encode()
            cab["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            corpo = json.dumps(dados).encode()
            cab["Content-Type"] = "application/json"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=corpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        motivo = ""
        try:
            j = json.loads(texto)
            err = j.get("error")
            if isinstance(err, dict):
                motivo = (err.get("errors") or [{}])[0].get("reason", "") or err.get("status", "")
            else:
                motivo = str(err or "")
        except ValueError:
            pass
        raise ErroAPI(e.code, motivo, texto)


def pegar_token():
    faltando = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if faltando:
        print("Ainda não configurado (segredos faltando: " + ", ".join(faltando) + "). Nada a fazer.")
        sys.exit(0)
    try:
        r = http("POST", "https://oauth2.googleapis.com/token", {
            "client_id": os.environ["YT_CLIENT_ID"].strip(),
            "client_secret": os.environ["YT_CLIENT_SECRET"].strip(),
            "refresh_token": os.environ["YT_REFRESH_TOKEN"].strip(),
            "grant_type": "refresh_token",
        }, form=True)
    except ErroAPI as e:
        print(f"Não consegui entrar na conta do canal: {e}")
        for nome, pref in (("YT_CLIENT_SECRET", 7), ("YT_REFRESH_TOKEN", 3)):
            v = os.environ[nome]
            print(f"  diagnóstico {nome}: {len(v.strip())} caracteres, começa com {v.strip()[:pref]!r}, "
                  f"espaço ou quebra no meio: {bool(re.search(r'\s', v.strip()))}")
        print("Se for invalid_grant, a autorização foi revogada ou expirou: gerar um refresh token novo "
              "(passo a passo na nota do vault 'YouTube - Canal e Shorts') e gravar em YT_REFRESH_TOKEN.")
        sys.exit(1)
    return r["access_token"]


def get(caminho, token, **params):
    return http("GET", f"{API}/{caminho}?{urllib.parse.urlencode(params)}", token=token)


def data(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def conversas(token, canal_id):
    """Comentários de topo dos últimos DIAS dias, com todas as respostas."""
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS)
    saida, pagina = [], None
    for _ in range(20):
        params = dict(part="snippet,replies", allThreadsRelatedToChannelId=canal_id, maxResults=100,
                      order="time", textFormat="plainText")
        if pagina:
            params["pageToken"] = pagina
        r = get("commentThreads", token, **params)
        velho = False
        for th in r.get("items", []):
            topo = th["snippet"]["topLevelComment"]
            if data(topo["snippet"]["publishedAt"]) < limite:
                velho = True
                continue
            respostas = (th.get("replies") or {}).get("comments", [])
            if th["snippet"].get("totalReplyCount", 0) > len(respostas):
                respostas, pr = [], None
                while True:
                    p = dict(part="snippet", parentId=th["id"], maxResults=100, textFormat="plainText")
                    if pr:
                        p["pageToken"] = pr
                    rr = get("comments", token, **p)
                    respostas += rr.get("items", [])
                    pr = rr.get("nextPageToken")
                    if not pr:
                        break
            saida.append((th, topo, sorted(respostas, key=lambda c: c["snippet"]["publishedAt"])))
        pagina = r.get("nextPageToken")
        if not pagina or velho:
            break
    return saida


def videos_info(token, ids):
    info = {}
    ids = list(ids)
    for i in range(0, len(ids), 50):
        r = get("videos", token, part="snippet", id=",".join(ids[i:i + 50]))
        for v in r.get("items", []):
            info[v["id"]] = v["snippet"]
    return info


def eh_terceiro(snippet):
    """Vídeo de criador autorizado: título ou descrição cita um @ que não é o nosso."""
    texto = (snippet.get("title", "") + " " + snippet.get("description", "")).lower()
    for h in re.findall(r"@[\w.\-]+", texto):
        if h.strip(".") not in NOSSOS_HANDLES:
            return True
    return False


def autor_id(c):
    return ((c["snippet"].get("authorChannelId") or {}).get("value")) or ""


def pendentes(topo, respostas, meu_id):
    """O que ainda não tem resposta do canal depois dele: o mais recente de cada pessoa."""
    msgs = [topo] + respostas
    meus = [i for i, c in enumerate(msgs) if autor_id(c) == meu_id]
    if len(meus) >= MAX_DO_ROBO_POR_CONVERSA:
        return []
    depois = msgs[(meus[-1] + 1) if meus else 0:]
    por_pessoa = {}
    for c in depois:
        a = autor_id(c)
        if a and a != meu_id:
            por_pessoa[a] = c
    vagas = MAX_DO_ROBO_POR_CONVERSA - len(meus)
    return sorted(por_pessoa.values(), key=lambda c: c["snippet"]["publishedAt"])[:vagas]


def main():
    token = pegar_token()
    eu = get("channels", token, part="snippet", mine="true").get("items", [])
    if not eu:
        print("A conta autorizada não tem canal do YouTube.")
        sys.exit(1)
    meu_id, meu_nome = eu[0]["id"], eu[0]["snippet"]["title"]
    print(f"Canal: {meu_nome} ({meu_id}) · {'SIMULAÇÃO, nada é respondido' if DRY else 'respondendo'}")

    lista = conversas(token, meu_id)
    info = videos_info(token, {th["snippet"]["videoId"] for th, _, _ in lista if th["snippet"].get("videoId")})
    print(f"{len(lista)} conversas nos últimos {DIAS} dias")

    feitas = puladas = erros = 0
    parar = False
    for th, topo, respostas in lista:
        if parar:
            break
        if feitas >= MAX_POR_RODADA:
            print(f"Teto de {MAX_POR_RODADA} respostas por rodada: o resto fica para a próxima.")
            break
        if th["snippet"].get("canReply") is False:
            continue
        vid = th["snippet"].get("videoId", "")
        snip = info.get(vid, {})
        terceiro = eh_terceiro(snip)
        for c in pendentes(topo, respostas, meu_id):
            if feitas >= MAX_POR_RODADA or parar:
                break
            s = c["snippet"]
            texto = s.get("textOriginal") or s.get("textDisplay") or ""
            eh_resp = c is not topo
            cat, resposta = escrever(texto, c["id"], terceiro, eh_resp, s.get("authorDisplayName", ""))
            titulo = snip.get("title", vid)[:40]
            if not resposta:
                puladas += 1
                print(f"· pulado (spam/xingamento) [{titulo}] {texto[:80]!r}")
                continue
            print(f"→ [{titulo}] {texto[:80]!r}\n  {cat}: {resposta}")
            if DRY:
                feitas += 1
                continue
            try:
                http("POST", f"{API}/comments?part=snippet",
                     {"snippet": {"parentId": th["id"], "textOriginal": resposta}}, token=token)
                feitas += 1
                time.sleep(random.uniform(4, 9))
            except ErroAPI as e:
                erros += 1
                print(f"  ✗ erro: {e}")
                if e.motivo in ("quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"):
                    print("Cota do dia acabou: o resto fica para amanhã.")
                    parar = True
                elif e.status == 401:
                    sys.exit(1)
                elif erros >= 5 and feitas == 0:
                    print("Cinco erros seguidos sem nenhuma resposta: parando a rodada.")
                    parar = True

    acao = "responderia" if DRY else "respondidas"
    print(f"Fim: {feitas} {acao}, {puladas} puladas, {erros} erros.")
    if erros and not feitas:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--teste":
        for frase in sys.argv[2:]:
            for terceiro in (False, True):
                cat, r = escrever(frase, frase + str(terceiro), terceiro)
                print(f"{'terceiro' if terceiro else 'nosso   '} | {frase!r} → {cat}: {r}")
        sys.exit(0)
    main()
