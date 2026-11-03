"""Registro dos módulos de função de proteção com campos e critérios declarativos.

Cada módulo (core/f_*.py) declara:
  COD        códigos ANSI que ele calcula, ex.: ("27", "59", "81")
  ENTRADAS   lista de campos de entrada do terminal (E(...))
  CRITERIOS  lista de critérios editáveis na etapa 4 (K(...))
  TEXTOS     {cod: {"secao","metodologia","premissas","limitacoes"}}
  REFS       referências normativas adicionais
  calcular(d, c, casos, sel, incluir_base) -> {"passos","verif","alertas","ajustes","conferencia","dados","cards","tabelas"}
  figuras(r) -> [(legenda, matplotlib.Figure)]      (opcional)

O app (etapas 2, 4 e 5), o relatório Word e o manual são gerados a partir dessas declarações,
de modo que um novo módulo aparece em todos sem código adicional de interface.
"""
from __future__ import annotations

import importlib

NOMES_MODULOS = ["f_tensao_freq", "f_disjuntor", "f_diferencial", "f_gerador"]          # ordem de execução/relatório; novos lotes acrescentam aqui


def E(k, rot, pad, funcs, grupo, porque, como, onde, tipo="num", mn=0.0, mx=1e6, passo=1.0, fmt="%.2f",
      unid="", opcoes=None, conf=False):
    """Campo de entrada do terminal."""
    return dict(k=k, rot=rot, pad=pad, funcs=tuple(funcs), grupo=grupo, porque=porque, como=como, onde=onde,
                tipo=tipo, mn=mn, mx=mx, passo=passo, fmt=fmt, unid=unid, opcoes=opcoes, conf=conf)


def K(k, rot, pad, funcs, porque, como, onde, mn=0.0, mx=1e6, passo=0.01, fmt="%.2f", unid=""):
    """Critério de ajuste (etapa 4)."""
    return dict(k=k, rot=rot, pad=pad, funcs=tuple(funcs), porque=porque, como=como, onde=onde,
                mn=mn, mx=mx, passo=passo, fmt=fmt, unid=unid)


def modulos() -> list:
    return [importlib.import_module(f"core.{n}") for n in NOMES_MODULOS]


def codigos() -> list[str]:
    return [c for m in modulos() for c in m.COD]


def modulo_de(cod: str):
    for m in modulos():
        if cod in m.COD:
            return m
    return None


def entradas(sel: list[str] | None = None, conf: bool | None = None) -> list[dict]:
    """Campos de entrada dos módulos, filtrados pelas funções selecionadas (None = todos)."""
    vistos, out = set(), []
    for m in modulos():
        for e in m.ENTRADAS:
            if sel is not None and not (set(e["funcs"]) & set(sel)):
                continue
            if conf is not None and e["conf"] != conf:
                continue
            if e["k"] in vistos:
                continue
            vistos.add(e["k"])
            out.append(e)
    return out


def criterios(sel: list[str] | None = None) -> list[dict]:
    vistos, out = set(), []
    for m in modulos():
        for k in m.CRITERIOS:
            if sel is not None and not (set(k["funcs"]) & set(sel)):
                continue
            if k["k"] in vistos:
                continue
            vistos.add(k["k"])
            out.append(k)
    return out


def dados_padrao() -> dict:
    return {e["k"]: e["pad"] for e in entradas()}


def criterios_padrao() -> dict:
    return {k["k"]: k["pad"] for k in criterios()}


def textos(cod: str) -> dict:
    m = modulo_de(cod)
    return (m.TEXTOS.get(cod) or {}) if m else {}


def referencias(sel: list[str]) -> list[str]:
    out = []
    for m in modulos():
        if set(m.COD) & set(sel):
            out += [r for r in getattr(m, "REFS", []) if r not in out]
    return out


def executar(d, c, casos, sel, incluir_base=False) -> list[dict]:
    """Executa os módulos que têm ao menos uma função selecionada. Devolve a lista de resultados."""
    res = []
    primeiro = True
    for m in modulos():
        if set(m.COD) & set(sel):
            res.append(m.calcular(d, c, casos, sel, incluir_base=incluir_base and primeiro))
            primeiro = False
    return res


def figuras(r: dict) -> list[tuple[str, object]]:
    out = []
    for m in modulos():
        if set(m.COD) & set(r.get("funcoes") or []) and hasattr(m, "figuras"):
            out += m.figuras(r)
    return out
