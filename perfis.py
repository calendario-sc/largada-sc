#!/usr/bin/env python3
"""Perfil de cada prova: site, perfil, ticketeira, precos e patrocinio.

Cada campo sai de uma fonte que da para citar. O que nao for encontrado fica
vazio, e a pagina escreve "nao encontrado" -- nada e deduzido.

  site / instagram   pagina do evento no roadrunners, link oficial no corridasbr
  ticketeira         link de inscricao da Ticket Sports, ou o link oficial
                     quando ele ja e de uma ticketeira
  precos             Ticket Sports, kit a kit, no lote em vigor no dia da coleta
  patrocinio         texto do regulamento, com o trecho guardado como prova

Uso:  python perfis.py [ANO ...]        (padrao: 2026 2027)
"""

import datetime
import difflib
import html as entidades
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import fontes
import pdftexto
import scrape
from comum import UA_NAVEGADOR, baixar, limpar, sem_acento

AQUI = Path(__file__).resolve().parent
PAUSA = 0.2

# Dominio -> nome da ticketeira. Um link oficial nesses dominios e o link de
# inscricao, nao o site do evento.
TICKETEIRAS = {
    "ticketsports.com.br": "Ticket Sports",
    "atletis.com.br": "Atletis",
    "movnow.com.br": "MovNow",
    "pfeventos.com.br": "PF Eventos",
    "vemcorrer.com": "Vem Correr",
    "sympla.com.br": "Sympla",
    "doity.com.br": "Doity",
    "minhasinscricoes.com.br": "Minhas Inscrições",
    "ativo.com": "Ativo.com",
    "brasilquecorre.com": "Brasil que Corre",
    "chiprun.com.br": "ChipRun",
    "supercrono.com.br": "Super Crono",
    "centraldacorrida.com.br": "Central da Corrida",
    "sprintsystem.com.br": "Sprint",
    "sprint.run": "Sprint",
    "zeroumeventos.com.br": "Zero Um",
    "e-inscricao.com": "e-Inscrição",
    "inscricoes.com.br": "Inscrições",
    "cronomax.com.br": "Chronomax",
    "runking.com.br": "RunKing",
    # Achadas nos links oficiais das provas de 2026/2027.
    "blueticket.com.br": "Blueticket",
    "evemaster.app": "Evemaster",
    "sprinta.com.br": "Sprinta",
    "sprintcrono.com.br": "Sprint Crono",
    "podiumchip.com.br": "Podium Chip",
    "korremais.com": "Korre Mais",
    "assessocor.online": "Assessocor",
    "eventooficial.com.br": "Evento Oficial",
    "rsfproeventos.com.br": "RSF Pro Eventos",
}

# Redes sociais e servicos que aparecem em qualquer pagina: nunca sao o site.
NAO_E_SITE = ("instagram.com", "facebook.com", "fb.com", "youtube.com",
              "youtu.be", "twitter.com", "x.com", "tiktok.com", "whatsapp.com",
              "wa.me", "linkedin.com", "google.", "goo.gl", "maps.app",
              "mapbox.com", "apple.com", "strava.com", "spotify.com",
              "cloudflare", "gstatic", "jsdelivr", "unpkg", "fonts.",
              "corridasbr.com.br", "roadrunners.run", "openresults.run",
              "runnerhub", "perfil.run", "focoradical.com.br",
              "circuitobrasilgigante.com.br", "wixstatic", "wix.com",
              "waze.com", "bit.ly", "linktr.ee",
              # Agendas de corrida, como o proprio corridasbr: nao sao o site da prova.
              "agendaoffroad.com.br",
              # Central de ajuda, termos, lojas de app: nunca sao o site da prova.
              "zendesk.com", "freshdesk.com", "play.google", "apps.apple",
              "politica-de-privacidade", "termos",
              # E-mail, vagas, bibliotecas e arquivos servidos por CDN.
              "outlook.live.com", "live.com", "office.com", "mailto:", "inhire.com",
              "gupy.io", "fontawesome", "datatables", "wpcc.io", "imgix.net",
              "digitaloceanspaces", "amazonaws.com", "blob.core.windows.net",
              "cloudfront.net", "jquery", "bootstrapcdn",
              "openstreetmap.org", "wa.link", "treinus.com.br")
# Endereco de arquivo (folha de estilo, script, imagem) nao e site de ninguem.
ARQUIVO = re.compile(r"\.(?:css|js|png|jpe?g|gif|svg|webp|ico|pdf|woff2?|ttf)(?:\?|$)", re.I)
CDN = re.compile(r"^(?:cdn|static|assets|img|images)[.-]|\.cdn\.", re.I)


def pode_ser_site(url):
    """O link tem cara de pagina de evento, e nao de servico ou arquivo?"""
    baixo = url.lower()
    if not baixo.startswith(("http://", "https://")):
        return False
    if any(x in baixo for x in NAO_E_SITE) or ARQUIVO.search(baixo):
        return False
    return not CDN.search(dominio(url))


RASTREIO = {"cupom", "origem", "ref", "fbclid", "gclid", "source"}


def sem_rastreio(url):
    """Tira do link o que so serve para contar de onde o clique veio."""
    partes = urllib.parse.urlparse(url)
    fica = [(k, v) for k, v in urllib.parse.parse_qsl(partes.query, keep_blank_values=True)
            if k.lower() not in RASTREIO and not k.lower().startswith("utm_")]
    return urllib.parse.urlunparse(partes._replace(query=urllib.parse.urlencode(fica)))


def dominio(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def ticketeira_de(url):
    """Nome da ticketeira, se o link for de uma."""
    host = dominio(url)
    for raiz, nome in TICKETEIRAS.items():
        if host == raiz or host.endswith("." + raiz):
            return nome
    return ""


def _post(url, dados, referer):
    corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(url, data=corpo, headers={
        "User-Agent": UA_NAVEGADOR, "Referer": referer,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _texto(html):
    return limpar(re.sub(r"<(script|style|noscript).*?</\1>", " ", html, flags=re.S | re.I))


# ---------------------------------------------------------------- corridasbr

CBR_LINK = re.compile(r"function paraonde\(\)\{\s*window\.open\('([^']+)'")


def link_corridasbr(corrida_id):
    """O botao "Mais informacoes" da pagina da prova, sem o redirecionador."""
    html = baixar(f"{fontes.CBR_BASE}mostracorrida.asp?escolha={corrida_id}")
    achado = CBR_LINK.search(html)
    if not achado:
        return ""
    url = achado.group(1)
    destino = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("c")
    return destino[0] if destino else ("" if "corridasbr" in url else url)


# --------------------------------------------------------------- roadrunners

RR_EVENTO = "https://roadrunners.run/evento/{slug}/"
LINK = re.compile(r'href="(https?://[^"#\s]+)"')


def _links(html):
    return {sem_rastreio(entidades.unescape(u)).rstrip("/?") for u in LINK.findall(html)}


def links_do_roadrunners(slugs):
    """Links externos da pagina de cada evento, sem os que toda pagina tem.

    Rodape, parceiros e canais do proprio roadrunners aparecem em todos os
    eventos. O que aparece em mais de um terco das paginas e moldura do site,
    nao informacao da prova.
    """
    paginas = {}
    for slug in slugs:
        try:
            paginas[slug] = _links(baixar(RR_EVENTO.format(slug=slug)))
        except Exception:
            continue
        time.sleep(PAUSA)
    if not paginas:
        return {}
    contagem = {}
    for links in paginas.values():
        for u in links:
            contagem[u] = contagem.get(u, 0) + 1
    limite = max(2, len(paginas) // 3)
    moldura = {u for u, n in contagem.items() if n >= limite}
    return {slug: links - moldura for slug, links in paginas.items()}


INSTAGRAM = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?(?:\?.*)?$", re.I)
INSTAGRAM_NAO = {"p", "reel", "reels", "explore", "stories", "accounts", "tv"}


# Perfis das plataformas e entidades que aparecem no rodape de muita pagina.
INSTAGRAM_ALHEIO = {"ticket.sports", "ticketsports", "atletis", "movnow", "sympla",
                    "roadrunners.run", "roadrunnersrun", "openresults", "corridasbr",
                    "fcatletismo.oficial", "cbatletismo", "blueticket", "doity",
                    "vemcorrercom", "vemcorrer", "pfeventos", "evemaster", "sprinta",
                    "korremais", "podiumchip", "sprintcrono", "desstecnologia"}
VAZIAS_PERFIL = {"corrida", "corridas", "run", "running", "race", "oficial", "evento",
                 "eventos", "esporte", "esportes", "sports", "sport", "santa", "catarina",
                 "maratona", "meia", "night", "trail", "edicao"}


def instagram_relevante(handle, nome_prova, organizadores=(), cidade=""):
    """O perfil tem a ver com a prova ou com quem a organiza?

    Rodape de ticketeira e de federacao traz o instagram delas, nao o da
    prova. O nome do perfil precisa conter uma palavra propria da prova --
    nome de cidade nao conta: "floripa" casava a Floripa Ultra Trail com o
    @restaurantelulafloripa -- ou o nome inteiro da organizadora.
    """
    h = re.sub(r"[^a-z0-9]", "", sem_acento(handle).lower())
    if h in {re.sub(r"[^a-z0-9]", "", x) for x in INSTAGRAM_ALHEIO}:
        return False
    lugar = {w for w in re.findall(r"[a-z0-9]{3,}", sem_acento(cidade))} | {
        "floripa", "florianopolis", "sc", "brasil", "catarinense"}
    for w in re.findall(r"[a-z0-9]{5,}", sem_acento(nome_prova)):
        if w not in VAZIAS_PERFIL and w not in lugar and w in h:
            return True
    for org in organizadores:
        junto = re.sub(r"[^a-z0-9]", "", sem_acento(org))
        if len(junto) >= 5 and junto in h:
            return True
        # Ou duas palavras proprias dela: "Hospital Infantil Pequeno Anjo"
        # e o @hospitalpequenoanjo.
        proprias = [w for w in re.findall(r"[a-z0-9]{4,}", sem_acento(org))
                    if w not in ORG_GENERICA]
        if sum(w in h for w in proprias) >= 2:
            return True
    return False


ORG_GENERICA = {"associacao", "instituto", "eventos", "evento", "esportes", "esportivos",
                "esportiva", "esportivo", "marketing", "prefeitura", "municipal", "municipio",
                "secretaria", "clube", "grupo", "empresa", "ltda", "oficial", "sports", "sport",
                "corrida", "corridas", "federacao", "liga", "servicos", "promocoes"}


def separar_links(links, prova, curado=False):
    """Dos links de uma pagina, o site oficial, o instagram e a ticketeira.

    curado: a pagina e so do evento (a do roadrunners, ja sem a moldura do
    site), entao o instagram dela e o do evento sem precisar provar nada.
    """
    site, instagram, ticket = "", "", ""
    nome_prova = prova["nome"]
    palavras = {w for w in re.findall(r"[a-z0-9]{4,}", sem_acento(nome_prova))}
    candidatos = []
    for u in sorted(links):
        achado = INSTAGRAM.search(u)
        if achado and achado.group(1).lower() not in INSTAGRAM_NAO:
            handle = achado.group(1)
            alheio = re.sub(r"[^a-z0-9]", "", handle.lower()) in {
                re.sub(r"[^a-z0-9]", "", x) for x in INSTAGRAM_ALHEIO}
            relevante = (curado and not alheio) or instagram_relevante(
                handle, nome_prova, prova.get("organizadores") or [], prova.get("cidade", ""))
            if not instagram and relevante:
                instagram = f"https://instagram.com/{handle}"
            continue
        if not pode_ser_site(u):
            continue
        if ticketeira_de(u):
            ticket = ticket or u
            continue
        candidatos.append(u)
    # Entre varios, fica o que tem no endereco uma palavra do nome da prova.
    candidatos.sort(key=lambda u: -sum(w in u.lower() for w in palavras))
    if candidatos:
        site = candidatos[0]
    return site, instagram, ticket


# --------------------------------------------------------------- ticketsports

TS_CATEGORIAS = "https://site.ticketsports.com.br/Inscricao/Controller/CategoriaController.ashx"
TS_PAGINA = "https://site.ticketsports.com.br/Inscricao/Categoria.aspx?__idEvento={id}&lang=pt-BR"
TS_KIT = re.compile(r'data-id="(\d+)".*?titulo-categoria-menor"\s*>\s*(.*?)\s*</span>', re.S)
TS_OPCAO = re.compile(r"title='([^']*)'")
TS_PRECO = re.compile(r"^(.*?)\s+(R\$\s*[\d.,]+|Gratuito)(?:\s*\+\s*(R\$\s*[\d.,]+)\s*taxa)?", re.I)


TS_DETALHE = ("https://www.ticketsports.com.br/api/events/detail"
              "?eventId={id}&athleteId=0&clientTypeId=1")


def detalhe_ticketsports(ts_id):
    """O que a propria pagina do evento le: textos, organizadora e regulamento."""
    d = json.loads(baixar(TS_DETALHE.format(id=ts_id), {"Accept": "application/json"}))
    secoes = [f"{c.get('title') or ''}: {_texto(c.get('description') or '')}"
              for c in (d.get("eventContents") or [])]
    return {
        "texto": " ".join(secoes),
        "regulamento": d.get("regulationDocument") or "",
        "organizador": (d.get("organizer") or "").strip(),
        "cnpj": (d.get("organizerDocumentNumber") or "").strip(),
        "pagina_propria": d.get("linkLP") or "",
        "aceitando": bool(d.get("isAcceptingRegistration")),
        "prazo": d.get("signUpDeadLine") or "",
    }


def _baixar_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA_NAVEGADOR})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(8_000_000), resp.headers.get("Content-Type", "")


def texto_do_regulamento(url):
    """Texto do regulamento, PDF ou pagina. Vazio se nao der para ler."""
    try:
        bruto, tipo = _baixar_bytes(url)
    except Exception:
        return ""
    if bruto.startswith(b"%PDF") or "pdf" in tipo.lower():
        texto = pdftexto.texto_do_pdf(bruto)
        if not pdftexto.parece_legivel(texto):
            return ""
    else:
        texto = _texto(bruto.decode("utf-8", errors="replace"))
    return " ".join(texto.split())


def links_de_regulamento(html):
    """Links que parecem ser o regulamento da prova."""
    return sorted(u for u in _links(html)
                  if "regulamento" in u.lower() or u.lower().split("?")[0].endswith(".pdf"))


# Onde o regulamento lista os valores: um trecho com varios "R$" juntos.
VALOR = re.compile(r"R\$\s*\d")


def precos_do_regulamento(texto):
    """O trecho do regulamento com a tabela de valores, como esta escrito.

    A tabela chega achatada -- colunas misturadas numa linha so --, e
    reorganizar arriscaria trocar o valor de um kit pelo de outro. Por isso
    o trecho vai inteiro, como citacao.
    """
    posicoes = [m.start() for m in VALOR.finditer(texto)]
    corrompido = lambda trecho: "�" in trecho
    for i in range(len(posicoes) - 2):
        if posicoes[i + 2] - posicoes[i] <= 300:
            ini = posicoes[i]
            # Recua ate o titulo da secao ("Valores", "Inscricoes", "Lote").
            titulo = max(texto.rfind(chave, max(0, ini - 400), ini)
                         for chave in ("Valor", "VALOR", "Lote", "LOTE", "Inscri", "INSCRI",
                                       "Investimento", "INVESTIMENTO", "Taxa", "TAXA"))
            ini = titulo if titulo >= 0 else max(0, ini - 60)
            fim = posicoes[min(len(posicoes) - 1, i + 30)]
            fim = texto.find(". ", fim)
            fim = len(texto) if fim < 0 else fim + 1
            trecho = texto[ini:min(fim, ini + 900)].strip()
            # Trecho com letra que nao se conseguiu ler nao e citacao fiel.
            return "" if corrompido(trecho) else trecho
    return ""


def precos_ticketsports(ts_id):
    """Tabela de precos do lote em vigor: kit, modalidade, valor e taxa."""
    referer = TS_PAGINA.format(id=ts_id)
    cats = json.loads(baixar(f"{TS_CATEGORIAS}?eventoId={ts_id}&tagO=&action=categoria&lang=pt-BR",
                             {"Referer": referer}))
    if cats.get("erro"):
        return []
    linhas = []
    for kit_id, kit_nome in TS_KIT.findall(cats.get("body") or ""):
        kit = limpar(kit_nome)
        try:
            corpo = json.loads(_post(TS_CATEGORIAS, {"__idMOD": kit_id, "__idEV": ts_id},
                                     referer)).get("body") or ""
        except Exception:
            continue
        for titulo in TS_OPCAO.findall(corpo):
            texto = " ".join(entidades.unescape(titulo).split())
            if texto.lower().startswith(kit.lower()):
                texto = texto[len(kit):].strip()
            achado = TS_PRECO.search(texto)
            if not achado:
                continue
            linhas.append({
                "kit": kit,
                "modalidade": achado.group(1).strip(),
                "preco": achado.group(2).replace("R$", "R$ ").replace("  ", " ").strip(),
                "taxa": (achado.group(3) or "").replace("R$", "R$ ").replace("  ", " ").strip(),
            })
        time.sleep(PAUSA)
    return linhas


TS_ID_NO_LINK = re.compile(r"(?:__idEvento=|-)(\d{4,7})(?:&|$|/)", re.I)


def id_ticketsports(url):
    """O numero do evento num link da Ticket Sports (inscricao ou pagina)."""
    if ticketeira_de(url) != "Ticket Sports":
        return None
    achado = TS_ID_NO_LINK.search(url)
    return int(achado.group(1)) if achado else None


# --------------------------------------------------------- patrocinio nos logos

# Sites de prova mostram patrocinio como logos agrupados sob um titulo
# ("Patrocinio", "Apresenta", "Apoio"). O nome vem do texto alternativo da
# imagem -- ou do nome do arquivo, quando o texto alternativo nao tem nada a
# ver com ele: na Maratona de Floripa o logo Fibra-Sports.svg esta marcado
# como "IBRA INTEL".
SECOES = [
    (re.compile(r"^(?:patroc[ií]nio(?:\s+master)?|patrocinadores?(?:\s+(?:master|oficia(?:l|is)))?|"
                r"co-?patroc[ií]nio|naming\s+rights?|apresenta(?:[çc][ãa]o)?|master|"
                r"marca\s+esportiva|t[êe]nis\s+oficial|fornecedor(?:es)?\s+oficia(?:l|is))$", re.I),
     "patrocinio"),
    (re.compile(r"^(?:apoio(?:\s+institucional)?|apoiadores?)$", re.I), "apoio"),
    (re.compile(r"^(?:realiza[çc][ãa]o|organiza[çc][ãa]o|promo[çc][ãa]o)$", re.I), "realizacao"),
]
# O texto nao pode consumir o "<" que vem depois: ele e o comeco da proxima
# tag, e a imagem logo depois de um titulo sumiria.
PECA = re.compile(r"<img\b[^>]*>|>([^<>]{1,60})(?=<)", re.I)
LOGO_VAZIO = {"logo", "logos", "imagem", "image", "img", "banner", "icone", "icon",
              "patrocinador", "patrocinadores", "apoio", "parceiro", "parceiros"}
LEI_NO_LOGO = re.compile(r"lei[\s_-]*de[\s_-]*incentivo|incentivo[\s_-]*ao[\s_-]*esporte|"
                         r"lei[\s_-]*11[\s_.-]*438", re.I)


def _palavras(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", sem_acento(s))}


def _limpar_nome_arquivo(nome):
    """"logo-m-sports-manatex.png" -> "M Sports Manatex"."""
    base = urllib.parse.unquote(nome.rsplit("/", 1)[-1])
    base = re.sub(r"\.(?:png|jpe?g|svg|webp|gif)$", "", base, flags=re.I)
    base = re.sub(r"[_-]+", " ", base)
    base = re.sub(r"^(?:logo|logotipo|marca)(?=[a-z])", "", base, flags=re.I)   # "logomombora"
    base = re.sub(r"\b(?:logo|logotipo|marca|v|h|horizontal|vertical|\d+x\d+|"
                  r"branco|preto|color(?:ido)?|png|svg|final|novo)\b", " ", base, flags=re.I)
    base = " ".join(base.split())
    # Arquivo costuma vir todo em minuscula: "columbia" -> "Columbia".
    if base and base == base.lower():
        base = " ".join(w[:1].upper() + w[1:] for w in base.split())
    return base


def nome_do_logo(tag):
    """O nome de uma marca a partir da tag <img>."""
    alt = re.search(r'alt="([^"]*)"', tag, re.I)
    src = re.search(r'(?:data-src|src)="([^"]+)"', tag, re.I)
    alt = " ".join(entidades.unescape(alt.group(1)).split()) if alt else ""
    # Texto alternativo que e nome de arquivo recebe a mesma limpeza.
    if re.search(r"\.(?:png|jpe?g|svg|webp|gif)$", alt, re.I) or re.fullmatch(r"[a-z0-9_-]+", alt):
        alt = _limpar_nome_arquivo(alt)
    arquivo = _limpar_nome_arquivo(src.group(1)) if src else ""
    alt_util = bool(alt) and sem_acento(alt).strip().lower() not in LOGO_VAZIO and len(alt) >= 2
    so = lambda s: re.sub(r"[^a-z0-9]", "", sem_acento(s).lower())
    na, nf = so(alt), so(arquivo)
    # Nome de arquivo gerado (hash, numero) nao diz nada: vale o texto.
    arquivo_util = bool(nf) and re.search(r"[a-z]{3}", nf) and not re.fullmatch(
        r"(?=.*\d)[a-z0-9]{10,}", nf) and nf not in LOGO_VAZIO
    if alt_util and arquivo_util:
        # Um contido no outro: fica o mais completo ("Villa Romana Shopping").
        if na in nf or nf in na:
            return arquivo if len(nf) > len(na) else alt
        # Parecidos, vale o texto, que costuma ter a grafia certa ("Whoosh" e
        # nao o arquivo "Woosh"). Diferentes demais, o texto esta errado.
        if difflib.SequenceMatcher(None, na, nf).ratio() >= 0.55:
            return alt
        return arquivo
    if alt_util:
        return alt
    return arquivo if arquivo_util else ""


def patrocinio_dos_logos(html):
    """Logos agrupados pelo titulo da secao em que aparecem."""
    secao, achados, leis = None, {"patrocinio": [], "apoio": [], "realizacao": []}, []
    for m in PECA.finditer(html):
        peca = m.group(0)
        if peca.lower().startswith("<img"):
            if LEI_NO_LOGO.search(peca):
                leis.append(peca)
            if secao:
                nome = nome_do_logo(peca)
                if nome and nome not in achados[secao]:
                    achados[secao].append(nome)
            continue
        texto = " ".join(entidades.unescape(m.group(1) or "").split())
        if len(re.findall(r"[A-Za-zÀ-ÿ]", texto)) < 3:
            continue
        nova = next((nome for padrao, nome in SECOES if padrao.match(texto)), None)
        # Outro titulo qualquer encerra a secao de logos.
        secao = nova
    return achados, bool(leis)


# ------------------------------------------------------ patrocinio no regulamento

# So o que o texto diz com todas as letras. Cada achado leva o trecho de
# onde saiu, para poder ser conferido.
LEIS = [
    (re.compile(r"lei\s+(?:federal\s+)?de\s+incentivo\s+ao\s+esporte|lei\s*(?:n[ºo°.]*\s*)?11\.?438",
                re.I), "Lei Federal de Incentivo ao Esporte (Lei 11.438/2006)"),
    # So por extenso: a sigla "PIE" casava com o icone ".fa-chart-pie" de
    # uma folha de estilo que vazou para o texto da pagina.
    (re.compile(r"programa\s+(?:estadual\s+)?de\s+incentivo\s+ao\s+esporte|fundesporte", re.I),
     "Programa Estadual de Incentivo ao Esporte (SC)"),
    (re.compile(r"lei\s+(?:estadual\s+)?de\s+incentivo\s+(?:ao\s+esporte\s+)?(?:de\s+)?santa\s+catarina",
                re.I), "Lei Estadual de Incentivo ao Esporte (SC)"),
    (re.compile(r"lei\s+municipal\s+de\s+incentivo", re.I), "Lei Municipal de Incentivo"),
    (re.compile(r"lei\s+rouanet|lei\s*(?:n[ºo°.]*\s*)?8\.?313", re.I),
     "Lei Rouanet (Lei 8.313/1991)"),
]

# A pergunta e "usou?", e o texto responde de tres jeitos. So o primeiro e sim.
#   usou      "projeto aprovado", "realizado com recursos da Lei..."
#   pendente  "prevista para ser viabilizada... projeto em analise",
#             "os trofeus poderao ser custeados..."
#   cita      menciona a lei sem dizer nem uma coisa nem outra
PENDENTE = re.compile(
    r"poder(?:[áa]|ão|ao)\s+ser|previst[oa]s?\s+para|em\s+an[áa]lise|aguard|condicionad|"
    r"caso\s+(?:seja|haja|o\s+projeto)|pleite|submetid|dependendo|se\s+aprovad", re.I)
USOU = re.compile(
    r"projeto\s+(?:n[ºo°.]*\s*[\d./-]+\s+)?aprovad|aprovad[oa]\s+(?:pel[ao]|n[ao])\s+(?:lei|programa|minist)|"
    r"realizad[oa]\s+com\s+(?:o\s+)?(?:recursos|apoio|incentivo)|com\s+(?:o\s+)?incentivo\s+d[ao]|"
    r"(?:por\s+meio|atrav[ée]s)\s+d[ao]\s+(?:lei|programa)|incentivad[oa]\s+pel[ao]|"
    r"patroc[ií]nio\s+incentivado|recursos\s+captados|n[ºo°.]\s*do\s+projeto|"
    r"processo\s+(?:n[ºo°.]|sei)", re.I)
# Texto que e codigo (CSS, JS) nao e regulamento.
CODIGO = re.compile(r"[{}]|:before|content\s*:|function\s*\(|var\s+\w+\s*=|px;")


def _janela(texto, ini, fim, raio=240):
    """O trecho em volta do achado, sempre contendo o proprio achado."""
    a = max(0, ini - raio)
    b = min(len(texto), fim + raio)
    return (("…" if a else "") + " ".join(texto[a:b].split()) + ("…" if b < len(texto) else ""))


def situacao_da_lei(janela):
    if PENDENTE.search(janela):
        return "pendente"
    if USOU.search(janela):
        return "usou"
    return "cita"


# O nome do proponente comeca com maiuscula e termina na pontuacao, no CNPJ
# ou no inicio de outra oracao. So a palavra-chave ignora caixa: se a regra
# toda ignorasse, "o proponente devera..." daria o nome "devera".
NOME_PROPRIO = r"([A-ZÀ-Ý][\wÀ-ÿ&.'’/ -]{3,100}?)"
# " e patrocinio da..." encerra o nome; " e Caminhada", com maiuscula, nao.
FIM_DO_NOME = r"(?=\s*(?:[,;:()]|\.\s|\.$|\s[-–]\s|\s+e\s+[a-zà-ÿ]|(?i:cnpj|inscrit|sob\s+o|com\s+sede)|$))"
PROPONENTE = re.compile(
    r"(?:(?i:proponente)(?:\s+(?i:do|deste)\s+(?i:projeto))?\s*(?:[:\-–]|(?i:é|e|será|sera|foi))\s*"
    r"|(?i:tendo\s+como|tem\s+como|teve\s+como|cujo|com)\s+(?i:proponente)\s+(?:(?i:é|e|a|o)\s+)?"
    r"|(?i:proposto|apresentado)\s+(?i:pel[ao])\s+)"
    r"(?:(?i:a|o)\s+)?" + NOME_PROPRIO + FIM_DO_NOME)
# So "Patrocinio:" com dois-pontos. Com hifen valia qualquer coisa: "brindes
# dos patrocinadores) Lote Promocional - R$..." virava o patrocinador "o comp".
PATROCINIO = re.compile(
    r"\b(?:patroc[ií]nio|patrocinadores?(?:\s+master|\s+oficia(?:l|is))?|patrocinado\s+por)\s*:\s*"
    r"([^.;\n]{3,220})", re.I)
NOME_DE_MARCA = re.compile(r"^[A-ZÀ-Ý0-9][\wÀ-ÿ&!'’.+ -]{1,50}$")


def _frase(texto, ini, fim):
    """A frase inteira em volta de um achado, para guardar como prova."""
    a = max(texto.rfind(". ", 0, ini), texto.rfind("\n", 0, ini)) + 1
    b = texto.find(". ", fim)
    b = len(texto) if b < 0 else b + 1
    return " ".join(texto[a:b].split())[:400]


def patrocinio_do_texto(texto):
    """Leis de incentivo, proponente e patrocinadores ditos no regulamento."""
    incentivo, vistas = [], {}
    for padrao, nome in LEIS:
        for achado in padrao.finditer(texto):
            janela = _janela(texto, achado.start(), achado.end())
            if CODIGO.search(janela):
                continue
            situacao = situacao_da_lei(janela)
            # Fica a mencao mais forte da mesma lei: usou > pendente > cita.
            peso = {"usou": 3, "pendente": 2, "cita": 1}[situacao]
            if nome not in vistas or peso > vistas[nome]["peso"]:
                vistas[nome] = {"lei": nome, "trecho": janela, "situacao": situacao, "peso": peso}
    for item in vistas.values():
        item.pop("peso")
        incentivo.append(item)

    proponente = ""
    achado = PROPONENTE.search(texto)
    if achado:
        proponente = " ".join(achado.group(1).split()).strip(" ,-–")

    patrocinadores, trecho_patrocinio = [], ""
    achado = PATROCINIO.search(texto)
    if achado:
        trecho_patrocinio = _frase(texto, achado.start(), achado.end())
        for nome in re.split(r"\s*(?:,|;| e |\||/)\s*", achado.group(1)):
            nome = nome.strip(" .-–")
            if (NOME_DE_MARCA.match(nome) and len(nome.split()) <= 5
                    and not re.search(r"\d{3,}|R\$", nome)):
                patrocinadores.append(nome)
        # Um nome so, sem lista, e mais provavel ser frase solta que patrocinio.
        if len(patrocinadores) < 2:
            patrocinadores, trecho_patrocinio = [], ""

    return {
        "incentivo": incentivo,
        "proponente": proponente,
        "patrocinadores": patrocinadores[:15],
        "trecho_patrocinio": trecho_patrocinio,
    }


# --------------------------------------------------------------------- perfil

def ligar_enderecos(historico, anos):
    """Poe em cada prova o endereco dela nas fontes de calendario.

    A coleta diaria passa a fazer isso sozinha; aqui e a carga inicial, e
    serve tambem para provas que entraram antes de os enderecos existirem.
    """
    por_data = {}
    for p in historico:
        if p["ano"] in anos:
            por_data.setdefault(p["data"], []).append(p)
    ligadas = 0
    for nome, funcao in (("corridasbr", fontes.corridasbr),
                         ("roadrunners", fontes.roadrunners),
                         ("ticketsports", fontes.ticketsports)):
        try:
            registros = funcao()
        except Exception as erro:
            print(f"  {nome}: FALHOU ({erro.__class__.__name__}: {erro})")
            continue
        for r in registros:
            alvo = scrape.casar_no_historico(r, por_data)
            if not alvo:
                continue
            for campo in ("corrida_id", "ts_id", "ts_url", "rr_slug"):
                if r.get(campo) and not alvo.get(campo):
                    alvo[campo] = r[campo]
                    ligadas += 1
    return ligadas


def _novo_perfil():
    return {"site": "", "instagram": "", "ticketeira": "", "inscricao": "",
            "precos": [], "precos_em": "", "precos_regulamento": "",
            "regulamento": "", "incentivo": [], "proponente": "",
            "patrocinadores": [], "apoio": [], "trecho_patrocinio": "",
            "organizador_cnpj": "", "fontes": []}


def _ler(url):
    try:
        return baixar(url)
    except Exception:
        return ""


def montar_perfil(p, rr_links, hoje):
    """Junta, fonte por fonte, o que se sabe de uma prova."""
    perfil = _novo_perfil()
    refs = [p["nome"], *(p.get("organizadores") or [])]
    textos, paginas, regulamentos = [], [], []

    def anota_links(links, fonte, curado=False):
        site, insta, ticket = separar_links(links, p, curado)
        achou = False
        # Site oficial so da pagina curada do evento. Numa pagina de
        # ticketeira ou de organizadora, "um link externo qualquer" e rodape:
        # parceiro, mapa, investidor -- o febacapital.com aparecia em 17 provas.
        if curado and site and not perfil["site"]:
            perfil["site"], achou = site, True
        if insta and not perfil["instagram"]:
            perfil["instagram"], achou = insta, True
        if ticket and not perfil["inscricao"]:
            perfil["inscricao"], perfil["ticketeira"], achou = ticket, ticketeira_de(ticket), True
        if achou and fonte not in perfil["fontes"]:
            perfil["fontes"].append(fonte)

    # 1. roadrunners: a pagina do evento lista site, instagram e inscricao.
    if p.get("rr_slug") in rr_links:
        anota_links(rr_links[p["rr_slug"]], "roadrunners", curado=True)

    # 2. corridasbr: o botao "Mais informacoes".
    if p.get("corrida_id"):
        try:
            link = link_corridasbr(p["corrida_id"])
        except Exception:
            link = ""
        time.sleep(PAUSA)
        if link:
            perfil["fontes"].append("corridasbr")
            insta = INSTAGRAM.search(link)
            if insta and insta.group(1).lower() not in INSTAGRAM_NAO:
                # O corridasbr aponta direto para ele: e o canal que a prova divulga.
                perfil["instagram"] = perfil["instagram"] or f"https://instagram.com/{insta.group(1)}"
            elif ticketeira_de(link):
                if not perfil["inscricao"]:
                    perfil["inscricao"], perfil["ticketeira"] = link, ticketeira_de(link)
                pagina = _ler(link)
                if pagina:
                    paginas.append(pagina)
                    textos.append(_texto(pagina))
                    regulamentos += links_de_regulamento(pagina)
                    anota_links(_links(pagina), "corridasbr")
            elif not perfil["site"] and pode_ser_site(link):
                perfil["site"] = link

    # 3. site oficial: logos de patrocinio, instagram e link do regulamento.
    if perfil["site"]:
        pagina = _ler(perfil["site"])
        time.sleep(PAUSA)
        if pagina:
            paginas.append(pagina)
            textos.append(_texto(pagina))
            regulamentos += links_de_regulamento(pagina)
            anota_links(_links(pagina), "site oficial")

    # 4. Ticket Sports: o id vem da lista dela ou de um link de inscricao.
    ts_id = p.get("ts_id") or id_ticketsports(perfil["inscricao"] or "")
    if ts_id:
        p["ts_id"] = ts_id
        perfil["ticketeira"] = "Ticket Sports"
        perfil["inscricao"] = p.get("ts_url") or perfil["inscricao"] or TS_PAGINA.format(id=ts_id)
        if "ticketsports" not in perfil["fontes"]:
            perfil["fontes"].append("ticketsports")
        try:
            det = detalhe_ticketsports(ts_id)
            textos.append(det["texto"])
            if det["regulamento"]:
                regulamentos.insert(0, det["regulamento"])
            perfil["organizador_cnpj"] = det["cnpj"]
            if det["pagina_propria"]:
                pagina = _ler(det["pagina_propria"])
                if pagina:
                    paginas.append(pagina)
                    textos.append(_texto(pagina))
        except Exception:
            pass
        # Preco so existe enquanto a inscricao esta aberta.
        if p["data"] >= hoje:
            try:
                perfil["precos"] = precos_ticketsports(ts_id)
                if perfil["precos"]:
                    perfil["precos_em"] = hoje
            except Exception:
                pass
        time.sleep(PAUSA)

    # 5. regulamento: o primeiro que der para ler.
    for url in dict.fromkeys(regulamentos):
        texto = texto_do_regulamento(url)
        time.sleep(PAUSA)
        if texto:
            perfil["regulamento"] = url
            textos.insert(0, texto)
            perfil["precos_regulamento"] = precos_do_regulamento(texto)
            break

    # 6. patrocinio: logos com titulo de secao, depois o texto dito.
    for pagina in paginas:
        logos, lei_no_logo = patrocinio_dos_logos(pagina)
        if logos["patrocinio"] and not perfil["patrocinadores"]:
            perfil["patrocinadores"] = logos["patrocinio"][:20]
            perfil["trecho_patrocinio"] = "logos da seção de patrocínio do site oficial"
        if logos["apoio"] and not perfil["apoio"]:
            perfil["apoio"] = logos["apoio"][:20]
        if lei_no_logo and not perfil["incentivo"]:
            perfil["incentivo"] = [{"lei": "Lei Federal de Incentivo ao Esporte (Lei 11.438/2006)",
                                    "trecho": "logo da Lei de Incentivo ao Esporte no site oficial"}]
    for texto in textos:
        achado = patrocinio_do_texto(" ".join(texto.split()))
        perfil["incentivo"] = perfil["incentivo"] or achado["incentivo"]
        perfil["proponente"] = perfil["proponente"] or achado["proponente"]
        if not perfil["patrocinadores"] and achado["patrocinadores"]:
            perfil["patrocinadores"] = achado["patrocinadores"]
            perfil["trecho_patrocinio"] = achado["trecho_patrocinio"]

    antigo = p.get("perfil") or {}
    # Tabela ja coletada de um lote antigo nao se perde quando a inscricao fecha.
    if not perfil["precos"] and antigo.get("precos"):
        perfil["precos"], perfil["precos_em"] = antigo["precos"], antigo.get("precos_em", "")
    # O resto so e herdado quando nenhuma fonte respondeu desta vez -- a prova
    # saiu do ar. Se alguma respondeu, vale o que se leu agora: herdar campo
    # vazio faria um achado errado de uma versao antiga das regras nunca sair.
    if not perfil["fontes"] and antigo.get("fontes"):
        for campo in ("regulamento", "precos_regulamento", "site", "instagram", "inscricao",
                      "ticketeira", "patrocinadores", "apoio", "trecho_patrocinio",
                      "incentivo", "proponente", "organizador_cnpj", "fontes"):
            if not perfil[campo] and antigo.get(campo):
                perfil[campo] = antigo[campo]
    return perfil


def montar_perfis(historico, anos, rr_links):
    hoje = datetime.date.today().isoformat()
    alvo = [p for p in historico
            if p["ano"] in anos and "Treino" not in (p.get("tags") or [])]
    for n, p in enumerate(alvo, 1):
        p["perfil"] = montar_perfil(p, rr_links, hoje)
        p["perfil_em"] = hoje
        if n % 25 == 0:
            print(f"  {n}/{len(alvo)} perfis", flush=True)
    return len(alvo)


# Anos com perfil. A carga comecou por 2026 e 2027; para estender, basta
# acrescentar o ano aqui e rodar "python perfis.py <ano>" uma vez.
ANOS_PERFIL = (2026, 2027)
# Preco muda a cada lote: prova futura e revista a cada poucos dias.
REVER_A_CADA_DIAS = 3
LIMITE_DIARIO = 150


def atualizar_perfis(historico):
    """Rodada diaria: perfis novos e provas futuras com perfil envelhecido.

    Prova que ja aconteceu nao e revista -- as fontes a tiram do ar, e o que
    foi coletado enquanto ela estava anunciada e o que fica.
    """
    hoje = datetime.date.today()
    limite = (hoje - datetime.timedelta(days=REVER_A_CADA_DIAS)).isoformat()
    candidatas = [p for p in historico
                  if p["ano"] in ANOS_PERFIL and "Treino" not in (p.get("tags") or [])
                  and (not p.get("perfil")
                       or (p["data"] >= hoje.isoformat() and (p.get("perfil_em") or "") <= limite))]
    # As mais proximas primeiro: e nelas que o preco e a inscricao importam.
    candidatas.sort(key=lambda p: (bool(p.get("perfil")), p["data"]))
    candidatas = candidatas[:LIMITE_DIARIO]
    if not candidatas:
        return 0
    ligar_enderecos(historico, list(ANOS_PERFIL))
    slugs = sorted({p["rr_slug"] for p in candidatas if p.get("rr_slug")})
    rr_links = links_do_roadrunners(slugs)
    for p in candidatas:
        p["perfil"] = montar_perfil(p, rr_links, hoje.isoformat())
        p["perfil_em"] = hoje.isoformat()
    return len(candidatas)


def reler_regulamentos(historico, anos):
    """Reaplica a leitura de patrocinio e precos aos regulamentos ja achados.

    Serve quando a regra de extracao muda: nao precisa refazer o perfil
    inteiro, so ler de novo o documento que ele ja aponta.
    """
    feitos = 0
    for p in historico:
        perfil = p.get("perfil") or {}
        if p["ano"] not in anos or not perfil.get("regulamento"):
            continue
        texto = texto_do_regulamento(perfil["regulamento"])
        time.sleep(PAUSA)
        if not texto:
            continue
        achado = patrocinio_do_texto(texto)
        if achado["incentivo"]:
            perfil["incentivo"] = achado["incentivo"]
        if achado["proponente"]:
            perfil["proponente"] = achado["proponente"]
        # Logo com titulo de secao vale mais que lista solta no texto.
        if achado["patrocinadores"] and not str(perfil.get("trecho_patrocinio", "")).startswith("logos"):
            perfil["patrocinadores"] = achado["patrocinadores"]
            perfil["trecho_patrocinio"] = achado["trecho_patrocinio"]
        perfil["precos_regulamento"] = precos_do_regulamento(texto) or perfil.get("precos_regulamento", "")
        feitos += 1
    return feitos


def resumo(historico, anos):
    alvo = [p for p in historico if p["ano"] in anos and p.get("perfil")]
    conta = lambda f: sum(1 for p in alvo if f(p["perfil"]))
    print(f"\n{len(alvo)} perfis montados ({', '.join(map(str, anos))})")
    print(f"  site oficial:        {conta(lambda x: x['site'])}")
    print(f"  instagram:           {conta(lambda x: x['instagram'])}")
    print(f"  link de inscricao:   {conta(lambda x: x['inscricao'])}")
    print(f"  tabela de precos:    {conta(lambda x: x['precos'])}")
    print(f"  regulamento lido:    {conta(lambda x: x.get('regulamento'))}")
    print(f"  precos no regulam.:  {conta(lambda x: x.get('precos_regulamento'))}")
    print(f"  lei de incentivo:    {conta(lambda x: x['incentivo'])}")
    print(f"  proponente:          {conta(lambda x: x['proponente'])}")
    print(f"  patrocinadores:      {conta(lambda x: x['patrocinadores'])}")


def main(anos):
    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))
    print("enderecos nas fontes:", ligar_enderecos(historico, anos))

    slugs = sorted({p["rr_slug"] for p in historico
                    if p["ano"] in anos and p.get("rr_slug")})
    print(f"roadrunners: {len(slugs)} paginas de evento")
    rr_links = links_do_roadrunners(slugs)

    montar_perfis(historico, anos, rr_links)
    scrape.SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
    resumo(historico, anos)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    anos = [int(a) for a in sys.argv[1:]] or [2026, 2027]
    main(anos)
