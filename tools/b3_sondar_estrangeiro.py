#!/usr/bin/env python3
"""Sonda a página "Dados de Mercado" da B3 (fluxo de investidor estrangeiro, item 3.2)
e lista os links de planilha encontrados. Só grava o resultado em sondagem/; não publica dados.
"""

import re
import urllib.request
from pathlib import Path

PAGES = [
    "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/mercado-a-vista/dados-de-mercado/",
    "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/mercado-a-vista/participacao-dos-investidores/",
]


def main() -> None:
    out: list[str] = []
    for url in PAGES:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (atlas-dados)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8", "replace")
            out.append(f"== {url}: HTTP {r.status}, {len(html)} bytes")
            for m in sorted(set(re.findall(r'href="([^"]+)"', html))):
                if re.search(r"\.(xlsx?|csv|zip)|data/files|download", m, re.I):
                    out.append(f"  {m}")
            for m in sorted(set(re.findall(r'src="([^"]+)"', html))):
                if "iframe" in m or "sistemaswebb3" in m or "arquivos" in m:
                    out.append(f"  src: {m}")
            for m in sorted(set(re.findall(r'https?://[^"\'\s<>]*(?:sistemaswebb3|arquivos\.b3)[^"\'\s<>]*', html))):
                out.append(f"  url: {m}")
        except Exception as e:  # noqa: BLE001
            out.append(f"== {url}: falhou ({e})")
    Path("sondagem").mkdir(exist_ok=True)
    Path("sondagem/estrangeiro.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
