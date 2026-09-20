#!/usr/bin/env python3
"""Coleta as tres fontes, funde as provas repetidas e acumula em corridas.json.

O arquivo e um HISTORICO: provas ja realizadas continuam nele mesmo depois de
sairem das fontes. Nada e apagado; cada rodada so acrescenta e atualiza.

Uso:  python scrape.py
"""

import datetime
import json
import re
import sys
import time
from pathlib import Path

import fontes
from comum import (FAIXAS, NAO_CORRIDA, UF_ALVO, arrumar_titulo, canonizar_cidade,
                   classificar, faixas_de, mesma_prova, parecidos,
                   separar_organizadores, sem_acento)

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
        "corrida_id": next((g["corrida_id"] for g in grupo if g.get("corrida_id")), None),
        # Co-organizacao e comum: vale a uniao do que cada fonte informa.
        "organizadores": sorted({o for g in grupo for o in g.get("organizadores", [])},
                                key=sem_acento),
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


def completar_organizadores(historico, limite=LIMITE_DETALHES):
    """Busca o organizador prova a prova, na pagina do corridasbr.

    Nenhuma listagem traz esse campo: so a pagina de cada prova (futura) ou a
    do resultado (passada). Cada prova e consultada uma unica vez.
    """
    pendentes = [p for p in historico
                 if not p.get("organizadores")
                 and (p.get("corrida_id") or p.get("resultado_id"))
                 and not p.get("org_tentado")]
    if not pendentes:
        return 0, 0

    achados = 0
    for p in pendentes[:limite]:
        try:
            texto = fontes.organizador_da_prova(p.get("corrida_id"), p.get("resultado_id"))
        except Exception:
            continue          # tenta de novo numa proxima rodada
        p["org_tentado"] = True
        nomes = separar_organizadores(texto)
        if nomes:
            p["organizadores"] = nomes
            achados += 1
        time.sleep(PAUSA_DETALHES)
    return len(pendentes[:limite]), achados


def _chave_org(nome):
    return " ".join(sem_acento(nome).replace(".", " ").split()).strip(" -–:,")


def _prefixo_de(curto, longo):
    """'acorsj' e prefixo de 'acorsj - associacao...' (no limite de palavra)."""
    return longo.startswith(curto) and (len(longo) == len(curto)
                                        or longo[len(curto)] in " -–:,")


def _parecem_mesma_coisa(a, b):
    """Dois complementos de um mesmo tronco dizem a mesma coisa?

    'associacao de corredores...' x 'assoc dos corredores...' -> sim, e a mesma
    entidade escrita de dois jeitos (ou truncada pela fonte).
    'de guaramirim' x 'de pinhalzinho' -> nao, sao unidades diferentes.
    """
    ta = {w for w in a.split() if len(w) > 2}
    tb = {w for w in b.split() if len(w) > 2}
    if not ta or not tb:
        return True
    if _prefixo_de(a, b) or _prefixo_de(b, a):
        return True
    # "assoc" e "associacao" sao a mesma palavra abreviada.
    def casa(x, y):
        return x == y or (min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x)))
    iguais = sum(1 for x in ta if any(casa(x, y) for y in tb))
    return iguais / (len(ta) + len(tb) - iguais) >= 0.5


def _lugar(resto):
    """'de salete' -> True. Complemento que e municipio indica outra unidade:
    a Rede Feminina de Guaramirim nao e a de Pinhalzinho."""
    casa = re.match(r"^(?:de|do|da|em)\s+(.+)$", resto or "")
    if not casa:
        return False
    _, regiao, _ = canonizar_cidade(casa.group(1))
    return regiao != "Outras"


# Onde uma prova co-organizada pode estar juntando duas empresas.
SEPARADOR_DUPLA = re.compile(r"(\s+e\s+|\s*&\s*|\s*\+\s*)")


def padronizar_organizadores(historico):
    """Uma empresa so, escrita de varios jeitos, vira um nome so.

    Tres decisoes que so dao para tomar olhando o conjunto inteiro:

    1. Dividir "ACORSJ e TM4" em duas empresas, mas nao "Thome & Santos".
       A divisao e testada em cada separador e so vale quando um lado e uma
       empresa que aparece sozinha em outras provas e o outro tambem aparece
       ou ao menos tem cara de nome de empresa (duas palavras ou mais).
    2. Juntar variantes da mesma empresa, inclusive as que o corridasbr corta
       em 50 caracteres. Vence a grafia mais usada.
    3. NAO juntar nomes que apenas compartilham um tronco generico:
       "Rede Feminina ... de Guaramirim" e "... de Pinhalzinho" sao duas
       entidades, e "Prefeitura Municipal" sozinha nao representa nenhuma.
    """
    contagem = {}
    for p in historico:
        for nome in p.get("organizadores", []):
            contagem[nome] = contagem.get(nome, 0) + 1
    if not contagem:
        return 0

    conhecidos = {_chave_org(n): n for n in contagem}

    def resolve(parte, exceto=None):
        """Devolve o nome oficial se a parte for uma empresa ja conhecida.

        Nome comum exige correspondencia exata: "Saude" nao pode casar com
        "Saude em Movimento" so por comecar igual, senao "SESI +Saude" viraria
        duas empresas. Sigla em caixa alta pode casar por prefixo.
        """
        chave = _chave_org(parte)
        if not chave or len(chave) < 2:
            return None
        achado = conhecidos.get(chave)
        if achado and achado != exceto:
            return achado
        candidatos = [n for k, n in conhecidos.items()
                      if n != exceto and (_prefixo_de(chave, k)
                                          if re.fullmatch(r"[A-Z0-9]{2,}", parte.strip())
                                          else _prefixo_de(k, chave))]
        return max(candidatos, key=lambda n: (contagem[n], len(n))) if candidatos else None

    def plausivel(parte):
        """Nao conhecida, mas com cara de nome de empresa."""
        limpo = " ".join(parte.split()).strip(" -–:,.")
        return limpo if len(limpo.split()) >= 2 and len(limpo) >= 6 else None

    def dividir(nome, original, profundidade=0):
        """Tenta cada separador; so divide se a divisao se sustentar."""
        if profundidade > 3 or not SEPARADOR_DUPLA.search(nome):
            return [nome]
        pedacos = SEPARADOR_DUPLA.split(nome)
        for i in range(1, len(pedacos), 2):
            esquerda = "".join(pedacos[:i]).strip()
            direita = "".join(pedacos[i + 1:]).strip()
            if not esquerda or not direita:
                continue
            a, b = resolve(esquerda, original), resolve(direita, original)
            if a and (b or plausivel(direita)):
                return (dividir(a, original, profundidade + 1)
                        + dividir(b or plausivel(direita), original, profundidade + 1))
            if b and plausivel(esquerda):
                return (dividir(plausivel(esquerda), original, profundidade + 1)
                        + dividir(b, original, profundidade + 1))
        return [nome]

    divisao = {n: dividir(n, n) for n in contagem if SEPARADOR_DUPLA.search(n)}

    # --- variantes: agrupa por tronco, sem misturar entidades diferentes
    nomes = sorted(contagem, key=lambda n: (len(_chave_org(n)), n))
    grupos = {}
    for nome in nomes:
        chave = _chave_org(nome)
        alvo = None
        for raiz, membros in grupos.items():
            if not _prefixo_de(raiz, chave):
                continue
            resto = chave[len(raiz):].lstrip(" -–:,")
            if re.match(r"(e\s|&|\+)", resto):
                continue      # emenda outra empresa: nao e variante
            if _lugar(resto):
                continue      # "de Salete", "de Guaramirim": outra entidade
            outros = [_chave_org(m)[len(raiz):].lstrip(" -–:,") for m in membros
                      if _chave_org(m) != raiz]
            # Basta parecer com UM dos que ja estao no grupo: as variantes
            # truncadas nem sempre se parecem entre si duas a duas.
            if not outros or any(_parecem_mesma_coisa(resto, o) for o in outros):
                alvo = raiz
                break
        grupos.setdefault(alvo or chave, []).append(nome)

    troca = {}
    for membros in grupos.values():
        vence = max(membros, key=lambda n: (contagem.get(n, 0), len(n)))
        for n in membros:
            troca[n] = vence

    ajustados = 0
    for p in historico:
        atuais = p.get("organizadores", [])
        finais = []
        for nome in atuais:
            for parte in divisao.get(nome, [nome]):
                finais.append(troca.get(parte, parte))
        finais = sorted(set(finais), key=sem_acento)
        if finais != atuais:
            p["organizadores"] = finais
            ajustados += 1
    return ajustados


def vincular_concluintes(historico, desde=None):
    """Anexa a cada prova realizada quantos atletas concluiram, por distancia.

    O Open Results e portal de resultados, nao calendario: nunca cria prova
    aqui, so completa as que ja existem. Casamento por data + nome + cidade,
    a mesma regra usada para fundir as fontes.
    """
    if desde is None:
        # Na rodada diaria so interessam as provas recentes; numeros antigos
        # nao mudam. O historico completo vem pelo importar_concluintes.py.
        desde = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()

    eventos = fontes.openresults(desde=desde)
    por_data = {}
    for p in historico:
        por_data.setdefault(p["data"], []).append(p)

    hoje = datetime.date.today().isoformat()
    ligados, atualizados, criados = 0, 0, 0
    for e in eventos:
        if not e["concluintes_total"]:
            continue          # prova sem resultado publicado ainda
        alvo = next((p for p in por_data.get(e["data"], []) if mesma_prova(e, p)), None)

        if alvo is None:
            # Prova que mudou de nome: o calendario ainda usa o antigo
            # ("Sunset Jurere - Corrida & Vinho") e o portal ja usa o novo
            # ("Jurere Wine Run"). Mesma data, mesma cidade e um unico
            # candidato sem resultado e a mesma prova.
            alvo = _candidato_unico(por_data.get(e["data"], []), e)
            if alvo is not None:
                _guardar_outro_nome(alvo, e["nome"])

        if alvo is None:
            # Prova que ja aconteceu e nenhuma fonte de calendario listou.
            # O portal de resultados e a unica prova de que ela existiu.
            # Respeita o corte: criar prova fora da janela daria um ano com
            # cobertura pela metade, pior que nenhum para comparar.
            if (e["data"] >= hoje or e["data"] < desde
                    or e["regiao"] in ("Outras", "Fora de SC")):
                continue
            alvo = _prova_do_openresults(e)
            historico.append(alvo)
            por_data.setdefault(e["data"], []).append(alvo)
            criados += 1

        ligados += 1
        if alvo.get("concluintes_total") != e["concluintes_total"]:
            atualizados += 1
        alvo["concluintes"] = e["concluintes"]
        alvo["concluintes_total"] = e["concluintes_total"]
        alvo["or_slug"] = e["slug"]
    return len(eventos), ligados, atualizados, criados


def _candidato_unico(provas_do_dia, evento):
    """A unica prova da mesma cidade e data que ainda nao tem resultado."""
    candidatos = [p for p in provas_do_dia
                  if p.get("cidade") == evento["cidade"]
                  and not p.get("concluintes_total")
                  and p.get("fontes") != ["openresults"]]
    return candidatos[0] if len(candidatos) == 1 else None


def _guardar_outro_nome(prova, nome):
    """Registra o nome alternativo, para a prova ser achada pelos dois."""
    if not nome or parecidos(nome, prova["nome"]):
        return
    outros = prova.get("outros_nomes") or []
    if nome not in outros:
        outros.append(nome)
        prova["outros_nomes"] = outros


def unificar_openresults(historico):
    """Junta prova criada pelo portal com a do calendario que mudou de nome.

    Necessario porque as primeiras rodadas criaram registros separados antes
    de existir a regra de candidato unico. Fica o registro do calendario, com
    os numeros do portal e o nome novo guardado em outros_nomes.
    """
    por_data = {}
    for p in historico:
        por_data.setdefault(p["data"], []).append(p)

    juntadas = []
    for p in list(historico):
        if p.get("fontes") != ["openresults"]:
            continue
        alvo = _candidato_unico([q for q in por_data[p["data"]] if q is not p], p)
        if alvo is None:
            continue
        alvo["concluintes"] = p.get("concluintes", {})
        alvo["concluintes_total"] = p.get("concluintes_total", 0)
        if p.get("or_slug"):
            alvo["or_slug"] = p["or_slug"]
        if not alvo.get("pills") and p.get("pills"):
            alvo["pills"] = p["pills"]
            alvo["faixas"] = p.get("faixas", [])
            alvo["max_km"] = p.get("max_km", 0)
        _guardar_outro_nome(alvo, p["nome"])
        historico.remove(p)
        por_data[p["data"]].remove(p)
        juntadas.append((alvo, p))
    return juntadas


def _prova_do_openresults(e):
    """Monta o registro de uma prova que so existe no portal de resultados.

    As distancias saem das proprias modalidades com resultado; organizador
    fica em branco, porque o portal nao informa.
    """
    hoje = datetime.date.today().isoformat()
    km = sorted((float(d) for d in e["concluintes"]), reverse=True)
    ano, mes, dia = (int(x) for x in e["data"].split("-"))
    return {
        "data": e["data"], "dia": dia, "mes": mes, "ano": ano,
        "cidade": e["cidade"], "regiao": e["regiao"], "uf": e["uf"],
        "nome": arrumar_titulo(e["nome"]),
        "pills": [f"{v:g}km" for v in km], "faixas": faixas_de(km),
        "max_km": round(max(km), 1) if km else 0,
        "tags": classificar(e["nome"], km),
        "fontes": ["openresults"],
        "organizadores": [],
        "primeira_vez": hoje, "visto_em": hoje,
    }


def completar_runking(historico, limite=60):
    """Completa os concluintes pelas paginas do RunKing (Chronomax).

    O Open Results nao cobre tudo. Onde ele falta, a cronometragem publica os
    numeros no proprio site. So consulta prova que ainda esta sem resultado, e
    so marca como tentada quando houve consulta de verdade -- assim, incluir
    uma empresa nova em fontes.RK_EMPRESAS faz as pendentes serem revistas.
    """
    hoje = datetime.date.today().isoformat()
    pendentes = [p for p in historico
                 if p["data"] < hoje and not p.get("concluintes_total")
                 and not p.get("runking_tentado")]
    if not pendentes:
        return 0, 0

    por_data = {}
    for empresa in fontes.RK_EMPRESAS:
        try:
            for e in fontes.runking_eventos(empresa):
                por_data.setdefault(e["data"], []).append(e)
        except Exception as erro:
            print(f"  runking/{empresa}: FALHOU ({erro.__class__.__name__}: {erro})")
    if not por_data:
        return 0, 0

    consultadas = achados = 0
    for p in pendentes:
        if consultadas >= limite:
            break
        alvo = next((e for e in por_data.get(p["data"], []) if mesma_prova(e, p)), None)
        if not alvo:
            continue          # sem candidato: nao marca, para rever depois
        consultadas += 1
        p["runking_tentado"] = True
        try:
            por_distancia, total = fontes.runking_concluintes(alvo["empresa"], alvo["slug"])
        except Exception:
            continue
        if total:
            p["concluintes"] = por_distancia
            p["concluintes_total"] = total
            p["fonte_resultado"] = "runking"
            achados += 1
        time.sleep(PAUSA_DETALHES)
    return consultadas, achados


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
    renomeadas = unificar_openresults(historico)
    if renomeadas:
        print(f"provas que mudaram de nome: {len(renomeadas)} registros unificados")
        for alvo, outro in renomeadas[:6]:
            print(f"  = {alvo['data']}  {alvo['cidade']} - {alvo['nome'][:38]}  <-  {outro['nome'][:38]}")

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
            org_tentado = antiga.get("org_tentado")
            organizadores = antiga.get("organizadores") or []
            resultado = {c: antiga[c] for c in
                         ("concluintes", "concluintes_total", "or_slug",
                          "fonte_resultado", "runking_tentado")
                         if antiga.get(c)}
            antiga.clear()
            antiga.update(prova)
            antiga["fontes"] = creditos
            if guardado:
                antiga["pills"], antiga["faixas"], antiga["max_km"] = guardado
            if tentada:
                antiga["dist_tentada"] = True
            if org_tentado:
                antiga["org_tentado"] = True
            if organizadores and not antiga.get("organizadores"):
                antiga["organizadores"] = organizadores
            antiga.update(resultado)
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

    try:
        vistos, ligados, atualizados, criados = vincular_concluintes(historico)
        print(f"concluintes: {vistos} provas no Open Results, {ligados} casadas, "
              f"{atualizados} com numero novo, {criados} provas criadas")
    except Exception as erro:
        print(f"concluintes: FALHOU ({erro.__class__.__name__}: {erro})")

    try:
        consultadas, achadas_rk = completar_runking(historico)
        if consultadas:
            print(f"concluintes (runking): {consultadas} provas consultadas, "
                  f"{achadas_rk} preenchidas")
    except Exception as erro:
        print(f"concluintes (runking): FALHOU ({erro.__class__.__name__}: {erro})")

    tentados, achados = completar_organizadores(historico)
    if tentados:
        print(f"organizador: {tentados} provas consultadas, {achados} preenchidas")
    ajustados = padronizar_organizadores(historico)
    if ajustados:
        print(f"organizador: {ajustados} provas tiveram a grafia padronizada")

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
