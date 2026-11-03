#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install -q -r requirements.txt
echo "Abra http://localhost:8501"
python -m streamlit run app.py --server.port 8501
