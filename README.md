# 🏍️ Maravilha Motos — Backend

API REST desenvolvida em **Python/Flask** para gerenciar o sistema de consórcios da **Maravilha Motos**. Permite cadastrar clientes, extrair dados de documentos (PDF/imagens) e gerenciar o estoque de motos.

## 🚀 Acesse a API

A API está hospedada no Railway:
```
https://maravilha-backend.up.railway.app
```

## 🛠️ Tecnologias Utilizadas

- **Python 3** — linguagem principal
- **Flask** — framework web
- **Flask-CORS** — suporte a requisições cross-origin
- **PostgreSQL** — banco de dados em produção
- **Google Gemini** — extração de dados de documentos com IA
- **pdfplumber** — leitura de PDFs
- **Pytesseract + Pillow** — OCR para imagens
- **Railway** — hospedagem e deploy automático

## 📋 Endpoints Disponíveis

### ✅ Saúde da API
```
GET /health
```

### 📄 Extração de Dados de Documentos
```
POST /extrair
```
Recebe um arquivo PDF ou imagem de cadastro de consórcio e retorna os dados extraídos (nome, grupo/cota, modelo, cor).

### 👤 Clientes
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | /clientes | Lista todos os clientes |
| POST | /clientes | Cadastra um novo cliente |
| PUT | /clientes/:id | Atualiza dados de um cliente |
| DELETE | /clientes/:id | Remove um cliente |

### 📦 Estoque
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | /estoque | Retorna dados do estoque |
| POST | /estoque | Atualiza o estoque |

### 📜 Histórico
```
GET /historico
```
Retorna as últimas 50 ações realizadas (adições, edições, remoções).

## ⚙️ Como Executar Localmente

```bash
# Clone o repositório
git clone https://github.com/Diggo1926/maravilha-backend.git
cd maravilha-backend

# Crie e ative um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Instale as dependências
pip install -r requirements.txt

# Configure as variáveis de ambiente
export GEMINI_API_KEY=sua_chave_aqui
export DATABASE_URL=sua_url_postgres  # opcional, usa JSON como fallback

# Inicie o servidor
python app.py
```

## 📂 Estrutura de Arquivos

```
maravilha-backend/
├── app.py              # Aplicação principal com todas as rotas
├── requirements.txt    # Dependências do projeto
├── Procfile            # Configuração para Railway
└── nixpacks.toml       # Configuração de build
```

## 👨‍💻 Desenvolvedor

Feito por [Rodrigo Mamede](https://github.com/Diggo1926)
