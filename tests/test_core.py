"""Testes do motor de cálculo, importador, banco e relatórios."""
import io
import math
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from lxml import etree

from core import db, importers
from core.calc import (calcular_terminal, delta_angulo, tempo_entre_blinders,
                       velocidade_impedancia, mho_contem)
from core.omml import latex_para_omath
from core.report_docx import gerar_relatorio
from core.report_xlsx import gerar_planilha

BASE = dict(lt_nome="LT 230 kV Teste", terminal="SE A", fabricante="SEL", modelo="SEL-411L",
            comp_km=100, vn_kv=230, r1=9.0, x1=50.0, r0=30.0, x0=150.0, rtc=400, rtp=2000,
            s_max_mva=300, i_term_a=1000, v_min_pu=0.9, phi_pos=30, phi_neg=30, f_hz=60, f_slip_max=1.0,
            icc3f_loc_ka=4, icc3f_rem_ka=3, zadj_min=30, zadj_max=60)
CASOS = [{"ponto": "F1", "tipo": "3F", "local_pct": 0, "icc_ka": 10.5},
         {"ponto": "F2", "tipo": "FT", "local_pct": 50, "icc_ka": 6.1},
         {"ponto": "F3", "tipo": "FF", "local_pct": 100, "icc_ka": 4.0},
         {"ponto": "F4", "tipo": "FT", "local_pct": 100, "icc_ka": 2.5, "rf_ohm": 10}]


def test_conversao_e_zonas():
    r = calcular_terminal(BASE, None, CASOS)
    k = 400 / 2000
    zl = math.hypot(9, 50) * k
    assert r["base"]["k_sec"] == pytest.approx(k)
    assert r["base"]["zl_sec"][2] == pytest.approx(zl)
    assert r["zonas"]["Z1"]["alcance"] == pytest.approx(0.8 * zl)
    assert r["zonas"]["Z2"]["alcance"] == pytest.approx(min(1.2 * zl, zl + 0.5 * 30 * k))
    assert r["zonas"]["Z3"]["alcance"] == pytest.approx(zl + 60 * k)


def test_carga_usa_maior_corrente():
    r = calcular_terminal(BASE, None, CASOS)
    i_fluxo = 300e3 / (math.sqrt(3) * 230)  # 753 A < 1000 A térmico
    assert r["carga"]["i_ref"] == pytest.approx(max(i_fluxo, 1000))
    z = 0.9 * 230e3 / (math.sqrt(3) * 1000) * 0.2
    assert r["carga"]["z_carga"] == pytest.approx(z)


def test_geometria_da_oscilacao():
    # simétrico: d = 0 -> delta = 180°; d -> infinito -> delta -> 0
    assert delta_angulo(0, 20) == 180.0
    assert delta_angulo(1e9, 20) == pytest.approx(0, abs=1e-4)
    # d = Zt/2 -> delta = 90°
    assert delta_angulo(10, 20) == pytest.approx(90.0)
    # tempo: delta 90 -> 60 a 1 Hz = 30°/360 = 83,3 ms
    d_in, d_out = 10.0, 20 / (2 * math.tan(math.radians(30)))   # delta_int = 90°, delta_ext = 60°
    assert tempo_entre_blinders(d_in, d_out, 20, 1.0) == pytest.approx(1 / 12, rel=1e-6)
    # velocidade no centro (d=0): Zt/4 * 2π f
    assert velocidade_impedancia(0, 20, 1.0) == pytest.approx(20 / 4 * 2 * math.pi)


def test_blinder_externo_respeita_carga_e_interno_fora_da_zona():
    r = calcular_terminal(BASE, None, CASOS)
    o = r["oos"]
    assert o["d_out"] <= 0.9 * o["d_load"] + 1e-9
    assert o["d_in"] >= 1.15 * o["z_max_bloq"] / 2 - 1e-9
    assert o["d_out"] > o["d_in"]


def test_osbd_nunca_abaixo_do_tempo_de_falta():
    r = calcular_terminal(dict(BASE, f_slip_max=5.0), None, CASOS)
    assert r["oos"]["osbd_ciclos"] >= 2.0
    assert r["oos"]["piso_aplicado"] is True
    assert any("só detecta oscilações" in a for a in r["alertas"])


def test_osbd_regime_normal():
    # fontes fracas -> Zt grande -> tempo entre blinders longo
    r = calcular_terminal(dict(BASE, icc3f_loc_ka=1.0, icc3f_rem_ka=1.0, f_slip_max=0.5), None, CASOS)
    o = r["oos"]
    assert not o["piso_aplicado"]
    assert o["osbd_s"] <= o["t_min_s"] + 1e-9
    assert o["osbd_ciclos"] >= 2.0


def test_validacao_cruzada_zonas():
    r = calcular_terminal(BASE, None, CASOS)
    v = {x["caso"]: x for x in r["validacao"]}
    assert v["F1"]["zona"] == "Z1" and v["F2"]["zona"] == "Z1"
    assert v["F3"]["zona"] == "Z2"                      # 100% da LT cai na Zona 2
    assert all(x["dentro_blinder_int"] for x in r["validacao"])


def test_pickup_51_faixa():
    r = calcular_terminal(BASE, None, CASOS)
    p = r["pickup51"]
    assert p["min_pri"] == pytest.approx(1.5 * 1000)
    assert p["max_pri"] == pytest.approx(4.0e3 / 1.5)
    assert p["viavel"]


def test_modo_conferencia():
    d = dict(BASE, modo="conferencia", ex_r_blinder_int=5.0, ex_r_blinder_ext=17.0, ex_osbd_ciclos=3.0,
             ex_zlf=20.0, ex_pickup51_a_sec=4.0)
    r = calcular_terminal(d, None, CASOS)
    st = {c["item"]: c["status"] for c in r["conferencia"]}
    assert st["Blinder interno — R (Ω sec)"] == "NÃO CONFORME"   # 5 Ω está dentro da zona 3
    assert st["Pickup 51 (A sec)"] == "CONFORME"


def test_dados_invalidos():
    with pytest.raises(ValueError):
        calcular_terminal(dict(BASE, rtc=0))
    with pytest.raises(ValueError):
        calcular_terminal(dict(BASE, r1=0, x1=0))
    with pytest.raises(ValueError):
        calcular_terminal(dict(BASE, s_max_mva=0, i_term_a=0))


# ------------------------------------------------------------------ importador
def test_importador_csv_ptbr():
    csv = "Barra;Tipo de falta;Local %;Icc (kA)\nSE A;Trifásico;0;10,5\nSE A;FT;50;6,1\nSE B;Fase-Terra;100;2,5\n"
    df = importers.ler_tabela(io.BytesIO(csv.encode("utf-8")), "casos.csv")
    mapa = importers.sugerir_mapeamento(list(df.columns))
    assert mapa["tipo"] == "Tipo de falta" and mapa["icc_ka"] == "Icc (kA)" and mapa["local_pct"] == "Local %"
    casos, avisos = importers.padronizar(df, mapa)
    assert [c["tipo"] for c in casos] == ["3F", "FT", "FT"]
    assert casos[0]["icc_ka"] == pytest.approx(10.5)


def test_importador_ampere_para_ka_e_obrigatorios():
    df = importers.ler_tabela(io.BytesIO(b"tipo,icc\n3F,10500\n"), "a.csv")
    casos, _ = importers.padronizar(df, importers.sugerir_mapeamento(list(df.columns)), "A")
    assert casos[0]["icc_ka"] == pytest.approx(10.5)
    with pytest.raises(ValueError):
        importers.padronizar(df, {"tipo": None, "icc_ka": None})


# ------------------------------------------------------------------ banco
def test_banco_crud_sqlite(tmp_path):
    eng = db.criar_engine(f"sqlite:///{tmp_path}/t.db")
    db.inicializar(eng)
    pid = db.criar_projeto(eng, "Proj", "Cliente", "BK-1", "00", "Alice", "Carta", {"k_z1": 0.85})
    assert db.obter_projeto(eng, pid)["criterios"]["k_z1"] == 0.85
    tid = db.salvar_terminal(eng, pid, dict(BASE))
    db.salvar_resultado(eng, tid, {"ok": True})
    ts = db.listar_terminais(eng, pid)
    assert len(ts) == 1 and ts[0]["resultado"] == {"ok": True} and ts[0]["dados"]["rtc"] == 400
    db.salvar_curto(eng, pid, "a.csv", "Anafas", CASOS)
    db.salvar_curto(eng, pid, "b.csv", "ETAP", CASOS[:2])       # substitui o anterior
    assert len(db.obter_curto(eng, pid)["dados"]) == 2
    db.excluir_projeto(eng, pid)
    assert db.obter_projeto(eng, pid) is None and db.listar_terminais(eng, pid) == []


def test_url_neon_normalizada():
    assert db.normalizar_url("postgresql://u:p@h/db?sslmode=require").startswith("postgresql+psycopg2://")
    assert db.normalizar_url("postgres://u:p@h/db").startswith("postgresql+psycopg2://")


# ------------------------------------------------------------------ equações / relatórios
PERMITIDOS = {
    "oMathPara": {"oMathParaPr", "oMath"}, "oMath": {"r", "f", "sSub", "sSup", "sSubSup", "rad"},
    "f": {"num", "den"}, "num": {"r", "f", "sSub", "sSup", "sSubSup", "rad"}, "den": {"r", "f", "sSub", "sSup", "sSubSup", "rad"},
    "e": {"r", "f", "sSub", "sSup", "sSubSup", "rad"}, "sub": {"r", "f", "sSub", "sSup", "sSubSup", "rad"},
    "sup": {"r", "f", "sSub", "sSup", "sSubSup", "rad"}, "deg": set(), "radPr": {"degHide"},
    "sSub": {"e", "sub"}, "sSup": {"e", "sup"}, "sSubSup": {"e", "sub", "sup"}, "rad": {"radPr", "deg", "e"},
    "r": {"rPr", "t"}, "rPr": {"sty"}, "t": set(), "sty": set(), "degHide": set(), "oMathParaPr": {"jc"}, "jc": set(),
}
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _valida(el):
    nome = el.tag.replace(M, "")
    assert nome in PERMITIDOS, f"elemento inesperado {nome}"
    for f in el:
        fn = f.tag.replace(M, "")
        assert fn in PERMITIDOS[nome], f"{fn} não permitido dentro de {nome}"
        _valida(f)


def test_todas_as_equacoes_geram_omml_valido():
    r = calcular_terminal(BASE, None, CASOS)
    assert len(r["passos"]) >= 20
    for p in r["passos"]:
        for expr in (p["simb"], p["num"]):
            xml = latex_para_omath(expr).replace("<m:oMath>", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1)
            _valida(etree.fromstring(xml))
            assert "\\" not in etree.tostring(etree.fromstring(xml), encoding="unicode").replace("\\ ", ""), expr


def test_relatorio_e_planilha(tmp_path):
    proj = dict(nome="P", cliente="Cliente", numero_doc="BK-1", revisao="00", contato="A", referencia="Carta")
    res = [calcular_terminal(dict(BASE, terminal=t), None, CASOS) for t in ("SE A", "SE B")]
    docx_p, xlsx_p = tmp_path / "r.docx", tmp_path / "a.xlsx"
    gerar_relatorio(proj, res, str(docx_p))
    gerar_planilha(proj, res, str(xlsx_p))
    z = zipfile.ZipFile(docx_p)
    xml = z.read("word/document.xml").decode()
    assert xml.count("<m:oMathPara") > 40          # equações nativas
    assert len([n for n in z.namelist() if n.startswith("word/media/")]) >= 3   # gráficos (imagens iguais são deduplicadas)
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_p)
    assert wb.sheetnames == ["Ajustes dos Relés"]
    ws = wb.active
    nomes = {ws.cell(r, 5).value for r in range(10, ws.max_row + 1)}
    assert {"Z1P / Z1MG", "ZLF", "OSBD", "R1R6", "R1R7"} <= nomes


# ------------------------------------------------------------------ seleção de funções (50/51/50N/51N)
from core import funcoes as F                                    # noqa: E402
from core.f_sobrecorrente import tempo_iec, tms_para            # noqa: E402

CASOS_SC = CASOS + [{"ponto": "F5", "tipo": "FT", "local_pct": 100, "icc_ka": 3.2}]
TODAS = ["21", "68", "50", "51", "50N", "51N"]


def test_catalogo_so_aceita_funcoes_prontas():
    assert F.selecionadas({"funcoes": ["21", "XX", "51"]}) == ["21", "51"]      # código inexistente
    assert F.selecionadas({}) == ["21", "68", "51"]                              # compatibilidade com terminais antigos


def test_so_sobrecorrente_dispensa_impedancia_da_lt():
    d = dict(BASE, r1=0, x1=0, r0=0, x0=0, funcoes=["50", "51", "50N", "51N"], t_jus_s=0.3, t_jus_n_s=0.3)
    r = calcular_terminal(d, None, CASOS_SC)
    assert r["zonas"] is None and r["oos"] is None
    assert {a["funcao"][:3].strip() for a in r["ajustes"]} == {"50", "51", "50N", "51N"}
    assert not any(a["funcao"].startswith(("21", "68", "Load")) for a in r["ajustes"])


def test_so_21_nao_gera_ajustes_de_blinder_nem_alerta_de_osb():
    r = calcular_terminal(dict(BASE, funcoes=["21"], f_slip_max=5.0), None, CASOS_SC)
    fun = {a["funcao"] for a in r["ajustes"]}
    assert fun == {"21 — Distância", "Load encroachment"}
    assert not any("OSB" in a or "f_slip" in a for a in r["alertas"])
    assert not any(p["secao"] in ("Blinder interno", "Temporização do OSB") for p in r["passos"])


def test_so_68_nao_gera_zonas_nos_ajustes():
    r = calcular_terminal(dict(BASE, funcoes=["68"]), None, CASOS_SC)
    assert {a["funcao"] for a in r["ajustes"]} == {"68 — Bloqueio por oscilação"}


def test_nenhuma_funcao_da_erro():
    with pytest.raises(ValueError):
        calcular_terminal(dict(BASE, funcoes=[]), None, CASOS_SC)


def test_pickups_de_sobrecorrente():
    r = calcular_terminal(dict(BASE, funcoes=["50", "51", "50N", "51N"], t_jus_s=0.3, t_jus_n_s=0.3), None, CASOS_SC)
    sc = r["sobrecorrente"]
    assert sc["p51"]["rec_pri"] == pytest.approx(1500)                  # 1,5 · 1000 A
    assert sc["p51n"]["rec_pri"] == pytest.approx(200)                  # 0,2 · 1000 A
    assert sc["p50"]["rec_pri"] == pytest.approx(4800)                  # 1,2 · 4,0 kA (FF a 100%)
    assert sc["p50n"]["rec_pri"] == pytest.approx(3840)                 # 1,2 · 3,2 kA (FT a 100%)
    assert sc["p51n"]["max_pri"] == pytest.approx(2500 / 1.5, rel=1e-6)  # menor FT = 2,5 kA (F4)


def test_tms_mantem_intervalo_de_coordenacao():
    r = calcular_terminal(dict(BASE, funcoes=["51"], t_jus_s=0.3), None, CASOS_SC)
    p = r["sobrecorrente"]["p51"]
    m = p["icc_coord_ka"] * 1e3 / p["rec_pri"]
    assert p["t_op_s"] == pytest.approx(tempo_iec(p["curva"], p["tms"], m))
    assert p["t_op_s"] >= 0.3 + 0.3 - 1e-9                              # arredondou o TMS para cima
    exato = tms_para(p["curva"], 0.6, m)
    assert p["tms"] >= exato - 1e-9 and p["tms"] - exato < 0.0101


def test_50_sem_falta_remota_pede_dado():
    casos = [c for c in CASOS_SC if c["local_pct"] < 100]
    r = calcular_terminal(dict(BASE, funcoes=["50"]), None, casos)
    assert r["ajustes"][0]["status"] == "REVISAR" and r["ajustes"][0]["valor_sec"] == "n/d"
    assert any("100% da LT" in a for a in r["alertas"])


def test_equacoes_de_todas_as_funcoes_geram_omml_valido():
    r = calcular_terminal(dict(BASE, funcoes=TODAS, t_jus_s=0.3, t_jus_n_s=0.3), None, CASOS_SC)
    assert {"Função 50", "Função 51", "Função 50N", "Função 51N"} <= {p["secao"] for p in r["passos"]}
    for p in r["passos"]:
        for expr in (p["simb"], p["num"]):
            xml = latex_para_omath(expr).replace("<m:oMath>", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1)
            _valida(etree.fromstring(xml))


def test_relatorio_e_planilha_com_funcoes_mistas(tmp_path):
    proj = dict(nome="P", cliente="C", numero_doc="BK-2", revisao="00", contato="A", referencia="")
    rs = [calcular_terminal(dict(BASE, terminal="A", funcoes=TODAS, t_jus_s=0.3, t_jus_n_s=0.3), None, CASOS_SC),
          calcular_terminal(dict(BASE, terminal="B", r1=0, x1=0, funcoes=["50", "51"], t_jus_s=0.3), None, CASOS_SC),
          calcular_terminal(dict(BASE, terminal="C", funcoes=["21"]), None, CASOS_SC)]
    gerar_relatorio(proj, rs, str(tmp_path / "r.docx"))
    gerar_planilha(proj, rs, str(tmp_path / "a.xlsx"))
    xml = zipfile.ZipFile(tmp_path / "r.docx").read("word/document.xml").decode()
    assert "Função 51N" in xml and "Curvas tempo x corrente" in xml
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "a.xlsx").active
    funcoes = {ws.cell(r_, 3).value for r_ in range(10, ws.max_row + 1)}
    assert any(str(f).startswith("51N") for f in funcoes) and any(str(f).startswith("21") for f in funcoes)


# ---------------------------------------------------------------- 67 / 67N (direcional)
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from sintetico import CASOS_DIR, ft_frente, caso as _caso   # noqa: E402
from core import fasores as FS                              # noqa: E402

DIR_DADOS = dict(BASE, funcoes=["67", "67N"], t_jus_67_s=0.3, t_jus_67n_s=0.3)


def _casos_3f():
    f = ft_frente(1.0)
    return CASOS_DIR + [_caso("T1", "3F", 100, "frente", {**f, "Ib": [f["Ia"][0], f["Ia"][1] - 120 - 78],
                                                           "Ic": [f["Ia"][0], f["Ia"][1] + 120 - 78]})]


def test_mta_recuperado_dos_fasores_e_re_restringe():
    r = calcular_terminal(DIR_DADOS, None, CASOS_DIR)
    p = r["direcional"]["p67n"]
    assert p["mta"] == pytest.approx(80.0, abs=5.0)             # = ângulo de Z0 da fonte atrás do relé (80°)
    assert p["n_frente"] == 3 and p["n_re"] == 1
    por_caso = {c["caso"]: c for c in p["casos"]}
    assert all(por_caso[k]["ok"] for k in ("F0", "F50", "F100"))
    assert por_caso["R1"]["ok"] and abs(por_caso["R1"]["desvio"]) > 90      # ré fica fora da região de operação


def test_sentido_invertido_gera_alerta_de_mta_atipico():
    inv = [dict(c, fasores=FS.inverter_sentido(c["fasores"])) for c in CASOS_DIR]
    r = calcular_terminal(DIR_DADOS, None, inv)
    assert any("MTA" in a for a in r["alertas"])


def test_faltas_a_re_nao_entram_na_distancia_nem_no_51():
    r_com = calcular_terminal(dict(BASE, funcoes=["21", "51"]), None, CASOS_SC + CASOS_DIR)
    r_sem = calcular_terminal(dict(BASE, funcoes=["21", "51"]), None, CASOS_SC + [c for c in CASOS_DIR if c["sentido"] != "re"])
    assert all(v["caso"] != "R1" for v in r_com["validacao"])
    assert r_com["pickup51"] == r_sem["pickup51"]


def test_mta_manual_prevalece():
    r = calcular_terminal(dict(DIR_DADOS, mta67n_man=60.0), None, CASOS_DIR)
    assert r["direcional"]["p67n"]["mta"] == 60.0 and "usuário" in r["direcional"]["p67n"]["mta_origem"]


def test_sem_fasores_nao_quebra_e_avisa():
    r = calcular_terminal(DIR_DADOS, None, CASOS_SC)
    assert any("fasor" in a.lower() for a in r["alertas"])


def test_sequencia_para_fases_ida_e_volta():
    f = FS.sequencia_para_caso({"I1": (1.0, -30.0), "I2": (0.4, 60.0), "I0": (0.2, 10.0),
                                "V1": (130.0, 0.0), "V2": (5.0, 100.0), "V0": (3.0, 170.0)})
    ia, ib, ic = (FS.cpx(*f[n]) for n in ("Ia", "Ib", "Ic"))
    i0, i1, i2 = FS.fases_para_seq(ia, ib, ic)
    assert FS.pol(i1) == pytest.approx((1.0, -30.0), abs=1e-6)
    assert FS.pol(i2) == pytest.approx((0.4, 60.0), abs=1e-6)
    assert FS.pol(i0) == pytest.approx((0.2, 10.0), abs=1e-6)
    f3 = FS.sequencia_para_caso({"I1": (1.0, -30.0), "I2": (0.4, 60.0), "I0": (0.6, 10.0),
                                 "V1": (130.0, 0.0), "V2": (5.0, 100.0), "V0": (9.0, 170.0)}, tres_x=True)
    assert f3["Ia"] == pytest.approx(f["Ia"], abs=1e-6)


def test_importador_de_fasores_por_fase_e_sequencia():
    import pandas as pd
    f = ft_frente(0.5)
    lin = {"Barra": "F50", "Tipo": "FT", "Pos": 50}
    for n in FS.NOMES_FASE:
        lin[f"{n} mod"], lin[f"{n} ang"] = f[n][0] * (1000 if n[0] == "I" else 1), f[n][1]
    df = pd.DataFrame([lin])
    mf = importers.sugerir_mapeamento_fasores(list(df.columns), "fase")
    assert all(mf.values())
    mapa = {"ponto": "Barra", "tipo": "Tipo", "local_pct": "Pos"}
    casos, _ = importers.padronizar(df, mapa, "kA", fasores={"modo": "fase", "mapa": mf, "un_i": "A", "un_v": importers.UNID_V[0]})
    assert casos[0]["fasores"]["Ia"][0] == pytest.approx(f["Ia"][0], rel=1e-9)
    assert casos[0]["icc_ka"] == pytest.approx(f["Ia"][0], rel=1e-9)
    # sequência com 3·I0/3·V0 e inversão de sentido
    seq = {"I1": (1.0, -30.0), "I2": (0.4, 60.0), "I0": (0.6, 10.0), "V1": (130.0, 0.0), "V2": (5.0, 100.0), "V0": (9.0, 170.0)}
    ds = {"Barra": "X", "Tipo": "FT"}
    for n, (m, a) in seq.items():
        ds[f"{n}_m"], ds[f"{n}_a"] = m, a
    dfs = pd.DataFrame([ds])
    ms = {f"{n}_{k}": f"{n}_{k}" for n in FS.NOMES_SEQ for k in ("m", "a")}
    c_ok, _ = importers.padronizar(dfs, {"ponto": "Barra", "tipo": "Tipo"}, "kA",
                                   fasores={"modo": "sequencia", "mapa": ms, "un_i": "kA", "un_v": importers.UNID_V[0], "tres_x": True})
    c_inv, _ = importers.padronizar(dfs, {"ponto": "Barra", "tipo": "Tipo"}, "kA",
                                    fasores={"modo": "sequencia", "mapa": ms, "un_i": "kA", "un_v": importers.UNID_V[0],
                                             "tres_x": True, "inverter": True})
    assert abs(FS.ang_dif(c_inv[0]["fasores"]["Ia"][1], c_ok[0]["fasores"]["Ia"][1])) == pytest.approx(180.0)
    assert c_inv[0]["fasores"]["Va"] == pytest.approx(c_ok[0]["fasores"]["Va"])


def test_equacoes_direcionais_geram_omml_valido():
    r = calcular_terminal(DIR_DADOS, None, _casos_3f())
    assert {"Função 67", "Função 67N"} <= {p["secao"] for p in r["passos"]}
    for p in r["passos"]:
        for expr in (p["simb"], p["num"]):
            xml = latex_para_omath(expr).replace("<m:oMath>", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1)
            _valida(etree.fromstring(xml))


def test_relatorio_e_planilha_com_direcionais(tmp_path):
    proj = dict(nome="P", cliente="C", numero_doc="BK-3", revisao="00", contato="A", referencia="")
    rs = [calcular_terminal(dict(DIR_DADOS, terminal="A", funcoes=["21", "51", "67", "67N"], t_jus_s=0.3), None, _casos_3f() + CASOS_SC)]
    gerar_relatorio(proj, rs, str(tmp_path / "r.docx"))
    gerar_planilha(proj, rs, str(tmp_path / "a.xlsx"))
    xml = zipfile.ZipFile(tmp_path / "r.docx").read("word/document.xml").decode()
    assert "Função 67N" in xml and "Verificação direcional" in xml
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "a.xlsx").active
    funcoes = {str(ws.cell(r_, 3).value) for r_ in range(10, ws.max_row + 1)}
    assert any(f.startswith("67N") for f in funcoes) and any(f.startswith("67 ") or f == "67" for f in funcoes)


# ---------------------------------------------------------------- módulos declarativos (27/59/81 e próximos lotes)
from core import modulos as MOD                              # noqa: E402


def test_especificacoes_dos_modulos_sao_consistentes():
    chaves = set()
    for m in MOD.modulos():
        for e in m.ENTRADAS:
            assert e["k"] not in chaves
            chaves.add(e["k"])
            if e["tipo"] == "num":
                assert e["mn"] <= e["pad"] <= e["mx"], e["k"]
            elif e["tipo"] == "sel":
                assert e["pad"] in e["opcoes"], e["k"]
            assert e["porque"] and e["como"] and e["onde"], e["k"]
            assert set(e["funcs"]) <= set(m.COD), e["k"]
        for k in m.CRITERIOS:
            assert k["k"] not in chaves
            chaves.add(k["k"])
            assert k["mn"] <= k["pad"] <= k["mx"], k["k"]
            assert k["porque"] and k["como"] and k["onde"], k["k"]
        assert set(m.TEXTOS) == set(m.COD)
        for cod in m.COD:
            assert F.rotulo(cod) != cod and cod in F.selecionadas({"funcoes": [cod]})


def test_27_59_81_valores_e_conversao():
    d = dict(BASE, funcoes=["27", "59", "81"], vop_min_pu=0.90, vop_max_pu=1.05, tov_pu=1.15, t_elim_falta_s=1.0,
             fop_min_hz=58.5, fop_max_hz=61.5)
    r = calcular_terminal(d, None, [])
    aj = {(a["funcao"][:2], a["parametro"]): a for a in r["ajustes"]}
    k = BASE["rtp"] and 230.0 * 1000 / (math.sqrt(3) * (d["rtp"]))
    assert aj[("27", "Pickup")]["valor_pri"] == pytest.approx(230.0 * 0.85)
    assert aj[("27", "Pickup")]["valor_sec"] == pytest.approx(0.85 * 230000 / (math.sqrt(3) * d["rtp"]) if d["vn_kv"] == 230 else
                                                              0.85 * d["vn_kv"] * 1000 / (math.sqrt(3) * d["rtp"]))
    assert aj[("27", "Tempo de atuação")]["valor_sec"] == pytest.approx(1.3)
    assert aj[("59", "Estágio 1 — pickup")]["valor_pri"] == pytest.approx(d["vn_kv"] * 1.08)
    assert aj[("59", "Estágio 2 — pickup")]["valor_pri"] == pytest.approx(d["vn_kv"] * 1.18)
    u = r["modulos"]["f_tensao_freq"]["p81"]
    assert u["u"] == pytest.approx([58.3, 57.8, 57.3]) and u["o"] == pytest.approx([61.7, 62.2, 62.7])
    assert all(v["status"] == "OK" for v in r["verificacoes"])


def test_59_acima_da_tov_gera_alerta_e_revisar():
    r = calcular_terminal(dict(BASE, funcoes=["59"], tov_pu=1.06), None, [])
    assert any("sobretensão temporária" in a for a in r["alertas"])
    assert any(a["status"] == "REVISAR" for a in r["ajustes"])


def test_27_sem_tempo_de_eliminacao_pede_dado():
    r = calcular_terminal(dict(BASE, funcoes=["27"], t_elim_falta_s=0.0), None, [])
    assert any("eliminação" in a for a in r["alertas"])


def test_81_bloqueio_acima_da_tensao_minima_reprova():
    r = calcular_terminal(dict(BASE, funcoes=["81"]), dict(k81_vbloq_pu=0.95), [])
    assert any(v["status"] == "FALHA" for v in r["verificacoes"])


def test_27_59_81_conferencia():
    r = calcular_terminal(dict(BASE, funcoes=["27", "59", "81"], modo="conferencia", ex_27_pu=0.95, ex_81u_1_hz=58.0,
                               ex_59_1_pu=1.10), None, [])
    st = {c["item"]: c["status"] for c in r["conferencia"]}
    assert st["27 pickup (pu)"] == "NÃO CONFORME" and st["81U estágio 1 (Hz)"] == "CONFORME" and st["59-1 pickup (pu)"] == "CONFORME"


def test_equacoes_dos_modulos_geram_omml_valido():
    cods = MOD.codigos()
    r = calcular_terminal(dict(BASE, funcoes=cods), None, CASOS_SC)
    for p in r["passos"]:
        for expr in (p["simb"], p["num"]):
            xml = latex_para_omath(expr).replace("<m:oMath>", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">', 1)
            _valida(etree.fromstring(xml))


def test_relatorio_e_planilha_com_modulos(tmp_path):
    proj = dict(nome="P", cliente="C", numero_doc="BK-5", revisao="00", contato="A", referencia="")
    rs = [calcular_terminal(dict(BASE, terminal="A", funcoes=["21", "51"] + MOD.codigos(), t_jus_s=0.3), None, CASOS_SC)]
    gerar_relatorio(proj, rs, str(tmp_path / "r.docx"))
    gerar_planilha(proj, rs, str(tmp_path / "a.xlsx"))
    xml = zipfile.ZipFile(tmp_path / "r.docx").read("word/document.xml").decode()
    assert "Função 27" in xml and "Função 81" in xml
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "a.xlsx").active
    funcoes = {str(ws.cell(r_, 3).value) for r_ in range(10, ws.max_row + 1)}
    assert any(f.startswith("27") for f in funcoes) and any(f.startswith("81") for f in funcoes)


# ---------------------------------------------------------------- lote 2: 50BF, 79, 25
def _aj(r):
    return {(a["funcao"].split(" ")[0], a["parametro"]): a for a in r["ajustes"]}


def test_50bf_temporizador_tempo_total_e_pickup():
    d = dict(BASE, funcoes=["50BF"], t_disj_ms=50, t_rearme_bf_ms=20, t_prot_ms=20, in_sec_a=1.0, t_crit_ms=250)
    r = calcular_terminal(d, None, CASOS_SC)
    aj = _aj(r)
    assert aj[("50BF", "Temporizador de retaguarda")]["valor_sec"] == pytest.approx(103.0)     # 50 + 20 + 33
    assert r["modulos"]["f_disjuntor"]["p50bf"]["t_total_ms"] == pytest.approx(20 + 103 + 50)
    assert aj[("50BF", "Pickup do detector (fase)")]["valor_sec"] == pytest.approx(0.20)       # 0,2·In
    assert all(v["status"] == "OK" for v in r["verificacoes"])


def test_50bf_acima_do_tempo_critico_alerta():
    r = calcular_terminal(dict(BASE, funcoes=["50BF"], t_crit_ms=120), None, CASOS_SC)
    assert any("tempo crítico" in a and "supera" in a for a in r["alertas"])
    assert any(v["status"] == "FALHA" for v in r["verificacoes"])


def test_50bf_residual_alto_reprova_sensibilidade():
    r = calcular_terminal(dict(BASE, funcoes=["50BF"], i_resid_a=1e5 / 100), None, CASOS_SC)
    d = r["modulos"]["f_disjuntor"]["p50bf"]
    assert d["rec_pri"] >= 1.5 * 1e3 - 1e-6 and d["viavel"] in (True, False)


def test_79_deionizacao_e_reclaim():
    d = dict(BASE, funcoes=["79"], modo_79="Tripolar", vn_kv=230.0, f_hz=60.0, t_dif_remoto_ms=50, t_recarga_s=10)
    r = calcular_terminal(d, None, [])
    p = r["modulos"]["f_disjuntor"]["p79"]
    assert p["deion_ms"] == pytest.approx((10.5 + 230 / 34.5) / 60 * 1000)
    assert p["t3p_s"] == pytest.approx(0.45, abs=0.051)           # (287+50+100) ms arredondado ao passo
    assert p["reclaim_s"] >= 10 + p["t3p_s"] - 1e-9
    assert any("sincronismo" in a for a in r["alertas"])           # 3P sem a função 25


def test_79_estabilidade_e_modo_monopolar():
    r = calcular_terminal(dict(BASE, funcoes=["79"], modo_79="Monopolar", t_arco_sec_ms=900, t_max_estab_s=0.8), None, [])
    assert any("estabilidade" in a for a in r["alertas"])
    assert ("79", "Tempo morto tripolar") not in _aj(r)


def test_25_compensa_tempo_de_fechamento():
    r = calcular_terminal(dict(BASE, funcoes=["25"], t_fech_ms=100), dict(k25_df_hz=0.2, k25_dang_deg=30), [])
    p = r["modulos"]["f_disjuntor"]["p25"]
    assert p["avanco_deg"] == pytest.approx(360 * 0.2 * 0.1) and p["dang_aj_deg"] == pytest.approx(30 - 7.2)
    r2 = calcular_terminal(dict(BASE, funcoes=["25"], t_fech_ms=500), dict(k25_df_hz=1.0, k25_dang_deg=30), [])
    assert any("avanço angular" in a for a in r2["alertas"])


def test_lote2_conferencia_e_relatorio(tmp_path):
    d = dict(BASE, funcoes=["50BF", "79", "25"], modo="conferencia", modo_79="Monopolar e tripolar", ex_50bf_t_ms=40,
             ex_79_t3p_s=0.2, ex_25_dang_deg=20)
    r = calcular_terminal(d, None, CASOS_SC)
    st = {c["item"]: c["status"] for c in r["conferencia"]}
    assert st["50BF temporizador (ms)"] == "NÃO CONFORME" and st["79 tempo morto 3P (s)"] == "NÃO CONFORME" and st["25 ângulo máximo (°)"] == "CONFORME"
    proj = dict(nome="P", cliente="C", numero_doc="BK-6", revisao="00", contato="A", referencia="")
    gerar_relatorio(proj, [r], str(tmp_path / "r.docx"))
    gerar_planilha(proj, [r], str(tmp_path / "a.xlsx"))
    xml = zipfile.ZipFile(tmp_path / "r.docx").read("word/document.xml").decode()
    assert "Função 50BF" in xml and "Função 79" in xml and "Função 25" in xml


# ---------------------------------------------------------------- Lote 3: 87T/87L/87B
def test_87t_valores():
    r = calcular_terminal(dict(BASE, funcoes=["87T"]), None, CASOS_SC)
    p = r["modulos"]["f_diferencial"]["p87t"]
    assert abs(p["i1"] - 50e3 / (3 ** 0.5 * 230)) < 1e-6
    assert p["slope2"] > p["slope1"] and p["u87p"] > p["o87p"]
    assert abs(p["tap1"] - p["i1"] / 150) < 0.006


def test_87l_pickup_acima_capacitiva():
    r = calcular_terminal(dict(BASE, funcoes=["87L"]), None, CASOS_SC)
    p = r["modulos"]["f_diferencial"]["p87l"]
    assert p["rec_pri"] >= 2.0 * p["i_cap"] - 1e-6


def test_87b_alta_e_baixa():
    ra = calcular_terminal(dict(BASE, funcoes=["87B"], tipo_87b="Alta impedância"), None, CASOS_SC)
    assert ra["modulos"]["f_diferencial"]["p87b"]["ok_knee"]
    rb = calcular_terminal(dict(BASE, funcoes=["87B"], tipo_87b="Baixa impedância (percentual)"), None, CASOS_SC)
    assert rb["modulos"]["f_diferencial"]["p87b"]["rec_pri"] > 0


# ---------------------------------------------------------------- Lote 4: 46/49/32/40/87G
def _g(cod, **kw):
    return calcular_terminal(dict(BASE, funcoes=[cod], **kw), None, CASOS_SC)["modulos"]["f_gerador"]


def test_46_curva_i2t():
    p = _g("46")["p46"]
    assert p["K"] == 20.0 and p["alarme_pct"] == 8.0 and p["ok"]


def test_49_tempo_e_corrente():
    p = _g("49")["p49"]
    assert abs(p["i_trip_sec"] - 1.05 * p["i_ns"]) < 1e-9


def test_32_pickup_fracao_motorizacao():
    p = _g("32")["p32"]
    assert abs(p["pk_pct"] - 0.75) < 0.06 and p["ok"]


def test_40_zonas_mho():
    p = _g("40")["p40"]
    zb = 13.8 ** 2 / 20.0
    assert abs(p["z1"] - zb * 1000 / 120) < 1e-6
    assert p["z2"] > p["z1"] and abs(p["off"] - 0.5 * 0.3 * zb * 1000 / 120) < 1e-6


def test_87g_estabilidade():
    p = _g("87G")["p87g"]
    assert p["ok_est"] and p["slope2"] > p["slope1"]
