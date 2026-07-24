import os
import json
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------
# 1. Autenticação na API do Google Sheets
# ---------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_json = os.environ.get("GOOGLE_CREDENTIALS")
if not creds_json:
    raise ValueError("Variável de ambiente GOOGLE_CREDENTIALS não configurada!")

creds_dict = json.loads(creds_json)
credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
client = gspread.authorize(credentials)

# ---------------------------------------------------------
# 2. Definição do Cabeçalho Padrão (26 Colunas de Dados)
# ---------------------------------------------------------
HEADERS = [
    "URL",                                                                            # Coluna A
    "Documentos",                                                                     # Coluna B (1)
    "Publicidades",                                                                   # Coluna C (2)
    "Participantes",                                                                  # Coluna D (3)
    "Lotes & Itens",                                                                 # Coluna E (4)
    "Contratos (Aba)",                                                                # Coluna F (5)
    "Aditivos (Aba)",                                                                 # Coluna G (6)
    "LICITAÇÃO",                                                                      # Coluna H (7)
    "Nº do Processo Administrativo",                                                  # Coluna I (8)
    "Regime",                                                                         # Coluna J (9)
    "Critério de Avaliação",                                                         # Coluna K (10)
    "Elemento de Despesa",                                                            # Coluna L (11)
    "Local de Abertura",                                                              # Coluna M (12)
    "Observação",                                                                     # Coluna N (13)
    "Há itens exclusivos para EPP/ME?",                                              # Coluna O (14)
    "Há cote de participação para EPP/ME?",                                           # Coluna P (15)
    "Percentual de participação para EPP/ME",                                        # Coluna Q (16)
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",       # Coluna R (17)
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?", # Coluna S (18)
    "Exercício",                                                                      # Coluna T (19)
    "Abertura",                                                                       # Coluna U (20)
    "Publicação",                                                                     # Coluna V (21)
    "Homologação",                                                                    # Coluna W (22)
    "Carácter Sigiloso",                                                              # Coluna X (23)
    "Será Firmado Contrato",                                                          # Coluna Y (24)
    "Contratos (Painel)",                                                             # Coluna Z (25)
    "Aditivos (Painel)"                                                               # Coluna AA (26)
]

# ---------------------------------------------------------
# 3. Função de Extração (Web Scraping)
# ---------------------------------------------------------
def extract_page_data(url):
    headers_req = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(url, headers=headers_req, timeout=30)
    
    if response.status_code != 200:
        print(f"Erro ao acessar {url}: Status {response.status_code}")
        return None
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    def get_text_by_label(p_tags, label_text):
        for p in p_tags:
            text = p.get_text(strip=True)
            if label_text.lower() in text.lower():
                parts = text.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
                return text
        return ""

    def get_badge_count(tab_id):
        tab = soup.find('a', href=f"#{tab_id}")
        if tab:
            badge = tab.find('span', class_='badge')
            if badge:
                return badge.get_text(strip=True)
        return "0"

    def get_bill_data_value(label):
        bill_data = soup.find('div', class_='bill-data')
        if not bill_data:
            return ""
        for p in bill_data.find_all('p'):
            text = p.get_text(" ", strip=True)
            if label.lower() in text.lower():
                parts = text.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
        return ""

    # Extração das Variáveis
    doc_count = get_badge_count('documentos')
    pub_count = get_badge_count('publicidades')
    part_count = get_badge_count('participantes')
    lotes_count = get_badge_count('lotes-itens')
    contratos_aba = get_badge_count('contratos')
    aditivos_aba = get_badge_count('aditivos')

    licitacao_h5 = soup.find('h5', class_='text-blue')
    licitacao_id = licitacao_h5.get_text(strip=True) if licitacao_h5 else ""

    bill_to_ps = soup.select('.bill-to p')
    proc_admin = get_text_by_label(bill_to_ps, "Nº do Processo Administrativo")
    regime = get_text_by_label(bill_to_ps, "Regime")
    crit_aval = get_text_by_label(bill_to_ps, "Critério de Avaliação")
    elem_desp = get_text_by_label(bill_to_ps, "Elemento de Despesa")
    loc_abertura = get_text_by_label(bill_to_ps, "Local de Abertura")
    obs = get_text_by_label(bill_to_ps, "Observação")
    epp_exclusivo = get_text_by_label(bill_to_ps, "Há itens exclusivos para EPP/ME?")
    epp_cota = get_text_by_label(bill_to_ps, "Há cote de participação para EPP/ME?")
    epp_perc = get_text_by_label(bill_to_ps, "Percentual de participação para EPP/ME")
    epp_prio = get_text_by_label(bill_to_ps, "Nas aquisições, há prioridade para as microempresas regionais ou locais?")
    rec_fed = get_text_by_label(bill_to_ps, "Contratação com utilização de recursos federais advindos de transferências voluntárias?")

    exercicio = get_bill_data_value("Exercício")
    abertura = get_bill_data_value("Abertura")
    publicacao = get_bill_data_value("Publicação")
    homologacao = get_bill_data_value("Homologação")
    sigiloso = get_bill_data_value("Caráter Sigiloso")
    firmado_contrato = get_bill_data_value("Será Firmado Contrato")
    contratos_panel = get_bill_data_value("Contratos")
    aditivos_panel = get_bill_data_value("Aditivos")

    return [
        url, doc_count, pub_count, part_count, lotes_count, contratos_aba, aditivos_aba,
        licitacao_id, proc_admin, regime, crit_aval, elem_desp, loc_abertura, obs,
        epp_exclusivo, epp_cota, epp_perc, epp_prio, rec_fed, exercicio, abertura,
        publicacao, homologacao, sigiloso, firmado_contrato, contratos_panel, aditivos_panel
    ]

# ---------------------------------------------------------
# 4. Processamento Principal
# ---------------------------------------------------------
def main():
    print("--- MODO DE TESTE ATIVADO: PROCESSANDO APENAS AS 5 PRIMEIRAS LINHAS ---")

    # A) Leitura dos Links
    sheet_origem = client.open_by_key("1UTIgbvelQP4CMNblsB9WDfNvKMdi17SI8I7EQer_GEs").sheet1
    
    col_c_values = sheet_origem.col_values(3)
    
    # Filtra URLs válidas
    all_urls = [url.strip() for url in col_c_values[1:] if url.strip().startswith("http")]
    
    # LIMITAÇÃO PARA O TESTE: Pega apenas as 5 primeiras
    urls = all_urls[:5]
    print(f"Total de links encontrados na aba: {len(all_urls)}. Serão processados apenas: {len(urls)}")

    # B) Leitura / Preparação da Planilha de Destino
    doc_destino = client.open_by_key("1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U")
    sheet_destino = doc_destino.worksheet("Abas_Detalhes_Fato")

    # Atualiza cabeçalhos
    sheet_destino.update('A1:AA1', [HEADERS])

    # C) Extração e Envio
    rows_to_append = []
    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] Extraindo dados de: {url}")
        row_data = extract_page_data(url)
        if row_data:
            rows_to_append.append(row_data)

    if rows_to_append:
        sheet_destino.append_rows(rows_to_append, value_input_option='USER_ENTERED')
        print(f"\n--- TESTE FINALIZADO ---")
        print(f"{len(rows_to_append)} linhas gravadas na planilha 'Abas_Detalhes_Fato'.")
    else:
        print("Nenhum dado extraído durante o teste.")

if __name__ == "__main__":
    main()
