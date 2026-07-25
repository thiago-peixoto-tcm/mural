import os
import json
import time
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- CONFIGURAÇÕES DE PLANILHA ---
PLANILHA_ENTRADA_ID = "1UTIgbvelQP4CMNblsB9WDfNvKMdi17Sl8I7EQer_GEs"
ABA_ENTRADA = "licitacoes_2026"  # Garantido: com underline!

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
    """Autentica via Service Account usando a Secret do GitHub Actions."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    json_str = os.environ.get("GOOGLE_DRIVE_JSON")
    
    if json_str:
        print("[INFO] Autenticando via Secret GOOGLE_DRIVE_JSON...")
        credentials_info = json.loads(json_str)
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    else:
        print("[INFO] Secret não encontrada no ambiente local. Buscando 'credentials.json'...")
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        
    return build('sheets', 'v4', credentials=creds)

def extrair_dados_ficha(url: str) -> dict:
    """Raspa as informações da ficha no portal do TCM-PA."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    dados = {k: "não informado" for k in CABECALHOS_ESPERADOS}
    dados["Link Ficha"] = url

    try:
        resp = requests.get(url, headers=headers, timeout=25)
        if resp.status_code != 200:
            print(f"  [AVISO] HTTP Status {resp.status_code} ao acessar {url}")
            return dados

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Contadores das Abas Superior
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

        # Número da Licitação (Título H5)
        lic_num = soup.find("h5", class_="text-blue")
        if lic_num:
            dados["LICITAÇÃO"] = lic_num.get_text(strip=True)

        # Painel Esquerdo (Dados de Cadastro)
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

        # Painel Direito (Datas e Resumos)
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
        print(f"  [ERRO] Falha na raspagem do link {url}: {e}")

    return dados

def executar_robo(modo_teste: bool = True, limite_teste: int = 5):
    print("==================================================")
    print(f"=== INICIANDO ROBÔ DE LICITAÇÕES (Teste: {modo_teste}) ===")
    print("==================================================")

    service = obter_servico_sheets()
    sheets = service.spreadsheets()

    # 1. Busca os links na coluna C da planilha de entrada
    intervalo_busca = f"{ABA_ENTRADA}!C2:C"
    print(f"[PASSO 1] Lendo a célula {intervalo_busca} da planilha ID: {PLANILHA_ENTRADA_ID}...")
    
    resultado = sheets.values().get(spreadsheetId=PLANILHA_ENTRADA_ID, range=intervalo_busca).execute()
    linhas_coluna_c = resultado.get('values', [])

    print(f"[PASSO 1] Total de linhas brutas retornadas da Coluna C: {len(linhas_coluna_c)}")

    urls = []
    for row in linhas_coluna_c:
        if row and len(row) > 0:
            link = str(row[0]).strip()
            if "http" in link or "tcmpa" in link:
                urls.append(link)

    print(f"[PASSO 1] URLs válidas identificadas para processamento: {len(urls)}")

    if not urls:
        print("[ALERTA] Nenhuma URL válida foi encontrada na Coluna C. Encerrando o fluxo.")
        return

    if modo_teste:
        urls = urls[:limite_teste]
        print(f"[MODO TESTE] Limitando a execução aos primeiros {len(urls)} links.")

    # 2. Raspagem dos links
    print(f"\n[PASSO 2] Iniciando extração dos {len(urls)} links...")
    novas_linhas = []
    for idx, url in enumerate(urls, start=1):
        print(f"  -> [{idx}/{len(urls)}] Processando: {url}")
        dados_dict = extrair_dados_ficha(url)
        linha = [dados_dict.get(col, "não informado") for col in CABECALHOS_ESPERADOS]
        novas_linhas.append(linha)
        time.sleep(1)

    # 3. Gravação dos dados extraídos na planilha de destino
    if novas_linhas:
        print(f"\n[PASSO 3] Enviando {len(novas_linhas)} linhas para a planilha destino ID: {PLANILHA_SAIDA_ID}...")
        body = {'values': novas_linhas}
        
        resposta = sheets.values().append(
            spreadsheetId=PLANILHA_SAIDA_ID,
            range="A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        
        print("==================================================")
        print("=== SUCESSO! Dados gravados na planilha de destino. ===")
        print("==================================================")

if __name__ == "__main__":
    modo_env = os.environ.get("MODO_TESTE", "true").lower() == "true"
    executar_robo(modo_teste=modo_env, limite_teste=5)
