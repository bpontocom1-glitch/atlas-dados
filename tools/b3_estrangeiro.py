#!/usr/bin/env python3
"""Fluxo de investidor estrangeiro na B3 (mercado à vista), do relatório oficial
"Dados de Mercado" da B3 (CSV).

Uso:
  python3 tools/b3_estrangeiro.py                 # baixa da B3
  python3 tools/b3_estrangeiro.py --arquivo X.csv # arquivo local

O CSV traz o saldo mensal (compras, vendas, IPO/follow-on, saldo) e o mês corrente
acumulado "até dia N", atualizado diariamente com cerca de dois pregões de defasagem.
Guardando o acumulado do mês a cada execução (estrangeiro/acumulado.json), o saldo de
cada dia sai da diferença entre dois acumulados seguidos — sem estimativa.

Gera estrangeiro/latest.json. Valores em R$ milhões.
"""

import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "estrangeiro"
URL = (
    "https://sistemaswebb3-listados.b3.com.br/marketDataProxy/MarketDataCall/"
    "GetDownloadMarketData/RELATORIO_DADOS_DE_MERCADO.csv"
)
PAGE = (
    "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/"
    "consultas/mercado-a-vista/dados-de-mercado/"
)
MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
          "set": 9, "out": 10, "nov": 11, "dez": 12}
MONTHS_EN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
             "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def num(s: str) -> float:
    return float(s.strip().replace(".", "").replace(",", "."))


def parse(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines()]
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("Movimentacao dos Investidores Estrangeiros"))
    except StopIteration as e:
        raise ValueError("tabela de investidores estrangeiros não encontrada no CSV") from e

    monthly, yearly = [], []
    as_of_day = as_of_month = None
    for ln in lines[start + 1 :]:
        if not ln or ln.startswith("Mes /") or ln.startswith("Ano /"):
            continue
        if ln.startswith("(***)"):
            break
        m = re.match(r"\(\*\)\s*Ate dia (\d+)\s+(\w+)", ln)
        if m:
            as_of_day, as_of_month = int(m.group(1)), MONTHS_EN.get(m.group(2)[:3].lower())
            continue
        parts = ln.split(";")
        if len(parts) < 5:
            continue
        label = parts[0]
        values = {"buy": num(parts[1]), "sell": num(parts[2]), "ipo": num(parts[3]), "balance": num(parts[4])}
        mm = re.match(r"(\w{3})/\w{3}/(\d{4})", label)
        if mm and mm.group(1).lower() in MONTHS:
            monthly.append({"month": f"{mm.group(2)}-{MONTHS[mm.group(1).lower()]:02d}", **values})
        elif re.fullmatch(r"\d{4}", label):
            yearly.append({"year": label, **values})
        elif re.fullmatch(r"\d{4}\(\*\)", label):
            yearly.append({"year": label[:4], "partial": True, **values})

    if not monthly or as_of_day is None:
        raise ValueError("CSV sem meses ou sem a data de referência ('Ate dia N')")
    last = monthly[-1]["month"]
    year = int(last[:4])
    as_of = date(year, as_of_month or int(last[5:]), as_of_day).isoformat()
    return {"asOf": as_of, "monthly": monthly, "yearly": sorted(yearly, key=lambda y: y["year"])}


def update_daily(parsed: dict) -> list[dict]:
    """Acrescenta o acumulado do mês e devolve o saldo diário derivado."""
    path = OUT / "acumulado.json"
    acc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    month = parsed["asOf"][:7]
    current = next((m for m in parsed["monthly"] if m["month"] == month), None)
    if current and not any(a["asOf"] == parsed["asOf"] for a in acc):
        acc.append({"asOf": parsed["asOf"], "month": month, "balance": current["balance"]})
        acc.sort(key=lambda a: a["asOf"])
        path.write_text(json.dumps(acc, ensure_ascii=False, indent=0), encoding="utf-8")

    daily = []
    for i, a in enumerate(acc):
        prev = acc[i - 1] if i > 0 else None
        if prev and prev["month"] == a["month"]:
            # diferença de acumulados: pode cobrir mais de um pregão se faltou uma leitura
            daily.append({"date": a["asOf"], "since": prev["asOf"], "balance": round(a["balance"] - prev["balance"], 1)})
        elif a["asOf"][8:] in ("01", "02", "03", "04", "05") and (not prev or prev["month"] != a["month"]):
            daily.append({"date": a["asOf"], "since": f"{a['month']}-01", "balance": a["balance"]})
    return daily[-30:]


def main(argv: list[str]) -> int:
    if "--arquivo" in argv:
        text = Path(argv[argv.index("--arquivo") + 1]).read_text(encoding="latin-1")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (atlas-dados)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("latin-1")
    parsed = parse(text)
    OUT.mkdir(exist_ok=True)
    daily = update_daily(parsed)
    doc = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asOf": parsed["asOf"],
        "unit": "R$ milhões",
        "source": {"title": "B3 — Dados de Mercado: movimentação dos investidores estrangeiros", "url": PAGE},
        "notes": [
            "Mercado à vista. Saldo = compras + IPO/follow-on − vendas.",
            "O mês corrente é acumulado até a data asOf (defasagem de cerca de dois pregões).",
            "Saldo diário = diferença entre dois acumulados seguidos do mês; 'since' indica o "
            "início do intervalo quando ele cobre mais de um pregão.",
        ],
        "monthly": parsed["monthly"],
        "yearly": parsed["yearly"],
        "daily": daily,
    }
    (OUT / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: até {parsed['asOf']}, {len(parsed['monthly'])} meses, {len(daily)} saldos diários")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
