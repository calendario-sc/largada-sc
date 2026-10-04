#!/usr/bin/env python3
"""Monta as paginas a partir de template.html + corridas.json.

Gera dois arquivos com o mesmo conteudo:
  artifact.html - fragmento para publicar como Artifact (sem <html>/<head>/<body>)
  index.html    - pagina completa, abre direto no navegador

Uso:  python build.py
"""

import datetime
import shutil
import seo
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent

CABECALHO = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
"""


def data_coleta():
    marca = AQUI / "coletado_em.txt"
    iso = marca.read_text(encoding="utf-8").strip() if marca.exists() \
        else datetime.date.today().isoformat()
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


# O que nao conta para o "a partir de": o kit kids da NJR Run custa R$ 79 e o
# adulto R$ 139,90 -- o preco de entrada de um adulto e o que interessa.
NAO_E_ENTRADA = re.compile(r"kid|infantil|crian|pcd|idos|60\s*\+|cortesia|gratuit|elite|"
                           r"cadeirant|\bcad\b|\bdv\b|\bdi\b|isen", re.I)


def _valor(texto):
    achado = re.search(r"R\$\s*([\d.]+,\d{2}|[\d.]+)", texto or "")
    if not achado:
        return 0.0
    return float(achado.group(1).replace(".", "").replace(",", "."))


def _para_o_cartao(perfil):
    """Do perfil coletado, so o que vai no cartao de uma prova futura."""
    cartao = {}
    if perfil.get("inscricao"):
        cartao["inscricao"] = perfil["inscricao"]
        cartao["ticketeira"] = perfil.get("ticketeira", "")
    entrada = [x for x in perfil.get("precos") or []
               if _valor(x.get("preco")) > 0 and not NAO_E_ENTRADA.search(
                   f"{x.get('kit', '')} {x.get('modalidade', '')}")]
    if entrada:
        mais_barato = min(entrada, key=lambda x: _valor(x["preco"]))
        cartao["preco"] = mais_barato["preco"]
        if _valor(mais_barato.get("taxa")) > 0:
            cartao["taxa"] = True
    if perfil.get("regulamento"):
        cartao["regulamento"] = perfil["regulamento"]
    return cartao


# A area de BI (bi.cuponsdecorrida.com.br) e um repositorio privado ao lado
# deste, publicado pelo Cloudflare Pages atras de login. Quando a pasta
# existe, o build escreve la a pagina completa.
BI_DIR = AQUI.parent / "cupons-bi"
# O que so a pagina de BI leva: quem vende a inscricao, quem cronometra e
# quem fotografa cada prova.
# Fontes que a coleta usa e o BI mostra, mas que nao aparecem na pagina publica (pedido do dono em 04/10/2026).
FONTES_OCULTAS = {"roadrunners"}
CAMPOS_BI = ("ticketeira", "cronometragem", "fotografia", "locais", "locais_km", "largada", "local_banlek")


def dados_floripa():
    """O mapa do Raio-X Floripa: contorno projetado e os pontos da cidade."""
    import math
    import locais_floripa
    contorno = json.loads((AQUI / "floripa_contorno.json").read_text(encoding="utf-8"))
    escala = contorno["w"] / ((contorno["lon1"] - contorno["lon0"]) * math.cos(math.radians(contorno["lat_ref"])))
    pontos = []
    for nome, lat, lon, _rx in locais_floripa.LOCAIS:
        x = (lon - contorno["lon0"]) * math.cos(math.radians(contorno["lat_ref"])) * escala
        y = (contorno["lat1"] - lat) * escala
        pontos.append({"nome": nome, "x": round(x, 1), "y": round(y, 1)})
    return json.dumps({"w": contorno["w"], "h": contorno["h"], "aneis": contorno["aneis"], "pontos": pontos},
                      ensure_ascii=False, separators=(",", ":"))


def dados_da_pagina(historico, bi=True):
    """O historico guarda o perfil inteiro; a pagina leva so o que mostra.

    O perfil completo acrescentava ~430 KB, quase tudo campo vazio ou de
    prova ja realizada -- peso a toa no celular. Sem bi, saem tambem os
    campos que so os paineis restritos usam.
    """
    hoje = datetime.date.today().isoformat()
    for p in historico:
        perfil = p.pop("perfil", None)
        for campo in ("perfil_em", "ts_id", "ts_url", "rr_slug", "inscricao_url", "resultado_url", "link_resultado_em", "cronometragem_url", "cronometragem_em",
                      "fotografia_em", "fotografia_detalhe", "maissport_tentado",
                      "largada_em", "local_texto", "local_texto_em", "permit_status", "organizador_fca"):
            p.pop(campo, None)
        # Resultado lido direto na cronometradora: ela e a cronometragem.
        if not p.get("cronometragem") and p.get("fonte_resultado") in ("supercrono", "chiprun"):
            p["cronometragem"] = {"supercrono": "Super Crono", "chiprun": "ChipRun"}[p["fonte_resultado"]]
        # Ticketeira de toda prova que tem uma: e o que alimenta o grafico de
        # participacao. Prova listada pelo Ticket Sports vende por ele mesmo
        # quando o perfil nao achou o link.
        fontes = p.get("fontes") or []
        ticketeira = (perfil or {}).get("ticketeira") or (
            "Ticket Sports" if "ticketsports" in fontes else "MovNow" if "movnow" in fontes
            else "Sympla" if "sympla" in fontes else "Blueticket" if "blueticket" in fontes else "")
        if ticketeira:
            p["ticketeira"] = ticketeira
        if perfil and p["data"] >= hoje:
            cartao = _para_o_cartao(perfil)
            if cartao:
                p["cartao"] = cartao
        if not bi:
            for campo in CAMPOS_BI:
                p.pop(campo, None)
            # Fonte que continua sendo coletada, mas nao e informada na pagina publica.
            if any(f in FONTES_OCULTAS for f in fontes):
                p["fontes"] = [f for f in fontes if f not in FONTES_OCULTAS]
    return json.dumps(historico, ensure_ascii=False, separators=(",", ":"))


# Pedacos do template que so existem na pagina de BI. O JS tolera a falta
# deles (ver `ao` e `BI` no template).
SO_BI = [
    r'[ \t]*<button class="chip" id="btn-comparativo"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-ticketeiras"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-crono"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-foto"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-raiox"[^\n]*\n',
    r'[ \t]*<a class="chip" id="btn-patrocinios"[^\n]*\n',
    r'[ \t]*<button class="chip" id="btn-cupons"[^\n]*\n',
    r'<dialog class="orgs cp" id="cupons".*?</dialog>\n\n',
    r'[ \t]*<button class="chip" id="btn-empresas"[^\n]*\n',
    r'<dialog class="orgs cp" id="empresas".*?</dialog>\n\n',
    r'<!-- painel do BI -->.*?</script>\n?',
    r'[ \t]*<button class="chip" id="btn-fotos"[^\n]*\n',
    r'<dialog class="orgs cp" id="fotos".*?</dialog>\n\n',
    r'[ \t]*<button class="chip" id="btn-leads"[^\n]*\n',
    r'<dialog class="orgs ld" id="leads".*?</dialog>\n\n',
    r'[ \t]*<button class="chip" id="btn-assessorias"[^\n]*\n',
    r'<dialog class="orgs as" id="assess".*?</dialog>\n\n',
    r'<section class="rel" id="rel-assess"[^\n]*\n',
    r'<dialog class="orgs rx" id="raiox".*?</dialog>\n\n',
    r'<section class="rel" id="rel-raiox"[^\n]*\n',
    r'  <section class="comparativo" id="comparativo".*?\n  </section>\n',
    r'<dialog class="orgs tk" id="tk".*?</dialog>\n\n',
    r'<dialog class="orgs tk" id="crono".*?</dialog>\n\n',
    r'<dialog class="orgs tk" id="foto".*?</dialog>\n\n',
    r'<dialog class="orgs" id="orgs".*?</dialog>\n',
    r'<section class="rel" id="rel-orgs"[^\n]*\n',
]
# O texto do rodape (fontes, cobertura, area restrita) fica so no BI; o
# publico leva so a assinatura.
RODAPE = re.compile(r'<footer class="foot">.*?</footer>', re.S)
RODAPE_PUBLICO = ('<footer class="foot">\n  <div class="wrap">\n'
                  '    <p><b>Cupons de Corrida</b> · <a href="cupons.html">Central de Cupons</a>'
                  ' · <a href="parceiros.html">Seja parceiro</a></p>\n  </div>\n</footer>')
STAT_ORGS = re.compile(r'<button class="stat stat--btn" id="stat-orgs".*?</button>', re.S)


def so_publico(pagina):
    """A pagina publica: sem os paineis de BI e sem o clique nas organizadoras."""
    for padrao in SO_BI:
        pagina, n = re.subn(padrao, "", pagina, count=1, flags=re.S)
        if n != 1:
            raise SystemExit(f"template.html: nao achei o trecho de BI {padrao[:40]!r}")
    pagina, n = STAT_ORGS.subn('<div class="stat"><b id="s-orgs">0</b><span>organizadoras</span></div>', pagina, count=1)
    if n != 1:
        raise SystemExit("template.html: nao achei a caixa das organizadoras")
    pagina, n = RODAPE.subn(lambda m: RODAPE_PUBLICO, pagina, count=1)
    if n != 1:
        raise SystemExit("template.html: nao achei o rodape")
    return pagina


# Google Analytics: so nas paginas publicas. O BI e privado e os acessos
# da equipe nao entram na conta do publico.
GOOGLE_ANALYTICS = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-P0JZLDPQ7W"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-P0JZLDPQ7W');
</script>
"""


def completa(pagina, publica=False, uf="SC", seo_info=None):
    """A pagina standalone precisa do <head>: o <style> sobe para dentro dele."""
    estilo, corpo = pagina.split("</style>", 1)
    if publica:
        titulo, cabeca = cabeca_publica(uf, seo_info or {})
        estilo = estilo.replace("<title>Cupons de Corrida</title>", f"<title>{titulo}</title>", 1)
    else:
        cabeca = '<meta name="robots" content="noindex">\n'
    return (CABECALHO + cabeca + (GOOGLE_ANALYTICS if publica else "") + estilo
            + "</style>\n</head>\n<body>\n" + corpo + "\n</body>\n</html>\n")


# Uma pagina por estado: o seletor do cabecalho troca de pagina. Cada uma
# leva so as provas do seu estado, e a de SC continua sendo a index.
PAGINAS = [("index.html", "SC"), ("pr.html", "PR"), ("rs.html", "RS"), ("todos.html", "")]
PAGINAS_HTML = [arquivo for arquivo, _ in PAGINAS]


# Titulo, descricao e dados estruturados de cada pagina publica do calendario.
UF_TITULO = {"SC": ("Calendário de Corridas em SC {ano} | Cupons de Corrida", "Santa Catarina", "/"),
             "PR": ("Calendário de Corridas no Paraná {ano} | Cupons de Corrida", "Paraná", "/pr.html"),
             "RS": ("Calendário de Corridas no Rio Grande do Sul {ano} | Cupons de Corrida", "Rio Grande do Sul", "/rs.html"),
             "": ("Corridas de Rua na Região Sul {ano}: SC, PR e RS | Cupons de Corrida", "Santa Catarina, Paraná e Rio Grande do Sul", "/todos.html")}


def cabeca_publica(uf, info):
    import html as _h
    ano = datetime.date.today().year
    titulo, lugar, caminho = UF_TITULO[uf]
    titulo = titulo.format(ano=ano)
    cidades = [c for u, lista in (info.get("cidades") or {}).items() if not uf or u == uf for c, _, fut, _ in lista if fut][:3]
    n_cid = sum(1 for u, lista in (info.get("cidades") or {}).items() if not uf or u == uf for _ in lista)
    desc = (f"Calendário completo de corridas de rua e trail em {lugar} {ano}: datas, distâncias, inscrições, "
            f"resultados e cupons de desconto" + (f" em {', '.join(cidades)} e mais {max(n_cid - len(cidades), 0)} cidades." if cidades else "."))
    url = seo.SITE + caminho
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Cupons de Corrida", "url": seo.SITE + "/", "inLanguage": "pt-BR"},
        {"@type": "Organization", "name": "Cupons de Corrida", "url": seo.SITE + "/", "logo": seo.SITE + "/og-cupons-de-corrida.png",
         "email": "contato@cuponsdecorrida.com.br"},
        {"@type": "WebPage", "name": titulo, "url": url, "description": desc}]}
    e = lambda s: _h.escape(s, quote=True)
    cabeca = (f'<meta name="description" content="{e(desc)}">\n<link rel="canonical" href="{e(url)}">\n'
              f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="Cupons de Corrida">\n'
              f'<meta property="og:locale" content="pt_BR">\n<meta property="og:title" content="{e(titulo)}">\n'
              f'<meta property="og:description" content="{e(desc)}">\n<meta property="og:url" content="{e(url)}">\n'
              f'<meta property="og:image" content="{seo.SITE}/og-cupons-de-corrida.png">\n<meta name="twitter:card" content="summary_large_image">\n'
              f'<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
              f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False, separators=(",", ":"))}</script>\n')
    return e(titulo), cabeca


def rodape_cidades(uf, info):
    """Links para as paginas de cidade (seo.py): o Google chega nelas pelo calendario."""
    lista = [(c, u) for u2, l in (info.get("cidades") or {}).items() if not uf or u2 == uf for c, u, fut, n in l][:48]
    if not lista:
        return ""
    import html as _h
    links = " · ".join(f'<a href="/corridas-em/{seo.slug_cidade(c, u)}/">{_h.escape(c)}</a>' for c, u in lista)
    return f'    <p class="foot__cidades"><b>Corridas por cidade:</b> {links}</p>\n'


def build():
    template = (AQUI / "template.html").read_text(encoding="utf-8")
    for marcador in ("__DATA__", "__COLETA__", "__BI__", "__FLORIPA__", "__UF__"):
        if marcador not in template:
            raise SystemExit(f"template.html perdeu o marcador {marcador}")
    historico = json.loads((AQUI / "corridas.json").read_text(encoding="utf-8"))
    # Paginas de prova e de cidade, sitemap e robots (seo.py). O calendario
    # linka cada prova pela pagina dela (campo "pg").
    seo_info = seo.gerar(historico, GOOGLE_ANALYTICS)
    for p in historico:
        pg = seo_info["slugs"].get((p["data"], p["nome"], p.get("cidade")))
        if pg:
            p["pg"] = pg
    coleta = data_coleta()
    publico = so_publico(template)

    # Provas futuras, leves, para o painel do parceiro (parceiros.html) escolher
    # em que provas vale o cupom. A chave "data|nome" e a mesma do calendario.
    hoje = datetime.date.today().isoformat()
    futuras = sorted(({"chave": p["data"] + "|" + p["nome"], "data": p["data"], "nome": p["nome"],
                       "cidade": p.get("cidade") or "", "uf": p.get("uf") or "SC", "org": p.get("organizadores") or []}
                      for p in historico if p["data"] >= hoje and "Treino" not in (p.get("tags") or [])),
                     key=lambda x: (x["data"], x["nome"]))
    (AQUI / "provas-futuras.json").write_text(json.dumps(futuras, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tamanho = 0
    for arquivo, uf in PAGINAS:
        provas = [p for p in historico if not uf or (p.get("uf") or "SC") == uf]
        floripa = dados_floripa() if uf in ("SC", "") else "null"      # o Raio-X e de Florianopolis

        # Pagina de BI: tudo. A de SC vai tambem para o Artifact (privado do
        # dono); todas vao para o repositorio privado, se a pasta existir.
        dados_bi = dados_da_pagina(json.loads(json.dumps(provas)), bi=True)
        pagina_bi = (template.replace("__COLETA__", coleta).replace("__DATA__", dados_bi).replace("__BI__", "true")
                     .replace("__FLORIPA__", floripa).replace("__UF__", uf))
        if arquivo == "index.html":
            (AQUI / "artifact.html").write_text(pagina_bi, encoding="utf-8")
            tamanho = len(pagina_bi)
        if BI_DIR.is_dir():
            # No BI o calendario mora em /corridas/ (a raiz e a Visao geral dos
            # modulos); os arquivos de apoio continuam na raiz.
            (BI_DIR / "corridas").mkdir(exist_ok=True)
            pagina_bi_dir = (completa(pagina_bi).replace('src="cadastro.js"', 'src="/cadastro.js"')
                             .replace('href="cupons.html"', 'href="/cupons.html"')
                             .replace('fetch("assessorias.json"', 'fetch("/assessorias.json"'))
            (BI_DIR / "corridas" / arquivo).write_text(pagina_bi_dir, encoding="utf-8")
            # O formulario de cadastro e um arquivo a parte, usado pelas paginas.
            (BI_DIR / "cadastro.js").write_text((AQUI / "cadastro.js").read_text(encoding="utf-8"), encoding="utf-8")
            # Central de Cupons: o botao do topo aponta para ela tambem no BI
            # (sem o Google Analytics, que e so do publico).
            central = (AQUI / "cupons.html").read_text(encoding="utf-8")
            if GOOGLE_ANALYTICS not in central:
                raise SystemExit("cupons.html: trecho do Google Analytics diferente do build.py")
            (BI_DIR / "cupons.html").write_text(central.replace(GOOGLE_ANALYTICS, ""), encoding="utf-8")
            shutil.copyfile(AQUI / "logo-cupons-de-corrida.png", BI_DIR / "logo-cupons-de-corrida.png")

        # Pagina publica: sem os paineis e sem os campos de BI.
        # Copia: dados_da_pagina tira campos, e a proxima pagina precisa deles.
        dados_pub = dados_da_pagina(json.loads(json.dumps(provas)), bi=False)
        pagina_pub = (publico.replace("__COLETA__", coleta).replace("__DATA__", dados_pub).replace("__BI__", "false")
                      .replace("__FLORIPA__", "null").replace("__UF__", uf))
        pagina_pub = pagina_pub.replace(RODAPE_PUBLICO, RODAPE_PUBLICO.replace("  </div>\n</footer>", rodape_cidades(uf, seo_info) + "  </div>\n</footer>"), 1)
        (AQUI / arquivo).write_text(completa(pagina_pub, publica=True, uf=uf, seo_info=seo_info), encoding="utf-8")

    return tamanho


if __name__ == "__main__":
    tamanho = build()
    print(f"index.html (publica) e artifact.html (BI) gerados ({tamanho:,} bytes, coleta de {data_coleta()})"
          + (f" | BI tambem em {BI_DIR}" if BI_DIR.is_dir() else ""))
    sys.exit(0)
