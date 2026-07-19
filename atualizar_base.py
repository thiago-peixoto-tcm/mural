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
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# --- CONFIGURAÇÃO DA NUVEM (GOOGLE DRIVE) ---
ID_PASTA_GOOGLE_DRIVE = "1RQETN6nX3L2_4tZHeu5zGJElIxn38yZ6"
NOME_CSV_ORIGEM = "base_licitacoes.csv"
NOME_EXCEL_FINAL = "base_licitacoes_relacional.xlsx"

CONEXOES_SIMULTANEAS = 10  
MODO_TESTE = False # Mude para True para testar apenas as 2 primeiras páginas da listagem
# ---------------------------------------------

URL_BASE_MURAL = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def obter_servico_google_drive():
    dados_chave_json = os.environ.get("GOOGLE_DRIVE_JSON")
    if not dados_chave_json:
        raise Exception("❌ Erro: A variável de ambiente GOOGLE_DRIVE_JSON não foi encontrada.")
    info_credenciais = json.loads(dados_chave_json)
    return build('drive', 'v3', credentials=Credentials.from_service_account_info(info_credenciais, scopes=['https://www.googleapis.com/auth/drive']))

def baixar_arquivo_drive_se_existir(servico, nome_arquivo, formato='csv'):
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{nome_arquivo}' and trashed=false"
    resultado = servico.files().list(q=query, fields="files(id)").execute()
    arquivos = resultado.get('files', [])
    if not arquivos:
        return None
    
    file_id = arquivos[0]['id']
    requisicao = servico.files().get_media(fileId=file_id)
    bytes_arquivo = io.BytesIO()
    baixador = MediaIoBaseDownload(bytes_arquivo, requisicao)
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
    bytes_arquivo.seek(0)
    
    try:
        if formato == 'csv':
            return pd.read_csv(bytes_arquivo, sep=';', encoding='utf-8')
        else:
            return pd.read_excel(bytes_arquivo, sheet_name=None)
    except Exception:
        bytes_arquivo.seek(0)
        if formato == 'csv':
            return pd.read_csv(bytes_arquivo, sep=';', encoding='latin-1')
        return None

def salvar_arquivo_no_drive(servico, nome_arquivo, conteudo_bytes, mimetype):
    query = f"'{ID_PASTA_GOOGLE_DRIVE}' in parents and name='{nome_arquivo}' and trashed=false"
    # Adicionado supportsAllDrives=True para ler pastas compartilhadas corretamente
    resultado = servico.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    arquivos = resultado.get('files', [])
    
    midia = MediaIoBaseUpload(conteudo_bytes, mimetype=mimetype, resumable=True)
    if arquivos:
        servico.files().update(fileId=arquivos[0]['id'], media_body=midia, supportsAllDrives=True).execute()
    else:
        metadados = {'name': nome_arquivo, 'parents': [ID_PASTA_GOOGLE_DRIVE]}
        # Adicionado supportsAllDrives=True para forçar a gravação usando a cota do dono da pasta
        servico.files().create(body=metadados, media_body=midia, supportsAllDrives=True).execute()
        
def descobrir_total_itens_e_paginas():
    """Acessa a página 1 para identificar dinamicamente o total de itens no mural."""
    url = f"{URL_BASE_MURAL}?page=1&per-page=30"
    res = requests.get(url, headers=HEADERS, timeout=20)
    if res.status_code != 200:
        raise Exception("❌ Não foi possível acessar o Mural do TCM-PA para ler o total de itens.")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    texto_pagina = soup.get_text()
    
    match = re.search(r"A exibir\s+\d+-\d+\s+de\s+([\d\.]+)\s+itens", texto_pagina, re.IGNORECASE)
    if match:
        total_texto = match.group(1).replace(".", "")
        total_itens = int(total_texto)
        total_paginas = math.ceil(total_itens / 30)
        print(f"📊 Total de Itens identificados no TCM-PA: {total_itens} ({total_paginas} páginas)")
        return total_paginas
    else:
        print("⚠️ Aviso: Texto de paginação não localizado. Usando contingência padrão de páginas.")
        return 5000 

def raspar_pagina_listagem(num_pagina):
    """Raspa a tabela de uma página específica da listagem do mural."""
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
                            link_tag = tds[1].find('a') # Coluna 'Número' contém o ID/link
                            if link_tag and link_tag.get('href'):
                                link_ficha = link_tag['href']
                                if not link_ficha.startswith('http'):
                                    link_ficha = "https://www.tcmpa.tc.br" + link_ficha
                                
                                linhas_coletadas.append({
                                    "Legislação": tds[0].get_text(strip=True),
                                    "Número": tds[1].get_text(strip=True),
                                    "Link_Ficha": link_ficha,
                                    "Modalidade": tds[2].get_text(strip=True),
                                    "Tipo": tds[3].get_text(strip=True),
                                    "Objeto": tds[4].get_text(strip=True),
                                    "Abertura": tds[5].get_text(strip=True),
                                    "Publicação": tds[6].get_text(strip=True),
                                    "Município": tds[7].get_text(strip=True),
                                    "Órgão": tds[8].get_text(strip=True),
                                    "Situação": tds[9].get_text(strip=True)
                                })
    except Exception:
        pass
    return linhas_coletadas

def extrair_campo_limpo(texto_completo, termo_alvo):
    ancoras = [
        "Nº do Processo Administrativo", "Legislação Aplicável", "Modalidade", "Tipo", 
        "Regime", "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura", 
        "Observação", "Há itens exclusivos", "Há lote de participação", "Percentual de participação", 
        "Nas aquisições", "Contratação com utilização", "Exercício", "Situação", "Abertura", 
        "Publicação", "Homologação", "Caráter Sigiloso", "Será Firmado Contrato", "Contratos", "Aditivos", "OBJETO"
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

def quebrar_bloco_contrato(texto_bloco):
    info = {"Contrato_Numero": "", "Contrato_Valor": "", "Contrato_Data_Cadastro": "", "Contrato_Contratante": "", "Contrato_Contratado": "", "Contrato_Vigencia_Inicio": "", "Contrato_Vigencia_Fim": "", "Contrato_Aditivos_Info": "", "Contrato_Outros_Documentos": ""}
    texto_norm = " ".join(texto_bloco.split())
    m_num = re.search(r"(Contrato\s+n[°º\.]*.*?)(?=R\$\s*[\d\.,]+|$)", texto_norm, re.IGNORECASE)
    if m_num: info["Contrato_Numero"] = m_num.group(1).strip()
    m_vlr = re.search(r"(R\$\s*[\d\.,]+)", texto_norm)
    if m_vlr: info["Contrato_Valor"] = m_vlr.group(1).strip()
    m_dt = re.search(r"([\d/]{10}\s+[\d:]{5})", texto_norm)
    if m_dt: info["Contrato_Data_Cadastro"] = m_dt.group(1).strip()
    if "CONTRATANTE" in texto_norm: info["Contrato_Contratante"] = texto_norm.split("CONTRATANTE")[-1].split("CONTRATADO")[0].strip(" :")
    if "CONTRATADO" in texto_norm: info["Contrato_Contratado"] = texto_norm.split("CONTRATADO")[-1].split("VIGÊNCIA")[0].strip(" :")
    m_ini = re.search(r"INÍCIO\s*([\d/]+)", texto_norm, re.IGNORECASE)
    m_fim = re.search(r"FIM\s*([\d/]+)", texto_norm, re.IGNORECASE)
    if m_ini: info["Contrato_Vigencia_Inicio"] = m_ini.group(1).strip()
    if m_fim: info["Contrato_Vigencia_Fim"] = m_fim.group(1).strip()
    return info

def raspar_ficha_detalhes(linha_dados):
    link = linha_dados.get("Link_Ficha", "")
    detalhes = {
        "Nº do Processo Administrativo": "", "Legislação Aplicável": "", "Regime": "", "Critério de Avaliação": "", 
        "Elemento de Despesa": "", "Local de Abertura": "", "Observação": "", "Há itens exclusivos para EPP/ME?": "",
        "Há lote de participação para EPP/ME?": "", "Percentual de participação para EPP/ME": "",
        "Nas aquisições, há prioridade para as microempresas regionais ou locais?": "",
        "Contratação com utilização de recursos federais advindos de transferências voluntárias?": "",
        "Exercício": "", "Homologação": "", "Caráter Sigiloso": "", "Será Firmado Contrato": "",
        "Total_Documentos": "0", "Total_Publicidades": "0", "Total_Participantes": "0", "Total_Lotes_Itens": "0", "Total_Contratos": "0", "Total_Aditivos": "0"
    }
    sub_linhas = []
    if not link or pd.isna(link): return linha_dados, sub_linhas

    for _ in range(2):
        try:
            res = requests.get(link, headers=HEADERS, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                txt_pag = soup.get_text(" ", strip=True)
                for k in detalhes.keys():
                    if "Total_" not in k: detalhes[k] = extrair_campo_limpo(txt_pag, k)
                
                badges = soup.find_all('span', class_='badge')
                if len(badges) >= 6:
                    detalhes["Total_Documentos"] = badges[0].get_text(strip=True)
                    detalhes["Total_Publicidades"] = badges[1].get_text(strip=True)
                    detalhes["Total_Participantes"] = badges[2].get_text(strip=True)
                    detalhes["Total_Lotes_Itens"] = badges[3].get_text(strip=True)
                    detalhes["Total_Contratos"] = badges[4].get_text(strip=True)
                    detalhes["Total_Aditivos"] = badges[5].get_text(strip=True)

                # Abas secundárias (Documentos / Publicidades / Participantes / Contratos)
                for aba_id, nome_aba in [('documentos', 'Documentos'), ('publicidades', 'Publicidades')]:
                    div = soup.find('div', id=aba_id)
                    if div:
                        for tr in div.find_all('tr'):
                            tds = tr.find_all('td')
                            if len(tds) >= 3:
                                sub_linhas.append({"Link_Ficha": link, "Origem_Aba": nome_aba, "Propriedade_Coluna": tds[1].get_text(strip=True), "Valor_Resultado": tds[2].get_text(strip=True)})

                div_part = soup.find('div', id='participantes')
                if div_part:
                    for b in div_part.find_all(['div', 'tr']):
                        t = " ".join(b.get_text(" ", strip=True).split())
                        if any(k in t for k in ["LTDA", "EIRELI", "S.A.", "CNPJ", "CPF"]):
                            sub_linhas.append({"Link_Ficha": link, "Origem_Aba": "Participantes", "Propriedade_Coluna": "Participante", "Valor_Resultado": t})

                div_cont = soup.find('div', id='contratos')
                if div_cont:
                    paineis = div_cont.find_all('div', class_='panel') or [div_cont]
                    for p in paineis:
                        txt_c = p.get_text(" ", strip=True)
                        if txt_c:
                            base_c = {"Link_Ficha": link, "Origem_Aba": "Contratos", "Propriedade_Coluna": "Ficha Completa", "Valor_Resultado": txt_c}
                            base_c.update(quebrar_bloco_contrato(txt_c))
                            sub_linhas.append(base_c)
                
                linha_dados.update(detalhes)
                return linha_dados, sub_linhas
        except Exception:
            time.sleep(1)
    linha_dados.update(detalhes)
    return linha_dados, sub_linhas

def principal():
    print("🔄 Conectando ao Google Drive...")
    servico = obter_servico_google_drive()
    
    # 1. Descobrir total de páginas dinamicamente no site do TCM
    total_paginas = descobrir_total_itens_e_paginas()
    if MODO_TESTE:
        total_paginas = 2
    
    # 2. Carregar o histórico existente no Drive para evitar retrabalho estrutural
    df_csv_antigo = baixar_arquivo_drive_se_existir(servico, NOME_CSV_ORIGEM, 'csv')
    links_ja_mapeados = set(df_csv_antigo['Link_Ficha'].tolist()) if df_csv_antigo is not None else set()
    
    print(f"🔎 Varrendo as {total_paginas} páginas do mural em busca de novas licitações...")
    novas_linhas_mural = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
        paginas_alvo = range(1, total_paginas + 1)
        resultados = executor.map(raspar_pagina_listagem, paginas_alvo)
        for res_pag in resultados:
            novas_linhas_mural.extend(res_pag)

    if not novas_linhas_mural:
        print("❌ Nenhuma linha capturada do portal. Abortando para proteger os dados anteriores.")
        return

    df_mural_atualizado = pd.DataFrame(novas_linhas_mural).drop_duplicates(subset=['Link_Ficha'])
    
    # Salvar a nova lista consolidada no formato CSV de origem
    output_csv = io.StringIO()
    df_mural_atualizado.to_csv(output_csv, sep=';', index=False, encoding='utf-8')
    csv_bytes = io.BytesIO(output_csv.getvalue().encode('utf-8'))
    salvar_arquivo_no_drive(servico, NOME_CSV_ORIGEM, csv_bytes, 'text/csv')
    print(f"💾 Arquivo '{NOME_CSV_ORIGEM}' atualizado e salvo no Drive.")

    # 3. Filtrar apenas o que é REALMENTE novo para extrair os detalhes
    fichas_para_detalhar = [r for r in novas_linhas_mural if r['Link_Ficha'] not in links_ja_mapeados]
    print(f"🚀 {len(fichas_para_detalhar)} novas licitações encontradas para detalhamento profundo.")
    
    dict_excel_antigo = baixar_arquivo_drive_se_existir(servico, NOME_EXCEL_FINAL, 'excel')
    df_principal_acumulado = dict_excel_antigo['Licitacoes_Principais'] if dict_excel_antigo and 'Licitacoes_Principais' in dict_excel_antigo else pd.DataFrame()
    df_fato_acumulado = dict_excel_antigo['Abas_Detalhes_Fato'] if dict_excel_antigo and 'Abas_Detalhes_Fato' in dict_excel_antigo else pd.DataFrame()

    if fichas_para_detalhar:
        novas_principais = []
        novas_fato = []
        processados = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONEXOES_SIMULTANEAS) as executor:
            futuros = {executor.submit(raspar_ficha_detalhes, f): f for f in fichas_para_detalhar}
            for futuro in concurrent.futures.as_completed(futuros):
                processados += 1
                try:
                    p_res, f_res = futuro.result()
                    novas_principais.append(p_res)
                    novas_fato.extend(f_res)
                except Exception:
                    pass
                if processados % 50 == 0 or processados == len(fichas_para_detalhar):
                    print(f"   Progresso Detalhamento: {processados}/{len(fichas_para_detalhar)} fichas...")

        df_novas_p = pd.DataFrame(novas_principais)
        df_novas_f = pd.DataFrame(novas_fato)
        
        df_principal_acumulado = pd.concat([df_principal_acumulado, df_novas_p], ignore_index=True).drop_duplicates(subset=['Link_Ficha'])
        df_fato_acumulado = pd.concat([df_fato_acumulado, df_novas_f], ignore_index=True)
    else:
        print("☕ Nenhuma nova ficha encontrada para detalhar hoje. Apenas sincronizando estruturas.")

    # Ajuste de colunas da tabela fato
    colunas_fato = ["Link_Ficha", "Origem_Aba", "Propriedade_Coluna", "Valor_Resultado", "Contrato_Numero", "Contrato_Valor", "Contrato_Data_Cadastro", "Contrato_Contratante", "Contrato_Contratado", "Contrato_Vigencia_Inicio", "Contrato_Vigencia_Fim"]
    for c in colunas_fato:
        if c not in df_fato_acumulado.columns: df_fato_acumulado[c] = ""
    if not df_fato_acumulado.empty:
        df_fato_acumulado = df_fato_acumulado[colunas_fato]

    # Guardar Excel relacional com as duas abas atualizadas no Drive
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        df_principal_acumulado.to_excel(writer, sheet_name='Licitacoes_Principais', index=False)
        df_fato_acumulado.to_excel(writer, sheet_name='Abas_Detalhes_Fato', index=False)
    output_excel.seek(0)
    
    salvar_arquivo_no_drive(servico, NOME_EXCEL_FINAL, output_excel, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    print("✅ PROCESSO CONCLUÍDO COM SUCESSO COLETANDO DIRETAMENTE DO SITE!")

if __name__ == "__main__":
    principal()
