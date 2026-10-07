"""Acesso ao Supabase. Todo o resto do bot fala com o banco só por aqui."""

from datetime import date, datetime, timezone
from typing import Any, Protocol

from supabase import Client, create_client

from . import telefone as tel

Linha = dict[str, Any]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repo(Protocol):
    def motoboy_por_telefone(self, telefone: str) -> Linha | None: ...
    def motoboy(self, motoboy_id: int) -> Linha | None: ...
    def criar_motoboy(self, telefone: str) -> Linha: ...
    def atualizar_motoboy(self, motoboy_id: int, dados: Linha) -> None: ...
    def motoboys_ativos(self, cidade: str) -> list[Linha]: ...

    def documentos(self, motoboy_id: int) -> list[Linha]: ...
    def inserir_documento(self, dados: Linha) -> Linha: ...
    def documentos_aprovados_vencendo(self, ate: date) -> list[Linha]: ...

    def turno(self, turno_id: int) -> Linha | None: ...
    def turnos_do_motoboy(self, motoboy_id: int, de: date, ate: date) -> list[Linha]: ...
    def turnos_por_status(self, status: list[str], de: date, ate: date) -> list[Linha]: ...
    def atualizar_turno(self, turno_id: int, dados: Linha) -> None: ...
    def assumir_turno(self, turno_id: int, motoboy_id: int) -> bool: ...

    def criar_convites(self, turno_id: int, motoboy_ids: list[int]) -> None: ...
    def convites_pendentes(self, motoboy_id: int) -> list[Linha]: ...
    def convites_do_turno(self, turno_id: int) -> list[Linha]: ...
    def recusar_convite(self, turno_id: int, motoboy_id: int) -> None: ...

    def inserir_ocorrencia(self, dados: Linha) -> Linha: ...
    def avisar_coordenacao(self, texto: str, origem: str) -> None: ...

    def conversa_recente(self, telefone: str, desde: datetime) -> Linha | None: ...
    def criar_conversa(self, telefone: str, motoboy_id: int | None) -> Linha: ...
    def tocar_conversa(self, conversa_id: int, dados: Linha) -> None: ...
    def mensagens(self, conversa_id: int) -> list[Linha]: ...
    def anexar_mensagens(self, conversa_id: int, mensagens: list[Linha]) -> None: ...

    def evento_novo(self, mensagem_id: str) -> bool: ...
    def guardar_arquivo(self, caminho: str, conteudo: bytes, tipo: str) -> None: ...


class SupabaseRepo:
    def __init__(self, url: str, chave_service_role: str, destino_coordenacao: str):
        self.db: Client = create_client(url, chave_service_role)
        self.destino_coordenacao = destino_coordenacao

    # ---- motoboys
    def motoboy_por_telefone(self, telefone):
        r = self.db.table("motoboys").select("*").in_("telefone", tel.variantes(telefone)).limit(1).execute()
        return r.data[0] if r.data else None

    def motoboy(self, motoboy_id):
        r = self.db.table("motoboys").select("*").eq("id", motoboy_id).limit(1).execute()
        return r.data[0] if r.data else None

    def criar_motoboy(self, telefone):
        r = self.db.table("motoboys").insert({"telefone": tel.normalizar(telefone)}).execute()
        return r.data[0]

    def atualizar_motoboy(self, motoboy_id, dados):
        self.db.table("motoboys").update({**dados, "atualizado_em": _agora()}).eq("id", motoboy_id).execute()

    def motoboys_ativos(self, cidade):
        return self.db.table("motoboys").select("*").eq("status", "ativo").eq("cidade", cidade).execute().data

    # ---- documentos
    def documentos(self, motoboy_id):
        return (self.db.table("motoboy_documentos").select("*").eq("motoboy_id", motoboy_id)
                .order("criado_em", desc=True).execute().data)

    def inserir_documento(self, dados):
        return self.db.table("motoboy_documentos").insert(dados).execute().data[0]

    def documentos_aprovados_vencendo(self, ate):
        return (self.db.table("motoboy_documentos").select("*, motoboys(id, nome, telefone, status)")
                .eq("status", "aprovado").lte("validade", ate.isoformat()).execute().data)

    # ---- turnos
    def turno(self, turno_id):
        r = self.db.table("turnos").select("*").eq("id", turno_id).limit(1).execute()
        return r.data[0] if r.data else None

    def turnos_do_motoboy(self, motoboy_id, de, ate):
        return (self.db.table("turnos").select("*").eq("motoboy_id", motoboy_id)
                .gte("data", de.isoformat()).lte("data", ate.isoformat())
                .order("data").order("inicio").execute().data)

    def turnos_por_status(self, status, de, ate):
        return (self.db.table("turnos").select("*").in_("status", status)
                .gte("data", de.isoformat()).lte("data", ate.isoformat())
                .order("data").order("inicio").execute().data)

    def atualizar_turno(self, turno_id, dados):
        self.db.table("turnos").update({**dados, "atualizado_em": _agora()}).eq("id", turno_id).execute()

    def assumir_turno(self, turno_id, motoboy_id):
        r = self.db.rpc("assumir_turno", {"p_turno_id": turno_id, "p_motoboy_id": motoboy_id}).execute()
        return bool(r.data)

    # ---- coberturas
    def criar_convites(self, turno_id, motoboy_ids):
        if motoboy_ids:
            self.db.table("coberturas").upsert(
                [{"turno_id": turno_id, "motoboy_id": m} for m in motoboy_ids],
                on_conflict="turno_id,motoboy_id", ignore_duplicates=True,
            ).execute()

    def convites_pendentes(self, motoboy_id):
        return (self.db.table("coberturas").select("*, turnos(*)").eq("motoboy_id", motoboy_id)
                .eq("status", "convidado").execute().data)

    def convites_do_turno(self, turno_id):
        return self.db.table("coberturas").select("*").eq("turno_id", turno_id).execute().data

    def recusar_convite(self, turno_id, motoboy_id):
        (self.db.table("coberturas").update({"status": "recusado", "respondido_em": _agora()})
         .eq("turno_id", turno_id).eq("motoboy_id", motoboy_id).execute())

    # ---- ocorrências e avisos
    def inserir_ocorrencia(self, dados):
        return self.db.table("ocorrencias").insert(dados).execute().data[0]

    def avisar_coordenacao(self, texto, origem):
        # Usa a mesma fila de WhatsApp que o painel já consome.
        self.db.table("whatsapp_fila").insert(
            {"destino": self.destino_coordenacao, "texto": texto, "origem": origem}
        ).execute()

    # ---- conversas
    def conversa_recente(self, telefone, desde):
        r = (self.db.table("mb_conversas").select("*").eq("telefone", tel.normalizar(telefone))
             .gte("ultima_msg_em", desde.isoformat()).order("ultima_msg_em", desc=True).limit(1).execute())
        return r.data[0] if r.data else None

    def criar_conversa(self, telefone, motoboy_id):
        return self.db.table("mb_conversas").insert(
            {"telefone": tel.normalizar(telefone), "motoboy_id": motoboy_id}
        ).execute().data[0]

    def tocar_conversa(self, conversa_id, dados):
        self.db.table("mb_conversas").update({**dados, "ultima_msg_em": _agora()}).eq("id", conversa_id).execute()

    def mensagens(self, conversa_id):
        return (self.db.table("mb_mensagens").select("role, content").eq("conversa_id", conversa_id)
                .order("id").execute().data)

    def anexar_mensagens(self, conversa_id, mensagens):
        if mensagens:
            self.db.table("mb_mensagens").insert(
                [{"conversa_id": conversa_id, **m} for m in mensagens]
            ).execute()

    # ---- infraestrutura
    def evento_novo(self, mensagem_id):
        r = (self.db.table("mb_eventos_whatsapp")
             .upsert({"mensagem_id": mensagem_id}, on_conflict="mensagem_id", ignore_duplicates=True)
             .execute())
        return bool(r.data)

    def guardar_arquivo(self, caminho, conteudo, tipo):
        self.db.storage.from_("motoboys").upload(caminho, conteudo, {"content-type": tipo, "upsert": "true"})
