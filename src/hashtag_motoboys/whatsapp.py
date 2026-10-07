"""Provedores de WhatsApp: Z-API (padrão) e WhatsApp Cloud API oficial da Meta.

Cada provedor sabe três coisas: ler o webhook, baixar mídia e enviar texto.
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import Config

GRAPH = "https://graph.facebook.com/v21.0"


@dataclass
class Midia:
    tipo: str            # "imagem", "documento", "audio", "video", "figurinha"
    mime: str
    referencia: str      # URL (Z-API) ou id da mídia (Meta)
    nome_arquivo: str | None = None


@dataclass
class MensagemRecebida:
    id: str
    telefone: str
    nome: str | None
    texto: str
    midia: Midia | None = None


class WhatsApp(Protocol):
    def ler_webhook(self, corpo: dict[str, Any]) -> list[MensagemRecebida]: ...
    def baixar_midia(self, midia: Midia) -> bytes: ...
    def enviar_texto(self, telefone: str, texto: str) -> None: ...


class ZApi:
    def __init__(self, instancia: str, token: str, client_token: str):
        self.base = f"https://api.z-api.io/instances/{instancia}/token/{token}"
        self.http = httpx.Client(timeout=30, headers={"Client-Token": client_token})

    def ler_webhook(self, corpo):
        if corpo.get("type") != "ReceivedCallback" or corpo.get("fromMe") or corpo.get("isGroup"):
            return []
        texto = (corpo.get("text") or {}).get("message", "")
        midia = None
        for chave, tipo, campo_url in (
            ("image", "imagem", "imageUrl"),
            ("document", "documento", "documentUrl"),
            ("audio", "audio", "audioUrl"),
            ("video", "video", "videoUrl"),
            ("sticker", "figurinha", "stickerUrl"),
        ):
            if bloco := corpo.get(chave):
                midia = Midia(tipo, bloco.get("mimeType", ""), bloco.get(campo_url, ""), bloco.get("fileName"))
                texto = texto or bloco.get("caption") or ""
                break
        return [MensagemRecebida(corpo["messageId"], corpo["phone"], corpo.get("senderName"), texto, midia)]

    def baixar_midia(self, midia):
        r = self.http.get(midia.referencia)
        r.raise_for_status()
        return r.content

    def enviar_texto(self, telefone, texto):
        self.http.post(f"{self.base}/send-text", json={"phone": telefone, "message": texto}).raise_for_status()


class MetaCloud:
    TIPOS = {"image": "imagem", "document": "documento", "audio": "audio", "video": "video", "sticker": "figurinha"}

    def __init__(self, token: str, phone_number_id: str, app_secret: str):
        self.phone_number_id = phone_number_id
        self.app_secret = app_secret.encode()
        self.http = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})

    def assinatura_valida(self, corpo_bruto: bytes, cabecalho: str | None) -> bool:
        esperado = "sha256=" + hmac.new(self.app_secret, corpo_bruto, hashlib.sha256).hexdigest()
        return hmac.compare_digest(esperado, cabecalho or "")

    def ler_webhook(self, corpo):
        recebidas = []
        for entrada in corpo.get("entry", []):
            for mudanca in entrada.get("changes", []):
                valor = mudanca.get("value", {})
                nomes = {c["wa_id"]: c.get("profile", {}).get("name") for c in valor.get("contacts", [])}
                for m in valor.get("messages", []):
                    texto = (m.get("text") or {}).get("body", "")
                    midia = None
                    if (tipo := m.get("type")) in self.TIPOS:
                        bloco = m[tipo]
                        midia = Midia(self.TIPOS[tipo], bloco.get("mime_type", ""), bloco["id"], bloco.get("filename"))
                        texto = texto or bloco.get("caption") or ""
                    recebidas.append(MensagemRecebida(m["id"], m["from"], nomes.get(m["from"]), texto, midia))
        return recebidas

    def baixar_midia(self, midia):
        info = self.http.get(f"{GRAPH}/{midia.referencia}")
        info.raise_for_status()
        r = self.http.get(info.json()["url"])
        r.raise_for_status()
        return r.content

    def enviar_texto(self, telefone, texto):
        # Fora da janela de 24h desde a última mensagem do motoboy, a Meta só aceita
        # templates aprovados; este envio de texto livre vai falhar nesses casos.
        self.http.post(
            f"{GRAPH}/{self.phone_number_id}/messages",
            json={"messaging_product": "whatsapp", "to": telefone, "type": "text", "text": {"body": texto}},
        ).raise_for_status()


def criar(config: Config) -> ZApi | MetaCloud:
    if config.whatsapp_provedor == "meta":
        return MetaCloud(config.meta_token, config.meta_phone_number_id, config.meta_app_secret)
    if config.whatsapp_provedor == "zapi":
        return ZApi(config.zapi_instancia, config.zapi_token, config.zapi_client_token)
    raise RuntimeError(f"WHATSAPP_PROVEDOR inválido: {config.whatsapp_provedor!r} (use 'zapi' ou 'meta')")
