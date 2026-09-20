#!/usr/bin/env python3
"""Peças compartilhadas pelos adaptadores de fonte e pelo merge."""

import gzip
import re
import unicodedata
import urllib.request
import zlib

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) largada-sc/2.0"

MESES_ABBR = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
MESES_NOME = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

FAIXAS = ["5k", "10k", "21k", "42k", "ultra"]

# Estado que a coleta cobre. A expansao nacional troca isto por um laco.
UF_ALVO = "SC"

# Apelidos por UF: grafias que as fontes usam e que o IBGE nao reconhece.
APELIDOS = {
    "SC": {
        "floripa": "Florianópolis",
        "balneario camboriu bc": "Balneário Camboriú",
        "sao jose sc": "São José",
    },
}

# Numerais romanos que o roadrunners rebaixa para "Ii", "Iii", "Xii".
ROMANO = re.compile(r"[IiVvXxLl]{2,}")

# Palavras que ficam minusculas ao arrumar a caixa de um nome de cidade.
LIGACOES = {"de", "do", "da", "dos", "das", "e"}

# Idem para titulos de prova, onde cabem mais preposicoes.
LIGACOES_TITULO = LIGACOES | {"a", "as", "ao", "aos", "em", "no", "na", "nos",
                              "nas", "pelo", "pela", "pelos", "pelas", "com",
                              "para", "por", "o", "os", "um", "uma", "e"}

# Eventos que nao sao corrida e vazam pelos filtros de modalidade das fontes.
NAO_CORRIDA = ("duathlon", "duatlon", "triathlon", "triatlon", "aquathlon",
               "ironman", "cicloturismo", "ciclismo", "mountain bike", "mtb",
               "gran fondo", "beach tennis", "futevolei", "canoagem",
               "pedal", "bike",
               # prova virtual nao acontece num lugar: nao e calendario
               "corrida virtual", "desafio virtual", "(virtual)")

# Textos que aparecem no lugar do nome do organizador e nao identificam ninguem.
ORG_VAZIO = {"", "-", "--", "a definir", "a confirmar", "nao informado",
             "sem organizador", "diversos", "varios", "organizador"}

# Uma prova co-organizada traz as empresas separadas por barra, ponto-e-virgula
# ou barra vertical. "&", "+" e " e " ficam de fora de proposito: aparecem
# DENTRO de nomes de empresa ("Thome & Santos", "AB Bike & Fitness",
# "SESI +Saude", "CJR Academia e Eventos"). Subcontar e melhor que inventar.
ORG_SEPARADOR = re.compile(r"\s*[/;|]\s*")


def separar_organizadores(texto):
    """'LDM Eventos / Prefeitura' -> ['LDM Eventos', 'Prefeitura'].

    Cada empresa vira um item, porque o painel conta uma a uma.
    """
    nomes = []
    for parte in ORG_SEPARADOR.split(texto or ""):
        nome = " ".join(parte.split()).strip(" .,-")
        if nome and sem_acento(nome) not in ORG_VAZIO and len(nome) > 1:
            nomes.append(nome)
    return nomes


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


def consertar_mojibake(s):
    """'TubarÃo' -> 'Tubarão'.

    Alguns titulos do Open Results vem com UTF-8 lido como latin-1.
    """
    if not s or "Ã" not in s and "Â" not in s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def arrumar_caixa(nome):
    """'JACINTO MACHADO' -> 'Jacinto Machado'. Preserva nomes ja bem escritos."""
    if not nome.isupper() and not nome.islower():
        return nome
    palavras = []
    for i, p in enumerate(nome.split()):
        baixo = p.lower()
        palavras.append(baixo if i and baixo in LIGACOES else baixo.capitalize())
    return " ".join(palavras)


def arrumar_titulo(nome):
    """Conserta a caixa que o roadrunners aplica aos titulos.

    'Circuito Do Contestado'  -> 'Circuito do Contestado'
    '2º Pedal Da IntegraÇÃo'  -> '2º Pedal da Integração'
    """
    if nome.isupper():
        return nome            # CAIXA ALTA inteira e escolha da fonte, nao erro
    palavras = []
    for i, p in enumerate(nome.split()):
        if not p:
            continue
        # Maiuscula no meio da palavra depois de minuscula e artefato: 'IntegraÇÃo'.
        # Compara com a letra ja corrigida, senao 'Ç' protege o 'Ã' seguinte.
        letras = [p[0]]
        for atual in p[1:]:
            letras.append(atual.lower() if letras[-1].islower() else atual)
        palavra = "".join(letras)

        if ROMANO.fullmatch(palavra):
            palavra = palavra.upper()      # 'Ii Corrida' -> 'II Corrida'
        elif i and palavra.lower() in LIGACOES_TITULO:
            palavra = palavra.lower()
        elif palavra in ("Á", "á"):
            palavra = "à"                  # 'Sunset Á Vida' -> 'Sunset à Vida'
        palavras.append(palavra)
    return " ".join(palavras)


_INDICE = None          # {uf: {chave: [nome, regiao]}}, carregado sob demanda
_REVERSO = None         # {chave: uf}, para achar cidade de outro estado


def _indice():
    global _INDICE, _REVERSO
    if _INDICE is None:
        import municipios
        _INDICE = municipios.carregar()
        _REVERSO = {}
        for uf, cidades in _INDICE.items():
            for chave in cidades:
                _REVERSO.setdefault(chave, uf)
    return _INDICE


def canonizar_cidade(cidade, uf=None):
    """Devolve (nome, regiao, uf) usando a malha municipal do IBGE.

    regiao e a mesorregiao oficial. Cidade que existe em outro estado volta
    como "Fora de {UF}" com a sigla encontrada; cidade que nao existe em
    lugar nenhum volta como "Outras" para ser reportada.
    """
    uf = uf or UF_ALVO
    # As fontes as vezes colam endereco ("Sombrio, Rua Coberta, Centro.")
    # ou juntam varias sedes ("Laguna | Imbituba | Garopaba").
    bruta = re.split(r"[,|/]", cidade or "")[0].strip(" .	-–")
    if not bruta:
        return "", "Outras", None

    from municipios import chave_cidade
    chave = chave_cidade(bruta)
    tabela = _indice().get(uf, {})

    apelido = APELIDOS.get(uf, {}).get(chave)
    if apelido:
        chave = chave_cidade(apelido)

    achada = tabela.get(chave)
    if achada:
        return achada[0], achada[1], uf

    outra = _REVERSO.get(chave)
    if outra:
        return _INDICE[outra][chave][0], f"Fora de {uf}", outra

    return arrumar_caixa(bruta), "Outras", None


def baixar(url, headers=None, timeout=60):
    cabecalhos = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
    cabecalhos.update(headers or {})
    req = urllib.request.Request(url, headers=cabecalhos)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        bruto = resp.read()
        tipo = resp.headers.get("Content-Type", "")
        codificacao = (resp.headers.get("Content-Encoding") or "").lower()

    # O IBGE responde gzip mesmo sem Accept-Encoding; urllib nao descomprime.
    if codificacao == "gzip":
        bruto = gzip.decompress(bruto)
    elif codificacao == "deflate":
        bruto = zlib.decompress(bruto, -zlib.MAX_WBITS)
    if "charset=utf-8" in tipo.lower():
        return bruto.decode("utf-8", errors="replace")
    if "corridasbr" in url:
        return bruto.decode("cp1252", errors="replace")  # ASP legado
    return bruto.decode("utf-8", errors="replace")


ENTIDADES = [("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
             ("&lt;", "<"), ("&gt;", ">"), (" ", " ")]


def limpar(html):
    txt = re.sub(r"<[^>]+>", " ", html or "")
    # O roadrunners emite &nbsp sem o ponto-e-virgula; aceita as duas formas.
    txt = re.sub(r"&nbsp;?", " ", txt)
    for ent, ch in ENTIDADES:
        txt = txt.replace(ent, ch)
    # Entidades numericas: o corridasbr escreve "Solu&#231;&#245;es".
    txt = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), txt)
    txt = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), txt)
    return " ".join(txt.split())


def fmt(n):
    return str(int(n)) if float(n).is_integer() else ("%g" % n)


def distancias(bruto):
    """Devolve (pills, km, tag_extra) a partir de um texto de distancias."""
    s = (bruto or "").strip()
    baixo = s.lower()
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", s)]

    if "milha" in baixo:
        return [fmt(n) + " milhas" for n in nums], [n * 1.60934 for n in nums], None
    if "degrau" in baixo:
        return [fmt(n) + " degraus" for n in nums], [], "Vertical"
    if nums and re.fullmatch(r"[\d,./\s]*(km)?", baixo):
        return [fmt(n) + "km" for n in nums], nums, None
    return ([s] if s else []), [], None


def faixas_de(km):
    achadas = set()
    for v in km:
        achadas.add("5k" if v <= 6 else "10k" if v <= 12 else
                    "21k" if v <= 25 else "42k" if v <= 45 else "ultra")
    return sorted(achadas, key=FAIXAS.index)


def classificar(nome, km, extras=()):
    n = sem_acento(nome)
    tags = [t for t in extras if t]
    if any(p in n for p in ("trail", "montanha", "cross")) and "Trail" not in tags:
        tags.append("Trail")
    if ("ultra" in n or any(v > 42 for v in km)) and "Ultra" not in tags:
        tags.append("Ultra")
    if ("night" in n or "noturn" in n) and "Noturna" not in tags:
        tags.append("Noturna")
    if "revezamento" in n and "Revezamento" not in tags:
        tags.append("Revezamento")
    if any(p in n for p in ("infantil", "kids", "crianca")) and "Kids" not in tags:
        tags.append("Kids")
    if "caminhada" in n and "Caminhada" not in tags:
        tags.append("Caminhada")
    return tags or ["Rua"]


# Palavras que nao ajudam a distinguir uma prova de outra no pareamento.
VAZIAS = {
    "a", "as", "o", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
    "nos", "nas", "para", "por", "com", "corrida", "corridas", "caminhada",
    "prova", "etapa", "edicao", "run", "running", "race", "sc", "santa",
    "catarina", "2024", "2025", "2026", "2027", "2028",
}


def tokens_nome(nome):
    """Reduz o nome a um conjunto de palavras significativas para o pareamento."""
    n = sem_acento(nome)
    n = re.sub(r"\b\d+\s*[oa]?\b(?=\s)", " ", n)   # ordinais: 1a, 18o, 3
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return {p for p in n.split() if p and p not in VAZIAS and len(p) > 1}


def parecidos(a, b, ignorar=frozenset(), minimo=2):
    """True se dois nomes provavelmente designam a mesma prova.

    `ignorar` tira palavras da comparacao -- usado para o nome da cidade
    quando as duas provas ja sao da mesma cidade.
    """
    ta, tb = tokens_nome(a), tokens_nome(b)
    if ignorar and (ta - ignorar) and (tb - ignorar):
        ta, tb = ta - ignorar, tb - ignorar
    if not ta or not tb:
        return False
    # "Um nome contem o outro" precisa de `minimo` palavras no menor nome:
    # sozinha, "natal" casaria a Corrida de Natal de Lages com a de Apiuna.
    # Na mesma cidade e no mesmo dia isso nao e risco, e quem chama afrouxa.
    if len(min(ta, tb, key=len)) >= minimo and (ta <= tb or tb <= ta):
        return True
    return len(ta & tb) / len(ta | tb) >= 0.55


def _cidade_conhecida(p):
    regiao = p.get("regiao") or ""
    return bool(p.get("cidade")) and regiao != "Outras" and not regiao.startswith("Fora de")


def mesma_prova(a, b):
    """Dois registros da MESMA DATA designam a mesma prova?

    Cidade diferente decide contra: etapas de um circuito caem no mesmo dia
    em cidades diferentes e tem nomes quase iguais. Se uma das cidades e
    desconhecida, vale so o nome.
    """
    if _cidade_conhecida(a) and _cidade_conhecida(b):
        if a["cidade"] != b["cidade"]:
            return False
        # Mesma cidade: o nome dela nao distingue nada ("Corrida de Natal de
        # Apiuna" x "Corrida de Natal", ambas em Apiuna).
        # Mesma cidade e mesma data: uma palavra em comum ja basta
        # ("4a Corrida do Fogo" x "4a Corrida do Fogo - 100 anos").
        return parecidos(a["nome"], b["nome"],
                         frozenset(tokens_nome(a["cidade"])), minimo=1)
    return parecidos(a["nome"], b["nome"])
