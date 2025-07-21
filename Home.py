import streamlit as st

st.set_page_config(
    page_title="Página Inicial - Análise Geoespacial de Espécies",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 Bem-vindo à Ferramenta de Análise Geoespacial de Espécies")

st.markdown("""
Esta é uma aplicação interativa projetada para ajudar pesquisadores, biólogos e entusiastas da natureza a explorar a distribuição de espécies usando dados do **GBIF (Global Biodiversity Information Facility)**.
""")

st.header("Funcionalidades Disponíveis")

st.subheader("1. Analisar Minhas Espécies")
st.markdown("""
- **O que faz?** Verifica a ocorrência de uma lista de espécies que você já possui em uma área de interesse específica.
- **Como usar?** Navegue até a página **`Analisar Minhas Espécies`** no menu lateral, faça o upload de um arquivo Excel com os nomes científicos e um shapefile da sua área.
- **Resultado:** Você obterá um relatório detalhado, um mapa de proximidade e a opção de baixar os resultados em formatos CSV e GeoJSON.
""")

st.subheader("2. Buscar Novas Espécies")
st.markdown("""
- **O que faz?** Descobre quais espécies de um determinado reino (como Plantas ou Animais) foram registradas em uma área geográfica.
- **Como usar?** Vá para a página **`Buscar Novas Espécies`** no menu, carregue um shapefile da sua área de interesse e selecione o reino taxonômico.
- **Resultado:** A ferramenta retornará um mapa com todas as ocorrências encontradas, uma lista de espécies únicas e a opção de baixar esses dados.
""")

st.info("Para começar, selecione uma das funcionalidades no menu à esquerda.")

st.markdown("---")
st.write("Desenvolvido com Streamlit e ❤ por dados abertos.") 