import streamlit as st
import pandas as pd
import geopandas as gpd
from utils.helpers import processar_shapefile_zip, criar_mapa_base, search_gbif_with_retries
from pygbif import occurrences as occ
from shapely.geometry import Point
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Analisar Minhas Espécies", layout="wide", page_icon="🔬")

st.title("🔬 Analisar Ocorrências de Espécies Conhecidas")
st.markdown("""
Nesta seção, você pode fazer o upload de uma lista de espécies e um shapefile de uma área de interesse. 
A ferramenta irá verificar a ocorrência de cada espécie dentro da área e em um buffer ao redor, calculando um escore de proximidade.
""")

# --- FUNÇÕES DE ANÁLISE ---

def analisar_ocorrencia_especies(df_especies, gdf_area, distancia_maxima_relevancia_km, grupo_taxon=None):
    poligono = gdf_area.geometry.unary_union
    resultados = []
    
    if 'scientificName' not in df_especies.columns:
        st.error("O arquivo Excel precisa ter uma coluna chamada 'scientificName'.")
        return pd.DataFrame()

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_especies = len(df_especies['scientificName'])

    for i, especie in enumerate(df_especies['scientificName']):
        status_text.text(f"Analisando: {especie} ({i+1}/{total_especies})")
        
        search_params = {'scientificName': especie, 'hasCoordinate': True, 'limit': 300}
        if grupo_taxon and grupo_taxon.lower() != 'qualquer':
            search_params['class'] = grupo_taxon
        
        dados_gbif = search_gbif_with_retries(search_params)
        
        if dados_gbif is None: # Se a busca falhar após as tentativas
            resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Falha na busca", 'escore_proximidade': -1, 'gbif_total_records': 0, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
            continue

        gbif_total_records = dados_gbif.get('count', 0)

        lon_ocorrencia, lat_ocorrencia = None, None
        pontos_mapa = []

        if dados_gbif['results']:
            pontos = [Point(rec['decimalLongitude'], rec['decimalLatitude']) for rec in dados_gbif['results'] if 'decimalLongitude' in rec and 'decimalLatitude' in rec]
            pontos_mapa = pontos
            
            if pontos:
                gdf_ocorrencias = gpd.GeoDataFrame(geometry=pontos, crs="EPSG:4326")
                ocorrencias_dentro = gpd.sjoin(gdf_ocorrencias, gdf_area, how="inner", predicate='within')

                if not ocorrencias_dentro.empty:
                    escore = 10
                    ocorrencia_regiao = f"Dentro da área ({len(ocorrencias_dentro)} registros)"
                    ponto_dentro = ocorrencias_dentro.geometry.iloc[0]
                    lon_ocorrencia, lat_ocorrencia = ponto_dentro.x, ponto_dentro.y
                else:
                    distancias = gdf_ocorrencias.geometry.apply(lambda ponto: poligono.distance(ponto))
                    distancia_minima_deg = distancias.min()
                    ponto_mais_proximo = gdf_ocorrencias.geometry.loc[distancias.idxmin()]
                    lon_ocorrencia, lat_ocorrencia = ponto_mais_proximo.x, ponto_mais_proximo.y
                    distancia_minima_km = distancia_minima_deg * 111.32
                    
                    if distancia_minima_km >= distancia_maxima_relevancia_km:
                        escore, ocorrencia_regiao = 0, f"Longe (>{distancia_maxima_relevancia_km:.0f} km)"
                    else:
                        escore = 9 * (1 - (distancia_minima_km / distancia_maxima_relevancia_km))
                        ocorrencia_regiao = f"Próxima ({distancia_minima_km:.1f} km)"

                resultados.append({'especie': especie, 'ocorrencia_na_regiao': ocorrencia_regiao, 'escore_proximidade': round(escore), 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': lon_ocorrencia, 'latitude_ocorrencia': lat_ocorrencia, 'pontos': pontos_mapa})
            else:
                 resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Dados insuficientes", 'escore_proximidade': -1, 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
        else:
            resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Não encontrado no GBIF", 'escore_proximidade': -1, 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
        
        progress_bar.progress((i + 1) / total_especies)

    status_text.text("Análise concluída!")
    return pd.DataFrame(resultados)

# --- LAYOUT DA PÁGINA ---

# Painel de Controle
st.sidebar.header("Painel de Controle")
uploaded_excel = st.sidebar.file_uploader("1. Carregue seu arquivo Excel (.xlsx)", type=['xlsx'], key="uploader_analise_excel")
uploaded_zip = st.sidebar.file_uploader("2. Carregue o shapefile da área (.zip)", type=['zip'], key="uploader_analise_zip")

grupos_taxon = ['Qualquer', 'Aves', 'Mammalia', 'Reptilia', 'Amphibia', 'Insecta', 'Arachnida', 'Mollusca', 'Plantae']
grupo_selecionado = st.sidebar.selectbox("3. Filtrar por Grupo Taxonômico", options=grupos_taxon)
distancia_buffer_km = st.sidebar.slider("4. Distância do buffer (km)", 10, 2000, 500, 10)

# Inicializa o session state
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None

# Botão de Análise
if st.sidebar.button("Analisar Ocorrências", type="primary", use_container_width=True):
    if uploaded_excel is None or uploaded_zip is None:
        st.warning("Por favor, carregue o arquivo de espécies e o shapefile.")
        st.session_state.analysis_results = None
    else:
        gdf_area, area_km2 = processar_shapefile_zip(uploaded_zip)
        df_especies = pd.read_excel(uploaded_excel)

        if gdf_area is not None and not df_especies.empty:
            with st.spinner('Buscando dados no GBIF e analisando...'):
                df_resultados = analisar_ocorrencia_especies(df_especies, gdf_area, distancia_buffer_km, grupo_selecionado)
            
            # Salva os resultados no session_state
            st.session_state.analysis_results = {
                "df_resultados": df_resultados,
                "df_especies": df_especies,
                "gdf_area": gdf_area,
                "area_km2": area_km2,
                "distancia_buffer_km": distancia_buffer_km
            }
        else:
            st.error("Falha ao processar os arquivos de entrada.")
            st.session_state.analysis_results = None

# ---- Seção de exibição de resultados ----
if st.session_state.analysis_results:
    results = st.session_state.analysis_results
    df_resultados = results["df_resultados"]
    df_especies = results["df_especies"]
    gdf_area = results["gdf_area"]
    area_km2 = results["area_km2"]
    distancia_buffer_km = results["distancia_buffer_km"]
    
    st.success("Análise finalizada!")

    st.header("📈 Estatísticas Gerais")
    col1, col2 = st.columns(2)
    col1.metric("Área do Projeto (km²)", f"{area_km2:,.2f}")
    col2.metric("Buffer de Proximidade (km)", f"{distancia_buffer_km} km")

    st.header("📊 Resultados Detalhados")
    df_final = pd.merge(df_especies, df_resultados.drop(columns=['pontos']), left_on='scientificName', right_on='especie', how='left')
    st.dataframe(df_final)

    # Botões de Download
    col1_dl, col2_dl = st.columns(2)
    with col1_dl:
        csv = df_final.to_csv(index=False).encode('utf-8')
        st.download_button("Baixar em CSV", csv, "analise_especies.csv", "text/csv", use_container_width=True)
    with col2_dl:
        df_geojson = df_final.dropna(subset=['longitude_ocorrencia', 'latitude_ocorrencia'])
        if not df_geojson.empty:
            gdf_export = gpd.GeoDataFrame(df_geojson, geometry=gpd.points_from_xy(df_geojson.longitude_ocorrencia, df_geojson.latitude_ocorrencia), crs="EPSG:4326")
            st.download_button("Baixar em GeoJSON", gdf_export.to_json(), "analise_especies.geojson", "application/json", use_container_width=True)

    # Mapa
    st.header("🗺️ Mapa Interativo")
    mapa = criar_mapa_base(gdf_area)
    try:
        gdf_area_proj = gdf_area.to_crs(epsg=3857)
        buffer_geom = gdf_area_proj.buffer(distancia_buffer_km * 1000).to_crs(epsg=4326)
        folium.GeoJson(buffer_geom, name=f"Buffer ({distancia_buffer_km} km)", style_function=lambda x: {'color': 'orange', 'dashArray': '5, 5', 'fillOpacity': 0.0, 'weight': 2}).add_to(mapa)
    except Exception:
        st.warning("Não foi possível gerar o buffer visual no mapa, mas a análise foi concluída.")

    for _, linha in df_resultados.iterrows():
        if linha['pontos']:
            grupo_especie = folium.FeatureGroup(name=f"{linha['especie']} ({linha['ocorrencia_na_regiao']})")
            for ponto in linha['pontos']:
                folium.CircleMarker(location=[ponto.y, ponto.x], radius=4, popup=f"<i>{linha['especie']}</i>", color='#FF5733', fill=True, fill_opacity=0.6).add_to(grupo_especie)
            grupo_especie.add_to(mapa)

    folium.LayerControl().add_to(mapa)
    st_folium(mapa, width='100%', height=500) 