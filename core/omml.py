"""Equações nativas do Word (OMML) a partir de um subconjunto de LaTeX.

Suporta: \\frac{a}{b}, \\sqrt{x}, \\left( ... \\right), sub/sobrescritos (_ ^), letras gregas,
\\mathrm{texto}, operadores (\\cdot, \\times, \\le, \\ge, \\approx, \\pm, \\angle), funções
(\\sin, \\cos, \\arctan, \\min, \\max ...), \\qquad e \\ (espaço).
O resultado é inserido no .docx como equação editável (Inserir > Equação).
"""
from __future__ import annotations

from xml.sax.saxutils import escape

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

SIMBOLOS = {
    "cdot": "·", "times": "×", "angle": "∠", "theta": "θ", "varphi": "φ", "phi": "φ", "delta": "δ",
    "Delta": "Δ", "pi": "π", "Omega": "Ω", "omega": "ω", "geq": "≥", "ge": "≥", "leq": "≤", "le": "≤",
    "approx": "≈", "pm": "±", "alpha": "α", "mu": "μ", "rightarrow": "→", "circ": "°", "infty": "∞",
    "lambda": "λ", "sigma": "σ", "rho": "ρ", "tau": "τ", "psi": "ψ", "neq": "≠", "sum": "∑",
}
FUNCOES = {"sin": "sen", "cos": "cos", "tan": "tan", "cot": "cot", "csc": "csc", "sec": "sec",
           "arctan": "arctan", "arcsin": "arcsen", "arccos": "arccos", "min": "min", "max": "max",
           "log": "log", "ln": "ln", "exp": "exp", "arg": "arg"}
ESPACOS = {"qquad": "      ", "quad": "   ", " ": " ", ",": " ", ";": " "}


def _run(texto: str, upright: bool = False) -> str:
    if not texto:
        return ""
    rpr = '<m:rPr><m:sty m:val="p"/></m:rPr>' if upright else ""
    return f'<m:r>{rpr}<m:t xml:space="preserve">{escape(texto)}</m:t></m:r>'


class _Parser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def eof(self):
        return self.i >= len(self.s)

    def peek(self):
        return self.s[self.i] if not self.eof() else ""

    def sequencia(self, fim: str | None = None) -> str:
        out = []
        while not self.eof():
            ch = self.peek()
            if fim and ch == fim:
                break
            if ch == "}":                      # fecha grupo que o chamador trata
                break
            if ch.isspace():
                self.i += 1
                continue
            base = self.atomo()
            base = self.suffixes(base)
            out.append(base)
        return "".join(out)

    def grupo(self) -> str:
        """Lê {...} e devolve o conteúdo já convertido."""
        while self.peek().isspace():
            self.i += 1
        if self.peek() == "{":
            self.i += 1
            conteudo = self.sequencia()
            if self.peek() == "}":
                self.i += 1
            return conteudo
        # argumento de um só caractere
        if self.eof():
            return ""
        atomo = self.atomo()
        return atomo

    def suffixes(self, base: str) -> str:
        sub = sup = None
        while self.peek() in ("_", "^"):
            op = self.peek()
            self.i += 1
            arg = self.grupo()
            if op == "_":
                sub = arg
            else:
                sup = arg
        if sub is not None and sup is not None:
            return f"<m:sSubSup><m:e>{base}</m:e><m:sub>{sub}</m:sub><m:sup>{sup}</m:sup></m:sSubSup>"
        if sub is not None:
            return f"<m:sSub><m:e>{base}</m:e><m:sub>{sub}</m:sub></m:sSub>"
        if sup is not None:
            return f"<m:sSup><m:e>{base}</m:e><m:sup>{sup}</m:sup></m:sSup>"
        return base

    def atomo(self) -> str:
        ch = self.peek()
        if ch == "{":
            return self.grupo()
        if ch == "\\":
            return self.comando()
        self.i += 1
        # agrupa dígitos/vírgula decimais num único run para melhor espaçamento
        if ch.isdigit():
            j = self.i
            while j < len(self.s) and (self.s[j].isdigit() or
                                        (self.s[j] in ",." and j + 1 < len(self.s) and self.s[j + 1].isdigit())):
                j += 1
            num = ch + self.s[self.i:j]
            self.i = j
            return _run(num, upright=True)
        if ch in "()[]|":
            return _run(ch, upright=True)
        if ch in "=+-<>/,":
            return _run(ch, upright=True)
        return _run(ch)

    def comando(self) -> str:
        self.i += 1  # '\'
        if self.eof():
            return ""
        if not self.peek().isalpha():
            c = self.peek()
            self.i += 1
            return _run(ESPACOS.get(c, c), upright=True)
        j = self.i
        while j < len(self.s) and self.s[j].isalpha():
            j += 1
        nome = self.s[self.i:j]
        self.i = j
        if nome == "frac":
            num = self.grupo()
            den = self.grupo()
            return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"
        if nome == "sqrt":
            x = self.grupo()
            return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{x}</m:e></m:rad>'
        if nome in ("mathrm", "text"):
            if self.peek() == "{":
                self.i += 1
                j = self.i
                prof = 1
                while j < len(self.s) and prof:
                    if self.s[j] == "{":
                        prof += 1
                    elif self.s[j] == "}":
                        prof -= 1
                    j += 1
                txt = self.s[self.i:j - 1]
                self.i = j
                return _run(txt.replace("\\ ", " "), upright=True)
            return ""
        if nome == "left" or nome == "right":
            if self.peek() in "()[]|.":
                c = self.peek()
                self.i += 1
                return _run("" if c == "." else c, upright=True)
            return ""
        if nome in FUNCOES:
            return _run(FUNCOES[nome], upright=True)
        if nome in ESPACOS:
            return _run(ESPACOS[nome], upright=True)
        if nome in SIMBOLOS:
            return _run(SIMBOLOS[nome], upright=nome in ("cdot", "times", "angle", "geq", "ge", "leq", "le",
                                                         "approx", "pm", "circ", "rightarrow", "neq"))
        return _run(nome)


def latex_para_omath(expr: str) -> str:
    """Converte a expressão em <m:oMath>...</m:oMath> (sem namespaces declarados)."""
    p = _Parser(expr)
    corpo = p.sequencia()
    return f"<m:oMath>{corpo}</m:oMath>"


def inserir_equacao(paragrafo, expr: str, display: bool = True):
    """Insere a equação no parágrafo python-docx."""
    from docx.oxml import parse_xml
    omath = latex_para_omath(expr)
    if display:
        xml = f'<m:oMathPara xmlns:m="{M_NS}" xmlns:w="{W_NS}"><m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>{omath}</m:oMathPara>'
    else:
        xml = omath.replace("<m:oMath>", f'<m:oMath xmlns:m="{M_NS}" xmlns:w="{W_NS}">', 1)
    paragrafo._p.append(parse_xml(xml))
    return paragrafo
