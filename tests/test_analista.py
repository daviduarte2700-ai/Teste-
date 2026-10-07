import json
from datetime import date

from anthropic.types.beta import BetaMessage

from hashtag_analista import painel
from hashtag_analista.analista import Analista
from hashtag_analista.sendflow import por_dia

# Trecho com a mesma estrutura do HTML que o painel comercial grava na tabela cache.
HTML_PAINEL = (
    '<div class="card "><div class="r">Investimento Meta</div><div class="v m">R$ 1.552,31</div>'
    '<div class="s">Meta Ads</div></div>'
    '<div class="card "><div class="r">Custo por lead</div><div class="v m">R$ 24,25</div>'
    '<div class="s">64 leads de anúncio</div></div>'
    '<h2 id="anuncios">Anúncios <span class="sub">Meta Ads · leads criados no mês</span></h2>'
    '<table><tr><th></th><th>Investimento</th><th>Leads</th></tr>'
    '<tr class="top"><td class="n">🥇 <b>AD_10</b></td><td class="money">R$ 201,01</td><td>25</td></tr></table>'
    '<h2 id="perdas">Perdas</h2>'
    '<script type="application/json" id="leads-json">'
    + json.dumps({"leads": [
        {"id": 1, "o": "Meta Ads", "cr": "2026-10-06 10:00"},
        {"id": 2, "o": "Meta Ads", "cr": "2026-10-06 11:00"},
        {"id": 3, "o": "WhatsApp / outros", "cr": "2026-10-07 09:00"},
    ]}) + "</script>"
)


def test_resumo_anuncios_le_totais_e_tabela():
    texto = painel.resumo_anuncios(HTML_PAINEL)
    assert "Investimento Meta: R$ 1.552,31 (Meta Ads)" in texto
    assert "AD_10 | R$ 201,01 | 25" in texto
    assert "Perdas" not in texto


def test_leads_por_dia():
    assert painel.leads_por_dia(HTML_PAINEL) == {
        "2026-10-06": {"Meta Ads": 2}, "2026-10-07": {"WhatsApp / outros": 1},
    }


def test_sendflow_por_dia():
    dias = por_dia({"add": {"total": 5, "dates": {"06102026": 3, "07102026": 2}},
                    "remove": {"total": 1, "dates": {"07102026": 1}}, "clicks": {}})
    assert dias[date(2026, 10, 7)] == {"entradas": 2, "saidas": 1, "cliques": 0}


class FakeTabela:
    def __init__(self, db, nome):
        self.db, self.nome, self.op, self.filtros = db, nome, None, []

    def select(self, *_):
        self.op = "select"
        return self

    def eq(self, campo, valor):
        self.filtros.append((campo, "eq", valor))
        return self

    def lt(self, campo, valor):
        self.filtros.append((campo, "lt", valor))
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def upsert(self, linha):
        self.op, self.linha = "upsert", linha
        return self

    def insert(self, linha):
        self.op, self.linha = "insert", linha
        return self

    def update(self, linha):
        self.op, self.linha = "update", linha
        return self

    def execute(self):
        linhas = self.db.dados.setdefault(self.nome, [])
        if self.op == "select":
            ok = [l for l in linhas if all((l.get(c) == v) if o == "eq" else (l.get(c) < v) for c, o, v in self.filtros)]
            return type("R", (), {"data": ok})
        if self.op in ("insert", "upsert"):
            linhas.append(dict(self.linha))
        if self.op == "update":
            for l in linhas:
                if all(l.get(c) == v for c, _, v in self.filtros):
                    l.update(self.linha)
        return type("R", (), {"data": [self.linha]})


class FakeDb:
    def __init__(self):
        self.dados = {}

    def table(self, nome):
        return FakeTabela(self, nome)


class FakeSendFlow:
    def analytics(self, lancamento_id):
        return {"add": {"dates": {"07102026": 12}}, "remove": {"dates": {"07102026": 2}}, "clicks": {"dates": {}}}


class FakeClaude:
    def __init__(self):
        self.pedidos = []
        self.beta = self.messages = self

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        return BetaMessage.model_validate({
            "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "*Entradas subiram* 12 ontem."}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
        })


def test_rodada_diaria_grava_snapshot_e_enfileira_resumo(monkeypatch):
    db = FakeDb()
    db.dados["cache"] = [{"chave": "comercial:2026-10", "html": HTML_PAINEL, "atualizado_em": "2026-10-07"}]
    claude = FakeClaude()
    a = Analista(db, FakeSendFlow(), ["PI-OUT-26"], "marketing", cliente=claude)
    monkeypatch.setattr("hashtag_analista.analista.datetime",
                        type("D", (), {"now": staticmethod(lambda tz: __import__("datetime").datetime(2026, 10, 8, 8, 0))}))

    resultado = a.rodar()

    assert resultado["dia"] == "2026-10-08"
    [fila] = db.dados["whatsapp_fila"]
    assert fila["destino"] == "marketing" and "Entradas subiram" in fila["texto"]
    enviado = json.loads(claude.pedidos[0]["messages"][0]["content"].split("\n", 1)[1])
    assert enviado["sendflow_por_lancamento"]["PI-OUT-26"]["2026-10-07"]["entradas"] == 12
    assert "AD_10" in enviado["painel_hoje"]["anuncios_mes"]
    assert db.dados["mkt_snapshots"][0]["resumo"].startswith("*Entradas")
