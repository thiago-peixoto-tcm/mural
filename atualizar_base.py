import math
import time
import re
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcmpa.tc.br"
URL_BASE_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

def extrair_pagina_debug(pagina):
    url = URL_BASE_PAGINA.format(pagina)
    print(f"🌐 Conectando à URL: {url}")
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        # Usa impersonate do Chrome
        response = requests.get(url, headers=headers, impersonate="chrome120", timeout=25, verify=False)
        print(f"📡 Status Code retornado: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ O servidor respondeu com erro HTTP {response.status_code}")
            return []

        html_conteudo = response.text
        print(f"📄 Tamanho do HTML recebido: {len(html_conteudo)} caracteres")
        
        soup = BeautifulSoup(html_conteudo, 'html.parser')
        
        # Procura qualquer tabela na página
        tabelas = soup.find_all('table')
        print(f"🔍 Total de tabelas <table> encontradas no HTML: {len(tabelas)}")

        rows = soup.select('tbody tr')
        print(f"🔍 Total de linhas <tr> dentro de <tbody>: {len(rows)}")

        linhas = []
        for index, row in enumerate(rows):
            cols = row.find_all('td')
            if len(cols) >= 12:
                link_tag = cols[1].find('a')
                numero_texto = link_tag.get_text(strip=True) if link_tag else cols[1].get_text(strip=True)
                
                link_ficha = ""
                if link_tag and 'href' in link_tag.attrs:
                    href = link_tag['href']
                    link_ficha = href if href.startswith('http') else BASE_URL + href

                linhas.append([
                    cols[0].get_text(strip=True),
                    numero_texto,
                    link_ficha,
                    cols[2].get_text(strip=True),
                    cols[3].get_text(strip=True),
                    cols[4].get_text(strip=True),
                    cols[5].get_text(strip=True),
                    cols[6].get_text(strip=True),
                    cols[7].get_text(strip=True),
                    cols[8].get_text(strip=True),
                    cols[9].get_text(strip=True),
                    cols[10].get_text(strip=True),
                    cols[11].get_text(strip=True)
                ])

        print(f"✅ Linhas válidas extraídas da página {pagina}: {len(linhas)}")
        return linhas

    except Exception as e:
        print(f"💥 Exceção durante a requisição: {e}")
        return []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def executar():
    print("🚀 INICIANDO TESTE DE CONEXÃO E EXTRAÇÃO...")
    dados = extrair_pagina_debug(1)
    
    if dados:
        print(f"📤 Salvando {len(dados)} linhas no Google Sheets...")
        sheet = conectar_google_sheets()
        cabecalho = [[
            'Legislação', 'Número', 'Link Ficha', 'Modalidade', 'Tipo', 
            'Objeto', 'Data Abertura', 'Data Publicação', 'Município', 
            'Órgão', 'Situação', 'Valor Referência (R$)', 'Valor Adjudicado (R$)'
        ]]
        sheet.clear()
        sheet.update('A1', cabecalho)
        sheet.append_rows(dados)
        print("🎉 GRAVAÇÃO CONCLUÍDA COM SUCESSO!")
    else:
        print("⚠️ Nenhuma linha extraída. Verifique os logs acima para identificar a causa.")

if __name__ == "__main__":
    executar()
