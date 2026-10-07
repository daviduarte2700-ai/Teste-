"""Cliente da SendAPI do SendFlow (https://sendapi.sendflow.pro, token em Painel > API Keys)."""

from datetime import date, datetime

import httpx

BASE = "https://sendapi.sendflow.pro"


def _dia(chave: str) -> date:
    return datetime.strptime(chave, "%d%m%Y").date()


class SendFlow:
    def __init__(self, token: str, base: str = BASE):
        self.http = httpx.Client(base_url=base, timeout=30, headers={"Authorization": f"Bearer {token}"})

    def analytics(self, lancamento_id: str) -> dict:
        """Entradas (add), saídas (remove) e cliques (clicks) de um lançamento, por dia."""
        r = self.http.get(f"/releases/{lancamento_id}/analytics")
        r.raise_for_status()
        return r.json()


def por_dia(analytics: dict) -> dict[date, dict[str, int]]:
    """Converte {"add": {"dates": {"07102026": 12}}, ...} em {date: {"entradas": 12, "saidas": 0, "cliques": 0}}."""
    nomes = {"add": "entradas", "remove": "saidas", "clicks": "cliques"}
    dias: dict[date, dict[str, int]] = {}
    for chave, nome in nomes.items():
        datas = (analytics.get(chave) or {}).get("dates") or {}
        for d, n in datas.items():
            try:
                dia = _dia(d)
            except ValueError:
                continue
            dias.setdefault(dia, {v: 0 for v in nomes.values()})[nome] += int(n or 0)
    return dias
