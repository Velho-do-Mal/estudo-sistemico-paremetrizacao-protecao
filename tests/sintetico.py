"""Gera fasores fisicamente coerentes (falta fase-terra A) para relé com fonte atrás e linha à frente."""
import cmath, math, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from core import fasores as FS

E = 230 / math.sqrt(3)                      # kV fase-neutro
def z(m, a): return cmath.rect(m, math.radians(a))
ZS1, ZS0 = z(6, 78), z(9, 80)               # fonte atrás do relé (Ω pri)
ZL1, ZL0 = z(50.8, 79.8), z(153, 78.7)      # LT 100 km: ~9+j50 / 30+j150

def ft_frente(m):                           # m = posição da falta (0..1)
    z1t, z0t = ZS1 + m * ZL1, ZS0 + m * ZL0
    i = E / (2 * z1t + z0t)                 # kA (E em kV, Z em Ω)
    v1, v2, v0 = E - i * ZS1, -i * ZS1, -i * ZS0
    ia, ib, ic = FS.seq_para_fases(i, i, i)
    ia, ib, ic = i * 3, 0j, 0j              # SLG fase A: Ib = Ic = 0
    va, vb, vc = FS.seq_para_fases(v0, v1, v2)
    return {n: list(FS.pol(x)) for n, x in zip(FS.NOMES_FASE, (ia, ib, ic, va, vb, vc))}

def ft_re(ir=1.0):                          # falta atrás do relé: corrente entra na barra vinda da LT
    zah1, zah0 = ZL1 + z(8, 77), ZL0 + z(12, 79)
    i_out = -ir                             # sentido de proteção: negativo (da LT para a barra)
    v0 = i_out * zah0
    v1 = E * 0.85 + i_out * zah1 * 0.0
    v2 = i_out * zah1
    ia, ib, ic = i_out * 3, 0j, 0j
    va, vb, vc = FS.seq_para_fases(v0, v1, v2)
    return {n: list(FS.pol(x)) for n, x in zip(FS.NOMES_FASE, (ia, ib, ic, va, vb, vc))}

def caso(ponto, tipo, loc, sentido, f):
    icc = max(f["Ia"][0], f["Ib"][0], f["Ic"][0])
    return {"ponto": ponto, "tipo": tipo, "local_pct": loc, "icc_ka": icc, "sentido": sentido, "fasores": f}

CASOS_DIR = [caso("F0", "FT", 0, "frente", ft_frente(0.0)), caso("F50", "FT", 50, "frente", ft_frente(0.5)),
             caso("F100", "FT", 100, "frente", ft_frente(1.0)), caso("R1", "FT", -1, "re", ft_re(1.2))]
