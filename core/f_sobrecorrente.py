"""Funções de sobrecorrente: 50, 51, 50N e 51N.

Critérios (valores padrão editáveis na etapa 4; devem ser alinhados à norma do cliente):
  * 51  : k_pickup_min·Iref ≤ Ipk ≤ Icc_fase,min / k_sens_51
  * 51N : k_desb·Iref       ≤ Ipk ≤ Icc_FT,min  / k_sens_51n   (k_desb = desequilíbrio admissível)
  * 50  : Ipk ≥ k_inst · Icc_fase na barra remota (falta a 100 % da LT) -> não sobrealcança
  * 50N : Ipk ≥ k_inst · Icc_FT   na barra remota
  * Curvas IEC 60255-151: t = TMS · k / ((I/Ipk)^α − 1). TMS calculado para que o tempo de atuação,
    na corrente da falta remota, seja t_jusante + Δt (intervalo de coordenação).

Convenção dos casos de curto: `local_pct` é a posição da falta medida a partir do terminal do relé
(0 = barra local, 100 = barra remota). Para falta fase-terra, `icc_ka` é a corrente de falta
(= 3I0, corrente residual).
"""
from __future__ import annotations

import math

# nome: (k, alfa, descrição, curva equivalente SEL — conferir no manual do firmware)
CURVAS = {
    "IEC NI": (0.14, 0.02, "IEC normal inversa", "C1"),
    "IEC VI": (13.5, 1.0, "IEC muito inversa", "C2"),
    "IEC EI": (80.0, 2.0, "IEC extremamente inversa", "C3"),
    "IEC LTI": (120.0, 1.0, "IEC inversa de longo tempo", "C4"),
}

CRITERIOS_SOBRECORRENTE = {
    "k_desb": 0.20,          # pickup 51N >= k_desb * Iref (desequilíbrio/corrente residual de regime)
    "k_sens_51n": 1.50,      # Icc_FT,min / pickup 51N >= k
    "k_inst": 1.20,          # pickup 50/50N >= k_inst * Icc na barra remota
    "dt_coord": 0.30,        # intervalo de coordenação (s)
    "passo_pickup_a": 10.0,  # arredondamento do pickup (A primários)
    "tms_min": 0.05,
    "tms_max": 1.00,
    "passo_tms": 0.01,
}


def tempo_iec(curva: str, tms: float, m: float) -> float:
    """Tempo de atuação (s) para a razão m = I/Ipk (m > 1)."""
    k, a, _, _ = CURVAS[curva]
    if m <= 1.0:
        return float("inf")
    return tms * k / (m ** a - 1.0)


def tms_para(curva: str, t_alvo: float, m: float) -> float | None:
    k, a, _, _ = CURVAS[curva]
    if m <= 1.0 or t_alvo <= 0:
        return None
    return t_alvo * (m ** a - 1.0) / k


def _sobe(x: float, passo: float) -> float:
    return math.ceil(x / passo - 1e-9) * passo if passo > 0 else x


def _separa_casos(casos):
    fase, terra = [], []
    for x in casos or []:
        tipo = str(x.get("tipo", "")).upper()
        try:
            icc = float(x.get("icc_ka"))
        except (TypeError, ValueError):
            continue
        if not icc > 0:
            continue
        try:
            loc = float(x.get("local_pct"))
        except (TypeError, ValueError):
            loc = None
        if tipo in ("3F", "FF", "FFT"):
            fase.append((icc, loc))
        if tipo in ("FT", "FFT"):
            terra.append((icc, loc))
    return fase, terra


def corrente_referencia(d: dict, c: dict) -> float:
    vn = float(d["vn_kv"])
    s_max = float(d.get("s_max_mva") or 0.0)
    i_term = float(d.get("i_term_a") or 0.0)
    i_fluxo = s_max * 1e3 / (math.sqrt(3) * vn) if s_max > 0 else 0.0
    return max(i_fluxo, i_term) if c.get("usar_limite_termico", True) else (i_fluxo or i_term)


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    """Retorna passos, verificações, alertas, ajustes e conferência das funções de sobrecorrente marcadas."""
    from core.calc import fmt, fmt_eq        # import tardio: evita ciclo calc <-> módulo

    cc = dict(CRITERIOS_SOBRECORRENTE)
    cc.update({k: c[k] for k in CRITERIOS_SOBRECORRENTE if k in c})
    rtc = float(d["rtc"])
    if rtc <= 0:
        raise ValueError("RTC deve ser maior que zero.")
    i_ref = corrente_referencia(d, c)
    if i_ref <= 0:
        raise ValueError("Informe o fluxo máximo (MVA) ou o limite térmico (A) para as funções de sobrecorrente.")

    passos, verif, alertas, aj, conf = [], [], [], [], []
    saida: dict = {}
    fase, terra = _separa_casos(casos)
    icc_min_fase = min((i for i, _ in fase), default=0.0)
    icc_min_terra = min((i for i, _ in terra), default=0.0)
    rem_fase = [i for i, loc in fase if loc is not None and loc >= 99.5]
    rem_terra = [i for i, loc in terra if loc is not None and loc >= 99.5]
    prox_fase = [i for i, loc in fase if loc is not None and loc <= 50.0]
    prox_terra = [i for i, loc in terra if loc is not None and loc <= 50.0]
    icc_rem_fase = max(rem_fase, default=0.0)
    icc_rem_terra = max(rem_terra, default=0.0)
    passo_a = cc["passo_pickup_a"]
    nomes_sel = str(d.get("fabricante", "")).strip().upper().startswith("SEL")

    nomes_ge = str(d.get("fabricante", "")).strip().upper().startswith("GE MULTILIN")

    def n(sel_nome):
        if nomes_sel:
            return sel_nome
        if nomes_ge:  # GE L90 (manual 7.2x §5.6.8/5.6.9); pickup em pu do TC (1 A sec = pu)
            blk = "NEUTRAL TOC1" if sel_nome.startswith("51G") else "PHASE TOC1"
            if sel_nome.startswith(("51P", "51G")):
                suf = {"P": "PICKUP (pu)", "C": "CURVE", "D": "TD MULTIPLIER"}.get(sel_nome[-1] if not sel_nome.endswith("TD") else "D")
                return f"{blk} {suf}" if suf else "—"
        return "—"

    def passo(secao, titulo, simb, num, nota=""):
        passos.append({"secao": secao, "titulo": titulo, "simb": simb, "num": num, "nota": nota})

    def check(item, criterio, valor, limite, ok, nota=""):
        verif.append({"item": item, "criterio": criterio, "valor": valor, "limite": limite,
                      "status": "OK" if ok else "FALHA", "nota": nota})

    def add(funcao, param, nome, vsec, usec, vpri, upri, criterio, status="OK", item=""):
        aj.append({"funcao": funcao, "parametro": param, "nome_rele": n(nome), "valor_sec": vsec,
                   "unid_sec": usec, "valor_pri": vpri, "unid_pri": upri, "criterio": criterio,
                   "item_carta": item, "status": status})

    def linha_conf(item, existente, minimo, maximo, unid, nota=""):
        if not existente:
            conf.append({"item": item, "existente": "não informado", "minimo": minimo, "maximo": maximo,
                         "unid": unid, "status": "SEM DADO", "nota": nota})
            return
        ok = (minimo is None or existente >= minimo - 1e-9) and (maximo is None or existente <= maximo + 1e-9)
        conf.append({"item": item, "existente": existente, "minimo": minimo, "maximo": maximo, "unid": unid,
                     "status": "CONFORME" if ok else "NÃO CONFORME", "nota": nota})

    # ---------------------------------------------------------------- temporizadas (51 / 51N)
    def temporizada(cod, neutro):
        sec = f"Função {cod}"
        k_min = cc["k_desb"] if neutro else c["k_pickup_min"]
        k_sens = cc["k_sens_51n"] if neutro else c["k_sens_51"]
        icc_min = icc_min_terra if neutro else icc_min_fase
        icc_coord = icc_rem_terra if neutro else icc_rem_fase
        curva = d.get("curva51n" if neutro else "curva51") or "IEC NI"
        if curva not in CURVAS:
            curva = "IEC NI"
        t_jus = float(d.get("t_jus_n_s" if neutro else "t_jus_s") or 0.0)
        ex_pk = float(d.get("ex_pickup51n_a_sec" if neutro else "ex_pickup51_a_sec") or 0.0)
        ex_tms = float(d.get("ex_tms51n" if neutro else "ex_tms51") or 0.0)
        p_min = k_min * i_ref
        p_max = (icc_min * 1e3) / k_sens if icc_min > 0 else 0.0
        rec = _sobe(p_min, passo_a)
        viavel = p_max == 0 or rec <= p_max
        icc_txt = "Icc_{FT,min}" if neutro else "Icc_{min}"
        kp_txt = "k_{d}" if neutro else "k_{p}"
        ks_txt = "k_{s51N}" if neutro else "k_{s51}"
        pk_txt = "I_{pk,N}" if neutro else "I_{pk}"
        passo(sec, "Faixa admissível do pickup",
              rf"{kp_txt} \cdot I_{{ref}} \le {pk_txt} \le \frac{{{icc_txt}}}{{{ks_txt}}}",
              rf"{fmt_eq(k_min)} \cdot {fmt_eq(i_ref,1)} = {fmt_eq(p_min,0)}\ \mathrm{{A}} \le {pk_txt} \le "
              + (rf"\frac{{{fmt_eq(icc_min*1e3,0)}}}{{{fmt_eq(k_sens)}}} = {fmt_eq(p_max,0)}\ \mathrm{{A}}"
                 if icc_min > 0 else r"(Icc mínima não informada)"))
        if icc_min == 0:
            alertas.append(f"Sem casos de curto-circuito de {'fase-terra' if neutro else 'fase'} importados: o limite "
                           f"superior do pickup {cod} não pôde ser verificado.")
        check(f"Pickup {cod} recomendado", f"Faixa {fmt(k_min,2)}·Iref ≤ Ipk ≤ Icc,min/{fmt(k_sens,2)}",
              rec, p_max if p_max else "—", viavel)

        # curva e TMS
        k, a, desc, c_sel = CURVAS[curva]
        tms, t_op, status_tms, crit_tms = None, None, "OK", f"{desc}; informe o tempo do dispositivo a jusante"
        if icc_coord > 0 and t_jus > 0:
            m = icc_coord * 1e3 / rec
            t_alvo = t_jus + cc["dt_coord"]
            tms_calc = tms_para(curva, t_alvo, m)
            if tms_calc is not None:
                tms = _sobe(max(tms_calc, 0.0), cc["passo_tms"])   # arredonda p/ cima: mantém o intervalo de coordenação
                tms_fora = tms < cc["tms_min"] - 1e-9 or tms > cc["tms_max"] + 1e-9
                tms = min(max(tms, cc["tms_min"]), cc["tms_max"])
                t_op = tempo_iec(curva, tms, m)
                passo(sec, "Curva e multiplicador de tempo (TMS)",
                      r"M = \frac{I_{cc,coord}}{I_{pk}} \qquad t_{alvo} = t_{jus} + \Delta t \qquad "
                      r"TMS = t_{alvo} \cdot \frac{M^{\alpha} - 1}{k}",
                      rf"M = \frac{{{fmt_eq(icc_coord*1e3,0)}}}{{{fmt_eq(rec,0)}}} = {fmt_eq(m,2)} \qquad "
                      rf"t_{{alvo}} = {fmt_eq(t_jus)} + {fmt_eq(cc['dt_coord'])} = {fmt_eq(t_alvo)}\ \mathrm{{s}} \qquad "
                      rf"TMS = {fmt_eq(t_alvo)} \cdot \frac{{{fmt_eq(m,2)}^{{{fmt_eq(a,2)}}} - 1}}{{{fmt_eq(k,2)}}} = {fmt_eq(tms,2)}",
                      f"Curva {curva} (k = {fmt(k,2)}; α = {fmt(a,2)}). Tempo de atuação resultante em "
                      f"{fmt(icc_coord,2)} kA: {fmt(t_op,3)} s.")
                crit_tms = f"{desc}; atua em {fmt(t_op,2)} s na falta remota (t_jus {fmt(t_jus,2)} s + Δt {fmt(cc['dt_coord'],2)} s)"
                check(f"TMS {cod}", "TMS dentro da faixa do relé", tms, f"{cc['tms_min']}–{cc['tms_max']}", not tms_fora,
                      "Faixa assumida; conferir no manual" if tms_fora else "")
                if tms_fora:
                    status_tms = "REVISAR"
                    alertas.append(f"TMS da função {cod} ficou fora da faixa {cc['tms_min']}–{cc['tms_max']}; "
                                   "trocar o tipo de curva ou rever o tempo do dispositivo a jusante.")
        else:
            falta = []
            if icc_coord <= 0:
                falta.append("falta a 100% da LT")
            if t_jus <= 0:
                falta.append("tempo do dispositivo a jusante")
            alertas.append(f"TMS da função {cod} não calculado: informe {' e '.join(falta)}.")
            status_tms = "REVISAR"
        status = "OK" if viavel else "REVISAR"
        crit_pk = f"{fmt(k_min,2)}·Iref ≤ Ipk ≤ Icc,min/{fmt(k_sens,2)}"
        nm = "51G1" if neutro else "51P1"
        add(f"{cod} — Sobrecorrente temporizada {'de neutro' if neutro else 'de fase'}", "Pickup", f"{nm}P",
            rec / rtc, "A sec", rec, "A pri", crit_pk, status)
        add(f"{cod} — Sobrecorrente temporizada {'de neutro' if neutro else 'de fase'}", "Curva", f"{nm}C",
            curva, "—", curva, "—", f"Curva escolhida (SEL: {c_sel}, conferir)", "OK")
        add(f"{cod} — Sobrecorrente temporizada {'de neutro' if neutro else 'de fase'}", "Multiplicador de tempo (TMS)",
            f"{nm}TD", tms if tms is not None else "n/d", "—", tms if tms is not None else "n/d", "—", crit_tms, status_tms)
        res = {"i_ref": i_ref, "min_pri": p_min, "max_pri": p_max, "rec_pri": rec, "rec_sec": rec / rtc,
               "icc_min_fase_ka": icc_min_fase, "icc_min_terra_ka": icc_min_terra, "viavel": viavel,
               "curva": curva, "tms": tms, "t_op_s": t_op, "icc_coord_ka": icc_coord, "t_jus_s": t_jus,
               "dt_coord_s": cc["dt_coord"], "neutro": neutro}
        # conferência (modo "conferencia")
        if d.get("modo") == "conferencia":
            linha_conf(f"Pickup {cod} (A sec)", ex_pk, p_min / rtc, (p_max / rtc) if p_max else None, "A",
                       "Faixa k·Iref ≤ Ipk ≤ Icc,min/k")
            if tms is not None:
                linha_conf(f"TMS {cod}", ex_tms, max(tms - 0.10, cc["tms_min"]), tms + 0.10, "—",
                           "Tolerância ±0,10 em torno do TMS calculado")
        return res

    # ---------------------------------------------------------------- instantâneas (50 / 50N)
    def instantanea(cod, neutro):
        sec = f"Função {cod}"
        icc_rem = icc_rem_terra if neutro else icc_rem_fase
        prox = prox_terra if neutro else prox_fase
        ex_pk = float(d.get("ex_pickup50n_a_sec" if neutro else "ex_pickup50_a_sec") or 0.0)
        nm = "50G1P" if neutro else "50P1P"
        funcao = f"{cod} — Sobrecorrente instantânea {'de neutro' if neutro else 'de fase'}"
        if icc_rem <= 0:
            alertas.append(f"Função {cod}: não há caso de curto {'fase-terra' if neutro else 'de fase'} a 100% da LT "
                           "(barra remota). Importe/digite essa falta para calcular o pickup instantâneo.")
            add(funcao, "Pickup", nm, "n/d", "A sec", "n/d", "A pri", "Requer falta a 100% da LT", "REVISAR")
            return {"neutro": neutro, "calculado": False}
        p_min = cc["k_inst"] * icc_rem * 1e3
        rec = _sobe(p_min, passo_a)
        icc_txt = "Icc_{FT,rem}" if neutro else "Icc_{rem}"
        passo(sec, "Pickup instantâneo (não sobrealcançar a barra remota)",
              rf"I_{{pk,inst}} \ge k_{{i}} \cdot {icc_txt}",
              rf"I_{{pk,inst}} \ge {fmt_eq(cc['k_inst'])} \cdot {fmt_eq(icc_rem*1e3,0)} = {fmt_eq(p_min,0)}\ \mathrm{{A}} "
              rf"\rightarrow {fmt_eq(rec,0)}\ \mathrm{{A}}")
        ok = True
        icc_prox = min(prox, default=0.0)
        if icc_prox > 0:
            ok = icc_prox * 1e3 >= rec
            check(f"Pickup {cod} x faltas próximas", "Icc mín. em faltas ≤ 50% da LT ≥ pickup", icc_prox * 1e3, rec, ok,
                  "O elemento instantâneo deve enxergar as faltas próximas ao terminal")
        else:
            alertas.append(f"Função {cod}: sem casos de curto em ≤ 50% da LT; não foi possível verificar a cobertura do "
                           "elemento instantâneo.")
        if not ok:
            alertas.append(f"Função {cod}: o pickup instantâneo ({fmt(rec,0)} A) supera a menor corrente de falta próxima "
                           f"({fmt(icc_prox*1e3,0)} A). O elemento não cobrirá toda a zona próxima; avaliar desabilitar o {cod} "
                           "ou usar proteção de distância/diferencial.")
        add(funcao, "Pickup", nm, rec / rtc, "A sec", rec, "A pri",
            f"{fmt(cc['k_inst'],2)}·Icc na barra remota", "OK" if ok else "REVISAR")
        if d.get("modo") == "conferencia":
            linha_conf(f"Pickup {cod} (A sec)", ex_pk, p_min / rtc, None, "A", "Mínimo: k_inst·Icc remota")
        return {"neutro": neutro, "calculado": True, "min_pri": p_min, "rec_pri": rec, "rec_sec": rec / rtc,
                "icc_rem_ka": icc_rem, "icc_prox_ka": icc_prox, "viavel": ok}

    # ordem fixa: 50, 51, 50N, 51N
    saida["i_ref"] = i_ref
    if incluir_base:                     # sem 21/68, o bloco "Base" do cálculo de distância não existe
        rtp = float(d["rtp"])
        vn = float(d["vn_kv"])
        s_max = float(d.get("s_max_mva") or 0.0)
        i_term = float(d.get("i_term_a") or 0.0)
        passo("Base", "Relação de conversão primário/secundário", r"k_{s} = \frac{RTC}{RTP}",
              rf"k_{{s}} = \frac{{{fmt_eq(rtc,1)}}}{{{fmt_eq(rtp,1)}}} = {fmt_eq(rtc/rtp,4)}")
        passo("Corrente de referência", "Corrente de referência de carga",
              r"I_{ref} = \max\left( \frac{S_{max}}{\sqrt{3} \cdot V_{n}},\ I_{term} \right)",
              rf"I_{{ref}} = \max\left( \frac{{{fmt_eq(s_max,1)}\ \mathrm{{MVA}}}}{{\sqrt{{3}} \cdot {fmt_eq(vn,1)}\ \mathrm{{kV}}}},\ "
              rf"{fmt_eq(i_term,0)}\ \mathrm{{A}} \right) = {fmt_eq(i_ref,1)}\ \mathrm{{A}}")
    if "50" in sel:
        saida["p50"] = instantanea("50", False)
    if "51" in sel:
        saida["p51"] = temporizada("51", False)
    if "50N" in sel:
        saida["p50n"] = instantanea("50N", True)
    if "51N" in sel:
        saida["p51n"] = temporizada("51N", True)
    return {"passos": passos, "verif": verif, "alertas": alertas, "ajustes": aj, "conferencia": conf, "dados": saida}
