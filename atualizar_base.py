import math
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcm.pa.gov.br"
URL_BASE_PAGINA = "https://www.tcm.pa.gov.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def obter_total_paginas():
    """Acessa a primeira página para descobrir o total de registros/páginas."""
    url = URL_BASE_PAGINA.format(1)
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Procura o texto de paginação (ex: "Exibindo 1-30 de 140.242 itens")
        summary_div = soup.find('div', class_='summary')
        if summary_div:
            texto = summary_div.get_text()
            # Extrai os dígitos do total de itens
            import re
            match = re.search(r'de\s+([\d\.]+)', texto)
            if match:
                total_itens = int(match.group(1).replace('.', ''))
                total_paginas = math.ceil(total_itens / 30)
                print(f"📊 Total de licitações: {total_itens:,} | Total de páginas: {total_paginas}")
                return total_paginas
    except Exception as e:
        print(f"⚠️ Não foi possível identificar o total automaticamente: {e}")
    
    # Fallback com base no seu valor informado
    return 4675

def extrair_dados_pagina(pagina):
    url = URL_BASE_PAGINA.format(pagina)
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        div_tabela = soup.find('div', id='w0')
        if not div_tabela or not div_tabela.find('table'):
            return []
            
        rows = div_tabela.find('table').find('tbody').find_all('tr')
        linhas = []
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 12:
                link_tag = cols[1].find('a')
                numero_texto = link_tag.get_text(strip=True) if link_tag else cols[1].get_text(strip=True)
                link_ficha = BASE_URL + link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""

                linhas.append([
                    cols[0].get_text(strip=True),  # Legislação
                    numero_texto,                   # Número
                    link_ficha,                     # Link Ficha
                    cols[2].get_text(strip=True),  # Modalidade
                    cols[3].get_text(strip=True),  # Tipo
                    cols[4].get_text(strip=True),  # Objeto
                    cols[5].get_text(strip=True),  # Data Abertura
                    cols[6].get_text(strip=True),  # Data Publicação
                    cols[7].get_text(strip=True),  # Município
                    cols[8].get_text(strip=True),  # Órgão
                    cols[9].get_text(strip=True),  # Situação
                    cols[10].get_text(strip=True), # Valor Referência
                    cols[11].get_text(strip=True)  # Valor Adjudicado
                ])
        return linhas
    except Exception:
        return []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

def executar():
    total_paginas = obter_total_paginas()
    sheet = conectar_google_sheets()
    
    # Cabeçalho da planilha
    cabecalho = [[
        'Legislação', 'Número', 'Link Ficha', 'Modalidade', 'Tipo', 
        'Objeto', 'Data Abertura', 'Data Publicação', 'Município', 
        'Órgão', 'Situação', 'Valor Referência (R$)', 'Valor Adjudicado (R$)'
    ]]
    
    # Limpa a planilha e insere o cabeçalho
    sheet.clear()
    sheet.update('A1', cabecalho)
    
    print("🚀 Iniciando extração e envio para o Google Sheets...")
    
    buffer_linhas = []
    
    for pag in range(1, total_paginas + 1):
        dados_pag = extrair_dados_pagina(pag)
        buffer_linhas.extend(dados_pag)
        
        # Envia para a planilha em blocos a cada 10 páginas (300 registros) para otimizar a API
        if len(buffer_linhas) >= 300 or pag == total_paginas:
            if buffer_linhas:
                sheet.append_rows(buffer_linhas)
                print(f"✅ Página {pag}/{total_paginas} processada ({len(buffer_linhas)} linhas enviadas).")
                buffer_linhas = []
        
        time.sleep(0.3)

if __name__ == "__main__":
    executar()
