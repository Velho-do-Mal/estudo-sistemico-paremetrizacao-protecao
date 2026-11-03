"""Funções de gerador/máquina: 46 (sequência negativa), 49 (sobrecarga térmica), 32 (potência reversa), 40 (perda de excitação), 87G (diferencial).

Referências de critério (valores padrão editáveis na etapa 4; conferir no manual do relé):
  * 46: I2²t = K (IEEE C37.102 / ANSI C50.13); alarme em I2 contínuo admissível.
  * 49: modelo térmico t = τ·ln[(I²−Ip²)/(I²−(k·In)²)] (IEC 60255-149).
  * 32: pickup = fração da potência de motorização do acionador (IEEE C37.102).
  * 40: dois círculos mho com offset Xd'/2; Z1 = 1,0 pu, Z2 = Xd (IEEE C37.102).
  * 87G: característica percentual com duas inclinações.
"""
from __future__ import annotations

import math

from core.base_modulo import Ctx, cfg, num, sobe
from core.modulos import E, K

COD = ("46", "49", "32", "40", "87G")
TITULO = "Gerador e máquinas (46 / 49 / 32 / 40 / 87G)"
G = "Gerador / máquina"
ACION = ["Turbina a vapor", "Turbina hidráulica", "Turbina a gás", "Motor diesel"]
P_MOT = {"Turbina a vapor": 1.5, "Turbina hidráulica": 1.0, "Turbina a gás": 50.0, "Motor diesel": 25.0}
TODOS = COD

ENTRADAS = [
    E("sg_mva", "Potência nominal da máquina (MVA)", 20.0, TODOS, G, "Base de todas as correntes e impedâncias da máquina.", "MVA nominal de placa.", "Placa do gerador.",
      mn=0.01, mx=2000.0, passo=0.5, fmt="%.2f"),
    E("vg_kv", "Tensão nominal da máquina (kV)", 13.8, TODOS, G, "Base de corrente e impedância.", "kV fase-fase.", "Placa do gerador.", mn=0.1, mx=50.0, passo=0.1, fmt="%.2f"),
    E("rtc_g", "RTC do gerador", 1000.0, TODOS, G, "Converte corrente primária em secundária.", "Relação total do TC de terminal (ex.: 5000:5 → 1000).", "Folha de dados do TC; projeto.",
      mn=0.1, mx=1e5, passo=1.0, fmt="%.1f"),
    E("rtp_g", "RTP do gerador", 120.0, ("32", "40"), G, "Converte tensão/impedância primária em secundária.", "Ex.: 13800/115 → 120.", "Folha de dados do TP; projeto.",
      mn=0.1, mx=1e5, passo=0.1, fmt="%.1f"),
    E("fp_g", "Fator de potência nominal", 0.85, ("40", "32"), G, "Potência ativa nominal = S × FP.", "Valor de placa.", "Placa do gerador.", mn=0.5, mx=1.0, passo=0.01, fmt="%.2f"),
    # 46
    E("i2_cont_pct", "46: I2 contínuo admissível (% de In)", 8.0, ("46",), "Função 46", "Define o alarme e o início da curva de disparo.", "Norma ANSI C50.13: 8 % (polos salientes) a 5-10 % (rotor cilíndrico).",
      "Folha de dados do fabricante da máquina.", mn=0.5, mx=30.0, passo=0.5, fmt="%.1f"),
    E("k_i2t", "46: constante I2²t da máquina (K, s)", 20.0, ("46",), "Função 46", "Capacidade térmica do rotor para desequilíbrio: t = K / I2².", "K = 10 (cilíndrico indireto), 30 (hidro) ... use o dado do fabricante.",
      "Curva de capabilidade/ficha do gerador (ANSI C50.13).", mn=1.0, mx=200.0, passo=1.0, fmt="%.1f"),
    E("i2_falta_pu", "46: I2 de falta externa desequilibrada (pu de In)", 0.5, ("46",), "Função 46", "Verifica se a função 46 não atua antes da proteção de retaguarda.", "I2 pu vista pela máquina em falta bifásica/monofásica externa.",
      "Estudo de curto-circuito (sequência negativa).", mn=0.0, mx=5.0, passo=0.05, fmt="%.2f"),
    E("t_backup_s", "46: tempo de eliminação da retaguarda (s)", 1.0, ("46",), "Função 46", "O disparo por 46 deve ser mais lento que a retaguarda externa.", "Tempo total da retaguarda mais lenta para falta externa.",
      "Estudo de coordenação.", mn=0.1, mx=10.0, passo=0.1, fmt="%.2f"),
    # 49
    E("fs_term", "49: fator de serviço (k)", 1.05, ("49",), "Função 49", "Corrente contínua máxima = k × In.", "1,00 a 1,15 conforme a máquina.", "Placa/folha de dados.", mn=1.0, mx=1.5, passo=0.01, fmt="%.2f"),
    E("tau_min", "49: constante de tempo térmica (min)", 30.0, ("49",), "Função 49", "Velocidade de aquecimento do enrolamento.", "Dado do fabricante; típico 10 a 60 min.", "Folha de dados; ensaio térmico.",
      mn=1.0, mx=500.0, passo=1.0, fmt="%.1f"),
    E("i_part_pu", "49: corrente de partida/carga transitória (pu de In)", 1.0, ("49",), "Função 49", "Para verificar que a função não atua na partida.", "Ex.: 6 para motor; 1 se for gerador.", "Folha de dados; estudo de partida.",
      mn=0.0, mx=10.0, passo=0.1, fmt="%.1f"),
    E("t_part_s", "49: duração da partida (s)", 0.0, ("49",), "Função 49", "Tempo em que a corrente de partida circula.", "0 se não aplicável (gerador).", "Estudo de partida.",
      mn=0.0, mx=600.0, passo=1.0, fmt="%.0f"),
    # 32
    E("acionador", "32: tipo de acionador", "Turbina a vapor", ("32",), "Função 32", "Define a potência de motorização típica.", "Selecione conforme a máquina primária.", "Projeto da usina.",
      tipo="sel", opcoes=ACION),
    E("p_mot_pct", "32: potência de motorização (% de Pn; 0 = valor típico do acionador)", 0.0, ("32",), "Função 32", "Perdas do acionador quando a máquina funciona como motor.", "Dado do fabricante do acionador; 0 usa tabela típica.",
      "Folha de dados da turbina/motor.", mn=0.0, mx=100.0, passo=0.1, fmt="%.2f"),
    # 40
    E("xd_pu", "40: reatância síncrona Xd (pu)", 1.8, ("40",), "Função 40", "Diâmetro do mho de segunda zona.", "Xd não saturada, na base da máquina.", "Folha de dados do gerador.", mn=0.2, mx=4.0, passo=0.01, fmt="%.2f"),
    E("xdl_pu", "40: reatância transitória X'd (pu)", 0.3, ("40",), "Função 40", "Offset do mho (X'd/2).", "X'd saturada/não saturada na base da máquina.", "Folha de dados do gerador.", mn=0.05, mx=1.0, passo=0.01, fmt="%.2f"),
    # 87G
    E("err_tc_g_pct", "87G: erro de TC (%)", 5.0, ("87G",), "Função 87G", "Base da inclinação e do pickup.", "Classe de exatidão dos TCs de fase e neutro.", "Folha de dados dos TCs.", mn=0.0, mx=30.0, passo=0.5, fmt="%.1f"),
    E("i_ext_g_pu", "87G: maior falta externa (pu de In)", 6.0, ("87G",), "Função 87G", "Verifica estabilidade com saturação de TC.", "Corrente de falta trifásica nos terminais, em pu da corrente nominal.", "Estudo de curto-circuito.",
      mn=0.5, mx=40.0, passo=0.5, fmt="%.1f"),
    E("i_int_min_pu", "87G: menor falta interna (pu de In; 0 = não informado)", 0.0, ("87G",), "Função 87G", "Verifica a sensibilidade.", "Corrente mínima de falta no enrolamento (ex.: neutro com resistor).", "Estudo de curto-circuito.",
      mn=0.0, mx=40.0, passo=0.05, fmt="%.2f"),
    # conferência
    E("ex_46_alarme", "46 — alarme existente (% de In)", 0.0, ("46",), G, "Compara com o ajuste atual.", "% da corrente nominal.", "Arquivo de ajustes.", mn=0.0, mx=30.0, passo=0.1, conf=True),
    E("ex_49_trip", "49 — corrente de disparo existente (A sec)", 0.0, ("49",), G, "Compara com o ajuste atual.", "A secundários.", "Arquivo de ajustes.", mn=0.0, mx=50.0, passo=0.01, conf=True),
    E("ex_32_p", "32 — potência de disparo existente (% de Pn)", 0.0, ("32",), G, "Compara com o ajuste atual.", "% da potência nominal.", "Arquivo de ajustes.", mn=0.0, mx=100.0, passo=0.1, conf=True),
    E("ex_40_z2", "40 — diâmetro da Zona 2 existente (Ω sec)", 0.0, ("40",), G, "Compara com o ajuste atual.", "Ω secundários.", "Arquivo de ajustes.", mn=0.0, mx=500.0, passo=0.1, conf=True),
    E("ex_87g_pk", "87G — pickup existente (pu de In)", 0.0, ("87G",), G, "Compara com o ajuste atual.", "pu da corrente nominal.", "Arquivo de ajustes.", mn=0.0, mx=5.0, passo=0.01, conf=True),
]

CRITERIOS = [
    K("k46_alarme", "46: alarme = k × I2 contínuo", 1.0, ("46",), "O alarme alerta quando o desequilíbrio atinge o limite contínuo.", "Típico 1,0.", "Critério do projetista.", mn=0.5, mx=2.0, passo=0.05),
    K("k46_pk_trip", "46: início da curva = k × I2 contínuo", 1.0, ("46",), "O disparo só atua acima do limite contínuo.", "Típico 1,0 a 1,2.", "Critério do projetista.", mn=1.0, mx=3.0, passo=0.05),
    K("k46_t_alarme", "46: tempo do alarme (s)", 10.0, ("46",), "Evita alarme por transitório.", "Típico 5 a 30 s.", "Critério do cliente.", mn=0.1, mx=120.0, passo=1.0, fmt="%.0f"),
    K("k46_t_max", "46: tempo máximo da curva (s)", 1000.0, ("46",), "Limita a cauda da curva.", "Típico 1000 s.", "Manual do relé.", mn=100.0, mx=10000.0, passo=100.0, fmt="%.0f"),
    K("k46_marg_ret", "46: t_disparo / t_retaguarda ≥", 1.5, ("46",), "Seletividade com a retaguarda para falta externa.", "Típico 1,5.", "Critério do cliente.", mn=1.0, mx=5.0, passo=0.1),
    K("k49_alarme", "49: alarme (% da capacidade térmica)", 90.0, ("49",), "Aviso antes do disparo.", "Típico 90 %.", "Manual do relé.", mn=50.0, mx=100.0, passo=1.0, fmt="%.0f"),
    K("k49_marg_part", "49: t_disparo / t_partida ≥", 1.25, ("49",), "Margem para não atuar na partida.", "Típico 1,2 a 1,5.", "Critério do cliente.", mn=1.0, mx=3.0, passo=0.05),
    K("k32_fator", "32: pickup = k × potência de motorização", 0.5, ("32",), "Pickup abaixo da potência de motorização para garantir a atuação.", "Típico 0,5.", "IEEE C37.102.", mn=0.1, mx=1.0, passo=0.05),
    K("k32_t", "32: temporização do disparo (s)", 10.0, ("32",), "Evita atuar em oscilações de potência e sincronismo.", "Típico 2 a 30 s (vapor: 10 a 30 s).", "IEEE C37.102; critério da usina.", mn=0.1, mx=120.0, passo=0.5, fmt="%.1f"),
    K("k32_pk_min_pct", "32: pickup mínimo viável (% de Pn)", 0.2, ("32",), "Limite de sensibilidade do relé/TC/TP.", "Típico 0,2 a 0,5 %.", "Manual do relé.", mn=0.05, mx=5.0, passo=0.05, fmt="%.2f"),
    K("k40_z1_pu", "40: Zona 1 – diâmetro (pu da base da máquina)", 1.0, ("40",), "Zona 1 detecta perda total de campo (carga alta).", "IEEE C37.102: 1,0 pu.", "IEEE C37.102.", mn=0.2, mx=3.0, passo=0.05, fmt="%.2f"),
    K("k40_t1", "40: Zona 1 – tempo (s)", 0.25, ("40",), "Disparo rápido para perda total.", "Típico 0,1 a 0,3 s.", "IEEE C37.102.", mn=0.0, mx=5.0, passo=0.05, fmt="%.2f"),
    K("k40_z2_xd", "40: Zona 2 – diâmetro = k × Xd", 1.0, ("40",), "Zona 2 detecta perda parcial em qualquer carga.", "IEEE C37.102: 1,0 × Xd.", "IEEE C37.102.", mn=0.5, mx=2.0, passo=0.05),
    K("k40_t2", "40: Zona 2 – tempo (s)", 0.5, ("40",), "Evita atuar em oscilações estáveis.", "Típico 0,5 a 0,6 s.", "IEEE C37.102.", mn=0.0, mx=5.0, passo=0.05, fmt="%.2f"),
    K("k40_off", "40: offset = k × X'd", 0.5, ("40",), "Desloca o mho para o 2º quadrante.", "IEEE C37.102: X'd/2.", "IEEE C37.102.", mn=0.0, mx=1.0, passo=0.05),
    K("k87g_pk_min", "87G: pickup mínimo (pu de In)", 0.10, ("87G",), "Piso de sensibilidade.", "Típico 0,1 a 0,3 pu.", "Manual do relé.", mn=0.02, mx=1.0, passo=0.01),
    K("k87g_kseg", "87G: pickup ≥ k × erro de TC", 2.0, ("87G",), "Cobre erro de TC em regime.", "Típico 2.", "Critério do cliente.", mn=1.0, mx=5.0, passo=0.1),
    K("k87g_margem", "87G: margem da inclinação 1 (%)", 5.0, ("87G",), "Folga na inclinação 1.", "Típico 5 %.", "Critério do cliente.", mn=0.0, mx=30.0, passo=0.5, fmt="%.1f"),
    K("k87g_slope2", "87G: inclinação 2 (%)", 50.0, ("87G",), "Restrição extra em falta externa severa.", "Típico 50 %.", "Manual do relé.", mn=20.0, mx=150.0, passo=1.0, fmt="%.0f"),
    K("k87g_irs", "87G: ponto de transição (pu de In)", 3.0, ("87G",), "Corrente de restrição em que a inclinação 2 começa.", "Típico 2 a 4 pu.", "Manual do relé.", mn=0.5, mx=10.0, passo=0.1, fmt="%.1f"),
    K("k87g_sat_pct", "87G: erro por saturação em falta externa (% da corrente)", 20.0, ("87G",), "Diferencial falso máximo esperado em falta externa.", "Típico 10 a 30 %.", "Estudo de TC.", mn=0.0, mx=60.0, passo=1.0, fmt="%.0f"),
    K("k87g_est", "87G: limiar na falta externa / diferencial falso ≥", 1.2, ("87G",), "Margem de estabilidade.", "Típico 1,2.", "Critério do cliente.", mn=1.0, mx=3.0, passo=0.05),
    K("k87g_sens", "87G: I falta interna mín. / pickup ≥", 2.0, ("87G",), "Margem de sensibilidade.", "Típico 2.", "Critério do cliente.", mn=1.0, mx=10.0, passo=0.1),
]

TEXTOS = {
    "46": {"secao": "Função 46",
           "metodologia": "A proteção de sequência negativa limita o aquecimento do rotor pela relação I2²t = K. O alarme usa o I2 contínuo admissível da máquina e o disparo segue a curva t = K / I2², limitada a um tempo máximo. Verifica-se que o disparo é mais lento que a retaguarda para faltas externas desequilibradas.",
           "premissas": ["Função 46: curva I2²t com constante K do fabricante."],
           "limitacoes": ["não foi modelado o resfriamento do rotor (tempo de reset); curvas de relé podem diferir da forma t = K/I2²"]},
    "49": {"secao": "Função 49",
           "metodologia": "O modelo térmico de primeira ordem calcula o tempo de disparo t = τ·ln[(I² − Ip²)/(I² − (k·In)²)], com corrente de pré-carga Ip. O alarme ocorre em percentual da capacidade térmica, e verifica-se que a partida não provoca disparo.",
           "premissas": ["Função 49: constante de tempo única e corrente de pré-carga nula (partida a frio)."],
           "limitacoes": ["não há modelagem de resfriamento nem de temperatura ambiente; constantes distintas para parado/em marcha devem ser tratadas no relé"]},
    "32": {"secao": "Função 32",
           "metodologia": "A proteção de potência reversa detecta a motorização da máquina. O pickup é uma fração da potência de motorização do acionador, convertida à base secundária, e a temporização evita atuações em oscilações de potência.",
           "premissas": ["Função 32: potência de motorização típica do acionador quando não informada."],
           "limitacoes": ["a potência de motorização típica é referência; use o dado do fabricante do acionador; o erro angular de TC/TP afeta a sensibilidade"]},
    "40": {"secao": "Função 40",
           "metodologia": "A perda de excitação é detectada por dois círculos mho com offset X'd/2: Zona 1 com diâmetro de 1,0 pu e Zona 2 com diâmetro Xd, com temporizações distintas (IEEE C37.102). Os alcances são convertidos de pu da máquina para ohms secundários.",
           "premissas": ["Função 40: dois mho com offset, sem supervisão por tensão ou limitador de subexcitação."],
           "limitacoes": ["não foi verificada a coordenação com o limitador de subexcitação (UEL), a curva de capabilidade nem a oscilação estável; compare a característica no plano R-X"]},
    "87G": {"secao": "Função 87G",
            "metodologia": "A diferencial percentual do gerador compara as correntes dos lados terminal e neutro. O pickup supera o erro de TC, a inclinação 1 cobre o erro de TC com margem e a inclinação 2 assegura estabilidade em falta externa com saturação de TC.",
            "premissas": ["Função 87G: TCs do terminal e neutro de mesma relação."],
            "limitacoes": ["não foi modelada a diferencial de gerador-transformador (unidade); falta à terra no estator com alta impedância usa a função 64G/87GN"]},
}
REFS = ["IEEE Std C37.102 — Guide for AC Generator Protection.",
        "ANSI C50.13 — Cylindrical-Rotor Synchronous Generators (limites de sequência negativa).",
        "IEC 60255-149 — Functional requirements for thermal electrical relays.",
        "IEEE Std C37.2 — funções 46, 49, 32, 40 e 87G."]


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    cc = cfg(c, CRITERIOS)
    sn, vn, rtc, rtp = num(d, "sg_mva"), num(d, "vg_kv"), num(d, "rtc_g", 1.0), num(d, "rtp_g", 1.0)
    if min(sn, vn, rtc, rtp) <= 0:
        raise ValueError("Gerador: informe potência, tensão, RTC e RTP maiores que zero.")
    x = Ctx(d)
    fq, fmt = x.fq, x.fmt
    conf = d.get("modo") == "conferencia"
    dados: dict = {}
    i_n = sn * 1e3 / (math.sqrt(3) * vn)
    i_ns = i_n / rtc
    x.passo("Base da máquina", "Corrente nominal", r"I_{n} = \frac{S_{n} \cdot 1000}{\sqrt{3} \cdot V_{n}}",
            rf"I_{{n}} = \frac{{{fq(sn,2)} \cdot 1000}}{{\sqrt{{3}} \cdot {fq(vn,2)}}} = {fq(i_n,1)}\ \mathrm{{A}} \qquad I_{{n,sec}} = \frac{{{fq(i_n,1)}}}{{{fq(rtc,1)}}} = {fq(i_ns,3)}\ \mathrm{{A}}")

    # ---------------------------------------------------------------- 46
    if "46" in sel:
        sec = "Função 46"
        i2c, kk = num(d, "i2_cont_pct"), num(d, "k_i2t")
        i2f, tb = num(d, "i2_falta_pu"), num(d, "t_backup_s", 1.0)
        al = sobe(cc["k46_alarme"] * i2c, 0.1)
        pk = sobe(cc["k46_pk_trip"] * i2c, 0.1)
        x.passo(sec, "Pickups de alarme e disparo", r"I2_{al} = k_{a} \cdot I2_{cont} \qquad I2_{pk} = k_{p} \cdot I2_{cont}",
                rf"I2_{{al}} = {fq(cc['k46_alarme'])} \cdot {fq(i2c,1)} = {fq(al,1)}\ \% \qquad I2_{{pk}} = {fq(cc['k46_pk_trip'])} \cdot {fq(i2c,1)} = {fq(pk,1)}\ \%")
        x.passo(sec, "Curva I2²t", r"t = \frac{K}{(I2/I_{n})^{2}}",
                rf"t = \frac{{{fq(kk,1)}}}{{(I2/I_{{n}})^{{2}}}} \qquad t(I2 = 1{{,}}0\ \mathrm{{pu}}) = {fq(kk,1)}\ \mathrm{{s}}")
        t_falta = kk / (i2f ** 2) if i2f > 0 else float("inf")
        ok = (i2f * 100 < pk) or (t_falta >= cc["k46_marg_ret"] * tb)
        x.check("46: seletividade com a retaguarda", f"t_46 ≥ {fmt(cc['k46_marg_ret'],1)}·t_retaguarda",
                (t_falta if t_falta != float("inf") else "não opera"), cc["k46_marg_ret"] * tb, ok)
        if not ok:
            x.alertas.append(f"Função 46: para I2 = {fmt(i2f,2)} pu o disparo ocorre em {fmt(t_falta,1)} s, antes da retaguarda ({fmt(tb,1)} s); reveja K ou o tempo da retaguarda.")
        F = "46 — Sequência negativa"
        st = "OK" if ok else "REVISAR"
        x.add(F, "Alarme (I2)", "—", al / 100 * i_ns, "A sec", al / 100 * i_n, "A pri", f"{fmt(al,1)} % de In", "OK")
        x.add(F, "Tempo do alarme", "—", cc["k46_t_alarme"], "s", cc["k46_t_alarme"], "s", "Critério (etapa 4)", "OK")
        x.add(F, "Início da curva de disparo", "—", pk / 100 * i_ns, "A sec", pk / 100 * i_n, "A pri", f"{fmt(pk,1)} % de In", st)
        x.add(F, "Constante K (I2²t)", "—", kk, "s", kk, "s", "Dado do fabricante", st)
        x.add(F, "Tempo máximo da curva", "—", cc["k46_t_max"], "s", cc["k46_t_max"], "s", "Critério (etapa 4)", "OK")
        x.card("46", f"{fmt(pk,1)} % · K={fmt(kk,0)}", f"Alarme {fmt(al,1)} % · t(1 pu)={fmt(kk,0)} s")
        dados["p46"] = {"alarme_pct": al, "pk_pct": pk, "K": kk, "t_max": cc["k46_t_max"], "t_falta": t_falta if t_falta != float("inf") else None, "ok": ok}
        if conf:
            x.conferir("46 alarme (% In)", num(d, "ex_46_alarme"), al * 0.8, al * 1.2, "%", "Faixa em torno do calculado (±20 %)")

    # ---------------------------------------------------------------- 49
    if "49" in sel:
        sec = "Função 49"
        k, tau, ip, tp = num(d, "fs_term", 1.05), num(d, "tau_min", 30.0) * 60.0, num(d, "i_part_pu"), num(d, "t_part_s")
        i_trip = k * i_ns
        al = cc["k49_alarme"]
        x.passo(sec, "Corrente de disparo térmico", r"I_{trip} = k \cdot I_{n,sec}",
                rf"I_{{trip}} = {fq(k,2)} \cdot {fq(i_ns,3)} = {fq(i_trip,3)}\ \mathrm{{A}}")

        def t_trip(i_pu):
            if i_pu <= k:
                return float("inf")
            return tau * math.log(i_pu ** 2 / (i_pu ** 2 - k ** 2))

        x.passo(sec, "Tempo de disparo (partida a frio)", r"t = \tau \cdot \ln\left[ \frac{I^{2}}{I^{2} - (k \cdot I_{n})^{2}} \right]",
                rf"t(1{{,}}5\ \mathrm{{pu}}) = {fq(t_trip(1.5)/60,1)}\ \mathrm{{min}} \qquad t(2{{,}}0\ \mathrm{{pu}}) = {fq(t_trip(2.0)/60,1)}\ \mathrm{{min}}")
        ok = tp <= 0 or ip <= k or t_trip(ip) >= cc["k49_marg_part"] * tp
        x.check("49: não atua na partida", f"t_trip(Ipart) ≥ {fmt(cc['k49_marg_part'],2)}·t_part", t_trip(ip) if ip > k else "não opera", cc["k49_marg_part"] * tp, ok)
        if not ok:
            x.alertas.append("Função 49: o modelo térmico dispararia durante a partida; aumente τ, reduza a partida ou use constantes de tempo distintas parado/em marcha.")
        F = "49 — Sobrecarga térmica"
        st = "OK" if ok else "REVISAR"
        x.add(F, "Corrente de disparo (k·In)", "—", i_trip, "A sec", i_trip * rtc, "A pri", "Fator de serviço × In", st)
        x.add(F, "Constante de tempo", "—", tau / 60.0, "min", tau / 60.0, "min", "Dado do fabricante", st)
        x.add(F, "Alarme térmico", "—", al, "%", al, "%", "Critério (etapa 4)", "OK")
        x.card("49", f"{fmt(i_trip,2)} A sec", f"τ {fmt(tau/60,0)} min · alarme {fmt(al,0)} %")
        dados["p49"] = {"k": k, "tau": tau, "i_trip_sec": i_trip, "i_ns": i_ns, "ok": ok}
        if conf:
            x.conferir("49 corrente de disparo (A sec)", num(d, "ex_49_trip"), i_trip * 0.9, i_trip * 1.1, "A", "Faixa ±10 %")

    # ---------------------------------------------------------------- 32
    if "32" in sel:
        sec = "Função 32"
        ac = d.get("acionador") or ACION[0]
        pm = num(d, "p_mot_pct") or P_MOT.get(ac, 1.0)
        pn_mw = sn * num(d, "fp_g", 0.85)
        pk = max(cc["k32_fator"] * pm, cc["k32_pk_min_pct"])
        pk = sobe(pk, 0.05)
        p_pri = pk / 100.0 * pn_mw
        p_sec = p_pri * 1e6 / (rtc * rtp)
        x.passo(sec, "Pickup de potência reversa", r"P_{pk} = k \cdot P_{mot} \qquad P_{sec} = \frac{P_{pk} \cdot P_{n}}{RTC \cdot RTP}",
                rf"P_{{pk}} = {fq(cc['k32_fator'])} \cdot {fq(pm,2)} = {fq(pk,2)}\ \% \qquad P_{{sec}} = \frac{{{fq(p_pri*1e6,0)}}}{{{fq(rtc,1)} \cdot {fq(rtp,1)}}} = {fq(p_sec,2)}\ \mathrm{{W}}")
        ok = pk <= pm
        x.check("32: pickup abaixo da motorização", "P_pk ≤ P_mot", pk, pm, ok)
        if not ok:
            x.alertas.append("Função 32: o pickup mínimo viável excede a potência de motorização; a função pode não detectar a motorização.")
        F = "32 — Potência reversa"
        x.add(F, "Pickup de potência reversa", "—", p_sec, "W sec", p_pri * 1e3, "kW pri", f"{fmt(pk,2)} % de Pn ({ac})", "OK" if ok else "REVISAR")
        x.add(F, "Temporização", "—", cc["k32_t"], "s", cc["k32_t"], "s", "Critério (etapa 4)", "OK")
        x.card("32", f"{fmt(pk,2)} % Pn", f"{fmt(p_sec,1)} W sec · {fmt(cc['k32_t'],1)} s")
        dados["p32"] = {"pk_pct": pk, "p_mot": pm, "p_sec": p_sec, "ok": ok}
        if conf:
            x.conferir("32 potência (% Pn)", num(d, "ex_32_p"), pk * 0.5, pm, "%", "Entre metade do calculado e a motorização")

    # ---------------------------------------------------------------- 40
    if "40" in sel:
        sec = "Função 40"
        xd, xdl = num(d, "xd_pu", 1.8), num(d, "xdl_pu", 0.3)
        zb = vn ** 2 / sn
        fz = rtc / rtp
        z1 = cc["k40_z1_pu"] * zb * fz
        z2 = cc["k40_z2_xd"] * xd * zb * fz
        off = cc["k40_off"] * xdl * zb * fz
        x.passo(sec, "Impedância base e conversão ao secundário", r"Z_{b} = \frac{V_{n}^{2}}{S_{n}} \qquad Z_{sec} = Z_{pu} \cdot Z_{b} \cdot \frac{RTC}{RTP}",
                rf"Z_{{b}} = \frac{{{fq(vn,2)}^{{2}}}}{{{fq(sn,2)}}} = {fq(zb,3)}\ \Omega \qquad \frac{{RTC}}{{RTP}} = {fq(fz,3)}")
        x.passo(sec, "Zonas mho", r"Z1 = k_{1} \cdot Z_{b} \qquad Z2 = k_{2} \cdot X_{d} \cdot Z_{b} \qquad Off = k_{o} \cdot X'_{d} \cdot Z_{b}",
                rf"Z1 = {fq(z1,2)}\ \Omega \qquad Z2 = {fq(z2,2)}\ \Omega \qquad Off = {fq(off,2)}\ \Omega")
        ok = z2 > z1 > 0 and off > 0
        x.check("40: Zona 2 > Zona 1", "Z2 > Z1", z2, z1, z2 > z1)
        F = "40 — Perda de excitação"
        st = "OK" if ok else "REVISAR"
        x.add(F, "Zona 1 – diâmetro", "40Z1P", z1, "Ω sec", z1 / fz, "Ω pri", f"{fmt(cc['k40_z1_pu'],2)} pu", st)
        x.add(F, "Zona 1 – offset", "40XD1", -off, "Ω sec", -off / fz, "Ω pri", "−X'd/2", st)
        x.add(F, "Zona 1 – tempo", "40Z1D", cc["k40_t1"], "s", cc["k40_t1"], "s", "Critério (etapa 4)", "OK")
        x.add(F, "Zona 2 – diâmetro", "40Z2P", z2, "Ω sec", z2 / fz, "Ω pri", f"{fmt(cc['k40_z2_xd'],2)}·Xd", st)
        x.add(F, "Zona 2 – offset", "40XD2", -off, "Ω sec", -off / fz, "Ω pri", "−X'd/2", st)
        x.add(F, "Zona 2 – tempo", "40Z2D", cc["k40_t2"], "s", cc["k40_t2"], "s", "Critério (etapa 4)", "OK")
        x.card("40", f"Z1 {fmt(z1,1)} / Z2 {fmt(z2,1)} Ω", f"Offset −{fmt(off,2)} Ω sec")
        dados["p40"] = {"z1": z1, "z2": z2, "off": off, "fz": fz, "zb": zb, "t1": cc["k40_t1"], "t2": cc["k40_t2"]}
        if conf:
            x.conferir("40 diâmetro Zona 2 (Ω sec)", num(d, "ex_40_z2"), z2 * 0.9, z2 * 1.1, "Ω", "Faixa ±10 %")

    # ---------------------------------------------------------------- 87G
    if "87G" in sel:
        sec = "Função 87G"
        e, ext = num(d, "err_tc_g_pct", 5.0), num(d, "i_ext_g_pu", 6.0)
        imin = num(d, "i_int_min_pu")
        pk = sobe(max(cc["k87g_pk_min"], cc["k87g_kseg"] * e / 100.0), 0.01)
        s1 = sobe(e + cc["k87g_margem"], 1.0)
        s2, irs = cc["k87g_slope2"], cc["k87g_irs"]
        x.passo(sec, "Pickup e inclinação 1", r"I_{pk} \ge \max\left( I_{min},\ k \cdot e_{TC} \right) \qquad SLP_{1} = e_{TC} + m",
                rf"I_{{pk}} = \max\left( {fq(cc['k87g_pk_min'])},\ {fq(cc['k87g_kseg'])} \cdot {fq(e/100,3)} \right) = {fq(pk)}\ \mathrm{{pu}} \qquad SLP_{{1}} = {fq(e,1)} + {fq(cc['k87g_margem'],1)} \rightarrow {fq(s1,0)}\ \%")
        thr = (s1 / 100.0 * ext) if ext <= irs else (s1 / 100.0 * irs + s2 / 100.0 * (ext - irs))
        thr = max(thr, pk)
        falso = cc["k87g_sat_pct"] / 100.0 * ext
        ok_e = thr >= cc["k87g_est"] * falso
        x.passo(sec, "Estabilidade em falta externa", r"I_{lim} = SLP \cdot I_{rest} \ge k_{e} \cdot e_{sat} \cdot I_{ext}",
                rf"I_{{lim}} = {fq(thr,2)}\ \mathrm{{pu}} \ge {fq(cc['k87g_est'])} \cdot {fq(cc['k87g_sat_pct']/100,2)} \cdot {fq(ext,1)} = {fq(cc['k87g_est']*falso,2)}\ \mathrm{{pu}}")
        x.check("87G: estabilidade em falta externa", "Ilim ≥ k·diferencial falso", thr, cc["k87g_est"] * falso, ok_e)
        ok_s = imin == 0 or imin >= cc["k87g_sens"] * pk
        x.check("87G: sensibilidade", f"Ifalta,int ≥ {fmt(cc['k87g_sens'],1)}·pickup", imin if imin else "—", cc["k87g_sens"] * pk, ok_s)
        if not ok_e:
            x.alertas.append("Função 87G: a inclinação 2 não garante estabilidade com a saturação informada; aumente a inclinação 2 ou melhore os TCs.")
        if imin == 0:
            x.alertas.append("Função 87G: menor falta interna não informada; a sensibilidade não foi verificada.")
        elif not ok_s:
            x.alertas.append("Função 87G: sensibilidade insuficiente para a menor falta interna informada.")
        F = "87G — Diferencial de gerador"
        st = "OK" if (ok_e and ok_s) else "REVISAR"
        x.add(F, "Pickup mínimo", "—", pk * i_ns, "A sec", pk * i_n, "A pri", f"{fmt(pk,2)} pu de In", st)
        x.add(F, "Inclinação 1", "—", s1, "%", s1, "%", "Erro de TC + margem", st)
        x.add(F, "Inclinação 2", "—", s2, "%", s2, "%", "Critério (etapa 4)", st)
        x.add(F, "Ponto de transição", "—", irs * i_ns, "A sec", irs * i_n, "A pri", f"{fmt(irs,1)} pu de In", "OK")
        x.card("87G", f"{fmt(pk,2)} pu · {fmt(s1,0)}/{fmt(s2,0)} %", f"Pickup {fmt(pk*i_ns,2)} A sec")
        dados["p87g"] = {"pk": pk, "slope1": s1, "slope2": s2, "irs": irs, "ok_est": ok_e, "ok_sens": ok_s}
        if conf:
            x.conferir("87G pickup (pu)", num(d, "ex_87g_pk"), pk - 1e-9, None, "pu", "Mínimo calculado")
    return x.pacote(dados)


def figuras(r: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.plots import AZUL, AZUL_ESCURO, AZUL_PALIDO, CINZA, CINZA_CLARO
    md = (r.get("modulos") or {}).get("f_gerador") or {}
    out = []
    p = md.get("p46")
    if p:
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=170)
        xs = [0.05 + i * 0.01 for i in range(0, 200)]
        ys = [min(p["K"] / (v * v), p["t_max"]) for v in xs]
        ax.loglog(xs, ys, color=AZUL_ESCURO, lw=2, label="t = K / I2²")
        ax.axvline(p["pk_pct"] / 100.0, color=CINZA, ls="--", label="Início da curva")
        ax.set_xlabel("I2 (pu de In)"); ax.set_ylabel("Tempo (s)"); ax.grid(True, which="both", color=CINZA_CLARO, lw=0.5)
        ax.set_title("Função 46: curva I2²t", color=AZUL_ESCURO, fontsize=10); ax.legend(fontsize=7, frameon=False)
        fig.tight_layout(); out.append(("Curva I2²t — função 46", fig))
    p = md.get("p49")
    if p:
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=170)
        k, tau = p["k"], p["tau"]
        xs = [k + 0.02 + i * 0.02 for i in range(0, 150)]
        ys = [tau * math.log(v * v / (v * v - k * k)) / 60.0 for v in xs]
        ax.loglog(xs, ys, color=AZUL_ESCURO, lw=2, label="Partida a frio")
        ax.set_xlabel("I (pu de In)"); ax.set_ylabel("Tempo (min)"); ax.grid(True, which="both", color=CINZA_CLARO, lw=0.5)
        ax.set_title("Função 49: curva térmica", color=AZUL_ESCURO, fontsize=10); ax.legend(fontsize=7, frameon=False)
        fig.tight_layout(); out.append(("Curva térmica — função 49", fig))
    p = md.get("p40")
    if p:
        fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=170)
        for dm, cor, nm in ((p["z1"], AZUL, "Zona 1"), (p["z2"], AZUL_ESCURO, "Zona 2")):
            cy = -(p["off"] + dm / 2.0)
            th = [i * math.pi / 90 for i in range(181)]
            ax.plot([dm / 2.0 * math.cos(t) for t in th], [cy + dm / 2.0 * math.sin(t) for t in th], color=cor, lw=2, label=nm)
        ax.axhline(0, color=CINZA, lw=0.8); ax.axvline(0, color=CINZA, lw=0.8)
        ax.set_aspect("equal"); ax.grid(True, color=CINZA_CLARO, lw=0.5)
        ax.set_xlabel("R (Ω sec)"); ax.set_ylabel("X (Ω sec)")
        ax.set_title("Função 40: círculos mho", color=AZUL_ESCURO, fontsize=10); ax.legend(fontsize=7, frameon=False)
        fig.tight_layout(); out.append(("Plano R-X — função 40", fig))
    p = md.get("p87g")
    if p:
        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=170)
        xs = [i * 0.05 for i in range(0, 161)]
        ys = [max(p["pk"], p["slope1"] / 100 * v) if v <= p["irs"] else p["slope1"] / 100 * p["irs"] + p["slope2"] / 100 * (v - p["irs"]) for v in xs]
        ax.fill_between(xs, ys, [max(ys)] * len(xs), color=AZUL_PALIDO)
        ax.plot(xs, ys, color=AZUL_ESCURO, lw=2)
        ax.set_xlabel("Corrente de restrição (pu)"); ax.set_ylabel("Corrente diferencial (pu)"); ax.grid(True, color=CINZA_CLARO, lw=0.6)
        ax.set_title("Função 87G: característica percentual", color=AZUL_ESCURO, fontsize=10)
        fig.tight_layout(); out.append(("Característica diferencial — função 87G", fig))
    return out
