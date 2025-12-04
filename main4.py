import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import numpy as np
import time # Importar a biblioteca time para a função sleep

# --- NOVO: Bibliotecas para Geocodificação ---
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Rastreio de Ônibus RJ",
    page_icon="🚌",
    layout="wide"
)


# --- FUNÇÕES AUXILIARES ---

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula a distância Haversine entre dois pares de coordenadas em km."""
    R = 6371 # Raio da Terra em km
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lon2 - lon1) # Correção: deve ser a diferença de longitude
    dlambda = np.radians(lat2 - lat1) # Correção: deve ser a diferença de latitude

    a = np.sin(dlambda / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dphi / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c


@st.cache_data(ttl=15) # O TTL (Time To Live) de 15s garante que não chamaremos a API a cada segundo.
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


@st.cache_data(ttl=3600) # Cache por 1 hora para endereços
def geocode_address(address):
    """Converte um endereço em coordenadas geográficas usando Nominatim."""
    try:
        # User-Agent necessário para o serviço Nominatim
        geolocator = Nominatim(user_agent="streamlit_rj_bus_tracker_app")
        return geolocator.geocode(address)
    except GeocoderTimedOut:
        # Se ocorrer timeout, retorna um sinal de erro
        return "TIMEOUT"
    except GeocoderServiceError:
        # Se ocorrer erro no serviço, retorna um sinal de erro
        return "SERVICE_ERROR"
    except Exception:
        # Outros erros (ex: endereço vazio, conexão)
        return None


# --- INTERFACE LATERAL E LÓGICA DE LOCALIZAÇÃO ---
st.sidebar.header("🔍 Configuração de Busca")

linha_desejada = st.sidebar.text_input("Qual a linha?", value="112")
usar_localizacao = st.sidebar.checkbox("Filtrar por localização?", value=True)

# Coordenadas e raio padrão (Botafogo, RJ)
user_lat, user_lon, raio_km = -22.9559, -43.1789, 2.0
localizacao_sucesso = True

if usar_localizacao:
    st.sidebar.markdown("---")
    st.sidebar.write("📍 **Sua Localização**")

    # Opção para escolher entre Endereço ou Coordenadas
    location_source = st.sidebar.radio(
        "Como deseja informar sua localização?",
        ('Endereço (Geocodificação)', 'Coordenadas (Lat/Lon)'),
        index=0 # Padrão para Endereço
    )

    raio_km = st.sidebar.slider("Raio de busca (km)", 0.5, 20.0, 2.0)

    if location_source == 'Coordenadas (Lat/Lon)':
        # Inputs de coordenadas existentes
        user_lat = st.sidebar.number_input("Sua Latitude", value=-22.9559, format="%.5f")
        user_lon = st.sidebar.number_input("Sua Longitude", value=-43.1789, format="%.5f")
        st.sidebar.success(f"Usando coordenadas: {user_lat:.5f}, {user_lon:.5f}")

    elif location_source == 'Endereço (Geocodificação)':
        # Input do endereço
        endereco_input = st.sidebar.text_input(
            "Digite o endereço (Ex: Rua Voluntários da Pátria, 300, Rio de Janeiro)",
            value="Av. Rio Branco, 1 - Centro, Rio de Janeiro"
        )

        if endereco_input:
            # Chama a função de geocodificação
            with st.spinner("Buscando coordenadas do endereço..."):
                loc = geocode_address(endereco_input)

            if loc == "TIMEOUT":
                st.sidebar.error("Erro de tempo limite (Timeout) ao buscar o endereço.")
                localizacao_sucesso = False
            elif loc == "SERVICE_ERROR":
                st.sidebar.error("Erro no serviço de geocodificação. Tente novamente.")
                localizacao_sucesso = False
            elif loc:
                # Endereço encontrado com sucesso
                user_lat = loc.latitude
                user_lon = loc.longitude
                st.sidebar.success(f"Endereço encontrado: Lat {user_lat:.5f}, Lon {user_lon:.5f}")
            else:
                # Endereço não encontrado ou genérico
                st.sidebar.warning("Endereço não encontrado. Tente ser mais específico (Rua, Número, Cidade).")
                localizacao_sucesso = False
        else:
            st.sidebar.info("Aguardando endereço para geocodificação...")
            localizacao_sucesso = False

    # Se a localização falhou ou não foi usada, a lógica de filtro principal será ajustada
    if not localizacao_sucesso and usar_localizacao:
        st.sidebar.warning("Usando coordenadas padrão de fallback para exibição no mapa.")

# --- CONTROLE DE ATUALIZAÇÃO AUTOMÁTICA ---
st.sidebar.markdown("---")
st.sidebar.write("⚙️ **Controle de Atualização**")
auto_refresh = st.sidebar.checkbox("Atualização Automática a cada 25s", value=True) # Padrão como True

# Botão de atualização manual (agora ele só força o rerun)
if st.sidebar.button("🔄 Atualizar Dados Agora"):
    st.rerun() # Força a re-execução imediata do script

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
        
        # --- MODIFICAÇÃO PARA AJUSTE DE FUSO HORÁRIO (UTC-3) ---
        # A datahora da API é em milissegundos (assumido UTC).
        # 1. Converte para datetime (objeto ingênuo/naive)
        df_linha['datahora_utc'] = pd.to_datetime(df_linha['datahora'], unit='ms', errors='coerce')
        
        # 2. Aplica o ajuste de -3 horas para o horário de Brasília (BRT/GMT-3)
        df_linha['datahora'] = df_linha['datahora_utc'] - pd.Timedelta(hours=3)
        
        # 3. Remove a coluna original da API para usar apenas a ajustada
        df_linha = df_linha.drop(columns=['datahora_utc'])
        # -----------------------------------------------------

        df_linha = df_linha.dropna(subset=['latitude', 'longitude'])

        # --- DEDUPLICAÇÃO ---
        # 1. Ordena por data (mais recente no topo)
        df_linha = df_linha.sort_values(by='datahora', ascending=False)

        # 2. Remove duplicatas da coluna 'ordem' (ID do ônibus), mantendo só o primeiro (mais recente)
        df_linha = df_linha.drop_duplicates(subset=['ordem'], keep='first')
        # -------------------

        # --- FILTRO DE LOCALIZAÇÃO ---
        if usar_localizacao and localizacao_sucesso:
            # Calcula distância
            df_linha['distancia_km'] = haversine_distance(
                user_lat, user_lon,
                df_linha['latitude'], df_linha['longitude']
            )

            # Filtra pelo raio
            df_filtrada = df_linha[df_linha['distancia_km'] <= raio_km].copy()

            msg_filtro = f"Mostrando **{len(df_filtrada)}** ônibus únicos num raio de **{raio_km}km**."
        else:
            # Se a localização não for usada ou a geocodificação falhou, mostra todos
            df_filtrada = df_linha.copy()
            msg_filtro = f"Mostrando todos os **{len(df_filtrada)}** ônibus da linha."
            if usar_localizacao and not localizacao_sucesso:
                st.warning("O filtro por proximidade não foi aplicado devido ao endereço não encontrado/inválido.")

        # --- PLOTAGEM ---
        if not df_filtrada.empty:
            st.info(msg_filtro)

            # Métricas
            col1, col2 = st.columns(2)
            col1.metric("Ônibus na região", len(df_filtrada))
            # Mostra há quanto tempo foi a atualização do ônibus mais recente, agora em BRT.
            tempo_recente = df_filtrada['datahora'].max().strftime('%H:%M:%S')
            
            # O texto da métrica foi ajustado para indicar o fuso horário
            col2.metric("Último sinal recebido (BRT) às", tempo_recente)

            # Centro do mapa
            if usar_localizacao and localizacao_sucesso:
                # Centraliza na localização do usuário/endereço
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
                # A coluna 'datahora' agora contém o tempo ajustado
                hover_data={"velocidade": True, "linha": True, "datahora": True,
                            "latitude": ':.5f', "longitude": ':.5f',
                            "distancia_km": ':.2f'} if usar_localizacao and localizacao_sucesso else None,
                zoom=zoom_start,
                height=600,
                center={"lat": center_lat, "lon": center_lon},
                mapbox_style="open-street-map",
                title=f"Posição atual dos ônibus da linha {linha_desejada}"
            )

            fig.update_traces(marker=dict(size=18, color='red'))

            # Adiciona o usuário no mapa
            if usar_localizacao and localizacao_sucesso:
                fig.add_scattermapbox(
                    lat=[user_lat], lon=[user_lon],
                    mode='markers',
                    marker=dict(size=25, color='blue', symbol='circle'),
                    name='SUA LOCALIZAÇÃO'
                )

            st.plotly_chart(fig, use_container_width=True)

            # Mostra tabela simples ordenada por distância (se houver geolocalização) ou ordem
            cols_show = ['ordem', 'datahora', 'velocidade', 'latitude', 'longitude']
            
            # Renomeia a coluna 'datahora' na cópia para o display na tabela
            df_display = df_filtrada.rename(columns={'datahora': 'Data/Hora (BRT)'})
            cols_show[cols_show.index('datahora')] = 'Data/Hora (BRT)'
            
            if usar_localizacao and localizacao_sucesso:
                cols_show.append('distancia_km')
                df_display = df_display.sort_values('distancia_km')

            st.write("📋 Detalhes dos veículos encontrados:")
            st.dataframe(df_display[cols_show], hide_index=True)

        else:
            if usar_localizacao and localizacao_sucesso:
                st.warning(f"Nenhum ônibus da linha {linha_desejada} encontrado dentro do raio de {raio_km}km.")
            else:
                st.warning(
                    f"Não há dados disponíveis para a linha {linha_desejada} no momento, ou o endereço não foi encontrado.")
    else:
        st.warning(f"Não há dados disponíveis para a linha {linha_desejada} no momento.")
else:
    st.error("Erro ao obter dados da API. Tente novamente mais tarde.")

# --- LÓGICA DE ATUALIZAÇÃO AUTOMÁTICA OTIMIZADA ---
if auto_refresh:
    # Cria um placeholder para o cronômetro para evitar o "flicker" de um novo elemento
    countdown_placeholder = st.empty()

    # Loop de 25 segundos para a contagem regressiva, mantendo a UI responsiva
    for i in range(25, 0, -1):
        countdown_placeholder.markdown(
            f"**Próxima atualização em {i} segundos...** (Atualização Automática Ativa)"
        )
        time.sleep(1) # Pausa de 1 segundo

    # Após a contagem regressiva, força a re-execução do script
    st.rerun()
