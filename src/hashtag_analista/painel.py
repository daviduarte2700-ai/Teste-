"""Lê os números de anúncio que o painel comercial (painel.hashtagentrega.com) já calcula.

O Apps Script do painel gera o HTML com o investimento do Meta Ads por campanha e por anúncio,
e a função `sync` grava esse HTML na tabela `cache` (chave "comercial:AAAA-MM") a cada 10 min.
Aqui transformamos a seção "Anúncios" desse HTML em texto e contamos os leads por dia.
"""

import html as htmllib
import json
import re
from collections import Counter
from datetime import date

RE_SECAO = re.compile(r'<h2 id="anuncios">([\s\S]*?)(?=<h2 id=|$)')
RE_LEADS = re.compile(r'<script type="application/json" id="leads-json">([\s\S]*?)</script>')
RE_CARDS_TOPO = re.compile(r'<div class="r">((?:Investimento Meta|Custo por lead|Custo por reunião|Custo por venda|Retorno do anúncio|Leads))</div><div class="v[^"]*">([^<]+)</div><div class="s">([^<]*)</div>')


def _texto(fragmento: str) -> str:
    t = re.sub(r"<tr[^>]*>", "\n", fragmento)
    t = re.sub(r"</t[dh]>", " | ", t)
    t = re.sub(r"<(?:br|/div|/h[23])[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    linhas = [re.sub(r"[ \t]+", " ", l).strip(" |") for l in t.splitlines()]
    return "\n".join(l for l in linhas if l)


def resumo_anuncios(html: str) -> str:
    """Texto com os totais do mês (investimento, custo por lead...) e as tabelas por anúncio e campanha."""
    topo = [f"{nome}: {valor} ({obs})" for nome, valor, obs in RE_CARDS_TOPO.findall(html)]
    secao = RE_SECAO.search(html)
    corpo = _texto(secao.group(1)) if secao else "(seção Anúncios não encontrada no painel)"
    return "\n".join(topo) + "\n\n" + corpo


def leads_por_dia(html: str) -> dict[str, Counter]:
    """Leads criados por dia, separados por origem (ex.: Meta Ads, WhatsApp / outros)."""
    m = RE_LEADS.search(html)
    if not m:
        return {}
    dias: dict[str, Counter] = {}
    for lead in json.loads(m.group(1)).get("leads", []):
        dia = str(lead.get("cr") or "")[:10]
        if dia:
            dias.setdefault(dia, Counter())[lead.get("o") or "sem origem"] += 1
    return dict(sorted(dias.items()))


def chave_mes(d: date) -> str:
    return f"comercial:{d:%Y-%m}"
