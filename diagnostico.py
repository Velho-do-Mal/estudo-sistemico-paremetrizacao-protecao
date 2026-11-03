"""Diagnóstico: python diagnostico.py  -> mostra o que impede o app de abrir."""
import importlib, os, sys
print("Python:", sys.version.split()[0], "|", sys.executable)
print("Pasta :", os.getcwd(), "| app.py existe:", os.path.exists("app.py"))
for m in ("streamlit", "pandas", "numpy", "openpyxl", "docx", "matplotlib", "sqlalchemy", "psycopg2", "lxml"):
    try:
        mod = importlib.import_module(m); print(f"OK   {m} {getattr(mod, '__version__', '')}")
    except Exception as e:
        print(f"FALTA {m}: {e}")
try:
    import tomllib
    url = tomllib.load(open(".streamlit/secrets.toml", "rb")).get("DATABASE_URL", "")
    print("secrets.toml: DATABASE_URL", "presente" if url else "vazio")
    from sqlalchemy import create_engine, text
    from core.db import normalizar_url
    with create_engine(normalizar_url(url), connect_args={"connect_timeout": 8}).connect() as c:
        print("Neon: conexão OK", c.execute(text("select 1")).scalar())
except Exception as e:
    print("Neon/secrets:", type(e).__name__, str(e)[:200])
