import concurrent.futures
import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import json
import os
import re
import math
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAÇÕES ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_PLANILHA = "Base_Licitacoes_Principais"
CONEXOES_SIMULTANEAS = 15
MODO_TESTE = False  # Mude para True se quiser testar apenas 2 páginas
# ---------------------

URL_INICIAL = "https://www.tcmpa.tc.br/mural-de-licitacoes/"
URL_LISTAGEM = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8"
}

def obter_servicos_google():
    dados_chave_json = os.environ.get("GOOGLE_DRIVE_JSON")
    if not dados_chave_json:
        raise Exception("❌ Erro: A variável de ambiente GOOGLE_DRIVE_JSON não foi encontrada.")
    info_credenciais = json.loads(dados_chave_json)
    creds = Credentials.from_service_account_info(
        info_credenciais, 
        scopes=['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    )
    return build('drive', 'v3', credentials=creds, cache_discovery=False), build('sheets', 'v4', credentials=creds, cache_discovery=False)

def obter_id_google_sheet():
    servico_drive, _ = obter_servicos_google()
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{NOME_PLANILHA}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    resultado = servico_drive.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    arquivos = resultado.get('files', [])
    if arquivos:
        return arquivos[0]['id']
    else:
        raise Exception(f"❌ Erro Crítico: A planilha '{NOME_PLANILHA}' não foi encontrada.")

def atualizar_dados_google_sheet(spreadsheet_id, df):
    """Atualiza a planilha limpando o conteúdo e reescrevendo com fatiamento."""
    df_strings = df.fillna("").astype(str)
    linhas_totais = len(df_strings)
    
    _, servico_sheets = obter_servicos_google()
    sheet_metadata = servico_sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    aba_id = sheet_metadata['sheets'][0]['properties']['sheetId']
    
    print("🧹 Limpando conteúdo antigo da planilha...")
    servico_sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="A1:Z").execute()
    
    linhas_necessarias = max(linhas_totais + 500, 1000)
    print(f"📐 Redimensionando a aba para {linhas_necessarias} linhas e 26 colunas...")
    req_redimensionar = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": aba_id,
                        "gridProperties": {
                            "rowCount": linhas_necessarias,
                            "columnCount": 26
                        }
                    },
                    "fields": "gridProperties.rowCount,gridProperties.columnCount"
                }
            }
        ]
    }
    servico_sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=req_redimensionar).execute()

    colunas = [df_strings.columns.tolist()]
    servico_sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="A1",
        valueInputOption="RAW",
        body={'values': colunas}
    ).execute()
    
    tamanho_bloco = 5000
    print(f"📦 Enviando {linhas_totais} linhas para o Google Sheets...")
    valores_matriz = df_strings.values.tolist()
    
    for i in range(0, linhas_totais, tamanho_bloco):
        bloco = valores_matriz[i : i + tamanho_bloco]
        linha_inicio = i + 2
        linha_fim = linha_inicio + len(bloco) - 1
        intervalo = f"A{linha_inicio}:Z{linha_fim}"
        
        for t in range(1, 4):
            try:
                _, servicos_novos = obter_servicos_google()
                servicos_novos.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=intervalo,
                    valueInputOption="RAW",
                    body={'values': bloco}
                ).execute()
                print(f"   --> Bloco de linhas {linha_inicio} até {linha_fim} enviado!")
                break
            except Exception as e:
                if t == 3: raise e
                time.sleep(3)
                
    print("💾 ✅ Tabela 'Base_Licitacoes_Principais' atualizada com sucesso total!")

def obter_total_paginas():
    """Acessa o site, captura o texto 'A exibir 1-30 de X itens', extrai o X e calcula as páginas."""
    try:
        res = requests.get(URL_INICIAL, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # Procura por texto contendo "de X itens"
            texto_busca = soup.find(string=re.compile(r'de\s+[\d\.]+\s+itens', re.IGNORECASE))
            if texto_busca:
                match = re.search(r'de\s+([\d\.]+)\s+itens', texto_busca, re.IGNORECASE)
                if match:
                    total_itens_str = match.group(1).replace('.', '')
                    total_itens = int(total_itens_str)
                    total_paginas = math.ceil(total_itens / 30)
                    print(f"🎯 Total de licitações identificadas: {total_itens:,}")
                    print(f"📄 Total de páginas calculado (divido por 30): {total_paginas}")
                    return total_paginas
    except Exception as e:
        print(f"⚠️ Erro ao calcular total de páginas automaticamente: {e}")
    
    print("⚠️ Usando estimativa padrão de páginas...")
    return 4675  # Valor de contingência baseado nas ~140 mil licitações

def raspar_pagina(num_pagina):
    url = f"{URL_LISTAGEM}?page={num_pagina}&per-page=30"
    licitacoes_pag = []
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                linhas = tabela.find('tbody').find_all('tr') if tabela.find('tbody') else tabela.find_all('tr')
                for linha in linhas:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 10:
                        # Extrai o link da ficha de licitação
                        link_tag = colunas[1].find('a')
                        href = link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""
                        if href.startswith("/"):
                            link_completo = f"https://www.tcmpa.tc.br{href}"
                        elif href.startswith("http"):
                            link_completo = href
                        else:
                            link_completo = f"https://www.tcmpa.tc.br/mural-de-licitacoes/{href}"

                        licitacao = {
                            "Legislação": colunas[0].get_text(strip=True),
                            "Número": colunas[1].get_text(strip=True),
                            "Modalidade": colunas[2].get_text(strip=True),
                            "Tipo": colunas[3].get_text(strip=True),
                            "Objeto": colunas[4].get_text(strip=True),
                            "Abertura": colunas[5].get_text(strip=True),
                            "Publicação": colunas[6].get_text(strip=True),
                            "Município": colunas[7].get_text(strip=True),
                            "Órgão": colunas[8].get_text(strip=True),
                            "Situação": colunas[9].get_text(strip=True),
                            "Referência": colunas[10].get_text(strip=True) if len(colunas) > 10 else "",
                            "Adjudicado": colunas[11].get_text(strip=True) if len(colunas) > 11 else "",
                            "Link_Ficha": link_completo
                        }
                        licitacoes_pag.append(licitacao)
    except Exception:
        pass
    return licitacoes_pag

def principal():
    print("🔄 --- INICIANDO ATUALIZAÇÃO DA BASE PRINCIPAL DO TCM-PA ---")
    spreadsheet_id = obter_id_google_sheet()

    total_paginas = obter_total_paginas()
    if MODO_TESTE:
        total_paginas = 2
        print("💡 Modo de teste ativo: raspando apenas 2 páginas.")

    todas_licitacoes = []
    print(f"🚀 Varrendo {total_paginas} páginas com {CONEXOES_SIMULTANEAS} conexões em paralelo...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        futuros = {executor.submit(raspar_pagina, p): p for p in range(1, total_paginas + 1)}
        for futuro in concurrent.futures.as_completed(futuros):
            res = futuro.result()
            todas_licitacoes.extend(res)

    df = pd.DataFrame(todas_licitacoes)

    print(f"📊 Total de licitações extraídas: {len(df)}")

    if not df.empty:
        atualizar_dados_google_sheet(spreadsheet_id, df)
    else:
        print("⚠️ Nenhuma licitação foi extraída. Verifique a conexão com o portal.")

if __name__ == "__main__":
    principal()
