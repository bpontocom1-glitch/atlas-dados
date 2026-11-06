#!/usr/bin/env python3
"""Sonda fontes oficiais para as séries diárias dos fatores (juros, dólar, petróleo).
Grava sondagem/fatores.txt. Não publica dados."""

import json
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (atlas-dados)"}


def get(url: str, n: int = 400) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    return f"HTTP {r.status}, {len(data)} bytes: " + data[:n].decode("utf-8", "replace").replace("\n", " | ")


def main() -> None:
    out = []
    for code in [1, 432, 4389, 7805, 7806, 7807, 7808, 7809, 7810, 7811, 7812, 7813, 7814, 7815, 7816, 7817, 7818, 7819, 7820]:
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial=01/01/2019&dataFinal=31/01/2019"
        url_last = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/2?formato=json"
        try:
            first = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
            last = json.loads(urllib.request.urlopen(urllib.request.Request(url_last, headers=UA), timeout=60).read())
            out.append(f"SGS {code}: jan/2019 {len(first)} pontos {first[:2]} ... últimos {last}")
        except Exception as e:  # noqa: BLE001
            out.append(f"SGS {code}: falhou ({e})")
    for name, url in [
        ("FRED Brent", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"),
        ("FRED minério (mensal)", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PIORECRUSDM"),
        ("Tesouro Direto taxas", "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"),
    ]:
        try:
            out.append(f"{name}: {get(url)}")
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: falhou ({e})")
    Path("sondagem").mkdir(exist_ok=True)
    Path("sondagem/fatores.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
