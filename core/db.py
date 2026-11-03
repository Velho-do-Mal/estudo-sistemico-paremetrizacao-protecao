"""Camada de banco de dados (Neon/PostgreSQL via SQLAlchemy).

- Em produção usa a variável DATABASE_URL (st.secrets ou ambiente) apontando para o Neon.
- Sem DATABASE_URL, cai para SQLite local (apenas para testes/desenvolvimento).
- Todas as tabelas usam o prefixo `protsis_` para conviver com outros apps no mesmo banco.
- Dados estruturados (parâmetros, resultados) são guardados como JSON em colunas Text,
  o que funciona igual em PostgreSQL e SQLite.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, delete, insert, select, update)

PREFIXO = "protsis_"
metadata = MetaData()

projetos = Table(
    PREFIXO + "projetos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(200), nullable=False),
    Column("cliente", String(200)),
    Column("numero_doc", String(100)),
    Column("revisao", String(20)),
    Column("contato", String(200)),
    Column("referencia", Text),
    Column("criterios", Text),
    Column("criado_em", DateTime(timezone=True)),
    Column("atualizado_em", DateTime(timezone=True)),
)

terminais = Table(
    PREFIXO + "terminais", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("projeto_id", Integer, ForeignKey(PREFIXO + "projetos.id"), nullable=False),
    Column("lt", String(200)),
    Column("terminal", String(100)),
    Column("fabricante", String(100)),
    Column("modelo", String(100)),
    Column("modo", String(20)),       # 'novo' | 'conferencia'
    Column("dados", Text),            # JSON com todos os dados de entrada
    Column("resultado", Text),        # JSON com o último resultado calculado
    Column("atualizado_em", DateTime(timezone=True)),
)

curto = Table(
    PREFIXO + "curto_circuito", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("projeto_id", Integer, ForeignKey(PREFIXO + "projetos.id"), nullable=False),
    Column("arquivo", String(300)),
    Column("origem", String(100)),    # Anafas, ETAP, outro
    Column("dados", Text),            # JSON (lista de casos já padronizados)
    Column("criado_em", DateTime(timezone=True)),
)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def normalizar_url(url: str) -> str:
    """Garante o driver psycopg2 no SQLAlchemy 2.x."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def criar_engine(url: str | None = None):
    """Cria o engine. `url=None` usa DATABASE_URL do ambiente ou SQLite local."""
    url = url or os.environ.get("DATABASE_URL") or ""
    if not url:
        url = "sqlite:///bk_protecao_local.db"
    url = normalizar_url(url)
    kwargs = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs.update(pool_recycle=300)
    engine = create_engine(url, **kwargs)
    return engine


def modo_banco(engine) -> str:
    return "Neon (PostgreSQL)" if engine.dialect.name == "postgresql" else "SQLite local (teste)"


def inicializar(engine) -> None:
    metadata.create_all(engine)


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=float)


def _l(s, padrao=None):
    if not s:
        return padrao
    return json.loads(s)


# ----------------------------------------------------------------- projetos
def listar_projetos(engine) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(projetos).order_by(projetos.c.id.desc())).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["criterios"] = _l(d.get("criterios"), {})
        out.append(d)
    return out


def obter_projeto(engine, pid: int) -> dict | None:
    with engine.connect() as c:
        r = c.execute(select(projetos).where(projetos.c.id == pid)).mappings().first()
    if not r:
        return None
    d = dict(r)
    d["criterios"] = _l(d.get("criterios"), {})
    return d


def criar_projeto(engine, nome, cliente="", numero_doc="", revisao="00", contato="",
                  referencia="", criterios=None) -> int:
    with engine.begin() as c:
        res = c.execute(insert(projetos).values(
            nome=nome, cliente=cliente, numero_doc=numero_doc, revisao=revisao,
            contato=contato, referencia=referencia, criterios=_j(criterios or {}),
            criado_em=_agora(), atualizado_em=_agora()))
        return int(res.inserted_primary_key[0])


def atualizar_projeto(engine, pid: int, **campos) -> None:
    if "criterios" in campos:
        campos["criterios"] = _j(campos["criterios"])
    campos["atualizado_em"] = _agora()
    with engine.begin() as c:
        c.execute(update(projetos).where(projetos.c.id == pid).values(**campos))


def excluir_projeto(engine, pid: int) -> None:
    with engine.begin() as c:
        c.execute(delete(terminais).where(terminais.c.projeto_id == pid))
        c.execute(delete(curto).where(curto.c.projeto_id == pid))
        c.execute(delete(projetos).where(projetos.c.id == pid))


# ---------------------------------------------------------------- terminais
def listar_terminais(engine, pid: int) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(select(terminais).where(terminais.c.projeto_id == pid)
                         .order_by(terminais.c.id)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["dados"] = _l(d.get("dados"), {})
        d["resultado"] = _l(d.get("resultado"), None)
        out.append(d)
    return out


def salvar_terminal(engine, pid: int, dados: dict, tid: int | None = None) -> int:
    campos = dict(lt=dados.get("lt_nome", ""), terminal=dados.get("terminal", ""),
                  fabricante=dados.get("fabricante", ""), modelo=dados.get("modelo", ""),
                  modo=dados.get("modo", "novo"), dados=_j(dados), atualizado_em=_agora())
    with engine.begin() as c:
        if tid:
            c.execute(update(terminais).where(terminais.c.id == tid).values(**campos))
            return tid
        res = c.execute(insert(terminais).values(projeto_id=pid, **campos))
        return int(res.inserted_primary_key[0])


def salvar_resultado(engine, tid: int, resultado: dict) -> None:
    with engine.begin() as c:
        c.execute(update(terminais).where(terminais.c.id == tid)
                  .values(resultado=_j(resultado), atualizado_em=_agora()))


def excluir_terminal(engine, tid: int) -> None:
    with engine.begin() as c:
        c.execute(delete(terminais).where(terminais.c.id == tid))


# ------------------------------------------------------------ curto-circuito
def salvar_curto(engine, pid: int, arquivo: str, origem: str, casos: list[dict]) -> int:
    with engine.begin() as c:
        # um conjunto de casos ativo por projeto: substitui o anterior
        c.execute(delete(curto).where(curto.c.projeto_id == pid))
        res = c.execute(insert(curto).values(projeto_id=pid, arquivo=arquivo, origem=origem,
                                             dados=_j(casos), criado_em=_agora()))
        return int(res.inserted_primary_key[0])


def obter_curto(engine, pid: int) -> dict | None:
    with engine.connect() as c:
        r = c.execute(select(curto).where(curto.c.projeto_id == pid)
                      .order_by(curto.c.id.desc())).mappings().first()
    if not r:
        return None
    d = dict(r)
    d["dados"] = _l(d.get("dados"), [])
    return d
