import streamlit as st
import pandas as pd
import geopandas as gpd
from utils.helpers import processar_shapefile_zip, criar_mapa_base, buscar_com_paginacao, get_plant_traits
from streamlit_folium import st_folium
import folium
import plotly.express as px

st.set_page_config(page_title="Buscar Novas Espécies", layout="wide", page_icon="🔎")

st.title("🔎 Busca Avançada de Espécies por Região")
st.markdown("""
Forneça um shapefile. A ferramenta encontrará o **ponto central** da sua área e buscará espécies dentro de um **raio circular (buffer)** 
que você definir, usando paginação para obter milhares de registros do GBIF.
""")

# --- FUNÇÕES DE PROCESSAMENTO ---
def processar_resultados_gbif(resultados):
    """Converte a lista de resultados do GBIF em um DataFrame detalhado."""
    dados_coletados = []
    for rec in resultados:
        info = {
            'ID_GBIF': rec.get('gbifID'),
            'Nome_Cientifico': rec.get('scientificName'),
            'Reino': rec.get('kingdom'),
            'Familia': rec.get('family'),
            'Data_Coleta': rec.get('eventDate'),
            'Pais': rec.get('countryCode'),
            'Latitude': rec.get('decimalLatitude'),
            'Longitude': rec.get('decimalLongitude'),
            'Coletor': rec.get('recordedBy'),
            'Tipo_Registro': rec.get('basisOfRecord'),
            'Link_GBIF': f"https://www.gbif.org/occurrence/{rec.get('gbifID', '')}",
            'Chave_Especie': rec.get('speciesKey')
        }
        dados_coletados.append(info)
    return pd.DataFrame(dados_coletados)

# --- LAYOUT DA PÁGINA ---
st.sidebar.header("Painel de Controle")
uploaded_zip = st.sidebar.file_uploader("1. Carregue o shapefile da área (.zip)", type=['zip'], key="uploader_busca")

reinos = {"Plantas (Plantae)": 6, "Animais (Animalia)": 1, "Fungos (Fungi)": 5}
reino_selecionado = st.sidebar.selectbox("2. Selecione o Reino para a busca", options=list(reinos.keys()))

buffer_km = st.sidebar.slider(
    "3. Raio de busca a partir do centro (km)", 1, 1000, 10, 5,
    help="Define o raio do círculo de busca a partir do ponto central da sua área."
)

limit = st.sidebar.number_input("4. Limite máximo de registros", 100, 50000, 5000, 100)

if 'search_results' not in st.session_state:
    st.session_state.search_results = None

if st.sidebar.button("Buscar Espécies", type="primary", use_container_width=True):
    if uploaded_zip is None:
        st.warning("Por favor, carregue o arquivo .zip do shapefile.")
        st.session_state.search_results = None
    else:
        gdf_area, area_km2 = processar_shapefile_zip(uploaded_zip)
        
        if gdf_area is not None:
            st.info(f"Calculando área de busca com raio de {buffer_km} km a partir do centroide...")
            gdf_buffer_para_busca = None
            try:
                # 1. Encontra o ponto central (centroide)
                ponto_central = gdf_area.geometry.unary_union.centroid
                lat, lon = ponto_central.y, ponto_central.x
                print(lat, lon)

                # 2. Cria um GeoDataFrame para o ponto para poder projetá-lo
                gdf_ponto = gpd.GeoDataFrame([1], geometry=[ponto_central], crs="EPSG:4326")

                # 3. Define e aplica uma projeção Azimutal Equidistante para um buffer preciso em metros
                crs_projetado_str = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
                ponto_projetado = gdf_ponto.to_crs(crs_projetado_str)

                # 4. Cria o buffer circular em metros
                buffer_projetado = ponto_projetado.buffer(buffer_km * 1000)

                # 5. Converte o buffer de volta para o sistema de coordenadas padrão (WGS84)
                gdf_buffer_para_busca = buffer_projetado.to_crs("EPSG:4326")

            except Exception as e:
                st.error(f"Não foi possível criar a área de busca circular: {e}")
                st.stop()

            status_placeholder = st.empty()
            resultados_brutos = buscar_com_paginacao(gdf_buffer_para_busca, reinos[reino_selecionado], limit, status_placeholder)
            
            if not resultados_brutos:
                st.warning("Nenhuma ocorrência encontrada para os critérios de busca.")
                st.session_state.search_results = None
            else:
                df_resultados = processar_resultados_gbif(resultados_brutos)

                if reino_selecionado == "Plantas (Plantae)" and not df_resultados.empty:
                    species_names = df_resultados['Nome_Cientifico'].unique().tolist()
                    plant_traits = get_plant_traits(species_names)
                    df_resultados['Forma_de_Vida'] = df_resultados['Nome_Cientifico'].map(plant_traits).fillna('Não categorizado')

                st.session_state.search_results = {
                    "df": df_resultados,
                    "gdf_area": gdf_area, # A área original para visualização
                    "area_km2": area_km2,
                    "gdf_buffer": gdf_buffer_para_busca, # A área de busca para o mapa
                    "buffer_km": buffer_km
                }
        else:
            st.error("Falha ao processar o shapefile.")
            st.session_state.search_results = None

# ---- Seção de exibição de resultados ----
if st.session_state.search_results:
    results = st.session_state.search_results
    df_resultados = results["df"]
    
    st.header("📈 Resumo da Busca")
    col1, col2, col3 = st.columns(3)
    col1.metric("Área Original do Shapefile (km²)", f"{results['area_km2']:,.2f}")
    col2.metric("Total de Ocorrências Encontradas", f"{len(df_resultados):,}")
    col3.metric("Espécies Únicas", f"{df_resultados['Nome_Cientifico'].nunique():,}")

    # Gráfico de formas de vida para plantas
    if 'Forma_de_Vida' in df_resultados.columns:
        st.header("🌿 Formas de Vida (Plantas)")
        life_form_counts = df_resultados['Forma_de_Vida'].value_counts().reset_index()
        life_form_counts.columns = ['Forma_de_Vida', 'Contagem']
        
        fig = px.bar(life_form_counts, 
                     x='Forma_de_Vida', 
                     y='Contagem',
                     title='Distribuição de Formas de Vida das Plantas Encontradas',
                     labels={'Contagem': 'Número de Ocorrências', 'Forma_de_Vida': 'Forma de Vida'},
                     color='Forma_de_Vida')
        st.plotly_chart(fig, use_container_width=True)


    st.header("🗺️ Mapa de Ocorrências")
    mapa = criar_mapa_base(results["gdf_area"]) # Mostra a área original
    
    # Adiciona o buffer circular que foi usado na busca
    if results["gdf_buffer"] is not None:
        folium.GeoJson(
            results["gdf_buffer"].to_json(),
            name=f"Área de Busca ({results['buffer_km']} km de raio)",
            style_function=lambda x: {'color': 'orange', 'dashArray': '5, 5', 'fillOpacity': 0.1, 'weight': 2},
            tooltip=f"Raio de busca: {results['buffer_km']} km"
        ).add_to(mapa)

    df_geo = df_resultados.dropna(subset=['Latitude', 'Longitude'])
    if not df_geo.empty:
        for _, row in df_geo.iterrows():
            popup = f"<b>{row['Nome_Cientifico']}</b><br>Família: {row['Familia']}<br>Data: {row['Data_Coleta']}"
            folium.CircleMarker(
                location=[row['Latitude'], row['Longitude']], radius=3,
                popup=folium.Popup(popup, max_width=300),
                color='#228B22', fill=True, fill_opacity=0.7
            ).add_to(mapa)
    
    folium.LayerControl().add_to(mapa)
    st_folium(mapa, width='100%', height=500)
    
    st.header("📋 Tabela de Registros Detalhados")
    st.dataframe(df_resultados)
    
    col1_dl, col2_dl = st.columns(2)
    with col1_dl:
        csv = df_resultados.to_csv(index=False).encode('utf-8')
        st.download_button("Baixar Tabela (CSV)", csv, "relatorio_gbif_detalhado.csv", "text/csv", use_container_width=True)
    with col2_dl:
        df_geo_dl = df_resultados.dropna(subset=['Longitude', 'Latitude']).copy()
        if not df_geo_dl.empty:
            gdf_export = gpd.GeoDataFrame(
                df_geo_dl, geometry=gpd.points_from_xy(df_geo_dl.Longitude, df_geo_dl.Latitude), crs="EPSG:4326"
            )
            st.download_button("Baixar Mapa (GeoJSON)", gdf_export.to_json(), "relatorio_gbif_detalhado.geojson", "application/json", use_container_width=True) 