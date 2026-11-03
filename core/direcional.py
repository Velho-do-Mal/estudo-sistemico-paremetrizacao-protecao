"""Funções direcionais de sobrecorrente: 67 (fase) e 67N (neutro/residual).

Princípio (IEEE C37.113; guias Basler, GE D60, Protecta TOC67N, SEL): o relé decide o sentido da falta pelo
ângulo entre a corrente de operação e uma grandeza de polarização. O elemento opera quando esse ângulo está
dentro do semiplano  MTA ± ROA  (ROA = 90° para o semiplano clássico).

  67N  (polarização por 3V0):   Δ = ∠3I0 − ∠(−3V0).
        Em falta à frente, −V0 = I0·Z0s (Z0s = impedância de sequência zero atrás do relé), logo a corrente
        ATRASA −V0 do ângulo de Z0s: MTA = −Δ_frente.   Região de operação:  |Δ + MTA| < ROA.
  67   (polarização em quadratura, conexão 90°):  Ia com Vbc, Ib com Vca, Ic com Vab.
        Em falta à frente Ia = I∠(∠Va − φ) e ∠Vbc = ∠Va − 90°, logo  MTA = φ = ∠Vpol + 90° − ∠I.
        Região de operação:  |∠I − (∠Vpol + 90° − MTA)| < ROA.   O elemento avaliado é o da fase de maior corrente.

O MTA é calculado a partir dos fasores de falta importados (média circular dos casos à frente, arredondada ao passo);
sem fasores, usa-se o ângulo da impedância da LT como estimativa, com alerta.
Limiares de polarização: assimetria de regime < limiar < menor valor observado em falta (Protecta/GE).
Pickup e curva seguem o critério das funções 51/51N, considerando só as faltas à frente.

Premissas: sequência de fases A-B-C; corrente positiva saindo da barra do relé para a linha; V em kV fase-neutro.
Polarização por sequência negativa (V2/I2), memória de tensão e elemento instantâneo direcional ficam para a próxima etapa.
"""
from __future__ import annotations

import math

from core import f_sobrecorrente as SC
from core import fasores as FS

CRITERIOS_DIRECIONAL = {
    "roa_dir": 90.0,          # semiplano de operação: MTA ± ROA
    "margem_ang_dir": 15.0,   # margem angular até a fronteira (à frente dentro; à ré fora)
    "passo_mta": 5.0,         # arredondamento do MTA (graus)
    "assim_v0_pu": 0.02,      # |3V0| de assimetria em regime, fração da tensão fase-neutro nominal
    "k_pol": 1.25,            # margem sobre a assimetria para o limiar de polarização
    "k_sens_pol": 1.50,       # menor valor observado em falta / limiar >= k
    "v_pol_min_pu": 0.02,     # |Vquadratura| mínimo aceitável (fração da tensão nominal fase-fase)
}


def _arred(x: float, passo: float) -> float:
    return round(x / passo) * passo if passo > 0 else x


def _sentido(caso: dict) -> str | None:
    s = caso.get("sentido")
    if s in ("frente", "re"):
        return s
    loc = caso.get("local_pct")
    try:
        loc = float(loc)
    except (TypeError, ValueError):
        return None
    return "re" if loc < 0 else "frente"


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    from core.calc import fmt, fmt_eq      # import tardio: evita ciclo calc <-> módulo

    cd = dict(CRITERIOS_DIRECIONAL)
    cd.update({k: c[k] for k in CRITERIOS_DIRECIONAL if k in c})
    cs = dict(SC.CRITERIOS_SOBRECORRENTE)
    cs.update({k: c[k] for k in SC.CRITERIOS_SOBRECORRENTE if k in c})
    rtc, rtp = float(d["rtc"]), float(d["rtp"])
    if rtc <= 0 or rtp <= 0:
        raise ValueError("RTC e RTP devem ser maiores que zero.")
    vn = float(d["vn_kv"])
    v_fn = vn / math.sqrt(3.0)                                   # kV fase-neutro nominal
    i_ref = SC.corrente_referencia(d, c)
    if i_ref <= 0:
        raise ValueError("Informe o fluxo máximo (MVA) ou o limite térmico (A) para as funções direcionais.")

    passos, verif, alertas, aj, conf = [], [], [], [], []
    dados: dict = {}

    def passo(secao, titulo, simb, num, nota=""):
        passos.append({"secao": secao, "titulo": titulo, "simb": simb, "num": num, "nota": nota})

    def check(item, criterio, valor, limite, ok, nota=""):
        verif.append({"item": item, "criterio": criterio, "valor": valor, "limite": limite,
                      "status": "OK" if ok else "FALHA", "nota": nota})

    def add(funcao, param, vsec, usec, vpri, upri, criterio, status="OK", nome="—"):
        aj.append({"funcao": funcao, "parametro": param, "nome_rele": nome, "valor_sec": vsec, "unid_sec": usec,
                   "valor_pri": vpri, "unid_pri": upri, "criterio": criterio, "item_carta": "", "status": status})

    if incluir_base:
        passo("Base", "Relação de conversão primário/secundário", r"k_{s} = \frac{RTC}{RTP}",
              rf"k_{{s}} = \frac{{{fmt_eq(rtc,1)}}}{{{fmt_eq(rtp,1)}}} = {fmt_eq(rtc/rtp,4)}")
        passo("Corrente de referência", "Corrente de referência de carga",
              r"I_{ref} = \max\left( \frac{S_{max}}{\sqrt{3} \cdot V_{n}},\ I_{term} \right)",
              rf"I_{{ref}} = \max\left( \frac{{{fmt_eq(float(d.get('s_max_mva') or 0),1)}\ \mathrm{{MVA}}}}"
              rf"{{\sqrt{{3}} \cdot {fmt_eq(vn,1)}\ \mathrm{{kV}}}},\ {fmt_eq(float(d.get('i_term_a') or 0),0)}\ \mathrm{{A}} \right) "
              rf"= {fmt_eq(i_ref,1)}\ \mathrm{{A}}")

    # ------------------------------------------------------------------ casos com fasores
    todos = []
    for cs_ in casos or []:
        f = FS.fasores_do_caso(cs_)
        todos.append((cs_, f, _sentido(cs_)))
    sem_sentido = sum(1 for cs_, f, s in todos if f is not None and s is None)
    if sem_sentido:
        alertas.append(f"{sem_sentido} caso(s) com fasores não têm o sentido (frente/ré) e foram ignorados na verificação direcional.")

    def _icc(tipos, so_frente=True, remoto=False):
        vals = []
        for cs_, _, s in todos:
            if str(cs_.get("tipo", "")).upper() not in tipos or not (cs_.get("icc_ka") or 0) > 0:
                continue
            if so_frente and s == "re":
                continue
            if remoto:
                try:
                    if float(cs_.get("local_pct")) < 99.5:
                        continue
                except (TypeError, ValueError):
                    continue
            vals.append(float(cs_["icc_ka"]))
        return vals

    # ------------------------------------------------------------------ cálculo por função
    def funcao_direcional(cod: str, neutro: bool):
        sec = f"Função {cod}"
        rotulo = f"{cod} — Sobrecorrente direcional {'de neutro' if neutro else 'de fase'}"
        tipos_ang = ("FT", "FFT") if neutro else ("3F", "FF", "FFT", "FT")
        linhas = []                          # um dicionário por caso avaliado
        for cs_, f, s in todos:
            if f is None or s is None or str(cs_.get("tipo", "")).upper() not in tipos_ang:
                continue
            if neutro:
                i_op = f["Ia"] + f["Ib"] + f["Ic"]                  # 3I0
                v_ref = f["Va"] + f["Vb"] + f["Vc"]                 # 3V0
                if abs(i_op) < 1e-9 or abs(v_ref) < 1e-9:
                    continue
                delta = FS.ang_dif(FS.pol(i_op)[1], FS.pol(-v_ref)[1])
                lag = -delta
                mod_i, mod_v = abs(i_op), abs(v_ref)
                fase = "—"
            else:
                fase = max("ABC", key=lambda x: abs(f[f"I{x.lower()}"]))
                i_op = f[f"I{fase.lower()}"]
                v_ref = FS.tensao_quadratura(f, fase)
                if abs(i_op) < 1e-9 or abs(v_ref) < 1e-9:
                    continue
                lag = FS.norm180(FS.pol(v_ref)[1] + 90.0 - FS.pol(i_op)[1])
                delta = None
                mod_i, mod_v = abs(i_op), abs(v_ref)
            linhas.append({"caso": cs_.get("ponto", ""), "tipo": cs_.get("tipo", ""), "sentido": s, "fase": fase,
                           "i_mod": mod_i, "v_mod": mod_v, "i_ang": FS.pol(i_op)[1], "v_ang": FS.pol(v_ref)[1],
                           "lag": lag, "delta": delta})
        frente = [x for x in linhas if x["sentido"] == "frente"]
        re_ = [x for x in linhas if x["sentido"] == "re"]

        # ---- MTA
        mta_man = float(d.get("mta67n_man" if neutro else "mta67_man") or 0.0)
        mta_dados = FS.media_circular([x["lag"] for x in frente])
        if mta_man:
            mta, origem = mta_man, "informado pelo usuário"
        elif mta_dados is not None:
            mta, origem = _arred(mta_dados, cd["passo_mta"]), "média dos casos à frente"
        else:
            r_, x_ = (float(d.get("r0") or 0), float(d.get("x0") or 0)) if neutro else (float(d.get("r1") or 0), float(d.get("x1") or 0))
            if r_ or x_:
                mta, origem = _arred(math.degrees(math.atan2(x_, r_)), cd["passo_mta"]), "ângulo da impedância da LT (estimativa)"
            else:
                mta, origem = 75.0, "valor típico 75° (estimativa)"
            alertas.append(f"Função {cod}: sem fasores de falta à frente; MTA estimado ({origem}). Importe/digite os fasores "
                           "(corrente e tensão no terminal do relé) para calculá-lo e verificar a direção.")
        mta = FS.norm180(mta)
        roa, margem = cd["roa_dir"], cd["margem_ang_dir"]
        mta_atipico = not (0.0 <= mta <= 90.0)
        if mta_atipico:
            alertas.append(f"Função {cod}: MTA = {fmt(mta,0)}° fora do intervalo esperado para linhas (0° a 90°). Verifique se o sentido da "
                           "corrente importada está invertido (marque 'inverter sentido' na importação) e a polaridade dos TCs/TPs.")

        # ---- memória de cálculo
        if linhas:
            ex = (frente or linhas)[0]
            if neutro:
                passo(sec, "Grandezas de operação e de polarização",
                      r"3I_{0} = I_{a} + I_{b} + I_{c} \qquad 3V_{0} = V_{a} + V_{b} + V_{c} \qquad \Delta = \angle 3I_{0} - \angle \left( -3V_{0} \right)",
                      rf"\Delta = {fmt_eq(ex['i_ang'],1)}^{{\circ}} - ({fmt_eq(FS.norm180(ex['v_ang'] + 180.0),1)}^{{\circ}}) = {fmt_eq(ex['delta'],1)}^{{\circ}}",
                      f"Caso de exemplo: {ex['caso']} ({ex['tipo']}, {'à frente' if ex['sentido']=='frente' else 'à ré'}).")
                passo(sec, "Ângulo de máximo torque (MTA)",
                      r"MTA = -\Delta_{med,frente} = \angle Z_{0s} \qquad \left| \Delta + MTA \right| < ROA",
                      rf"MTA = {fmt_eq(mta,1)}^{{\circ}}\ \ ({origem}) \qquad ROA = {fmt_eq(roa,0)}^{{\circ}}")
            else:
                passo(sec, "Grandezas de operação e de polarização (conexão 90°)",
                      r"V_{pol,A} = V_{b} - V_{c} \qquad MTA = \angle V_{pol} + 90^{\circ} - \angle I",
                      rf"MTA = {fmt_eq(ex['v_ang'],1)}^{{\circ}} + 90^{{\circ}} - ({fmt_eq(ex['i_ang'],1)}^{{\circ}}) = {fmt_eq(ex['lag'],1)}^{{\circ}}",
                      f"Caso de exemplo: {ex['caso']} ({ex['tipo']}, fase {ex['fase']}).")
                passo(sec, "Região de operação",
                      r"\left| \angle I - \left( \angle V_{pol} + 90^{\circ} - MTA \right) \right| < ROA",
                      rf"MTA = {fmt_eq(mta,1)}^{{\circ}}\ \ ({origem}) \qquad ROA = {fmt_eq(roa,0)}^{{\circ}}")

        # ---- verificação por caso
        casos_out, falhas = [], 0
        for x in linhas:
            desvio = FS.norm180(x["delta"] + mta) if neutro else FS.norm180(x["i_ang"] - (x["v_ang"] + 90.0 - mta))
            dentro = abs(desvio) < roa
            if x["sentido"] == "frente":
                ok = abs(desvio) <= roa - margem
                folga = roa - abs(desvio)
            else:
                ok = abs(desvio) >= roa + margem
                folga = abs(desvio) - roa
            falhas += 0 if ok else 1
            casos_out.append({**x, "desvio": desvio, "dentro_regiao": dentro, "folga": folga, "ok": ok})
        if casos_out:
            n_f = sum(1 for x in casos_out if x["sentido"] == "frente")
            n_r = len(casos_out) - n_f
            check(f"Direção {cod} — faltas à frente", f"|desvio| ≤ ROA − {fmt(margem,0)}°",
                  sum(1 for x in casos_out if x["sentido"] == "frente" and x["ok"]), n_f,
                  all(x["ok"] for x in casos_out if x["sentido"] == "frente"), "Casos que operam com margem / total")
            if n_r:
                check(f"Direção {cod} — faltas à ré", f"|desvio| ≥ ROA + {fmt(margem,0)}°",
                      sum(1 for x in casos_out if x["sentido"] == "re" and x["ok"]), n_r,
                      all(x["ok"] for x in casos_out if x["sentido"] == "re"), "Casos que restringem com margem / total")
            else:
                alertas.append(f"Função {cod}: sem falta à ré (atrás do relé); a restrição direcional não foi verificada.")
            if falhas:
                alertas.append(f"Função {cod}: {falhas} caso(s) sem a margem angular de {fmt(margem,0)}°; rever o MTA "
                               "(ou o sentido da corrente importada) e conferir a polaridade dos TCs/TPs.")

        # ---- limiares de polarização
        status_pol = "OK"
        if neutro:
            v_pu = math.ceil(cd["k_pol"] * cd["assim_v0_pu"] / 0.005 - 1e-9) * 0.005
            v_kv = v_pu * v_fn
            v_sec = v_kv * 1e3 / rtp
            passo(sec, "Tensão mínima de polarização (3V0)",
                  r"V_{0,min} = k_{pol} \cdot a_{3V0} \cdot V_{fn}",
                  rf"V_{{0,min}} = {fmt_eq(cd['k_pol'])} \cdot {fmt_eq(cd['assim_v0_pu'],3)} \cdot {fmt_eq(v_fn,2)}\ \mathrm{{kV}} "
                  rf"\rightarrow {fmt_eq(v_kv,2)}\ \mathrm{{kV}} = {fmt_eq(v_sec,1)}\ \mathrm{{V\ sec}}")
            i_pol = math.ceil(cd["k_pol"] * cs["k_desb"] * i_ref / cs["passo_pickup_a"] - 1e-9) * cs["passo_pickup_a"]
            passo(sec, "Corrente residual mínima de polarização (3I0)",
                  r"I_{0,min} = k_{pol} \cdot k_{d} \cdot I_{ref}",
                  rf"I_{{0,min}} = {fmt_eq(cd['k_pol'])} \cdot {fmt_eq(cs['k_desb'])} \cdot {fmt_eq(i_ref,1)} \rightarrow {fmt_eq(i_pol,0)}\ \mathrm{{A}} "
                  rf"= {fmt_eq(i_pol/rtc,2)}\ \mathrm{{A\ sec}}")
            vmin_obs = min((x["v_mod"] for x in frente), default=0.0)
            imin_obs = min((x["i_mod"] for x in frente), default=0.0) * 1e3
            if frente:
                ok_v = vmin_obs >= cd["k_sens_pol"] * v_kv
                ok_i = imin_obs >= cd["k_sens_pol"] * i_pol
                check(f"3V0 mínimo {cod}", f"3V0 obs. ≥ {fmt(cd['k_sens_pol'],2)}·V0,min (kV)", vmin_obs, cd["k_sens_pol"] * v_kv, ok_v)
                check(f"3I0 mínimo {cod}", f"3I0 obs. ≥ {fmt(cd['k_sens_pol'],2)}·I0,min (A)", imin_obs, cd["k_sens_pol"] * i_pol, ok_i)
                if not (ok_v and ok_i):
                    status_pol = "REVISAR"
                    alertas.append(f"Função {cod}: o menor 3V0/3I0 observado nas faltas à frente não tem folga sobre os limiares de "
                                   "polarização (falta de alta resistência?). Avaliar polarização por corrente ou por sequência negativa.")
            add(rotulo, "Tensão mínima de polarização (3V0)", v_sec, "V sec", v_kv, "kV pri",
                f"{fmt(cd['k_pol'],2)}·{fmt(cd['assim_v0_pu']*100,1)}% de Vfn (assimetria de regime)", status_pol)
            add(rotulo, "Corrente residual mínima de polarização (3I0)", i_pol / rtc, "A sec", i_pol, "A pri",
                f"{fmt(cd['k_pol'],2)}·{fmt(cs['k_desb'],2)}·Iref", status_pol)
            piso_pickup = max(cs["k_desb"] * i_ref, i_pol)
        else:
            vpol_min_obs = min((x["v_mod"] for x in frente), default=None)
            v_ll_min = cd["v_pol_min_pu"] * vn
            ok_vp = True
            if vpol_min_obs is not None:
                ok_vp = vpol_min_obs >= v_ll_min
                check(f"Vquadratura mínima {cod}", f"|Vpol| obs. ≥ {fmt(cd['v_pol_min_pu']*100,1)}% de Vn (kV)",
                      vpol_min_obs, v_ll_min, ok_vp)
                if not ok_vp:
                    alertas.append(f"Função {cod}: a tensão de quadratura caiu abaixo de {fmt(cd['v_pol_min_pu']*100,1)}% de Vn em falta à "
                                   "frente (falta trifásica próxima); habilitar polarização por memória de tensão no relé.")
            add(rotulo, "Tensão de polarização mínima (informativo)", v_ll_min * 1e3 / rtp, "V sec", v_ll_min, "kV pri",
                f"{fmt(cd['v_pol_min_pu']*100,1)}% de Vn; abaixo disso usar memória de tensão", "OK" if ok_vp else "REVISAR")
            piso_pickup = c["k_pickup_min"] * i_ref
            status_pol = "OK" if ok_vp else "REVISAR"

        # ---- parâmetros direcionais no quadro de ajustes
        st_dir = "REVISAR" if (falhas or not linhas or mta_atipico) else "OK"
        add(rotulo, "Ângulo de máximo torque (MTA)", mta, "graus", mta, "graus",
            f"{origem}; mapear para o parâmetro do relé (RCA/ECA/MTA — conferir convenção do firmware)", st_dir)
        add(rotulo, "Semiplano de operação (ROA)", roa, "graus", roa, "graus", "Semiplano clássico ±90° em torno do MTA", "OK")

        # ---- pickup, curva e TMS (apenas faltas à frente)
        tipos_icc = ("FT", "FFT") if neutro else ("3F", "FF", "FFT")
        icc_min = min(_icc(tipos_icc), default=0.0)
        icc_coord = max(_icc(tipos_icc, remoto=True), default=0.0)
        k_sens = cs["k_sens_51n"] if neutro else c["k_sens_51"]
        p_min = piso_pickup
        p_max = (icc_min * 1e3) / k_sens if icc_min > 0 else 0.0
        rec = SC._sobe(p_min, cs["passo_pickup_a"])
        viavel = p_max == 0 or rec <= p_max
        if neutro:
            simb = (r"\max\left( k_{d} \cdot I_{ref},\ I_{0,min} \right) \le I_{pk} \le \frac{I_{cc,FT,min}}{k_{s51N}}")
            num = (rf"\max\left( {fmt_eq(cs['k_desb'])} \cdot {fmt_eq(i_ref,1)},\ {fmt_eq(i_pol,0)} \right) = {fmt_eq(p_min,0)}\ \mathrm{{A}} \le I_{{pk}} \le ")
        else:
            simb = r"k_{p} \cdot I_{ref} \le I_{pk} \le \frac{I_{cc,min}}{k_{s51}}"
            num = rf"{fmt_eq(c['k_pickup_min'])} \cdot {fmt_eq(i_ref,1)} = {fmt_eq(p_min,0)}\ \mathrm{{A}} \le I_{{pk}} \le "
        num += (rf"\frac{{{fmt_eq(icc_min*1e3,0)}}}{{{fmt_eq(k_sens)}}} = {fmt_eq(p_max,0)}\ \mathrm{{A}}" if icc_min > 0 else r"(Icc mínima à frente não informada)")
        passo(sec, "Faixa admissível do pickup (faltas à frente)", simb, num)
        if icc_min == 0:
            alertas.append(f"Função {cod}: sem casos de curto {'fase-terra' if neutro else 'de fase'} à frente; o limite superior do pickup não foi verificado.")
        check(f"Pickup {cod} recomendado", f"Faixa do pickup à frente (k = {fmt(k_sens,2)})", rec, p_max if p_max else "—", viavel)
        curva = d.get("curva67n" if neutro else "curva67") or "IEC NI"
        curva = curva if curva in SC.CURVAS else "IEC NI"
        t_jus = float(d.get("t_jus_67n_s" if neutro else "t_jus_67_s") or 0.0)
        k_c, a_c, desc, c_sel = SC.CURVAS[curva]
        tms = t_op = None
        status_tms = "OK"
        crit_tms = f"{desc}; informe o tempo do dispositivo a jusante"
        if icc_coord > 0 and t_jus > 0:
            m = icc_coord * 1e3 / rec
            t_alvo = t_jus + cs["dt_coord"]
            tc = SC.tms_para(curva, t_alvo, m)
            if tc is not None:
                tms = SC._sobe(max(tc, 0.0), cs["passo_tms"])
                fora = tms < cs["tms_min"] - 1e-9 or tms > cs["tms_max"] + 1e-9
                tms = min(max(tms, cs["tms_min"]), cs["tms_max"])
                t_op = SC.tempo_iec(curva, tms, m)
                passo(sec, "Curva e multiplicador de tempo (TMS)",
                      r"M = \frac{I_{cc,coord}}{I_{pk}} \qquad t_{alvo} = t_{jus} + \Delta t \qquad TMS = t_{alvo} \cdot \frac{M^{\alpha} - 1}{k}",
                      rf"M = \frac{{{fmt_eq(icc_coord*1e3,0)}}}{{{fmt_eq(rec,0)}}} = {fmt_eq(m,2)} \qquad t_{{alvo}} = {fmt_eq(t_jus)} + {fmt_eq(cs['dt_coord'])} = "
                      rf"{fmt_eq(t_alvo)}\ \mathrm{{s}} \qquad TMS = {fmt_eq(t_alvo)} \cdot \frac{{{fmt_eq(m,2)}^{{{fmt_eq(a_c,2)}}} - 1}}{{{fmt_eq(k_c,2)}}} = {fmt_eq(tms,2)}",
                      f"Curva {curva} (k = {fmt(k_c,2)}; α = {fmt(a_c,2)}). Atuação resultante em {fmt(icc_coord,2)} kA: {fmt(t_op,3)} s.")
                crit_tms = f"{desc}; atua em {fmt(t_op,2)} s na falta remota (t_jus {fmt(t_jus,2)} s + Δt {fmt(cs['dt_coord'],2)} s)"
                check(f"TMS {cod}", "TMS dentro da faixa do relé", tms, f"{cs['tms_min']}–{cs['tms_max']}", not fora)
                if fora:
                    status_tms = "REVISAR"
                    alertas.append(f"TMS da função {cod} fora da faixa {cs['tms_min']}–{cs['tms_max']}; trocar a curva ou rever o tempo a jusante.")
        else:
            falta = []
            if icc_coord <= 0:
                falta.append("falta a 100% da LT à frente")
            if t_jus <= 0:
                falta.append("tempo do dispositivo a jusante")
            alertas.append(f"TMS da função {cod} não calculado: informe {' e '.join(falta)}.")
            status_tms = "REVISAR"
        add(rotulo, "Pickup", rec / rtc, "A sec", rec, "A pri",
            f"{'max(k_d·Iref; I0,min)' if neutro else fmt(c['k_pickup_min'],2) + '·Iref'} ≤ Ipk ≤ Icc,min/{fmt(k_sens,2)}",
            "OK" if viavel else "REVISAR")
        add(rotulo, "Curva", curva, "—", curva, "—", f"Curva escolhida (SEL: {c_sel}, conferir)")
        add(rotulo, "Multiplicador de tempo (TMS)", tms if tms is not None else "n/d", "—",
            tms if tms is not None else "n/d", "—", crit_tms, status_tms)

        # ---- conferência de ajustes existentes
        if d.get("modo") == "conferencia":
            ex_pk = float(d.get("ex_pickup67n_a_sec" if neutro else "ex_pickup67_a_sec") or 0.0)
            ex_mta = float(d.get("ex_mta67n" if neutro else "ex_mta67") or 0.0)
            for item, ex, mn, mx, un, nota in (
                    (f"Pickup {cod} (A sec)", ex_pk, p_min / rtc, (p_max / rtc) if p_max else None, "A", "Faixa do pickup à frente"),
                    (f"MTA {cod} (graus)", ex_mta, mta - 15.0, mta + 15.0, "graus", "Tolerância ±15° em torno do MTA calculado")):
                if not ex:
                    conf.append({"item": item, "existente": "não informado", "minimo": mn, "maximo": mx, "unid": un,
                                 "status": "SEM DADO", "nota": nota})
                else:
                    ok = (mn is None or ex >= mn - 1e-9) and (mx is None or ex <= mx + 1e-9)
                    conf.append({"item": item, "existente": ex, "minimo": mn, "maximo": mx, "unid": un,
                                 "status": "CONFORME" if ok else "NÃO CONFORME", "nota": nota})
        return {"neutro": neutro, "mta": mta, "mta_origem": origem, "roa": roa, "margem": margem, "casos": casos_out,
                "n_frente": len(frente), "n_re": len(re_), "min_pri": p_min, "max_pri": p_max, "rec_pri": rec,
                "rec_sec": rec / rtc, "viavel": viavel, "curva": curva, "tms": tms, "t_op_s": t_op,
                "icc_coord_ka": icc_coord, "t_jus_s": t_jus, "dt_coord_s": cs["dt_coord"],
                "icc_min_fase_ka": icc_min if not neutro else 0.0, "icc_min_terra_ka": icc_min if neutro else 0.0,
                "i_ref": i_ref, "mta_atipico": mta_atipico}

    dados["i_ref"] = i_ref
    if "67" in sel:
        dados["p67"] = funcao_direcional("67", False)
    if "67N" in sel:
        dados["p67n"] = funcao_direcional("67N", True)
    return {"passos": passos, "verif": verif, "alertas": alertas, "ajustes": aj, "conferencia": conf, "dados": dados}
