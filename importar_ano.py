#!/usr/bin/env python3
"""Traz para o historico um ano inteiro ja encerrado, do arquivo do corridasbr.

A coleta diaria so olha o ano corrente. Este script e para trazer anos
anteriores uma vez, quando se quer material de comparacao.

Uso:  python importar_ano.py 2024 2025 [--uf PR]
"""

import datetime
import json
import sys

import fontes
import scrape
from comum import sem_acento


def importar(anos, uf="SC"):
    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8")) \
        if scrape.SAIDA.exists() else []
    hoje = datetime.date.today().isoformat()

    for ano in anos:
        registros = fontes.corridasbr_arquivo(ano=ano, ate_mes=12, uf=uf)
        if not registros:
            print(f"{ano}: nada encontrado no arquivo")
            continue

        provas, descartadas = scrape.peneirar(scrape.agrupar(registros))
        print(f"{ano}: {len(registros)} linhas -> {len(provas)} provas "
              f"({len(descartadas)} descartadas)")

        por_data = {}
        for p in historico:
            por_data.setdefault(p["data"], []).append(p)

        novas = 0
        for prova in provas:
            antiga = scrape.casar_no_historico(prova, por_data)
            if antiga:
                # Prova que so o portal de resultados trazia: o link do
                # corridasbr e o que deixa achar organizador e percurso.
                if prova.get("resultado_id") and not antiga.get("resultado_id"):
                    antiga["resultado_id"] = prova["resultado_id"]
                    antiga["fontes"] = sorted(set(antiga.get("fontes") or []) | {"corridasbr"})
                continue      # ja estava no historico
            prova["primeira_vez"] = hoje
            prova["visto_em"] = hoje
            historico.append(prova)
            por_data.setdefault(prova["data"], []).append(prova)
            novas += 1
        print(f"      {novas} entraram no historico")

    # Preenche percurso e organizador das provas novas. Uma pagina por prova:
    # o cache faz os dois campos saírem da mesma requisicao.
    while True:
        tentados, achados = scrape.completar_organizadores(historico, limite=500)
        if tentados:
            print(f"organizador: {tentados} consultadas, {achados} preenchidas")
        tentadas, achadas = scrape.completar_distancias(historico, limite=500)
        if tentadas:
            print(f"percurso: {tentadas} consultadas, {achadas} preenchidas")
        if not tentados and not tentadas:
            break

    scrape.padronizar_organizadores(historico)
    historico.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    scrape.SAIDA.write_text(
        json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    por_ano = {}
    for p in historico:
        por_ano[p["ano"]] = por_ano.get(p["ano"], 0) + 1
    print(f"\nhistorico: {len(historico)} provas")
    for ano in sorted(por_ano):
        print(f"  {ano}: {por_ano[ano]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = sys.argv[1:]
    uf = "SC"
    if "--uf" in args:
        uf = args[args.index("--uf") + 1].upper()
        args = [a for a in args if a not in ("--uf", uf, uf.lower())]
    anos = [int(a) for a in args] or [datetime.date.today().year - 1]
    importar(anos, uf)
