#!/usr/bin/env python3
"""Fotografia oficial de cada prova: quem cobriu, pelas plataformas de fotos.

Cada plataforma lista os eventos que fotografou, com data e cidade:

  Foco Radical  API do site, por estado (next-api/home/competitions)
  Banlek        GraphQL (graphql.banlek.com), por estado e categoria
  Fotop         busca por nome (webservices/eventos/nome-eventos)

A prova casa com o evento da plataforma pela data, pela cidade e pelo nome.
Uma prova pode ter mais de uma plataforma: fica a lista. O campo vai em
"fotografia"; "fotografia_em" diz quando se procurou.

Uso:  python fotografia.py            (provas realizadas ainda sem busca)
"""

import datetime
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import UA_NAVEGADOR, mesmo_evento_renomeado, parecidos, sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
PAUSA = 0.4
FOCO_ESTADO_SC = 24
FOCO_URL = ("https://www.focoradical.com.br/next-api/home/competitions"
            "?CompetitionSearch%5Bstate%5D={estado}&page={pagina}")
BANLEK_URL = "https://graphql.banlek.com/graphql"
FOTOP_URL = "https://fotop.com.br/fotos/webservices/eventos/nome-eventos?h=1&n={nome}"
# O que na Foco Radical e corrida (treino e outros esportes ficam de fora).
FOCO_CORRIDA = re.compile(r"corrida|trail|maratona|atletismo|r[uú]stica|montanha|cross|ultra", re.I)
FOCO_NAO = re.compile(r"treino|esteira|orienta", re.I)
REVER_DIAS = 7          # prova recente sem foto: procura de novo daqui a tantos dias
JANELA_RECENTE = 90     # ate quando vale a pena procurar de novo

BANLEK_QUERY = """query Q($nav: NavInput, $categoria: String, $estado: String, $data_inicio: String, $data_final: String, $pais: String) {
  albuns(nav: $nav, categoria: $categoria, estado: $estado, data_inicio: $data_inicio, data_final: $data_final, pais: $pais) {
    items { id titulo data_inicio endereco_completo { cidade } usuario { nome_exibicao } }
    metadata { hasMorePages } } }"""


def _baixar(url, dados=None):
    cab = {"User-Agent": UA_NAVEGADOR, "Accept": "application/json,*/*", "Accept-Language": "pt-BR",
           "Origin": "https://banlek.com", "Referer": "https://banlek.com/"}
    if dados is not None:
        cab["Content-Type"] = "application/json"
        dados = json.dumps(dados).encode()
    req = urllib.request.Request(url, data=dados, headers=cab)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _chave_cidade(nome):
    return re.sub(r"[^a-z]", "", sem_acento(nome or "").lower())


# ------------------------------------------------------------------ fontes

def foco_eventos(desde, estado=FOCO_ESTADO_SC, registrar=print):
    """Corridas da Foco Radical no estado, da mais recente ate a data pedida.

    A lista vem por data decrescente, 80 por pagina: para em quando a
    pagina inteira ja e anterior a `desde`.
    """
    saida, pagina, total = [], 1, 1
    while pagina <= total:
        try:
            d = json.loads(_baixar(FOCO_URL.format(estado=estado, pagina=pagina)))
        except Exception as erro:
            registrar(f"  foco radical pagina {pagina}: FALHOU ({erro.__class__.__name__})")
            break
        total = d.get("_meta", {}).get("pageCount", pagina)
        itens = d.get("items") or []
        for i in itens:
            esporte = (i.get("sport") or {}).get("name") or ""
            if FOCO_CORRIDA.search(esporte) and not FOCO_NAO.search(esporte):
                saida.append({"nome": (i.get("name") or "").strip(), "data": i.get("date") or "",
                              "cidade": (i.get("place") or "").strip(), "fonte": "Foco Radical"})
        if not itens or min(i.get("date") or "9999" for i in itens) < desde:
            break
        pagina += 1
        time.sleep(PAUSA)
    return saida


def banlek_albuns(desde, ate, registrar=print):
    """Albuns de corrida da Banlek em SC entre as datas (aaaa-mm-dd)."""
    saida, pagina = [], 1
    while True:
        v = {"estado": "SC", "categoria": "Corrida", "pais": "BR", "data_inicio": desde, "data_final": ate,
             "nav": {"page": pagina, "itemsPerPage": 500}}
        try:
            d = json.loads(_baixar(BANLEK_URL, {"query": BANLEK_QUERY, "variables": v}))
            bloco = d["data"]["albuns"]
        except Exception as erro:
            registrar(f"  banlek pagina {pagina}: FALHOU ({erro.__class__.__name__})")
            break
        for i in bloco.get("items") or []:
            saida.append({"nome": (i.get("titulo") or "").strip(), "data": (i.get("data_inicio") or "")[:10],
                          "cidade": ((i.get("endereco_completo") or {}).get("cidade") or "").strip(),
                          "fotografo": ((i.get("usuario") or {}).get("nome_exibicao") or "").strip(),
                          "fonte": "Banlek"})
        if not bloco.get("metadata", {}).get("hasMorePages"):
            break
        pagina += 1
        time.sleep(PAUSA)
    return saida


ANO_OU_ORDINAL = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{1,3}\s*[ªº°]|^\s*[IVXLivxl]{1,6}\s+")


def fotop_eventos(prova):
    """Eventos da Fotop com o nome parecido com o da prova (busca do site)."""
    termo = ANO_OU_ORDINAL.sub(" ", prova["nome"])
    termo = re.sub(r"[-–|:]", " ", termo)
    termo = " ".join(termo.split())[:40]
    if len(termo) < 4:
        return []
    d = json.loads(_baixar(FOTOP_URL.format(nome=urllib.parse.quote(termo))))
    saida = []
    for i in d or []:
        data = i.get("data") or ""
        if re.match(r"\d{2}/\d{2}/\d{4}$", data):
            data = f"{data[6:]}-{data[3:5]}-{data[:2]}"
        local = (i.get("local") or "")
        saida.append({"nome": (i.get("nome") or "").strip(), "data": data,
                      "cidade": local.split(" - ")[0].strip(), "uf": local[-2:], "fonte": "Fotop"})
    return saida


# ---------------------------------------------------------------- casamento

def _datas_da_prova(prova):
    """A data da prova e, num evento de mais de um dia, a vespera e o dia
    seguinte tambem: a plataforma marca um dia so."""
    d = datetime.date.fromisoformat(prova["data"])
    if prova.get("evento_dias", 1) > 1:
        return {(d + datetime.timedelta(days=k)).isoformat() for k in (-1, 0, 1)}
    return {prova["data"]}


def casa(prova, evento):
    """A prova e o evento da plataforma sao a mesma coisa?"""
    if evento["data"] not in _datas_da_prova(prova):
        return False
    cidade_ev = _chave_cidade(evento.get("cidade"))
    cidade = _chave_cidade(prova.get("cidade"))
    if cidade_ev and cidade and cidade_ev != cidade and cidade not in cidade_ev and cidade_ev not in cidade:
        return False
    return (mesmo_evento_renomeado(prova["nome"], evento["nome"], prova.get("cidade", ""))
            or parecidos(prova["nome"], evento["nome"]))


def _indexar(eventos):
    por_data = {}
    for e in eventos:
        por_data.setdefault(e["data"], []).append(e)
    return por_data


def plataformas_da_prova(prova, indice, com_fotop=True):
    """Plataformas que fotografaram a prova, e o fotografo da Banlek."""
    achadas, detalhes = [], {}
    candidatos = [e for d in _datas_da_prova(prova) for e in indice.get(d, [])]
    if com_fotop:
        try:
            candidatos += fotop_eventos(prova)
        except Exception:
            pass
        time.sleep(PAUSA)
    for e in candidatos:
        if e["fonte"] in achadas or not casa(prova, e):
            continue
        achadas.append(e["fonte"])
        if e.get("fotografo"):
            detalhes[e["fonte"]] = e["fotografo"]
    return achadas, detalhes


def provas_alvo(historico, hoje):
    """Provas realizadas ainda nao procuradas, ou recentes e sem foto (a
    plataforma publica dias depois da prova)."""
    limite_rever = (hoje - datetime.timedelta(days=REVER_DIAS)).isoformat()
    recente = (hoje - datetime.timedelta(days=JANELA_RECENTE)).isoformat()
    saida = []
    for p in historico:
        if p["data"] > hoje.isoformat() or "Treino" in (p.get("tags") or []):
            continue
        em = p.get("fotografia_em") or ""
        if not em or (not p.get("fotografia") and p["data"] >= recente and em <= limite_rever):
            saida.append(p)
    return saida


def completar_fotografia(historico, limite=None, registrar=print, foco=None, banlek=None):
    """Preenche "fotografia" nas provas realizadas. foco/banlek: listas ja
    baixadas (a carga inicial); sem elas, baixa o periodo das provas alvo."""
    hoje = datetime.date.today()
    alvo = provas_alvo(historico, hoje)
    alvo.sort(key=lambda p: p["data"], reverse=True)
    alvo = alvo[:limite] if limite else alvo
    if not alvo:
        return 0, 0
    desde = min(p["data"] for p in alvo)
    if foco is None:
        foco = foco_eventos(desde, registrar=registrar)
    if banlek is None:
        banlek = banlek_albuns(desde, hoje.isoformat(), registrar=registrar)
    registrar(f"  fotografia: {len(foco)} corridas na Foco Radical, {len(banlek)} álbuns na Banlek desde {desde}")
    indice = _indexar(foco + banlek)
    achadas = 0
    for p in alvo:
        plataformas, detalhes = plataformas_da_prova(p, indice)
        p["fotografia_em"] = hoje.isoformat()
        if plataformas:
            p["fotografia"] = plataformas
            if detalhes:
                p["fotografia_detalhe"] = detalhes
            achadas += 1
        else:
            p.pop("fotografia", None)
            p.pop("fotografia_detalhe", None)
    return len(alvo), achadas


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    import scrape
    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))
    n, ok = completar_fotografia(historico)
    historico.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    scrape.SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"fotografia: {n} provas procuradas, {ok} com plataforma")
