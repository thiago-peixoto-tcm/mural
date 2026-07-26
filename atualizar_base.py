import time
import re
import math
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
MODO_TESTE = True  # Mantenha True para testar apenas 2 páginas

def extrair_html_com_playwright(page_playwright, url):
    """Navega até a URL aguardando apenas o carregamento base do HTML."""
    try:
        # Aguarda apenas o evento 'commit' ou 'domcontentloaded' para não travar
        response = page_playwright.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # Pausa para dar tempo do JavaScript da página carregar os dados
        time.sleep(5)
        
        if response:
            print(f"📡 Status HTTP retornado: {response.status}")
            
        return page_playwright.content()
    except Exception as e:
        print(f"⚠️ Alerta/Erro ao navegar em {url}: {e}")
        try:
            return page_playwright.content()
        except:
            return None

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID).sheet1

def principal():
    print("🚀 Iniciando extração adaptativa com Playwright...")
    
    lista_final = []
    
    with sync_playwright() as p:
        # Configura o Chromium com cabeçalhos reais em Português-BR
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1366, 'height': 768},
            locale="pt-BR",
            timezone_id="America/Belem",
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            }
        )
        page = context.new_page()

        # 1. Acessa a primeira página
        url_p1 = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page=1&per-page=30"
        print(f"🌐 Acessando página inicial: {url_p1}")
        html_p1 = extrair_html_com_playwright(page, url_p1)
        
        paginas_para_rodar = 2
        if html_p1:
            soup_p1 = BeautifulSoup(html_p1, 'html.parser')
            text_p1 = soup_p1.get_text()
            
            # Verifica se caiu em página de bloqueio/erro
            if "403 Forbidden" in text_p1 or "Access Denied" in text_p1:
                print("❌ SERVIDO DO TCMPA BLOQUEOU O IP DA NUVEM (Erro 403 / Access Denied).")
            
            match = re.search(r'de\s+([\d.]+)\s+itens', text_p1)
            if match:
                total_itens = int(match.group(1).replace('.', ''))
                paginas_calculadas = math.ceil(total_itens / 30)
                print(f"📊 Total de licitações encontradas: {total_itens}")
                print(f"🔄 Páginas necessárias: {paginas_calculadas}")
                if not MODO_TESTE:
                    paginas_para_rodar = paginas_calculadas

        if MODO_TESTE:
            print("▶️ MODO TESTE ATIVADO: Processando até 2 páginas.")

        # 2. Extrai os dados das páginas
        for num_pagina in range(1, paginas_para_rodar + 1):
            url = f"https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={num_pagina}&per-page=30"
            print(f"🔎 Extraindo página {num_pagina}/{paginas_para_rodar}...")
            
            html = extrair_html_com_playwright(page, url)
            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            
            # Tenta localizar por tabela ou estrutura alternativa
            tabela = soup.find('table')
            
            if tabela:
                linhas_pagina = 0
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
                            cols[0],                                                # Legisl
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
                        lista_final.append(dados_linha)
                        linhas_pagina += 1
                print(f"  └─ Página {num_pagina}: {linhas_pagina} linhas capturadas.")
            else:
                print(f"  ⚠️ Tabela não encontrada na página {num_pagina}. Conteúdo retornado pode ter sido bloqueado.")

            time.sleep(2)

        browser.close()

    # 3. Grava no Google Sheets se encontrou dados
    if lista_final:
        print(f"\n✅ SUCESSO! {len(lista_final)} linhas extraídas no total.")
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
        print("\n❌ Nenhuma linha pôde ser extraída. O acesso foi bloqueado pelo servidor do TCM-PA.")

if __name__ == "__main__":
    principal()
