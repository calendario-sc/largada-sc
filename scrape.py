#!/usr/bin/env python3
"""Coleta as tres fontes, funde as provas repetidas e acumula em corridas.json.

O arquivo e um HISTORICO: provas ja realizadas continuam nele mesmo depois de
sairem das fontes. Nada e apagado; cada rodada so acrescenta e atualiza.

Uso:  python scrape.py
"""

import datetime
import json
import sys
import time
from pathlib import Path

import fontes
from comum import (FAIXAS, NAO_CORRIDA, UF_ALVO, canonizar_cidade, classificar,
                   faixas_de, mesma_prova, sem_acento)

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "corridas.json"

# Piso de sanidade: abaixo disso a coleta e considerada quebrada e o
# historico fica intacto.
MINIMO = 60

ORDEM_TAGS = ["Trail", "Ultra", "Noturna", "Vertical", "Revezamento",
              "Caminhada", "Kids", "Rua"]

# Quantas paginas de resultado consultar por rodada, e a pausa entre elas.
# So provas ainda sem percurso entram na fila, entao depois do primeiro
# preenchimento a fila fica vazia e a rodada diaria nao pede nada.
LIMITE_DETALHES = 400
PAUSA_DETALHES = 0.15


def qualidade_nome(nome):
    """Nome melhor = mais informativo e sem CAIXA ALTA gritada."""
    return (0 if nome.isupper() else 1, len(nome))


def fundir(grupo):
    """Combina os registros de uma mesma prova vindos de fontes diferentes."""
    melhor_nome = max((g["nome"] for g in grupo), key=qualidade_nome)

    # Cidade: vale a que o mapa de regioes reconhece.
    com_regiao = [g for g in grupo
                  if g["regiao"] != "Outras" and not g["regiao"].startswith("Fora de")]
    referencia = com_regiao[0] if com_regiao else grupo[0]

    # Distancias: a fonte que traz quilometragem real ganha das faixas genericas.
    com_km = [g for g in grupo if g.get("km")]
    if com_km:
        rico = max(com_km, key=lambda g: len(g["km"]))
        pills, faixas = rico["pills"], faixas_de(rico["km"])
        max_km = round(max(rico["km"]), 1)
    else:
        com_pills = [g for g in grupo if g["pills"]]
        rico = max(com_pills, key=lambda g: len(g["pills"])) if com_pills else grupo[0]
        pills = rico["pills"]
        faixas = sorted({f for g in grupo for f in g.get("faixas_diretas", [])},
                        key=FAIXAS.index)
        max_km = 0

    tags = sorted({t for g in grupo for t in g["tags"]},
                  key=lambda t: ORDEM_TAGS.index(t) if t in ORDEM_TAGS else 99)
    if len(tags) > 1 and "Rua" in tags:
        tags.remove("Rua")   # "Rua" so vale quando nao ha nada mais especifico

    return {
        "data": grupo[0]["data"],
        "dia": grupo[0]["dia"], "mes": grupo[0]["mes"], "ano": grupo[0]["ano"],
        "cidade": referencia["cidade"], "regiao": referencia["regiao"],
        "uf": referencia.get("uf"),
        "nome": melhor_nome,
        "pills": pills, "faixas": faixas, "max_km": max_km,
        "tags": tags,
        "fontes": sorted({g["fonte"] for g in grupo}),
        "resultado_id": next((g["resultado_id"] for g in grupo if g.get("resultado_id")), None),
    }


def agrupar(registros):
    """Junta registros da mesma data cujos nomes designam a mesma prova."""
    por_data = {}
    for r in registros:
        por_data.setdefault(r["data"], []).append(r)

    fundidas = []
    for data in sorted(por_data):
        grupos = []
        for r in por_data[data]:
            for g in grupos:
                if mesma_prova(r, g[0]):
                    g.append(r)
                    break
            else:
                grupos.append([r])
        fundidas += [fundir(g) for g in grupos]

    fundidas.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    return fundidas


def peneirar(provas):
    """Tira o que nao pertence a um calendario de corridas da UF alvo.

    As fontes trazem eventos de outros estados e outras modalidades mesmo com
    os filtros aplicados; o descarte e reportado para poder ser auditado.
    """
    ficam, saem = [], []
    for p in provas:
        if p["regiao"].startswith("Fora de"):
            saem.append((p, f"é de {p.get('uf') or 'outro estado'}"))
            continue
        nome = sem_acento(p["nome"])
        modalidade = next((m for m in NAO_CORRIDA if m in nome), None)
        if modalidade:
            saem.append((p, modalidade))
            continue
        ficam.append(p)
    return ficam, saem


def completar_distancias(historico, limite=LIMITE_DETALHES):
    """Busca o percurso das provas passadas, uma pagina de resultado por prova.

    O arquivo mensal do corridasbr lista as provas realizadas mas nao o
    percurso. Cada prova e consultada uma unica vez: quem ja foi tentada fica
    marcada, entao a rodada diaria nao repete o trabalho.
    """
    pendentes = [p for p in historico
                 if not p["pills"] and p.get("resultado_id") and not p.get("dist_tentada")]
    if not pendentes:
        return 0, 0

    achadas = 0
    for p in pendentes[:limite]:
        try:
            pills, km = fontes.distancias_do_resultado(p["resultado_id"])
        except Exception:
            continue          # tenta de novo numa proxima rodada
        p["dist_tentada"] = True
        if pills:
            p["pills"] = pills
            p["faixas"] = faixas_de(km)
            p["max_km"] = round(max(km), 1) if km else 0
            p["tags"] = sorted(set(p["tags"]) | set(classificar(p["nome"], km)),
                               key=lambda t: ORDEM_TAGS.index(t) if t in ORDEM_TAGS else 99)
            if len(p["tags"]) > 1 and "Rua" in p["tags"]:
                p["tags"].remove("Rua")
            achadas += 1
        time.sleep(PAUSA_DETALHES)
    return len(pendentes[:limite]), achadas


def normalizar_historico(historico):
    """Repassa cidade e regiao de TODO o historico pela malha do IBGE.

    Provas que sumiram das fontes nunca sao reescritas pelo merge, entao sem
    isto elas ficariam com a grafia e a regiao de versoes antigas do mapa.
    Rodar em cima de um registro ja normalizado nao muda nada.
    """
    ajustadas = 0
    for p in historico:
        if not p.get("cidade"):
            continue
        cidade, regiao, uf = canonizar_cidade(p["cidade"])
        if (cidade, regiao, uf) != (p["cidade"], p.get("regiao"), p.get("uf")):
            p["cidade"], p["regiao"], p["uf"] = cidade, regiao, uf
            ajustadas += 1
    return ajustadas


def coletar():
    """Roda as tres fontes. Uma fonte que falha nao derruba as outras."""
    registros, relatorio = [], []
    for nome, funcao in fontes.TODAS:
        try:
            dados = funcao()
            registros += dados
            relatorio.append(f"  {nome}: {len(dados)} provas")
        except Exception as erro:
            relatorio.append(f"  {nome}: FALHOU ({erro.__class__.__name__}: {erro})")
    return registros, relatorio


def consolidar_historico(historico):
    """Junta registros do historico que sao a mesma prova na mesma data.

    Aparecem quando uma fonte muda a grafia do nome: a versao nova vira um
    registro e a antiga fica parada, parecendo cancelada. Fica o registro
    visto mais recentemente; os creditos, a primeira aparicao e o percurso
    ja conhecido dos outros sao preservados.
    """
    por_data = {}
    for p in historico:
        por_data.setdefault(p["data"], []).append(p)

    resultado, juntadas = [], []
    for data in sorted(por_data):
        grupos = []
        for p in por_data[data]:
            for g in grupos:
                if mesma_prova(p, g[0]):
                    g.append(p)
                    break
            else:
                grupos.append([p])
        for g in grupos:
            if len(g) == 1:
                resultado.append(g[0])
                continue
            g.sort(key=lambda p: (p.get("visto_em") or "", len(p.get("fontes", []))),
                   reverse=True)
            base = g[0]
            for outro in g[1:]:
                base["fontes"] = sorted(set(base.get("fontes", [])) | set(outro.get("fontes", [])))
                if outro.get("primeira_vez") and outro["primeira_vez"] < base.get("primeira_vez", "9"):
                    base["primeira_vez"] = outro["primeira_vez"]
                if not base.get("pills") and outro.get("pills"):
                    base["pills"] = outro["pills"]
                    base["faixas"] = outro.get("faixas", [])
                    base["max_km"] = outro.get("max_km", 0)
                juntadas.append((base, outro))
            resultado.append(base)
    return resultado, juntadas


def casar_no_historico(prova, historico_por_data):
    for antiga in historico_por_data.get(prova["data"], []):
        if mesma_prova(prova, antiga):
            return antiga
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    hoje = datetime.date.today().isoformat()

    print("== fontes ==")
    registros, relatorio = coletar()
    for linha in relatorio:
        print(linha)

    if len(registros) < MINIMO:
        print(f"\nERRO: so {len(registros)} registros no total (minimo {MINIMO}).")
        print("Historico preservado, nada foi gravado.")
        return 1

    atuais = agrupar(registros)
    print(f"\n{len(atuais)} provas distintas depois de fundir as fontes")

    atuais, descartadas = peneirar(atuais)
    if descartadas:
        print(f"descartadas ({len(descartadas)}): fora de {UF_ALVO} ou nao sao corrida")
        for p, motivo in descartadas[:8]:
            print(f"  - {p['data']}  {p['cidade']} - {p['nome'][:44]} [{motivo}]")
        if len(descartadas) > 8:
            print(f"  - ... e mais {len(descartadas) - 8}")
        print(f"restam {len(atuais)} provas")

    historico = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else []
    historico, juntadas = consolidar_historico(historico)
    if juntadas:
        print(f"historico: {len(juntadas)} registros duplicados juntados")
        for base, outro in juntadas[:8]:
            print(f"  = {base['data']}  {base['cidade']} - {base['nome'][:44]}  <-  {outro['nome'][:40]}")
    por_data = {}
    for p in historico:
        por_data.setdefault(p["data"], []).append(p)

    novas = 0
    for prova in atuais:
        antiga = casar_no_historico(prova, por_data)
        if antiga:
            primeira = antiga.get("primeira_vez", hoje)
            # Procedencia e cumulativa: quem ja anunciou a prova continua creditado
            # mesmo depois de tirar o anuncio do ar.
            creditos = sorted(set(antiga.get("fontes", [])) | set(prova["fontes"]))
            # Distancia ja conhecida nunca regride para vazio: o arquivo mensal
            # nao traz percurso, mas o que ja recuperamos continua valendo.
            guardado = None
            if antiga.get("pills") and not prova["pills"]:
                guardado = (antiga["pills"], antiga.get("faixas", []),
                            antiga.get("max_km", 0))
            tentada = antiga.get("dist_tentada")
            antiga.clear()
            antiga.update(prova)
            antiga["fontes"] = creditos
            if guardado:
                antiga["pills"], antiga["faixas"], antiga["max_km"] = guardado
            if tentada:
                antiga["dist_tentada"] = True
            antiga["primeira_vez"] = primeira
            antiga["visto_em"] = hoje
        else:
            prova["primeira_vez"] = hoje
            prova["visto_em"] = hoje
            historico.append(prova)
            por_data.setdefault(prova["data"], []).append(prova)
            novas += 1

    ajustadas = normalizar_historico(historico)
    if ajustadas:
        print(f"malha do IBGE: {ajustadas} registros com cidade ou regiao corrigida")

    tentadas, achadas = completar_distancias(historico)
    if tentadas:
        print(f"percurso: {tentadas} provas consultadas no arquivo, {achadas} preenchidas")

    historico.sort(key=lambda p: (p["data"], sem_acento(p["cidade"]), p["nome"]))
    SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    (AQUI / "coletado_em.txt").write_text(hoje, encoding="utf-8")

    passadas = sum(1 for p in historico if p["data"] < hoje)
    print(f"historico: {len(historico)} provas ({passadas} ja realizadas) | "
          f"{len({p['cidade'] for p in historico})} cidades")
    print(f"novas nesta rodada: {novas}")
    for p in sorted((p for p in historico if p.get("primeira_vez") == hoje),
                    key=lambda p: p["data"])[:15]:
        print(f"  + {p['data']}  {p['cidade']} - {p['nome']}")

    # Prova futura que sumiu de todas as fontes costuma ser cancelamento.
    sumidas = [p for p in historico
               if p["data"] >= hoje and p.get("visto_em") != hoje]
    if sumidas:
        print(f"\nfuturas que nao apareceram hoje ({len(sumidas)}) - "
              "possivel cancelamento, mantidas no historico:")
        for p in sorted(sumidas, key=lambda p: p["data"])[:10]:
            print(f"  ? {p['data']}  {p['cidade']} - {p['nome']} "
                  f"(visto pela ultima vez em {p.get('visto_em', '?')})")

    fora = sorted({p["cidade"] for p in atuais if p["regiao"] == "Outras"})
    if fora:
        print(f"\ncidades sem regiao (adicionar em REGIOES no comum.py): {fora}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
