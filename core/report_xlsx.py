"""Planilha Excel com os ajustes de cada relé (uma única aba, azul/cinza/branco)."""
from __future__ import annotations

from datetime import date

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONTE = "Arial"
AZUL_ESCURO = "1F3864"
AZUL = "1F4E9C"
AZUL_PALIDO = "DCE6F5"
CINZA = "F2F2F2"

COLUNAS = [
    ("Terminal", 26), ("Relé", 16), ("Função", 24), ("Parâmetro", 44), ("Nome no relé (ref.)", 16),
    ("Valor secundário", 15), ("Un. sec.", 10), ("Valor primário", 15), ("Un. pri.", 10),
    ("Critério", 52), ("Origem", 16), ("Status", 11), ("Valor ajustado", 15), ("Observações", 30),
]


def origem(a: dict) -> str:
    """Classifica o valor: CALCULADO, ADOTADO (critério), ASSUMIDO (premissa) ou A DEFINIR (regra do projeto)."""
    v = a.get("valor_sec")
    crit = str(a.get("criterio", ""))
    fun = str(a.get("funcao", ""))
    par = str(a.get("parametro", ""))
    if isinstance(v, str) and v.strip().lower() in ("n/d", "", "a definir"):
        return "A DEFINIR"
    if crit.startswith(("Estimativa", "Espelhado")) or ("Load" in fun and "Ângulo" in par):
        return "ASSUMIDO"
    if fun.startswith(("68", "Load")) or par.startswith("Ângulo da impedância"):
        return "CALCULADO"
    return "ADOTADO"


def gerar_planilha(projeto: dict, resultados: list[dict], destino) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ajustes dos Relés"
    borda = Side(style="thin", color="BFBFBF")
    B = Border(left=borda, right=borda, top=borda, bottom=borda)
    ncol = len(COLUNAS)

    ws["A1"] = "BK Engenharia e Tecnologia — Ajustes recomendados dos relés"
    ws["A1"].font = Font(name=FONTE, size=14, bold=True, color=AZUL_ESCURO)
    ws["A2"] = (f"Cliente: {projeto.get('cliente') or '—'}   |   Projeto: {projeto.get('nome') or '—'}   |   "
                f"Documento: {projeto.get('numero_doc') or '—'}   |   Rev.: {projeto.get('revisao') or '00'}   |   "
                f"Data: {date.today().strftime('%d/%m/%Y')}")
    ws["A2"].font = Font(name=FONTE, size=10, italic=True, color="595959")
    ws["A3"] = ("Valores calculados pelo estudo (secundário = valor a ser inserido no relé). Conferir nome, faixa, passo e convenção "
                "de sinal no manual do firmware. Preencha 'Valor ajustado' e 'Observações' (colunas amarelas) após a parametrização.")
    ws["A3"].font = Font(name=FONTE, size=9, color="7F7F7F")

    # resumo com fórmulas (acima da tabela)
    ws["A5"] = "Total de ajustes"
    ws["A6"] = "Ajustes a revisar"
    ws["A7"] = "Terminais"
    for r in (5, 6, 7):
        ws.cell(r, 1).font = Font(name=FONTE, size=10, bold=True, color=AZUL_ESCURO)
    HR = 9
    primeira = HR + 1

    for c, (nome, larg) in enumerate(COLUNAS, 1):
        x = ws.cell(HR, c, nome)
        x.font = Font(name=FONTE, bold=True, color="FFFFFF", size=10)
        x.fill = PatternFill("solid", fgColor=AZUL_ESCURO)
        x.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        x.border = B
        ws.column_dimensions[get_column_letter(c)].width = larg
    ws.row_dimensions[HR].height = 32

    amarelo = PatternFill("solid", fgColor="FFF2CC")
    cinza = PatternFill("solid", fgColor=CINZA)
    azul_pal = PatternFill("solid", fgColor=AZUL_PALIDO)

    r = primeira
    zebra = 0
    for res in resultados:
        e = res["entrada"]
        term = f"{e.get('lt_nome', '')} — {e.get('terminal', '')}".strip(" —")
        rele = f"{e.get('fabricante', '')} {e.get('modelo', '')}".strip()
        # faixa de separação por terminal
        ws.cell(r, 1, term).font = Font(name=FONTE, bold=True, size=10, color=AZUL_ESCURO)
        for c in range(1, ncol + 1):
            ws.cell(r, c).fill = azul_pal
            ws.cell(r, c).border = B
        ws.cell(r, 2, rele).font = Font(name=FONTE, size=10, color=AZUL_ESCURO)
        ws.cell(r, 3, "Conferência" if e.get("modo") == "conferencia" else "Novos ajustes").font = Font(name=FONTE, size=10, color=AZUL_ESCURO)
        r += 1
        zebra = 0
        for a in res["ajustes"]:
            vals = [term, rele, a["funcao"], a["parametro"], a["nome_rele"], a["valor_sec"], a["unid_sec"],
                    a["valor_pri"], a["unid_pri"], a["criterio"], origem(a), a["status"], None, None]
            for c, v in enumerate(vals, 1):
                x = ws.cell(r, c, v)
                x.font = Font(name=FONTE, size=10, bold=(c == 6))
                x.border = B
                x.alignment = Alignment(vertical="top", wrap_text=c in (4, 10, 14),
                                        horizontal="center" if c in (5, 6, 7, 8, 9, 11, 12, 13) else "left")
                if zebra % 2:
                    x.fill = cinza
                if c in (13, 14):
                    x.fill = amarelo
            for c in (6, 8):
                v = ws.cell(r, c).value
                if isinstance(v, (int, float)):
                    ws.cell(r, c).number_format = "#,##0.000"
            zebra += 1
            r += 1
    ultima = r - 1

    # resumo (fórmulas)
    ws["B5"] = f'=COUNTIF(L{primeira}:L{ultima},"OK")+COUNTIF(L{primeira}:L{ultima},"REVISAR")'
    ws["B6"] = f'=COUNTIF(L{primeira}:L{ultima},"REVISAR")'
    ws["B7"] = len(resultados)
    for c in ("B5", "B6", "B7"):
        ws[c].font = Font(name=FONTE, size=10, bold=True)
        ws[c].alignment = Alignment(horizontal="left")

    ws.conditional_formatting.add(f"L{primeira}:L{ultima}",
        CellIsRule(operator="equal", formula=['"REVISAR"'], font=Font(name=FONTE, bold=True, color="FFFFFF"),
                   fill=PatternFill("solid", bgColor=AZUL, fgColor=AZUL)))
    ws.freeze_panes = ws.cell(primeira, 5)
    ws.auto_filter.ref = f"A{HR}:{get_column_letter(ncol)}{ultima}"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{HR}:{HR}"
    # ---- aba Revisões (rastreabilidade do documento)
    wr = wb.create_sheet("Revisões")
    wr["A1"] = "Histórico de revisões"
    wr["A1"].font = Font(name=FONTE, size=14, bold=True, color=AZUL_ESCURO)
    cab = ["Rev.", "Data", "Descrição", "Base de dados", "Elaboração", "Verificação independente"]
    for c, t in enumerate(cab, 1):
        x = wr.cell(3, c, t)
        x.font = Font(name=FONTE, bold=True, color="FFFFFF", size=10)
        x.fill = PatternFill("solid", fgColor=AZUL_ESCURO)
        x.border = B
    linhas = projeto.get("revisoes") or [[projeto.get("revisao") or "00", date.today().strftime("%d/%m/%Y"),
                                            "Emissão preliminar", projeto.get("base_dados") or "A DEFINIR",
                                            "BK Engenharia", "Pendente"]]
    for i, ln in enumerate(linhas, 4):
        for c, v in enumerate(ln, 1):
            x = wr.cell(i, c, v)
            x.font = Font(name=FONTE, size=10)
            x.border = B
            x.alignment = Alignment(vertical="top", wrap_text=True)
    for c, w in enumerate((8, 12, 48, 36, 18, 24), 1):
        wr.column_dimensions[get_column_letter(c)].width = w
    wr.sheet_view.showGridLines = False

    # ---- aba Premissas e A DEFINIR (opcional; vem de projeto["pendencias"])
    pend = projeto.get("pendencias") or []
    if pend:
        wp = wb.create_sheet("Premissas e A DEFINIR")
        wp["A1"] = "Premissas numeradas e itens A DEFINIR"
        wp["A1"].font = Font(name=FONTE, size=14, bold=True, color=AZUL_ESCURO)
        for c, t in enumerate(["Nº", "Tipo", "Item", "Fonte / como resolver"], 1):
            x = wp.cell(3, c, t)
            x.font = Font(name=FONTE, bold=True, color="FFFFFF", size=10)
            x.fill = PatternFill("solid", fgColor=AZUL_ESCURO)
            x.border = B
        for i, ln in enumerate(pend, 4):
            for c, v in enumerate(ln, 1):
                x = wp.cell(i, c, v)
                x.font = Font(name=FONTE, size=10)
                x.border = B
                x.alignment = Alignment(vertical="top", wrap_text=True)
        for c, w in enumerate((6, 14, 60, 60), 1):
            wp.column_dimensions[get_column_letter(c)].width = w
        wp.sheet_view.showGridLines = False
    wb.save(destino)
