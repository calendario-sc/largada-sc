#!/usr/bin/env python3
"""Monta o indice de atletas que a pagina atletas.html consulta.

Le atletas/provas/<slug>.json (um por prova) e escreve:

  atletas/indice.json         lista de provas e de prefixos, mais totais
  atletas/dados/<prefixo>.json  atletas cujo nome comeca com o prefixo

A pagina nao carrega tudo: acha o prefixo do nome digitado no indice e
baixa so aquele arquivo. Prefixo comeca com duas letras e ganha uma terceira
(ou quarta) quando o balde fica grande demais: "ma" sozinho teria um quinto
dos corredores do estado.

Cada atleta: [nome, sexo, [[prova, km, tempo_s, pace_s, posicao, categoria,
modalidade], ...]], indexado pelo slug que o Open Results da ao nome.

Uso:  python atletas_build.py
"""

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
PROVAS = AQUI / "atletas" / "provas"
DADOS = AQUI / "atletas" / "dados"
INDICE = AQUI / "atletas" / "indice.json"
BALDE = 600          # atletas por arquivo; acima disso o prefixo cresce

KM = re.compile(r"(\d+)(?:[.,](\d+))?\s*k", re.I)
KM_HIFEN = re.compile(r"^(\d)-(\d)\s*k", re.I)      # "2-5KM" e 2,5 km
MILHAS = re.compile(r"(\d+(?:[.,]\d+)?)\s*milhas?", re.I)


def km_da_modalidade(rotulo):
    """'MEIA MARATONA 21KM' -> 21.1; '3,5K' -> 3.5; 'SOLO' -> None."""
    r = rotulo or ""
    baixo = sem_acento(r).lower()
    achado = KM_HIFEN.search(r)
    if achado:
        return float(f"{achado.group(1)}.{achado.group(2)}")
    achado = KM.search(r)
    if achado:
        inteiro, frac = achado.group(1), achado.group(2) or ""
        valor = float(f"{inteiro}.{frac}" if frac else inteiro)
        if valor == 21:
            return 21.1
        if valor == 42:
            return 42.2
        return valor
    achado = MILHAS.search(r)
    if achado:
        return round(float(achado.group(1).replace(",", ".")) * 1.609, 1)
    if "meia" in baixo:
        return 21.1
    if "maratona" in baixo:
        return 42.2
    return None


def chave(slug):
    return re.sub(r"[^a-z0-9]", "", sem_acento(slug).lower())


def repartir(atletas):
    """slug -> prefixo do arquivo, com baldes de no maximo BALDE atletas."""
    def dividir(grupo, tamanho):
        baldes = {}
        for slug in grupo:
            baldes.setdefault(chave(slug)[:tamanho] or "_", []).append(slug)
        saida = {}
        for pref, membros in baldes.items():
            # "maria" sozinho passa de 2 mil corredoras: precisa ir ate a
            # inicial do sobrenome para caber no balde.
            if len(membros) > BALDE and tamanho < 8 and len(pref) == tamanho:
                saida.update(dividir(membros, tamanho + 1))
            else:
                saida[pref] = membros
        return saida
    return dividir(list(atletas), 2)


def organizadores_por_slug():
    """or_slug -> organizadoras, do historico do calendario."""
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    return {p["or_slug"]: p.get("organizadores") or [] for p in historico if p.get("or_slug")}


def montar(registrar=print):
    provas, atletas = [], {}
    organizadores = organizadores_por_slug()
    for arquivo in sorted(PROVAS.glob("*.json")):
        d = json.loads(arquivo.read_text(encoding="utf-8"))
        if d.get("erro") or not d.get("linhas"):
            continue
        indice_prova = len(provas)
        # O quinto campo, as organizadoras, e o que da o selo de superfa.
        provas.append([d["data"], d["nome"], d["cidade"], d.get("slug_real") or d["slug"],
                       organizadores.get(d["slug"], [])])
        for slug, nome, sexo, modalidade, cat, _equipe, pos, tempo, pace in d["linhas"]:
            km = km_da_modalidade(modalidade)
            if pace is None and km:
                pace = round(tempo / km)
            entrada = atletas.setdefault(slug, [nome, sexo, []])
            entrada[2].append([indice_prova, km, tempo, pace, pos, cat, modalidade])

    # Ordem cronologica dentro de cada atleta.
    for entrada in atletas.values():
        entrada[2].sort(key=lambda r: provas[r[0]][0])

    reparticao = repartir(atletas)
    if DADOS.exists():
        shutil.rmtree(DADOS)
    DADOS.mkdir(parents=True)
    for pref, membros in reparticao.items():
        bloco = {slug: atletas[slug] for slug in sorted(membros)}
        (DADOS / f"{pref}.json").write_text(
            json.dumps(bloco, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    resultados = sum(len(a[2]) for a in atletas.values())
    INDICE.write_text(json.dumps({
        "provas": provas,
        "prefixos": sorted(reparticao),
        "atletas": len(atletas),
        "resultados": resultados,
        "anos": sorted({p[0][:4] for p in provas}),
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    maior = max((len(m) for m in reparticao.values()), default=0)
    registrar(f"atletas: {len(atletas)} | resultados: {resultados} | provas: {len(provas)} | "
              f"arquivos: {len(reparticao)} (maior com {maior} atletas)")
    return len(atletas)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    montar()
