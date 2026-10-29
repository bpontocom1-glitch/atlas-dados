#!/usr/bin/env python3
"""Valida um relatório diário do Atlas antes de publicar.

Uso: python3 tools/validar.py briefings/AAAA-MM-DD.json

Espelha as regras de src/lib/briefing.ts do Atlas (versão 1) e confere se os
setores usados existem no universo de ativos. Sai com código 1 se houver erro.
"""

import json
import re
import sys
from urllib.parse import urlparse

SETORES = {
    "Índice",
    "Petróleo e gás",
    "Mineração",
    "Siderurgia",
    "Bancos",
    "Serviços financeiros",
    "Consumo e varejo",
    "Bebidas",
    "Papel e celulose",
    "Bens de capital",
    "Locação de veículos",
    "Energia elétrica",
    "Saneamento",
    "Combustíveis e logística",
}
TICKERS = {
    "BOVA11", "PETR4", "PRIO3", "VALE3", "GGBR4", "CSNA3", "USIM5", "ITUB4", "BBDC4",
    "BBAS3", "B3SA3", "ABEV3", "MGLU3", "LREN3", "SUZB3", "WEGE3", "RENT3", "CMIG4",
    "SBSP3", "CSAN3",
}
FATORES = {"juros", "dolar", "petroleo", "minerio", "china", "risco-fiscal"}
DIRECOES = {"alta", "baixa", "estavel", "incerto"}
VIES = {"positivo", "negativo", "neutro"}
CONFIANCA = {"baixa", "media", "alta"}
IMPACTO = {"alto", "medio", "baixo"}
TIPOS = {"resultado", "indicador", "politica", "outro"}
EDICOES = {"abertura", "meio-dia"}
HORA = re.compile(r"^\d{1,2}:\d{2}$")
DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main(path: str) -> int:
    erros: list[str] = []
    avisos: list[str] = []

    def err(msg: str) -> None:
        erros.append(msg)

    with open(path, encoding="utf-8") as f:
        b = json.load(f)

    if b.get("version") != 1:
        err("version deve ser 1")
    if not isinstance(b.get("date"), str) or not DATA.match(b["date"]):
        err("date deve ser aaaa-mm-dd")
    if b.get("edition", "abertura") not in EDICOES:
        err(f"edition inválido: {b.get('edition')}")
    if not isinstance(b.get("generatedAt"), str):
        err("generatedAt ausente")
    if not isinstance(b.get("summary"), str) or len(b["summary"]) < 40:
        err("summary ausente ou curto demais")

    for i, f in enumerate(b.get("factors", [])):
        if f.get("factor") not in FATORES:
            err(f"factors[{i}].factor inválido: {f.get('factor')}")
        if f.get("direction") not in DIRECOES:
            err(f"factors[{i}].direction inválido: {f.get('direction')}")
        if not isinstance(f.get("comment"), str):
            err(f"factors[{i}].comment ausente")

    for campo in ("macro", "geopolitics"):
        for i, m in enumerate(b.get(campo, [])):
            if not isinstance(m.get("title"), str) or not isinstance(m.get("detail"), str):
                err(f"{campo}[{i}] precisa de title e detail")

    for i, s in enumerate(b.get("sectors", [])):
        if s.get("sector") not in SETORES:
            avisos.append(f"sectors[{i}].sector fora do universo: {s.get('sector')}")
        if s.get("bias") not in VIES:
            err(f"sectors[{i}].bias inválido: {s.get('bias')}")
        if s.get("confidence") not in CONFIANCA:
            err(f"sectors[{i}].confidence inválido: {s.get('confidence')}")
        if not isinstance(s.get("rationale"), str):
            err(f"sectors[{i}].rationale ausente")
        if not isinstance(s.get("against", []), list):
            err(f"sectors[{i}].against deve ser lista")

    for i, a in enumerate(b.get("assets", [])):
        if a.get("ticker") not in TICKERS:
            avisos.append(f"assets[{i}].ticker fora do universo: {a.get('ticker')}")
        if a.get("bias") not in VIES:
            err(f"assets[{i}].bias inválido: {a.get('bias')}")
        if not isinstance(a.get("note"), str):
            err(f"assets[{i}].note ausente")

    for i, e in enumerate(b.get("events", [])):
        if not isinstance(e.get("date"), str) or not isinstance(e.get("title"), str):
            err(f"events[{i}] precisa de date e title")
        if e.get("impact") not in IMPACTO:
            err(f"events[{i}].impact inválido: {e.get('impact')}")
        if e.get("kind", "outro") not in TIPOS:
            err(f"events[{i}].kind inválido: {e.get('kind')}")
        if "time" in e and not HORA.match(str(e["time"])):
            err(f"events[{i}].time deve ser HH:MM (sem horário definido: omita o campo): {e['time']}")
        for t in e.get("tickers", []):
            if t not in TICKERS:
                avisos.append(f"events[{i}].tickers fora do universo: {t}")
        if e.get("kind") == "resultado" and not e.get("tickers"):
            avisos.append(f"events[{i}] é resultado sem tickers do universo (não bloqueia nenhum ativo)")

    contratos = set()
    for i, o in enumerate(b.get("opening", [])):
        if o.get("contract") not in {"WIN", "WDO"}:
            err(f"opening[{i}].contract inválido: {o.get('contract')}")
        elif o["contract"] in contratos:
            err(f"opening[{i}]: contrato {o['contract']} repetido")
        else:
            contratos.add(o["contract"])
        if o.get("bias") not in {"alta", "baixa", "neutro"}:
            err(f"opening[{i}].bias inválido: {o.get('bias')}")
        if o.get("confidence") not in CONFIANCA:
            err(f"opening[{i}].confidence inválido: {o.get('confidence')}")
        if not o.get("drivers"):
            err(f"opening[{i}].drivers vazio: explique o que sustenta o viés")
    if b.get("edition", "abertura") == "abertura" and contratos != {"WIN", "WDO"}:
        avisos.append("edição de abertura sem viés de abertura para WIN e WDO")

    if not b.get("sources"):
        err("sources vazio: todo relatório precisa citar as fontes")
    for i, s in enumerate(b.get("sources", [])):
        u = urlparse(s.get("url", ""))
        if u.scheme not in ("http", "https") or not u.netloc:
            err(f"sources[{i}].url inválida: {s.get('url')}")
        if not isinstance(s.get("title"), str):
            err(f"sources[{i}].title ausente")

    for a in avisos:
        print("AVISO:", a)
    for e in erros:
        print("ERRO:", e)
    if erros:
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
