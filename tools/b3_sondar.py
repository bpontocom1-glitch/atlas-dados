#!/usr/bin/env python3
"""Sonda a API do Boletim Diário do Mercado da B3 (arquivos.b3.com.br/bdi) para descobrir
quais tabelas estão acessíveis sem login. Só imprime o resultado; não grava nada.

"ConsolidatedTradesDerivatives" é o nome usado pelo pacote rb3 (rOpenSci) e serve de controle.
Os demais são tentativas para posições em aberto e negócios de ações.
"""

import json
import sys
import urllib.request
from datetime import date

URL = "https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-br"
NAMES = [
    "ConsolidatedTradesDerivatives",
    "ConsolidatedTradesEquities",
    "ConsolidatedTrades",
    "OpenPositionsDerivatives",
    "DerivativesOpenPositions",
    "OpenPositions",
    "OpenPosition",
    "OpenInterest",
    "EquityOptionsOpenPositions",
    "LendingOpenPositions",
]


def main(day: str) -> None:
    for name in NAMES:
        body = json.dumps({"Name": name, "Date": day, "FinalDate": day}).encode()
        req = urllib.request.Request(
            URL, data=body, headers={"Content-Type": "application/json", "User-Agent": "atlas-dados/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            text = data.decode("utf-8", "replace")
            print(f"== {name}: HTTP {r.status}, {len(data)} bytes")
            print("\n".join(text.splitlines()[:4])[:600])
        except Exception as e:  # noqa: BLE001
            print(f"== {name}: falhou ({e})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat())
