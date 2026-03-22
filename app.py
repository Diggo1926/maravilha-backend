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
DATA_FILE  = BASE_DIR / "clientes.json"

UPLOAD_DIR.mkdir(exist_ok=True)


# ─── PERSISTÊNCIA ───────────────────────────────────────────
def carregar_clientes():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_clientes(clientes):
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
    resultado = {"nome": None, "grupo_cota": None, "modelo": None, "cor": None}

    cota = re.search(r'\b(\d{3,5}-\d{2,3}-\d-\d)\b', texto)
    if cota:
        resultado["grupo_cota"] = cota.group(1)

    nome = re.search(
        r'(?:Nome\s+Completo|Nome)[:\s]+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Za-záéíóúâêîôûãõàèìòùçÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{5,70}?)(?:\s{2,}|\n|CPF|Data|Tipo|Grupo)',
        texto, re.IGNORECASE
    )
    if nome:
        n = nome.group(1).strip().replace('\n', ' ')
        n = re.sub(r'\s+', ' ', n)
        if len(n.split()) >= 2:
            resultado["nome"] = n

    modelos = ['CG', 'NXR', 'BIZ', 'PCX', 'CB ', 'XRE', 'LEAD', 'POP', 'FAN', 'BROS', 'TWISTER', 'START', 'SHINE', 'TITAN', 'DREAM']
    for mod in modelos:
        m = re.search(rf'{mod}[\s\w]{{0,30}}', texto, re.IGNORECASE)
        if m:
            resultado["modelo"] = m.group(0).strip().rstrip('.,;')
            break

    cores = ['BRANCA?', 'PRETA?', 'VERMELH[AO]', 'AZUL', 'PRATA', 'CINZA', 'AMARELA?', 'VERDE', 'LARANJA', 'VINHO', 'GRAFITE']
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

    prompt = """Analise este documento de consórcio de moto e extraia os dados abaixo.
Retorne SOMENTE um JSON válido, sem texto adicional, sem markdown, sem explicações.
Formato exato:
{"nome": "NOME COMPLETO DO CLIENTE", "grupo_cota": "XXXX-XXX-X-X", "modelo": "MODELO DA MOTO", "cor": "COR DA MOTO"}

Se algum campo não for encontrado, use null.
Não inclua nada além do JSON."""

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
    txt = re.sub(r'```(?:json)?', '', txt).strip().rstrip('`').strip()
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
        "versao": "2.0"
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
        resultado = extrair_com_gemini(caminho, ext)
        print(f"[Gemini] Extração OK: {resultado}")

    except ValueError as ve:
        print(f"[Gemini] {ve} — usando fallback regex")
        metodo = "regex"
        texto = extrair_texto_pdf(str(caminho)) if ext == '.pdf' else ocr_imagem(str(caminho))
        resultado = parsear_campos_regex(texto)

    except json.JSONDecodeError as je:
        print(f"[Gemini] JSON inválido: {je} — usando fallback regex")
        metodo = "regex"
        texto = extrair_texto_pdf(str(caminho)) if ext == '.pdf' else ocr_imagem(str(caminho))
        resultado = parsear_campos_regex(texto)

    except Exception as e:
        print(f"[Gemini] Erro: {e} — usando fallback regex")
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

    resultado["_metodo"] = metodo
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

    clientes = carregar_clientes()
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
    clientes.insert(0, cliente)
    salvar_clientes(clientes)
    return jsonify(cliente), 201


@app.route('/clientes/<id>', methods=['PUT'])
def editar_cliente(id):
    dados = request.get_json()
    if not dados:
        return jsonify({"erro": "Corpo da requisição inválido"}), 400

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
    clientes = [c for c in carregar_clientes() if c["id"] != id]
    salvar_clientes(clientes)
    return jsonify({"ok": True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)