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


def dados_da_pagina(historico):
    """O historico guarda o perfil inteiro; a pagina leva so o que mostra.

    O perfil completo acrescentava ~430 KB, quase tudo campo vazio ou de
    prova ja realizada -- peso a toa no celular.
    """
    hoje = datetime.date.today().isoformat()
    for p in historico:
        perfil = p.pop("perfil", None)
        for campo in ("perfil_em", "ts_id", "ts_url", "rr_slug"):
            p.pop(campo, None)
        if perfil and p["data"] >= hoje:
            cartao = _para_o_cartao(perfil)
            if cartao:
                p["cartao"] = cartao
    return json.dumps(historico, ensure_ascii=False, separators=(",", ":"))


def build():
    template = (AQUI / "template.html").read_text(encoding="utf-8")
    dados = dados_da_pagina(json.loads((AQUI / "corridas.json").read_text(encoding="utf-8")))

    for marcador in ("__DATA__", "__COLETA__"):
        if marcador not in template:
            raise SystemExit(f"template.html perdeu o marcador {marcador}")

    pagina = template.replace("__COLETA__", data_coleta()).replace("__DATA__", dados)
    (AQUI / "artifact.html").write_text(pagina, encoding="utf-8")

    # A pagina standalone precisa do <head>, entao o <style> sobe para dentro dele.
    estilo, corpo = pagina.split("</style>", 1)
    completa = CABECALHO + estilo + "</style>\n</head>\n<body>\n" + corpo + "\n</body>\n</html>\n"
    (AQUI / "index.html").write_text(completa, encoding="utf-8")

    return len(pagina)


if __name__ == "__main__":
    tamanho = build()
    print(f"artifact.html e index.html gerados ({tamanho:,} bytes, coleta de {data_coleta()})")
    sys.exit(0)
