#!/usr/bin/env python3
"""Assessorias e equipes: quantos alunos cada uma leva a cada prova.

Le o campo "Equipe/Assessoria" das classificacoes (atletas/provas/*.json),
limpa o que o corredor digitou e junta as grafias da mesma equipe. Escreve,
so no repositorio privado do BI (../cupons-bi/assessorias.json):

  {"provas": [or_slug, ...], "equipes": [[nome, [prova, alunos, prova, alunos, ...]], ...]}

A pagina de BI cruza o or_slug com as provas do filtro: o ranking segue o
ano, a cidade e a regiao escolhidos.

Uso:  python assessorias.py
"""

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import consertar_mojibake, sem_acento  # noqa: E402

AQUI = Path(__file__).resolve().parent
PROVAS = AQUI / "atletas" / "provas"
BI_DIR = AQUI.parent / "cupons-bi"
SAIDA = BI_DIR / "assessorias.json"

# O que o corredor escreve quando nao tem equipe.
SEM_EQUIPE = re.compile(r"""^(
    avuls[oa]s?|individual|particular|independente|autonom[oa]|sozinh[oa]|livre|solo|nenhum[a]?|
    sem(\s.*)?|nao(\s.*)?|n\s?a|na|nt|nd|x+|geral|equipe(\s(geral|livre|unica))?|assessoria|team|
    eu(\s.*)?|mim(\s.*)?|so\s?eu|ninguem|corredor(a)?|atleta|runner|pessoal|propria|proprio|
    familia|amigos|particular|outr[oa]s?|teste|a\s?definir|nenhuma\s.*|
    \W*|\d*|[a-z]
)$""", re.X)
# Palavras de enfeite que nao mudam a equipe: "Equipe Loucos na Pista" e
# "Loucos na Pista Assessoria" sao a mesma.
ENFEITE_INICIO = re.compile(r"^(equipe|assessoria esportiva|assessoria|grupo|team)\s+")
ENFEITE_FIM = re.compile(r"\s+(equipe|assessoria esportiva|assessoria|team|sc)$")
# Chaves que aparecem no campo mas nao sao equipe: ticketeira, "site",
# palavra solta.
NAO_E_EQUIPE = {"sympla", "ticketsports", "site", "instituto", "extrasemkit", "runners", "runner",
                "corredores", "corredor", "running", "run", "instagram", "facebook", "whatsapp",
                "google", "indicacao", "internet", "amigo", "amigos", "outros", "outro", "kit"}
SUFIXO = ("assessoriaesportiva", "assessoria", "equipe", "team")
# Grafias que a limpeza nao junta sozinha: chave -> chave.
MESMA_EQUIPE = {
    "ojaniosantos": "ojanio",
}
MINIMO_ALUNOS = 5      # equipe com menos que isso no total fica de fora


def _cidades():
    """Nomes de municipios (qualquer UF): corredor que escreve a cidade no
    campo da equipe nao tem equipe."""
    dados = json.loads((AQUI / "municipios.json").read_text(encoding="utf-8"))
    return {re.sub(r"[^a-z0-9]", "", k) for uf in dados.values() for k in uf}


def limpar(texto):
    """Texto digitado -> (chave, texto limpo) ou None quando nao e equipe."""
    t = consertar_mojibake(texto or "").replace("�", "?")
    t = sem_acento(t)
    t = re.sub(r"[^a-z0-9?&]+", " ", t).strip()
    # "acessoria", "assesoria", "acesoria": tudo e assessoria.
    t = re.sub(r"a[cs]{1,2}es{1,2}oria", "assessoria", t)
    if SEM_EQUIPE.match(t):
        return None
    base = t
    for _ in range(2):
        base = ENFEITE_INICIO.sub("", base)
        base = ENFEITE_FIM.sub("", base)
    base = base.strip() or t
    # Mesmas palavras em outra ordem ("loucas e loucos" / "loucos e loucas")
    # sao a mesma equipe: a chave junta as palavras em ordem alfabetica.
    chave = "".join(sorted(base.split()))
    for suf in SUFIXO:
        if chave.endswith(suf) and len(chave) - len(suf) >= 3:
            chave = chave[:-len(suf)]
            break
    if len(chave.replace("?", "")) < 3 or chave in NAO_E_EQUIPE:
        return None
    return chave, t


def _juntar_interrogacao(chaves):
    """"esquadr?oadventure" (acento perdido na fonte) vira a chave limpa que
    casa, quando so uma casa."""
    limpas = [c for c in chaves if "?" not in c]
    por_tamanho = collections.defaultdict(list)
    for c in limpas:
        por_tamanho[len(c)].append(c)
    troca = {}
    for c in chaves:
        if "?" not in c:
            continue
        rx = re.compile("^" + re.escape(c).replace(r"\?", "[a-z]{1,2}") + "$")
        casam = [x for n in (len(c), len(c) + 1) for x in por_tamanho[n] if rx.match(x)]
        if len(casam) == 1:
            troca[c] = casam[0]
    return troca


def montar(registrar=print):
    cidades = _cidades()
    # chave -> {or_slug: set(atletas)} e chave -> Counter(grafias)
    alunos = collections.defaultdict(lambda: collections.defaultdict(set))
    grafias = collections.defaultdict(collections.Counter)
    for arquivo in sorted(PROVAS.glob("*.json")):
        d = json.loads(arquivo.read_text(encoding="utf-8"))
        if d.get("erro") or not d.get("linhas"):
            continue
        for slug, _nome, _sexo, _mod, _cat, equipe, *_ in d["linhas"]:
            if not equipe:
                continue
            achado = limpar(equipe)
            if not achado:
                continue
            chave, _ = achado
            if chave in cidades:
                continue
            alunos[chave][d["slug"]].add(slug)
            grafias[chave][equipe.strip()] += 1

    troca = _juntar_interrogacao(list(alunos))
    troca.update(MESMA_EQUIPE)
    for velha, nova in troca.items():
        if velha == nova or velha not in alunos:
            continue
        for prova, quem in alunos.pop(velha).items():
            alunos[nova][prova] |= quem
        grafias[nova].update(grafias.pop(velha))

    equipes, indice_prova, lista_provas = [], {}, []

    def ip(slug):
        if slug not in indice_prova:
            indice_prova[slug] = len(lista_provas)
            lista_provas.append(slug)
        return indice_prova[slug]

    for chave, provas in alunos.items():
        total = sum(len(q) for q in provas.values())
        if total < MINIMO_ALUNOS:
            continue
        # O nome exibido e a grafia mais usada, sem a interrogacao do acento
        # perdido; entre as bem usadas, a com espaco ("Ojanio Assessoria" e
        # nao "Ojanioassessoria").
        boas = [(g, n) for g, n in grafias[chave].most_common() if "�" not in g and "?" not in g]
        nome = boas[0][0] if boas else grafias[chave].most_common(1)[0][0]
        if boas and " " not in nome:
            nome = next((g for g, n in boas if " " in g and n * 4 >= boas[0][1]), nome)
        equipes.append([_bonito(nome), sorted(([p, len(q)] for p, q in provas.items()), key=lambda x: -x[1])])
    equipes.sort(key=lambda e: -sum(n for _, n in e[1]))
    # No arquivo a prova vai pelo numero (a lista "provas" da o or_slug):
    # corta o tamanho pela metade.
    compacto = [[nome, [x for p, n in provas for x in (ip(p), n)]] for nome, provas in equipes]
    if BI_DIR.is_dir():
        SAIDA.write_text(json.dumps({"provas": lista_provas, "equipes": compacto}, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    registrar(f"assessorias: {len(equipes)} equipes com {MINIMO_ALUNOS}+ participacoes")
    return equipes


PEQUENAS = {"da", "de", "do", "das", "dos", "e", "na", "no", "em"}


def _bonito(nome):
    """"LOUCOS NA PISTA" -> "Loucos na Pista"; sigla curta fica em maiuscula."""
    nome = consertar_mojibake(nome).strip()
    if not nome.isupper() and not nome.islower():
        return nome
    palavras = []
    for i, p in enumerate(nome.split()):
        pl = p.lower()
        if i and pl in PEQUENAS:
            palavras.append(pl)
        elif len(p) <= 3 and p.isalpha() and pl not in PEQUENAS and not re.search(r"[aeiou]", pl[1:]):
            palavras.append(p.upper())
        else:
            palavras.append(pl[:1].upper() + pl[1:])
    # "Performance/fw" -> "Performance/Fw"
    return re.sub(r"([/-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), " ".join(palavras))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    eq = montar()
    for nome, provas in eq[:int(sys.argv[1]) if len(sys.argv) > 1 else 0]:
        print(sum(n for _, n in provas), len(provas), nome)
