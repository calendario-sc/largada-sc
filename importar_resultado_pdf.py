#!/usr/bin/env python3
"""Importa uma classificacao em PDF (paginas de resultado da ChipRun salvas em
PDF, um arquivo por distancia e sexo) para resultados-importados/<slug>.json.

Serve para as edicoes que os portais de resultado nao tem (ex.: Meia Maratona
de Palhoca 2022 e 2023, cujos PDFs oficiais vieram da organizacao). O arquivo
gerado entra no ranking das corridas (ranking_build.py) como mais uma edicao
da serie informada.

Le o texto com o pdftotext (Poppler, -layout). Cada atleta vem assim:
      1           #562 GABRIELA PAULA SANTOS
  POSICAO        F1629            10k
                     00:43:16     00:43:20
Sexo e distancia vem do nome do arquivo ("10KM FEMININO - ..."). Dos dois
tempos fica o menor (o liquido; o outro e o bruto).

Uso:  python importar_resultado_pdf.py PASTA --serie palhoca-meia-maratona-da-palhoca
          --data 2022-04-24 --nome "Meia Maratona de Palhoça 2022" --cidade Palhoça
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "resultados-importados"
ATLETA = re.compile(r"^\s*(\d{1,5})\s+(?:-\s+)?#\s*(\d+)\s*-?\s*(.+?)\s*$")
TEMPO = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")
CATEGORIA = re.compile(r"\b([FM]\d{2,4})\b")


def slug(nome):
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(nome).lower()).strip("-")


def texto(pdf):
    exe = shutil.which("pdftotext")
    if not exe:
        raise SystemExit("pdftotext nao encontrado (Poppler)")
    return subprocess.run([exe, "-enc", "UTF-8", "-layout", str(pdf), "-"], capture_output=True,
                          check=True).stdout.decode("utf-8", "replace")


def ler_arquivo(pdf):
    nome = sem_acento(pdf.name).upper()
    sexo = "F" if "FEMININ" in nome else "M" if "MASCULIN" in nome else None
    km = re.search(r"(\d+)\s*KM", nome)
    if not sexo or not km:
        raise SystemExit(f"nao sei o sexo/distancia pelo nome: {pdf.name}")
    modalidade = f"{int(km.group(1))}k"
    linhas, atual = [], None

    def fechar():
        if atual and atual["tempos"]:
            t = min(atual["tempos"])
            km_num = 21.1 if modalidade == "21k" else 42.2 if modalidade == "42k" else float(modalidade[:-1])
            linhas.append([slug(atual["nome"]), atual["nome"], sexo, modalidade, atual["cat"] or "", "-",
                           atual["pos"], t, round(t / km_num)])

    for linha in texto(pdf).splitlines():
        m = ATLETA.match(linha)
        if m and not TEMPO.search(linha):
            fechar()
            atual = {"pos": int(m.group(1)), "nome": " ".join(m.group(3).split()).title(), "cat": None, "tempos": []}
            continue
        if not atual:
            continue
        c = CATEGORIA.search(linha)
        if c and not atual["cat"]:
            atual["cat"] = c.group(1)
        atual["tempos"] += [int(h) * 3600 + int(mi) * 60 + int(s) for h, mi, s in TEMPO.findall(linha)]
    fechar()
    return linhas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--serie", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--nome", required=True)
    ap.add_argument("--cidade", required=True)
    ap.add_argument("--uf", default="SC")
    a = ap.parse_args()
    todas = []
    for pdf in sorted(Path(a.pasta).glob("*.pdf")):
        ls = ler_arquivo(pdf)
        posicoes = [l[6] for l in ls]
        aviso = "" if posicoes == list(range(1, len(ls) + 1)) else "  (colocacoes com falha: confira)"
        print(f"{pdf.name[:60]:60} {len(ls):4} atletas{aviso}")
        todas += ls
    s = f"{a.data[:4]}-{slug(a.nome)}"
    SAIDA.mkdir(exist_ok=True)
    destino = SAIDA / f"{s}.json"
    destino.write_text(json.dumps({"slug": s, "serie": a.serie, "data": a.data, "nome": a.nome, "cidade": a.cidade,
                                   "uf": a.uf, "fonte": "classificacao oficial em PDF (ChipRun)", "linhas": todas},
                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"ok: {destino.name} ({len(todas)} linhas)")


if __name__ == "__main__":
    main()
