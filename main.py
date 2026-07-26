import os
import math
import re
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# CONFIGURAÇÕES E PARÂMETROS
# ==========================================
MODO_TESTE = True
MAX_PAGINAS_TESTE = 3

BASE_URL = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={page}&per-page=30"
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_ARQUIVO_CSV = "Base_Licitacoes_Principais.csv"

SCOPES = ['https://www.googleapis.com/auth/drive']

def obter_credenciais_google():
    json_str = os.getenv('GOOGLE_DRIVE_JSON')
    if not json_str:
        raise ValueError("A variável de ambiente GOOGLE_DRIVE_JSON não foi configurada nas Secrets do GitHub.")
    
    info = json.loads(json_str)
    return Credentials.from_service_account_info(info, scopes=SCOPES)

def criar_sessao_http():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    })
    return session

def extrair_total_registros(soup):
    summary_div = soup.find('div', class_='summary')
    if summary_div:
        texto = summary_div.get_text()
        match = re.search(r'de\s+<b>?([\d\.]+)</b?>', summary_div.decode_contents()) or re.search(r'de\s+([\d\.]+)\s+itens', texto)
        if match:
            return int(match.group(1).replace('.', ''))
    
    match_bruto = re.search(r'de\s*<b>?\s*([\d\.]+)\s*<\/b>?\s*itens', str(soup), re.IGNORECASE)
    if match_bruto:
        return int(match_bruto.group(1).replace('.', ''))

    paginacao = soup.find('ul', class_='pagination')
    if paginacao:
        links = paginacao.find_all('a')
        paginas = [int(l.get_text()) for l in links if l.get_text().isdigit()]
        if paginas:
            max_p = max(paginas)
            return max_p * 30

    return 30 * MAX_PAGINAS_TESTE if MODO_TESTE else 3000

def raspar_pagina(soup):
    dados = []
    tbody = soup.find('tbody')
    if not tbody:
        return dados

    rows = tbody.find_all('tr')
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 12:
            continue
        
        legislacao = cols[0].get_text(strip=True)
        
        col_numero = cols[1]
        numero = col_numero.get_text(strip=True)
        id_licitacao = ""
        link_tag = col_numero.find('a')
        if link_tag and 'href' in link_tag.attrs:
            href = link_tag['href']
            match_id = re.search(r'/ficha/(\d+)', href)
            if match_id:
                id_licitacao = match_id.group(1)

        modalidade = cols[2].get_text(strip=True)
        tipo = cols[3].get_text(strip=True)
        objeto = cols[4].get_text(strip=True)
        abertura = cols[5].get_text(strip=True)
        publicacao = cols[6].get_text(strip=True)
        municipio = cols[7].get_text(strip=True)
        orgao = cols[8].get_text(strip=True)
        situacao = cols[9].get_text(strip=True)
        referencia = cols[10].get_text(strip=True)
        adjudicado = cols[11].get_text(strip=True)

        dados.append({
            'Legislação': legislacao,
            'Número': numero,
            'Modalidade': modalidade,
            'Tipo': tipo,
            'Objeto': objeto,
            'Abertura': abertura,
            'Publicação': publicacao,
            'Município': municipio,
            'Órgão': orgao,
            'Situação': situacao,
            'Referência': referencia,
            'Adjudicado': adjudicado,
            'ID': id_licitacao
        })

    return dados

def upload_para_google_drive(caminho_arquivo_local, nome_arquivo_destino, id_pasta):
    """
    Envia/Atualiza o CSV no Google Drive contornando a restrição de quota da Service Account.
    """
    creds = obter_credenciais_google()
    service = build('drive', 'v3', credentials=creds)

    # Busca se o arquivo já existe na pasta
    query = f"'{id_pasta}' in parents and name = '{nome_arquivo_destino}' and trashed = false"
    response = service.files().list(
        q=query, 
        fields='files(id, name)',
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = response.get('files', [])

    media = MediaFileUpload(caminho_arquivo_local, mimetype='text/csv', resumable=True)

    if files:
        file_id = files[0]['id']
        print(f"Substituindo arquivo existente no Google Drive (ID: {file_id})...")
        service.files().update(
            fileId=file_id, 
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print("Arquivo sobrescrito com sucesso!")
    else:
        print("Criando arquivo na pasta compartilhada do Google Drive...")
        file_metadata = {
            'name': nome_arquivo_destino, 
            'parents': [id_pasta]
        }
        service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        print("Arquivo criado e salvo com sucesso!")

def main():
    session = criar_sessao_http()
    url_inicial = BASE_URL.format(page=1)
    
    print(f"Acessando página inicial: {url_inicial}")
    resp = session.get(url_inicial, timeout=30)
    soup = BeautifulSoup(resp.content, 'html.parser')

    total_registros = extrair_total_registros(soup)
    total_paginas = math.ceil(total_registros / 30)
    print(f"Total de registros estimados: {total_registros:,}")
    print(f"Total de páginas calculadas: {total_paginas:,}")

    if MODO_TESTE:
        paginas_para_raspar = min(MAX_PAGINAS_TESTE, total_paginas)
        print(f"*** MODO TESTE ATIVADO: Raspando {paginas_para_raspar} página(s) ***")
    else:
        paginas_para_raspar = total_paginas
        print(f"*** MODO COMPLETO ATIVADO: Raspando {paginas_para_raspar} páginas ***")

    todos_dados = []

    for pagina in range(1, paginas_para_raspar + 1):
        print(f"Raspando página {pagina} de {paginas_para_raspar}...")
        if pagina == 1:
            dados_pag = raspar_pagina(soup)
        else:
            url_pag = BASE_URL.format(page=pagina)
            res_pag = session.get(url_pag, timeout=30)
            soup_pag = BeautifulSoup(res_pag.content, 'html.parser')
            dados_pag = raspar_pagina(soup_pag)

        todos_dados.extend(dados_pag)

    print(f"Total de registros extraídos: {len(todos_dados)}")

    df = pd.DataFrame(todos_dados)
    df.to_csv(NOME_ARQUIVO_CSV, index=False, encoding='utf-8-sig', sep=';')
    print(f"Arquivo CSV '{NOME_ARQUIVO_CSV}' gerado localmente.")

    print("Enviando para o Google Drive...")
    upload_para_google_drive(NOME_ARQUIVO_CSV, NOME_ARQUIVO_CSV, ID_PASTA_GOOGLE_DRIVE)
    print("Processo concluído!")

if __name__ == '__main__':
    main()
