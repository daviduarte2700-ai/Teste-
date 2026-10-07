"""Versões em memória do banco e do WhatsApp, para testar sem Supabase nem celular."""

from datetime import datetime, timezone
from itertools import count

from hashtag_motoboys import telefone as tel


class FakeRepo:
    def __init__(self):
        self.motoboys, self.docs, self.turnos, self.convites = {}, [], {}, []
        self.ocorrencias, self.avisos, self.conversas, self.msgs, self.eventos, self.arquivos = [], [], {}, [], set(), {}
        self._id = count(1)

    def novo_id(self):
        return next(self._id)

    def motoboy_por_telefone(self, telefone):
        vs = tel.variantes(telefone)
        return next((dict(m) for m in self.motoboys.values() if m["telefone"] in vs), None)

    def motoboy(self, motoboy_id):
        m = self.motoboys.get(motoboy_id)
        return dict(m) if m else None

    def criar_motoboy(self, telefone):
        m = {"id": self.novo_id(), "telefone": tel.normalizar(telefone), "status": "pendente"}
        self.motoboys[m["id"]] = m
        return dict(m)

    def atualizar_motoboy(self, motoboy_id, dados):
        self.motoboys[motoboy_id].update(dados)

    def motoboys_ativos(self, cidade):
        return [dict(m) for m in self.motoboys.values() if m["status"] == "ativo" and m.get("cidade") == cidade]

    def documentos(self, motoboy_id):
        return [d for d in self.docs if d["motoboy_id"] == motoboy_id]

    def inserir_documento(self, dados):
        d = {"id": self.novo_id(), "status": "pendente_validacao", "criado_em": datetime.now(timezone.utc).isoformat(), **dados}
        self.docs.append(d)
        return d

    def documentos_aprovados_vencendo(self, ate):
        return [{**d, "motoboys": self.motoboys[d["motoboy_id"]]} for d in self.docs
                if d["status"] == "aprovado" and d.get("validade") and d["validade"] <= ate.isoformat()]

    def turno(self, turno_id):
        t = self.turnos.get(turno_id)
        return dict(t) if t else None

    def turnos_do_motoboy(self, motoboy_id, de, ate):
        return [dict(t) for t in self.turnos.values()
                if t.get("motoboy_id") == motoboy_id and de.isoformat() <= t["data"] <= ate.isoformat()]

    def turnos_por_status(self, status, de, ate):
        return [dict(t) for t in self.turnos.values()
                if t["status"] in status and de.isoformat() <= t["data"] <= ate.isoformat()]

    def atualizar_turno(self, turno_id, dados):
        self.turnos[turno_id].update(dados)

    def assumir_turno(self, turno_id, motoboy_id):
        t = self.turnos[turno_id]
        if t.get("motoboy_id") is not None or t["status"] not in ("aberto", "falta"):
            return False
        t.update(motoboy_id=motoboy_id, status="coberto" if t["status"] == "falta" else "confirmado")
        for c in self.convites:
            if c["turno_id"] == turno_id:
                if c["motoboy_id"] == motoboy_id:
                    c["status"] = "aceito"
                elif c["status"] == "convidado":
                    c["status"] = "expirado"
        return True

    def criar_convites(self, turno_id, motoboy_ids):
        for m in motoboy_ids:
            self.convites.append({"turno_id": turno_id, "motoboy_id": m, "status": "convidado"})

    def convites_pendentes(self, motoboy_id):
        return [{**c, "turnos": self.turnos[c["turno_id"]]} for c in self.convites
                if c["motoboy_id"] == motoboy_id and c["status"] == "convidado"]

    def convites_do_turno(self, turno_id):
        return [c for c in self.convites if c["turno_id"] == turno_id]

    def recusar_convite(self, turno_id, motoboy_id):
        for c in self.convites:
            if c["turno_id"] == turno_id and c["motoboy_id"] == motoboy_id:
                c["status"] = "recusado"

    def inserir_ocorrencia(self, dados):
        o = {"id": self.novo_id(), **dados}
        self.ocorrencias.append(o)
        return o

    def avisar_coordenacao(self, texto, origem):
        self.avisos.append((origem, texto))

    def conversa_recente(self, telefone, desde):
        return next((c for c in self.conversas.values() if c["telefone"] == tel.normalizar(telefone)), None)

    def criar_conversa(self, telefone, motoboy_id):
        c = {"id": self.novo_id(), "telefone": tel.normalizar(telefone), "motoboy_id": motoboy_id}
        self.conversas[c["id"]] = c
        return c

    def tocar_conversa(self, conversa_id, dados):
        self.conversas[conversa_id].update(dados)

    def mensagens(self, conversa_id):
        return [{"role": m["role"], "content": m["content"]} for m in self.msgs if m["conversa_id"] == conversa_id]

    def anexar_mensagens(self, conversa_id, mensagens):
        self.msgs.extend({"conversa_id": conversa_id, **m} for m in mensagens)

    def evento_novo(self, mensagem_id):
        if mensagem_id in self.eventos:
            return False
        self.eventos.add(mensagem_id)
        return True

    def guardar_arquivo(self, caminho, conteudo, tipo):
        self.arquivos[caminho] = conteudo


class FakeWhatsApp:
    def __init__(self):
        self.enviadas: list[tuple[str, str]] = []

    def ler_webhook(self, corpo):
        return []

    def baixar_midia(self, midia):
        return b"\xff\xd8foto"

    def enviar_texto(self, telefone, texto):
        self.enviadas.append((telefone, texto))
