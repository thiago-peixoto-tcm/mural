import re
import time
import gspread
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google.oauth2.service_account import Credentials

# ==============================================================================
# ⚙️ CONFIGURAÇÃO DE TESTE
MODO_TESTE = True
LIMITE_TESTE = 10
# ==============================================================================

ORIGEM_SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
DESTINO_SPREADSHEET_ID = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U"

CABECALHO = [
    "Link Ficha",
    "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos", "Aditivos",
    "Município", "Órgão", "LICITAÇÃO", 
    "Nº do Processo Administrativo", "Legislação Aplicável", "Modalidade", "Tipo", "Regime",
    "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",
    "Observação", "Há itens exclusivos para EPP/ME?",
    "Há cote de participação para EPP/ME?", "Percentual de participação para EPP/ME",
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?",
    "Exercício", "Situação", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",
    "Será Firmado Contrato", "Contratos_Data", "Aditivos_Data"
]

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(credentials)

def obter_links_origem(client):
    sheet = client.open_by_key(ORIGEM_SPREADSHEET_ID).sheet1
    dados = sheet.get_all_records()
    links = [str(linha.get("Link Ficha", "")).strip() for linha in dados if linha.get("Link Ficha")]
    links_validos = [url for url in links if url.startswith("http")]

    if MODO_TESTE:
        print(f"🧪 [MODO TESTE ATIVO] Executando para as primeiras {LIMITE_TESTE} linhas.")
        return links_validos[:LIMITE_TESTE]
    return links_validos

def formatar_url_licitacao(url):
    url_limpa = url.split("#")[0].strip()
    return f"{url_limpa}#licitacao"

def extrair_dados_pagina(page, url_ficha):
    url_com_hash = formatar_url_licitacao(url_ficha)
    dados = {k: "não informado" for k in CABECALHO}
    dados["Link Ficha"] = url_ficha

    try:
        page.goto(url_com_hash, wait_until="networkidle", timeout=60000)
        
        # 🟢 ESPERA CRÍTICA: Aguarda o AJAX carregar o título da licitação na tela
        try:
            page.wait_for_selector(".bill-to", timeout=15000)
        except Exception:
            # Caso não encontre de primeira, força um clique na aba "Dados da Licitação" se existir
            if page.is_visible("a[href='#licitacao']"):
                page.click("a[href='#licitacao']")
                page.wait_for_timeout(2000)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # --- 1: Abas Superiores (Estatísticas/Contagens) ---
        mapa_abas = {
            "Documentos": "#documentos",
            "Publicidades": "#publicidades",
            "Participantes": "#participantes",
            "Lotes & Itens": "#lotes-itens",
            "Contratos": "#contratos",
            "Aditivos": "#aditivos"
        }
        for campo, href in mapa_abas.items():
            aba = soup.find("a", href=href)
            if aba:
                # Procura por badge ou label que contenha a contagem
                badge = aba.find(class_=re.compile(r'(badge|label)'))
                if badge:
                    dados[campo] = badge.get_text(strip=True)

        # --- 2: Município e Órgão ---
        address = soup.find("address")
        if address:
            strongs = address.find_all("strong")
            if len(strongs) >= 1:
                dados["Município"] = strongs[0].get_text(strip=True)
            if len(strongs) >= 2:
                dados["Órgão"] = strongs[1].get_text(strip=True)

        # --- 3: Número da Licitação ---
        # No site aparece como h5 ou h3 com o ID/Número da Licitação (ex: #005/2026-CMAC)
        h_lic = soup.find(re.compile(r'^h[1-6]'), text=re.compile(r'#|\bLICITAÇÃO\b', re.IGNORECASE))
        if not h_lic:
            h_lic = soup.find("h5", class_="text-blue")
        if h_lic:
            dados["LICITAÇÃO"] = h_lic.get_text(strip=True)

        # --- 4: Bloco Principal (bill-to) ---
        bill_to = soup.find("div", class_="bill-to")
        if bill_to:
            for p in bill_to.find_all("p"):
                texto = p.get_text(" ", strip=True)
                if ":" in texto:
                    chave_bruta, valor = texto.split(":", 1)
                    chave_limpa = re.sub(r'^[>\s\W]+', '', chave_bruta).strip().lower()
                    valor_limpo = valor.strip()

                    for campo_ref in CABECALHO:
                        if campo_ref in ["Link Ficha", "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos", "Aditivos", "Município", "Órgão", "LICITAÇÃO"]:
                            continue
                        
                        # Normalização de strings para comparação flexível
                        ref_low = campo_ref.lower().replace("?", "").strip()
                        if ref_low in chave_limpa or chave_limpa in ref_low:
                            dados[campo_ref] = valor_limpo
                            break

        # --- 5: Bloco Lateral (bill-data) ---
        bill_data = soup.find("div", class_="bill-data")
        if bill_data:
            for p in bill_data.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if ":" in txt:
                    chave, val = txt.split(":", 1)
                    chave_limpa = chave.strip().lower()
                    valor_limpo = val.strip()

                    if "exercício" in chave_limpa:
                        dados["Exercício"] = valor_limpo
                    elif "situação" in chave_limpa:
                        dados["Situação"] = valor_limpo
                    elif "abertura" in chave_limpa:
                        dados["Abertura"] = valor_limpo
                    elif "publicação" in chave_limpa:
                        dados["Publicação"] = valor_limpo
                    elif "homologação" in chave_limpa:
                        dados["Homologação"] = valor_limpo
                    elif "sigiloso" in chave_limpa:
                        dados["Caráter Sigiloso"] = valor_limpo
                    elif "firmado contrato" in chave_limpa:
                        dados["Será Firmado Contrato"] = valor_limpo
                    elif "contratos" in chave_limpa:
                        dados["Contratos_Data"] = valor_limpo
                    elif "aditivos" in chave_limpa:
                        dados["Aditivos_Data"] = valor_limpo

        return [dados[col] for col in CABECALHO]

    except Exception as e:
        print(f"⚠️ Erro ao processar {url_com_hash}: {e}")
        return [url_ficha] + ["ERRO / TEMPO EXCEDIDO"] * (len(CABECALHO) - 1)

def executar():
    print("🔌 Conectando ao Google Sheets...")
    client = conectar_google_sheets()

    print("📖 Lendo links da planilha de origem...")
    links = obter_links_origem(client)
    total = len(links)

    if not links:
        print("⚠️ Nenhum link encontrado.")
        return

    resultados = []
    
    print("🌐 Iniciando o Navegador Chromium (Playwright)...")
    with sync_playwright() as p:
        # Abre o navegador visível (headless=False) se quiser depurar visualmente
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        print(f"🚀 Processando {total} fichas...")
        for idx, url in enumerate(links, 1):
            print(f"⚡ [{idx}/{total}] Carregando: {url}")
            linha = extrair_dados_pagina(page, url)
            resultados.append(linha)
            time.sleep(1)

        browser.close()

    print("📤 Gravando dados na planilha de destino...")
    sheet_destino = client.open_by_key(DESTINO_SPREADSHEET_ID).sheet1
    sheet_destino.clear()
    sheet_destino.update('A1', [CABECALHO])
    sheet_destino.append_rows(resultados)

    print("🎉 Concluído com sucesso!")

if __name__ == "__main__":
    executar()
