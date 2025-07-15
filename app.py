import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon
from pygbif import occurrences as occ
import folium
from streamlit_folium import st_folium
import zipfile
import io
import os
import tempfile

def processar_shapefile_zip(zip_file):
    """
    Extrai um arquivo zip em memória, encontra o .shp e o lê com GeoPandas.
    """
    with tempfile.TemporaryDirectory() as tempdir:
        with zipfile.ZipFile(zip_file) as zf:
            zf.extractall(tempdir)
            shp_path = None
            for filename in os.listdir(tempdir):
                # Encontre o arquivo .shp principal (não um arquivo de metadados como .shp.xml)
                if filename.endswith('.shp') and not filename.endswith('.xml'):
                    shp_path = os.path.join(tempdir, filename)
                    break
            if shp_path:
                gdf = gpd.read_file(shp_path)
                return gdf
            else:
                st.error("Nenhum arquivo .shp encontrado no arquivo .zip.")
                return None

def analisar_ocorrencia_especies(df_especies, gdf_area, distancia_maxima_relevancia_km, grupo_taxon=None):
    """
    Analisa a ocorrência de espécies em uma área definida por um polígono.

    Args:
        df_especies (pd.DataFrame): DataFrame com os nomes das espécies.
        gdf_area (gpd.GeoDataFrame): GeoDataFrame da área do projeto.
        distancia_maxima_relevancia_km (float): Distância em km para o cálculo do buffer de proximidade.
        grupo_taxon (str, optional): Classe taxonômica para filtrar a busca (ex: 'Aves', 'Mammalia'). Defaults to None.

    Returns:
        pandas.DataFrame: DataFrame com os resultados da análise.
    """
    # Garante que o polígono seja uma geometria única para a análise
    poligono = gdf_area.geometry.unary_union

    resultados = []
    
    # Verifica se a coluna 'scientificName' existe
    if 'scientificName' not in df_especies.columns:
        st.error("O arquivo Excel precisa ter uma coluna chamada 'scientificName'.")
        st.stop()
        
    total_especies = len(df_especies['scientificName'])
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, especie in enumerate(df_especies['scientificName']):
        status_text.text(f"Analisando espécie: {especie} ({i+1}/{total_especies})")

        gbif_total_records = 0
        search_params = {
            'scientificName': especie,
            'hasCoordinate': True,
            'limit': 300
        }
        if grupo_taxon and grupo_taxon.lower() != 'qualquer':
            search_params['class'] = grupo_taxon

        try:
            dados_gbif = occ.search(**search_params)
            gbif_total_records = dados_gbif.get('count', 0)
        except Exception as e:
            st.warning(f"Não foi possível buscar dados para '{especie}' no GBIF. Erro: {e}")
            resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Erro na busca", 'escore_proximidade': -1, 'gbif_total_records': 0, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
            continue

        pontos_ocorrencia_para_mapa = []
        lon_ocorrencia, lat_ocorrencia = None, None
        if dados_gbif['results']:
            pontos_ocorrencia = [Point(rec['decimalLongitude'], rec['decimalLatitude']) for rec in dados_gbif['results'] if 'decimalLongitude' in rec and 'decimalLatitude' in rec]
            pontos_ocorrencia_para_mapa = pontos_ocorrencia
            
            if pontos_ocorrencia:
                gdf_ocorrencias = gpd.GeoDataFrame(geometry=pontos_ocorrencia, crs="EPSG:4326")
                
                # Garante que o CRS de ambos os GeoDataFrames sejam compatíveis antes do sjoin
                if gdf_ocorrencias.crs != gdf_area.crs:
                    gdf_ocorrencias = gdf_ocorrencias.to_crs(gdf_area.crs)
                
                ocorrencias_dentro = gpd.sjoin(gdf_ocorrencias, gdf_area, how="inner", predicate='within')

                if not ocorrencias_dentro.empty:
                    escore = 10
                    ocorrencia_regiao = f"Dentro da área ({len(ocorrencias_dentro)} registros)"
                    ponto_dentro = ocorrencias_dentro.geometry.iloc[0]
                    lon_ocorrencia, lat_ocorrencia = ponto_dentro.x, ponto_dentro.y
                else:
                    distancias = gdf_ocorrencias.geometry.apply(lambda ponto: poligono.distance(ponto))
                    distancia_minima = distancias.min()
                    ponto_mais_proximo = gdf_ocorrencias.geometry.loc[distancias.idxmin()]
                    lon_ocorrencia, lat_ocorrencia = ponto_mais_proximo.x, ponto_mais_proximo.y
                    
                    # Converte a distância para km (aproximado)
                    distancia_minima_km = distancia_minima * 111.32
                    
                    if distancia_minima_km >= distancia_maxima_relevancia_km:
                        escore = 0
                        ocorrencia_regiao = f"Distante (>{distancia_maxima_relevancia_km:.0f} km)"
                    else:
                        escore = 9 * (1 - (distancia_minima_km / distancia_maxima_relevancia_km))
                        if distancia_minima_km < 1:
                            ocorrencia_regiao = f"Muito Próxima ({distancia_minima_km*1000:.0f} m)"
                        elif distancia_minima_km < 50:
                            ocorrencia_regiao = f"Próxima ({distancia_minima_km:.1f} km)"
                        else:
                            ocorrencia_regiao = f"Moderadamente Próxima ({distancia_minima_km:.1f} km)"

                resultados.append({'especie': especie, 'ocorrencia_na_regiao': ocorrencia_regiao, 'escore_proximidade': round(escore), 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': lon_ocorrencia, 'latitude_ocorrencia': lat_ocorrencia, 'pontos': pontos_ocorrencia_para_mapa})
            else:
                 resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Dados insuficientes", 'escore_proximidade': -1, 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
        else:
            resultados.append({'especie': especie, 'ocorrencia_na_regiao': "Não encontrado no GBIF", 'escore_proximidade': -1, 'gbif_total_records': gbif_total_records, 'longitude_ocorrencia': None, 'latitude_ocorrencia': None, 'pontos': []})
        
        progress_bar.progress((i + 1) / total_especies)

    status_text.text("Análise concluída!")
    return pd.DataFrame(resultados)

def criar_mapa_interativo(gdf_area, gdf_buffer, distancia_buffer_km, df_resultados):
    """
    Cria um mapa interativo com Folium.

    Args:
        gdf_area (GeoDataFrame): GeoDataFrame da área do polígono.
        gdf_buffer (GeoDataFrame): GeoDataFrame da área de buffer.
        distancia_buffer_km (int): Distância do buffer em km.
        df_resultados (DataFrame): DataFrame com os resultados da análise.

    Returns:
        folium.Map: Objeto do mapa Folium.
    """
    if gdf_area.empty or gdf_area.geometry.is_empty.all():
        return folium.Map(location=[-15.78, -47.92], zoom_start=4)

    # Transforma o CRS para um sistema de coordenadas projetadas para calcular o centroide com segurança
    try:
        centro_mapa = gdf_area.to_crs(epsg=3857).centroid.to_crs(epsg=4326).iloc[0]
        mapa = folium.Map(location=[centro_mapa.y, centro_mapa.x], zoom_start=10)
    except:
        # Fallback se a transformação de CRS falhar
        centro_mapa = gdf_area.geometry.unary_union.centroid
        mapa = folium.Map(location=[centro_mapa.y, centro_mapa.x], zoom_start=10)


    folium.GeoJson(
        gdf_area.to_json(),
        name="Área do Projeto",
        style_function=lambda x: {'color': '#1E90FF', 'fillColor': '#1E90FF', 'fillOpacity': 0.2, 'weight': 2}
    ).add_to(mapa)

    if gdf_buffer is not None and not gdf_buffer.empty:
        folium.GeoJson(
            gdf_buffer.to_json(),
            name=f"Área de Buffer ({distancia_buffer_km} km)",
            style_function=lambda x: {'color': 'orange', 'dashArray': '5, 5', 'fillOpacity': 0.0, 'weight': 2},
            tooltip=f"Buffer de {distancia_buffer_km} km para espécies próximas"
        ).add_to(mapa)

    cores = ['#FF5733', '#33FF57', '#3357FF', '#FF33A1', '#A133FF', '#33FFA1']
    cor_idx = 0

    for _, linha in df_resultados.iterrows():
        especie = linha['especie']
        pontos = linha['pontos']
        if pontos:
            cor = cores[cor_idx % len(cores)]
            cor_idx += 1
            grupo_especie = folium.FeatureGroup(name=f"{especie} ({linha['ocorrencia_na_regiao']})")
            for ponto in pontos:
                folium.CircleMarker(
                    location=[ponto.y, ponto.x],
                    radius=5,
                    popup=f"<i>{especie}</i>",
                    color=cor,
                    fill=True,
                    fill_color=cor,
                    fill_opacity=0.7
                ).add_to(grupo_especie)
            grupo_especie.add_to(mapa)

    folium.LayerControl().add_to(mapa)
    return mapa

def main():
    st.set_page_config(page_title="Análise de Ocorrência de Espécies", layout="wide", page_icon="🐾")
    st.title("🐾 Análise de Ocorrência de Espécies")
    st.markdown("""
    Esta ferramenta interativa analisa a ocorrência de espécies em uma área de interesse, 
    utilizando dados do [GBIF](https://www.gbif.org/) para encontrar registros e calcular um escore de proximidade.
    """)

    st.sidebar.header("Painel de Controle")

    uploaded_excel = st.sidebar.file_uploader(
        "1. Carregue seu arquivo Excel com as espécies",
        type=['xlsx'],
        help="O arquivo deve ser um .xlsx e conter uma coluna chamada 'scientificName'."
    )

    uploaded_zip = st.sidebar.file_uploader(
        "2. Carregue o shapefile da área do projeto (.zip)",
        type=['zip'],
        help="O arquivo .zip deve conter todos os arquivos do shapefile (.shp, .shx, .dbf, etc.)."
    )

    grupos_taxon = ['Qualquer', 'Aves', 'Mammalia', 'Reptilia', 'Amphibia', 'Insecta', 'Arachnida', 'Mollusca']
    grupo_selecionado = st.sidebar.selectbox(
        "3. Filtrar por Grupo Taxonômico (Opcional)",
        options=grupos_taxon,
        index=0, 
        help="Selecione um grupo para refinar a busca no GBIF. 'Qualquer' busca sem filtro de classe."
    )

    distancia_buffer_km = st.sidebar.slider(
        "4. Defina a distância do buffer (km)",
        min_value=10,
        max_value=2000,
        value=500,
        step=10,
        help="Distância em quilômetros ao redor da área para procurar por espécies 'próximas'."
    )

    if st.sidebar.button("Analisar Ocorrências", type="primary"):
        if uploaded_excel is None:
            st.warning("Por favor, carregue um arquivo Excel com as espécies.")
            st.stop()
        
        if uploaded_zip is None:
            st.warning("Por favor, carregue o arquivo .zip do shapefile.")
            st.stop()

        try:
            df_especies = pd.read_excel(uploaded_excel)
        except Exception as e:
            st.error(f"Erro ao ler o arquivo Excel: {e}")
            st.stop()
            
        gdf_buffer = None
        area_km2 = 0
        try:
            gdf_area = processar_shapefile_zip(uploaded_zip)
            if gdf_area is None:
                st.stop()
            # Garante que o CRS seja o WGS84
            gdf_area = gdf_area.to_crs(epsg=4326)

            # --- Area Calculation ---
            try:
                # Use uma projeção de área igual para o cálculo preciso da área
                gdf_area_eq_area = gdf_area.to_crs("EPSG:6933") 
                area_m2 = gdf_area_eq_area.geometry.area.sum()
                area_km2 = area_m2 / 1_000_000
            except Exception as e:
                st.warning(f"Não foi possível calcular a área com precisão: {e}")
                area_km2 = 0
            # --- End Area Calculation ---

            # --- Buffer calculation ---
            gdf_area_proj = gdf_area.to_crs(epsg=3857)
            buffer_geom_proj = gdf_area_proj.buffer(distancia_buffer_km * 1000)
            gdf_buffer_proj = gpd.GeoDataFrame(geometry=buffer_geom_proj, crs="EPSG:3857")
            gdf_buffer = gdf_buffer_proj.to_crs(epsg=4326)
            # --- End buffer calculation ---
        except Exception as e:
            st.error(f"Erro ao processar o shapefile ou criar o buffer: {e}")
            st.stop()

        with st.spinner('Buscando dados no GBIF e analisando... Isso pode levar alguns minutos.'):
            df_resultados = analisar_ocorrencia_especies(df_especies, gdf_area, distancia_buffer_km, grupo_selecionado)
        
        st.success("Análise concluída com sucesso!")

        st.header("📈 Estatísticas Gerais")
        col1, col2 = st.columns(2)
        col1.metric("Área do Projeto (km²)", f"{area_km2:,.2f}")
        col2.metric("Distância do Buffer (km)", f"{distancia_buffer_km} km")

        st.header("📊 Resultados da Análise")
        
        # Exibe todas as colunas do excel original + as colunas geradas
        df_final = pd.merge(df_especies, df_resultados.drop(columns=['pontos']), left_on='scientificName', right_on='especie', how='left')
        st.dataframe(df_final)

        col1_download, col2_download = st.columns(2)

        with col1_download:
            csv = df_final.to_csv(index=False).encode('utf-8')
            st.download_button(
               "Baixar resultados em CSV",
               csv,
               "resultados_ocorrencia_especies.csv",
               "text/csv",
               key='download-csv',
               use_container_width=True
            )
        
        with col2_download:
            try:
                # Filtra as linhas que não possuem coordenadas
                df_geojson = df_final.dropna(subset=['longitude_ocorrencia', 'latitude_ocorrencia']).copy()
                if not df_geojson.empty:
                    gdf_export = gpd.GeoDataFrame(
                        df_geojson, 
                        geometry=gpd.points_from_xy(df_geojson.longitude_ocorrencia, df_geojson.latitude_ocorrencia),
                        crs="EPSG:4326"
                    )
                    
                    geojson_data = gdf_export.to_json()
                    st.download_button(
                        label="Baixar resultados em GeoJSON",
                        data=geojson_data,
                        file_name="resultados_ocorrencia_especies.geojson",
                        mime="application/json",
                        key='download-geojson',
                        use_container_width=True
                    )
                else:
                    st.info("Nenhuma ocorrência com coordenadas para exportar para GeoJSON.")
            except Exception as e:
                st.error(f"Erro ao gerar o arquivo GeoJSON: {e}")


        st.header("🗺️ Mapa Interativo de Ocorrências")
        with st.spinner("Gerando mapa..."):
            mapa = criar_mapa_interativo(gdf_area, gdf_buffer, distancia_buffer_km, df_resultados)
            st_folium(mapa, width='100%', height=500, returned_objects=[])

if __name__ == "__main__":
    main()