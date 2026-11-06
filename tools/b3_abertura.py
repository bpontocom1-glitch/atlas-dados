#!/usr/bin/env python3
"""Histórico do viés de abertura (WIN e WDO) e o que o mercado fez de fato.

Uso: python3 tools/b3_abertura.py

- Viés: lido de briefings/AAAA-MM-DD.json (seção "opening", publicada antes do pregão).
- Resultado: Boletim Diário da B3, tabela "ConsolidatedTradesDerivatives" (oficial), do
  contrato mais negociado do mini índice (WIN) e do mini dólar (WDO): abertura, máxima,
  mínima, fechamento, ajuste do dia e ajuste do dia anterior.

Gera abertura/historico.json (dia a dia) e abertura/placar.json (resumo, lido pela tarefa
do relatório da manhã). O acerto é calculado contra o AJUSTE DO DIA ANTERIOR:
- abertura: preço de abertura vs ajuste anterior;
- dia: ajuste do dia vs ajuste anterior.
Movimento menor que a faixa lateral (WIN 0,15%, WDO 0,10%) conta como "lateral".
"""

import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "abertura"
BOLETIM = "https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-br"
LATERAL = {"WIN": 0.15, "WDO": 0.10}  # % abaixo do qual o movimento é "lateral"
CONTRACT = {"WIN": re.compile(r"^WIN[FGHJKMNQUVXZ]\d{2}$"), "WDO": re.compile(r"^WDO[FGHJKMNQUVXZ]\d{2}$")}
SOURCE = {
    "title": "B3 — Boletim Diário do Mercado (negócios consolidados de derivativos)",
    "url": "https://arquivos.b3.com.br/bdi/",
}


def num(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def fetch_derivatives(day: str) -> list[dict] | None:
    body = json.dumps({"Name": "ConsolidatedTradesDerivatives", "Date": day, "FinalDate": day}).encode()
    req = urllib.request.Request(
        BOLETIM, data=body, headers={"Content-Type": "application/json", "User-Agent": "atlas-dados/1.0"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8-sig", "replace")
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("Instrumento financeiro;"))
    except StopIteration:
        return None
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter=";"))
    return [r for r in rows if r.get("Instrumento financeiro") and "Nenhum resultado" not in r["Instrumento financeiro"]]


def front_contract(rows: list[dict], key: str) -> dict | None:
    """Contrato mais negociado do mini (WIN ou WDO) no dia."""
    cands = [r for r in rows if CONTRACT[key].match(r["Instrumento financeiro"].strip())]
    if not cands:
        return None
    r = max(cands, key=lambda x: num(x.get("Quantidade de contratos")) or 0)
    return {
        "contract": r["Instrumento financeiro"].strip(),
        "open": num(r.get("Preço de abertura")),
        "high": num(r.get("Preço máximo")),
        "low": num(r.get("Preço mínimo")),
        "close": num(r.get("Preço de fechamento")),
        "settle": num(r.get("Ajuste")),
        "prevSettle": num(r.get("Ajuste do dia anterior")),
        "contracts": num(r.get("Quantidade de contratos")),
    }


def direction(move_pct: float | None, key: str) -> str | None:
    if move_pct is None:
        return None
    if abs(move_pct) < LATERAL[key]:
        return "lateral"
    return "alta" if move_pct > 0 else "baixa"


def score(bias: str, realized: str | None) -> bool | None:
    if realized is None:
        return None
    if bias == "neutro":
        return realized == "lateral"
    return bias == realized


def pct(a: float | None, b: float | None) -> float | None:
    return round((a / b - 1) * 100, 3) if a and b else None


def main() -> int:
    OUT.mkdir(exist_ok=True)
    cache_path = OUT / "resultados.json"
    cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    now_br = datetime.now(timezone.utc) - timedelta(hours=3)

    days = []
    for path in sorted((ROOT / "briefings").glob("20??-??-??.json")):
        b = json.loads(path.read_text(encoding="utf-8"))
        opening = {o["contract"]: o for o in b.get("opening", []) if o.get("contract") in CONTRACT}
        if not opening:
            continue
        day = b["date"]
        # Resultado oficial: só depois do pregão (a B3 publica à noite).
        finished = day < now_br.date().isoformat() or now_br.hour >= 19
        if day not in cache and finished:
            try:
                rows = fetch_derivatives(day)
                if rows:
                    cache[day] = {k: front_contract(rows, k) for k in CONTRACT}
                    print(f"{day}: resultado oficial obtido")
                else:
                    print(f"{day}: boletim ainda sem dados")
            except Exception as e:  # noqa: BLE001
                print(f"{day}: boletim indisponível ({e})")
        entry = {"date": day, "edition": b.get("edition", "abertura"), "generatedAt": b.get("generatedAt")}
        for k, o in opening.items():
            res = (cache.get(day) or {}).get(k)
            item = {
                "bias": o["bias"],
                "confidence": o["confidence"],
                "drivers": o.get("drivers", []),
                "against": o.get("against", []),
                "note": o.get("note"),
            }
            if res:
                open_move = pct(res["open"], res["prevSettle"])
                day_move = pct(res["settle"] or res["close"], res["prevSettle"])
                item["result"] = {
                    **res,
                    "openMovePct": open_move,
                    "dayMovePct": day_move,
                    "openDirection": direction(open_move, k),
                    "dayDirection": direction(day_move, k),
                    "openHit": score(o["bias"], direction(open_move, k)),
                    "dayHit": score(o["bias"], direction(day_move, k)),
                }
            entry[k] = item
        days.append(entry)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "version": 1,
        "generatedAt": now,
        "source": SOURCE,
        "lateralPct": LATERAL,
        "notes": [
            "Viés: seção 'opening' do relatório de cada pregão (antes da abertura).",
            "Resultado: contrato mais negociado do dia; abertura e ajuste comparados com o ajuste do dia anterior.",
            "Movimento abaixo da faixa lateral conta como 'lateral'; viés neutro acerta quando o movimento é lateral.",
        ],
        "days": sorted(days, key=lambda d: d["date"], reverse=True),
    }
    (OUT / "historico.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Placar resumido para a tarefa da manhã
    summary = {}
    for k in CONTRACT:
        scored = [d[k] for d in days if k in d and d[k].get("result") and d[k]["result"]["openHit"] is not None]
        by_conf = {}
        for c in ("baixa", "media", "alta"):
            sub = [x for x in scored if x["confidence"] == c]
            if sub:
                by_conf[c] = {
                    "n": len(sub),
                    "openHits": sum(1 for x in sub if x["result"]["openHit"]),
                    "dayHits": sum(1 for x in sub if x["result"]["dayHit"]),
                }
        summary[k] = {"n": len(scored), "byConfidence": by_conf}
    recent_misses = [
        {"date": d["date"], "contract": k, "bias": d[k]["bias"], "confidence": d[k]["confidence"],
         "opened": d[k]["result"]["openDirection"], "day": d[k]["result"]["dayDirection"], "drivers": d[k]["drivers"]}
        for d in sorted(days, key=lambda x: x["date"], reverse=True)[:15]
        for k in CONTRACT
        if k in d and d[k].get("result") and d[k]["result"]["openHit"] is False
    ][:8]
    (OUT / "placar.json").write_text(
        json.dumps({"version": 1, "generatedAt": now, "summary": summary, "recentMisses": recent_misses},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"OK: {len(days)} dias com viés; resultados oficiais de {len(cache)} dias")
    return 0


if __name__ == "__main__":
    sys.exit(main())
