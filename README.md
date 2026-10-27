# F.O.G.O. — Central de operações

Demonstração integrada de inventário urbano, monitoramento e apoio à decisão. O foco é ser pequena o bastante para explicar cada parte e completa o bastante para percorrer um fluxo de ponta a ponta.

[Assistir à demonstração em vídeo](demo/demonstracao.mp4).

## Iniciar no Windows

1. Tenha Python 3.10 ou posterior instalado. Não há pacotes Python para instalar.
2. Execute `Iniciar FOGO.bat`.
3. O painel abre em `http://127.0.0.1:8000`. O servidor e o simulador ficam em janelas separadas; encerre cada uma com `Ctrl+C`.

Também é possível iniciar manualmente em dois terminais, nesta pasta:

```powershell
python server.py
python simulador.py --interval 25
```

O banco `fogo.sqlite3` e os dados de demonstração são criados automaticamente na primeira inicialização. Ao abrir uma base existente, o aplicativo acrescenta as colunas de órgão e referência sem apagar os cadastros. Para recomeçar do zero, pare os processos e apague esse banco local. Os bairros, coordenadas e ocorrências iniciais são **dados sintéticos de demonstração** situados aproximadamente em João Pessoa/PB; não representam ativos, efetivo ou ocorrências reais.

## Percurso da demonstração

1. **Inventário:** busque e filtre por tipo, situação, bairro, região administrativa e órgão responsável; crie, edite ou exclua equipamentos e agentes. Equipamentos incluem referência de localização, órgão responsável, endereço por CEP (ViaCEP), coordenadas GPS e características editáveis em JSON. Se o serviço de CEP estiver indisponível, o cadastro manual continua disponível.
2. **Central:** veja equipamentos e agentes no Leaflet e filtre por tipo, situação, bairro, região e órgão. Os popups mostram modelo, endereço, referência, órgão e atributos do equipamento; os agentes têm ícones por função. Acompanhe disponibilidade, alertas, manutenção próxima e atividade ao vivo. Use **Simular evento** para disparar uma leitura na hora.
3. **Cidade preditiva:** explore a matriz de risco por região e hora, a tendência de saúde dos equipamentos, sinais fora do padrão e recomendações de cobertura. **Registrar ocorrência** acrescenta um dado ao histórico e recalcula a previsão.

## Arquitetura enxuta

- `server.py`: API HTTP em Python padrão, persistência SQLite, validação dos cadastros, cálculo das previsões e eventos SSE. Os dados de fuso IANA necessários no Windows estão incluídos em `vendor/tzdata`; mantenha essa pasta ao copiar ou compactar o projeto.
- `simulador.py`: processo independente que envia leituras IoT; atualiza saúde, muda situação em casos de falha, pode simular furto e movimenta agentes ativos.
- `static/index.html`, `static/style.css`, `static/app.js`: aplicação web responsiva. O mapa usa Leaflet e tiles do OpenStreetMap; não precisa de chave de mapa, mas precisa de internet para carregar tiles, Leaflet, ViaCEP e fontes remotas.

Rotas principais: `GET /api/state`, `GET /api/predictions`, `GET /api/events` (SSE), `GET /api/cep?cep=...`, operações CRUD em `/api/equipment` e `/api/agents`, `POST /api/simulate`, `POST /api/occurrences` e `POST /api/maintenance`.

## Como explicar as previsões

- **Risco relativo por região/hora:** soma ponderada de ocorrências dos últimos 90 dias, com decaimento exponencial de recência e vizinhança de uma hora (65%); proporção de equipamentos instalados fora de operação (20%); e manutenções imediatas ou previstas para até sete dias (15%). O resultado é limitado ao intervalo 0–100% e serve para priorizar revisão humana. Não é probabilidade calibrada de crime.
- **Tendência e projeção de falha:** compara a média de saúde recente (últimos três dias) com a janela anterior (10–14 dias) e estende linearmente essa variação por sete dias, limitada a 0–100. Uma queda acima de 5 ou 12 pontos percentuais eleva o nível de atenção. A projeção é indicativa; amostra pequena reduz a confiança.
- **Fora do padrão:** compara a contagem móvel de 24 horas por bairro com as 28 janelas anteriores de 24 horas. Sinaliza contagens acima da média + 2,5 desvios-padrão, com mínimo de três eventos, junto às regras explícitas de situação e manutenção. O alerta orienta revisão humana e não é uma conclusão sobre crime.
- **Reforço de agentes:** setores acima de 55% de risco recebem uma referência demonstrativa de efetivo mínimo (máximo entre dois agentes e teto de risco × 3). O painel compara essa referência com agentes ativos por bairro. O cálculo não representa escala operacional nem despacha equipes.

## Escopo e limites desta versão

- É uma prova de conceito local. Não inclui autenticação, perfis, auditoria administrativa, criptografia em trânsito, hospedagem, integração com sensores reais nem SLA; não exponha o servidor à internet pública nem use dados pessoais/reais sem projetar essas salvaguardas.
- A relação entre bairros e regiões administrativas é sintética e serve somente à demonstração; não representa limites oficiais. Ajuste os setores e coordenadas a uma fonte municipal validada antes de qualquer uso operacional.
- A simulação e o histórico sintético servem para demonstrar a interface e o fluxo de dados, não para avaliar desempenho preditivo.
- Prazo informado para esta etapa: 27/10/2026 às 23:59 (horário de Brasília).

## Transparência sobre IA

Este protótipo foi elaborado com assistência de **OpenAI Codex (GPT-6)**. A lógica de risco é determinística e pode ser explicada e revisada pelo autor; a IA foi usada como apoio de desenvolvimento, não como componente de decisão do sistema. O autor deve descrever no formulário da competição como utilizou assistência de IA e confirmar que a declaração corresponde ao processo real de desenvolvimento.
