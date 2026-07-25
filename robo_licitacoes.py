import os
import json
import time
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÃO DOS IDS DAS PLANILHAS ---
PLANILHA_ENTRADA_KEY = "1UTIgbvelQP4CMNblsB9WDfNvKMdi17Sl8I7EQer_GEs"
PLANILHA_SAIDA_KEY = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U"

# 27 Colunas Exatas (Link Ficha na Coluna A + 26 Campos das Fichas)
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
    """Autentica na API do Google Sheets via Secret do GitHub ou arquivo local."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file"
    ]
    
    json_str = os.environ.get("GOOGLE_DRIVE_JSON")
    
    if json_str:
        print("Autenticando via Secret do GitHub Actions (GOOGLE_DRIVE_JSON)...")
        credentials_info = json.loads(json_str)
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    else:
        print("Secret não encontrada. Tentando arquivo local 'credentials.json'...")
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    return gspread.authorize(creds)

def extrair_dados_ficha(url: str) -> dict:
    """Acessa a URL da ficha técnica no TCM-PA e raspa os 26 campos."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    dados = {k: "não informado" for k in CABECALHOS_ESPERADOS}
    dados["Link Ficha"] = url

    try:
        resp = requests.get(url, headers=headers, timeout=25)
        if resp.status_code != 200:
            print(f"  [Aviso] HTTP Status {resp.status_code} em: {url}")
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

        # 3. Painel da Esquerda (bill-to)
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

        # 4. Painel da Direita (bill-data)
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
        print(f"  [Erro] Falha ao raspar a URL {url}: {e}")

    return dados

def executar_robo(modo_teste: bool = False, limite_teste: int = 5):
    """Executa a leitura da planilha principal, faz o scraping e grava no destino."""
    print(f"=== INICIANDO ROBÔ DE LICITAÇÕES (Modo Teste: {modo_teste}) ===")

    client = obter_cliente_gspread()

    # 1. Conectar e Ler a Planilha de Origem
    print(f"Conectando à planilha de ORIGEM [ID: {PLANILHA_ENTRADA_KEY}]...")
    sh_origem = client.open_by_key(PLANILHA_ENTRADA_KEY)
    ws_origem = sh_origem.worksheet("licitacoes_2026")

    # Extrai os links da Coluna C (a partir da linha 2)
    coluna_c = ws_origem.col_values(3)
    urls = [url.strip() for url in coluna_c[1:] if url.strip().startswith("http")]

    print(f"Total de URLs encontradas na Coluna C: {len(urls)}")

    if not urls:
        print("Nenhuma URL válida encontrada na aba 'licitacoes_2026'. Encerrando.")
        return

    if modo_teste:
        urls = urls[:limite_teste]
        print(f"-> MODO TESTE ATIVO: Processando apenas os {len(urls)} primeiros links.")

    # 2. Conectar à Planilha de Destino
    print(f"Conectando à planilha de DESTINO [ID: {PLANILHA_SAIDA_KEY}]...")
    sh_destino = client.open_by_key(PLANILHA_SAIDA_KEY)
    ws_destino = sh_destino.sheet1

    # Adiciona o cabeçalho se a aba estiver em branco
    if not ws_destino.row_values(1):
        ws_destino.append_row(CABECALHOS_ESPERADOS)

    # 3. Processamento Linha a Linha
    novas_linhas = []
    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] Extraindo: {url}")
        dados_dict = extrair_dados_ficha(url)
        linha = [dados_dict.get(col, "não informado") for col in CABECALHOS_ESPERADOS]
        novas_linhas.append(linha)
        time.sleep(1)

    # 4. Salvar na Planilha Fato
    if novas_linhas:
        print("Gravando dados na planilha 'Abas_Detalhes_Fato'...")
        ws_destino.append_rows(novas_linhas, value_input_option="USER_ENTERED")
        print(f"=== SUCESSO! {len(novas_linhas)} linhas inseridas com êxito! ===")

if __name__ == "__main__":
    is_teste = os.environ.get("MODO_TESTE", "true").lower() == "true"
    executar_robo(modo_teste=is_teste, limite_teste=5)
