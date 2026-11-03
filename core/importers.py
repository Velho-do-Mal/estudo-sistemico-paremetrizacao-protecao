"""Importação de resultados de curto-circuito (Anafas, ETAP, PowerFactory, ASPEN etc.).

Estratégia: os programas de curto exportam tabelas (CSV, XLSX, TXT delimitado). O app lê a
tabela, tenta reconhecer as colunas por sinônimos (presets) e o usuário confirma/ajusta o
mapeamento antes de salvar. Nenhum formato proprietário binário é lido diretamente.

Colunas padronizadas (saída):
    ponto      identificação do caso/barra/ponto de falta
    tipo       3F, FT, FF ou FFT
    local_pct  posição da falta na LT em % do comprimento (0 = barra local, 100 = remota)
    icc_ka     corrente de falta vista pelo terminal (kA)
    rf_ohm     resistência de falta (ohms primários), opcional
    terminal   (opcional) terminal/LT a que o caso se refere
    sentido    (opcional) "frente" (falta na LT/à frente do relé) ou "re" (falta atrás do relé)
    fasores    (opcional, p/ 67 e 67N) {"Ia","Ib","Ic","Va","Vb","Vc": [módulo, ângulo°]}, em kA e kV fase-neutro
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

from core import fasores as FS

CAMPOS = {
    "ponto": "Ponto / barra / caso",
    "tipo": "Tipo de falta (3F, FT, FF, FFT)",
    "local_pct": "Posição na LT (%)",
    "icc_ka": "Corrente de falta no terminal (kA)",
    "rf_ohm": "Resistência de falta (Ω pri) — opcional",
    "terminal": "Terminal / LT — opcional",
    "sentido": "Sentido da falta (frente/ré) — opcional",
}
OBRIGATORIOS = ("tipo", "icc_ka")

SINONIMOS = {
    "ponto": ["ponto", "barra", "bus", "bus id", "bus name", "caso", "case", "nome", "fault location", "local da falta", "ponto de falta"],
    "tipo": ["tipo", "tipo de falta", "falta", "fault type", "type", "tp", "tipo curto"],
    "local_pct": ["local_pct", "local %", "posicao", "posição", "% da lt", "percent", "position", "distancia %", "distância %", "local (%)", "pos (%)"],
    "icc_ka": ["icc", "icc ka", "icc (ka)", "ik", "i k", "ik ka", "i\"k", "corrente", "corrente ka", "i falta", "if", "if ka", "i (ka)", "current ka", "fault current", "corrente de curto", "ka"],
    "rf_ohm": ["rf", "rf ohm", "rf (ohm)", "resistencia de falta", "resistência de falta", "fault resistance", "r falta", "zf"],
    "terminal": ["terminal", "lt", "linha", "line", "circuito", "circuit", "branch"],
    "sentido": ["sentido", "direcao", "direção", "direction", "dir", "forward reverse", "frente re"],
}

SENTIDO_FRENTE = {"frente", "forward", "fw", "f", "direta", "direto", "fwd", "a frente", "à frente", "1"}
SENTIDO_RE = {"re", "ré", "reverso", "reversa", "reverse", "rev", "r", "atras", "atrás", "tras", "trás", "-1"}

# ---- fasores: 12 colunas (módulo e ângulo de 6 grandezas), em fases (A,B,C) ou sequência (1,2,0)
UNID_I = {"kA": 1.0, "A": 1e-3}
UNID_V = ["kV (fase-neutro)", "kV (fase-fase)", "V (fase-neutro)", "pu (base = tensão nominal da LT)"]


def campos_fasores(modo: str) -> dict[str, str]:
    nomes = FS.NOMES_FASE if modo == "fase" else FS.NOMES_SEQ
    out = {}
    for n in nomes:
        un = "kA" if n.startswith("I") else "kV/pu"
        out[f"{n}_m"] = f"|{n}| ({un})"
        out[f"{n}_a"] = f"∠{n} (graus)"
    return out


_PALAVRAS_ANG = ("ang", "angle", "angulo", "deg", "grau", "fase deg", "phi")


def sugerir_mapeamento_fasores(colunas: list[str], modo: str) -> dict:
    """Reconhece colunas como 'Ia (A)', 'Ia ang', '|IA|', 'Va_mod' etc. Devolve {campo_m/a: coluna|None}."""
    norm = {c: _norm(c) for c in colunas}
    nomes = FS.NOMES_FASE if modo == "fase" else FS.NOMES_SEQ
    mapa, usadas = {}, set()
    for n in nomes:
        alvo = n.lower()
        cands = [c for c, t in norm.items() if alvo in t.split() or t.startswith(alvo) or t.replace(" ", "").startswith(alvo)]
        for campo, quer_ang in ((f"{n}_m", False), (f"{n}_a", True)):
            achado = None
            for c in cands:
                if c in usadas:
                    continue
                eh_ang = any(p in norm[c] for p in _PALAVRAS_ANG)
                if eh_ang == quer_ang:
                    achado = c
                    break
            if achado:
                usadas.add(achado)
            mapa[campo] = achado
    return mapa


def normalizar_sentido(x, local_pct=None):
    s = str(x).strip().lower() if x is not None else ""
    if s in SENTIDO_FRENTE:
        return "frente"
    if s in SENTIDO_RE:
        return "re"
    if local_pct is not None and local_pct < 0:
        return "re"
    return None

PRESETS = {
    "Automático (todos os formatos)": {},
    "Anafas (relatório exportado em CSV/Excel)": {"icc_ka": ["ik", "i\"k", "corrente", "icc"]},
    "ETAP (Short Circuit — exportado em CSV/Excel)": {"icc_ka": ["i\"k", "ik", "ikss", "i sc", "isc", "fault current"]},
    "Genérico (colunas já padronizadas)": {},
}

TIPOS_NORMAIS = {
    "3F": "3F", "TRIFASICO": "3F", "TRIFÁSICO": "3F", "3PH": "3F", "3-PH": "3F", "LLL": "3F", "3P": "3F",
    "FT": "FT", "MONOFASICO": "FT", "MONOFÁSICO": "FT", "FASE-TERRA": "FT", "FASE TERRA": "FT", "SLG": "FT", "LG": "FT", "1F": "FT", "1PH": "FT",
    "FF": "FF", "BIFASICO": "FF", "BIFÁSICO": "FF", "FASE-FASE": "FF", "FASE FASE": "FF", "LL": "FF", "2F": "FF",
    "FFT": "FFT", "BIFASICO-TERRA": "FFT", "BIFÁSICO-TERRA": "FFT", "FASE-FASE-TERRA": "FFT", "DLG": "FFT", "LLG": "FFT", "2FT": "FFT",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9%\"]+", " ", s).strip()


def ler_tabela(arquivo, nome: str) -> pd.DataFrame:
    """Lê CSV/TXT/XLSX em DataFrame (colunas como texto, para o usuário revisar)."""
    ext = nome.lower().rsplit(".", 1)[-1]
    dados = arquivo.read() if hasattr(arquivo, "read") else arquivo
    if ext in ("xlsx", "xlsm", "xls"):
        df = pd.read_excel(io.BytesIO(dados), dtype=str)
    else:
        txt = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                txt = dados.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if txt is None:
            raise ValueError("Não foi possível decodificar o arquivo.")
        primeira = txt.splitlines()[0] if txt else ""
        sep = max([";", ",", "\t", "|"], key=primeira.count)
        if primeira.count(sep) == 0:
            df = pd.read_csv(io.StringIO(txt), sep=r"\s{2,}|\t", engine="python", dtype=str)
        else:
            df = pd.read_csv(io.StringIO(txt), sep=sep, dtype=str)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df.reset_index(drop=True)


def sugerir_mapeamento(colunas: list[str], preset: str = "Automático (todos os formatos)") -> dict:
    """Devolve {campo_padrao: nome_da_coluna_ou_None}."""
    extra = PRESETS.get(preset, {})
    norm = {c: _norm(c) for c in colunas}
    mapa = {}
    usadas = set()
    for campo, sins in SINONIMOS.items():
        lista = [_norm(x) for x in extra.get(campo, [])] + [_norm(x) for x in sins]
        achado = None
        for alvo in lista:                      # prioridade: igualdade exata
            for col, n in norm.items():
                if col not in usadas and n == alvo:
                    achado = col
                    break
            if achado:
                break
        if not achado:                          # depois: coluna contém o sinônimo
            for alvo in lista:
                if len(alvo) < 3:
                    continue
                for col, n in norm.items():
                    if col not in usadas and alvo in n:
                        achado = col
                        break
                if achado:
                    break
        if achado:
            usadas.add(achado)
        mapa[campo] = achado
    return mapa


def _num(x):
    if x is None:
        return None
    s = str(x).strip().replace(" ", "")
    if s == "" or s.lower() in ("nan", "none", "-"):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    s = s.replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalizar_tipo(x) -> str:
    s = str(x).strip().upper()
    return TIPOS_NORMAIS.get(s, TIPOS_NORMAIS.get(s.replace("Ø", "F"), s))


def _fasores_da_linha(row, fas: dict, vn_kv: float | None):
    """Lê os 12 campos de fasor de uma linha. Devolve dict de fases em kA/kV fase-neutro ou None."""
    modo, mf = fas["modo"], fas["mapa"]
    nomes = FS.NOMES_FASE if modo == "fase" else FS.NOMES_SEQ
    fi = UNID_I.get(fas.get("un_i", "kA"), 1.0)
    un_v = fas.get("un_v", UNID_V[0])
    base = (vn_kv or 0.0) / (3 ** 0.5)
    valores = {}
    for n in nomes:
        cm, ca = mf.get(f"{n}_m"), mf.get(f"{n}_a")
        if not cm or not ca:
            return None
        m, a = _num(row[cm]), _num(row[ca])
        if m is None or a is None:
            return None
        if n.startswith("I"):
            m *= fi
        else:
            if un_v.startswith("kV (fase-fase)"):
                m /= 3 ** 0.5
            elif un_v.startswith("V (fase-neutro)"):
                m *= 1e-3
            elif un_v.startswith("pu"):
                m *= base
        valores[n] = (m, a)
    if modo == "sequencia":
        f = FS.sequencia_para_caso(valores, tres_x=bool(fas.get("tres_x")))
    else:
        f = {n: [valores[n][0], FS.norm180(valores[n][1])] for n in nomes}
    return FS.inverter_sentido(f) if fas.get("inverter") else f


def padronizar(df: pd.DataFrame, mapa: dict, unidade_corrente: str = "kA",
               fasores: dict | None = None, vn_kv: float | None = None) -> tuple[list[dict], list[str]]:
    """Aplica o mapeamento e devolve (casos, avisos).

    `fasores` (opcional): {"modo": "fase"|"sequencia", "mapa": {campo_m/a: coluna}, "un_i": "kA"|"A",
    "un_v": um de UNID_V, "tres_x": bool, "inverter": bool}. Com ele, cada caso recebe a chave "fasores".
    """
    avisos = []
    tem_fasores = bool(fasores and fasores.get("modo") in ("fase", "sequencia"))
    for campo in OBRIGATORIOS:
        if campo == "icc_ka" and tem_fasores:        # com fasores, a Icc pode ser derivada (maior corrente de fase)
            continue
        if not mapa.get(campo):
            raise ValueError(f"Mapeie a coluna obrigatória: {CAMPOS[campo]}.")
    fator = 1.0 if unidade_corrente == "kA" else 1e-3
    casos, descartados, sem_fasor = [], 0, 0
    for i, row in df.iterrows():
        icc = _num(row[mapa["icc_ka"]]) if mapa.get("icc_ka") else None
        fj = _fasores_da_linha(row, fasores, vn_kv) if tem_fasores else None
        if icc is None and fj is not None:
            icc = max(fj["Ia"][0], fj["Ib"][0], fj["Ic"][0]) / (1.0 if not mapa.get("icc_ka") else fator)
        if icc is None:
            descartados += 1
            continue
        caso = {
            "ponto": str(row[mapa["ponto"]]).strip() if mapa.get("ponto") else f"Caso {i + 1}",
            "tipo": normalizar_tipo(row[mapa["tipo"]]),
            "icc_ka": icc * fator,
            "local_pct": _num(row[mapa["local_pct"]]) if mapa.get("local_pct") else None,
            "rf_ohm": _num(row[mapa["rf_ohm"]]) if mapa.get("rf_ohm") else None,
            "terminal": str(row[mapa["terminal"]]).strip() if mapa.get("terminal") else "",
        }
        if mapa.get("sentido"):
            caso["sentido"] = normalizar_sentido(row[mapa["sentido"]], caso["local_pct"])
        elif caso["local_pct"] is not None and caso["local_pct"] < 0:
            caso["sentido"] = "re"
        if tem_fasores:
            if fj is None:
                sem_fasor += 1
            else:
                caso["fasores"] = fj
        if caso["tipo"] not in ("3F", "FT", "FF", "FFT"):
            avisos.append(f"Linha {i + 2}: tipo de falta '{caso['tipo']}' não reconhecido (use 3F, FT, FF ou FFT).")
        casos.append(caso)
    if descartados:
        avisos.append(f"{descartados} linha(s) sem corrente numérica foram descartadas.")
    if sem_fasor:
        avisos.append(f"{sem_fasor} caso(s) ficaram sem fasores completos (módulo e ângulo de todas as grandezas); "
                      "eles não entram na verificação direcional (67/67N).")
    if not mapa.get("local_pct"):
        avisos.append("Sem coluna de posição na LT: os casos serão usados só para níveis de curto (pickup 51), "
                      "não para a validação cruzada de zonas.")
    return casos, avisos


def casos_para_terminal(casos: list[dict], lt: str, terminal: str) -> list[dict]:
    """Se os casos trazem a coluna terminal/LT, filtra; senão devolve todos."""
    if not any(c.get("terminal") for c in casos):
        return casos
    alvos = {_norm(lt), _norm(terminal), _norm(f"{lt} {terminal}")}
    # 1º: correspondência exata (evita que "AED (Arcoverde II)" capture casos de outra LT)
    exatos = [c for c in casos if _norm(c.get("terminal", "")) in alvos]
    if exatos:
        return exatos
    filtrados = [c for c in casos if any(a and a in _norm(c.get("terminal", "")) for a in alvos)]
    return filtrados or casos
