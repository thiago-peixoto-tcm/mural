import concurrent.futures
import cloudscraper
import pandas as pd
from bs4 import BeautifulSoup
import math
import time
import re
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
CONEXOES_SIMULTANEAS = 3

# MODO TESTE: True roda só 2 páginas para testar rápido.
MODO_TESTE = True

# Cria um scraper que simula navegador de computador
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def descobrir_total_paginas():
    url = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page=1&per-page=30"
    
    for tentativa in range(3):
        try:
            response = scraper.get(url, timeout=20)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                texto_paginacao = soup.get_text()
                
                match = re.search(r'de\s+([\d.]+)\s+itens', texto_paginacao)
                if match:
                    total_itens = int(match.group(1).replace('.', ''))
                    paginas_calculadas = math.ceil(total_itens / 30)
                    print(f"📊 Sistema Identificou: {total_itens} licitações no total.")
                    print(f"🔄 Total necessário: {paginas_calculadas} páginas.")
                    return paginas_calculadas
        except Exception as e:
            if tentativa < 2:
                print(f"⚠️ Servidor recusou a conexão inicial (Tentativa {tentativa+1}/3). Aguardando...")
                time.sleep(2)
            else:
                print(f"❌ Erro ao calcular páginas: {e}")
    
    print("📋 Usando valor padrão de segurança: 10 páginas.")
    return 10

def baixar_pagina(page):
    url = f"https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={page}&per-page=30"
    
    for tentativa in range(3):
        try:
            response = scraper.get(url, timeout=20)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                tabela = soup.find('table')
                if not tabela: 
                    return []
                    
                linhas_da_pagina = []
                for row in tabela.find_all('tr'):
                    if row.find('th') or row.find('select') or row.find('input'): 
                        continue
                        
                    tds = row.find_all('td')
                    if tds and len(tds) >= 10:
                        cols = [td.get_text(strip=True) for td in tds]
                        
                        td_numero = tds[1]
                        tag_a = td_numero.find('a')
                        link_ficha = ""
                        if tag_a and tag_a.has_attr('href'):
                            link_ficha = tag_a['href']
                            if not link_ficha.startswith('http'):
                                link_ficha = "https://www.tcmpa.tc.br" + link_ficha
                        
                        dados_linha = [
                            cols[0],                                                # legisl
                            cols[1],                                                # Número LIC
                            link_ficha,                                             # Link_Ficha
                            cols[2],                                                # Modalidade
                            cols[3],                                                # Tipo
                            cols[4],                                                # Objeto
                            cols[5],                                                # Abertura
                            cols[6],                                                # Publicação
                            cols[7],                                                # Município
                            cols[8],                                                # UG
                            cols[9],                                                # Situação
                            cols[10] if len(cols) > 10 else "0,00",                 # VLR Referência
                            cols[11] if len(cols) > 11 else "0,00"                  # VLR Adjudicado
                        ]
                        linhas_da_pagina.append(dados_linha)
                return linhas_da_pagina
        except Exception:
            time.sleep(1.5)
    return []

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def principal():
    print("🚀 Iniciando a extração do TCM-PA via GitHub Actions...")
    
    total_paginas_dinamico = descobrir_total_paginas()
    paginas_para_rodar = 2 if MODO_TESTE else total_paginas_dinamico
    
    if MODO_TESTE:
        print("▶️ MODO TESTE ATIVADO: Rodando apenas 2 páginas.")
        
    lista_final = []
    paginas_processadas = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        futuros = {executor.submit(baixar_pagina, p): p for p in range(1, paginas_para_rodar + 1)}
        for futuro in concurrent.futures.as_completed(futuros):
            paginas_processadas += 1
            resultado = futuro.result()
            if resultado: 
                lista_final.extend(resultado)
            
            if paginas_processadas % 5 == 0 or paginas_processadas == paginas_para_rodar:
                print(f"  └─ Progresso: {paginas_processadas}/{paginas_para_rodar} páginas concluídas...")

    if lista_final:
        print(f"\n✅ SUCESSO! {len(lista_final)} linhas extraídas.")
        print("📤 Enviando para o Google Sheets...")
        
        sheet = conectar_google_sheets()
        cabecalho = [[
            'Legislação', 'Número LIC', 'Link Ficha', 'Modalidade', 'Tipo', 
            'Objeto', 'Abertura', 'Publicação', 'Município', 
            'UG', 'Situação', 'VLR Referência', 'VLR Adjudicado'
        ]]
        
        sheet.clear()
        sheet.update('A1', cabecalho)
        sheet.append_rows(lista_final)
        print("🎉 GRAVAÇÃO CONCLUÍDA COM SUCESSO NO GOOGLE SHEETS!")
    else:
        print("\n❌ Nenhuma linha pôde ser extraída do site.")

if __name__ == "__main__":
    principal()
