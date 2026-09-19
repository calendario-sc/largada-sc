#!/usr/bin/env python3
"""Baixa a lista de municipios do IBGE e guarda um indice enxuto em disco.

Substitui o mapa de cidades escrito a mao: cobre os 5.571 municipios do
Brasil, traz a mesorregiao oficial de cada um e nao precisa de manutencao.

O indice fica em municipios.json, no formato:
    {"SC": {"florianopolis": ["Florianópolis", "Grande Florianópolis"], ...}, ...}

Uso:  python municipios.py           # baixa se faltar ou estiver velho
      python municipios.py --forcar  # baixa de novo de qualquer jeito
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
AQUI = Path(__file__).resolve().parent
CACHE = AQUI / "municipios.json"

# Fronteiras municipais mudam de vez em quando, mas nao de mes para mes.
DIAS_DE_VALIDADE = 180


def chave_cidade(nome):
    """Normaliza para comparacao: sem acento, sem pontuacao, minusculo.

    Faz 'Grão-Pará', 'GRAO PARA' e 'grão pará' caírem na mesma chave.
    """
    sem = "".join(c for c in unicodedata.normalize("NFD", nome or "")
                  if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", sem).split()).lower()


def _uf_e_regiao(municipio):
    """O IBGE expoe a UF por dois caminhos; um deles falta em alguns registros."""
    micro = municipio.get("microrregiao")
    if micro:
        meso = micro["mesorregiao"]
        return meso["UF"]["sigla"], meso["nome"]
    imediata = municipio.get("regiao-imediata")
    if imediata:
        intermediaria = imediata["regiao-intermediaria"]
        return intermediaria["UF"]["sigla"], intermediaria["nome"]
    return None, None


def baixar_indice():
    from comum import baixar          # importado aqui para evitar ciclo

    bruto = json.loads(baixar(IBGE, {"Accept": "application/json"}, timeout=120))
    indice = {}
    perdidos = []
    for m in bruto:
        uf, regiao = _uf_e_regiao(m)
        if not uf:
            perdidos.append(m.get("nome"))
            continue
        indice.setdefault(uf, {})[chave_cidade(m["nome"])] = [m["nome"], regiao]
    return indice, perdidos


def precisa_atualizar():
    if not CACHE.exists():
        return True
    import datetime
    idade = datetime.date.today() - datetime.date.fromtimestamp(CACHE.stat().st_mtime)
    return idade.days > DIAS_DE_VALIDADE


def carregar(forcar=False):
    """Devolve o indice, baixando do IBGE se o cache faltar ou envelhecer."""
    if forcar or precisa_atualizar():
        indice, perdidos = baixar_indice()
        CACHE.write_text(json.dumps(indice, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
        if perdidos:
            print(f"aviso: {len(perdidos)} municipios sem UF no IBGE: {perdidos[:3]}")
    return json.loads(CACHE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    indice = carregar(forcar="--forcar" in sys.argv)
    total = sum(len(v) for v in indice.values())
    print(f"{total} municipios em {len(indice)} UFs "
          f"({CACHE.stat().st_size / 1024:.0f} KB)")
    for uf in ("SC", "PR", "SP"):
        regioes = sorted({r for _, r in indice.get(uf, {}).values()})
        print(f"  {uf}: {len(indice.get(uf, {}))} municipios, "
              f"{len(regioes)} regioes -> {regioes[:3]}...")
