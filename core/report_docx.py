"""Relatório técnico (Word) do estudo de proteção sistêmica.

Gera: capa, controle de revisões, sumário, objetivo/escopo, referências, dados de entrada,
metodologia com equações NATIVAS do Word (OMML), memória de cálculo por terminal (equação
simbólica + substituição numérica), tabelas de resultados, gráficos R-X e conclusões.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

from core.calc import fmt
from core.omml import inserir_equacao
from core.funcoes import rotulo
from core import modulos as MOD
from core.plots import grafico_rx, grafico_tempo_slip, grafico_curvas_sobrecorrente, grafico_direcional

AZUL_ESCURO = "1F3864"
AZUL = "1F4E9C"
AZUL_PALIDO = "DCE6F5"
CINZA_CLARO = "F2F2F2"
CINZA = "7F7F7F"
FONTE = "Arial"
TEMPLATE = Path(__file__).with_name("modelo_bk.docx")      # DOCUMENTO PADRÃO BK (capa, cabeçalho, rodapé e estilos)
LARG_UTIL_CM = 16.0                                          # largura útil (A4, margens 3,0 / 2,0 cm)

REFERENCIAS = [
    "IEEE Std C37.113 — Guide for Protective Relay Applications to Transmission Lines.",
    "IEEE PSRC WG D6 — Power Swing and Out-of-Step Considerations on Transmission Lines (2005).",
    "IEC 60255-121 — Measuring relays and protection equipment: functional requirements for distance protection.",
    "IEEE Std C37.2 — Standard for Electrical Power System Device Function Numbers (funções 21, 50, 51, 68 e 78).",
    "IEC 60255-151 — Measuring relays and protection equipment: functional requirements for over/under current protection (curvas IEC).",
    "IEEE Std C37.112 — Standard Inverse-Time Characteristic Equations for Overcurrent Relays.",
    "IEEE Std C37.102 / C37.113 e guias de aplicação de relés direcionais (Basler, GE D60, SEL, Protecta) — funções 67 e 67N.",
    "ONS — Procedimentos de Rede (submódulos aplicáveis aos requisitos de proteção).",
    "Manuais dos fabricantes dos relés (nomes de parâmetros, faixas e passos de ajuste).",
]

TEXTO_SECAO = {
    "Base": ("As impedâncias do sistema primário são referidas ao secundário dos transformadores de instrumentos "
             "por meio da relação de conversão RTC/RTP. O ângulo da impedância da LT orienta todos os alcances e blinders."),
    "Zonas de distância": ("As zonas de distância são modeladas como círculos mho cujo diâmetro está sobre a impedância da LT. "
                           "Z1 evita sobrealcance; Z2 cobre a LT inteira sem invadir a Z1 do adjacente; Z3 cobre o adjacente mais longo."),
    "Carga e load encroachment": ("A menor impedância de carga é calculada com a maior corrente entre o fluxo máximo e o limite térmico da LT, "
                                  "na tensão mínima operativa. A região de load encroachment é delimitada por ZLF e pelos ângulos de carga."),
    "Blinder interno": ("O blinder interno é uma reta paralela à impedância da LT, posicionada além da maior zona de distância "
                        "bloqueada pelo OSB, com margem percentual. É o limite em que o relé identifica o início da oscilação."),
    "Blinder externo": ("O blinder externo é limitado pela carga: deve permanecer a uma fração da distância perpendicular entre a "
                        "menor impedância de carga e a linha de impedância, para não confundir carga pesada com oscilação."),
    "Oscilação de potência": ("Com fontes de mesma magnitude, o lugar geométrico da impedância durante a oscilação é uma reta "
                              "perpendicular à impedância total. O ângulo entre fontes e o tempo de travessia entre blinders "
                              "decorrem da frequência de escorregamento máxima obtida nos estudos de estabilidade."),
    "Temporização do OSB": ("O temporizador do OSB discrimina falta de oscilação: faltas atravessam os blinders em menos de um ciclo "
                            "e não são bloqueadas; oscilações levam mais tempo que o OSBD e são bloqueadas."),
    "Função 51": ("O pickup da sobrecorrente temporizada de fase deve ficar acima da corrente de carga máxima (com fator de "
                  "segurança) e abaixo da corrente de curto-circuito mínima dividida pelo fator de sensibilidade. A curva e o "
                  "multiplicador de tempo (TMS) são escolhidos para atuar após o dispositivo a jusante, com o intervalo de coordenação."),
    "Função 51N": ("O pickup da sobrecorrente temporizada de neutro (corrente residual) deve superar o desequilíbrio admissível em "
                   "regime e ficar abaixo da corrente de falta fase-terra mínima dividida pelo fator de sensibilidade. A coordenação "
                   "de tempo segue o mesmo critério da função 51."),
    "Função 50": ("O elemento instantâneo de fase não deve sobrealcançar a barra remota: o pickup fica acima da maior corrente de "
                  "falta trifásica/bifásica vista a 100% da linha, com fator de segurança."),
    "Função 50N": ("O elemento instantâneo de neutro segue o critério da função 50, usando a corrente de falta fase-terra a 100% da linha."),
    "Função 67": ("O elemento direcional de fase decide o sentido da falta pelo ângulo entre a corrente da fase de maior corrente e a tensão "
                  "de polarização em quadratura (conexão 90°: Ia com Vbc, Ib com Vca, Ic com Vab), que se mantém sã em faltas próximas. "
                  "O MTA é o ângulo de atraso da corrente de falta e a região de operação é MTA ± ROA."),
    "Função 67N": ("O elemento direcional de neutro compara a corrente residual 3I0 com a tensão de polarização −3V0. Em falta à frente, "
                   "−V0 = I0·Z0s, de modo que 3I0 atrasa −3V0 do ângulo da impedância de sequência zero atrás do relé; esse ângulo é o MTA. "
                   "Os limiares mínimos de 3V0 e 3I0 ficam acima da assimetria de regime e abaixo dos valores observados em falta."),
    "Corrente de referência": ("A corrente de referência de carga é a maior entre o fluxo máximo e o limite térmico, e serve de base "
                               "para os limites inferiores dos pickups de sobrecorrente."),
}


def _texto_modulos():
    for m in MOD.modulos():
        for cod, t in m.TEXTOS.items():
            if t.get("metodologia"):
                TEXTO_SECAO[t["secao"]] = t["metodologia"]


_texto_modulos()


def _funcs(r: dict) -> list[str]:
    return r.get("funcoes") or ["21", "68", "51"]


# --------------------------------------------------------------------------- helpers
def _shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{hex_}"/>')
    tcPr.append(shd)


def _borders(table, cor="BFBFBF"):
    tbl = table._tbl
    tblPr = tbl.tblPr
    b = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        + "".join(f'<w:{e} w:val="single" w:sz="4" w:space="0" w:color="{cor}"/>'
                  for e in ("top", "left", "bottom", "right", "insideH", "insideV"))
        + "</w:tblBorders>")
    tblPr.append(b)


def _run(par, texto, bold=False, italic=False, size=10, color=None):
    r = par.add_run(texto)
    r.font.name = FONTE
    r._element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
    if size is not None:
        r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return r


def _campo(par, instrucao, size=8, color=CINZA):
    """Insere um campo (PAGE, NUMPAGES, TOC...)."""
    r = par.add_run()
    r.font.size = Pt(size)
    r.font.name = FONTE
    r.font.color.rgb = RGBColor.from_string(color)
    for tipo, txt in (("begin", None), (None, instrucao), ("separate", None), (None, "1"), ("end", None)):
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
            r._r.append(el)
        else:
            if txt == "1":
                t = OxmlElement("w:t")
                t.text = "1"
                r._r.append(t)
            else:
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = f" {txt} "
                r._r.append(it)


def _texto_par(p_el) -> str:
    return "".join(t.text or "" for t in p_el.iter(qn("w:t"))).strip()


def _set_par_texto(p_el, novo: str):
    ts = list(p_el.iter(qn("w:t")))
    if ts:
        ts[0].text = novo
        ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for t in ts[1:]:
            t.text = ""


def _substituir(raiz, exatos: dict, contem: dict):
    """Troca o texto de parágrafos do modelo (preserva formatação do 1º trecho)."""
    for p_el in raiz.iter(qn("w:p")):
        tx = _texto_par(p_el)
        if not tx:
            continue
        if tx in exatos:
            _set_par_texto(p_el, exatos[tx])
            continue
        for old, new in contem.items():
            if old in tx:
                _set_par_texto(p_el, new)
                break


def _logo_texto(w, h, linhas, jpg=False) -> bytes:
    """Imagem simples (texto) no lugar do logotipo do cliente do modelo."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    y = h * 0.28
    for i, t in enumerate(linhas):
        tam = int(h * (0.22 if i == 0 else 0.15))
        try:
            f = ImageFont.truetype("DejaVuSans-Bold.ttf", tam)
        except Exception:
            try:
                f = ImageFont.load_default(tam)
            except Exception:
                f = ImageFont.load_default()
        d.text((w / 2, y), t, fill=(60, 60, 60), font=f, anchor="mm")
        y += h * 0.30
    b = io.BytesIO()
    im.save(b, format="JPEG" if jpg else "PNG")
    return b.getvalue()


class Relatorio:
    def __init__(self, projeto: dict, logo: bytes | None = None):
        self.p = projeto
        self.tpl = TEMPLATE.exists()
        self.doc = Document(str(TEMPLATE)) if self.tpl else Document()
        self.logo = logo
        self._fig = 0
        self._heads = []
        self._toc_ref = None
        self._tab = 0
        self._config()

    # ------------------------------------------------------------ configuração
    def _config(self):
        if self.tpl:
            return self._config_modelo()
        d = self.doc
        sec = d.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(2.0)
        sec.top_margin, sec.bottom_margin = Cm(2.6), Cm(2.2)
        st = d.styles["Normal"]
        st.font.name = FONTE
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
        st.font.size = Pt(10)
        st.paragraph_format.space_after = Pt(4)
        st.paragraph_format.line_spacing = 1.12
        for nome, tam, cor in (("Heading 1", 14, AZUL_ESCURO), ("Heading 2", 12, AZUL), ("Heading 3", 10.5, AZUL)):
            h = d.styles[nome]
            h.font.name = FONTE
            h.element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
            h.element.rPr.rFonts.set(qn("w:ascii"), FONTE)
            h.element.rPr.rFonts.set(qn("w:hAnsi"), FONTE)
            h.font.size = Pt(tam)
            h.font.bold = True
            h.font.color.rgb = RGBColor.from_string(cor)
            h.paragraph_format.space_before = Pt(14 if nome == "Heading 1" else 10)
            h.paragraph_format.space_after = Pt(5)
            h.paragraph_format.keep_with_next = True
        # atualizar campos (sumário) ao abrir
        settings = d.settings.element
        upd = OxmlElement("w:updateFields")
        upd.set(qn("w:val"), "true")
        settings.append(upd)
        self._cabecalho_rodape(sec)

    def _config_modelo(self):
        """Usa o DOCUMENTO PADRÃO BK: mantém capa + seção 1, apaga o conteúdo de exemplo e preenche capa/cabeçalho."""
        d = self.doc
        p = self.p
        body = d.element.body
        for el in list(body)[3:]:                       # 0 = capa, 1-2 = quebra de seção
            if el.tag != qn("w:sectPr"):
                body.remove(el)
        hoje = date.today().strftime("%d/%m/%Y")
        cliente = (p.get("cliente") or "CLIENTE").strip()
        numdoc = p.get("numero_doc") or "—"
        rev = str(p.get("revisao") or "00")
        titulo = p.get("titulo_capa") or "MEMÓRIA DE CÁLCULO E TABELA DE AJUSTES"
        exatos = {"EMISSÃO INICIAL": p.get("motivo_rev") or "EMISSÃO INICIAL", "Diretor": p.get("aprovador") or "Diretor",
                  "ESE-2LAG-721-059-MC": numdoc, "02/09/2026": hoje, "0": rev, "0A": rev,
                  "SE Lagartos II": cliente.upper(), "PROJETO EXECUTIVO": p.get("subtitulo_capa") or "ESTUDO DE PARAMETRIZAÇÃO DE PROTEÇÃO SISTÊMICA"}
        contem = {"MEMÓRIA DE CÁLCULO ESTRUTURAL": titulo,
                  "Memória de Cálculo – Parede Corta-Fogo": p.get("titulo_cab") or f"Memória de Cálculo – Proteção Sistêmica — {cliente}"}
        _substituir(body, exatos, contem)
        for sec in d.sections:
            _substituir(sec.header._element, exatos, contem)
        cp = d.core_properties
        cp.title = f"Memória de Cálculo – Estudo de Proteção Sistêmica — {cliente}"
        cp.author = "BARABACH & KNOPP ENGENHARIA E TECNOLOGIA"
        settings = d.settings.element
        if settings.find(qn("w:updateFields")) is None:
            upd = OxmlElement("w:updateFields")
            upd.set(qn("w:val"), "true")
            settings.append(upd)

    def _trocar_logos(self, dados: bytes) -> bytes:
        """O modelo traz o logotipo de outro cliente: troca por texto com o nome do cliente deste projeto."""
        cli = (self.p.get("cliente") or "CLIENTE").strip().upper()
        linhas = cli.split(" TRANSMISS", 1)
        linhas = [linhas[0], "TRANSMISSÃO" + linhas[1]] if len(linhas) == 2 else [cli]
        trocas = {"word/media/image2.png": _logo_texto(563, 181, linhas),
                  "word/media/image4.jpg": _logo_texto(385, 123, linhas, jpg=True)}
        ent, sai = io.BytesIO(dados), io.BytesIO()
        with zipfile.ZipFile(ent) as zi, zipfile.ZipFile(sai, "w", zipfile.ZIP_DEFLATED) as zo:
            for it in zi.infolist():
                zo.writestr(it, trocas.get(it.filename, zi.read(it.filename)))
        return sai.getvalue()

    def _cabecalho_rodape(self, sec):
        p = self.p
        hdr = sec.header
        hdr.is_linked_to_previous = False
        t = hdr.add_table(1, 3, Cm(17))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _borders(t, "7F7F7F")
        larguras = (Cm(3.6), Cm(9.4), Cm(4.0))
        for i, w in enumerate(larguras):
            t.rows[0].cells[i].width = w
        c0, c1, c2 = t.rows[0].cells
        c0.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if self.logo:
            try:
                c0.paragraphs[0].add_run().add_picture(io.BytesIO(self.logo), width=Cm(2.6))
            except Exception:
                _run(c0.paragraphs[0], "BK", bold=True, size=16, color=AZUL)
        else:
            _run(c0.paragraphs[0], "BK", bold=True, size=18, color=AZUL)
            q = c0.add_paragraph()
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(q, "ENGENHARIA E TECNOLOGIA", size=5.5, color=CINZA)
        c1.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(c1.paragraphs[0], "BARABACH & KNOPP ENGENHARIA E TECNOLOGIA", bold=True, size=9, color=AZUL_ESCURO)
        q = c1.add_paragraph()
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(q, "Estudo de Parametrização de Proteção Sistêmica — Memória de Cálculo", size=8, color=CINZA)
        c2.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
        _run(c2.paragraphs[0], f"Doc.: {p.get('numero_doc') or '—'}", size=8, bold=True)
        q = c2.add_paragraph()
        _run(q, f"Rev.: {p.get('revisao') or '00'}   Pág. ", size=8)
        _campo(q, "PAGE", size=8, color="000000")
        _run(q, " / ", size=8)
        _campo(q, "NUMPAGES", size=8, color="000000")
        for c in (c0, c1, c2):
            for par in c.paragraphs:
                par.paragraph_format.space_after = Pt(0)
        # remove parágrafo vazio inicial do cabeçalho
        if hdr.paragraphs and not hdr.paragraphs[0].text:
            hdr.paragraphs[0]._p.getparent().remove(hdr.paragraphs[0]._p)

        ftr = sec.footer
        ftr.is_linked_to_previous = False
        fp = ftr.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(fp, "Este documento é de propriedade da BARABACH & KNOPP ENGENHARIA E TECNOLOGIA, não sendo permitida a sua "
                 "reprodução ou comunicação a terceiros sem prévia autorização.", size=7, color=CINZA)

    # ------------------------------------------------------------ elementos
    def h(self, texto, nivel=1):
        if not self.tpl:
            return self.doc.add_heading(texto, level=nivel)
        if nivel == 1:                                  # numeração automática do estilo do modelo
            t_ = re.sub(r"^\d+\.\s*", "", texto)
            self._heads.append((1, f"{sum(1 for n_, _ in self._heads if n_ == 1) + 1}. {t_.upper()}"))
            return self.doc.add_paragraph(t_, style="1. Título BK principal")
        if nivel == 2:                                  # o modelo digita a numeração no texto (numeração automática desligada)
            q = self.doc.add_paragraph(texto, style="1.1. Subtítulo BK")
            q._p.get_or_add_pPr().append(parse_xml(
                f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'))
            self._heads.append((2, texto))
            return q
        q = self.doc.add_paragraph(style="Body Text")
        q.paragraph_format.keep_with_next = True
        q.paragraph_format.space_after = Pt(4)
        _run(q, texto, bold=True, size=None, color=None)
        return q

    def par(self, texto, bold=False, italic=False, size=10, align=None, color=None, space_after=None):
        p = self.doc.add_paragraph(style="Body Text") if self.tpl else self.doc.add_paragraph()
        _run(p, texto, bold=bold, italic=italic, size=(None if self.tpl and size == 10 else size), color=color)
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "justify":
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if space_after is not None:
            p.paragraph_format.space_after = Pt(space_after)
        return p

    def bullets(self, itens):
        for it in itens:
            if self.tpl:                                # o modelo usa "- texto" em Body Text
                p = self.doc.add_paragraph(style="Body Text")
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p.paragraph_format.space_after = Pt(4)
                _run(p, "- " + it, size=None)
            else:
                p = self.doc.add_paragraph(style="List Bullet")
                _run(p, it, size=10)

    def eq(self, expr):
        p = self.doc.add_paragraph(style="Body Text") if self.tpl else self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_together = True
        try:
            inserir_equacao(p, expr)
        except Exception:                                   # fallback: texto simples
            _run(p, expr, italic=True, size=9)
        return p

    def legenda(self, tipo, texto):
        if tipo == "Figura":
            self._fig += 1
            n = self._fig
        else:
            self._tab += 1
            n = self._tab
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(p, f"{tipo} {n} — {texto}", italic=True, size=8.5, color=CINZA)
        return p

    def tabela(self, cab, linhas, larguras=None, legenda=None, tam=8.5, alinha_num=True):
        if legenda:
            self.legenda("Tabela", legenda)
        t = self.doc.add_table(rows=1, cols=len(cab))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        if self.tpl:                                    # padrão do modelo: cabeçalho cinza D9D9D9, bordas pretas
            _borders(t, "000000")
            if larguras:
                fator = LARG_UTIL_CM / sum(larguras)
                larguras = [w * fator for w in larguras]
            t._tbl.tblPr.append(parse_xml(
                f'<w:tblCellMar {nsdecls("w")}><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
                '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'))
        else:
            _borders(t)
        for i, c in enumerate(cab):
            cel = t.rows[0].cells[i]
            _shade(cel, "D9D9D9" if self.tpl else AZUL_ESCURO)
            cel.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(cel.paragraphs[0], str(c), bold=True, size=tam, color=(None if self.tpl else "FFFFFF"))
        # cabeçalho repetido
        trPr = t.rows[0]._tr.get_or_add_trPr()
        trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
        for n, lin in enumerate(linhas):
            row = t.add_row()
            trPr = row._tr.get_or_add_trPr()
            trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
            for i, v in enumerate(lin):
                cel = row.cells[i]
                if n % 2 and not self.tpl:
                    _shade(cel, CINZA_CLARO)
                txt = str(v)
                par = cel.paragraphs[0]
                par.paragraph_format.space_after = Pt(0)
                eh_num = alinha_num and i > 0 and _eh_numero(txt)
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER if eh_num or len(txt) < 12 and i > 0 else WD_ALIGN_PARAGRAPH.LEFT
                cor = None
                neg = txt in ("FALHA", "REVISAR", "NÃO CONFORME")
                _run(par, txt, size=tam, bold=neg, color=(None if self.tpl else ("1F3864" if neg else cor)))
        if larguras:
            for i, w in enumerate(larguras):             # grade da tabela (Word/LibreOffice respeitam tblGrid)
                t.columns[i].width = Cm(w)
            for row in t.rows:
                for i, w in enumerate(larguras):
                    row.cells[i].width = Cm(w)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def figura(self, fig, largura=15.5, legenda=""):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=170)
        import matplotlib.pyplot as _plt
        _plt.close(fig)                                  # libera memória (relatórios com muitos gráficos)
        buf.seek(0)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(buf, width=Cm(min(largura, LARG_UTIL_CM) if self.tpl else largura))
        p.paragraph_format.keep_with_next = True
        self.legenda("Figura", legenda)

    def quebra(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ------------------------------------------------------------ capa
    def capa(self):
        if self.tpl:                                    # a capa já vem do modelo
            return
        d = self.doc
        p = self.p
        for _ in range(3):
            d.add_paragraph()
        t = d.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.rows[0].cells[0]
        _shade(c, AZUL_ESCURO)
        par = c.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_before = Pt(26)
        _run(par, (p.get("cliente") or "CLIENTE").upper(), bold=True, size=15, color="FFFFFF")
        for txt, tam, neg in (("ESTUDO DE PARAMETRIZAÇÃO DE PROTEÇÃO SISTÊMICA", 14, True),
                              ("MEMÓRIA DE CÁLCULO E TABELA DE AJUSTES", 11, False),
                              (p.get("nome") or "", 11, False)):
            q = c.add_paragraph()
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            q.paragraph_format.space_before = Pt(8)
            _run(q, txt, bold=neg, size=tam, color="FFFFFF")
        c.add_paragraph().paragraph_format.space_after = Pt(20)
        d.add_paragraph()
        info = [("Documento nº", p.get("numero_doc") or "—"), ("Revisão", p.get("revisao") or "00"),
                ("Data", date.today().strftime("%d/%m/%Y")), ("Contato do cliente", p.get("contato") or "—"),
                ("Documento de referência", p.get("referencia") or "—")]
        t2 = d.add_table(rows=0, cols=2)
        t2.alignment = WD_TABLE_ALIGNMENT.CENTER
        t2.autofit = False
        _borders(t2)
        for k, v in info:
            r = t2.add_row()
            _shade(r.cells[0], AZUL_PALIDO)
            _run(r.cells[0].paragraphs[0], k, bold=True, size=9)
            _run(r.cells[1].paragraphs[0], v, size=9)
            r.cells[0].width, r.cells[1].width = Cm(5), Cm(12)
        d.add_paragraph()
        self.par("Controle de revisões", bold=True, size=10, color=AZUL_ESCURO)
        self.tabela(["Rev.", "Motivo da revisão", "Data", "Exec.", "Verif.", "Aprov."],
                    [[p.get("revisao") or "00", "Emissão", date.today().strftime("%d/%m/%Y"), "", "", ""]],
                    larguras=[1.5, 7.0, 2.5, 2.0, 2.0, 2.0])
        self.quebra()

    def sumario(self):
        if self.tpl:
            q = self.doc.add_paragraph(style="Body Text")
            _run(q, "SUMÁRIO", bold=True, size=None)
            self._toc_ref = q._p                         # as linhas do sumário são inseridas ao salvar
            self.quebra()
            return
        else:
            self.h("Sumário", 1)
        par = self.doc.add_paragraph()
        _campo(par, 'TOC \\o "1-2" \\h \\z \\u', size=10, color="000000")
        self.par("(Se o sumário aparecer vazio, clique com o botão direito sobre ele e escolha “Atualizar campo”.)",
                 italic=True, size=8, color=CINZA)
        self.quebra()

    # ------------------------------------------------------------ conteúdo
    def objetivo(self, resultados):
        self.h("1. Objetivo e escopo", 1)
        n = len(resultados)
        todas = []
        for r in resultados:
            for f in _funcs(r):
                if f not in todas:
                    todas.append(f)
        ordem = {f: i for i, f in enumerate(["21", "68", "50", "51", "50N", "51N", "67", "67N"] + MOD.codigos())}
        todas.sort(key=lambda f: ordem.get(f, 99))
        self.par("Este documento apresenta o estudo de parametrização das funções de proteção selecionadas para "
                 f"{n} terminal(is), com a memória de cálculo completa e a tabela de ajustes recomendados. "
                 "Funções abrangidas:", align="justify")
        self.bullets([rotulo(f) for f in todas])
        self.par("O serviço é um estudo técnico realizado em escritório: são entregues os valores de ajuste calculados. "
                 "A aplicação dos ajustes nos relés, os ensaios e o comissionamento são de responsabilidade da contratante.",
                 align="justify")
        self.tabela(["LT / Terminal", "Relé", "Funções", "Tipo de trabalho"],
                    [[f"{r['entrada'].get('lt_nome','')} — {r['entrada'].get('terminal','')}",
                      f"{r['entrada'].get('fabricante','')} {r['entrada'].get('modelo','')}".strip(),
                      ", ".join(_funcs(r)),
                      "Cálculo de novos ajustes" if r["entrada"].get("modo") != "conferencia" else "Conferência de conformidade"]
                     for r in resultados],
                    larguras=[6.0, 3.6, 3.6, 3.8], legenda="Terminais abrangidos pelo estudo")

    def referencias(self, resultados=None):
        self.h("2. Referências", 1)
        if self.p.get("referencia"):
            self.par(f"Documento de referência do cliente: {self.p['referencia']}.", align="justify")
        sel_ = [f for r in (resultados or []) for f in _funcs(r)]
        self.bullets(REFERENCIAS + MOD.referencias(sel_))

    def entrada(self, resultados):
        self.h("3. Dados de entrada", 1)
        self.par("Os dados abaixo foram fornecidos pela contratante e são de sua responsabilidade quanto à integridade e "
                 "atualidade. Impedâncias em ohms primários, salvo indicação.", align="justify")
        for r in resultados:
            e = r["entrada"]
            self.h(f"3.{resultados.index(r) + 1}. {e.get('lt_nome','')} — {e.get('terminal','')}", 2)
            fs = _funcs(r)
            dist = "21" in fs or "68" in fs
            lin = [["Funções ajustadas", ", ".join(fs)],
                   ["Tensão nominal", f"{fmt(e['vn_kv'],1)} kV"]]
            if dist:
                lin += [["Comprimento", f"{fmt(e['comp_km'],1)} km"],
                        ["Z1 da LT (R1 + jX1)", f"{fmt(e['r1'])} + j{fmt(e['x1'])} Ω"],
                        ["Z0 da LT (R0 + jX0)", f"{fmt(e['r0'])} + j{fmt(e['x0'])} Ω"]]
            lin += [["RTC / RTP", f"{fmt(e['rtc'],1)} / {fmt(e['rtp'],1)}"],
                    ["Fluxo máximo", f"{fmt(e['s_max_mva'],1)} MVA"],
                    ["Limite térmico", f"{fmt(e['i_term_a'],0)} A"]]
            if dist:
                lin += [["Tensão mínima operativa", f"{fmt(e['v_min_pu'],2)} pu"],
                        ["Ângulos de carga (indutivo / capacitivo)", f"{fmt(e['phi_pos'],1)}° / {fmt(e['phi_neg'],1)}°"]]
            if "68" in fs:
                lin += [["Icc 3F barra local / remota", f"{fmt(e['icc3f_loc_ka'],2)} / {fmt(e['icc3f_rem_ka'],2)} kA"],
                        ["Frequência de escorregamento máxima", f"{fmt(e['f_slip_max'],2)} Hz"]]
            if "21" in fs:
                lin += [["Impedância do adjacente (mín. / máx.)", f"{fmt(e['zadj_min'])} / {fmt(e['zadj_max'])} Ω"]]
            if "51" in fs:
                lin += [["Curva 51 / tempo do dispositivo a jusante", f"{e.get('curva51','IEC NI')} / {fmt(e.get('t_jus_s',0),2)} s"]]
            if "51N" in fs:
                lin += [["Curva 51N / tempo do dispositivo a jusante", f"{e.get('curva51n','IEC NI')} / {fmt(e.get('t_jus_n_s',0),2)} s"]]
            if "67" in fs:
                lin += [["Curva 67 / tempo do dispositivo a jusante", f"{e.get('curva67','IEC NI')} / {fmt(e.get('t_jus_67_s',0),2)} s"]]
            if "67N" in fs:
                lin += [["Curva 67N / tempo do dispositivo a jusante", f"{e.get('curva67n','IEC NI')} / {fmt(e.get('t_jus_67n_s',0),2)} s"]]
            dr_ = r.get("direcional") or {}
            for k_, rot_ in (("p67", "67"), ("p67n", "67N")):
                if k_ in dr_:
                    lin += [[f"Casos com fasores — função {rot_} (à frente / à ré)", f"{dr_[k_]['n_frente']} / {dr_[k_]['n_re']}"]]
            for sp in MOD.entradas(fs, conf=False):
                v = e.get(sp["k"], sp["pad"])
                lin.append([sp["rot"], fmt(v, 2) if isinstance(v, (int, float)) else str(v)])
            self.tabela(["Parâmetro", "Valor"], lin, larguras=[9.0, 8.0], legenda=f"Dados de entrada — {e.get('terminal','')}")

    def metodologia(self, resultados: list[dict]):
        self.h("4. Metodologia e equações", 1)
        self.h("4.1. Premissas do modelo", 2)
        fs = {f for r in resultados for f in _funcs(r)}
        prem = []
        if fs & {"21", "68"}:
            prem += ["Zonas de distância modeladas como círculos mho com diâmetro sobre a impedância da LT."]
        if "68" in fs:
            prem += ["Fontes com mesma magnitude de tensão durante a oscilação e ângulo de impedância igual ao da LT (sistema homogêneo).",
                     "Blinders como retas paralelas à impedância da LT, à distância perpendicular d da linha.",
                     "Impedâncias de fonte obtidas dos níveis de curto-circuito trifásico: Z = Vn / (√3·Icc)."]
        if fs & {"50", "51", "50N", "51N"}:
            prem += ["Nos casos de curto-circuito, a posição da falta é medida a partir do terminal do relé (0% = barra local; 100% = barra remota).",
                     "Para falta fase-terra, a corrente informada é a corrente de falta (= 3·I0, corrente residual).",
                     "Curvas temporizadas conforme IEC 60255-151: t = TMS · k / ((I/Ipk)^α − 1); o TMS é arredondado para cima no passo do relé, "
                     "preservando o intervalo de coordenação."]
        if fs & {"67", "67N"}:
            prem += ["Funções direcionais: sequência de fases A-B-C; corrente positiva saindo da barra do relé em direção à linha; "
                     "tensões em kV fase-neutro no ponto de instalação do relé.",
                     "MTA obtido da média circular dos casos à frente, arredondado ao passo do relé; região de operação MTA ± ROA (ROA = 90°).",
                     "Polarização do 67N por 3V0 e do 67 por tensão em quadratura; polarização por sequência negativa, memória de tensão e "
                     "elemento instantâneo direcional não foram consideradas."]
        for cod_ in sorted(fs):
            for t_ in MOD.textos(cod_).get("premissas", []):
                if t_ not in prem:
                    prem.append(t_)
        prem += ["Valores calculados são recomendações; a validação final dos limites de faixa e passo de cada relé é feita na parametrização."]
        self.bullets(prem)
        ordem, fonte = [], {}
        for r in resultados:
            for pa in r["passos"]:
                if pa["secao"] not in ordem:
                    ordem.append(pa["secao"])
                    fonte[pa["secao"]] = r
        for i, sec in enumerate(ordem, 2):
            self.h(f"4.{i}. {sec}", 2)
            if sec in TEXTO_SECAO:
                self.par(TEXTO_SECAO[sec], align="justify")
            for pa in [x for x in fonte[sec]["passos"] if x["secao"] == sec]:
                self.par(pa["titulo"] + ":", bold=True, size=9.5, space_after=1)
                self.eq(pa["simb"])
        if any(r.get("validacao") for r in resultados):
            self.h(f"4.{len(ordem) + 2}. Validação cruzada com curto-circuito", 2)
            self.par("Para cada falta importada do programa de curto-circuito, a impedância aparente é Z = m·ZL + Rf (m = posição na LT). "
                     "Verifica-se a zona de atuação e a posição relativa aos blinders: faltas saltam diretamente para dentro do blinder interno, "
                     "percorrendo a distância entre blinders em tempo inferior ao OSBD, e portanto não são bloqueadas.", align="justify")
            self.eq(r"Z_{ap} = m \cdot Z_{L,sec} + R_{f} \cdot k_{s} \qquad d_{perp} = \left| \mathrm{Im}\left( Z_{ap} \cdot e^{-j\theta_{L}} \right) \right|")

    def resultado_terminal(self, idx, r):
        e = r["entrada"]
        o = r.get("oos")
        c = r["criterios"]
        fs = _funcs(r)
        titulo = f"{e.get('lt_nome','')} — {e.get('terminal','')} ({e.get('fabricante','')} {e.get('modelo','')})".strip()
        self.h(f"5.{idx}. {titulo}", 2)

        if r["alertas"]:
            self.par("Pontos de atenção", bold=True, color=AZUL_ESCURO, size=10, space_after=2)
            self.bullets(r["alertas"])

        self.h("Memória de cálculo", 3)
        secao_atual = None
        for pa in r["passos"]:
            if pa["secao"] != secao_atual:
                secao_atual = pa["secao"]
                self.par(secao_atual, bold=True, size=9.5, color=AZUL, space_after=1)
            self.par(pa["titulo"], size=9, space_after=0)
            self.eq(pa["num"])
            if pa.get("nota"):
                self.par(pa["nota"], italic=True, size=8.5, color=CINZA)

        self.h("Resultados", 3)
        z = r["zonas"]
        if "21" in fs and z:
            self.tabela(["Zona", "Alcance (Ω sec)", "Alcance (Ω pri)", "Ângulo"],
                    [[n, fmt(z[n]["alcance"]), fmt(z[n]["pri"]), f"{fmt(z[n]['ang'],1)}°"] for n in ("Z1", "Z2", "Z3", "Zrev")],
                    larguras=[3, 4.5, 4.5, 3.5], legenda="Alcances das zonas de distância")
        cg = r["carga"]
        if cg:
            self.tabela(["Grandeza", "Valor"],
                    [["Corrente de referência de carga", f"{fmt(cg['i_ref'],1)} A"],
                     ["Menor impedância de carga", f"{fmt(cg['z_carga'])} Ω sec ({fmt(cg['z_carga_pri'])} Ω pri)"],
                     ["ZLF / ZLR", f"{fmt(cg['zlf'])} Ω sec"],
                     ["Ângulos PLAF / NLAF", f"{fmt(cg['plaf'],1)}° / {fmt(cg['nlaf'],1)}°"],
                     ["Load encroachment necessário", "Sim" if cg["load_enc_necessario"] else "Não (mantido como segurança)"]],
                    larguras=[8.0, 9.0], legenda="Região de carga")
        if "68" in fs and o:
            self.tabela(["Grandeza", "Interno", "Externo"],
                    [["Distância perpendicular d (Ω sec)", fmt(o["d_in"]), fmt(o["d_out"])],
                     ["Interseção com eixo R (Ω sec)", fmt(o["r_in"]), fmt(o["r_out"])],
                     ["Reatância superior (Ω sec)", fmt(o["x_top_in"]), fmt(o["x_top_out"])],
                     ["Reatância inferior (Ω sec)", fmt(o["x_bot_in"]), fmt(o["x_bot_out"])],
                     ["Ângulo entre fontes (graus)", fmt(o["delta_in"], 1), fmt(o["delta_out"], 1)],
                     ["Velocidade de impedância (Ω/s sec)", fmt(o["v_in"], 1), fmt(o["v_out"], 1)]],
                    larguras=[8.0, 4.5, 4.5], legenda="Blinders e velocidade de impedância")
        if "68" in fs and o:
            self.tabela(["Grandeza", "Valor"],
                    [["Impedância total Zt (Ω sec)", fmt(o["zt"])],
                     ["Tempo entre blinders (f_slip máx.)", f"{fmt(o['t_min_s']*1000,1)} ms ({fmt(o['t_min_s']*e['f_hz'],2)} ciclos)"],
                     ["OSBD adotado", f"{fmt(o['osbd_ciclos'],2)} ciclos ({fmt(o['osbd_s']*1000,1)} ms)"],
                     ["Maior f_slip detectada pelo OSB", f"{fmt(o['f_slip_detectavel'],2)} Hz"]],
                    larguras=[8.0, 9.0], legenda="Temporização do OSB")
        if r["tabela_fslip"]:
            self.tabela(["f_slip (Hz)", "Tempo entre blinders (ms)", "Ciclos", "OSB bloqueia?"],
                        [[fmt(x["f_slip"], 2), fmt(x["t_ms"], 1), fmt(x["t_ciclos"], 2), "Sim" if x["osb_bloqueia"] else "Não"]
                         for x in r["tabela_fslip"]],
                        larguras=[3.5, 5.0, 3.0, 4.0], legenda="Resposta do OSB por frequência de escorregamento")
        sc = r.get("sobrecorrente") or {}
        inst = [(c_, sc[k]) for c_, k in (("50", "p50"), ("50N", "p50n")) if k in sc]
        if inst:
            self.tabela(["Função", "Icc a 100% da LT (kA)", "Mínimo k·Icc (A pri)", "Pickup recomendado", "Icc mín. em ≤50% da LT (kA)"],
                        [[c_, fmt(p_.get("icc_rem_ka", 0), 2), fmt(p_["min_pri"], 0) if p_.get("calculado") else "não calculado",
                          f"{fmt(p_['rec_pri'], 0)} A pri = {fmt(p_['rec_sec'], 2)} A sec" if p_.get("calculado") else "—",
                          fmt(p_.get("icc_prox_ka", 0), 2) if p_.get("calculado") else "—"] for c_, p_ in inst],
                        larguras=[1.8, 3.4, 3.6, 4.6, 3.6], tam=8, legenda="Funções 50/50N — pickup instantâneo")
        temp = [(c_, sc[k]) for c_, k in (("51", "p51"), ("51N", "p51n")) if k in sc]
        if temp:
            self.tabela(["Função", "Mín. (A pri)", "Máx. (A pri)", "Pickup", "Curva", "TMS", "Atuação na falta remota (s)"],
                        [[c_, fmt(p_["min_pri"], 0), fmt(p_["max_pri"], 0) if p_["max_pri"] else "não verificado",
                          f"{fmt(p_['rec_pri'], 0)} A pri = {fmt(p_['rec_sec'], 2)} A sec", p_["curva"],
                          fmt(p_["tms"], 2) if p_.get("tms") is not None else "n/d",
                          fmt(p_["t_op_s"], 3) if p_.get("t_op_s") is not None else "n/d"] for c_, p_ in temp],
                        larguras=[1.6, 2.2, 2.4, 4.2, 2.0, 1.4, 3.6], tam=8, legenda="Funções 51/51N — faixa do pickup, curva e TMS")

        dr = r.get("direcional") or {}
        dirs = [(c_, dr[k]) for c_, k in (("67", "p67"), ("67N", "p67n")) if k in dr]
        if dirs:
            self.tabela(["Função", "MTA (°)", "ROA (°)", "Mín. (A pri)", "Máx. (A pri)", "Pickup", "Curva", "TMS", "Atuação (s)"],
                        [[c_, fmt(p_["mta"], 0), fmt(p_["roa"], 0), fmt(p_["min_pri"], 0),
                          fmt(p_["max_pri"], 0) if p_["max_pri"] else "n/v",
                          f"{fmt(p_['rec_pri'], 0)} A pri = {fmt(p_['rec_sec'], 2)} A sec", p_["curva"],
                          fmt(p_["tms"], 2) if p_.get("tms") is not None else "n/d",
                          fmt(p_["t_op_s"], 3) if p_.get("t_op_s") is not None else "n/d"] for c_, p_ in dirs],
                        larguras=[1.4, 1.5, 1.5, 2.0, 2.0, 3.8, 1.6, 1.3, 1.9], tam=7.5,
                        legenda="Funções 67/67N — MTA, pickup, curva e TMS (n/v = não verificado)")
            for c_, p_ in dirs:
                if p_["casos"]:
                    self.tabela(["Caso", "Tipo", "Sentido", "|I| (kA)", "∠I (°)", "Atraso de I (°)", "Desvio do máx. torque (°)", "Folga (°)", "Resultado"],
                                [[x["caso"], x["tipo"], "frente" if x["sentido"] == "frente" else "ré", fmt(x["i_mod"], 2),
                                  fmt(x["i_ang"], 1), fmt(x["lag"], 1), fmt(x["desvio"], 1), fmt(x["folga"], 1),
                                  "OK" if x["ok"] else "FALHA"] for x in p_["casos"]],
                                larguras=[2.4, 1.2, 1.6, 1.8, 1.8, 2.2, 2.6, 1.7, 1.7], tam=7.5,
                                legenda=f"Verificação direcional {c_} por caso (MTA {fmt(p_['mta'],0)}° — {p_['mta_origem']})")

        if r["validacao"]:
            self.tabela(["Caso", "Tipo", "Local (%)", "|Z| (Ω)", "∠ (°)", "Zona", "d_perp (Ω)", "Dentro bl. int."],
                        [[v["caso"], v["tipo"], fmt(v["local_pct"], 0), fmt(v["z_mod"]), fmt(v["z_ang"], 1), v["zona"],
                          fmt(v["d_perp"]), "Sim" if v["dentro_blinder_int"] else "Não"] for v in r["validacao"]],
                        larguras=[2.6, 1.4, 1.8, 2.0, 1.8, 2.8, 2.2, 2.4], tam=8, legenda="Validação cruzada com os casos de curto-circuito")

        self.tabela(["Item", "Critério", "Valor", "Limite", "Status"],
                    [[v["item"], v["criterio"], fmt(v["valor"]) if isinstance(v["valor"], (int, float)) else v["valor"],
                      fmt(v["limite"]) if isinstance(v["limite"], (int, float)) else v["limite"], v["status"]]
                     for v in r["verificacoes"]],
                    larguras=[3.6, 6.4, 2.2, 2.2, 2.6], tam=8, legenda="Verificações de critério")

        if r.get("conferencia"):
            self.h("Conferência dos ajustes existentes", 3)
            self.tabela(["Item", "Existente", "Mínimo", "Máximo", "Status"],
                        [[v["item"], fmt(v["existente"]) if isinstance(v["existente"], (int, float)) else v["existente"],
                          fmt(v["minimo"]) if isinstance(v["minimo"], (int, float)) else "—",
                          fmt(v["maximo"]) if isinstance(v["maximo"], (int, float)) else "—", v["status"]]
                         for v in r["conferencia"]],
                        larguras=[6.0, 2.6, 2.6, 2.6, 3.2], legenda="Checklist de conformidade dos ajustes existentes")

        if z and o:
            self.figura(grafico_rx(r, titulo=f"Diagrama R-X — {titulo}"), 15.5, f"Diagrama R-X (secundário) — {e.get('terminal','')}")
        if "68" in fs and o:
            self.figura(grafico_tempo_slip(r), 13.5, f"Tempo entre blinders x frequência de escorregamento — {e.get('terminal','')}")
        for c_, _p in dirs:
            fig_d = grafico_direcional(r, c_)
            if fig_d is not None:
                self.figura(fig_d, 10.5, f"Característica direcional {c_} e casos de falta — {e.get('terminal','')}")
        for tb_ in r.get("tabelas_extra", []):
            n_ = len(tb_["cab"])
            self.tabela(tb_["cab"], tb_["linhas"], larguras=[17.0 / n_] * n_, legenda=tb_["titulo"] + f" — {e.get('terminal','')}")
        for leg_, fig_x in MOD.figuras(r):
            self.figura(fig_x, 14.0, f"{leg_} — {e.get('terminal','')}")
        fig_c = grafico_curvas_sobrecorrente(r)
        if fig_c is not None:
            self.figura(fig_c, 14.0, f"Curvas tempo x corrente (funções 51/51N) — {e.get('terminal','')}")

        self.h("Ajustes recomendados", 3)
        self.tabela(["Função", "Parâmetro", "Nome (ref.)", "Valor sec.", "Un.", "Valor pri.", "Un."],
                    [[a["funcao"], a["parametro"], a["nome_rele"],
                      fmt(a["valor_sec"], 3) if isinstance(a["valor_sec"], (int, float)) else a["valor_sec"], a["unid_sec"],
                      fmt(a["valor_pri"], 3) if isinstance(a["valor_pri"], (int, float)) else a["valor_pri"], a["unid_pri"]]
                     for a in r["ajustes"]],
                    larguras=[3.0, 5.0, 2.0, 2.0, 1.4, 2.0, 1.4], tam=7.5, legenda=f"Ajustes recomendados — {e.get('terminal','')}")

    def conclusao(self, resultados):
        self.h("6. Conclusões", 1)
        linhas = []
        for r in resultados:
            e = r["entrada"]
            falhas = [v for v in r["verificacoes"] if v["status"] == "FALHA"]
            linhas.append([f"{e.get('lt_nome','')} — {e.get('terminal','')}", f"{len(r['ajustes'])}",
                           f"{len(falhas)}", "Revisar" if (falhas or r["alertas"]) else "Sem pendências"])
        self.tabela(["Terminal", "Nº de ajustes", "Verificações com falha", "Situação"], linhas,
                    larguras=[8.0, 2.8, 3.4, 3.0], legenda="Resumo do estudo")
        self.par("Os ajustes recomendados constam na planilha Excel que acompanha este relatório. Os nomes de parâmetros "
                 "indicados como referência devem ser conferidos no manual da versão de firmware de cada relé, assim como faixas, "
                 "passos e convenções de sinal, antes da aplicação.", align="justify")
        fs = {f for r in resultados for f in _funcs(r)}
        lim = []
        if "68" in fs:
            lim.append("o modelo de oscilação considera sistema homogêneo e fontes de mesma magnitude; a frequência de escorregamento "
                       "máxima deve ser confirmada pelos estudos de estabilidade")
        if fs & {"50", "51", "50N", "51N"}:
            lim.append("a coordenação de tempo das funções 51/51N considera o tempo informado do dispositivo a jusante e o intervalo de "
                       "coordenação adotado; a coordenação completa com todos os relés do caminho de falta deve ser verificada")
        if fs & {"67", "67N"}:
            lim.append("a verificação direcional depende dos fasores de falta fornecidos (sentido da corrente, sequência de fases e polaridade "
                       "de TCs/TPs devem ser conferidos); polarização por sequência negativa, memória de tensão e elemento instantâneo "
                       "direcional não foram avaliados")
        for cod_ in sorted(fs):
            for t_ in MOD.textos(cod_).get("limitacoes", []):
                if t_ not in lim:
                    lim.append(t_)
        lim.append("a aplicação, os ensaios e o comissionamento são responsabilidade da contratante")
        self.par("Limitações: " + "; ".join(lim) + ".", align="justify")

    def salvar(self, caminho_ou_buf):
        if not self.tpl:
            self.doc.save(caminho_ou_buf)
            return
        if self._toc_ref is not None:                    # sumário estático, como no modelo
            ant = self._toc_ref
            for nivel, txt in self._heads:
                q = self.doc.add_paragraph(style="Body Text")
                q.paragraph_format.space_after = Pt(2)
                q.paragraph_format.line_spacing = 1.0
                if nivel == 2:
                    q.paragraph_format.left_indent = Cm(0.8)
                _run(q, txt, size=None)
                ant.addnext(q._p)
                ant = q._p
        buf = io.BytesIO()
        self.doc.save(buf)
        dados = self._trocar_logos(buf.getvalue())
        if hasattr(caminho_ou_buf, "write"):
            caminho_ou_buf.write(dados)
        else:
            with open(caminho_ou_buf, "wb") as f:
                f.write(dados)


def _eh_numero(s: str) -> bool:
    t = s.replace(".", "").replace(",", "").replace("-", "").replace("°", "").replace(" ", "")
    return t.isdigit()


def gerar_relatorio(projeto: dict, resultados: list[dict], destino, logo: bytes | None = None):
    rel = Relatorio(projeto, logo)
    rel.capa()
    rel.sumario()
    rel.objetivo(resultados)
    rel.referencias(resultados)
    rel.entrada(resultados)
    rel.metodologia(resultados)
    rel.h("5. Resultados por terminal", 1)
    for i, r in enumerate(resultados, 1):
        rel.resultado_terminal(i, r)
    rel.conclusao(resultados)
    rel.salvar(destino)
