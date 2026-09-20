#!/usr/bin/env python3
"""Traz os concluintes de todo o periodo, do Open Results.

A rodada diaria so olha os ultimos 90 dias, porque numero de prova antiga nao
muda. Este script e para a carga inicial, ou para refazer o periodo inteiro.

Uso:  python importar_concluintes.py [AAAA-MM-DD]
"""

import json
import sys

import scrape
from comum import sem_acento

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    desde = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))

    vistos, ligados, atualizados = scrape.vincular_concluintes(historico, desde=desde)
    print(f"Open Results desde {desde}: {vistos} provas | {ligados} casadas | "
          f"{atualizados} com numero novo")

    historico.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    scrape.SAIDA.write_text(
        json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    com = [p for p in historico if p.get("concluintes_total")]
    print(f"historico: {len(com)}/{len(historico)} provas com concluintes")
    total = sum(p["concluintes_total"] for p in com)
    print(f"total de concluintes: {total:,}".replace(",", "."))
