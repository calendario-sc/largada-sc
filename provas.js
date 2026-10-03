// Caixas de ofertas nas paginas de prova (bloco #ofertas, gerado pelo seo.py): produtos da vitrine das lojas
// parceiras (API /vitrine), alternando as lojas; o navegador guarda a vez e cada visita mostra os seguintes.
(async () => {
  const bloco = document.getElementById("ofertas"), lista = document.getElementById("ofertas-lista");
  if (!bloco || !lista) return;
  const API = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? "http://localhost:8787" : "https://api.cuponsdecorrida.com.br";
  const QUANTAS = 4;
  try {
    const d = await fetch(API + "/vitrine").then(r => r.json());
    const lojas = new Map();
    (d.produtos || []).forEach(p => (lojas.get(p.marca) || lojas.set(p.marca, []).get(p.marca)).push(p));
    if (!lojas.size) return;
    let vez = -1;
    try { vez = Number(localStorage.getItem("oferta-prova-vez") ?? -1); } catch (e) { /* sem armazenamento */ }
    vez = Number.isInteger(vez) && vez >= 0 ? vez + 1 : Math.floor(Math.random() * 1000);
    try { localStorage.setItem("oferta-prova-vez", String(vez)); } catch (e) { /* sem armazenamento */ }
    const porLoja = Math.ceil(QUANTAS / lojas.size), escolhidos = [];
    for (let k = 0; k < porLoja; k++) for (const ps of lojas.values()) {
      const p = ps[(vez * porLoja + k) % ps.length];
      if (escolhidos.length < QUANTAS && !escolhidos.includes(p)) escolhidos.push(p);
    }
    const el = (tag, cls, txt) => { const n = document.createElement(tag); if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };
    const reais = n => Number(n).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    lista.replaceChildren(...escolhidos.map(p => {
      const a = el("a", "oferta");
      a.href = p.link; a.target = "_blank"; a.rel = "noopener sponsored";
      const img = el("img"); img.src = p.imagem; img.alt = ""; img.width = 400; img.height = 400; img.loading = "lazy";
      const preco = el("span", "preco");
      if (p.preco_de > p.preco) preco.append(el("s", "", reais(p.preco_de)));
      preco.append(el("b", "", reais(p.preco) + (p.nota ? " " + p.nota : "")));
      if (p.desconto_pct) preco.append(el("span", "pct", "-" + p.desconto_pct + "%"));
      a.append(img, el("span", "rot", p.marca + " · em promoção"), el("span", "nome", p.nome), preco, el("span", "pe", "Ver na loja ↗"));
      a.onclick = () => { if (typeof gtag === "function") gtag("event", "oferta_prova_clique", { marca: p.marca, produto: p.nome }); };
      return a;
    }));
    bloco.hidden = false;
  } catch (e) { /* sem API: sem ofertas */ }
})();
