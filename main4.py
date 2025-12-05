import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import numpy as np
import time
from streamlit.components.v1 import html # NOVO: Para injetar JavaScript

# --- Bibliotecas para Geocodificação ---
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Rastreio de Ônibus RJ",
    page_icon="🚌",
    layout="wide"
)

# --- INICIALIZAÇÃO DE ESTADO (Para armazenar o resultado da localização JS) ---
if 'geo_result' not in st.session_state:
    # 'pending' = esperando o JS rodar ou a permissão do usuário
    st.session_state.geo_result = {'status': 'pending'}
if 'location_source' not in st.session_state:
    st.session_state.location_source = 'Localização Automática (Browser)'

# --- COMPONENTE DE GEOLOCALIZAÇÃO (NOVO) ---
def get_browser_location():
    """
    Injeta um componente HTML/JS invisível para obter a localização do dispositivo do usuário
    usando a API Geolocation do navegador e retorna o resultado.
    """
    js_code = """
    <script>
        // Função para enviar dados de volta ao Streamlit
        function sendData(data) {
            // Este é o método padrão para componentes Streamlit comunicarem resultados
            if (window.parent.postMessage) {
                window.parent.postMessage({
                    source: 'streamlit',
                    type: 'streamlit:setComponentValue',
                    value: data
                }, '*');
            }
        }

        // Tenta obter a localização.
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(success, error, {
                enableHighAccuracy: true,
                timeout: 5000, // 5 segundos
                maximumAge: 0
            });
        } else {
            sendData({ error: 'Geolocation not supported', status: 'error' });
        }

        function success(position) {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            sendData({ latitude: lat, longitude: lon, status: 'success' });
        }

        function error(err) {
            let message;
            switch (err.code) {
                case err.PERMISSION_DENIED:
                    message = "Permissão negada. Você bloqueou o acesso à localização.";
                    break;
                case err.POSITION_UNAVAILABLE:
                    message = "Localização indisponível.";
                    break;
                case err.TIMEOUT:
                    message = "Tempo limite excedido. Tente novamente ou use outro método.";
                    break;
                default:
                    message = "Erro desconhecido: " + err.message;
            }
            sendData({ error: message, status: 'error' });
        }
    </script>
    """
    
    # Renderiza o componente HTML/JS. Ele é invisível (height=0).
    # O valor retornado será o último JSON enviado pelo JS.
    result = html(js_code, height=0, width=0, scrolling=False, default={'status': 'pending'})
    return result

# --- FUNÇÕES AUXILIARES ---

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula a distância Haversine entre dois pares de coordenadas em km."""
    R = 6371 # Raio da Terra em km
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lon2 - lon1) 
    dlambda = np.radians(lat2 - lat1) 

    a = np.sin(dlambda / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dphi / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c


@st.cache_data(ttl=15) 
def get_data(url):
    """Busca dados da API de GPS dos ônibus (Cache de 15 segundos)."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            st.warning(f"Erro ao buscar dados da API. Código: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão com a API: {e}")
        return None


@st.cache_data(ttl=3600) 
def geocode_address(address):
    """Converte um endereço em coordenadas geográficas usando Nominatim."""
    try:
        geolocator = Nominatim(user_agent="streamlit_rj_bus_tracker_app")
        return geolocator.geocode(address)
    except GeocoderTimedOut:
        return "TIMEOUT"
    except GeocoderServiceError:
        return "SERVICE_ERROR"
    except Exception:
        return None


# --- INTERFACE LATERAL E LÓGICA DE LOCALIZAÇÃO ---
st.sidebar.header("🔍 Configuração de Busca")

linha_desejada = st.sidebar.text_input("Qual a linha?", value="112")
usar_localizacao = st.sidebar.checkbox("Filtrar por localização?", value=True)

# Coordenadas e raio padrão (Botafogo, RJ)
user_lat, user_lon, raio_km = -22.9559, -43.1789, 2.0
localizacao_sucesso = True # Estado de sucesso da localização para o filtro

if usar_localizacao:
    st.sidebar.markdown("---")
    st.sidebar.write("📍 **Sua Localização**")

    location_options = ('Localização Automática (Browser)', 'Endereço (Geocodificação)', 'Coordenadas (Lat/Lon)')
    
    # Use o último valor salvo no estado ou o padrão
    location_source = st.sidebar.radio(
        "Como deseja informar sua localização?",
        location_options,
        index=location_options.index(st.session_state.location_source)
    )
    # Atualiza o estado da escolha do usuário
    st.session_state.location_source = location_source

    raio_km = st.sidebar.slider("Raio de busca (km)", 0.5, 20.0, 2.0)
    
    # -----------------------------------------------------------
    # LÓGICA DE LOCALIZAÇÃO AUTOMÁTICA
    # -----------------------------------------------------------
    if location_source == 'Localização Automática (Browser)':
        
        # Chama a função que injeta o JS e pega o resultado
        # O resultado do componente é sempre o último valor enviado pelo JS
        geo_result = get_browser_location()
        
        # Atualiza o session_state com o resultado, exceto se ainda for 'pending'
        if geo_result and geo_result.get('status') != 'pending':
            # Isso garante que a latitude/longitude sejam salvas
            st.session_state.geo_result = geo_result

        # Lógica para consumir o resultado armazenado
        if st.session_state.geo_result['status'] == 'success':
            user_lat = st.session_state.geo_result['latitude']
            user_lon = st.session_state.geo_result['longitude']
            st.sidebar.success(f"Localização Automática obtida: Lat {user_lat:.5f}, Lon {user_lon:.5f}")
        elif st.session_state.geo_result['status'] == 'error':
            st.sidebar.error(f"Erro ao obter localização: {st.session_state.geo_result['error']}. Tente outro método.")
            localizacao_sucesso = False
        else: # 'pending'
            st.sidebar.info("Aguardando permissão do navegador para localização...")
            localizacao_sucesso = False
            
    # -----------------------------------------------------------
    # LÓGICA DE COORDENADAS MANUAIS
    # -----------------------------------------------------------
    elif location_source == 'Coordenadas (Lat/Lon)':
        # Inputs de coordenadas existentes
        # Limpa o resultado automático se o usuário mudar
        st.session_state.geo_result = {'status': 'pending'} 

        user_lat = st.sidebar.number_input("Sua Latitude", value=-22.9559, format="%.5f")
        user_lon = st.sidebar.number_input("Sua Longitude", value=-43.1789, format="%.5f")
        st.sidebar.success(f"Usando coordenadas: {user_lat:.5f}, {user_lon:.5f}")
        
    # -----------------------------------------------------------
    # LÓGICA DE ENDEREÇO (GEOCODIFICAÇÃO)
    # -----------------------------------------------------------
    elif location_source == 'Endereço (Geocodificação)':
        # Limpa o resultado automático se o usuário mudar
        st.session_state.geo_result = {'status': 'pending'} 
        
        # Input do endereço
        endereco_input = st.sidebar.text_input(
            "Digite o endereço (Ex: Rua Voluntários da Pátria, 300, Rio de Janeiro)",
            value="Av. Rio Branco, 1 - Centro, Rio de Janeiro"
        )

        if endereco_input:
            # Chama a função de geocodificação
            with st.spinner("Buscando coordenadas do endereço..."):
                loc = geocode_address(endereco_input)

            if loc == "TIMEOUT" or loc == "SERVICE_ERROR":
                st.sidebar.error("Erro no serviço de geocodificação. Tente outro endereço.")
                localizacao_sucesso = False
            elif loc:
                # Endereço encontrado com sucesso
                user_lat = loc.latitude
                user_lon = loc.longitude
                st.sidebar.success(f"Endereço encontrado: Lat {user_lat:.5f}, Lon {user_lon:.5f}")
            else:
                # Endereço não encontrado ou genérico
                st.sidebar.warning("Endereço não encontrado. Tente ser mais específico.")
                localizacao_sucesso = False
        else:
            st.sidebar.info("Aguardando endereço para geocodificação...")
            localizacao_sucesso = False

    # Se a localização falhou (em qualquer método), volta para o padrão de Botafogo
    if not localizacao_sucesso:
        user_lat, user_lon = -22.9559, -43.1789
        st.sidebar.warning("Usando coordenadas padrão de fallback (Botafogo) e sem filtro de proximidade.")


# --- CONTROLE DE ATUALIZAÇÃO AUTOMÁTICA E ESTILO DO MAPA ---
st.sidebar.markdown("---")
st.sidebar.write("⚙️ **Controle de Atualização**")
auto_refresh = st.sidebar.checkbox("Atualização Automática a cada 25s", value=True) 

# --- SELEÇÃO DE ESTILO DO MAPA ---
st.sidebar.markdown("---")
st.sidebar.write("🗺️ **Estilo do Mapa**")
map_style = st.sidebar.selectbox(
    "Escolha o estilo do mapa:",
    options=["open-street-map", "stamen-terrain", "stamen-toner", "carto-positron", "carto-darkmatter"],
    index=0, 
    format_func=lambda x: x.replace('-', ' ').title() 
)
# ----------------------------------------

# Botão de atualização manual 
if st.sidebar.button("🔄 Atualizar Dados Agora"):
    st.rerun() 

# --- LÓGICA PRINCIPAL ---
st.title(f"🚌 Monitoramento: Linha {linha_desejada}")

# Tenta pegar a URL do secrets ou usa a padrão
try:
    url_api = st.secrets["API_URL"]
except:
    url_api = "https://dados.mobilidade.rio/gps/sppo"

# Usa st.spinner para mostrar que está buscando dados
with st.spinner("Buscando dados em tempo real..."):
    data = get_data(url_api)

if data:
    df_realtime = pd.DataFrame(data)
    df_realtime.columns = df_realtime.columns.str.lower()

    # 1. Filtra a linha desejada
    df_linha = df_realtime[df_realtime['linha'].astype(str).str.contains(linha_desejada, na=False)].copy()

    if not df_linha.empty:
        # Tratamento de tipos
        df_linha['latitude'] = df_linha['latitude'].astype(str).str.replace(',', '.')
        df_linha['longitude'] = df_linha['longitude'].astype(str).str.replace(',', '.')
        df_linha['latitude'] = pd.to_numeric(df_linha['latitude'], errors='coerce')
        df_linha['longitude'] = pd.to_numeric(df_linha['longitude'], errors='coerce')
        
        # --- AJUSTE DE FUSO HORÁRIO (UTC-3) ---
        df_linha['datahora_utc'] = pd.to_datetime(df_linha['datahora'], unit='ms', errors='coerce')
        df_linha['datahora'] = df_linha['datahora_utc'] - pd.Timedelta(hours=3)
        df_linha = df_linha.drop(columns=['datahora_utc'])
        # -----------------------------------------------------

        df_linha = df_linha.dropna(subset=['latitude', 'longitude'])

        # --- DEDUPLICAÇÃO ---
        df_linha = df_linha.sort_values(by='datahora', ascending=False)
        df_linha = df_linha.drop_duplicates(subset=['ordem'], keep='first')
        # -------------------

        # --- FILTRO DE LOCALIZAÇÃO ---
        # Só aplica o filtro se a caixa estiver marcada E se a localização não tiver falhado 
        # (se o localizacao_sucesso for falso, user_lat/lon estão em Botafogo, mas o filtro será ignorado)
        if usar_localizacao and location_source != 'Localização Automática (Browser)' and localizacao_sucesso:
             # Lógica para Geocodificação ou Coordenadas Manuais
             df_linha['distancia_km'] = haversine_distance(
                 user_lat, user_lon,
                 df_linha['latitude'], df_linha['longitude']
             )
             df_filtrada = df_linha[df_linha['distancia_km'] <= raio_km].copy()
             msg_filtro = f"Mostrando **{len(df_filtrada)}** ônibus únicos num raio de **{raio_km}km**."
        elif usar_localizacao and location_source == 'Localização Automática (Browser)' and st.session_state.geo_result['status'] == 'success':
             # Lógica para Localização Automática (se for sucesso)
             df_linha['distancia_km'] = haversine_distance(
                 user_lat, user_lon,
                 df_linha['latitude'], df_linha['longitude']
             )
             df_filtrada = df_linha[df_linha['distancia_km'] <= raio_km].copy()
             msg_filtro = f"Mostrando **{len(df_filtrada)}** ônibus únicos num raio de **{raio_km}km** (via localização automática)."
        else:
            # Mostra todos os ônibus se o filtro falhou ou não foi selecionado
            df_filtrada = df_linha.copy()
            msg_filtro = f"Mostrando todos os **{len(df_filtrada)}** ônibus da linha."
            if usar_localizacao:
                st.warning("O filtro por proximidade não foi aplicado devido à falha ou indisponibilidade da localização.")

        # --- PLOTAGEM ---
        if not df_filtrada.empty:
            st.info(msg_filtro)

            # Métricas
            col1, col2 = st.columns(2)
            col1.metric("Ônibus na região", len(df_filtrada))
            tempo_recente = df_filtrada['datahora'].max().strftime('%H:%M:%S')
            col2.metric("Último sinal recebido (BRT) às", tempo_recente)

            # Centro do mapa
            # Centraliza na localização do usuário/endereço se a localização foi bem-sucedida (não é o fallback)
            if localizacao_sucesso and usar_localizacao and (location_source != 'Localização Automática (Browser)' or st.session_state.geo_result['status'] == 'success'):
                center_lat, center_lon, zoom_start = user_lat, user_lon, 14
            else:
                # Centraliza na média dos ônibus encontrados
                center_lat = df_filtrada['latitude'].mean()
                center_lon = df_filtrada['longitude'].mean()
                zoom_start = 12

            fig = px.scatter_mapbox(
                df_filtrada,
                lat="latitude",
                lon="longitude",
                hover_name="ordem",
                hover_data={"velocidade": True, "linha": True, "datahora": True,
                             "latitude": ':.5f', "longitude": ':.5f',
                             "distancia_km": ':.2f'} if usar_localizacao else None,
                zoom=zoom_start,
                height=600,
                center={"lat": center_lat, "lon": center_lon},
                mapbox_style=map_style,
                title=f"Posição atual dos ônibus da linha {linha_desejada}"
            )

            fig.update_traces(marker=dict(size=18, color='red'))

            # Adiciona o usuário no mapa (Se a localização foi obtida com sucesso)
            if usar_localizacao and localizacao_sucesso:
                fig.add_scattermapbox(
                    lat=[user_lat], lon=[user_lon],
                    mode='markers',
                    marker=dict(size=25, color='blue', symbol='circle'),
                    name='SUA LOCALIZAÇÃO'
                )

            st.plotly_chart(fig, use_container_width=True)

            # Mostra tabela simples
            cols_show = ['ordem', 'datahora', 'velocidade', 'latitude', 'longitude']
            
            df_display = df_filtrada.rename(columns={'datahora': 'Data/Hora (BRT)'})
            cols_show[cols_show.index('datahora')] = 'Data/Hora (BRT)'
            
            if usar_localizacao:
                cols_show.append('distancia_km')
                df_display = df_display.sort_values('distancia_km')

            st.write("📋 Detalhes dos veículos encontrados:")
            st.dataframe(df_display[cols_show], hide_index=True)

        else:
            st.warning(f"Nenhum ônibus da linha {linha_desejada} encontrado dentro da área de busca ou dados indisponíveis.")
    else:
        st.warning(f"Não há dados disponíveis para a linha {linha_desejada} no momento.")
else:
    st.error("Erro ao obter dados da API. Tente novamente mais tarde.")

# --- LÓGICA DE ATUALIZAÇÃO AUTOMÁTICA OTIMIZADA ---
if auto_refresh:
    countdown_placeholder = st.empty()

    for i in range(25, 0, -1):
        countdown_placeholder.markdown(
            f"**Próxima atualização em {i} segundos...** (Atualização Automática Ativa)"
        )
        time.sleep(1) 

    st.rerun()
