import os
import json
import time
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES DE PLANILHAS ---
PLANILHA_ENTRADA_KEY = "1UTIgbvelQP4CMNblsB9WDfNvKMdi17Sl8I7EQer_GEs"
PLANILHA_SAIDA_KEY = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U"

CABECALHOS_ESPERADOS = [
    "Link Ficha", "Documentos", "Publicidades", "Participantes", "Lotes & Itens",
    "Contratos", "Aditivos", "LICITAÇÃO", "Nº do Processo Administrativo",
    "Regime", "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",
    "Observação", "Há itens exclusivos para EPP/ME?", "Há cote de participação para EPP/ME?",
    "Percentual de participação para EPP/ME", "Nas aquisições, há prioridade para as microempresas regionais ou locais?",
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?",
    "Exercício", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",
    "Será Firmado Contrato", "Contratos (Resumo)", "Aditivos (Resumo)"
]

def obter_cliente_gspread():
    """Autentica no Google Sheets usando o conteúdo da Secret do GitHub Actions."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Busca o conteúdo do JSON da Secret 'GOOGLE_DRIVE_JSON'
    json_str = os.environ.get("GOOGLE_DRIVE_JSON")
    
    if json_str:
        # Se estiver rodando no GitHub Actions
        credentials_info = json.loads(json_str)
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    else:
        # Fallback para execução local (caso tenha credentials.json no PC)
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    return gspread.authorize(creds)

def extrair_dados_ficha(url: str) -> dict:
    """Acessa o site do TCM-PA e extrai os 26 campos solicitados."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    dados = {k: "não informado" for k in CABECALHOS_ESPERADOS}
    dados["Link Ficha"] = url

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"Aviso: Status {resp.status_code} ao acessar {url}")
            return dados

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 1. Contadores das Abas
        abas_map = {
            "#documentos": "Documentos",
            "#publicidades": "Publicidades",
            "#participantes": "Participantes",
            "#lotes-itens": "Lotes & Itens",
            "#contratos": "Contratos",
            "#aditivos": "Aditivos"
        }
        for href_id, nome_campo in abas_map.items():
            aba_elem = soup.find("a", href=href_id)
            if aba_elem:
                badge = aba_elem.find("span", class_="badge")
                if badge:
                    dados[nome_campo] = badge.get_text(strip=True)

        # 2. Número da Licitação (#005/2026-CMAC)
        lic_num = soup.find("h5", class_="text-blue")
        if lic_num:
            dados["LICITAÇÃO"] = lic_num.get_text(strip=True)

        # 3. Seção Esquerda (bill-to)
        bill_to = soup.find("div", class_="bill-to")
        if bill_to:
            p_tags = bill_to.find_all("p")
            for p in p_tags:
                texto_p = p.get_text(separator=" ", strip=True)
                if ":" in texto_p:
                    partes = texto_p.split(":", 1)
                    chave = partes[0].replace(">", "").strip()
                    valor = partes[1].strip()

                    for col in CABECALHOS_ESPERADOS:
                        if col.lower() in chave.lower():
                            dados[col] = valor
                            break

        # 4. Seção Direita (bill-data)
        bill_data = soup.find("div", class_="bill-data")
        if bill_data:
            spans = bill_data.find_all("span", class_="text-dark")
            for span in spans:
                texto_span = span.get_text(separator=" ", strip=True)
                if ":" in texto_span:
                    partes = texto_span.split(":", 1)
                    chave = partes[0].strip()
                    valor = partes[1].strip()

                    if "Exercício" in chave:
                        dados["Exercício"] = valor
                    elif "Abertura" in chave:
                        dados["Abertura"] = valor
                    elif "Publicação" in chave:
                        dados["Publicação"] = valor
                    elif "Homologação" in chave:
                        dados["Homologação"] = valor
                    elif "Caráter Sigiloso" in chave:
                        dados["Caráter Sigiloso"] = valor
                    elif "Será Firmado Contrato" in chave:
                        dados["Será Firmado Contrato"] = valor
                    elif "Contratos" in chave:
                        dados["Contratos (Resumo)"] = valor
                    elif "Aditivos" in chave:
                        dados["Aditivos (Resumo)"] = valor

    except Exception as e:
        print(f"Erro ao processar {url}: {e}")

    return dados

def executar_robo(modo_teste: bool = False, limite_teste: int = 5):
    """Lê os links e atualiza a planilha destino."""
    print(f"--- Iniciando Robô (Modo Teste: {modo_teste}) ---")

    client = obter_cliente_gspread()

    # 1. Ler Links da Planilha de Origem
    sh_origem = client.open_by_key(PLANILHA_ENTRADA_KEY)
    ws_origem = sh_origem.worksheet("licitacoes_2026")

    coluna_c = ws_origem.col_values(3)
    urls = [url for url in coluna_c[1:] if url.strip().startswith("http")]

    if modo_teste:
        urls = urls[:limite_teste]
        print(f"Modo teste ATIVO. Processando apenas os {len(urls)} primeiros links.")

    # 2. Planilha de Destino
    sh_destino = client.open_by_key(PLANILHA_SAIDA_KEY)
    ws_destino = sh_destino.sheet1

    # Inserir cabeçalho se a aba estiver vazia
    if not ws_destino.row_values(1):
        ws_destino.append_row(CABECALHOS_ESPERADOS)

    # 3. Scraping
    novas_linhas = []
    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] Processando: {url}")
        dados_dict = extrair_dados_ficha(url)
        linha = [dados_dict.get(col, "não informado") for col in CABECALHOS_ESPERADOS]
        novas_linhas.append(linha)
        time.sleep(1)

    # 4. Salvar
    if novas_linhas:
        ws_destino.append_rows(novas_linhas, value_input_option="USER_ENTERED")
        print(f"Sucesso! {len(novas_linhas)} linhas adicionadas.")

if __name__ == "__main__":
    # Define se roda no Modo Teste via variável de ambiente do GitHub ou local
    # Por padrão, se MODO_TESTE="true", vai rodar 5 linhas.
    is_teste = os.environ.get("MODO_TESTE", "false").lower() == "true"
    
    # Se quiser testar direto localmente no Python, basta forçar True:
    # is_teste = True 
    
    executar_robo(modo_teste=is_teste, limite_teste=5)
