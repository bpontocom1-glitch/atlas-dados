# atlas-dados

Dados públicos do **Atlas Market Intelligence**: o relatório diário de contexto
(macro, geopolítica, notícias e direção por setor) que o Atlas lê antes de cada pregão.

- `briefings/latest.json` — relatório mais recente (é o que o Atlas lê).
- `briefings/AAAA-MM-DD.json` — histórico, um arquivo por pregão.
- `tools/validar.py` — validação obrigatória antes de publicar.

Conteúdo: análise de mercado de caráter informativo, com fontes citadas.
Não é recomendação de investimento.

---

## Como produzir o relatório (procedimento da tarefa agendada)

1. **Pesquisar** (fontes jornalísticas e oficiais reconhecidas; sempre a data de hoje ou
   do pregão anterior):
   - Fechamento/abertura do Ibovespa, dólar e juros futuros (DI) e o que moveu o mercado.
   - Política monetária e fiscal no Brasil (Copom, Fazenda, Tesouro, Congresso).
   - Exterior: Fed, dados dos EUA, Europa, China.
   - Commodities: petróleo (Brent), minério de ferro.
   - Geopolítica com efeito em mercado.
   - Resultados de empresas e fatos relevantes dos ativos do universo.
   - **Calendário de resultados**: datas de divulgação dos ativos do universo nos próximos
     7 dias úteis e as divulgadas no pregão anterior. Cada uma vira um evento com
     `"kind": "resultado"` e `"tickers": [...]` — o Atlas suspende sugestões nesses ativos.
   - Agenda do dia (horário de Brasília) e da noite anterior.
   - **Curva de juros (DI futuro)**: taxas dos principais contratos DI1 (ex.: DI1F27, DI1F28,
     DI1F29, DI1F31, DI1F33, DI1F35) com a variação do dia, como publicadas nas fontes. Na
     abertura, as do fechamento anterior; no meio-dia, as da manhã. Só publique taxas que
     estejam numa fonte listada; se não houver, omita a seção `rates`.
   - **Viés de abertura do mini índice (WIN) e do mini dólar (WDO)** — só na edição de
     abertura. Leia o que aconteceu fora do pregão brasileiro: futuros de S&P 500 e Nasdaq
     nesta manhã, ADRs brasileiros/EWZ no after-market e no pré-mercado, bolsas da Ásia e da
     Europa, DXY e moedas emergentes, juros dos Treasuries, petróleo e minério, e notícias da
     noite (Brasil e exterior). Para cada contrato: `bias` (alta/baixa/neutro), `confidence`,
     `drivers` (o que sustenta, com números das fontes) e `against` (o que pode inverter).
2. **Escrever** o JSON no formato abaixo, em português, com palavras próprias
   (resumir, nunca copiar trechos das matérias).
3. **Validar**: `python3 tools/validar.py briefings/AAAA-MM-DD.json` precisa terminar com `OK`.
4. **Publicar**: copiar para `briefings/latest.json`, commitar e fazer push em `main`.

### Edições

- **Abertura** (`"edition": "abertura"`, antes do pregão): relatório completo do dia.
- **Meio-dia** (`"edition": "meio-dia"`): parte do relatório da manhã e atualiza o que mudou
  durante a manhã (juros futuros, dólar, notícias, anúncios do governo, resultados). Se um
  setor mudou de direção, ajuste `bias`/`confidence` e explique no `summary`, que deve
  começar com "Atualização do meio-dia:". Se nada relevante mudou, republique com
  `generatedAt` novo e diga isso no `summary`. Sobrescreve o arquivo do mesmo dia.

### Regras

- Nada de números inventados: todo número precisa vir de uma fonte listada em `sources`.
  Se não encontrou, não escreva o número.
- Cada setor com viés precisa de `rationale` (por quê) e, quando houver, `against`
  (o que pode dar errado). Na dúvida, `neutro` com confiança `baixa`.
- Use somente os nomes de setor e tickers do universo (listas em `tools/validar.py`).
- `date` é o pregão a que o relatório se refere; `generatedAt` é o horário real de geração (UTC).
- `time` em eventos é sempre `HH:MM` (horário de Brasília). Sem horário definido, omita o campo.
  Eventos de impacto `alto` com horário bloqueiam entradas no Atlas de 30 minutos antes até
  15 minutos depois; sem horário, viram alerta.
- Se a pesquisa falhar, **não publique** — o Atlas mostra "sem relatório" e não sugere
  operações, que é o comportamento seguro.

### Formato (versão 1)

```json
{
  "version": 1,
  "date": "AAAA-MM-DD",
  "generatedAt": "AAAA-MM-DDTHH:MM:SSZ",
  "edition": "abertura|meio-dia",
  "summary": "Parágrafo com a leitura do dia e o viés geral.",
  "factors": [
    { "factor": "juros|dolar|petroleo|minerio|china|risco-fiscal",
      "direction": "alta|baixa|estavel|incerto", "comment": "..." }
  ],
  "macro": [{ "title": "...", "detail": "..." }],
  "geopolitics": [{ "title": "...", "detail": "..." }],
  "sectors": [
    { "sector": "Nome exato do setor", "bias": "positivo|negativo|neutro",
      "confidence": "baixa|media|alta", "rationale": "...", "against": ["..."] }
  ],
  "assets": [{ "ticker": "PETR4", "bias": "positivo|negativo|neutro", "note": "..." }],
  "events": [{ "date": "AAAA-MM-DD", "time": "09:00", "title": "...",
               "impact": "alto|medio|baixo",
               "kind": "resultado|indicador|politica|outro",
               "tickers": ["VALE3"] }],
  "rates": { "asOf": "Fechamento de DD/MM", "items": [{ "contract": "DI1F27", "rate": 14.97,
             "change": 0.12 }] },
  "opening": [{ "contract": "WIN|WDO", "bias": "alta|baixa|neutro",
                "confidence": "baixa|media|alta", "drivers": ["..."], "against": ["..."],
                "note": "opcional" }],
  "sources": [{ "title": "...", "url": "https://...", "publisher": "...",
                "publishedAt": "AAAA-MM-DD" }]
}
```

Os fatores são lidos pelo Atlas junto com a sensibilidade de cada ativo. Exemplo: com
`juros` em `alta`, ativos sensíveis a juros (varejo, locadoras, elétricas) recebem
contexto negativo. O Atlas só sugere uma opção quando esse contexto e a análise
técnica apontam para o mesmo lado.

---

## Fundamentos por empresa (`fundamentos/latest.json`)

Resultado do último trimestre divulgado de cada ativo do universo (exceto BOVA11). O Atlas
calcula uma nota de qualidade (forte/neutra/fraca) e barra CALL em empresa fraca e PUT em
empresa forte.

### Procedimento (tarefa agendada semanal)

1. Partir do `fundamentos/latest.json` atual (se existir) e, para cada ticker do universo,
   procurar se saiu resultado trimestral mais recente que o registrado (release de resultados
   na página de RI da empresa, ou matéria de fonte jornalística reconhecida sobre o resultado).
2. Só atualizar a empresa que divulgou trimestre novo; as outras ficam como estão.
3. Preencher apenas os campos que estão na fonte. **Campo sem fonte é omitido** — nunca
   calcular, estimar ou completar com memória.
4. Validar: `python3 tools/validar_fundamentos.py fundamentos/latest.json` precisa terminar com `OK`.
5. Copiar para `fundamentos/AAAA-MM-DD.json` (histórico), commitar e fazer push em `main`.

### Formato (versão 1)

```json
{
  "version": 1,
  "generatedAt": "AAAA-MM-DDTHH:MM:SSZ",
  "companies": [
    {
      "ticker": "VALE3",
      "period": "3T26",
      "reportedAt": "AAAA-MM-DD",
      "revenue": 45000,
      "revenueYoyPct": -3.2,
      "netIncome": 9800,
      "netIncomeYoyPct": 12.5,
      "ebitda": 18000,
      "ebitdaYoyPct": 4.1,
      "netDebtToEbitda": 0.9,
      "roePct": 18.2,
      "netMarginPct": 21.8,
      "highlights": ["Frase curta com palavras próprias sobre o que mais pesou."],
      "sources": [{ "title": "...", "url": "https://...", "publisher": "...",
                    "publishedAt": "AAAA-MM-DD" }]
    }
  ]
}
```

- Valores monetários em **R$ milhões**; variações (`...YoyPct`) em % contra o mesmo trimestre do
  ano anterior; `roePct` e `netMarginPct` em %.
- Lucro e EBITDA: usar o número **ajustado/recorrente** quando a empresa divulgar, e dizer isso
  em `highlights`.
- Bancos (ITUB4, BBDC4, BBAS3): sem EBITDA e sem dívida líquida/EBITDA; usar lucro, ROE e
  margem quando houver.
- Empresa sem nenhum resultado encontrado com fonte: deixar fora do arquivo.

---

## Opções — arquivo oficial da B3 (`opcoes/latest.json`)

Gerado automaticamente por um GitHub Action (`.github/workflows/b3-opcoes.yml`) depois do
fechamento, a partir do arquivo público **Cotações Históricas — arquivo diário (COTAHIST)** da
B3. Script: `tools/b3_opcoes.py`.

- `ranking`: todos os ativos com opções negociadas no dia, por volume financeiro em opções,
  com negócios, número de séries líquidas (10+ negócios) e volume de CALL e de PUT.
- `underlyings`: para os ativos do universo, as séries dos dois próximos vencimentos com último
  preço, melhor oferta de compra (`bid`) e de venda (`ask`) no fechamento, negócios e volume.

Nada é estimado: os números são os do arquivo da B3. Não é dado em tempo real (fechamento do
pregão).
