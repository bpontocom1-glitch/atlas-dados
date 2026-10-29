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
   - Resultados de empresas e fatos relevantes dos 20 ativos do universo.
   - Agenda do dia (horário de Brasília) e da noite anterior.
2. **Escrever** o JSON no formato abaixo, em português, com palavras próprias
   (resumir, nunca copiar trechos das matérias).
3. **Validar**: `python3 tools/validar.py briefings/AAAA-MM-DD.json` precisa terminar com `OK`.
4. **Publicar**: copiar para `briefings/latest.json`, commitar e fazer push em `main`.

### Regras

- Nada de números inventados: todo número precisa vir de uma fonte listada em `sources`.
  Se não encontrou, não escreva o número.
- Cada setor com viés precisa de `rationale` (por quê) e, quando houver, `against`
  (o que pode dar errado). Na dúvida, `neutro` com confiança `baixa`.
- Use somente os nomes de setor e tickers do universo (listas em `tools/validar.py`).
- `date` é o pregão a que o relatório se refere; `generatedAt` é o horário real de geração (UTC).
- Se a pesquisa falhar, **não publique** — o Atlas mostra "sem relatório" e não sugere
  operações, que é o comportamento seguro.

### Formato (versão 1)

```json
{
  "version": 1,
  "date": "AAAA-MM-DD",
  "generatedAt": "AAAA-MM-DDTHH:MM:SSZ",
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
               "impact": "alto|medio|baixo" }],
  "sources": [{ "title": "...", "url": "https://...", "publisher": "...",
                "publishedAt": "AAAA-MM-DD" }]
}
```

Os fatores são lidos pelo Atlas junto com a sensibilidade de cada ativo. Exemplo: com
`juros` em `alta`, ativos sensíveis a juros (varejo, locadoras, elétricas) recebem
contexto negativo. O Atlas só sugere uma opção quando esse contexto e a análise
técnica apontam para o mesmo lado.
