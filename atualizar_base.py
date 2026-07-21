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

# --- CONFIGURAÇÃO DA NUVEM (GOOGLE DRIVE) ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
CONEXOES_SIMULTANEAS = 4   
MODO_TESTE = False         
# ---------------------------------------------

URL_BASE_MURAL = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem"
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

def obter_id_google_sheet(nome_planilha):
    servico_drive, _ = obter_servicos_google()
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{nome_planilha}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    resultado = servico_drive.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    arquivos = resultado.get('files', [])
    if arquivos:
        return arquivos[0]['id']
    else:
        raise Exception(f"❌ Erro Crítico: A planilha '{nome_planilha}' não foi encontrada na sua pasta do Drive.")

def ler_dados_google_sheet(spreadsheet_id):
    _, servico_sheets = obter_servicos_google()
    try:
        resultado = servico_sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="A1:Z").execute()
        valores = resultado.get('values', [])
        if not valores:
            return pd.DataFrame()
        return pd.DataFrame(valores[1:], columns=valores[0])
    except Exception as e:
        print(f"⚠️ Aviso ao ler do Google Sheets: {e}")
        return pd.DataFrame()

def atualizar_dados_google_sheet(spreadsheet_id, df):
    df_strings = df.fillna("").astype(str)
    valores = [df_strings.columns.tolist()] + df_strings.values.tolist()
    corpo = {'values': valores}

    tentativas = 3
    for tentativa in range(1, tentativas + 1):
        try:
            _, servico_sheets = obter_servicos_google()
            
            # Limpa o conteúdo e grava a matriz atualizada
            servico_sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="A1:Z").execute()
            servico_sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range="A1",
                valueInputOption="RAW",
                body=corpo
            ).execute()
            
            print("💾 ✅ Tabela 'Base_Licitacoes_Principais' atualizada com sucesso no Google Sheets!")
            break
        except Exception as e:
            print(f"⚠️ Falha de envio (Tentativa {tentativa}/{tentativas}): {e}")
            if tentativa == tentativas:
                raise e
            time.sleep(5)

def descobrir_total_itens_e_paginas():
    url = f"{URL_BASE_MURAL}?page=1&per-page=30"
    res = requests.get(url, headers=HEADERS, timeout=20)
    if res.status_code != 200:
        raise Exception("❌ Não foi possível acessar o Mural do TCM-PA.")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    texto_pagina = soup.get_text()
    match = re.search(r"A exibir\s+\d+-\d+\s+de\s+([\d\.]+)\s+itens", texto_pagina, re.IGNORECASE)
    if match:
        total_texto = match.group(1).replace(".", "")
        total_itens = int(total_texto)
        total_pags = math.ceil(total_itens / 30)
        print(f"📊 Total de licitações identificadas: {total_itens} em {total_pags} páginas.")
        return total_pags
    return 5000 

def raspar_pagina_listagem(num_pagina):
    url = f"{URL_BASE_MURAL}?page={num_pagina}&per-page=30"
    linhas_coletadas = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            tabela = soup.find('table')
            if tabela:
                corpo = tabela.find('tbody')
                if corpo:
                    for tr in corpo.find_all('tr'):
                        tds = tr.find_all('td')
                        if len(tds) >= 10:
                            link_tag = tds[1].find('a')
                            if link_tag and link_tag.get('href'):
                                link_ficha = link_tag['href']
                                if not link_ficha.startswith('http'):
                                    link_ficha = "https://www.tcmpa.tc.br" + link_ficha
                                
                                linhas_coletadas.append({
                                    "Legislação": tds[0].get_text(strip=True), "Número": tds[1].get_text(strip=True),
                                    "Link_Ficha": link_ficha, "Modalidade": tds[2].get_text(strip=True),
                                    "Tipo": tds[3].get_text(strip=True), "Objeto": tds[4].get_text(strip=True),
                                    "Abertura": tds[5].get_text(strip=True), "Publicação": tds[6].get_text(strip=True),
                                    "Município": tds[7].get_text(strip=True), "Órgão": tds[8].get_text(strip=True),
                                    "Situação": tds[9].get_text(strip=True)
                                })
    except Exception: pass
    return linhas_coletadas

def principal():
    print("🔄 --- ETAPA 1: EXTRAÇÃO DA BASE PRINCIPAL ---")
    id_sheet_principal = obter_id_google_sheet("Base_Licitacoes_Principais")
    
    total_paginas = descobrir_total_itens_e_paginas()
    if MODO_TESTE:
        total_paginas = 2
        print("💡 Modo de teste ativo: varrendo apenas 2 páginas.")
        
    df_antigo_p = ler_dados_google_sheet(id_sheet_principal)
    
    print(f"🔎 Coletando as {total_paginas} páginas do mural...")
    novas_linhas_mural = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        resultados = executor.map(raspar_pagina_listagem, range(1, total_paginas + 1))
        for i, res_pag in enumerate(resultados, 1):
            novas_linhas_mural.extend(res_pag)
            if i % 500 == 0 or i == total_paginas:
                print(f"   Progresso das páginas: {i}/{total_paginas}...")

    if not novas_linhas_mural:
        print("❌ Nenhuma linha capturada. Verifique a conexão com o TCM-PA.")
        return

    df_mural_atualizado = pd.DataFrame(novas_linhas_mural).drop_duplicates(subset=['Link_Ficha'])
    
    # Junta com os dados históricos existentes na planilha (para preservar colunas já preenchidas)
    if not df_antigo_p.empty:
        df_principal_acumulado = pd.concat([df_antigo_p, df_mural_atualizado], ignore_index=True).drop_duplicates(subset=['Link_Ficha'], keep='first')
    else:
        df_principal_acumulado = df_mural_atualizado

    print("💾 Gravando dados finais no Google Drive...")
    atualizar_dados_google_sheet(id_sheet_principal, df_principal_acumulado)
    print("🎉 PARABÉNS! ETAPA 1 FINALIZADA COM SUCESSO!")

if __name__ == "__main__":
    principal()
