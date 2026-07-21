import concurrent.futures
import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import io
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
    """Cria instâncias novas e autenticadas para evitar estouro de timeout do socket SSL."""
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
    """Atualiza a planilha usando reconexão automática e retentativas contra falhas de rede SSL."""
    df_strings = df.fillna("").astype(str)
    valores = [df_strings.columns.tolist()] + df_strings.values.tolist()
    corpo = {'values': valores}

    tentativas = 3
    for tentativa in range(1, tentativas + 1):
        try:
            # Força a criação de um serviço HTTP completamente limpo
            _, servico_sheets = obter_servicos_google()
            
            # 1. Limpa o conteúdo
            servico_sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="A1:Z").execute()
            
            # 2. Insere a nova matriz de dados
            servico_sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range="A1",
                valueInputOption="RAW",
                body=corpo
            ).execute()
            
            print("   ✅ Dados gravados com sucesso no Google Sheets!")
            break
        except Exception as e:
            print(f"⚠️ Falha de envio SSL (Tentativa {tentativa}/{tentativas}): {e}")
            if tentativa == tentativas:
                raise e
            time.sleep(5)  # Espera 5 segundos antes de re-tentar

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
        return math.ceil(total_itens / 30)
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

def extrair_campo_limpo(texto_completo, termo_alvo):
    ancoras = ["Nº do Processo Administrativo", "Legislação Aplicável", "Modalidade", "Tipo", "Regime", "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura", "Observação", "Há itens exclusivos", "Há lote de participação", "Percentual de participação", "Nas aquisições", "Contratação com utilização", "Exercício", "Situação", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso", "Será Firmado Contrato", "Contratos", "Aditivos", "OBJETO"]
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

def quebrar_bloco_contrato(texto_bloco):
    info = {"Contrato_Numero": "", "Contrato_Valor": "", "Contrato_Data_Cadastro": "", "Contrato_Contratante": "", "Contrato_Contratado": "", "Contrato_Vigencia_Inicio": "", "Contrato_Vigencia_Fim": ""}
    texto_norm = " ".join(texto_bloco.split())
    m_num = re.search(r"(Contrato\s+n[°º\.]*.*?)(?=R\$\s*[\d\.,]+|$)", texto_norm, re.IGNORECASE)
    if m_num: info["Contrato_Numero"] = m_num.group(1).strip()
    m_vlr = re.search(r"(R\$\s*[\d\.,]+)", texto_norm)
    if m_vlr: info["Contrato_Valor"] = m_vlr.group(1).strip()
    m_dt = re.search(r"([\d/]{10}\s+[\d:]{5})", texto_norm)
    if m_dt: info["Contrato_Data_Cadastro"] = m_dt.group(1).strip()
    return info

def raspar_ficha_detalhes(linha_dados):
    link = linha_dados.get("Link_Ficha", "")
    detalhes = {"Nº do Processo Administrativo": "", "Legislação Aplicável": "", "Regime": "", "Critério de Avaliação": "", "Elemento de Despesa": "", "Local de Abertura": "", "Observação": "", "Exercício": "", "Homologação": "", "Caráter Sigiloso": "", "Será Firmado Contrato": "", "Total_Documentos": "0", "Total_Publicidades": "0", "Total_Participantes": "0", "Total_Contratos": "0"}
    sub_linhas = []
    if not link or pd.isna(link): return linha_dados, sub_linhas

    try:
        res = requests.get(link, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            txt_pag = soup.get_text(" ", strip=True)
            
            ano_exercicio = extrair_campo_limpo(txt_pag, "Exercício")
            detalhes["Exercício"] = ano_exercicio
            
            try:
                ano_int = int(re.sub(r'\D', '', ano_exercicio))
            except:
                ano_int = 2024 
                
            if ano_int < 2024:
                linha_dados.update(detalhes)
                return linha_dados, sub_linhas

            for k in detalhes.keys():
                if "Total_" not in k and k != "Exercício": 
                    detalhes[k] = extrair_campo_limpo(txt_pag, k)
            
            badges = soup.find_all('span', class_='badge')
            if len(badges) >= 5:
                detalhes["Total_Documentos"] = badges[0].get_text(strip=True)
                detalhes["Total_Publicidades"] = badges[1].get_text(strip=True)
                detalhes["Total_Participantes"] = badges[2].get_text(strip=True)
                detalhes["Total_Contratos"] = badges[4].get_text(strip=True)

            for aba_id, nome_aba in [('documentos', 'Documentos'), ('publicidades', 'Publicidades')]:
                div = soup.find('div', id=aba_id)
                if div:
                    for tr in div.find_all('tr'):
                        tds = tr.find_all('td')
                        if len(tds) >= 3:
                            sub_linhas.append({"Link_Ficha": link, "Origem_Aba": nome_aba, "Propriedade_Coluna": tds[1].get_text(strip=True), "Valor_Resultado": tds[2].get_text(strip=True)})

            div_cont = soup.find('div', id='contratos')
            if div_cont:
                paineis = div_cont.find_all('div', class_='panel') or [div_cont]
                for p in paineis:
                    txt_c = p.get_text(" ", strip=True)
                    if txt_c:
                        base_c = {"Link_Ficha": link, "Origem_Aba": "Contratos", "Propriedade_Coluna": "Ficha", "Valor_Resultado": txt_c}
                        base_c.update(quebral_bloco_contrato(txt_c))
                        sub_linhas.append(base_c)
            
            linha_dados.update(detalhes)
    except Exception: pass
    return linha_dados, sub_linhas

def principal():
    print("🔄 Localizando planilhas no Google Drive...")
    id_sheet_principal = obter_id_google_sheet("Base_Licitacoes_Principais")
    id_sheet_fato = obter_id_google_sheet("Abas_Detalhes_Fato")
    
    total_paginas = descobrir_total_itens_e_paginas()
    if MODO_TESTE:
        total_paginas = 2
        print("💡 Modo de teste ativo: varrendo as 2 primeiras páginas.")
        
    df_antigo_p = ler_dados_google_sheet(id_sheet_principal)
    
    # ----------------------------------------------------
    # FASE 1: EXTRAIR LISTAGEM DO PORTAL E SALVAR
    # ----------------------------------------------------
    print(f"🔎 FASE 1: Carregando todas as {total_paginas} páginas do mural para a Base Principal...")
    novas_linhas_mural = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        resultados = executor.map(raspar_pagina_listagem, range(1, total_paginas + 1))
        for res_pag in resultados: novas_linhas_mural.extend(res_pag)

    if not novas_linhas_mural:
        print("❌ Nenhuma linha capturada da listagem. Abortando FASE 1.")
        return

    df_mural_atualizado = pd.DataFrame(novas_linhas_mural).drop_duplicates(subset=['Link_Ficha'])
    
    if not df_antigo_p.empty:
        df_principal_acumulado = pd.concat([df_antigo_p, df_mural_atualizado], ignore_index=True).drop_duplicates(subset=['Link_Ficha'], keep='first')
    else:
        df_principal_acumulado = df_mural_atualizado

    print("💾 Gravando a listagem atualizada na planilha Base_Licitacoes_Principais...")
    atualizar_dados_google_sheet(id_sheet_principal, df_principal_acumulado)
    print("✅ FASE 1 CONCLUÍDA! Planilha principal atualizada com sucesso no Drive.")

    # ----------------------------------------------------
    # FASE 2: DETALHAMENTO COM RE-CONEXÃO AUTOMÁTICA
    # ----------------------------------------------------
    print("🚀 FASE 2: Iniciando o detalhamento e filtragem por Exercício...")
    
    df_principal_atualizada_drive = ler_dados_google_sheet(id_sheet_principal)
    df_antigo_f = ler_dados_google_sheet(id_sheet_fato)
    
    links_com_exercicio_antigo = set()
    if 'Exercício' in df_principal_atualizada_drive.columns:
        for _, row in df_principal_atualizada_drive.iterrows():
            ex_val = str(row['Exercício']).strip()
            if ex_val.isdigit() and int(ex_val) < 2024:
                links_com_exercicio_antigo.add(row['Link_Ficha'])
                
    links_ja_detalhados_fato = set(df_antigo_f['Link_Ficha'].tolist()) if not df_antigo_f.empty else set()
    
    fichas_para_analisar = [item for item in novas_linhas_mural if item['Link_Ficha'] not in links_com_exercicio_antigo and item['Link_Ficha'] not in links_ja_detalhados_fato]

    print(f"📋 Encontradas {len(fichas_para_analisar)} fichas para checar detalhes de 2024+.")
    
    if fichas_para_analisar:
        novas_p, novas_f = [], []
        processados = 0
        total_fichas = len(fichas_para_analisar)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
            futuros = {executor.submit(raspar_ficha_detalhes, f): f for f in fichas_para_analisar}
            for futuro in concurrent.futures.as_completed(futuros):
                processados += 1
                p_res, f_res = futuro.result()
                novas_p.append(p_res)
                novas_f.extend(f_res)
                if processados % 100 == 0 or processados == total_fichas:
                    print(f"   Progresso Fichas: {processados}/{total_fichas}...")

        # Monta os DataFrames finais
        df_novas_p_df = pd.DataFrame(novas_p)
        df_novas_f_df = pd.DataFrame(novas_f)
        
        if not df_novas_p_df.empty:
            df_principal_final = pd.concat([df_principal_atualizada_drive, df_novas_p_df], ignore_index=True).drop_duplicates(subset=['Link_Ficha'], keep='last')
            print("💾 Gravando atualizações finais na Base_Licitacoes_Principais...")
            atualizar_dados_google_sheet(id_sheet_principal, df_principal_final)
            
        if not df_novas_f_df.empty:
            df_fato_final = pd.concat([df_antigo_f, df_novas_f_df], ignore_index=True)
            print("💾 Gravando atualizações finais na Abas_Detalhes_Fato...")
            atualizar_dados_google_sheet(id_sheet_fato, df_fato_final)
            
        print("💾 [SALVAMENTO FINAL] Todas as fichas gravadas no Google Sheets!")
    else:
        print("☕ Nenhuma nova ficha pendente para 2024+.")
        
    print("✅ PROCESSO TOTAL CONCLUÍDO COM SUCESSO!")

if __name__ == "__main__":
    principal()
