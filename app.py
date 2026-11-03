"""BK Proteção Sistêmica — estudo de oscilação de potência, blinders, load encroachment e função 51.

Execução:  streamlit run app.py
Banco:     Neon (PostgreSQL) via DATABASE_URL em .streamlit/secrets.toml ou variável de ambiente.
"""
from __future__ import annotations

import io
import os
import traceback

import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

from core import db, funcoes as F, importers, modulos as MOD
from core.f_sobrecorrente import CURVAS
from core.calc import CRITERIOS_PADRAO, DADOS_PADRAO, calcular_terminal, fmt
from core import fasores as FS
from core.plots import grafico_curvas_sobrecorrente, grafico_direcional, grafico_rx, grafico_tempo_slip
from core.report_docx import gerar_relatorio
from core.report_xlsx import gerar_planilha

st.set_page_config(page_title="BK Proteção Sistêmica", page_icon="⚡", layout="wide",
                   initial_sidebar_state="expanded")

AZUL_ESCURO, AZUL, AZUL_PALIDO, CINZA = "#1F3864", "#1F4E9C", "#DCE6F5", "#7F7F7F"

CSS = f"""
<style>
:root {{ --azul-escuro:{AZUL_ESCURO}; --azul:{AZUL}; --palido:{AZUL_PALIDO}; --cinza:#EEF1F6; }}
.block-container {{ padding-top: 1.4rem; max-width: 1280px; }}
[data-testid="stSidebar"] {{ background: var(--azul-escuro); }}
[data-testid="stSidebar"] * {{ color: #FFFFFF !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 6px 8px; border-radius: 6px; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,.10); }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.25); }}
h1, h2, h3 {{ color: var(--azul-escuro); }}
.bk-banner {{ background: linear-gradient(90deg, var(--azul-escuro), var(--azul)); color:#fff; padding:18px 24px;
  border-radius:10px; margin-bottom:18px; }}
.bk-banner h1 {{ color:#fff; margin:0; font-size:1.6rem; }}
.bk-banner p {{ margin:2px 0 0 0; opacity:.85; font-size:.92rem; }}
.bk-card {{ background:#fff; border:1px solid #D9D9D9; border-left:5px solid var(--azul); border-radius:8px;
  padding:12px 14px; height:100%; }}
.bk-card .t {{ color:{CINZA}; font-size:.78rem; text-transform:uppercase; letter-spacing:.03em; }}
.bk-card .v {{ color:var(--azul-escuro); font-size:1.35rem; font-weight:700; }}
.bk-card .s {{ color:{CINZA}; font-size:.78rem; }}
.bk-aviso {{ background:var(--cinza); border-left:5px solid {CINZA}; padding:10px 14px; border-radius:6px; margin:6px 0; }}
.bk-ok {{ color:{AZUL}; font-weight:700; }} .bk-fail {{ color:{AZUL_ESCURO}; font-weight:800; text-decoration:underline; }}
.stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"] {{ background:var(--azul); border-color:var(--azul); }}
div[data-testid="stMetricValue"] {{ color: var(--azul-escuro); }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------------ banco
def _url_banco() -> str:
    try:
        u = st.secrets.get("DATABASE_URL", "")
    except Exception:
        u = ""
    return u or os.environ.get("DATABASE_URL", "")


@st.cache_resource(show_spinner="Conectando ao banco…")
def obter_engine():
    url = _url_banco()
    erro = None
    if url:
        try:
            eng = db.criar_engine(url)
            db.inicializar(eng)
            return eng, None
        except Exception as e:                      # falha de rede/credencial: cai para SQLite local
            erro = f"{type(e).__name__}: {str(e).splitlines()[0][:220]}"
    eng = db.criar_engine("sqlite:///bk_protecao_local.db")
    db.inicializar(eng)
    return eng, erro


ENGINE, ERRO_BANCO = obter_engine()


def banner(titulo, sub=""):
    st.markdown(f'<div class="bk-banner"><h1>{titulo}</h1><p>{sub}</p></div>', unsafe_allow_html=True)


def card(col, titulo, valor, sub=""):
    col.markdown(f'<div class="bk-card"><div class="t">{titulo}</div><div class="v">{valor}</div>'
                 f'<div class="s">{sub}</div></div>', unsafe_allow_html=True)


def campo_spec(col, e, d0, tid):
    """Renderiza um campo declarado em um módulo de função (core/modulos.py)."""
    v = d0.get(e["k"], e["pad"])
    key = f"x_{tid}_{e['k']}"
    ajuda = f"{e['porque']}\n\nOnde buscar: {e['onde']}"
    if e["tipo"] == "sel":
        ops = list(e["opcoes"])
        return col.selectbox(e["rot"], ops, index=ops.index(v) if v in ops else 0, help=ajuda, key=key)
    if e["tipo"] == "bool":
        return col.checkbox(e["rot"], bool(v), help=ajuda, key=key)
    v = min(max(float(v), float(e["mn"])), float(e["mx"]))
    return col.number_input(e["rot"], float(e["mn"]), float(e["mx"]), v, float(e["passo"]), format=e["fmt"], help=ajuda, key=key)


def grupo_specs(specs, d0, tid, ncol=3):
    """Desenha os campos agrupados por seção e devolve {chave: valor}."""
    vals, grupos = {}, {}
    for e in specs:
        grupos.setdefault(e["grupo"], []).append(e)
    for g, lista in grupos.items():
        st.markdown(f"##### {g}")
        for i in range(0, len(lista), ncol):
            cols = st.columns(ncol)
            for col, e in zip(cols, lista[i:i + ncol]):
                vals[e["k"]] = campo_spec(col, e, d0, tid)
    return vals


# ------------------------------------------------------------------------ estado
ss = st.session_state
ss.setdefault("pid", None)
ss.setdefault("resultados", {})        # {terminal_id: resultado}
ss.setdefault("docx", None)
ss.setdefault("xlsx", None)


def projeto_atual():
    if not ss.pid:
        return None
    return db.obter_projeto(ENGINE, ss.pid)


def exige_projeto():
    p = projeto_atual()
    if not p:
        st.info("Selecione ou crie um projeto na etapa **1 · Projeto**.")
        st.stop()
    return p


def criterios_do(p):
    c = dict(CRITERIOS_PADRAO)
    c.update(p.get("criterios") or {})
    return c


# ------------------------------------------------------------------------ navegação
PAGINAS = ["1 · Projeto", "2 · Terminais e LT", "3 · Curto-circuito", "4 · Critérios", "5 · Cálculo", "6 · Relatórios"]
with st.sidebar:
    st.markdown("### ⚡ BK Proteção Sistêmica")
    st.caption("Barabach & Knopp Engenharia e Tecnologia")
    pagina = st.radio("Etapas", PAGINAS, label_visibility="collapsed")
    st.markdown("---")
    pa = projeto_atual()
    st.caption("Projeto ativo")
    st.markdown(f"**{pa['nome']}**" if pa else "_nenhum_")
    st.caption(f"Banco: {db.modo_banco(ENGINE)}")
    if ERRO_BANCO:
        st.warning("Neon indisponível — usando SQLite local. " + ERRO_BANCO)

# ------------------------------------------------------------------------ 1 · Projeto
if pagina == PAGINAS[0]:
    banner("Projeto", "Cadastre o cliente e o documento. Os dados ficam salvos no banco Neon.")
    projetos = db.listar_projetos(ENGINE)
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Projetos")
        opcoes = {f"#{p['id']} · {p['nome']}": p["id"] for p in projetos}
        if opcoes:
            rotulos = list(opcoes)
            idx = next((i for i, k in enumerate(rotulos) if opcoes[k] == ss.pid), 0)
            sel = st.selectbox("Abrir projeto existente", rotulos, index=idx)
            if st.button("Abrir", type="primary", width="stretch"):
                ss.pid = opcoes[sel]
                ss.resultados = {}
                ss.docx = ss.xlsx = None
                st.rerun()
        else:
            st.caption("Nenhum projeto cadastrado ainda.")
    with col2:
        st.subheader("Novo projeto")
        with st.form("novo_projeto", clear_on_submit=True):
            a, b = st.columns(2)
            nome = a.text_input("Nome do projeto *", placeholder="Estudo de ajustes de proteção — [nome do empreendimento]")
            cliente = b.text_input("Cliente", placeholder="ARCOVERDE Transmissão de Energia")
            c, d, e = st.columns(3)
            numero = c.text_input("Nº do documento", placeholder="BK-REL-2026-028")
            rev = d.text_input("Revisão", value="00")
            contato = e.text_input("Contato")
            ref = st.text_area("Documentos de referência do cliente", placeholder="Normas técnicas do cliente, procedimentos de rede, NTs aplicáveis", height=70)
            if st.form_submit_button("Criar projeto", type="primary"):
                if not nome.strip():
                    st.error("Informe o nome do projeto.")
                else:
                    ss.pid = db.criar_projeto(ENGINE, nome.strip(), cliente, numero, rev, contato, ref)
                    ss.resultados = {}
                    st.success("Projeto criado e aberto.")
                    st.rerun()
    p = projeto_atual()
    if p:
        st.markdown("---")
        st.subheader(f"Editar: {p['nome']}")
        with st.form("editar_projeto"):
            a, b = st.columns(2)
            nome = a.text_input("Nome do projeto", p["nome"])
            cliente = b.text_input("Cliente", p.get("cliente") or "")
            c, d, e = st.columns(3)
            numero = c.text_input("Nº do documento", p.get("numero_doc") or "")
            rev = d.text_input("Revisão", p.get("revisao") or "00")
            contato = e.text_input("Contato", p.get("contato") or "")
            ref = st.text_area("Documentos de referência", p.get("referencia") or "", height=70)
            if st.form_submit_button("Salvar alterações", type="primary"):
                db.atualizar_projeto(ENGINE, p["id"], nome=nome, cliente=cliente, numero_doc=numero,
                                     revisao=rev, contato=contato, referencia=ref)
                st.success("Projeto atualizado.")
                st.rerun()
        with st.expander("Excluir projeto"):
            ok = st.checkbox("Confirmo que quero excluir este projeto e todos os seus dados")
            if st.button("Excluir definitivamente", disabled=not ok):
                db.excluir_projeto(ENGINE, p["id"])
                ss.pid = None
                ss.resultados = {}
                st.rerun()

# ------------------------------------------------------------------------ 2 · Terminais
elif pagina == PAGINAS[1]:
    p = exige_projeto()
    banner("Terminais e dados da LT", f"Projeto: {p['nome']}")
    terms = db.listar_terminais(ENGINE, p["id"])
    if terms:
        df = pd.DataFrame([{"ID": t["id"], "LT": t["lt"], "Terminal": t["terminal"],
                            "Relé": f"{t['fabricante']} {t['modelo']}".strip(),
                            "Funções": ", ".join(F.selecionadas(t["dados"])),
                            "Trabalho": "Conferência" if t["modo"] == "conferencia" else "Novos ajustes",
                            "Calculado": "Sim" if t["resultado"] else "Não"} for t in terms])
        st.dataframe(df, hide_index=True, width="stretch")
    opcoes = {"➕ Novo terminal": None}
    opcoes.update({f"#{t['id']} · {t['lt']} — {t['terminal']}": t["id"] for t in terms})
    esc = st.selectbox("Terminal", list(opcoes))
    tid = opcoes[esc]
    atual = next((t for t in terms if t["id"] == tid), None)
    d0 = dict(DADOS_PADRAO)
    if atual:
        d0.update(atual["dados"])

    c1, c2, c3 = st.columns(3)
    modo = c1.selectbox("Trabalho a realizar", ["novo", "conferencia"], index=0 if d0["modo"] == "novo" else 1,
                        format_func=lambda x: "Calcular novos ajustes" if x == "novo" else "Conferir ajustes existentes")
    fabs = ["SEL", "GE MiCOM", "GE Multilin", "Siemens", "ABB", "Schneider", "Outro"]
    fab = c2.selectbox("Fabricante do relé", fabs, index=fabs.index(d0["fabricante"]) if d0["fabricante"] in fabs else 5)
    modo_z = c3.selectbox("Impedância da LT informada em", ["Ω totais da LT", "Ω/km (multiplica pelo comprimento)"])

    # ---- escolha das funções (fora do formulário: os campos abaixo se adaptam à seleção)
    codigos = [f["cod"] for f in F.prontas()]
    padrao_f = [x for x in (d0.get("funcoes") if d0.get("funcoes") is not None else F.PADRAO) if x in codigos]
    funcs = st.multiselect("Funções de proteção a ajustar neste relé", codigos, default=padrao_f,
                           format_func=F.rotulo, key=f"funcs_{tid}",
                           help="Só as funções marcadas entram no cálculo, no relatório e na planilha. "
                                "Os campos abaixo mostram apenas o que essas funções precisam.")
    dist = "21" in funcs or "68" in funcs
    usa_sc = F.usa_sobrecorrente(funcs)
    if funcs:
        precisa = [f"{f['cod']}: {f['entradas']}" for f in F.prontas() if f["cod"] in funcs]
        st.caption("Dados necessários — " + " | ".join(precisa))
    else:
        st.warning("Marque ao menos uma função.")
    with st.expander("Funções em desenvolvimento (roteiro)"):
        por_grupo = {}
        for f in F.em_desenvolvimento():
            por_grupo.setdefault(f["grupo"], []).append(f"{f['cod']} — {f['nome']}")
        for g, itens in por_grupo.items():
            st.markdown(f"**{g}:** " + "; ".join(itens))

    with st.form("form_terminal"):
        st.markdown("##### Identificação")
        a, b, c, d = st.columns(4)
        lt_nome = a.text_input("LT / equipamento protegido", d0["lt_nome"], placeholder="LT 230 kV SE-A – SE-B (ou transformador, gerador, barra)")
        terminal = b.text_input("Terminal (SE)", d0["terminal"], placeholder="SE-A")
        modelo = c.text_input("Modelo do relé", d0["modelo"], placeholder="SEL-411L")
        remoto = d.text_input("Terminal remoto", d0["terminal_remoto"])

        st.markdown("##### Tensão e transformadores de instrumentos")
        a, b, c = st.columns(3)
        vn = a.number_input("Tensão nominal (kV)", 1.0, 1000.0, float(d0["vn_kv"]), 1.0)
        rtc = b.number_input("RTC (ex.: 2000:5 → 400)", 0.1, 1e5, float(d0["rtc"]), 0.1)
        rtp = c.number_input("RTP (ex.: 230 kV/115 V → 2000)", 0.1, 1e6, float(d0["rtp"]), 0.1)

        comp, k = float(d0["comp_km"]), 1.0
        r1, x1, r0, x0 = float(d0["r1"]), float(d0["x1"]), float(d0["r0"]), float(d0["x0"])
        if dist:
            st.markdown("##### Linha de transmissão")
            a, b, c = st.columns(3)
            comp = a.number_input("Comprimento (km)", 0.0, 2000.0, float(d0["comp_km"]), 0.1)
            b.caption("Os campos abaixo seguem o modo escolhido acima.")
            k = comp if modo_z.startswith("Ω/km") else 1.0
            fator_exib = (1.0 / comp) if (modo_z.startswith("Ω/km") and comp > 0) else 1.0
            a, b, c, d = st.columns(4)
            r1 = a.number_input("R1", 0.0, 1e5, float(d0["r1"] * fator_exib), 0.0001, format="%.4f") * k
            x1 = b.number_input("X1", 0.0, 1e5, float(d0["x1"] * fator_exib), 0.0001, format="%.4f") * k
            r0 = c.number_input("R0", 0.0, 1e5, float(d0["r0"] * fator_exib), 0.0001, format="%.4f") * k
            x0 = d.number_input("X0", 0.0, 1e5, float(d0["x0"] * fator_exib), 0.0001, format="%.4f") * k

        st.markdown("##### Carga")
        a, b, c, d = st.columns(4)
        smax = a.number_input("Fluxo máximo (MVA)", 0.0, 1e5, float(d0["s_max_mva"]), 1.0)
        iterm = b.number_input("Limite térmico (A)", 0.0, 1e5, float(d0["i_term_a"]), 10.0)
        vmin, phi_p, phi_n = float(d0["v_min_pu"]), float(d0["phi_pos"]), float(d0["phi_neg"])
        q_max = float(d0.get("q_max_mvar", 0.0))
        if dist:
            vmin = c.number_input("Tensão mínima (pu)", 0.5, 1.2, float(d0["v_min_pu"]), 0.01)
        f_hz = d.selectbox("Frequência (Hz)", [60.0, 50.0], index=0 if d0["f_hz"] == 60.0 else 1)
        if dist:
            a, b = st.columns(2)
            phi_p = a.number_input("Ângulo máx. de carga indutiva (°)", 0.0, 89.0, float(d0["phi_pos"]), 1.0)
            phi_n = b.number_input("Ângulo máx. de carga capacitiva (°)", 0.0, 89.0, float(d0["phi_neg"]), 1.0)
            q_max = st.number_input("Q máx. da carga (Mvar) — opcional: se > 0, calcula o ângulo indutivo (arctan Q/P)",
                                    0.0, 1e5, float(d0.get("q_max_mvar", 0.0)), 1.0)

        icl, icr, fslip = float(d0["icc3f_loc_ka"]), float(d0["icc3f_rem_ka"]), float(d0["f_slip_max"])
        zadj_min, zadj_max = float(d0["zadj_min"]), float(d0["zadj_max"])
        if "68" in funcs:
            st.markdown("##### Sistema (oscilação de potência)")
            a, b, c = st.columns(3)
            icl = a.number_input("Icc 3F barra local (kA)", 0.0, 500.0, float(d0["icc3f_loc_ka"]), 0.001, format="%.3f")
            icr = b.number_input("Icc 3F barra remota (kA)", 0.0, 500.0, float(d0["icc3f_rem_ka"]), 0.001, format="%.3f")
            fslip = c.number_input("Freq. de escorregamento máx. (Hz)", 0.1, 20.0, float(d0["f_slip_max"]), 0.1)
        if "21" in funcs:
            st.markdown("##### Adjacentes (coordenação da distância)")
            a, b = st.columns(2)
            zadj_min = a.number_input("Zadj mínima — 1ª zona do adjacente mais curto (Ω pri)", 0.0, 1e5, float(d0["zadj_min"]), 0.1)
            zadj_max = b.number_input("Zadj máxima — adjacente mais longo (Ω pri)", 0.0, 1e5, float(d0["zadj_max"]), 0.1)

        curvas = list(CURVAS)
        curva51, curva51n = d0.get("curva51", "IEC NI"), d0.get("curva51n", "IEC NI")
        t_jus, t_jus_n = float(d0.get("t_jus_s", 0.0)), float(d0.get("t_jus_n_s", 0.0))
        if "51" in funcs or "51N" in funcs:
            st.markdown("##### Temporização (51 / 51N)")
            st.caption("Informe o tempo de atuação do dispositivo a jusante para a falta a 100% da LT; o app soma o intervalo "
                       "de coordenação (etapa 4) e calcula o TMS. Deixe 0 se ainda não tiver.")
            a, b, c, d = st.columns(4)
            if "51" in funcs:
                curva51 = a.selectbox("Curva 51 (fase)", curvas, index=curvas.index(curva51) if curva51 in curvas else 0)
                t_jus = b.number_input("Tempo a jusante — fase (s)", 0.0, 10.0, t_jus, 0.05)
            if "51N" in funcs:
                curva51n = c.selectbox("Curva 51N (neutro)", curvas, index=curvas.index(curva51n) if curva51n in curvas else 0)
                t_jus_n = d.number_input("Tempo a jusante — neutro (s)", 0.0, 10.0, t_jus_n, 0.05)

        curva67, curva67n = d0.get("curva67", "IEC NI"), d0.get("curva67n", "IEC NI")
        t_jus67, t_jus67n = float(d0.get("t_jus_67_s", 0.0)), float(d0.get("t_jus_67n_s", 0.0))
        mta67, mta67n = float(d0.get("mta67_man", 0.0)), float(d0.get("mta67n_man", 0.0))
        if "67" in funcs or "67N" in funcs:
            st.markdown("##### Direcionais (67 / 67N)")
            st.caption("O MTA (ângulo de máximo torque) é calculado dos fasores de falta à frente (etapa 3). Só preencha o MTA manual "
                       "se não tiver fasores ou se o cliente impuser um valor (0 = automático). Tempo a jusante: igual ao 51/51N.")
            a, b, c = st.columns(3)
            if "67" in funcs:
                curva67 = a.selectbox("Curva 67 (fase)", curvas, index=curvas.index(curva67) if curva67 in curvas else 0)
                t_jus67 = b.number_input("Tempo a jusante — 67 (s)", 0.0, 10.0, t_jus67, 0.05)
                mta67 = c.number_input("MTA 67 manual (°; 0 = automático)", -180.0, 180.0, mta67, 1.0)
            a, b, c = st.columns(3)
            if "67N" in funcs:
                curva67n = a.selectbox("Curva 67N (neutro)", curvas, index=curvas.index(curva67n) if curva67n in curvas else 0)
                t_jus67n = b.number_input("Tempo a jusante — 67N (s)", 0.0, 10.0, t_jus67n, 0.05)
                mta67n = c.number_input("MTA 67N manual (°; 0 = automático)", -180.0, 180.0, mta67n, 1.0)

        extra = grupo_specs(MOD.entradas(funcs, conf=False), d0, tid)

        ex = {}
        if modo == "conferencia":
            st.markdown("##### Ajustes existentes no relé (valores secundários; 0 = não informado)")
            if "21" in funcs:
                a, b, c = st.columns(3)
                ex["ex_z1"] = a.number_input("Zona 1 (Ω sec)", 0.0, 1e4, float(d0["ex_z1"]), 0.01)
                ex["ex_z2"] = b.number_input("Zona 2 (Ω sec)", 0.0, 1e4, float(d0["ex_z2"]), 0.01)
                ex["ex_z3"] = c.number_input("Zona 3 (Ω sec)", 0.0, 1e4, float(d0["ex_z3"]), 0.01)
                ex["ex_zlf"] = st.number_input("ZLF (Ω sec)", 0.0, 1e4, float(d0["ex_zlf"]), 0.01)
            if "68" in funcs:
                a, b, c = st.columns(3)
                ex["ex_r_blinder_int"] = a.number_input("Blinder interno — R (Ω sec)", 0.0, 1e4, float(d0["ex_r_blinder_int"]), 0.01)
                ex["ex_r_blinder_ext"] = b.number_input("Blinder externo — R (Ω sec)", 0.0, 1e4, float(d0["ex_r_blinder_ext"]), 0.01)
                ex["ex_osbd_ciclos"] = c.number_input("OSBD (ciclos)", 0.0, 1e3, float(d0["ex_osbd_ciclos"]), 0.25)
            if usa_sc:
                a, b, c, d = st.columns(4)
                if "50" in funcs:
                    ex["ex_pickup50_a_sec"] = a.number_input("Pickup 50 (A sec)", 0.0, 1e4, float(d0["ex_pickup50_a_sec"]), 0.01)
                if "51" in funcs:
                    ex["ex_pickup51_a_sec"] = b.number_input("Pickup 51 (A sec)", 0.0, 1e4, float(d0["ex_pickup51_a_sec"]), 0.01)
                    ex["ex_tms51"] = c.number_input("TMS 51", 0.0, 10.0, float(d0["ex_tms51"]), 0.01)
                a, b, c, d = st.columns(4)
                if "50N" in funcs:
                    ex["ex_pickup50n_a_sec"] = a.number_input("Pickup 50N (A sec)", 0.0, 1e4, float(d0["ex_pickup50n_a_sec"]), 0.01)
                if "51N" in funcs:
                    ex["ex_pickup51n_a_sec"] = b.number_input("Pickup 51N (A sec)", 0.0, 1e4, float(d0["ex_pickup51n_a_sec"]), 0.01)
                    ex["ex_tms51n"] = c.number_input("TMS 51N", 0.0, 10.0, float(d0["ex_tms51n"]), 0.01)

            if "67" in funcs or "67N" in funcs:
                a, b, c, d = st.columns(4)
                if "67" in funcs:
                    ex["ex_pickup67_a_sec"] = a.number_input("Pickup 67 (A sec)", 0.0, 1e4, float(d0["ex_pickup67_a_sec"]), 0.01)
                    ex["ex_mta67"] = b.number_input("MTA 67 (°)", -180.0, 180.0, float(d0["ex_mta67"]), 1.0)
                if "67N" in funcs:
                    ex["ex_pickup67n_a_sec"] = c.number_input("Pickup 67N (A sec)", 0.0, 1e4, float(d0["ex_pickup67n_a_sec"]), 0.01)
                    ex["ex_mta67n"] = d.number_input("MTA 67N (°)", -180.0, 180.0, float(d0["ex_mta67n"]), 1.0)

            conf_specs = MOD.entradas(funcs, conf=True)
            if conf_specs:
                for i in range(0, len(conf_specs), 4):
                    cols = st.columns(4)
                    for col, e in zip(cols, conf_specs[i:i + 4]):
                        ex[e["k"]] = campo_spec(col, e, d0, tid)

        salvar = st.form_submit_button("Salvar terminal", type="primary")
    if salvar:
        if not lt_nome.strip() or not terminal.strip():
            st.error("Informe a LT e o terminal.")
        elif not funcs:
            st.error("Marque ao menos uma função de proteção.")
        else:
            dados = dict(d0)
            dados.update(dict(modo=modo, fabricante=fab, modelo=modelo, lt_nome=lt_nome.strip(),
                              terminal=terminal.strip(), terminal_remoto=remoto, comp_km=comp, vn_kv=vn,
                              r1=r1, x1=x1, r0=r0, x0=x0, rtc=rtc, rtp=rtp, s_max_mva=smax,
                              i_term_a=iterm, v_min_pu=vmin, phi_pos=phi_p, phi_neg=phi_n, q_max_mvar=q_max, f_hz=f_hz,
                              f_slip_max=fslip, icc3f_loc_ka=icl, icc3f_rem_ka=icr, zadj_min=zadj_min,
                              zadj_max=zadj_max, funcoes=list(funcs), curva51=curva51, curva51n=curva51n,
                              t_jus_s=t_jus, t_jus_n_s=t_jus_n, curva67=curva67, curva67n=curva67n,
                              t_jus_67_s=t_jus67, t_jus_67n_s=t_jus67n, mta67_man=mta67, mta67n_man=mta67n))
            dados.update(extra)
            dados.update(ex)
            novo = db.salvar_terminal(ENGINE, p["id"], dados, tid)
            ss.resultados.pop(novo, None)
            st.success("Terminal salvo.")
            st.rerun()
    if atual:
        b1, b2 = st.columns(2)
        if b1.button("Duplicar como outro terminal", width="stretch"):
            copia = dict(atual["dados"])
            copia["terminal"] = (copia.get("terminal_remoto") or copia.get("terminal", "") + " (cópia)")
            copia["terminal_remoto"] = atual["dados"].get("terminal", "")
            db.salvar_terminal(ENGINE, p["id"], copia)
            st.rerun()
        if b2.button("Excluir este terminal", width="stretch"):
            db.excluir_terminal(ENGINE, atual["id"])
            ss.resultados.pop(atual["id"], None)
            st.rerun()

# ------------------------------------------------------------------------ 3 · Curto-circuito
elif pagina == PAGINAS[2]:
    p = exige_projeto()
    banner("Resultados de curto-circuito", "Importe a tabela exportada do Anafas, ETAP, PowerFactory, ASPEN ou outro programa.")
    salvo = db.obter_curto(ENGINE, p["id"])
    if salvo:
        st.success(f"Conjunto ativo: **{salvo['arquivo']}** ({salvo['origem']}) — {len(salvo['dados'])} caso(s).")
        st.dataframe(pd.DataFrame(salvo["dados"]), hide_index=True, width="stretch")
    st.markdown("##### Digitar manualmente")
    st.caption("Adicione linhas (botão + da tabela). Tipo: 3F, FT, FF ou FFT. Corrente em kA. Local em % da LT "
               "(0 = terminal local, 100 = terminal remoto). Rf em Ω (opcional). Terminal: deixe vazio para valer para todos.")
    base_man = pd.DataFrame(salvo["dados"]) if salvo else pd.DataFrame(
        {"ponto": ["F1"], "tipo": ["3F"], "local_pct": [0.0], "icc_ka": [0.0], "rf_ohm": [0.0], "terminal": [""], "sentido": ["frente"]})
    for c_ in ("ponto", "tipo", "local_pct", "icc_ka", "rf_ohm", "terminal", "sentido"):
        if c_ not in base_man.columns:
            base_man[c_] = "" if c_ in ("ponto", "tipo", "terminal") else ("frente" if c_ == "sentido" else 0.0)
    base_man = base_man[["ponto", "tipo", "local_pct", "icc_ka", "rf_ohm", "terminal", "sentido"]].fillna(
        {"ponto": "", "tipo": "3F", "local_pct": 0.0, "icc_ka": 0.0, "rf_ohm": 0.0, "terminal": "", "sentido": "frente"})
    base_man["sentido"] = base_man["sentido"].replace("", "frente").map(lambda x: "ré" if str(x).lower() in ("re", "ré") else "frente")
    ed = st.data_editor(
        base_man, num_rows="dynamic", hide_index=True, width="stretch", key="ed_curto_manual",
        column_config={
            "ponto": st.column_config.TextColumn("Ponto / descrição"),
            "tipo": st.column_config.SelectboxColumn("Tipo de falta", options=["3F", "FT", "FF", "FFT"], required=True),
            "local_pct": st.column_config.NumberColumn("Local na LT (%)", min_value=0.0, max_value=100.0, step=1.0),
            "icc_ka": st.column_config.NumberColumn("Icc (kA)", min_value=0.0, step=0.001, format="%.3f"),
            "rf_ohm": st.column_config.NumberColumn("Rf (Ω)", min_value=0.0, step=0.5),
            "terminal": st.column_config.TextColumn("Terminal (opcional)"),
            "sentido": st.column_config.SelectboxColumn("Sentido", options=["frente", "ré"], help="Falta à frente (na LT) ou à ré (atrás do relé)"),
        })
    def _casos_da_tabela(df_):
        out = []
        for _, rw in df_.iterrows():
            icc = pd.to_numeric(rw.get("icc_ka"), errors="coerce")
            if pd.isna(icc) or icc <= 0:
                continue
            out.append({"ponto": str(rw.get("ponto") or f"F{len(out) + 1}"),
                        "tipo": importers.normalizar_tipo(rw.get("tipo") or "3F"),
                        "local_pct": float(pd.to_numeric(rw.get("local_pct"), errors="coerce") or 0.0),
                        "icc_ka": float(icc),
                        "rf_ohm": float(pd.to_numeric(rw.get("rf_ohm"), errors="coerce") or 0.0),
                        "terminal": str(rw.get("terminal") or "").strip(),
                        "sentido": importers.normalizar_sentido(rw.get("sentido"), None) or "frente"})
        return out

    def _chave(casos_):
        return [(c["ponto"], c["tipo"], round(c["local_pct"], 3), round(c["icc_ka"], 4), round(c["rf_ohm"], 3),
                 c["terminal"], c["sentido"]) for c in casos_]

    _atual = _casos_da_tabela(ed)
    _gravado = _casos_da_tabela(pd.DataFrame(salvo["dados"])) if salvo else []
    if _chave(_atual) != _chave(_gravado):
        st.warning(f"⚠ Alterações NÃO salvas na tabela ({len(_atual)} caso(s) com Icc > 0 digitado(s)). "
                   "Clique em **Salvar valores digitados** antes de mudar de etapa ou recarregar a página — "
                   "senão os valores se perdem.")
    if st.button("Salvar valores digitados", type="primary", key="salvar_manual"):
        casos_m = _atual
        if not casos_m:
            st.error("Informe ao menos um caso com Icc > 0.")
        else:
            db.salvar_curto(ENGINE, p["id"], "Digitação manual", "Manual", casos_m)
            ss.resultados = {}
            st.success(f"{len(casos_m)} caso(s) salvos.")
            st.rerun()
    with st.expander("Fasores de falta para 67 / 67N (digitar manualmente)"):
        st.caption("Para cada falta, informe módulo e ângulo de corrente (kA) e tensão (kV fase-neutro) **medidos no relé**, com a corrente "
                   "positiva saindo da barra para a LT. Programas como Anafas/ETAP/PowerFactory exibem fasores de fase ou de sequência "
                   "no relatório de falta; copie de lá. Sentido: frente (falta na LT) ou ré (atrás do relé).")
        modo_f = st.radio("Grandezas informadas", ["fase", "sequencia"], format_func=lambda x: "Fases A, B, C" if x == "fase" else "Sequências 1, 2, 0",
                          horizontal=True, key="modo_fas_man")
        tres = False
        if modo_f == "sequencia":
            tres = st.checkbox("I0 e V0 informados como 3·I0 e 3·V0", key="tres_man")
        nomes_f = FS.NOMES_FASE if modo_f == "fase" else FS.NOMES_SEQ
        colsf = ["ponto", "tipo", "sentido"] + [f"{n}_{k}" for n in nomes_f for k in ("m", "a")]
        vazio = pd.DataFrame([{**{"ponto": "F1", "tipo": "FT", "sentido": "frente"}, **{c_: 0.0 for c_ in colsf[3:]}}])
        cfg = {"ponto": st.column_config.TextColumn("Ponto"),
               "tipo": st.column_config.SelectboxColumn("Tipo", options=["3F", "FT", "FF", "FFT"], required=True),
               "sentido": st.column_config.SelectboxColumn("Sentido", options=["frente", "ré"], required=True)}
        for n in nomes_f:
            cfg[f"{n}_m"] = st.column_config.NumberColumn(f"|{n}| ({'kA' if n[0] == 'I' else 'kV'})", min_value=0.0, format="%.4f")
            cfg[f"{n}_a"] = st.column_config.NumberColumn(f"∠{n} (°)", min_value=-360.0, max_value=360.0, format="%.1f")
        edf = st.data_editor(vazio, num_rows="dynamic", hide_index=True, width="stretch", column_config=cfg, key=f"ed_fas_{modo_f}")
        inv_m = st.checkbox("Meus fasores têm corrente entrando na barra (inverter sentido)", key="inv_man")
        if st.button("Adicionar casos com fasores", key="add_fas"):
            novos, erros = [], 0
            for _, rw in edf.iterrows():
                try:
                    vals = {n: (float(rw[f"{n}_m"]), float(rw[f"{n}_a"])) for n in nomes_f}
                    if modo_f == "sequencia":
                        f_ = FS.sequencia_para_caso(vals, tres_x=tres)
                    else:
                        f_ = {n: [vals[n][0], FS.norm180(vals[n][1])] for n in nomes_f}
                    if inv_m:
                        f_ = FS.inverter_sentido(f_)
                    icc_f = max(f_["Ia"][0], f_["Ib"][0], f_["Ic"][0])
                    if icc_f <= 0:
                        raise ValueError
                    novos.append({"ponto": str(rw["ponto"] or f"F{len(novos) + 1}"), "tipo": importers.normalizar_tipo(rw["tipo"]),
                                  "local_pct": 0.0 if importers.normalizar_sentido(rw["sentido"]) != "re" else -1.0,
                                  "icc_ka": icc_f, "rf_ohm": 0.0, "terminal": "",
                                  "sentido": importers.normalizar_sentido(rw["sentido"]) or "frente", "fasores": f_})
                except (TypeError, ValueError, KeyError):
                    erros += 1
            if not novos:
                st.error("Nenhuma linha válida (correntes com módulo > 0).")
            else:
                existentes = [c_ for c_ in (salvo["dados"] if salvo else []) if not c_.get("fasores")]
                db.salvar_curto(ENGINE, p["id"], "Digitação manual + fasores", "Manual", existentes + novos)
                ss.resultados = {}
                st.success(f"{len(novos)} caso(s) com fasores adicionados" + (f"; {erros} linha(s) ignorada(s)." if erros else "."))
                st.rerun()
    with st.expander("Colar casos de curto (texto CSV / planilha)"):
        st.caption("Cole linhas com as colunas: ponto, tipo, local_pct, icc_ka, rf_ohm, terminal, sentido "
                   "(separador vírgula, ponto-e-vírgula ou tabulação; decimal com ponto ou vírgula; 1ª linha = cabeçalho). "
                   "Icc em kA. O conjunto colado SUBSTITUI o conjunto ativo.")
        txt_colado = st.text_area("Texto", height=180, key="txt_curto_colado")
        if st.button("Importar texto colado", key="btn_curto_colado"):
            import csv as _csv, io as _io
            _lin = [l for l in txt_colado.splitlines() if l.strip()]
            if len(_lin) < 2:
                st.error("Cole o cabeçalho e ao menos uma linha.")
            else:
                _sep = max([";", "\t", ","], key=lambda c_: _lin[0].count(c_))
                _rd = list(_csv.DictReader(_io.StringIO("\n".join(_lin)), delimiter=_sep))
                _cs, _err = [], 0
                for _r in _rd:
                    _r = {str(k).strip().lower(): (v or "").strip() for k, v in _r.items() if k}
                    try:
                        _icc = float(_r.get("icc_ka", "").replace(",", "."))
                        if _icc <= 0:
                            raise ValueError
                        _cs.append({"ponto": _r.get("ponto") or f"F{len(_cs) + 1}",
                                    "tipo": importers.normalizar_tipo(_r.get("tipo") or "3F"),
                                    "local_pct": float((_r.get("local_pct") or "0").replace(",", ".")),
                                    "icc_ka": _icc,
                                    "rf_ohm": float((_r.get("rf_ohm") or "0").replace(",", ".")),
                                    "terminal": _r.get("terminal", ""),
                                    "sentido": importers.normalizar_sentido(_r.get("sentido"), None) or "frente"})
                    except (ValueError, AttributeError):
                        _err += 1
                if not _cs:
                    st.error("Nenhuma linha válida (confira os nomes das colunas e Icc > 0).")
                else:
                    db.salvar_curto(ENGINE, p["id"], "Texto colado", "Manual", _cs)
                    ss.resultados = {}
                    st.success(f"{len(_cs)} caso(s) salvos" + (f"; {_err} linha(s) ignorada(s)." if _err else "."))
                    st.rerun()
    st.markdown("##### Importar novo arquivo")
    modelo = pd.DataFrame({"ponto": ["SE-A (barra local)", "LT 50%", "SE-B (barra remota)"], "tipo": ["3F", "FT", "FT"], "local_pct": [0, 50, 100],
                           "icc_ka": [10.5, 6.1, 2.5], "rf_ohm": [0, 0, 10], "terminal": ["", "", ""]})
    st.download_button("Baixar modelo CSV", modelo.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       "modelo_curto_circuito.csv", "text/csv")
    origem = st.selectbox("Origem dos dados", list(importers.PRESETS))
    arq = st.file_uploader("Arquivo (CSV, TXT delimitado ou Excel)", type=["csv", "txt", "xlsx", "xls"])
    if arq is not None:
        try:
            df = importers.ler_tabela(arq, arq.name)
        except Exception as e:
            st.error(f"Não foi possível ler o arquivo: {e}")
            st.stop()
        st.caption(f"{len(df)} linha(s) e {len(df.columns)} coluna(s) lidas.")
        st.dataframe(df.head(15), hide_index=True, width="stretch")
        mapa_sug = importers.sugerir_mapeamento(list(df.columns), origem)
        st.markdown("##### Mapeamento de colunas")
        cols = ["—"] + list(df.columns)
        mapa = {}
        cc = st.columns(3)
        for i, (campo, rot) in enumerate(importers.CAMPOS.items()):
            sug = mapa_sug.get(campo)
            esc = cc[i % 3].selectbox(rot, cols, index=cols.index(sug) if sug in cols else 0, key=f"map_{campo}")
            mapa[campo] = None if esc == "—" else esc
        unid = st.radio("Unidade da corrente (coluna Icc)", ["kA", "A"], horizontal=True)
        fas_cfg, vn_base = None, None
        if st.checkbox("O arquivo traz fasores (módulo e ângulo de I e V) para as funções 67 / 67N"):
            st.caption("Exporte do programa de curto o relatório de falta **no ponto do relé** com correntes de contribuição e tensões "
                       "da barra, em módulo e ângulo (fases ou sequências). O app não adivinha o formato: confira o mapeamento abaixo.")
            modo_i = st.radio("Grandezas do arquivo", ["fase", "sequencia"], horizontal=True, key="modo_fas_imp",
                              format_func=lambda x: "Fases A, B, C" if x == "fase" else "Sequências 1, 2, 0")
            sug_f = importers.sugerir_mapeamento_fasores(list(df.columns), modo_i)
            mapa_f = {}
            cf = st.columns(4)
            for i, (campo, rot_) in enumerate(importers.campos_fasores(modo_i).items()):
                sg = sug_f.get(campo)
                esc = cf[i % 4].selectbox(rot_, cols, index=cols.index(sg) if sg in cols else 0, key=f"mapf_{modo_i}_{campo}")
                mapa_f[campo] = None if esc == "—" else esc
            a, b = st.columns(2)
            un_i = a.radio("Unidade das correntes", ["kA", "A"], horizontal=True, key="un_i_fas")
            un_v = b.selectbox("Unidade das tensões", importers.UNID_V, key="un_v_fas")
            a, b = st.columns(2)
            tres_i = a.checkbox("I0 / V0 vêm como 3·I0 / 3·V0", disabled=modo_i == "fase")
            inv_i = b.checkbox("Corrente entra na barra (inverter sentido)",
                               help="O app assume corrente saindo da barra do relé para a LT. Se o programa exporta o contrário, marque.")
            if un_v.startswith("pu"):
                terms_ = db.listar_terminais(ENGINE, p["id"])
                vn_base = st.number_input("Tensão base (kV fase-fase) para converter pu", 1.0, 1000.0,
                                          float(terms_[0]["dados"].get("vn_kv", 138.0)) if terms_ else 138.0, 1.0)
            fas_cfg = {"modo": modo_i, "mapa": mapa_f, "un_i": un_i, "un_v": un_v, "tres_x": tres_i, "inverter": inv_i}
        if st.button("Padronizar e salvar no projeto", type="primary"):
            try:
                casos, avisos = importers.padronizar(df, mapa, unid, fasores=fas_cfg, vn_kv=vn_base)
                if not casos:
                    st.error("Nenhum caso válido encontrado.")
                else:
                    db.salvar_curto(ENGINE, p["id"], arq.name, origem.split(" (")[0], casos)
                    for a in avisos:
                        st.warning(a)
                    st.success(f"{len(casos)} caso(s) salvos.")
                    ss.resultados = {}
                    st.rerun()
            except Exception as e:
                st.error(str(e))
    st.markdown('<div class="bk-aviso">Colunas: <b>tipo</b> e <b>corrente</b> são obrigatórias. Com a <b>posição na LT (%)</b> '
                'o app faz a validação cruzada das zonas; sem ela, os casos só alimentam os níveis de curto do pickup 51. '
                'Se o arquivo tiver a coluna <b>terminal/LT</b>, cada terminal usa só os seus casos.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------ 4 · Critérios
elif pagina == PAGINAS[3]:
    p = exige_projeto()
    banner("Critérios de ajuste", "Valores padrão de engenharia, editáveis por projeto. Ficam registrados no relatório.")
    c0 = criterios_do(p)
    with st.form("form_criterios"):
        st.markdown("##### Zonas de distância")
        a, b, c, d = st.columns(4)
        k1 = a.number_input("Zona 1 (× ZL)", 0.5, 1.0, float(c0["k_z1"]), 0.01)
        k2 = b.number_input("Zona 2 (× ZL)", 1.0, 2.0, float(c0["k_z2"]), 0.01)
        f2 = c.number_input("Zona 2 ≤ ZL + (× Zadj mín.)", 0.0, 1.0, float(c0["z2_frac_adj"]), 0.05)
        k3 = d.number_input("Zona 3 = ZL + (× Zadj máx.)", 0.0, 2.0, float(c0["k_z3"]), 0.05)
        a, b = st.columns(2)
        z3s = a.number_input("Zona 3 sem adjacente (× ZL)", 1.0, 3.0, float(c0["z3_sem_adj"]), 0.05)
        krev = b.number_input("Alcance reverso (× ZL)", 0.0, 1.0, float(c0["k_rev"]), 0.05)
        st.markdown("##### Carga e load encroachment")
        a, b, c = st.columns(3)
        kload = a.number_input("ZLF = k × Zcarga mín.", 0.5, 1.0, float(c0["k_load"]), 0.01)
        dang = b.number_input("Folga angular (°)", 0.0, 30.0, float(c0["delta_ang_carga"]), 1.0)
        term = c.checkbox("Usar limite térmico como carga de referência", bool(c0["usar_limite_termico"]))
        st.markdown("##### Blinders e OSB")
        a, b, c = st.columns(3)
        zb = a.multiselect("Zonas bloqueadas pelo OSB", [1, 2, 3], default=list(c0["zonas_bloqueadas"]))
        min_ = b.number_input("Margem do blinder interno", 0.0, 1.0, float(c0["margem_blinder_interno"]), 0.01)
        fext = c.number_input("Blinder externo ≤ fração da carga", 0.3, 1.0, float(c0["frac_blinder_externo_carga"]), 0.01)
        a, b, c = st.columns(3)
        tf = a.number_input("Tempo de evolução da falta (ciclos)", 0.5, 10.0, float(c0["t_falta_ciclos"]), 0.25)
        kt = b.number_input("OSBD = k × tempo de travessia", 0.3, 1.0, float(c0["k_timer"]), 0.05)
        pt = c.number_input("Passo do temporizador (ciclos)", 0.05, 1.0, float(c0["passo_timer_ciclos"]), 0.05)
        st.markdown("##### Sobrecorrente (50 / 51 / 50N / 51N)")
        a, b, c, d = st.columns(4)
        kp = a.number_input("51: pickup ≥ k × I carga", 1.0, 3.0, float(c0["k_pickup_min"]), 0.05)
        ks = b.number_input("51: Icc mín. / pickup ≥", 1.0, 5.0, float(c0["k_sens_51"]), 0.05)
        kd = c.number_input("51N: pickup ≥ k × I carga (desequilíbrio)", 0.05, 1.0, float(c0["k_desb"]), 0.05)
        ksn = d.number_input("51N: Icc FT mín. / pickup ≥", 1.0, 5.0, float(c0["k_sens_51n"]), 0.05)
        a, b, c, d = st.columns(4)
        kinst = a.number_input("50/50N: pickup ≥ k × Icc na barra remota", 1.0, 2.0, float(c0["k_inst"]), 0.05)
        dtc = b.number_input("Intervalo de coordenação Δt (s)", 0.1, 1.0, float(c0["dt_coord"]), 0.05)
        pasa = c.number_input("Passo do pickup (A pri)", 1.0, 100.0, float(c0["passo_pickup_a"]), 1.0)
        pst = d.number_input("Passo do TMS", 0.001, 0.1, float(c0["passo_tms"]), 0.001, format="%.3f")
        a, b = st.columns(2)
        tmin = a.number_input("TMS mínimo do relé", 0.01, 1.0, float(c0["tms_min"]), 0.01)
        tmax = b.number_input("TMS máximo do relé", 0.1, 20.0, float(c0["tms_max"]), 0.1)
        st.markdown("##### Direcional (67 / 67N)")
        a, b, c, d = st.columns(4)
        roa = a.number_input("ROA — semiabertura (°)", 45.0, 90.0, float(c0["roa_dir"]), 5.0)
        mang = b.number_input("Margem angular (°)", 0.0, 45.0, float(c0["margem_ang_dir"]), 1.0)
        pmta = c.number_input("Passo do MTA (°)", 1.0, 15.0, float(c0["passo_mta"]), 1.0)
        av0 = d.number_input("Assimetria 3V0 em regime (pu de V fase-neutro)", 0.0, 0.2, float(c0["assim_v0_pu"]), 0.005, format="%.3f")
        a, b, c = st.columns(3)
        kpol = a.number_input("Limiar de polarização ≥ k × assimetria", 1.0, 5.0, float(c0["k_pol"]), 0.05)
        kspol = b.number_input("Mín. observado em falta / limiar ≥", 1.0, 10.0, float(c0["k_sens_pol"]), 0.1)
        vpol = c.number_input("Tensão de quadratura mínima (pu de V fase-fase)", 0.0, 0.5, float(c0["v_pol_min_pu"]), 0.005, format="%.3f")
        crit_extra = {}
        for m in MOD.modulos():
            st.markdown(f"##### {m.TITULO}")
            lista = list(m.CRITERIOS)
            for i in range(0, len(lista), 4):
                cols = st.columns(4)
                for col, k in zip(cols, lista[i:i + 4]):
                    crit_extra[k["k"]] = col.number_input(
                        k["rot"], float(k["mn"]), float(k["mx"]), min(max(float(c0.get(k["k"], k["pad"])), float(k["mn"])), float(k["mx"])),
                        float(k["passo"]), format=k["fmt"], help=f"{k['porque']}\n\nComo escolher: {k['como']}\nOnde buscar: {k['onde']}",
                        key=f"crit_{k['k']}")
        ok = st.form_submit_button("Salvar critérios", type="primary")
    if ok:
        novos = dict(k_z1=k1, k_z2=k2, z2_frac_adj=f2, k_z3=k3, z3_sem_adj=z3s, k_rev=krev, k_load=kload,
                     delta_ang_carga=dang, usar_limite_termico=term, zonas_bloqueadas=zb or [1, 2, 3],
                     margem_blinder_interno=min_, frac_blinder_externo_carga=fext, t_falta_ciclos=tf, k_timer=kt,
                     passo_timer_ciclos=pt, k_pickup_min=kp, k_sens_51=ks, k_desb=kd, k_sens_51n=ksn, k_inst=kinst,
                     dt_coord=dtc, passo_pickup_a=pasa, passo_tms=pst, tms_min=tmin, tms_max=tmax,
                     roa_dir=roa, margem_ang_dir=mang, passo_mta=pmta, assim_v0_pu=av0, k_pol=kpol,
                     k_sens_pol=kspol, v_pol_min_pu=vpol)
        novos.update(crit_extra)
        db.atualizar_projeto(ENGINE, p["id"], criterios=novos)
        ss.resultados = {}
        st.success("Critérios salvos. Refaça o cálculo para aplicá-los.")
    if st.button("Restaurar padrões"):
        db.atualizar_projeto(ENGINE, p["id"], criterios={})
        ss.resultados = {}
        st.rerun()

# ------------------------------------------------------------------------ 5 · Cálculo
elif pagina == PAGINAS[4]:
    p = exige_projeto()
    banner("Cálculo", "Calcula apenas as funções marcadas em cada relé (etapa 2) e valida com o curto-circuito.")
    terms = db.listar_terminais(ENGINE, p["id"])
    if not terms:
        st.info("Cadastre ao menos um terminal na etapa 2.")
        st.stop()
    crit = criterios_do(p)
    curto = db.obter_curto(ENGINE, p["id"])
    todos_casos = curto["dados"] if curto else []
    if not todos_casos:
        st.markdown('<div class="bk-aviso">Sem curto-circuito importado: a validação cruzada e o limite superior do pickup 51 '
                    'não serão calculados.</div>', unsafe_allow_html=True)
    rot = {t["id"]: f"{t['lt']} — {t['terminal']}" for t in terms}
    sel = st.multiselect("Terminais a calcular", list(rot), default=list(rot), format_func=lambda i: rot[i])
    if st.button("Calcular", type="primary"):
        for t in terms:
            if t["id"] not in sel:
                continue
            casos = importers.casos_para_terminal(todos_casos, t["lt"], t["terminal"])
            try:
                r = calcular_terminal(t["dados"], crit, casos)
                ss.resultados[t["id"]] = r
                db.salvar_resultado(ENGINE, t["id"], r)
            except ValueError as e:
                st.error(f"{rot[t['id']]}: {e}")
            except Exception:
                st.error(f"{rot[t['id']]}: erro inesperado.")
                st.code(traceback.format_exc())
    for t in terms:                                   # recarrega o que já foi salvo
        if t["id"] not in ss.resultados and t["resultado"]:
            ss.resultados[t["id"]] = t["resultado"]
    prontos = [t for t in terms if t["id"] in ss.resultados and t["id"] in sel]
    if not prontos:
        st.stop()
    abas = st.tabs([rot[t["id"]] for t in prontos])
    for aba, t in zip(abas, prontos):
        r = ss.resultados[t["id"]]
        o, z = r.get("oos"), r.get("zonas")
        fs = r.get("funcoes") or ["21", "68", "51"]
        sc = r.get("sobrecorrente") or {}
        dr = r.get("direcional") or {}
        with aba:
            itens = []
            if "21" in fs and z:
                itens.append(("Zona 1 / 2 / 3", f"{fmt(z['Z1']['alcance'])} / {fmt(z['Z2']['alcance'])} / {fmt(z['Z3']['alcance'])}", "Ω secundários"))
                itens.append(("ZLF", fmt(r["carga"]["zlf"]), f"Load enc.: {'necessário' if r['carga']['load_enc_necessario'] else 'sem invasão'}"))
            if "68" in fs and o:
                itens.append(("Blinders (R int / ext)", f"{fmt(o['r_in'])} / {fmt(o['r_out'])}", "Ω secundários"))
                itens.append(("OSBD", f"{fmt(o['osbd_ciclos'],2)} ciclos", f"{fmt(o['osbd_s']*1000,1)} ms"))
            for cod, chave in (("50", "p50"), ("50N", "p50n")):
                if chave in sc:
                    pp = sc[chave]
                    itens.append((f"Pickup {cod}", (f"{fmt(pp['rec_sec'],2)} A sec" if pp.get("calculado") else "n/d"),
                                  (f"{fmt(pp['rec_pri'],0)} A pri" if pp.get("calculado") else "falta a 100% da LT")))
            for cod, chave in (("51", "p51"), ("51N", "p51n")):
                if chave in sc:
                    pp = sc[chave]
                    itens.append((f"Pickup {cod}", f"{fmt(pp['rec_sec'],2)} A sec",
                                  f"{fmt(pp['rec_pri'],0)} A pri · TMS {fmt(pp['tms'],2) if pp.get('tms') is not None else 'n/d'}"))
            for cod, chave in (("67", "p67"), ("67N", "p67n")):
                if chave in dr:
                    pp = dr[chave]
                    itens.append((f"MTA {cod}", f"{fmt(pp['mta'],0)}°", f"ROA ±{fmt(pp['roa'],0)}° · {pp['mta_origem']}"))
                    itens.append((f"Pickup {cod}", f"{fmt(pp['rec_sec'],2)} A sec",
                                  f"{fmt(pp['rec_pri'],0)} A pri · TMS {fmt(pp['tms'],2) if pp.get('tms') is not None else 'n/d'}"))
            itens += [(c_["titulo"], c_["valor"], c_["sub"]) for c_ in r.get("cards_extra", [])]
            for ini in range(0, len(itens), 4):
                linha = itens[ini:ini + 4]
                cols = st.columns(len(linha))
                for col, (tit, val, sub_) in zip(cols, linha):
                    card(col, tit, val, sub_)
            for a in r["alertas"]:
                st.markdown(f'<div class="bk-aviso">⚠ {a}</div>', unsafe_allow_html=True)
            ta, tb, tc, td, te = st.tabs(["Ajustes", "Gráficos", "Memória de cálculo", "Verificações", "Validação com curto"])
            with ta:
                adf = pd.DataFrame(r["ajustes"])[["funcao", "parametro", "nome_rele", "valor_sec", "unid_sec",
                                                  "valor_pri", "unid_pri", "criterio", "status"]]
                for col in ("valor_sec", "valor_pri"):           # colunas mistas (números e Y/N) -> texto
                    adf[col] = adf[col].map(lambda v: fmt(v, 3) if isinstance(v, (int, float)) else str(v))
                adf.columns = ["Função", "Parâmetro", "Nome (ref.)", "Valor sec.", "Un.", "Valor pri.", "Un. ", "Critério", "Status"]
                st.dataframe(adf, hide_index=True, width="stretch")
                if r["conferencia"]:
                    st.markdown("**Conferência dos ajustes existentes**")
                    st.dataframe(pd.DataFrame(r["conferencia"]), hide_index=True, width="stretch")
            with tb:
                if z and o:
                    g1, g2 = st.columns([3, 2])
                    g1.pyplot(grafico_rx(r, titulo="Diagrama R-X"), width="stretch")
                    if "68" in fs:
                        g2.pyplot(grafico_tempo_slip(r), width="stretch")
                fig_c = grafico_curvas_sobrecorrente(r)
                if fig_c is not None:
                    st.pyplot(fig_c, width="stretch")
                for cod in ("67", "67N"):
                    fig_d = grafico_direcional(r, cod) if cod in fs else None
                    if fig_d is not None:
                        st.pyplot(fig_d, width="stretch")
                for leg, fig_x in MOD.figuras(r):
                    st.pyplot(fig_x, width="stretch")
                    plt.close(fig_x)
                for tb_ in r.get("tabelas_extra", []):
                    st.markdown(f"**{tb_['titulo']}**")
                    st.dataframe(pd.DataFrame(tb_["linhas"], columns=tb_["cab"]), hide_index=True, width="stretch")
                if not (z and o) and fig_c is None and not dr and not r.get("modulos"):
                    st.caption("Sem gráficos para as funções selecionadas.")
                if r["tabela_fslip"]:
                    st.dataframe(pd.DataFrame(r["tabela_fslip"]).rename(columns={
                        "f_slip": "f_slip (Hz)", "t_ms": "Tempo entre blinders (ms)", "t_ciclos": "Ciclos",
                        "osb_bloqueia": "OSB bloqueia?"}), hide_index=True, width="stretch")
            with tc:
                secao = None
                for pa in r["passos"]:
                    if pa["secao"] != secao:
                        secao = pa["secao"]
                        st.markdown(f"##### {secao}")
                    st.caption(pa["titulo"])
                    try:
                        st.latex(pa["simb"])
                        st.latex(pa["num"])
                    except Exception:
                        st.code(pa["num"])
                    if pa.get("nota"):
                        st.caption(pa["nota"])
            with td:
                vdf = pd.DataFrame(r["verificacoes"])
                vdf["valor"] = vdf["valor"].map(lambda v: fmt(v) if isinstance(v, (int, float)) else v)
                vdf["limite"] = vdf["limite"].map(lambda v: fmt(v) if isinstance(v, (int, float)) else v)
                st.dataframe(vdf[["item", "criterio", "valor", "limite", "status", "nota"]], hide_index=True, width="stretch")
            with te:
                for cod, chave in (("67", "p67"), ("67N", "p67n")):
                    if chave in dr and dr[chave]["casos"]:
                        st.markdown(f"**Verificação direcional {cod}** (MTA {fmt(dr[chave]['mta'],0)}°)")
                        ddf = pd.DataFrame(dr[chave]["casos"])[["caso", "tipo", "sentido", "fase", "i_mod", "i_ang", "lag",
                                                                  "desvio", "folga", "ok"]]
                        ddf.columns = ["Caso", "Tipo", "Sentido", "Fase", "|I| (kA)", "∠I (°)", "Atraso (°)", "Desvio (°)", "Folga (°)", "OK"]
                        st.dataframe(ddf, hide_index=True, width="stretch")
                    elif chave in dr:
                        st.caption(f"{cod}: nenhum caso com fasores — importe ou digite fasores na etapa 3.")
                if r["validacao"]:
                    st.dataframe(pd.DataFrame(r["validacao"]), hide_index=True, width="stretch")
                else:
                    st.caption("Nenhum caso com posição na LT para validar.")

# ------------------------------------------------------------------------ 6 · Relatórios
elif pagina == PAGINAS[5]:
    p = exige_projeto()
    banner("Relatórios", "Relatório técnico em Word (metodologia, equações e memória de cálculo) e planilha Excel de ajustes.")
    terms = db.listar_terminais(ENGINE, p["id"])
    for t in terms:
        if t["id"] not in ss.resultados and t["resultado"]:
            ss.resultados[t["id"]] = t["resultado"]
    prontos = [t for t in terms if t["id"] in ss.resultados]
    if not prontos:
        st.info("Calcule ao menos um terminal na etapa 5.")
        st.stop()
    rot = {t["id"]: f"{t['lt']} — {t['terminal']}" for t in prontos}
    sel = st.multiselect("Terminais no relatório", list(rot), default=list(rot), format_func=lambda i: rot[i])
    logo = st.file_uploader("Logo da empresa (só usado se o modelo core/modelo_bk.docx não existir)", type=["png", "jpg", "jpeg"])
    resultados = [ss.resultados[i] for i in sel]
    nome_base = (p.get("numero_doc") or f"projeto_{p['id']}").replace("/", "-").replace(" ", "_")
    c1, c2 = st.columns(2)
    if c1.button("Gerar relatório Word", type="primary", width="stretch", disabled=not sel):
        buf = io.BytesIO()
        with st.spinner("Montando relatório…"):
            gerar_relatorio(p, resultados, buf, logo.getvalue() if logo else None)
        ss.docx = buf.getvalue()
    if c2.button("Gerar planilha Excel", type="primary", width="stretch", disabled=not sel):
        buf = io.BytesIO()
        gerar_planilha(p, resultados, buf)
        ss.xlsx = buf.getvalue()
    d1, d2 = st.columns(2)
    if ss.docx:
        d1.download_button("⬇ Baixar relatório (.docx)", ss.docx, f"{nome_base}_Relatorio.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document", width="stretch")
    if ss.xlsx:
        d2.download_button("⬇ Baixar ajustes (.xlsx)", ss.xlsx, f"{nome_base}_Ajustes_Reles.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    st.markdown('<div class="bk-aviso">O relatório segue o DOCUMENTO PADRÃO BK (core/modelo_bk.docx). Ao abrir o .docx, o Word pode pedir para atualizar campos (numeração de páginas): '
                'aceite. As equações são nativas do Word e podem ser editadas normalmente.</div>', unsafe_allow_html=True)
