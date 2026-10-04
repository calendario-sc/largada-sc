#!/usr/bin/env python3
"""Gera modelo-calendario-provas.xlsx: a planilha que as organizadoras baixam
no portal do parceiro para enviar o calendario de provas de uma vez.

So biblioteca padrao (o .xlsx e um zip de XML). A leitura da planilha
preenchida e feita no navegador (parceiros.html), que entende estas colunas
pelo titulo -- mudar um titulo aqui pede o mesmo ajuste la.

Uso:  python modelo_planilha.py
"""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

SAIDA = Path(__file__).resolve().parent / "modelo-calendario-provas.xlsx"

COLUNAS = [  # (titulo, largura, exemplo 1, exemplo 2)
    ("Nome da prova", 42, "Corrida Exemplo de Verão 2027", "Trail Exemplo da Serra"),
    ("Data (dd/mm/aaaa)", 18, "17/01/2027", "21/03/2027"),
    ("Cidade", 22, "Florianópolis", "Urubici"),
    ("UF", 6, "SC", "SC"),
    ("Distâncias (km)", 18, "5, 10, 21", "12, 25"),
    ("Tipo", 14, "Rua", "Trail"),
    ("Link de inscrição", 40, "https://www.exemplo.com.br/inscricao", ""),
    ("Local de largada", 30, "Beira-Mar Norte", "Praça central"),
    ("Horário", 10, "07:00", "06:30"),
    ("Observações", 40, "Apague as linhas de exemplo antes de enviar", ""),
]
TIPOS = ["Rua", "Trail", "Caminhada", "Kids", "Revezamento", "Noturna", "Ultra", "Duathlon", "Triathlon", "Outro"]
LINHAS_VALIDADAS = 500

INSTRUCOES = [
    "Como preencher o calendário de provas",
    "",
    "1. Uma prova por linha, na aba Provas. Apague as duas linhas de exemplo.",
    "2. Nome da prova, data, cidade e UF são obrigatórios. O calendário cobre SC, PR e RS.",
    "3. Data no formato dd/mm/aaaa (ex.: 17/01/2027). Só provas futuras.",
    "4. Distâncias em km, separadas por vírgula (ex.: 3, 5, 10, 21,1).",
    "5. Tipo: Rua, Trail, Caminhada, Kids, Revezamento, Noturna, Ultra, Duathlon, Triathlon ou Outro.",
    "6. Link de inscrição: o endereço completo, começando com https://",
    "7. Salve e envie o arquivo no painel do parceiro (Meu calendário de provas > Enviar planilha).",
    "",
    "Antes de gravar, o painel mostra a prévia e aponta as linhas com problema.",
    "Enviar de novo a mesma prova (mesmo nome e data) atualiza os dados, sem duplicar.",
    "As provas entram no calendário do site na atualização diária da manhã.",
    "",
    "Dúvidas: contato@cuponsdecorrida.com.br",
]


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def celula(ref, texto, estilo=0):
    s = f' s="{estilo}"' if estilo else ""
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{escape(texto)}</t></is></c>'


def aba_provas():
    linhas = []
    cab = "".join(celula(f"{col(i)}1", c[0], 1) for i, c in enumerate(COLUNAS))
    linhas.append(f'<row r="1" ht="22" customHeight="1">{cab}</row>')
    for n, idx in ((2, 2), (3, 3)):
        linhas.append(f'<row r="{n}">' + "".join(celula(f"{col(i)}{n}", c[idx], 2) for i, c in enumerate(COLUNAS) if c[idx]) + "</row>")
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{c[1]}" customWidth="1" style="3"/>' for i, c in enumerate(COLUNAS))
    ufs = f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" errorTitle="UF" error="Use SC, PR ou RS." sqref="D2:D{LINHAS_VALIDADAS}"><formula1>"SC,PR,RS"</formula1></dataValidation>'
    tipos = (f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" errorTitle="Tipo" error="Escolha um tipo da lista." '
             f'sqref="F2:F{LINHAS_VALIDADAS}"><formula1>"{",".join(TIPOS)}"</formula1></dataValidation>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0" tabSelected="1"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(linhas)}</sheetData>'
            f'<autoFilter ref="A1:{col(len(COLUNAS) - 1)}1"/>'
            f'<dataValidations count="2">{ufs}{tipos}</dataValidations></worksheet>')


def aba_instrucoes():
    linhas = "".join(f'<row r="{n}">{celula(f"A{n}", texto, 1 if n == 1 else 0)}</row>'
                     for n, texto in enumerate(INSTRUCOES, 1) if texto)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols><col min="1" max="1" width="110" customWidth="1"/></cols><sheetData>{linhas}</sheetData></worksheet>')


ESTILOS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="49" formatCode="@"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><i/><sz val="11"/><color rgb="FF5B6880"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0A2F73"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment vertical="center"/></xf>
<xf numFmtId="49" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>
<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs></styleSheet>"""


def gerar():
    arquivos = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Provas" sheetId="1" r:id="rId1"/><sheet name="Instruções" sheetId="2" r:id="rId2"/></sheets>
<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">Provas!$A$1:$J$1</definedName></definedNames>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        "xl/styles.xml": ESTILOS,
        "xl/worksheets/sheet1.xml": aba_provas(),
        "xl/worksheets/sheet2.xml": aba_instrucoes(),
    }
    with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    print(f"{SAIDA.name}: {SAIDA.stat().st_size} bytes")


if __name__ == "__main__":
    gerar()
