"""Utilitários comuns aos módulos de função (contexto de acumulação de resultados)."""
from __future__ import annotations

import math


def sobe(x: float, passo: float) -> float:
    """Arredonda para cima ao passo do relé."""
    return round(math.ceil(x / passo - 1e-9) * passo, 9) if passo > 0 else x


def desce(x: float, passo: float) -> float:
    """Arredonda para baixo ao passo do relé."""
    return round(math.floor(x / passo + 1e-9) * passo, 9) if passo > 0 else x


def cfg(c: dict, specs: list[dict]) -> dict:
    """Critérios do módulo: padrão da especificação sobrescrito pelos valores do projeto."""
    return {k["k"]: (c[k["k"]] if k["k"] in c and c[k["k"]] is not None else k["pad"]) for k in specs}


def num(d: dict, k: str, padrao: float = 0.0) -> float:
    try:
        v = d.get(k)
        return float(v) if v is not None else padrao
    except (TypeError, ValueError):
        return padrao


class Ctx:
    """Acumula passos, verificações, alertas, ajustes, conferência, cartões e tabelas de um módulo."""

    def __init__(self, d: dict):
        self.d = d
        self.passos, self.verif, self.alertas, self.aj, self.conf = [], [], [], [], []
        self.cards, self.tabelas = [], []
        self.sel_ref = str(d.get("fabricante", "")).strip().upper().startswith("SEL")
        from core.calc import fmt, fmt_eq                      # import tardio: evita ciclo
        self.fmt, self.fq = fmt, fmt_eq

    def nome(self, n):
        return n if self.sel_ref else "—"

    def passo(self, secao, titulo, simb, numerico, nota=""):
        self.passos.append({"secao": secao, "titulo": titulo, "simb": simb, "num": numerico, "nota": nota})

    def check(self, item, criterio, valor, limite, ok, nota=""):
        self.verif.append({"item": item, "criterio": criterio, "valor": valor, "limite": limite,
                           "status": "OK" if ok else "FALHA", "nota": nota})

    def add(self, funcao, param, nome, vsec, usec, vpri, upri, criterio, status="OK", item=""):
        self.aj.append({"funcao": funcao, "parametro": param, "nome_rele": self.nome(nome), "valor_sec": vsec,
                        "unid_sec": usec, "valor_pri": vpri, "unid_pri": upri, "criterio": criterio,
                        "item_carta": item, "status": status})

    def conferir(self, item, existente, minimo, maximo, unid, nota=""):
        """Linha de conferência: faixa [minimo, maximo] (None = sem limite). existente 0/None = não informado."""
        if not existente:
            self.conf.append({"item": item, "existente": "não informado", "minimo": minimo, "maximo": maximo,
                              "unid": unid, "status": "SEM DADO", "nota": nota})
            return
        ok = (minimo is None or existente >= minimo - 1e-9) and (maximo is None or existente <= maximo + 1e-9)
        self.conf.append({"item": item, "existente": existente, "minimo": minimo, "maximo": maximo, "unid": unid,
                          "status": "CONFORME" if ok else "NÃO CONFORME", "nota": nota})

    def card(self, titulo, valor, sub=""):
        self.cards.append({"titulo": titulo, "valor": valor, "sub": sub})

    def tabela(self, titulo, cab, linhas):
        self.tabelas.append({"titulo": titulo, "cab": cab, "linhas": linhas})

    def pacote(self, dados: dict) -> dict:
        return {"passos": self.passos, "verif": self.verif, "alertas": self.alertas, "ajustes": self.aj,
                "conferencia": self.conf, "dados": dados, "cards": self.cards, "tabelas": self.tabelas}
