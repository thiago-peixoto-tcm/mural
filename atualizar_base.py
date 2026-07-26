import math
import time
import re
import sys
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# Tenta importar o cloudscraper e avisa no log caso falhe
try:
    import cloudscraper
    print("✅ Biblioteca 'cloudscraper' importada com sucesso!")
except ImportError as e:
    print(f"❌ Erro ao importar cloudscraper: {e}")
    sys.exit(1)

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcmpa.tc.br"
URL_BASE_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

# Instancia o scraper com emulação de navegador Chrome
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def extrair_pagina(pagina):
    url = URL_BASE_PAGINA.format(pagina)
    print(f"🌐 Acessando página {pagina}: {url}")
    try:
        response = scraper.get(url, timeout=30)
        print(f"📡 Status da resposta na página {pagina}: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Busca flexível por tabelas
            tabela = soup.find('table', class_='table') or soup.find('table')
            if not tabela:
                print(f"⚠️ Nenhuma tabela encontrada na página {pagina}.")
                return []

            tbody = tabela.find('tbody')
            if not tbody:
                return []

            rows = tbody.find_all('tr')
            linhas = []
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 12:
                    link_tag = cols[1].find('a')
                    numero_texto = link_tag.get_text(strip=True) if link_tag else cols[1].get_text(strip=True)
                    
                    link_ficha = ""
                    if link_tag and 'href' in link_tag.attrs:
                        href = link_tag['href']
                        link_ficha = href if href.startswith('http') else BASE_URL + href

                    linhas.append([
                        cols[0].get_text(strip=True),   # Legislação
                        numero_texto,                  # Número
                        link_ficha,                    # Link Ficha
                        cols[2].get_text(strip=True),   # Modalidade
                        cols[3].get_text(strip=True),   # Tipo
                        cols[4].get_text(strip=True),   # Objeto
                        cols[5].get_text(strip=True),   # Data Abertura
                        cols[6].get_text(strip=True),   # Data Publicação
                        cols[7].get_text(strip=True),   # Município
                        cols[8].get_text(strip=True),   # Órgão
                        cols[9].get_text(strip=True),   # Situação
                        cols[10].get_text(strip=True),  # Valor Referência
                        cols[11].get_text(strip=True)   # Valor Adjudicado
                    ])
                    
            print(f"✅ Página {pagina}: {len(linhas)} linhas extraídas.")
            return linhas
        else:
            print(f"❌ Erro na página {pagina}: HTTP {response.status_code}")
    except Exception as e:
        print(f"💥 Exceção na página {pagina}: {e}")
        
    return []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def executar():
    print("🚀 INICIANDO PROCESSAMENTO...")
    
    # Teste inicial na página 1
    dados = extrair_pagina(1)
    
    if dados:
        print(f"\n📤 Conectando ao Google Sheets para enviar {len(dados)} registros...")
        sheet = conectar_google_sheets()
        cabecalho = [[
            'Legislação', 'Número', 'Link Ficha', 'Modalidade', 'Tipo', 
            'Objeto', 'Data Abertura', 'Data Publicação', 'Município', 
            'Órgão', 'Situação', 'Valor Referência (R$)', 'Valor Adjudicado (R$)'
        ]]
        
        sheet.clear()
        sheet.update('A1', cabecalho)
        sheet.append_rows(dados)
        print("🎉 GRAVAÇÃO NO GOOGLE SHEETS FINALIZADA COM SUCESSO!")
    else:
        print("⚠️ Nenhuma linha extraída. Verifique os status acima.")

if __name__ == "__main__":
    executar()
