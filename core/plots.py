"""Gráficos do estudo (matplotlib) na paleta azul/cinza/branco do app."""
from __future__ import annotations

import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon

AZUL_ESCURO = "#1F3864"
AZUL = "#1F4E9C"
AZUL_CLARO = "#8FAADC"
AZUL_PALIDO = "#DCE6F5"
CINZA = "#7F7F7F"
CINZA_CLARO = "#D9D9D9"
GRAFITE = "#2B2F36"


def _rot(z: complex, theta_deg: float) -> complex:
    import cmath
    return z * cmath.exp(1j * math.radians(theta_deg))


def grafico_rx(res: dict, titulo: str = "", figsize=(7.6, 6.4), dpi=170, mostrar_blinders: bool | None = None):
    """Diagrama R-X: zonas mho, região de carga, blinders interno/externo, LT e casos de falta."""
    z = res["zonas"]
    o = res["oos"]
    cg = res["carga"]
    if mostrar_blinders is None:
        mostrar_blinders = "68" in (res.get("funcoes") or ["21", "68"])
    th = res["base"]["theta"]
    zl = res["base"]["zl_sec"]
    sen = math.sin(math.radians(th))
    cos = math.cos(math.radians(th))

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.set_facecolor("white")
    ax.axhline(0, color=CINZA_CLARO, lw=0.8, zorder=0)
    ax.axvline(0, color=CINZA_CLARO, lw=0.8, zorder=0)

    # região de carga (setor com |Z| >= ZLF entre -NLAF e +PLAF), direita e esquerda
    zlf, plaf, nlaf = cg["zlf"], cg["plaf"], cg["nlaf"]
    rmax = max(o["zt"], zlf * 1.6, z["Z3"]["alcance"] * 1.4)
    for lado in (1, -1):
        pts = [(0, 0)]
        n = 40
        for k in range(n + 1):
            ang = -nlaf + (plaf + nlaf) * k / n
            a = math.radians(ang)
            r0 = zlf
            pts.append((lado * r0 * math.cos(a), r0 * math.sin(a)))
        for k in range(n, -1, -1):
            ang = -nlaf + (plaf + nlaf) * k / n
            a = math.radians(ang)
            pts.append((lado * rmax * math.cos(a), rmax * math.sin(a)))
        pts = pts[1:]
        ax.add_patch(Polygon(pts, closed=True, facecolor=CINZA_CLARO, edgecolor=CINZA, lw=0.8,
                             alpha=0.55, zorder=1, label="Região de carga" if lado == 1 else None))

    # blinders: retas paralelas à LT a distância d (interno e externo, ambos os lados)
    ux, uy = cos, sen                 # direção da LT
    px, py = -sen, cos                # perpendicular
    L = rmax * 1.1
    blinders = ((o["d_in"], "-", AZUL, "Blinder interno"),
                (o["d_out"], "--", AZUL_ESCURO, "Blinder externo")) if mostrar_blinders else ()
    for d, estilo, cor, rot in blinders:
        for s in (1, -1):
            x0, y0 = s * d * px, s * d * py
            ax.plot([x0 - L * ux, x0 + L * ux], [y0 - L * uy, y0 + L * uy], estilo, color=cor, lw=1.4,
                    zorder=3, label=rot if s == 1 else None)

    # zonas mho
    cores = {"Z1": AZUL_ESCURO, "Z2": AZUL, "Z3": AZUL_CLARO}
    for nome in ("Z3", "Z2", "Z1"):
        alc = z[nome]["alcance"]
        cx, cy = (alc / 2) * cos, (alc / 2) * sen
        ax.add_patch(Circle((cx, cy), alc / 2, fill=True, facecolor=cores[nome], alpha=0.10,
                            edgecolor=cores[nome], lw=1.6, zorder=2, label=f"Zona {nome[1]} ({alc:.2f} Ω)"))
    # reverso
    ar = z["Zrev"]["alcance"]
    ax.add_patch(Circle((-(ar / 2) * cos, -(ar / 2) * sen), ar / 2, fill=False, edgecolor=CINZA, lw=1.2,
                        ls=":", zorder=2, label="Zona reversa"))

    # LT
    ax.annotate("", xy=(zl[0], zl[1]), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=GRAFITE, lw=1.6), zorder=5)
    ax.text(zl[0] * 0.5 + 0.6, zl[1] * 0.5 - 0.6, f"ZL = {zl[2]:.2f} ∠ {th:.1f}°".replace(".", ","), color=GRAFITE,
            fontsize=8, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.2), zorder=7)

    # lugar geométrico da oscilação (reta perpendicular que passa pelo centro elétrico)
    zt = o["zt"]
    cen = (zt / 2 - o["zs"])
    cx0, cy0 = cen * ux, cen * uy
    if mostrar_blinders:
        ax.plot([cx0 - L * px, cx0 + L * px], [cy0 - L * py, cy0 + L * py], "-.", color=CINZA, lw=1.0, zorder=3,
                label="Lugar geométrico da oscilação")

    # casos de falta
    val = res.get("validacao") or []
    if val:
        ax.scatter([v["r"] for v in val], [v["x"] for v in val], s=22, marker="o", color=GRAFITE,
                   zorder=6, label="Faltas (Z aparente)")

    # ponto de carga mínima
    zc = cg["z_carga"]
    ax.scatter([zc * math.cos(math.radians(30))], [zc * math.sin(math.radians(30))], marker="s", s=26,
               color=CINZA, zorder=6)

    lim = max(rmax * 0.9, z["Z3"]["alcance"] * 1.25, o["d_out"] * 1.6)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim * 0.55, lim * 1.05)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("R (Ω secundários)", color=GRAFITE)
    ax.set_ylabel("X (Ω secundários)", color=GRAFITE)
    ax.grid(True, color="#EEF1F6", lw=0.7)
    for sp in ax.spines.values():
        sp.set_color(CINZA_CLARO)
    ax.tick_params(colors=GRAFITE, labelsize=8)
    if titulo:
        ax.set_title(titulo, color=AZUL_ESCURO, fontsize=11, fontweight="bold", loc="left")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=7.5, frameon=False)
    fig.tight_layout()
    return fig


def grafico_tempo_slip(res: dict, figsize=(6.4, 3.4), dpi=170):
    """Tempo de travessia entre blinders x frequência de escorregamento, com o OSBD."""
    o = res["oos"]
    from core.calc import tempo_entre_blinders
    fmax = max(o["f_slip_max"], 1.0)
    xs = [0.1 + i * (fmax - 0.1) / 80 for i in range(81)]
    f = res["entrada"]["f_hz"]
    ys = [tempo_entre_blinders(o["d_in"], o["d_out"], o["zt"], x) * 1000 if o["d_out"] > o["d_in"] else 0 for x in xs]
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.plot(xs, ys, color=AZUL, lw=2, label="Tempo entre blinders")
    ax.axhline(o["osbd_s"] * 1000, color=AZUL_ESCURO, ls="--", lw=1.3, label=f"OSBD = {o['osbd_ciclos']:.2f} ciclos")
    ax.axhline(o["t_falta_ciclos"] / f * 1000, color=CINZA, ls=":", lw=1.2, label="Evolução da falta")
    ax.set_xlabel("Frequência de escorregamento (Hz)", color=GRAFITE)
    ax.set_ylabel("Tempo (ms)", color=GRAFITE)
    ax.set_yscale("log")
    ax.grid(True, which="both", color="#EEF1F6", lw=0.7)
    for sp in ax.spines.values():
        sp.set_color(CINZA_CLARO)
    ax.tick_params(colors=GRAFITE, labelsize=8)
    ax.legend(fontsize=7.5, frameon=True, edgecolor=CINZA_CLARO)
    fig.tight_layout()
    return fig


def grafico_curvas_sobrecorrente(res: dict, figsize=(6.8, 3.9), dpi=170):
    """Curvas tempo x corrente (IEC) das funções 51/51N com pickup e ponto de coordenação."""
    from core.f_sobrecorrente import CURVAS, tempo_iec
    sc = res.get("sobrecorrente") or {}
    itens = [(k, sc[k]) for k in ("p51", "p51n") if k in sc and sc[k].get("tms") is not None]
    if not itens:
        return None
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    cores = {"p51": AZUL, "p51n": CINZA}
    for k, p in itens:
        nome = "51 (fase)" if k == "p51" else "51N (neutro)"
        pk = p["rec_pri"]
        xmax = max(p["icc_coord_ka"] * 1e3 * 3, pk * 3)
        xs = [pk * 1.05 * (xmax / (pk * 1.05)) ** (i / 150) for i in range(151)]
        ys = [tempo_iec(p["curva"], p["tms"], x / pk) for x in xs]
        ax.plot(xs, ys, color=cores[k], lw=2, label=f"{nome}: {p['curva']}, TMS {p['tms']:.2f}".replace(".", ","))
        ax.scatter([p["icc_coord_ka"] * 1e3], [p["t_op_s"]], color=GRAFITE, zorder=5, s=24)
        ax.axvline(pk, color=cores[k], ls=":", lw=1)
        ax.axhline(p["t_jus_s"], color=CINZA_CLARO, ls="--", lw=1)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Corrente primária (A)", color=GRAFITE)
    ax.set_ylabel("Tempo de atuação (s)", color=GRAFITE)
    ax.grid(True, which="both", color="#EEF1F6", lw=0.7)
    for sp in ax.spines.values():
        sp.set_color(CINZA_CLARO)
    ax.tick_params(colors=GRAFITE, labelsize=8)
    ax.legend(fontsize=7.5, frameon=True, edgecolor=CINZA_CLARO)
    fig.tight_layout()
    return fig


def grafico_direcional(res: dict, cod: str, figsize=(4.9, 4.9), dpi=170):
    """Característica direcional (67/67N): semiplano de operação MTA ± ROA e casos de falta (fasores do terminal).

    Eixo angular: ângulo da corrente em relação à referência (−3V0 no 67N; Vpol + 90° no 67), isto é, o ângulo
    Δ da memória de cálculo. O torque é máximo em −MTA (corrente atrasada do MTA em relação à referência)."""
    dr = (res.get("direcional") or {}).get("p67n" if cod == "67N" else "p67")
    if not dr or not dr["casos"]:
        return None
    import numpy as np
    mta, roa = dr["mta"], dr["roa"]
    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)
    centro = math.radians(-mta)
    th = np.linspace(centro - math.radians(roa), centro + math.radians(roa), 90)
    ax.fill_between(th, 0, 1.0, color=AZUL_PALIDO, alpha=0.9, label=f"Região de operação (MTA {mta:.0f}° ± {roa:.0f}°)".replace(".", ","))
    ax.plot([centro, centro], [0, 1.0], color=AZUL_ESCURO, lw=1.8, label="Máximo torque")
    ax.plot([0, 0], [0, 1.0], color=CINZA, lw=1, ls=":", label="Referência de polarização")
    imax = max(x["i_mod"] for x in dr["casos"]) or 1.0
    for sentido, cor, marc, rot in (("frente", AZUL, "o", "Faltas à frente"), ("re", GRAFITE, "s", "Faltas à ré")):
        pts = [x for x in dr["casos"] if x["sentido"] == sentido]
        if pts:
            ax.scatter([math.radians(-x["lag"]) for x in pts], [0.35 + 0.65 * x["i_mod"] / imax for x in pts],
                       color=cor, marker=marc, s=34, zorder=5, label=rot)
    ax.set_rlim(0, 1.05)
    ax.set_yticklabels([])
    ax.tick_params(labelsize=8, colors=GRAFITE)
    ax.grid(color="#D9D9D9", lw=0.6)
    ax.set_title(f"Característica direcional — {cod}", color=AZUL_ESCURO, fontsize=10, fontweight="bold", pad=14)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2, fontsize=7.2, frameon=False)
    fig.tight_layout()
    return fig
