#!/usr/bin/env python3
"""Monta as paginas a partir de template.html + corridas.json.

Gera dois arquivos com o mesmo conteudo:
  artifact.html - fragmento para publicar como Artifact (sem <html>/<head>/<body>)
  index.html    - pagina completa, abre direto no navegador

Uso:  python build.py
"""

import datetime
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

CABECALHO = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Calendario de corridas de rua e trail em Santa Catarina.">
"""


def data_coleta():
    marca = AQUI / "coletado_em.txt"
    iso = marca.read_text(encoding="utf-8").strip() if marca.exists() \
        else datetime.date.today().isoformat()
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


# O que nao conta para o "a partir de": o kit kids da NJR Run custa R$ 79 e o
# adulto R$ 139,90 -- o preco de entrada de um adulto e o que interessa.
NAO_E_ENTRADA = re.compile(r"kid|infantil|crian|pcd|idos|60\s*\+|cortesia|gratuit|elite|"
                           r"cadeirant|\bcad\b|\bdv\b|\bdi\b|isen", re.I)


def _valor(texto):
    achado = re.search(r"R\$\s*([\d.]+,\d{2}|[\d.]+)", texto or "")
    if not achado:
        return 0.0
    return float(achado.group(1).replace(".", "").replace(",", "."))


def _para_o_cartao(perfil):
    """Do perfil coletado, so o que vai no cartao de uma prova futura."""
    cartao = {}
    if perfil.get("inscricao"):
        cartao["inscricao"] = perfil["inscricao"]
        cartao["ticketeira"] = perfil.get("ticketeira", "")
    entrada = [x for x in perfil.get("precos") or []
               if _valor(x.get("preco")) > 0 and not NAO_E_ENTRADA.search(
                   f"{x.get('kit', '')} {x.get('modalidade', '')}")]
    if entrada:
        mais_barato = min(entrada, key=lambda x: _valor(x["preco"]))
        cartao["preco"] = mais_barato["preco"]
        if _valor(mais_barato.get("taxa")) > 0:
            cartao["taxa"] = True
    if perfil.get("regulamento"):
        cartao["regulamento"] = perfil["regulamento"]
    return cartao


# A area de BI (bi.cuponsdecorrida.com.br) e um repositorio privado ao lado
# deste, publicado pelo Cloudflare Pages atras de login. Quando a pasta
# existe, o build escreve la a pagina completa.
BI_DIR = AQUI.parent / "cupons-bi"
# O que so a pagina de BI leva: quem vende a inscricao, quem cronometra e
# quem fotografa cada prova.
CAMPOS_BI = ("ticketeira", "cronometragem", "fotografia", "locais", "locais_km", "largada", "local_banlek")


def dados_floripa():
    """O mapa do Raio-X Floripa: contorno projetado e os pontos da cidade."""
    import math
    import locais_floripa
    contorno = json.loads((AQUI / "floripa_contorno.json").read_text(encoding="utf-8"))
    escala = contorno["w"] / ((contorno["lon1"] - contorno["lon0"]) * math.cos(math.radians(contorno["lat_ref"])))
    pontos = []
    for nome, lat, lon, _rx in locais_floripa.LOCAIS:
        x = (lon - contorno["lon0"]) * math.cos(math.radians(contorno["lat_ref"])) * escala
        y = (contorno["lat1"] - lat) * escala
        pontos.append({"nome": nome, "x": round(x, 1), "y": round(y, 1)})
    return json.dumps({"w": contorno["w"], "h": contorno["h"], "aneis": contorno["aneis"], "pontos": pontos},
                      ensure_ascii=False, separators=(",", ":"))


def dados_da_pagina(historico, bi=True):
    """O historico guarda o perfil inteiro; a pagina leva so o que mostra.

    O perfil completo acrescentava ~430 KB, quase tudo campo vazio ou de
    prova ja realizada -- peso a toa no celular. Sem bi, saem tambem os
    campos que so os paineis restritos usam.
    """
    hoje = datetime.date.today().isoformat()
    for p in historico:
        perfil = p.pop("perfil", None)
        for campo in ("perfil_em", "ts_id", "ts_url", "rr_slug", "cronometragem_url", "cronometragem_em",
                      "fotografia_em", "fotografia_detalhe", "maissport_tentado",
                      "largada_em", "local_texto", "local_texto_em", "permit_status", "organizador_fca"):
            p.pop(campo, None)
        # Resultado lido direto na cronometradora: ela e a cronometragem.
        if not p.get("cronometragem") and p.get("fonte_resultado") in ("supercrono", "chiprun"):
            p["cronometragem"] = {"supercrono": "Super Crono", "chiprun": "ChipRun"}[p["fonte_resultado"]]
        # Ticketeira de toda prova que tem uma: e o que alimenta o grafico de
        # participacao. Prova listada pelo Ticket Sports vende por ele mesmo
        # quando o perfil nao achou o link.
        fontes = p.get("fontes") or []
        ticketeira = (perfil or {}).get("ticketeira") or (
            "Ticket Sports" if "ticketsports" in fontes else "MovNow" if "movnow" in fontes else "")
        if ticketeira:
            p["ticketeira"] = ticketeira
        if perfil and p["data"] >= hoje:
            cartao = _para_o_cartao(perfil)
            if cartao:
                p["cartao"] = cartao
        if not bi:
            for campo in CAMPOS_BI:
                p.pop(campo, None)
    return json.dumps(historico, ensure_ascii=False, separators=(",", ":"))


# Pedacos do template que so existem na pagina de BI. O JS tolera a falta
# deles (ver `ao` e `BI` no template).
SO_BI = [
    r'[ \t]*<button class="chip" id="btn-comparativo"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-ticketeiras"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-crono"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-foto"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-raiox"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-assessorias"[^\n]*\n',
    r'<dialog class="orgs as" id="assess".*?</dialog>\n\n',
    r'<section class="rel" id="rel-assess"[^\n]*\n',
    r'<dialog class="orgs rx" id="raiox".*?</dialog>\n\n',
    r'<section class="rel" id="rel-raiox"[^\n]*\n',
    r'  <section class="comparativo" id="comparativo".*?\n  </section>\n',
    r'<dialog class="orgs tk" id="tk".*?</dialog>\n\n',
    r'<dialog class="orgs tk" id="crono".*?</dialog>\n\n',
    r'<dialog class="orgs tk" id="foto".*?</dialog>\n\n',
    r'<dialog class="orgs" id="orgs".*?</dialog>\n',
    r'<section class="rel" id="rel-orgs"[^\n]*\n',
]
STAT_ORGS = re.compile(r'<button class="stat stat--btn" id="stat-orgs".*?</button>', re.S)


def so_publico(pagina):
    """A pagina publica: sem os paineis de BI e sem o clique nas organizadoras."""
    for padrao in SO_BI:
        pagina, n = re.subn(padrao, "", pagina, count=1, flags=re.S)
        if n != 1:
            raise SystemExit(f"template.html: nao achei o trecho de BI {padrao[:40]!r}")
    pagina, n = STAT_ORGS.subn('<div class="stat"><b id="s-orgs">0</b><span>organizadoras</span></div>', pagina, count=1)
    if n != 1:
        raise SystemExit("template.html: nao achei a caixa das organizadoras")
    return pagina


def completa(pagina):
    """A pagina standalone precisa do <head>: o <style> sobe para dentro dele."""
    estilo, corpo = pagina.split("</style>", 1)
    return CABECALHO + estilo + "</style>\n</head>\n<body>\n" + corpo + "\n</body>\n</html>\n"


def build():
    template = (AQUI / "template.html").read_text(encoding="utf-8")
    for marcador in ("__DATA__", "__COLETA__", "__BI__", "__FLORIPA__"):
        if marcador not in template:
            raise SystemExit(f"template.html perdeu o marcador {marcador}")
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    coleta = data_coleta()

    # Pagina de BI: tudo. Vai para o Artifact (privado do dono) e, se a
    # pasta do repositorio privado existir, para ela.
    dados_bi = dados_da_pagina(json.loads(json.dumps(historico)), bi=True)
    pagina_bi = (template.replace("__COLETA__", coleta).replace("__DATA__", dados_bi).replace("__BI__", "true")
                 .replace("__FLORIPA__", dados_floripa()))
    (AQUI / "artifact.html").write_text(pagina_bi, encoding="utf-8")
    if BI_DIR.is_dir():
        (BI_DIR / "index.html").write_text(completa(pagina_bi), encoding="utf-8")

    # Pagina publica: sem os paineis e sem os campos de BI.
    dados_pub = dados_da_pagina(historico, bi=False)
    pagina_pub = (so_publico(template).replace("__COLETA__", coleta).replace("__DATA__", dados_pub).replace("__BI__", "false")
                  .replace("__FLORIPA__", "null"))
    (AQUI / "index.html").write_text(completa(pagina_pub), encoding="utf-8")

    return len(pagina_bi)


if __name__ == "__main__":
    tamanho = build()
    print(f"index.html (publica) e artifact.html (BI) gerados ({tamanho:,} bytes, coleta de {data_coleta()})"
          + (f" | BI tambem em {BI_DIR}" if BI_DIR.is_dir() else ""))
    sys.exit(0)
