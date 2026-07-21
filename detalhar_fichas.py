import concurrent.futures
import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import json
import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAÇÕES ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_PLANILHA = "Base_Licitacoes_Principais"
NOME_ABA_DETALHES = "detalhamento"
CONEXOES_SIMULTANEAS = 4
MODO_TESTE = False  # Altere para True se quiser testar apenas 20 fichas antes de rodar tudo
# ---------------------

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

def garantir_ou_obter_aba(spreadsheet_id, nome_aba):
    _, servico_sheets = obter_servicos_google()
    sheet_metadata = servico_sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = sheet_metadata.get('sheets', [])
    
    for s in sheets:
        if s['properties']['title'] == nome_aba:
            return s['properties']['sheetId']
            
    body = {'requests': [{'addSheet': {'properties': {'title': nome_aba}}}]}
    res = servico_sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return res['replies'][0]['addSheet']['properties']['sheetId']

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

def atualizar_aba_detalhamento(spreadsheet_id, df_detalhes, aba_id):
    df_strings = df_detalhes.fillna("").astype(str)
    linhas_totais = len(df_strings)
    if linhas_totais == 0:
        return

    _, servico_sheets = obter_servicos_google()
    
    # Redimensiona o Grid
    linhas_necessarias = max(linhas_totais + 500, 1000)
    print(f"📐 Redimensionando aba '{NOME_ABA_DETALHES}' para {linhas_necessarias} linhas...")
    req_redimensionar = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": aba_id,
                        "gridProperties": {
                            "rowCount": linhas_necessarias,
                            "columnCount": 30
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
    print(f"📦 Enviando {linhas_totais} linhas detalhadas em fatias...")
    
    for i in range(0, len(valores_matriz), tamanho_bloco):
        bloco = valores_matriz[i : i + tamanho_bloco]
        linha_inicio = i + 1
        linha_fim = linha_inicio + len(bloco) - 1
        intervalo = f"'{NOME_ABA_DETALHES}'!A{linha_inicio}:ZZ{linha_fim}"
        
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

def extrair_campo_limpo(texto_completo, termo_alvo):
    ancoras = [
        "Nº do Processo Administrativo", "Legislação Aplicável", "Modalidade", "Tipo", "Regime", 
        "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura", "Observação", 
        "Há itens exclusivos", "Há cota de participação", "Percentual de participação", 
        "Nas aquisições", "Contratação com utilização", "Exercício", "Situação", "Abertura", 
        "Publicação", "Homologação", "Caráter Sigiloso", "Será Firmado Contrato", "REFERÊNCIA", "ADJUDICADO"
    ]
    texto_norm = " ".join(texto_completo.split())
    termo_norm = " ".join(termo_alvo.split())
    if termo_norm not in texto_norm: return ""
    try:
        pos_termo = texto_norm.find(termo_norm)
        sub_texto = texto_norm[pos_termo + len(termo_norm):].strip()
        if sub_texto.startswith(":"): sub_texto = sub_texto[1:].strip()
        menor_indice = len(sub_texto)
        for ancora in ancoras:
            ancora_norm = " ".join(ancora.split())
            if ancora_norm != termo_norm and ancora_norm in sub_texto:
                idx = sub_texto.find(ancora_norm)
                if 0 <= idx < menor_indice: menor_indice = idx
        return sub_texto[:menor_indice].strip(" >:-#\t\r")
    except: return ""

def raspar_ficha_detalhada(link_original):
    link_completo = f"{link_original}#licitacao" if not link_original.endswith("#licitacao") else link_original
    
    detalhes = {
        "ID_Link_Ficha": link_completo,
        "Link_Ficha_Base": link_original,
        "Nº do Processo Administrativo": "",
        "Regime": "",
        "Critério de Avaliação": "",
        "Elemento de Despesa": "",
        "Local de Abertura": "",
        "Observação": "",
        "Há itens exclusivos para EPP/ME?": "",
        "Há cota de participação para EPP/ME?": "",
        "Percentual de participação para EPP/ME": "",
        "Nas aquisições, há prioridade para as microempresas regionais ou locais?": "",
        "Contratação com utilização de recursos federais advindos de transferências voluntárias?": "",
        "Exercício": "",
        "Homologação": "",
        "Caráter Sigiloso": "",
        "Será Firmado Contrato": "",
        "Total_Documentos": "0",
        "Total_Publicidades": "0",
        "Total_Participantes": "0",
        "Total_Lotes_Itens": "0",
        "Total_Contratos": "0",
        "Total_Aditivos": "0",
        "VLR Referência": "",
        "VLR Adjudicado": ""
    }

    try:
        res = requests.get(link_completo, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            txt_pag = soup.get_text(" ", strip=True)

            # Campos Textuais
            detalhes["Nº do Processo Administrativo"] = extrair_campo_limpo(txt_pag, "Nº do Processo Administrativo")
            detalhes["Regime"] = extrair_campo_limpo(txt_pag, "Regime")
            detalhes["Critério de Avaliação"] = extrair_campo_limpo(txt_pag, "Critério de Avaliação")
            detalhes["Elemento de Despesa"] = extrair_campo_limpo(txt_pag, "Elemento de Despesa")
            detalhes["Local de Abertura"] = extrair_campo_limpo(txt_pag, "Local de Abertura")
            detalhes["Observação"] = extrair_campo_limpo(txt_pag, "Observação")
            detalhes["Há itens exclusivos para EPP/ME?"] = extrair_campo_limpo(txt_pag, "Há itens exclusivos para EPP/ME")
            detalhes["Há cota de participação para EPP/ME?"] = extrair_campo_limpo(txt_pag, "Há cota de participação para EPP/ME")
            detalhes["Percentual de participação para EPP/ME"] = extrair_campo_limpo(txt_pag, "Percentual de participação para EPP/ME")
            detalhes["Nas aquisições, há prioridade para as microempresas regionais ou locais?"] = extrair_campo_limpo(txt_pag, "Nas aquisições, há prioridade")
            detalhes["Contratação com utilização de recursos federais advindos de transferências voluntárias?"] = extrair_campo_limpo(txt_pag, "Contratação com utilização de recursos federais")
            detalhes["Exercício"] = extrair_campo_limpo(txt_pag, "Exercício")
            detalhes["Homologação"] = extrair_campo_limpo(txt_pag, "Homologação")
            detalhes["Caráter Sigiloso"] = extrair_campo_limpo(txt_pag, "Caráter Sigiloso")
            detalhes["Será Firmado Contrato"] = extrair_campo_limpo(txt_pag, "Será Firmado Contrato")

            # Badges (Contadores de abas)
            badges = soup.find_all('span', class_='badge')
            if len(badges) >= 6:
                detalhes["Total_Documentos"] = badges[0].get_text(strip=True)
                detalhes["Total_Publicidades"] = badges[1].get_text(strip=True)
                detalhes["Total_Participantes"] = badges[2].get_text(strip=True)
                detalhes["Total_Lotes_Itens"] = badges[3].get_text(strip=True)
                detalhes["Total_Contratos"] = badges[4].get_text(strip=True)
                detalhes["Total_Aditivos"] = badges[5].get_text(strip=True)

            # Valores Monetários do Bloco de Objeto
            match_ref = re.search(r"REFERÊNCIA\s*:\s*(R\$\s*[\d\.,]+)", txt_pag, re.IGNORECASE)
            if match_ref: 
                detalhes["VLR Referência"] = match_ref.group(1).strip()
            
            match_adj = re.search(r"ADJUDICADO\s*:\s*([^OBJETO]+)", txt_pag, re.IGNORECASE)
            if match_adj: 
                txt_adj = match_adj.group(1).strip()
                if "R$" in txt_adj:
                    m_vlr = re.search(r"(R\$\s*[\d\.,]+)", txt_adj)
                    detalhes["VLR Adjudicado"] = m_vlr.group(1).strip() if m_vlr else txt_adj[:50]
                else:
                    detalhes["VLR Adjudicado"] = txt_adj[:50]

    except Exception: pass
    return detalhes

def principal():
    print("🔄 --- INICIANDO EXTRAÇÃO DE DETALHES DAS FICHAS ---")
    
    spreadsheet_id = obter_id_google_sheet()
    aba_detalhes_id = garantir_ou_obter_aba(spreadsheet_id, NOME_ABA_DETALHES)
    
    servico_sheets = build('sheets', 'v4', credentials=Credentials.from_service_account_info(json.loads(os.environ.get("GOOGLE_DRIVE_JSON")), scopes=['https://www.googleapis.com/auth/spreadsheets']))
    sheet_metadata = servico_sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    nome_primeira_aba = sheet_metadata['sheets'][0]['properties']['title']
    
    df_principal = ler_aba_google_sheet(spreadsheet_id, nome_primeira_aba)
    df_detalhes_existente = ler_aba_google_sheet(spreadsheet_id, NOME_ABA_DETALHES)

    if df_principal.empty:
        print("❌ A aba principal está vazia.")
        return

    ids_ja_processados = set(df_detalhes_existente['ID_Link_Ficha'].tolist()) if not df_detalhes_existente.empty and 'ID_Link_Ficha' in df_detalhes_existente.columns else set()
    
    links_para_processar = []
    for link in df_principal['Link_Ficha'].dropna().unique():
        id_composto = f"{link}#licitacao" if not link.endswith("#licitacao") else link
        if id_composto not in ids_ja_processados:
            links_para_processar.append(link)

    total_pendentes = len(links_para_processar)
    print(f"📋 Total de fichas pendentes para detalhar: {total_pendentes}")

    if MODO_TESTE and total_pendentes > 20:
        links_para_processar = links_para_processar[:20]
        total_pendentes = len(links_para_processar)
        print("💡 Modo de teste ativo: varrendo 20 fichas.")

    if total_pendentes > 0:
        novos_detalhes = []
        processados = 0
        
        print("🚀 Extraindo informações detalhadas...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
            futuros = {executor.submit(raspar_ficha_detalhada, link): link for link in links_para_processar}
            for futuro in concurrent.futures.as_completed(futuros):
                processados += 1
                res = futuro.result()
                novos_detalhes.append(res)
                if processados % 100 == 0 or processados == total_pendentes:
                    print(f"   Progresso: {processados}/{total_pendentes}...")

        df_novos = pd.DataFrame(novos_detalhes)
        
        if not df_detalhes_existente.empty:
            df_final = pd.concat([df_detalhes_existente, df_novos], ignore_index=True).drop_duplicates(subset=['ID_Link_Ficha'], keep='last')
        else:
            df_final = df_novos

        print(f"💾 Gravando resultados na aba '{NOME_ABA_DETALHES}'...")
        atualizar_aba_detalhamento(spreadsheet_id, df_final, aba_detalhes_id)
        print("🎉 TUDO PRONTO! ABA 'detalhamento' ATUALIZADA COM SUCESSO!")
    else:
        print("☕ Nenhuma nova ficha pendente. Todas as licitações já foram detalhadas!")

if __name__ == "__main__":
    principal()
