"""
Extrai pedidos da API da Reserva INK e gera o CSV de vendas confirmadas.

Uso:
    py extrair_ink.py                  # histórico completo
    py extrair_ink.py --desde 2026-09-01

O token é lido de api_ink.txt (fora do git). Nunca hardcode a chave aqui.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://api.reserva.ink/v1/stores"
AQUI = Path(__file__).parent
PER_PAGE = 100          # máximo permitido; menos páginas = menos consumo do rate limit
PAUSA = 0.7             # ~85 req/min, folga sob o teto de 100
MAX_TENTATIVAS = 5

# A API devolve o comprador inteiro (CPF, e-mail, telefone, endereço). Nada disso
# entra no CSV: o dashboard é de performance, não de cadastro. Só sai um hash
# estável do documento, que permite contar clientes recorrentes sem guardar o CPF.
SALT = "b16-ink-verum"


def carregar_token() -> str:
    """Le a linha 'API:' do api_ink.txt. O arquivo tambem guarda a service_role
    do Supabase, entao a busca e ancorada no rotulo — nao na primeira string
    longa que aparecer."""
    txt = (AQUI / "api_ink.txt").read_text(encoding="utf-8")
    m = re.search(r"^\s*API\s*[:=]\s*(\S+)", txt, re.MULTILINE)
    if not m:
        sys.exit("Token da INK não encontrado: falta a linha 'API: <token>' em api_ink.txt")
    return m.group(1)


def get(caminho: str, token: str, **params) -> dict:
    """GET com backoff para 429 (a INK não manda Retry-After)."""
    url = f"{BASE}/{caminho}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    for tentativa in range(MAX_TENTATIVAS):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                espera = (5, 15, 30, 60, 90)[tentativa]
                print(f"  429 — aguardando {espera}s", file=sys.stderr)
                time.sleep(espera)
                continue
            raise
    sys.exit("Rate limit persistente. Tente mais tarde.")


def anonimo(doc: str | None) -> str:
    if not doc:
        return ""
    limpo = re.sub(r"\D", "", doc)
    return hashlib.sha256((SALT + limpo).encode()).hexdigest()[:16] if limpo else ""


def baixar_pedidos(token: str, desde: str | None) -> list[dict]:
    filtros = {"per_page": PER_PAGE}
    if desde:
        filtros["begin_date"] = desde

    primeira = get("orders", token, page=1, **filtros)
    total_paginas = primeira.get("total_pages", 1)
    total = primeira.get("total_count", 0)
    print(f"{total} pedidos em {total_paginas} páginas")

    pedidos = list(primeira["orders"])
    for p in range(2, total_paginas + 1):
        time.sleep(PAUSA)
        print(f"  página {p}/{total_paginas}", file=sys.stderr)
        pedidos.extend(get("orders", token, page=p, **filtros)["orders"])
    return pedidos


def achatar(o: dict) -> dict:
    """Uma linha por pedido, só com o que o dashboard usa."""
    entrega = o.get("delivery") or {}
    comprador = o.get("buyer") or {}
    envio = o.get("shipping_address") or {}
    itens = o.get("items") or []

    return {
        "pedido_id": o["id"],
        "referencia": o.get("rsv_factory_id"),
        "criado_em": o.get("created_at"),
        "data": (o.get("created_at") or "")[:10],
        "status_pedido": o.get("order_status"),
        "status_pedido_txt": o.get("formatted_order_status"),
        "status_pagamento": o.get("payment_status"),
        "forma_pagamento": o.get("payment_method"),
        "eh_troca": o.get("is_exchange"),
        # valores: a API manda string, converto para número aqui
        "valor_total": float(o.get("total_value") or 0),
        "valor_frete": float(o.get("shipping_value") or 0),
        "valor_desconto": float(o.get("promotion_value") or 0),
        "desconto_pagamento": float(o.get("payment_discount_value") or 0),
        "dif_frete": float(o.get("freight_value_difference") or 0),
        # kickback = a margem que fica para a loja (a INK retém o custo de produção)
        "valor_kickback": float(o.get("kickback_value") or 0),
        "cupom": o.get("promotion_code"),
        "qtd_itens": sum(i.get("quantity", 0) for i in itens),
        "skus": "|".join(str(i.get("sku")) for i in itens if i.get("sku")),
        # geografia serve para segmentar mídia; endereço exato não entra
        "uf": envio.get("state"),
        "cidade": envio.get("city"),
        "cliente_hash": anonimo(comprador.get("document")),
        "transportadora": entrega.get("carrier"),
        "entregue_em": entrega.get("delivered_at"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="YYYY-MM-DD (filtra por data de criação)")
    ap.add_argument("--saida", default="vendas_ink.csv")
    args = ap.parse_args()

    token = carregar_token()
    brutos = baixar_pedidos(token, args.desde)

    # dedup por id: reprocessar um dia já visto é seguro, mas não pode duplicar
    unicos = {o["id"]: o for o in brutos}
    linhas = [achatar(o) for o in unicos.values()]
    linhas.sort(key=lambda r: r["criado_em"] or "")

    destino = AQUI / args.saida
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)

    # Regra de "venda" da INK, conciliada contra a tela de Estatísticas do painel:
    # pago E não-troca. Troca é reenvio de um pedido que já foi vendido, não
    # receita nova — contá-la duplicava 106 pedidos / R$ 19 mil no histórico.
    vendas = [
        r for r in linhas
        if r["status_pagamento"] == "Pago" and not r["eh_troca"]
    ]
    receita = sum(r["valor_total"] for r in vendas)
    lucro = sum(r["valor_kickback"] for r in vendas)
    itens = sum(r["qtd_itens"] for r in vendas)

    print(f"\n{destino.name}: {len(linhas)} pedidos | {len(vendas)} vendas")
    print(f"faturado:     R$ {receita:,.2f}")
    print(f"lucro:        R$ {lucro:,.2f}")
    if vendas:
        print(f"ticket médio: R$ {receita / len(vendas):,.2f}")
        print(f"itens:        {itens} ({itens / len(vendas):.1f} por venda)")


if __name__ == "__main__":
    main()
