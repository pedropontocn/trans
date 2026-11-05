"""Trechos da interface do diagnóstico e do ofício no app.py 1.11 (barra lateral e painel). Referência, não roda sozinho."""

# --- BARRA LATERAL: seção "2. Diagnóstico de lacunas" ---

if False:  # noqa: SIM108 (bloco de referência)
        st.markdown("---")
        st.header("2. Diagnóstico de lacunas")
        st.caption("Antes do debate: o que falta no relatório, e a minuta de ofício para pedir ao órgão.")
        for chave, padrao in [("of_secretaria", ""), ("of_titular", ""), ("of_numero", ""), ("of_signatario", ""),
                              ("of_cargo", "Coordenador(a) da Equipe de Transição"), ("of_data_relatorio", ""),
                              ("of_canal", "no processo SEI de resposta dessa Pasta, remetido à SECC/TRANSIÇÃO, conforme o "
                                           "Ofício Circular SECC/TRANSICAO nº 1/2026"),
                              ("of_oficios", ["02", "06", "07", "08"])]:
            st.session_state.setdefault(chave, padrao)
        with st.expander("Dados do ofício"):
            st.text_input("Secretaria analisada", key="of_secretaria", placeholder="ex.: Secretaria de Estado das Cidades")
            st.multiselect("Ofícios a conferir", list(OFICIOS), key="of_oficios",
                           format_func=lambda n: f"Ofício nº {n}/2026 – {OFICIOS[n]['tema']}",
                           help="Os ofícios já enviados a essa secretaria. O diagnóstico confere, item por item, se o relatório "
                                "os atende. Vêm marcados conforme a pasta.")
            st.radio("Tratamento do(a) titular", ["Senhor", "Senhora"], horizontal=True, key="of_tratamento")
            st.text_input("Nome do(a) titular", key="of_titular", placeholder="Em branco, a minuta deixa o campo para preencher")
            st.text_input("Número do ofício", key="of_numero", placeholder="___/2026")
            st.text_input("Quem assina", key="of_signatario", placeholder="Nome de quem assina")
            st.text_input("Cargo de quem assina", key="of_cargo")
            st.text_input("Como responder", key="of_canal",
                          placeholder="ex.: por meio do processo SEI nº ... ou ao e-mail ...")
            st.number_input("Prazo de resposta (dias úteis)", min_value=1, max_value=30, value=5, key="of_prazo")
        botao_diagnostico = st.button("🔎 Diagnosticar lacunas do relatório", width="stretch",
                                      disabled=not st.session_state.get("texto_relatorio"))
        refazer_diagnostico = st.session_state.pop("diag_refazer", False)
        if botao_diagnostico or refazer_diagnostico:
            with st.spinner("Procurando o que falta no relatório..."):
                try:
                    anteriores_debate = [i for i in (st.session_state.get("diagnostico") or {}).get("itens", [])
                                         if i["tipo"] == "questao_debate"]
                    novo_diag = diagnosticar(modelo, st.session_state["texto_relatorio"],
                                             st.session_state.get("texto_base", ""), montar_cenario(),
                                             st.session_state.get("of_oficios", []), reaproveitar=not refazer_diagnostico)
                    ja = {_norm(i["pedido"])[:80] for i in novo_diag["itens"]}
                    novo_diag["itens"] += [i for i in anteriores_debate if _norm(i["pedido"])[:80] not in ja]
                    st.session_state["diagnostico"] = novo_diag
                except Exception as e:
                    st.error(f"Não foi possível fazer o diagnóstico: {e}")
        diag_atual = st.session_state.get("diagnostico")
        if (diag_atual or {}).get("reaproveitado"):
            st.caption("♻️ Diagnóstico reaproveitado de um anterior com os mesmos insumos, sem nova chamada ao modelo.")
            st.button("Refazer o diagnóstico do zero", width="stretch",
                      on_click=lambda: st.session_state.update(diag_refazer=True))
        criticas_pendentes = [i for i in (diag_atual or {}).get("itens", [])
                              if i["verificado"] and i["materialidade"] == "critica" and i["tipo"] != "questao_debate"]


# --- PAINEL ---

# --- DIAGNÓSTICO DE LACUNAS (painel) --------------------------------------------------

diag = st.session_state.get("diagnostico")
if diag:
    with st.expander("🔎 Diagnóstico de lacunas e minuta de ofício", expanded=not st.session_state.get("resultado")):
        itens = diag["itens"]
        conferidas = [i for i in itens if i["verificado"]]
        atend = diag.get("atendimento") or []
        if atend:
            st.markdown("**Atendimento aos ofícios já enviados**")
            resumo_of = []
            for num in diag.get("oficios") or []:
                linhas_of = [a for a in atend if a["oficio"] == num]
                resumo_of.append({"Ofício": f"nº {num}/2026 – {OFICIOS[num]['tema']}",
                                  "Atendidos": sum(a["situacao"] == "atendido" for a in linhas_of),
                                  "Parciais": sum(a["situacao"] == "parcial" for a in linhas_of),
                                  "Não atendidos": sum(a["situacao"] == "nao_atendido" for a in linhas_of),
                                  "Não avaliados": sum(a["situacao"] == "nao_avaliado" for a in linhas_of)})
            st.dataframe(resumo_of, hide_index=True, width="stretch")
            with st.expander("Ver item por item"):
                icones = {"atendido": "🟢", "parcial": "🟡", "nao_atendido": "🔴", "nao_avaliado": "⚪"}
                for a in atend:
                    st.markdown(f"{icones[a['situacao']]} **{a['item_id']}** {a['item']}"
                                + (f" — “{a['evidencia']}”" if a["evidencia"] else "")
                                + (f"  \n⚠️ {a['alerta']}" if a["alerta"] else ""))
        if diag.get("so_debate"):
            st.caption("O diagnóstico de lacunas não foi rodado; a tabela traz só os pedidos que saíram das questões em "
                       "aberto do debate. Para incluir as lacunas do relatório, clique em \"Diagnosticar lacunas\".")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Lacunas críticas", sum(1 for i in conferidas if i["materialidade"] == "critica"))
        d2.metric("Relevantes", sum(1 for i in conferidas if i["materialidade"] == "relevante"))
        d3.metric("Acessórias", sum(1 for i in conferidas if i["materialidade"] == "acessoria"))
        d4.metric("Sem evidência conferida", len(itens) - len(conferidas),
                  help="O trecho citado como evidência não foi encontrado no relatório nem na base. Fica fora do ofício, "
                       "a menos que você marque.")
        custo_diag, _ = custo_estimado(diag.get("uso") or [])
        st.caption(f"Diagnóstico feito por {diag['modelo']} · custo estimado US$ {custo_diag:.2f}".replace(".", ",", 1)
                   + (" · com a base de projetos" if diag.get("com_base") else " · sem base de projetos (as omissões de "
                      "obras e projetos só aparecem se a base for enviada)")
                   + (" · ⚠️ a resposta foi cortada; pode faltar algum item" if diag.get("cortado") else ""))
        if not itens:
            st.success("O diagnóstico não encontrou lacunas a pedir ao órgão.")
        else:
            import pandas as pd
            tabela = pd.DataFrame([{
                "Incluir": i["incluir"], "Materialidade": ROTULO_MATERIALIDADE[i["materialidade"]],
                "Tipo": TIPOS_LACUNA[i["tipo"]], "Seção": i["secao"], "Item": i["item"], "Pedido ao órgão": i["pedido"],
                "Evidência": ("✓ " if i["verificado"] else "✗ ") + i["evidencia"]} for i in itens])
            editada = st.data_editor(
                tabela, key="editor_lacunas", width="stretch", hide_index=True,
                disabled=["Materialidade", "Tipo", "Seção", "Item", "Evidência"],
                column_config={"Incluir": st.column_config.CheckboxColumn(help="Entra no ofício"),
                               "Pedido ao órgão": st.column_config.TextColumn(width="large", help="Pode editar o texto"),
                               "Evidência": st.column_config.TextColumn(help="✓ conferida no relatório ou na base; ✗ não encontrada")})
            for k, linha in editada.iterrows():
                itens[k]["incluir"], itens[k]["pedido"] = bool(linha["Incluir"]), str(linha["Pedido ao órgão"])
            with st.expander("Por que cada item falta"):
                for i in itens:
                    st.markdown(f"- **{i['item']}** ({TIPOS_LACUNA[i['tipo']].lower()}, {i['secao']}): {i['por_que_falta']}"
                                + (f" — *evidência na {i['onde']}*" if i["verificado"] else " — *evidência não encontrada*"))
            escolhidos = [i for i in itens if i["incluir"]]
            dados_oficio = {
                "secretaria": st.session_state.get("of_secretaria", "").strip(),
                "titular": st.session_state.get("of_titular", "").strip(),
                "tratamento": st.session_state.get("of_tratamento", "Senhor"),
                "numero": st.session_state.get("of_numero", "").strip(),
                "referencia": referencia_oficios(sorted({i["oficio"] for i in itens if i["incluir"] and i.get("oficio")}),
                                                 st.session_state.get("of_data_relatorio", "")),
                "data_relatorio": st.session_state.get("of_data_relatorio", ""),
                "signatario": st.session_state.get("of_signatario", "").strip(),
                "cargo_signatario": st.session_state.get("of_cargo", "").strip(),
                "canal": st.session_state.get("of_canal", "").strip(),
                "prazo_dias": st.session_state.get("of_prazo", 5),
                "data_oficio": date.today(),
            }
            oficio, limite = gerar_oficio_docx(dados_oficio, escolhidos) if escolhidos else (None, None)
            o1, o2 = st.columns(2)
            with o1:
                st.download_button("⬇️ Minuta de ofício (.docx)", data=oficio or b"", disabled=not escolhidos,
                                   file_name=f"oficio_transicao_{slug_arquivo(dados_oficio['secretaria'])}.docx",
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                   width="stretch", type="primary")
            with o2:
                st.download_button("⬇️ Matriz de lacunas (.csv)", data=matriz_lacunas_csv(itens),
                                   file_name="matriz_de_lacunas.csv", width="stretch")
            if escolhidos:
                st.caption(f"{len(escolhidos)} pedido(s) no ofício. Prazo: {dados_oficio['prazo_dias']} dias úteis a partir "
                           f"de hoje, até {limite:%d/%m/%Y} (estimativa com feriados nacionais e do RJ; confira o calendário "
                           "oficial). Preencha os dados do ofício na barra lateral e revise o texto antes de assinar.")
            else:
                st.caption("Marque ao menos um item para gerar o ofício.")
