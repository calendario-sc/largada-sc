#!/usr/bin/env python3
"""Coleta as tres fontes, funde as provas repetidas e acumula em corridas.json.

O arquivo e um HISTORICO: provas ja realizadas continuam nele mesmo depois de
sairem das fontes. Nada e apagado; cada rodada so acrescenta e atualiza.

Uso:  python scrape.py
"""

import datetime
import difflib
import json
import re
import sys
import time
from pathlib import Path

import fontes
from comum import (FAIXAS, NAO_CORRIDA, ORG_ALIAS, UF_ALVO, arrumar_titulo,
                   canonizar_cidade,
                   classificar, esta_excluida, faixas_de, mesma_prova,
                   mesmo_evento_renomeado, palavras_distintivas, parecidos,
                   separar_organizadores, sem_acento)

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "corridas.json"

# Piso de sanidade: abaixo disso a coleta e considerada quebrada e o
# historico fica intacto.
MINIMO = 60

ORDEM_TAGS = ["Treino", "Trail", "Ultra", "Noturna", "Vertical", "Revezamento",
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
        # Endereco da prova em cada fonte: e dele que sai o perfil.
        "ts_id": next((g["ts_id"] for g in grupo if g.get("ts_id")), None),
        "ts_url": next((g["ts_url"] for g in grupo if g.get("ts_url")), None),
        "rr_slug": next((g["rr_slug"] for g in grupo if g.get("rr_slug")), None),
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
        if esta_excluida(p):
            saem.append((p, "retirada a pedido"))
            continue
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
    # Apelidos declarados a mao valem antes de qualquer regra automatica.
    por_apelido = 0
    for p in historico:
        nomes = p.get("organizadores", [])
        trocados = [ORG_ALIAS.get(_chave_org(n), n) for n in nomes]
        if trocados != nomes:
            p["organizadores"] = sorted(set(trocados), key=sem_acento)
            por_apelido += 1

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
    return ajustados + por_apelido


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
    if len(candidatos) != 1:
        return None
    unico = candidatos[0]
    # Data e cidade iguais nao bastam: numa cidade grande ha varias provas no
    # mesmo dia. O nome precisa sustentar que e a mesma.
    return unico if mesmo_evento_renomeado(evento["nome"], unico["nome"],
                                           unico["cidade"]) else None


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
            por_distancia, total, por_genero = fontes.runking_concluintes(
                alvo["empresa"], alvo["slug"])
        except Exception:
            continue
        if total:
            _guardar_resultado(p, por_distancia, total, por_genero, "runking")
            achados += 1
        time.sleep(PAUSA_DETALHES)
    return consultadas, achados


def _guardar_resultado(prova, por_distancia, total, por_genero, fonte):
    """Grava os numeros de uma cronometragem na prova."""
    prova["concluintes"] = por_distancia
    prova["concluintes_total"] = total
    prova["fonte_resultado"] = fonte
    if por_genero:
        prova["concluintes_genero"] = por_genero
        prova["concluintes_f"] = sum(v["f"] for v in por_genero.values())
        prova["concluintes_m"] = sum(v["m"] for v in por_genero.values())
        prova["genero_tentado"] = True


def _sem_resultado(historico, marca):
    """Provas ja realizadas que continuam sem numeros e ainda nao foram
    procuradas nesta cronometragem."""
    hoje = datetime.date.today().isoformat()
    return [p for p in historico
            if p["data"] < hoje and not p.get("concluintes_total")
            and not p.get(marca)]


def completar_supercrono(historico, limite=30):
    """Completa os concluintes pelos arquivos da Super Crono.

    A cronometragem publica a lista inteira de atletas em JSON, entao o
    casamento e barato: uma consulta traz o catalogo, e so as provas que
    batem em data, nome e cidade fazem o resto.
    """
    pendentes = _sem_resultado(historico, "supercrono_tentado")
    if not pendentes:
        return 0, 0
    por_data = {}
    for e in fontes.supercrono_eventos():
        por_data.setdefault(e["data"], []).append(e)
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
        p["supercrono_tentado"] = True
        try:
            por_distancia, total, por_genero = fontes.supercrono_concluintes(alvo["id"])
        except Exception:
            continue
        if total:
            _guardar_resultado(p, por_distancia, total, por_genero, "supercrono")
            achados += 1
        time.sleep(PAUSA_DETALHES)
    return consultadas, achados


def _mesma_praca(cidade, prova):
    """A cidade que a cronometragem informa cabe na da prova?

    Cidade igual nao da para exigir: a Corrida Outubro Rosa sai como
    Florianopolis num lado e Sao Jose no outro, e e a mesma prova. Mas a
    regiao tem de bater, senao duas provas de mesmo nome e mesma data em
    pontas opostas do estado virariam uma so.
    """
    if not cidade:
        return True
    achada, regiao, uf = canonizar_cidade(cidade)
    if uf and uf != UF_ALVO:
        return False
    if not achada or regiao in ("Outras", ""):
        return True
    return achada == prova.get("cidade") or regiao == prova.get("regiao")


def completar_chiprun(historico, limite=8):
    """Completa os concluintes pelas paginas do ChipRun.

    Aqui cada contagem custa varias paginas, entao o limite e baixo de
    proposito: o que faltar hoje entra amanha. O catalogo da API so tem
    nome, entao o candidato e escolhido pelo nome e confirmado pela data da
    pagina do evento -- o nome sozinho casaria edicoes de anos diferentes.
    """
    pendentes = _sem_resultado(historico, "chiprun_tentado")
    if not pendentes:
        return 0, 0
    eventos = fontes.chiprun_eventos()
    if not eventos:
        return 0, 0

    consultadas = achados = 0
    for p in pendentes:
        if consultadas >= limite:
            break
        candidatos = [e for e in eventos if parecidos(e["nome"], p["nome"])]
        for candidato in candidatos[:3]:
            try:
                data, cidade, modalidades = fontes.chiprun_evento(candidato["slug"])
            except Exception:
                continue
            if data != p["data"] or not modalidades:
                continue
            if not _mesma_praca(cidade, p):
                continue
            consultadas += 1
            p["chiprun_tentado"] = True
            try:
                por_distancia, total, por_genero = fontes.chiprun_concluintes(
                    candidato["slug"], modalidades)
            except Exception:
                break
            if total:
                _guardar_resultado(p, por_distancia, total, por_genero, "chiprun")
                achados += 1
            time.sleep(PAUSA_DETALHES)
            break
    return consultadas, achados


def completar_generos(historico, limite=LIMITE_DETALHES):
    """Busca a divisao entre mulheres e homens, prova a prova.

    So a pagina do evento no Open Results traz esse recorte; a listagem por
    estado nao. Cada prova e consultada uma unica vez.
    """
    pendentes = [p for p in historico
                 if p.get("or_slug") and not p.get("genero_tentado")
                 and p.get("concluintes_total")]
    if not pendentes:
        return 0, 0

    achadas = 0
    for p in pendentes[:limite]:
        try:
            por_distancia, total_f, total_m = fontes.openresults_generos(p["or_slug"])
        except Exception:
            continue          # tenta de novo numa proxima rodada
        p["genero_tentado"] = True
        if total_f or total_m:
            p["concluintes_genero"] = por_distancia
            p["concluintes_f"] = total_f
            p["concluintes_m"] = total_m
            achadas += 1
        time.sleep(PAUSA_DETALHES)
    return len(pendentes[:limite]), achadas


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
    retiradas = [p for p in historico if esta_excluida(p)]
    if retiradas:
        historico[:] = [p for p in historico if p not in retiradas]
        print(f"retiradas a pedido: {len(retiradas)}")
        for p in retiradas:
            print(f"  - {p['data']}  {p['cidade']} - {p['nome'][:44]}")

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
                          "fonte_resultado", "runking_tentado",
                          "concluintes_genero", "concluintes_f", "concluintes_m",
                          "genero_tentado", "perfil", "perfil_em")
                         if antiga.get(c)}
            enderecos = {c: antiga[c] for c in
                         ("corrida_id", "resultado_id", "ts_id", "ts_url", "rr_slug")
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
            for campo, valor in enderecos.items():
                antiga.setdefault(campo, valor)
                if not antiga[campo]:
                    antiga[campo] = valor
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

    for nome, funcao in (("supercrono", completar_supercrono),
                         ("chiprun", completar_chiprun)):
        try:
            consultadas, achadas = funcao(historico)
            if consultadas:
                print(f"concluintes ({nome}): {consultadas} provas consultadas, "
                      f"{achadas} preenchidas")
        except Exception as erro:
            print(f"concluintes ({nome}): FALHOU ({erro.__class__.__name__}: {erro})")

    tentadas_g, achadas_g = completar_generos(historico)
    if tentadas_g:
        print(f"genero: {tentadas_g} provas consultadas, {achadas_g} preenchidas")

    tentados, achados = completar_organizadores(historico)
    if tentados:
        print(f"organizador: {tentados} provas consultadas, {achados} preenchidas")
    ajustados = padronizar_organizadores(historico)
    if ajustados:
        print(f"organizador: {ajustados} provas tiveram a grafia padronizada")

    tentadas, achadas = completar_distancias(historico)
    if tentadas:
        print(f"percurso: {tentadas} provas consultadas no arquivo, {achadas} preenchidas")

    series = agrupar_series(historico)
    parciais = marcar_resultados_parciais(historico)
    print(f"series: {series} eventos com uma ou mais edicoes | "
          f"{len(parciais)} resultados parciais marcados")

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


# ------------------------------------------------------- series (as edicoes)

# Folga entre uma edicao e a seguinte. Uma prova anual volta por volta da
# mesma data, mas o dia exato anda: feriado, calendario do organizador, chuva.
# Quando os dois nomes sao praticamente o mesmo, a data pode andar mais: a
# Trilha das Bruxas saiu de fim de julho para inicio de junho e continua a
# mesma prova. Com nome so parecido, a janela fecha -- e ela que separa a
# "Jurere Night Run" da "One Day Run - Jurere", a 49 dias de distancia.
JANELA_SERIE = 35
JANELA_MESMO_NOME = 75
# Duas edicoes do mesmo ano so convivem numa serie se forem o mesmo fim de
# semana -- evento de dois dias. Mais que isso sao etapas de um circuito ou
# provas diferentes que o nome generico aproximou.
JANELA_MESMO_ANO = 20

MES_DO_ANO = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _dia_do_ano(data):
    ano, mes, dia = (int(x) for x in data.split("-"))
    return datetime.date(ano, mes, dia).timetuple().tm_yday


def _mesma_epoca(a, b, janela=JANELA_SERIE):
    """As duas edicoes caem na mesma epoca do ano? (dezembro e janeiro sim)"""
    d = abs(_dia_do_ano(a["data"]) - _dia_do_ano(b["data"]))
    return min(d, 365 - d) <= janela


def _so_letras(s):
    return re.sub(r"[^a-z]", "", sem_acento(s))


# Nome parecido basta para juntar duas edicoes -- menos quando o nome inteiro
# e feito de palavras que toda prova tem. "Meia Maratona Internacional de
# Florianopolis" e "Meia e Maratona Cidade de Florianopolis" se parecem em 81%
# das letras e sao provas diferentes, com um mes de distancia.
PARECIDO = 0.80
PARECIDO_SO_GENERICO = 0.92


def _quase_o_mesmo_nome(a, b):
    da = palavras_distintivas(a["nome"], a.get("cidade", ""))
    db = palavras_distintivas(b["nome"], b.get("cidade", ""))
    # Cada uma tem a sua palavra, e nao e a mesma: "Corrida da Virada
    # Floripa" e "Corrida da Folia Floripa" se parecem em 93% das letras
    # justamente porque so diferem no que as distingue.
    if da and db and not (da & db):
        return False
    ratio = difflib.SequenceMatcher(None, _so_letras(a["nome"]),
                                    _so_letras(b["nome"])).ratio()
    return ratio >= (PARECIDO_SO_GENERICO if not (da or db) else PARECIDO)


def _evidencia_de_serie(a, b):
    """O nome sustenta que sao duas edicoes do mesmo evento?

    Mais exigente que o casamento entre fontes: aqui uma ligacao errada
    contamina a serie inteira, porque as edicoes se ligam em cadeia.
    Uma palavra em comum nao basta -- "Sicredi Lagoa Run" e "Trail Run
    Praias - Lagoa do Peri" dividem "lagoa" e nao tem nada a ver.
    """
    if _quase_o_mesmo_nome(a, b):
        return True
    da = palavras_distintivas(a["nome"], a.get("cidade", ""))
    db = palavras_distintivas(b["nome"], b.get("cidade", ""))
    comuns = da & db
    if not comuns:
        return False
    if len(comuns) / len(da | db) >= 0.5:
        return True
    # Uma edicao ganhou patrocinador no nome ("Jurere Night Run" virou
    # "Jurere Night Run - Hard Rock Cafe"): so vale se a mesma empresa
    # assina as duas.
    if da <= db or db <= da:
        oa = set(a.get("organizadores") or [])
        ob = set(b.get("organizadores") or [])
        return bool(oa & ob)
    return False


def mesma_serie(a, b):
    """Duas edicoes da mesma prova, em anos diferentes?

    Nome parecido nao basta numa cidade grande: "Jurere Night Run" e "Sunset
    Jurere - Corrida & Vinho" dividem a palavra que identifica o lugar. A
    epoca do ano desempata -- e duas provas do MESMO ano nunca sao edicoes
    uma da outra.
    """
    if a["ano"] == b["ano"] or a.get("cidade") != b.get("cidade"):
        return False
    janela = JANELA_MESMO_NOME if _quase_o_mesmo_nome(a, b) else JANELA_SERIE
    return _mesma_epoca(a, b, janela) and _evidencia_de_serie(a, b)


ANO_NO_NOME = re.compile(r"\b(?:19|20)\d{2}\b")
ABERTURA = re.compile(r"^\s*(?:\d{1,3}\s*[\u00ba\u00aa\u00b0]?|[IVXLivxl]{1,6})\s+")


def nome_da_serie(nome):
    """O nome da prova sem o que muda a cada edicao: o ano e o ordinal."""
    limpo = ABERTURA.sub("", ANO_NO_NOME.sub(" ", nome))
    # Evento de dois dias: o rotulo da serie nao precisa dizer qual deles.
    limpo = re.sub(r"[-–|]?\s*\d{1,2}\s*[ºª°oa]?\s*dia\b",
                   "", limpo, flags=re.I)
    limpo = re.sub(r"\s{2,}", " ", limpo).strip(" -\u2013|\u00b7")
    return limpo or nome


def _pode_juntar(grupo_a, grupo_b):
    """A juncao criaria duas edicoes do mesmo ano em epocas diferentes?

    E o sinal mais confiavel de fusao errada: a Meia Maratona Internacional
    de Florianopolis (maio) tinha sido juntada com a Meia e Maratona Cidade
    de Florianopolis (junho), e o painel somava as duas no mesmo ano.
    """
    for a in grupo_a:
        for b in grupo_b:
            if a["ano"] != b["ano"]:
                continue
            d = abs(_dia_do_ano(a["data"]) - _dia_do_ano(b["data"]))
            if min(d, 365 - d) > JANELA_MESMO_ANO:
                return False
    return True


# Um resultado que fica muito abaixo das outras edicoes da mesma prova nao
# conta uma prova pequena: conta um resultado que subiu pela metade no
# portal. A Corrida Mulheres na Pista de Blumenau tem 727 e 1.120 concluintes
# em 2024 e 2025, e "60" em 2026 -- 30 em cada distancia, numero redondo de
# upload interrompido.
FRACAO_PARCIAL = 0.15
PISO_PARCIAL = 100


def marcar_resultados_parciais(historico):
    """Marca o resultado que destoa demais das outras edicoes da prova.

    O numero continua a vista na prova, com a ressalva; o que ele deixa de
    fazer e entrar nos totais e nos rankings, onde faria a prova parecer ter
    encolhido 95%.
    """
    series = {}
    for p in historico:
        if p.get("serie") and p.get("concluintes_total"):
            series.setdefault(p["serie"], []).append(p)

    marcadas = []
    for provas in series.values():
        if len(provas) < 2:
            continue
        for p in provas:
            outras = [q for q in provas if q is not p]
            if _parece_parcial(p, outras):
                p["resultado_parcial"] = True
                marcadas.append(p)
            else:
                p.pop("resultado_parcial", None)
    return marcadas


def _mediana(valores):
    ordenados = sorted(valores)
    return ordenados[len(ordenados) // 2]


def _parece_parcial(prova, outras):
    """O resultado desta edicao destoa das outras a ponto de nao ser dela?"""
    minhas = prova.get("concluintes") or {}
    # A comparacao e por distancia. Uma edicao que so teve a maratona nao e
    # resultado pela metade: e um evento que so depois ganhou 5km e 10km --
    # a Maratona de Tubarao foi de 62 para 813 assim, com a maratona parada
    # em torno de 100.
    comuns = []
    for km, quantos in minhas.items():
        refs = [o["concluintes"][km] for o in outras
                if (o.get("concluintes") or {}).get(km)]
        if refs:
            comuns.append((quantos, _mediana(refs)))
    if comuns:
        referencia = max(r for _, r in comuns)
        return (referencia >= PISO_PARCIAL
                and all(q < r * FRACAO_PARCIAL for q, r in comuns))
    # Sem nenhuma distancia em comum, so resta o total.
    referencia = _mediana([o["concluintes_total"] for o in outras])
    return (referencia >= PISO_PARCIAL
            and prova["concluintes_total"] < referencia * FRACAO_PARCIAL)


# Evento que se espalha por mais de um dia: "1o Dia", "2o Dia Noturno",
# "- Sabado". A Maratona de Jurere tem duas entradas no calendario (cada dia
# tem suas distancias), mas e uma prova so, e assim deve ser contada.
MARCA_DE_DIA = re.compile(r"\b\d{1,2}\s*[ºª°oa]?\s*dia\b|[-–|]\s*(?:s[aá]bado|domingo|sexta(?:-feira)?)\b",
                          re.I)
PERIODO_DO_DIA = re.compile(r"\b(?:tarde|manh[aã]|noite|noturn[oa]|matinal)\b", re.I)
JANELA_EVENTO = 3        # dias entre um dia e o seguinte do mesmo evento


def _nome_sem_dia(nome):
    """O nome da prova sem o que diz qual dia do evento e."""
    limpo = PERIODO_DO_DIA.sub(" ", MARCA_DE_DIA.sub(" ", nome_da_serie(nome)))
    return _so_letras(limpo)


def _mesmo_evento(a, b):
    """Dois dias de um mesmo evento? Mesma cidade e ano, datas coladas, ao
    menos um dos nomes se anuncia como um dia, e o resto do nome bate."""
    if a["ano"] != b["ano"] or a.get("cidade") != b.get("cidade"):
        return False
    gap = abs((datetime.date.fromisoformat(a["data"]) - datetime.date.fromisoformat(b["data"])).days)
    if not 0 < gap <= JANELA_EVENTO:
        return False
    if not (MARCA_DE_DIA.search(a["nome"]) or MARCA_DE_DIA.search(b["nome"])):
        return False
    na, nb = _nome_sem_dia(a["nome"]), _nome_sem_dia(b["nome"])
    if na == nb:
        return True
    menor, maior = sorted((na, nb), key=len)
    if len(menor) >= 8 and menor in maior:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85


def agrupar_eventos(historico):
    """Marca os dias de um mesmo evento com a chave "evento".

    A chave e a serie mais o ano quando os dias ja estao na mesma serie;
    senao sai da cidade, do nome sem a marca de dia e do ano. Cada dia
    guarda tambem sua posicao (evento_dia) e o total (evento_dias).
    """
    for p in historico:
        for campo in ("evento", "evento_dia", "evento_dias"):
            p.pop(campo, None)

    por_praca = {}
    for p in historico:
        if MARCA_DE_DIA.search(p["nome"]):
            por_praca.setdefault((p.get("cidade", ""), p["ano"]), None)
    candidatos = {}
    for p in historico:
        chave = (p.get("cidade", ""), p["ano"])
        if chave in por_praca:
            candidatos.setdefault(chave, []).append(p)

    eventos = 0
    for provas in candidatos.values():
        dono = list(range(len(provas)))

        def raiz(i):
            while dono[i] != i:
                dono[i] = dono[dono[i]]
                i = dono[i]
            return i

        for i in range(len(provas)):
            for j in range(i + 1, len(provas)):
                if raiz(i) != raiz(j) and _mesmo_evento(provas[i], provas[j]):
                    dono[raiz(j)] = raiz(i)
        grupos = {}
        for i, p in enumerate(provas):
            grupos.setdefault(raiz(i), []).append(p)
        for grupo in grupos.values():
            if len(grupo) < 2:
                continue
            grupo.sort(key=lambda p: p["data"])
            series = {p.get("serie") for p in grupo}
            if len(series) == 1 and grupo[0].get("serie"):
                chave = f"{grupo[0]['serie']}-{grupo[0]['ano']}"
            else:
                base = sem_acento(f"{grupo[0].get('cidade','')} {_nome_sem_dia(grupo[0]['nome'])} {grupo[0]['ano']}")
                chave = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
            for k, p in enumerate(grupo, 1):
                p["evento"] = chave
                p["evento_dia"] = k
                p["evento_dias"] = len(grupo)
            eventos += 1
    return eventos


def agrupar_series(historico):
    """Marca cada prova com a serie a que pertence (as edicoes de um evento).

    A serie e o que permite mostrar a evolucao ano a ano. O identificador sai
    do nome da edicao mais recente, para a serie nao mudar de rotulo quando
    uma edicao antiga e corrigida.
    """
    por_cidade = {}
    for p in historico:
        por_cidade.setdefault(p.get("cidade", ""), []).append(p)

    series = 0
    for provas in por_cidade.values():
        dono = list(range(len(provas)))

        def raiz(i):
            while dono[i] != i:
                dono[i] = dono[dono[i]]
                i = dono[i]
            return i

        membros = {i: [p] for i, p in enumerate(provas)}
        for i in range(len(provas)):
            for j in range(i + 1, len(provas)):
                ri, rj = raiz(i), raiz(j)
                if ri == rj or not mesma_serie(provas[i], provas[j]):
                    continue
                if not _pode_juntar(membros[ri], membros[rj]):
                    continue
                dono[rj] = ri
                membros[ri] += membros.pop(rj)

        grupos = {}
        for i, p in enumerate(provas):
            grupos.setdefault(raiz(i), []).append(p)

        # Mesma cidade, mesmo nome, epocas diferentes: a Black Trunk Race
        # acontece duas vezes por ano em Florianopolis. Sao series distintas
        # e precisam de identificadores distintos, senao o painel soma as
        # duas. A colisao e testada no identificador ja normalizado, porque
        # "Corrida do Fogo  CBM" e "Corrida do Fogo - CBM" viram o mesmo.
        def rotulo_e_chave(grupo, mes=False):
            recente = max(grupo, key=lambda p: p["data"])
            rotulo = nome_da_serie(recente["nome"])
            if mes:
                rotulo += f" ({MES_DO_ANO[recente['mes'] - 1]})"
            chave = sem_acento(f"{recente.get('cidade','')} {rotulo}")
            return rotulo, re.sub(r"[^a-z0-9]+", "-", chave).strip("-")

        chaves = [rotulo_e_chave(g)[1] for g in grupos.values()]
        repetidas = {c for c in chaves if chaves.count(c) > 1}

        usadas = set()
        for grupo in grupos.values():
            rotulo, chave = rotulo_e_chave(grupo)
            if chave in repetidas:
                rotulo, chave = rotulo_e_chave(grupo, mes=True)
            # Duas series no mesmo mes e com o mesmo nome: sobrou o numero.
            base, conta = chave, 2
            while chave in usadas:
                chave = f"{base}-{conta}"
                conta += 1
            usadas.add(chave)
            for p in grupo:
                p["serie"] = chave
                p["serie_nome"] = rotulo
            series += 1
    agrupar_eventos(historico)
    return series
