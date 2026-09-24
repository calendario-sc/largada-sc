#!/usr/bin/env python3
"""Onde cada prova de Florianopolis larga e chega: o Raio-X Floripa.

O local sai de quatro pistas, nesta ordem de confianca:

  1. o campo "Largada:" da pagina da prova no corridasbr
  2. o endereco do album da Banlek (local, bairro, logradouro)
  3. as frases com "largada" ou "chegada" no regulamento e na pagina da
     ticketeira (so as provas com perfil, 2026 em diante)
  4. o proprio nome da prova ("Jurere Night Run", "Volta da Lagoa")

Cada pista vira um ou mais pontos da cidade pela tabela LOCAIS. Prova que
nao casa com nada herda o local das outras edicoes da mesma serie; o que
sobra vai para a lista "sem local identificado" do painel, para ser
apontado a mao em LOCAIS_POR_SERIE.

Uso:  python locais_floripa.py        (atualiza corridas.json)
"""

import datetime
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import UA_NAVEGADOR, sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
CIDADE = "Florianópolis"
PAUSA = 0.3

# Pontos da cidade: nome, latitude, longitude e o que os textos dizem.
LOCAIS = [
    ("Beira-Mar Norte", -27.583, -48.547,
     r"beira ?-?mar norte|beiramar norte|trapiche|sesquicentenario|koesa|beira-?mar shopping|\bagronomica\b"),
    ("Beira-Mar Continental", -27.594, -48.578,
     r"beira ?-?mar continental|\bcontinental\b|balneario\b|estreito|claudio alvim|coqueiros|abraao|bom abrigo|villa romana|jardim atlantico|capoeiras"),
    ("Centro", -27.597, -48.551,
     r"\bcentro\b|praca xv|hercilio luz|largo da alfandega|mercado publico|catedral|praca de portugal|passeio publico|trompowsk"),
    ("Morro da Cruz", -27.590, -48.535, r"morro da cruz"),
    ("Trindade / UFSC", -27.600, -48.519,
     r"\bufsc\b|trindade|carvoeira|corrego grande|udesc|itacorubi|santa monica|\bpantanal\b|serrinha"),
    ("Saco Grande / João Paulo", -27.545, -48.510,
     r"saco grande|joao paulo|monte verde|floripa shopping|cacupe"),
    ("Santo Antônio de Lisboa", -27.505, -48.522, r"santo antonio de lisboa|sambaqui|barra do sambaqui"),
    ("Jurerê Internacional", -27.437, -48.495, r"jurere|il campanario|open shopping"),
    ("Daniela", -27.445, -48.530, r"daniela"),
    ("Canasvieiras", -27.428, -48.463, r"canasvieiras|sapiens|cachoeira do bom jesus"),
    ("Ponta das Canas / Brava", -27.398, -48.428, r"ponta das canas|lagoinha|praia brava"),
    ("Ingleses", -27.435, -48.395, r"ingleses|praia dos ingleses"),
    ("Santinho / Costão", -27.455, -48.375, r"santinho|costao"),
    ("Rio Vermelho", -27.500, -48.415, r"rio vermelho|mocambique|sao joao do rio vermelho"),
    ("Barra da Lagoa / Praia Mole", -27.578, -48.428, r"barra da lagoa|praia mole|galheta"),
    ("Lagoa da Conceição", -27.605, -48.468, r"lagoa da conceicao|\blagoa\b(?! do peri)|rendeiras|canto da lagoa"),
    ("Joaquina", -27.630, -48.452, r"joaquina"),
    ("Rio Tavares", -27.645, -48.480, r"rio tavares|hiperselect"),
    ("Campeche", -27.675, -48.480, r"campeche|morro das pedras"),
    ("Aeroporto / Carianos", -27.670, -48.545, r"aeroporto|floripa airport|carianos|base aerea|ressacada"),
    ("Costeira / Saco dos Limões", -27.625, -48.530, r"costeira|saco dos limoes|jose mendes"),
    ("Ribeirão da Ilha", -27.715, -48.560, r"ribeirao da ilha|tapera|caieira|freguesia do ribeirao"),
    ("Sul da Ilha", -27.775, -48.505,
     r"pantano do sul|armacao|lagoa do peri|\bacores\b|naufragados|caldeirao|matadeiro|solidao"),
    ("Vargem Grande / Norte interior", -27.470, -48.435, r"vargem grande|vargem pequena|ratones|canto do moreira"),
]
# Prova cujo texto nao ajuda, mas cujo lugar e conhecido: pela serie. Para
# apontar a mao; a lista "sem local" do painel diz o que falta.
LOCAIS_POR_SERIE = {
}
# Prova cujo nome engana: a "Figueira Run" nao e na Figueira da Praca XV, e
# no Estreito. Chave: trecho do nome normalizado (sem acento, minusculas).
LOCAIS_PELO_NOME = [
    ("figueira run", ["Beira-Mar Continental"]),
]
# Correcao pontual, informada pelo usuario: data e trecho do nome (sem
# acento, minusculas). Vale so para aquela edicao e para os outros dias do
# mesmo evento. O quarto campo, opcional, restringe as distancias de um
# local: {"Beira-Mar Norte": ["5", "21"]} = so 5 km e 21 km largaram ali.
LOCAIS_POR_PROVA = [
    ("2026-08-29", "maratona internacional de floripa", ["Beira-Mar Norte"],
     {"Beira-Mar Norte": ["5", "21"]}),
    ("2026-09-13", "lupo sport corre", ["Beira-Mar Continental"]),
    ("2026-09-06", "vascorrida", ["Beira-Mar Continental"]),
    ("2026-08-01", "santander night run", ["Beira-Mar Continental"]),
    ("2026-07-26", "corrida verde", ["Beira-Mar Continental"]),
    ("2026-07-05", "circuito das estacoes", ["Beira-Mar Continental"]),
    ("2026-06-14", "circuito caixa de corridas", ["Beira-Mar Continental"]),
    ("2026-04-12", "circuito das estacoes", ["Beira-Mar Continental"]),
    ("2026-04-26", "circuito das estacoes", ["Beira-Mar Continental"]),
    ("2026-03-29", "live! run xp", ["Beira-Mar Continental"]),
]
# Um lugar dentro do outro: quem larga na Beira-Mar Norte esta no Centro,
# mas conta uma vez so, no ponto mais preciso.
CONTIDOS = {"Beira-Mar Norte": "Centro"}

REGISTRAR = print

LARGADA_CBR = re.compile(r"Largada:\s*\|\s*([^|]+)")
FRASE_LOCAL = re.compile(r"[^.\n]{0,120}\b(largada|chegada|concentra[cç][aã]o|arena)\b[^.\n]{0,160}", re.I)


def _baixar(url, enc="utf-8", dados=None, cab=None):
    cabs = {"User-Agent": UA_NAVEGADOR, "Accept": "*/*"}
    cabs.update(cab or {})
    req = urllib.request.Request(url, data=dados, headers=cabs)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read().decode(enc, errors="replace")


def _texto(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " | ", t)
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\s*\|\s*)+", " | ", t)


def largada_corridasbr(corrida_id):
    """O campo 'Largada:' da pagina da prova no corridasbr."""
    import fontes
    html = _baixar(f"{fontes.CBR_BASE}mostracorrida.asp?escolha={corrida_id}", "latin-1")
    achado = LARGADA_CBR.search(_texto(html))
    if not achado:
        return ""
    import html as entidades
    return entidades.unescape(achado.group(1)).strip()


BANLEK_QUERY = """query Q($nav: NavInput, $categoria: String, $cidade: String, $estado: String, $data_inicio: String, $data_final: String) {
  albuns(nav: $nav, categoria: $categoria, cidade: $cidade, estado: $estado, data_inicio: $data_inicio, data_final: $data_final) {
    items { titulo data_inicio endereco_completo { local logradouro bairro } } metadata { totalItems } } }"""


def albuns_banlek(desde="2022-01-01"):
    """Albuns de corrida da Banlek em Florianopolis, com o endereco."""
    v = {"estado": "SC", "cidade": CIDADE, "categoria": "Corrida", "data_inicio": desde,
         "data_final": "2030-12-31", "nav": {"page": 1, "itemsPerPage": 500}}
    corpo = json.dumps({"query": BANLEK_QUERY, "variables": v}).encode()
    d = json.loads(_baixar("https://graphql.banlek.com/graphql", dados=corpo,
                           cab={"Content-Type": "application/json", "Origin": "https://banlek.com"}))
    saida = []
    for i in d["data"]["albuns"]["items"]:
        e = i.get("endereco_completo") or {}
        saida.append({"nome": (i.get("titulo") or "").strip(), "data": (i.get("data_inicio") or "")[:10],
                      "texto": " ".join(x for x in (e.get("local"), e.get("bairro"), e.get("logradouro")) if x)})
    return saida


def frases_de_local(texto):
    """As frases que falam de largada ou chegada num regulamento ou pagina."""
    return " ".join(m.group(0) for m in FRASE_LOCAL.finditer(texto or ""))[:1500]


def texto_do_perfil(prova):
    """Frases de largada/chegada do regulamento e da pagina da ticketeira."""
    import perfis
    perfil = prova.get("perfil") or {}
    pedacos = []
    if perfil.get("regulamento"):
        try:
            pedacos.append(frases_de_local(perfis.texto_do_regulamento(perfil["regulamento"])))
        except Exception:
            pass
        time.sleep(PAUSA)
    if prova.get("ts_id"):
        try:
            detalhe = perfis.detalhe_ticketsports(prova["ts_id"]) or {}
            pedacos.append(frases_de_local(detalhe.get("texto") or ""))
        except Exception:
            pass
        time.sleep(PAUSA)
    return " ".join(p for p in pedacos if p)


def classificar(textos):
    """Os pontos da cidade que os textos mencionam, na ordem da tabela."""
    achados = []
    for nome, _lat, _lon, rx in LOCAIS:
        for t in textos:
            if t and re.search(rx, sem_acento(t).lower()):
                achados.append(nome)
                break
    return achados


def locais_da_prova(prova):
    """Pelas pistas guardadas na prova: largada do corridasbr, endereco da
    Banlek, frases do regulamento; o nome so quando nada mais diz."""
    nome = sem_acento(prova["nome"]).lower()
    for data, trecho, locais, *_km in LOCAIS_POR_PROVA:
        if prova["data"] == data and trecho in nome:
            return list(locais)
    for trecho, locais in LOCAIS_PELO_NOME:
        if trecho in nome:
            return list(locais)
    pistas = [prova.get("largada"), prova.get("local_banlek"), prova.get("local_texto")]
    achados = classificar(pistas)
    if not achados:
        achados = classificar([prova["nome"]])
    # Beira-Mar Norte fica no Centro: nao conta duas vezes.
    for preciso, amplo in CONTIDOS.items():
        if preciso in achados and amplo in achados:
            achados.remove(amplo)
    return achados[:2]        # largada e chegada: no maximo dois pontos


def atualizar_locais(historico, limite=None, registrar=print):
    """Busca as pistas que faltam e classifica toda prova de Florianopolis."""
    hoje = datetime.date.today().isoformat()
    floripa = [p for p in historico if p.get("cidade") == CIDADE and "Treino" not in (p.get("tags") or [])]

    # 1. corridasbr: uma vez por prova
    pendentes = [p for p in floripa if p.get("corrida_id") and not p.get("largada_em")]
    for p in pendentes[:limite] if limite else pendentes:
        try:
            p["largada"] = largada_corridasbr(p["corrida_id"])
        except Exception as erro:
            registrar(f"  largada {p['data']} {p['nome'][:40]}: FALHOU ({erro.__class__.__name__})")
            continue
        p["largada_em"] = hoje
        if not p["largada"]:
            p.pop("largada", None)
        time.sleep(PAUSA)

    # 2. Banlek: um pedido para a cidade inteira
    try:
        import fotografia
        albuns = albuns_banlek()
        por_data = {}
        for a in albuns:
            por_data.setdefault(a["data"], []).append(a)
        for p in floripa:
            if p.get("local_banlek"):
                continue
            for a in por_data.get(p["data"], []):
                if a["texto"] and fotografia.casa(p, {"data": p["data"], "cidade": CIDADE, "nome": a["nome"]}):
                    p["local_banlek"] = a["texto"][:200]
                    break
    except Exception as erro:
        registrar(f"  banlek: FALHOU ({erro.__class__.__name__}: {erro})")

    # 3. regulamento e ticketeira, so quem tem perfil e ainda nao foi lido
    for p in floripa:
        if p.get("local_texto_em") or not (p.get("perfil") or p.get("ts_id")):
            continue
        p["local_texto_em"] = hoje
        texto = texto_do_perfil(p)
        if texto:
            p["local_texto"] = texto

    # 4. classificacao, com heranca pela serie
    por_serie = {}
    for p in floripa:
        p["locais"] = locais_da_prova(p)
        p.pop("locais_km", None)
    # Correcao pontual vale para todos os dias do evento, com as distancias.
    for data, trecho, locais, *km in LOCAIS_POR_PROVA:
        dono = next((p for p in floripa if p["data"] == data and trecho in sem_acento(p["nome"]).lower()), None)
        if dono is None:
            continue
        dias = [p for p in floripa if dono.get("evento") and p.get("evento") == dono["evento"]] or [dono]
        for p in dias:
            p["locais"] = list(locais)
            if km and km[0]:
                p["locais_km"] = km[0]
    for p in floripa:
        if p["locais"] and p.get("serie"):
            por_serie.setdefault(p["serie"], []).append(tuple(p["locais"]))
    herdadas = 0
    for p in floripa:
        if p["locais"]:
            continue
        manual = LOCAIS_POR_SERIE.get(p.get("serie") or "")
        if manual:
            p["locais"] = list(manual)
            continue
        irmas = por_serie.get(p.get("serie") or "")
        if irmas:
            p["locais"] = list(max(set(irmas), key=irmas.count))
            herdadas += 1
    com = sum(1 for p in floripa if p["locais"])
    registrar(f"raio-x floripa: {len(floripa)} provas, {com} com local ({herdadas} pela serie), "
              f"{len(floripa) - com} sem local")
    return com


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    import scrape
    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))
    atualizar_locais(historico)
    historico.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    scrape.SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
