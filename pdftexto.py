"""Texto de um PDF, so com a biblioteca padrao.

Suficiente para regulamento de corrida: PDFs gerados por Word, Canva ou
Google Docs, com o conteudo comprimido em zlib e fontes que trazem a tabela
de traducao para Unicode (ToUnicode). PDF escaneado (imagem) ou com fonte sem
essa tabela devolve pouco ou nada -- e quem chama trata como "nao achado",
nunca adivinha.
"""

import re
import zlib

OBJETO = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
FLUXO = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
REF = re.compile(rb"(\d+)\s+\d+\s+R")


def _descomprimir(dicionario, dados):
    if b"/FlateDecode" in dicionario:
        try:
            return zlib.decompress(dados)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(dados)
            except zlib.error:
                return b""
    return dados


def _objetos(pdf):
    """numero -> (dicionario, conteudo do fluxo ja descomprimido ou None)."""
    saida = {}
    for m in OBJETO.finditer(pdf):
        corpo = m.group(3)
        fluxo = FLUXO.search(corpo)
        if fluxo:
            dicionario = corpo[:fluxo.start()]
            saida[int(m.group(1))] = (dicionario, _descomprimir(dicionario, fluxo.group(1)))
        else:
            saida[int(m.group(1))] = (corpo, None)
    return saida


# ------------------------------------------------------------------ ToUnicode

def _hex(s):
    return int(s, 16)


def _tabela_unicode(cmap):
    """Le um CMap ToUnicode: codigo do glifo -> texto."""
    tabela = {}
    texto = cmap.decode("latin-1", errors="replace")
    for bloco in re.findall(r"beginbfchar(.*?)endbfchar", texto, re.S):
        for de, para in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", bloco):
            tabela[_hex(de)] = _utf16(para)
    for bloco in re.findall(r"beginbfrange(.*?)endbfrange", texto, re.S):
        for ini, fim, para in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", bloco):
            a, b = _hex(ini), _hex(fim)
            if para.startswith("<"):
                base = _hex(para[1:-1])
                for i in range(b - a + 1):
                    tabela[a + i] = chr(base + i) if base + i < 0x110000 else ""
            else:
                alvos = re.findall(r"<([0-9A-Fa-f]+)>", para)
                for i, alvo in enumerate(alvos):
                    tabela[a + i] = _utf16(alvo)
    return tabela


def _utf16(hexa):
    try:
        return bytes.fromhex(hexa).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return ""


def _fontes(objetos):
    """Nome da fonte no recurso (/F1) -> (tabela ToUnicode, bytes por codigo)."""
    por_objeto = {}
    for num, (dicionario, _) in objetos.items():
        if b"/Type" not in dicionario or b"/Font" not in dicionario:
            continue
        tabela, largura = {}, 1
        ref = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", dicionario)
        if ref and int(ref.group(1)) in objetos:
            cmap = objetos[int(ref.group(1))][1] or b""
            tabela = _tabela_unicode(cmap)
            # Fonte composta (Type0) usa dois bytes por glifo.
            largura = 2 if b"/Type0" in dicionario else 1
            if b"begincodespacerange" in cmap and re.search(
                    rb"begincodespacerange\s*<([0-9A-Fa-f]{4})>", cmap):
                largura = 2
        por_objeto[num] = (tabela, largura)

    nomes = {}
    for dicionario, _ in objetos.values():
        for bloco in re.findall(rb"/Font\s*<<(.*?)>>", dicionario, re.S):
            for nome, num in re.findall(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+\d+\s+R", bloco):
                if int(num) in por_objeto:
                    nomes[nome.decode("latin-1")] = por_objeto[int(num)]
    return nomes


# --------------------------------------------------------- operadores de texto

STRING = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>")
OPERADOR = re.compile(
    rb"/([A-Za-z0-9_.+-]+)\s+[-\d.]+\s+Tf"          # troca de fonte
    rb"|(\[(?:\\.|[^\]\\])*\])\s*TJ"                  # [ (a) -20 (b) ] TJ
    rb"|(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>)\s*(?:Tj|'|\")"  # (a) Tj
    rb"|\b(T\*|Td|TD|Tm|ET|BT)\b", re.S)
ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
           b"(": b"(", b")": b")", b"\\": b"\\"}


def _bytes_da_string(s):
    if s.startswith(b"<"):
        limpo = re.sub(rb"\s", b"", s[1:-1])
        if len(limpo) % 2:
            limpo += b"0"
        return bytes.fromhex(limpo.decode("ascii"))
    corpo, saida, i = s[1:-1], bytearray(), 0
    while i < len(corpo):
        c = corpo[i:i + 1]
        if c == b"\\" and i + 1 < len(corpo):
            prox = corpo[i + 1:i + 2]
            if prox in ESCAPES:
                saida += ESCAPES[prox]
                i += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", corpo[i + 1:i + 4])
            if octal:
                saida.append(int(octal.group(0), 8) & 0xFF)
                i += 1 + len(octal.group(0))
                continue
            i += 1
            continue
        saida += c
        i += 1
    return bytes(saida)


def _decodificar(dados, fonte):
    tabela, largura = fonte if fonte else ({}, 1)
    if tabela:
        passo = largura
        partes = []
        for i in range(0, len(dados) - passo + 1, passo):
            codigo = int.from_bytes(dados[i:i + passo], "big")
            partes.append(tabela.get(codigo, ""))
        return "".join(partes)
    return dados.decode("cp1252", errors="replace")


def _texto_do_fluxo(conteudo, fontes):
    atual, pedacos = None, []
    for m in OPERADOR.finditer(conteudo):
        if m.group(1):
            atual = fontes.get(m.group(1).decode("latin-1"))
        elif m.group(2):
            for s in STRING.findall(m.group(2)):
                pedacos.append(_decodificar(_bytes_da_string(s), atual))
        elif m.group(3):
            pedacos.append(_decodificar(_bytes_da_string(m.group(3)), atual))
        elif m.group(4) in (b"T*", b"Td", b"TD", b"ET"):
            pedacos.append("\n" if m.group(4) != b"Td" else " ")
    return "".join(pedacos)


def texto_do_pdf(pdf):
    """Texto legivel do PDF; vazio se nao der para extrair."""
    if not pdf.startswith(b"%PDF"):
        return ""
    objetos = _objetos(pdf)
    fontes = _fontes(objetos)
    saida = []
    for dicionario, conteudo in objetos.values():
        if not conteudo or b"/Type" in dicionario and (b"/XObject" in dicionario
                                                       or b"/Font" in dicionario):
            continue
        if b"BT" not in conteudo or b"ET" not in conteudo:
            continue
        saida.append(_texto_do_fluxo(conteudo, fontes))
    texto = "\n".join(saida)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


def parece_legivel(texto):
    """A extracao deu texto de verdade, e nao lixo de fonte sem tabela?"""
    if len(texto) < 200:
        return False
    letras = sum(ch.isalpha() for ch in texto)
    palavras = re.findall(r"\b(?:de|da|do|que|para|com|prova|corrida|atleta|inscri)", texto, re.I)
    return letras / max(len(texto), 1) > 0.5 and len(palavras) >= 10
