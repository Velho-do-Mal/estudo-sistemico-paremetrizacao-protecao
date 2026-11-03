"""Catálogo de funções de proteção (numeração ANSI/IEEE C37.2) e seleção por relé.

Cada terminal/relé guarda em `dados["funcoes"]` a lista de códigos que o engenheiro quer ajustar.
Só as funções com `pronta=True` têm módulo de cálculo; as demais aparecem como "em desenvolvimento"
e não podem ser marcadas.
"""
from __future__ import annotations

# grupo -> usado para organizar a interface
CATALOGO = [
    # ---- implementadas
    {"cod": "21",  "nome": "Distância (mho) + load encroachment", "grupo": "Linha", "pronta": True,
     "entradas": "Impedâncias da LT, carga, Zadj"},
    {"cod": "68",  "nome": "Bloqueio por oscilação de potência (OSB / blinders)", "grupo": "Linha", "pronta": True,
     "entradas": "Impedâncias da LT, carga, Icc 3F das barras, f_slip máx."},
    {"cod": "50",  "nome": "Sobrecorrente instantânea de fase", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, curtos (falta a 100% da LT)"},
    {"cod": "51",  "nome": "Sobrecorrente temporizada de fase", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, curtos de fase, tempo do dispositivo a jusante"},
    {"cod": "67",  "nome": "Sobrecorrente direcional de fase (polarização em quadratura)", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, fasores de falta (I e V no terminal) à frente e à ré, tempo a jusante"},
    {"cod": "67N", "nome": "Sobrecorrente direcional de neutro (polarização por 3V0)", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, fasores de falta fase-terra (I e V no terminal) à frente e à ré, tempo a jusante"},
    {"cod": "50N", "nome": "Sobrecorrente instantânea de neutro/residual", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, curtos fase-terra (falta a 100% da LT)"},
    {"cod": "51N", "nome": "Sobrecorrente temporizada de neutro/residual", "grupo": "Sobrecorrente", "pronta": True,
     "entradas": "Carga, curtos fase-terra, tempo do dispositivo a jusante"},
    # ---- roteiro (ainda sem módulo de cálculo)
    {"cod": "50BF", "nome": "Falha de disjuntor", "grupo": "Disjuntor", "pronta": True, "entradas": "Corrente nominal do TC, tempos do disjuntor, tempo crítico"},
    {"cod": "79",  "nome": "Religamento automático", "grupo": "Disjuntor", "pronta": True, "entradas": "Modo, tempos do disjuntor e da LT"},
    {"cod": "25",  "nome": "Verificação de sincronismo", "grupo": "Disjuntor", "pronta": True, "entradas": "Tempo de fechamento, critérios de sincronismo"},
    {"cod": "27",  "nome": "Subtensão", "grupo": "Tensão e frequência", "pronta": True, "entradas": "Faixa operativa e critérios da etapa 4"},
    {"cod": "59",  "nome": "Sobretensão", "grupo": "Tensão e frequência", "pronta": True, "entradas": "Faixa operativa e critérios da etapa 4"},
    {"cod": "81",  "nome": "Sub/sobrefrequência", "grupo": "Tensão e frequência", "pronta": True, "entradas": "Faixa operativa e critérios da etapa 4"},
    {"cod": "87L", "nome": "Diferencial de linha", "grupo": "Diferencial", "pronta": True, "entradas": "Capacitância da LT, Icc mínima, TC"},
    {"cod": "87T", "nome": "Diferencial de transformador", "grupo": "Diferencial", "pronta": True, "entradas": "Dados de placa do transformador, RTCs, comutador"},
    {"cod": "87B", "nome": "Diferencial de barra", "grupo": "Diferencial", "pronta": True, "entradas": "Tipo, TCs, faltas externa e interna"},
    {"cod": "87G", "nome": "Diferencial de gerador", "grupo": "Gerador", "pronta": True, "entradas": "Erro de TC e faltas externa/interna"},
    {"cod": "46",  "nome": "Sobrecorrente de sequência negativa", "grupo": "Gerador", "pronta": True, "entradas": "I2 contínuo e K do gerador"},
    {"cod": "49",  "nome": "Sobrecarga térmica", "grupo": "Gerador", "pronta": True, "entradas": "Fator de serviço e constante térmica"},
    {"cod": "32",  "nome": "Potência reversa", "grupo": "Gerador", "pronta": True, "entradas": "Acionador e potência de motorização"},
    {"cod": "40",  "nome": "Perda de excitação", "grupo": "Gerador", "pronta": True, "entradas": "Xd e X'd da máquina"},
]

PADRAO = ["21", "68", "51"]                  # terminais antigos (sem campo "funcoes") mantêm o comportamento anterior
_POR_COD = {f["cod"]: f for f in CATALOGO}


def prontas() -> list[dict]:
    return [f for f in CATALOGO if f["pronta"]]


def em_desenvolvimento() -> list[dict]:
    return [f for f in CATALOGO if not f["pronta"]]


def rotulo(cod: str) -> str:
    f = _POR_COD.get(cod)
    return f"{cod} — {f['nome']}" if f else cod


def selecionadas(dados: dict) -> list[str]:
    """Lista de funções marcadas para o terminal (somente as que têm módulo), na ordem do catálogo."""
    marcadas = dados.get("funcoes")
    if marcadas is None:
        marcadas = PADRAO
    validas = {f["cod"] for f in CATALOGO if f["pronta"]}
    return [f["cod"] for f in CATALOGO if f["cod"] in marcadas and f["cod"] in validas]


def usa_distancia(sel: list[str]) -> bool:
    return "21" in sel or "68" in sel


def usa_sobrecorrente(sel: list[str]) -> bool:
    return any(c in sel for c in ("50", "51", "50N", "51N"))


def usa_direcional(sel: list[str]) -> bool:
    return any(c in sel for c in ("67", "67N"))
