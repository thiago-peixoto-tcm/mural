import os
import json
import time
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAÇÃO DOS IDS E ABAS ---
PLANILHA_ENTRADA_ID = "1UTIgbvelQP4CMNblsB9WDfNvKMdi17Sl8I7EQer_GEs"
ABA_ENTRADA = "licitacoes_2026"  # Garantido: com underline conforme sua foto!

PLANILHA_SAIDA_ID = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U"

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

def obter_servico_sheets():
    """Conecta diretamente à Google Sheets API v4."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    json_str = os.environ.get("GOOGLE_DRIVE_JSON")
    
    if json_str:
        print("Autenticando via Secret do GitHub Actions...")
        credentials_info = json.loads(json_str)
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    else:
        print("Secret não encontrada. Tentando arquivo local 'credentials.json'...")
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    return build('sheets', 'v4', credentials=creds)

def extrair_dados_ficha(url: str) -> dict:
    """Acessa a URL da ficha técnica no TCM-PA e raspa os campos."""
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

        # Contadores das Abas
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

        # Número da Licitação
        lic_num = soup.find("h5", class_="text-blue")
        if lic_num:
            dados["LICITAÇÃO"] = lic_num.get_text(strip=True)

        # Painel Esquerda
        bill_to = soup.find("div", class_="bill-to")
        if bill_to:
            for p in bill_to.find_all("p"):
                texto_p = p.get_text(separator=" ", strip=True)
                if ":" in texto_p:
                    partes = texto_p.split(":", 1)
                    chave = partes[0].replace(">", "").strip()
                    valor = partes[1].strip()

                    for col in CABECALHOS_ESPERADOS:
                        if col.lower() in chave.lower():
                            dados[col] = valor
                            break

        # Painel Direita
        bill_data = soup.find("div", class_="bill-data")
        if bill_data:
            for span in bill_data.find_all("span", class_="text-dark"):
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
    print(f"=== INICIANDO ROBÔ DE LICITAÇÕES (Modo Teste: {modo_teste}) ===")

    service = obter_servico_sheets()
    sheets = service.spreadsheets()

   # 1. Ler Coluna C da Planilha de Origem
    print(f"Lendo URLs da planilha de ORIGEM (Aba: {ABA_ENTRADA})...")
    intervalo_busca = f"{ABA_ENTRADA}!C2:C"
    
    resultado = sheets.values().get(spreadsheetId=PLANILHA_ENTRADA_ID, range=intervalo_busca).execute()
    linhas_coluna_c = resultado.get('values', [])

    # Pega qualquer link que contenha 'http' ou 'tcmpa'
    urls = []
    for row in linhas_coluna_c:
        if row and len(row) > 0:
            val = row[0].strip()
            if "tcmpa" in val or val.startswith("http"):
                urls.append(val)

    print(f"Total de URLs encontradas na Coluna C: {len(urls)}")
    
    if not urls:
        print("Nenhuma URL válida encontrada. Encerrando.")
        return

    if modo_teste:
        urls = urls[:limite_teste]
        print(f"-> MODO TESTE ATIVO: Processando apenas os {len(urls)} primeiros links.")

    # 2. Raspagem de Dados
    novas_linhas = []
    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] Extraindo: {url}")
        dados_dict = extrair_dados_ficha(url)
        linha = [dados_dict.get(col, "não informado") for col in CABECALHOS_ESPERADOS]
        novas_linhas.append(linha)
        time.sleep(1)

    # 3. Gravar na Planilha de Destino
    if novas_linhas:
        print("Gravando dados na planilha 'Abas_Detalhes_Fato'...")
        body = {'values': novas_linhas}
        sheets.values().append(
            spreadsheetId=PLANILHA_SAIDA_ID,
            range="A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        
        print(f"=== SUCESSO! {len(novas_linhas)} linhas inseridas com êxito! ===")
