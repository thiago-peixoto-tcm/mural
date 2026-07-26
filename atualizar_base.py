import math
import time
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
BASE_URL = "https://www.tcmpa.tc.br"
URL_BASE_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=30"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Número de requisições simultâneas
MAX_WORKERS = 15 

def obter_total_paginas():
    """Acessa a primeira página para descobrir o total de registros e calcula o total de páginas."""
    url = URL_BASE_PAGINA.format(1)
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        summary_div = soup.find('div', class_='summary')
        if summary_div:
            texto = summary_div.get_text()
            match = re.search(r'de\s+([\d\.]+)', texto)
            if match:
                total_itens = int(match.group(1).replace('.', ''))
                total_paginas = math.ceil(total_itens / 30)
                print(f"📊 Total de licitações identificadas: {total_itens:,} | Páginas: {total_paginas}")
                return total_paginas
    except Exception as e:
        print(f"⚠️ Erro ao calcular total de páginas: {e}")
    
    return 4677

def extrair_pagina(pagina, retentativas=3):
    """Lê uma única página com suporte a retentativas."""
    url = URL_BASE_PAGINA.format(pagina)
    for tentativa in range(1, retentativas + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=12)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                div_tabela = soup.find('div', id='w0')
                if not div_tabela or not div_tabela.find('table'):
                    return pagina, []
                    
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
                return pagina, linhas
        except Exception:
            time.sleep(2)
            
    return pagina, []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

def executar():
    inicio_tempo = time.time()
    total_paginas = obter_total_paginas()
    
    print(f"🚀 Baixando {total_paginas} páginas em paralelo (usando {MAX_WORKERS} conexões)...")
    
    todas_linhas = [None] * total_paginas
    
    # Baixa todas as páginas em blocos paralelos
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extrair_pagina, pag): pag for pag in range(1, total_paginas + 1)}
        
        concluidos = 0
        for future in as_completed(futures):
            pag, linhas = future.result()
            todas_linhas[pag - 1] = linhas
            concluidos += 1
            if concluidos % 100 == 0 or concluidos == total_paginas:
                print(f"⚡ Progresso da raspagem: {concluidos}/{total_paginas} páginas baixadas...")

    # Achata a lista preservando a ordem original
    dados_finais = []
    for bloco in todas_linhas:
        if bloco:
            dados_finais.extend(bloco)

    print(f"✅ Raspagem concluída! Total de {len(dados_finais):,} licitações extraídas.")
    print("📤 Enviando para o Google Sheets...")

    sheet = conectar_google_sheets()
    
    cabecalho = [[
        'Legislação', 'Número', 'Link Ficha', 'Modalidade', 'Tipo', 
        'Objeto', 'Data Abertura', 'Data Publicação', 'Município', 
        'Órgão', 'Situação', 'Valor Referência (R$)', 'Valor Adjudicado (R$)'
    ]]
    
    # Sobrescreve a planilha mantendo a ordem atualizada
    sheet.clear()
    sheet.update('A1', cabecalho)
    
    # Envia para a API do Google em lotes de 2.000 linhas
    TAMANHO_LOTE = 2000
    for i in range(0, len(dados_finais), TAMANHO_LOTE):
        lote = dados_finais[i:i + TAMANHO_LOTE]
        sheet.append_rows(lote)
        print(f"📊 Lote {i//TAMANHO_LOTE + 1} enviado ({len(lote)} linhas)...")
        time.sleep(1)

    tempo_decorrido = (time.time() - inicio_tempo) / 60
    print(f"🎉 Processo concluído com sucesso em {tempo_decorrido:.2f} minutos!")

if __name__ == "__main__":
    executar()
