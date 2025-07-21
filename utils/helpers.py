import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from shapely.geometry import Point
from pygbif import occurrences as occ, species as species_api
from pygbif import utils
import zipfile
import os
import tempfile
import time
import requests # Adicionado

def search_gbif_with_retries(params, max_retries=4):
    """
    Tenta buscar dados no GBIF com um sistema de retentativas para lidar com erros de conexão.
    """
    for attempt in range(max_retries):
        try:
            return occ.search(**params)
        except Exception as e:
            if 'Connection' in str(e) or 'RemoteDisconnected' in str(e):
                wait_time = 2 ** (attempt + 1)  # Exponential backoff: 2, 4, 8, 16 segundos
                st.warning(f"Erro de conexão com o GBIF (tentativa {attempt + 1}/{max_retries}). Tentando novamente em {wait_time}s...")
                time.sleep(wait_time)
            else:
                # Se for outro tipo de erro, não tenta novamente e mostra a mensagem
                st.error(f"Ocorreu um erro inesperado ao buscar no GBIF: {e}")
                return None
    
    st.error(f"Não foi possível conectar ao GBIF após {max_retries} tentativas. O servidor pode estar indisponível. Tente novamente mais tarde.")
    return None

def buscar_com_paginacao(gdf_area, reino_key, limite_registros, status_placeholder):
    """
    Busca ocorrências no GBIF usando paginação para obter um grande número de registros.
    """
    if gdf_area is None:
        return []

    try:
        wkt_geom = gdf_area.geometry.unary_union.wkt
        geometria_wkt = utils.wkt_rewind(wkt_geom, digits=6)
    except Exception as e:
        st.error(f"Erro ao processar a geometria do shapefile: {e}")
        return []

    todos_os_resultados = []
    offset = 0
    passo = 300  # Limite de registros por chamada da API

    while offset < limite_registros:
        status_placeholder.info(f"Buscando no GBIF... ({len(todos_os_resultados)} de {limite_registros} registros obtidos)")
        
        params = {
            'geometry': geometria_wkt,
            'kingdomKey': reino_key,
            'hasCoordinate': True,
            'limit': passo,
            'offset': offset
        }
        
        registros_pagina = search_gbif_with_retries(params)
        
        if registros_pagina is None:
            st.error("A busca falhou. Não foi possível continuar.")
            break
        
        resultados_da_pagina = registros_pagina.get('results', [])
        if not resultados_da_pagina:
            status_placeholder.success("Não há mais registros disponíveis no GBIF para esta área.")
            break
            
        todos_os_resultados.extend(resultados_da_pagina)
        offset += passo
        time.sleep(0.2) # Pausa para não sobrecarregar a API

    status_placeholder.success(f"Busca finalizada! Total de {len(todos_os_resultados)} registros encontrados.")
    return todos_os_resultados[:limite_registros]

def get_categoria_flora_brasil(nome_cientifico):
    """
    Consulta a API da Flora e Funga do Brasil, navegando pela estrutura
    correta do JSON para encontrar a forma de vida.
    """
    partes_nome = nome_cientifico.split(' ')
    if len(partes_nome) < 2:
        return None

    genus = partes_nome[0]
    nome_para_comparar = f"{partes_nome[0]} {partes_nome[1]}"
    url = f"https://servicos.jbrj.gov.br/v2/flora/taxon/{genus}"
    
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()

        if data and isinstance(data, list):
            print(data)
            for item in data:
                # O nome científico está em item['taxon']['scientificname']
                taxon_info = item.get('taxon')
                api_full_name = taxon_info.get('scientificname') if taxon_info else None
            
                # Compara o nome da API com o nosso nome limpo
                if api_full_name and api_full_name.startswith(nome_para_comparar):
                    # O perfil da espécie está em item['specie_profile']
                    profile = item.get('specie_profile')
                    if profile and profile.get('lifeForm'):
                        return ", ".join(profile['lifeForm'])
                    return None # Encontrou a espécie, mas sem perfil
        return None

    except requests.exceptions.RequestException as e:
        print(f"  - Aviso (Flora do Brasil): Erro de conexão para '{genus}'. Detalhes: {e}")
    
    return None

def get_plant_traits(_scientific_names):
    """
    Busca informações de 'lifeForm' (forma de vida) para uma lista de nomes científicos de plantas
    usando a API da Flora do Brasil. Utiliza um cache na session_state para evitar buscas repetidas.
    Retorna um dicionário mapeando o nome científico para a forma de vida.
    """
    if 'lifeform_cache' not in st.session_state:
        st.session_state.lifeform_cache = {}

    traits = {}
    
    # Filtra nomes que ainda não estão no cache para fazer a busca
    names_to_fetch = [name for name in set(_scientific_names) if name and name not in st.session_state.lifeform_cache]
    
    # Se houver novos nomes para buscar, mostra a barra de progresso
    if names_to_fetch:
        progress_text = f"Categorizando {len(names_to_fetch)} novas espécies de plantas... (0%)"
        try:
            progress_bar = st.progress(0, text=progress_text)
            total_to_fetch = len(names_to_fetch)

            for i, name in enumerate(names_to_fetch):
                try:
                    life_form = get_categoria_flora_brasil(name)
                    st.session_state.lifeform_cache[name] = life_form if life_form else 'Não categorizado'
                except Exception:
                    st.session_state.lifeform_cache[name] = 'Erro ao buscar dados'
                
                progress_value = (i + 1) / total_to_fetch
                progress_bar.progress(progress_value, text=f"Categorizando {len(names_to_fetch)} novas espécies de plantas... ({int(progress_value * 100)}%)")
                time.sleep(0.05) 

            progress_bar.empty()
        except Exception as e:
            st.warning(f"A barra de progresso falhou, mas a análise continua em segundo plano. Erro: {e}")

    # Monta o dicionário de retorno com todos os nomes da busca atual, usando o cache
    for name in _scientific_names:
        if name:
            traits[name] = st.session_state.lifeform_cache.get(name, 'Não categorizado')

    return traits

@st.cache_data(show_spinner=False)
def processar_shapefile_zip(uploaded_file):
    """
    Extrai um arquivo zip em memória, encontra o .shp, lê com GeoPandas
    e retorna o GeoDataFrame e a área calculada em km².
    """
    if uploaded_file is None:
        return None, 0

    with tempfile.TemporaryDirectory() as tempdir:
        try:
            with zipfile.ZipFile(uploaded_file) as zf:
                zf.extractall(tempdir)
                shp_path = next((os.path.join(tempdir, f) for f in os.listdir(tempdir) if f.endswith('.shp')), None)
                
                if shp_path:
                    gdf = gpd.read_file(shp_path)
                    gdf = gdf.to_crs(epsg=4326)
                    
                    gdf_proj = gdf.to_crs("EPSG:6933")
                    area_m2 = gdf_proj.geometry.area.sum()
                    area_km2 = area_m2 / 1_000_000
                    return gdf, area_km2
                else:
                    st.error("Nenhum arquivo .shp encontrado no arquivo .zip.")
                    return None, 0
        except Exception as e:
            st.error(f"Erro ao processar o arquivo zip: {e}")
            return None, 0

def criar_mapa_base(gdf_area):
    """Cria um mapa Folium base com a área do projeto."""
    if gdf_area is None or gdf_area.empty:
        return folium.Map(location=[-15.78, -47.92], zoom_start=4)

    mapa = folium.Map()

    folium.GeoJson(
        gdf_area.to_json(),
        name="Área do Projeto",
        style_function=lambda x: {'color': '#1E90FF', 'fillColor': '#1E90FF', 'fillOpacity': 0.2, 'weight': 2.5}
    ).add_to(mapa)
    
    bounds = gdf_area.total_bounds
    mapa.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    
    return mapa 