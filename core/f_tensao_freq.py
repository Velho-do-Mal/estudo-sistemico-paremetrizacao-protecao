"""Funções de tensão e frequência: 27 (subtensão), 59 (sobretensão) e 81 (sub/sobrefrequência).

Critérios (valores padrão editáveis na etapa 4; devem ser alinhados à norma técnica/critério do cliente):
  * 27 : Vpk = Vop,min − margem  (não atua na faixa operativa);  t ≥ t_eliminação_de_falta + Δt (não atua em falta eliminada)
  * 59 : estágio 1 = Vop,max + margem, temporizado, limitado pela sobretensão temporária suportada;
         estágio 2 = estágio 1 + degrau, rápido
  * 81 : 3 estágios de subfrequência e 3 de sobrefrequência abaixo/acima da faixa de operação sem desligamento,
         escalonados em frequência e em tempo; bloqueio por subtensão para não atuar em curto/perda de referência.
Tensões em pu da tensão nominal (fase-fase); no secundário, em V fase-neutro: V_sec = pu · Vn / (√3 · RTP).
"""
from __future__ import annotations

import math

from core.base_modulo import Ctx, cfg, desce, num, sobe
from core.modulos import E, K

COD = ("27", "59", "81")
TITULO = "Tensão e frequência (27 / 59 / 81)"
G = "Tensão e frequência (27 / 59 / 81)"

ENTRADAS = [
    E("vop_min_pu", "Tensão mínima de operação contínua (pu)", 0.90, ("27", "81"), G,
      "Limite inferior da faixa em que o sistema pode operar sem desligar. O 27 e o bloqueio do 81 precisam ficar abaixo dele.",
      "Valor em pu da tensão nominal. Use a faixa de operação do nível de tensão da LT/barra (condição normal ou de emergência, conforme o critério do cliente).",
      "Procedimentos de Rede do ONS (faixas de tensão por nível); instrução de operação da instalação; documentos técnicos do cliente.",
      mn=0.5, mx=1.2, passo=0.01),
    E("vop_max_pu", "Tensão máxima de operação contínua (pu)", 1.05, ("59",), G,
      "Limite superior da faixa operativa. O 59 precisa ficar acima dele para não atuar em operação normal.",
      "Valor em pu da tensão nominal.",
      "Procedimentos de Rede do ONS (faixas de tensão por nível); instrução de operação; documentos técnicos do cliente.",
      mn=1.0, mx=1.5, passo=0.01),
    E("tov_pu", "Sobretensão temporária suportada pelos equipamentos (pu)", 1.15, ("59",), G,
      "Limita o pickup do 59 estágio 1: o relé deve atuar antes de a tensão superar o que o equipamento suporta pelo tempo ajustado.",
      "Em pu, para o tempo do estágio 1 (segundos). Use a menor suportabilidade entre os equipamentos da instalação.",
      "Curvas de suportabilidade temporária (TOV) do fabricante de transformador, para-raios, TP e disjuntor; folhas de dados.",
      mn=1.0, mx=2.0, passo=0.01),
    E("t_elim_falta_s", "Maior tempo de eliminação de falta na região (s)", 1.0, ("27",), G,
      "O 27 não pode atuar enquanto uma falta ainda está sendo eliminada pela proteção de retaguarda; o tempo do 27 parte desse valor.",
      "Tempo total da retaguarda mais lenta que ainda deve ser esperada (zona 3/51 remota + disjuntor), em segundos.",
      "Estudo de coordenação e seletividade da região; tempos da proteção de retaguarda dos adjacentes.",
      mn=0.0, mx=30.0, passo=0.05),
    E("fop_min_hz", "Frequência mínima sem desligamento (Hz)", 58.5, ("81",), G,
      "Limite inferior da faixa de frequência em que o equipamento/sistema deve permanecer conectado; o 81U atua abaixo dele.",
      "Valor em Hz. O app escalona os estágios a partir dele.",
      "Procedimentos de Rede do ONS (requisitos de frequência); documentos técnicos do cliente; requisitos do fabricante do gerador/transformador.",
      mn=40.0, mx=70.0, passo=0.1),
    E("fop_max_hz", "Frequência máxima sem desligamento (Hz)", 61.5, ("81",), G,
      "Limite superior da faixa de frequência permitida; o 81O atua acima dele.",
      "Valor em Hz.",
      "Procedimentos de Rede do ONS; documentos técnicos do cliente.",
      mn=40.0, mx=70.0, passo=0.1),
    # ---- conferência
    E("ex_27_pu", "27 — pickup existente (pu)", 0.0, ("27",), G, "Compara com o ajuste atual.", "Valor lido no relé, em pu de Vn.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=2.0, passo=0.01, conf=True),
    E("ex_27_t_s", "27 — tempo existente (s)", 0.0, ("27",), G, "Compara com o ajuste atual.", "Segundos.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=600.0, passo=0.05, conf=True),
    E("ex_59_1_pu", "59 estágio 1 — pickup existente (pu)", 0.0, ("59",), G, "Compara com o ajuste atual.", "Valor lido no relé, em pu de Vn.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=2.0, passo=0.01, conf=True),
    E("ex_59_1_t_s", "59 estágio 1 — tempo existente (s)", 0.0, ("59",), G, "Compara com o ajuste atual.", "Segundos.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=600.0, passo=0.05, conf=True),
    E("ex_81u_1_hz", "81U estágio 1 — pickup existente (Hz)", 0.0, ("81",), G, "Compara com o ajuste atual.", "Hz.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=70.0, passo=0.01, conf=True),
    E("ex_81o_1_hz", "81O estágio 1 — pickup existente (Hz)", 0.0, ("81",), G, "Compara com o ajuste atual.", "Hz.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=70.0, passo=0.01, conf=True),
]

CRITERIOS = [
    K("k27_margem_pu", "27: margem abaixo da tensão mínima (pu)", 0.05, ("27",),
      "Garante que o 27 não atue na faixa operativa, cobrindo erro de TP e medição.",
      "Pickup = Vop,mín − margem. Típico 0,03–0,10 pu.", "Critério da norma técnica/critério do cliente.", mn=0.0, mx=0.3, passo=0.01),
    K("k27_dt_s", "27: intervalo sobre a eliminação de falta (s)", 0.30, ("27",),
      "Garante seletividade: o 27 só atua depois que as proteções de falta já tiveram tempo de eliminar a falta.",
      "t27 = t_eliminação + Δt.", "Critério de coordenação do cliente.", mn=0.0, mx=5.0, passo=0.05),
    K("k27_passo_pu", "27/59: passo do pickup de tensão (pu)", 0.01, ("27", "59"),
      "Resolução do relé no ajuste de tensão.", "Passo do parâmetro no relé (ex.: 0,01 pu ou 0,25 V sec).", "Manual do relé.",
      mn=0.001, mx=0.1, passo=0.001, fmt="%.3f"),
    K("k59_margem_pu", "59: margem acima da tensão máxima (pu)", 0.03, ("59",),
      "Garante que o 59 não atue na faixa operativa.", "Pickup 1 = Vop,máx + margem. Típico 0,02–0,05 pu.",
      "Critério da norma técnica/critério do cliente.", mn=0.0, mx=0.3, passo=0.01),
    K("k59_t1_s", "59 estágio 1: tempo (s)", 3.0, ("59",),
      "Tempo longo: tolera sobretensões transitórias de manobra e regulação.", "Segundos. Deve respeitar a suportabilidade temporária.",
      "Critério do cliente; curva TOV dos equipamentos.", mn=0.0, mx=600.0, passo=0.5),
    K("k59_delta2_pu", "59 estágio 2: degrau sobre o estágio 1 (pu)", 0.10, ("59",),
      "Estágio rápido para sobretensões severas.", "Pickup 2 = pickup 1 + degrau.", "Critério do cliente.", mn=0.01, mx=0.5, passo=0.01),
    K("k59_t2_s", "59 estágio 2: tempo (s)", 0.5, ("59",),
      "Atuação rápida para proteger isolamento em sobretensão severa.", "Segundos.", "Critério do cliente; curva TOV.",
      mn=0.0, mx=60.0, passo=0.1),
    K("k81_margem_hz", "81: margem além da faixa de operação (Hz)", 0.2, ("81",),
      "Evita atuação por erro de medição de frequência dentro da faixa permitida.", "Pickup 1 = limite da faixa ∓ margem.",
      "Critério do cliente / manual do relé.", mn=0.0, mx=2.0, passo=0.05),
    K("k81_passo_est_hz", "81: degrau entre estágios (Hz)", 0.5, ("81",),
      "Escalona os estágios para desligar progressivamente.", "Frequência entre estágios sucessivos.", "Critério do cliente.",
      mn=0.1, mx=3.0, passo=0.1),
    K("k81_passo_hz", "81: passo do ajuste de frequência (Hz)", 0.01, ("81",),
      "Resolução do relé.", "Passo do parâmetro no relé.", "Manual do relé.", mn=0.001, mx=0.5, passo=0.001, fmt="%.3f"),
    K("k81_t1_s", "81 estágio 1: tempo (s)", 10.0, ("81",),
      "Estágio mais próximo da faixa permitida: tempo mais longo.", "Segundos.", "norma técnica/critério do cliente.", mn=0.0, mx=600.0, passo=0.5),
    K("k81_t2_s", "81 estágio 2: tempo (s)", 3.0, ("81",),
      "Estágio intermediário.", "Segundos.", "norma técnica/critério do cliente.", mn=0.0, mx=600.0, passo=0.5),
    K("k81_t3_s", "81 estágio 3: tempo (s)", 0.5, ("81",),
      "Estágio mais afastado: atuação rápida.", "Segundos.", "norma técnica/critério do cliente.", mn=0.0, mx=600.0, passo=0.1),
    K("k81_vbloq_pu", "81: bloqueio por subtensão (pu)", 0.80, ("81",),
      "O elemento de frequência é bloqueado com tensão baixa, onde a medição de frequência não é confiável (falta, perda de TP).",
      "Pickup do bloqueio; deve ficar abaixo da tensão mínima operativa.", "Manual do relé; critério do cliente.",
      mn=0.1, mx=1.0, passo=0.01),
]

TEXTOS = {
    "27": {"secao": "Função 27",
           "metodologia": ("O elemento de subtensão deve permanecer em repouso em toda a faixa de operação e só atuar para tensão sustentadamente "
                           "baixa. O pickup fica abaixo da tensão mínima operativa por uma margem e o tempo supera a eliminação das faltas "
                           "pela proteção de retaguarda, para não atuar durante curtos eliminados."),
           "premissas": ["Funções 27/59: tensões em pu da tensão nominal fase-fase; no secundário, em V fase-neutro (Vn/(√3·RTP))."],
           "limitacoes": ["as funções 27/59/81 foram ajustadas por critério de faixa operativa e tempo; estudos de estabilidade de tensão, "
                          "ride-through de geração distribuída e esquemas regionais de alívio de carga devem ser verificados à parte"]},
    "59": {"secao": "Função 59",
           "metodologia": ("O elemento de sobretensão é ajustado em dois estágios: o primeiro, temporizado, acima da tensão máxima operativa "
                           "e abaixo da sobretensão temporária suportada pelos equipamentos; o segundo, rápido, atua em sobretensões severas."),
           "premissas": [], "limitacoes": []},
    "81": {"secao": "Função 81",
           "metodologia": ("Os elementos de frequência são escalonados em três estágios de subfrequência e três de sobrefrequência, "
                           "além da faixa de operação permitida, com tempos decrescentes conforme o desvio. Um bloqueio por subtensão evita "
                           "atuação quando a tensão é insuficiente para medir a frequência."),
           "premissas": ["Função 81: faixa de frequência sem desligamento informada pelo usuário; os tempos dos estágios são critérios editáveis."],
           "limitacoes": []},
}
REFS = ["IEEE Std C37.2 — funções 27, 59 e 81.",
        "IEEE Std C37.117 — Guide for the Application of Protective Relays Used for Abnormal Frequency Load Shedding and Restoration.",
        "IEC 60255-127 / IEC 60255-181 — Relés de medição e proteção: subtensão/sobretensão e frequência."]


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    cc = cfg(c, CRITERIOS)
    rtp, vn = num(d, "rtp", 1.0), num(d, "vn_kv", 230.0)
    if rtp <= 0 or vn <= 0:
        raise ValueError("RTP e tensão nominal devem ser maiores que zero.")
    x = Ctx(d)
    fq, fmt = x.fq, x.fmt
    f_nom = num(d, "f_hz", 60.0)
    modo_conf = d.get("modo") == "conferencia"
    dados: dict = {}
    passo_v = cc["k27_passo_pu"]
    f_vsec = vn * 1000.0 / (math.sqrt(3) * rtp)           # V sec fase-neutro correspondente a 1 pu

    def vsec(pu):
        return pu * f_vsec

    if incluir_base:
        x.passo("Base", "Conversão de tensão do primário ao secundário", r"V_{sec} = V_{pu} \cdot \frac{V_{n}}{\sqrt{3} \cdot RTP}",
                rf"V_{{sec}} = V_{{pu}} \cdot \frac{{{fq(vn*1000,0)}}}{{\sqrt{{3}} \cdot {fq(rtp,1)}}} = {fq(f_vsec,2)} \cdot V_{{pu}}\ \mathrm{{V}}")

    # ------------------------------------------------------------------ 27
    if "27" in sel:
        sec = "Função 27"
        v_min = num(d, "vop_min_pu", 0.90)
        t_el = num(d, "t_elim_falta_s", 0.0)
        pk = desce(v_min - cc["k27_margem_pu"], passo_v)
        t27 = t_el + cc["k27_dt_s"]
        x.passo(sec, "Pickup de subtensão", r"V_{pk,27} = V_{op,min} - m_{27}",
                rf"V_{{pk,27}} = {fq(v_min)} - {fq(cc['k27_margem_pu'])} = {fq(pk)}\ \mathrm{{pu}} \qquad "
                rf"V_{{pk,27}} = {fq(vsec(pk))}\ \mathrm{{V\ sec\ (F-N)}}")
        x.passo(sec, "Tempo de atuação", r"t_{27} \ge t_{elim} + \Delta t_{27}",
                rf"t_{{27}} \ge {fq(t_el)} + {fq(cc['k27_dt_s'])} = {fq(t27)}\ \mathrm{{s}}")
        x.check("27: pickup abaixo da faixa operativa", "Vpk < Vop,mín", pk, v_min, pk < v_min)
        x.check("27: pickup coerente", "Vpk > 0", pk, 0.0, pk > 0)
        if t_el <= 0:
            x.alertas.append("Função 27: tempo de eliminação de falta não informado; o tempo do 27 ficou só com o intervalo Δt. Informe a retaguarda mais lenta.")
        crit = f"Vop,mín − {fmt(cc['k27_margem_pu'],2)} pu; t ≥ t_elim + {fmt(cc['k27_dt_s'],2)} s"
        x.add("27 — Subtensão", "Pickup", "27P1P", vsec(pk), "V sec F-N", vn * pk, "kV F-F", crit)
        x.add("27 — Subtensão", "Tempo de atuação", "27P1D", t27, "s", t27, "s", "t ≥ eliminação de falta + Δt",
              "OK" if t_el > 0 else "REVISAR")
        x.card("Pickup 27", f"{fmt(vsec(pk),1)} V sec", f"{fmt(pk,2)} pu · {fmt(t27,2)} s")
        dados["p27"] = {"pu": pk, "v_sec": vsec(pk), "t_s": t27, "t_elim_s": t_el}
        if modo_conf:
            x.conferir("27 pickup (pu)", num(d, "ex_27_pu"), None, v_min - 1e-9, "pu", "Deve ficar abaixo de Vop,mín")
            x.conferir("27 tempo (s)", num(d, "ex_27_t_s"), t_el, None, "s", "Deve superar a eliminação de falta")

    # ------------------------------------------------------------------ 59
    if "59" in sel:
        sec = "Função 59"
        v_max = num(d, "vop_max_pu", 1.05)
        tov = num(d, "tov_pu", 1.15)
        pk1 = sobe(v_max + cc["k59_margem_pu"], passo_v)
        pk2 = sobe(pk1 + cc["k59_delta2_pu"], passo_v)
        x.passo(sec, "Pickup do estágio 1 (temporizado)", r"V_{pk,59-1} = V_{op,max} + m_{59}",
                rf"V_{{pk,59-1}} = {fq(v_max)} + {fq(cc['k59_margem_pu'])} = {fq(pk1)}\ \mathrm{{pu}} \qquad "
                rf"V_{{pk,59-1}} = {fq(vsec(pk1))}\ \mathrm{{V\ sec\ (F-N)}}")
        x.passo(sec, "Pickup do estágio 2 (rápido)", r"V_{pk,59-2} = V_{pk,59-1} + \Delta V_{2}",
                rf"V_{{pk,59-2}} = {fq(pk1)} + {fq(cc['k59_delta2_pu'])} = {fq(pk2)}\ \mathrm{{pu}} \qquad "
                rf"V_{{pk,59-2}} = {fq(vsec(pk2))}\ \mathrm{{V\ sec\ (F-N)}}")
        ok1 = pk1 > v_max
        ok_tov = pk1 <= tov + 1e-9
        x.check("59-1: acima da faixa operativa", "Vpk1 > Vop,máx", pk1, v_max, ok1)
        x.check("59-1: abaixo da suportabilidade temporária", "Vpk1 ≤ TOV suportada", pk1, tov, ok_tov,
                "" if ok_tov else "Reduza o tempo do estágio 1 ou avalie a suportabilidade do equipamento")
        x.check("59-2 acima do 59-1", "Vpk2 > Vpk1", pk2, pk1, pk2 > pk1)
        if not ok_tov:
            x.alertas.append(f"Função 59: o pickup do estágio 1 ({fmt(pk1,2)} pu) supera a sobretensão temporária suportada "
                             f"({fmt(tov,2)} pu); avalie reduzir a margem ou confirmar a suportabilidade com o fabricante.")
        st1 = "OK" if (ok1 and ok_tov) else "REVISAR"
        x.add("59 — Sobretensão", "Estágio 1 — pickup", "59P1P", vsec(pk1), "V sec F-N", vn * pk1, "kV F-F",
              f"Vop,máx + {fmt(cc['k59_margem_pu'],2)} pu ≤ TOV", st1)
        x.add("59 — Sobretensão", "Estágio 1 — tempo", "59P1D", cc["k59_t1_s"], "s", cc["k59_t1_s"], "s", "Critério de tempo longo", "OK")
        x.add("59 — Sobretensão", "Estágio 2 — pickup", "59P2P", vsec(pk2), "V sec F-N", vn * pk2, "kV F-F",
              f"Estágio 1 + {fmt(cc['k59_delta2_pu'],2)} pu", "OK")
        x.add("59 — Sobretensão", "Estágio 2 — tempo", "59P2D", cc["k59_t2_s"], "s", cc["k59_t2_s"], "s", "Critério de atuação rápida", "OK")
        x.card("Pickup 59 (1 / 2)", f"{fmt(vsec(pk1),1)} / {fmt(vsec(pk2),1)} V sec",
               f"{fmt(pk1,2)} / {fmt(pk2,2)} pu · {fmt(cc['k59_t1_s'],1)} / {fmt(cc['k59_t2_s'],1)} s")
        dados["p59"] = {"pu1": pk1, "pu2": pk2, "t1_s": cc["k59_t1_s"], "t2_s": cc["k59_t2_s"], "tov_pu": tov,
                        "v_sec1": vsec(pk1), "v_sec2": vsec(pk2)}
        if modo_conf:
            x.conferir("59-1 pickup (pu)", num(d, "ex_59_1_pu"), v_max + 1e-9, tov, "pu", "Entre Vop,máx e a TOV suportada")
            x.conferir("59-1 tempo (s)", num(d, "ex_59_1_t_s"), None, None, "s", "Sem limite automático; confirmar com a suportabilidade")

    # ------------------------------------------------------------------ 81
    if "81" in sel:
        sec = "Função 81"
        f_lo, f_hi = num(d, "fop_min_hz", 58.5), num(d, "fop_max_hz", 61.5)
        m, dst, pf = cc["k81_margem_hz"], cc["k81_passo_est_hz"], cc["k81_passo_hz"]
        tempos = [cc["k81_t1_s"], cc["k81_t2_s"], cc["k81_t3_s"]]
        u = [desce(f_lo - m - i * dst, pf) for i in range(3)]
        o = [sobe(f_hi + m + i * dst, pf) for i in range(3)]
        v_min = num(d, "vop_min_pu", 0.90)
        vb = desce(cc["k81_vbloq_pu"], passo_v)
        x.passo(sec, "Estágios de subfrequência", r"f_{81U,i} = f_{min} - m_{81} - (i-1) \cdot \Delta f",
                rf"f_{{81U,i}} = {fq(f_lo)} - {fq(m)} - (i-1) \cdot {fq(dst)} \rightarrow "
                + r"\ ".join(rf"{fq(v)}" for v in u) + r"\ \mathrm{Hz}")
        x.passo(sec, "Estágios de sobrefrequência", r"f_{81O,i} = f_{max} + m_{81} + (i-1) \cdot \Delta f",
                rf"f_{{81O,i}} = {fq(f_hi)} + {fq(m)} + (i-1) \cdot {fq(dst)} \rightarrow "
                + r"\ ".join(rf"{fq(v)}" for v in o) + r"\ \mathrm{Hz}")
        x.passo(sec, "Bloqueio por subtensão", r"V_{bloq} < V_{op,min}",
                rf"V_{{bloq}} = {fq(vb)}\ \mathrm{{pu}} < {fq(v_min)}\ \mathrm{{pu}} \qquad V_{{bloq}} = {fq(vsec(vb))}\ \mathrm{{V\ sec\ (F-N)}}")
        x.check("81U: abaixo da faixa", "f81U,1 < f_min", u[0], f_lo, u[0] < f_lo)
        x.check("81O: acima da faixa", "f81O,1 > f_max", o[0], f_hi, o[0] > f_hi)
        x.check("81: tempos decrescentes", "t1 ≥ t2 ≥ t3", f"{tempos[0]}/{tempos[1]}/{tempos[2]}", "decrescente",
                tempos[0] >= tempos[1] >= tempos[2])
        x.check("81: bloqueio abaixo da faixa operativa", "Vbloq < Vop,mín", vb, v_min, vb < v_min)
        if not (f_lo < f_nom < f_hi):
            x.alertas.append(f"Função 81: a frequência nominal ({fmt(f_nom,1)} Hz) não está dentro da faixa informada ({fmt(f_lo,1)}–{fmt(f_hi,1)} Hz).")
        st_bl = "OK" if vb < v_min else "REVISAR"
        for i in range(3):
            x.add("81 — Frequência", f"81U estágio {i+1} — pickup", f"81D{i+1}P", u[i], "Hz", u[i], "Hz",
                  f"{fmt(f_lo,2)} Hz − {fmt(m,2)} − {i}·{fmt(dst,2)}", "OK")
            x.add("81 — Frequência", f"81U estágio {i+1} — tempo", f"81D{i+1}D", tempos[i], "s", tempos[i], "s", "Critério de tempo (etapa 4)", "OK")
        for i in range(3):
            x.add("81 — Frequência", f"81O estágio {i+1} — pickup", f"81D{i+4}P", o[i], "Hz", o[i], "Hz",
                  f"{fmt(f_hi,2)} Hz + {fmt(m,2)} + {i}·{fmt(dst,2)}", "OK")
            x.add("81 — Frequência", f"81O estágio {i+1} — tempo", f"81D{i+4}D", tempos[i], "s", tempos[i], "s", "Critério de tempo (etapa 4)", "OK")
        x.add("81 — Frequência", "Bloqueio por subtensão", "—", vsec(vb), "V sec F-N", vn * vb, "kV F-F",
              "Abaixo de Vop,mín", st_bl)
        x.card("81U / 81O (estágio 1)", f"{fmt(u[0],2)} / {fmt(o[0],2)} Hz", f"{fmt(tempos[0],1)} s · bloqueio {fmt(vsec(vb),1)} V")
        x.tabela("Funções 81 — estágios", ["Estágio", "81U (Hz)", "81O (Hz)", "Tempo (s)"],
                 [[str(i + 1), fmt(u[i], 2), fmt(o[i], 2), fmt(tempos[i], 1)] for i in range(3)])
        dados["p81"] = {"u": u, "o": o, "t": tempos, "f_lo": f_lo, "f_hi": f_hi, "f_nom": f_nom, "vbloq_pu": vb, "vbloq_sec": vsec(vb)}
        if modo_conf:
            x.conferir("81U estágio 1 (Hz)", num(d, "ex_81u_1_hz"), None, f_lo - 1e-9, "Hz", "Deve ficar abaixo de f_mín")
            x.conferir("81O estágio 1 (Hz)", num(d, "ex_81o_1_hz"), f_hi + 1e-9, None, "Hz", "Deve ficar acima de f_máx")
    return x.pacote(dados)


def figuras(r: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.plots import AZUL, AZUL_ESCURO, AZUL_PALIDO, CINZA, CINZA_CLARO
    md = (r.get("modulos") or {}).get("f_tensao_freq") or {}
    out = []
    p27, p59 = md.get("p27"), md.get("p59")
    if p27 or p59:
        e = r["entrada"]
        vmin, vmax = float(e.get("vop_min_pu", 0.9)), float(e.get("vop_max_pu", 1.05))
        fig, ax = plt.subplots(figsize=(6.8, 3.8), dpi=170)
        ax.axhspan(vmin, vmax, color=AZUL_PALIDO, label="Faixa operativa")
        if p27:
            ax.hlines(p27["pu"], p27["t_s"], 100, color=AZUL_ESCURO, lw=2, label="27 (atua abaixo, após t)")
            ax.vlines(p27["t_s"], 0.2, p27["pu"], color=AZUL_ESCURO, lw=1, ls=":")
        if p59:
            ax.hlines(p59["pu1"], p59["t1_s"], 100, color=AZUL, lw=2, label="59-1 (atua acima, após t)")
            ax.hlines(p59["pu2"], p59["t2_s"], 100, color=CINZA, lw=2, label="59-2 (atua acima, após t)")
            ax.axhline(p59["tov_pu"], color=CINZA, lw=1, ls="--", label="TOV suportada")
        ax.set_xscale("log"); ax.set_xlim(0.1, 100)
        ax.set_xlabel("Tempo (s)"); ax.set_ylabel("Tensão (pu)")
        ax.grid(True, color=CINZA_CLARO, lw=0.6)
        ax.set_title("Características 27 / 59: tensão × tempo", color=AZUL_ESCURO, fontsize=10)
        ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
        fig.tight_layout()
        out.append(("Características de tensão — funções 27/59", fig))
    p81 = md.get("p81")
    if p81:
        fig, ax = plt.subplots(figsize=(6.8, 3.8), dpi=170)
        ax.axhspan(p81["f_lo"], p81["f_hi"], color=AZUL_PALIDO, label="Faixa sem desligamento")
        for i in range(3):
            ax.hlines(p81["u"][i], p81["t"][i], 100, color=AZUL_ESCURO, lw=1.8, label="81U" if i == 0 else None)
            ax.hlines(p81["o"][i], p81["t"][i], 100, color=AZUL, lw=1.8, label="81O" if i == 0 else None)
        ax.axhline(p81["f_nom"], color=CINZA, lw=0.8, ls="--", label="Nominal")
        ax.set_xscale("log"); ax.set_xlim(0.1, 100)
        ax.set_xlabel("Tempo (s)"); ax.set_ylabel("Frequência (Hz)")
        ax.grid(True, color=CINZA_CLARO, lw=0.6)
        ax.set_title("Escalonamento 81: frequência × tempo", color=AZUL_ESCURO, fontsize=10)
        ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
        fig.tight_layout()
        out.append(("Estágios de frequência — função 81", fig))
    return out
