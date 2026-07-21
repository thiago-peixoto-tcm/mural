import concurrent.futures
import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import json
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAÇÕES ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_PLANILHA = "Base_Licitacoes_Principais"
ANO_ALVO = 2026
CONEXOES_SIMULTANEAS = 10
MODO_TESTE = False
# ---------------------

URL_BASE = "https://spe.tcm.pa.gov.br/consultas/licitacoes"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    """Garante expansão das linhas no Google Sheets e grava dados fatiados sem estourar limites."""
    df_strings = df.fillna("").astype(str)
    linhas_totais = len(df_strings)
    
    _, servico_sheets = obter_servicos_google()
    
    # 1. Pega o ID interno da primeira aba (sheetId)
    sheet_metadata = servico_sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    aba_id = sheet_metadata['sheets'][0]['properties']['sheetId']
    
    # 2. Limpa o conteúdo antigo
    print("🧹 Limpando conteúdo antigo da planilha...")
    servico_sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="A1:Z").execute()
    
    # 3. EXPANSÃO DO GRID: Redimensiona a aba para ter linhas suficientes (+ 500 de folga)
    linhas_necessarias = linhas_totais + 500
    print(f"📐 Redimensionando a aba no Google Sheets para comportar {linhas_necessarias} linhas...")
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

    # 4. Escreve os Cabeçalhos na primeira linha
    colunas = [df_strings.columns.tolist()]
    servico_sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="A1",
        valueInputOption="RAW",
        body={'values': colunas}
    ).execute()
    
    # 5. Envia o conteúdo em blocos de 5.000 linhas
    tamanho_bloco = 5000
    print(f"📦 Enviando {linhas_totais} linhas para o Google Sheets em fatias de {tamanho_bloco}...")
    
    valores_matriz = df_strings.values.tolist()
    
    for i in range(0, linhas_totais, tamanho_bloco):
        bloco = valores_matriz[i : i + tamanho_bloco]
        linha_inicio = i + 2  # +2 por conta do cabeçalho
        linha_fim = linha_inicio + len(bloco) - 1
        intervalo = f"A{linha_inicio}:Z{linha_fim}"
        
        tentativas = 3
        for t in range(1, tentativas + 1):
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
                print(f"⚠️ Erro ao enviar bloco {linha_inicio}-{linha_fim} (tentativa {t}/{tentativas}): {e}")
                if t == tentativas: raise e
                time.sleep(3)
                
    print("💾 ✅ Tabela 'Base_Licitacoes_Principais' atualizada no Google Sheets com sucesso total!")

def raspar_pagina(num_pagina):
    url = f"{URL_BASE}?page={num_pagina}"
    licitacoes_pag = []
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                linhas = tabela.find('tbody').find_all('tr') if tabela.find('tbody') else tabela.find_all('tr')
                for linha in linhas:
                    colunas = linha.find_all('td')
                    if len(colunas) >= 10:
                        link_tag = colunas[1].find('a')
                        href = link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""
                        link_completo = f"https://spe.tcm.pa.gov.br{href}" if href.startswith("/") else href

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
                            # Captura segura das duas novas colunas
                            "Referência": colunas[10].get_text(strip=True) if len(colunas) > 10 else "",
                            "Adjudicado": colunas[11].get_text(strip=True) if len(colunas) > 11 else "",
                            "Link_Ficha": link_completo
                        }
                        licitacoes_pag.append(licitacao)
    except Exception: pass
    return licitacoes_pag

def principal():
    print("🔄 --- INICIANDO ATUALIZAÇÃO DA BASE PRINCIPAL ---")
    
    spreadsheet_id = obter_id_google_sheet()

    print("🔎 Descobrindo total de páginas no Mural...")
    res = requests.get(URL_BASE, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    total_paginas = 1
    paginacao = soup.find('ul', class_='pagination')
    if paginacao:
        links = paginacao.find_all('a')
        nums = [int(l.get_text()) for l in links if l.get_text().isdigit()]
        if nums: total_paginas = max(nums)
        
    print(f"📄 Total de páginas no site: {total_paginas}")

    limite_varredura = min(total_paginas, 300)
    if MODO_TESTE:
        limite_varredura = 2

    todas_licitacoes = []
    print(f"🚀 Raspando {limite_varredura} páginas com {CONEXOES_SIMULTANEAS} conexões...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        futuros = {executor.submit(raspar_pagina, p): p for p in range(1, limite_varredura + 1)}
        for futuro in concurrent.futures.as_completed(futuros):
            res = futuro.result()
            todas_licitacoes.extend(res)

    df = pd.DataFrame(todas_licitacoes)

    if not df.empty:
        mask_2026 = (
            df['Número'].str.contains(str(ANO_ALVO), na=False) |
            df['Publicação'].str.endswith(str(ANO_ALVO), na=False) |
            df['Abertura'].str.endswith(str(ANO_ALVO), na=False)
        )
        df = df[mask_2026]

    print(f"📊 Licitações de {ANO_ALVO} filtradas: {len(df)}")

    if not df.empty:
        atualizar_dados_google_sheet(spreadsheet_id, df)
    else:
        print("⚠️ Nenhuma licitação encontrada para o filtro especificado.")

if __name__ == "__main__":
    principal()
