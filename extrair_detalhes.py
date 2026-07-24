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
    "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos",
    "Aditivos", "LICITAÇÃO", "Nº do Processo Administrativo", "Regime",
    "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",
    "Observação", "Há itens exclusivos para EPP/ME?",
    "Há cote de participação para EPP/ME?", "Percentual de participação para EPP/ME",
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?",
    "Exercício", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",
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
        print(f"🧪 [MODO TESTE ATIVO] Executando apenas para as primeiras {LIMITE_TESTE} linhas.")
        return links_validos[:LIMITE_TESTE]
    return links_validos

def formatar_url_licitacao(url):
    """Garante que a URL termine exatamente com #licitacao."""
    url_limpa = url.split("#")[0].strip()
    return f"{url_limpa}#licitacao"

def extrair_dados_pagina(page, url_ficha):
    url_com_hash = formatar_url_licitacao(url_ficha)
    dados = {k: "não informado" for k in CABECALHO}
    dados["Link Ficha"] = url_ficha

    try:
        # Abre a página no navegador real e aguarda o carregamento dos seletores DOM
        page.goto(url_com_hash, wait_until="domcontentloaded", timeout=40000)
        
        # Aguarda 2 segundos adicionais para renderização do JavaScript do TCM
        page.wait_for_timeout(2000)

        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # --- 1 a 6: Abas Superiores ---
        try:
            resumo_badges = soup.find_all("span", class_="resumo-qtd")
            if len(resumo_badges) >= 6:
                dados["Documentos"] = resumo_badges[0].get_text(strip=True)
                dados["Publicidades"] = resumo_badges[1].get_text(strip=True)
                dados["Participantes"] = resumo_badges[2].get_text(strip=True)
                dados["Lotes & Itens"] = resumo_badges[3].get_text(strip=True)
                dados["Contratos"] = resumo_badges[4].get_text(strip=True)
                dados["Aditivos"] = resumo_badges[5].get_text(strip=True)
        except Exception:
            pass

        # --- 7: Número da Licitação ---
        try:
            h5_lic = soup.find("h5", class_="text-blue")
            if h5_lic:
                dados["LICITAÇÃO"] = h5_lic.get_text(strip=True)
        except Exception:
            pass

        # --- 8 a 18: Bloco Principal (bill-to) ---
        try:
            bill_to = soup.find("div", class_="bill-to")
            if bill_to:
                for p in bill_to.find_all("p"):
                    texto = p.get_text(" ", strip=True)
                    if ":" in texto:
                        chave_bruta, valor = texto.split(":", 1)
                        chave_limpa = re.sub(r'^[>\s\W]+', '', chave_bruta).strip().lower()
                        valor_limpo = valor.strip()
                        
                        for campo_ref in CABECALHO[8:19]:
                            if campo_ref.lower() in chave_limpa:
                                dados[campo_ref] = valor_limpo
                                break
        except Exception:
            pass

        # --- 19 a 26: Bloco Lateral (bill-data) ---
        try:
            bill_data = soup.find("div", class_="bill-data")
            if bill_data:
                mapeamento = [
                    ("Exercício", "Exercício"), ("Abertura", "Abertura"),
                    ("Publicação", "Publicação"), ("Homologação", "Homologação"),
                    ("Caráter Sigiloso", "Caráter Sigiloso"), ("Será Firmado Contrato", "Será Firmado Contrato"),
                    ("Contratos", "Contratos_Data"), ("Aditivos", "Aditivos_Data")
                ]
                for p in bill_data.find_all("p"):
                    txt = p.get_text(" ", strip=True)
                    for rotulo, chave_dest in mapeamento:
                        if rotulo.lower() in txt.lower() and ":" in txt:
                            _, val = txt.split(":", 1)
                            dados[chave_dest] = val.strip()
                            break
        except Exception:
            pass

        return [dados[col] for col in CABECALHO]

    except Exception as e:
        print(f"⚠️ Erro ao carregar {url_com_hash}: {e}")
        return [url_ficha] + ["ERRO / BLOQUEIO"] * 26

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
        # Inicia um navegador real
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
        page = context.new_page()

        print(f"🚀 Processando {total} fichas com renderização de JavaScript...")
        for idx, url in enumerate(links, 1):
            print(f"⚡ [{idx}/{total}] Carregando página: {url}")
            linha = extrair_dados_pagina(page, url)
            resultados.append(linha)
            time.sleep(1) # Pausa amigável entre páginas

        browser.close()

    print("📤 Enviando resultados para a planilha 'Abas_Detalhes_Fato'...")
    sheet_destino = client.open_by_key(DESTINO_SPREADSHEET_ID).sheet1
    sheet_destino.clear()
    sheet_destino.update('A1', [CABECALHO])
    sheet_destino.append_rows(resultados)

    print("🎉 Teste concluído com sucesso! Verifique a planilha 'Abas_Detalhes_Fato'.")

if __name__ == "__main__":
    executar()
