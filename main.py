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
ID_ARQUIVO_EXISTENTE = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8I7EQer_GEs"
NOME_ARQUIVO_CSV = "Base_Licitacoes_Principais.csv"

SCOPES = ['https://www.googleapis.com/auth/drive']

def obter_credenciais_google():
    json_str = os.getenv('GOOGLE_DRIVE_JSON')
    if not json_str:
        raise ValueError("A variável GOOGLE_DRIVE_JSON não foi encontrada nas Secrets.")
    info = json.loads(json_str)
    return Credentials.from_service_account_info(info, scopes=SCOPES)

def criar_sessao_http():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    })
    return session

def extrair_total_registros(soup):
    summary_div = soup.find('div', class_='summary')
    if summary_div:
        texto = summary_div.get_text()
        match = re.search(r'de\s+<b>?([\d\.]+)</b?>', summary_div.decode_contents()) or re.search(r'de\s+([\d\.]+)', texto)
        if match:
            return int(match.group(1).replace('.', ''))

    return 30 * MAX_PAGINAS_TESTE if MODO_TESTE else 3000

def raspar_pagina(soup):
    dados = []
    
    # Busca a tabela por container comum do framework ou por tag table direta
    container = soup.find('div', id='w0') or soup.find('div', class_='grid-view')
    tabela = container.find('table') if container else soup.find('table')
    
    if not tabela:
        return dados

    # Pega todas as linhas do corpo da tabela ou da tabela inteira
    tbody = tabela.find('tbody')
    rows = tbody.find_all('tr') if tbody else tabela.find_all('tr')

    for row in rows:
        cols = row.find_all('td')
        # Ignora cabeçalhos ou linhas sem colunas suficientes
        if len(cols) < 5:
            continue
        
        legislacao = cols[0].get_text(strip=True) if len(cols) > 0 else ""
        
        col_numero = cols[1] if len(cols) > 1 else None
        numero = col_numero.get_text(strip=True) if col_numero else ""
        
        id_licitacao = ""
        if col_numero:
            link_tag = col_numero.find('a')
            if link_tag and 'href' in link_tag.attrs:
                match_id = re.search(r'/ficha/(\d+)', link_tag['href'])
                if match_id:
                    id_licitacao = match_id.group(1)

        modalidade = cols[2].get_text(strip=True) if len(cols) > 2 else ""
        tipo = cols[3].get_text(strip=True) if len(cols) > 3 else ""
        objeto = cols[4].get_text(strip=True) if len(cols) > 4 else ""
        abertura = cols[5].get_text(strip=True) if len(cols) > 5 else ""
        publicacao = cols[6].get_text(strip=True) if len(cols) > 6 else ""
        municipio = cols[7].get_text(strip=True) if len(cols) > 7 else ""
        orgao = cols[8].get_text(strip=True) if len(cols) > 8 else ""
        situacao = cols[9].get_text(strip=True) if len(cols) > 9 else ""
        referencia = cols[10].get_text(strip=True) if len(cols) > 10 else ""
        adjudicado = cols[11].get_text(strip=True) if len(cols) > 11 else ""

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

def upload_para_google_drive(caminho_arquivo_local, file_id):
    creds = obter_credenciais_google()
    service = build('drive', 'v3', credentials=creds)

    media = MediaFileUpload(
        caminho_arquivo_local, 
        mimetype='text/csv', 
        resumable=True
    )

    print(f"Atualizando diretamente a Planilha do Google (ID: {file_id})...")
    service.files().update(
        fileId=file_id, 
        media_body=media,
        supportsAllDrives=True
    ).execute()
    print("Planilha atualizada com sucesso no Google Drive!")

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

    paginas_para_raspar = min(MAX_PAGINAS_TESTE, total_paginas) if MODO_TESTE else total_paginas
    print(f"*** Raspando {paginas_para_raspar} página(s) ***")

    todos_dados = []

    for pagina in range(1, paginas_para_raspar + 1):
        print(f"Raspando página {pagina} de {paginas_para_raspar}...")
        url_pag = BASE_URL.format(page=pagina)
        res_pag = session.get(url_pag, timeout=30)
        soup_pag = BeautifulSoup(res_pag.content, 'html.parser')
        
        dados_pag = raspar_pagina(soup_pag)
        todos_dados.extend(dados_pag)

    print(f"Total de registros extraídos: {len(todos_dados)}")

    if len(todos_dados) > 0:
        df = pd.DataFrame(todos_dados)
        df.to_csv(NOME_ARQUIVO_CSV, index=False, encoding='utf-8-sig', sep=';')
        print(f"Arquivo CSV '{NOME_ARQUIVO_CSV}' gerado localmente.")

        print("Enviando atualização para a Planilha do Google Drive...")
        upload_para_google_drive(NOME_ARQUIVO_CSV, ID_ARQUIVO_EXISTENTE)
        print("Processo concluído com sucesso!")
    else:
        print("Nenhum dado foi extraído. Verifique o acesso ao site do TCM-PA.")

if __name__ == '__main__':
    main()
