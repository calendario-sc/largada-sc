#!/usr/bin/env python3
"""Coleta dos concluintes feita neste computador, e nao no GitHub.

O Open Results e o RunKing ficam atras do Cloudflare, que recusa o servidor
do GitHub (HTTP 403): na coleta das 8h a linha "concluintes" sai FALHOU.
Daqui eles respondem. Este script roda pelo Agendador do Windows as 9h,
depois da coleta do GitHub, e faz so a parte que la falha:

  1. puxa o repositorio (com o que o robo das 8h publicou)
  2. liga os concluintes do Open Results dos ultimos 90 dias, completa pelo
     RunKing e busca a divisao por sexo
  3. refaz series e marcas de resultado parcial, reconstroi a pagina
  4. publica, se algo mudou

Tudo vai para coleta-local.log. Se o repositorio local tiver mudanca que nao
seja deste script, ele nao mexe em nada e registra o motivo -- melhor um dia
sem numero novo que sobrescrever trabalho em andamento.

Uso:  python resultados_locais.py
"""

import datetime
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
LOG = AQUI / "coleta-local.log"
sys.path.insert(0, str(AQUI))


def registrar(texto):
    linha = f"{datetime.datetime.now():%Y-%m-%d %H:%M} {texto}"
    print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def git(*args, checar=True):
    exe = shutil.which("git")
    if not exe:
        raise RuntimeError("git nao encontrado no PATH")
    r = subprocess.run([exe, *args], cwd=AQUI, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if checar and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def repositorio_limpo():
    """Nada modificado alem do que o proprio script gera.

    Arquivo novo em atletas/ e obra da coleta de atletas, que pode estar
    rodando em paralelo ou ter sido interrompida: nao e trabalho em andamento
    de ninguem, e entra no commit normalmente.
    """
    mudancas = [l for l in git("status", "--porcelain").stdout.splitlines()
                if l.strip() and not l[3:].startswith("atletas/")]
    return not mudancas, mudancas


def coletar():
    import scrape

    historico = json.loads(scrape.SAIDA.read_text(encoding="utf-8"))
    com_antes = sum(1 for p in historico if p.get("concluintes_total"))

    vistos, ligados, novos, criados = scrape.vincular_concluintes(historico)
    registrar(f"open results: {vistos} eventos, {ligados} casados, "
              f"{novos} com numero novo, {criados} provas criadas")
    juntadas = scrape.unificar_openresults(historico)
    if juntadas:
        registrar(f"provas que mudaram de nome: {len(juntadas)} unificadas")
    manuais = scrape.unificar_manualmente(historico)
    if manuais:
        registrar(f"provas declaradas iguais: {manuais} unificadas")
    duplicadas = scrape.remover_resultado_duplicado(historico)
    if duplicadas:
        registrar(f"resultados repetidos removidos: {duplicadas}")

    try:
        consultadas, achadas = scrape.completar_runking(historico)
        if consultadas:
            registrar(f"runking: {consultadas} consultadas, {achadas} preenchidas")
    except Exception as erro:
        registrar(f"runking: FALHOU ({erro.__class__.__name__}: {erro})")

    try:
        n = scrape.completar_extras(historico, registrar=registrar)
        if n:
            registrar(f"resultados apontados a mao: {n} preenchidos")
        n, ok = scrape.completar_maissport(historico, registrar=registrar)
        if n:
            registrar(f"mais sports: {n} provas procuradas, {ok} preenchidas")
    except Exception as erro:
        registrar(f"clax: FALHOU ({erro.__class__.__name__}: {erro})")

    for _ in range(10):
        n, ok = scrape.completar_generos(historico, limite=200)
        if not n:
            break
        registrar(f"genero: {n} consultadas, {ok} preenchidas")

    try:
        feitas, achadas = scrape.completar_cronometragem(historico, limite=120, registrar=registrar)
        if feitas:
            registrar(f"cronometragem: {feitas} paginas lidas, {achadas} empresas achadas")
    except Exception as erro:
        registrar(f"cronometragem: FALHOU ({erro.__class__.__name__}: {erro})")

    try:
        import locais_floripa
        locais_floripa.atualizar_locais(historico, limite=60, registrar=registrar)
    except Exception as erro:
        registrar(f"raio-x floripa: FALHOU ({erro.__class__.__name__}: {erro})")

    try:
        import fotografia
        n, ok = fotografia.completar_fotografia(historico, limite=120, registrar=registrar)
        if n:
            registrar(f"fotografia: {n} provas procuradas, {ok} com plataforma")
    except Exception as erro:
        registrar(f"fotografia: FALHOU ({erro.__class__.__name__}: {erro})")

    scrape.agrupar_series(historico)
    parciais = scrape.marcar_resultados_parciais(historico)

    historico.sort(key=lambda p: (p["data"], scrape.sem_acento(p["cidade"]), p["nome"]))
    scrape.SAIDA.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
    com_depois = sum(1 for p in historico if p.get("concluintes_total"))
    registrar(f"provas com resultado: {com_antes} -> {com_depois} "
              f"({len(parciais)} parciais marcadas)")
    return com_depois - com_antes


def coletar_atletas():
    """Resultado por atleta das provas que ainda nao tem, e o indice da pagina.

    O portal limita o ritmo depois de umas centenas de provas seguidas, entao
    a rodada tem teto: o que faltar entra nos dias seguintes.
    """
    import atletas_build
    import atletas_coleta

    feitas = atletas_coleta.coletar(atletas_coleta.ANOS_ATLETAS, limite=80, registrar=registrar)
    if feitas:
        atletas_build.montar(registrar=registrar)
    # Alunos por assessoria (so para o BI): refeito todo dia, e barato.
    import assessorias
    assessorias.montar(registrar=registrar)
    return feitas


def publicar():
    import build

    build.build()
    if not git("status", "--porcelain").stdout.strip():
        registrar("nada mudou: nada a publicar")
        return
    git("add", "corridas.json", "index.html", "atletas")
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    git("-c", "user.name=Largada SC", "-c", "user.email=thiagomansur@gmail.com",
        "commit", "-q", "-m", f"concluintes de {hoje} (coleta local)")
    envio = git("push", "-q", "origin", "main", checar=False)
    if envio.returncode != 0:
        # O robo do GitHub publicou no meio do caminho. O historico local ja
        # contem o dele (foi puxado no inicio) e mais os numeros de hoje.
        registrar("push recusado: juntando com o que chegou e tentando de novo")
        git("fetch", "-q", "origin")
        git("-c", "user.name=Largada SC", "-c", "user.email=thiagomansur@gmail.com",
            "merge", "-q", "-X", "ours", "origin/main", "-m", "junta coleta local")
        build.build()
        git("add", "corridas.json", "index.html", "atletas")
        git("-c", "user.name=Largada SC", "-c", "user.email=thiagomansur@gmail.com",
            "commit", "-q", "-m", "reconstroi a pagina", checar=False)
        git("push", "-q", "origin", "main")
    registrar("publicado")
    publicar_bi()


def publicar_bi():
    """A pagina de BI vive num repositorio privado ao lado deste (../cupons-bi),
    publicado pelo Cloudflare Pages. O build ja escreveu o index.html la."""
    pasta = AQUI.parent / "cupons-bi"
    if not (pasta / ".git").is_dir():
        return
    exe = shutil.which("git")

    def g(*args, checar=True):
        r = subprocess.run([exe, *args], cwd=pasta, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if checar and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
        return r

    try:
        if not g("status", "--porcelain").stdout.strip():
            return
        g("add", "index.html")
        if (pasta / "assessorias.json").exists():
            g("add", "assessorias.json")
        hoje = datetime.date.today().strftime("%d/%m/%Y")
        g("-c", "user.name=Cupons de Corrida", "-c", "user.email=thiagomansur@gmail.com",
          "commit", "-q", "-m", f"BI de {hoje}")
        if g("remote").stdout.strip():
            g("push", "-q", "origin", "main")
        registrar("BI publicado")
    except Exception as erro:
        registrar(f"BI: FALHOU ({erro.__class__.__name__}: {erro})")


def main():
    registrar("== inicio ==")
    try:
        limpo, mudancas = repositorio_limpo()
        if not limpo:
            registrar("repositorio com mudancas locais, nada feito: " + "; ".join(mudancas[:5]))
            return 1
        git("pull", "-q", "--ff-only", "origin", "main")
        coletar()
        try:
            coletar_atletas()
        except Exception as erro:
            registrar(f"atletas: FALHOU ({erro.__class__.__name__}: {erro})")
        publicar()
        return 0
    except Exception as erro:
        registrar(f"FALHOU: {erro.__class__.__name__}: {erro}")
        with LOG.open("a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        return 1
    finally:
        registrar("== fim ==")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    sys.exit(main())
