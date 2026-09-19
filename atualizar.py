#!/usr/bin/env python3
"""Atualiza o Largada SC: coleta o calendario e remonta as paginas.

Se a coleta falhar, o corridas.json anterior e mantido e nada e reconstruido,
para nunca publicar uma pagina vazia.

Uso:  python atualizar.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build
import scrape


def main():
    print("== coleta ==")
    if scrape.main() != 0:
        print("\nRESULTADO: nada a publicar (coleta falhou).")
        return 1

    print("\n== build ==")
    tamanho = build.build()
    print(f"artifact.html e index.html gerados ({tamanho:,} bytes)")
    print(f"\nRESULTADO: pronto para publicar (coleta de {build.data_coleta()}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
