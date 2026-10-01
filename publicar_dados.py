#!/usr/bin/env python3
"""Envia os resultados por atleta para o R2 publico (dados.cuponsdecorrida.com.br).

Os arquivos de atletas/ (resultado de cada prova, indice e baldes de atletas,
campeoes, recordes) saem do GitHub e passam a ser servidos pela Cloudflare:
o repositorio para de crescer a cada coleta e o site aguenta mais estados.

So manda o que mudou desde o ultimo envio (.estado_r2.json guarda o hash de
cada arquivo) e apaga do R2 o que sumiu daqui. Envia em lotes pela API
(POST /interno/lote), com a chave em .segredos/upload_token.

Uso:  python publicar_dados.py            (envia o que mudou)
      python publicar_dados.py --tudo     (reenvia tudo)
"""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ATLETAS = AQUI / "atletas"
ESTADO = AQUI / ".estado_r2.json"
CHAVE = AQUI / ".segredos" / "upload_token"
API = "https://api.cuponsdecorrida.com.br/interno/lote"
API_ARQUIVO = "https://api.cuponsdecorrida.com.br/interno/arquivo"
# Arquivo maior que isto vai sozinho, direto para o R2 (o recordes.json passa de 4 MB).
GRANDE = 800 * 1024
PARALELOS = 8
# Por pedido. O Worker gratuito tem pouco tempo de CPU por pedido: ler um
# JSON de 6 MB estoura; 1 MB passa em ~1 s.
LOTE_BYTES = 1024 * 1024
UA = "cupons-de-corrida-coleta/1.0"


def arquivos():
    """chave no R2 -> (caminho, cache). Resultado de prova nao muda: cache longo."""
    saida = {}
    for p in sorted((ATLETAS / "provas").glob("*.json")):
        saida[f"atletas/provas/{p.name}"] = (p, "longo")
    for p in sorted((ATLETAS / "dados").glob("*.json")):
        saida[f"atletas/dados/{p.name}"] = (p, "curto")
    for p in sorted((ATLETAS / "ranking").glob("*.json")):
        saida[f"atletas/ranking/{p.name}"] = (p, "curto")
    for nome in ("indice", "campeoes", "recordes"):
        p = ATLETAS / f"{nome}.json"
        if p.exists():
            saida[f"atletas/{nome}.json"] = (p, "curto")
    return saida


def enviar(token, lote, registrar):
    corpo = json.dumps(lote, ensure_ascii=False).encode("utf-8")
    for tentativa in range(4):
        try:
            req = urllib.request.Request(API, data=corpo, method="POST", headers={
                "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            if not d.get("ok"):
                raise RuntimeError(d.get("erro") or "resposta sem ok")
            return d
        except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError) as erro:
            if isinstance(erro, urllib.error.HTTPError) and erro.code in (400, 401):
                raise RuntimeError(f"HTTP {erro.code}: {erro.read()[:200]!r}")
            registrar(f"  lote: tentativa {tentativa + 1} falhou ({erro}); de novo em 20 s")
            time.sleep(20)
    raise RuntimeError("lote nao enviado depois de 4 tentativas")


def enviar_arquivo(token, chave, conteudo, cache, registrar):
    corpo = conteudo.encode("utf-8")
    url = API_ARQUIVO + "?" + urllib.parse.urlencode({"chave": chave, "cache": cache})
    for tentativa in range(4):
        try:
            req = urllib.request.Request(url, data=corpo, method="PUT", headers={
                "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read().decode("utf-8"))
            if not d.get("ok"):
                raise RuntimeError(d.get("erro") or "resposta sem ok")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError) as erro:
            if isinstance(erro, urllib.error.HTTPError) and erro.code in (400, 401):
                raise RuntimeError(f"HTTP {erro.code}: {erro.read()[:200]!r}")
            registrar(f"  {chave}: tentativa {tentativa + 1} falhou ({erro}); de novo em 20 s")
            time.sleep(20)
    raise RuntimeError(f"{chave} nao enviado depois de 4 tentativas")


def publicar(tudo=False, registrar=print):
    if not CHAVE.exists():
        registrar("dados publicos: sem .segredos/upload_token, nada enviado")
        return 0
    token = CHAVE.read_text(encoding="utf-8").strip()
    estado = {} if tudo or not ESTADO.exists() else json.loads(ESTADO.read_text(encoding="utf-8"))
    atuais = arquivos()

    pendentes = []
    for chave, (caminho, cache) in atuais.items():
        conteudo = caminho.read_bytes()
        h = hashlib.sha1(conteudo).hexdigest()
        if estado.get(chave) != h:
            pendentes.append((chave, conteudo.decode("utf-8"), cache, h))
    apagar = [c for c in estado if c not in atuais]

    # Um arquivo por pedido, direto para o R2 (o lote em JSON estourava o tempo de
    # CPU do Worker e, em dia de instabilidade do R2, o tempo de resposta).
    from concurrent.futures import ThreadPoolExecutor, as_completed
    enviados = 0
    registrar(f"dados publicos: {len(pendentes)} arquivos para enviar")
    with ThreadPoolExecutor(max_workers=PARALELOS) as pool:
        futuros = {pool.submit(enviar_arquivo, token, c, txt, k, registrar): (c, h) for c, txt, k, h in pendentes}
        for fut in as_completed(futuros):
            c, h = futuros[fut]
            fut.result()                      # erro definitivo interrompe (o que ja foi fica gravado)
            estado[c] = h
            enviados += 1
            if enviados % 200 == 0:
                registrar(f"  ... {enviados} de {len(pendentes)} enviados")
                # Grava o progresso: uma queda no meio nao obriga a reenviar tudo.
                ESTADO.write_text(json.dumps(estado, separators=(",", ":")), encoding="utf-8")
    ESTADO.write_text(json.dumps(estado, separators=(",", ":")), encoding="utf-8")

    for i in range(0, len(apagar), 500):
        parte = apagar[i:i + 500]
        enviar(token, {"apagar": parte}, registrar)
        for c in parte:
            estado.pop(c, None)
    ESTADO.write_text(json.dumps(estado, separators=(",", ":")), encoding="utf-8")
    registrar(f"dados publicos: {enviados} arquivos enviados, {len(apagar)} apagados, {len(atuais)} no total")
    return enviados


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    publicar(tudo="--tudo" in sys.argv)
