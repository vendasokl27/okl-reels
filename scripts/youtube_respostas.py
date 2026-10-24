#!/usr/bin/env python3
"""Responde sozinho os comentários do canal VENDAS OKL no YouTube, na voz do Dr. X.

O Dr. X é o Cientista Maluco da logo. Quem segue é "cobaia"; quem compra sai
"vacinado contra réplica". Identidade completa no Vault OKL, nota
"Personagem IA - Cientista Maluco", seção "Identidade nas redes: Dr. X".

REGRA (Thiago, 24/10/2026): o YouTube não vende. Lá o laboratório só mostra; a
plataforma de vendas é o Instagram @vendas.okl. Toda resposta (menos a de hater)
manda seguir o Instagram e, para comprar, chamar no Direct de lá. Sem preço,
WhatsApp, Pix ou link. `conferir_regra()` trava o robô se um texto fugir disso.

Roda no GitHub Actions a cada 30 min. A cada rodada:
1. troca, nas descrições dos vídeos do canal, o rodapé antigo (que mandava para o
   WhatsApp) pelo novo, que diz que a venda é só no Instagram;
2. deixa um comentário do Dr. X em todo vídeo público dos últimos DIAS dias que
   ainda não tem comentário do canal, mandando para o Instagram;
3. lê os comentários dos vídeos do canal (últimos DIAS dias), acha o que ainda não
   tem resposta do canal depois dele e responde no estilo Dr. X (sem link, sem
   atestar peça que não é nossa), sempre puxando para o Instagram;
4. pula spam, golpe de link e xingamento pesado.

Não guarda estado: "já respondido" é conferido no próprio YouTube (resposta do
canal depois do comentário). Uso de cota: 1 unidade por leitura, 50 por resposta,
50 por comentário de abertura, 50 por descrição corrigida, 10.000 por dia.

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
MAX_CTA_POR_RODADA = int(os.environ.get("MAX_CTA_POR_RODADA", "10"))
MAX_DESC_POR_RODADA = int(os.environ.get("MAX_DESC_POR_RODADA", "20"))
ASSINATURA = " ~Dr. X"

# ---------------------------------------------------------------------------
# Estilo Dr. X
# ---------------------------------------------------------------------------

# REGRA DO THIAGO (24/10/2026): o YouTube NÃO VENDE. Lá o laboratório só mostra.
# A plataforma de vendas é o Instagram @vendas.okl: toda resposta (menos a de hater)
# manda a pessoa seguir o Instagram e, quando quer comprar, chamar no Direct de lá.
# Nada de preço, WhatsApp, Pix, frete ou link no YouTube. `conferir_regra()` barra
# o robô se alguém reescrever um banco quebrando isso.
INSTA = "Instagram @vendas.okl"

PT = {
    "comprou": [
        "Mais uma cobaia vacinada contra réplica 💉✅ As próximas peças saem no Instagram @vendas.okl",
        "Vacina aplicada com sucesso, cobaia! Agora você é imune a réplica 💉 Segue o Instagram @vendas.okl pra ver as próximas",
        "Experimento concluído: cobaia vacinada contra réplica 💉✅ Bem-vindo ao bunker! O resto do acervo tá no Instagram @vendas.okl",
    ],
    "golpe": [
        "Aqui é só peça original, testada no laboratório e com procedência, cobaia. No YouTube o Doutor só mostra: peça por peça, à venda, só no Instagram @vendas.okl 💉",
        "Réplica não entra no bunker, cobaia. Quer conferir? Segue o Instagram @vendas.okl e chama no Direct que o Doutor mostra peça por peça 🧪",
    ],
    "original": [
        "Passou pelo laboratório, cobaia. Réplica não entra no bunker ☠️ As peças à venda estão no Instagram @vendas.okl",
        "Testada no laboratório, cobaia. Aqui é 100% original 💉 A vitrine do bunker é o Instagram @vendas.okl",
        "Original, cobaia. Réplica aqui não passa nem da porta do bunker ☠️ Segue o Instagram @vendas.okl",
    ],
    "original_terceiro": [
        "Essa é do acervo do criador do vídeo, cobaia. As do nosso laboratório saem testadas, com procedência, e são vendidas só no Instagram @vendas.okl 💉",
        "Essa peça é do criador do vídeo, cobaia. As que saem do nosso bunker são testadas no laboratório e estão no Instagram @vendas.okl 🧪",
    ],
    "preco": [
        "Aqui no YouTube o laboratório só mostra, cobaia. Venda é só no Instagram: segue @vendas.okl e chama no Direct que o Doutor te passa a fórmula 💉",
        "A fórmula (e o preço) é só no Instagram, cobaia: segue @vendas.okl e chama no Direct 💉",
        "No YouTube o Doutor não vende, cobaia. Venda é só no Instagram @vendas.okl: segue lá e chama no Direct 🧪",
    ],
    "preco_terceiro": [
        "Essa é do acervo do criador do vídeo, cobaia. As peças do nosso laboratório são vendidas só no Instagram @vendas.okl: segue e chama no Direct 💉",
        "Essa peça é do criador do vídeo. As do nosso bunker estão à venda só no Instagram @vendas.okl, cobaia: segue lá e chama no Direct 🧪",
    ],
    "contato": [
        "O Doutor atende só no Instagram @vendas.okl, cobaia: segue lá e chama no Direct 💉 (o link tá no perfil do canal)",
        "É no Instagram, cobaia: segue @vendas.okl e chama no Direct 🧪 Lá é a nossa loja",
    ],
    "modelo_terceiro": [
        "Boa pergunta, cobaia! Quem conhece essa de perto é o criador do vídeo (o @ dele está na descrição) 🧪 As peças do nosso laboratório estão no Instagram @vendas.okl",
    ],
    "desejo_terceiro": [
        "Peça de respeito, cobaia ⚡ Os experimentos do nosso bunker estão à venda no Instagram @vendas.okl",
    ],
    "raro_terceiro": [
        "Peça de respeito, cobaia ⚡ Raridade de verdade. As do nosso laboratório saem no Instagram @vendas.okl",
        "Coisa de colecionador, cobaia ⚡ O laboratório aprova. Segue o Instagram @vendas.okl",
    ],
    "modelo": [
        "Boa pergunta, cobaia! O nome e a ficha completa o Doutor passa no Direct do Instagram @vendas.okl 🧪",
        "É peça de laboratório, cobaia ⚡ Segue o Instagram @vendas.okl e chama no Direct que o Doutor te passa a ficha",
    ],
    "ia": [
        "O Doutor foi feito em laboratório, cobaia 🧪 As peças é que são 100% reais, e estão no Instagram @vendas.okl",
        "MUAHAHA o Doutor saiu do laboratório, cobaia 🧪 Mas as peças são todas reais e originais: Instagram @vendas.okl",
    ],
    "caramelo": [
        "O Caramelo agradece. Ele fareja réplica de longe 🐶 Ele também bate ponto no Instagram @vendas.okl",
        "O Caramelo mandou um abraço, cobaia 🐶 Assistente oficial do laboratório e do Instagram @vendas.okl",
    ],
    "amigo": [
        "Traz ele pro laboratório 🧪 A casa do bunker é o Instagram @vendas.okl",
        "Chama a cobaia pro laboratório que tem vaga 🧪 Segue o Instagram @vendas.okl",
        "Mais uma cobaia chegando no bunker ⚡ Leva ela pro Instagram @vendas.okl",
    ],
    "desejo": [
        "Então segue o Instagram @vendas.okl e chama no Direct antes que outra cobaia leve ⚡",
        "Experimento raro, cobaia. Desse só sai um do bunker ⚡ Venda é só no Instagram @vendas.okl",
        "Quem quer, chama no Direct do Instagram @vendas.okl 💉 O Doutor separa pra você",
    ],
    "raro": [
        "Experimento raro. Desse só sai um do bunker ⚡ Os raros aparecem primeiro no Instagram @vendas.okl",
        "Peça de laboratório, cobaia. Rara de verdade ⚡ Segue o Instagram @vendas.okl",
    ],
    "risada": [
        "MUAHAHA 🧪 Tem mais no Instagram @vendas.okl, cobaia",
        "MUAHAHAHA tamo junto, cobaia 🧪 Segue o laboratório no Instagram @vendas.okl",
        "MUAHAHA ⚡ O bunker mora no Instagram @vendas.okl",
    ],
    "hater": [
        "MUAHAHA 🧪",
        "MUAHAHA o laboratório agradece a visita, cobaia 🧪",
    ],
    "elogio": [
        "Tamo junto, cobaia! 🧪 Segue o laboratório no Instagram @vendas.okl",
        "Valeu demais, cobaia! O laboratório agradece 🧪 A vitrine do bunker é o Instagram @vendas.okl",
        "Tamo junto, cobaia! Réplica não entra no bunker ☠️ Segue o Instagram @vendas.okl",
        "Aprovado no laboratório, cobaia ⚡ Tem mais no Instagram @vendas.okl",
    ],
    "pergunta": [
        "Boa pergunta, cobaia! Chama no Direct do Instagram @vendas.okl que o Doutor te responde com calma 🧪",
        "O Doutor responde tudo no Direct do Instagram @vendas.okl, cobaia 💉",
    ],
    "padrao": [
        "Tamo junto, cobaia! 🧪 Segue o laboratório no Instagram @vendas.okl",
        "Bem-vindo ao laboratório, cobaia ⚡ A casa do bunker é o Instagram @vendas.okl",
        "Valeu, cobaia! O Doutor agradece 🧪 Segue o Instagram @vendas.okl",
        "Tamo junto, cobaia! 💉 O laboratório mora no Instagram @vendas.okl",
    ],
}

EN = {
    "comprou": ["Another guinea pig vaccinated against replicas 💉✅ The next pieces drop on Instagram @vendas.okl",
                "Vaccine applied, guinea pig! You are now immune to replicas 💉 Follow Instagram @vendas.okl for the next ones"],
    "golpe": ["Only original pieces here, lab tested and traceable, guinea pig. YouTube is just the showroom: we only sell on Instagram @vendas.okl 💉"],
    "original": ["Lab tested, guinea pig. No replicas get into the bunker ☠️ Pieces for sale are on Instagram @vendas.okl",
                 "100% original, guinea pig. Tested in the lab 💉 Follow Instagram @vendas.okl"],
    "original_terceiro": ["That piece belongs to the creator of the video, guinea pig. Ours leave the lab tested and are sold only on Instagram @vendas.okl 💉"],
    "preco": ["YouTube is just the showroom, guinea pig. We only sell on Instagram: follow @vendas.okl and DM the Doctor 💉",
              "The formula (and the price) is only on Instagram, guinea pig: follow @vendas.okl and send a DM 💉"],
    "preco_terceiro": ["That piece belongs to the creator of the video. Ours are sold only on Instagram @vendas.okl, guinea pig 💉"],
    "contato": ["Only on Instagram, guinea pig: follow @vendas.okl and send a DM 💉"],
    "modelo_terceiro": ["Good question, guinea pig! The creator of the video knows this one best (handle in the description) 🧪 Ours are on Instagram @vendas.okl"],
    "desejo_terceiro": ["A serious piece, guinea pig ⚡ Ours are for sale on Instagram @vendas.okl"],
    "raro_terceiro": ["A serious piece, guinea pig ⚡ Real collector stuff. Follow Instagram @vendas.okl"],
    "modelo": ["Good question, guinea pig! DM us on Instagram @vendas.okl for the full spec sheet 🧪"],
    "ia": ["The Doctor was made in a lab, guinea pig 🧪 The pieces are 100% real, and they are on Instagram @vendas.okl"],
    "caramelo": ["Caramelo says thanks. He can smell a replica from miles away 🐶 He is on Instagram @vendas.okl too"],
    "amigo": ["Bring them to the lab 🧪 Our home is Instagram @vendas.okl",
              "One more guinea pig coming to the bunker ⚡ Follow Instagram @vendas.okl"],
    "desejo": ["Then follow Instagram @vendas.okl and DM us before another guinea pig takes it ⚡",
               "Rare experiment, guinea pig. Only one of these leaves the bunker ⚡ We only sell on Instagram @vendas.okl"],
    "raro": ["Rare experiment. Only one of these leaves the bunker ⚡ Rare drops land first on Instagram @vendas.okl"],
    "risada": ["MUAHAHA 🧪 More on Instagram @vendas.okl", "MUAHAHAHA cheers, guinea pig 🧪 Follow Instagram @vendas.okl"],
    "hater": ["MUAHAHA 🧪"],
    "elogio": ["Thanks, guinea pig! The lab appreciates it 🧪 Follow Instagram @vendas.okl",
               "Respect from the lab, guinea pig ⚡ More on Instagram @vendas.okl",
               "Lab approved, guinea pig 🧪 Our home is Instagram @vendas.okl"],
    "pergunta": ["Good question, guinea pig! DM us on Instagram @vendas.okl and the Doctor answers 🧪"],
    "padrao": ["Cheers, guinea pig! 🧪 Follow Instagram @vendas.okl", "Welcome to the lab, guinea pig ⚡ Our home is Instagram @vendas.okl",
               "Thanks, guinea pig! 💉 Follow Instagram @vendas.okl"],
}

# Comentário do próprio canal em todo vídeo público (o Dr. X "abre" a conversa).
# A API do YouTube não fixa comentário: fixar, se quiser, é no app (3 pontinhos → Fixar).
CTA_VIDEO = {
    "nosso": ("🧪 Aqui no YouTube o laboratório só mostra, cobaia. As peças originais à venda estão só no "
              "Instagram @vendas.okl (link no perfil do canal): segue lá e chama no Direct 💉" + " ~Dr. X"),
    "terceiro": ("🧪 Esse vídeo é do criador citado na descrição. As peças do nosso laboratório, originais e à venda, "
                 "estão só no Instagram @vendas.okl (link no perfil do canal). Segue lá, cobaia 💉" + " ~Dr. X"),
}

# Rodapé das descrições: o antigo mandava para o WhatsApp; o novo deixa claro que a venda é no Instagram.
RODAPE_ANTIGO = ("🏴‍☠️ VENDAS.OKL: Oakley vintage 100% original. X-Metal, relógios e vestuário raro. "
                 "Compra, venda e troca.\n📲 Instagram: @vendas.okl\n💬 WhatsApp: link no perfil do canal")
RODAPE_NOVO = ("🛒 Aqui no YouTube a gente só mostra. Venda é só no Instagram @vendas.okl: segue lá e chama no Direct.\n"
               "📲 instagram.com/vendas.okl (link também no perfil do canal)\n"
               "🏴‍☠️ VENDAS.OKL: Oakley vintage 100% original. X-Metal, relógios e vestuário raro.")

PROIBIDO_NO_YOUTUBE = ["whats", "zap", "r$", "pix", "frete", "parcel", "http", "www.", "wa.me", "wa.link",
                       "link do canal"]


def conferir_regra():
    """Barra o robô se algum texto quebrar a regra 'YouTube não vende, manda pro Instagram'."""
    problemas = []
    textos = [(f"{nome}.{cat}", t) for nome, banco in (("PT", PT), ("EN", EN))
              for cat, opcoes in banco.items() for t in opcoes]
    textos += [(f"CTA.{k}", v) for k, v in CTA_VIDEO.items()]
    for onde, t in textos:
        baixo = t.lower()
        for termo in PROIBIDO_NO_YOUTUBE:
            if termo in baixo:
                problemas.append(f"{onde}: tem '{termo}' -> {t!r}")
        if not onde.endswith(".hater") and "instagram" not in baixo:
            problemas.append(f"{onde}: não manda para o Instagram -> {t!r}")
    for banco in (PT, EN):
        if set(banco) != set(PT):
            problemas.append("PT e EN com categorias diferentes")
    if problemas:
        print("REGRA QUEBRADA (YouTube não vende, manda pro Instagram):")
        for p in problemas:
            print("  " + p)
        sys.exit(1)


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
CONTATO = ["whats", "whatsapp", "zap", "zapzap", "contato", "numero", "telefone", "insta", "instagram", "loja",
           "site", "link", "direct", "dm"]
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
    # Colagem com sobra (chave colada duas vezes, texto do botão junto) acontece: aproveita só a chave.
    segredo = os.environ["YT_CLIENT_SECRET"].strip()
    achado = re.search(r"GOCSPX-[A-Za-z0-9_\-]{28}", segredo)
    if achado and achado.group(0) != segredo:
        print(f"Aviso: YT_CLIENT_SECRET tem {len(segredo)} caracteres; usando só a chave GOCSPX (35). "
              "Vale regravar o segredo só com a chave.")
        segredo = achado.group(0)
    try:
        r = http("POST", "https://oauth2.googleapis.com/token", {
            "client_id": os.environ["YT_CLIENT_ID"].strip(),
            "client_secret": segredo,
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


def videos_do_canal(token, meu_id):
    """Todos os envios do canal (inclusive agendados e privados), com snippet e status."""
    canal = get("channels", token, part="contentDetails", id=meu_id).get("items", [])
    if not canal:
        return {}
    uploads = canal[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, pagina = [], None
    for _ in range(20):
        params = dict(part="contentDetails", playlistId=uploads, maxResults=50)
        if pagina:
            params["pageToken"] = pagina
        try:
            r = get("playlistItems", token, **params)
        except ErroAPI as e:
            if e.status == 404:  # canal sem nenhum envio ainda
                return {}
            raise
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        pagina = r.get("nextPageToken")
        if not pagina:
            break
    saida = {}
    for i in range(0, len(ids), 50):
        r = get("videos", token, part="snippet,status", id=",".join(ids[i:i + 50]))
        for v in r.get("items", []):
            saida[v["id"]] = v
    return saida


def rodape_novo(desc):
    """Descrição com o rodapé que manda para o Instagram (devolve igual se já estiver certa)."""
    nova = desc.replace(RODAPE_ANTIGO, RODAPE_NOVO)
    # Sobra de rodapé antigo editado à mão: tira só a linha do WhatsApp.
    nova = re.sub(r"\n?💬 WhatsApp: link no perfil do canal", "", nova)
    return nova


class Rodada:
    def __init__(self):
        self.feitas = self.puladas = self.erros = self.ctas = self.descs = 0
        self.parar = False

    def falhou(self, e):
        self.erros += 1
        print(f"  ✗ erro: {e}")
        if e.motivo in ("quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"):
            print("Cota do dia acabou: o resto fica para amanhã.")
            self.parar = True
        elif e.status == 401:
            sys.exit(1)
        elif self.erros >= 5 and not (self.feitas or self.ctas or self.descs):
            print("Cinco erros seguidos sem nenhuma ação: parando a rodada.")
            self.parar = True


def corrigir_descricoes(token, canal, rodada):
    """Troca o rodapé antigo (WhatsApp) pelo que manda para o Instagram, vídeo por vídeo."""
    for vid, v in canal.items():
        if rodada.parar or rodada.descs >= MAX_DESC_POR_RODADA:
            break
        snip = v["snippet"]
        desc = snip.get("description", "")
        nova = rodape_novo(desc)
        if nova == desc:
            continue
        print(f"✎ descrição [{snip.get('title', vid)[:40]}] ({v.get('status', {}).get('privacyStatus', '?')}): "
              "rodapé do WhatsApp → Instagram")
        if DRY:
            rodada.descs += 1
            continue
        # videos.update troca o snippet inteiro: devolve tudo o que veio, só com a descrição nova.
        corpo = {k: snip[k] for k in ("title", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
                 if k in snip}
        corpo["description"] = nova
        try:
            http("PUT", f"{API}/videos?part=snippet", {"id": vid, "snippet": corpo}, token=token)
            rodada.descs += 1
            time.sleep(random.uniform(2, 4))
        except ErroAPI as e:
            rodada.falhou(e)


def comentar_cta(token, canal, lista, meu_id, rodada):
    """Comentário de abertura do Dr. X (manda pro Instagram) em vídeo público que ainda não tem."""
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS)
    com_comentario_nosso = {th["snippet"].get("videoId") for th, topo, _ in lista if autor_id(topo) == meu_id}
    for vid, v in sorted(canal.items(), key=lambda kv: kv[1]["snippet"].get("publishedAt", "")):
        if rodada.parar or rodada.ctas >= MAX_CTA_POR_RODADA:
            break
        if v.get("status", {}).get("privacyStatus") != "public" or vid in com_comentario_nosso:
            continue
        publicado = v["snippet"].get("publishedAt")
        if not publicado or data(publicado) < limite:
            continue
        texto = CTA_VIDEO["terceiro" if eh_terceiro(v["snippet"]) else "nosso"]
        print(f"💬 abertura [{v['snippet'].get('title', vid)[:40]}]: {texto}")
        if DRY:
            rodada.ctas += 1
            continue
        try:
            http("POST", f"{API}/commentThreads?part=snippet",
                 {"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": texto}}}}, token=token)
            rodada.ctas += 1
            time.sleep(random.uniform(4, 9))
        except ErroAPI as e:
            if e.status == 403 and e.motivo in ("commentsDisabled", "forbidden"):
                print("  (comentários fechados nesse vídeo; segue)")
                continue
            rodada.falhou(e)


def responder(token, lista, info, meu_id, rodada):
    for th, topo, respostas in lista:
        if rodada.parar:
            break
        if rodada.feitas >= MAX_POR_RODADA:
            print(f"Teto de {MAX_POR_RODADA} respostas por rodada: o resto fica para a próxima.")
            break
        if th["snippet"].get("canReply") is False:
            continue
        vid = th["snippet"].get("videoId", "")
        snip = info.get(vid, {})
        terceiro = eh_terceiro(snip)
        for c in pendentes(topo, respostas, meu_id):
            if rodada.feitas >= MAX_POR_RODADA or rodada.parar:
                break
            s = c["snippet"]
            texto = s.get("textOriginal") or s.get("textDisplay") or ""
            eh_resp = c is not topo
            cat, resposta = escrever(texto, c["id"], terceiro, eh_resp, s.get("authorDisplayName", ""))
            titulo = snip.get("title", vid)[:40]
            if not resposta:
                rodada.puladas += 1
                print(f"· pulado (spam/xingamento) [{titulo}] {texto[:80]!r}")
                continue
            print(f"→ [{titulo}] {texto[:80]!r}\n  {cat}: {resposta}")
            if DRY:
                rodada.feitas += 1
                continue
            try:
                http("POST", f"{API}/comments?part=snippet",
                     {"snippet": {"parentId": th["id"], "textOriginal": resposta}}, token=token)
                rodada.feitas += 1
                time.sleep(random.uniform(4, 9))
            except ErroAPI as e:
                rodada.falhou(e)


def main():
    conferir_regra()
    token = pegar_token()
    eu = get("channels", token, part="snippet", mine="true").get("items", [])
    if not eu:
        print("A conta autorizada não tem canal do YouTube.")
        sys.exit(1)
    meu_id, meu_nome = eu[0]["id"], eu[0]["snippet"]["title"]
    print(f"Canal: {meu_nome} ({meu_id}) · {'SIMULAÇÃO, nada é alterado' if DRY else 'respondendo'}")

    rodada = Rodada()
    canal = videos_do_canal(token, meu_id)
    print(f"{len(canal)} vídeos no canal (inclui agendados)")
    corrigir_descricoes(token, canal, rodada)

    lista = conversas(token, meu_id)
    info = {vid: v["snippet"] for vid, v in canal.items()}
    faltam = {th["snippet"].get("videoId") for th, _, _ in lista} - set(info) - {None, ""}
    if faltam:
        info.update(videos_info(token, faltam))
    print(f"{len(lista)} conversas nos últimos {DIAS} dias")

    if not rodada.parar:
        comentar_cta(token, canal, lista, meu_id, rodada)
    if not rodada.parar:
        responder(token, lista, info, meu_id, rodada)

    verbo = "simuladas" if DRY else "feitas"
    print(f"Fim ({verbo}): {rodada.descs} descrições corrigidas, {rodada.ctas} comentários de abertura, "
          f"{rodada.feitas} respostas, {rodada.puladas} puladas, {rodada.erros} erros.")
    if rodada.erros and not (rodada.feitas or rodada.ctas or rodada.descs):
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--teste":
        conferir_regra()
        print("Regra conferida: nenhum texto vende no YouTube, todos (menos hater) mandam pro Instagram.")
        for frase in sys.argv[2:]:
            for terceiro in (False, True):
                cat, r = escrever(frase, frase + str(terceiro), terceiro)
                print(f"{'terceiro' if terceiro else 'nosso   '} | {frase!r} → {cat}: {r}")
        sys.exit(0)
    main()
