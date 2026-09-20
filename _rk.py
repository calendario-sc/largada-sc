"""Uso unico: adaptador do RunKing (Chronomax) como fonte de resultados."""

from pathlib import Path

p = Path(__file__).resolve().parent / "fontes.py"
t = p.read_text(encoding="utf-8")

BLOCO = '''# ------------------------------------------------- runking (Chronomax)

# Cronometragem que publica resultados em resultados.runking.com.br/<empresa>/
# <evento>. Nao e calendario: entra so para completar os concluintes das
# provas que o Open Results nao cobre. Cada empresa tem uma pagina listando
# seus eventos, e cada evento traz os numeros por modalidade.
RK_BASE = "https://resultados.runking.com.br/"

# Empresas ja mapeadas. A lista cresce quando se descobre outra: basta o
# trecho que vem depois do dominio na URL do resultado.
RK_EMPRESAS = ["sportsland"]

RK_EVENTO = re.compile(
    r'\\{"id":(\\d+),"companysId":\\d+,"name":"([^"]+)","slug":"([^"]+)".*?"mainDate":"([^"]+)"')


def _rk_payload(caminho):
    """Os dados do RunKing vem embutidos no payload do React (Next.js)."""
    return _payload_next(baixar(RK_BASE + caminho))


def runking_eventos(empresa):
    """Eventos publicados por uma empresa de cronometragem."""
    dados = _rk_payload(empresa)
    vistos, eventos = set(), []
    for _, nome, slug, data in RK_EVENTO.findall(dados):
        if slug in vistos:
            continue
        vistos.add(slug)
        eventos.append({
            "empresa": empresa, "slug": slug,
            "nome": consertar_mojibake(nome).strip(),
            "data": data[:10],
        })
    return eventos


def runking_concluintes(empresa, slug):
    """Concluintes por distancia de um evento, somando as modalidades.

    A pagina mostra os numeros de UMA modalidade por vez, entao e preciso
    pedir cada uma: ?modality=5K, ?modality=10K...
    """
    dados = _rk_payload(f"{empresa}/{slug}")
    achado = re.search(r'"distinctModalities":(\\[[^\\]]*\\])', dados)
    if not achado:
        return {}, 0

    por_distancia, total = {}, 0
    for modalidade in json.loads(achado.group(1)):
        pagina = _rk_payload(f"{empresa}/{slug}?modality={urllib.parse.quote(modalidade)}")
        resultado = re.search(r'"totalAthletesResults":(\\d+)', pagina)
        n = int(resultado.group(1)) if resultado else 0
        if not n:
            continue
        total += n
        km = re.match(r"(\\d+(?:[.,]\\d+)?)\\s*k", modalidade.strip(), re.I)
        if km:
            chave = km.group(1).replace(",", ".").rstrip(".")
            por_distancia[chave] = por_distancia.get(chave, 0) + n
    return por_distancia, total


'''

ancora = "# -------------------------------------------------------------- roadrunners"
assert t.count(ancora) == 1
t = t.replace(ancora, BLOCO + ancora)

# o urllib.parse passa a ser usado no topo do modulo
assert "import urllib.parse" not in t
t = t.replace("import datetime\nimport functools\nimport json\nimport re",
              "import datetime\nimport functools\nimport json\nimport re\nimport urllib.parse", 1)

p.write_text(t, encoding="utf-8")
print("fontes.py: adaptador do RunKing")
