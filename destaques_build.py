#!/usr/bin/env python3
"""Curiosidades dos atletas para a abertura de atletas.html.

A pagina so baixa o balde do nome buscado; o que precisa da base inteira
(o mais rapido do ano, quem mais venceu, quem ja correu todas as distancias)
sai daqui pronto, num arquivo pequeno: atletas/destaques.json.

Le atletas/indice.json, atletas/dados/*.json e atletas/campeoes.json (o que o
atletas_build.py escreve). Roda depois dele.

Homonimos: o portal junta pelo nome, e "Joao Silva" pode ser varias pessoas.
Atleta com duas provas no mesmo dia, ou com ritmos muito diferentes na mesma
distancia, fica fora das listas (e ruido, nao curiosidade).

Uso:  python destaques_build.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atletas_build import (DISTANCIAS_RECORDE, NAO_E_PESSOA, NAO_E_RECORDE, RITMO_MINIMO,  # noqa: E402
                           SEM_POSICAO, TEMPO_MINIMO, coerente)

AQUI = Path(__file__).resolve().parent
ATLETAS = AQUI / "atletas"
SAIDA = ATLETAS / "destaques.json"
TOP = 5
PADRAO = (5.0, 10.0, 21.1, 42.2)
RITMO_HOMONIMO = 1.5      # pior ritmo / melhor ritmo na mesma distancia acima disso: duas pessoas
# Trilha e montanha: o tempo nao se compara com o do asfalto (fica fora das listas de tempo).
TRILHA = re.compile(r"trail|trilha|off.?road|montanh|serra|rastro|cross|subida|vertical|morro|mountain|sky", re.I)
EDICOES_FIEL = 4          # edicoes da mesma prova para contar como "fiel"


def valido(r, sexo):
    """Resultado que conta para tempo e ritmo: distancia conhecida, classificado,
    sem revezamento ou kids, e sem tempo impossivel."""
    _i, km, tempo, _pace, pos, cat, modalidade = r
    if not km or not tempo or km < 1 or sexo not in RITMO_MINIMO or pos == SEM_POSICAO:
        return False
    if NAO_E_RECORDE.search(f"{modalidade} {cat}"):
        return False
    if tempo / km < RITMO_MINIMO[sexo]:
        return False
    padrao = DISTANCIAS_RECORDE.get(km)
    return not (padrao and tempo < TEMPO_MINIMO[padrao][sexo])


def homonimo(res, provas):
    dias = {}
    for r in res:
        d = provas[r[0]][0]
        if d in dias and dias[d] != r[0]:
            return True                  # duas provas diferentes no mesmo dia
        dias[d] = r[0]
    ritmos = {}
    for r in res:
        if r[1] and r[2]:
            ritmos.setdefault(r[1], []).append(r[2] / r[1])
    return any(max(v) / min(v) > RITMO_HOMONIMO for v in ritmos.values() if len(v) > 1)


def montar(registrar=print):
    indice = json.loads((ATLETAS / "indice.json").read_text(encoding="utf-8"))
    provas = indice["provas"]
    ano = str(date.today().year)
    if not any(p[0].startswith(ano) for p in provas):
        ano = max(p[0][:4] for p in provas)

    titulos = {}
    for por_dist in json.loads((ATLETAS / "campeoes.json").read_text(encoding="utf-8")).values():
        for _km, f, m in por_dist:
            for v in (f, m):
                if v:
                    titulos[v[2]] = titulos.get(v[2], 0) + 1

    rapidos = {(km, s): [] for km in PADRAO for s in "FM"}   # do ano
    paces = {"F": [], "M": []}
    trofeus, provas_total, km_total, no_ano, fieis, evolucao = [], [], [], [], [], []
    papa, viajantes, maratonas = [], [], []
    total = suspeitos = estreantes = ativos = maratonistas = sempre = 0
    todos_anos = {p[0][:4] for p in provas}

    for arquivo in sorted((ATLETAS / "dados").glob("*.json")):
        for slug, (nome, sexo, res) in json.loads(arquivo.read_text(encoding="utf-8")).items():
            if NAO_E_PESSOA.search(slug) or not res:
                continue
            total += 1
            datas = sorted(provas[r[0]][0] for r in res)
            if datas[0].startswith(ano):
                estreantes += 1
            if datas[-1].startswith(ano):
                ativos += 1
            if homonimo(res, provas):
                suspeitos += 1
                continue
            sx = sexo if sexo in ("F", "M") else ""
            bons = [r for r in res if valido(r, sx)]
            asfalto = [r for r in bons if not TRILHA.search(f"{provas[r[0]][1]} {r[6]} {r[5]}")]
            distintas = {provas[r[0]][3] for r in res}
            pessoa = [nome, sx, slug]

            provas_total.append((len(distintas), pessoa))
            km_total.append((round(sum(r[1] for r in bons)), pessoa))
            n_ano = len({provas[r[0]][3] for r in res if provas[r[0]][0].startswith(ano)})
            if n_ano:
                no_ano.append((n_ano, pessoa))
            if titulos.get(slug):
                trofeus.append((titulos[slug], pessoa))
            # fiel a prova: mais edicoes da mesma serie
            series = {}
            for r in res:
                s = provas[r[0]][5]
                if s:
                    series.setdefault(s, set()).add(provas[r[0]][0][:4])
            cativas = [s for s, anos in series.items() if len(anos) >= EDICOES_FIEL]
            if cativas:
                fieis.append(((len(cativas), len(distintas)), pessoa + [len(cativas)]))
            if {d[:4] for d in datas} >= todos_anos:
                sempre += 1
            cidades = {provas[r[0]][2] for r in res if provas[r[0]][2]}
            viajantes.append(((len(cidades), len(distintas)), pessoa + [len(cidades)]))
            n42 = len({r[0] for r in bons if r[1] == 42.2})
            if n42:
                maratonas.append(((n42, len(distintas)), pessoa + [n42]))

            melhor = {}
            for r in bons:
                if r[1] in PADRAO and (r[1] not in melhor or r[2] < melhor[r[1]][2]):
                    melhor[r[1]] = r
            if 42.2 in melhor:
                maratonistas += 1
            if all(k in melhor for k in PADRAO):
                papa.append((len({r[1] for r in bons}), len(distintas), pessoa))
            if not sx:
                continue
            plano = {}
            for r in asfalto:
                if r[1] in PADRAO and (r[1] not in plano or r[2] < plano[r[1]][2]):
                    plano[r[1]] = r
            # melhor pace nas distancias de 10 km para cima (nos 5 km e o "mais rapido do ano")
            ritmos = [(r[2] / km, km, r) for km, r in plano.items() if km >= 10 and coerente(km, r[2], res)]
            if ritmos:
                rt, km, r = min(ritmos)
                paces[sx].append((rt, pessoa + [km, r[2], r[0]]))
            for km in PADRAO:
                do_ano = [r for r in asfalto if r[1] == km and provas[r[0]][0].startswith(ano) and coerente(km, r[2], res)]
                if do_ano:
                    r = min(do_ano, key=lambda r: r[2])
                    rapidos[(km, sx)].append((r[2], pessoa + [r[0]]))
            # evolucao nos 10 km: o primeiro tempo e o melhor, com ao menos 6 meses entre eles
            dez = [r for r in asfalto if r[1] == 10.0 and coerente(10.0, r[2], res)]
            if len(dez) >= 2:
                prim, best = dez[0], min(dez, key=lambda r: r[2])
                meses = (date.fromisoformat(provas[best[0]][0]) - date.fromisoformat(provas[prim[0]][0])).days / 30.4
                if best[2] < prim[2] and meses >= 6:
                    evolucao.append((prim[2] - best[2], pessoa + [prim[2], best[2], prim[0], best[0]]))

    def topo(lista, n=TOP, menor=False):
        lista.sort(key=lambda x: x[0], reverse=not menor)
        return [[x[0]] + x[1] for x in lista[:n]]

    def prova(i):
        p = provas[i]
        return [p[1], p[0], p[3]]

    saida = {
        "ano": ano, "gerado": date.today().isoformat(), "desde": min(p[0][:4] for p in provas),
        "totais": {"atletas": total, "ativos_ano": ativos, "estreantes_ano": estreantes, "maratonistas": maratonistas,
                   "papa_distancias": len(papa), "todos_os_anos": sempre, "fieis": len(fieis), "homonimos_fora": suspeitos},
        # tempo, nome, sexo, slug, prova
        "rapidos_ano": {f"{km:g}": {s: [[t, n, sx, sl, prova(i)] for t, (n, sx, sl, i) in sorted(rapidos[(km, s)], key=lambda x: x[0])[:3]]
                                    for s in "FM"} for km in PADRAO},
        "trofeus": topo(trofeus),
        # ritmo s/km, nome, sexo, slug, km, tempo, prova
        "paces": {s: [[round(r, 1), n, sx, sl, km, t, prova(i)] for r, (n, sx, sl, km, t, i) in sorted(paces[s], key=lambda x: x[0])[:TOP]] for s in "FM"},
        "papa_distancias": [[d, p, *pessoa] for d, p, pessoa in sorted(papa, key=lambda x: (-x[0], -x[1]))[:TOP]],
        "mais_provas": topo(provas_total),
        "mais_km": topo(km_total),
        "mais_provas_ano": topo(no_ano),
        # (provas com 4+ edicoes, provas), nome, sexo, slug, provas com 4+ edicoes
        "fieis": [[x[1][-1]] + x[1][:-1] for x in sorted(fieis, key=lambda x: x[0], reverse=True)[:TOP]],
        "viajantes": [[x[1][-1]] + x[1][:-1] for x in sorted(viajantes, key=lambda x: x[0], reverse=True)[:TOP]],
        "maratonas": [[x[1][-1]] + x[1][:-1] for x in sorted(maratonas, key=lambda x: x[0], reverse=True)[:TOP]],
        "edicoes_fiel": EDICOES_FIEL,
        # segundos ganhos, nome, sexo, slug, primeiro tempo, melhor tempo, prova do primeiro, prova do melhor
        "evolucao_10k": [[g, n, sx, sl, t1, t2, prova(i1), prova(i2)] for g, (n, sx, sl, t1, t2, i1, i2) in sorted(evolucao, key=lambda x: -x[0])[:TOP]],
    }
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    registrar(f"destaques: {total} atletas, {suspeitos} homonimos fora, {len(papa)} papa-distancias "
              f"({SAIDA.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    montar()
