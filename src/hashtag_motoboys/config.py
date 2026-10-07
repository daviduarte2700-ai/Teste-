import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(nome: str, padrao: str | None = None) -> str:
    valor = os.environ.get(nome, padrao)
    if valor is None:
        raise RuntimeError(f"Variável de ambiente {nome} não definida (veja .env.example)")
    return valor


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_service_key: str
    whatsapp_provedor: str              # "zapi" ou "meta"
    webhook_segredo: str                # vai na URL do webhook: /webhook?token=...
    tarefas_segredo: str                # protege os endpoints /tarefas/*
    modelo: str = "claude-opus-5-5"
    esforco: str = "medium"
    coordenacao_destino: str = "coordenacao"   # chave em whatsapp_destinos
    convites_por_falta: int = 5
    horas_nova_conversa: int = 12
    fuso: ZoneInfo = field(default_factory=lambda: ZoneInfo("America/Fortaleza"))
    arquivo_regras: Path = Path("conhecimento/regras.md")
    # Z-API
    zapi_instancia: str = ""
    zapi_token: str = ""
    zapi_client_token: str = ""
    # WhatsApp Cloud API (Meta)
    meta_token: str = ""
    meta_phone_number_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""

    @classmethod
    def do_ambiente(cls) -> "Config":
        return cls(
            supabase_url=_env("SUPABASE_URL"),
            supabase_service_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
            whatsapp_provedor=_env("WHATSAPP_PROVEDOR", "zapi"),
            webhook_segredo=_env("WEBHOOK_SEGREDO"),
            tarefas_segredo=_env("TAREFAS_SEGREDO"),
            modelo=_env("CLAUDE_MODELO", "claude-opus-5-5"),
            esforco=_env("CLAUDE_ESFORCO", "medium"),
            coordenacao_destino=_env("COORDENACAO_DESTINO", "coordenacao"),
            convites_por_falta=int(_env("CONVITES_POR_FALTA", "5")),
            horas_nova_conversa=int(_env("HORAS_NOVA_CONVERSA", "12")),
            fuso=ZoneInfo(_env("FUSO", "America/Fortaleza")),
            arquivo_regras=Path(_env("ARQUIVO_REGRAS", "conhecimento/regras.md")),
            zapi_instancia=_env("ZAPI_INSTANCIA", ""),
            zapi_token=_env("ZAPI_TOKEN", ""),
            zapi_client_token=_env("ZAPI_CLIENT_TOKEN", ""),
            meta_token=_env("META_TOKEN", ""),
            meta_phone_number_id=_env("META_PHONE_NUMBER_ID", ""),
            meta_app_secret=_env("META_APP_SECRET", ""),
            meta_verify_token=_env("META_VERIFY_TOKEN", ""),
        )
