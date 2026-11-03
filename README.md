# BK Proteção Sistêmica

App em **Python + Streamlit + Neon (PostgreSQL)** para estudos de ajustes de proteção, genérico para qualquer cliente/empreendimento.
Recebe os resultados de curto-circuito (Anafas, ETAP, PowerFactory etc., importados ou digitados) e calcula os ajustes das funções
selecionadas: 21/68 (distância, load encroachment, OSB), 50/51/50N/51N, 67/67N, 27/59/81, 50BF/79/25, 87T/87L/87B e 46/49/32/40/87G,
com verificações, alertas e conferência de ajustes existentes.

Entrega: **relatório Word** (metodologia, equações nativas do Word, memória de cálculo, gráficos R-X) e
**planilha Excel** (uma aba) com os valores a ajustar em cada relé.

## Rodar localmente
```bash
pip install -r requirements.txt
streamlit run app.py
```
O banco é lido de `DATABASE_URL` (arquivo `.streamlit/secrets.toml` ou variável de ambiente).
Sem a variável, o app usa SQLite local só para teste (aviso na barra lateral).
**Não versione o `secrets.toml`** (já está no `.gitignore`).

## Publicar (Railway)
1. Suba o código (sem `secrets.toml`) para o GitHub e conecte no Railway.
2. Em *Variables*, crie `DATABASE_URL` com a string de conexão do Neon.
3. O `Procfile` já inicia o app. As tabelas `protsis_*` são criadas automaticamente no primeiro acesso.

## Fluxo de uso
1. **Projeto** — cliente, nº do documento, revisão, referências.
2. **Terminais e LT** — dados da LT, RTC/RTP, carga, sistema; modo *novos ajustes* ou *conferência*.
3. **Curto-circuito** — importe CSV/TXT/Excel exportado do Anafas, ETAP, PowerFactory, ASPEN etc. e confirme o mapeamento de colunas.
4. **Critérios** — alcances, margens, tempos e fatores (valores padrão editáveis por projeto).
5. **Cálculo** — resultados, gráficos R-X, memória de cálculo, verificações.
6. **Relatórios** — baixe o `.docx` e o `.xlsx`.

## Formato do curto-circuito
Colunas padronizadas (o app reconhece sinônimos e permite mapear manualmente):
`ponto`, `tipo` (3F/FT/FF/FFT), `local_pct` (posição na LT, %), `icc_ka`, `rf_ohm` (opcional), `terminal` (opcional).
Veja `exemplos/curto_exemplo.csv`.

## Metodologia (resumo)
- Conversão primário→secundário: `ks = RTC/RTP`.
- Zonas mho: `Z1 = k1·ZL`; `Z2 = min(k2·ZL, ZL + f·Zadj,mín)`; `Z3 = ZL + k3·Zadj,máx`.
- Carga: `Zcarga,mín = Vmín·Vn / (√3·Iref)`, `Iref = max(Smáx/(√3·Vn), Itérm)`; `ZLF = kL·Zcarga,mín`.
- Blinder interno: `dint = (1+m)·Zmáx,bloq/2`; externo: `dext = kext·dcarga`, com `dcarga = Zcarga,mín·|sen(θL−φ)|`.
- Oscilação: `δ = 2·arctan(Zt/(2d))`; tempo entre blinders `t = (δint − δext)/(360·fslip)`; velocidade de impedância
  `|dZ/dt| = (Zt/4)·[1+(2d/Zt)²]·2π·fslip`; `OSBD = kt·t` (nunca abaixo do tempo de evolução da falta).
- Pickup 51: `kp·Iref ≤ Ipk ≤ Icc,mín/ks51`.
- Pickup 51N: `kd·Iref ≤ Ipk ≤ Icc,FT,mín/ks51N` (kd = desequilíbrio admissível).
- Pickup 50/50N: `Ipk ≥ k_inst · Icc na barra remota` (falta a 100 % da LT).
- Curvas IEC 60255-151: `t = TMS·k/((I/Ipk)^α − 1)`; TMS calculado para atuar em `t_jusante + Δt` na falta remota (arredondado para cima).

## Escolha das funções por relé
Na etapa **2** marque as funções a ajustar em cada relé (`21`, `68`, `50`, `51`, `50N`, `51N`). Só elas entram no cálculo,
no relatório e na planilha, e o formulário mostra apenas os dados que elas exigem (ex.: só sobrecorrente dispensa R1/X1).
Funções ainda sem módulo (67, 50BF, 79, 25, 27, 59, 81, 87L/T/B/G, 46, 49, 32, 40) aparecem como roteiro.
Para criar uma nova função: acrescente-a em `core/funcoes.py` (`pronta=True`) e crie o módulo em `core/` com a mesma
interface de `core/f_sobrecorrente.py` (`calcular(...)` → passos, verificações, alertas, ajustes, conferência).

## Funções direcionais 67 / 67N e fasores de falta
- **Entrada**: para cada falta, módulo e ângulo de I (kA) e V (kV fase-neutro) **no relé**, em fases (A,B,C) ou sequências (1,2,0).
  Pode ser **importado** de qualquer programa (Anafas, ETAP, PowerFactory, ASPEN…: relatório de falta com contribuições e tensões da barra,
  exportado em CSV/Excel, com mapeamento de colunas) ou **digitado** na etapa 3. O app não depende de um layout específico do Anafas.
- **Convenções**: sequência ABC; ângulos em graus; corrente positiva **saindo da barra do relé para a LT** (marque "inverter" se o
  programa exporta o contrário); I0/V0 podem vir como 3·I0/3·V0; coluna "sentido" (frente/ré) ou posição negativa na LT = falta à ré.
- **Cálculo**: MTA = média circular do atraso da corrente nas faltas à frente (arredondado ao passo); região MTA ± ROA; 67N polarizado por
  −3V0, 67 por tensão em quadratura (Ia–Vbc, Ib–Vca, Ic–Vab); limiares de polarização acima da assimetria e abaixo do observado em falta;
  pickup e TMS como no 51/51N. Faltas à ré devem ficar fora da região (verificação por caso).
- **Não cobre**: polarização por sequência negativa, memória de tensão, elemento direcional instantâneo, SEL (usa limiares Z2F/Z2R — mapear no manual).

## Funções de tensão e frequência (27 / 59 / 81)
- **27**: pickup = Vop,mín − margem; tempo = eliminação de falta + Δt. **59**: estágio 1 temporizado (Vop,máx + margem ≤ TOV suportada) e estágio 2 rápido.
  **81**: 3 estágios de sub e 3 de sobrefrequência escalonados, com bloqueio por subtensão.
- Os tempos e margens padrão são critérios editáveis (etapa 4), **não são norma**: alinhar à norma técnica/critério do cliente.
- Arquitetura: cada módulo declara campos e critérios em `core/f_*.py` (ver `core/modulos.py`); app, relatório e manual leem dessa declaração.

## Funções de disjuntor (50BF / 79 / 25)
- **50BF**: temporizador = t_disjuntor + t_rearme + margem; tempo total vs tempo crítico de estabilidade; pickup entre o mínimo/residual e Icc,mín/k.
- **79**: tempo morto ≥ deionização (10,5 + Vn/34,5 ciclos) + diferença entre terminais + margem; monopolar com arco secundário; reclaim ≥ recarga + tempo morto.
- **25**: ΔV, Δf, Δφ; Δφ de ajuste = Δφ máx − 360·Δf·t_fechamento; tensões de vivo/morto.

## Premissas e limitações
- Sistema homogêneo (fontes e LT com o mesmo ângulo), fontes de mesma magnitude durante a oscilação.
- Impedância de fonte obtida do Icc 3F das barras (`Vn/(√3·Icc)`); informe o equivalente **atrás do relé**.
- Impedância aparente das faltas = `m·ZL + Rf` (não lê fasores de tensão/corrente).
- A `f_slip` máxima deve vir do estudo de estabilidade do cliente.
- Os **nomes de parâmetros SEL** (Z1P, ZLF, R1R6, OSBD etc.) são referência: confira no manual do firmware, assim como faixas, passos e convenções de sinal.
  Para outros fabricantes o app entrega o valor calculado e o nome fica "—" (mapear no software do fabricante).
- O app calcula e recomenda ajustes; aplicação nos relés, testes e comissionamento ficam fora do escopo.

## Testes
```bash
pytest -q
```

## Funções 87T/87L/87B e 46/49/32/40/87G (Lotes 3 e 4)
- `core/f_diferencial.py`: 87T (TAP, descasamento, inclinações, pickup, instantâneo), 87L (pickup × corrente capacitiva) e 87B (alta/baixa impedância).
- `core/f_gerador.py`: 46 (I2²t), 49 (modelo térmico), 32 (potência reversa), 40 (dois mho com offset) e 87G (percentual).
- Critérios padrão são valores de engenharia assumidos (etapa 4); nomes de parâmetros SEL devem ser conferidos no manual do relé.
