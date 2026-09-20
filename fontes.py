#!/usr/bin/env python3
"""Adaptadores das tres fontes do calendario.

Cada funcao devolve uma lista de registros no mesmo formato:
    {fonte, data, dia, mes, ano, cidade, regiao, nome, pills, km, tags}
O merge fica em scrape.py.
"""

import datetime
import functools
import html as entidades
import json
import re
import urllib.parse

from comum import (MESES_ABBR, MESES_NOME, UF_ALVO, arrumar_titulo, baixar,
                   canonizar_cidade, classificar, consertar_mojibake,
                   distancias, limpar, separar_organizadores, sem_acento)

# ---------------------------------------------------------------- corridasbr

CBR_BASE = f"https://www.corridasbr.com.br/{UF_ALVO}/"
CBR_PAGINAS = ["Calendario.asp", "Calendario2.asp", "Calendario3.asp"]


def corridasbr():
    """Calendario do corridasbr.com.br: tres paginas de HTML em cp1252."""
    provas = []
    ano = datetime.date.today().year
    mes_anterior = None

    for pagina in CBR_PAGINAS:
        html = baixar(CBR_BASE + pagina)
        blocos = re.split(r'tipo6"><font color="#FFFFFF">\s*([A-Za-zÀ-ÿ]+)', html)

        for i in range(1, len(blocos), 2):
            mes_cab = MESES_NOME.get(sem_acento(blocos[i].strip()))
            if not mes_cab:
                continue
            # A lista anda sempre para a frente: mes menor que o anterior = virou o ano.
            if mes_anterior is not None and mes_cab < mes_anterior:
                ano += 1
            mes_anterior = mes_cab

            for tr in re.findall(r'<tr align="center" height="45".*?</tr>',
                                 blocos[i + 1], re.S):
                tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
                if len(tds) < 4:
                    continue
                casa = re.match(r"(\d{1,2})\.(\d{1,2})", limpar(tds[0]))
                nome = limpar(tds[2])
                if not casa or not nome:
                    continue

                dia, mes = int(casa.group(1)), int(casa.group(2))
                cidade = limpar(tds[1])
                if not cidade:
                    # Linhas sem cidade as vezes trazem no nome: "Eco Run - Navegantes".
                    fim = nome.rsplit("-", 1)
                    if len(fim) == 2:
                        cidade = fim[1].strip()

                pills, km, extra = distancias(limpar(tds[3]))
                cidade, regiao, uf = canonizar_cidade(cidade)
                # O id leva a pagina da prova, que traz o organizador.
                ident = re.search(r"escolha=(\d+)", tds[2])
                provas.append({
                    "fonte": "corridasbr",
                    "corrida_id": ident.group(1) if ident else None,
                    "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
                    "dia": dia, "mes": mes, "ano": ano,
                    "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
                    "pills": pills, "km": km,
                    "tags": classificar(nome, km, [extra]),
                })
    return provas


# ------------------------------------------------- corridasbr (arquivo do ano)

# O arquivo de resultados guarda mes a mes as provas ja realizadas, que ja
# sairam do calendario. E a unica fonte de provas passadas que encontrei.
# Nao traz distancias: a quarta coluna e o link do resultado, nao o percurso.
CBR_ARQUIVO = CBR_BASE + "Res_{ano}.asp?escolha={mes}"

CBR_LINHA = re.compile(r'<tr align="center" height="50".*?(?=<tr|\Z)', re.S)


def corridasbr_arquivo(ano=None, ate_mes=None):
    """Provas ja realizadas no ano corrente, do arquivo de resultados."""
    hoje = datetime.date.today()
    ano = ano or hoje.year
    ate_mes = ate_mes or hoje.month

    provas = []
    for mes in range(1, ate_mes + 1):
        try:
            html = baixar(CBR_ARQUIVO.format(ano=ano, mes=mes))
        except Exception:
            continue          # mes ainda sem pagina publicada
        for linha in CBR_LINHA.findall(html):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
            if len(tds) < 3:
                continue
            casa = re.match(r"(\d{1,2})\.(\d{1,2})", limpar(tds[0]))
            nome = limpar(tds[2])
            if not casa or not nome:
                continue
            dia, mes_linha = int(casa.group(1)), int(casa.group(2))
            if mes_linha != mes:
                continue      # linha fora do mes da pagina: ignora
            cidade, regiao, uf = canonizar_cidade(limpar(tds[1]))
            # O link do resultado leva a pagina que tem as distancias,
            # recuperadas depois por distancias_do_resultado().
            ident = re.search(r"mostraresultado\.asp\?escolha=(\d+)", linha)
            provas.append({
                "fonte": "corridasbr",
                "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
                "dia": dia, "mes": mes, "ano": ano,
                "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
                "pills": [], "km": [],
                "resultado_id": ident.group(1) if ident else None,
                "tags": classificar(nome, []),
            })
    return provas


CBR_ORGANIZADOR = re.compile(r"Organizador:\s*(.+?)\s+(?:Mais Informa|Compartilhar|Resultados|Publicidade|$)")


@functools.lru_cache(maxsize=4096)
def _texto_corridasbr(caminho):
    """Texto limpo de uma pagina do corridasbr, com cache.

    A mesma pagina de resultado traz o percurso E o organizador; sem o cache,
    cada prova passada seria baixada duas vezes.
    """
    html = baixar(CBR_BASE + caminho)
    return limpar(re.sub(r"<script.*?</script>", " ", html, flags=re.S))


def organizador_da_prova(corrida_id=None, resultado_id=None):
    """Le a pagina da prova (futura) ou a do resultado (passada) e devolve o
    organizador. Nenhuma das listagens traz esse campo."""
    if corrida_id:
        caminho = f"mostracorrida.asp?escolha={corrida_id}"
    elif resultado_id:
        caminho = f"mostraresultado.asp?escolha={resultado_id}"
    else:
        return ""
    achado = CBR_ORGANIZADOR.search(_texto_corridasbr(caminho))
    return achado.group(1).strip() if achado else ""


CBR_DISTANCIA = re.compile(r"ncia\(s\):\s*(.+?)\s+(?:Organizador|Resultados|Publicidade)")


def distancias_do_resultado(resultado_id):
    """Le a pagina de resultado de uma prova passada e devolve (pills, km).

    O arquivo mensal nao traz percurso; a pagina de cada prova traz.
    """
    texto = _texto_corridasbr(f"mostraresultado.asp?escolha={resultado_id}")
    achado = CBR_DISTANCIA.search(texto)
    if not achado:
        return [], []
    pills, km, _ = distancias(achado.group(1).strip())
    return pills, km


# -------------------------------------------------------------- ticketsports

TS_LISTA = ("https://www.ticketsports.com.br/api/events/list"
            "?quantity=500&atlheteId=0&term=&country=BR&region=" + UF_ALVO)
# Filtros que a API aplica de fato. Um filtro desconhecido e ignorado e devolve
# a lista inteira, entao qualquer resultado do tamanho do total e descartado.
TS_EXCLUIR = ["ciclismo", "mountain-bike", "triathlon", "natacao"]
TS_DISTANCIAS = [("4k", ["5k"], "até 4km"), ("5k-a-10k", ["5k", "10k"], "5 a 10km"),
                 ("11k-a-20k", ["21k"], "11 a 20km"), ("21k", ["21k"], "21km"),
                 ("42k", ["42k"], "42km")]


def _ts_ids(quick_filter):
    dados = json.loads(baixar(TS_LISTA + "&quickFilter=" + quick_filter,
                              {"Accept": "application/json"}))
    return {e["eventId"] for e in dados}


def ticketsports():
    """API publica do calendario da Ticket Sports, recortada em SC."""
    base = json.loads(baixar(TS_LISTA, {"Accept": "application/json"}))
    total = {e["eventId"] for e in base}

    fora = set()
    for filtro in TS_EXCLUIR:
        ids = _ts_ids(filtro)
        if ids != total:                      # filtro reconhecido pela API
            fora |= ids

    bandas = {}
    for filtro, faixas, rotulo in TS_DISTANCIAS:
        ids = _ts_ids(filtro)
        if ids == total:
            continue
        for i in ids:
            achada = bandas.setdefault(i, {"faixas": set(), "rotulos": []})
            achada["faixas"].update(faixas)
            achada["rotulos"].append(rotulo)

    provas = []
    for e in base:
        if e["eventId"] in fora or e.get("isVirtualEvent"):
            continue
        try:
            dia, mes, ano = int(e["day"]), MESES_ABBR[e["month"][:3].lower()], int(e["year"])
        except (KeyError, ValueError):
            continue

        cidade, regiao, uf = canonizar_cidade(e.get("address", "").rsplit(",", 1)[0])
        nome = " ".join((e.get("title") or "").split())
        banda = bandas.get(e["eventId"])
        provas.append({
            "fonte": "ticketsports",
            "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
            "dia": dia, "mes": mes, "ano": ano,
            "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
            # A API nao expoe as distancias exatas, so as faixas do filtro.
            "pills": banda["rotulos"] if banda else [],
            "km": [],
            "faixas_diretas": sorted(banda["faixas"]) if banda else [],
            "organizadores": separar_organizadores(e.get("organizer")),
            "tags": classificar(nome, []),
        })
    return provas


# -------------------------------------------------------------- catarinarun

# Laravel: a lista de /eventos vem por POST paginado (20 por pagina), exigindo o
# cookie de sessao e o token CSRF da propria pagina. O site e lento -- a
# primeira resposta passa de 40 s --, dai o tempo limite folgado.
CR_EVENTOS = "https://www.catarinarun.com.br/eventos"
CR_TIMEOUT = 120
CR_MAX_PAGINAS = 40


def catarinarun():
    """Agenda do catarinarun.com.br, so eventos de Santa Catarina.

    DESLIGADA a pedido do usuario: nao consta em TODAS, entao a coleta nao a
    chama. A funcao fica aqui pronta caso seja religada.
    """
    import http.cookiejar
    import urllib.parse
    import urllib.request

    from comum import UA

    sessao = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def ler(req, tentativas=3):
        # O servidor as vezes derruba a conexao (WinError 10054) ou estoura o
        # tempo; uma pausa e nova tentativa costuma bastar.
        import time
        for n in range(tentativas):
            try:
                with sessao.open(req, timeout=CR_TIMEOUT) as resp:
                    corpo = resp.read()
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        import gzip
                        corpo = gzip.decompress(corpo)
                return corpo.decode("utf-8", errors="replace")
            except OSError:
                if n == tentativas - 1:
                    raise
                time.sleep(20 * (n + 1))

    pagina_html = ler(urllib.request.Request(CR_EVENTOS, headers={"User-Agent": UA}))
    token = re.search(r'name="csrf-token" content="([^"]+)"', pagina_html)
    if not token:
        raise RuntimeError("token CSRF nao encontrado em /eventos")
    token = token.group(1)

    vistos, provas = set(), []
    for pagina in range(1, CR_MAX_PAGINAS + 1):
        corpo = urllib.parse.urlencode({
            "filtro": "all", "pagina": pagina, "cidade": "",
            "ordenacao_evento": "", "tipo_evento": "", "_token": token,
        }).encode()
        lista = json.loads(ler(urllib.request.Request(CR_EVENTOS, data=corpo, headers={
            "User-Agent": UA, "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest", "X-CSRF-TOKEN": token,
            "Referer": CR_EVENTOS,
        })))
        novos = [e for e in lista if e.get("link") not in vistos]
        if not novos:
            break

        for e in novos:
            vistos.add(e.get("link"))
            # O site so cobre SC, mas o campo existe: respeita a UF alvo.
            if sem_acento(e.get("estado") or "") not in ("santa catarina", ""):
                continue
            casa = re.match(r"(\d{1,2}),\s*([A-Za-zç]{3})\w*\s+(\d{4})", e.get("data") or "")
            mes = MESES_ABBR.get(casa.group(2).lower()) if casa else None
            nome = " ".join((e.get("titulo") or "").split())
            if not (casa and mes and nome):
                continue
            dia, ano = int(casa.group(1)), int(casa.group(3))
            cidade, regiao, uf = canonizar_cidade(e.get("cidade") or "")
            provas.append({
                "fonte": "catarinarun",
                "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
                "dia": dia, "mes": mes, "ano": ano,
                "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
                # A lista nao traz percurso; na fusao vale o das outras fontes.
                "pills": [], "km": [],
                "tags": classificar(nome, []),
            })
    return provas


# ------------------------------------------------------------------ movnow

# Next.js sem pagina de listagem: os eventos saem do sitemap e cada pagina
# embute os dados no payload do React (self.__next_f), com cidade/estado
# estruturados e os percursos no nome de cada inscricao ("12K", "6K").
MN_SITEMAP = "https://www.movnow.com.br/sitemap.xml"
MN_BASE = "https://www.movnow.com.br"
MN_PAUSA = 0.3

UF_NOME = {"SC": "santa catarina"}
# Categorias do MovNow que sao corrida; o resto (natacao, aquathlon, MTB,
# workshops, eventos de entretenimento) fica de fora.
MN_CORRIDA = {"corrida", "corrida de rua", "trail run", "trail", "caminhada",
              "corrida de montanha", "corrida de obstaculos"}


def _payload_next(html):
    """Junta e desescapa os pedacos do payload RSC de uma pagina Next.js."""
    partes = []
    for bruto in re.findall(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html, re.S):
        try:
            partes.append(json.loads('"' + bruto + '"'))
        except ValueError:
            continue
    return "".join(partes)


def _km_de_rotulos(rotulos):
    """'12K', 'Corrida 10km', '21,1 KM' -> [12.0, 10.0, 21.1]; ignora o resto."""
    km = []
    for r in rotulos:
        for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*k(?:m)?\b", r, re.I):
            v = float(n.replace(",", "."))
            if 0 < v <= 400 and v not in km:
                km.append(v)
    return sorted(km, reverse=True)


def movnow(categorias=MN_CORRIDA):
    """Corridas do movnow.com.br na UF alvo. categorias=None traz todas."""
    import time

    xml = baixar(MN_SITEMAP)
    caminhos = sorted(set(re.findall(r"<loc>https?://[^<]*?(/eventos/\d+-[^<]+)</loc>", xml)))
    alvo = UF_NOME.get(UF_ALVO, UF_ALVO.lower())

    provas = []
    for caminho in caminhos:
        try:
            dados = _payload_next(baixar(MN_BASE + caminho))
        except Exception:
            continue
        time.sleep(MN_PAUSA)

        cab = re.search(r'"name":"([^"]+)","dateLabel":"(\d{2})/(\d{2})/(\d{4})[^"]*",'
                        r'"category":"([^"]*)"', dados)
        local = re.search(r'"location":\{[^{}]*?"city":"([^"]*)","state":"([^"]*)"', dados)
        if not (cab and local):
            continue
        if sem_acento(local.group(2)) != alvo:
            continue
        categoria = cab.group(5)
        if categorias is not None and sem_acento(categoria) not in categorias:
            continue

        nome = " ".join(cab.group(1).split())
        dia, mes, ano = int(cab.group(2)), int(cab.group(3)), int(cab.group(4))
        rotulos = re.findall(r'\{"id":"\d+","name":"([^"]+)","participants"', dados)
        km = _km_de_rotulos(rotulos)
        cidade, regiao, uf = canonizar_cidade(local.group(1))
        extras = ["Trail"] if "trail" in sem_acento(categoria) else []
        provas.append({
            "fonte": "movnow",
            "categoria": categoria,
            "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
            "dia": dia, "mes": mes, "ano": ano,
            "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
            "pills": [f"{v:g}km" for v in km], "km": km,
            "tags": classificar(nome, km, extras),
        })
    return provas


# ------------------------------------------------------------------ atletis

# Plataforma multiesportiva pequena: /eventos lista poucos eventos, sem
# paginacao, e cada pagina de evento traz um JSON-LD SportsEvent com a
# modalidade ("sport"), a data e a UF -- entao o filtro nao depende do nome.
AT_LISTA = "https://www.atletis.com.br/eventos"
AT_ESPORTES = {"corrida de rua", "corrida", "trail run", "trail", "corrida de montanha",
               "corrida de aventura", "caminhada", "maratona", "meia maratona",
               "corrida de obstaculos", "cross country"}


def _nome_organizador(evento):
    """O JSON-LD traz organizer como objeto ou, raramente, como texto."""
    org = evento.get("organizer")
    if isinstance(org, dict):
        return org.get("name") or ""
    return org or ""


def atletis():
    """Eventos de corrida do atletis.com.br na UF alvo."""
    lista = baixar(AT_LISTA)
    urls = sorted(set(re.findall(r'data-url="(https://www\.atletis\.com\.br/evento/[^"]+)"', lista)))
    alvo = UF_NOME.get(UF_ALVO, UF_ALVO.lower())

    provas = []
    for url in urls:
        try:
            html = baixar(url)
        except Exception:
            continue
        evento = None
        for bloco in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S):
            try:
                obj = json.loads(bloco)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("@type") == "SportsEvent":
                evento = obj
                break
        if not evento:
            continue

        endereco = (evento.get("location") or {}).get("address") or {}
        if sem_acento(endereco.get("addressRegion") or "") != alvo:
            continue
        if sem_acento(evento.get("sport") or "") not in AT_ESPORTES:
            continue
        casa = re.match(r"(\d{4})-(\d{2})-(\d{2})", evento.get("startDate") or "")
        nome = " ".join((evento.get("name") or "").split())
        if not (casa and nome):
            continue

        ano, mes, dia = (int(g) for g in casa.groups())
        cidade, regiao, uf = canonizar_cidade(endereco.get("addressLocality") or "")
        extras = ["Trail"] if "trail" in sem_acento(evento.get("sport") or "") else []
        provas.append({
            "fonte": "atletis",
            "data": f"{ano:04d}-{mes:02d}-{dia:02d}",
            "dia": dia, "mes": mes, "ano": ano,
            "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
            "pills": [], "km": [],
            "organizadores": separar_organizadores(_nome_organizador(evento)),
            "tags": classificar(nome, [], extras),
        })
    return provas


# --------------------------------------------------- open results (RunnerHub)

# Portal de resultados do mesmo grupo do roadrunners ("Powered by RunnerHub").
# Nao e um calendario: entra so para dizer quantos atletas CONCLUIRAM cada
# prova, por distancia. A listagem por estado ja traz essa quebra, entao nao e
# preciso abrir a pagina de cada evento.
OR_LISTA = ("https://openresults.run/api/eventos_por_estado.cfm"
            "?filtro=&tag={uf}&page={page}&lastWeek=0&lastMonth=0"
            "&lastMonthKey=&distancia=&tempo=")
OR_MAX_PAGINAS = 60

OR_CARD = re.compile(
    r'<a href="/evento/[^"]+/" class="or-event-card-link">.*?</article>', re.S)
OR_DISTANCIA = re.compile(r'or-event-distance">.*?([\d.,]+)\s*k\s*<span[^>]*>\s*\|\s*([\d.]+)', re.S)


def _numero(texto):
    """'1.098' -> 1098."""
    try:
        return int(re.sub(r"[^\d]", "", texto or "") or 0)
    except ValueError:
        return 0


def openresults(desde="2024-01-01", uf=None):
    """Concluintes por distancia das provas ja realizadas na UF alvo."""
    uf = uf or UF_ALVO
    eventos = []
    vistos = set()

    for pagina in range(OR_MAX_PAGINAS):
        html = baixar(OR_LISTA.format(uf=uf, page=pagina), {"Accept": "application/json"})
        cards = OR_CARD.findall(html)
        if not cards:
            break

        mais_antiga = None
        for card in cards:
            slug = re.search(r'href="/evento/([^"]+)/"', card)
            dia = re.search(r'<span class="day">\s*(\d{1,2})', card)
            mes = re.search(r'<span class="month">\s*([a-zç]{3})', card, re.I)
            ano = re.search(r'<span class="year">\s*(\d{4})', card)
            titulo = re.search(r'or-event-card-title">(.*?)</h2>', card, re.S)
            if not (slug and dia and mes and ano and titulo):
                continue
            mes_num = MESES_ABBR.get(mes.group(1)[:3].lower())
            if not mes_num:
                continue

            data = f"{int(ano.group(1)):04d}-{mes_num:02d}-{int(dia.group(1)):02d}"
            mais_antiga = data if mais_antiga is None else min(mais_antiga, data)
            if slug.group(1) in vistos:
                continue
            vistos.add(slug.group(1))

            local = re.search(r'location-dot[^>]*></i>(.*?)</span>', card, re.S)
            cidade = limpar(local.group(1)).split("-")[0].strip() if local else ""
            total = re.search(r'([\d.]+)\s*concluintes', limpar(card))

            por_distancia = {}
            for km, n in OR_DISTANCIA.findall(card):
                km = km.replace(",", ".").rstrip(".")
                por_distancia[km] = por_distancia.get(km, 0) + _numero(n)

            cidade, regiao, uf_achada = canonizar_cidade(cidade)
            eventos.append({
                "slug": slug.group(1),
                "data": data,
                "nome": consertar_mojibake(limpar(titulo.group(1))),
                "cidade": cidade, "regiao": regiao, "uf": uf_achada,
                "concluintes": por_distancia,
                "concluintes_total": _numero(total.group(1)) if total else 0,
            })

        if mais_antiga and mais_antiga < desde:
            break

    return eventos


OR_CARTAO = re.compile(r'<div class="card or-event-card">.*?</table>', re.S)
OR_TOTAIS = re.compile(r"Totais:.*?</tr>", re.S)


def openresults_generos(slug):
    """Concluintes por genero de um evento, por distancia.

    A listagem por estado so traz o total de cada distancia; a divisao entre
    feminino e masculino esta na pagina do evento. As colunas sao
    identificadas pelos links genero=F e genero=M, nao pela ordem.
    """
    # Ha slugs com acento e aspas tipograficas; a URL precisa vir codificada.
    endereco = urllib.parse.quote(slug, safe="")
    html = baixar(f"https://openresults.run/evento/{endereco}/")
    por_distancia, total_f, total_m = {}, 0, 0

    for cartao in OR_CARTAO.findall(html):
        rotulo = re.search(r'<span class="h5">([^<]+)</span>', cartao)
        totais = OR_TOTAIS.search(cartao)
        if not (rotulo and totais):
            continue
        linha = totais.group(0)
        # O numero vem com separador de milhar ("1.203"): exigir so digitos
        # zerava justamente as provas grandes.
        f = re.search(r'genero=F">([\d.,]+)</a>', linha)
        m = re.search(r'genero=M">([\d.,]+)</a>', linha)
        if not (f or m):
            continue
        nf, nm = _numero(f.group(1) if f else ""), _numero(m.group(1) if m else "")
        total_f += nf
        total_m += nm

        km = re.search(r"(\d+(?:[.,]\d+)?)\s*k", rotulo.group(1), re.I)
        if km:
            chave = km.group(1).replace(",", ".").rstrip(".")
            anterior = por_distancia.get(chave, {"f": 0, "m": 0})
            por_distancia[chave] = {"f": anterior["f"] + nf, "m": anterior["m"] + nm}

    return por_distancia, total_f, total_m


# ------------------------------------------------- runking (Chronomax)

# Cronometragem que publica resultados em resultados.runking.com.br/<empresa>/
# <evento>. Nao e calendario: entra so para completar os concluintes das
# provas que o Open Results nao cobre. Cada empresa tem uma pagina listando
# seus eventos, e cada evento traz os numeros por modalidade.
RK_BASE = "https://resultados.runking.com.br/"

# Empresas ja mapeadas. A lista cresce quando se descobre outra: basta o
# trecho que vem depois do dominio na URL do resultado.
RK_EMPRESAS = ["sportsland"]

RK_EVENTO = re.compile(
    r'\{"id":(\d+),"companysId":\d+,"name":"([^"]+)","slug":"([^"]+)".*?"mainDate":"([^"]+)"')


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
    import urllib.parse

    dados = _rk_payload(f"{empresa}/{slug}")
    achado = re.search(r'"distinctModalities":(\[[^\]]*\])', dados)
    if not achado:
        return {}, 0
    generos = re.search(r'"distinctGenders":(\[[^\]]*\])', dados)
    # Sem o parametro de genero a pagina devolve SO o feminino, entao cada
    # genero e pedido em separado e somado. Sem isso o total sai pela metade.
    generos = json.loads(generos.group(1)) if generos else []

    por_distancia, por_genero, total = {}, {}, 0
    for modalidade in json.loads(achado.group(1)):
        contagem = {"f": 0, "m": 0}
        n_modalidade = 0
        for genero in (generos or [None]):
            url = f"{empresa}/{slug}?modality={urllib.parse.quote(modalidade)}"
            if genero:
                url += f"&gender={urllib.parse.quote(genero)}"
            pagina = _rk_payload(url)
            resultado = re.search(r'"totalAthletesResults":(\d+)', pagina)
            n = int(resultado.group(1)) if resultado else 0
            n_modalidade += n
            if genero and genero.upper().startswith("F"):
                contagem["f"] += n
            elif genero:
                contagem["m"] += n
        if not n_modalidade:
            continue
        total += n_modalidade
        km = re.match(r"(\d+(?:[.,]\d+)?)\s*k", modalidade.strip(), re.I)
        if km:
            chave = km.group(1).replace(",", ".").rstrip(".")
            por_distancia[chave] = por_distancia.get(chave, 0) + n_modalidade
            anterior = por_genero.get(chave, {"f": 0, "m": 0})
            por_genero[chave] = {"f": anterior["f"] + contagem["f"],
                                 "m": anterior["m"] + contagem["m"]}
    return por_distancia, total, por_genero


# -------------------------------------------------------------- roadrunners

RR_BASE = ("https://roadrunners.run/api/eventos_busca.cfm"
           "?badges=&rua=true&trail=true&nacional=true&internacional=false"
           "&tag=&cupom=false&busca_mode=plain&tipo_termo=indefinido"
           "&estado=" + UF_ALVO)
RR_MAX_PAGINAS = 12

RR_CARD = re.compile(
    r'<div class="home-event-card"[^>]*>(.*?)(?=<div class="home-event-card"|\Z)', re.S)


def roadrunners():
    """Busca do roadrunners.run: devolve cards HTML paginados de 50 em 50."""
    provas, vistos = [], set()

    for pagina in range(RR_MAX_PAGINAS):
        html = baixar(f"{RR_BASE}&page={pagina}",
                      {"X-Requested-With": "XMLHttpRequest"})
        novos = 0

        for corpo in RR_CARD.findall(html):
            dia = re.search(r'<span class="day">\s*(\d{1,2})', corpo)
            mes = re.search(r'<span class="month">\s*([a-zç]{3})', corpo, re.I)
            ano = re.search(r'<span class="year">\s*(\d{4})', corpo)
            titulo = re.search(r'class="home-event-card-title[^"]*">(.*?)</div>', corpo, re.S)
            if not (dia and mes and ano and titulo):
                continue

            nome = arrumar_titulo(limpar(titulo.group(1)))
            meta = re.search(r'class="home-event-card-meta">(.*?)</div>', corpo, re.S)
            local = limpar(meta.group(1)) if meta else ""
            # "Planalto Alegre - SC" -> so eventos do estado interessam.
            partes = re.split(r"\s*[-–]\s*", local)
            sigla = re.sub(r"[^A-Za-z]", "", partes[-1]).upper() if len(partes) > 1 else ""
            if sigla and sigla != UF_ALVO:
                continue
            cidade, regiao, uf = canonizar_cidade(partes[0] if partes else "")

            chave = (dia.group(1), mes.group(1).lower(), ano.group(1), sem_acento(nome))
            if chave in vistos:
                continue
            vistos.add(chave)
            novos += 1

            marcas = [limpar(f) for f in
                      re.findall(r'class="home-event-flag">(.*?)</span>', corpo, re.S)]
            extras = []
            if any("trail" in sem_acento(m) for m in marcas):
                extras.append("Trail")
            if any("caminhada" in sem_acento(m) for m in marcas):
                extras.append("Caminhada")

            # Cada distancia vem no seu proprio span ("5km", "21km", "10 milhas").
            pills, km = [], []
            for span in re.findall(r'class="home-event-distance">(.*?)</span>', corpo, re.S):
                p, k, extra = distancias(limpar(span))
                pills += p
                km += k
                if extra:
                    extras.append(extra)

            mes_num = MESES_ABBR.get(mes.group(1)[:3].lower())
            if not mes_num:
                continue
            provas.append({
                "fonte": "roadrunners",
                "data": f"{int(ano.group(1)):04d}-{mes_num:02d}-{int(dia.group(1)):02d}",
                "dia": int(dia.group(1)), "mes": mes_num, "ano": int(ano.group(1)),
                "cidade": cidade, "regiao": regiao, "uf": uf, "nome": nome,
                "pills": pills, "km": km,
                "tags": classificar(nome, km, extras),
            })

        if novos == 0:
            break
    return provas


TODAS = [("corridasbr", corridasbr),
         ("corridasbr/arquivo", corridasbr_arquivo),
         ("ticketsports", ticketsports),
         ("roadrunners", roadrunners),
         ("movnow", movnow),
         ("atletis", atletis)]


# ----------------------------------------------- super crono (cronometragem)

# Cronometragem de Santa Catarina. Publica os resultados num aplicativo que
# le arquivos JSON estaticos -- os mesmos que a pagina busca -- com a lista
# completa de atletas. Nao e calendario: entra so para completar os
# concluintes das provas que o Open Results nao cobre, principalmente trail.
SC_BASE = "https://www.supercrono.com.br/resultados/result/data/"
SC_NAO_CONCLUIU = {"DSQ", "DQ"}
SC_KM = re.compile(r"(\d+(?:[.,]\d+)?)\s*k", re.I)


def supercrono_eventos():
    """Provas cronometradas pela Super Crono, so as da UF alvo."""
    eventos = []
    for e in json.loads(baixar(SC_BASE + "events.json")):
        cidade, regiao, uf = canonizar_cidade(e.get("place") or "")
        if uf != UF_ALVO or not e.get("startDate"):
            continue
        eventos.append({
            "id": e["id"], "data": e["startDate"][:10],
            "nome": arrumar_titulo(e.get("name") or ""),
            "cidade": cidade, "regiao": regiao, "uf": uf,
            "organizadores": separar_organizadores(e.get("organizer") or ""),
        })
    return eventos


def _supercrono_rotas(ident):
    """Percurso -> distancia em km, lida do nome ("29KM - TTR-VA Via Alpina").

    A distancia medida vem em metros e nao serve de rotulo: 10.600 m e a
    aferricao de uma prova que todo mundo chama de 10 km.
    """
    evento = json.loads(baixar(f"{SC_BASE}{ident}/event.json"))
    rotas = {}
    for r in evento.get("routes", []):
        achado = SC_KM.search(r.get("n") or "")
        if achado:
            rotas[r["i"]] = achado.group(1).replace(",", ".").rstrip(".")
        else:
            km = round((r.get("d") or 0) / 1000)
            rotas[r["i"]] = str(km) if km else ""
    return rotas


def supercrono_concluintes(ident):
    """Concluintes por distancia e por sexo.

    Concluiu quem tem tempo de chegada. Olhar so o campo de status contaria
    tambem quem se inscreveu e nao largou: na Corrida do Trabalhador isso
    daria 520 em vez dos 437 que o Open Results publica.
    """
    rotas = _supercrono_rotas(ident)
    por_distancia, por_genero = {}, {}
    for a in json.loads(baixar(f"{SC_BASE}{ident}/results.json")):
        if not (a.get("tn") or a.get("tg")):
            continue
        if (a.get("s") or "").upper() in SC_NAO_CONCLUIU:
            continue
        km = rotas.get(a.get("r"))
        if not km:
            continue
        por_distancia[km] = por_distancia.get(km, 0) + 1
        sexo = (a.get("g") or "").upper()
        if sexo in ("F", "M"):
            atual = por_genero.setdefault(km, {"f": 0, "m": 0})
            atual["f" if sexo == "F" else "m"] += 1
    return por_distancia, sum(por_distancia.values()), por_genero


# --------------------------------------------------- chiprun (cronometragem)

# Outra cronometragem catarinense. Aqui nao ha API: a pagina do evento monta
# a lista de atletas no servidor e pagina de 20 em 20, filtrando por
# modalidade e sexo pela query string. Contam-se as paginas em vez de baixar
# a lista inteira. O catalogo de eventos, esse sim, sai da API do WordPress.
CR_BASE = "https://chiprun.com.br/"
CR_EVENTOS = CR_BASE + "wp-json/wp/v2/evento?per_page=100&page={pagina}"
CR_POR_PAGINA = 20
CR_LINHA = re.compile(r'class="nome-atleta"')
CR_PAGINA = re.compile(r"pagina=(\d+)")
CR_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
CR_MODALIDADE = re.compile(r'<option[^>]*value="([^"]+)"')
# Cidade e data ficam lado a lado no cabecalho, cada uma num <span> destacado.
CR_DESTAQUE = re.compile(r'<span class="font-bold">([^<]+)</span>')
CR_MAX_PAGINAS = 60


def chiprun_eventos():
    """Catalogo de eventos: so nome e identificador, que e o que a API traz.

    Data e modalidades ficam na pagina de cada evento, e sao caras demais
    para buscar de todos: quem precisa chama chiprun_evento no candidato.
    """
    eventos, vistos = [], set()
    for pagina in range(1, 8):
        try:
            lote = json.loads(baixar(CR_EVENTOS.format(pagina=pagina)))
        except Exception:
            break
        if not lote:
            break
        for e in lote:
            slug = e.get("slug")
            if not slug or slug in vistos:
                continue
            vistos.add(slug)
            eventos.append({
                "slug": slug,
                "nome": entidades.unescape((e.get("title") or {}).get("rendered") or ""),
            })
        if len(lote) < 100:
            break
    return eventos


def chiprun_evento(slug):
    """Data, cidade e modalidades de um evento, lidas da pagina dele."""
    pagina = baixar(f"{CR_BASE}evento/{slug}/")
    achado = CR_DATA.search(pagina)
    data = (f"{achado.group(3)}-{achado.group(2)}-{achado.group(1)}"
            if achado else "")
    cidade = next((d for d in CR_DESTAQUE.findall(pagina)
                   if not CR_DATA.fullmatch(d.strip())), "")
    return data, limpar(cidade), [m for m in CR_MODALIDADE.findall(pagina) if m.strip()]


def _chiprun_total(url):
    """Quantos atletas a consulta devolve, sem baixar a lista inteira.

    O rodape linka a ultima pagina, mas nem sempre a ultima de verdade --
    numa lista longa ele mostra uma janela. Por isso a contagem segue adiante
    enquanto a pagina vier cheia.
    """
    html_pagina = baixar(url)
    linhas = len(CR_LINHA.findall(html_pagina))
    if linhas < CR_POR_PAGINA:
        return linhas
    paginas = [int(p) for p in CR_PAGINA.findall(html_pagina)]
    numero = max(paginas) if paginas else 1
    for _ in range(CR_MAX_PAGINAS):
        fim = baixar(f"{url}&pagina={numero}")
        linhas = len(CR_LINHA.findall(fim))
        if linhas < CR_POR_PAGINA:
            return (numero - 1) * CR_POR_PAGINA + linhas
        numero += 1
    return (numero - 1) * CR_POR_PAGINA


def chiprun_concluintes(slug, modalidades):
    """Concluintes por distancia e por sexo.

    Modalidade sem quilometragem no nome ("ELITE", "DUPLA MISTA") fica de
    fora: sem distancia ela nao entra em nenhum recorte do site.
    """
    base = f"{CR_BASE}evento/{slug}/"
    por_distancia, por_genero = {}, {}
    for modalidade in modalidades:
        km = SC_KM.search(modalidade)
        if not km:
            continue
        chave = km.group(1).replace(",", ".").rstrip(".")
        consulta = base + "?modalidade=" + urllib.parse.quote_plus(modalidade)
        total = _chiprun_total(consulta)
        if not total:
            continue
        feminino = _chiprun_total(consulta + "&sexo=F")
        por_distancia[chave] = por_distancia.get(chave, 0) + total
        atual = por_genero.setdefault(chave, {"f": 0, "m": 0})
        atual["f"] += feminino
        atual["m"] += total - feminino
    return por_distancia, sum(por_distancia.values()), por_genero
