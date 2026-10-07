import re


def normalizar(telefone: str) -> str:
    """Deixa só os dígitos e garante o 55 do Brasil na frente."""
    digitos = re.sub(r"\D", "", telefone or "")
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    return digitos


def variantes(telefone: str) -> list[str]:
    """O WhatsApp às vezes entrega celulares brasileiros sem o nono dígito.

    Devolve as duas formas (com e sem o 9) para achar o motoboy de qualquer jeito.
    """
    t = normalizar(telefone)
    if not t.startswith("55"):
        return [t]
    ddd, numero = t[2:4], t[4:]
    if len(numero) == 9 and numero.startswith("9"):
        return [t, f"55{ddd}{numero[1:]}"]
    if len(numero) == 8:
        return [f"55{ddd}9{numero}", t]
    return [t]
