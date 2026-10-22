#!/usr/bin/env python3
"""Renova a chave do Instagram (vale 60 dias) e avisa se ela mudou.

Roda no GitHub Actions nos dias 1 e 15 de cada mês. A Meta só renova chaves com
mais de 24 h de vida; cada renovação vale 60 dias a partir dela. Se a Meta devolver
uma chave diferente, o script grava a nova no segredo IG_TOKEN quando existir o
segredo GH_PAT; sem ele, sai com erro para o GitHub mandar e-mail avisando.
"""
import os
import subprocess
import sys

import requests

TOKEN = os.environ.get("IG_TOKEN", "").strip()
if not TOKEN:
    print("IG_TOKEN não configurado.")
    sys.exit(1)

r = requests.get("https://graph.instagram.com/refresh_access_token",
                 params={"grant_type": "ig_refresh_token", "access_token": TOKEN}, timeout=60)
corpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
if r.status_code >= 400 or "access_token" not in corpo:
    print(f"Falha ao renovar: HTTP {r.status_code} {str(corpo.get('error', r.text))[:300]}")
    print("Gere uma chave nova no painel da Meta e grave em Settings → Secrets → IG_TOKEN.")
    sys.exit(1)

dias = int(corpo.get("expires_in", 0)) // 86400
nova = corpo["access_token"]
if nova == TOKEN:
    print(f"Chave renovada: vale por mais {dias} dias.")
    sys.exit(0)

if os.environ.get("GH_PAT"):
    subprocess.run(["gh", "secret", "set", "IG_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"]],
                   input=nova.encode(), check=True, env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]})
    print(f"Chave nova gravada no segredo IG_TOKEN; vale por {dias} dias.")
    sys.exit(0)

print("A Meta devolveu uma chave nova e não há GH_PAT para gravá-la sozinha.")
print("Gere a chave no painel da Meta e grave em Settings → Secrets → IG_TOKEN.")
sys.exit(1)
