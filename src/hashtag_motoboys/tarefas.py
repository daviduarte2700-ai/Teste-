"""Tarefas agendadas. Rode por cron chamando POST /tarefas/<nome> ou `python -m hashtag_motoboys.tarefas <nome>`.

- documentos_vencendo: 1x por dia (manhã)
- lembrete_turnos:     1x por dia (fim da tarde), pede confirmação dos turnos de amanhã
- coberturas:          a cada 30 min, insiste nas faltas ainda sem cobertura
"""

import logging
import sys
from datetime import date, datetime, timedelta

from . import servicos
from .config import Config
from .repo import Repo
from .whatsapp import WhatsApp

log = logging.getLogger(__name__)
AVISOS_VENCIMENTO = (30, 7, 0)
MARCA_SEM_COBERTURA = "[coordenação avisada: sem cobertura]"
NOMES_DOC = {"cnh": "CNH", "crlv": "CRLV", "comprovante_residencia": "comprovante de residência", "mei": "MEI"}


def documentos_vencendo(repo: Repo, wa: WhatsApp, config: Config, hoje: date) -> dict:
    enviados, vencidos = 0, []
    for doc in repo.documentos_aprovados_vencendo(hoje + timedelta(days=max(AVISOS_VENCIMENTO))):
        m = doc.get("motoboys") or {}
        if m.get("status") != "ativo" or doc["tipo"] not in NOMES_DOC:
            continue
        validade = date.fromisoformat(str(doc["validade"]))
        faltam = (validade - hoje).days
        nome = NOMES_DOC[doc["tipo"]]
        if faltam in AVISOS_VENCIMENTO:
            quando = "vence *hoje*" if faltam == 0 else f"vence em {faltam} dias ({validade:%d/%m})"
            wa.enviar_texto(m["telefone"], f"Oi! Sua {nome} {quando}. Manda aqui a foto da nova para não ficar fora da escala. 🛵")
            enviados += 1
        if faltam == 0:
            vencidos.append(f"• {m.get('nome') or m['telefone']}: {nome}")
    if vencidos:
        repo.avisar_coordenacao("📄 DOCUMENTOS VENCENDO HOJE\n" + "\n".join(vencidos), origem="motoboys:documentos")
    return {"avisos_enviados": enviados, "vencendo_hoje": len(vencidos)}


def lembrete_turnos(repo: Repo, wa: WhatsApp, config: Config, hoje: date) -> dict:
    amanha = hoje + timedelta(days=1)
    enviados = 0
    for t in repo.turnos_por_status(["escalado"], amanha, amanha):
        m = repo.motoboy(t["motoboy_id"]) if t.get("motoboy_id") else None
        if not m:
            continue
        wa.enviar_texto(
            m["telefone"],
            f"Lembrete do seu turno de amanhã:\n{servicos.descrever_turno(t)}\n\n"
            "Responde aqui confirmando que vai. Se não puder ir, avisa agora para eu achar quem cubra.",
        )
        enviados += 1
    return {"lembretes_enviados": enviados}


def coberturas(repo: Repo, wa: WhatsApp, config: Config, hoje: date) -> dict:
    rodadas, sem_ninguem = 0, 0
    for t in repo.turnos_por_status(["falta"], hoje, hoje + timedelta(days=1)):
        if t.get("motoboy_id") is not None:
            continue
        convites = repo.convites_do_turno(t["id"])
        if any(c["status"] == "convidado" for c in convites):
            continue  # ainda tem gente para responder
        novos = servicos.disparar_cobertura(repo, wa, t, config.convites_por_falta)
        rodadas += 1
        if not novos and MARCA_SEM_COBERTURA not in (t.get("obs") or ""):
            sem_ninguem += 1
            repo.avisar_coordenacao(
                f"❗ SEM COBERTURA\nNinguém disponível ou todos recusaram:\n{servicos.descrever_turno(t)}",
                origem="motoboys:cobertura",
            )
            repo.atualizar_turno(t["id"], {"obs": f"{t.get('obs') or ''} {MARCA_SEM_COBERTURA}".strip()})
    return {"novas_rodadas": rodadas, "sem_cobertura": sem_ninguem}


TAREFAS = {f.__name__: f for f in (documentos_vencendo, lembrete_turnos, coberturas)}


def rodar(nome: str, repo: Repo, wa: WhatsApp, config: Config) -> dict:
    if nome not in TAREFAS:
        raise KeyError(nome)
    return TAREFAS[nome](repo, wa, config, datetime.now(config.fuso).date())


if __name__ == "__main__":
    from . import whatsapp
    from .repo import SupabaseRepo

    logging.basicConfig(level=logging.INFO)
    cfg = Config.do_ambiente()
    print(rodar(sys.argv[1], SupabaseRepo(cfg.supabase_url, cfg.supabase_service_key, cfg.coordenacao_destino),
                whatsapp.criar(cfg), cfg))
