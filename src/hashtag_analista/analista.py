"""Junta SendFlow + anúncios do painel, pede a análise ao Claude e manda o resumo no WhatsApp.

Rodar todo dia (cron): python -m hashtag_analista
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic
from supabase import Client, create_client

from . import painel
from .sendflow import SendFlow, por_dia

log = logging.getLogger(__name__)
DIAS_HISTORICO = 14

INSTRUCOES = """\
Você é o analista de marketing do Grupo HASHTAG (empresa de entregas com motoboys). Todo dia você \
recebe os números do SendFlow (entradas, saídas e cliques nos grupos de WhatsApp de cada lançamento) \
e os números de anúncio do painel comercial (investimento no Meta Ads, leads, custo por lead, \
reuniões e vendas, por campanha e por anúncio, acumulados no mês).

Escreva o resumo do dia para mandar num grupo de WhatsApp:
- Comece pelo que mais importa hoje, em uma ou duas linhas.
- Depois os números de ontem comparados com a média dos 7 dias anteriores: entradas, saídas, \
saldo e cliques por lançamento; investimento do dia (diferença do acumulado do mês entre os dois \
últimos dias, quando houver) e leads de anúncio.
- Aponte o que está fora do normal: queda ou alta forte de entradas, saídas maiores que entradas, \
anúncio gastando sem trazer lead ou reunião, custo por lead subindo.
- Feche com no máximo 3 recomendações práticas.
- Formato de WhatsApp: frases curtas, *negrito* com um asterisco, sem tabelas nem markdown de títulos. \
Até ~1.200 caracteres.
- Use só os números recebidos. Se um dado faltar ou parecer errado, diga isso em vez de estimar.
"""


class Analista:
    def __init__(self, db: Client, sendflow: SendFlow | None, lancamentos: list[str], destino: str,
                 cliente: anthropic.Anthropic | None = None, modelo: str = "claude-opus-5-5",
                 esforco: str = "medium", fuso: ZoneInfo = ZoneInfo("America/Fortaleza")):
        self.db, self.sendflow, self.lancamentos, self.destino = db, sendflow, lancamentos, destino
        self.cliente = cliente or anthropic.Anthropic()
        self.modelo, self.esforco, self.fuso = modelo, esforco, fuso

    @classmethod
    def do_ambiente(cls) -> "Analista":
        token = os.environ.get("SENDFLOW_TOKEN", "")
        return cls(
            db=create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]),
            sendflow=SendFlow(token) if token else None,
            lancamentos=[l.strip() for l in os.environ.get("SENDFLOW_LANCAMENTOS", "").split(",") if l.strip()],
            destino=os.environ.get("ANALISTA_DESTINO", "marketing"),
            modelo=os.environ.get("CLAUDE_MODELO", "claude-opus-5-5"),
            esforco=os.environ.get("CLAUDE_ESFORCO", "medium"),
            fuso=ZoneInfo(os.environ.get("FUSO", "America/Fortaleza")),
        )

    # ---------- coleta
    def coletar_sendflow(self, hoje: date) -> dict:
        if not self.sendflow or not self.lancamentos:
            return {"erro": "SendFlow não configurado (SENDFLOW_TOKEN / SENDFLOW_LANCAMENTOS)"}
        inicio = hoje - timedelta(days=DIAS_HISTORICO)
        saida = {}
        for lancamento in self.lancamentos:
            try:
                dias = por_dia(self.sendflow.analytics(lancamento))
                saida[lancamento] = {d.isoformat(): v for d, v in sorted(dias.items()) if inicio <= d <= hoje}
            except Exception as erro:
                log.exception("SendFlow falhou para %s", lancamento)
                saida[lancamento] = {"erro": str(erro)[:200]}
        return saida

    def coletar_painel(self, hoje: date) -> dict:
        r = self.db.table("cache").select("html, atualizado_em").eq("chave", painel.chave_mes(hoje)).limit(1).execute()
        if not r.data:
            return {"erro": f"painel {painel.chave_mes(hoje)} ainda não sincronizado"}
        html = r.data[0]["html"]
        leads = painel.leads_por_dia(html)
        inicio = (hoje - timedelta(days=DIAS_HISTORICO)).isoformat()
        return {
            "atualizado_em": r.data[0]["atualizado_em"],
            "anuncios_mes": painel.resumo_anuncios(html),
            "leads_por_dia": {d: dict(c) for d, c in leads.items() if d >= inicio},
        }

    def snapshot_anterior(self, hoje: date) -> dict | None:
        r = (self.db.table("mkt_snapshots").select("dia, dados").lt("dia", hoje.isoformat())
             .order("dia", desc=True).limit(1).execute())
        return r.data[0] if r.data else None

    # ---------- análise
    def analisar(self, hoje: date, sendflow: dict, painel_dados: dict, anterior: dict | None) -> str:
        dados = {
            "hoje": hoje.isoformat(),
            "sendflow_por_lancamento": sendflow,
            "painel_hoje": painel_dados,
            "painel_snapshot_anterior": anterior,
        }
        r = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.esforco},
            system=INSTRUCOES,
            messages=[{"role": "user", "content": "Números de hoje:\n" + json.dumps(dados, ensure_ascii=False, default=str)}],
        )
        if r.stop_reason == "refusal":
            raise RuntimeError(f"o modelo recusou a análise: {r.stop_details}")
        return "\n\n".join(b.text for b in r.content if b.type == "text").strip()

    # ---------- rodada diária
    def rodar(self) -> dict:
        hoje = datetime.now(self.fuso).date()
        sendflow = self.coletar_sendflow(hoje)
        painel_dados = self.coletar_painel(hoje)
        anterior = self.snapshot_anterior(hoje)
        self.db.table("mkt_snapshots").upsert({
            "dia": hoje.isoformat(), "dados": {"sendflow": sendflow, "painel": painel_dados},
        }).execute()
        resumo = self.analisar(hoje, sendflow, painel_dados, anterior)
        self.db.table("whatsapp_fila").insert({
            "destino": self.destino, "texto": f"📊 *Resumo de marketing · {hoje:%d/%m}*\n\n{resumo}",
            "origem": "analista:diario",
        }).execute()
        self.db.table("mkt_snapshots").update({"resumo": resumo}).eq("dia", hoje.isoformat()).execute()
        return {"dia": hoje.isoformat(), "lancamentos": list(sendflow), "caracteres": len(resumo)}
