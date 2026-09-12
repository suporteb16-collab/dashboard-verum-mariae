"""
Sincroniza os pedidos da Reserva INK com o Supabase (vendas.ink_pedidos).

    py sync_ink_supabase.py                 # incremental: ultimos 30 dias
    py sync_ink_supabase.py --full          # historico completo
    py sync_ink_supabase.py --desde 2026-01-01

Por que os ultimos 30 dias e nao "desde a ultima sync": na INK, mudanca de
status NAO altera created_at, e o filtro begin_date opera sobre a data de
criacao. Um pedido de 20 dias atras que saiu de "Pendente" para "Pago" hoje
nunca apareceria num filtro incremental estreito. A janela movel de 30 dias
recaptura essas mudancas; o upsert por (loja, pedido_id) as aplica sem duplicar.

Credenciais (nenhuma fica no codigo):
  api_ink.txt          token da INK
  SUPABASE_SERVICE_KEY service_role do projeto Data&Revenue
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extrair_ink import AQUI, achatar, baixar_pedidos, carregar_token  # noqa: E402

SUPABASE_URL = "https://afmisfmhfloabudcajbh.supabase.co"
TABELA = "ink_pedidos"
SCHEMA = "vendas"
LOTE = 500          # linhas por request; acima disso o PostgREST fica lento
JANELA_DIAS = 30


def chave_supabase() -> str:
    """Le do ambiente; se nao houver, cai para a linha service_role= do api_ink.txt."""
    k = os.environ.get("SUPABASE_SERVICE_KEY")

    if not k:
        txt = (AQUI / "api_ink.txt").read_text(encoding="utf-8")
        m = re.search(r"^\s*service_role\s*=\s*(\S+)", txt, re.MULTILINE)
        if m:
            k = m.group(1)

    if not k:
        sys.exit(
            "Falta SUPABASE_SERVICE_KEY.\n"
            "  Coloque no api_ink.txt uma linha:  service_role=<chave>\n"
            '  ou no PowerShell:  $env:SUPABASE_SERVICE_KEY = "<chave>"\n'
            "  Supabase > Project Settings > API Keys > service_role (Reveal)."
        )

    k = k.strip().strip('"').strip("'")

    # O projeto aceita dois formatos: JWT legado (eyJ...) e o novo (sb_secret_...).
    # A publishable/anon nao serve: o schema 'vendas' nao e exposto ao PostgREST.
    if k.startswith("sb_publishable_") or '"role":"anon"' in k:
        sys.exit("Essa e a chave publishable/anon. Pegue a service_role (ou sb_secret_).")
    if not (k.startswith("eyJ") or k.startswith("sb_secret_")):
        sys.exit(f"Formato de chave inesperado (comeca com '{k[:12]}...').")
    return k


def conferir_chave(key: str) -> None:
    """Falha rapido: valida a credencial antes de baixar as 24 paginas da INK."""
    # pela view em public — o schema 'vendas' nao e exposto ao PostgREST
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/dash_ink_vendas?select=pedido_id&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print("credencial ok")
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8")[:300]
        if e.code == 401:
            sys.exit(
                f"401 — chave invalida.\n  {corpo}\n\n"
                "  Confira em Project Settings > API Keys:\n"
                "  - use a linha 'service_role' (ou 'secret'), nao a publishable/anon\n"
                "  - clique em Reveal e copie o valor inteiro\n"
                "  - no PowerShell, entre aspas: $env:SUPABASE_SERVICE_KEY = \"...\""
            )
        sys.exit(f"Erro {e.code} ao validar a chave: {corpo}")


def upsert(linhas: list[dict], key: str) -> None:
    """Grava em lotes pela RPC public.ink_upsert_pedidos.

    Nao da para gravar direto em vendas.ink_pedidos: o PostgREST expoe apenas
    'public'. A RPC e security definer e faz o upsert por (loja, pedido_id) —
    reprocessar um periodo ja sincronizado atualiza, nao duplica."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    total = 0
    for i in range(0, len(linhas), LOTE):
        lote = linhas[i : i + LOTE]
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/rpc/ink_upsert_pedidos",
            data=json.dumps({"p_rows": lote}, ensure_ascii=False, default=str).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                total += int(r.read().decode("utf-8") or 0)
            print(f"  gravadas {i + len(lote)}/{len(linhas)}")
        except urllib.error.HTTPError as e:
            sys.exit(f"Erro {e.code} ao gravar: {e.read().decode('utf-8')[:400]}")
    print(f"  linhas afetadas: {total}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loja", default="verum", help="verum | mariae")
    ap.add_argument("--full", action="store_true", help="histórico completo")
    ap.add_argument("--desde", help="YYYY-MM-DD")
    ap.add_argument(
        "--do-csv",
        metavar="ARQUIVO",
        nargs="?",
        const="vendas_ink.csv",
        help="sobe do CSV já baixado, sem chamar a API da INK",
    )
    args = ap.parse_args()

    if args.full:
        desde = None
    elif args.desde:
        desde = args.desde
    else:
        desde = (date.today() - timedelta(days=JANELA_DIAS)).isoformat()

    print(f"loja={args.loja} | janela={desde or 'histórico completo'}")

    # valida a credencial antes de gastar 24 páginas da API da INK
    key = chave_supabase()
    conferir_chave(key)

    if args.do_csv:
        import csv

        NUM = {
            "valor_total", "valor_frete", "valor_desconto",
            "desconto_pagamento", "dif_frete", "valor_kickback",
        }
        linhas = []
        with (AQUI / args.do_csv).open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r = {k: (v if v != "" else None) for k, v in r.items()}
                r["loja"] = args.loja
                r["eh_troca"] = r["eh_troca"] == "True"
                r["pedido_id"] = int(r["pedido_id"])
                r["qtd_itens"] = int(r["qtd_itens"] or 0)
                for c in NUM:
                    r[c] = float(r.get(c) or 0)
                linhas.append(r)
        print(f"lidos {len(linhas)} pedidos de {args.do_csv}")
    else:
        token = carregar_token()
        brutos = baixar_pedidos(token, desde)

        unicos = {o["id"]: o for o in brutos}
        linhas = []
        for o in unicos.values():
            r = achatar(o)
            r["loja"] = args.loja
            linhas.append(r)

    print(f"\ngravando {len(linhas)} pedidos...")
    upsert(linhas, key)

    vendas = [r for r in linhas if r["status_pagamento"] == "Pago" and not r["eh_troca"]]
    receita = sum(r["valor_total"] for r in vendas)
    print(f"\nok — {len(linhas)} pedidos | {len(vendas)} vendas | R$ {receita:,.2f}")


if __name__ == "__main__":
    main()
