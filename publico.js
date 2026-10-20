// Layout novo do site publico (19/10/2026): monta a barra superior, o hero e a coluna lateral em cima do
// calendario que ja existe. Nada do comportamento muda: o JavaScript do calendario continua dono dos filtros,
// da lista e dos paineis; aqui so se movem blocos de lugar e se embrulham os filtros em menus suspensos.
// No BI (body.bi) nao faz nada.
(() => {
  if (document.body.classList.contains("bi") || (typeof BI !== "undefined" && BI)) return;
  const el = (tag, props = {}, kids = []) => { const n = Object.assign(document.createElement(tag), props); kids.forEach(k => k && n.append(k)); return n; };
  const $ = id => document.getElementById(id);
  const top = document.querySelector("header.top"), inner = top && top.querySelector(".top__inner");
  if (!top || !inner) return;

  // ---- barra superior: logo, menu, estado, area do atleta, criar perfil ----
  const ufs = [...document.querySelectorAll("nav.uf a")];
  const ufPagina = typeof UF !== "undefined" ? UF : "";          // const UF do script do calendario
  const atual = ufs.find(a => (a.dataset.uf || "") === ufPagina);
  const sel = el("select", { ariaLabel: "Estado" }, ufs.map(a => el("option", { value: a.getAttribute("href"), textContent: a.textContent, selected: a === atual })));
  sel.onchange = () => { location.href = sel.value; };
  const pino = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  pino.setAttribute("viewBox", "0 0 24 24"); pino.innerHTML = '<path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z"/>';
  const entrar = el("a", { className: "entrar-topo", href: "area.html" }, [el("span", { textContent: "Área do atleta" })]);
  entrar.setAttribute("data-entrar", "");
  const perfil = el("button", { className: "cta-cadastro", type: "button", textContent: "Criar perfil grátis", hidden: true });
  perfil.setAttribute("data-cadastro", "nav");
  const links = el("ul", { className: "pub-nav__links" }, [
    el("li", {}, [el("a", { href: "./", textContent: "Calendário" })]),
    el("li", {}, [el("a", { href: "cupons.html", textContent: "Cupons" })]),
    el("li", {}, [el("a", { href: "#resultados", textContent: "Resultados" })]),
    el("li", {}, [el("a", { href: "ranking.html", textContent: "Ranking" })]),
  ]);
  links.querySelector("a").setAttribute("aria-current", "page");
  links.querySelector('a[href="#resultados"]').onclick = e => { e.preventDefault(); const b = $("btn-resultados"); if (b) b.click(); else location.href = "atletas.html"; };
  const menu = el("button", { className: "pub-menu", type: "button", ariaLabel: "Menu" });
  menu.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
  const nav = el("nav", { className: "pub-nav", ariaLabel: "Principal" }, [el("div", { className: "wrap pub-nav__in" }, [
    el("a", { className: "pub-nav__logo", href: "./" }, [el("picture", {}, [
      Object.assign(document.createElement("source"), { srcset: "logo-cupons-de-corrida.png", media: "(prefers-color-scheme: dark)" }),
      el("img", { src: "logo-cupons-de-corrida-escuro.png", alt: "Cupons de Corrida", width: 960, height: 221 })])]),
    links, el("label", { className: "pub-uf" }, [pino, sel]), entrar, perfil, menu])]);
  menu.onclick = () => nav.classList.toggle("aberto");
  top.before(nav);

  // ---- hero: titulo, frase e a barra de busca (o #bar sai de baixo da pagina e sobe para ca) ----
  const marca = inner.querySelector(":scope > div:first-child");
  const h1 = marca.querySelector("h1");
  h1.after(el("p", { className: "pub-titulo" }, [document.createTextNode("Encontre sua próxima "), el("em", { textContent: "corrida" })]));
  const lede = marca.querySelector(".lede"); if (lede) lede.textContent = "Provas de rua e trail, com datas, distâncias e inscrições em um só lugar.";
  const bar = $("bar");
  const busca = el("div", { className: "pub-busca" });
  marca.append(busca);
  if (bar) {
    busca.append(bar);
    // cada grupo de filtros vira um menu suspenso: Periodo, Regiao, Distancia, Tipo
    const nomes = { "g-escopo": "Período", "g-regiao": "Região", "g-faixa": "Distância", "g-tipo": "Tipo" };
    const dds = [];
    Object.entries(nomes).forEach(([id, rotulo]) => {
      const g = $(id); if (!g) return;
      const dd = el("div", { className: "pub-dd" });
      const btn = el("button", { className: "pub-dd__btn", type: "button", textContent: rotulo });
      btn.setAttribute("aria-expanded", "false");
      const painel = el("div", { className: "pub-dd__menu" });
      g.before(dd); dd.append(btn, painel); painel.append(g);
      btn.onclick = e => { e.stopPropagation(); const abre = !dd.classList.contains("open"); dds.forEach(x => x.classList.remove("open")); dd.classList.toggle("open", abre); btn.setAttribute("aria-expanded", String(abre)); };
      dds.push(dd);
    });
    document.addEventListener("click", e => { if (!e.target.closest(".pub-dd")) dds.forEach(x => x.classList.remove("open")); });
    document.addEventListener("keydown", e => { if (e.key === "Escape") dds.forEach(x => x.classList.remove("open")); });
    const filtrar = el("button", { className: "pub-filtrar", type: "button", textContent: "Filtrar" });
    filtrar.onclick = () => { dds.forEach(x => x.classList.remove("open")); const l = $("list"); if (l) l.scrollIntoView({ behavior: "smooth", block: "start" }); };
    const grupos = bar.querySelector(".groups"); if (grupos) grupos.append(filtrar);
    // menu com filtro marcado fica destacado (o calendario marca os chips com aria-pressed)
    const marcar = () => dds.forEach(dd => dd.classList.toggle("ativo", !!dd.querySelector('.chip[aria-pressed="true"]:not(#esc-proximas)') && !/^(Próximas)$/.test((dd.querySelector('.escopo .chip[aria-pressed="true"]') || {}).textContent || "")));
    new MutationObserver(marcar).observe(bar, { subtree: true, attributes: true, attributeFilter: ["aria-pressed"] });
    marcar();
  }
  inner.append(el("div", { className: "pub-ilustra", ariaHidden: "true" }));   // coluna da direita da grade do hero
  // o eyebrow fica so "Calendario de corridas · Estado": o texto solto depois do estado sai
  const eyebrow = marca.querySelector(".eyebrow");
  if (eyebrow) [...eyebrow.childNodes].forEach(n => { if (n.nodeType === 3 && n.previousSibling) n.remove(); });
  // atalhos (ano, cidade, empresa, resultados, PDF, agenda) e o botao do app descem para uma faixa abaixo do hero
  const acoes = inner.querySelector(".top__acoes"), ctas = marca.querySelector(".top__ctas");
  const faixa = el("div", { className: "pub-ferramentas" }, [el("div", { className: "wrap pub-ferramentas__in" }, [acoes, ctas])]);
  top.after(faixa);

  // ---- lista: titulo "Proximas corridas", meses, grade com a coluna lateral ----
  const pulse = document.querySelector(".pulse"), main = document.querySelector("main.results");
  if (pulse && main) {
    const n = el("span", { className: "pub-n" });
    const cab = el("div", { className: "pub-lista-cab" }, [el("h2", { textContent: "Próximas corridas" }), n]);
    pulse.prepend(cab);
    const count = $("count");
    const titulo = cab.querySelector("h2");
    const atualizar = () => {
      const t = (count && count.textContent) || "";
      const m = t.match(/^([\d.]+)\s+(\w+)/);
      n.textContent = m ? m[1] + " " + m[2] : "";
      const chip = document.querySelector('.escopo .chip[aria-pressed="true"]');
      titulo.textContent = chip && /realizadas/i.test(chip.textContent) ? "Corridas realizadas" : chip && /todas/i.test(chip.textContent) ? "Todas as corridas" : "Próximas corridas";
    };
    if (count) new MutationObserver(atualizar).observe(count, { childList: true, characterData: true, subtree: true });
    atualizar();
    const grid = el("div", { className: "wrap pub-grid" });
    main.before(grid); grid.append(main);
    const lado = el("aside", { className: "pub-lado" }, [
      el("div", { className: "pub-eco" }, [el("small", { textContent: "Cupons de Corrida" }), el("b", { textContent: "Economize na sua próxima prova" }),
        el("p", { textContent: "Cupons e descontos em inscrições de corridas em SC, PR, RS e SP." }), el("a", { href: "cupons.html", textContent: "Ver cupons" })]),
    ]);
    const perfil = document.querySelector(".perfil-cta");
    if (perfil) { const caixa = perfil.parentElement; lado.append(perfil); if (caixa && caixa.classList.contains("wrap") && !caixa.children.length) caixa.remove(); }
    grid.append(lado);
    // destaques antes do rodape
    const feats = el("div", { className: "wrap pub-feats" }, [
      ["Todos os tipos de prova", "Rua e trail", "M2 20 9 6l4 7 2.5-4L22 20H2Z"],
      ["Descubra novas cidades", "Explore o Sul e São Paulo correndo", "M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z"],
      ["Uma comunidade maior", "Mais corridas, mais histórias", "M7 3h10v2h3v4a4 4 0 0 1-4 4h-.3A5 5 0 0 1 13 15.9V18h3v2H8v-2h3v-2.1A5 5 0 0 1 8.3 13H8a4 4 0 0 1-4-4V5h3V3Zm10 4v4a2 2 0 0 0 2-2V7h-2ZM5 7v2a2 2 0 0 0 2 2V7H5Z"],
    ].map(([b, s, d]) => el("div", { className: "pub-feat", style: "--ico:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='" + d + "'/%3E%3C/svg%3E\")" }, [el("i"), el("div", {}, [el("b", { textContent: b }), el("span", { textContent: s })])])));
    const foot = document.querySelector("footer.foot"); if (foot) foot.before(feats);
  }

  // ---- cartoes: icone do tipo e botao "Ver prova" quando nao ha inscricao ----
  const lista = $("list");
  const completar = () => lista.querySelectorAll(".race:not(.pub-ok)").forEach(r => {
    r.classList.add("pub-ok");
    const tags = [...r.querySelectorAll(".race__meta .tag")].map(t => t.className);
    const tipo = tags.some(c => /tag--trail/.test(c)) ? "trail" : tags.some(c => /tag--caminhada/.test(c)) ? "caminhada" : tags.some(c => /tag--treino/.test(c)) ? "treino" : "";
    const ico = el("span", { className: "pub-ico" + (tipo ? " pub-ico--" + tipo : ""), ariaHidden: "true" });
    const date = r.querySelector(".race__date"); if (date) date.after(ico);
    if (!r.querySelector(".race__acoes .inscrever")) {
      const a = r.querySelector(".race__name a");
      if (a) r.append(el("a", { className: "pub-ver", href: a.href, textContent: r.classList.contains("passada") ? "Ver resultado" : "Ver prova" }));
    }
  });
  if (lista) { new MutationObserver(completar).observe(lista, { childList: true }); completar(); }
})();
