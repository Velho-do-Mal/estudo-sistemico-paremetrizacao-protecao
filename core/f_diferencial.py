"""Funções diferenciais: 87T (transformador), 87L (linha) e 87B (barra).

Critérios (valores padrão editáveis na etapa 4; devem ser alinhados à norma técnica/critério do cliente e ao manual do relé):
  * 87T: TAP = corrente nominal secundária de cada enrolamento; Slope1 = erro de TC + faixa do comutador + descasamento + margem;
         O87P ≥ k·(excitação + comutador + erro de TC); U87P ≥ máx(k·falta passante, k·inrush).
  * 87L: pickup ≥ k·corrente capacitiva da LT e ≤ Icc,mín/k_sens; inclinações e ponto de joelho por critério.
  * 87B: alta impedância: Vset = k·I_ext,sec·(R_TC + R_cabo), Vk ≥ 2·Vset; baixa impedância: pickup acima do erro de TC com a carga da barra.
Convenções: TAP e correntes secundárias em A; correntes de disparo em pu do TAP (87T).
"""
from __future__ import annotations

import math

from core.base_modulo import Ctx, cfg, num, sobe
from core.modulos import E, K

COD = ("87T", "87L", "87B")
TITULO = "Diferenciais (87T / 87L / 87B)"
G_T, G_L, G_B = "Transformador (87T)", "Linha (87L)", "Barra (87B)"
LIG = ["Estrela (Y)", "Delta (D)"]
TIPOS_87B = ["Alta impedância", "Baixa impedância (percentual)"]

ENTRADAS = [
    # ---------------- 87T
    E("s_tr_mva", "Potência nominal do transformador (MVA)", 50.0, ("87T",), G_T,
      "Define a corrente nominal de cada enrolamento e, portanto, o TAP.", "Potência no estágio de maior ventilação que a proteção deve cobrir (ONAF/ONAF2 se aplicável).",
      "Placa do transformador; folha de dados.", mn=0.1, mx=5000.0, passo=1.0, fmt="%.1f"),
    E("v_at_kv", "Tensão nominal do enrolamento de alta (kV)", 230.0, ("87T",), G_T,
      "Base da corrente nominal do lado AT.", "kV fase-fase, tensão nominal (não o tap em operação).", "Placa do transformador.",
      mn=0.1, mx=1000.0, passo=0.1, fmt="%.1f"),
    E("v_bt_kv", "Tensão nominal do enrolamento de baixa (kV)", 69.0, ("87T",), G_T,
      "Base da corrente nominal do lado BT.", "kV fase-fase.", "Placa do transformador.", mn=0.1, mx=1000.0, passo=0.1, fmt="%.1f"),
    E("rtc_at", "RTC do lado AT", 150.0, ("87T",), G_T,
      "Converte a corrente nominal AT em corrente secundária no relé.", "Relação total do TC usado na zona diferencial (ex.: 750:5 → 150).",
      "Folha de dados do TC; projeto executivo; ajuste atual do relé.", mn=0.1, mx=1e5, passo=0.1, fmt="%.1f"),
    E("rtc_bt", "RTC do lado BT", 100.0, ("87T",), G_T,
      "Converte a corrente nominal BT em corrente secundária no relé.", "Idem (ex.: 500:5 → 100).",
      "Folha de dados do TC; projeto executivo.", mn=0.1, mx=1e5, passo=0.1, fmt="%.1f"),
    E("lig_at", "Ligação do enrolamento AT", "Estrela (Y)", ("87T",), G_T,
      "Define a necessidade de compensar defasagem e eliminar a sequência zero.", "Estrela (Y) ou Delta (D).", "Placa do transformador (diagrama fasorial).",
      tipo="sel", opcoes=LIG),
    E("lig_bt", "Ligação do enrolamento BT", "Delta (D)", ("87T",), G_T,
      "Idem.", "Estrela (Y) ou Delta (D).", "Placa do transformador.", tipo="sel", opcoes=LIG),
    E("tap_oltc_pct", "Faixa do comutador sob carga (± %)", 10.0, ("87T",), G_T,
      "A variação de tap cria corrente diferencial aparente; entra na inclinação e no pickup.", "Faixa total em % (ex.: ±10 %). 0 se não houver comutador.",
      "Placa/folha de dados do transformador (OLTC).", mn=0.0, mx=40.0, passo=0.5, fmt="%.1f"),
    E("i_exc_pct", "Corrente de excitação em regime (% da nominal)", 1.0, ("87T",), G_T,
      "Corrente de magnetização vista como diferencial em regime.", "Em % da corrente nominal; típico 0,5 a 2 %.", "Relatório de ensaio de rotina do transformador.",
      mn=0.0, mx=20.0, passo=0.1, fmt="%.1f"),
    E("z_tr_pct", "Impedância do transformador (%)", 12.0, ("87T",), G_T,
      "Estima a maior falta passante quando não há dado do estudo de curto.", "Z% na base da potência nominal.", "Placa/relatório de ensaio do transformador.",
      mn=1.0, mx=50.0, passo=0.1, fmt="%.1f"),
    E("icc_pass_ka", "Maior falta passante (externa) vista pelo transformador (kA; 0 = estimar por Z%)", 0.0, ("87T",), G_T,
      "Base do ajuste instantâneo sem restrição (não pode operar em falta externa com TC saturado).",
      "Maior corrente de falta trifásica externa que atravessa o enrolamento de maior corrente. 0 = o app usa 100/Z%.",
      "Estudo de curto-circuito (Anafas/ETAP).", mn=0.0, mx=500.0, passo=0.1, fmt="%.2f"),
    E("inrush_pu", "Corrente de energização (inrush) máxima (pu da nominal)", 8.0, ("87T",), G_T,
      "O ajuste instantâneo precisa ficar acima do pico de inrush.", "Múltiplo da corrente nominal; típico 6 a 12.", "Folha de dados/ensaio do transformador; estudo de energização.",
      mn=1.0, mx=30.0, passo=0.5, fmt="%.1f"),
    # ---------------- comum 87L/87B
    E("in_sec_diff_a", "Corrente nominal secundária do TC (A)", 1.0, ("87L", "87B"), G_L,
      "Base do pickup mínimo (fração da corrente nominal do relé).", "Escolha 1 A ou 5 A.", "Folha de dados do TC; ajuste atual do relé.",
      tipo="sel", opcoes=[1.0, 5.0]),
    # ---------------- 87L
    E("q_cap_mvar", "Potência reativa de carregamento da LT (Mvar)", 10.0, ("87L",), G_L,
      "A corrente capacitiva da linha aparece como corrente diferencial; o pickup precisa superá-la.", "Mvar trifásico à tensão nominal (0 se desprezível).",
      "Cálculo de parâmetros da LT (PLS-CADD): susceptância de sequência positiva × Vn²; ou dados do cadastro.", mn=0.0, mx=2000.0, passo=0.5, fmt="%.1f"),
    # ---------------- 87B
    E("tipo_87b", "Tipo do diferencial de barra", "Alta impedância", ("87B",), G_B,
      "Define o método de ajuste (tensão de ajuste x percentual).", "Escolha conforme o relé/esquema instalado.", "Especificação do relé de barra; projeto.",
      tipo="sel", opcoes=TIPOS_87B),
    E("n_alim_87b", "Número de TCs/alimentadores na zona", 6.0, ("87B",), G_B,
      "Cada TC contribui com corrente de magnetização em alta impedância.", "Quantidade de TCs ligados ao circuito diferencial.", "Unifilar da barra.",
      mn=2.0, mx=40.0, passo=1.0, fmt="%.0f"),
    E("i_ext_max_ka", "Maior falta externa passante pela barra (kA)", 20.0, ("87B",), G_B,
      "Base da estabilidade: o relé não pode operar em falta externa com TC saturado.", "Maior corrente de falta em um alimentador (barra remota/na saída).",
      "Estudo de curto-circuito.", mn=0.1, mx=500.0, passo=0.1, fmt="%.2f"),
    E("icc_bar_min_ka", "Menor curto na barra (kA; 0 = não informado)", 10.0, ("87B",), G_B,
      "Verifica a sensibilidade para a menor falta interna.", "Menor Icc na barra (mínima geração, FT com Rf se exigido).", "Estudo de curto-circuito.",
      mn=0.0, mx=500.0, passo=0.1, fmt="%.2f"),
    E("r_ct_sec_ohm", "Resistência do secundário do TC (Ω)", 2.5, ("87B",), G_B,
      "Compõe a tensão que aparece no circuito em falta externa.", "Maior resistência de enrolamento entre os TCs da zona.", "Folha de dados/ensaio do TC.",
      mn=0.0, mx=100.0, passo=0.1, fmt="%.2f"),
    E("r_cabo_ohm", "Resistência do cabo até o relé, ida e volta (Ω)", 1.0, ("87B",), G_B,
      "Idem: queda no circuito secundário.", "Resistência do pior caso (cabo mais longo, ida e volta).", "Projeto de cabos; medição.",
      mn=0.0, mx=100.0, passo=0.1, fmt="%.2f"),
    E("v_knee_v", "Tensão de joelho do TC (V)", 600.0, ("87B",), G_B,
      "O TC precisa ter joelho acima do dobro da tensão de ajuste, para operar em falta interna.", "Tensão de joelho (Vk) do pior TC da zona.", "Curva de excitação/folha de dados do TC.",
      mn=1.0, mx=10000.0, passo=10.0, fmt="%.0f"),
    E("i_mag_a", "Corrente de magnetização por TC na tensão de ajuste (A sec)", 0.02, ("87B",), G_B,
      "Reduz a sensibilidade em alta impedância: soma-se à corrente de operação.", "Valor lido na curva de excitação do TC à tensão de ajuste.", "Curva de excitação do TC.",
      mn=0.0, mx=5.0, passo=0.005, fmt="%.3f"),
    E("i_carga_barra_a", "Maior corrente de carga da barra (A pri)", 1500.0, ("87B",), G_B,
      "Baixa impedância: o pickup precisa superar o erro de TC com carga máxima.", "Maior soma de correntes que passam pela barra.", "Estudos de fluxo/planejamento.",
      mn=0.0, mx=1e5, passo=10.0, fmt="%.0f"),
    # ---------------- conferência
    E("ex_87t_o87p", "87T — O87P existente (pu)", 0.0, ("87T",), G_T, "Compara com o ajuste atual.", "pu do TAP.", "Arquivo de ajustes do relé.", mn=0.0, mx=5.0, passo=0.01, conf=True),
    E("ex_87t_slp1", "87T — Slope 1 existente (%)", 0.0, ("87T",), G_T, "Compara com o ajuste atual.", "%.", "Arquivo de ajustes do relé.", mn=0.0, mx=200.0, passo=1.0, fmt="%.0f", conf=True),
    E("ex_87t_slp2", "87T — Slope 2 existente (%)", 0.0, ("87T",), G_T, "Compara com o ajuste atual.", "%.", "Arquivo de ajustes do relé.", mn=0.0, mx=200.0, passo=1.0, fmt="%.0f", conf=True),
    E("ex_87t_u87p", "87T — U87P existente (pu)", 0.0, ("87T",), G_T, "Compara com o ajuste atual.", "pu do TAP.", "Arquivo de ajustes do relé.", mn=0.0, mx=50.0, passo=0.1, conf=True),
    E("ex_87l_pk_a", "87L — pickup existente (A pri)", 0.0, ("87L",), G_L, "Compara com o ajuste atual.", "A primários.", "Arquivo de ajustes do relé.", mn=0.0, mx=1e5, passo=1.0, fmt="%.0f", conf=True),
    E("ex_87b_vset_v", "87B — tensão de ajuste existente (V; alta impedância)", 0.0, ("87B",), G_B, "Compara com o ajuste atual.", "V.", "Arquivo de ajustes do relé.", mn=0.0, mx=10000.0, passo=1.0, fmt="%.0f", conf=True),
    E("ex_87b_pk_a", "87B — pickup existente (A pri; baixa impedância)", 0.0, ("87B",), G_B, "Compara com o ajuste atual.", "A primários.", "Arquivo de ajustes do relé.", mn=0.0, mx=1e5, passo=1.0, fmt="%.0f", conf=True),
]

CRITERIOS = [
    K("k87t_err_tc_pct", "87T: erro de TC (%)", 5.0, ("87T",), "Parcela da inclinação que cobre o erro de TC.", "Típico 5 a 10 % (classe 5P/10P).", "Classe de exatidão dos TCs.", mn=0.0, mx=30.0, passo=0.5, fmt="%.1f"),
    K("k87t_margem_pct", "87T: margem de segurança da inclinação (%)", 5.0, ("87T",), "Folga adicional na inclinação 1.", "Típico 5 %.", "Critério do cliente.", mn=0.0, mx=30.0, passo=0.5, fmt="%.1f"),
    K("k87t_slope2_pct", "87T: inclinação 2 (%)", 60.0, ("87T",), "Mais restrição em faltas externas severas (TC saturando).", "Típico 50 a 80 %.", "Manual do relé; critério do cliente.", mn=20.0, mx=150.0, passo=1.0, fmt="%.0f"),
    K("k87t_irs1_pu", "87T: ponto de transição das inclinações IRS1 (pu)", 3.0, ("87T",), "Corrente de restrição em que a inclinação 2 passa a valer.", "Típico 2 a 4 pu do TAP.", "Manual do relé.", mn=0.5, mx=10.0, passo=0.1, fmt="%.1f"),
    K("k87t_pk_min_pu", "87T: pickup mínimo O87P (pu)", 0.20, ("87T",), "Piso de sensibilidade do elemento percentual.", "Típico 0,2 a 0,3 pu.", "Manual do relé.", mn=0.05, mx=1.0, passo=0.01),
    K("k87t_kseg", "87T: fator de segurança do pickup", 1.5, ("87T",), "Cobre excitação, comutador e erro de TC com margem.", "O87P ≥ k × (excitação + comutador + erro de TC).", "Critério do cliente.", mn=1.0, mx=5.0, passo=0.1),
    K("k87t_u_pass", "87T: instantâneo ≥ k × falta passante", 1.2, ("87T",), "O elemento sem restrição não pode operar em falta externa.", "Típico 1,2.", "Critério do cliente.", mn=1.0, mx=3.0, passo=0.1),
    K("k87t_u_inrush", "87T: instantâneo ≥ k × inrush", 1.0, ("87T",), "Evita operar na energização.", "Fator sobre o pico de inrush informado.", "Critério do cliente.", mn=0.5, mx=3.0, passo=0.1),
    K("k87t_h2", "87T: restrição por 2ª harmônica (%)", 15.0, ("87T",), "Bloqueia o elemento durante o inrush.", "Típico 15 a 20 %.", "Manual do relé.", mn=5.0, mx=40.0, passo=1.0, fmt="%.0f"),
    K("k87t_h5", "87T: restrição por 5ª harmônica (%)", 35.0, ("87T",), "Bloqueia na sobre-excitação.", "Típico 25 a 35 %.", "Manual do relé.", mn=5.0, mx=60.0, passo=1.0, fmt="%.0f"),
    K("k87t_passo_tap", "87T: passo do TAP (A)", 0.01, ("87T",), "Resolução do TAP no relé.", "Passo do parâmetro.", "Manual do relé.", mn=0.001, mx=0.5, passo=0.001, fmt="%.3f"),
    K("k87t_rel_tap_max", "87T: relação máxima entre TAPs", 7.5, ("87T",), "Limite do relé para a relação entre os TAPs dos enrolamentos.", "Típico 7,5.", "Manual do relé.", mn=1.0, mx=30.0, passo=0.5, fmt="%.1f"),
    K("k87l_cap", "87L: pickup ≥ k × corrente capacitiva", 2.0, ("87L",), "O carregamento da LT aparece como diferencial.", "Típico 1,5 a 3.", "Critério do cliente / manual do relé.", mn=1.0, mx=5.0, passo=0.1),
    K("k87l_pk_pu", "87L: pickup mínimo (fração de In do TC)", 0.20, ("87L",), "Piso de sensibilidade.", "Fração da corrente nominal do TC.", "Manual do relé.", mn=0.02, mx=2.0, passo=0.01),
    K("k87l_sens", "87L: Icc mín. / pickup ≥", 2.0, ("87L",), "Garante a atuação para faltas de menor corrente (alta resistência/fonte fraca).", "Típico 2.", "Critério do cliente.", mn=1.0, mx=10.0, passo=0.1),
    K("k87l_slope1_pct", "87L: inclinação 1 (%)", 30.0, ("87L",), "Cobre erro de TC e atraso de canal na região de baixa restrição.", "Típico 20 a 40 %.", "Manual do relé.", mn=5.0, mx=100.0, passo=1.0, fmt="%.0f"),
    K("k87l_slope2_pct", "87L: inclinação 2 (%)", 60.0, ("87L",), "Mais restrição com TC saturando em faltas externas.", "Típico 50 a 80 %.", "Manual do relé.", mn=10.0, mx=150.0, passo=1.0, fmt="%.0f"),
    K("k87l_irs_pu", "87L: ponto de joelho (pu de In)", 2.0, ("87L",), "Corrente de restrição em que a inclinação 2 começa.", "Típico 1,5 a 3 pu.", "Manual do relé.", mn=0.5, mx=10.0, passo=0.1, fmt="%.1f"),
    K("k87l_passo_a", "87L: passo do pickup (A pri)", 10.0, ("87L",), "Resolução do relé.", "Passo do parâmetro.", "Manual do relé.", mn=1.0, mx=100.0, passo=1.0, fmt="%.0f"),
    K("k87b_stab", "87B (alta Z): fator de estabilidade", 1.25, ("87B",), "Margem sobre a tensão máxima gerada em falta externa com TC saturado.", "Típico 1,2 a 1,5.", "Critério do projetista/fabricante.", mn=1.0, mx=3.0, passo=0.05),
    K("k87b_knee", "87B (alta Z): Vk ≥ k × Vset", 2.0, ("87B",), "O TC deve fornecer tensão suficiente para operar em falta interna.", "Típico 2.", "Critério do fabricante.", mn=1.0, mx=4.0, passo=0.1),
    K("k87b_i_rele_a", "87B (alta Z): corrente no relé na tensão de ajuste (A sec)", 0.05, ("87B",), "Define o resistor estabilizador (R = Vset / I).", "Valor típico do relé de alta impedância.", "Manual do relé.", mn=0.001, mx=2.0, passo=0.005, fmt="%.3f"),
    K("k87b_sens", "87B: Icc mín. na barra / corrente de operação ≥", 2.0, ("87B",), "Sensibilidade para faltas internas.", "Típico 2.", "Critério do cliente.", mn=1.0, mx=10.0, passo=0.1),
    K("k87b_pk_pu", "87B (baixa Z): pickup mínimo (fração de In)", 0.20, ("87B",), "Piso do elemento percentual.", "Fração da corrente nominal do TC.", "Manual do relé.", mn=0.02, mx=2.0, passo=0.01),
    K("k87b_err_tc_pct", "87B (baixa Z): erro de TC com a carga (%)", 10.0, ("87B",), "O pickup supera o erro de TC com a corrente máxima da barra.", "Típico 5 a 10 %.", "Classe de exatidão dos TCs.", mn=0.0, mx=30.0, passo=0.5, fmt="%.1f"),
    K("k87b_slope_pct", "87B (baixa Z): inclinação (%)", 60.0, ("87B",), "Restrição em faltas externas com saturação de TC.", "Típico 50 a 80 %.", "Manual do relé.", mn=10.0, mx=150.0, passo=1.0, fmt="%.0f"),
    K("k87b_passo_a", "87B: passo do pickup (A pri)", 10.0, ("87B",), "Resolução do relé.", "Passo do parâmetro.", "Manual do relé.", mn=1.0, mx=100.0, passo=1.0, fmt="%.0f"),
]

TEXTOS = {
    "87T": {"secao": "Função 87T",
            "metodologia": ("A proteção diferencial percentual do transformador compara as correntes dos enrolamentos referidas ao TAP (corrente nominal secundária). "
                            "A inclinação 1 cobre o erro de TC, a faixa do comutador sob carga e o descasamento de TAP; a inclinação 2 aumenta a restrição "
                            "em faltas externas severas. O pickup mínimo supera excitação e erros em regime, e o elemento instantâneo fica acima da falta "
                            "passante e do inrush. As restrições por 2ª e 5ª harmônicas bloqueiam energização e sobre-excitação."),
            "premissas": ["Função 87T: transformador de dois enrolamentos, compensação digital de fase no relé (módulo da corrente preservado) e TAP igual à corrente nominal secundária."],
            "limitacoes": ["o 87T foi ajustado para transformador de dois enrolamentos; autotransformadores, terciário e transformadores defasadores exigem análise específica; "
                           "a matriz de compensação e as convenções de TAP devem ser conferidas no manual do relé"]},
    "87L": {"secao": "Função 87L",
            "metodologia": ("O pickup da diferencial de linha fica acima da corrente capacitiva da LT (que aparece como diferencial) e abaixo da menor corrente de falta "
                            "dividida pelo fator de sensibilidade. A característica percentual usa duas inclinações com ponto de joelho, para tolerar erro de TC "
                            "e saturação em faltas externas."),
            "premissas": ["Função 87L: característica percentual de duas inclinações; relés com plano alfa (ex.: SEL-411L) usam raio e ângulo equivalentes que devem ser derivados no manual."],
            "limitacoes": ["não foram modelados atraso/assimetria de canal, linhas multiterminais nem derivação (tap); relés de plano alfa requerem conversão da característica"]},
    "87B": {"secao": "Função 87B",
            "metodologia": ("Na alta impedância, a tensão de ajuste supera a máxima tensão gerada no relé em falta externa com um TC saturado (corrente de falta externa x resistências do TC e do cabo), "
                            "com fator de estabilidade; o joelho dos TCs deve superar o dobro dessa tensão; a sensibilidade soma a corrente do relé e as magnetizações. "
                            "Na baixa impedância, o pickup supera o erro de TC com a carga máxima e a inclinação restringe faltas externas."),
            "premissas": ["Função 87B: zona única com TCs de mesma relação; em alta impedância, resistor estabilizador definido pela corrente de ajuste do relé."],
            "limitacoes": ["esquemas de barra dupla com seleção de zona, supervisão de TC aberto e lógica de falha de disjuntor associada não foram modelados"]},
}
REFS = ["IEEE Std C37.91 — Guide for Protective Relay Applications to Power Transformers.",
        "IEEE Std C37.243 — Guide for Application of Digital Line Current Differential Relays.",
        "IEEE Std C37.97 — Guide for Protective Relay Applications to Power System Buses.",
        "IEEE Std C37.2 — funções 87T, 87L e 87B."]


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def calcular(d: dict, c: dict, casos: list[dict], sel: list[str], incluir_base: bool = False) -> dict:
    cc = cfg(c, CRITERIOS)
    rtc, rtp, vn = num(d, "rtc", 1.0), num(d, "rtp", 1.0), num(d, "vn_kv", 230.0)
    if rtc <= 0 or rtp <= 0 or vn <= 0:
        raise ValueError("RTC, RTP e tensão nominal devem ser maiores que zero.")
    x = Ctx(d)
    fq, fmt = x.fq, x.fmt
    modo_conf = d.get("modo") == "conferencia"
    dados: dict = {}
    icc_casos = [float(k["icc_ka"]) for k in casos or [] if _pos(k.get("icc_ka"))]
    icc_min = min(icc_casos, default=0.0)

    if incluir_base:
        x.passo("Base", "Relação de conversão primário/secundário", r"k_{s} = \frac{RTC}{RTP}",
                rf"k_{{s}} = \frac{{{fq(rtc,1)}}}{{{fq(rtp,1)}}} = {fq(rtc/rtp,4)}")

    # ------------------------------------------------------------------ 87T
    if "87T" in sel:
        sec = "Função 87T"
        s_mva, v1, v2 = num(d, "s_tr_mva"), num(d, "v_at_kv"), num(d, "v_bt_kv")
        r1, r2 = num(d, "rtc_at", 1.0), num(d, "rtc_bt", 1.0)
        if min(s_mva, v1, v2, r1, r2) <= 0:
            raise ValueError("87T: informe potência, tensões e RTCs maiores que zero.")
        oltc, iexc, ztr = num(d, "tap_oltc_pct"), num(d, "i_exc_pct"), num(d, "z_tr_pct", 10.0)
        i_pass_ka, inrush = num(d, "icc_pass_ka"), num(d, "inrush_pu", 8.0)
        lig1, lig2 = d.get("lig_at") or LIG[0], d.get("lig_bt") or LIG[1]
        passo_tap = cc["k87t_passo_tap"]
        i1 = s_mva * 1e3 / (math.sqrt(3) * v1)
        i2 = s_mva * 1e3 / (math.sqrt(3) * v2)
        s1, s2 = i1 / r1, i2 / r2
        tap1, tap2 = round(round(s1 / passo_tap) * passo_tap, 6), round(round(s2 / passo_tap) * passo_tap, 6)
        if tap1 <= 0 or tap2 <= 0:
            raise ValueError("87T: o TAP calculado é menor que o passo do relé; revise as RTCs (corrente secundária nominal muito baixa) ou o passo do TAP.")
        x.passo(sec, "Corrente nominal e TAP de cada enrolamento", r"I_{n} = \frac{S_{n} \cdot 1000}{\sqrt{3} \cdot V_{n}} \qquad TAP = \frac{I_{n}}{RTC}",
                rf"I_{{n,AT}} = \frac{{{fq(s_mva,1)} \cdot 1000}}{{\sqrt{{3}} \cdot {fq(v1,1)}}} = {fq(i1,1)}\ \mathrm{{A}} \qquad TAP_{{AT}} = \frac{{{fq(i1,1)}}}{{{fq(r1,1)}}} = {fq(tap1,3)}\ \mathrm{{A}}"
                rf" \qquad I_{{n,BT}} = {fq(i2,1)}\ \mathrm{{A}} \qquad TAP_{{BT}} = \frac{{{fq(i2,1)}}}{{{fq(r2,1)}}} = {fq(tap2,3)}\ \mathrm{{A}}")
        ratio_real, ratio_tap = (s1 / s2), (tap1 / tap2)
        mism = abs(ratio_tap / ratio_real - 1.0) * 100.0
        rel_tap = max(tap1, tap2) / min(tap1, tap2)
        x.passo(sec, "Descasamento de TAP", r"M = \left| \frac{TAP_{AT} / TAP_{BT}}{I_{sec,AT} / I_{sec,BT}} - 1 \right| \cdot 100",
                rf"M = {fq(mism,2)}\ \%")
        e_tc, mg = cc["k87t_err_tc_pct"], cc["k87t_margem_pct"]
        slope1 = sobe(e_tc + oltc + mism + mg, 1.0)
        slope2 = cc["k87t_slope2_pct"]
        x.passo(sec, "Inclinação 1", r"SLP_{1} = e_{TC} + \Delta_{OLTC} + M + m",
                rf"SLP_{{1}} = {fq(e_tc,1)} + {fq(oltc,1)} + {fq(mism,2)} + {fq(mg,1)} = {fq(e_tc+oltc+mism+mg,1)}\ \% \rightarrow {fq(slope1,0)}\ \%")
        o87 = sobe(max(cc["k87t_pk_min_pu"], cc["k87t_kseg"] * (iexc + oltc + e_tc) / 100.0), 0.01)
        x.passo(sec, "Pickup mínimo", r"O87P \ge \max\left( O87P_{min},\ k_{seg} \cdot (I_{exc} + \Delta_{OLTC} + e_{TC}) \right)",
                rf"O87P \ge \max\left( {fq(cc['k87t_pk_min_pu'])},\ {fq(cc['k87t_kseg'])} \cdot {fq((iexc+oltc+e_tc)/100,3)} \right) = {fq(o87)}\ \mathrm{{pu}}")
        i_pass_pu = (i_pass_ka * 1e3 / i1) if i_pass_ka > 0 else 100.0 / ztr
        u87 = sobe(max(cc["k87t_u_pass"] * i_pass_pu, cc["k87t_u_inrush"] * inrush), 0.5)
        x.passo(sec, "Elemento instantâneo", r"U87P \ge \max\left( k_{p} \cdot I_{pass,pu},\ k_{i} \cdot I_{inrush} \right)",
                rf"U87P \ge \max\left( {fq(cc['k87t_u_pass'])} \cdot {fq(i_pass_pu,2)},\ {fq(cc['k87t_u_inrush'])} \cdot {fq(inrush,1)} \right) = {fq(u87,1)}\ \mathrm{{pu}}")
        ok_rel = rel_tap <= cc["k87t_rel_tap_max"]
        x.check("87T: relação entre TAPs", "TAPmáx/TAPmín ≤ limite do relé", rel_tap, cc["k87t_rel_tap_max"], ok_rel,
                "" if ok_rel else "Revise as RTCs para aproximar as correntes secundárias")
        x.check("87T: descasamento", "M ≤ 5 %", mism, 5.0, mism <= 5.0)
        x.check("87T: inclinação 2 > inclinação 1", "SLP2 > SLP1", slope2, slope1, slope2 > slope1)
        x.check("87T: instantâneo > pickup", "U87P > O87P", u87, o87, u87 > o87)
        if not ok_rel:
            x.alertas.append(f"Função 87T: a relação entre TAPs ({fmt(rel_tap,2)}) excede o limite do relé ({fmt(cc['k87t_rel_tap_max'],1)}); revise as relações dos TCs.")
        if mism > 5.0:
            x.alertas.append(f"Função 87T: descasamento de TAP de {fmt(mism,1)} % acima de 5 %; ajuste as RTCs ou o passo de TAP.")
        comp_txt = "Compensação Δ no(s) enrolamento(s) em estrela (conferir deslocamento no grupo de ligação)" if lig1 != lig2 \
            else "Sem defasagem; remover a sequência zero nos enrolamentos em estrela aterrada"
        if lig1 == lig2 and "Estrela" in lig1:
            x.alertas.append("Função 87T: transformador com enrolamentos em estrela nos dois lados: remova a sequência zero (compensação Δ) "
                             "se houver caminho de 3I0 para falta externa à terra.")
        stt = "OK" if (ok_rel and mism <= 5.0 and slope2 > slope1) else "REVISAR"
        F = "87T — Diferencial de transformador"
        x.add(F, "TAP enrolamento 1 (AT)", "TAP1", tap1, "A sec", i1, "A pri", "Corrente nominal ÷ RTC", stt)
        x.add(F, "TAP enrolamento 2 (BT)", "TAP2", tap2, "A sec", i2, "A pri", "Corrente nominal ÷ RTC", stt)
        x.add(F, "Pickup mínimo", "O87P", o87, "pu do TAP", o87 * i1, "A pri (AT)", "Excitação + comutador + erro de TC", "OK")
        x.add(F, "Inclinação 1", "SLP1", slope1, "%", slope1, "%", "Erro de TC + comutador + descasamento + margem", "OK")
        x.add(F, "Inclinação 2", "SLP2", slope2, "%", slope2, "%", "Critério (etapa 4)", "OK")
        x.add(F, "Ponto de transição", "IRS1", cc["k87t_irs1_pu"], "pu do TAP", cc["k87t_irs1_pu"], "pu do TAP", "Critério (etapa 4)", "OK")
        x.add(F, "Instantâneo sem restrição", "U87P", u87, "pu do TAP", u87 * i1, "A pri (AT)", "Falta passante e inrush", "OK")
        x.add(F, "Restrição 2ª harmônica", "PCT2", cc["k87t_h2"], "%", cc["k87t_h2"], "%", "Bloqueio por inrush", "OK")
        x.add(F, "Restrição 5ª harmônica", "PCT5", cc["k87t_h5"], "%", cc["k87t_h5"], "%", "Bloqueio por sobre-excitação", "OK")
        x.add(F, "Compensação de fase", "W1CTC/W2CTC", comp_txt, "—", comp_txt, "—", f"{lig1} / {lig2}", "OK")
        x.card("87T (TAP AT / BT)", f"{fmt(tap1,2)} / {fmt(tap2,2)} A", f"O87P {fmt(o87,2)} pu · SLP {fmt(slope1,0)}/{fmt(slope2,0)} %")
        x.tabela("Função 87T — enrolamentos", ["Enrolamento", "Tensão (kV)", "I nominal (A pri)", "RTC", "I sec (A)", "TAP (A)"],
                 [["AT", fmt(v1, 1), fmt(i1, 1), fmt(r1, 1), fmt(s1, 3), fmt(tap1, 3)], ["BT", fmt(v2, 1), fmt(i2, 1), fmt(r2, 1), fmt(s2, 3), fmt(tap2, 3)]])
        dados["p87t"] = {"tap1": tap1, "tap2": tap2, "o87p": o87, "slope1": slope1, "slope2": slope2, "irs1": cc["k87t_irs1_pu"], "u87p": u87,
                         "mism_pct": mism, "rel_tap": rel_tap, "i1": i1, "i2": i2, "i_pass_pu": i_pass_pu}
        if modo_conf:
            x.conferir("87T O87P (pu)", num(d, "ex_87t_o87p"), o87 - 1e-9, None, "pu", "Mínimo calculado")
            x.conferir("87T Slope 1 (%)", num(d, "ex_87t_slp1"), slope1 - 1e-9, None, "%", "Mínimo calculado")
            x.conferir("87T Slope 2 (%)", num(d, "ex_87t_slp2"), slope1 + 1e-9, None, "%", "Deve superar o Slope 1")
            x.conferir("87T U87P (pu)", num(d, "ex_87t_u87p"), u87 - 1e-9, None, "pu", "Mínimo calculado")

    # ------------------------------------------------------------------ 87L
    if "87L" in sel:
        sec = "Função 87L"
        q, in_a = num(d, "q_cap_mvar"), num(d, "in_sec_diff_a", 1.0)
        i_cap = q * 1e3 / (math.sqrt(3) * vn)
        pmin = max(cc["k87l_cap"] * i_cap, cc["k87l_pk_pu"] * in_a * rtc)
        rec = sobe(pmin, cc["k87l_passo_a"])
        pmax = icc_min * 1e3 / cc["k87l_sens"] if icc_min > 0 else 0.0
        ok = pmax == 0 or rec <= pmax
        x.passo(sec, "Corrente capacitiva da LT", r"I_{cap} = \frac{Q_{c} \cdot 1000}{\sqrt{3} \cdot V_{n}}",
                rf"I_{{cap}} = \frac{{{fq(q,1)} \cdot 1000}}{{\sqrt{{3}} \cdot {fq(vn,1)}}} = {fq(i_cap,1)}\ \mathrm{{A}}")
        x.passo(sec, "Pickup diferencial", r"I_{pk} \ge \max\left( k_{c} \cdot I_{cap},\ k_{min} \cdot I_{n} \cdot RTC \right) \qquad I_{pk} \le \frac{I_{cc,min}}{k_{s}}",
                rf"I_{{pk}} \ge \max\left( {fq(cc['k87l_cap'])} \cdot {fq(i_cap,1)},\ {fq(cc['k87l_pk_pu'])} \cdot {fq(in_a,0)} \cdot {fq(rtc,1)} \right) = {fq(pmin,0)}\ \mathrm{{A}}"
                + (rf" \qquad I_{{pk}} \le \frac{{{fq(icc_min*1e3,0)}}}{{{fq(cc['k87l_sens'])}}} = {fq(pmax,0)}\ \mathrm{{A}}" if icc_min > 0 else "")
                + rf" \rightarrow {fq(rec,0)}\ \mathrm{{A}}")
        x.check("87L: pickup recomendado", f"k·Icap ≤ Ipk ≤ Icc,min/{fmt(cc['k87l_sens'],1)}", rec, pmax if pmax else "—", ok)
        x.check("87L: inclinação 2 > inclinação 1", "SLP2 > SLP1", cc["k87l_slope2_pct"], cc["k87l_slope1_pct"], cc["k87l_slope2_pct"] > cc["k87l_slope1_pct"])
        if icc_min == 0:
            x.alertas.append("Função 87L: sem casos de curto-circuito; o limite superior do pickup (sensibilidade) não foi verificado.")
        if not ok:
            x.alertas.append(f"Função 87L: o pickup mínimo ({fmt(rec,0)} A) supera Icc,min/k ({fmt(pmax,0)} A); avalie compensação de corrente capacitiva ou reveja o critério.")
        comp = "Sim" if i_cap >= 0.25 * rec else "Não"
        F = "87L — Diferencial de linha"
        x.add(F, "Pickup diferencial", "—", rec / rtc, "A sec", rec, "A pri", "Acima da corrente capacitiva e abaixo de Icc,mín/k", "OK" if ok else "REVISAR")
        x.add(F, "Inclinação 1", "—", cc["k87l_slope1_pct"], "%", cc["k87l_slope1_pct"], "%", "Critério (etapa 4)", "OK")
        x.add(F, "Inclinação 2", "—", cc["k87l_slope2_pct"], "%", cc["k87l_slope2_pct"], "%", "Critério (etapa 4)", "OK")
        x.add(F, "Ponto de joelho", "—", cc["k87l_irs_pu"] * in_a, "A sec", cc["k87l_irs_pu"] * in_a * rtc, "A pri", f"{fmt(cc['k87l_irs_pu'],1)} pu de In", "OK")
        x.add(F, "Compensação de corrente capacitiva", "—", comp, "—", comp, "—", "Habilitar se Icap ≥ 25 % do pickup", "OK")
        x.card("87L", f"{fmt(rec/rtc,2)} A sec", f"{fmt(rec,0)} A pri · Icap {fmt(i_cap,0)} A")
        dados["p87l"] = {"i_cap": i_cap, "rec_pri": rec, "rec_sec": rec / rtc, "max_pri": pmax, "slope1": cc["k87l_slope1_pct"],
                         "slope2": cc["k87l_slope2_pct"], "irs_pu": cc["k87l_irs_pu"], "in_pri": in_a * rtc, "viavel": ok, "comp_cap": comp}
        if modo_conf:
            x.conferir("87L pickup (A pri)", num(d, "ex_87l_pk_a"), pmin - 1e-9, pmax if pmax else None, "A", "Faixa de pickup")

    # ------------------------------------------------------------------ 87B
    if "87B" in sel:
        sec = "Função 87B"
        tipo = d.get("tipo_87b") or TIPOS_87B[0]
        n_tc, i_ext = num(d, "n_alim_87b", 6.0), num(d, "i_ext_max_ka")
        icc_bar = num(d, "icc_bar_min_ka")
        F = "87B — Diferencial de barra"
        if tipo.startswith("Alta"):
            r_ct, r_cab, vk, imag = num(d, "r_ct_sec_ohm"), num(d, "r_cabo_ohm"), num(d, "v_knee_v"), num(d, "i_mag_a")
            i_ext_sec = i_ext * 1e3 / rtc
            vset = cc["k87b_stab"] * i_ext_sec * (r_ct + r_cab)
            vset_r = sobe(vset, 1.0)
            x.passo(sec, "Tensão de ajuste (alta impedância)", r"V_{set} = k_{e} \cdot \frac{I_{ext}}{RTC} \cdot (R_{TC} + R_{cabo})",
                    rf"V_{{set}} = {fq(cc['k87b_stab'])} \cdot \frac{{{fq(i_ext*1e3,0)}}}{{{fq(rtc,1)}}} \cdot ({fq(r_ct)} + {fq(r_cab)}) = {fq(vset,1)}\ \mathrm{{V}} \rightarrow {fq(vset_r,0)}\ \mathrm{{V}}")
            i_rele = cc["k87b_i_rele_a"]
            r_est = vset_r / i_rele
            x.passo(sec, "Resistor estabilizador", r"R_{est} = \frac{V_{set}}{I_{rele}}",
                    rf"R_{{est}} = \frac{{{fq(vset_r,0)}}}{{{fq(i_rele,3)}}} = {fq(r_est,0)}\ \Omega")
            i_op = rtc * (i_rele + n_tc * imag)
            x.passo(sec, "Corrente primária de operação", r"I_{op} = RTC \cdot (I_{rele} + n \cdot I_{mag})",
                    rf"I_{{op}} = {fq(rtc,1)} \cdot ({fq(i_rele,3)} + {fq(n_tc,0)} \cdot {fq(imag,3)}) = {fq(i_op,0)}\ \mathrm{{A}}")
            ok_k = vk >= cc["k87b_knee"] * vset_r
            ok_s = icc_bar == 0 or (icc_bar * 1e3 / i_op) >= cc["k87b_sens"]
            x.check("87B: joelho do TC", f"Vk ≥ {fmt(cc['k87b_knee'],1)}·Vset", vk, cc["k87b_knee"] * vset_r, ok_k)
            x.check("87B: sensibilidade", f"Icc,mín/Iop ≥ {fmt(cc['k87b_sens'],1)}", (icc_bar * 1e3 / i_op) if icc_bar > 0 else "—", cc["k87b_sens"], ok_s)
            if not ok_k:
                x.alertas.append(f"Função 87B: a tensão de joelho do TC ({fmt(vk,0)} V) é menor que {fmt(cc['k87b_knee'],1)}·Vset ({fmt(cc['k87b_knee']*vset_r,0)} V); "
                                 "use TC de joelho maior, reduza a resistência do circuito ou revise a falta externa considerada.")
            if not ok_s:
                x.alertas.append("Função 87B: sensibilidade insuficiente para o menor curto na barra; reduza o número de TCs, a magnetização ou a tensão de ajuste.")
            if icc_bar == 0:
                x.alertas.append("Função 87B: menor curto na barra não informado; a sensibilidade não foi verificada.")
            st = "OK" if (ok_k and ok_s) else "REVISAR"
            x.add(F, "Tensão de ajuste", "—", vset_r, "V", vset_r, "V", "k·I_ext·(R_TC+R_cabo)", st)
            x.add(F, "Resistor estabilizador", "—", r_est, "Ω", r_est, "Ω", "Vset ÷ corrente do relé", "OK")
            x.add(F, "Corrente primária de operação", "—", i_op / rtc, "A sec", i_op, "A pri", "RTC·(I_rele + n·I_mag)", st)
            x.card("87B (alta Z)", f"Vset {fmt(vset_r,0)} V", f"Rest {fmt(r_est,0)} Ω · Iop {fmt(i_op,0)} A")
            dados["p87b"] = {"tipo": tipo, "vset": vset_r, "r_est": r_est, "i_op_pri": i_op, "vk": vk, "ok_knee": ok_k, "ok_sens": ok_s}
            if modo_conf:
                x.conferir("87B tensão de ajuste (V)", num(d, "ex_87b_vset_v"), vset - 1e-9, vk / cc["k87b_knee"], "V", "Entre Vset mínimo e Vk/k")
        else:
            in_a, i_car = num(d, "in_sec_diff_a", 1.0), num(d, "i_carga_barra_a")
            pmin = max(cc["k87b_pk_pu"] * in_a * rtc, cc["k87b_err_tc_pct"] / 100.0 * i_car)
            rec = sobe(pmin, cc["k87b_passo_a"])
            pmax = icc_bar * 1e3 / cc["k87b_sens"] if icc_bar > 0 else 0.0
            ok = pmax == 0 or rec <= pmax
            slope = cc["k87b_slope_pct"]
            ok_sl = slope >= cc["k87b_err_tc_pct"] + 10.0
            x.passo(sec, "Pickup diferencial (baixa impedância)", r"I_{pk} \ge \max\left( k_{min} \cdot I_{n} \cdot RTC,\ e_{TC} \cdot I_{carga} \right) \qquad I_{pk} \le \frac{I_{cc,min}}{k_{s}}",
                    rf"I_{{pk}} \ge \max\left( {fq(cc['k87b_pk_pu'])} \cdot {fq(in_a,0)} \cdot {fq(rtc,1)},\ {fq(cc['k87b_err_tc_pct']/100,2)} \cdot {fq(i_car,0)} \right) = {fq(pmin,0)}\ \mathrm{{A}}"
                    + (rf" \qquad I_{{pk}} \le \frac{{{fq(icc_bar*1e3,0)}}}{{{fq(cc['k87b_sens'])}}} = {fq(pmax,0)}\ \mathrm{{A}}" if icc_bar > 0 else "")
                    + rf" \rightarrow {fq(rec,0)}\ \mathrm{{A}}")
            x.check("87B: pickup recomendado", f"Ipk entre mínimo e Icc,mín/{fmt(cc['k87b_sens'],1)}", rec, pmax if pmax else "—", ok)
            x.check("87B: inclinação", "SLP ≥ erro de TC + 10 %", slope, cc["k87b_err_tc_pct"] + 10.0, ok_sl)
            if not ok:
                x.alertas.append(f"Função 87B: o pickup mínimo ({fmt(rec,0)} A) supera Icc,min/k ({fmt(pmax,0)} A); reveja a carga máxima da barra ou o critério.")
            if icc_bar == 0:
                x.alertas.append("Função 87B: menor curto na barra não informado; a sensibilidade não foi verificada.")
            x.add(F, "Pickup diferencial", "—", rec / rtc, "A sec", rec, "A pri", "Erro de TC com a carga máx. e piso de sensibilidade", "OK" if ok else "REVISAR")
            x.add(F, "Inclinação", "—", slope, "%", slope, "%", "Critério (etapa 4)", "OK" if ok_sl else "REVISAR")
            x.card("87B (baixa Z)", f"{fmt(rec/rtc,2)} A sec", f"{fmt(rec,0)} A pri · SLP {fmt(slope,0)} %")
            dados["p87b"] = {"tipo": tipo, "rec_pri": rec, "rec_sec": rec / rtc, "max_pri": pmax, "slope": slope, "viavel": ok}
            if modo_conf:
                x.conferir("87B pickup (A pri)", num(d, "ex_87b_pk_a"), pmin - 1e-9, pmax if pmax else None, "A", "Faixa de pickup")
    return x.pacote(dados)


def figuras(r: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.plots import AZUL, AZUL_ESCURO, AZUL_PALIDO, CINZA, CINZA_CLARO
    md = (r.get("modulos") or {}).get("f_diferencial") or {}
    out = []

    def caracteristica(o, s1, s2, irs, u, titulo, unid):
        fig, ax = plt.subplots(figsize=(6.0, 4.2), dpi=170)
        xs = [i * 0.05 for i in range(0, 261)]
        ys = []
        for xv in xs:
            y = max(o, s1 / 100.0 * xv) if xv <= irs else max(o, s1 / 100.0 * irs + s2 / 100.0 * (xv - irs))
            ys.append(min(y, u))
        ax.fill_between(xs, ys, [u] * len(xs), color=AZUL_PALIDO, label="Região de operação")
        ax.plot(xs, ys, color=AZUL_ESCURO, lw=2, label="Característica percentual")
        ax.axhline(u, color=CINZA, lw=1.5, ls="--", label="Instantâneo")
        ax.set_xlim(0, 13); ax.set_ylim(0, min(u * 1.2, 14))
        ax.set_xlabel(f"Corrente de restrição ({unid})"); ax.set_ylabel(f"Corrente diferencial ({unid})")
        ax.grid(True, color=CINZA_CLARO, lw=0.6)
        ax.set_title(titulo, color=AZUL_ESCURO, fontsize=10)
        ax.legend(fontsize=7, loc="upper left", frameon=False)
        fig.tight_layout()
        return fig

    p = md.get("p87t")
    if p:
        out.append(("Característica diferencial percentual — função 87T",
                    caracteristica(p["o87p"], p["slope1"], p["slope2"], p["irs1"], p["u87p"], "87T: característica percentual", "pu do TAP")))
    q = md.get("p87l")
    if q and q["in_pri"] > 0:
        o = q["rec_pri"] / q["in_pri"]
        out.append(("Característica diferencial percentual — função 87L",
                    caracteristica(o, q["slope1"], q["slope2"], q["irs_pu"], 12.0, "87L: característica percentual", "pu de In")))
    return out
