"""Provas das organizadoras parceiras (portal do parceiro).

As organizadoras aprovadas cadastram o proprio calendario em
www.cuponsdecorrida.com.br/parceiros.html (uma a uma ou pela planilha
modelo) e a API publica a lista em /provas-parceiros. Aqui ela entra:

  - como mais uma fonte do calendario (fontes.TODAS): a prova nova aparece,
    e a que ja existe e casada pelas regras de sempre (mesma_prova);
  - depois dos perfis (atualizar.py), o link de inscricao e o nome da
    organizadora informados por ela passam a valer no cartao: a palavra da
    propria organizadora vale mais que a de terceiros.
"""

import json

from comum import UFS, baixar, canonizar_cidade, classificar

API = "https://api.cuponsdecorrida.com.br/provas-parceiros"
# Tipo informado pela organizadora que vira etiqueta do calendario.
TIPOS_ETIQUETA = {"Trail", "Ultra", "Noturna", "Revezamento", "Kids", "Caminhada"}
_cache = None


def _baixar():
    global _cache
    if _cache is None:
        _cache = json.loads(baixar(API, headers={"Accept": "application/json"})).get("provas") or []
    return _cache


def fonte():
    """As provas no formato das outras fontes (fonte "parceiro")."""
    provas = []
    for p in _baixar():
        cidade, regiao, uf = canonizar_cidade(p["cidade"], p["uf"])
        if uf not in UFS:
            continue
        a, m, d = (int(x) for x in p["data"].split("-"))
        km = [float(x) for x in p.get("distancias") or []]
        extras = [p["tipo"]] if p.get("tipo") in TIPOS_ETIQUETA else []
        provas.append({
            "fonte": "parceiro",
            "data": p["data"], "dia": d, "mes": m, "ano": a,
            "cidade": cidade, "regiao": regiao, "uf": uf,
            "nome": p["nome"],
            "pills": [f"{v:g}km" for v in km], "km": km,
            "tags": classificar(p["nome"], km, extras),
            "organizadores": [p["organizadora"]],
            "_link": p.get("link") or "",
        })
    return provas


def aplicar(historico, registrar=print):
    """Link de inscricao e organizadora da parceira nas provas do historico."""
    from perfis import ticketeira_de
    from scrape import casar_no_historico

    por_data = {}
    for p in historico:
        por_data.setdefault(p["data"], []).append(p)
    feitos = 0
    for r in fonte():
        alvo = casar_no_historico(r, por_data)
        if not alvo:
            continue
        organizadora = r["organizadores"][0]
        if organizadora not in (alvo.get("organizadores") or []):
            alvo["organizadores"] = sorted(set(alvo.get("organizadores") or []) | {organizadora})
        if r["_link"]:
            perfil = alvo.get("perfil") or {}
            if perfil.get("inscricao") != r["_link"]:
                perfil["inscricao"] = r["_link"]
                perfil["ticketeira"] = ticketeira_de(r["_link"]) or perfil.get("ticketeira", "")
                alvo["perfil"] = perfil
        alvo["parceira"] = organizadora
        feitos += 1
    registrar(f"parceiros: {feitos} provas das organizadoras parceiras no calendario")
    return feitos
