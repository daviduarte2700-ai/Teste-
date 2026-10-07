"""Servidor HTTP: webhook do WhatsApp e endpoints das tarefas agendadas.

Rodar: uvicorn hashtag_motoboys.app:app --host 0.0.0.0 --port 8000
"""

import hmac
import json
import logging
from functools import lru_cache

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from . import tarefas, whatsapp
from .agente import Agente
from .config import Config
from .repo import SupabaseRepo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Agente dos motoboys HASHTAG")


@lru_cache
def servicos() -> tuple[Config, SupabaseRepo, whatsapp.WhatsApp, Agente]:
    config = Config.do_ambiente()
    repo = SupabaseRepo(config.supabase_url, config.supabase_service_key, config.coordenacao_destino)
    wa = whatsapp.criar(config)
    return config, repo, wa, Agente(config, repo, wa)


def _confere(recebido: str | None, esperado: str) -> None:
    if not recebido or not hmac.compare_digest(recebido, esperado):
        raise HTTPException(status_code=403)


@app.get("/saude")
def saude():
    return {"ok": True}


@app.get("/webhook")
def verificar_meta(token: str | None = None, hub_mode: str | None = Query(None, alias="hub.mode"),
                   hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
                   hub_challenge: str | None = Query(None, alias="hub.challenge")):
    """Verificação do webhook pedida pela Meta ao cadastrar a URL."""
    config = servicos()[0]
    _confere(token, config.webhook_segredo)
    if hub_mode == "subscribe" and config.meta_verify_token:
        _confere(hub_verify_token, config.meta_verify_token)
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=400)


@app.post("/webhook")
async def receber(request: Request, tarefas_bg: BackgroundTasks, token: str | None = None):
    config, _, wa, agente = servicos()
    _confere(token, config.webhook_segredo)
    corpo_bruto = await request.body()
    if isinstance(wa, whatsapp.MetaCloud) and not wa.assinatura_valida(
        corpo_bruto, request.headers.get("x-hub-signature-256")
    ):
        raise HTTPException(status_code=403)
    for msg in wa.ler_webhook(json.loads(corpo_bruto or b"{}")):
        # Responde 200 na hora; o WhatsApp reenvia o webhook se a resposta demorar.
        tarefas_bg.add_task(agente.atender, msg)
    return {"ok": True}


@app.post("/tarefas/resumo_marketing")
def resumo_marketing(request: Request):
    from hashtag_analista.analista import Analista

    _confere(request.headers.get("x-segredo"), servicos()[0].tarefas_segredo)
    return Analista.do_ambiente().rodar()


@app.post("/tarefas/{nome}")
def rodar_tarefa(nome: str, request: Request):
    config, repo, wa, _ = servicos()
    _confere(request.headers.get("x-segredo"), config.tarefas_segredo)
    try:
        return tarefas.rodar(nome, repo, wa, config)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tarefas: {', '.join(tarefas.TAREFAS)}")
