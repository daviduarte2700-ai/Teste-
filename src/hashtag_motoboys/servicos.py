"""Regras de negócio dos motoboys: cadastro, escala, faltas e coberturas.

Nada aqui chama o modelo. São decisões feitas em código para não depender
do agente acertar regra de escala.
"""

from datetime import date, datetime, time, timedelta

from .repo import Linha, Repo
from .whatsapp import WhatsApp

CAMPOS_OBRIGATORIOS = {
    "nome": "nome completo",
    "cpf": "CPF",
    "cidade": "cidade onde trabalha",
    "chave_pix": "chave PIX",
    "moto_placa": "placa da moto",
}
DOCUMENTOS_OBRIGATORIOS = {"cnh": "CNH", "crlv": "CRLV (documento da moto)"}
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _d(valor) -> date | None:
    if valor is None or isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _t(valor) -> time:
    return valor if isinstance(valor, time) else time.fromisoformat(str(valor))


def documento_atual(docs: list[Linha], tipo: str) -> Linha | None:
    """O documento mais recente daquele tipo que não foi recusado."""
    validos = [d for d in docs if d["tipo"] == tipo and d["status"] != "recusado"]
    return max(validos, key=lambda d: str(d["criado_em"]), default=None)


def pendencias_cadastro(motoboy: Linha, docs: list[Linha], hoje: date) -> list[str]:
    faltando = [f"falta {rotulo}" for campo, rotulo in CAMPOS_OBRIGATORIOS.items() if not motoboy.get(campo)]
    for tipo, rotulo in DOCUMENTOS_OBRIGATORIOS.items():
        doc = documento_atual(docs, tipo)
        if doc is None:
            faltando.append(f"falta foto da {rotulo}")
        elif (validade := _d(doc.get("validade"))) and validade < hoje:
            faltando.append(f"{rotulo} vencida em {validade:%d/%m/%Y}, precisa mandar a nova")
    return faltando


def descrever_turno(t: Linha) -> str:
    valor = f" · R$ {float(t['valor']):.2f}".replace(".", ",") if t.get("valor") is not None else ""
    dia = _d(t["data"])
    return (f"#{t['id']} {t['loja_nome']} ({t['cidade']}) · {dia:%d/%m} ({DIAS[dia.weekday()]}) "
            f"{_t(t['inicio']):%H:%M}–{_t(t['fim']):%H:%M}{valor} · {t['status']}")


def _intervalo(t: Linha) -> tuple[datetime, datetime]:
    inicio = datetime.combine(_d(t["data"]), _t(t["inicio"]))
    fim = datetime.combine(_d(t["data"]), _t(t["fim"]))
    if fim <= inicio:  # turno que vira a noite
        fim += timedelta(days=1)
    return inicio, fim


def conflita(a: Linha, b: Linha) -> bool:
    ia, fa = _intervalo(a)
    ib, fb = _intervalo(b)
    return ia < fb and ib < fa


def pode_assumir(repo: Repo, motoboy: Linha, turno: Linha) -> str | None:
    """Devolve o motivo de não poder pegar o turno, ou None se pode."""
    if motoboy["status"] != "ativo":
        return "cadastro ainda não está ativo; a coordenação precisa aprovar os documentos antes"
    if motoboy.get("cidade") != turno["cidade"]:
        return f"o turno é em {turno['cidade']} e o cadastro está em {motoboy.get('cidade')}"
    cnh = documento_atual(repo.documentos(motoboy["id"]), "cnh")
    if cnh is None or cnh["status"] != "aprovado":
        return "a CNH ainda não foi aprovada"
    if (validade := _d(cnh.get("validade"))) and validade < _d(turno["data"]):
        return f"a CNH vence em {validade:%d/%m/%Y}, antes do turno"
    dia = _d(turno["data"])
    vizinhos = repo.turnos_do_motoboy(motoboy["id"], dia - timedelta(days=1), dia + timedelta(days=1))
    for outro in vizinhos:
        if outro["id"] != turno["id"] and outro["status"] not in ("cancelado", "falta") and conflita(outro, turno):
            return f"bate com outro turno seu: {descrever_turno(outro)}"
    return None


def disparar_cobertura(repo: Repo, wa: WhatsApp, turno: Linha, quantidade: int) -> list[Linha]:
    """Convida os motoboys livres da mesma cidade para cobrir o turno."""
    ja_convidados = {c["motoboy_id"] for c in repo.convites_do_turno(turno["id"])}
    excluidos = ja_convidados | {turno.get("motoboy_original_id"), turno.get("motoboy_id")}
    candidatos = []
    for m in repo.motoboys_ativos(turno["cidade"]):
        if m["id"] in excluidos or pode_assumir(repo, m, turno):
            continue
        dia = _d(turno["data"])
        carga = len(repo.turnos_do_motoboy(m["id"], dia - timedelta(days=3), dia + timedelta(days=3)))
        candidatos.append((carga, m["id"], m))
    escolhidos = [m for _, _, m in sorted(candidatos, key=lambda c: c[:2])[:quantidade]]

    repo.criar_convites(turno["id"], [m["id"] for m in escolhidos])
    for m in escolhidos:
        primeiro_nome = (m.get("nome") or "").split(" ")[0] or "parceiro"
        wa.enviar_texto(
            m["telefone"],
            f"Fala, {primeiro_nome}! 🛵 Surgiu uma cobertura:\n{descrever_turno(turno)}\n\n"
            "Quer pegar? Responde aqui que eu confirmo pra você. Quem confirmar primeiro leva.",
        )
    return escolhidos


def registrar_falta(repo: Repo, wa: WhatsApp, motoboy: Linha, turno: Linha, motivo: str, convites: int) -> str:
    if turno.get("motoboy_id") != motoboy["id"]:
        return "Esse turno não está no seu nome."
    if turno["status"] not in ("escalado", "confirmado"):
        return f"Esse turno está com status '{turno['status']}', não dá para avisar falta nele."
    repo.atualizar_turno(turno["id"], {
        "status": "falta", "motoboy_id": None, "motoboy_original_id": motoboy["id"],
        "obs": f"Falta avisada pelo motoboy: {motivo}",
    })
    turno = {**turno, "status": "falta", "motoboy_id": None, "motoboy_original_id": motoboy["id"]}
    convidados = disparar_cobertura(repo, wa, turno, convites)
    repo.avisar_coordenacao(
        f"⚠️ FALTA AVISADA\n{motoboy.get('nome') or motoboy['telefone']} não vai em:\n{descrever_turno(turno)}\n"
        f"Motivo: {motivo}\nConvites de cobertura enviados: {len(convidados)}"
        + ("" if convidados else "\n❗ Ninguém disponível na cidade, precisa cobrir manualmente."),
        origem="motoboys:falta",
    )
    return (f"Falta registrada. Convidei {len(convidados)} motoboy(s) para cobrir e avisei a coordenação."
            if convidados else "Falta registrada e coordenação avisada. Não achei ninguém livre para cobrir.")


def aceitar_turno(repo: Repo, motoboy: Linha, turno_id: int) -> str:
    turno = repo.turno(turno_id)
    if turno is None:
        return f"Não existe turno #{turno_id}."
    if turno.get("motoboy_id") is not None or turno["status"] not in ("aberto", "falta"):
        return "Esse turno já foi pego por outra pessoa ou não está mais disponível."
    if motivo := pode_assumir(repo, motoboy, turno):
        return f"Não dá para pegar esse turno: {motivo}."
    if not repo.assumir_turno(turno_id, motoboy["id"]):
        return "Alguém confirmou esse turno segundos antes. Ele não está mais disponível."
    repo.avisar_coordenacao(
        f"✅ TURNO ASSUMIDO\n{motoboy.get('nome') or motoboy['telefone']} pegou:\n{descrever_turno(turno)}",
        origem="motoboys:cobertura" if turno["status"] == "falta" else "motoboys:turno",
    )
    return f"Confirmado! O turno é seu: {descrever_turno({**turno, 'status': 'confirmado'})}"


def confirmar_presenca(repo: Repo, motoboy: Linha, turno_id: int) -> str:
    turno = repo.turno(turno_id)
    if turno is None or turno.get("motoboy_id") != motoboy["id"]:
        return "Esse turno não está no seu nome."
    if turno["status"] == "confirmado":
        return "Esse turno já estava confirmado."
    if turno["status"] != "escalado":
        return f"Esse turno está com status '{turno['status']}', não precisa confirmar."
    repo.atualizar_turno(turno_id, {"status": "confirmado", "confirmado_em": datetime.now().astimezone().isoformat()})
    return "Presença confirmada. Bom trabalho!"
