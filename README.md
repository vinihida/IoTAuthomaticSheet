# IoT Inventory & Reports (Flask + SQLite)

Sistema de "planilha" automatizada para controle de EPI e materiais (cobre e metais), com autenticação (usuário/admin), atualização em tempo real (SSE) e simulador IoT (preços e eventos de estoque). Gera relatórios mensais e exportação CSV.

## Requisitos
- Python 3.10+
- Windows PowerShell ou terminal equivalente

## Instalação
```bash
python -m venv .venv
. .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Banco e dados de exemplo
```bash
python manage.py init-db
python manage.py seed-demo
```
Cria usuários:
- admin: admin@local / Admin123!
- user: user@local / User123!

## Rodando
```bash
python manage.py run
```
Acesse `http://localhost:5000`.

O simulador IoT roda em background e:
- Aplica jitter de preço periódico para cada material
- Gera eventos de entrada/saída aleatórios (sem deixar o estoque negativo)

A dashboard atualiza automaticamente via SSE.

## Estrutura
- `app/__init__.py`: app factory, DB, login, SSE broker
- `app/config.py`: configuração e intervalos do simulador
- `app/models.py`: User, Material, Price, StockEvent
- `app/auth.py`: login/logout/registro (admin)
- `app/routes.py`: dashboard, materiais, estoque, SSE, relatórios
- `app/iot_simulator.py`: simulador de preços/eventos
- `app/templates/`: páginas HTML
- `app/static/`: JS/CSS
- `manage.py`: CLI (init-db, seed-demo, run)

## Notas
- Os gastos mensais consideram apenas saídas (qty negativa) com preço do momento do evento.
- As tabelas replicam a experiência de planilha e permitem exportar CSV.

# IoTAuthomaticSheet