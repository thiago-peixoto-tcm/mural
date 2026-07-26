import math
import time
import re
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import gspread
from google.oauth2.service_account import Credentials
# USAMOS curl_cffi PARA BURLAR O BLOQUEIO DO SITE NO GITHUB ACTIONS
from curl_cffi import requests

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcmpa.tc.br"
URL_BASE_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

MAX_WORKERS = 2  # Limite seguro para não sobrecarregar

def obter_total_paginas():
    """Acessa a primeira página simulando um navegador real (Chrome 120)."""
    url = URL_BASE_PAGINA.format(1)
    try:
        response = requests.get(url, impersonate="chrome120", timeout=20)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            summary_div = soup.find('div', class_='summary')
            if summary_div:
                texto = summary_div.get_text()
                match = re.search(r'de\s+([\d\.]+)', texto)
                if match:
                    total_itens = int(match.group(1).replace('.', ''))
                    total_paginas = math.ceil(total_itens / 30)
                    print(f"📊 Total de licitações: {total_itens:,} | Páginas: {total_paginas}")
                    return total_paginas
        else:
            print(f"⚠️ Erro ao acessar primeira página. Status Code: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Exceção ao obter total de páginas: {e}")
    
    return 3

def extrair_pagina(pagina, retentativas=3):
    """Extrai as linhas da tabela de uma página simulando requisição de navegador."""
    url = URL_BASE_PAGINA.format(pagina)
    for tentativa in range(1, retentativas + 1):
        try:
            response = requests.get(url, impersonate="chrome120", timeout=20)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Busca flexível da tabela
                table = soup.find('table', class_='table') or soup.find('table')
                if not table:
                    continue

                tbody = table.find('tbody')
                if not tbody:
                    continue

                rows = tbody.find_all('tr')
                linhas = []
                
                for row in rows:
                    cols = row.find_all('td')
                    
                    # Linhas de dados válidas têm 12 colunas
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
                        
                if linhas:
                    return pagina, linhas
            else:
                print(f"⚠️ Página {pagina} retornou Status Code {response.status_code} na tentativa {tentativa}")
                
        except Exception as e:
            time.sleep(2)
            
    return pagina, []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

def executar(modo_teste=True, limite_paginas_teste=3):
    inicio_tempo = time.time()
    
    total_paginas = obter_total_paginas()
    paginas_para_rodar = min(limite_paginas_teste, total_paginas) if modo_teste else total_paginas
    
    print(f"\n🧪 Executando raspagem de {paginas_para_rodar} página(s)...")

    todas_linhas = [None] * paginas_para_rodar

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extrair_pagina, pag): pag for pag in range(1, paginas_para_rodar + 1)}
        
        concluidos = 0
        for future in as_completed(futures):
            pag, linhas = future.result()
            todas_linhas[pag - 1] = linhas
            concluidos += 1
            print(f"  └─ Página {pag}: {len(linhas)} registros extraídos.")

    dados_finais = [item for bloco in todas_linhas if bloco for item in bloco]

    print(f"\n✅ Total extraído: {len(dados_finais)} registros.")

    if not dados_finais:
        print("❌ Nenhum dado foi extraído.")
        return

    print("📤 Enviando para o Google Sheets...")

    sheet = conectar_google_sheets()
    
    cabecalho = [[
        'Legislação', 'Número', 'Link Ficha', 'Modalidade', 'Tipo', 
        'Objeto', 'Data Abertura', 'Data Publicação', 'Município', 
        'Órgão', 'Situação', 'Valor Referência (R$)', 'Valor Adjudicado (R$)'
    ]]
    
    sheet.clear()
    sheet.update('A1', cabecalho)
    sheet.append_rows(dados_finais)
    
    print(f"🎉 Concluído com sucesso em {time.time() - inicio_tempo:.2f}s!")

if __name__ == "__main__":
    executar(modo_teste=True)
