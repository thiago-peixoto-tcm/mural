def extrair_dados_pagina(page, url_ficha):
    # Força a URL base limpa
    url_base = url_ficha.split("#")[0].strip()
    url_com_hash = f"{url_base}#licitacao"
    
    dados = {k: "não informado" for k in CABECALHO}
    dados["Link Ficha"] = url_ficha

    try:
        # 1. Navega para a página e aguarda a carga inicial
        page.goto(url_com_hash, wait_until="domcontentloaded", timeout=60000)
        
        # 2. Espera forçada para renderização das requisições AJAX do TCM-PA
        page.wait_for_timeout(4000)

        # 3. Se a aba não tiver carregado o conteúdo, simula o clique na aba 'Dados da Licitação'
        selector_licitacao = "a[href='#licitacao'], a:has-text('Dados da Licitação')"
        if page.is_visible(selector_licitacao):
            page.click(selector_licitacao)
            page.wait_for_timeout(2000)

        # 4. Aguarda explicitamente o surgimento de algum elemento de dados (ex: 'bill-to' ou 'address')
        try:
            page.wait_for_selector(".bill-to, address, h5.text-blue", timeout=10000)
        except Exception:
            print(f"⚠️ Alerta: Elementos principais não carregaram a tempo para {url_ficha}")

        # Pega o HTML final após a renderização do JS
        html_content = page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # --- A. ABAS SUPERIORES (Documentos, Publicidades, etc.) ---
        # Mapeamento exato de textos das abas
        abas = soup.find_all("a", class_=re.compile(r'nav-link|tab', re.I)) or soup.find_all("a")
        for a in abas:
            txt_aba = a.get_text(" ", strip=True)
            for chave_aba in ["Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos", "Aditivos"]:
                if chave_aba.lower() in txt_aba.lower():
                    # Extrai apenas os números entre parênteses ou dentro de badges
                    nums = re.findall(r'\d+', txt_aba)
                    if nums:
                        dados[chave_aba] = nums[-1]

        # --- B. MUNICÍPIO E ÓRGÃO ---
        address = soup.find("address")
        if address:
            strongs = address.find_all("strong")
            if len(strongs) >= 1:
                dados["Município"] = strongs[0].get_text(strip=True)
            if len(strongs) >= 2:
                dados["Órgão"] = strongs[1].get_text(strip=True)

        # --- C. TÍTULO / NÚMERO DA LICITAÇÃO ---
        # Procura por elementos h5 ou textos que contenham o formato #005/2026
        for h in soup.find_all(["h3", "h4", "h5", "h6", "strong", "div"]):
            txt_h = h.get_text(strip=True)
            if "#" in txt_h and "/" in txt_h:
                dados["LICITAÇÃO"] = txt_h
                break

        # --- D. CORPO PRINCIPAL DE DADOS (bill-to) ---
        bill_to = soup.find("div", class_="bill-to")
        if bill_to:
            p_list = bill_to.find_all("p")
            for p in p_list:
                texto_p = p.get_text(" ", strip=True)
                if ":" in texto_p:
                    partes = texto_p.split(":", 1)
                    chave_p = re.sub(r'^[>\s\W]+', '', partes[0]).strip().lower()
                    val_p = partes[1].strip()

                    for campo in CABECALHO:
                        if campo in ["Link Ficha", "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos", "Aditivos", "Município", "Órgão", "LICITAÇÃO"]:
                            continue
                        
                        campo_limpo = campo.lower().replace("?", "").strip()
                        if campo_limpo in chave_p or chave_p in campo_limpo:
                            dados[campo] = val_p
                            break

        # --- E. COLUNA LATERAL (bill-data) ---
        bill_data = soup.find("div", class_="bill-data")
        if bill_data:
            p_list_data = bill_data.find_all("p")
            for p in p_list_data:
                texto_p = p.get_text(" ", strip=True)
                if ":" in texto_p:
                    partes = texto_p.split(":", 1)
                    chave_p = partes[0].strip().lower()
                    val_p = partes[1].strip()

                    if "exercício" in chave_p:
                        dados["Exercício"] = val_p
                    elif "situação" in chave_p:
                        dados["Situação"] = val_p
                    elif "abertura" in chave_p:
                        dados["Abertura"] = val_p
                    elif "publicação" in chave_p:
                        dados["Publicação"] = val_p
                    elif "homologação" in chave_p:
                        dados["Homologação"] = val_p
                    elif "sigiloso" in chave_p:
                        dados["Caráter Sigiloso"] = val_p
                    elif "firmado contrato" in chave_p:
                        dados["Será Firmado Contrato"] = val_p
                    elif "contratos" in chave_p:
                        dados["Contratos_Data"] = val_p
                    elif "aditivos" in chave_p:
                        dados["Aditivos_Data"] = val_p

        return [dados[col] for col in CABECALHO]

    except Exception as e:
        print(f"❌ Erro ao extrair dados de {url_ficha}: {e}")
        return [url_ficha] + ["ERRO NA LEITURA"] * (len(CABECALHO) - 1)
