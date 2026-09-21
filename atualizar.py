#!/usr/bin/env python3
"""Atualiza o Largada SC: coleta o calendario e remonta as paginas.

Se a coleta falhar, o corridas.json anterior e mantido e nada e reconstruido,
para nunca publicar uma pagina vazia.

Uso:  python atualizar.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json

import build
import perfis
import scrape


def main():
    print("== coleta ==")
    if scrape.main() != 0:
        print("\nRESULTADO: nada a publicar (coleta falhou).")
        return 1

    # Perfil falhando nao impede a publicacao do calendario.
    print("\n== perfis ==")
    try:
        historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))
        feitos = perfis.atualizar_perfis(historico)
        scrape.SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
                                encoding="utf-8")
        print(f"perfis revistos: {feitos}")
    except Exception as erro:
        print(f"perfis: FALHOU ({erro.__class__.__name__}: {erro})")

    print("\n== build ==")
    tamanho = build.build()
    print(f"artifact.html e index.html gerados ({tamanho:,} bytes)")
    print(f"\nRESULTADO: pronto para publicar (coleta de {build.data_coleta()}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
