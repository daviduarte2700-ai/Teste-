from datetime import date, timedelta
from pathlib import Path

import pytest
from anthropic.types.beta import BetaMessage

from hashtag_motoboys import servicos, tarefas, telefone
from hashtag_motoboys.agente import Agente
from hashtag_motoboys.config import Config
from hashtag_motoboys.whatsapp import MetaCloud, Midia, MensagemRecebida, ZApi

from fakes import FakeRepo, FakeWhatsApp

HOJE = date(2026, 10, 7)
AMANHA = (HOJE + timedelta(days=1)).isoformat()
CIDADE = "Fortaleza - CE"


def config(**extra) -> Config:
    return Config(supabase_url="", supabase_service_key="", whatsapp_provedor="zapi",
                  webhook_segredo="s", tarefas_segredo="t", arquivo_regras=Path("conhecimento/regras.md"), **extra)


def motoboy_ativo(repo: FakeRepo, telefone_: str, nome: str, cnh_validade: str = "2030-01-01") -> dict:
    m = repo.criar_motoboy(telefone_)
    repo.atualizar_motoboy(m["id"], {"nome": nome, "status": "ativo", "cidade": CIDADE})
    repo.inserir_documento({"motoboy_id": m["id"], "tipo": "cnh", "validade": cnh_validade})
    repo.docs[-1]["status"] = "aprovado"
    return repo.motoboy(m["id"])


def turno(repo: FakeRepo, motoboy_id=None, status="escalado", data=AMANHA, inicio="18:00", fim="23:00") -> dict:
    t = {"id": repo.novo_id(), "loja_nome": "Loja X", "cidade": CIDADE, "data": data, "inicio": inicio,
         "fim": fim, "valor": 80, "motoboy_id": motoboy_id, "status": status}
    repo.turnos[t["id"]] = t
    return dict(t)


# ---------- telefone

def test_variantes_do_nono_digito():
    assert telefone.variantes("(85) 99999-8888") == ["5585999998888", "558599998888"]
    assert telefone.variantes("558599998888") == ["5585999998888", "558599998888"]


# ---------- falta e cobertura

def test_falta_convida_livres_e_avisa_coordenacao():
    repo, wa = FakeRepo(), FakeWhatsApp()
    joao = motoboy_ativo(repo, "85911111111", "João")
    livre = motoboy_ativo(repo, "85922222222", "Pedro Livre")
    ocupado = motoboy_ativo(repo, "85933333333", "Ocupado")
    vencido = motoboy_ativo(repo, "85944444444", "CNH Vencida", cnh_validade="2026-01-01")
    turno(repo, ocupado["id"], inicio="20:00", fim="23:30")
    t = turno(repo, joao["id"])

    msg = servicos.registrar_falta(repo, wa, joao, t, "moto quebrou", convites=5)

    assert "Convidei 1" in msg
    assert [tel for tel, _ in wa.enviadas] == [livre["telefone"]]
    assert repo.turnos[t["id"]]["status"] == "falta" and repo.turnos[t["id"]]["motoboy_id"] is None
    assert repo.avisos[0][0] == "motoboys:falta"
    assert vencido["id"] not in {c["motoboy_id"] for c in repo.convites}


def test_primeiro_que_aceita_leva():
    repo, wa = FakeRepo(), FakeWhatsApp()
    a = motoboy_ativo(repo, "85922222222", "A")
    b = motoboy_ativo(repo, "85933333333", "B")
    t = turno(repo, None, status="falta")

    assert "Confirmado" in servicos.aceitar_turno(repo, a, t["id"])
    assert "já foi pego" in servicos.aceitar_turno(repo, b, t["id"])
    assert repo.turnos[t["id"]]["motoboy_id"] == a["id"]
    assert repo.turnos[t["id"]]["status"] == "coberto"


def test_nao_pode_pegar_turno_que_bate_horario():
    repo = FakeRepo()
    a = motoboy_ativo(repo, "85922222222", "A")
    turno(repo, a["id"], inicio="22:00", fim="02:00")       # vira a noite
    t = turno(repo, None, status="aberto", data=(HOJE + timedelta(days=2)).isoformat(), inicio="01:00", fim="05:00")
    assert "bate com outro turno" in servicos.aceitar_turno(repo, a, t["id"])


def test_cadastro_pendente_nao_pega_turno():
    repo = FakeRepo()
    m = repo.criar_motoboy("85955555555")
    repo.atualizar_motoboy(m["id"], {"cidade": CIDADE})
    t = turno(repo, None, status="aberto")
    assert "não está ativo" in servicos.aceitar_turno(repo, repo.motoboy(m["id"]), t["id"])


def test_pendencias_de_cadastro():
    m = {"nome": "Ana", "cpf": None, "cidade": CIDADE, "chave_pix": "x", "moto_placa": "ABC1D23"}
    docs = [{"tipo": "cnh", "status": "aprovado", "validade": "2026-01-01", "criado_em": "1"}]
    p = servicos.pendencias_cadastro(m, docs, HOJE)
    assert p == ["falta CPF", "CNH vencida em 01/01/2026, precisa mandar a nova", "falta foto da CRLV (documento da moto)"]


# ---------- tarefas

def test_tarefa_coberturas_avisa_uma_vez_quando_ninguem_disponivel():
    repo, wa = FakeRepo(), FakeWhatsApp()
    turno(repo, None, status="falta", data=HOJE.isoformat())
    for _ in range(2):
        tarefas.coberturas(repo, wa, config(), HOJE)
    assert [o for o, _ in repo.avisos] == ["motoboys:cobertura"]


def test_tarefa_documentos_vencendo():
    repo, wa = FakeRepo(), FakeWhatsApp()
    motoboy_ativo(repo, "85922222222", "A", cnh_validade=(HOJE + timedelta(days=7)).isoformat())
    motoboy_ativo(repo, "85933333333", "B", cnh_validade=(HOJE + timedelta(days=8)).isoformat())
    assert tarefas.documentos_vencendo(repo, wa, config(), HOJE) == {"avisos_enviados": 1, "vencendo_hoje": 0}
    assert "vence em 7 dias" in wa.enviadas[0][1]


# ---------- webhooks

def test_zapi_ignora_grupo_e_le_imagem():
    z = ZApi("i", "t", "c")
    assert z.ler_webhook({"type": "ReceivedCallback", "isGroup": True, "phone": "1", "messageId": "x"}) == []
    [m] = z.ler_webhook({"type": "ReceivedCallback", "phone": "5585999998888", "messageId": "abc",
                         "image": {"imageUrl": "https://f/1.jpg", "mimeType": "image/jpeg", "caption": "minha cnh"}})
    assert m.texto == "minha cnh" and m.midia.tipo == "imagem" and m.midia.referencia == "https://f/1.jpg"


def test_meta_le_texto_e_valida_assinatura():
    meta = MetaCloud("tok", "pid", "segredo")
    corpo = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "558599998888", "profile": {"name": "Zé"}}],
        "messages": [{"from": "558599998888", "id": "wamid.1", "type": "text", "text": {"body": "oi"}}]}}]}]}
    [m] = meta.ler_webhook(corpo)
    assert (m.telefone, m.nome, m.texto) == ("558599998888", "Zé", "oi")
    import hashlib, hmac
    assinatura = "sha256=" + hmac.new(b"segredo", b"{}", hashlib.sha256).hexdigest()
    assert meta.assinatura_valida(b"{}", assinatura) and not meta.assinatura_valida(b"{}", "sha256=00")


# ---------- agente (Claude simulado)

def _resposta(conteudo, stop="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": conteudo, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    })


class ClaudeRoteirizado:
    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        return self.respostas.pop(0)


def test_agente_registra_cnh_com_foto():
    repo, wa = FakeRepo(), FakeWhatsApp()
    caminho_esperado = "recebidos/1/wamid.9.jpg"
    claude = ClaudeRoteirizado([
        _resposta([{"type": "tool_use", "id": "t1", "name": "registrar_documento", "input": {
            "tipo": "cnh", "arquivo": caminho_esperado, "numero": "123", "validade": "2031-05-01",
            "nome_no_documento": "Zé", "observacao": None}}], stop="tool_use"),
        _resposta([{"type": "text", "text": "Recebi sua CNH! ✅"}]),
    ])
    agente = Agente(config(), repo, wa, cliente=claude)
    msg = MensagemRecebida("wamid.9", "5585999998888", "Zé", "", Midia("imagem", "image/jpeg", "url"))

    agente.atender(msg)
    agente.atender(msg)  # webhook repetido não responde de novo

    assert wa.enviadas == [("5585999998888", "Recebi sua CNH! ✅")]
    assert repo.docs[0]["tipo"] == "cnh" and repo.docs[0]["arquivo"] == caminho_esperado
    assert caminho_esperado in repo.arquivos
    primeiro = claude.pedidos[0]
    assert primeiro["fallbacks"] == "default" and "thinking" not in primeiro
    assert primeiro["messages"][0]["content"][0]["type"] == "image"
    # Histórico gravado: user, assistant(tool_use), user(tool_result), assistant(texto)
    assert [m["role"] for m in repo.msgs] == ["user", "assistant", "user", "assistant"]


def test_agente_nao_aceita_arquivo_inventado():
    repo, wa = FakeRepo(), FakeWhatsApp()
    claude = ClaudeRoteirizado([
        _resposta([{"type": "tool_use", "id": "t1", "name": "registrar_documento", "input": {
            "tipo": "cnh", "arquivo": "recebidos/99/outro.jpg", "numero": None, "validade": None,
            "nome_no_documento": None, "observacao": None}}], stop="tool_use"),
        _resposta([{"type": "text", "text": "Manda a foto, por favor."}]),
    ])
    Agente(config(), repo, wa, cliente=claude).atender(MensagemRecebida("w1", "5585999998888", None, "já mandei"))
    assert repo.docs == []
    resultado = claude.pedidos[1]["messages"][-1]["content"][0]
    assert "não foi recebido" in resultado["content"]


def test_agente_recusa_chama_coordenacao():
    repo, wa = FakeRepo(), FakeWhatsApp()
    claude = ClaudeRoteirizado([_resposta([], stop="refusal")])
    Agente(config(), repo, wa, cliente=claude).atender(MensagemRecebida("w2", "5585999998888", None, "oi"))
    assert "coordenação" in wa.enviadas[0][1]
    assert repo.avisos and repo.avisos[0][0] == "motoboys:atendimento"
    assert [m["role"] for m in repo.msgs] == ["user"]
