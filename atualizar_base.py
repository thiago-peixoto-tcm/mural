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
CONEXOES_SIMULTANEAS = 5
MODO_TESTE = False  # Altere para True se quiser testar apenas 2 páginas
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

def garantir_ou_obter_primeira_aba(spreadsheet_id, nome_aba_desejado):
    _, servico_sheets = obter_servicos_google()
    sheet_metadata = servico_sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = sheet_metadata.get('sheets', [])
    primeira_aba = sheets[0]['properties']
    
    if primeira_aba['title'] != nome_aba_desejado:
        body = {'requests': [{'updateSheetProperties': {'properties': {'sheetId': primeira_aba['sheetId'], 'title': nome_aba_desejado}, 'fields': 'title'}}]}
        servico_sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return primeira_aba['sheetId']

def ler_aba_google_sheet(spreadsheet_id, nome_aba):
    _, servico_sheets = obter_servicos_google()
    try:
        resultado = servico_sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{nome_aba}'!A1:ZZ").execute()
        valores = resultado.get('values', [])
        if not valores:
            return pd.DataFrame()
        return pd.DataFrame(valores[1:], columns=valores[0])
    except Exception:
        return pd.DataFrame()

def atualizar_aba_google_sheet(spreadsheet_id, df_dados, nome_aba, sheet_id):
    df_strings = df_dados.fillna("").astype(str)
    linhas_totais = len(df_strings)
    if linhas_totais == 0:
        return

    _, servico_sheets = obter_servicos_google()
    
    linhas_necessarias = max(linhas_totais + 500, 1000)
    print(f"📐 Redimensionando aba '{nome_aba}' para {linhas_necessarias} linhas...")
    req_redimensionar = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "rowCount": linhas_necessarias,
                            "columnCount": 20
                        }
                    },
                    "fields": "gridProperties.rowCount,gridProperties.columnCount"
                }
            }
        ]
    }
    servico_sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=req_redimensionar).execute()

    valores_matriz = [df_strings.columns.tolist()] + df_strings.values.tolist()
    tamanho_bloco = 5000
    print(f"📦 Enviando {linhas_totais} linhas em fatias...")
    
    for i in range(0, len(valores_matriz), tamanho_bloco):
        bloco = valores_matriz[i : i + tamanho_bloco]
        linha_inicio = i + 1
        linha_fim = linha_inicio + len(bloco) - 1
        intervalo = f"'{nome_aba}'!A{linha_inicio}:ZZ{linha_fim}"
        
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
                print(f"   --> Bloco {linha_inicio} a {linha_fim} gravado com sucesso!")
                break
            except Exception as e:
                if t == tentativas: raise e
                time.sleep(3)

def raspar_pagina(num_pagina):
    url = f"{URL_BASE}?page={num_pagina}"
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
                    # Tabela principal tem 11 colunas
                    if len(colunas) >= 11:
                        # Extração do Link do Número da Licitação
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
                            "Referência": colunas[10].get_text(strip=True),  # <-- Nova coluna
                            "Adjudicado": colunas[11].get_text(strip=True) if len(colunas) > 11 else "", # <-- Nova coluna
                            "Link_Ficha": link_completo
                        }
                        licitacoes_pag.append(licitacao)
    except Exception: pass
    return licitacoes_pag

def principal():
    print("🔄 --- INICIANDO ATUALIZAÇÃO DA BASE PRINCIPAL ---")
    
    spreadsheet_id = obter_id_google_sheet()
    nome_aba_base = f"licitacoes_{ANO_ALVO}"
    aba_base_id = garantir_ou_obter_primeira_aba(spreadsheet_id, nome_aba_base)
    
    df_existente = ler_aba_google_sheet(spreadsheet_id, nome_aba_base)

    print("🔎 Descobrindo total de páginas no Mural...")
    res = requests.get(URL_BASE, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    total_paginas = 1
    paginacao = soup.find('ul', class_='pagination')
    if paginacao:
        links = paginacao.find_all('a')
        nums = [int(l.get_text()) for l in links if l.get_text().isdigit()]
        if nums: total_paginas = max(nums)
        
    print(f"📄 Total de páginas encontradas: {total_paginas}")

    if MODO_TESTE:
        total_paginas = min(2, total_paginas)
        print("💡 Modo de teste ativo: raspando 2 páginas.")

    todas_licitacoes = []
    print(f"🚀 Raspando páginas com {CONEXOES_SIMULTANEAS} conexões...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        futuros = {executor.submit(raspar_pagina, p): p for p in range(1, total_paginas + 1)}
        for futuro in concurrent.futures.as_completed(futuros):
            res = futuro.result()
            todas_licitacoes.extend(res)

    df_novos = pd.DataFrame(todas_licitacoes)

    if not df_novos.empty:
        # Filtra pelo ano de 2026 no Número ou nas datas de Publicação/Abertura
        mask_2026 = (
            df_novos['Número'].str.contains(str(ANO_ALVO), na=False) |
            df_novos['Publicação'].str.endswith(str(ANO_ALVO), na=False) |
            df_novos['Abertura'].str.endswith(str(ANO_ALVO), na=False)
        )
        df_novos = df_novos[mask_2026]

    print(f"📊 Licitações de {ANO_ALVO} encontradas nesta varredura: {len(df_novos)}")

    if not df_existente.empty and not df_novos.empty:
        df_final = pd.concat([df_existente, df_novos], ignore_index=True).drop_duplicates(subset=['Link_Ficha'], keep='last')
    elif not df_novos.empty:
        df_final = df_novos
    else:
        df_final = df_existente

    print(f"💾 Gravando resultados na aba '{nome_aba_base}'...")
    atualizar_aba_google_sheet(spreadsheet_id, df_final, nome_aba_base, aba_base_id)
    print("🎉 ATUALIZAÇÃO DA BASE PRINCIPAL CONCLUÍDA COM SUCESSO!")

if __name__ == "__main__":
    principal()
