# Maravilha Motos — Backend

API REST desenvolvida em **Python/Flask** para gerenciar o sistema de consorcios da **Maravilha Motos**. Permite cadastrar clientes, extrair dados de documentos (PDF/imagens) e gerenciar o estoque de motos.

## Acesse a API

A API esta hospedada no Railway:
```
https://maravilha-backend.up.railway.app
```

## Tecnologias Utilizadas

- **Python 3** — linguagem principal
- **Flask** — framework web
- **Flask-CORS** — suporte a requisicoes cross-origin
- **PostgreSQL** — banco de dados em producao
- **Google Gemini** — extracao de dados de documentos
- **pdfplumber** — leitura de PDFs
- **Pytesseract + Pillow** — OCR para imagens
- **Railway** — hospedagem e deploy automatico

## Endpoints Disponiveis

### Saude da API
```
GET /health
```

### Extracao de Dados de Documentos
```
POST /extrair
```
Recebe um arquivo PDF ou imagem de cadastro de consorcio e retorna os dados extraidos (nome, grupo/cota, modelo, cor).

### Clientes
| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | /clientes | Lista todos os clientes |
| POST | /clientes | Cadastra um novo cliente |
| PUT | /clientes/:id | Atualiza dados de um cliente |
| DELETE | /clientes/:id | Remove um cliente |

### Estoque
| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | /estoque | Retorna dados do estoque |
| POST | /estoque | Atualiza o estoque |

### Historico
```
GET /historico
```
Retorna as ultimas 50 acoes realizadas (adicoes, edicoes, remocoes).

## Como Executar Localmente

```bash
# Clone o repositorio
git clone https://github.com/Diggo1926/maravilha-backend.git
cd maravilha-backend

# Crie e ative um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Instale as dependencias
pip install -r requirements.txt

# Configure as variaveis de ambiente
export GEMINI_API_KEY=sua_chave_aqui
export DATABASE_URL=sua_url_postgres  # opcional, usa JSON como fallback

# Inicie o servidor
python app.py
```

## Estrutura de Arquivos

```
maravilha-backend/
├── app.py              # Aplicacao principal com todas as rotas
├── requirements.txt    # Dependencias do projeto
├── Procfile            # Configuracao para Railway
└── nixpacks.toml       # Configuracao de build
```

## Desenvolvedor

Feito por [Rodrigo Mamede](https://github.com/Diggo1926)
