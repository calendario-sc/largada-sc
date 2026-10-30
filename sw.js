// Service worker do app Cupons de Corrida (PWA).
// Paginas: rede primeiro, com a copia guardada como reserva (abre offline o que ja foi visto).
// Arquivos fixos (logo, icones, css, js): cache primeiro. A API e os dados nunca passam pelo cache.
const VERSAO = "cupons-v4";
const FIXOS = ["/", "/cupons.html", "/cadastro.js", "/logo-cupons-de-corrida.png", "/favicon.svg", "/icone-app-192.png", "/icone-app-512.png", "/offline.html"];
const SEM_CACHE = /(^https:\/\/api\.)|(^https:\/\/dados\.)|challenges\.cloudflare\.com|googletagmanager|google-analytics|\.json(\?|$)|\.ics(\?|$)/;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSAO).then(c => c.addAll(FIXOS.map(u => new Request(u, { cache: "reload" }))).catch(() => null)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSAO).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || SEM_CACHE.test(req.url) || new URL(req.url).origin !== location.origin) return;
  // Paginas e os dados do calendario (dados-<uf>.js): rede primeiro, copia guardada como reserva.
  const pagina = req.mode === "navigate" || /\.html(\?|$)|\/$|\/dados-[a-z]+\.js$/.test(new URL(req.url).pathname);
  if (pagina) {
    e.respondWith(fetch(req).then(r => { const copia = r.clone(); caches.open(VERSAO).then(c => c.put(req, copia)); return r; })
      .catch(() => caches.match(req).then(r => r || caches.match("/offline.html"))));
    return;
  }
  e.respondWith(caches.match(req).then(r => r || fetch(req).then(resp => {
    if (resp.ok && /\.(png|svg|css|js|woff2?)(\?|$)/.test(req.url)) { const copia = resp.clone(); caches.open(VERSAO).then(c => c.put(req, copia)); }
    return resp;
  })));
});
