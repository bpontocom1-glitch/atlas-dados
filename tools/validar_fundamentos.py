#!/usr/bin/env python3
"""Valida o arquivo de fundamentos do Atlas antes de publicar.

Uso: python3 tools/validar_fundamentos.py fundamentos/latest.json

Espelha src/lib/fundamentals.ts do Atlas (versão 1). Sai com código 1 se houver erro.
"""

import json
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from validar import TICKERS  # noqa: E402

DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIODO = re.compile(r"^[1-4]T\d{2}$")
CAMPOS = {
    # campo: (mínimo, máximo) plausíveis — fora disso é quase sempre erro de unidade
    "revenue": (-1e7, 1e7),
    "revenueYoyPct": (-100, 1000),
    "netIncome": (-1e7, 1e7),
    "netIncomeYoyPct": (-10000, 10000),
    "ebitda": (-1e7, 1e7),
    "ebitdaYoyPct": (-10000, 10000),
    "netDebtToEbitda": (-20, 50),
    "roePct": (-200, 200),
    "netMarginPct": (-500, 200),
}


def main(path: str) -> int:
    erros: list[str] = []
    avisos: list[str] = []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    if d.get("version") != 1:
        erros.append("version deve ser 1")
    if not isinstance(d.get("generatedAt"), str):
        erros.append("generatedAt ausente")
    empresas = d.get("companies")
    if not isinstance(empresas, list):
        erros.append("companies deve ser lista")
        empresas = []

    vistos = set()
    for i, c in enumerate(empresas):
        t = c.get("ticker")
        if t not in TICKERS:
            erros.append(f"companies[{i}].ticker fora do universo: {t}")
        if t in vistos:
            erros.append(f"companies[{i}]: ticker {t} repetido")
        vistos.add(t)
        if not PERIODO.match(str(c.get("period", ""))):
            erros.append(f"companies[{i}].period deve ser no formato 3T26: {c.get('period')}")
        if not DATA.match(str(c.get("reportedAt", ""))):
            erros.append(f"companies[{i}].reportedAt deve ser aaaa-mm-dd")
        preenchidos = 0
        for campo, (lo, hi) in CAMPOS.items():
            v = c.get(campo)
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                erros.append(f"companies[{i}].{campo} deve ser número (ou omitido): {v}")
                continue
            preenchidos += 1
            if not (lo <= v <= hi):
                erros.append(f"companies[{i}].{campo} fora do plausível: {v} (confira a unidade)")
        if preenchidos < 2:
            avisos.append(f"companies[{i}] ({t}): menos de 2 indicadores, o Atlas não calcula nota")
        if not isinstance(c.get("highlights", []), list):
            erros.append(f"companies[{i}].highlights deve ser lista")
        fontes = c.get("sources") or []
        if not fontes:
            erros.append(f"companies[{i}] ({t}): sem fontes — todo número precisa de fonte")
        for j, s in enumerate(fontes):
            u = urlparse(s.get("url", ""))
            if u.scheme not in ("http", "https") or not u.netloc:
                erros.append(f"companies[{i}].sources[{j}].url inválida: {s.get('url')}")
            if not isinstance(s.get("title"), str):
                erros.append(f"companies[{i}].sources[{j}].title ausente")

    for a in avisos:
        print("AVISO:", a)
    for e in erros:
        print("ERRO:", e)
    if erros:
        return 1
    print(f"OK: {path} ({len(empresas)} empresas)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
