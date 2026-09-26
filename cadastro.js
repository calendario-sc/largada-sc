/* Cadastro de atletas (newsletter + cupons), comum a todas as paginas.
   Qualquer elemento com [data-cadastro] abre o formulario. O envio vai para
   a API (Cloudflare Worker); o cadastro so vale depois do clique no link do
   e-mail. Na volta, ?cadastro=confirmado|expirado|invalido mostra o aviso. */
(() => {
  const LOCAL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  const API = LOCAL ? "http://localhost:8787" : "https://api.cuponsdecorrida.com.br";
  // Chave publica do Turnstile (anti-robo). Em localhost, a chave de teste.
  const TURNSTILE = LOCAL ? "1x00000000000000000000AA" : "0x4AAAAAAB_CHAVE_PUBLICA";
  const PRIVACIDADE = "https://www.cuponsdecorrida.com.br/privacidade.html";
  const DISTANCIAS = [["5k", "5 km"], ["10k", "10 km"], ["21k", "Meia (21 km)"], ["42k", "Maratona"],
                      ["trail", "Trail"], ["ultra", "Ultra"]];

  const css = `
.cta-cadastro{display:inline-flex; align-items:center; gap:.45rem; margin-top:1rem; font:inherit; font-weight:700; font-size:.95rem;
  cursor:pointer; border:0; border-radius:999px; padding:.65rem 1.15rem; background:#FFC21A; color:#0A2F73;
  box-shadow:0 6px 18px rgba(0,0,0,.18)}
.cta-cadastro:hover{background:#FFD24D}
.cta-cadastro::before{content:"%"; display:inline-grid; place-items:center; width:1.35rem; height:1.35rem; border-radius:50%;
  background:#0A2F73; color:#FFC21A; font-size:.8rem}
.cad{border:0; padding:0; border-radius:18px; width:min(30rem, calc(100% - 1.5rem)); max-height:calc(100vh - 1.5rem);
  background:var(--surface,#fff); color:var(--ink,#0E1726); box-shadow:0 24px 60px rgba(0,0,0,.35)}
.cad::backdrop{background:rgba(10,20,40,.55)}
.cad{overflow-x:hidden}
.cad__captcha{max-width:100%; overflow:hidden}
.cad__topo{background:#0A2F73; color:#fff; padding:1.1rem 1.3rem .9rem; position:relative}
.cad__topo::after{content:""; position:absolute; left:0; right:0; bottom:-6px; height:6px;
  background:repeating-linear-gradient(90deg,#FFC21A 0 20px,#EF4E16 20px 40px)}
.cad__topo h2{margin:0; font-size:1.35rem; font-weight:800; letter-spacing:-.02em}
.cad__topo p{margin:.3rem 0 0; font-size:.88rem; opacity:.85}
.cad__fechar{position:absolute; top:.7rem; right:.8rem; border:0; background:none; color:#fff; font-size:1.4rem; cursor:pointer; line-height:1}
.cad form{padding:1.4rem 1.3rem 1.2rem; display:grid; gap:.75rem}
.cad label.campo{display:grid; gap:.25rem; font-size:.8rem; font-weight:600; color:var(--ink-2,#2E3A50)}
.cad input[type=text],.cad input[type=email],.cad input[type=tel],.cad select{font:inherit; font-size:.95rem; padding:.6rem .7rem;
  border-radius:10px; border:1px solid var(--line,#BFC7D4); background:var(--surface,#fff); color:var(--ink,#0E1726); width:100%; box-sizing:border-box}
.cad .linha{display:grid; grid-template-columns:minmax(0,1fr) 5.5rem; gap:.6rem}
.cad fieldset{border:0; margin:0; padding:0}
.cad legend{font-size:.8rem; font-weight:600; color:var(--ink-2,#2E3A50); margin-bottom:.35rem}
.cad .dist{display:flex; flex-wrap:wrap; gap:.35rem}
.cad .dist label{cursor:pointer}
.cad .dist input{position:absolute; opacity:0; pointer-events:none}
.cad .dist span{display:inline-block; font-size:.82rem; padding:.35rem .7rem; border-radius:999px; border:1px solid var(--line,#BFC7D4)}
.cad .dist input:checked + span{background:#0A2F73; border-color:#0A2F73; color:#fff}
.cad .dist input:focus-visible + span{outline:2px solid #FFC21A}
.cad .aceite{display:flex; gap:.5rem; align-items:flex-start; font-size:.82rem; line-height:1.4; color:var(--ink-2,#2E3A50)}
.cad .aceite input{margin-top:.15rem; flex:none}
.cad .aceite a{color:inherit}
.cad .opcional{font-weight:400; color:var(--muted,#5B6880)}
.cad__enviar{font:inherit; font-weight:700; cursor:pointer; border:0; border-radius:12px; padding:.8rem; background:#FFC21A; color:#0A2F73; font-size:1rem}
.cad__enviar[disabled]{opacity:.6; cursor:wait}
.cad__erro{margin:0; color:#B81C26; font-size:.85rem}
.cad__ok{padding:1.6rem 1.3rem; text-align:center}
.cad__ok b{display:block; font-size:1.2rem; margin-bottom:.4rem}
.cad__ok p{margin:0 0 1rem; color:var(--ink-2,#2E3A50)}
.cad__aviso{position:fixed; left:50%; bottom:1.2rem; transform:translateX(-50%); z-index:50; max-width:calc(100% - 2rem);
  background:#0A2F73; color:#fff; padding:.85rem 1.1rem; border-radius:14px; box-shadow:0 12px 30px rgba(0,0,0,.3);
  display:flex; gap:.8rem; align-items:center; font-size:.92rem}
.cad__aviso button{border:0; background:none; color:#FFC21A; font:inherit; font-weight:700; cursor:pointer}
@media (max-width:480px){ .cad .linha{grid-template-columns:1fr} }`;

  const el = (tag, props = {}, kids = []) => {
    const n = Object.assign(document.createElement(tag), props);
    kids.forEach(k => n.append(k));
    return n;
  };

  function aviso(texto, acao) {
    const caixa = el("div", { className: "cad__aviso", role: "status" }, [el("span", { textContent: texto })]);
    if (acao) {
      const b = el("button", { type: "button", textContent: acao[0] });
      b.onclick = () => { caixa.remove(); acao[1](); };
      caixa.append(b);
    }
    const fechar = el("button", { type: "button", textContent: "×", title: "Fechar" });
    fechar.onclick = () => caixa.remove();
    caixa.append(fechar);
    document.body.append(caixa);
    setTimeout(() => caixa.remove(), 12000);
  }

  let dialogo = null, widget = null;

  function carregarTurnstile() {
    if (window.turnstile) return Promise.resolve();
    return new Promise((ok, falha) => {
      const s = el("script", { src: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", async: true });
      s.onload = ok; s.onerror = falha;
      document.head.append(s);
    });
  }

  function montar() {
    const cidades = el("datalist", { id: "cad-cidades" });
    // Na pagina do calendario, as cidades das provas viram sugestao.
    const provas = typeof RACES !== "undefined" ? RACES : [];     // const do script da pagina
    const nomes = new Set(provas.map(r => r.cidade).filter(Boolean));
    [...nomes].sort((a, b) => a.localeCompare(b, "pt-BR")).forEach(c => cidades.append(el("option", { value: c })));

    const dist = el("div", { className: "dist" });
    DISTANCIAS.forEach(([v, rot]) => dist.append(el("label", {}, [
      el("input", { type: "checkbox", name: "distancias", value: v }), el("span", { textContent: rot })])));

    const uf = el("select", { name: "uf", required: true });
    [["", "UF"], ["SC", "SC"], ["PR", "PR"], ["RS", "RS"], ["SP", "SP"], ["OU", "Outro"]].forEach(([v, t]) =>
      uf.append(el("option", { value: v, textContent: t })));
    // A pagina do Parana ja sugere PR.
    if (/\/pr\.html$/.test(location.pathname)) uf.value = "PR";
    else if (!/todos\.html$/.test(location.pathname)) uf.value = "SC";

    const erro = el("p", { className: "cad__erro", role: "alert" });
    const enviar = el("button", { className: "cad__enviar", type: "submit", textContent: "Quero receber os cupons" });
    const captcha = el("div", { className: "cad__captcha" });
    const campo = (rotulo, input, extra) => el("label", { className: "campo" }, [
      el("span", {}, [document.createTextNode(rotulo), extra ? el("span", { className: "opcional", textContent: " " + extra }) : ""]), input]);

    const cidade = el("input", { type: "text", name: "cidade", autocomplete: "address-level2", required: true, maxLength: 80 });
    cidade.setAttribute("list", "cad-cidades");      // "list" so aceita atributo
    const form = el("form", { noValidate: true }, [
      campo("Nome", el("input", { type: "text", name: "nome", autocomplete: "name", required: true, maxLength: 80 })),
      campo("E-mail", el("input", { type: "email", name: "email", autocomplete: "email", required: true, maxLength: 120 })),
      el("div", { className: "linha" }, [
        campo("Cidade", cidade),
        campo("Estado", uf),
      ]),
      el("fieldset", {}, [el("legend", { textContent: "Distâncias que você corre" }), dist]),
      campo("WhatsApp", el("input", { type: "tel", name: "whatsapp", autocomplete: "tel", placeholder: "(48) 99999-0000", maxLength: 20 }), "(opcional)"),
      el("label", { className: "aceite" }, [el("input", { type: "checkbox", name: "aceitaWhatsapp" }),
        el("span", { textContent: "Aceito receber avisos de cupons e provas pelo WhatsApp." })]),
      el("label", { className: "aceite" }, [el("input", { type: "checkbox", name: "aceitaNewsletter" }),
        el("span", { textContent: "Quero receber a newsletter e os cupons de desconto por e-mail." })]),
      el("label", { className: "aceite" }, [el("input", { type: "checkbox", name: "aceitaPrivacidade" }),
        el("span", {}, [document.createTextNode("Li e aceito a "),
          el("a", { href: PRIVACIDADE, target: "_blank", rel: "noopener", textContent: "Política de Privacidade" }), document.createTextNode(".")])]),
      captcha, erro, enviar, cidades,
    ]);

    const fechar = el("button", { className: "cad__fechar", type: "button", textContent: "×", title: "Fechar" });
    const corpo = el("div", {}, [form]);
    dialogo = el("dialog", { className: "cad", ariaLabel: "Cadastro" }, [
      el("div", { className: "cad__topo" }, [
        el("h2", { textContent: "Ganhe cupons de desconto" }),
        el("p", { textContent: "Cadastre-se para receber a newsletter com cupons nas inscrições e as provas da sua região." }),
        fechar]),
      corpo]);
    fechar.onclick = () => dialogo.close();
    dialogo.addEventListener("click", e => { if (e.target === dialogo) dialogo.close(); });
    document.body.append(dialogo);

    form.onsubmit = async e => {
      e.preventDefault();
      erro.textContent = "";
      const f = new FormData(form);
      const dados = {
        nome: (f.get("nome") || "").trim(), email: (f.get("email") || "").trim(),
        cidade: (f.get("cidade") || "").trim(), uf: f.get("uf") || "",
        distancias: f.getAll("distancias"), whatsapp: (f.get("whatsapp") || "").trim(),
        aceitaWhatsapp: f.get("aceitaWhatsapp") === "on",
        aceitaNewsletter: f.get("aceitaNewsletter") === "on", aceitaPrivacidade: f.get("aceitaPrivacidade") === "on",
        origem: location.pathname, turnstile: window.turnstile && widget != null ? window.turnstile.getResponse(widget) : "",
      };
      if (dados.nome.length < 2) return (erro.textContent = "Informe seu nome.");
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(dados.email)) return (erro.textContent = "Informe um e-mail válido.");
      if (dados.cidade.length < 2 || !dados.uf) return (erro.textContent = "Informe sua cidade e o estado.");
      if (!dados.aceitaNewsletter) return (erro.textContent = "Para receber os cupons, marque a opção da newsletter.");
      if (!dados.aceitaPrivacidade) return (erro.textContent = "É preciso aceitar a Política de Privacidade.");
      enviar.disabled = true; enviar.textContent = "Enviando…";
      try {
        const r = await fetch(API + "/cadastro", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dados) });
        const d = await r.json();
        if (!d.ok) throw new Error(d.erro || "Não foi possível cadastrar.");
        if (typeof gtag === "function") gtag("event", "sign_up", { method: "formulario" });
        const ok = el("div", { className: "cad__ok" }, [
          el("b", { textContent: "Falta só confirmar!" }),
          el("p", { textContent: d.mensagem + " Se não chegar em alguns minutos, veja a caixa de spam ou promoções." }),
        ]);
        if (d.dev_link) ok.append(el("p", {}, [el("a", { href: d.dev_link.replace(/^https?:\/\/[^/]+/, API), textContent: "(teste local) confirmar agora" })]));
        const fecharOk = el("button", { className: "cad__enviar", type: "button", textContent: "Fechar" });
        fecharOk.onclick = () => dialogo.close();
        ok.append(fecharOk);
        corpo.replaceChildren(ok);
      } catch (x) {
        erro.textContent = x.message === "Failed to fetch" ? "Sem conexão com o servidor. Tente de novo em instantes." : x.message;
        if (window.turnstile && widget != null) window.turnstile.reset(widget);
      } finally {
        enviar.disabled = false; enviar.textContent = "Quero receber os cupons";
      }
    };

    carregarTurnstile().then(() => {
      widget = window.turnstile.render(captcha, { sitekey: TURNSTILE, size: "flexible", language: "pt-br" });
    }).catch(() => {});
  }

  function abrir() {
    if (!dialogo) montar();
    dialogo.showModal();
    const nome = dialogo.querySelector("input[name=nome]");
    if (nome) nome.focus();
  }

  // Enquanto a chave publica do Turnstile nao for configurada, a API ainda
  // nao esta no ar: os botoes continuam escondidos (vem com hidden no HTML).
  const ATIVO = LOCAL || !/CHAVE/.test(TURNSTILE);

  function iniciar() {
    if (!ATIVO) return;
    document.head.append(el("style", { textContent: css }));
    document.querySelectorAll("[data-cadastro]").forEach(b => { b.hidden = false; b.addEventListener("click", abrir); });
    // Volta do link do e-mail.
    const estado = new URLSearchParams(location.search).get("cadastro");
    if (estado) {
      const textos = {
        confirmado: "Cadastro confirmado! Você vai receber a newsletter e os cupons no seu e-mail.",
        expirado: "O link de confirmação expirou. Cadastre-se de novo para receber outro.",
        invalido: "Link de confirmação inválido ou já usado.",
      };
      if (estado === "confirmado" && typeof gtag === "function") gtag("event", "cadastro_confirmado");
      aviso(textos[estado] || "", estado === "confirmado" ? null : ["Cadastrar", abrir]);
      history.replaceState(null, "", location.pathname + location.hash);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
  window.abrirCadastro = abrir;
})();
