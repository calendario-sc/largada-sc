#!/usr/bin/env python3
"""Ranking de cada corrida (serie de edicoes) para a pagina ranking.html.

Regra (a mesma do ranking historico da Meia Maratona de Palhoca): em cada
edicao, os 20 primeiros da classificacao geral -- separados por distancia e
sexo -- ganham pontos pela tabela PONTOS; os pontos se somam ao longo das
edicoes, desde 2022. Junto vai a galeria de campeoes (vencedor e vencedora de
cada edicao, com o recorde da distancia marcado).

Le atletas/provas/*.json (resultados coletados), resultados-importados/*.json
(edicoes que os portais nao tem, importadas de PDF oficial) e corridas.json
(qual serie cada prova e). Escreve:
  atletas/ranking/indice.json   lista de corridas com ranking
  atletas/ranking/<serie>.json  ranking e campeoes de uma corrida
(publicados no R2 junto com o resto de atletas/, ver publicar_dados.py).

Uso:  python ranking_build.py
"""

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atletas_build import (DISTANCIAS_RECORDE, NAO_E_CAMPEAO, NAO_E_PESSOA, RITMO_MINIMO,  # noqa: E402
                           SEM_POSICAO, TEMPO_MINIMO, coerente, km_da_modalidade)
from comum import sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
PROVAS = AQUI / "atletas" / "provas"
IMPORTADOS = AQUI / "resultados-importados"
SAIDA = AQUI / "atletas" / "ranking"
DESDE = "2022-01-01"
PONTOS = [250, 190, 170, 160, 150, 140, 130, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


def chave_nome(nome):
    """Mesma pessoa com grafias que mudam de um ano para outro: sem acento,
    maiuscula, particulas (de/da/dos), y/i e letra dobrada."""
    s = sem_acento(nome).lower().replace("y", "i")
    palavras = [p for p in re.findall(r"[a-z]+", s) if p not in PARTICULAS]
    return re.sub(r"(.)\1+", r"\1", "".join(palavras))


def nome_bonito(nome):
    """'DENISE DE FARIAS DA MAIA' -> 'Denise de Farias da Maia' (nome ja em caixa mista fica)."""
    n = " ".join(str(nome).split())
    if n == n.upper() or n == n.lower():
        n = n.title()
    return " ".join(p if i == 0 or p.lower() not in PARTICULAS else p.lower() for i, p in enumerate(n.split()))


def rotulo_km(km):
    return {21.1: "21 km", 42.2: "42 km"}.get(km, (f"{km:g}".replace(".", ",")) + " km")


def valida(slug, sexo, modalidade, cat, pos, tempo):
    if NAO_E_PESSOA.search(slug or "") or sexo not in ("F", "M") or not tempo:
        return None
    if NAO_E_CAMPEAO.search(f"{modalidade} {cat}") or pos == SEM_POSICAO:
        return None
    km = km_da_modalidade(modalidade)
    if not km or km < 1 or tempo / km < RITMO_MINIMO[sexo]:
        return None
    padrao = DISTANCIAS_RECORDE.get(km)
    if padrao and tempo < TEMPO_MINIMO[padrao][sexo]:
        return None
    return km


def edicoes_por_serie():
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    cal = {p["or_slug"]: p for p in historico if p.get("or_slug")}
    info = {}                       # serie -> dados da edicao mais recente do calendario
    for p in historico:
        if p.get("serie") and p["data"] >= DESDE:
            if p["serie"] not in info or p["data"] >= info[p["serie"]]["data"]:
                info[p["serie"]] = p
    series = defaultdict(dict)      # serie -> {data: edicao}
    historico_atleta = defaultdict(list)   # slug -> resultados (para o filtro de coerencia)
    for arq in sorted(PROVAS.glob("*.json")):
        d = json.loads(arq.read_text(encoding="utf-8"))
        for slug, _n, _s, modalidade, _c, _e, _pos, tempo, _p in d.get("linhas") or []:
            km = km_da_modalidade(modalidade)
            if km and tempo:
                historico_atleta[slug].append([0, km, tempo, 0, 0, "", ""])
        p = cal.get(d.get("slug"))
        if d.get("erro") or not d.get("linhas") or not p or not p.get("serie") or d["data"] < DESDE:
            continue
        series[p["serie"]][d["data"]] = {"data": d["data"], "nome": d["nome"], "linhas": d["linhas"]}
    for arq in sorted(IMPORTADOS.glob("*.json")) if IMPORTADOS.exists() else []:
        d = json.loads(arq.read_text(encoding="utf-8"))
        if d["data"] >= DESDE:
            series[d["serie"]].setdefault(d["data"], {"data": d["data"], "nome": d["nome"], "linhas": d["linhas"],
                                                       "importado": True})
    return series, info, historico_atleta


def ranking_da_serie(edicoes, historico_atleta):
    edicoes = sorted(edicoes.values(), key=lambda e: e["data"])
    anos = [e["data"][:4] for e in edicoes]
    rotulos = [a if anos.count(a) == 1 else f"{a} {MESES[int(e['data'][5:7]) - 1]}" for a, e in zip(anos, edicoes)]
    grupos = defaultdict(lambda: {"atletas": {}, "campeoes": []})
    for i, e in enumerate(edicoes):
        por = defaultdict(list)
        for slug, nome, sexo, modalidade, cat, _eq, pos, tempo, _pace in e["linhas"]:
            km = valida(slug, sexo, modalidade, cat, pos, tempo)
            if km:
                por[(km, sexo)].append((tempo, pos if isinstance(pos, int) else 999999, nome, slug))
        for (km, sexo), lista in por.items():
            g = grupos[(km, sexo)]
            vistos, colocados = set(), []
            for tempo, _pos, nome, slug in sorted(lista):
                k = chave_nome(nome)
                if k in vistos:
                    continue
                # Tempo que nao combina com o resto do historico do atleta (21 km no ritmo
                # em que ele corre 5 km): corte de percurso ou chip -- a cronometragem tira da classificacao.
                if historico_atleta.get(slug) and not coerente(km, tempo, historico_atleta[slug]):
                    continue
                vistos.add(k)
                colocados.append((k, nome, slug, tempo))
                if len(colocados) == len(PONTOS):
                    break
            for lugar, (k, nome, slug, tempo) in enumerate(colocados):
                a = g["atletas"].setdefault(k, {"nome": nome, "slug": slug, "pts": [None] * len(edicoes), "melhor": tempo})
                a["nome"], a["slug"] = nome, slug or a["slug"]       # fica a grafia mais recente
                a["pts"][i] = PONTOS[lugar]
                a["melhor"] = min(a["melhor"], tempo)
            if colocados:
                g["campeoes"].append([i, nome_bonito(colocados[0][1]), colocados[0][3], colocados[0][2]])
    distancias = []
    for km in sorted({km for km, _ in grupos}, reverse=True):
        d = {"km": km, "rotulo": rotulo_km(km)}
        for sexo in ("M", "F"):
            g = grupos.get((km, sexo))
            if not g or not g["campeoes"]:
                continue
            lista = []
            for a in g["atletas"].values():
                pts = [p or 0 for p in a["pts"]]
                primeira = next((j for j, p in enumerate(a["pts"]) if p is not None), 99)
                lista.append((-sum(pts), -max(pts), primeira, a["melhor"], a["nome"], a))
            lista.sort(key=lambda x: x[:5])
            recorde = min(c[2] for c in g["campeoes"])
            d[sexo] = {
                "ranking": [[nome_bonito(a["nome"]), a["slug"], a["pts"], -tot, a["melhor"]] for tot, _m, _p, _b, _n, a in lista],
                "campeoes": [[i, nome, tempo, slug, tempo == recorde] for i, nome, tempo, slug in g["campeoes"]],
            }
        if "M" in d or "F" in d:
            distancias.append(d)
    return {"edicoes": [{"rotulo": r, "data": e["data"], "nome": e["nome"], **({"importado": True} if e.get("importado") else {})}
                        for r, e in zip(rotulos, edicoes)], "distancias": distancias}


def montar(registrar=print):
    series, info, historico_atleta = edicoes_por_serie()
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir(parents=True)
    indice = []
    for serie, edicoes in series.items():
        r = ranking_da_serie(edicoes, historico_atleta)
        if not r["distancias"]:
            continue
        p = info.get(serie) or {}
        ultima = r["edicoes"][-1]
        r.update({"serie": serie, "nome": p.get("serie_nome") or ultima["nome"], "cidade": p.get("cidade") or "",
                  "uf": p.get("uf") or "SC", "desde": DESDE[:4], "pontos": PONTOS,
                  "proxima": p["data"] if p.get("data", "") > ultima["data"] else None})
        (SAIDA / f"{serie}.json").write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        n = len({chave_nome(a[0]) for d in r["distancias"] for s in ("M", "F") for a in (d.get(s) or {}).get("ranking", [])})
        indice.append([serie, r["nome"], r["cidade"], r["uf"], [e["rotulo"] for e in r["edicoes"]],
                       [d["rotulo"] for d in r["distancias"]], n])
    indice.sort(key=lambda x: sem_acento(x[1]).lower())
    (SAIDA / "indice.json").write_text(json.dumps({"desde": DESDE[:4], "pontos": PONTOS, "corridas": indice},
                                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    registrar(f"ranking: {len(indice)} corridas, {sum(len(x[4]) for x in indice)} edicoes")
    return len(indice)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    montar()
