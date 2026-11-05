#!/usr/bin/env python3
"""Histórico oficial da B3 para o backtest e o IV rank do Atlas.

Uso:
  python3 tools/b3_historico.py --anos 2019-2026      # reconstrói tudo (arquivos anuais)
  python3 tools/b3_historico.py --dia 2026-11-05      # acrescenta um pregão (arquivo diário)
  python3 tools/b3_historico.py --dia                 # último pregão disponível

Fonte: B3, Cotações Históricas (COTAHIST), arquivos anuais e diários.

Gera:
- historico/precos/AAAA.json — candles diários (abertura, máxima, mínima, fechamento, volume)
  das ações do universo, mercado à vista, lote padrão. Desdobramentos e grupamentos
  são detectados pelo salto entre fechamento e abertura e ajustados para trás (lista em
  "adjustments" de historico/index.json). Dividendos NÃO são ajustados.
- historico/iv/AAAA.json — volatilidade implícita no fechamento, por ativo e pregão: média da
  CALL e da PUT mensais mais próximas do dinheiro, no primeiro vencimento com 15 dias
  corridos ou mais, só séries com 5 negócios ou mais. Taxa de juros: Selic meta do
  Banco Central (SGS 432) na data.
"""

import io
import json
import math
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validar import TICKERS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "historico"
URL_YEAR = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{y}.ZIP"
URL_DAY = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{d:%d%m%Y}.ZIP"
SGS_SELIC = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial={i}&dataFinal={f}"

#: Tickers renomeados: ticker atual → (ticker antigo, último pregão com o nome antigo)
ALIASES = {
    "AXIA3": ("ELET3", "2025-11-07"),
    "EMBJ3": ("EMBR3", "2025-10-31"),
}

FIELDS = {
    "regtype": (1, 2),
    "date": (3, 8),
    "bdi": (11, 2),
    "symbol": (13, 12),
    "market": (25, 3),
    "open": (57, 13),
    "high": (70, 13),
    "low": (83, 13),
    "close": (109, 13),
    "bid": (122, 13),
    "ask": (135, 13),
    "trades": (148, 5),
    "volume": (171, 18),
    "strike": (189, 13),
    "expiry": (203, 8),
}


def f(line: str, name: str) -> str:
    s, w = FIELDS[name]
    return line[s - 1 : s - 1 + w]


def m(line: str, name: str) -> float:
    return int(f(line, name)) / 100


def roots_for(ticker: str) -> list[str]:
    r = [ticker[:4]]
    if ticker in ALIASES:
        r.append(ALIASES[ticker][0][:4])
    return r


def spot_names() -> dict[str, str]:
    """Código negociado → ticker do universo (inclui nomes antigos)."""
    names = {t: t for t in TICKERS}
    for t, (old, _) in ALIASES.items():
        names[old] = t
    return names


def is_weekly(symbol: str) -> bool:
    return len(symbol) > 2 and symbol[-2] == "W" and symbol[-1].isdigit()


# ------------------------------------------------------------------ leitura


def read_lines(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open(z.namelist()[0]) as fh:
            for raw in io.TextIOWrapper(fh, encoding="latin-1"):
                yield raw.rstrip("\r\n")


def collect(lines, spots: dict, options: dict) -> None:
    """spots[ticker][date] = candle; options[date][root] = lista de séries."""
    names = spot_names()
    roots = {r: t for t in TICKERS for r in roots_for(t)}
    for line in lines:
        if f(line, "regtype") != "01":
            continue
        market = f(line, "market")
        sym = f(line, "symbol").strip()
        d = f(line, "date")
        day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        # BDI 02 = lote padrão; 14 = cotas de fundos (BOVA11)
        if market == "010" and f(line, "bdi") in ("02", "14") and sym in names:
            t = names[sym]
            if sym != t and day > ALIASES[t][1]:
                continue
            spots.setdefault(t, {})[day] = [
                m(line, "open"), m(line, "high"), m(line, "low"), m(line, "close"),
                round(m(line, "volume")),
            ]
        elif market in ("070", "080") and sym[:4] in roots and not is_weekly(sym):
            trades = int(f(line, "trades"))
            if trades < 5:
                continue
            e = f(line, "expiry")
            options.setdefault(day, {}).setdefault(sym[:4], []).append(
                {
                    "type": "call" if market == "070" else "put",
                    "strike": m(line, "strike"),
                    "expiry": f"{e[:4]}-{e[4:6]}-{e[6:]}",
                    "close": m(line, "close"),
                    "bid": m(line, "bid"),
                    "ask": m(line, "ask"),
                }
            )


def download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-dados/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        print(f"indisponível: {url} ({e})")
        return None
    return data if data.startswith(b"PK") else None


# ------------------------------------------------------- desdobramentos


NICE = [2, 3, 4, 5, 8, 10, 20, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 8, 1 / 10, 1 / 20]


def adjust_splits(ticker: str, candles: list[list]) -> list[dict]:
    """Ajusta para trás os saltos que batem com razões de desdobramento/grupamento.

    candles: [[date, o, h, l, c, v], ...] ordenados. Altera no lugar.
    """
    adjustments = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1][4]
        open_ = candles[i][1]
        if prev_close <= 0 or open_ <= 0:
            continue
        r = open_ / prev_close
        if 0.7 < r < 1.4:
            continue
        k = min(NICE, key=lambda n: abs(r / n - 1))
        if abs(r / k - 1) > 0.12:
            continue
        for j in range(i):
            c = candles[j]
            c[1], c[2], c[3], c[4] = (round(x * k, 4) for x in c[1:5])
            c[5] = round(c[5])  # volume financeiro não muda com desdobramento
        adjustments.append({"ticker": ticker, "date": candles[i][0], "factor": round(1 / k, 4)})
    return adjustments


# ---------------------------------------------------------- volatilidade


def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def bs(type_: str, s: float, k: float, t: float, r: float, v: float) -> float:
    if t <= 0 or v <= 0:
        return max(0.0, s - k) if type_ == "call" else max(0.0, k - s)
    d1 = (math.log(s / k) + (r + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    if type_ == "call":
        return s * ncdf(d1) - k * math.exp(-r * t) * ncdf(d2)
    return k * math.exp(-r * t) * ncdf(-d2) - s * ncdf(-d1)


def implied_vol(type_, price, s, k, t, r) -> float | None:
    intrinsic = max(0.0, s - k * math.exp(-r * t)) if type_ == "call" else max(0.0, k * math.exp(-r * t) - s)
    if price <= intrinsic + 1e-6:
        return None
    lo, hi = 0.01, 5.0
    if bs(type_, s, k, t, r, hi) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs(type_, s, k, t, r, mid) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def business_days(a: str, b: str) -> int:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def selic_series(start: str, end: str) -> list[tuple[str, float]]:
    out = []
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    while d0 <= d1:  # a API limita a 10 anos por consulta
        chunk_end = min(d1, d0.replace(year=d0.year + 9))
        url = SGS_SELIC.format(i=d0.strftime("%d/%m/%Y"), f=chunk_end.strftime("%d/%m/%Y"))
        with urllib.request.urlopen(url, timeout=60) as r:
            for row in json.load(r):
                dd, mm, yy = row["data"].split("/")
                out.append((f"{yy}-{mm}-{dd}", float(row["valor"])))
        d0 = chunk_end + timedelta(days=1)
    return sorted(out)


def rate_on(series: list[tuple[str, float]], day: str) -> float:
    value = series[0][1] if series else 10.0
    for d, v in series:
        if d > day:
            break
        value = v
    return math.log(1 + value / 100)


def atm_iv(day: str, spot: float, opts: list[dict], selic) -> float | None:
    expiries = sorted({o["expiry"] for o in opts if (date.fromisoformat(o["expiry"]) - date.fromisoformat(day)).days >= 15})
    if not expiries:
        return None
    exp = expiries[0]
    t = business_days(day, exp) / 252
    r = rate_on(selic, day)
    ivs = []
    for type_ in ("call", "put"):
        series = [o for o in opts if o["expiry"] == exp and o["type"] == type_]
        if not series:
            continue
        o = min(series, key=lambda x: abs(x["strike"] - spot))
        if abs(o["strike"] / spot - 1) > 0.05:
            continue
        price = o["close"]
        if o["bid"] > 0 and o["ask"] >= o["bid"]:
            mid = (o["bid"] + o["ask"]) / 2
            if mid > 0 and (o["ask"] - o["bid"]) / mid <= 0.3:
                price = mid
        v = implied_vol(type_, price, spot, o["strike"], t, r)
        if v is not None and 0.03 < v < 3:
            ivs.append(v)
    return round(sum(ivs) / len(ivs), 4) if ivs else None


# ------------------------------------------------------------------ saída


SOURCE = {
    "title": "B3 — Cotações Históricas (COTAHIST), arquivos anuais e diários",
    "url": "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/",
}


def dump(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def load_all() -> tuple[dict, list, dict] | None:
    index = OUT / "index.json"
    if not index.exists():
        return None
    meta = json.loads(index.read_text(encoding="utf-8"))
    prices: dict = {}
    iv: dict = {}
    for y in meta["years"]:
        for kind, target in (("precos", prices), ("iv", iv)):
            path = OUT / kind / f"{y}.json"
            if path.exists():
                for t, rows in json.loads(path.read_text(encoding="utf-8"))["tickers"].items():
                    target.setdefault(t, []).extend(rows)
    return prices, meta["adjustments"], iv


def write(prices: dict, adjustments: list, iv: dict, years: set[str] | None = None) -> None:
    """Grava um arquivo por ano (precos/AAAA.json e iv/AAAA.json) e o índice.

    `years`: só esses anos são regravados (None = todos).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_years = sorted({r[0][:4] for rows in prices.values() for r in rows})
    for kind, data in (("precos", prices), ("iv", iv)):
        for y in all_years:
            if years is not None and y not in years:
                continue
            subset = {t: [r for r in rows if r[0][:4] == y] for t, rows in data.items()}
            dump(OUT / kind / f"{y}.json", {"version": 1, "year": y, "tickers": {t: r for t, r in subset.items() if r}})
    dump(
        OUT / "index.json",
        {
            "version": 1,
            "generatedAt": now,
            "source": SOURCE,
            "years": all_years,
            "lastDate": max((rows[-1][0] for rows in prices.values() if rows), default=None),
            "notes": [
                "precos/AAAA.json: candles [data, abertura, máxima, mínima, fechamento, volume financeiro], "
                "mercado à vista, lote padrão.",
                "Desdobramentos/grupamentos ajustados para trás (lista em adjustments); dividendos não ajustados.",
                "iv/AAAA.json: [data, volatilidade implícita no fechamento (fração anual)] — média da CALL e da "
                "PUT mensais mais próximas do dinheiro, primeiro vencimento com 15+ dias corridos, séries com "
                "5+ negócios; taxa: Selic meta (BCB SGS 432).",
            ],
            "adjustments": adjustments,
        },
    )


def build_years(first: int, last: int) -> int:
    spots: dict = {}
    options: dict = {}
    for y in range(first, last + 1):
        data = download(URL_YEAR.format(y=y))
        if data is None:
            print(f"{y}: sem arquivo")
            continue
        collect(read_lines(data), spots, options)
        print(f"{y}: ok ({sum(len(v) for v in spots.values())} candles até aqui)")
    if not spots:
        return 1
    prices = {}
    adjustments = []
    for t, by_day in sorted(spots.items()):
        candles = [[d, *by_day[d]] for d in sorted(by_day)]
        adjustments += adjust_splits(t, candles)
        prices[t] = candles
    selic = selic_series(f"{first}-01-01", date.today().isoformat())
    iv = compute_iv(spots, options, selic)
    write(prices, adjustments, iv)
    print(f"OK: {len(prices)} ativos, {len(adjustments)} ajustes, IV de {len(iv)} ativos")
    for a in adjustments:
        print("  ajuste:", a)
    return 0


def compute_iv(spots: dict, options: dict, selic) -> dict:
    """IV usa o fechamento SEM ajuste (o strike do dia está na mesma base)."""
    iv: dict = {}
    for t in TICKERS:
        by_day = spots.get(t, {})
        for day in sorted(by_day):
            opts = []
            for root in roots_for(t):
                opts += options.get(day, {}).get(root, [])
            if not opts:
                continue
            v = atm_iv(day, by_day[day][3], opts, selic)
            if v is not None:
                iv.setdefault(t, []).append([day, v])
    return iv


def append_day(day: date | None) -> int:
    loaded = load_all()
    if not loaded:
        print("Histórico ainda não construído: rode com --anos primeiro.")
        return 1
    prices, adjustments, iv = loaded
    candidates = [day] if day else [
        (datetime.now(timezone.utc) - timedelta(hours=3)).date() - timedelta(days=n) for n in range(7)
    ]
    for d in candidates:
        if d.weekday() >= 5:
            continue
        iso = d.isoformat()
        if any(rows and rows[-1][0] >= iso for rows in prices.values()):
            print(f"{iso}: já no histórico")
            return 0
        data = download(URL_DAY.format(d=d))
        if data is None:
            continue
        spots: dict = {}
        options: dict = {}
        collect(read_lines(data), spots, options)
        if not spots:
            continue
        split_today = False
        for t, by_day in spots.items():
            candles = prices.setdefault(t, [])
            candles.append([iso, *by_day[iso]])
            # adjust_splits sobre os 2 últimos já ajusta o penúltimo; o resto vem aqui
            new = adjust_splits(t, candles[-2:]) if len(candles) >= 2 else []
            if new:
                k = 1 / new[0]["factor"]
                for c in candles[:-2]:
                    c[1], c[2], c[3], c[4] = (round(x * k, 4) for x in c[1:5])
                adjustments.append(new[0])
                split_today = True
        selic = selic_series((d - timedelta(days=40)).isoformat(), iso)
        for t, values in compute_iv(spots, options, selic).items():
            iv.setdefault(t, []).extend(values)
        write(prices, adjustments, iv, None if split_today else {iso[:4]})
        print(f"OK {iso}: {len(spots)} ativos acrescentados" + (" (com desdobramento)" if split_today else ""))
        return 0
    print("Nenhum pregão novo disponível.")
    return 0


def main(argv: list[str]) -> int:
    if "--anos" in argv:
        a, b = argv[argv.index("--anos") + 1].split("-")
        return build_years(int(a), int(b))
    if "--dia" in argv:
        i = argv.index("--dia")
        d = date.fromisoformat(argv[i + 1]) if len(argv) > i + 1 else None
        return append_day(d)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
