@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === BK Protecao Sistemica ===
if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv || (echo ERRO: Python nao encontrado. Instale Python 3.11-3.13 e marque "Add to PATH". & pause & exit /b 1)
)
call .venv\Scripts\activate
python -m pip install -q -r requirements.txt || (echo ERRO na instalacao. & pause & exit /b 1)
echo.
echo Abrindo o app em http://localhost:8501 ...
start "" http://localhost:8501
python -m streamlit run app.py --server.headless true --server.port 8501
pause
