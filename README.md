# Largada SC

Calendário de corridas de rua e trail de Santa Catarina. O site é um arquivo
único (`index.html`, ~230 KB) com os dados embutidos: não precisa de servidor,
banco nem build. Qualquer hospedagem estática serve.

## Como funciona

`atualizar.py` faz tudo:

1. `scrape.py` coleta seis origens de cinco sites (corridasbr.com.br — calendário
   e arquivo de resultados —, ticketsports.com.br, roadrunners.run,
   movnow.com.br e atletis.com.br), funde as provas anunciadas em mais de um
   lugar e acumula em `corridas.json`.
2. `build.py` injeta esses dados em `template.html` e gera `index.html`.

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

`.github/workflows/atualizar.yml` roda todo dia às 8h de Brasília, commita o
resultado e publica. Também dá para rodar na mão pela aba **Actions**.

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
