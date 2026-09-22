#!/usr/bin/env python3
"""Resultado de cada atleta, prova a prova, do Open Results.

A pagina do evento monta a tabela por chamadas a ajax_resultados_evento.cfm,
de 100 em 100 linhas, uma modalidade e um sexo por vez. Aqui se faz o mesmo
caminho e se guarda um arquivo por prova em atletas/provas/<slug>.json --
resultado publicado nao muda, entao a prova so e baixada uma vez.

So roda daqui: o Open Results recusa o servidor do GitHub (HTTP 403).

Cada linha: [slug do atleta, nome, sexo, modalidade, categoria, equipe,
             posicao geral, tempo em segundos, pace em s/km]

Uso:  python atletas_coleta.py [ANO ...]        (padrao: 2026)
"""

import datetime
import html as entidades
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import UA_NAVEGADOR, limpar  # noqa: E402

AQUI = Path(__file__).resolve().parent
PASTA = AQUI / "atletas" / "provas"
ANOS_ATLETAS = (2026,)
BASE = "https://openresults.run"
PAUSA = 0.12
LIMITE = 100          # o servidor devolve no maximo 100 por chamada

# O ColdFusion do portal quer a sessao (CFID/CFTOKEN) que a pagina cria.
_cookies = http.cookiejar.CookieJar()
_abrir = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies)).open


def baixar(url, ajax=False, referer=BASE + "/"):
    cab = {"User-Agent": UA_NAVEGADOR, "Accept-Language": "pt-BR,pt;q=0.9", "Referer": referer}
    if ajax:
        cab.update({"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    with _abrir(urllib.request.Request(url, headers=cab), timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def segundos(texto):
    """'00:25:29' -> 1529; '03:38' (pace) -> 218. Vazio ou '--' -> None."""
    partes = re.findall(r"\d+", texto or "")
    if not partes or len(partes) > 3:
        return None
    partes = [int(x) for x in partes]
    while len(partes) < 3:
        partes.insert(0, 0)
    h, m, s = partes
    total = h * 3600 + m * 60 + s
    return total or None


def pagina_do_evento(slug):
    """HTML da pagina que tem a tabela, seguindo o redirecionamento por link.

    Slug antigo vira uma pagina-casca com um unico link para o slug novo:
    "2026-maratona-internacional-de-floripa" aponta para "...-floripa-2026".
    """
    url = f"{BASE}/evento/{urllib.parse.quote(slug, safe='')}/"
    html = baixar(url)
    if 'id="tableResultados"' not in html and "genero=" not in html:
        outros = {u for u in re.findall(r'href="/evento/([^/"]+)/"', html) if u != slug}
        if len(outros) == 1:
            slug = outros.pop()
            url = f"{BASE}/evento/{urllib.parse.quote(slug, safe='')}/"
            html = baixar(url)
    return html, url, slug


def modalidades(html):
    """Nomes de modalidade como o portal os usa na query string, sem repetir."""
    vistas, saida = set(), []
    for bruto in re.findall(r'modalidade=([^&"]+)&(?:amp;)?genero=', html):
        nome = urllib.parse.unquote(entidades.unescape(bruto)).strip()
        if nome and nome != "0" and nome not in vistas:
            vistas.add(nome)
            saida.append(nome)
    return saida


def id_do_evento(html, url, modalidade):
    achado = re.search(r"id_evento=(\d+)", html)
    if achado:
        return achado.group(1)
    # Evento grande abre em cartoes; a tabela (e o id) so vem com uma
    # modalidade escolhida.
    com = baixar(f"{url}?modalidade={urllib.parse.quote(modalidade)}&genero=F", referer=url)
    achado = re.search(r"id_evento=(\d+)", com)
    return achado.group(1) if achado else None


LINHA = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELULA = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
PERFIL = re.compile(r'href="/resultados/([^/"]+)/"[^>]*>([^<]+)</a>')


def colunas(html):
    thead = re.search(r'id="tableResultados".*?<thead>(.*?)</thead>', html, re.S)
    if not thead:
        return []
    return [limpar(c).lower() for c in re.findall(r"<th[^>]*>(.*?)</th>", thead.group(1), re.S)]


def linhas_da_modalidade(id_evento, modalidade, sexo, cols, referer):
    """Todas as linhas de uma modalidade e um sexo, pagina a pagina."""
    idx = {c: i for i, c in enumerate(cols)}
    i_nome = idx.get("nome")
    i_tempo = next((i for c, i in idx.items() if c.startswith("tempo")), None)
    i_pace = idx.get("pace")
    i_cat = idx.get("cat.", idx.get("categoria"))
    i_eq = idx.get("equipe")
    i_pos = idx.get("geral", 0)
    if i_nome is None or i_tempo is None:
        return [], 0

    base = (f"{BASE}/ajax_resultados_evento.cfm?id_evento={id_evento}"
            f"&modalidade={urllib.parse.quote(modalidade)}&genero={sexo}")
    saida, offset, declarado = [], 0, 0
    for _ in range(400):                      # 40 mil linhas: nenhuma prova chega perto
        dados = json.loads(baixar(f"{base}&offset={offset}&limit={LIMITE}", ajax=True, referer=referer))
        declarado = dados.get("recordsTotal") or declarado
        trs = LINHA.findall(dados.get("html") or "")
        for tr in trs:
            tds = CELULA.findall(tr)
            if len(tds) <= max(i_nome, i_tempo):
                continue
            perfil = PERFIL.search(tds[i_nome])
            if not perfil:
                continue
            tempo = segundos(limpar(tds[i_tempo]))
            if not tempo:
                continue                      # sem tempo de chegada nao concluiu
            saida.append([
                perfil.group(1),
                " ".join(entidades.unescape(perfil.group(2)).split()),
                sexo,
                modalidade,
                limpar(tds[i_cat]) if i_cat is not None and i_cat < len(tds) else "",
                limpar(tds[i_eq]) if i_eq is not None and i_eq < len(tds) else "",
                int(limpar(tds[i_pos])) if i_pos < len(tds) and limpar(tds[i_pos]).isdigit() else None,
                tempo,
                segundos(limpar(tds[i_pace])) if i_pace is not None and i_pace < len(tds) else None,
            ])
        if not dados.get("hasMore") or not trs:
            break
        offset = int(dados.get("nextOffset") or offset + LIMITE)
        time.sleep(PAUSA)
    return saida, declarado


def coletar_prova(prova):
    """Baixa os resultados de uma prova. Devolve o registro a gravar."""
    html, url, slug_real = pagina_do_evento(prova["or_slug"])
    mods = modalidades(html)
    if not mods:
        return {"slug": prova["or_slug"], "erro": "sem modalidades na pagina"}
    ident = id_do_evento(html, url, mods[0])
    if not ident:
        return {"slug": prova["or_slug"], "erro": "sem id_evento"}
    cols = colunas(html)
    if not cols:
        com = baixar(f"{url}?modalidade={urllib.parse.quote(mods[0])}&genero=F", referer=url)
        cols = colunas(com)

    linhas, esperado = [], 0
    for modalidade in mods:
        for sexo in ("F", "M"):
            parte, declarado = linhas_da_modalidade(ident, modalidade, sexo, cols, url)
            linhas += parte
            esperado += declarado
            time.sleep(PAUSA)
    return {
        "slug": prova["or_slug"], "slug_real": slug_real, "id_evento": ident,
        "data": prova["data"], "nome": prova["nome"], "cidade": prova["cidade"],
        "coletado_em": datetime.date.today().isoformat(),
        "declarado": esperado, "linhas": linhas,
    }


def provas_alvo(historico, anos):
    hoje = datetime.date.today().isoformat()
    return [p for p in historico
            if p["ano"] in anos and p["data"] < hoje and p.get("or_slug")
            and p.get("concluintes_total") and not p.get("resultado_parcial")
            and "Treino" not in (p.get("tags") or [])]


def arquivo_de(slug):
    return PASTA / (re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") + ".json")


def coletar(anos, limite=None, registrar=print):
    PASTA.mkdir(parents=True, exist_ok=True)
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    alvo = provas_alvo(historico, anos)
    pendentes = [p for p in alvo if not arquivo_de(p["or_slug"]).exists()]
    registrar(f"{len(alvo)} provas de {', '.join(map(str, anos))} com resultado; "
              f"{len(pendentes)} ainda sem atletas")
    feitas, linhas_total = 0, 0
    for n, p in enumerate(pendentes[:limite] if limite else pendentes, 1):
        try:
            registro = coletar_prova(p)
        except Exception as erro:
            registrar(f"  {p['data']} {p['nome'][:40]}: FALHOU ({erro.__class__.__name__}: {erro})")
            continue
        if registro.get("erro"):
            registrar(f"  {p['data']} {p['nome'][:40]}: {registro['erro']}")
            # Grava a marca para nao tentar todo dia; apaga o arquivo para rever.
            arquivo_de(p["or_slug"]).write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")
            continue
        arquivo_de(p["or_slug"]).write_text(
            json.dumps(registro, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        feitas += 1
        linhas_total += len(registro["linhas"])
        falta = registro["declarado"] - len(registro["linhas"])
        aviso = f" (declarado {registro['declarado']}, {falta} sem tempo)" if falta > 5 else ""
        registrar(f"  {n}/{len(pendentes)} {p['data']} {p['nome'][:40]}: {len(registro['linhas'])} atletas{aviso}")
    registrar(f"provas baixadas: {feitas} | linhas: {linhas_total}")
    return feitas


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    anos = tuple(int(a) for a in sys.argv[1:]) or ANOS_ATLETAS
    coletar(anos)
