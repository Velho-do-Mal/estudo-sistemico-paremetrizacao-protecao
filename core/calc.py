"""Motor de cálculo do estudo de proteção sistêmica de LTs (oscilação de potência).

Todas as grandezas de impedância internas estão em ohms SECUNDÁRIOS, salvo indicação
`_pri`. Ângulos em graus. O retorno de `calcular_terminal` é um dicionário serializável
em JSON, que alimenta a interface, o relatório Word e a planilha Excel.

Modelo adotado (premissas declaradas no relatório):
  * Zonas de distância como círculos mho com diâmetro ao longo do ângulo da LT.
  * Fontes e LT com mesmo ângulo de impedância (sistema homogêneo) -> o lugar geométrico
    da oscilação é uma reta perpendicular à linha de impedância total.
  * Blinders (interno/externo) são retas paralelas à impedância da LT, a uma distância
    perpendicular d da linha.
  * Fontes de mesma magnitude de tensão (|E_S| = |E_R|) durante a oscilação.
"""
from __future__ import annotations

import cmath
import math

from core import direcional as DIR
from core import f_sobrecorrente as SC
from core import funcoes as F
from core import modulos as MOD

# --------------------------------------------------------------------------- padrões
CRITERIOS_PADRAO = {
    # alcances das zonas de distância
    "k_z1": 0.80,                  # Z1 = k_z1 * ZL
    "k_z2": 1.20,                  # Z2 = k_z2 * ZL (limitado por z2_frac_adj)
    "z2_frac_adj": 0.50,           # Z2 <= ZL + z2_frac_adj * Zadj_min
    "k_z3": 1.00,                  # Z3 = ZL + k_z3 * Zadj_max
    "z3_sem_adj": 1.50,            # Z3 = z3_sem_adj * ZL se não houver adjacente
    "k_rev": 0.25,                 # alcance reverso (fração de ZL)
    # carga / load encroachment
    "k_load": 0.90,                # ZLF = k_load * Zcarga_min
    "delta_ang_carga": 10.0,       # folga angular (graus) nos ângulos de carga
    "usar_limite_termico": True,   # carga de referência = max(fluxo, limite térmico)
    # blinders
    "zonas_bloqueadas": [1, 2, 3],  # zonas de distância bloqueadas pelo OSB
    "margem_blinder_interno": 0.15,  # blinder interno fica 15% além da maior zona bloqueada
    "frac_blinder_externo_carga": 0.90,  # blinder externo <= 90% da distância da carga
    # temporização do OSB
    "t_falta_ciclos": 2.0,         # tempo máximo de evolução de uma falta (ciclos)
    "k_timer": 0.80,               # OSBD = k_timer * tempo mínimo entre blinders (swing mais rápido)
    "osb_modo": "carta",           # "carta": OSBD pela velocidade de impedância (Carta ONS 4.c); "slip": pelo f_slip
    "v_imp_osb_pri": 1500.0,       # velocidade de impedância de referência da Carta ONS (Ω primários/s)
    "passo_timer_ciclos": 0.25,    # arredondamento do temporizador
    # função 51
    "k_pickup_min": 1.50,          # pickup >= k * I_carga_max
    "k_sens_51": 1.50,             # Icc_min / pickup >= k
}
CRITERIOS_PADRAO.update(SC.CRITERIOS_SOBRECORRENTE)
CRITERIOS_PADRAO.update(DIR.CRITERIOS_DIRECIONAL)
CRITERIOS_PADRAO.update(MOD.criterios_padrao())

DADOS_PADRAO = {
    "fabricante": "SEL", "modelo": "", "modo": "novo",
    "lt_nome": "", "terminal": "", "terminal_remoto": "",
    "comp_km": 0.0, "vn_kv": 230.0,
    "r1": 0.0, "x1": 0.0, "r0": 0.0, "x0": 0.0,          # ohms primários (total da LT)
    "rtc": 1.0, "rtp": 1.0,                               # relações
    "s_max_mva": 0.0, "i_term_a": 0.0, "v_min_pu": 0.90,
    "phi_pos": 30.0, "phi_neg": 30.0,
    "q_max_mvar": 0.0,                                    # opcional: Q máx. (Mvar) para calcular o ângulo de carga indutiva
    "f_hz": 60.0, "f_slip_max": 5.0,
    "icc3f_loc_ka": 0.0, "icc3f_rem_ka": 0.0,
    "zadj_min": 0.0, "zadj_max": 0.0,
    # ajustes existentes (modo conferência) - valores secundários; 0 = não informado
    "ex_z1": 0.0, "ex_z2": 0.0, "ex_z3": 0.0,
    "ex_r_blinder_int": 0.0, "ex_r_blinder_ext": 0.0, "ex_osbd_ciclos": 0.0,
    "ex_zlf": 0.0, "ex_pickup51_a_sec": 0.0,
    # funções selecionadas e parâmetros de sobrecorrente
    "funcoes": list(F.PADRAO),
    "curva51": "IEC NI", "curva51n": "IEC NI", "t_jus_s": 0.0, "t_jus_n_s": 0.0,
    "ex_tms51": 0.0, "ex_pickup50_a_sec": 0.0, "ex_pickup51n_a_sec": 0.0,
    "ex_pickup50n_a_sec": 0.0, "ex_tms51n": 0.0,
    # funções direcionais 67/67N (mta_*_man: 0 = calcular a partir dos fasores)
    "curva67": "IEC NI", "curva67n": "IEC NI", "t_jus_67_s": 0.0, "t_jus_67n_s": 0.0,
    "mta67_man": 0.0, "mta67n_man": 0.0,
    "ex_pickup67_a_sec": 0.0, "ex_pickup67n_a_sec": 0.0, "ex_mta67": 0.0, "ex_mta67n": 0.0,
}
DADOS_PADRAO.update(MOD.dados_padrao())


# --------------------------------------------------------------------------- utilidades
def pol(z: complex) -> tuple[float, float]:
    return abs(z), math.degrees(cmath.phase(z))


def rect(m: float, ang_deg: float) -> complex:
    return cmath.rect(m, math.radians(ang_deg))


def fmt(x, n=2) -> str:
    """Formata número no padrão brasileiro (1.234,56)."""
    try:
        s = f"{float(x):,.{n}f}"
    except (TypeError, ValueError):
        return str(x)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_eq(x, n=2) -> str:
    """Número para equações (sem separador de milhar; vírgula decimal)."""
    try:
        return f"{float(x):.{n}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(x)


def _mescla(padrao: dict, extra: dict | None) -> dict:
    d = dict(padrao)
    if extra:
        for k, v in extra.items():
            if v is not None:
                d[k] = v
    return d


def arredonda_passo(x: float, passo: float) -> float:
    if passo <= 0:
        return x
    return round(x / passo) * passo


def delta_angulo(d: float, zt: float) -> float:
    """Ângulo de defasagem (graus) em que o lugar geométrico da oscilação está a uma
    distância perpendicular d da linha de impedância total de módulo zt."""
    if d <= 0:
        return 180.0
    return math.degrees(2.0 * math.atan(zt / (2.0 * d)))


def tempo_entre_blinders(d_in: float, d_out: float, zt: float, f_slip: float) -> float:
    """Tempo (s) para o lugar geométrico ir do blinder externo ao interno."""
    if f_slip <= 0:
        return float("inf")
    dd = delta_angulo(d_in, zt) - delta_angulo(d_out, zt)
    return math.radians(dd) / (2.0 * math.pi * f_slip)


def velocidade_impedancia(d: float, zt: float, f_slip: float) -> float:
    """|dZ/dt| (ohm/s) do lugar geométrico ao cruzar a reta a distância d."""
    w = 2.0 * math.pi * f_slip
    return (zt / 4.0) * (1.0 + (2.0 * d / zt) ** 2) * w


def mho_contem(ponto: complex, alcance: float, ang_deg: float) -> bool:
    c = rect(alcance / 2.0, ang_deg)
    return abs(ponto - c) <= alcance / 2.0 + 1e-9


# --------------------------------------------------------------------------- cálculo
# Nomes dos ajustes no GE L90 UR (manual 7.2x, cap. 5.6; revisão do firmware dos relés = A DEFINIR, .urs indicam código 770).
GE_L90_NOMES = {
    "Z1P / Z1MG": "PHS DIST Z1 REACH / GND DIST Z1 REACH (Ω sec)",
    "Z2P / Z2MG": "PHS DIST Z2 REACH / GND DIST Z2 REACH (Ω sec)",
    "Z3P / Z3MG": "PHS DIST Z3 REACH / GND DIST Z3 REACH (Ω sec)",
    "ELOAD": "LOAD ENCROACHMENT FUNCTION",
    "ZLF": "LOAD ENCROACHMENT REACH (único, Ω sec, FP unitário)",
    "PLAF": "LOAD ENCROACHMENT ANGLE (único, 5–50°)",
    "EOOS": "POWER SWING FUNCTION",
    "R1R6": "POWER SWING INNER RGT BLD",
    "R1L6": "POWER SWING INNER LFT BLD",
    "R1R7": "POWER SWING OUTER RGT BLD",
    "R1L7": "POWER SWING OUTER LFT BLD",
    "X1T6": "POWER SWING FWD REACH (A VALIDAR: L90 usa alcance ao longo do RCA)",
    "X1B6": "POWER SWING REV REACH (A VALIDAR: L90 usa alcance ao longo do RCA)",
    "X1T7": "POWER SWING QUAD FWD REACH OUT (A VALIDAR)",
    "X1B7": "POWER SWING QUAD REV REACH OUT (A VALIDAR)",
    "OSBD": "POWER SWING PICKUP DELAY 1",
}


def _calc_distancia(d: dict, c: dict, casos: list[dict], sel: list[str]) -> dict:
    """Funções 21 (distância + load encroachment) e 68 (OSB). Calcula tudo o que é comum e depois
    mantém no resultado apenas o que pertence às funções marcadas."""
    alertas: list[str] = []
    alertas21: list[str] = []
    alertas68: list[str] = []
    passos: list[dict] = []
    verif: list[dict] = []

    def passo(secao, titulo, simb, num, nota=""):
        passos.append({"secao": secao, "titulo": titulo, "simb": simb, "num": num, "nota": nota})

    def check(item, criterio, valor, limite, ok, nota=""):
        verif.append({"item": item, "criterio": criterio, "valor": valor,
                      "limite": limite, "status": "OK" if ok else "FALHA", "nota": nota})

    # ---- validação mínima de dados
    rtc, rtp = float(d["rtc"]), float(d["rtp"])
    if rtc <= 0 or rtp <= 0:
        raise ValueError("RTC e RTP devem ser maiores que zero.")
    zl_pri = complex(d["r1"], d["x1"])
    if abs(zl_pri) <= 0:
        raise ValueError("Informe a impedância de sequência positiva da LT (R1, X1).")
    f = float(d["f_hz"])
    vn = float(d["vn_kv"])

    # ---- 1. base: conversão primário -> secundário e ângulo da LT
    k_sec = rtc / rtp
    zl_sec = zl_pri * k_sec
    zl_m, theta = pol(zl_sec)
    z0_pri = complex(d["r0"], d["x0"])
    z0_sec = z0_pri * k_sec
    k0 = (z0_pri - zl_pri) / (3 * zl_pri) if abs(zl_pri) > 0 else 0
    sen_t = math.sin(math.radians(theta))
    base = {
        "k_sec": k_sec, "zl_pri": [zl_pri.real, zl_pri.imag, abs(zl_pri), pol(zl_pri)[1]],
        "zl_sec": [zl_sec.real, zl_sec.imag, zl_m, theta],
        "z0_sec": [z0_sec.real, z0_sec.imag, abs(z0_sec), pol(z0_sec)[1]],
        "k0": [k0.real, k0.imag, abs(k0), pol(k0)[1] if abs(k0) > 0 else 0.0],
        "theta": theta,
    }
    passo("Base", "Relação de conversão primário/secundário",
          r"k_{s} = \frac{RTC}{RTP}",
          rf"k_{{s}} = \frac{{{fmt_eq(rtc,1)}}}{{{fmt_eq(rtp,1)}}} = {fmt_eq(k_sec,4)}")
    passo("Base", "Impedância de sequência positiva da LT (secundário)",
          r"Z_{L,sec} = k_{s} \cdot Z_{L,pri}",
          rf"Z_{{L,sec}} = {fmt_eq(k_sec,4)} \cdot ({fmt_eq(zl_pri.real)} + j{fmt_eq(zl_pri.imag)}) = "
          rf"{fmt_eq(zl_m)} \angle {fmt_eq(theta,1)}^{{\circ}}\ \Omega")

    # ---- 2. zonas de distância (mho)
    zadj_min = float(d["zadj_min"]) * k_sec
    zadj_max = float(d["zadj_max"]) * k_sec
    z1 = c["k_z1"] * zl_m
    z2_base = c["k_z2"] * zl_m
    if zadj_min > 0:
        z2 = min(z2_base, zl_m + c["z2_frac_adj"] * zadj_min)
    else:
        z2 = z2_base
    z3 = zl_m + c["k_z3"] * zadj_max if zadj_max > 0 else c["z3_sem_adj"] * zl_m
    zr_rev = c["k_rev"] * zl_m
    zonas = {
        "Z1": {"alcance": z1, "ang": theta, "pri": z1 / k_sec},
        "Z2": {"alcance": z2, "ang": theta, "pri": z2 / k_sec},
        "Z3": {"alcance": z3, "ang": theta, "pri": z3 / k_sec},
        "Zrev": {"alcance": zr_rev, "ang": theta + 180.0, "pri": zr_rev / k_sec},
    }
    passo("Zonas de distância", "Zona 1", r"Z_{1} = k_{1} \cdot Z_{L}",
          rf"Z_{{1}} = {fmt_eq(c['k_z1'])} \cdot {fmt_eq(zl_m)} = {fmt_eq(z1)}\ \Omega")
    if zadj_min > 0:
        passo("Zonas de distância", "Zona 2",
              r"Z_{2} = \min\left( k_{2} \cdot Z_{L},\ Z_{L} + f_{2} \cdot Z_{adj,min} \right)",
              rf"Z_{{2}} = \min\left( {fmt_eq(c['k_z2'])} \cdot {fmt_eq(zl_m)},\ {fmt_eq(zl_m)} + "
              rf"{fmt_eq(c['z2_frac_adj'])} \cdot {fmt_eq(zadj_min)} \right) = {fmt_eq(z2)}\ \Omega")
    else:
        passo("Zonas de distância", "Zona 2", r"Z_{2} = k_{2} \cdot Z_{L}",
              rf"Z_{{2}} = {fmt_eq(c['k_z2'])} \cdot {fmt_eq(zl_m)} = {fmt_eq(z2)}\ \Omega")
    if zadj_max > 0:
        passo("Zonas de distância", "Zona 3", r"Z_{3} = Z_{L} + k_{3} \cdot Z_{adj,max}",
              rf"Z_{{3}} = {fmt_eq(zl_m)} + {fmt_eq(c['k_z3'])} \cdot {fmt_eq(zadj_max)} = {fmt_eq(z3)}\ \Omega")
    else:
        passo("Zonas de distância", "Zona 3", r"Z_{3} = k_{3}' \cdot Z_{L}",
              rf"Z_{{3}} = {fmt_eq(c['z3_sem_adj'])} \cdot {fmt_eq(zl_m)} = {fmt_eq(z3)}\ \Omega",
              "Sem dados do adjacente: Z3 estimada em função de ZL.")
    if z2 < 1.1 * zl_m:
        alertas21.append("Zona 2 resultou menor que 1,10·ZL (limitada pelo adjacente). Revisar coordenação.")
    check("Zona 1", "Z1 < ZL (sem sobrealcance)", z1, zl_m, z1 < zl_m)
    check("Zona 2", "Z2 > ZL (cobre 100% da LT)", z2, zl_m, z2 > zl_m)

    # ---- 3. carga e load encroachment
    s_max = float(d["s_max_mva"])
    i_term = float(d["i_term_a"])
    vmin = float(d["v_min_pu"])
    i_fluxo = s_max * 1e3 / (math.sqrt(3) * vn) if s_max > 0 else 0.0          # A
    i_ref = max(i_fluxo, i_term) if c["usar_limite_termico"] else (i_fluxo or i_term)
    if i_ref <= 0:
        raise ValueError("Informe o fluxo máximo (MVA) ou o limite térmico (A) da LT.")
    z_carga_pri = vmin * vn * 1e3 / (math.sqrt(3) * i_ref)                    # ohm primário
    z_carga = z_carga_pri * k_sec
    phi_pos, phi_neg = float(d["phi_pos"]), float(d["phi_neg"])
    dang = c["delta_ang_carga"]
    # origem do ângulo de carga: CALCULADO (Q máx. informado) ou ASSUMIDO (padrão BK 30°/30°)
    q_max = float(d.get("q_max_mvar", 0.0) or 0.0)
    phi_origem = "ADOTADO (informado pelo usuário)"
    if q_max > 0 and 0 < q_max < s_max:
        phi_pos = math.degrees(math.atan2(q_max, math.sqrt(s_max ** 2 - q_max ** 2)))
        phi_origem = "CALCULADO: φ_ind = arctan(Q_máx / P_máx) com Q_máx informado"
    elif abs(phi_pos - 30.0) < 1e-9 and abs(phi_neg - 30.0) < 1e-9:
        phi_origem = "ASSUMIDO (padrão BK 30°/30°) — A DEFINIR: Q máx. / ângulo de carga do cliente"
        alertas68.append("Ângulos de carga em 30°/30° = padrão BK (ASSUMIDO): sem Q máx. nem ângulo informado. "
                         "A DEFINIR: Q máx. / ângulo de carga a partir do fluxo de potência do cliente.")
    zlf = c["k_load"] * z_carga
    plaf, nlaf = phi_pos + dang, phi_neg + dang
    if min(plaf, nlaf) < 30.0 or max(plaf, nlaf) > 60.0:
        alertas68.append(f"Ângulo de carga efetivo (φ+Δφ = {fmt(plaf,1)}° / {fmt(nlaf,1)}°) fora da faixa usual de 30° a 60°. Conferir dados.")
    r_carga_min = z_carga * math.cos(math.radians(max(phi_pos, phi_neg)))
    passo("Carga e load encroachment", "Corrente de referência de carga",
          r"I_{ref} = \max\left( \frac{S_{max}}{\sqrt{3} \cdot V_{n}},\ I_{term} \right)",
          rf"I_{{ref}} = \max\left( \frac{{{fmt_eq(s_max,1)}\ \mathrm{{MVA}}}}{{\sqrt{{3}} \cdot {fmt_eq(vn,1)}\ \mathrm{{kV}}}},\ "
          rf"{fmt_eq(i_term,0)}\ \mathrm{{A}} \right) = {fmt_eq(i_ref,1)}\ \mathrm{{A}}")
    passo("Carga e load encroachment", "Menor impedância de carga",
          r"Z_{carga,min} = \frac{V_{min} \cdot V_{n}}{\sqrt{3} \cdot I_{ref}} \cdot k_{s}",
          rf"Z_{{carga,min}} = \frac{{{fmt_eq(vmin)} \cdot {fmt_eq(vn,1)}\ \mathrm{{kV}}}}"
          rf"{{\sqrt{{3}} \cdot {fmt_eq(i_ref,1)}\ \mathrm{{A}}}} \cdot {fmt_eq(k_sec,4)} = {fmt_eq(z_carga)}\ \Omega")
    passo("Carga e load encroachment", "Alcance da região de carga",
          r"Z_{LF} = k_{L} \cdot Z_{carga,min}",
          rf"Z_{{LF}} = {fmt_eq(c['k_load'])} \cdot {fmt_eq(z_carga)} = {fmt_eq(zlf)}\ \Omega")
    passo("Carga e load encroachment", "Ângulos da região de carga",
          r"\varphi_{+} = \varphi_{max,ind} + \Delta\varphi \qquad \varphi_{-} = \varphi_{max,cap} + \Delta\varphi",
          rf"\varphi_{{+}} = {fmt_eq(phi_pos,1)}^{{\circ}} + {fmt_eq(dang,1)}^{{\circ}} = {fmt_eq(plaf,1)}^{{\circ}} \qquad "
          rf"\varphi_{{-}} = {fmt_eq(phi_neg,1)}^{{\circ}} + {fmt_eq(dang,1)}^{{\circ}} = {fmt_eq(nlaf,1)}^{{\circ}}",
          "Origem de φ: " + phi_origem)

    # invasão da carga pelas zonas (mho): raio da zona no ângulo da carga
    inv = []
    for nome in ("Z1", "Z2", "Z3"):
        alc = zonas[nome]["alcance"]
        r_max = 0.0
        for phi in (plaf, -nlaf):
            r = alc * math.cos(math.radians(theta - phi)) if abs(theta - phi) < 90 else 0.0
            r_max = max(r_max, r)
        invade = r_max >= z_carga
        inv.append({"zona": nome, "r_max": r_max, "z_carga": z_carga, "invade": invade,
                    "folga": z_carga / r_max if r_max > 0 else float("inf")})
        check(f"{nome} x carga", "Alcance da zona no ângulo da carga < Zcarga,min",
              r_max, z_carga, not invade,
              "Load encroachment evita a atuação" if invade else "")
    load_enc_necessario = any(i["invade"] for i in inv)
    eload = "Y" if load_enc_necessario else "N"

    # ---- 4. blinders
    zbloq = [zonas[f"Z{n}"]["alcance"] for n in c["zonas_bloqueadas"] if f"Z{n}" in zonas]
    z_max_bloq = max(zbloq) if zbloq else z3
    m_in = c["margem_blinder_interno"]
    d_in = (1 + m_in) * z_max_bloq / 2.0
    passo("Blinder interno", "Distância perpendicular do blinder interno",
          r"d_{int} = (1 + m_{int}) \cdot \frac{Z_{max,bloq}}{2}",
          rf"d_{{int}} = (1 + {fmt_eq(m_in)}) \cdot \frac{{{fmt_eq(z_max_bloq)}}}{{2}} = {fmt_eq(d_in)}\ \Omega")
    # distância perpendicular mínima da carga à linha de impedância
    d_load = min(z_carga * abs(math.sin(math.radians(theta - phi))) for phi in (plaf, -nlaf))   # ângulos com folga Δφ (conforme exibido na memória)
    d_out_max = c["frac_blinder_externo_carga"] * d_load
    passo("Blinder externo", "Distância perpendicular da carga à linha de impedância",
          r"d_{carga} = Z_{carga,min} \cdot \left| \sin(\theta_{L} - \varphi) \right|_{min}",
          rf"d_{{carga}} = {fmt_eq(z_carga)} \cdot {fmt_eq(abs(math.sin(math.radians(theta - plaf))),4)} = {fmt_eq(d_load)}\ \Omega"
          if abs(math.sin(math.radians(theta - plaf))) <= abs(math.sin(math.radians(theta + nlaf)))
          else rf"d_{{carga}} = {fmt_eq(z_carga)} \cdot {fmt_eq(abs(math.sin(math.radians(theta + nlaf))),4)} = {fmt_eq(d_load)}\ \Omega")
    passo("Blinder externo", "Distância perpendicular do blinder externo",
          r"d_{ext} = k_{ext} \cdot d_{carga}",
          rf"d_{{ext}} = {fmt_eq(c['frac_blinder_externo_carga'])} \cdot {fmt_eq(d_load)} = {fmt_eq(d_out_max)}\ \Omega")
    d_out = d_out_max
    folga_blinders = d_out - d_in
    if d_out <= d_in:
        alertas68.append("O blinder externo (limitado pela carga) ficou dentro do blinder interno: "
                       "não há espaço para o OSB. Reduzir alcance da zona 3 ou habilitar load encroachment.")
    check("Blinder externo x carga", "d_ext ≤ k_ext · d_carga", d_out, d_out_max, d_out <= d_out_max + 1e-9)
    check("Blinder interno x zonas", "d_int ≥ (1+m)·Zmax/2", d_in, (1 + m_in) * z_max_bloq / 2.0,
          d_in >= (1 + m_in) * z_max_bloq / 2.0 - 1e-9)
    check("Espaço entre blinders", "d_ext > d_int", d_out, d_in, d_out > d_in)

    r_in = d_in / sen_t
    r_out = d_out / sen_t
    escala = d_out / d_in if d_in > 0 else 1.0
    x_top_in = (1 + m_in) * (z_max_bloq / 2.0) * (1 + sen_t)
    x_bot_in = -(1 + m_in) * max((z_max_bloq / 2.0) * (1 - sen_t), c["k_rev"] * zl_m * sen_t)
    x_top_out, x_bot_out = x_top_in * escala, x_bot_in * escala
    passo("Blinder interno", "Interseção com o eixo R",
          r"R_{int} = \frac{d_{int}}{\sin\theta_{L}}",
          rf"R_{{int}} = \frac{{{fmt_eq(d_in)}}}{{{fmt_eq(sen_t,4)}}} = {fmt_eq(r_in)}\ \Omega")
    passo("Blinder externo", "Interseção com o eixo R",
          r"R_{ext} = \frac{d_{ext}}{\sin\theta_{L}}",
          rf"R_{{ext}} = \frac{{{fmt_eq(d_out)}}}{{{fmt_eq(sen_t,4)}}} = {fmt_eq(r_out)}\ \Omega")

    # ---- 5. oscilação: Zt, tempos e velocidade de impedância (item OSB)
    def z_fonte(icc_ka):
        return vn * 1e3 / (math.sqrt(3) * icc_ka * 1e3) * k_sec if icc_ka > 0 else 0.0
    zs = z_fonte(float(d["icc3f_loc_ka"]))
    zr = z_fonte(float(d["icc3f_rem_ka"]))
    if zs == 0 or zr == 0:
        alertas68.append("Icc 3F das barras local/remota não informada: impedâncias de fonte assumidas "
                       "iguais a 1,0·ZL cada (estimativa). Informe os níveis de curto do estudo de curto-circuito.")
        zs = zs or zl_m
        zr = zr or zl_m
    zt = zs + zl_m + zr
    passo("Oscilação de potência", "Impedância total entre fontes",
          r"Z_{t} = Z_{S} + Z_{L} + Z_{R} \qquad Z_{S,R} = \frac{V_{n}}{\sqrt{3} \cdot I_{cc3\phi}} \cdot k_{s}",
          rf"Z_{{t}} = {fmt_eq(zs)} + {fmt_eq(zl_m)} + {fmt_eq(zr)} = {fmt_eq(zt)}\ \Omega")
    f_slip = float(d["f_slip_max"])
    dlt_in = delta_angulo(d_in, zt)
    dlt_out = delta_angulo(d_out, zt)
    t_min = tempo_entre_blinders(d_in, d_out, zt, f_slip) if d_out > d_in else 0.0
    passo("Oscilação de potência", "Ângulo entre fontes nos blinders",
          r"\delta = 2 \cdot \arctan\left( \frac{Z_{t}}{2 \cdot d} \right)",
          rf"\delta_{{ext}} = {fmt_eq(dlt_out,1)}^{{\circ}} \qquad \delta_{{int}} = {fmt_eq(dlt_in,1)}^{{\circ}}")
    passo("Oscilação de potência", "Tempo de travessia entre blinders (oscilação mais rápida)",
          r"t_{trav} = \frac{\delta_{int} - \delta_{ext}}{360 \cdot f_{slip}}",
          rf"t_{{trav}} = \frac{{{fmt_eq(dlt_in,1)} - {fmt_eq(dlt_out,1)}}}{{360 \cdot {fmt_eq(f_slip,2)}}} = "
          rf"{fmt_eq(t_min*1000,1)}\ \mathrm{{ms}}")
    v_out = velocidade_impedancia(d_out, zt, f_slip)
    v_in = velocidade_impedancia(d_in, zt, f_slip)
    passo("Oscilação de potência", "Velocidade de impedância no cruzamento dos blinders",
          r"\left| \frac{dZ}{dt} \right| = \frac{Z_{t}}{4} \cdot \left[ 1 + \left( \frac{2 \cdot d}{Z_{t}} \right)^{2} \right] \cdot 2\pi f_{slip}",
          rf"v_{{ext}} = {fmt_eq(v_out,1)}\ \Omega/\mathrm{{s}} \qquad v_{{int}} = {fmt_eq(v_in,1)}\ \Omega/\mathrm{{s}}")

    # temporizador do OSB
    t_falta_s = c["t_falta_ciclos"] / f
    # --- critério da Carta ONS (item 4.c): OSBD = (d_ext - d_int) / (velocidade de impedância de referência)
    v_ref_pri = float(c["v_imp_osb_pri"])
    dz_pri = (d_out - d_in) / k_sec if d_out > d_in else 0.0           # distância entre blinders (Ω pri)
    t_carta = dz_pri / v_ref_pri if v_ref_pri > 0 else 0.0
    modo_carta = c["osb_modo"] == "carta" and t_carta > 0
    if modo_carta:
        osbd_calc_s = t_carta
        passo("Temporização do OSB", "Tempo de travessia pela velocidade de impedância da Carta ONS (item 4.c)",
              r"t_{carta} = \frac{(d_{ext} - d_{int}) / k_{s}}{v_{ref}}",
              rf"t_{{carta}} = \frac{{({fmt_eq(d_out)} - {fmt_eq(d_in)}) / {fmt_eq(k_sec,4)}}}{{{fmt_eq(v_ref_pri,0)}\ \Omega/s}} = "
              rf"{fmt_eq(t_carta*1000,1)}\ \mathrm{{ms}} = {fmt_eq(t_carta*f,2)}\ \mathrm{{ciclos}}",
              "A Carta pede OSBD correspondente a 1.500 Ω primários/s: oscilações mais lentas que isso são bloqueadas.")
    else:
        osbd_calc_s = c["k_timer"] * t_min
    osbd_cic = arredonda_passo(osbd_calc_s * f, c["passo_timer_ciclos"])
    osbd_cic = max(osbd_cic, 0.0)
    osbd_s = osbd_cic / f
    passo("Temporização do OSB", "Temporizador de bloqueio",
          r"OSBD = k_{t} \cdot t_{trav}",
          rf"OSBD = {fmt_eq(c['k_timer'])} \cdot {fmt_eq(t_min*1000,1)}\ \mathrm{{ms}} \approx "
          rf"{fmt_eq(osbd_s*1000,1)}\ \mathrm{{ms}} = {fmt_eq(osbd_cic,2)}\ \mathrm{{ciclos}}")
    # piso: o temporizador nunca pode ser menor que o tempo de evolução de uma falta
    piso_aplicado = False
    if osbd_cic < c["t_falta_ciclos"] and not modo_carta:
        osbd_cic = c["t_falta_ciclos"]
        osbd_s = osbd_cic / f
        piso_aplicado = True
        passo("Temporização do OSB", "Piso do temporizador (tempo de evolução da falta)",
              r"OSBD \ge t_{falta}",
              rf"OSBD = {fmt_eq(osbd_cic,2)}\ \mathrm{{ciclos}} = {fmt_eq(osbd_s*1000,1)}\ \mathrm{{ms}}",
              "O OSBD calculado ficou abaixo do tempo de evolução da falta e foi elevado ao piso.")
    ok_timer_inf = osbd_s >= t_falta_s - 1e-9
    ok_timer_sup = osbd_s <= t_min + 1e-9 and t_min > 0
    v_equiv_pri = dz_pri / osbd_s if osbd_s > 0 else 0.0              # velocidade de impedância equivalente ao OSBD (Ω pri/s)
    if modo_carta:
        ok_timer_sup = True       # o limite superior passa a ser informativo: vale a velocidade da Carta
    # maior frequência de escorregamento que ainda é detectada (t_trav >= OSBD)
    dd_deg = dlt_in - dlt_out
    f_slip_det = dd_deg / (360.0 * osbd_s) if osbd_s > 0 and dd_deg > 0 else 0.0
    check("OSBD x falta", "OSBD ≥ tempo máximo de evolução da falta",
          osbd_cic, c["t_falta_ciclos"], ok_timer_inf or modo_carta,
          ("Faltas evoluem em menos que o OSBD e não são bloqueadas" if not modo_carta else
           ("Informativo (critério BK): prevalece a Carta ONS 4.c, OSBD pela velocidade de impedância de 1.500 Ω pri/s"
            if not ok_timer_inf else "")))
    check("OSBD x oscilação", "OSBD ≤ tempo de travessia da oscilação mais rápida",
          osbd_s * 1000, t_min * 1000, ok_timer_sup,
          "Valores em ms" if not modo_carta else
          f"Informativo (f_slip = {fmt(f_slip,1)} Hz): vale o critério da Carta; o OSB detecta oscilações até ≈ {fmt(f_slip_det,2)} Hz")
    if modo_carta:
        check("OSBD x Carta ONS 4.c", "Velocidade de impedância equivalente ≈ 1.500 Ω pri/s (±15%)",
              v_equiv_pri, v_ref_pri, abs(v_equiv_pri - v_ref_pri) <= 0.15 * v_ref_pri,
              "Diferença causada pelo arredondamento do temporizador")
    check("Blinder externo x Carta ONS 4.b", "R_ext < impedância mínima de carga",
          r_out / k_sec, z_carga_pri, r_out < z_carga, "Valores em Ω primários")
    d_out_req = None
    if piso_aplicado and t_min > 0:
        t_req = t_falta_s / c["k_timer"]
        dlt_out_req = dlt_in - math.degrees(2 * math.pi * f_slip * t_req)
        if dlt_out_req > 0:
            d_out_req = zt / (2 * math.tan(math.radians(dlt_out_req / 2)))
    if not ok_timer_sup or piso_aplicado:
        alertas68.append(
            f"Com f_slip máx. = {fmt(f_slip,1)} Hz o tempo entre blinders ({fmt(t_min*1000,1)} ms) é menor que o piso do "
            f"OSBD ({fmt(c['t_falta_ciclos'],1)} ciclos). O OSB adotado só detecta oscilações até "
            f"≈ {fmt(f_slip_det,2)} Hz; oscilações mais rápidas não serão bloqueadas. "
            + (f"Para detectar {fmt(f_slip,1)} Hz seria necessário d_ext ≥ {fmt(d_out_req)} Ω "
               f"(R_ext ≈ {fmt(d_out_req / sen_t)} Ω), exigindo afastar a carga (limite térmico) ou reduzir a zona 3. "
               if d_out_req else "")
            + "Confirmar a oscilação máxima nos estudos de estabilidade.")
    # tabela f_slip x resposta do OSB
    tabela_f = []
    for fs in sorted({0.1, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, round(f_slip, 2)}):
        if fs > f_slip + 1e-9:
            continue
        t = tempo_entre_blinders(d_in, d_out, zt, fs) if d_out > d_in else 0.0
        tabela_f.append({"f_slip": fs, "t_ms": t * 1000, "t_ciclos": t * f,
                         "osb_bloqueia": bool(t >= osbd_s - 1e-12 and t > 0)})

    oos = {
        "z_max_bloq": z_max_bloq, "d_in": d_in, "d_out": d_out, "d_load": d_load, "d_out_max": d_out_max,
        "r_in": r_in, "r_out": r_out,
        "x_top_in": x_top_in, "x_bot_in": x_bot_in, "x_top_out": x_top_out, "x_bot_out": x_bot_out,
        "zs": zs, "zr": zr, "zt": zt, "delta_in": dlt_in, "delta_out": dlt_out,
        "t_min_s": t_min, "v_out": v_out, "v_in": v_in,
        "osbd_s": osbd_s, "osbd_ciclos": osbd_cic, "t_falta_ciclos": c["t_falta_ciclos"],
        "piso_aplicado": piso_aplicado, "f_slip_detectavel": f_slip_det, "f_slip_max": f_slip,
        "d_out_necessario": d_out_req, "folga_blinders": folga_blinders,
    }

    # ---- 7. validação cruzada com os casos de curto-circuito
    validacao = []
    zl_dir = rect(1.0, theta)
    for cs in casos:
        loc = cs.get("local_pct")
        if loc in (None, "", "nan"):
            continue
        try:
            m = float(loc) / 100.0
        except (TypeError, ValueError):
            continue
        rf_pri = float(cs.get("rf_ohm") or 0.0)
        zap = m * zl_sec + rf_pri * k_sec
        am, aang = pol(zap)
        zonas_ok = [n for n in ("Z1", "Z2", "Z3") if mho_contem(zap, zonas[n]["alcance"], theta)]
        zrot = zap * cmath.exp(-1j * math.radians(theta))
        dperp = abs(zrot.imag)
        validacao.append({
            "caso": cs.get("ponto", ""), "tipo": cs.get("tipo", ""), "local_pct": float(loc),
            "icc_ka": cs.get("icc_ka"), "z_mod": am, "z_ang": aang, "r": zap.real, "x": zap.imag,
            "zona": zonas_ok[0] if zonas_ok else "Fora das zonas",
            "d_perp": dperp, "dentro_blinder_int": dperp <= d_in + 1e-9,
            "osb_bloqueia": False,
        })
    n_fora = sum(1 for v in validacao if v["local_pct"] <= 100 and v["zona"] == "Fora das zonas")
    n_z1 = sum(1 for v in validacao if v["local_pct"] <= 100 * c["k_z1"] and v["zona"] != "Z1")
    if validacao:
        check("Curto x zonas", "Faltas internas (≤100% da LT) cobertas por alguma zona",
              len(validacao) - n_fora, len(validacao), n_fora == 0)
        check("Curto x blinders", "Faltas internas dentro do blinder interno (evoluem em <OSBD)",
              sum(v["dentro_blinder_int"] for v in validacao), len(validacao),
              all(v["dentro_blinder_int"] for v in validacao))
        if n_z1:
            alertas21.append(f"{n_z1} falta(s) até {fmt(c['k_z1']*100,0)}% da LT não estão na Zona 1 (conferir Rf informado).")

    # ---- 8. modo conferência: compara ajustes existentes com os critérios
    conferencia = []
    if d["modo"] == "conferencia":
        ex = d
        def linha(item, existente, minimo, maximo, unid, nota=""):
            if not existente:
                conferencia.append({"item": item, "existente": "não informado", "minimo": minimo,
                                    "maximo": maximo, "unid": unid, "status": "SEM DADO", "nota": nota})
                return
            ok = (minimo is None or existente >= minimo - 1e-9) and (maximo is None or existente <= maximo + 1e-9)
            conferencia.append({"item": item, "existente": existente, "minimo": minimo,
                                "maximo": maximo, "unid": unid, "status": "CONFORME" if ok else "NÃO CONFORME",
                                "nota": nota})
        zmax_ex = max([v for v in (ex["ex_z1"], ex["ex_z2"], ex["ex_z3"]) if v] or [z_max_bloq])
        linha("Blinder interno — R (Ω sec)", ex["ex_r_blinder_int"], (1 + m_in) * zmax_ex / 2.0 / sen_t, None, "Ω",
              f"Deve ficar fora da maior zona bloqueada (Zmax={fmt(zmax_ex)} Ω)")
        linha("Blinder externo — R (Ω sec)", ex["ex_r_blinder_ext"], ex["ex_r_blinder_int"] or None, d_out_max / sen_t, "Ω",
              "Maior que o interno e dentro do limite da carga")
        linha("OSBD (ciclos)", ex["ex_osbd_ciclos"], c["t_falta_ciclos"],
              t_min * f if t_min > 0 else None, "ciclos",
              "Entre o tempo de evolução da falta e a travessia da oscilação mais rápida")
        linha("ZLF — load encroachment (Ω sec)", ex["ex_zlf"], None, z_carga, "Ω",
              "Deve ser ≤ menor impedância de carga")

    # ---- 9. tabela de ajustes (insumo do Excel)
    nomes_sel = d["fabricante"].strip().upper().startswith("SEL")
    nomes_ge = d["fabricante"].strip().upper().startswith("GE MULTILIN")
    def n(sel):  # nome do parâmetro no relé (SEL e GE L90 mapeados; outros fabricantes: "—")
        if nomes_sel:
            return sel
        return GE_L90_NOMES.get(sel, "—") if nomes_ge else "—"
    ref_in, ref_out, ref_osb, ref_ex = "Carta ONS 4.a", "Carta ONS 4.b", "Carta ONS 4.c", ""
    aj = []
    def add(funcao, param, nome, vsec, usec, vpri, upri, criterio, item=""):
        aj.append({"funcao": funcao, "parametro": param, "nome_rele": n(nome), "valor_sec": vsec,
                   "unid_sec": usec, "valor_pri": vpri, "unid_pri": upri, "criterio": criterio,
                   "item_carta": item})
    ang = round(theta, 1)
    add("21 — Distância", "Alcance Zona 1 (fase/terra, mho)", "Z1P / Z1MG", z1, "Ω sec", z1 / k_sec, "Ω pri",
        f"{fmt(c['k_z1']*100,0)}% de ZL")
    add("21 — Distância", "Alcance Zona 2 (fase/terra, mho)", "Z2P / Z2MG", z2, "Ω sec", z2 / k_sec, "Ω pri",
        f"min({fmt(c['k_z2']*100,0)}% ZL; ZL+{fmt(c['z2_frac_adj']*100,0)}% Zadj,min)")
    add("21 — Distância", "Alcance Zona 3 (fase/terra, mho)", "Z3P / Z3MG", z3, "Ω sec", z3 / k_sec, "Ω pri",
        "ZL + adjacente mais longo" if zadj_max > 0 else "Estimativa (sem adjacente)")
    add("21 — Distância", "Ângulo da impedância da LT", "—", ang, "graus", ang, "graus", "Arg(ZL)")
    add("Load encroachment", "Habilitação", "ELOAD", eload, "Y/N", eload, "Y/N",
        "Zonas invadem a região de carga" if load_enc_necessario else "Sem invasão, manter como segurança", ref_ex)
    add("Load encroachment", "Impedância de carga direta", "ZLF", zlf, "Ω sec", zlf / k_sec, "Ω pri",
        f"{fmt(c['k_load']*100,0)}% da menor impedância de carga", ref_ex)
    add("Load encroachment", "Impedância de carga reversa", "ZLR", zlf, "Ω sec", zlf / k_sec, "Ω pri",
        "Igual à direta (fluxo bidirecional)", ref_ex)
    add("Load encroachment", "Ângulo positivo direto", "PLAF", plaf, "graus", plaf, "graus",
        "φ indutivo máx. + folga", ref_ex)
    add("Load encroachment", "Ângulo negativo direto", "NLAF", nlaf, "graus", nlaf, "graus",
        "φ capacitivo máx. + folga", ref_ex)
    add("Load encroachment", "Ângulo positivo reverso", "PLAR", plaf, "graus", plaf, "graus", "Espelhado (conferir convenção)", ref_ex)
    add("Load encroachment", "Ângulo negativo reverso", "NLAR", nlaf, "graus", nlaf, "graus", "Espelhado (conferir convenção)", ref_ex)
    add("68 — Bloqueio por oscilação", "Habilitação do OOS", "EOOS", "Y", "Y/N", "Y", "Y/N", "Habilitar bloqueio", ref_osb)
    add("68 — Bloqueio por oscilação", "Blinder interno — resistência direita", "R1R6", r_in, "Ω sec", r_in / k_sec, "Ω pri",
        f"d_int = {fmt(d_in)} Ω; {fmt(m_in*100,0)}% além da maior zona bloqueada", ref_in)
    add("68 — Bloqueio por oscilação", "Blinder interno — resistência esquerda", "R1L6", r_in, "Ω sec", r_in / k_sec, "Ω pri",
        "Simétrico ao direito", ref_in)
    add("68 — Bloqueio por oscilação", "Blinder interno — reatância superior", "X1T6", x_top_in, "Ω sec", x_top_in / k_sec, "Ω pri",
        "Envolve topo das zonas bloqueadas + margem", ref_in)
    add("68 — Bloqueio por oscilação", "Blinder interno — reatância inferior", "X1B6", x_bot_in, "Ω sec", x_bot_in / k_sec, "Ω pri",
        "Envolve base/alcance reverso + margem", ref_in)
    add("68 — Bloqueio por oscilação", "Blinder externo — resistência direita", "R1R7", r_out, "Ω sec", r_out / k_sec, "Ω pri",
        f"d_ext = {fmt(d_out)} Ω; {fmt(c['frac_blinder_externo_carga']*100,0)}% da distância da carga", ref_out)
    add("68 — Bloqueio por oscilação", "Blinder externo — resistência esquerda", "R1L7", r_out, "Ω sec", r_out / k_sec, "Ω pri",
        "Simétrico ao direito", ref_out)
    add("68 — Bloqueio por oscilação", "Blinder externo — reatância superior", "X1T7", x_top_out, "Ω sec", x_top_out / k_sec, "Ω pri",
        "Escalonado pela razão d_ext/d_int", ref_out)
    add("68 — Bloqueio por oscilação", "Blinder externo — reatância inferior", "X1B7", x_bot_out, "Ω sec", x_bot_out / k_sec, "Ω pri",
        "Escalonado pela razão d_ext/d_int", ref_out)
    add("68 — Bloqueio por oscilação", "Temporizador de bloqueio (OSB)", "OSBD", osbd_cic, "ciclos", osbd_s * 1000, "ms",
        (f"Tempo para percorrer d_ext−d_int a {fmt(v_ref_pri,0)} Ω pri/s (Carta 4.c)" if modo_carta
         else f"{fmt(c['k_timer']*100,0)}% do tempo de travessia com f_slip = {fmt(f_slip,1)} Hz"), ref_osb)
    add("68 — Bloqueio por oscilação", "Velocidade de impedância (cruzamento do blinder externo)", "—", v_out, "Ω/s sec",
        v_out / k_sec, "Ω/s pri", f"Informativo (f_slip máximo); OSBD equivale a {fmt(v_equiv_pri,0)} Ω pri/s", ref_osb)
    # ---- filtra o que não foi selecionado
    usa21, usa68 = "21" in sel, "68" in sel
    falha_osb = (not ok_timer_inf) or (not ok_timer_sup) or (d_out <= d_in)
    saida_aj = []
    for a in aj:
        eh68 = a["funcao"].startswith("68")
        if eh68 and not usa68:
            continue
        if not eh68 and not usa21:
            continue
        a["status"] = "REVISAR" if (eh68 and falha_osb) else "OK"
        saida_aj.append(a)
    SEC_68 = {"Blinder interno", "Blinder externo", "Oscilação de potência", "Temporização do OSB"}
    CHK_68 = {"Blinder externo x carga", "Blinder interno x zonas", "Espaço entre blinders", "OSBD x falta",
              "OSBD x oscilação", "Curto x blinders", "OSBD x Carta ONS 4.c", "Blinder externo x Carta ONS 4.b"}
    CHK_21 = {"Zona 1", "Zona 2", "Curto x zonas"}
    if not usa68:
        passos = [p for p in passos if p["secao"] not in SEC_68]
        verif = [v for v in verif if v["item"] not in CHK_68]
        conferencia = [x for x in conferencia if not x["item"].startswith(("Blinder", "OSBD"))]
    if not usa21:
        verif = [v for v in verif if v["item"] not in CHK_21 and not v["item"].endswith(" x carga")
                 or v["item"] == "Blinder externo x carga"]
        conferencia = [x for x in conferencia if not x["item"].startswith("ZLF")]
    alertas = (alertas21 if usa21 else []) + (alertas68 if usa68 else []) + alertas

    return {
        "entrada": {k: d[k] for k in d}, "criterios": c, "base": base, "zonas": zonas,
        "carga": {"i_ref": i_ref, "z_carga": z_carga, "z_carga_pri": z_carga_pri, "zlf": zlf,
                  "plaf": plaf, "nlaf": nlaf, "r_carga_min": r_carga_min, "invasao": inv,
                  "load_enc_necessario": load_enc_necessario},
        "oos": oos, "tabela_fslip": tabela_f if usa68 else [], "validacao": validacao,
        "conferencia": conferencia, "verificacoes": verif, "alertas": alertas,
        "passos": passos, "ajustes": saida_aj,
    }


def _resultado_sem_distancia(d: dict, c: dict) -> dict:
    """Resultado-base quando nem 21 nem 68 foram marcadas (só funções de sobrecorrente)."""
    k_sec = float(d["rtc"]) / float(d["rtp"])
    return {"entrada": {k: d[k] for k in d}, "criterios": c, "base": {"k_sec": k_sec}, "zonas": None,
            "carga": None, "oos": None, "tabela_fslip": [], "validacao": [], "conferencia": [],
            "verificacoes": [], "alertas": [], "passos": [], "ajustes": []}


# --------------------------------------------------------------------------- orquestrador
def calcular_terminal(dados_in: dict, crit_in: dict | None = None,
                      casos: list[dict] | None = None) -> dict:
    """Calcula as funções marcadas em `dados["funcoes"]` (padrão: 21, 68 e 51)."""
    d = _mescla(DADOS_PADRAO, dados_in)
    c = _mescla(CRITERIOS_PADRAO, crit_in)
    casos = casos or []
    casos_frente = [x for x in casos if DIR._sentido(x) != "re"]   # faltas à ré só interessam às funções direcionais
    sel = F.selecionadas(d)
    if not sel:
        raise ValueError("Marque ao menos uma função de proteção para ajustar.")
    rtc, rtp = float(d["rtc"]), float(d["rtp"])
    if rtc <= 0 or rtp <= 0:
        raise ValueError("RTC e RTP devem ser maiores que zero.")
    usa_dist = F.usa_distancia(sel)
    r = _calc_distancia(d, c, casos_frente, sel) if usa_dist else _resultado_sem_distancia(d, c)
    r["funcoes"] = sel
    usa_sc = F.usa_sobrecorrente(sel)
    if usa_sc:
        sc = SC.calcular(d, c, casos_frente, sel, incluir_base=not usa_dist)
        r["passos"] += sc["passos"]
        r["verificacoes"] += sc["verif"]
        r["alertas"] += sc["alertas"]
        r["ajustes"] += sc["ajustes"]
        r["conferencia"] += sc["conferencia"]
        r["sobrecorrente"] = sc["dados"]
        if "p51" in sc["dados"]:
            r["pickup51"] = sc["dados"]["p51"]           # compatibilidade com versões anteriores
    if F.usa_direcional(sel):
        dr = DIR.calcular(d, c, casos, sel, incluir_base=not usa_dist and not usa_sc)
        r["passos"] += dr["passos"]
        r["verificacoes"] += dr["verif"]
        r["alertas"] += dr["alertas"]
        r["ajustes"] += dr["ajustes"]
        r["conferencia"] += dr["conferencia"]
        r["direcional"] = dr["dados"]
    # módulos declarativos (27, 59, 81 e os próximos lotes)
    usa_antes = usa_dist or usa_sc or F.usa_direcional(sel)
    r["cards_extra"], r["tabelas_extra"], r["modulos"] = [], [], {}
    for m, mr in zip([m for m in MOD.modulos() if set(m.COD) & set(sel)],
                     MOD.executar(d, c, casos_frente, sel, incluir_base=not usa_antes)):
        r["passos"] += mr["passos"]
        r["verificacoes"] += mr["verif"]
        r["alertas"] += mr["alertas"]
        r["ajustes"] += mr["ajustes"]
        r["conferencia"] += mr["conferencia"]
        r["cards_extra"] += mr["cards"]
        r["tabelas_extra"] += mr["tabelas"]
        r["modulos"][m.__name__.split(".")[-1]] = mr["dados"]
    return r
