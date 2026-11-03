"""Funções de disjuntor: 50BF (falha de disjuntor), 79 (religamento automático) e 25 (verificação de sincronismo).

Critérios (valores padrão editáveis na etapa 4; devem ser alinhados à norma técnica/critério do cliente):
  * 50BF: t_BF = t_disjuntor + t_rearme + margem;  t_total = t_proteção + t_BF + t_disjuntor_retaguarda ≤ t_crítico;
          pickup: acima do mínimo de detecção/ruído e abaixo de Icc,min / k_sens.
  * 79  : tempo morto ≥ tempo de deionização (10,5 + Vn/34,5 ciclos) + diferença de abertura dos terminais + margem;
          monopolar: tempo de extinção do arco secundário; reclaim ≥ recarga do mecanismo + tempo morto.
  * 25  : limites de ΔV, Δf e Δφ; Δφ de ajuste = Δφ máx − 360·Δf·t_fechamento (compensa o tempo de fechamento).
"""
from __future__ import annotations

import math

from core.base_modulo import Ctx, cfg, num, sobe
from core.modulos import E, K

COD = ("50BF", "79", "25")
TITULO = "Disjuntor (50BF / 79 / 25)"
G = "Disjuntor (50BF / 79 / 25)"
MODOS_79 = ["Monopolar", "Tripolar", "Monopolar e tripolar"]

ENTRADAS = [
    E("in_sec_a", "Corrente nominal secundária do TC (A)", 1.0, ("50BF",), G,
      "Base do pickup mínimo do detector de corrente do 50BF (fração da corrente nominal do relé).",
      "Escolha 1 A ou 5 A conforme o secundário do TC e a entrada de corrente do relé.",
      "Folha de dados do TC; projeto executivo; ajuste atual do relé (CTR / In).", tipo="sel", opcoes=[1.0, 5.0]),
    E("t_prot_ms", "Tempo da proteção principal até o trip (ms)", 20.0, ("50BF",), G,
      "Entra no tempo total de eliminação da falta com falha de disjuntor.",
      "Tempo de operação do relé principal mais saída/relé auxiliar, em ms.",
      "Ensaios/folha de dados do relé; estudo de coordenação.", mn=0.0, mx=2000.0, passo=1.0, fmt="%.0f"),
    E("t_disj_ms", "Tempo de interrupção do disjuntor (ms)", 50.0, ("50BF",), G,
      "O temporizador do 50BF precisa esperar o disjuntor abrir antes de acionar a retaguarda.",
      "Tempo total de interrupção (abertura + extinção do arco), em ms. Disjuntores de AT: tipicamente 2 a 3 ciclos.",
      "Folha de dados/ensaios do fabricante do disjuntor.", mn=1.0, mx=500.0, passo=1.0, fmt="%.0f"),
    E("t_rearme_bf_ms", "Tempo de rearme do detector de corrente (ms)", 20.0, ("50BF",), G,
      "Tempo que o detector leva para cair após a interrupção da corrente (inclui decaimento da componente CC no TC).",
      "Em ms; considere o pior caso (saturação/CC no TC).", "Manual do relé; ensaios.", mn=0.0, mx=500.0, passo=1.0, fmt="%.0f"),
    E("t_crit_ms", "Tempo crítico de eliminação de falta (ms; 0 = não informado)", 0.0, ("50BF",), G,
      "Limite de estabilidade: o tempo total (proteção + 50BF + retaguarda) não pode superá-lo.",
      "Tempo máximo, em ms, que a falta pode permanecer sem perda de sincronismo. 0 = não informado (não verifica).",
      "Estudo de estabilidade eletromecânica (ANATEM) / documentos técnicos do cliente.", mn=0.0, mx=5000.0, passo=10.0, fmt="%.0f"),
    E("i_resid_a", "Corrente residual máx. com o disjuntor aberto (A pri; 0 = não informado)", 0.0, ("50BF",), G,
      "O pickup do 50BF deve ficar acima de correntes que persistem com o disjuntor aberto (carga capacitiva, indução).",
      "Maior corrente primária medida/estimada com o disjuntor aberto. 0 = não informado.",
      "Estudo de regime/capacitiva da LT; medições em campo.", mn=0.0, mx=1e5, passo=1.0, fmt="%.0f"),
    E("modo_79", "Modo de religamento", "Monopolar", ("79",), G,
      "Define quais tempos mortos são calculados. Linhas de AT costumam religar monopolar em faltas fase-terra.",
      "Escolha Monopolar, Tripolar ou ambos, conforme a documentos técnicos do cliente e os disjuntores (comando por polo).",
      "Filosofia de proteção do cliente; especificação do disjuntor (acionamento por polo).", tipo="sel", opcoes=MODOS_79),
    E("t_recarga_s", "Tempo de recarga do mecanismo do disjuntor (s)", 10.0, ("79",), G,
      "O tempo de reclaim (rearme do 79) precisa superar a recarga do mecanismo do disjuntor.",
      "Tempo que o mecanismo leva para ficar apto a nova operação O–CO.",
      "Folha de dados do disjuntor (ciclo nominal de operação, ex.: O–0,3 s–CO–3 min–CO).", mn=0.0, mx=300.0, passo=1.0, fmt="%.1f"),
    E("t_dif_remoto_ms", "Diferença de abertura entre os terminais da LT (ms)", 50.0, ("79",), G,
      "Se um terminal abre depois do outro, o arco só começa a extinguir após o último abrir: soma-se ao tempo morto.",
      "Maior diferença esperada entre os trips dos dois terminais (zona 2 / teleproteção), em ms.",
      "Estudo de coordenação/teleproteção; esquema de comunicação.", mn=0.0, mx=2000.0, passo=10.0, fmt="%.0f"),
    E("t_arco_sec_ms", "Tempo de extinção do arco secundário (ms; 0 = usar mínimo do critério)", 0.0, ("79",), G,
      "No religamento monopolar o arco secundário é mantido por acoplamento com as fases sãs; religar antes dele extinguir reacende a falta.",
      "Em ms, a partir de cálculo/estudo para a LT. 0 = o app usa o tempo morto monopolar mínimo do critério.",
      "Estudo de arco secundário (EMTP/ATP) da LT; transposição, compensação shunt e comprimento da LT.",
      mn=0.0, mx=5000.0, passo=10.0, fmt="%.0f"),
    E("t_max_estab_s", "Tempo morto máximo por estabilidade (s; 0 = não informado)", 0.0, ("79",), G,
      "Tempo morto longo demais pode perder sincronismo; este é o teto.",
      "Em segundos. 0 = não informado (não verifica).", "Estudo de estabilidade / documentos técnicos do cliente.", mn=0.0, mx=10.0, passo=0.1, fmt="%.2f"),
    E("t_fech_ms", "Tempo de fechamento do disjuntor (ms)", 60.0, ("25",), G,
      "Compensa o avanço angular que ocorre entre a ordem de fechamento e o fechamento efetivo.",
      "Tempo entre a ordem de fechar e o toque dos contatos, em ms.", "Folha de dados/ensaios do disjuntor.",
      mn=0.0, mx=500.0, passo=1.0, fmt="%.0f"),
    E("comp_ang_25_deg", "Defasagem fixa entre as tensões comparadas (°)", 0.0, ("25",), G,
      "Corrige o ângulo quando as tensões vêm de lados com defasagem (ex.: TP após transformador Dy).",
      "Em graus (0 se as duas tensões são da mesma referência).", "Grupo de ligação do transformador; esquema de TPs do projeto.",
      mn=-180.0, mx=180.0, passo=1.0, fmt="%.0f"),
    # ---- conferência
    E("ex_50bf_pk_a_sec", "50BF — pickup existente (A sec)", 0.0, ("50BF",), G, "Compara com o ajuste atual.", "Valor lido no relé.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=100.0, passo=0.01, conf=True),
    E("ex_50bf_t_ms", "50BF — temporizador existente (ms)", 0.0, ("50BF",), G, "Compara com o ajuste atual.", "ms.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=5000.0, passo=1.0, fmt="%.0f", conf=True),
    E("ex_79_t1p_s", "79 — tempo morto monopolar existente (s)", 0.0, ("79",), G, "Compara com o ajuste atual.", "s.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=60.0, passo=0.05, conf=True),
    E("ex_79_t3p_s", "79 — tempo morto tripolar existente (s)", 0.0, ("79",), G, "Compara com o ajuste atual.", "s.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=60.0, passo=0.05, conf=True),
    E("ex_79_reclaim_s", "79 — tempo de reclaim existente (s)", 0.0, ("79",), G, "Compara com o ajuste atual.", "s.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=600.0, passo=0.5, conf=True),
    E("ex_25_dang_deg", "25 — ângulo máximo existente (°)", 0.0, ("25",), G, "Compara com o ajuste atual.", "Graus.",
      "Arquivo de ajustes do relé.", mn=0.0, mx=180.0, passo=1.0, fmt="%.0f", conf=True),
]

CRITERIOS = [
    K("k50bf_in_frac", "50BF: pickup mínimo (fração de In)", 0.20, ("50BF",),
      "Piso de sensibilidade do detector de corrente do 50BF.", "Fração da corrente nominal secundária do relé.",
      "Manual do relé; critério do cliente.", mn=0.02, mx=1.0, passo=0.01),
    K("k50bf_resid", "50BF: margem sobre a corrente residual", 1.50, ("50BF",),
      "Evita que o 50BF fique 'preso' por corrente residual com o disjuntor aberto.", "Pickup ≥ k × corrente residual.",
      "Critério do cliente.", mn=1.0, mx=5.0, passo=0.1),
    K("k50bf_sens", "50BF: Icc mín. / pickup ≥", 2.0, ("50BF",),
      "Garante detecção da menor falta que exige a retaguarda.", "Relação entre a menor corrente de falta e o pickup.",
      "Critério do cliente.", mn=1.0, mx=10.0, passo=0.1),
    K("k50bf_passo_a", "50BF: passo do pickup (A sec)", 0.05, ("50BF",),
      "Resolução do relé.", "Passo do parâmetro no relé.", "Manual do relé.", mn=0.001, mx=1.0, passo=0.001, fmt="%.3f"),
    K("k50bf_margem_ms", "50BF: margem de segurança do temporizador (ms)", 33.0, ("50BF",),
      "Cobre incertezas de tempo do disjuntor e do detector; evita retaguarda desnecessária.", "Tipicamente 1 a 2 ciclos.",
      "IEEE C37.119; critério do cliente.", mn=0.0, mx=300.0, passo=1.0, fmt="%.0f"),
    K("k50bf_retrip_ms", "50BF: tempo de re-disparo (ms)", 0.0, ("50BF",),
      "Re-disparo do mesmo disjuntor antes da retaguarda (0 = imediato).", "Em ms; 0 a 50 ms é comum.",
      "Esquema de proteção do cliente.", mn=0.0, mx=500.0, passo=1.0, fmt="%.0f"),
    K("k50bf_passo_ms", "50BF: passo do temporizador (ms)", 1.0, ("50BF",),
      "Resolução do relé.", "Passo do parâmetro no relé.", "Manual do relé.", mn=0.1, mx=20.0, passo=0.1, fmt="%.1f"),
    K("k79_margem_ms", "79: margem sobre o tempo de deionização (ms)", 100.0, ("79",),
      "Folga de segurança para o tempo morto.", "Soma ao tempo de deionização e à diferença entre terminais.",
      "Critério do cliente.", mn=0.0, mx=2000.0, passo=10.0, fmt="%.0f"),
    K("k79_t1p_min_s", "79: tempo morto monopolar mínimo (s)", 0.50, ("79",),
      "Piso usado quando o tempo do arco secundário não é informado.", "Típico 0,5 a 1,0 s em AT.",
      "Estudo de arco secundário; prática do cliente.", mn=0.1, mx=5.0, passo=0.05),
    K("k79_reclaim_min_s", "79: tempo de reclaim mínimo (s)", 10.0, ("79",),
      "Tempo que o religador fica bloqueado após religar com sucesso, para distinguir falta nova de falta persistente.",
      "Típico 10 a 60 s.", "Critério do cliente.", mn=1.0, mx=600.0, passo=1.0, fmt="%.1f"),
    K("k79_tentativas", "79: número de tentativas", 1.0, ("79",),
      "Número de religamentos antes do bloqueio definitivo.", "Em LT de AT, geralmente 1.", "Critério do cliente.",
      mn=1.0, mx=4.0, passo=1.0, fmt="%.0f"),
    K("k79_passo_s", "79: passo dos temporizadores (s)", 0.05, ("79",),
      "Resolução do relé.", "Passo do parâmetro no relé.", "Manual do relé.", mn=0.001, mx=1.0, passo=0.001, fmt="%.3f"),
    K("k25_dv_pu", "25: diferença máxima de tensão (pu)", 0.10, ("25",),
      "Limita o degrau de tensão ao fechar.", "Típico 5 a 10 % da tensão nominal.", "Critério do cliente.",
      mn=0.01, mx=0.5, passo=0.01),
    K("k25_df_hz", "25: diferença máxima de frequência (Hz)", 0.10, ("25",),
      "Limita a velocidade de escorregamento no fechamento.", "Típico 0,05 a 0,2 Hz.", "Critério do cliente.",
      mn=0.01, mx=1.0, passo=0.01),
    K("k25_dang_deg", "25: ângulo máximo na ordem de fechamento (°)", 30.0, ("25",),
      "Limita o choque de fechamento (ângulo entre as tensões).", "Típico 20 a 30°. O app desconta o avanço do tempo de fechamento.",
      "Critério do cliente; estudo de manobra.", mn=5.0, mx=90.0, passo=1.0, fmt="%.0f"),
    K("k25_vlive_pu", "25: tensão mínima de 'vivo' (pu)", 0.80, ("25",),
      "Acima dela o lado é considerado energizado.", "Típico 0,8 pu.", "Manual do relé; critério do cliente.",
      mn=0.5, mx=1.0, passo=0.01),
    K("k25_vdead_pu", "25: tensão máxima de 'morto' (pu)", 0.30, ("25",),
      "Abaixo dela o lado é considerado desenergizado (linha viva/barra morta etc.).", "Típico 0,2 a 0,3 pu.",
      "Manual do relé; critério do cliente.", mn=0.0, mx=0.6, passo=0.01),
]

TEXTOS = {
    "50BF": {"secao": "Função 50BF",
             "metodologia": ("A falha de disjuntor aciona a retaguarda quando o disjuntor não interrompe a corrente após o trip. "
                             "O temporizador deve esperar a interrupção e o rearme do detector, com margem, e o tempo total de eliminação "
                             "(proteção principal + 50BF + abertura da retaguarda) não pode superar o tempo crítico de estabilidade. "
                             "O detector de corrente fica acima de ruído/residual e abaixo da menor falta dividida pelo fator de sensibilidade."),
             "premissas": ["Função 50BF: esquema com detector de corrente de fase e temporizador único de retaguarda, com re-disparo opcional."],
             "limitacoes": ["o 50BF foi ajustado pela cadeia de tempos informada; a lógica de iniciação (por função, por pólo) e a transferência de "
                            "disparo para os disjuntores adjacentes devem ser verificadas no projeto"]},
    "79": {"secao": "Função 79",
           "metodologia": ("O tempo morto deve superar o tempo de deionização do arco, acrescido da diferença de abertura entre os terminais e de "
                           "uma margem. Para o religamento monopolar considera-se o tempo de extinção do arco secundário. O tempo de reclaim "
                           "deve cobrir a recarga do mecanismo do disjuntor mais o tempo morto, e o tempo morto não pode exceder o limite de estabilidade."),
           "premissas": ["Função 79: tempo de deionização estimado por t = 10,5 + Vn/34,5 ciclos (Vn em kV fase-fase), fórmula clássica de aplicação."],
           "limitacoes": ["o tempo de arco secundário depende de transposição, compensação e comprimento da LT; a estimativa deve ser "
                          "substituída por estudo específico (EMTP/ATP) quando disponível"]},
    "25": {"secao": "Função 25",
           "metodologia": ("A verificação de sincronismo autoriza o fechamento quando as tensões dos dois lados estão dentro de limites de módulo, "
                           "frequência de escorregamento e ângulo. O ângulo de ajuste desconta o avanço angular durante o tempo de fechamento do disjuntor."),
           "premissas": [],
           "limitacoes": ["a verificação de sincronismo não substitui estudo de manobra/energização; confira o esquema de TPs e a seleção de tensões"]},
}
REFS = ["IEEE Std C37.119 — Guide for Breaker Failure Protection of Power Circuit Breakers.",
        "IEEE Std C37.104 — Guide for Automatic Reclosing of Circuit Breakers for AC Distribution and Transmission Lines.",
        "IEEE Std C37.2 — funções 25, 50BF e 79."]


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    cc = cfg(c, CRITERIOS)
    rtc, rtp, vn = num(d, "rtc", 1.0), num(d, "rtp", 1.0), num(d, "vn_kv", 230.0)
    if rtc <= 0 or rtp <= 0 or vn <= 0:
        raise ValueError("RTC, RTP e tensão nominal devem ser maiores que zero.")
    x = Ctx(d)
    fq, fmt = x.fq, x.fmt
    f_hz = num(d, "f_hz", 60.0)
    modo_conf = d.get("modo") == "conferencia"
    dados: dict = {}
    f_vsec = vn * 1000.0 / (math.sqrt(3) * rtp)

    if incluir_base:
        x.passo("Base", "Relação de conversão primário/secundário", r"k_{s} = \frac{RTC}{RTP}",
                rf"k_{{s}} = \frac{{{fq(rtc,1)}}}{{{fq(rtp,1)}}} = {fq(rtc/rtp,4)}")

    # ------------------------------------------------------------------ 50BF
    if "50BF" in sel:
        sec = "Função 50BF"
        t_disj, t_rear, t_prot = num(d, "t_disj_ms"), num(d, "t_rearme_bf_ms"), num(d, "t_prot_ms")
        t_crit, i_res, in_a = num(d, "t_crit_ms"), num(d, "i_resid_a"), num(d, "in_sec_a", 1.0)
        mg, rt, pms = cc["k50bf_margem_ms"], cc["k50bf_retrip_ms"], cc["k50bf_passo_ms"]
        t_bf = sobe(t_disj + t_rear + mg, pms)
        t_tot = t_prot + t_bf + t_disj
        x.passo(sec, "Temporizador de retaguarda", r"t_{BF} = t_{disj} + t_{rearme} + t_{marg}",
                rf"t_{{BF}} = {fq(t_disj,0)} + {fq(t_rear,0)} + {fq(mg,0)} = {fq(t_bf,0)}\ \mathrm{{ms}}")
        x.passo(sec, "Tempo total de eliminação da falta", r"t_{total} = t_{prot} + t_{BF} + t_{disj,bk}",
                rf"t_{{total}} = {fq(t_prot,0)} + {fq(t_bf,0)} + {fq(t_disj,0)} = {fq(t_tot,0)}\ \mathrm{{ms}}"
                + (rf" \le t_{{crit}} = {fq(t_crit,0)}\ \mathrm{{ms}}" if t_crit > 0 else ""))
        if t_crit > 0:
            ok_t = t_tot <= t_crit
            x.check("50BF: tempo total x tempo crítico", "t_total ≤ t_crítico", t_tot, t_crit, ok_t)
            if not ok_t:
                x.alertas.append(f"Função 50BF: o tempo total de eliminação ({fmt(t_tot,0)} ms) supera o tempo crítico "
                                 f"({fmt(t_crit,0)} ms); reduza a margem, use disjuntores mais rápidos ou avalie a estabilidade.")
        else:
            x.alertas.append("Função 50BF: tempo crítico de eliminação não informado; o tempo total não foi comparado ao limite de estabilidade.")
        casos_i = [float(k.get("icc_ka")) for k in casos or [] if _pos(k.get("icc_ka"))]
        icc_min = min(casos_i, default=0.0)
        p_min = max(cc["k50bf_in_frac"] * in_a * rtc, cc["k50bf_resid"] * i_res)
        rec_sec = sobe(p_min / rtc, cc["k50bf_passo_a"])
        rec_pri = rec_sec * rtc
        p_max = icc_min * 1e3 / cc["k50bf_sens"] if icc_min > 0 else 0.0
        ok_p = p_max == 0 or rec_pri <= p_max
        x.passo(sec, "Pickup do detector de corrente",
                r"I_{pk,BF} \ge \max\left( k_{in} \cdot I_{n} \cdot RTC,\ k_{res} \cdot I_{res} \right) \qquad I_{pk,BF} \le \frac{I_{cc,min}}{k_{s}}",
                rf"I_{{pk,BF}} \ge \max\left( {fq(cc['k50bf_in_frac'])} \cdot {fq(in_a,0)} \cdot {fq(rtc,1)},\ {fq(cc['k50bf_resid'])} \cdot {fq(i_res,0)} \right) = {fq(p_min,0)}\ \mathrm{{A}}"
                + (rf" \qquad I_{{pk,BF}} \le \frac{{{fq(icc_min*1e3,0)}}}{{{fq(cc['k50bf_sens'])}}} = {fq(p_max,0)}\ \mathrm{{A}}" if icc_min > 0 else "")
                + rf" \rightarrow {fq(rec_pri,0)}\ \mathrm{{A}}")
        x.check("50BF: pickup recomendado", f"k·In·RTC ≤ Ipk ≤ Icc,min/{fmt(cc['k50bf_sens'],1)}", rec_pri, p_max if p_max else "—", ok_p)
        if icc_min == 0:
            x.alertas.append("Função 50BF: sem casos de curto-circuito; o limite superior do pickup não foi verificado.")
        if not ok_p:
            x.alertas.append(f"Função 50BF: o pickup mínimo ({fmt(rec_pri,0)} A pri) supera Icc,min/k ({fmt(p_max,0)} A); "
                             "reveja a corrente residual informada ou o critério de sensibilidade.")
        crit_t = f"t_disj + t_rearme + margem ({fmt(mg,0)} ms)"
        stt = "OK" if (t_crit <= 0 or t_tot <= t_crit) else "REVISAR"
        x.add("50BF — Falha de disjuntor", "Pickup do detector (fase)", "50FP", rec_sec, "A sec", rec_pri, "A pri",
              "Acima do residual/ruído e abaixo de Icc,mín/k", "OK" if ok_p else "REVISAR")
        x.add("50BF — Falha de disjuntor", "Temporizador de retaguarda", "BFPU", t_bf, "ms", t_bf, "ms", crit_t, stt)
        x.add("50BF — Falha de disjuntor", "Re-disparo", "RETRIP", rt, "ms", rt, "ms", "Critério de re-disparo (etapa 4)", "OK")
        x.card("50BF", f"{fmt(t_bf,0)} ms · {fmt(rec_sec,2)} A sec", f"total {fmt(t_tot,0)} ms" + (f" / crítico {fmt(t_crit,0)} ms" if t_crit > 0 else ""))
        x.tabela("Função 50BF — cadeia de tempos", ["Etapa", "Tempo (ms)"],
                 [["Proteção principal", fmt(t_prot, 0)], ["Re-disparo (opcional)", fmt(rt, 0)], ["Temporizador 50BF", fmt(t_bf, 0)],
                  ["Abertura da retaguarda", fmt(t_disj, 0)], ["Total", fmt(t_tot, 0)],
                  ["Tempo crítico", fmt(t_crit, 0) if t_crit > 0 else "não informado"]])
        dados["p50bf"] = {"t_bf_ms": t_bf, "t_total_ms": t_tot, "t_crit_ms": t_crit, "t_prot_ms": t_prot, "t_disj_ms": t_disj,
                          "retrip_ms": rt, "rec_sec": rec_sec, "rec_pri": rec_pri, "max_pri": p_max, "viavel": ok_p}
        if modo_conf:
            x.conferir("50BF pickup (A sec)", num(d, "ex_50bf_pk_a_sec"), p_min / rtc - 1e-9, p_max / rtc if p_max else None, "A", "Faixa de pickup")
            x.conferir("50BF temporizador (ms)", num(d, "ex_50bf_t_ms"), t_disj + t_rear, (t_crit - t_prot - t_disj) if t_crit > 0 else None,
                       "ms", "Mínimo: t_disj + t_rearme; máximo: restante do tempo crítico")

    # ------------------------------------------------------------------ 79
    if "79" in sel:
        sec = "Função 79"
        modo79 = d.get("modo_79") or "Monopolar"
        t_rec, t_dif, t_arco = num(d, "t_recarga_s"), num(d, "t_dif_remoto_ms"), num(d, "t_arco_sec_ms")
        t_est = num(d, "t_max_estab_s")
        mg, ps = cc["k79_margem_ms"], cc["k79_passo_s"]
        n_cic = 10.5 + vn / 34.5
        t_deion = n_cic / f_hz * 1000.0
        x.passo(sec, "Tempo de deionização", r"t_{deion} = \left( 10,5 + \frac{V_{n}}{34,5} \right) \cdot \frac{1}{f}",
                rf"t_{{deion}} = \left( 10,5 + \frac{{{fq(vn,1)}}}{{34,5}} \right) \cdot \frac{{1}}{{{fq(f_hz,0)}}} = {fq(t_deion,0)}\ \mathrm{{ms}}")
        t3 = sobe((t_deion + t_dif + mg) / 1000.0, ps)
        if t_arco > 0:
            t1 = sobe((t_arco + t_dif + mg) / 1000.0, ps)
            crit1 = "Arco secundário + diferença entre terminais + margem"
        else:
            t1 = sobe(max(cc["k79_t1p_min_s"], t3), ps)
            crit1 = f"Máx. entre o mínimo do critério ({fmt(cc['k79_t1p_min_s'],2)} s) e o tempo tripolar"
            if "ono" in modo79:
                x.alertas.append("Função 79: tempo de arco secundário não informado; o tempo morto monopolar usa o mínimo do critério. "
                                 "Substitua por estudo de arco secundário da LT.")
        x.passo(sec, "Tempo morto tripolar", r"t_{m,3P} \ge t_{deion} + \Delta t_{term} + t_{marg}",
                rf"t_{{m,3P}} \ge {fq(t_deion,0)} + {fq(t_dif,0)} + {fq(mg,0)} = {fq(t_deion+t_dif+mg,0)}\ \mathrm{{ms}} \rightarrow {fq(t3)}\ \mathrm{{s}}")
        x.passo(sec, "Tempo morto monopolar", r"t_{m,1P} \ge t_{arco,sec} + \Delta t_{term} + t_{marg}",
                (rf"t_{{m,1P}} \ge {fq(t_arco,0)} + {fq(t_dif,0)} + {fq(mg,0)} = {fq(t_arco+t_dif+mg,0)}\ \mathrm{{ms}} \rightarrow {fq(t1)}\ \mathrm{{s}}"
                 if t_arco > 0 else rf"t_{{m,1P}} \ge \max\left( {fq(cc['k79_t1p_min_s'])},\ t_{{m,3P}} \right) = {fq(t1)}\ \mathrm{{s}}"))
        reclaim = sobe(max(cc["k79_reclaim_min_s"], t_rec + max(t1, t3)), ps)
        x.passo(sec, "Tempo de reclaim", r"t_{rec} \ge \max\left( t_{rec,min},\ t_{recarga} + t_{morto} \right)",
                rf"t_{{rec}} \ge \max\left( {fq(cc['k79_reclaim_min_s'],1)},\ {fq(t_rec,1)} + {fq(max(t1,t3))} \right) = {fq(reclaim,1)}\ \mathrm{{s}}")
        usa1, usa3 = "ono" in modo79, "ripolar" in modo79
        if usa1 and t_est > 0:
            ok = t1 <= t_est
            x.check("79: tempo morto 1P x estabilidade", "t_m,1P ≤ t_estab", t1, t_est, ok)
            if not ok:
                x.alertas.append(f"Função 79: o tempo morto monopolar ({fmt(t1,2)} s) supera o limite de estabilidade ({fmt(t_est,2)} s).")
        if usa3 and t_est > 0:
            ok = t3 <= t_est
            x.check("79: tempo morto 3P x estabilidade", "t_m,3P ≤ t_estab", t3, t_est, ok)
            if not ok:
                x.alertas.append(f"Função 79: o tempo morto tripolar ({fmt(t3,2)} s) supera o limite de estabilidade ({fmt(t_est,2)} s).")
        x.check("79: reclaim > tempo morto", "t_rec > t_morto", reclaim, max(t1, t3), reclaim > max(t1, t3))
        if usa3 and "25" not in sel:
            x.alertas.append("Função 79: religamento tripolar requer verificação de sincronismo (25) ou lógica de linha viva/barra morta; "
                             "marque a função 25 ou confirme o esquema.")
        stc = lambda t: "OK" if (t_est <= 0 or t <= t_est) else "REVISAR"
        if usa1:
            x.add("79 — Religamento automático", "Tempo morto monopolar", "79OI1P", t1, "s", t1, "s", crit1, stc(t1))
        if usa3:
            x.add("79 — Religamento automático", "Tempo morto tripolar", "79OI3P1", t3, "s", t3, "s",
                  "Deionização + diferença entre terminais + margem", stc(t3))
        x.add("79 — Religamento automático", "Tempo de reclaim", "79RSD", reclaim, "s", reclaim, "s", "Recarga do mecanismo + tempo morto", "OK")
        x.add("79 — Religamento automático", "Número de tentativas", "E79", cc["k79_tentativas"], "—", cc["k79_tentativas"], "—", "Critério (etapa 4)", "OK")
        x.card("79", f"{fmt(t1 if usa1 else t3,2)} s · reclaim {fmt(reclaim,1)} s", modo79)
        x.tabela("Função 79 — tempos", ["Tempo", "Valor (s)"],
                 ([["Tempo morto monopolar", fmt(t1, 2)]] if usa1 else []) + ([["Tempo morto tripolar", fmt(t3, 2)]] if usa3 else [])
                 + [["Tempo de reclaim", fmt(reclaim, 1)], ["Deionização estimada", fmt(t_deion / 1000.0, 3)]])
        dados["p79"] = {"modo": modo79, "t1p_s": t1, "t3p_s": t3, "reclaim_s": reclaim, "deion_ms": t_deion, "usa1": usa1, "usa3": usa3,
                        "t_estab_s": t_est}
        if modo_conf:
            if usa1:
                x.conferir("79 tempo morto 1P (s)", num(d, "ex_79_t1p_s"), t1 - 1e-9, t_est if t_est > 0 else None, "s", "Mínimo calculado")
            if usa3:
                x.conferir("79 tempo morto 3P (s)", num(d, "ex_79_t3p_s"), t3 - 1e-9, t_est if t_est > 0 else None, "s", "Mínimo calculado")
            x.conferir("79 reclaim (s)", num(d, "ex_79_reclaim_s"), reclaim - 1e-9, None, "s", "Mínimo calculado")

    # ------------------------------------------------------------------ 25
    if "25" in sel:
        sec = "Função 25"
        t_f, comp = num(d, "t_fech_ms"), num(d, "comp_ang_25_deg")
        dv, df, dang = cc["k25_dv_pu"], cc["k25_df_hz"], cc["k25_dang_deg"]
        avanco = 360.0 * df * t_f / 1000.0
        dang_aj = dang - avanco
        x.passo(sec, "Avanço angular durante o fechamento", r"\Delta\phi_{fech} = 360 \cdot \Delta f \cdot t_{fech}",
                rf"\Delta\phi_{{fech}} = 360 \cdot {fq(df)} \cdot {fq(t_f/1000,3)} = {fq(avanco,1)}^{{\circ}}")
        x.passo(sec, "Ângulo de ajuste", r"\Delta\phi_{aj} = \Delta\phi_{max} - \Delta\phi_{fech}",
                rf"\Delta\phi_{{aj}} = {fq(dang,0)} - {fq(avanco,1)} = {fq(dang_aj,1)}^{{\circ}}")
        x.passo(sec, "Limites de tensão (secundário, fase-neutro)", r"\Delta V = \Delta V_{pu} \cdot \frac{V_{n}}{\sqrt{3} \cdot RTP}",
                rf"\Delta V = {fq(dv)} \cdot {fq(f_vsec,2)} = {fq(dv*f_vsec,2)}\ \mathrm{{V}}")
        x.check("25: ângulo de ajuste positivo", "Δφ_aj > 0", dang_aj, 0.0, dang_aj > 0,
                "" if dang_aj > 0 else "O avanço no fechamento consome todo o limite angular")
        x.check("25: tensão morta < viva", "Vmorto < Vvivo", cc["k25_vdead_pu"], cc["k25_vlive_pu"], cc["k25_vdead_pu"] < cc["k25_vlive_pu"])
        if dang_aj <= 0:
            x.alertas.append(f"Função 25: o avanço angular durante o fechamento ({fmt(avanco,1)}°) consome o limite de {fmt(dang,0)}°; "
                             "reduza Δf, o tempo de fechamento ou aumente o limite.")
        x.add("25 — Verificação de sincronismo", "Diferença máxima de tensão", "—", dv * f_vsec, "V sec F-N", dv * vn, "kV F-F",
              f"{fmt(dv,2)} pu", "OK")
        x.add("25 — Verificação de sincronismo", "Diferença máxima de frequência", "25SF", df, "Hz", df, "Hz", "Critério (etapa 4)", "OK")
        x.add("25 — Verificação de sincronismo", "Ângulo máximo", "25ANG1", dang_aj, "°", dang_aj, "°",
              f"{fmt(dang,0)}° − avanço de fechamento", "OK" if dang_aj > 0 else "REVISAR")
        x.add("25 — Verificação de sincronismo", "Compensação angular fixa", "—", comp, "°", comp, "°", "Defasagem entre tensões comparadas", "OK")
        x.add("25 — Verificação de sincronismo", "Tensão de 'vivo' (mín.)", "25VHI", cc["k25_vlive_pu"] * f_vsec, "V sec F-N",
              cc["k25_vlive_pu"] * vn, "kV F-F", f"{fmt(cc['k25_vlive_pu'],2)} pu", "OK")
        x.add("25 — Verificação de sincronismo", "Tensão de 'morto' (máx.)", "25VLO", cc["k25_vdead_pu"] * f_vsec, "V sec F-N",
              cc["k25_vdead_pu"] * vn, "kV F-F", f"{fmt(cc['k25_vdead_pu'],2)} pu", "OK")
        x.card("25", f"Δφ {fmt(dang_aj,0)}° · Δf {fmt(df,2)} Hz", f"ΔV {fmt(dv*f_vsec,1)} V sec")
        dados["p25"] = {"dv_pu": dv, "df_hz": df, "dang_deg": dang, "dang_aj_deg": dang_aj, "avanco_deg": avanco, "t_fech_ms": t_f}
        if modo_conf:
            x.conferir("25 ângulo máximo (°)", num(d, "ex_25_dang_deg"), None, dang_aj + 1e-9, "°", "Não deve superar o ângulo de ajuste")
    return x.pacote(dados)


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def figuras(r: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.plots import AZUL, AZUL_ESCURO, AZUL_CLARO, CINZA, CINZA_CLARO
    md = (r.get("modulos") or {}).get("f_disjuntor") or {}
    out = []
    p = md.get("p50bf")
    if p:
        fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=170)
        t0, segs = 0.0, [("Proteção", p["t_prot_ms"], AZUL_CLARO), ("Temporizador 50BF", p["t_bf_ms"], AZUL),
                         ("Retaguarda abre", p["t_disj_ms"], AZUL_ESCURO)]
        for nome, dur, cor in segs:
            ax.barh(0, dur, left=t0, color=cor, edgecolor="white", label=f"{nome} ({dur:.0f} ms)")
            t0 += dur
        if p["t_crit_ms"] > 0:
            ax.axvline(p["t_crit_ms"], color=CINZA, ls="--", lw=1.5, label=f"Tempo crítico ({p['t_crit_ms']:.0f} ms)")
        ax.set_yticks([]); ax.set_xlabel("Tempo desde o início da falta (ms)")
        ax.set_title("50BF: cadeia de tempos", color=AZUL_ESCURO, fontsize=10)
        ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.38), ncol=2, frameon=False)
        ax.grid(True, axis="x", color=CINZA_CLARO, lw=0.6)
        fig.tight_layout()
        out.append(("Cadeia de tempos — função 50BF", fig))
    q = md.get("p79")
    if q:
        fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=170)
        t0 = 0.0
        tm = q["t1p_s"] if q["usa1"] else q["t3p_s"]
        for nome, dur, cor in (("Tempo morto", tm, AZUL), ("Reclaim", q["reclaim_s"] - tm if q["reclaim_s"] > tm else 0, AZUL_CLARO)):
            ax.barh(0, dur, left=t0, color=cor, edgecolor="white", label=f"{nome} ({dur:.2f} s)")
            t0 += dur
        ax.set_yticks([]); ax.set_xlabel("Tempo após o trip (s)")
        ax.set_title("79: tempo morto e reclaim", color=AZUL_ESCURO, fontsize=10)
        ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.38), ncol=2, frameon=False)
        ax.grid(True, axis="x", color=CINZA_CLARO, lw=0.6)
        fig.tight_layout()
        out.append(("Sequência de religamento — função 79", fig))
    return out
