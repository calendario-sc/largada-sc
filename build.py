#!/usr/bin/env python3
"""Monta as paginas a partir de template.html + corridas.json.

Gera dois arquivos com o mesmo conteudo:
  artifact.html - fragmento para publicar como Artifact (sem <html>/<head>/<body>)
  index.html    - pagina completa, abre direto no navegador

Uso:  python build.py
"""

import datetime
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


def build():
    template = (AQUI / "template.html").read_text(encoding="utf-8")
    dados = (AQUI / "corridas.json").read_text(encoding="utf-8").strip()

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
