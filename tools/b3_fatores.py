#!/usr/bin/env python3
"""Sensibilidades medidas de cada ativo a juros, dólar, petróleo e mercado.

Uso: python3 tools/b3_fatores.py

Fontes (todas oficiais e gratuitas):
- Ações e mercado (BOVA11): historico/precos (COTAHIST da B3).
- Dólar: PTAX venda, Banco Central (SGS 1).
- Juros: Tesouro Prefixado (Tesouro Direto, Tesouro Transparente) — taxa do título com
  vencimento mais próximo de 3 anos; a variação diária é sempre do MESMO título, para não
  misturar a troca de vencimento com movimento de juros.
- Petróleo: Brent (EIA, via FRED, série DCOILBRENTEU). Se a fonte falhar, o fator fica fora.

Modelo, por ativo, nos últimos WINDOW pregões com todos os fatores:
  retorno_ativo = a + b_mercado·retorno_BOVA11 + b_juros·Δtaxa(p.p.) + b_dolar·retorno_dólar
                  + b_petroleo·retorno_Brent
Os coeficientes de juros, dólar e petróleo são o efeito ALÉM do mercado (o que diferencia
o ativo do índice). t ≥ 2 em módulo = efeito estatisticamente claro.

Gera fatores/betas.json e fatores/series.json.
"""

import csv
import io
import json
import math
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fatores"
UA = {"User-Agent": "Mozilla/5.0 (atlas-dados)"}
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial={i}&dataFinal={f}"
TESOURO = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
    "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)
FRED_BRENT = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd=2018-12-01"
WINDOW = 504  # cerca de 2 anos de pregões
MIN_OBS = 250
FACTORS = ["mercado", "juros", "dolar", "petroleo"]


def fetch(url: str, timeout: int = 120, tries: int = 3) -> bytes:
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"{url}: {last}")


# ------------------------------------------------------------------- séries


def load_prices() -> dict[str, dict[str, float]]:
    idx = json.loads((ROOT / "historico" / "index.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, float]] = {}
    for y in idx["years"]:
        doc = json.loads((ROOT / "historico" / "precos" / f"{y}.json").read_text(encoding="utf-8"))
        for t, rows in doc["tickers"].items():
            d = out.setdefault(t, {})
            for r in rows:
                d[r[0]] = r[4]
    return out


def usd_series(start: date) -> dict[str, float]:
    out: dict[str, float] = {}
    d0 = start
    today = date.today()
    while d0 <= today:
        d1 = min(today, d0.replace(year=d0.year + 9))
        rows = json.loads(fetch(SGS.format(code=1, i=d0.strftime("%d/%m/%Y"), f=d1.strftime("%d/%m/%Y"))))
        for r in rows:
            dd, mm, yy = r["data"].split("/")
            out[f"{yy}-{mm}-{dd}"] = float(r["valor"])
        d0 = d1 + timedelta(days=1)
    return out


def rate_changes(start: date) -> tuple[dict[str, float], dict[str, dict]]:
    """Δ diário (p.p.) da taxa do Tesouro Prefixado de ~3 anos, sempre do mesmo título."""
    text = fetch(TESOURO, timeout=300).decode("latin-1")
    by_day: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        if row.get("Tipo Titulo", "").strip() != "Tesouro Prefixado":
            continue
        dd, mm, yy = row["Data Base"].split("/")
        day = f"{yy}-{mm}-{dd}"
        if day < start.isoformat():
            continue
        vd, vm, vy = row["Data Vencimento"].split("/")
        try:
            rate = float(row["Taxa Compra Manha"].replace(",", "."))
        except ValueError:
            continue
        if rate <= 0:
            continue
        by_day.setdefault(day, {})[f"{vy}-{vm}-{vd}"] = rate
    days = sorted(by_day)
    changes: dict[str, float] = {}
    level: dict[str, dict] = {}
    for i, day in enumerate(days):
        target = date.fromisoformat(day) + timedelta(days=3 * 365)
        candidates = {m: r for m, r in by_day[day].items()
                      if 1.5 * 365 <= (date.fromisoformat(m) - date.fromisoformat(day)).days <= 6 * 365}
        if not candidates:
            continue
        bond = min(candidates, key=lambda m: abs((date.fromisoformat(m) - target).days))
        level[day] = {"maturity": bond, "rate": candidates[bond]}
        if i > 0 and bond in by_day[days[i - 1]]:
            changes[day] = round(candidates[bond] - by_day[days[i - 1]][bond], 4)
    return changes, level


def brent_series() -> dict[str, float]:
    text = fetch(FRED_BRENT, timeout=180).decode("utf-8")
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) == 2 and row[0][:2] in ("19", "20"):
            try:
                out[row[0]] = float(row[1])
            except ValueError:
                pass
    return out


def log_returns(series: dict[str, float]) -> dict[str, float]:
    days = sorted(series)
    return {days[i]: math.log(series[days[i]] / series[days[i - 1]])
            for i in range(1, len(days)) if series[days[i - 1]] > 0 and series[days[i]] > 0}


# ------------------------------------------------------------------ regressão


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Eliminação de Gauss com pivô (sistemas pequenos)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        if abs(m[c][c]) < 1e-15:
            raise ValueError("matriz singular")
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def inverse(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    cols = [solve(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def ols(y: list[float], xs: list[list[float]]) -> dict:
    """Mínimos quadrados com intercepto. xs: lista de linhas (um vetor de fatores por dia)."""
    rows = [[1.0, *x] for x in xs]
    k = len(rows[0])
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * yy for r, yy in zip(rows, y)) for i in range(k)]
    beta = solve(xtx, xty)
    resid = [yy - sum(b * v for b, v in zip(beta, r)) for r, yy in zip(rows, y)]
    n = len(y)
    s2 = sum(e * e for e in resid) / (n - k)
    cov = inverse(xtx)
    se = [math.sqrt(max(0.0, s2 * cov[i][i])) for i in range(k)]
    mean_y = sum(y) / n
    sst = sum((v - mean_y) ** 2 for v in y)
    return {
        "beta": beta,
        "t": [b / s if s > 0 else 0.0 for b, s in zip(beta, se)],
        "r2": 1 - sum(e * e for e in resid) / sst if sst > 0 else 0.0,
        "n": n,
    }


def stdev(v: list[float]) -> float:
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def main() -> int:
    start = date(2019, 1, 1)
    prices = load_prices()
    if "BOVA11" not in prices:
        print("Sem BOVA11 no histórico")
        return 1
    market = log_returns(prices["BOVA11"])
    usd = log_returns(usd_series(start))
    rates, rate_level = rate_changes(start)
    sources = {
        "mercado": {"title": "B3 — Cotações Históricas (BOVA11)", "url": "https://www.b3.com.br"},
        "juros": {"title": "Tesouro Direto — preços e taxas (Tesouro Transparente)", "url": TESOURO},
        "dolar": {"title": "Banco Central — PTAX venda (SGS 1)", "url": "https://www3.bcb.gov.br/sgspub/"},
    }
    factors_used = ["mercado", "juros", "dolar"]
    brent: dict[str, float] = {}
    try:
        brent = log_returns(brent_series())
        factors_used.append("petroleo")
        sources["petroleo"] = {"title": "EIA — Brent (FRED DCOILBRENTEU)", "url": "https://fred.stlouisfed.org/series/DCOILBRENTEU"}
    except Exception as e:  # noqa: BLE001
        print("Brent indisponível, fator fica fora:", e)

    def factor_row(day: str) -> list[float] | None:
        vals = {"mercado": market.get(day), "juros": rates.get(day), "dolar": usd.get(day), "petroleo": brent.get(day)}
        row = [vals[f] for f in factors_used]
        return None if any(v is None for v in row) else row

    days_all = sorted(d for d in market if factor_row(d) is not None)
    window_days = days_all[-WINDOW:]
    typical = {}
    for i, f in enumerate(factors_used):
        series = [factor_row(d)[i] for d in window_days]
        typical[f] = stdev(series)

    result = {}
    for t, series in prices.items():
        if t == "BOVA11":
            continue
        rets = log_returns(series)
        days = [d for d in window_days if d in rets]
        if len(days) < MIN_OBS:
            continue
        fit = ols([rets[d] for d in days], [factor_row(d) for d in days])
        entry = {"n": fit["n"], "r2": round(fit["r2"], 3), "alphaDailyPct": round(fit["beta"][0] * 100, 4)}
        for i, f in enumerate(factors_used):
            b = fit["beta"][i + 1]
            entry[f] = {
                "beta": round(b, 4),
                "t": round(fit["t"][i + 1], 2),
                # efeito de um movimento típico (1 desvio padrão diário) do fator, em %
                "typicalImpactPct": round(b * typical[f] * 100, 3),
            }
        result[t] = entry

    OUT.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "version": 1,
        "generatedAt": now,
        "window": {"from": window_days[0], "to": window_days[-1], "sessions": len(window_days)},
        "factors": {
            f: {
                "source": sources[f],
                "unit": "p.p. por dia" if f == "juros" else "retorno diário (log)",
                "typicalDailyMove": round(typical[f] * (1 if f == "juros" else 100), 4),
                "typicalDailyMoveUnit": "p.p." if f == "juros" else "%",
            }
            for f in factors_used
        },
        "notes": [
            "Regressão diária: retorno do ativo contra mercado (BOVA11), Δ juros do Tesouro Prefixado "
            "~3 anos, retorno do dólar (PTAX) e do Brent, nos últimos pregões da janela.",
            "Os coeficientes de juros, dólar e petróleo são o efeito além do mercado. |t| ≥ 2 = efeito claro.",
            "typicalImpactPct: quanto o ativo anda (%), além do mercado, num dia de movimento típico "
            "(1 desvio padrão) do fator.",
        ],
        "tickers": result,
    }
    (OUT / "betas.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    last_rate = rate_level[max(rate_level)] if rate_level else None
    (OUT / "series.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generatedAt": now,
                "lastRate": {"date": max(rate_level), **last_rate} if last_rate else None,
                "dolar": dict(list(sorted(usd_series(date.today() - timedelta(days=60)).items()))[-30:]),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"OK: {len(result)} ativos, fatores {factors_used}, janela {window_days[0]}→{window_days[-1]}")
    for t in sorted(result):
        r = result[t]
        print(" ", t, " ".join(f"{f}={r[f]['beta']:+.3f}(t={r[f]['t']:+.1f})" for f in factors_used), f"R2={r['r2']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
