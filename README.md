# Agente dos Motoboys — Grupo HASHTAG

Bot de WhatsApp que fica no ar 24h e atende os motoboys sozinho. Ele usa o Claude para conversar e grava tudo no Supabase do painel (`painel-hashtag`).

## O que ele faz

**Cadastro e documentos**
- Atende número novo e pede os dados que faltam: nome, CPF, cidade, PIX, placa e modelo da moto.
- Lê a foto da CNH e do CRLV (número, validade e nome), guarda o arquivo no Storage e deixa o documento *pendente* até a coordenação aprovar.
- Quando o cadastro fica completo, avisa a coordenação. Se um motoboy ativo trocar a chave PIX, a coordenação também é avisada (proteção contra golpe).
- Avisa o motoboy 30 dias, 7 dias e no dia em que um documento vence.

**Escala e cobertura**
- Mostra a escala do motoboy e confirma presença.
- Na véspera, pede confirmação de cada turno.
- Quando alguém avisa falta, libera o turno, convida até 5 motoboys livres da mesma cidade e avisa a coordenação. Ficam de fora quem tem turno no mesmo horário, quem está com a CNH vencida e quem ainda não foi aprovado. **Quem confirmar primeiro leva o turno.**
- Se todos recusarem, manda uma nova rodada de convites. Se não houver mais ninguém disponível, avisa a coordenação uma vez.

**Atendimento**
- Tira dúvidas com base em `conhecimento/regras.md` (**preencha esse arquivo com as regras reais**).
- Registra ocorrências (acidente, atraso, problema com loja). Acidente e gravidade alta avisam a coordenação na hora.
- **Pagamento ele não resolve:** registra a ocorrência e chama a coordenação.

Os avisos para a coordenação entram na tabela `whatsapp_fila`, com destino `coordenacao`, a mesma fila que o painel já usa.

## Como funciona

```
WhatsApp (Z-API ou Meta) ──webhook──▶ app.py ──▶ agente.py ──▶ Claude (claude-opus-5-5)
                                                    │ ferramentas.py (só agem no motoboy que está falando)
                                                    ▼
                                         servicos.py (regras de escala/cobertura, em código)
                                                    ▼
                                         Supabase: motoboys, motoboy_documentos, turnos,
                                         coberturas, ocorrencias, mb_conversas, mb_mensagens
cron ──▶ POST /tarefas/{documentos_vencendo | lembrete_turnos | coberturas}
```

- As ferramentas do agente só agem sobre o motoboy dono do número que está conversando. Ninguém consegue mexer no turno ou no cadastro de outro motoboy, nem pedindo.
- As regras de escala (conflito de horário, CNH vencida, quem já foi convidado, primeiro a aceitar) estão em código, não dependem do modelo.
- A conversa recomeça do zero depois de 12h sem mensagens.

## Como colocar no ar

1. **Banco:** aplique `supabase/migrations/20261007120000_motoboys.sql` no projeto `painel-hashtag` (pelo SQL Editor ou com `supabase db push`). Ele cria as tabelas, a função `assumir_turno` e o bucket privado `motoboys`.
2. **Destino da coordenação:** em `whatsapp_destinos`, preencha o `grupo_id` da chave `coordenacao`. Hoje está vazio e os avisos ficam com status `sem_destino`.
3. **WhatsApp:** escolha o provedor.
   - **Z-API** (padrão): é o mais simples, e o bot pode mandar mensagem a qualquer hora. Não é oficial, então existe risco de bloqueio do número. Use um chip só para o bot. No painel da Z-API, configure o webhook "Ao receber" para `https://SEU-SERVIDOR/webhook?token=WEBHOOK_SEGREDO`.
   - **Meta (Cloud API oficial):** sem risco de bloqueio, mas fora das 24h depois da última mensagem do motoboy só é permitido enviar *templates aprovados*. Lembretes, convites de cobertura e avisos de vencimento precisariam de templates, que **ainda não estão implementados**. Configure a URL de callback `https://SEU-SERVIDOR/webhook?token=WEBHOOK_SEGREDO` e o verify token `META_VERIFY_TOKEN`.
4. **Servidor:** qualquer hospedagem de Python serve (Railway, Render, Fly.io, uma VPS). Copie `.env.example` para `.env`, preencha as variáveis e rode:
   ```bash
   pip install .
   uvicorn hashtag_motoboys.app:app --host 0.0.0.0 --port 8000
   ```
   Rode **uma instância só**, porque a fila de mensagens de cada motoboy fica na memória do processo.
5. **Cron** (horários de Fortaleza), enviando o cabeçalho `x-segredo: TAREFAS_SEGREDO`:
   - `POST /tarefas/documentos_vencendo`: todo dia às 8h
   - `POST /tarefas/lembrete_turnos`: todo dia às 18h
   - `POST /tarefas/coberturas`: a cada 30 min

## Rotina da coordenação

- **Montar a escala:** insira os turnos na tabela `turnos` com status `escalado` (com motoboy) ou `aberto` (sem motoboy, que aparece para os motoboys da cidade). Por enquanto isso é feito pelo editor de tabelas do Supabase ou importando um CSV.
- **Aprovar cadastro:** confira os documentos em `motoboy_documentos` (os arquivos estão no bucket `motoboys`), mude o `status` para `aprovado` e o motoboy para `ativo`.
- **Ocorrências:** ficam em `ocorrencias`.
- **Histórico das conversas:** fica em `mb_conversas` e `mb_mensagens`.

## Desenvolvimento

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Os testes usam um banco e um WhatsApp em memória (`tests/fakes.py`) e simulam as respostas do Claude, então não gastam nada.

## Próximos passos sugeridos

- Tela no painel para montar a escala e aprovar documentos (hoje é direto no Supabase).
- Templates da Meta, se o provedor for a Cloud API oficial.
- Transcrição de áudio: hoje o bot pede para o motoboy escrever.

---

# Analista de marketing (SendFlow + anúncios)

Todo dia o analista junta os números de marketing e manda um resumo no WhatsApp:

- **SendFlow:** entradas, saídas e cliques por dia de cada lançamento (`GET /releases/{id}/analytics` da SendAPI, `https://sendapi.sendflow.pro`, com o token Bearer de *Painel SendFlow → API Keys*).
- **Anúncios:** investimento no Meta Ads, leads, custo por lead, por reunião e por venda, por campanha e por anúncio. Esses números vêm do painel comercial (painel.hashtagentrega.com), que a função `sync` grava na tabela `cache` a cada 10 minutos. Também entram os leads por dia e por origem.
- Ele guarda um retrato do dia em `mkt_snapshots`. É com esse retrato que calcula o gasto de cada dia, porque o painel só mostra o acumulado do mês.
- O Claude compara o dia anterior com a média dos 7 dias antes dele. Aponta o que está fora do normal (queda de entradas, saídas maiores que entradas, anúncio gastando sem trazer lead) e sugere até 3 ações.
- O resumo entra na `whatsapp_fila` com destino `marketing`.

**Como ativar**
1. Aplique `supabase/migrations/20261008090000_analista_marketing.sql`.
2. Em `whatsapp_destinos`, preencha o `grupo_id` da chave `marketing` com o grupo que deve receber o resumo.
3. Preencha no servidor `SENDFLOW_TOKEN` e `SENDFLOW_LANCAMENTOS` (os ids dos lançamentos, separados por vírgula).
4. Cron diário (por exemplo, às 8h): `POST /tarefas/resumo_marketing` com o cabeçalho `x-segredo`, ou `python -m hashtag_analista`.
