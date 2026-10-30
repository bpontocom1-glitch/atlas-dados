#!/usr/bin/env python3
"""Baixa o arquivo oficial diário de cotações da B3 (COTAHIST) e extrai as opções.

Uso:
  python3 tools/b3_opcoes.py              # último pregão disponível (até 6 dias para trás)
  python3 tools/b3_opcoes.py 2026-10-30   # pregão específico
  python3 tools/b3_opcoes.py --arquivo COTAHIST_D30102026.ZIP 2026-10-30   # arquivo local

Gera opcoes/AAAA-MM-DD.json e opcoes/latest.json com:
- ranking: todos os ativos com opções negociadas, por volume financeiro em opções;
- underlyings: para os ativos do universo do Atlas, as séries dos próximos vencimentos
  (último preço, melhor oferta de compra e de venda no fechamento, negócios, volume).

Fonte: B3, "Cotações Históricas — arquivo diário" (layout SeriesHistoricas_Layout.pdf).
Os números vêm direto do arquivo da B3; nada é estimado.
"""

import io
import json
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validar import TICKERS  # noqa: E402

URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{d:%d%m%Y}.ZIP"
LAYOUT_URL = (
    "https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/"
    "SeriesHistoricas_Layout.pdf"
)

# (início 1-based, largura) conforme o layout oficial
FIELDS = {
    "regtype": (1, 2),
    "date": (3, 8),
    "symbol": (13, 12),
    "market": (25, 3),
    "name": (28, 12),
    "open": (57, 13),
    "high": (70, 13),
    "low": (83, 13),
    "close": (109, 13),
    "bid": (122, 13),
    "ask": (135, 13),
    "trades": (148, 5),
    "contracts": (153, 18),
    "volume": (171, 18),
    "strike": (189, 13),
    "expiry": (203, 8),
}
MARKET_SPOT = "010"
MARKET_CALL = "070"
MARKET_PUT = "080"
#: série com pelo menos isto de negócios no dia conta como "líquida"
LIQUID_TRADES = 10
#: vencimentos publicados por ativo do universo: os próximos mensais e semanais
MAX_MONTHLY = 2
MAX_WEEKLY = 2
#: faixa de strikes publicada, em torno do fechamento da ação
STRIKE_BAND = 0.25


def is_weekly(symbol: str) -> bool:
    """Opções semanais terminam em W1–W5 (ex.: CSNAV420W5)."""
    return len(symbol) > 2 and symbol[-2] == "W" and symbol[-1].isdigit()


def field(line: str, name: str) -> str:
    start, width = FIELDS[name]
    return line[start - 1 : start - 1 + width]


def money(line: str, name: str) -> float:
    return int(field(line, name)) / 100


def parse(text: str) -> tuple[list[dict], list[dict]]:
    """Devolve (ações à vista, opções) do arquivo COTAHIST."""
    spots, options = [], []
    for line in text.splitlines():
        if field(line, "regtype") != "01":
            continue
        market = field(line, "market")
        if market not in (MARKET_SPOT, MARKET_CALL, MARKET_PUT):
            continue
        row = {
            "symbol": field(line, "symbol").strip(),
            "close": money(line, "close"),
            "trades": int(field(line, "trades")),
            "volume": money(line, "volume"),
        }
        if market == MARKET_SPOT:
            spots.append(row)
            continue
        exp = field(line, "expiry")
        row.update(
            {
                "type": "call" if market == MARKET_CALL else "put",
                "strike": money(line, "strike"),
                "expiry": f"{exp[:4]}-{exp[4:6]}-{exp[6:]}",
                "bid": money(line, "bid") or None,
                "ask": money(line, "ask") or None,
                "contracts": int(field(line, "contracts")),
            }
        )
        options.append(row)
    return spots, options


def build(day: date, spots: list[dict], options: list[dict], source_url: str) -> dict:
    # Raiz de 4 letras (PETR) → ação à vista mais negociada com essa raiz (PETR4).
    spot_by_root: dict[str, dict] = {}
    for s in spots:
        root = s["symbol"][:4]
        if root not in spot_by_root or s["volume"] > spot_by_root[root]["volume"]:
            spot_by_root[root] = s
    universe_by_root = {t[:4]: t for t in TICKERS}

    by_root: dict[str, list[dict]] = {}
    for o in options:
        by_root.setdefault(o["symbol"][:4], []).append(o)

    ranking = []
    underlyings = []
    for root, opts in by_root.items():
        traded = [o for o in opts if o["trades"] > 0]
        if not traded:
            continue
        ticker = universe_by_root.get(root) or spot_by_root.get(root, {}).get("symbol") or root
        call_vol = sum(o["volume"] for o in traded if o["type"] == "call")
        put_vol = sum(o["volume"] for o in traded if o["type"] == "put")
        ranking.append(
            {
                "root": root,
                "ticker": ticker,
                "inUniverse": ticker in TICKERS,
                "optionsVolume": round(call_vol + put_vol, 2),
                "optionsTrades": sum(o["trades"] for o in traded),
                "liquidSeries": sum(1 for o in traded if o["trades"] >= LIQUID_TRADES),
                "callVolume": round(call_vol, 2),
                "putVolume": round(put_vol, 2),
            }
        )
        if ticker not in TICKERS:
            continue
        future = [o for o in opts if o["expiry"] > day.isoformat()]
        monthly = sorted({o["expiry"] for o in future if not is_weekly(o["symbol"])})[:MAX_MONTHLY]
        weekly = sorted({o["expiry"] for o in future if is_weekly(o["symbol"])})[:MAX_WEEKLY]
        spot = spot_by_root.get(root) if ticker[:4] == root else None
        spot_close = next((s["close"] for s in spots if s["symbol"] == ticker), None) or (
            spot["close"] if spot else None
        )
        lo, hi = (
            (spot_close * (1 - STRIKE_BAND), spot_close * (1 + STRIKE_BAND))
            if spot_close
            else (0, float("inf"))
        )
        series = sorted(
            (
                {
                    **{k: o[k] for k in ("symbol", "type", "strike", "expiry", "close", "bid",
                                         "ask", "trades", "contracts", "volume")},
                    "weekly": is_weekly(o["symbol"]),
                }
                for o in future
                if (o["expiry"] in monthly and not is_weekly(o["symbol"]))
                or (o["expiry"] in weekly and is_weekly(o["symbol"]))
                if lo <= o["strike"] <= hi and (o["trades"] > 0 or o["bid"] or o["ask"])
            ),
            key=lambda o: (o["expiry"], o["weekly"], o["type"], o["strike"]),
        )
        underlyings.append(
            {
                "ticker": ticker,
                "spotClose": spot_close,
                "monthlyExpiries": monthly,
                "weeklyExpiries": weekly,
                "series": series,
            }
        )

    ranking.sort(key=lambda r: r["optionsVolume"], reverse=True)
    underlyings.sort(key=lambda u: u["ticker"])
    return {
        "version": 1,
        "date": day.isoformat(),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "title": "B3 — Cotações Históricas, arquivo diário (COTAHIST)",
            "url": source_url,
            "layout": LAYOUT_URL,
        },
        "notes": [
            "bid e ask são as melhores ofertas de compra e de venda no fechamento do pregão.",
            f"Série líquida: {LIQUID_TRADES} negócios ou mais no dia.",
            f"Séries do universo: 2 próximos vencimentos mensais e 2 semanais, strikes até "
            f"{int(STRIKE_BAND * 100)}% do fechamento; só séries com negócio ou oferta.",
        ],
        "ranking": ranking[:60],
        "underlyings": underlyings,
    }


def download(day: date) -> bytes | None:
    url = URL.format(d=day)
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-dados/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        print(f"{day}: indisponível ({e})")
        return None
    if not data.startswith(b"PK"):
        print(f"{day}: resposta não é um arquivo zip")
        return None
    return data


def read_zip(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = z.namelist()[0]
        return z.read(name).decode("latin-1")


def main(argv: list[str]) -> int:
    local = None
    if "--arquivo" in argv:
        i = argv.index("--arquivo")
        local = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]
    out_dir = Path(__file__).resolve().parent.parent / "opcoes"
    out_dir.mkdir(exist_ok=True)

    if argv:
        candidates = [date.fromisoformat(argv[0])]
    else:
        today = (datetime.now(timezone.utc) - timedelta(hours=3)).date()
        candidates = [today - timedelta(days=n) for n in range(0, 7)]

    for day in candidates:
        if day.weekday() >= 5:
            continue
        if not argv and (out_dir / f"{day.isoformat()}.json").exists():
            print(f"{day}: já publicado; nada a fazer")
            return 0
        data = local.read_bytes() if local else download(day)
        if data is None:
            continue
        spots, options = parse(read_zip(data))
        if not options:
            print(f"{day}: arquivo sem opções")
            continue
        result = build(day, spots, options, URL.format(d=day))
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        (out_dir / f"{day.isoformat()}.json").write_text(payload, encoding="utf-8")
        (out_dir / "latest.json").write_text(payload, encoding="utf-8")
        print(
            f"OK {day}: {len(options)} séries de opções, {len(result['ranking'])} ativos no ranking, "
            f"{len(result['underlyings'])} ativos do universo"
        )
        return 0
    print("Nenhum arquivo disponível.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
