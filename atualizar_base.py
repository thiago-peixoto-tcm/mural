import concurrent.futures
import requests
import pandas as pd
from bs4 import BeautifulSoup
import time
import io
import json
import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# --- CONFIGURAÇÃO DA NUVEM (GOOGLE DRIVE) ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_CSV_ORIGEM = "base_licitacoes.csv"
NOME_EXCEL_FINAL = "base_licitacoes_relacional.xlsx"

CONEXOES_SIMULTANEAS = 10  
MODO_TESTE = False
# ---------------------------------------------

def obter_servico_google_drive():
    """Autentica na API do Google usando a variável de ambiente do GitHub."""
    dados_chave_json = os.environ.get("GOOGLE_DRIVE_JSON")
    if not dados_chave_json:
        raise Exception("❌ Erro: A variável de ambiente GOOGLE_DRIVE_JSON não foi encontrada.")
        
    info_credenciais = json.loads(dados_chave_json)
    escopos = ['https://www.googleapis.com/auth/drive']
    credenciais = Credentials.from_service_account_info(info_credenciais, scopes=escopos)
    return build('drive', 'v3', credentials=credenciais)

def baixar_csv_do_drive(servico):
    """Procura pelo CSV na pasta do Google Drive e baixa para a memória, tratando delimitadores e encoding."""
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{NOME_CSV_ORIGEM}' and trashed=false"
    resultado = servico.files().list(q=query, fields="files(id, name)").execute()
    arquivos = resultado.get('files', [])
    
    if not arquivos:
        raise Exception(f"❌ Erro: Arquivo '{NOME_CSV_ORIGEM}' não foi encontrado na pasta do Google Drive.")
        
    file_id = arquivos[0]['id']
    requisicao = servico.files().get_media(fileId=file_id)
    
    bytes_arquivo = io.BytesIO()
    baixador = MediaIoBaseDownload(bytes_arquivo, requisicao)
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
        
    bytes_arquivo.seek(0)
    
    # Tratamento robusto para garantir a leitura completa de todas as linhas do CSV
    try:
        return pd.read_csv(bytes_arquivo, sep=';', encoding='utf-8')
    except UnicodeDecodeError:
        bytes_arquivo.seek(0)
        return pd.read_csv(bytes_arquivo, sep=';', encoding='latin-1')

def salvar_excel_no_drive(servico, df_principal, df_fato):
    """Gera o arquivo Excel em memória e envia/atualiza no Google Drive."""
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        df_principal.to_excel(writer, sheet_name='Licitacoes_Principais', index=False)
        df_fato.to_excel(writer, sheet_name='Abas_Detalhes_Fato', index=False)
    output_excel.seek(0)
    
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{NOME_EXCEL_FINAL}' and trashed=false"
    resultado = servico.files().list(q=query, fields="files(id)").execute()
    arquivos = resultado.get('files', [])
    
    midia = MediaIoBaseUpload(
        output_excel, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
        resumable=True
    )
    
    if arquivos:
        file_id = arquivos[0]['id']
        servico.files().update(fileId=file_id, media_body=midia).execute()
        print(f" Planilha '{NOME_EXCEL_FINAL}' atualizada com sucesso no Google Drive!")
    else:
        metadados_arquivo = {
            'name': NOME_EXCEL_FINAL,
            'parents': [ID_PASTA_GOOGLE_DRIVE]
        }
        servico.files().create(body=metadados_arquivo, media_body=midia, fields='id').execute()
        print(f" Planilha '{NOME_EXCEL_FINAL}' criada com sucesso no Google Drive!")

def extrair_campo_limpo(texto_completo, termo_alvo):
    """Extrai informações específicas baseadas em palavras-chave âncoras na página."""
    ancoras = [
        "Nº do Processo Administrativo", "Legislação Aplicável", "Modalidade", "Tipo", 
        "Regime", "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura", 
        "Observação", "Há itens exclusivos", "Há lote de participação", "Percentual de participação", 
        "Nas aquisições", "Contratação com utilização", "Exercício", "Situação", "Abertura", 
        "Publicação", "Homologação", "Caráter Sigiloso", "Será Firmado Contrato", "Contratos", "Aditivos", "OBJETO"
    ]
    texto_norm = " ".join(texto_completo.split())
    termo_norm = " ".join(termo_alvo.split())
    
    if termo_norm not in texto_norm:
        return ""
    try:
        pos_termo = texto_norm.find(termo_norm)
        sub_texto = texto_norm[pos_termo + len(termo_norm):].strip()
        if sub_texto.startswith(":"):
            sub_texto = sub_texto[1:].strip()
        menor_indice = len(sub_texto)
        for ancora in ancoras:
            ancora_norm = " ".join(ancora.split())
            if ancora_norm != termo_norm and ancora_norm in sub_texto:
                idx = sub_texto.find(ancora_norm)
                if 0 <= idx < menor_indice:
                    menor_indice = idx
        valor_final = sub_texto[:menor_indice].strip()
        return valor_final.strip(" >:-#\t\r")
    except:
        return ""

def quebrar_bloco_contrato(texto_bloco):
    """Processa blocos de texto contendo informações contratuais."""
    info = {
        "Contrato_Numero": "", "Contrato_Valor": "", "Contrato_Data_Cadastro": "",
        "Contrato_Contratante": "", "Contrato_Contratado": "", "Contrato_Vigencia_Inicio": "",
        "Contrato_Vigencia_Fim": "", "Contrato_Aditivos_Info": "", "Contrato_Outros_Documentos": ""
    }
    texto_bloco_norm = " ".join(texto_bloco.split())
    
    match_num = re.search(r"(Contrato\s+n[°º\.]*.*?)(?=R\$\s*[\d\.,]+|$)", texto_bloco_norm, re.IGNORECASE)
    if match_num: info["Contrato_Numero"] = match_num.group(1).strip()

    match_vlr = re.search(r"(R\$\s*[\d\.,]+)", texto_bloco_norm)
    if match_vlr: info["Contrato_Valor"] = match_vlr.group(1).strip()

    match_data_cad = re.search(r"([\d/]{10}\s+[\d:]{5})", texto_bloco_norm)
    if match_data_cad: info["Contrato_Data_Cadastro"] = match_data_cad.group(1).strip()

    if "CONTRATANTE" in texto_bloco_norm:
        info["Contrato_Contratante"] = texto_bloco_norm.split("CONTRATANTE")[-1].split("CONTRATADO")[0].strip(" :")
    
    if "CONTRATADO" in texto_bloco_norm:
        info["Contrato_Contratado"] = texto_bloco_norm.split("CONTRATADO")[-1].split("VIGÊNCIA")[0].strip(" :")

    match_ini = re.search(r"INÍCIO\s*([\d/]+)", texto_bloco_norm, re.IGNORECASE)
    match_fim = re.search(r"FIM\s*([\d/]+)", texto_bloco_norm, re.IGNORECASE)
    if match_ini: info["Contrato_Vigencia_Inicio"] = match_ini.group(1).strip()
    if match_fim: info["Contrato_Vigencia_Fim"] = match_fim.group(1).strip()

    if "ADITIVOS" in texto_bloco_norm:
        info["Contrato_Aditivos_Info"] = texto_bloco_norm.split("ADITIVOS")[-1].split("OUTROS DOCUMENTOS")[0].strip(" :")

    if "OUTROS DOCUMENTOS" in texto_bloco_norm:
        info["Contrato_Outros_Documentos"] = texto_bloco_norm.split("OUTROS DOCUMENTOS")[-1].strip(" :")

    return info

def raspar_ficha(linha_dados):
    """Efetua a raspagem de dados de uma única URL correspondente a uma licitação."""
    link = linha_dados.get("Link_Ficha", "")
    detalhes = {
        "Nº do Processo Administrativo": "", "Legislação Aplicável": "", "Regime": "", "Critério de Avaliação": "", 
        "Elemento de Despesa": "", "Local de Abertura": "", "Observação": "", "Há itens exclusivos para EPP/ME?": "",
        "Há lote de participação para EPP/ME?": "", "Percentual de participação para EPP/ME": "",
        "Nas aquisições, há prioridade para as microempresas regionais ou locais?": "",
        "Contratação com utilização de recursos federais advindos de transferências voluntárias?": "",
        "Exercício": "", "Homologação": "", "Caráter Sigiloso": "", "Será Firmado Contrato": "",
        "Total_Documentos": "0", "Total_Publicidades": "0", "Total_Participantes": "0",
        "Total_Lotes_Itens": "0", "Total_Contratos": "0", "Total_Aditivos": "0"
    }
    linhas_subtabela = []

    if not link or pd.isna(link) or not str(link).startswith("http"):
        linha_dados.update(detalhes)
        return linha_dados, linhas_subtabela

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    mapeamento_site = {
        "Nº do Processo Administrativo": "Nº do Processo Administrativo", 
        "Legislação Aplicável": "Legislação Aplicável",
        "Regime": "Regime", 
        "Critério de Avaliação": "Critério de Avaliação", 
        "Elemento de Despesa": "Elemento de Despesa",
        "Local de Abertura": "Local de Abertura", 
        "Observação": "Observação", 
        "Há itens exclusivos para EPP/ME?": "Há itens exclusivos para EPP/ME?",
        "Há lote de participação para EPP/ME?": "Há lote de participação para EPP/ME?", 
        "Percentual de participação para EPP/ME": "Percentual de participação para EPP/ME",
        "Nas aquisições, há prioridade para as microempresas regionais ou locais?": "Nas aquisições, há prioridade para as microempresas regionais ou locais?",
        "Contratação com utilização de recursos federais advindos de transferências voluntárias?": "Contratação com utilização de recursos federais advindos de transferências voluntárias?",
        "Exercício": "Exercício", 
        "Homologação": "Homologação", 
        "Caráter Sigiloso": "Caráter Sigiloso", 
        "Será Firmado Contrato": "Será Firmado Contrato"
    }

    for tentativa in range(3):
        try:
            response = requests.get(link, headers=headers, timeout=20)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                texto_pagina = soup.get_text(" ", strip=True)
                
                for termo_site, coluna_excel in mapeamento_site.items():
                    detalhes[coluna_excel] = extrair_campo_limpo(texto_pagina, termo_site)

                badges = soup.find_all('span', class_='badge')
                if len(badges) >= 6:
                    detalhes["Total_Documentos"] = badges[0].get_text(strip=True)
                    detalhes["Total_Publicidades"] = badges[1].get_text(strip=True)
                    detalhes["Total_Participantes"] = badges[2].get_text(strip=True)
                    detalhes["Total_Lotes_Itens"] = badges[3].get_text(strip=True)
                    detalhes["Total_Contratos"] = badges[4].get_text(strip=True)
                    detalhes["Total_Aditivos"] = badges[5].get_text(strip=True)

                # 1. Documentos
                div_docs = soup.find('div', id='documentos')
                if div_docs:
                    for tr in div_docs.find_all('tr'):
                        tds = tr.find_all('td')
                        if len(tds) >= 3:
                            linhas_subtabela.append({
                                "Link_Ficha": link, "Origem_Aba": "Documentos",
                                "Propriedade_Coluna": tds[1].get_text(strip=True),
                                "Valor_Resultado": f"{tds[2].get_text(strip=True)} ({tds[3].get_text(strip=True) if len(tds) > 3 else ''})"
                            })

                # 2. Publicidades
                div_pub = soup.find('div', id='publicidades')
                if div_pub:
                    for tr in div_pub.find_all('tr'):
                        tds = tr.find_all('td')
                        if len(tds) >= 3:
                            linhas_subtabela.append({
                                "Link_Ficha": link, "Origem_Aba": "Publicidades",
                                "Propriedade_Coluna": tds[1].get_text(strip=True),
                                "Valor_Resultado": f"{tds[2].get_text(strip=True)} ({tds[3].get_text(strip=True) if len(tds) > 3 else ''})"
                            })

                # 3. Participantes
                div_part = soup.find('div', id='participantes')
                if div_part:
                    for block in div_part.find_all(['div', 'tr']):
                        txt = block.get_text(" ", strip=True)
                        if any(k in txt for k in ["LTDA", "EIRELI", "S.A.", "SA", "CNPJ", "CPF", "/"]):
                            limpo = " ".join(txt.split())
                            if limpo and "Rastrear" not in limpo:
                                prop = "Participante"
                                if "CNPJ" in limpo:
                                    partes = limpo.split("CNPJ")
                                    prop = partes[0].strip()
                                    limpo = "CNPJ" + partes[1]
                                    
                                linhas_subtabela.append({
                                    "Link_Ficha": link, "Origem_Aba": "Participantes",
                                    "Propriedade_Coluna": prop, "Valor_Resultado": limpo
                                })

                # 4. Contratos
                div_cont = soup.find('div', id='contratos')
                if div_cont:
                    paineis_completos = div_cont.find_all('div', class_=lambda x: x and 'panel' in x and 'panel-body' not in x and 'panel-heading' not in x)
                    if not paineis_completos:
                        paineis_completos = div_cont.find_all('div', class_='panel-default') or div_cont.find_all('div', class_='panel')
                    itens = [p.get_text(" ", strip=True) for p in paineis_completos if p.get_text(strip=True)]
                    if not itens:
                        itens = [div_cont.get_text(" ", strip=True)]
                    for item in list(set(itens)):
                        base_contrato = {
                            "Link_Ficha": link, "Origem_Aba": "Contratos",
                            "Propriedade_Coluna": "Ficha Contratual Completa", "Valor_Resultado": item
                        }
                        base_contrato.update(quebrar_bloco_contrato(item))
                        linhas_subtabela.append(base_contrato)

                # 5. Aditivos
                div_adit = soup.find('div', id='aditivos')
                if div_adit:
                    itens = [tr.get_text(" ", strip=True) for tr in div_adit.find_all('tr') if tr.get_text(strip=True)]
                    if not itens:
                        itens = [d.get_text(" ", strip=True) for d in div_adit.find_all('div', class_='panel-body')]
                    for item in list(set(itens)):
                        linhas_subtabela.append({
                            "Link_Ficha": link, "Origem_Aba": "Aditivos",
                            "Propriedade_Coluna": "Resumo Aditivo", "Valor_Resultado": item
                        })

                linha_dados.update(detalhes)
                return linha_dados, linhas_subtabela
            else:
                time.sleep(2)
        except Exception:
            time.sleep(2)
            
    # Retorna os dados originais mesmo que a requisição venha a falhar para evitar perda de linhas
    linha_dados.update(detalhes)
    return linha_dados, linhas_subtabela

def principal():
    print("Conectando ao Google Drive na nuvem...")
    servico_drive = obter_servico_google_drive()
    
    print("Buscando e baixando arquivo original CSV...")
    df = baixar_csv_do_drive(servico_drive)
    
    # Remove linhas completamente nulas caso existam no arquivo
    df = df.dropna(subset=['Link_Ficha'])
    lista_linhas = df.to_dict(orient='records')
    
    if MODO_TESTE:
        print("▶️ MODO TESTE ATIVADO: Processando apenas 5 linhas.")
        lista_linhas = lista_linhas[:5]
        
    total_tarefas = len(lista_linhas)
    base_principal = []
    base_detalhes_fato = []
    processados = 0
    
    print(f"Iniciando a extração de {total_tarefas} fichas de licitação...")
    
    # Uso do ThreadPoolExecutor garantindo o fluxo contínuo até o fim do arquivo
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        futuros = {executor.submit(raspar_ficha, linha): linha for linha in lista_linhas}
        for futuro in concurrent.futures.as_completed(futuros):
            processados += 1
            try:
                res_principal, res_fato = futuro.result()
                base_principal.append(res_principal)
                base_detalhes_fato.extend(res_fato)
            except Exception as e:
                print(f"⚠️ Erro ao processar uma das linhas: {e}")
            
            if processados % 20 == 0 or processados == total_tarefas:
                print(f"Progresso: {processados}/{total_tarefas} fichas analisadas...")
                
    df_principal = pd.DataFrame(base_principal)
    df_fato = pd.DataFrame(base_detalhes_fato)
    
    colunas_ordenadas = [
        "Link_Ficha", "Origem_Aba", "Propriedade_Coluna", "Valor_Resultado",
        "Contrato_Numero", "Contrato_Valor", "Contrato_Data_Cadastro", 
        "Contrato_Contratante", "Contrato_Contratado", 
        "Contrato_Vigencia_Inicio", "Contrato_Vigencia_Fim", 
        "Contrato_Aditivos_Info", "Contrato_Outros_Documentos"
    ]
    
    for col in colunas_ordenadas:
        if col not in df_fato.columns:
            df_fato[col] = ""
            
    if not df_fato.empty:
        df_fato = df_fato[colunas_ordenadas]
    
    print("Salvando resultado diretamente no Google Drive...")
    salvar_excel_no_drive(servico_drive, df_principal, df_fato)
    print("✅ PROCESSO CONCLUÍDO COM SUCESSO NA NUVEM!")

if __name__ == "__main__":
    principal()
