"""Fasores (módulo e ângulo) e componentes simétricas — base das funções direcionais (67/67N).

Convenções do app (válidas para toda a entrada de dados):
  * ângulos em graus, normalizados em (-180, 180];
  * correntes em kA e tensões em kV fase-neutro;
  * sequência de fases A-B-C (a = 1∠120°);
  * a corrente é positiva quando SAI da barra do relé em direção à linha protegida
    ("sentido de proteção"). Se o programa de curto exportar o sentido oposto, marque a inversão na importação.
Fasores de um caso: {"Ia": [mod, ang], "Ib": ..., "Ic": ..., "Va": ..., "Vb": ..., "Vc": ...}.
"""
from __future__ import annotations

import cmath
import math

A_OP = cmath.rect(1.0, math.radians(120.0))
A2_OP = A_OP * A_OP
NOMES_FASE = ("Ia", "Ib", "Ic", "Va", "Vb", "Vc")
NOMES_SEQ = ("I1", "I2", "I0", "V1", "V2", "V0")


def cpx(mod: float, ang_deg: float) -> complex:
    return cmath.rect(float(mod), math.radians(float(ang_deg)))


def pol(z: complex) -> tuple[float, float]:
    return abs(z), norm180(math.degrees(cmath.phase(z)))


def norm180(a: float) -> float:
    """Normaliza o ângulo para (-180, 180]."""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def ang_dif(a: float, b: float) -> float:
    """a - b normalizado em (-180, 180]."""
    return norm180(a - b)


def media_circular(angs: list[float]) -> float | None:
    """Média de ângulos (graus) pela soma dos vetores unitários."""
    if not angs:
        return None
    x = sum(math.cos(math.radians(a)) for a in angs)
    y = sum(math.sin(math.radians(a)) for a in angs)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None
    return math.degrees(math.atan2(y, x))


def seq_para_fases(z0: complex, z1: complex, z2: complex) -> tuple[complex, complex, complex]:
    """(Z0, Z1, Z2) por fase -> (A, B, C)."""
    return z0 + z1 + z2, z0 + A2_OP * z1 + A_OP * z2, z0 + A_OP * z1 + A2_OP * z2


def fases_para_seq(za: complex, zb: complex, zc: complex) -> tuple[complex, complex, complex]:
    """(A, B, C) -> (Z0, Z1, Z2) por fase (Z0 = (A+B+C)/3)."""
    return (za + zb + zc) / 3.0, (za + A_OP * zb + A2_OP * zc) / 3.0, (za + A2_OP * zb + A_OP * zc) / 3.0


def fasores_do_caso(caso: dict) -> dict[str, complex] | None:
    """Fasores complexos (Ia..Vc) de um caso, ou None se o caso não os possui por completo."""
    f = caso.get("fasores") or {}
    try:
        return {n: cpx(*f[n]) for n in NOMES_FASE}
    except (KeyError, TypeError, ValueError):
        return None


def tensao_quadratura(v: dict[str, complex], fase: str) -> complex:
    """Tensão de polarização em quadratura (conexão 90°): Vbc para A, Vca para B, Vab para C."""
    if fase == "A":
        return v["Vb"] - v["Vc"]
    if fase == "B":
        return v["Vc"] - v["Va"]
    return v["Va"] - v["Vb"]


def sequencia_para_caso(mods_angs: dict[str, tuple[float, float]], tres_x: bool = False) -> dict[str, list[float]]:
    """Converte {'I1','I2','I0','V1','V2','V0'} -> fasores de fase. `tres_x`: I0/V0 informados como 3·I0 / 3·V0."""
    z = {k: cpx(*mods_angs[k]) for k in NOMES_SEQ}
    if tres_x:
        z["I0"], z["V0"] = z["I0"] / 3.0, z["V0"] / 3.0
    ia, ib, ic = seq_para_fases(z["I0"], z["I1"], z["I2"])
    va, vb, vc = seq_para_fases(z["V0"], z["V1"], z["V2"])
    return {n: list(pol(x)) for n, x in zip(NOMES_FASE, (ia, ib, ic, va, vb, vc))}


def inverter_sentido(fasores: dict[str, list[float]]) -> dict[str, list[float]]:
    """Inverte o sentido das correntes (soma 180° ao ângulo de Ia, Ib e Ic)."""
    out = {k: list(v) for k, v in fasores.items()}
    for n in ("Ia", "Ib", "Ic"):
        out[n][1] = norm180(out[n][1] + 180.0)
    return out
