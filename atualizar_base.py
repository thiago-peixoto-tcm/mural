import math
import time
import re
import cloudscraper
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcmpa.tc.br"
URL_BASE_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

# Cria a sessão do cloudscraper para simular um navegador completo
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def extrair_pagina(pagina):
    url = URL_BASE_PAGINA.format(pagina)
    try:
        response = scraper.get(url, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            div_tabela = soup.find('div', id='w1') or soup.find('div', class_='grid-view')
            tbody = div_tabela.find('tbody') if div_tabela else soup.find('tbody')
            
            if not tbody:
                return []

            linhas = []
            for row in tbody.find_all('tr'):
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
            return linhas
        else:
            print(f"Status Code: {response.status_code} na página {pagina}")
    except Exception as e:
        print(f"Erro na página {pagina}: {e}")
    return []

# --- Restante da lógica do Google Sheets permanece igual ---
