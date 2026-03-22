import os
import re
import json
import uuid
from datetime import datetime
from pathlib import Path
import google.generativeai as genai
import base64   
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pdfplumber
from PIL import Image
import pytesseract
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

app = Flask(__name__)
CORS(app)

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "exports"
DATA_FILE  = BASE_DIR / "clientes.json"

UPLOAD_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)


def carregar_clientes():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salvar_clientes(clientes):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(clientes, f, ensure_ascii=False, indent=2)


def extrair_texto_pdf(caminho):
    texto = ""
    with pdfplumber.open(caminho) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
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
        print(f"[OCR] Erro: {e}")
        return ""


def ocr_imagem(caminho):
    img = Image.open(caminho)
    return pytesseract.image_to_string(img, lang="por")


def parsear_campos(texto):
    resultado = {"nome": None, "grupo_cota": None, "modelo": None, "cor": None}

    cota = re.search(r'\b(\d{4}-\d{2,3}-\d-\d)\b', texto)
    if cota:
        resultado["grupo_cota"] = cota.group(1)

    nome = re.search(
        r'Nome\s+Completo[:\s]+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{5,70}?)(?:\s{2,}|\n|CPF|Data|Tipo)',
        texto, re.IGNORECASE
    )
    if nome:
        n = nome.group(1).strip().replace('\n', ' ').replace('  ', ' ')
        if len(n.split()) >= 2:
            resultado["nome"] = n

    modelo_patterns = [
        r'(?:CG|NXR|BIZ|PCX|CB|XRE|LEAD|POP|FAN|BROS|TWISTER|AFRICA\s*TWIN|START|SHINE)\s*[\d\w\s]{0,20}',
        r'Modelo\s*[\n\s]+([A-Z0-9][A-Z0-9\s]{3,25})',
    ]
    for pat in modelo_patterns:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            resultado["modelo"] = m.group(0).strip().replace('\n', ' ')
            break

    cores = ['BRANCA?','PRETA?','VERMELH[AO]','AZUL','PRATA','CINZA','AMARELA?','VERDE','LARANJA','VINHO','GRAFITE']
    cor = re.search(r'\b(' + '|'.join(cores) + r')\b', texto, re.IGNORECASE)
    if cor:
        resultado["cor"] = cor.group(1).upper()

    return resultado


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


@app.route('/extrair', methods=['POST'])
def extrair():
    if 'arquivo' not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    arquivo = request.files['arquivo']
    ext = Path(arquivo.filename).suffix.lower()
    nome_tmp = f"{uuid.uuid4()}{ext}"
    caminho = UPLOAD_DIR / nome_tmp
    arquivo.save(str(caminho))

    try:
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-1.5-flash')

        with open(caminho, 'rb') as f:
            dados_arquivo = f.read()

        mime = 'application/pdf' if ext == '.pdf' else f'image/{ext[1:]}'

        resposta = model.generate_content([
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(dados_arquivo).decode()
                }
            },
            """Extraia os dados deste documento de consórcio Honda e retorne APENAS JSON válido sem markdown:
{"nome": "nome completo", "grupo_cota": "código no formato NNNN-NNN-N-N", "modelo": "modelo da moto", "cor": "cor da moto"}"""
        ])

        txt = resposta.text.strip().replace('```json','').replace('```','').strip()
        return jsonify(json.loads(txt))

    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if caminho.exists():
            caminho.unlink()
@app.route('/clientes', methods=['GET'])
def listar_clientes():
    return jsonify(carregar_clientes())


@app.route('/clientes', methods=['POST'])
def adicionar_cliente():
    dados = request.get_json()
    clientes = carregar_clientes()
    cliente = {
        "id": str(uuid.uuid4()),
        "nome": dados.get("nome", "—"),
        "grupo_cota": dados.get("grupo_cota", "—"),
        "modelo": dados.get("modelo", "—"),
        "cor": dados.get("cor", "—"),
        "status": dados.get("status", "Aguardando Contemplação"),
        "data_entrada": dados.get("data_entrada", "—"),
        "data_contemplacao": dados.get("data_contemplacao", "—"),
        "criado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    clientes.insert(0, cliente)
    salvar_clientes(clientes)
    return jsonify(cliente), 201


@app.route('/clientes/<id>', methods=['DELETE'])
def remover_cliente(id):
    clientes = [c for c in carregar_clientes() if c["id"] != id]
    salvar_clientes(clientes)
    return jsonify({"ok": True})


@app.route('/clientes/<id>', methods=['PUT'])
def editar_cliente(id):
    dados = request.get_json()
    clientes = carregar_clientes()
    for c in clientes:
        if c["id"] == id:
            c.update({k: v for k, v in dados.items() if k != "id"})
            break
    salvar_clientes(clientes)
    return jsonify({"ok": True})


if __name__ == '__main__':
    app.run(debug=True, port=5000)