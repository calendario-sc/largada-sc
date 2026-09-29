#!/usr/bin/env python3
"""Paginas para o Google: uma por prova, uma por cidade, sitemap e robots.

O calendario (index/pr/todos) e montado no navegador a partir dos dados
embutidos -- otimo para filtrar, ruim para busca: nenhuma prova tinha endereco
proprio. Aqui cada prova ganha /provas/<slug>/ e cada cidade /corridas-em/<cidade-uf>/,
em HTML simples (sem JS), com titulo, descricao, dados estruturados (schema.org
SportsEvent) e links entre si. O sitemap.xml lista tudo para o Search Console.

Chamado pelo build.py. So biblioteca padrao.
"""

import datetime
import html
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from comum import sem_acento

AQUI = Path(__file__).resolve().parent
SITE = "https://www.cuponsdecorrida.com.br"
PASTA_PROVAS = AQUI / "provas"
PASTA_CIDADES = AQUI / "corridas-em"
UF_NOME = {"SC": "Santa Catarina", "PR": "Paraná"}
PAGINA_UF = {"SC": "/", "PR": "/pr.html"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
# Nunca linkar: agregadores concorrentes e fonte nao confiavel.
LINK_PROIBIDO = re.compile(r"corridasbr|corridassc|corridas-sc|catarinarun", re.I)

CSS = """*{box-sizing:border-box}
:root{--azul:#0A2F73;--azul2:#1450C8;--sol:#FFC21A;--ink:#0E1726;--ink2:#2E3A50;--muted:#5B6880;--line:#DDE3EC;--ground:#F4F6FA;--surface:#fff;--accent:#1450C8}
@media (prefers-color-scheme:dark){:root{--ink:#E8EDF6;--ink2:#C4CCDA;--muted:#8C97AA;--line:#223049;--ground:#0B1220;--surface:#121B2E;--accent:#8FB2FF}}
body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.55 "Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent)}
.topo{background:linear-gradient(135deg,var(--azul),var(--azul2));color:#fff}
.topo .w{display:flex;gap:1rem;align-items:center;justify-content:space-between;padding:.8rem 0}
.marca{font-family:"Archivo",system-ui,sans-serif;font-weight:800;font-size:1.25rem;color:#fff;text-decoration:none;letter-spacing:-.02em;white-space:nowrap}
.marca em{font-style:normal;color:var(--sol)}
.topo nav a{color:#fff;text-decoration:none;font-size:.9rem;margin-left:1rem;white-space:nowrap}
.topo nav a.cc{background:var(--sol);color:var(--azul);font-weight:700;border-radius:999px;padding:.35rem .8rem}
.faixa{height:5px;background:repeating-linear-gradient(90deg,#FFC21A 0 20px,#EF4E16 20px 40px)}
.w{width:min(960px,100% - 2rem);margin:0 auto}
.migalha{font-size:.82rem;color:var(--muted);margin:1rem 0 .4rem}
.migalha a{color:var(--muted)}
h1{font-family:"Archivo",system-ui,sans-serif;font-weight:800;letter-spacing:-.02em;line-height:1.1;font-size:clamp(1.7rem,4.5vw,2.5rem);margin:.2rem 0 .4rem}
.sub{color:var(--ink2);margin:0 0 1.2rem;font-size:1.02rem}
h2{font-family:"Archivo",system-ui,sans-serif;font-size:1.2rem;margin:1.8rem 0 .7rem}
.cartao{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem}
dl.fatos{display:grid;grid-template-columns:max-content 1fr;gap:.45rem 1rem;margin:0}
dl.fatos dt{color:var(--muted);font-size:.9rem}
dl.fatos dd{margin:0}
.pills span{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:.05rem .55rem;margin:0 .25rem .25rem 0;font-size:.88rem}
.acoes{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0 0}
.botao{display:inline-block;text-decoration:none;font-weight:700;border-radius:999px;padding:.6rem 1.1rem;background:var(--azul2);color:#fff}
.botao.sol{background:var(--sol);color:var(--azul)}
.botao.claro{background:none;color:var(--accent);border:1px solid var(--line)}
ul.lista{list-style:none;margin:0;padding:0}
ul.lista li{display:grid;grid-template-columns:6.5rem 1fr;gap:.8rem;padding:.6rem 0;border-bottom:1px solid var(--line)}
ul.lista li:last-child{border-bottom:0}
ul.lista time{font-size:.88rem;color:var(--muted);font-variant-numeric:tabular-nums}
ul.lista small{display:block;color:var(--muted);font-size:.85rem}
table.res{width:100%;border-collapse:collapse;font-size:.95rem}
table.res td,table.res th{padding:.4rem .3rem;border-bottom:1px solid var(--line);text-align:left}
table.res td.n,table.res th.n{text-align:right;font-variant-numeric:tabular-nums}
.nota{font-size:.85rem;color:var(--muted)}
.cidades{columns:2 12rem;font-size:.92rem}
.cidades a{display:block;padding:.15rem 0}
footer{margin:3rem 0 0;padding:1.4rem 0 2rem;border-top:1px solid var(--line);font-size:.88rem;color:var(--muted)}
footer a{color:var(--muted);margin-right:1rem}
@media (max-width:560px){.topo nav a:not(.cc){display:none} .marca{font-size:1.05rem} .topo nav a.cc{font-size:.8rem;padding:.3rem .65rem} ul.lista li{grid-template-columns:5.2rem 1fr} dl.fatos{grid-template-columns:1fr} dl.fatos dt{margin-top:.3rem}}
"""


def slug(texto):
    s = sem_acento(str(texto)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def slug_prova(p):
    """Endereco estavel: data + nome (+ cidade, se o nome nao a traz)."""
    nome, cidade = slug(p["nome"]), slug(p.get("cidade") or "")
    partes = [p["data"], nome] + ([cidade] if cidade and cidade not in nome else [])
    return "-".join(x for x in partes if x)[:90].strip("-")


def slug_cidade(cidade, uf):
    return f"{slug(cidade)}-{(uf or 'SC').lower()}"


def data_extenso(iso, semana=True):
    d = datetime.date.fromisoformat(iso)
    txt = f"{d.day} de {MESES[d.month - 1]} de {d.year}"
    return (SEMANA[d.weekday()] + ", " + txt) if semana else txt


def rotulo_km(k):
    """"21" -> "21 km"; "21,1" -> "21,1 km"; texto fica como veio."""
    k = str(k).strip()
    return k + " km" if re.fullmatch(r"\d+([.,]\d+)?", k) else k


def mil(n):
    return f"{n:,}".replace(",", ".")


def e(s):
    return html.escape(str(s or ""), quote=True)


def publicavel(p):
    return "Treino" not in (p.get("tags") or [])


def tipo_prova(p):
    tags = p.get("tags") or []
    if "Trail" in tags:
        return "corrida de trail"
    if "Caminhada" in tags and "Rua" not in tags:
        return "caminhada"
    return "corrida de rua"


def link_inscricao(p):
    perfil = p.get("perfil") or {}
    for url in (perfil.get("inscricao"), p.get("ts_url")):
        if url and url.startswith("http") and not LINK_PROIBIDO.search(url):
            return url
    return None


def preco(p):
    from build import _para_o_cartao          # mesma regra do cartao do calendario
    return (_para_o_cartao(p.get("perfil") or {}) or {}).get("preco")


def cabeca(titulo, descricao, caminho, ld, analytics, extra=""):
    url = SITE + caminho
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)}</title>
<meta name="description" content="{e(descricao)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Cupons de Corrida">
<meta property="og:locale" content="pt_BR">
<meta property="og:title" content="{e(titulo)}">
<meta property="og:description" content="{e(descricao)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{SITE}/og-cupons-de-corrida.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/provas.css">
{extra}<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")}</script>
{analytics}</head>
<body>
<header class="topo"><div class="w">
  <a class="marca" href="/">Cupons de <em>Corrida</em></a>
  <nav><a href="/">Santa Catarina</a><a href="/pr.html">Paraná</a><a class="cc" href="/cupons.html">% Central de Cupons</a></nav>
</div><div class="faixa"></div></header>
<main class="w">
"""


RODAPE = """</main>
<footer class="w">
  <p><a href="/">Calendário de corridas em SC</a><a href="/pr.html">Calendário de corridas no PR</a><a href="/cupons.html">Central de Cupons</a><a href="/atletas.html">Resultados por atleta</a><a href="/parceiros.html">Seja parceiro</a><a href="/privacidade.html">Privacidade</a></p>
  <p>Cupons de Corrida · calendário de corridas de rua e trail de Santa Catarina e do Paraná, com cupons de desconto nas inscrições.</p>
</footer>
</body>
</html>
"""


def migalha(itens):
    """[(nome, caminho ou None)] -> HTML + BreadcrumbList."""
    partes = [f'<a href="{e(c)}">{e(n)}</a>' if c else e(n) for n, c in itens]
    ld = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, **({"item": SITE + c} if c else {})} for i, (n, c) in enumerate(itens)]}
    return '<nav class="migalha" aria-label="Você está em">' + " › ".join(partes) + "</nav>\n", ld


def linha_prova(p, hoje):
    extra = [x for x in (p.get("cidade") + "/" + (p.get("uf") or "SC"), ", ".join(p.get("pills") or [])) if x]
    if p["data"] < hoje and p.get("concluintes_total"):
        extra.append(f"{p['concluintes_total']:,} concluintes".replace(",", "."))
    d = datetime.date.fromisoformat(p["data"])
    return (f'<li><time datetime="{p["data"]}">{d.day:02d}/{d.month:02d}/{d.year}</time>'
            f'<span><a href="/provas/{p["_slug"]}/">{e(p["nome"])}</a><small>{e(" · ".join(extra))}</small></span></li>')


def pagina_prova(p, provas_cidade, provas_regiao_mes, hoje, analytics):
    uf = p.get("uf") or "SC"
    cidade, regiao = p.get("cidade") or "", p.get("regiao") or ""
    futura = p["data"] >= hoje
    ano = p["ano"]
    nome = p["nome"]
    nome_ano = nome if str(ano) in nome else f"{nome} {ano}"
    tipo = tipo_prova(p)
    dists = p.get("pills") or []
    inscricao = link_inscricao(p) if futura else None
    valor = preco(p) if futura else None
    orgs = [o for o in (p.get("organizadores") or []) if o]
    conc = p.get("concluintes_total") if not futura else None

    if futura:
        titulo = f"{nome_ano} – {cidade}/{uf} | Inscrições e cupom"
        desc = (f"{nome_ano}: {tipo} em {cidade}/{uf}, {data_extenso(p['data'])}"
                + (f", {', '.join(dists)}" if dists else "") + ". Inscrições, preço, organização e cupom de desconto.")
    else:
        titulo = f"{nome_ano} – {cidade}/{uf} | Resultado" if conc else f"{nome_ano} – {cidade}/{uf}"
        desc = (f"{nome_ano}, {tipo} realizada em {cidade}/{uf} em {data_extenso(p['data'], False)}"
                + (f": {conc:,} concluintes".replace(",", ".") if conc else "") + (f", {', '.join(dists)}" if dists else "") + ".")
    caminho = f"/provas/{p['_slug']}/"
    cam_cidade = f"/corridas-em/{slug_cidade(cidade, uf)}/"
    mig_html, mig_ld = migalha([("Início", "/"), (UF_NOME.get(uf, uf), PAGINA_UF.get(uf, "/")), (cidade, cam_cidade), (nome_ano, None)])

    evento = {
        "@type": "SportsEvent", "name": nome_ano, "startDate": p["data"], "sport": "Corrida",
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"@type": "Place", "name": f"{cidade}, {UF_NOME.get(uf, uf)}",
                     "address": {"@type": "PostalAddress", "addressLocality": cidade, "addressRegion": uf, "addressCountry": "BR"}},
        "description": desc, "url": SITE + caminho,
    }
    if orgs:
        evento["organizer"] = [{"@type": "Organization", "name": o} for o in orgs]
    if inscricao:
        oferta = {"@type": "Offer", "url": inscricao, "availability": "https://schema.org/InStock", "priceCurrency": "BRL"}
        m = re.search(r"(\d+(?:[.,]\d{1,2})?)", str(valor or "").replace(".", "").replace(",", "."))
        if m:
            oferta["price"] = m.group(1)
        evento["offers"] = oferta
    ld = {"@context": "https://schema.org", "@graph": [evento, mig_ld]}

    fatos = [("Data", data_extenso(p["data"])),
             ("Local", f'<a href="{cam_cidade}">{e(cidade)}</a> · {e(UF_NOME.get(uf, uf))}' + (f" · região {e(regiao)}" if regiao else "")),
             ("Tipo", e(tipo.capitalize() + (" · " + ", ".join(t for t in p.get("tags") or [] if t not in ("Rua",)) if [t for t in p.get("tags") or [] if t != "Rua"] else "")))]
    if dists:
        fatos.append(("Distâncias", '<span class="pills">' + "".join(f"<span>{e(x)}</span>" for x in dists) + "</span>"))
    if orgs:
        fatos.append(("Organização", e(", ".join(orgs))))
    if valor:
        fatos.append(("Inscrição", "a partir de " + e(valor)))
    corpo = [mig_html, f"<h1>{e(nome_ano)}</h1>",
             f'<p class="sub">{e(tipo.capitalize())} em {e(cidade)}/{e(uf)} · {e(data_extenso(p["data"]))}</p>',
             '<section class="cartao"><dl class="fatos">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in fatos) + "</dl>"]
    acoes = []
    if futura:
        if inscricao:
            acoes.append(f'<a class="botao" href="{e(inscricao)}" rel="noopener nofollow" target="_blank">Fazer a inscrição</a>')
        acoes.append('<a class="botao sol" href="/cupons.html">Ver cupons de desconto</a>')
    elif p.get("or_slug") and conc:
        acoes.append(f'<a class="botao" href="/resultado.html?p={e(p["or_slug"])}">Ver a classificação completa</a>')
    acoes.append(f'<a class="botao claro" href="{PAGINA_UF.get(uf, "/")}">Calendário de {e(UF_NOME.get(uf, uf))}</a>')
    corpo.append('<div class="acoes">' + "".join(acoes) + "</div></section>")

    if conc:
        linhas = sorted((p.get("concluintes") or {}).items(), key=lambda x: -x[1])
        corpo.append("<h2>Resultado</h2>")
        genero = ""
        if p.get("concluintes_f") and p.get("concluintes_m"):
            genero = f": {mil(p['concluintes_f'])} mulheres e {mil(p['concluintes_m'])} homens"
        corpo.append(f'<p>{mil(conc)} atletas concluíram a prova{genero}.</p>')
        if linhas:
            corpo.append('<div class="cartao"><table class="res"><thead><tr><th>Distância</th><th class="n">Concluintes</th></tr></thead><tbody>'
                         + "".join(f'<tr><td>{e(rotulo_km(k))}</td><td class="n">{mil(v)}</td></tr>' for k, v in linhas) + "</tbody></table></div>")
    if futura:
        corpo.append(f'<p class="nota">Datas, distâncias e preços podem mudar: confirme sempre no site de inscrição. '
                     f'Viu algo errado? Escreva para <a href="mailto:contato@cuponsdecorrida.com.br">contato@cuponsdecorrida.com.br</a>.</p>')

    if provas_cidade:
        corpo.append(f"<h2>Outras corridas em {e(cidade)}</h2>")
        corpo.append('<div class="cartao"><ul class="lista">' + "".join(linha_prova(x, hoje) for x in provas_cidade) + "</ul></div>")
        corpo.append(f'<p><a href="{cam_cidade}">Todas as corridas em {e(cidade)} →</a></p>')
    if provas_regiao_mes:
        corpo.append(f"<h2>Mais corridas em {MESES[p['mes'] - 1]} de {ano} · {e(regiao or UF_NOME.get(uf, uf))}</h2>")
        corpo.append('<div class="cartao"><ul class="lista">' + "".join(linha_prova(x, hoje) for x in provas_regiao_mes) + "</ul></div>")

    return cabeca(titulo, desc, caminho, ld, analytics) + "\n".join(corpo) + RODAPE


def pagina_cidade(cidade, uf, provas, vizinhas, hoje, analytics):
    ano = int(hoje[:4])
    futuras = [p for p in provas if p["data"] >= hoje]
    passadas = [p for p in provas if p["data"] < hoje][::-1]
    caminho = f"/corridas-em/{slug_cidade(cidade, uf)}/"
    titulo = f"Corridas em {cidade} ({uf}) {ano} | Calendário de provas"
    desc = (f"Calendário de corridas de rua e trail em {cidade}/{uf}: "
            + (f"{len(futuras)} próximas provas, " if futuras else "")
            + f"datas, distâncias, inscrições, cupons de desconto e resultados das provas realizadas.")
    mig_html, mig_ld = migalha([("Início", "/"), (UF_NOME.get(uf, uf), PAGINA_UF.get(uf, "/")), (f"Corridas em {cidade}", None)])
    lista_ld = {"@type": "ItemList", "name": f"Próximas corridas em {cidade}", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "url": f"{SITE}/provas/{p['_slug']}/", "name": p["nome"]} for i, p in enumerate(futuras[:30])]}
    ld = {"@context": "https://schema.org", "@graph": [mig_ld, lista_ld]}
    corpo = [mig_html, f"<h1>Corridas em {e(cidade)}</h1>",
             f'<p class="sub">Calendário de corridas de rua, trail e caminhadas em {e(cidade)}/{e(uf)}'
             + (f" · região {e(provas[0].get('regiao'))}" if provas and provas[0].get("regiao") else "") + ".</p>"]
    if futuras:
        corpo.append(f"<h2>Próximas provas ({len(futuras)})</h2>")
        corpo.append('<div class="cartao"><ul class="lista">' + "".join(linha_prova(p, hoje) for p in futuras) + "</ul></div>")
        corpo.append('<div class="acoes"><a class="botao sol" href="/cupons.html">Ver cupons de desconto</a>'
                     f'<a class="botao claro" href="{PAGINA_UF.get(uf, "/")}">Calendário completo de {e(UF_NOME.get(uf, uf))}</a></div>')
    else:
        corpo.append(f'<p>Nenhuma prova futura em {e(cidade)} no calendário agora. '
                     f'<a href="{PAGINA_UF.get(uf, "/")}">Veja o calendário de {e(UF_NOME.get(uf, uf))}</a>.</p>')
    if passadas:
        corpo.append(f"<h2>Provas realizadas</h2>")
        corpo.append('<div class="cartao"><ul class="lista">' + "".join(linha_prova(p, hoje) for p in passadas[:60]) + "</ul></div>")
    if vizinhas:
        corpo.append("<h2>Cidades da mesma região</h2>")
        corpo.append('<div class="cidades">' + "".join(f'<a href="/corridas-em/{slug_cidade(c, u)}/">Corridas em {e(c)}</a>' for c, u in vizinhas) + "</div>")
    return cabeca(titulo, desc, caminho, ld, analytics) + "\n".join(corpo) + RODAPE


def gerar(historico, analytics=""):
    """Escreve provas/, corridas-em/, provas.css, sitemap.xml, robots.txt e 404.html.
    Devolve {uf: [(cidade, uf, n_futuras), ...]} para o rodape das paginas do calendario."""
    hoje = datetime.date.today().isoformat()
    provas = sorted((dict(p) for p in historico if publicavel(p)), key=lambda p: (p["data"], p["nome"]))
    vistos = set()
    for p in provas:
        s = slug_prova(p)
        while s in vistos:              # mesmo nome, dia e cidade (dois registros): o segundo ganha sufixo
            s += "-2"
        vistos.add(s)
        p["_slug"] = s

    por_cidade = defaultdict(list)
    por_regiao_mes = defaultdict(list)
    for p in provas:
        por_cidade[(p.get("cidade") or "", p.get("uf") or "SC")].append(p)
        por_regiao_mes[(p.get("regiao") or "", p.get("uf") or "SC", p["ano"], p["mes"])].append(p)
    cidades_da_regiao = defaultdict(set)
    for (c, u), ps in por_cidade.items():
        cidades_da_regiao[(ps[0].get("regiao") or "", u)].add((c, u))

    # So grava o que mudou (sao milhares de arquivos) e apaga as paginas que
    # sairam: prova que mudou de nome ou data some do endereco antigo.
    gravadas = set()

    def gravar(destino, texto):
        gravadas.add(destino.parent.name)
        if destino.exists() and destino.read_text(encoding="utf-8") == texto:
            return
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    for p in provas:
        mesma = [x for x in por_cidade[(p.get("cidade") or "", p.get("uf") or "SC")] if x is not p]
        futuras = [x for x in mesma if x["data"] >= hoje][:6]
        vizinhas = futuras or [x for x in mesma if x["data"] < hoje][::-1][:6]
        reg = [x for x in por_regiao_mes[(p.get("regiao") or "", p.get("uf") or "SC", p["ano"], p["mes"])]
               if x is not p and x.get("cidade") != p.get("cidade")][:8]
        gravar(PASTA_PROVAS / p["_slug"] / "index.html", pagina_prova(p, vizinhas, reg, hoje, analytics))

    for (c, u), ps in por_cidade.items():
        if not c:
            continue
        viz = sorted(cidades_da_regiao[(ps[0].get("regiao") or "", u)] - {(c, u)}, key=lambda x: sem_acento(x[0]))
        gravar(PASTA_CIDADES / slug_cidade(c, u) / "index.html", pagina_cidade(c, u, ps, viz[:30], hoje, analytics))
    for pasta in (PASTA_PROVAS, PASTA_CIDADES):
        for velha in pasta.iterdir() if pasta.exists() else []:
            if velha.is_dir() and velha.name not in gravadas:
                shutil.rmtree(velha)

    (AQUI / "provas.css").write_text(CSS, encoding="utf-8")

    # Sitemap: paginas fixas, cidades e provas (futuras primeiro na prioridade).
    urls = [("/", hoje, "1.0"), ("/pr.html", hoje, "0.9"), ("/todos.html", hoje, "0.6"), ("/cupons.html", hoje, "0.8"),
            ("/atletas.html", hoje, "0.6"), ("/parceiros.html", hoje, "0.5"), ("/privacidade.html", None, "0.2")]
    for (c, u), ps in sorted(por_cidade.items(), key=lambda x: -len(x[1])):
        if c:
            urls.append((f"/corridas-em/{slug_cidade(c, u)}/", max(x.get("visto_em") or x["data"] for x in ps), "0.7"))
    for p in provas:
        mod = max(x for x in (p.get("visto_em"), p.get("primeira_vez")) if x) if (p.get("visto_em") or p.get("primeira_vez")) else None
        urls.append((f"/provas/{p['_slug']}/", mod, "0.8" if p["data"] >= hoje else "0.4"))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, mod, pri in urls:
        xml.append(f"<url><loc>{SITE}{html.escape(u)}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + f"<priority>{pri}</priority></url>")
    xml.append("</urlset>")
    (AQUI / "sitemap.xml").write_text("\n".join(xml) + "\n", encoding="utf-8")
    (AQUI / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /area.html\nDisallow: /template.html\nDisallow: /artifact.html\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    (AQUI / "404.html").write_text(
        cabeca("Página não encontrada | Cupons de Corrida", "Esta página não existe mais. Veja o calendário de corridas de SC e do PR.",
               "/404.html", {"@context": "https://schema.org", "@type": "WebPage", "name": "Página não encontrada"}, analytics,
               '<meta name="robots" content="noindex">\n')
        + '<h1>Página não encontrada</h1><p>A prova pode ter mudado de nome ou de data. '
          'Procure no <a href="/">calendário de Santa Catarina</a>, no <a href="/pr.html">do Paraná</a> '
          'ou na <a href="/cupons.html">Central de Cupons</a>.</p>' + RODAPE, encoding="utf-8")

    ranking = defaultdict(list)
    for (c, u), ps in por_cidade.items():
        if c:
            ranking[u].append((c, u, sum(1 for x in ps if x["data"] >= hoje), len(ps)))
    for u in ranking:
        ranking[u].sort(key=lambda x: (-x[2], -x[3], sem_acento(x[0])))
    return {"slugs": {(p["data"], p["nome"], p.get("cidade")): p["_slug"] for p in provas}, "cidades": ranking,
            "total": len(provas), "n_cidades": sum(1 for c, _ in por_cidade if c), "n_urls": len(urls)}
