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
RECORDES = AQUI / "atletas" / "recordes.json"
# Distancias padrao dos recordes e, por sexo, o tempo abaixo do qual e erro
# de dado (modalidade trocada, chip disparado antes): ninguem corre 5 km em
# 12 minutos numa prova de bairro. O corte fica um pouco abaixo dos
# recordes brasileiros.
DISTANCIAS_RECORDE = {5.0: "5", 10.0: "10", 21.1: "21", 42.2: "42"}
TEMPO_MINIMO = {"5": {"M": 13 * 60 + 45, "F": 15 * 60 + 30},
                "10": {"M": 28 * 60 + 30, "F": 32 * 60},
                "21": {"M": 62 * 60, "F": 70 * 60},
                "42": {"M": 130 * 60, "F": 148 * 60}}
TOP_POR_PROVA = 10
CANDIDATOS_POR_PROVA = 16     # sobra para o que a coerencia derrubar
SEM_POSICAO = 999999          # o portal marca assim quem nao foi classificado
NAO_E_RECORDE = re.compile(r"revez|dupla|quarteto|trio|equipe|kids|infantil|pcd|cadeir|hand|bike|caminh", re.I)
# Ritmo do candidato comparado ao melhor ritmo do proprio atleta em outras
# provas: maratona a 2:58/km de quem corre 10 km a 4:43 e revezamento ou
# chip disparado antes da largada, nao recorde.
COERENCIA_CURTA = 0.92        # frente ao melhor ritmo em distancia menor
COERENCIA_QUALQUER = 0.80     # frente ao melhor ritmo em qualquer distancia
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


# Marcadores que a cronometragem usa quando nao sabe quem e: nao sao pessoa.
NAO_E_PESSOA = re.compile(r"desconhecid|nao-identificad|sem-nome|^atleta$|^participante$|^n-?a$", re.I)


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


def calendario_por_slug():
    """or_slug -> (organizadoras, serie, nome da serie), do calendario.

    A serie junta as edicoes de um mesmo evento: e por ela que se sabe qual
    prova o atleta mais repetiu.
    """
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    return {p["or_slug"]: (p.get("organizadores") or [], p.get("serie") or "", p.get("serie_nome") or "")
            for p in historico if p.get("or_slug")}


def top_da_prova(linhas):
    """Os melhores tempos da prova por distancia padrao e sexo: e o que a
    pagina do calendario cruza com os filtros para montar os recordes."""
    por = {}
    vistos = set()
    for slug, nome, sexo, modalidade, cat, _eq, pos, tempo, _pace in linhas:
        if NAO_E_PESSOA.search(slug) or (slug, modalidade) in vistos:
            continue
        vistos.add((slug, modalidade))
        dist = DISTANCIAS_RECORDE.get(km_da_modalidade(modalidade))
        if not dist or not tempo or sexo not in ("F", "M") or tempo < TEMPO_MINIMO[dist][sexo]:
            continue
        if pos in (None, SEM_POSICAO) or NAO_E_RECORDE.search(f"{modalidade} {cat}"):
            continue
        por.setdefault(dist, {}).setdefault(sexo, []).append((tempo, slug, nome))
    saida = {}
    for dist, sexos in por.items():
        linhas_dist = []
        for sexo, lista in sexos.items():
            lista.sort()
            melhores, ja = [], set()
            for tempo, slug, nome in lista:
                if slug in ja:
                    continue
                ja.add(slug)
                melhores.append([nome, sexo, tempo, slug])
                if len(melhores) == CANDIDATOS_POR_PROVA:
                    break
            linhas_dist += melhores
        saida[dist] = linhas_dist
    return saida


KM_RECORDE = {"5": 5.0, "10": 10.0, "21": 21.1, "42": 42.2}


def coerente(candidato_km, tempo, resultados):
    """O ritmo do candidato combina com o resto do historico do atleta?"""
    ritmo = tempo / candidato_km
    outros = [(km, t / km) for _i, km, t, _p, _pos, _c, _m in resultados if km and t and km != candidato_km]
    if not outros:
        return True
    if ritmo < COERENCIA_QUALQUER * min(r for _k, r in outros):
        return False
    curtas = [r for km, r in outros if km < candidato_km]
    return not curtas or ritmo >= COERENCIA_CURTA * min(curtas)


def filtrar_recordes(recordes, atletas):
    """Tira os candidatos incoerentes e deixa os TOP_POR_PROVA por sexo."""
    saida = {}
    for slug_prova, por_dist in recordes.items():
        novo = {}
        for dist, linhas in por_dist.items():
            km = KM_RECORDE[dist]
            por_sexo = {}
            for nome, sexo, tempo, slug in linhas:
                entrada = atletas.get(slug)
                if entrada and not coerente(km, tempo, entrada[2]):
                    continue
                lista = por_sexo.setdefault(sexo, [])
                if len(lista) < TOP_POR_PROVA:
                    lista.append([nome, sexo, tempo, slug])
            juntas = [x for lista in por_sexo.values() for x in lista]
            if juntas:
                novo[dist] = juntas
        if novo:
            saida[slug_prova] = novo
    return saida


def montar(registrar=print):
    provas, atletas, recordes = [], {}, {}
    calendario = calendario_por_slug()
    for arquivo in sorted(PROVAS.glob("*.json")):
        d = json.loads(arquivo.read_text(encoding="utf-8"))
        if d.get("erro") or not d.get("linhas"):
            continue
        indice_prova = len(provas)
        top = top_da_prova(d["linhas"])
        if top:
            recordes[d["slug"]] = top
        # Organizadoras dao o selo de superfa; serie diz qual prova se repetiu.
        orgs, serie, serie_nome = calendario.get(d["slug"], ([], "", ""))
        provas.append([d["data"], d["nome"], d["cidade"], d.get("slug_real") or d["slug"],
                       orgs, serie, serie_nome])
        vistas = set()
        for slug, nome, sexo, modalidade, cat, _equipe, pos, tempo, pace in d["linhas"]:
            if NAO_E_PESSOA.search(slug):
                continue
            # O portal repete uma linha aqui e ali (429 em 236 mil): fica a primeira.
            if (slug, modalidade) in vistas:
                continue
            vistas.add((slug, modalidade))
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

    recordes = filtrar_recordes(recordes, atletas)
    RECORDES.write_text(json.dumps(recordes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
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
