# Dashboard — Verum &amp; Mariae (Meta Ads)

Painel de performance de mídia paga das contas **Verum** e **Mariae Couture**, no padrão
visual da Agência B16.

🔗 https://suporteb16-collab.github.io/dashboard-verum-mariae/

---

## As duas abas

Duas contas de Meta, tabelas separadas, uma aba para cada.

| Aba | Conta | View | Janela de dado |
|---|---|---|---|
| **Verum** | `VERUM01` | `public.dash_verum_midia` | 01/01/2026 → 05/09/2026 |
| **Mariae Couture** | `MARIAE COUTURE` | `public.dash_mariae_midia` | 05/08/2026 → 05/09/2026 |

Não há visão somada. As contas têm portes muito diferentes (a Verum é ~94% do
investimento), então um total consolidado seria dominado por ela e o ROAS médio não
representaria nenhuma das duas.

Como as janelas de veiculação são diferentes, **o período é resolvido contra as datas da
aba ativa** — trocar de aba não arrasta o recorte da outra. O subtítulo de cada aba mostra
o intervalo real que ela cobre.

### Números do histórico completo

| | Investido | Compras | Receita | ROAS | Ticket médio |
|---|---|---|---|---|---|
| **Verum** | R$ 36.050,88 | 570 | R$ 158.391,33 | **4,39** | R$ 277,88 |
| **Mariae** | R$ 2.101,95 | 52 | R$ 11.249,70 | **5,35** | R$ 216,34 |

---

## Estas contas têm pixel de compra — por isso existe ROAS

Diferente do painel do Dr. Anderson (cujas campanhas são de perfil/WhatsApp e o resultado
é *conversa iniciada*), Verum e Mariae rodam e-commerce com o pixel de compra funcionando.
O funil vai até a compra e o KPI principal é o **ROAS**.

⚠️ **Receita, ROAS e ticket médio vêm do pixel do Meta**, não da plataforma de pagamento.
O pixel tende a superestimar — conversões mal atribuídas, testes, checkout abandonado que
ele ainda credita. O painel avisa isso no topo. Quando houver fonte de venda confirmada,
o plano é o mesmo do AAEMCWEB: uma view de vendas separada, cruzada por campanha, para
chegar a ROAS real.

### O alerta de compra dominante

Uma venda de ticket alto consegue sozinha distorcer um período curto. No mês atual da
Verum, **uma única compra de R$ 10.122,18 (04/09) responde por 97% da receita** e leva o
ROAS do mês a **36,98** — contra 4,39 do histórico. É dado real, não erro: é o maior
ticket de toda a base (o segundo é R$ 3.618,73).

Por isso, quando uma só compra representa ≥50% da receita de um período com ≤20 compras,
aparece um aviso explicando a concentração. Sem ele, o mês pareceria excepcional quando é
uma venda só.

Outros avisos automáticos: **sem investimento no período**, **ROAS abaixo de 1,0** (a mídia
devolveu menos do que custou) e **queda de ROAS acima de 25%** vs. o período anterior.

---

## A aba Pedidos (venda confirmada)

As duas primeiras abas mostram **mídia** (o que o pixel do Meta atribui). A aba
**Pedidos** mostra **venda confirmada**, direto da Reserva INK — a plataforma onde a
compra acontece.

Uma venda é um pedido **pago e que não é troca**. Troca é reenvio de um pedido já
vendido, não receita nova; incluí-la inflava a base em 106 pedidos / R$ 19.069,68.
É a mesma regra da tela de Estatísticas da INK, e 7 dos 8 KPIs batem na casa dos
centavos (o faturado difere R$ 61,05, 0,014%, não explicado — resíduo tolerado).

| | Pixel Meta | INK (real) |
|---|---|---|
| Compras (01/01→05/09) | 570 | **650** |
| Receita | R$ 158.391,33 | **R$ 147.307,49** |
| ROAS | 4,39 | **4,09** |

O pixel infla valor e erra data — a venda de R$ 10.122,18 que ele credita em 04/09 é
de **16/07**, atribuída ~7 semanas depois. Mas subconta pedidos.

A aba não tem ROAS: ela não conhece investimento. Cruzar venda real com gasto de
mídia é o passo seguinte, e depende de modelar isso para a Central de Performance.

**A INK é só a Verum.** Verificado pelos SKUs (catálogo contínuo, sem dois blocos de
marca) e pelo volume de agosto. A Mariae vende por outro canal.

### Como estes dados atualizam

Não é automático ainda. Hoje roda por comando:

```powershell
py sync_ink_supabase.py              # janela móvel de 30 dias
py sync_ink_supabase.py --full       # histórico completo
py sync_ink_supabase.py --do-csv     # sobe o CSV local, sem chamar a INK
```

A janela é de 30 dias, e não "desde a última sync", porque na INK **mudança de status
não altera `created_at`** e o filtro `begin_date` é por data de criação — um pedido de
20 dias atrás que virou "Pago" hoje não apareceria num filtro estreito. O upsert por
`(loja, pedido_id)` reaplica sem duplicar.

O Stract **não serve** para isso: o catálogo dele só tem conectores de mídia paga e
CRM, não há Reserva INK nem HTTP genérico. Para automatizar, n8n (como a Clint) ou
Task Scheduler do Windows.

## Fonte de dados

Tudo vem do **Supabase** (projeto `Data&Revenue`), por PostgREST, com a chave publishable.

| View | Origem |
|---|---|
| `public.dash_verum_midia` | `"trafego-pago".meta_ads_verum` (Meta Ads via Stract) |
| `public.dash_mariae_midia` | `"trafego-pago".meta_ads_mariae` (Meta Ads via Stract) |

### Por que views e não as tabelas direto

O schema `trafego-pago` **não é publicado no PostgREST** (só `public` e `graphql_public`).
A view em `public` é a ponte, com `security_definer` — é o que permite o anon ler sem ter
`select` na tabela do schema não publicado. Aparece no linter do Supabase como
`security_definer_view` (nível ERROR) e **é intencional**, igual às views dos demais
painéis B16. Tabelas de mídia não têm dado pessoal, então as views são projeções diretas,
sem mascaramento.

### Paginação

O PostgREST corta em **1.000 linhas por página**. A Verum já passa de 1.400, então sem
paginação o histórico viria truncado. A carga usa `sbPaginado()`, que pagina com o header
`Range` até a resposta vir menor que a página.

### Não há Google Ads para estes clientes

A `dash_google_ads` tem um registro `Verum` de 01/08/2024 com investimento, impressões,
cliques e conversões **todos zerados** — linha órfã, não conta real. Por isso este painel
não tem aba de Google, ao contrário do painel do Dr. Anderson.

---

## Como os números são calculados

- **ROAS** = receita do pixel ÷ investimento. **Ticket médio** = receita ÷ compras.
  **Custo por compra** = investimento ÷ compras. Todos retornam `—` (não `R$ 0,00` nem
  `0,00`) quando a base é zero.
- **Comparação "vs período anterior"** usa uma janela de mesma duração imediatamente
  anterior à selecionada, recalculada no cliente a cada filtro.
- **Nos KPIs de custo** (CPM, CPC, custo por compra) a seta verde é para *queda* — cair é
  bom. Nos de resultado (ROAS, receita, compras) é o contrário.
- **Funil:** a pílula de "% da etapa anterior" só aparece de Impressões em diante. Entre
  Investimento → Impressões são unidades diferentes (R$ vs. contagem) e a taxa não teria
  leitura válida.
- **A evolução diária mostra só investimento.** Plotar receita na mesma escala achatava
  as barras de gasto (uma venda de R$ 10 mil contra diárias de ~R$ 70, o eixo ia a R$ 12k),
  e o ROAS diário chegava a 150 num dia — a curva virava um pico isolado com o resto
  colado no zero. Receita e ROAS estão nos KPIs e na tabela, onde se leem melhor.

---

## Stack e design

HTML/CSS/JS puro, Chart.js 4, sem build. Paleta **clássica B16**: `#f4f4f2` / `#d4a800` /
`#111`, Bebas Neue + DM Sans, tema claro e escuro. 2 slots categóricos (amarelo =
investimento, azul = receita/resultado). O amarelo da marca fica abaixo de 3:1 no tema
claro, então **toda barra leva rótulo direto** — a leitura nunca depende só da cor. Funil
em trapézio (CSS puro), com a magnitude na largura, nunca na cor.

As duas abas têm estrutura idêntica, então existe **um único painel no HTML**, redesenhado
a cada troca de aba. Evita duplicar markup e garante que as duas contas sejam sempre lidas
do mesmo jeito.

---

## Arquivos

| | |
|---|---|
| `index.html` | o dashboard |

---

## Deploy

Repositório `suporteb16-collab/dashboard-verum-mariae`, branch `main`, GitHub Pages.
`git push origin main` e o Pages republica em ~20s.

**Agência B16** — Henrique Cardoso, Business Intelligence · 07/09/2026.
