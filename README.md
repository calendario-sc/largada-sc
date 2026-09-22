# Largada SC

Site no ar: https://calendario-sc.github.io/largada-sc/

Calendário de corridas de rua e trail de Santa Catarina. O site é um arquivo
único (`index.html`, ~230 KB) com os dados embutidos: não precisa de servidor,
banco nem build. Qualquer hospedagem estática serve.

## Como funciona

`atualizar.py` faz tudo:

1. `scrape.py` coleta seis origens de cinco sites (corridasbr.com.br — calendário
   e arquivo de resultados —, ticketsports.com.br, roadrunners.run,
   movnow.com.br e atletis.com.br), funde as provas anunciadas em mais de um
   lugar e acumula em `corridas.json`.
2. Para as provas já realizadas, busca quantos atletas concluíram: primeiro em
   openresults.run, que publica a quebra por distância de uma vez só, e depois
   nas cronometragens, uma prova por vez — supercrono.com.br, chiprun.com.br e
   resultados.runking.com.br. Concluinte é quem tem tempo de chegada; quem se
   inscreveu e não largou não entra.
3. `perfis.py` monta o perfil das provas de 2026 e 2027: site e Instagram
   oficiais, ticketeira e link de inscrição, tabela de preços, patrocinadores
   e lei de incentivo com o proponente. Cada campo sai de uma fonte citável
   (página do evento no roadrunners, link oficial do corridasbr, API da
   Ticket Sports, regulamento); o que não for achado aparece como "não
   encontrado", nunca deduzido. Provas futuras são revistas a cada 3 dias,
   porque o preço muda a cada lote.
4. `build.py` injeta esses dados em `template.html` e gera `index.html`.

Cidades e regiões saem da malha municipal do IBGE, guardada em
`municipios.json` e renovada sozinha a cada 180 dias.

```bash
python atualizar.py
```

Sem dependências: só a biblioteca padrão do Python 3.7+.

## corridas.json é insubstituível

É um **histórico cumulativo**. Provas já realizadas continuam nele depois de
saírem do ar nas fontes, que só listam provas futuras. Nada é apagado: cada
rodada acrescenta, atualiza e junta registros duplicados da mesma prova.

Se esse arquivo for perdido, o histórico não pode ser reconstruído. Ele é
versionado no git justamente por isso — cada coleta vira um commit.

## Atualização automática

`.github/workflows/atualizar.yml` roda todo dia às 8h de Brasília e commita o
resultado. O GitHub Pages serve o `index.html` direto do branch `main`, então a
publicação acontece sozinha a cada commit. Também dá para rodar na mão pela aba
**Actions**.

Se a coleta falhar (rede fora, ou menos de 60 provas no total), o script sai com
erro, nada é commitado e o histórico fica intacto.

## Arquivos

| arquivo | o que é |
|---|---|
| `index.html` | o site, pronto para publicar |
| `corridas.json` | o histórico acumulado |
| `template.html` | o molde da página |
| `comum.py` | regiões do IBGE, normalização, comparação de nomes |
| `fontes.py` | um adaptador por fonte |
| `scrape.py` | fusão, histórico e relatório |
| `municipios.py` | cache da malha municipal do IBGE |
| `perfis.py` | perfil de cada prova (links, preços, patrocínio, incentivo) |
| `atletas_coleta.py` | resultado de cada atleta, prova a prova, do Open Results (roda só localmente) |
| `atletas_build.py` | índice por prefixo de nome que a página `atletas.html` consulta |
| `atletas.html` | busca por atleta: distâncias, pace e melhores tempos |
| `resultados_locais.py` | rotina das 9h neste computador: concluintes, atletas e publicação |
| `pdftexto.py` | texto de regulamento em PDF, só com a biblioteca padrão |
