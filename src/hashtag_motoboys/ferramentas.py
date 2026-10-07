"""Ferramentas que o agente pode usar.

Toda ferramenta age só sobre o motoboy que está mandando mensagem: o id dele vem
do número do WhatsApp, nunca de um parâmetro que o modelo preenche. Assim um
motoboy não consegue mexer no cadastro ou nos turnos de outro.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import servicos
from .config import Config
from .repo import Linha, Repo
from .whatsapp import WhatsApp


def _texto(descricao: str) -> dict:
    return {"type": ["string", "null"], "description": descricao}


def _ferramenta(nome: str, descricao: str, propriedades: dict[str, Any]) -> dict:
    return {
        "name": nome,
        "description": descricao,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propriedades,
            "required": list(propriedades),
            "additionalProperties": False,
        },
    }


TIPOS_PIX = ("cpf", "telefone", "email", "aleatoria", "cnpj")
TURNO_ID = {"type": "integer", "description": "Número do turno (o que aparece depois do # na escala)."}

FERRAMENTAS = [
    _ferramenta(
        "ver_meu_cadastro",
        "Mostra os dados do motoboy, os documentos enviados, o que falta no cadastro, "
        "os convites de cobertura pendentes e os próximos turnos. Use no começo da conversa.",
        {},
    ),
    _ferramenta(
        "atualizar_cadastro",
        "Grava dados do cadastro que o motoboy informou. Mande null nos campos que ele não informou agora.",
        {
            "nome": _texto("Nome completo."),
            "cpf": _texto("CPF, só números."),
            "cidade": _texto("Cidade onde trabalha, no formato 'Cidade - UF', ex.: 'Fortaleza - CE'."),
            "chave_pix": _texto("Chave PIX para receber."),
            "tipo_pix": _texto("Tipo da chave PIX: cpf, telefone, email, aleatoria ou cnpj."),
            "moto_placa": _texto("Placa da moto, ex.: ABC1D23."),
            "moto_modelo": _texto("Modelo da moto, ex.: Honda CG 160."),
        },
    ),
    _ferramenta(
        "registrar_documento",
        "Registra a foto de um documento que o motoboy enviou. Leia a imagem e preencha o que conseguir. "
        "O documento fica pendente até a coordenação aprovar.",
        {
            "tipo": {"type": "string", "enum": ["cnh", "crlv", "comprovante_residencia", "foto_rosto", "mei", "outro"]},
            "arquivo": {"type": "string", "description": "Caminho do arquivo, exatamente como veio em [arquivo: ...]."},
            "numero": _texto("Número do documento (registro da CNH, RENAVAM do CRLV etc.)."),
            "validade": _texto("Data de validade no formato AAAA-MM-DD."),
            "nome_no_documento": _texto("Nome que aparece no documento."),
            "observacao": _texto("Problemas notados: foto cortada, ilegível, nome diferente do cadastro etc."),
        },
    ),
    _ferramenta(
        "minha_escala",
        "Lista os turnos do motoboy de hoje até daqui a N dias.",
        {"dias": {"type": "integer", "description": "Quantos dias para frente (1 a 31)."}},
    ),
    _ferramenta(
        "turnos_disponiveis",
        "Lista os turnos sem motoboy na cidade dele nos próximos 7 dias e os convites de cobertura que ele recebeu.",
        {},
    ),
    _ferramenta(
        "pegar_turno",
        "Coloca o motoboy num turno disponível ou numa cobertura. Só use depois que ele disser claramente que quer.",
        {"turno_id": TURNO_ID},
    ),
    _ferramenta("recusar_convite", "Registra que o motoboy não quer a cobertura para a qual foi convidado.",
                {"turno_id": TURNO_ID}),
    _ferramenta("confirmar_presenca", "Confirma que o motoboy vai num turno em que foi escalado.",
                {"turno_id": TURNO_ID}),
    _ferramenta(
        "avisar_falta",
        "Registra que o motoboy não vai num turno dele. Libera o turno, convida outros motoboys "
        "para cobrir e avisa a coordenação. Confirme com ele qual turno antes de usar.",
        {"turno_id": TURNO_ID, "motivo": {"type": "string"}},
    ),
    _ferramenta(
        "registrar_ocorrencia",
        "Registra um problema: acidente, atraso, problema com loja, pagamento ou reclamação. "
        "Gravidade alta avisa a coordenação na hora.",
        {
            "tipo": {"type": "string", "enum": ["acidente", "atraso", "problema_loja", "pagamento", "reclamacao", "outro"]},
            "gravidade": {"type": "string", "enum": ["baixa", "media", "alta"]},
            "descricao": {"type": "string", "description": "O que aconteceu, com loja, horário e detalhes que ele deu."},
            "turno_id": {"type": ["integer", "null"], "description": "Turno relacionado, se houver."},
        },
    ),
    _ferramenta(
        "chamar_coordenacao",
        "Passa a conversa para uma pessoa da coordenação. Use quando não souber responder, quando ele pedir "
        "para falar com alguém, ou em qualquer assunto de pagamento ou valores.",
        {"motivo": {"type": "string"}, "resumo": {"type": "string", "description": "Resumo para a coordenação."}},
    ),
]


@dataclass
class Contexto:
    repo: Repo
    wa: WhatsApp
    config: Config
    motoboy: Linha
    conversa_id: int
    hoje: date
    arquivos_recebidos: set[str] = field(default_factory=set)

    @property
    def quem(self) -> str:
        m = self.motoboy
        return f"{m.get('nome') or 'Sem nome'} ({m['telefone']})"


def executar(ctx: Contexto, nome: str, entrada: dict[str, Any]) -> str:
    funcao = _EXECUTORES.get(nome)
    if funcao is None:
        raise ValueError(f"Ferramenta desconhecida: {nome}")
    return funcao(ctx, **entrada)


def _json(dados: Any) -> str:
    return json.dumps(dados, ensure_ascii=False, default=str)


def ver_meu_cadastro(ctx: Contexto) -> str:
    m = ctx.repo.motoboy(ctx.motoboy["id"])
    ctx.motoboy = m
    docs = ctx.repo.documentos(m["id"])
    turnos = ctx.repo.turnos_do_motoboy(m["id"], ctx.hoje, ctx.hoje + timedelta(days=7))
    convites = ctx.repo.convites_pendentes(m["id"])
    return _json({
        "cadastro": {k: m.get(k) for k in ("nome", "cpf", "cidade", "chave_pix", "tipo_pix",
                                           "moto_placa", "moto_modelo", "status")},
        "documentos": [{k: d.get(k) for k in ("tipo", "validade", "status", "observacao")} for d in docs],
        "pendencias": servicos.pendencias_cadastro(m, docs, ctx.hoje),
        "proximos_turnos": [servicos.descrever_turno(t) for t in turnos],
        "convites_cobertura": [servicos.descrever_turno(c["turnos"]) for c in convites if c.get("turnos")],
    })


def _avisar_se_cadastro_completo(ctx: Contexto, pendencias_antes: list[str]) -> str:
    m = ctx.repo.motoboy(ctx.motoboy["id"])
    ctx.motoboy = m
    agora = servicos.pendencias_cadastro(m, ctx.repo.documentos(m["id"]), ctx.hoje)
    if m["status"] == "pendente" and pendencias_antes and not agora:
        ctx.repo.avisar_coordenacao(
            f"📋 CADASTRO COMPLETO\n{ctx.quem} · {m.get('cidade')}\nDocumentos aguardando aprovação no painel.",
            origem="motoboys:cadastro",
        )
        return " Cadastro completo! Avisei a coordenação para aprovar os documentos."
    return f" Ainda falta: {'; '.join(agora)}." if agora else ""


def atualizar_cadastro(ctx: Contexto, **campos) -> str:
    dados = {k: v.strip() if isinstance(v, str) else v for k, v in campos.items() if v not in (None, "")}
    if "cpf" in dados:
        dados["cpf"] = re.sub(r"\D", "", dados["cpf"])
        if len(dados["cpf"]) != 11:
            return "CPF precisa ter 11 números. Peça para ele conferir."
    if dados.get("tipo_pix") not in (None, *TIPOS_PIX):
        return f"tipo_pix precisa ser um destes: {', '.join(TIPOS_PIX)}."
    if "moto_placa" in dados:
        dados["moto_placa"] = re.sub(r"[^A-Za-z0-9]", "", dados["moto_placa"]).upper()
    if not dados:
        return "Nada para atualizar."
    antes = ctx.motoboy
    pendencias_antes = servicos.pendencias_cadastro(antes, ctx.repo.documentos(antes["id"]), ctx.hoje)
    ctx.repo.atualizar_motoboy(antes["id"], dados)
    if antes["status"] == "ativo" and "chave_pix" in dados and dados["chave_pix"] != antes.get("chave_pix"):
        ctx.repo.avisar_coordenacao(
            f"🔐 TROCA DE PIX\n{ctx.quem} mudou a chave PIX de {antes.get('chave_pix')} para "
            f"{dados['chave_pix']}. Confirme com ele por ligação antes do próximo pagamento.",
            origem="motoboys:pix",
        )
    return "Cadastro atualizado." + _avisar_se_cadastro_completo(ctx, pendencias_antes)


def registrar_documento(ctx: Contexto, tipo, arquivo, numero, validade, nome_no_documento, observacao) -> str:
    if arquivo not in ctx.arquivos_recebidos:
        return "Esse arquivo não foi recebido nesta conversa. Peça para ele mandar a foto do documento."
    if validade:
        try:
            date.fromisoformat(validade)
        except ValueError:
            return "Validade precisa estar no formato AAAA-MM-DD."
    pendencias_antes = servicos.pendencias_cadastro(ctx.motoboy, ctx.repo.documentos(ctx.motoboy["id"]), ctx.hoje)
    ctx.repo.inserir_documento({
        "motoboy_id": ctx.motoboy["id"], "tipo": tipo, "arquivo": arquivo, "numero": numero,
        "validade": validade, "nome_no_documento": nome_no_documento, "observacao": observacao,
    })
    aviso = ""
    if validade and date.fromisoformat(validade) < ctx.hoje:
        aviso = " Atenção: esse documento está vencido."
    return "Documento registrado, aguardando aprovação." + aviso + _avisar_se_cadastro_completo(ctx, pendencias_antes)


def minha_escala(ctx: Contexto, dias: int) -> str:
    dias = max(1, min(dias, 31))
    turnos = ctx.repo.turnos_do_motoboy(ctx.motoboy["id"], ctx.hoje, ctx.hoje + timedelta(days=dias))
    return _json([servicos.descrever_turno(t) for t in turnos] or "Nenhum turno nesse período.")


def turnos_disponiveis(ctx: Contexto) -> str:
    cidade = ctx.motoboy.get("cidade")
    abertos = [t for t in ctx.repo.turnos_por_status(["aberto", "falta"], ctx.hoje, ctx.hoje + timedelta(days=7))
               if t["cidade"] == cidade and t.get("motoboy_id") is None]
    convites = ctx.repo.convites_pendentes(ctx.motoboy["id"])
    return _json({
        "cidade": cidade,
        "turnos_abertos": [servicos.descrever_turno(t) for t in abertos],
        "convites_cobertura": [servicos.descrever_turno(c["turnos"]) for c in convites if c.get("turnos")],
    })


def pegar_turno(ctx: Contexto, turno_id: int) -> str:
    return servicos.aceitar_turno(ctx.repo, ctx.motoboy, turno_id)


def recusar_convite(ctx: Contexto, turno_id: int) -> str:
    ctx.repo.recusar_convite(turno_id, ctx.motoboy["id"])
    return "Convite recusado."


def confirmar_presenca(ctx: Contexto, turno_id: int) -> str:
    return servicos.confirmar_presenca(ctx.repo, ctx.motoboy, turno_id)


def avisar_falta(ctx: Contexto, turno_id: int, motivo: str) -> str:
    turno = ctx.repo.turno(turno_id)
    if turno is None:
        return f"Não existe turno #{turno_id}."
    return servicos.registrar_falta(ctx.repo, ctx.wa, ctx.motoboy, turno, motivo, ctx.config.convites_por_falta)


def registrar_ocorrencia(ctx: Contexto, tipo, gravidade, descricao, turno_id) -> str:
    o = ctx.repo.inserir_ocorrencia({
        "motoboy_id": ctx.motoboy["id"], "turno_id": turno_id, "tipo": tipo,
        "gravidade": gravidade, "descricao": descricao,
    })
    if gravidade == "alta" or tipo == "acidente":
        ctx.repo.avisar_coordenacao(
            f"🚨 OCORRÊNCIA #{o['id']} ({tipo}, gravidade {gravidade})\n{ctx.quem}\n{descricao}",
            origem="motoboys:ocorrencia",
        )
        return f"Ocorrência #{o['id']} registrada e coordenação avisada agora."
    return f"Ocorrência #{o['id']} registrada. A coordenação vai analisar."


def chamar_coordenacao(ctx: Contexto, motivo: str, resumo: str) -> str:
    ctx.repo.avisar_coordenacao(
        f"🙋 MOTOBOY PRECISA DE ATENDIMENTO\n{ctx.quem}\nMotivo: {motivo}\n{resumo}\n"
        f"Responda direto no WhatsApp dele: wa.me/{ctx.motoboy['telefone']}",
        origem="motoboys:atendimento",
    )
    ctx.repo.tocar_conversa(ctx.conversa_id, {"escalada": True})
    return "Coordenação avisada. Uma pessoa da coordenação vai entrar em contato com ele."


_EXECUTORES = {
    "ver_meu_cadastro": ver_meu_cadastro,
    "atualizar_cadastro": atualizar_cadastro,
    "registrar_documento": registrar_documento,
    "minha_escala": minha_escala,
    "turnos_disponiveis": turnos_disponiveis,
    "pegar_turno": pegar_turno,
    "recusar_convite": recusar_convite,
    "confirmar_presenca": confirmar_presenca,
    "avisar_falta": avisar_falta,
    "registrar_ocorrencia": registrar_ocorrencia,
    "chamar_coordenacao": chamar_coordenacao,
}
assert set(_EXECUTORES) == {f["name"] for f in FERRAMENTAS}
