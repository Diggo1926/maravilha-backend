import os
import re
import json
import uuid
import base64
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
from PIL import Image
import pytesseract

app = Flask(__name__)
CORS(app)

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_FILE    = BASE_DIR / "clientes.json"
ESTOQUE_FILE = BASE_DIR / "estoque.json"

UPLOAD_DIR.mkdir(exist_ok=True)

# ─── BANCO DE DADOS ─────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_usar_postgres = bool(DATABASE_URL)


def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _init_db():
    if not _usar_postgres:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id TEXT PRIMARY KEY,
                nome TEXT,
                grupo_cota TEXT,
                modelo TEXT,
                cor TEXT,
                status TEXT,
                data_entrada TEXT,
                data_contemplacao TEXT,
                criado_em TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historico (
                id SERIAL PRIMARY KEY,
                cliente_id TEXT,
                acao TEXT,
                dados_anteriores TEXT,
                dados_novos TEXT,
                data_hora TEXT
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[DB] Tabelas inicializadas.")
    except Exception as e:
        print(f"[DB] Erro ao inicializar tabelas: {e}")


_init_db()


def _row_to_dict(row):
    return {
        "id":                row[0],
        "nome":              row[1],
        "grupo_cota":        row[2],
        "modelo":            row[3],
        "cor":               row[4],
        "status":            row[5],
        "data_entrada":      row[6],
        "data_contemplacao": row[7],
        "criado_em":         row[8],
    }


def _registrar_historico(conn, cliente_id, acao, dados_anteriores=None, dados_novos=None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO historico (cliente_id, acao, dados_anteriores, dados_novos, data_hora) VALUES (%s, %s, %s, %s, %s)",
        (
            cliente_id,
            acao,
            json.dumps(dados_anteriores, ensure_ascii=False) if dados_anteriores else None,
            json.dumps(dados_novos, ensure_ascii=False) if dados_novos else None,
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        )
    )
    cur.close()


# ─── PERSISTÊNCIA ───────────────────────────────────────────
def carregar_clientes():
    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, nome, grupo_cota, modelo, cor, status, data_entrada, data_contemplacao, criado_em FROM clientes ORDER BY criado_em DESC")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [_row_to_dict(r) for r in rows]
        except Exception as e:
            print(f"[DB] Erro ao carregar clientes: {e}")
            return []
    # Fallback JSON
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_clientes(clientes):
    """Mantida apenas para fallback JSON."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(clientes, f, ensure_ascii=False, indent=2)


# ─── EXTRAÇÃO DE TEXTO (fallback sem IA) ────────────────────
def extrair_texto_pdf(caminho):
    texto = ""
    try:
        with pdfplumber.open(caminho) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texto += t + "\n"
    except Exception as e:
        print(f"[pdfplumber] Erro: {e}")

    if not texto.strip():
        texto = ocr_pdf(caminho)
    return texto


def ocr_pdf(caminho):
    try:
        from pdf2image import convert_from_path
        imagens = convert_from_path(caminho, dpi=300)
        texto = ""
        for img in imagens:
            texto += pytesseract.image_to_string(img, lang="por") + "\n"
        return texto
    except Exception as e:
        print(f"[OCR PDF] Erro: {e}")
        return ""


def ocr_imagem(caminho):
    try:
        img = Image.open(caminho)
        return pytesseract.image_to_string(img, lang="por")
    except Exception as e:
        print(f"[OCR IMG] Erro: {e}")
        return ""


def parsear_campos_regex(texto):
    """Fallback: extrai campos por regex quando a IA falha."""
    resultado = {"nome": None, "grupo_cota": None, "modelo": None, "cor": None}

    # Grupo/Cota: padrão NNNNN-NNN-N-N no topo do documento
    cota = re.search(r'\b(\d{4,5}-\d{2,3}-\d-\d)\b', texto)
    if cota:
        resultado["grupo_cota"] = cota.group(1)

    # Nome completo logo após "Nome Completo"
    nome = re.search(
        r'Nome\s+Completo[:\s]+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇa-záéíóúâêîôûãõàèìòùç\s]{5,70}?)(?:\s{2,}|\n|CPF|Data|Tipo)',
        texto, re.IGNORECASE
    )
    if nome:
        n = re.sub(r'\s+', ' ', nome.group(1)).strip()
        if len(n.split()) >= 2:
            resultado["nome"] = n

    # Modelo — procura padrões Honda comuns
    modelos = ['CG 160','CG160','NXR','BIZ','PCX','CB 300','CB300','XRE','LEAD','POP','FAN','BROS','TWISTER','TITAN','DREAM','CB 500','START','SHINE']
    for mod in modelos:
        m = re.search(rf'{re.escape(mod)}[\s\w]{{0,20}}', texto, re.IGNORECASE)
        if m:
            resultado["modelo"] = re.sub(r'\s+', ' ', m.group(0)).strip().rstrip('.,;')
            break

    if resultado["modelo"]:
        modelo = re.sub(r'\s+\d+[\.,]?\d*\s*%?$', '', resultado["modelo"]).strip()
        modelo = re.sub(r'\s+[A-Z]$', '', modelo).strip()
        resultado["modelo"] = modelo

    # Cor
    cores = ['BRANCA?','PRETA?','VERMELH[AO]','AZUL','PRATA','CINZA','AMARELA?','VERDE','LARANJA','VINHO','GRAFITE','MARROM']
    cor = re.search(r'\b(' + '|'.join(cores) + r')\b', texto, re.IGNORECASE)
    if cor:
        resultado["cor"] = cor.group(1).upper()

    return resultado


# ─── GEMINI ────────────────────────────────────────────────
def extrair_com_gemini(caminho, ext):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada no servidor.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    with open(caminho, 'rb') as f:
        dados_arquivo = f.read()

    mime = 'application/pdf' if ext == '.pdf' else f'image/{ext.lstrip(".")}'

    # Prompt detalhado baseado no formato real do documento Honda
    prompt = """Este é um documento "CADASTRO DE PESSOA FÍSICA - CONSORCIADO" da Honda Consórcio.

Extraia EXATAMENTE os seguintes campos:

1. "nome": O nome completo do consorciado. Está no campo "Nome Completo:" na seção INFORMAÇÕES PESSOAIS. Exemplo: "LORRAYNE DRIELLY CAMPOS MARTINS"

2. "grupo_cota": O código do grupo/cota. Está logo abaixo do título "CADASTRO DE PESSOA FÍSICA - CONSORCIADO", no formato NNNNN-NNN-N-N. Exemplo: "43460-563-0-0"

3. "modelo": O modelo da moto. Está na tabela "TERMO DE COMPROMISSO" na coluna "Modelo". Também pode aparecer no campo "Bem base plano" com asterisco. Exemplo: "CG 160 TITAN S"

4. "cor": A cor da moto. Está na tabela "TERMO DE COMPROMISSO" na coluna "Cor". Exemplo: "BRANCA"

Retorne SOMENTE este JSON, sem texto antes ou depois, sem markdown:
{"nome": "...", "grupo_cota": "...", "modelo": "...", "cor": "..."}

Se algum campo não for encontrado, use null."""

    resposta = model.generate_content([
        {
            "inline_data": {
                "mime_type": mime,
                "data": base64.b64encode(dados_arquivo).decode()
            }
        },
        prompt
    ])

    txt = resposta.text.strip()
    print(f"[Gemini raw] {txt}")

    # Remove possíveis marcações de markdown
    txt = re.sub(r'```(?:json)?', '', txt).strip().rstrip('`').strip()

    # Extrai apenas o objeto JSON
    match = re.search(r'\{.*\}', txt, re.DOTALL)
    if match:
        txt = match.group(0)

    return json.loads(txt)


# ─── ROTAS ─────────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    api_key = os.environ.get('GEMINI_API_KEY', '')
    return jsonify({
        "status": "ok",
        "gemini_key_configurada": bool(api_key),
        "banco": "postgres" if _usar_postgres else "json",
        "versao": "4.0"
    })


@app.route('/extrair', methods=['POST'])
def extrair():
    if 'arquivo' not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado. Use o campo 'arquivo'."}), 400

    arquivo = request.files['arquivo']
    if not arquivo.filename:
        return jsonify({"erro": "Nome de arquivo inválido."}), 400

    ext = Path(arquivo.filename).suffix.lower()
    if ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
        return jsonify({"erro": f"Formato '{ext}' não suportado. Use PDF, PNG ou JPG."}), 400

    nome_tmp = f"{uuid.uuid4()}{ext}"
    caminho = UPLOAD_DIR / nome_tmp
    arquivo.save(str(caminho))

    resultado = {}
    metodo = "gemini"

    try:
        # Tenta com Gemini (IA)
        resultado = extrair_com_gemini(caminho, ext)
        print(f"[Gemini OK] {resultado}")

    except ValueError as ve:
        # Chave não configurada
        print(f"[Gemini] {ve} — fallback regex")
        metodo = "regex"
        texto = extrair_texto_pdf(str(caminho)) if ext == '.pdf' else ocr_imagem(str(caminho))
        resultado = parsear_campos_regex(texto)

    except json.JSONDecodeError as je:
        # Gemini retornou JSON malformado — tenta regex
        print(f"[Gemini] JSON inválido: {je} — fallback regex")
        metodo = "regex"
        texto = extrair_texto_pdf(str(caminho)) if ext == '.pdf' else ocr_imagem(str(caminho))
        resultado = parsear_campos_regex(texto)

    except Exception as e:
        print(f"[Gemini] Erro: {type(e).__name__}: {e} — fallback regex")
        metodo = "regex"
        try:
            texto = extrair_texto_pdf(str(caminho)) if ext == '.pdf' else ocr_imagem(str(caminho))
            resultado = parsear_campos_regex(texto)
        except Exception as e2:
            print(f"[Fallback] Também falhou: {e2}")
            resultado = {"nome": None, "grupo_cota": None, "modelo": None, "cor": None}

    finally:
        if caminho.exists():
            caminho.unlink()

    # Limpa valores "null" string
    for k in resultado:
        if resultado[k] in (None, 'null', 'None', ''):
            resultado[k] = None

    resultado["_metodo"] = metodo
    print(f"[Resultado final] metodo={metodo} dados={resultado}")
    return jsonify(resultado)


# ─── CLIENTES CRUD ─────────────────────────────────────────
@app.route('/clientes', methods=['GET'])
def listar_clientes():
    return jsonify(carregar_clientes())


@app.route('/clientes', methods=['POST'])
def adicionar_cliente():
    dados = request.get_json()
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido"}), 400

    cliente = {
        "id":                str(uuid.uuid4()),
        "nome":              dados.get("nome", "—"),
        "grupo_cota":        dados.get("grupo_cota", "—"),
        "modelo":            dados.get("modelo", "—"),
        "cor":               dados.get("cor", "—"),
        "status":            dados.get("status", "Aguardando Contemplação"),
        "data_entrada":      dados.get("data_entrada", "—"),
        "data_contemplacao": dados.get("data_contemplacao", "—"),
        "criado_em":         datetime.now().strftime("%d/%m/%Y"),
    }

    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()

            # Validação de duplicata por grupo_cota
            gc = cliente["grupo_cota"]
            if gc and gc != "—":
                cur.execute("SELECT id FROM clientes WHERE grupo_cota = %s", (gc,))
                if cur.fetchone():
                    cur.close()
                    conn.close()
                    return jsonify({"erro": "Cliente com este Grupo/Cota já está cadastrado", "duplicado": True}), 409

            cur.execute(
                "INSERT INTO clientes (id, nome, grupo_cota, modelo, cor, status, data_entrada, data_contemplacao, criado_em) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (cliente["id"], cliente["nome"], cliente["grupo_cota"], cliente["modelo"],
                 cliente["cor"], cliente["status"], cliente["data_entrada"],
                 cliente["data_contemplacao"], cliente["criado_em"])
            )
            _registrar_historico(conn, cliente["id"], "ADICIONADO", dados_novos=cliente)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[DB] Erro ao adicionar cliente: {e}")
            return jsonify({"erro": "Erro interno ao salvar cliente"}), 500
    else:
        # Fallback JSON
        clientes = carregar_clientes()
        gc = cliente["grupo_cota"]
        if gc and gc != "—":
            if any(c.get("grupo_cota") == gc for c in clientes):
                return jsonify({"erro": "Cliente com este Grupo/Cota já está cadastrado", "duplicado": True}), 409
        clientes.insert(0, cliente)
        salvar_clientes(clientes)

    return jsonify(cliente), 201


@app.route('/clientes/<id>', methods=['PUT'])
def editar_cliente(id):
    dados = request.get_json()
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido"}), 400

    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()

            # Busca estado anterior para histórico
            cur.execute("SELECT id, nome, grupo_cota, modelo, cor, status, data_entrada, data_contemplacao, criado_em FROM clientes WHERE id = %s", (id,))
            row = cur.fetchone()
            anterior = _row_to_dict(row) if row else None

            campos = {k: v for k, v in dados.items() if k != "id"}
            if campos:
                sets = ", ".join(f"{k} = %s" for k in campos)
                valores = list(campos.values()) + [id]
                cur.execute(f"UPDATE clientes SET {sets} WHERE id = %s", valores)

            # Busca estado novo para histórico
            cur.execute("SELECT id, nome, grupo_cota, modelo, cor, status, data_entrada, data_contemplacao, criado_em FROM clientes WHERE id = %s", (id,))
            row_novo = cur.fetchone()
            novo = _row_to_dict(row_novo) if row_novo else None

            _registrar_historico(conn, id, "EDITADO", dados_anteriores=anterior, dados_novos=novo)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[DB] Erro ao editar cliente: {e}")
            return jsonify({"erro": "Erro interno ao editar cliente"}), 500
    else:
        clientes = carregar_clientes()
        for c in clientes:
            if c["id"] == id:
                for k, v in dados.items():
                    if k != "id":
                        c[k] = v
                break
        salvar_clientes(clientes)

    return jsonify({"ok": True})


@app.route('/clientes/<id>', methods=['DELETE'])
def remover_cliente(id):
    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()

            cur.execute("SELECT id, nome, grupo_cota, modelo, cor, status, data_entrada, data_contemplacao, criado_em FROM clientes WHERE id = %s", (id,))
            row = cur.fetchone()
            anterior = _row_to_dict(row) if row else None

            cur.execute("DELETE FROM clientes WHERE id = %s", (id,))
            _registrar_historico(conn, id, "REMOVIDO", dados_anteriores=anterior)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[DB] Erro ao remover cliente: {e}")
            return jsonify({"erro": "Erro interno ao remover cliente"}), 500
    else:
        clientes = [c for c in carregar_clientes() if c["id"] != id]
        salvar_clientes(clientes)

    return jsonify({"ok": True})


# ─── HISTÓRICO ──────────────────────────────────────────────
@app.route('/historico', methods=['GET'])
def listar_historico():
    if not _usar_postgres:
        return jsonify([])
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, cliente_id, acao, dados_anteriores, dados_novos, data_hora FROM historico ORDER BY id DESC LIMIT 50"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        resultado = []
        for r in rows:
            resultado.append({
                "id":               r[0],
                "cliente_id":       r[1],
                "acao":             r[2],
                "dados_anteriores": json.loads(r[3]) if r[3] else None,
                "dados_novos":      json.loads(r[4]) if r[4] else None,
                "data_hora":        r[5],
            })
        return jsonify(resultado)
    except Exception as e:
        print(f"[DB] Erro ao carregar histórico: {e}")
        return jsonify({"erro": "Erro ao carregar histórico"}), 500


# ─── ESTOQUE ────────────────────────────────────────────────
@app.route('/estoque', methods=['GET'])
def get_estoque():
    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS estoque (
                    id INTEGER DEFAULT 1,
                    dados TEXT,
                    PRIMARY KEY (id)
                )
            """)
            conn.commit()
            cur.execute("SELECT dados FROM estoque WHERE id = 1")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return jsonify(json.loads(row[0]) if row else {})
        except Exception as e:
            print(f"[DB] Erro ao carregar estoque: {e}")
            return jsonify({"erro": "Erro ao carregar estoque"}), 500
    else:
        if ESTOQUE_FILE.exists():
            with open(ESTOQUE_FILE, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify({})


@app.route('/estoque', methods=['POST'])
def save_estoque():
    dados = request.get_json()
    if not dados or "estoque" not in dados:
        return jsonify({"erro": "Corpo inválido, esperado {\"estoque\": {...}}"}), 400

    estoque = dados["estoque"]

    if _usar_postgres:
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS estoque (
                    id INTEGER DEFAULT 1,
                    dados TEXT,
                    PRIMARY KEY (id)
                )
            """)
            cur.execute(
                "INSERT INTO estoque (id, dados) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados",
                (json.dumps(estoque, ensure_ascii=False),)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[DB] Erro ao salvar estoque: {e}")
            return jsonify({"erro": "Erro ao salvar estoque"}), 500
    else:
        with open(ESTOQUE_FILE, "w", encoding="utf-8") as f:
            json.dump(estoque, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
