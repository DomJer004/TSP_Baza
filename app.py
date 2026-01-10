import streamlit as st
import pandas as pd
import datetime
import re
import os
import time
import calendar
import sqlite3
import hashlib

# --- KONFIGURACJA BAZY DANYCH DLA KIBICÓW ---
DB_FILE = "tsp_fans.db"


def init_db():
    """Tworzy tabele w bazie SQLite, jeśli nie istnieją."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Tabela użytkowników
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (username TEXT PRIMARY KEY, password TEXT, join_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance 
                     (username TEXT, match_id TEXT, date TEXT, UNIQUE(username, match_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, username TEXT, comment TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS favorites 
                     (username TEXT, player_name TEXT, UNIQUE(username, player_name))''')
    c.execute('''CREATE TABLE IF NOT EXISTS dream_team 
                     (username TEXT PRIMARY KEY, formation TEXT, gk TEXT, 
                      def1 TEXT, def2 TEXT, def3 TEXT, def4 TEXT, 
                      mid1 TEXT, mid2 TEXT, mid3 TEXT, mid4 TEXT, 
                      fwd1 TEXT, fwd2 TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_results 
                     (username TEXT, score INTEGER, date TEXT)''')

    # [NOWOŚĆ] Tabela pytań użytkowników
    # author: kto dodał pytanie
    # q: treść pytania
    # op_a, op_b, op_c: opcje odpowiedzi
    # ans: poprawna odpowiedź (tekst)
    c.execute('''CREATE TABLE IF NOT EXISTS user_questions 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      author TEXT, 
                      q TEXT, 
                      op_a TEXT, op_b TEXT, op_c TEXT, 
                      ans TEXT)''')

    conn.commit()
    conn.close()

init_db()  # Uruchom przy starcie


# Funkcje pomocnicze do bazy
def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(query, params)
        if fetch:
            res = c.fetchall()
            return res
        conn.commit()
    except Exception as e:
        return None
    finally:
        conn.close()


def hash_pass(password):
    return hashlib.sha256(str(password).encode()).hexdigest()

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(
    page_title="TSP Baza Danych",
    layout="wide",
    page_icon="⚽"
)


# ==========================================
# [NOWOŚĆ] GLOBALNE STYLE CSS (DARK MODE FIX)
# ==========================================
def apply_custom_css():
    st.markdown("""
        <style>
        /* 1. Kafelki w Kalendarzu */
        .cal-card {
            background-color: var(--secondary-background-color); /* Szary w light, Ciemny w dark */
            border: 1px solid var(--text-color);
            border-radius: 8px;
            padding: 5px;
            text-align: center;
            margin-bottom: 5px;
            color: var(--text-color);
            opacity: 0.9;
        }

        /* 2. Dzień dzisiejszy */
        .cal-card.today {
            border: 2px solid #28a745; /* Zielona ramka */
            background-color: rgba(40, 167, 69, 0.15); /* Półprzezroczysta zieleń - działa na czarnym i białym */
        }

        /* 3. Baner Dnia Meczowego */
        .match-banner {
            background-color: rgba(40, 167, 69, 0.2); /* Półprzezroczyste tło */
            border: 2px solid #28a745;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 20px;
            color: var(--text-color); /* Tekst dopasowuje się do trybu */
        }

        /* 4. Poprawa widoczności metryk */
        [data-testid="stMetricValue"] {
            font-weight: bold;
        }
        /* --- MOBILE TWEAKS --- */
@media (max-width: 640px) {
    /* Zmniejszenie paddingu głównego bloku na telefonach */
    .block-container {
        padding-top: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* Zmniejszenie czcionki w metrykach, żeby nie ucinało liczb */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
    }

    /* Ukrywanie indeksów w tabelach na siłę, jeśli st.dataframe pominie config */
    [data-testid="stDataFrame"] th:first-child {
        display: none;
    }

    /* Poprawa kafelków w kalendarzu */
    .cal-card {
        font-size: 0.8rem;
        padding: 2px;
    }

    /* Zmniejszenie nagłówków */
    h1 { font-size: 1.8rem !important; }
    h2 { font-size: 1.5rem !important; }
    h3 { font-size: 1.3rem !important; }
}
        </style>
    """, unsafe_allow_html=True)


apply_custom_css()  # <--- Uruchomienie stylów

# --- 2. ZARZĄDZANIE SESJĄ I NAWIGACJA (Router) ---
if 'uploader_key' not in st.session_state: st.session_state['uploader_key'] = 0
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""

# Zmienne do nawigacji (kliknięcie w piłkarza)
if 'cm_selected_player' not in st.session_state: st.session_state['cm_selected_player'] = None


def navigate_to_player(name):
    """Funkcja pomocnicza do otwierania profilu"""
    clean_name = str(name).replace("Ⓜ️", "").replace("🤕", "").strip()
    st.session_state['cm_selected_player'] = clean_name
    st.rerun()


# --- 3. LOGOWANIE ---
USERS = {
    "Djero": "TSP1995",
    "KKowalski": "Tsp2025",
    "PPorebski": "TSP2025",
    "MCzerniak": "TSP2025",
    "SJaszczurowski": "TSP2025",
    "guest": "123456789",
    "JFilip": "KochamPodbeskidzie",
    "Gabrielba": "TSP2026"
}

# --- KONFIGURACJA GLOBALNA ---
IGNORED_SEASONS = ["1995/96", "1996/97", "1995/1996", "1996/1997"]


def filter_seasons(df, col_name='Sezon'):
    """Usuwa z DataFrame rekordy z ignorowanych sezonów."""
    if df is None or col_name not in df.columns:
        return df
    return df[~df[col_name].isin(IGNORED_SEASONS)].copy()


def login():
    st.title("⚽ Logowanie do TSP Baza Danych")

    tab_login, tab_register = st.tabs(["Logowanie", "Załóż konto Kibica"])

    with tab_login:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            u = st.text_input("Użytkownik", key="login_u")
            p = st.text_input("Hasło", type="password", key="login_p")
            if st.button("Zaloguj", use_container_width=True):
                # 1. Sprawdź adminów/VIP (Hardcoded)
                if u in USERS and USERS[u] == p:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = u
                    st.session_state['role'] = 'admin'
                    st.rerun()

                # 2. Sprawdź bazę kibiców
                hashed = hash_pass(p)
                res = run_query("SELECT * FROM users WHERE username=? AND password=?", (u, hashed), fetch=True)
                if res:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = u
                    st.session_state['role'] = 'fan'
                    st.rerun()
                else:
                    st.error("Błędny login lub hasło")

    with tab_register:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            new_u = st.text_input("Wybierz nick", key="reg_u")
            new_p1 = st.text_input("Hasło", type="password", key="reg_p1")
            new_p2 = st.text_input("Powtórz hasło", type="password", key="reg_p2")

            if st.button("Zarejestruj się", use_container_width=True):
                if new_p1 != new_p2:
                    st.error("Hasła nie są identyczne!")
                elif len(new_u) < 3:
                    st.error("Nick musi mieć min. 3 znaki.")
                elif new_u in USERS:
                    st.error("Ten nick jest zarezerwowany.")
                else:
                    # Sprawdź czy już istnieje
                    exist = run_query("SELECT username FROM users WHERE username=?", (new_u,), fetch=True)
                    if exist:
                        st.error("Taki użytkownik już istnieje.")
                    else:
                        run_query("INSERT INTO users VALUES (?, ?, ?)",
                                  (new_u, hash_pass(new_p1), str(datetime.date.today())))
                        st.success("Konto założone! Możesz się zalogować.")


def logout():
    st.session_state['logged_in'] = False
    st.session_state['username'] = ""
    st.rerun()


if not st.session_state['logged_in']:
    login()
    st.stop()

# --- GŁÓWNA APLIKACJA ---
st.title("⚽ Baza Danych TSP - Centrum Wiedzy")

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except:
    HAS_PLOTLY = False

# --- MAPOWANIE KRAJÓW (BEZ ZMIAN) ---
COUNTRY_TO_ISO = {
    'polska': 'pl', 'hiszpania': 'es', 'słowacja': 'sk', 'łotwa': 'lv',
    'chorwacja': 'hr', 'kamerun': 'cm', 'zimbabwe': 'zw', 'finlandia': 'fi',
    'gruzja': 'ge', 'słowenia': 'si', 'ukraina': 'ua', 'holandia': 'nl',
    'czechy': 'cz', 'białoruś': 'by', 'serbia': 'rs', 'litwa': 'lt',
    'turcja': 'tr', 'bośnia i hercegowina': 'ba', 'japonia': 'jp',
    'senegal': 'sn', 'bułgaria': 'bg', 'izrael': 'il', 'nigeria': 'ng',
    'grecja': 'gr', 'francja': 'fr', 'niemcy': 'de', 'argentyna': 'ar',
    'usa': 'us', 'stany zjednoczone': 'us', 'kolumbia': 'co', 'włochy': 'it',
    'belgia': 'be', 'szwecja': 'se', 'portugalia': 'pt', 'węgry': 'hu',
    'austria': 'at', 'brazylia': 'br', 'szkocja': 'gb-sct', 'anglia': 'gb-eng',
    'walia': 'gb-wls', 'irlandia': 'ie', 'irlandia północna': 'gb-nir',
    'rosja': 'ru', 'dania': 'dk', 'norwegia': 'no', 'szwajcaria': 'ch',
    'rumunia': 'ro', 'cypr': 'cy', 'macedonia': 'mk', 'czarnogóra': 'me',
    'ghana': 'gh', 'estonia': 'ee', 'haiti': 'ht', 'kanada': 'ca',
    'wybrzeże kości słoniowej': 'ci', 'maroko': 'ma', 'tunezja': 'tn',
    'algieria': 'dz', 'egipt': 'eg', 'islandia': 'is', 'korea południowa': 'kr',
    'australia': 'au', 'urugwaj': 'uy', 'chile': 'cl', 'paragwaj': 'py',
    'kongo': 'cg', 'dr konga': 'cd', 'mali': 'ml', 'burkina faso': 'bf', 'albania': 'al',
    'liberia': 'lr'
}


# --- FUNKCJE POMOCNICZE ---
def render_player_profile(player_name):
    """Wyświetla profil zawodnika z historią podzieloną na sezony."""

    # --- 1. ŁADOWANIE DANYCH ---
    df_uv = load_data("pilkarze.csv")
    df_long = load_data("pilkarze.csv")
    df_strzelcy = load_data("strzelcy.csv")
    df_det_goals = load_details("wystepy.csv")

    if df_uv is None:
        st.error("Brak pliku pilkarze.csv")
        return

    # Przygotowanie danych
    df_uv = prepare_flags(df_uv)

    # Sortowanie (główny rekord)
    sort_col = 'suma' if 'suma' in df_uv.columns else ('mecze' if 'mecze' in df_uv.columns else None)
    if sort_col:
        df_uv[sort_col] = pd.to_numeric(df_uv[sort_col], errors='coerce').fillna(0)
        df_uv_sorted = df_uv.sort_values(sort_col, ascending=False).drop_duplicates(subset=['imię i nazwisko'])
    else:
        df_uv_sorted = df_uv.drop_duplicates(subset=['imię i nazwisko'])

    if player_name not in df_uv_sorted['imię i nazwisko'].values:
        st.warning(f"Nie znaleziono profilu: {player_name}")
        return

    row = df_uv_sorted[df_uv_sorted['imię i nazwisko'] == player_name].iloc[0]

    # --- A. WIEK ---
    col_b = next((c for c in row.index if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
    birth_date = None
    age_info, is_bday = "-", False
    if col_b:
        birth_date = pd.to_datetime(row[col_b], errors='coerce')
        a, is_bday = get_age_and_birthday(row[col_b])
        if a: age_info = f"{a} lat"
    if is_bday:
        st.balloons()
        st.success(f"🎉🎂 {player_name} kończy dzisiaj {age_info}! 🎂🎉")

    # --- B. ODZNAKI ---
    badges = get_player_record_badges(player_name, df_w=df_det_goals, df_p=df_uv_sorted)
    if badges:
        st.write("")
        badges_html = ""
        for b in badges:
            badges_html += f"""<span style="background-color: {b['color']}20; border: 1px solid {b['color']}; color: {b['color']}; padding: 4px 10px; border-radius: 15px; font-size: 0.9rem; font-weight: bold; margin-right: 5px; margin-bottom: 5px; display: inline-block;">{b['icon']} {b['text']}</span>"""
        st.markdown(badges_html, unsafe_allow_html=True)
        st.write("")

    # --- C. DEBIUT I OSTATNI MECZ ---
    debut_txt = "-"
    last_txt = "-"
    p_hist = pd.DataFrame()
    if df_det_goals is not None:
        p_hist = df_det_goals[df_det_goals['Zawodnik_Clean'] == player_name].copy()
        if not p_hist.empty and 'Data_Sort' in p_hist.columns:
            p_hist = p_hist.sort_values('Data_Sort', ascending=True)

            # Debiut
            fm = p_hist.iloc[0]
            d_dt = pd.to_datetime(fm['Data_Sort'])
            d_str = d_dt.strftime('%d.%m.%Y') if pd.notna(d_dt) else "-"
            debut_txt = f"{d_str} vs {fm.get('Przeciwnik', '')}\n{calculate_exact_age_str(birth_date, d_dt) if birth_date else ''}"

            # Ostatni mecz
            lm = p_hist.iloc[-1]
            l_dt = pd.to_datetime(lm['Data_Sort'])
            l_str = l_dt.strftime('%d.%m.%Y') if pd.notna(l_dt) else "-"
            last_txt = f"{l_str} vs {lm.get('Przeciwnik', '')}\n{calculate_exact_age_str(birth_date, l_dt) if birth_date else ''}"

    # --- D. NAGŁÓWEK ---
    c_p1, c_p2 = st.columns([1, 3])
    nat_raw = str(row.get('Narodowość', row.get('kraj', '-')))

    with c_p1:
        flags_html = get_multi_flags_html(nat_raw)
        if flags_html:
            st.markdown(flags_html, unsafe_allow_html=True)
        else:
            st.markdown("## 👤")

    with c_p2:
        st.markdown(f"## {player_name}")
        st.markdown(f"**Kraj:** {nat_raw} | **Poz:** {row.get('pozycja', '-')}")
        st.markdown(f"**Wiek:** {age_info}")

        hd1, hd2 = st.columns(2)
        hd1.info(f"🆕 **Debiut:**\n\n{debut_txt}")
        hd2.info(f"🏁 **Ostatni mecz:**\n\n{last_txt}")

    st.markdown("---")

    # [NOWOŚĆ] Przycisk Ulubiony
    if st.session_state.get('logged_in'):
        is_fav = run_query("SELECT * FROM favorites WHERE username=? AND player_name=?",
                           (st.session_state['username'], player_name), fetch=True)
        if is_fav:
            if st.button("❤️ Usuń z ulubionych", key=f"fav_rem_{player_name}"):
                run_query("DELETE FROM favorites WHERE username=? AND player_name=?",
                          (st.session_state['username'], player_name))
                st.rerun()
        else:
            if st.button("🤍 Dodaj do ulubionych", key=f"fav_add_{player_name}"):
                run_query("INSERT INTO favorites VALUES (?, ?)",
                          (st.session_state['username'], player_name))
                st.balloons()
                st.rerun()

    # --- E. WYKRES ---
    p_stats = df_long[df_long['imię i nazwisko'] == player_name].copy()
    if 'sezon' in p_stats.columns: p_stats = p_stats.sort_values('sezon')

    gole_l = []
    if df_strzelcy is not None:
        gm = df_strzelcy.set_index(['imię i nazwisko', 'sezon'])['gole'].to_dict()
        for _, r in p_stats.iterrows(): gole_l.append(gm.get((player_name, r.get('sezon', '-')), 0))
    else:
        gole_l = [0] * len(p_stats)
    p_stats['Gole_Calc'] = gole_l

    if 'sezon' in p_stats.columns and HAS_PLOTLY:
        try:
            p_stats['liczba'] = pd.to_numeric(p_stats.get('liczba', p_stats.get('mecze', 0)), errors='coerce').fillna(0)
            if not p_stats.empty and p_stats['liczba'].sum() > 0:
                fig = go.Figure()
                fig.add_trace(go.Bar(x=p_stats['sezon'], y=p_stats['liczba'], name='Mecze', marker_color='#3498db'))
                fig.add_trace(go.Bar(x=p_stats['sezon'], y=p_stats['Gole_Calc'], name='Gole', marker_color='#2ecc71'))
                fig.update_layout(title=f"Statystyki: {player_name}", barmode='group', height=350,
                                  margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, key=f"chart_{player_name}")
        except:
            pass

    # --- F. TABELA GOLI ---
    if df_det_goals is not None and 'Gole' in df_det_goals.columns:
        df_det_goals['Gole'] = pd.to_numeric(df_det_goals['Gole'], errors='coerce').fillna(0).astype(int)
        goals_df = df_det_goals[(df_det_goals['Zawodnik_Clean'] == player_name) & (df_det_goals['Gole'] > 0)].copy()
        if not goals_df.empty:
            if 'Data_Sort' in goals_df.columns: goals_df = goals_df.sort_values('Data_Sort', ascending=False)
            st.markdown(f"**⚽ Mecze ze zdobytą bramką (Łącznie: {goals_df['Gole'].sum()})**")
            st.dataframe(goals_df[['Sezon', 'Data_Sort', 'Przeciwnik', 'Wynik', 'Gole']], use_container_width=True,
                         hide_index=True,
                         column_config={"Data_Sort": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                                        "Gole": st.column_config.NumberColumn("Gole", format="%d ⚽")})

    # =========================================================
    # G. HISTORIA SZCZEGÓŁOWA (PODZIAŁ NA SEZONY)
    # =========================================================
    st.markdown("---")
    st.subheader("📜 Szczegółowa historia meczowa")
    st.caption("ℹ️ Kliknij w wiersz tabeli, aby zobaczyć pełny raport meczowy.")

    if not p_hist.empty:
        # Sortowanie ogólne chronologiczne (od najnowszych)
        if 'Data_Sort' in p_hist.columns:
            p_hist = p_hist.sort_values('Data_Sort', ascending=False)

        # Analiza dla bramkarzy
        pos_str = str(row.get('pozycja', '')).lower().strip()
        is_gk = ('bramkarz' in pos_str or 'gk' in pos_str)
        if is_gk:
            def analyze_gk(r):
                conceded = 0
                icon = ""
                try:
                    w = str(r.get('Wynik', '')).split('(')[0].strip()
                    parts = re.split(r'[:\-]', w)
                    if len(parts) >= 2:
                        g1, g2 = int(parts[0]), int(parts[1])
                        role = str(r.get('Rola', '')).lower()
                        if 'gospodarz' in role or 'dom' in role:
                            conceded = g2
                        elif 'gość' in role or 'wyjazd' in role:
                            conceded = g1
                except:
                    pass
                mins = pd.to_numeric(r.get('Minuty'), errors='coerce') or 0
                if mins >= 45 and conceded == 0:
                    icon = "🧱"
                elif mins > 0:
                    icon = "➖"
                return pd.Series([conceded, icon])

            p_hist[['Wpuszczone', 'Czyste konto']] = p_hist.apply(analyze_gk, axis=1)

        # Wybór kolumn
        cols_base = ['Data_Sort', 'Przeciwnik', 'Wynik', 'Rola', 'Status', 'Minuty']
        target = cols_base + (['Wpuszczone', 'Czyste konto'] if is_gk else ['Gole']) + ['Żółte', 'Czerwone']
        final_cols = [c for c in target if c in p_hist.columns]

        # --- PĘTLA PO SEZONACH ---
        # Zakładamy, że kolumna 'Sezon' istnieje (jest w wystepy.csv)
        if 'Sezon' in p_hist.columns:
            unique_seasons = p_hist['Sezon'].unique()
            # Sortujemy sezony tak, żeby "2024/25" było wyżej niż "2010/11"
            # Ponieważ p_hist jest już posortowane po dacie malejąco, unique() powinno zachować kolejność

            for sezon in unique_seasons:
                with st.expander(f"📂 Sezon {sezon}", expanded=True):
                    # Filtrujemy dane dla sezonu
                    season_df = p_hist[p_hist['Sezon'] == sezon].copy()

                    # Interaktywna tabela
                    event = st.dataframe(
                        season_df[final_cols].reset_index(drop=True),
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"hist_pl_{player_name}_{sezon}",  # Unikalny klucz
                        column_config={
                            "Data_Sort": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                            "Gole": st.column_config.NumberColumn("Gole", format="%d ⚽"),
                            "Wpuszczone": st.column_config.NumberColumn("Wpuszczone", format="%d ❌"),
                            "Minuty": st.column_config.NumberColumn("Minuty", format="%d'"),
                            "Żółte": st.column_config.NumberColumn("Żółte", format="%d 🟨"),
                            "Czerwone": st.column_config.NumberColumn("Czerwone", format="%d 🟥")
                        }
                    )

                    # Obsługa kliknięcia wewnątrz sezonu
                    if event.selection.rows:
                        idx = event.selection.rows[0]
                        selected_match = season_df.iloc[idx]
                        match_label = selected_match['Mecz_Label']

                        st.markdown("---")
                        st.markdown(f"#### 🔎 Raport meczowy")

                        full_match_squad = df_det_goals[df_det_goals['Mecz_Label'] == match_label].copy()
                        if not full_match_squad.empty:
                            full_match_squad = full_match_squad.sort_values('File_Order')
                            render_match_report_logic(match_label, full_match_squad)
                        else:
                            st.warning("Brak danych składu.")
        else:
            # Fallback jeśli nie ma kolumny Sezon (np. stary format pliku)
            st.dataframe(p_hist[final_cols], use_container_width=True)

    else:
        st.info("Brak historii meczowej.")

    # --- H. KOLEDZY Z ZESPOŁU ---
    st.markdown("---")
    st.subheader("🤝 Najwięcej meczów z...")

    if not p_hist.empty:
        my_m = p_hist['Mecz_Label'].unique()
        mates = df_det_goals[df_det_goals['Mecz_Label'].isin(my_m)].copy()
        mates = mates[mates['Zawodnik_Clean'] != player_name]

        if not mates.empty:
            tm = mates['Zawodnik_Clean'].value_counts().head(10)

            flags_dict = {}
            if 'Flaga' in df_uv_sorted.columns:
                flags_dict = df_uv_sorted.set_index('imię i nazwisko')['Flaga'].to_dict()

            idx_m = 0
            for mate_name, shared_count in tm.items():
                idx_m += 1
                medal = "🥇" if idx_m == 1 else ("🥈" if idx_m == 2 else ("🥉" if idx_m == 3 else f"{idx_m}."))

                expander_label = f"{medal} {mate_name} — {shared_count} meczów"
                with st.expander(expander_label):
                    f_url = flags_dict.get(mate_name)
                    if f_url: st.markdown(f'<img src="{f_url}" style="height:20px;"/> <b>{mate_name}</b>',
                                          unsafe_allow_html=True)

                    shared_g = mates[
                        (mates['Zawodnik_Clean'] == mate_name) &
                        (mates['Mecz_Label'].isin(my_m))
                        ].copy()

                    if not shared_g.empty:
                        if 'Data_Sort' in shared_g.columns: shared_g = shared_g.sort_values('Data_Sort',
                                                                                            ascending=False)
                        st.dataframe(
                            shared_g[['Sezon', 'Data_Sort', 'Przeciwnik', 'Wynik', 'Minuty']],
                            use_container_width=True, hide_index=True,
                            column_config={
                                "Data_Sort": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                                "Minuty": st.column_config.NumberColumn("Min.", format="%d'")
                            }
                        )
        else:
            st.info("Brak danych o kolegach.")
    else:
        st.info("Brak danych.")


def render_coach_profile(coach_name):
    """Generuje pełny profil trenera z podziałem na sezony."""

    # 1. Ładowanie danych
    df_t = load_data("trenerzy.csv")
    df_m = load_data("mecze.csv")
    df_details = load_details("wystepy.csv")

    if df_t is None:
        st.error("Brak pliku trenerzy.csv")
        return

    # Normalizacja flag
    df_t = prepare_flags(df_t)

    # 2. Znalezienie kadencji trenera
    coach_rows = df_t[df_t['imię i nazwisko'] == coach_name].copy()
    if coach_rows.empty:
        st.warning(f"Nie znaleziono trenera: {coach_name}")
        return

    # Pobieramy dane personalne
    base_info = coach_rows.iloc[0]

    # --- FUNKCJA POMOCNICZA DO DAT ---
    def safe_parse_date(val):
        """Próbuje sparsować datę na wiele sposobów."""
        s = str(val).strip().lower()
        if s in ['-', 'nan', '', 'obecnie', 'null']:
            return pd.NaT

        # Próba 1: DD.MM.YYYY
        try:
            return pd.to_datetime(s, dayfirst=True)
        except:
            pass

        # Próba 2: YYYY-MM-DD
        try:
            return pd.to_datetime(s, format='%Y-%m-%d')
        except:
            pass

        # Próba 3: Automatyczna
        try:
            return pd.to_datetime(s)
        except:
            return pd.NaT

    # 3. Filtrowanie meczów (Naprawiona logika)
    matches_mask = pd.Series([False] * len(df_m)) if df_m is not None else pd.Series([], dtype=bool)
    tenure_list = []

    if df_m is not None:
        # Znajdź kolumnę z datą w mecze.csv
        col_m_date = next((c for c in df_m.columns if c in ['data meczu', 'data', 'dt_obj']), None)

        if col_m_date:
            # Konwertujemy daty meczów raz
            df_m['dt_temp'] = df_m[col_m_date].apply(safe_parse_date)

            for _, row in coach_rows.iterrows():
                s_date = safe_parse_date(row.get('początek'))
                e_date = safe_parse_date(row.get('koniec'))

                # Obsługa "do teraz"
                is_curr = False
                if pd.isna(e_date):
                    e_date = pd.Timestamp.today() + pd.Timedelta(days=365)  # Margines na przyszłość
                    is_curr = True

                # Formatowanie do wyświetlania
                s_txt = s_date.strftime('%d.%m.%Y') if pd.notna(s_date) else "?"
                e_txt = "obecnie" if is_curr else (e_date.strftime('%d.%m.%Y') if pd.notna(row.get('koniec')) else "?")

                if pd.notna(s_date):
                    tenure_list.append(f"{s_txt} — {e_txt}")
                    # Dodajemy do maski mecze, które mieszczą się w tym zakresie
                    # Ważne: fillna(False) dla dat, których nie udało się sparsować
                    current_mask = (df_m['dt_temp'] >= s_date) & (df_m['dt_temp'] <= e_date)
                    matches_mask |= current_mask

    # Zastosowanie maski i sortowanie
    coach_matches = df_m[matches_mask].sort_values('dt_temp',
                                                   ascending=False) if not matches_mask.empty else pd.DataFrame()

    # --- WIDOK PROFILU ---
    st.markdown(f"## 👔 {coach_name}")

    nat_raw = base_info.get('Narodowość', '-')
    c1, c2 = st.columns([1, 4])

    with c1:
        flags_html = get_multi_flags_html(nat_raw)
        if flags_html:
            st.markdown(flags_html, unsafe_allow_html=True)
        else:
            st.markdown("### 🏳️")

    with c2:
        age_info = ""
        col_b = next((c for c in base_info.index if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
        if col_b:
            age, is_bday = get_age_and_birthday(base_info[col_b])
            if is_bday:
                st.balloons()
                st.success(f"🎉🎂 Wszystkiego najlepszego Trenerze! ({age} lat)")
            if age: age_info = f"| **Wiek:** {age} lat"

        st.markdown(f"**Narodowość:** {nat_raw} {age_info}")
        st.markdown("**Kadencje:**")
        if tenure_list:
            for t in tenure_list:
                st.markdown(f"- 📅 {t}")
        else:
            st.caption("Brak danych o datach kadencji.")

    st.divider()

    # --- STATYSTYKI OGÓLNE ---
    if not coach_matches.empty:
        wins, draws, losses, gf, ga = 0, 0, 0, 0, 0
        for _, m in coach_matches.iterrows():
            res = parse_result(m.get('wynik'))
            if res:
                gf += res[0];
                ga += res[1]
                if res[0] > res[1]:
                    wins += 1
                elif res[0] == res[1]:
                    draws += 1
                else:
                    losses += 1

        total = wins + draws + losses
        ppg = pts = (wins * 3) + draws
        ppg_val = pts / total if total > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Mecze", total)
        k2.metric("Bilans", f"{wins}-{draws}-{losses}")
        k3.metric("Średnia pkt", f"{ppg_val:.2f}")
        k4.metric("Bramki", f"{gf}:{ga}")

        st.divider()
        st.subheader("📜 Historia Meczów (Sezonami)")
        st.caption("ℹ️ Kliknij w wiersz tabeli, aby zobaczyć szczegóły meczu.")

        # Przygotowanie danych do wyświetlania
        display_df = coach_matches.copy()
        display_df['Data'] = display_df['dt_temp']
        display_df['Gdzie'] = display_df['dom'].apply(
            lambda x: "🏠" if str(x).lower() in ['1', 'true', 'dom', 'tak'] else "🚌")

        if 'sezon' not in display_df.columns:
            display_df['sezon'] = "Nieznany"

        # --- GRUPOWANIE PO SEZONACH ---
        # Pobieramy unikalne sezony w kolejności występowania (dzięki sortowaniu po dacie są już poukładane)
        unique_seasons = display_df['sezon'].unique()

        for sezon in unique_seasons:
            with st.expander(f"📂 Sezon {sezon}", expanded=True):
                # Filtrujemy mecze dla danego sezonu
                season_matches = display_df[display_df['sezon'] == sezon].copy()

                # Kolumny
                cols_needed = ['Data', 'rywal', 'wynik', 'Gdzie', 'rozgrywki']
                final_cols = [c for c in cols_needed if c in season_matches.columns]

                # Tabela interaktywna
                event = st.dataframe(
                    season_matches[final_cols].style.map(color_results_logic, subset=[
                        'wynik'] if 'wynik' in season_matches.columns else None),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"coach_hist_{sezon}",  # Unikalny klucz dla każdego sezonu
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                        "rywal": st.column_config.TextColumn("Rywal"),
                        "wynik": st.column_config.TextColumn("Wynik"),
                        "Gdzie": st.column_config.TextColumn("D/W", width="small")
                    }
                )

                # Obsługa kliknięcia w danym sezonie
                if event.selection.rows:
                    idx = event.selection.rows[0]
                    selected_match = season_matches.iloc[idx]

                    sel_date = selected_match['Data'].date()
                    sel_rival = selected_match.get('rywal', 'Rywal')
                    sel_score = selected_match.get('wynik', '-')

                    st.markdown("---")
                    st.markdown(f"#### 🔎 Raport meczowy ({sel_date.strftime('%d.%m.%Y')})")

                    # Szukamy składu w wystepy.csv
                    found_squad = pd.DataFrame()
                    if df_details is not None and 'Data_Sort' in df_details.columns:
                        found_squad = df_details[df_details['Data_Sort'].dt.date == sel_date].copy()

                    if not found_squad.empty:
                        found_squad = found_squad.sort_values('File_Order')
                        real_label = found_squad.iloc[0]['Mecz_Label']
                        render_match_report_logic(real_label, found_squad)
                    else:
                        # Jeśli brak składu w występy.csv, próbujemy pokazać chociaż strzelców z mecze.csv
                        # Wywołujemy naszą funkcję z pustym DF składu, ale z poprawnym labelem
                        # Żeby funkcja zadziałała, musimy oszukać sprawdzenie "if empty" wewnątrz niej,
                        # albo po prostu wyświetlić strzelców ręcznie tutaj.
                        # Wybierzmy opcję ręczną dla bezpieczeństwa:

                        st.warning("Brak szczegółowego składu (wystepy.csv). Wyświetlam dostępne dane ogólne:")

                        raw_scorers = str(selected_match.get('strzelcy', '-'))
                        if raw_scorers not in ['-', 'nan', '']:
                            st.markdown(f"**⚽ Strzelcy:** {raw_scorers}")
                        else:
                            st.info("Brak danych o strzelcach.")

    else:
        st.info("Brak zarejestrowanych meczów w bazie dla tego trenera (sprawdź poprawność dat w plikach csv).")


@st.cache_data
def load_details(filename="wystepy.csv"):
    if not os.path.exists(filename):
        return None
    try:
        try:
            df = pd.read_csv(filename, sep=';', encoding='utf-8')
        except:
            df = pd.read_csv(filename, sep=';', encoding='windows-1250')

        df['File_Order'] = df.index

        # --- 1. NAPRAWA DAT (CLEAN & PARSE) ---
        if 'Data' in df.columns:
            def clean_and_parse_date(date_str):
                s = str(date_str).strip().lower()
                if s in ['nan', '', '-', 'null']: return pd.NaT
                if ':' in s and len(s.split()) > 1:
                    s = " ".join(s.split()[:-1])

                months_map = {
                    'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
                    'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
                    'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12',
                    'styczeń': '01', 'luty': '02', 'marzec': '03', 'kwiecień': '04',
                    'maj': '05', 'czerwiec': '06', 'lipiec': '07', 'sierpień': '08',
                    'wrzesień': '09', 'październik': '10', 'listopad': '11', 'grudzień': '12'
                }

                for pl, digit in months_map.items():
                    if pl in s:
                        s = s.replace(pl, digit)
                        break
                s = re.sub(r'\s+', ' ', s).strip()
                for fmt in ['%d %m %Y', '%d.%m.%Y', '%Y-%m-%d']:
                    try:
                        return pd.to_datetime(s, format=fmt)
                    except:
                        continue
                return pd.NaT

            df['Data_Sort'] = df['Data'].apply(clean_and_parse_date)
            df['Data_Sort'] = df['Data_Sort'].fillna(pd.Timestamp('1900-01-01'))
            df = df.sort_values(['Data_Sort', 'File_Order'], ascending=[False, True])

        # --- 2. RESZTA LOGIKI ---
        if 'Zawodnik' in df.columns:
            df['Zawodnik_Clean'] = df['Zawodnik'].astype(str).str.strip()

        if 'Data' in df.columns:
            def make_label(row):
                d_str = str(row.get('Data', ''))
                if 'Gospodarz' in row and 'Gość' in row:
                    host, guest = str(row['Gospodarz']).strip(), str(row['Gość']).strip()
                    res = str(row.get('Wynik', '-'))
                    return f"{d_str} | {host} - {guest} ({res})"
                elif 'Przeciwnik' in row:
                    opp = str(row['Przeciwnik']).strip()
                    res = str(row.get('Wynik', '-'))
                    return f"{d_str} | {opp} ({res})"
                return "Mecz"

            df['Mecz_Label'] = df.apply(make_label, axis=1)

        numeric_cols = ['Minuty', 'Wejście', 'Zejście', 'Gole', 'Żółte', 'Czerwone']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            else:
                df[col] = 0

        # --- LOGIKA MINUT (POPRAWIONA) ---
        def calc_mins(row):
            status = str(row.get('Status', '')).strip()
            entry, exit_t, curr = row['Wejście'], row['Zejście'], row['Minuty']
            res_s = str(row.get('Wynik', '')).lower()

            # Dogrywka = 120 minut, zwykły = 90
            full = 120 if ('pd.' in res_s or 'dogr.' in res_s) else 90

            ev_min = 0
            if status == 'Wszedł':
                ev_min = entry
            elif status == 'Zszedł':
                ev_min = exit_t
            elif status == 'Czerwona kartka' or row['Czerwone'] > 0:
                ev_min = exit_t if exit_t > 0 else curr

            real = curr

            # 1. Czerwona kartka i zejście
            if (status == 'Czerwona kartka' or row['Czerwone'] > 0) and exit_t > 0:
                real = (exit_t - entry) if entry > 0 else exit_t

            # 2. Cały mecz
            elif status in ['Cały mecz', 'Grał'] and entry == 0 and exit_t == 0:
                real = full

            # 3. Wejście z ławki (POPRAWKA "BYCZKA")
            elif status == 'Wszedł' and exit_t == 0:
                calc = full - entry
                # Jeśli wszedł w 90 minucie (90-90=0) lub w doliczonym (np. 90-92=-2),
                # to i tak liczymy mu przynajmniej 1 minutę do statystyk.
                real = calc if calc > 0 else 1

            return pd.Series([ev_min, real])

        df[['Minuta_Zmiany_Real', 'Minuty']] = df.apply(calc_mins, axis=1)
        return df
    except Exception as e:
        return None


def get_flag_url(name):
    """Pobiera URL flagi. Dla wpisów typu 'Polska / Niemcy' bierze pierwszą część (do tabeli)."""
    if not isinstance(name, str) or pd.isna(name) or name.strip() in ['-', '']: return None
    # Bierzemy pierwszy człon przed ukośnikiem
    clean_name = name.split('/')[0].strip()
    code = COUNTRY_TO_ISO.get(clean_name.lower())
    if not code:
        name_lower = clean_name.lower()
        for k, v in COUNTRY_TO_ISO.items():
            if k.lower() == name_lower:
                code = v;
                break
    if code: return f"https://flagcdn.com/w40/{code}.png"
    return None


def get_multi_flags_html(nat_string):
    """Generuje czysty HTML dla wielu flag w profilu."""
    if pd.isna(nat_string) or str(nat_string).strip() in ['-', '', 'nan']: return ""

    # Dzielimy po ukośniku i czyścimy spacje
    parts = [p.strip() for p in str(nat_string).split('/')]

    imgs = ""
    for country_name in parts:
        url = get_flag_url(country_name)
        if url:
            # Styl inline dla pewności renderowania
            imgs += f'<img src="{url}" title="{country_name}" style="height: 24px; border: 1px solid #ddd; border-radius: 4px; margin-right: 6px;">'

    if not imgs: return ""
    # Zwracamy w kontenerze flex
    return f'<div style="display:flex; align-items:center; margin-top:8px;">{imgs}</div>'

    return html_out if found_any else ""


def prepare_flags(df, col='narodowość'):
    """Dodaje kolumnę 'Flaga' do DataFrame (tylko pierwsza flaga do tabel)."""
    target_col = col
    # Szukamy kolumny z narodowością
    if target_col not in df.columns:
        poss = [c for c in df.columns if c.lower() in ['kraj', 'narodowosc', 'narodowość']]
        if poss: target_col = poss[0]

    if target_col in df.columns:
        # Do tabeli głównej bierzemy URL pierwszej flagi
        df['Flaga'] = df[target_col].apply(get_flag_url)
        # Ujednolicamy nazwę kolumny
        df = df.rename(columns={target_col: 'Narodowość'})
    else:
        df['Flaga'] = None
        df['Narodowość'] = '-'
    return df


@st.cache_data
def load_data(filename):
    if not os.path.exists(filename): return None
    try:
        try:
            df = pd.read_csv(filename, sep=None, engine='python', encoding='utf-8')
        except:
            df = pd.read_csv(filename, sep=None, engine='python', encoding='windows-1250')

        df = df.fillna("-")
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        cols_drop = [c for c in df.columns if 'lp' in c]
        if cols_drop: df = df.drop(columns=cols_drop)

        # 1. PEŁNA LISTA KOLUMN LICZBOWYCH (DO NAPRAWY BŁĘDÓW)
        # Dodano wszystkie kolumny statystyczne, które mogą powodować błędy
        int_candidates = [
            'wiek', 'suma', 'liczba', 'mecze', 'gole', 'punkty', 'minuty', 'numer',
            'asysty', 'żółte kartki', 'czerwone kartki', 'kanadyjka',
            'gole samobójcze', 'asysta 2. stopnia', 'sprokurowany karny', 'wywalczony karny',
            'karny', 'niestrzelony karny', 'główka', 'lewa', 'prawa', 'czyste konta',
            'obronione karne', 'wpuszczone gole', 'obronione rzuty karne'
        ]

        for col in df.columns:
            # Sprawdzamy czy nazwa kolumny pasuje do listy kandydatów
            if col in int_candidates or 'kartki' in col or 'gole' in col or 'karny' in col:
                # Najpierw konwersja do liczb (zamienia puste i błędy na NaN)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                # Potem rzutowanie na liczbę całkowitą (usuwa ".0")
                df[col] = df[col].astype(int)

        # Specyficzne dla mecze.csv
        if 'mecze.csv' in filename:
            col_att = next((c for c in df.columns if c in ['frekwencja', 'widzów']), None)
            if col_att:
                if col_att != 'widzów': df.rename(columns={col_att: 'widzów'}, inplace=True)
                df['widzów'] = df['widzów'].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '',
                                                                                                         regex=True)
                df['widzów'] = pd.to_numeric(df['widzów'], errors='coerce').fillna(0).astype(int)

            place_col = next((c for c in df.columns if c in ['miejsce rozgrywania', 'miejsce', 'stadion']), None)
            if place_col:
                def is_h(val):
                    s = str(val).lower()
                    kw = ['bielsko', 'rychlińskiego', 'startowa', 'rekord', 'bks', 'czechowice', 'dom', 'gospodarz']
                    return '1' if any(k in s for k in kw) else '0'

                df['dom'] = df[place_col].apply(is_h)

        return df
    except Exception as e:
        return None


def prepare_flags(df, col='narodowość'):
    target_col = col
    if target_col not in df.columns:
        poss = [c for c in df.columns if c in ['kraj', 'narodowosc', 'narodowość']]
        if poss: target_col = poss[0]

    if target_col in df.columns:
        df['flaga'] = df[target_col].apply(get_flag_url)
        df = df.rename(columns={target_col: 'Narodowość', 'flaga': 'Flaga'})
        cols = list(df.columns)
        if 'Narodowość' in cols and 'Flaga' in cols:
            cols.remove('Flaga');
            cols.insert(cols.index('Narodowość') + 1, 'Flaga')
            df = df[cols]
    return df


def parse_result(val):
    if not isinstance(val, str): return None

    clean_val = val.lower().replace(" ", "")

    # 1. SZUKANIE KARNYCH (Priorytet najwyższy)
    pen_match = re.search(r'\(?k\.?(\d+)[:\-](\d+)\)?', clean_val)
    if pen_match:
        return int(pen_match.group(1)), int(pen_match.group(2))

    # 2. CZYSZCZENIE "pd." (Po dogrywce)
    clean_val = clean_val.replace("pd.", "").replace("dogr.", "")
    clean_val = re.sub(r'\(.*?\)', '', clean_val)

    # 3. SZUKANIE STANDARDOWEGO WYNIKU
    score_match = re.search(r'(\d+)[:\-](\d+)', clean_val)
    if score_match:
        return int(score_match.group(1)), int(score_match.group(2))

    return None


def render_match_report_logic(match_label, squad_df):
    """
    Wyświetla raport meczowy.
    Wersja FIXED: Pobiera datę bezpośrednio ze składu (squad_df) i łączy z mecze.csv/trenerzy.csv.
    """

    # 1. Pobranie daty i nazwy rywala BEZPOŚREDNIO z danych (Data_Sort z load_details)
    target_date = None
    rival_raw = ""

    if not squad_df.empty:
        # Pobieramy datę z już przetworzonej kolumny Data_Sort
        if 'Data_Sort' in squad_df.columns:
            try:
                dt_val = squad_df.iloc[0]['Data_Sort']
                if pd.notna(dt_val):
                    target_date = pd.to_datetime(dt_val).date()
            except:
                pass

        # Pobieramy rywala z kolumn (żeby mieć pewność kogo szukamy)
        if 'Przeciwnik' in squad_df.columns:
            rival_raw = str(squad_df.iloc[0]['Przeciwnik']).strip()
        elif 'Gospodarz' in squad_df.columns and 'Gość' in squad_df.columns:
            h = str(squad_df.iloc[0]['Gospodarz'])
            g = str(squad_df.iloc[0]['Gość'])
            my_aliases = ['podbeskidzie', 'tsp', 'bielsko']
            # Jeśli my jesteśmy gospodarzem, rywal to gość i vice versa
            if any(x in h.lower() for x in my_aliases):
                rival_raw = g
            elif any(x in g.lower() for x in my_aliases):
                rival_raw = h
            else:
                rival_raw = g  # Domyślnie gość

    # Fallback (gdyby Data_Sort z jakiegoś powodu nie zadziałała)
    if not target_date:
        try:
            date_part = match_label.split('|')[0].strip()
            # Próba parsowania polskiej daty
            months = {'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04', 'maja': '05', 'czerwca': '06',
                      'lipca': '07', 'sierpnia': '08', 'września': '09', 'października': '10', 'listopada': '11',
                      'grudnia': '12'}
            for k, v in months.items(): date_part = date_part.lower().replace(k, v)
            target_date = pd.to_datetime(date_part, dayfirst=True).date()
        except:
            pass

    # Helper do parsowania dat w CSV (mecze/trenerzy)
    def aggressive_date_parse(val):
        if pd.isna(val) or str(val).strip() in ['', '-', 'nan']: return None
        s = str(val).strip()
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y.%m.%d']:
            try:
                return pd.to_datetime(s, format=fmt).date()
            except:
                continue
        try:
            return pd.to_datetime(s).date()
        except:
            return None

    # ==========================
    # A. DANE Z MECZE.CSV (Strzelcy)
    # ==========================
    scorers_html = ""
    df_matches = load_data("mecze.csv")

    if df_matches is not None and target_date:
        col_d = next((c for c in df_matches.columns if c in ['data meczu', 'data', 'dt_obj']), None)

        if col_d:
            # Tworzymy kolumnę z czystą datą
            df_matches['clean_date'] = df_matches[col_d].apply(aggressive_date_parse)

            # Strategia 1: Szukamy idealnie po dacie (+/- 1 dzień tolerancji na błędy)
            s_win = target_date - datetime.timedelta(days=1)
            e_win = target_date + datetime.timedelta(days=1)
            match_row = df_matches[(df_matches['clean_date'] >= s_win) & (df_matches['clean_date'] <= e_win)]

            # Strategia 2: Jeśli znaleziono więcej niż 1 mecz, filtrujemy po Rywalu
            if len(match_row) > 1 and rival_raw:
                def norm(txt):
                    return str(txt).lower().replace('ks ', '').replace('mks ', '').replace('gks ', '').strip()

                r_target = norm(rival_raw)
                if 'rywal' in match_row.columns:
                    match_row = match_row[
                        match_row['rywal'].apply(lambda x: r_target in norm(x) or norm(x) in r_target)]

            # Generowanie HTML strzelców
            if not match_row.empty:
                raw_scorers = str(match_row.iloc[0].get('strzelcy', '-'))
                if raw_scorers not in ['-', 'nan', '', 'NaN']:
                    scorers_list = []
                    for part in raw_scorers.split(','):
                        part = part.strip()
                        if not part: continue

                        style = "font-weight:bold; color: inherit;"
                        icon = "⚽"

                        # Obsługa samobójów i karnych
                        if any(x in part.lower() for x in ['(s)', 'sam.', 's.']):
                            style = "color: #dc3545; font-weight:bold;"
                            icon = "🔴"
                            part = re.sub(r'\(s\)|s\.|sam\.', '(sam.)', part, flags=re.IGNORECASE)
                        elif any(x in part.lower() for x in ['(k)', 'k.', 'karny']):
                            style = "color: #28a745; font-weight:bold;"
                            icon = "🥅"
                            part = re.sub(r'\(k\)|k\.|karny', '(k)', part, flags=re.IGNORECASE)

                        scorers_list.append(f"<span style='{style}'>{icon} {part}</span>")

                    if scorers_list:
                        scorers_html = f"<div style='margin-top:10px; padding-top:10px; border-top:1px dashed #ccc; font-size:0.9em; line-height:1.6;'>{' &nbsp;•&nbsp; '.join(scorers_list)}</div>"

    # ==========================
    # B. DANE Z TRENERZY.CSV
    # ==========================
    coach_name = None
    df_coaches = load_data("trenerzy.csv")

    if df_coaches is not None and target_date:
        col_start = next((c for c in df_coaches.columns if c in ['początek', 'start']), None)
        col_end = next((c for c in df_coaches.columns if c in ['koniec', 'end']), None)

        if col_start:
            for _, c_row in df_coaches.iterrows():
                try:
                    s_date = aggressive_date_parse(c_row[col_start])
                    if not s_date: continue

                    if col_end and pd.notna(c_row[col_end]):
                        e_date = aggressive_date_parse(c_row[col_end])
                        if not e_date: e_date = datetime.date.today() + datetime.timedelta(days=365)
                    else:
                        e_date = datetime.date.today() + datetime.timedelta(days=365)

                    if s_date <= target_date <= e_date:
                        coach_name = c_row['imię i nazwisko']
                        break
                except:
                    continue

    # ==========================
    # C. WYŚWIETLANIE NAGŁÓWKA
    # ==========================
    # Parsowanie etykiety tylko do wyświetlenia tytułu
    try:
        parts = match_label.split('|')
        info_s = parts[1].strip() if len(parts) > 1 else match_label
        date_s = parts[0].strip()
    except:
        info_s = match_label
        date_s = str(target_date) if target_date else "-"

    st.markdown(f"""
    <div style="text-align: center; padding: 15px; background-color: rgba(40, 167, 69, 0.1); border: 1px solid #28a745; border-radius: 8px; margin-bottom: 10px;">
        <h3 style="margin:0; color: var(--text-color);">{info_s}</h3>
        <p style="color: gray; margin: 4px 0 0 0; font-size: 0.85em;">📅 {date_s}</p>
        {scorers_html}
    </div>
    """, unsafe_allow_html=True)

    if coach_name:
        _, c_btn, _ = st.columns([1, 2, 1])
        with c_btn:
            if st.button(f"👔 Trener: {coach_name}",
                         key=f"coach_btn_{match_label}_{st.session_state.get('uploader_key', 0)}",
                         use_container_width=True):
                st.session_state['selected_coach'] = coach_name
                st.session_state['coach_view_mode'] = 'profile'
                st.session_state['opcja'] = 'Trenerzy'
                st.rerun()

    # ==========================
    # D. SKŁAD I ZMIANY
    # ==========================
    if squad_df.empty:
        st.warning("Brak szczegółowego składu.")
        return

    map_in_to_out = {}
    map_out_to_in = {}

    sort_c = 'Wejście' if 'Wejście' in squad_df.columns else 'Minuty'
    in_rows = squad_df[squad_df['Status'] == 'Wszedł'].sort_values(sort_c)
    out_rows = squad_df[squad_df['Status'] == 'Zszedł'].sort_values(sort_c)
    used_out = []

    for _, row_in in in_rows.iterrows():
        t_in = row_in.get('Wejście', 0)
        cands = out_rows[~out_rows.index.isin(used_out)].copy()
        cands['diff'] = (cands.get('Zejście', 999) - t_in).abs()
        cands = cands[cands['diff'] <= 5].sort_values('diff')

        if not cands.empty:
            best = cands.iloc[0]
            map_in_to_out[row_in['Zawodnik_Clean']] = best['Zawodnik_Clean']
            map_out_to_in[best['Zawodnik_Clean']] = row_in['Zawodnik_Clean']
            used_out.append(best.name)

    def render_row(row, is_sub=False):
        c1, c2, c3 = st.columns([1, 4, 3])
        mins = int(row.get('Minuty', 0))
        entry = int(row.get('Wejście', 0)) if is_sub else 0
        name = row['Zawodnik_Clean']
        status = row.get('Status', '')

        with c1:
            if is_sub:
                st.caption(f"{entry}'" if entry > 0 else "-")
            else:
                st.write(f"{mins}'" if mins > 0 else "-")

        with c2:
            if st.button(name, key=f"p_{match_label}_{name}_{is_sub}_{st.session_state.get('uploader_key', 0)}"):
                st.session_state['cm_selected_player'] = name
                st.rerun()

        evs = []
        g = int(row.get('Gole', 0))
        if g > 0: evs.append(f"<span style='color:#28a745; font-weight:bold;'>{'⚽' * g}</span>")

        y = int(row.get('Żółte', 0))
        if y > 0: evs.append(f"🟨{'x' + str(y) if y > 1 else ''}")

        r = int(row.get('Czerwone', 0))
        if r > 0 or status == 'Czerwona kartka': evs.append("🟥")

        if is_sub:
            rep = map_in_to_out.get(name)
            txt = f"za: {rep}" if rep else "Wejście"
            evs.append(f"<small style='color:#28a745'>⬆️ {txt}</small>")
        elif status == 'Zszedł':
            rep = map_out_to_in.get(name)
            txt = f"zm: {rep}" if rep else "Zejście"
            out_min = int(row.get('Zejście', 0))
            t_info = f"({out_min}')" if out_min > 0 else ""
            evs.append(f"<small style='color:#dc3545'>⬇️ {txt} {t_info}</small>")

        with c3:
            if evs: st.markdown(" ".join(evs), unsafe_allow_html=True)

    starters = squad_df[
        (squad_df['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka'])) &
        (squad_df['Status'] != 'Wszedł')
        ].sort_values('File_Order')

    subs = squad_df[squad_df['Status'] == 'Wszedł'].sort_values('Wejście')
    unused = squad_df[squad_df['Status'] == 'Rezerwowy']

    col_l, col_r = st.columns(2)
    with col_l:
        st.caption("🏟️ Wyjściowa XI")
        for _, r in starters.iterrows(): render_row(r, False)
    with col_r:
        st.caption("🔄 Zmiennicy")
        if not subs.empty:
            for _, r in subs.iterrows(): render_row(r, True)
        else:
            st.text("Brak zmian")
        if not unused.empty:
            st.markdown("---")
            st.caption("💤 Ławka")
            for _, r in unused.iterrows(): st.text(f"{r['Zawodnik_Clean']}")

        st.markdown("---")
        st.subheader("📢 Strefa Kibica")

        if st.session_state.get('logged_in'):
            # 1. OBECNOŚĆ
            match_id = match_label  # Używamy etykiety jako ID
            is_there = run_query("SELECT * FROM attendance WHERE username=? AND match_id=?",
                                 (st.session_state['username'], match_id), fetch=True)

            c_att, c_comm = st.columns([1, 2])
            with c_att:
                if is_there:
                    st.success("✅ Byłeś na tym meczu!")
                    if st.button("Cofnij obecność"):
                        run_query("DELETE FROM attendance WHERE username=? AND match_id=?",
                                  (st.session_state['username'], match_id))
                        st.rerun()
                else:
                    if st.button("🙋‍♂️ Byłem tam!"):
                        run_query("INSERT INTO attendance VALUES (?, ?, ?)",
                                  (st.session_state['username'], match_id, str(datetime.date.today())))
                        st.balloons()
                        st.rerun()

                # Licznik
                count_att = run_query("SELECT count(*) FROM attendance WHERE match_id=?", (match_id,), fetch=True)
                if count_att:
                    st.caption(f"Kibiców z aplikacji na meczu: {count_att[0][0]}")

            # 2. KOMENTARZE
            with c_comm:
                st.write("**Komentarze**")
                # Dodaj komentarz
                with st.form(key=f"comm_form_{match_id}"):
                    txt = st.text_area("Twój komentarz", height=80)
                    if st.form_submit_button("Wyślij"):
                        if txt:
                            run_query(
                                "INSERT INTO comments (match_id, username, comment, timestamp) VALUES (?, ?, ?, ?)",
                                (match_id, st.session_state['username'], txt, str(datetime.datetime.now())[:16]))
                            st.success("Dodano!")
                            st.rerun()

                # Lista komentarzy
                comms = run_query("SELECT username, comment, timestamp FROM comments WHERE match_id=? ORDER BY id DESC",
                                  (match_id,), fetch=True)
                if comms:
                    for author, text, ts in comms:
                        st.markdown(f"""
                        <div style="background-color:rgba(255,255,255,0.05); padding:10px; border-radius:5px; margin-bottom:5px;">
                            <small style="color:#28a745">@{author}</small> <small style="color:gray">({ts})</small><br>
                            {text}
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("Brak komentarzy. Bądź pierwszy!")

def color_results_logic(val):
    if not isinstance(val, str): return ''
    res = parse_result(val)
    style = ''
    if res:
        t, o = res
        if t > o:
            style = 'color: #28a745; font-weight: bold;'
        elif t < o:
            style = 'color: #dc3545; font-weight: bold;'
        else:
            style = 'color: #fd7e14; font-weight: bold;'

    if any(x in val.lower() for x in ['pd', 'k.', 'wo']):
        style += ' font-style: italic; background-color: #f0f0f040;'
    return style


def extract_scorers_list(scorers_str):
    """
    Zwraca listę słowników dla przycisków strzelców.
    Obsługuje format: "Zawodnik 20, 40" oraz "Zawodnik 20, Inny 50".
    """
    if not isinstance(scorers_str, str) or pd.isna(scorers_str) or scorers_str.strip() in ['-', '']:
        return []

    parts = scorers_str.split(',')
    result = []
    last_valid_name = None

    for part in parts:
        part = part.strip()
        if not part: continue

        icon = "⚽"
        is_own = False

        # Rozpoznawanie (sam.) i (k)
        if any(x in part.lower() for x in ['(s)', 's.', 'sam.']):
            icon = "🔴"
            is_own = True
        elif any(x in part.lower() for x in ['(k)', 'k.', 'karny']):
            icon = "⚽🥅"

        # Czysta nazwa do linkowania profilu
        clean_name_candidate = re.sub(r'\(.*?\)', '', part)
        clean_name_candidate = re.sub(r'\d+', '', clean_name_candidate)
        clean_name_candidate = clean_name_candidate.replace("s.", "").replace("k.", "").replace("'", "").strip()

        # Czy to nazwisko czy tylko minuta?
        has_letters = bool(re.search(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{2,}', clean_name_candidate))

        display_text = part
        link_name = ""

        if has_letters:
            last_valid_name = clean_name_candidate
            link_name = clean_name_candidate
            display_text = f"{icon} {part}"
        else:
            # Sytuacja: "43" po "Lazar 27"
            if last_valid_name:
                link_name = last_valid_name
                # Doklejamy nazwisko do wyświetlania, np. "⚽ Lazar 43'"
                # Czyścimy part z ewentualnych śmieci, zostawiając liczbę i flagi
                display_text = f"{icon} {last_valid_name} {part}"
            else:
                display_text = f"{icon} {part}"

        result.append({'display': display_text, 'link_name': link_name, 'is_own': is_own})

    return result


def parse_scorers(scorers_str):
    if not isinstance(scorers_str, str) or pd.isna(scorers_str) or scorers_str == '-': return {}
    parts = scorers_str.split(',')
    stats = {}
    current_scorer = None
    for part in parts:
        part = part.strip()
        if not part: continue
        is_own = bool(re.search(r'\(s\)|s\.|sam\.', part.lower()))
        clean_check = re.sub(r'\(k\)|k\.|\(s\)|s\.|sam\.', '', part.lower())
        has_letters = bool(re.search(r'[a-z]{2,}', clean_check))

        if has_letters:
            name = re.sub(r'\d+', '', part)
            name = re.sub(r'\(k\)|k\.|\(s\)|s\.|sam\.', '', name, flags=re.IGNORECASE)
            name = name.replace('(', '').replace(')', '').replace('.', '').strip()
            if name:
                current_scorer = name
                target = 'Bramka samobójcza' if is_own else current_scorer
                stats[target] = stats.get(target, 0) + 1
        else:
            if current_scorer:
                target = 'Bramka samobójcza' if is_own else current_scorer
                stats[target] = stats.get(target, 0) + 1
    return stats


def format_scorers_html(scorers_str):
    """Formatuje tekst strzelców dodając ikony dla karnych i samobójów."""
    if not isinstance(scorers_str, str) or pd.isna(scorers_str) or scorers_str.strip() in ['-', '']:
        return "<span style='color: gray; font-style: italic;'>Brak bramek / Brak danych</span>"

    parts = scorers_str.split(',')
    html_parts = []

    for part in parts:
        part = part.strip()
        if not part: continue

        # Logika ikon i stylów
        icon = "⚽"  # Domyślna piłka
        style = ""
        suffix = ""

        # Samobóje (priorytet sprawdzania)
        if any(x in part.lower() for x in ['(s)', 's.', 'sam.']):
            icon = "🔴"
            suffix = " (sam.)"
            part = re.sub(r'\(s\)|s\.|sam\.', '', part, flags=re.IGNORECASE).strip()
            style = "color: #dc3545;"  # Czerwony kolor

        # Karne
        elif any(x in part.lower() for x in ['(k)', 'k.', 'karny']):
            icon = "⚽🥅"  # Piłka + Bramka
            part = re.sub(r'\(k\)|k\.|karny', '', part, flags=re.IGNORECASE).strip()
            style = "font-weight: bold; color: #28a745;"  # Zielony pogrubiony

        html_parts.append(f"<span style='{style}'>{icon} {part}{suffix}</span>")

    return " | ".join(html_parts)


def get_minutes_map(scorers_str):
    """
    Tworzy mapę: nazwisko -> sformatowany tekst minut (np. 15', 88' (k)).
    Naprawia błąd braku przypisania kolejnych goli (np. 'Lazar 27, 43').
    """
    if not isinstance(scorers_str, str) or pd.isna(scorers_str): return {}

    mapping = {}
    parts = scorers_str.split(',')

    # Zmienna do zapamiętywania ostatniego zidentyfikowanego strzelca
    last_valid_name = None

    for part in parts:
        part = part.strip()
        if not part: continue

        # Wykrywanie flag
        is_pen = any(x in part.lower() for x in ['(k)', 'k.', 'karny'])
        is_own = any(x in part.lower() for x in ['(s)', 's.', 'sam.'])

        # Wyciąganie minut (wszystko co w nawiasie i jest cyfrą)
        mins_match = re.search(r'(\d+)', part)  # Szukamy po prostu liczb
        minutes_txt = mins_match.group(1) if mins_match else ""

        # Wyciąganie nazwiska (usuwamy cyfry, flagi i nawiasy)
        name_candidate = re.sub(r'\d+', '', part)
        name_candidate = re.sub(r'[\(\)]', '', name_candidate)  # usuń nawiasy
        name_candidate = re.sub(r'(k\.|s\.|sam\.|karny)', '', name_candidate, flags=re.IGNORECASE).strip()
        name_candidate = name_candidate.replace("'", "").strip()

        # Sprawdzamy czy to nowe nazwisko (musi mieć min. 2 litery)
        has_letters = bool(re.search(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{2,}', name_candidate))

        final_key_name = None

        if has_letters:
            last_valid_name = name_candidate
            final_key_name = name_candidate
        elif last_valid_name:
            # Jeśli nie ma liter, ale mamy zapamiętane nazwisko (sytuacja "Lazar 27, 43")
            final_key_name = last_valid_name

        # Jeśli nie mamy nazwiska ani teraz, ani wcześniej, pomijamy
        if not final_key_name:
            continue

        # Budowanie sformatowanego stringa
        final_note = ""
        if minutes_txt:
            final_note = f"{minutes_txt}'"

        if is_pen: final_note += " (k)"
        if is_own: final_note += " (sam.)"

        if final_note:
            key = final_key_name.lower().strip()
            if key in mapping:
                mapping[key] += f", {final_note}"
            else:
                mapping[key] = final_note

    return mapping


def get_age_and_birthday(birth_date_val):
    if pd.isna(birth_date_val) or str(birth_date_val) in ['-', '', 'nan']: return None, False
    formats = ['%Y-%m-%d', '%d.%m.%Y', '%Y/%m/%d']
    dt = None
    for f in formats:
        try:
            dt = pd.to_datetime(birth_date_val, format=f);
            break
        except:
            continue
    if dt is None:
        try:
            dt = pd.to_datetime(birth_date_val)
        except:
            return None, False
    today = datetime.date.today()
    born = dt.date()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    is_birthday = (today.month == born.month) and (today.day == born.day)
    return age, is_birthday


def calculate_exact_age_str(birth_date, event_date):
    """Oblicza wiek w formacie: X lat, Y mies., Z dni"""
    if pd.isna(birth_date) or pd.isna(event_date): return ""
    try:
        # Upewniamy się, że to datetime
        b = pd.to_datetime(birth_date).date()
        e = pd.to_datetime(event_date).date()

        # Obliczenia
        years = e.year - b.year
        if (e.month, e.day) < (b.month, b.day):
            years -= 1

        # Do obliczenia miesięcy i dni można użyć dateutil, ale zrobimy to prosto bez dodatkowych bibliotek
        # Resetujemy rok urodzenia do roku wydarzenia (lub poprzedniego)
        if (e.month, e.day) < (b.month, b.day):
            last_bday = datetime.date(e.year - 1, b.month, b.day)
        else:
            last_bday = datetime.date(e.year, b.month, b.day)

        delta = e - last_bday
        # Przybliżenie miesięcy (delta.days // 30) lub dokładniej:
        months = 0
        days = delta.days

        # Prostszą metodą dla wyświetlania jest:
        return f"({years} lat, {days // 30} mies., {days % 30} dni)"
    except:
        return ""


def get_player_record_badges(player_name, df_w=None, df_p=None):
    badges = []
    try:
        if df_w is None: df_w = load_details("wystepy.csv")
        if df_p is None: df_p = load_data("pilkarze.csv")

        # Filtrujemy dane gracza
        p_data = df_w[df_w['Zawodnik_Clean'] == player_name].copy()
        if p_data.empty: return []

        # Statystyki
        matches = len(p_data)
        goals = p_data['Gole'].sum()
        reds = p_data['Czerwone'].sum() + len(p_data[p_data['Status'] == 'Czerwona kartka'])
        yellows = p_data['Żółte'].sum()

        # 1. 💯 KLUB 100
        if matches >= 100:
            badges.append({"icon": "💯", "text": f"Klub 100 ({matches} spotkań)", "color": "#d63031"})

        # 2. ⚖️ PRAWDZIWY DŻENTELMEN (Poprawione)
        # Warunek: Min. 30 meczów, 0 czerwonych, Max 4 żółte (czysta gra)
        if matches >= 30 and reds == 0 and yellows < 5:
            badges.append({"icon": "⚖️", "text": "Prawdziwy Dżentelmen (Fair Play)", "color": "#16a085"})

        # 3. 🟥 BAD BOY
        if reds >= 2:
            badges.append({"icon": "🟥", "text": f"Bad Boy ({int(reds)} cz. kartki)", "color": "#e74c3c"})

        # 4. 🃏 SUPER JOKER (Poprawione)
        # Liczymy gole strzelone TYLKO jako zmiennik
        bench_goals = p_data[p_data['Status'] == 'Wszedł']['Gole'].sum()
        if bench_goals >= 3:
            badges.append({"icon": "🃏", "text": f"Super Joker ({int(bench_goals)} goli z ławki)", "color": "#e67e22"})

        # 5. 🎩 HAT-TRICK
        if any(p_data['Gole'] >= 3):
            cnt = len(p_data[p_data['Gole'] >= 3])
            badges.append({"icon": "🎩", "text": f"Hat-trick Hero ({cnt}x)", "color": "#2ecc71"})

        # 6. 🧱 MURARZ (Tylko bramkarze - heurystyka po czystych kontach)
        # Jeśli zagrał min. 10 meczów na 0 z tyłu
        clean_sheets = 0
        for _, r in p_data.iterrows():
            if r['Minuty'] >= 45 and '0' in str(r['Wynik']) and (
                    '0' in str(r['Wynik']).split('-')[0] or '0' in str(r['Wynik']).split('-')[1]):
                # Uproszczone sprawdzanie wyniku dla wydajności
                clean_sheets += 1  # To tylko heurystyka, dokładna w render_profile

        if clean_sheets >= 15:
            badges.append({"icon": "🧱", "text": f"Murarz ({clean_sheets} czystych kont)", "color": "#2c3e50"})

        # 7. 🚀 AWANS
        if 'Sezon' in p_data.columns:
            seasons = p_data['Sezon'].unique()
            if any(s in ['2010/2011', '2010/11'] for s in seasons):
                badges.append({"icon": "🚀", "text": "Awans do Ekstraklasy 2011", "color": "#f1c40f"})
            if any(s in ['2019/2020', '2019/20'] for s in seasons):
                badges.append({"icon": "🚀", "text": "Awans do Ekstraklasy 2020", "color": "#f1c40f"})

    except Exception as e:
        pass
    return badges


def admin_save_csv(filename, new_data_dict):
    try:
        df = pd.read_csv(filename)
        new_row = pd.DataFrame([new_data_dict])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(filename, index=False)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Błąd zapisu: {e}");
        return False


def get_match_icon(val):
    if pd.isna(val): return "🚌"
    s = str(val).lower().strip()
    if s in ['1', 'true', 'tak', 'dom', 'gospodarz', 'd', 'u siebie']: return "🏠"
    return "🚌"


# --- MENU ---
st.sidebar.header("Nawigacja")

# Definiujemy dostępne opcje
menu_options = [
    "Kalendarz",
    "Aktualny Sezon (25/26)",
    "Składy Historyczne",
    "Centrum Zawodników",
    "Centrum Meczowe",
    "🏆 Rekordy & TOP",
    "Trenerzy",
    "Strefa Kibica"
]

# Dodajemy tajną sekcję tylko jeśli użytkownik to nie 'guest'
if st.session_state.get('username') != 'guest':
    menu_options.append("🕵️ Ciemne Karty Historii")

opcja = st.sidebar.radio("Moduł:", menu_options)

st.sidebar.divider()

# --- PANEL ADMINA (Djero) ---
if st.session_state.get('username') == 'Djero':
    st.sidebar.markdown("### 🛠️ Panel Admina (Djero)")
    all_files = [f for f in os.listdir('.') if f.endswith('.csv')]

    with st.sidebar.expander("📝 EDYTOR DANYCH"):
        st.info("💡 Kliknij w pusty wiersz na dole tabeli, aby dodać nowy rekord.")
        selected_file = st.selectbox("Wybierz plik do edycji:", all_files)

        if selected_file:
            try:
                try:
                    df_editor = pd.read_csv(selected_file, encoding='utf-8')
                except:
                    df_editor = pd.read_csv(selected_file, encoding='windows-1250')

                # --- AUTO-NAPRAWA DLA MECZE.CSV ---
                is_changed = False
                if selected_file == "mecze.csv":
                    for col in df_editor.columns:
                        if col.lower().strip() == 'frekwencja':
                            df_editor.rename(columns={col: 'Widzów'}, inplace=True)
                            is_changed = True
                            break

                    synonyms_dom = ['dom', 'gospodarz', 'u siebie', 'gdzie']
                    cols_lower = [c.lower().strip() for c in df_editor.columns]
                    if not any(x in cols_lower for x in synonyms_dom):
                        df_editor['Dom'] = "-"
                        is_changed = True

                edited_df = st.data_editor(
                    df_editor,
                    num_rows="dynamic",
                    key=f"editor_{selected_file}_{st.session_state['uploader_key']}",
                    height=400
                )

                save_label = "💾 Zapisz zmiany"
                if is_changed: save_label += " (Auto-korekta kolumn)"

                if st.button(save_label, use_container_width=True):
                    try:
                        edited_df.to_csv(selected_file, index=False)
                        st.success(f"✅ Zapisano {selected_file}!")
                        st.cache_data.clear()
                        st.session_state['uploader_key'] += 1
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd zapisu: {e}")

            except Exception as e:
                st.error(f"Błąd pliku: {e}")

    with st.sidebar.expander("➕ SZYBKIE DODAWANIE"):
        tab_p, tab_m = st.tabs(["Piłkarz", "Mecz"])
        with tab_p:
            with st.form("add_player_form"):
                a_imie = st.text_input("Imię i Nazwisko")
                a_kraj = st.text_input("Kraj", value="Polska")
                a_poz = st.selectbox("Pozycja", ["Bramkarz", "Obrońca", "Pomocnik", "Napastnik"])
                a_data = st.date_input("Data urodzenia", min_value=datetime.date(1970, 1, 1))
                if st.form_submit_button("Zapisz Piłkarza"):
                    if a_imie and os.path.exists("pilkarze.csv"):
                        admin_save_csv("pilkarze.csv", {"imię i nazwisko": a_imie, "kraj": a_kraj, "pozycja": a_poz,
                                                        "data urodzenia": str(a_data), "SUMA": 0})
                        st.success(f"Dodano: {a_imie}");
                        time.sleep(1);
                        st.rerun()
        with tab_m:
            with st.form("add_result_form"):
                a_sezon = st.text_input("Sezon", value="2025/26")
                a_rywal = st.text_input("Rywal")
                a_wynik = st.text_input("Wynik (np. 2:1)")
                a_data_m = st.date_input("Data meczu")
                a_dom = st.selectbox("Gdzie?", ["Dom", "Wyjazd"])
                dom_val = "1" if a_dom == "Dom" else "0"
                if st.form_submit_button("Zapisz Mecz"):
                    if os.path.exists("mecze.csv"):
                        admin_save_csv("mecze.csv", {"sezon": a_sezon, "rywal": a_rywal, "wynik": a_wynik,
                                                     "data meczu": str(a_data_m), "Dom": dom_val, "Widzów": 0})
                        st.success("Dodano mecz!");
                        time.sleep(1);
                        st.rerun()
    st.sidebar.divider()
    # [NOWOŚĆ] SYMULACJA DATY
    with st.sidebar.expander("🕒 SYMULACJA CZASU"):
        st.info("Zmień datę, aby sprawdzić 'Dzień Meczowy' w Kalendarzu.")
        use_sim = st.checkbox("Włącz symulację daty", value=False)
        if use_sim:
            sim_date = st.date_input("Ustaw 'Dzisiaj' na:", value=datetime.date.today())
            st.session_state['simulated_today'] = sim_date
        else:
            st.session_state['simulated_today'] = None
if st.sidebar.button("Wyloguj"):
    logout()

# --- LOGIKA MODUŁÓW ---
# =========================================================
# MODUŁ: KALENDARZ (ZINTEGROWANY Z PROFILAMI TRENERÓW)
# =========================================================
elif opcja == "Kalendarz":
    # --- A. ZARZĄDZANIE STANEM WIDOKU (ROUTER) ---
    if 'cal_view_mode' not in st.session_state: st.session_state['cal_view_mode'] = 'list'
    if 'cal_selected_item' not in st.session_state: st.session_state['cal_selected_item'] = None

    # 1. WIDOK PROFILU ZAWODNIKA
    if st.session_state['cal_view_mode'] == 'profile':
        if st.button("⬅️ Wróć do Kalendarza"):
            st.session_state['cal_view_mode'] = 'list'
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cal_selected_item'])

    # 2. WIDOK PROFILU TRENERA
    elif st.session_state['cal_view_mode'] == 'coach_profile':
        if st.button("⬅️ Wróć do Kalendarza"):
            st.session_state['cal_view_mode'] = 'list'
            st.rerun()
        st.divider()
        render_coach_profile(st.session_state['cal_selected_item'])

    # 3. WIDOK SZCZEGÓŁÓW MECZU (ULEPSZONY - STYL RAPORTU)
    elif st.session_state['cal_view_mode'] == 'match':
        if st.button("⬅️ Wróć do Kalendarza"):
            st.session_state['cal_view_mode'] = 'list'
            st.rerun()
        st.divider()

        m_data = st.session_state['cal_selected_item']

        # Nagłówek
        st.markdown(f"""
        <div style="text-align: center; padding: 15px; background-color: rgba(40, 167, 69, 0.15); border: 1px solid #28a745; border-radius: 10px; margin-bottom: 25px;">
            <h2 style="margin:0; color: var(--text-color);">{m_data.get('Rywal', 'Rywal')}</h2>
            <p style="color: gray; margin: 5px 0 0 0;">📅 {m_data.get('Data_Txt', '-')} | 🏟️ {"Dom" if str(m_data.get('Dom')) in ['1', 'True'] else "Wyjazd"}</p>
            <h1 style="margin: 10px 0;">{m_data.get('Wynik', '-')}</h1>
            <small>Widzów: {m_data.get('Widzów', '-')}</small>
        </div>
        """, unsafe_allow_html=True)

        # --- SEKCJA STRZELCÓW ---
        scorers_str = m_data.get('Strzelcy', '-')
        if scorers_str and scorers_str != '-' and str(scorers_str).lower() != 'nan':
            st.markdown("### 🥅 Strzelcy")
            scorers_list = extract_scorers_list(scorers_str)
            if scorers_list:
                cols_sc = st.columns(4)
                for idx, item in enumerate(scorers_list):
                    col_idx = idx % 4
                    with cols_sc[col_idx]:
                        if item['is_own']:
                            st.error(item['display'])
                        else:
                            if st.button(item['display'], key=f"cal_match_sc_{idx}_{item['link_name']}"):
                                st.session_state['cal_selected_item'] = item['link_name']
                                st.session_state['cal_view_mode'] = 'profile'
                                st.rerun()
            else:
                st.write(scorers_str)
            st.divider()

        # --- SEKCJA SKŁADU (ZAPOŻYCZONA Z RAPORTÓW) ---
        df_det = load_details("wystepy.csv")

        # Próba znalezienia składu po dacie
        found_squad = False
        if df_det is not None and 'Data_Obj' in m_data:
            match_date = pd.to_datetime(m_data['Data_Obj']).date()

            if 'Data_Sort' in df_det.columns:
                # Filtrujemy po dacie (ignorujemy godzinę)
                squad = df_det[df_det['Data_Sort'].dt.date == match_date].copy()

                if not squad.empty:
                    found_squad = True
                    squad = squad.sort_values('File_Order')  # Zachowaj kolejność z pliku

                    # --- LOGIKA ZMIAN (Kopiuj-Wklej z Centrum Meczowego) ---
                    map_in_to_out = {}
                    map_out_to_in = {}
                    in_rows = squad[squad['Status'] == 'Wszedł'].sort_values('Minuta_Zmiany_Real')
                    out_rows = squad[squad['Status'].isin(['Zszedł'])].sort_values('Minuta_Zmiany_Real')
                    used_out = []

                    for _, ri in in_rows.iterrows():
                        m = ri['Minuta_Zmiany_Real']
                        cands = out_rows[~out_rows.index.isin(used_out)].copy()
                        cands['d'] = (cands['Minuta_Zmiany_Real'] - m).abs()
                        cands = cands[cands['d'] <= 3].sort_values('d')
                        if not cands.empty:
                            best = cands.iloc[0]
                            map_in_to_out[ri['Zawodnik_Clean']] = best['Zawodnik_Clean']
                            map_out_to_in[best['Zawodnik_Clean']] = ri['Zawodnik_Clean']
                            used_out.append(best.name)


                    # --- FUNKCJA RENDERUJĄCA ---
                    def render_cal_row(row, is_bench=False):
                        c1, c2, c3 = st.columns([1, 4, 3])
                        name = row['Zawodnik_Clean']
                        mins = int(row.get('Minuty', 0))
                        ev_min = int(row.get('Minuta_Zmiany_Real', 0))

                        with c1:
                            if is_bench:
                                st.caption(f"{ev_min}'")
                            else:
                                st.write(f"{mins}'")

                        with c2:
                            if st.button(name, key=f"c_sq_{name}_{match_date}", use_container_width=True):
                                st.session_state['cal_selected_item'] = name
                                st.session_state['cal_view_mode'] = 'profile'
                                st.rerun()

                        # Zdarzenia
                        evs = []
                        g = int(row.get('Gole', 0));
                        if g > 0: evs.append(f"<span style='color:green'>{'⚽' * g}</span>")
                        y = int(row.get('Żółte', 0));
                        if y > 0: evs.append(f"🟨{'x' + str(y) if y > 1 else ''}")
                        r = int(row.get('Czerwone', 0));
                        if r > 0: evs.append("🟥")

                        stat = row.get('Status', '')
                        if stat == 'Wszedł':
                            rep = map_in_to_out.get(name)
                            txt = f"za: {rep}" if rep else ""
                            evs.append(f"<span style='color:#28a745; font-size:0.8em'>⬆️ {txt}</span>")
                        elif stat == 'Zszedł':
                            rep = map_out_to_in.get(name)
                            txt = f"zm: {rep}" if rep else ""
                            evs.append(f"<span style='color:#dc3545; font-size:0.8em'>⬇️ {txt} ({ev_min}')</span>")
                        elif stat == 'Czerwona kartka':
                            evs.append(f"<span style='color:red; font-size:0.8em'>🟥 ({ev_min}')</span>")

                        with c3:
                            if evs: st.markdown(" ".join(evs), unsafe_allow_html=True)


                    # --- WYŚWIETLANIE ---
                    starters = squad[
                        squad['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka'])].sort_values(
                        'File_Order')
                    subs = squad[squad['Status'] == 'Wszedł'].sort_values('Minuta_Zmiany_Real')
                    unused = squad[squad['Status'] == 'Rezerwowy']

                    cl, cr = st.columns(2)
                    with cl:
                        st.subheader("🏟️ Wyjściowa XI")
                        if not starters.empty:
                            for _, r in starters.iterrows(): render_cal_row(r, False)
                        else:
                            st.info("Brak danych.")
                    with cr:
                        st.subheader("🔄 Zmiennicy")
                        if not subs.empty:
                            for _, r in subs.iterrows(): render_cal_row(r, True)
                        else:
                            st.caption("Brak zmian.")

                        if not unused.empty:
                            st.divider()
                            st.markdown("**💤 Ławka**")
                            for _, r in unused.iterrows():
                                if st.button(r['Zawodnik_Clean'], key=f"c_bench_{r['Zawodnik_Clean']}_{match_date}"):
                                    st.session_state['cal_selected_item'] = r['Zawodnik_Clean']
                                    st.session_state['cal_view_mode'] = 'profile'
                                    st.rerun()

        if not found_squad:
            st.info("ℹ️ Brak szczegółowego składu w `wystepy.csv` dla tej daty.")

    # 4. GŁÓWNY WIDOK KALENDARZA (BEZ ZMIAN W LOGICE, TYLKO KOD)
    else:
        st.header("📅 Kalendarz Klubowy")

        # Symulacja daty
        if st.session_state.get('simulated_today'):
            today = st.session_state['simulated_today']
            st.warning(f"⚠️ TRYB SYMULACJI: {today.strftime('%d.%m.%Y')}")
        else:
            today = datetime.date.today()

        # --- PRZEŁĄCZNIK TRYBÓW ---
        c_mode1, c_mode2 = st.columns([2, 2])
        with c_mode1:
            cal_mode = st.radio("Tryb widoku:", ["Dzień w Historii (2026 + Archiwum)", "Konkretny Rocznik (Archiwum)"],
                                horizontal=True)

        # Ustalanie roku bazowego
        if "Konkretny" in cal_mode:
            with c_mode2:
                target_year = st.number_input("Wybierz rok do przeglądania:", min_value=1990, max_value=2030,
                                              value=today.year)
            show_history_matches = False
        else:
            target_year = today.year
            show_history_matches = True
            with c_mode2:
                st.write("")

        # Ładowanie danych
        df_m = load_data("mecze.csv")
        df_p = load_data("pilkarze.csv")
        df_curr = load_data("25_26.csv")
        df_t = load_data("trenerzy.csv")

        # --- ALERT DNIA MECZOWEGO ---
        match_today_alert = None
        if df_m is not None:
            col_date_m = next((c for c in df_m.columns if 'data' in c and 'sort' not in c), None)
            if col_date_m:
                df_m['dt_obj'] = pd.to_datetime(df_m[col_date_m], dayfirst=True, errors='coerce')
                matches_today = df_m[df_m['dt_obj'].dt.date == today]
                if not matches_today.empty:
                    row_t = matches_today.iloc[0]
                    rival = row_t.get('rywal', 'Rywal')
                    place = "🏠 u siebie" if str(row_t.get('dom', '0')) in ['1', 'True', 'dom'] else "🚌 wyjazd"
                    match_today_alert = f"{rival} ({place})"

        if match_today_alert:
            st.markdown(f"""
            <div style="background-color: rgba(40, 167, 69, 0.2); border: 2px solid #28a745; padding: 15px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
                <h2 style="color: #28a745; margin:0;">🔥 DZIEŃ MECZOWY! 🔥</h2>
                <h3 style="margin:5px 0;">TSP vs {match_today_alert.split('(')[0]}</h3>
                <p style="margin:0; font-weight:bold;">{match_today_alert.split('(')[1].replace(')', '')}</p>
            </div>
            """, unsafe_allow_html=True)

        # --- BUDOWANIE MAPY ZDARZEŃ ---
        events_map = {}

        # A. Urodziny Piłkarzy
        if df_p is not None:
            df_p['id_name'] = df_p['imię i nazwisko'].astype(str).str.lower().str.strip()
            df_unique = df_p.drop_duplicates(subset=['id_name'], keep='first')
            col_b = next((c for c in df_unique.columns if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
            current_squad_names = [str(x).lower().strip() for x in
                                   df_curr['imię i nazwisko'].unique()] if df_curr is not None else []

            if col_b:
                for _, row in df_unique.iterrows():
                    try:
                        name = row['imię i nazwisko']
                        # Fix dla Macieja Górskiego
                        if "Maciej Górski" in str(name):
                            bdate = pd.to_datetime("1990-03-01")
                        else:
                            bdate = pd.to_datetime(row[col_b], dayfirst=True, errors='coerce')

                        if pd.isna(bdate): continue
                        key = (bdate.month, bdate.day)
                        is_curr = row['id_name'] in current_squad_names
                        prefix = "🟢🎂" if is_curr else "🎂"
                        age = target_year - bdate.year
                        if age >= 0:
                            events_map.setdefault(key, []).append(
                                {'type': 'birthday', 'label': f"{prefix} {name} ({age})", 'name': name,
                                 'sort': 1 if is_curr else 2})
                    except:
                        pass

        # B. Urodziny Trenerów
        if df_t is not None:
            df_t['id_name'] = df_t['imię i nazwisko'].astype(str).str.lower().str.strip()
            df_t_unique = df_t.drop_duplicates(subset=['id_name'], keep='first')
            col_bt = next((c for c in df_t_unique.columns if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
            if col_bt:
                for _, row in df_t_unique.iterrows():
                    try:
                        bdate = pd.to_datetime(row[col_bt], dayfirst=True, errors='coerce')
                        if pd.isna(bdate): continue
                        key = (bdate.month, bdate.day)
                        name = row.get('imię i nazwisko', 'Trener')
                        age = target_year - bdate.year
                        if age >= 0:
                            events_map.setdefault(key, []).append(
                                {'type': 'coach_birthday', 'label': f"👔🎂 {name} ({age})", 'name': name, 'sort': 2})
                    except:
                        pass

        # C. Mecze
        if df_m is not None and 'dt_obj' in df_m.columns:
            for _, row in df_m.dropna(subset=['dt_obj']).iterrows():
                d = row['dt_obj']
                d_date = d.date()
                key = (d.month, d.day)

                should_add = False
                is_history_event = False

                if show_history_matches:
                    if d.year == target_year:
                        should_add = True;
                        is_history_event = False
                    else:
                        should_add = True;
                        is_history_event = True
                else:
                    if d.year == target_year: should_add = True; is_history_event = False

                if should_add:
                    raw_score = str(row.get('wynik', '')).strip()
                    if raw_score.lower() == 'nan': raw_score = ''
                    rywal = row.get('rywal', 'Rywal')

                    if is_history_event:
                        icon = "⚫"
                        sort_prio = 5
                        score_part = f" {raw_score}" if raw_score else ""
                        label_str = f"{icon} {rywal}{score_part} ({d.year})"
                    else:
                        if d_date > today and d.year == today.year:
                            icon = "🔜";
                            info = "";
                            sort_prio = 0
                        elif d_date == today:
                            icon = "🔥";
                            info = raw_score if raw_score else "DZIŚ";
                            sort_prio = 0
                        else:
                            icon = "⚽";
                            info = raw_score;
                            sort_prio = 3
                        label_str = f"{icon} {rywal} {info}"

                    match_details = {'Rywal': rywal, 'Data_Txt': d.strftime('%d.%m.%Y'), 'Data_Obj': d,
                                     'Wynik': f"{raw_score}", 'Strzelcy': row.get('strzelcy', '-'),
                                     'Widzów': row.get('widzów', '-'), 'Dom': row.get('dom', '0')}

                    events_map.setdefault(key, []).append({
                        'type': 'match', 'label': label_str, 'match_data': match_details,
                        'sort': sort_prio, 'is_history': is_history_event
                    })

        # --- WIDOK 1: TYGODNIOWY ---
        st.subheader(f"Ten tydzień ({today.strftime('%B')})")
        start_of_week = today - datetime.timedelta(days=today.weekday())
        cols = st.columns(7)
        days_pl = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Ndz"]

        for i, col in enumerate(cols):
            curr_day = start_of_week + datetime.timedelta(days=i)
            is_today = (curr_day == today)
            lookup_key = (curr_day.month, curr_day.day)
            day_events = events_map.get(lookup_key, [])
            day_events.sort(key=lambda x: (x.get('sort', 5)))

            with col:
                css_class = "cal-card today" if is_today else "cal-card"
                st.markdown(
                    f"<div class='{css_class}'><small>{days_pl[i]}</small><br><strong>{curr_day.strftime('%d.%m')}</strong></div>",
                    unsafe_allow_html=True)
                if not day_events: st.markdown(
                    "<div style='text-align: center; opacity: 0.3; font-size: 10px;'>Brak</div>",
                    unsafe_allow_html=True)

                for idx, ev in enumerate(day_events):
                    btn_key = f"ev_w_{i}_{idx}_{ev['label']}"
                    if ev['type'] == 'birthday':
                        if st.button(ev['label'], key=btn_key, use_container_width=True):
                            st.session_state['cal_selected_item'] = ev['name']
                            st.session_state['cal_view_mode'] = 'profile'
                            st.rerun()
                    elif ev['type'] == 'coach_birthday':
                        if st.button(ev['label'], key=btn_key, use_container_width=True):
                            st.session_state['cal_selected_item'] = ev['name']
                            st.session_state['cal_view_mode'] = 'coach_profile'
                            st.rerun()
                    elif ev['type'] == 'match':
                        b_type = "secondary"
                        if not ev.get('is_history', False):
                            if "🔜" in ev['label'] or "🔥" in ev['label']: b_type = "primary"
                        if st.button(ev['label'], key=btn_key, type=b_type, use_container_width=True):
                            st.session_state['cal_selected_item'] = ev['match_data']
                            st.session_state['cal_view_mode'] = 'match'
                            st.rerun()
        st.divider()

        # --- WIDOK 2: MIESIĘCZNY ---
        with st.expander(f"📅 Pełny Kalendarz - {target_year} (Widok Miesięczny)", expanded=False):
            c_m2 = st.container()
            pl_months = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień",
                         "Październik", "Listopad", "Grudzień"]
            sel_month_name = c_m2.selectbox("Miesiąc", pl_months, index=today.month - 1)
            sel_month = pl_months.index(sel_month_name) + 1

            cols_h = st.columns(7)
            for i, d in enumerate(days_pl): cols_h[i].markdown(f"**{d}**")

            cal_data = calendar.monthcalendar(target_year, sel_month)
            for week in cal_data:
                cols_w = st.columns(7)
                for i, day_num in enumerate(week):
                    with cols_w[i]:
                        if day_num != 0:
                            is_today_cell = (
                                    day_num == today.day and sel_month == today.month and target_year == today.year)
                            css_class = "cal-card today" if is_today_cell else "cal-card"
                            st.markdown(f"<div class='{css_class}'><strong>{day_num}</strong></div>",
                                        unsafe_allow_html=True)

                            valid_events = events_map.get((sel_month, day_num), [])
                            valid_events.sort(key=lambda x: (x.get('sort', 5)))

                            for idx, ev in enumerate(valid_events):
                                btn_key = f"ev_month_{target_year}_{sel_month}_{day_num}_{idx}_{ev['label']}"
                                if ev['type'] == 'match':
                                    b_type = "secondary"
                                    if not ev.get('is_history', False):
                                        if "🔜" in ev['label'] or "🔥" in ev['label']: b_type = "primary"
                                    if st.button(ev['label'], key=btn_key, type=b_type, use_container_width=True):
                                        st.session_state['cal_selected_item'] = ev['match_data']
                                        st.session_state['cal_view_mode'] = 'match'
                                        st.rerun()
                                elif ev['type'] == 'birthday':
                                    if st.button(ev['label'], key=btn_key, use_container_width=True):
                                        st.session_state['cal_selected_item'] = ev['name']
                                        st.session_state['cal_view_mode'] = 'profile'
                                        st.rerun()
                                elif ev['type'] == 'coach_birthday':
                                    if st.button(ev['label'], key=btn_key, use_container_width=True):
                                        st.session_state['cal_selected_item'] = ev['name']
                                        st.session_state['cal_view_mode'] = 'coach_profile'
                                        st.rerun()

    st.caption("Legenda: 🔥 Dzień Meczowy | 🔜 Nadchodzące | 🟢 Kadra | ⚫ Archiwum (inne lata)")

elif opcja == "Aktualny Sezon (25/26)":
    st.header("📊 Kadra 2025/2026")

    # --- 0. ROUTER (Profil) ---
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do kadry"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # --- 1. WIDOK GŁÓWNY ---
    else:
        df = load_data("25_26.csv")
        if df is not None:
            # Przygotowanie danych
            if 'status' in df.columns:
                df['is_youth'] = df['status'].astype(str).str.contains(r'\(M\)', case=False, regex=True)
                df.loc[df['is_youth'], 'imię i nazwisko'] = "Ⓜ️ " + df.loc[df['is_youth'], 'imię i nazwisko']

            # Konwersja liczb
            numeric_cols_list = [
                'mecze', 'gole', 'asysty', 'kanadyjka', 'minuty', 'żółte kartki', 'czerwone kartki',
                'gole samobójcze', 'asysta 2. stopnia', 'wywalczony karny', 'sprokurowany karny',
                'karny', 'niestrzelony karny', 'główka', 'lewa', 'prawa', 'czyste konta', 'obronione karne'
            ]
            for col in numeric_cols_list:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

            df = prepare_flags(df)

            # Filtry UI
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            with c1:
                search_q = st.text_input("🔍 Szukaj:", placeholder="Nazwisko...")
            with c2:
                view_mode = st.selectbox("Widok:", ["Tabela Szczegółowa", "Podział na Formacje"])
            with c3:
                sort_by = st.selectbox("Sortuj:", ["Nr", "Mecze", "Gole", "Kartki"], index=0)
            with c4:
                show_only_youth = st.checkbox("Młodzieżowcy", value=False)

            # Filtrowanie
            df_view = df.copy()
            if show_only_youth: df_view = df_view[df_view['is_youth']]
            if search_q: df_view = df_view[
                df_view.astype(str).apply(lambda x: x.str.contains(search_q, case=False)).any(axis=1)]

            # Sortowanie
            sort_map = {'Nr': 'numer', 'Mecze': 'mecze', 'Gole': 'gole', 'Kartki': 'żółte kartki'}
            s_col = sort_map.get(sort_by, 'numer')
            if s_col in df_view.columns:
                asc = (s_col == 'numer')
                df_view = df_view.sort_values(s_col, ascending=asc)

            # Konfiguracja kolumn
            mx_mecze = int(df['mecze'].max()) if not df.empty else 1
            col_config = {
                "Flaga": st.column_config.ImageColumn("", width="small"),
                "mecze": st.column_config.ProgressColumn("Mecze", format="%d", min_value=0, max_value=mx_mecze),
                "gole": st.column_config.NumberColumn("Gole", format="%d ⚽"),
                "asysty": st.column_config.NumberColumn("Asysty", format="%d 🅰️"),
                "minuty": st.column_config.NumberColumn("Minuty", format="%d'")
            }


            # Helper do wyświetlania interaktywnej tabeli Z PODŚWIETLENIEM
            def show_interactive_table(data_frame, key_suffix=""):
                cols = ['numer', 'imię i nazwisko', 'Flaga', 'pozycja', 'mecze', 'minuty', 'gole', 'asysty',
                        'żółte kartki', 'czerwone kartki']
                final_cols = [c for c in cols if c in data_frame.columns]

                # Highlight logic - podświetlamy max wartości w kluczowych kolumnach
                subset_to_highlight = [c for c in ['mecze', 'gole', 'asysty', 'minuty'] if c in data_frame.columns]

                styled_df = data_frame[final_cols].style.highlight_max(
                    subset=subset_to_highlight,
                    color='#28a74530',  # Jasnozielone tło
                    axis=0
                )

                event = st.dataframe(
                    styled_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config=col_config,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"tab_kadra_{key_suffix}"
                )
                if event.selection.rows:
                    idx = event.selection.rows[0]
                    raw_name = data_frame.iloc[idx]['imię i nazwisko']
                    clean_name = str(raw_name).replace("Ⓜ️ ", "").strip()
                    st.session_state['cm_selected_player'] = clean_name
                    st.rerun()


            # RENDEROWANIE
            if view_mode == "Tabela Szczegółowa":
                show_interactive_table(df_view, "main")
            else:
                if 'pozycja' in df_view.columns:
                    # Kolejność logiczna
                    order = ["Bramkarz", "Obrońca", "Pomocnik", "Napastnik"]
                    available = df_view['pozycja'].astype(str).unique()

                    for pos in order:
                        if pos in available:
                            sub = df_view[df_view['pozycja'] == pos]
                            if not sub.empty:
                                st.markdown(f"### {pos}")
                                show_interactive_table(sub, f"pos_{pos}")
                                st.write("")  # Odstęp

                    # Pozostałe
                    for pos in available:
                        if pos not in order:
                            sub = df_view[df_view['pozycja'] == pos]
                            if not sub.empty:
                                st.markdown(f"### {pos}")
                                show_interactive_table(sub, f"pos_{pos}")

        else:
            st.error("Brak pliku 25_26.csv")

elif opcja == "Składy Historyczne":
    st.header("🗂️ Składy Historyczne")

    # --- 0. ROUTER ---
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do składu", key="back_from_player_hist"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # --- 1. WIDOK GŁÓWNY ---
    else:
        df_det = load_details("wystepy.csv")
        df_bio = load_data("pilkarze.csv")
        df_t = load_data("trenerzy.csv")

        if 'filter_seasons' in globals(): df_det = filter_seasons(df_det, 'Sezon')

        if df_det is None or df_bio is None:
            st.error("Brak wymaganych plików.")
        else:
            if df_t is not None: df_t = prepare_flags(df_t)
            seasons = sorted(df_det['Sezon'].unique(), reverse=True)

            c_sel_s, c_check_m = st.columns([3, 1])
            with c_sel_s:
                sel_season = st.selectbox("Wybierz Sezon:", seasons)
            with c_check_m:
                st.write("")
                st.write("")
                show_only_youth = st.checkbox("Tylko Młodzieżowcy (Ⓜ️)")


            # --- DANE DO LAT GRY ---
            def format_tenure_smart_func(seasons_series):
                years = sorted(list(set([int(str(s).split('/')[0]) for s in seasons_series if '/' in str(s)])))
                if not years: return "-"
                ranges = []
                start = prev = years[0]
                for y in years[1:]:
                    if y == prev + 1:
                        prev = y
                    else:
                        ranges.append(f"{start}-{prev + 1}" if start != prev else f"{start}")
                        start = prev = y
                ranges.append(f"{start}-{prev + 1}" if start != prev else f"{start}")
                return ", ".join(ranges)


            tenure_map = df_det[['Zawodnik_Clean', 'Sezon']].drop_duplicates().groupby('Zawodnik_Clean')['Sezon'].apply(
                format_tenure_smart_func).to_dict()

            # Dane z występów (wszyscy, nawet 0 minut, ale obecni w protokole)
            season_data = df_det[df_det['Sezon'] == sel_season].copy()

            # --- OBLICZANIE RUCHÓW KADROWYCH (TYLKO GRAJĄCY!) ---
            arrived_list = []
            left_list = []
            transfer_text_in = "-"
            transfer_text_out = "-"

            try:
                curr_year = int(sel_season.split('/')[0])
                candidates = [f"{curr_year - 1}/{str(curr_year)[-2:]}", f"{curr_year - 1}/{curr_year}"]
                found_prev = next((s for s in seasons if s in candidates), None)

                if found_prev:
                    prev_data = df_det[df_det['Sezon'] == found_prev]
                    curr_active = set(season_data[season_data['Minuty'] > 0]['Zawodnik_Clean'].unique())
                    prev_active = set(prev_data[prev_data['Minuty'] > 0]['Zawodnik_Clean'].unique())
                    arrived_list = sorted(list(curr_active - prev_active))
                    left_list = sorted(list(prev_active - curr_active))
                    transfer_text_in = str(len(arrived_list))
                    transfer_text_out = str(len(left_list))
                else:
                    transfer_text_in = "?"
                    transfer_text_out = "?"
            except:
                pass

            # --- AGREGACJA DANYCH ---
            agg = season_data.groupby('Zawodnik_Clean').agg({
                'Minuty': 'sum', 'Mecz_Label': 'nunique', 'Gole': 'sum', 'Żółte': 'sum', 'Czerwone': 'sum'
            }).reset_index()


            # 2. DOCIĄGANIE PIŁKARZY Z PLIKU CSV (którzy nie zagrali)
            # Normalizacja sezonu (np. zamiana 2023/2024 na 2023/24)
            def norm_season_id(v):
                s = str(v).strip()
                if re.match(r'\d{4}/\d{4}', s):  # Jeśli format YYYY/YYYY
                    p = s.split('/')
                    return f"{p[0]}/{p[1][-2:]}"  # Zamień na YYYY/YY
                return s


            col_sezon_bio = next((c for c in df_bio.columns if c.lower() == 'sezon'), None)

            if col_sezon_bio:
                # Tworzymy kolumny znormalizowane do porównania
                df_bio['season_norm'] = df_bio[col_sezon_bio].apply(norm_season_id)
                target_season_norm = norm_season_id(sel_season)

                # Filtrujemy po znormalizowanym sezonie
                csv_squad = df_bio[df_bio['season_norm'] == target_season_norm]['imię i nazwisko'].unique()
                current_agg_names = set(agg['Zawodnik_Clean'].unique())

                extras = []
                for name in csv_squad:
                    clean_n = str(name).strip()
                    if clean_n not in current_agg_names:
                        extras.append({
                            'Zawodnik_Clean': clean_n,
                            'Minuty': 0, 'Mecz_Label': 0, 'Gole': 0, 'Żółte': 0, 'Czerwone': 0
                        })

                if extras:
                    agg = pd.concat([agg, pd.DataFrame(extras)], ignore_index=True)


            # Obliczanie czystych kont
            def count_clean_sheets_season(sub_df):
                cs = 0
                for _, r in sub_df.iterrows():
                    try:
                        mins = pd.to_numeric(r.get('Minuty'), errors='coerce') or 0
                        if mins >= 45:
                            w_str = str(r.get('Wynik', '')).split('(')[0].strip()
                            parts = re.split(r'[:\-]', w_str)
                            if len(parts) >= 2:
                                g1, g2 = int(parts[0]), int(parts[1])
                                role = str(r.get('Rola', '')).lower()
                                conceded = g2 if ('gospodarz' in role or 'dom' in role) else g1
                                if conceded == 0: cs += 1
                    except:
                        pass
                return cs


            clean_sheets_map = season_data.groupby('Zawodnik_Clean').apply(count_clean_sheets_season)
            agg['Czyste_Konta'] = agg['Zawodnik_Clean'].map(clean_sheets_map).fillna(0).astype(int)
            agg.rename(columns={'Mecz_Label': 'Mecze'}, inplace=True)
            agg['Gole'] = pd.to_numeric(agg['Gole'], errors='coerce').fillna(0).astype(int)

            # Łączenie z profilem (pilkarze.csv)
            df_bio_unique = df_bio.drop_duplicates(subset=['imię i nazwisko']).copy()
            df_bio_unique['join_key'] = df_bio_unique['imię i nazwisko'].astype(str).str.strip()
            df_bio_unique = prepare_flags(df_bio_unique)

            merged = pd.merge(agg, df_bio_unique, left_on='Zawodnik_Clean', right_on='join_key', how='left')
            merged['Lata_Gry'] = merged['Zawodnik_Clean'].map(tenure_map).fillna("-")

            # Młodzieżowiec
            try:
                start_year = int(sel_season.split('/')[0])
            except:
                start_year = 2025
            limit_year = start_year - 21


            def check_youth_status(row):
                nat = str(row.get('Narodowość', '')).lower()
                if not any(x in nat for x in ['polska', 'poland', 'pl']): return False
                dob_val = row.get('data urodzenia')
                if pd.isna(dob_val): return False
                try:
                    y = pd.to_datetime(dob_val).year
                    return y >= limit_year
                except:
                    return False


            merged['Is_Youth'] = merged.apply(check_youth_status, axis=1)
            merged['Zawodnik_Display'] = merged.apply(
                lambda r: f"Ⓜ️ {r['Zawodnik_Clean']}" if r['Is_Youth'] else r['Zawodnik_Clean'], axis=1)

            if show_only_youth: merged = merged[merged['Is_Youth'] == True]


            def normalize_position_group(val):
                s = str(val).lower().strip()
                if 'bram' in s or 'gk' in s: return "Bramkarz"
                if any(x in s for x in ['obr', 'stoper', 'def', 'boczny']): return "Obrońca"
                if any(x in s for x in ['pom', 'skrzyd', 'mid', 'wahad']): return "Pomocnik"
                if any(x in s for x in ['nap', 'snaj', 'for', 'atak']): return "Napastnik"
                return "Inne"


            merged['Grupa_Pozycji'] = merged['pozycja'].apply(normalize_position_group)


            def calc_season_age(dob_val):
                try:
                    return start_year - pd.to_datetime(dob_val).year
                except:
                    return None


            merged['Wiek_w_Sezonie'] = merged['data urodzenia'].apply(calc_season_age)

            # --- STATYSTYKI ZBIORCZE ---
            if not show_only_youth:
                st.markdown(f"""
                <div style="background-color: var(--secondary-background-color); padding: 15px; border-radius: 10px; border: 1px solid #ccc; margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-around; flex-wrap: wrap;">
                        <div style="text-align: center; margin: 5px;"><h3>{agg['Gole'].sum()} ⚽</h3><small>Goli</small></div>
                        <div style="text-align: center; margin: 5px;"><h3>{len(agg)} 👤</h3><small>Piłkarzy</small></div>
                        <div style="text-align: center; margin: 5px;"><h3>{merged['Wiek_w_Sezonie'].mean():.1f} lat</h3><small>Średnia wieku</small></div>
                        <div style="text-align: center; margin: 5px; border-left: 1px solid #666; padding-left: 15px;">
                            <small style="color: gray;">Transfery (Grający)</small><br>
                            <strong>📥 {transfer_text_in}</strong> | <strong>📤 {transfer_text_out}</strong>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                if arrived_list or left_list:
                    with st.expander("🔄 Zobacz szczegóły transferów (Tylko zawodnicy z minutami)", expanded=False):
                        c_in, c_out = st.columns(2)
                        with c_in:
                            st.markdown(f"**📥 Przyszli ({len(arrived_list)})**")
                            st.caption(", ".join(arrived_list))
                        with c_out:
                            st.markdown(f"**📤 Odeszli ({len(left_list)})**")
                            st.caption(", ".join(left_list))

                st.divider()

            # --- TABELE FORMACJI ---
            formations_order = [
                ("Bramkarz", "🧤 Bramkarze"),
                ("Obrońca", "🛡️ Obrońcy"),
                ("Pomocnik", "⚙️ Pomocnicy"),
                ("Napastnik", "⚽ Napastnicy"),
                ("Inne", "❓ Nieznana pozycja/Brak danych")
            ]

            for group_key, header_txt in formations_order:
                df_pos = merged[merged['Grupa_Pozycji'] == group_key].sort_values(['Minuty', 'Mecze'], ascending=False)

                if not df_pos.empty:
                    st.markdown(f"#### {header_txt}")

                    is_gk = (group_key == "Bramkarz")
                    cols_base = ['Flaga', 'Zawodnik_Display', 'Lata_Gry', 'Wiek_w_Sezonie', 'Mecze', 'Minuty']
                    cols_stats = ['Czyste_Konta'] if is_gk else ['Gole']
                    cols_cards = ['Żółte', 'Czerwone']
                    final_cols = cols_base + cols_stats + cols_cards
                    final_df = df_pos[final_cols]

                    col_cfg = {
                        "Flaga": st.column_config.ImageColumn("", width="small"),
                        "Lata_Gry": st.column_config.TextColumn("Lata gry", width="medium"),
                        "Wiek_w_Sezonie": st.column_config.NumberColumn("Wiek", format="%d"),
                        "Minuty": st.column_config.ProgressColumn("Minuty", format="%d'",
                                                                  max_value=int(merged['Minuty'].max() or 100)),
                        "Żółte": st.column_config.NumberColumn("Żółte", format="%d 🟨"),
                        "Czerwone": st.column_config.NumberColumn("Czerwone", format="%d 🟥")
                    }

                    if is_gk:
                        col_cfg["Czyste_Konta"] = st.column_config.NumberColumn("Czyste Konta", format="%d 🧤")
                        styled_pos = final_df.style.highlight_max(subset=['Minuty', 'Czyste_Konta', 'Mecze'],
                                                                  color='#28a74530', axis=0)
                    else:
                        col_cfg["Gole"] = st.column_config.NumberColumn("Gole", format="%d ⚽")
                        styled_pos = final_df.style.highlight_max(subset=['Minuty', 'Gole', 'Mecze'], color='#28a74530',
                                                                  axis=0)

                    event_pos = st.dataframe(
                        styled_pos,
                        use_container_width=True, hide_index=True,
                        column_config=col_cfg,
                        on_select="rerun", selection_mode="single-row",
                        key=f"hist_table_{sel_season}_{group_key}"
                    )

                    if event_pos.selection.rows:
                        idx = event_pos.selection.rows[0]
                        raw = final_df.iloc[idx]['Zawodnik_Display']
                        st.session_state['cm_selected_player'] = str(raw).replace("Ⓜ️ ", "").strip()
                        st.rerun()
                    st.write("")

elif opcja == "Centrum Zawodników":
    st.header("👤 Centrum Zawodników")

    # --- A. ROUTER PROFILU ---
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do listy", key="back_cz"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # --- B. GŁÓWNA LISTA ---
    else:
        df_p = load_data("pilkarze.csv")
        df_w = load_details("wystepy.csv")

        # 1. PRZYGOTOWANIE DANYCH (AGREGACJA)
        stats_map = {}
        if df_w is not None:
            stats = df_w.groupby('Zawodnik_Clean').agg({'Gole': 'sum', 'Mecz_Label': 'nunique'}).reset_index()
            stats_map = stats.set_index('Zawodnik_Clean').to_dict('index')

        display_data = []

        # Jeśli mamy plik pilkarze.csv
        if df_p is not None:
            df_p = prepare_flags(df_p)
            df_p['clean'] = df_p['imię i nazwisko'].astype(str).str.strip()

            # Sortujemy po sumie meczów
            sort_c = 'suma' if 'suma' in df_p.columns else 'mecze'
            if sort_c in df_p.columns:
                df_p[sort_c] = pd.to_numeric(df_p[sort_c], errors='coerce').fillna(0)
                df_p = df_p.sort_values(sort_c, ascending=False)

            df_unique = df_p.drop_duplicates(subset=['clean'])

            # Zbieramy wszystkie nacje do filtra
            all_nations_set = set()

            for _, row in df_unique.iterrows():
                name = row['clean']

                # Zbieranie nacji
                nat_raw = str(row.get('Narodowość', '-'))
                if nat_raw not in ['-', 'nan', '']:
                    # Obsługa wielu nacji dzielonych przez '/'
                    parts = [n.strip() for n in nat_raw.split('/')]
                    all_nations_set.update(parts)

                # Statystyki
                s_data = stats_map.get(name, {})
                matches_real = s_data.get('Mecz_Label', 0)
                goals_real = s_data.get('Gole', 0)

                # Fallback
                if matches_real == 0:
                    matches_real = int(pd.to_numeric(row.get('mecze', 0), errors='coerce') or 0)
                if goals_real == 0:
                    goals_real = int(pd.to_numeric(row.get('gole', 0), errors='coerce') or 0)

                # Wiek
                age_val = None
                if pd.notna(row.get('data urodzenia')):
                    a, _ = get_age_and_birthday(row.get('data urodzenia'))
                    if a: age_val = int(a)

                # Grupowanie pozycji
                pos = str(row.get('pozycja', '-')).capitalize()
                pos_grp = "Inne"
                p_l = pos.lower()
                if 'bram' in p_l or 'gk' in p_l:
                    pos_grp = "Bramkarz"
                elif 'obr' in p_l or 'def' in p_l:
                    pos_grp = "Obrońca"
                elif 'pom' in p_l or 'mid' in p_l:
                    pos_grp = "Pomocnik"
                elif 'nap' in p_l or 'for' in p_l:
                    pos_grp = "Napastnik"

                display_data.append({
                    "Flaga": row.get('Flaga'),
                    "Zawodnik": name,
                    "Pozycja": pos,
                    "Grupa": pos_grp,
                    "Wiek": age_val,
                    "Mecze": matches_real,
                    "Gole": goals_real,
                    "Narodowość": nat_raw  # Przechowujemy oryginał
                })

            sorted_nations = sorted(list(all_nations_set))

        # Jeśli brak pliku pilkarze.csv
        elif df_w is not None:
            sorted_nations = []
            for name, data in stats_map.items():
                display_data.append({
                    "Flaga": None, "Zawodnik": name, "Pozycja": "-", "Grupa": "Inne",
                    "Wiek": None, "Mecze": data['Mecz_Label'], "Gole": data['Gole'], "Narodowość": "-"
                })

        # --- TWORZENIE DATAFRAME ---
        df_display = pd.DataFrame(display_data)

        if not df_display.empty:
            # --- SEKCJA 1: METRYKI ---
            total_pl = len(df_display)
            total_gl = df_display['Gole'].sum()
            avg_age = df_display['Wiek'].mean()
            top_scorer = df_display.sort_values('Gole', ascending=False).iloc[0]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Baza Zawodników", total_pl)
            m2.metric("Liczba Goli", total_gl)
            m3.metric("Średni Wiek", f"{avg_age:.1f}" if pd.notna(avg_age) else "-")
            m4.metric("Najlepszy Strzelec", f"{top_scorer['Zawodnik']} ({top_scorer['Gole']})")

            st.divider()

            # --- SEKCJA 2: FILTRY ---
            with st.expander("🛠️ Rozbudowane Filtry", expanded=True):
                c_fil1, c_fil2 = st.columns(2)

                with c_fil1:
                    search_q = st.text_input("Szukaj nazwiska:", placeholder="np. Demjan")
                    sel_pos = st.multiselect("Pozycja:", ["Bramkarz", "Obrońca", "Pomocnik", "Napastnik"])

                    min_a, max_a = int(df_display['Wiek'].min() or 15), int(df_display['Wiek'].max() or 45)
                    sel_age = st.slider("Wiek:", min_a, max_a, (min_a, max_a))

                with c_fil2:
                    # Nowe filtry nacji
                    sel_nations = st.multiselect("🌍 Narodowość:", sorted_nations)
                    only_foreigners = st.checkbox("🌍 Tylko obcokrajowcy")

            # Filtrowanie
            df_filtered = df_display.copy()

            if search_q:
                df_filtered = df_filtered[df_filtered['Zawodnik'].str.contains(search_q, case=False)]

            if sel_pos:
                df_filtered = df_filtered[df_filtered['Grupa'].isin(sel_pos)]

            if only_foreigners:
                # Wykluczamy Polskę (case insensitive)
                df_filtered = df_filtered[
                    ~df_filtered['Narodowość'].astype(str).str.contains('Polska', case=False, na=False)]

            if sel_nations:
                # Sprawdzamy czy którakolwiek z wybranych nacji występuje w stringu (np. dla "Polska / Niemcy")
                # Tworzymy regex: (Niemcy|Czechy|Słowacja)
                pattern = '|'.join(sel_nations)
                df_filtered = df_filtered[
                    df_filtered['Narodowość'].astype(str).str.contains(pattern, case=False, regex=True)]

            # Filtr wieku
            df_filtered = df_filtered[
                (df_filtered['Wiek'].isna()) |
                ((df_filtered['Wiek'] >= sel_age[0]) & (df_filtered['Wiek'] <= sel_age[1]))
                ]

            # Sortowanie
            df_filtered = df_filtered.sort_values('Mecze', ascending=False)

            # --- PODIUM (TOP 3) ---
            if len(df_filtered) >= 3:
                st.markdown("##### 🏆 Najwięcej meczów (wyniki wyszukiwania)")
                top3 = df_filtered.head(3).reset_index(drop=True)
                cp2, cp1, cp3 = st.columns([1, 1, 1])


                def card(col, row, emoji):
                    with col:
                        nat_txt = row['Narodowość'] if row['Narodowość'] != '-' else ''
                        st.markdown(f"""
                        <div style="text-align:center; border:1px solid #444; border-radius:10px; padding:10px; background-color:rgba(255,255,255,0.05);">
                            <h1 style="margin:0;">{emoji}</h1>
                            <div style="font-weight:bold; margin-top:5px;">{row['Zawodnik']}</div>
                            <small>{nat_txt}</small>
                            <div style="color:#28a745; font-weight:bold;">{row['Mecze']} meczów</div>
                        </div>
                        """, unsafe_allow_html=True)


                card(cp1, top3.iloc[0], "🥇")
                card(cp2, top3.iloc[1], "🥈")
                card(cp3, top3.iloc[2], "🥉")
                st.write("")

            # --- SEKCJA 3: TABELA ---
            st.subheader(f"Lista wyników ({len(df_filtered)})")

            event = st.dataframe(
                df_filtered[['Flaga', 'Zawodnik', 'Narodowość', 'Pozycja', 'Wiek', 'Mecze', 'Gole']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Flaga": st.column_config.ImageColumn("", width="small"),
                    "Narodowość": st.column_config.TextColumn("Kraj", width="medium"),
                    "Wiek": st.column_config.NumberColumn("Wiek", format="%d"),
                    "Mecze": st.column_config.ProgressColumn("Mecze", format="%d", min_value=0,
                                                             max_value=int(df_display['Mecze'].max())),
                    "Gole": st.column_config.NumberColumn("Gole", format="%d ⚽")
                },
                on_select="rerun",
                selection_mode="single-row",
                height=600
            )

            if event.selection.rows:
                idx = event.selection.rows[0]
                sel_player = df_filtered.iloc[idx]['Zawodnik']
                st.session_state['cm_selected_player'] = sel_player
                st.rerun()

        else:
            st.warning("Brak danych do wyświetlenia.")

elif opcja == "Centrum Meczowe":
    st.header("⚽ Centrum Meczowe")

    # --- 0. ROUTER PROFILU ---
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do raportu", key="back_from_player_cm"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # --- 1. GŁÓWNY WIDOK ---
    else:
        df_m = load_data("mecze.csv")
        df_det_sq = load_details("wystepy.csv")

        if 'filter_seasons' in globals():
            df_m = filter_seasons(df_m, 'sezon')
            df_det_sq = filter_seasons(df_det_sq, 'Sezon')

        # USUNIĘTO LOKALNĄ DEFINICJĘ render_match_report_logic
        # Dzięki temu kod użyje teraz tej samej, ładnej funkcji co w profilach piłkarzy.

        # --- ZAKŁADKI ---
        tab1, tab2, tab3 = st.tabs(["📝 Raporty Meczowe", "🆚 Analiza Rywala", "📊 Statystyki"])

        # --- TAB 1: RAPORTY ---
        with tab1:
            if df_det_sq is not None:
                c1, c2 = st.columns([1, 2])
                seasons = sorted(df_det_sq['Sezon'].unique(), reverse=True)
                idx_season = 0
                if 'cm_season_sel' in st.session_state and st.session_state['cm_season_sel'] in seasons:
                    idx_season = seasons.index(st.session_state['cm_season_sel'])
                sel_season = c1.selectbox("Wybierz Sezon:", seasons, index=idx_season, key="cm_season_sel_box")
                st.session_state['cm_season_sel'] = sel_season

                subset = df_det_sq[df_det_sq['Sezon'] == sel_season]
                unique_matches = subset.groupby('Mecz_Label').first().reset_index()
                if 'Data_Sort' in unique_matches.columns: unique_matches = unique_matches.sort_values('Data_Sort',
                                                                                                      ascending=False)


                def get_display_label(row):
                    icon = "🏠" if any(
                        x in str(row.get('Rola', '')).lower() for x in ['dom', 'gospodarz', 'u siebie']) else "🚌"
                    return f"{icon} {row['Mecz_Label']}"


                unique_matches['Display_Label'] = unique_matches.apply(get_display_label, axis=1)
                display_to_id = dict(zip(unique_matches['Display_Label'], unique_matches['Mecz_Label']))
                options_display = list(unique_matches['Display_Label'])

                sel_display = c2.selectbox("Wybierz Mecz:", options_display, key="cm_match_sel_box_tab1")
                sel_match_lbl = display_to_id.get(sel_display)

                if sel_match_lbl:
                    st.divider()
                    match_squad = subset[subset['Mecz_Label'] == sel_match_lbl].copy().sort_values('File_Order')
                    render_match_report_logic(sel_match_lbl, match_squad)
            else:
                st.error("Brak pliku wystepy.csv")

        # --- TAB 2: ANALIZA RYWALA ---
        with tab2:
            st.subheader("🆚 Analiza Rywala i Historia Spotkań")
            if df_m is not None:
                rivs = sorted(df_m['rywal'].dropna().astype(str).unique()) if 'rywal' in df_m.columns else []
                sel_r = st.selectbox("Wybierz rywala:", [""] + rivs)
                if sel_r:
                    if 'dt_obj' not in df_m.columns:
                        col_d = next((c for c in df_m.columns if c in ['data meczu', 'data']), None)
                        if col_d: df_m['dt_obj'] = pd.to_datetime(df_m[col_d], dayfirst=True, errors='coerce')

                    rival_matches = df_m[df_m['rywal'] == sel_r].copy()
                    if 'dt_obj' in rival_matches.columns: rival_matches = rival_matches.sort_values('dt_obj',
                                                                                                    ascending=False)

                    wins, draws, losses, gf, ga = 0, 0, 0, 0, 0
                    for _, row in rival_matches.iterrows():
                        res = parse_result(row.get('wynik'))
                        if res:
                            gf += res[0];
                            ga += res[1]
                            if res[0] > res[1]:
                                wins += 1
                            elif res[0] == res[1]:
                                draws += 1
                            else:
                                losses += 1
                    total = wins + draws + losses
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Mecze", total)
                    k2.metric("Zwycięstwa", wins)
                    k3.metric("Remisy / Porażki", f"{draws} / {losses}")
                    k4.metric("Bramki", f"{gf}:{ga}", delta=gf - ga)
                    st.divider()
                    st.markdown("#### 📜 Historia Spotkań")
                    rival_matches['Data'] = rival_matches['dt_obj'].dt.strftime('%d.%m.%Y')
                    rival_matches['Gdzie'] = rival_matches['dom'].apply(
                        lambda x: "🏠 Dom" if str(x).lower() in ['1', 'true', 'dom', 'tak'] else "🚌 Wyjazd")
                    event = st.dataframe(rival_matches[['Data', 'sezon', 'Gdzie', 'wynik']], use_container_width=True,
                                         hide_index=True, on_select="rerun", selection_mode="single-row",
                                         key="rival_analysis_table")
                    if event.selection.rows:
                        idx = event.selection.rows[0]
                        sel_date = rival_matches.iloc[idx]['dt_obj'].date()
                        st.markdown("---")
                        st.subheader(f"Raport z dnia {sel_date.strftime('%d.%m.%Y')}")
                        if df_det_sq is not None and 'Data_Sort' in df_det_sq.columns:
                            found = df_det_sq[df_det_sq['Data_Sort'].dt.date == sel_date]
                            if not found.empty:
                                render_match_report_logic(found.iloc[0]['Mecz_Label'], found.sort_values('File_Order'))
                            else:
                                st.warning("Brak szczegółów składu.")
            else:
                st.error("Brak pliku mecze.csv")

        # --- TAB 3: STATYSTYKI ---
        with tab3:
            st.subheader("📊 Centrum Analityczne")
            if df_m is not None:
                if 'dt_obj' not in df_m.columns:
                    col_d = next((c for c in df_m.columns if c in ['data', 'data meczu']), None)
                    if col_d: df_m['dt_obj'] = pd.to_datetime(df_m[col_d], dayfirst=True, errors='coerce')

                df_stats = df_m.sort_values('dt_obj').copy()

                # --- [1] BILANS OGÓLNY ---
                f_mode = st.radio("Filtruj bilans:", ["Wszystkie", "🏠 Tylko Dom", "🚌 Tylko Wyjazd"], horizontal=True)
                df_bilans = df_stats.copy()
                if "Dom" in f_mode:
                    df_bilans = df_bilans[df_bilans['dom'].astype(str).str.lower().isin(['1', 'true', 'dom', 'tak'])]
                elif "Wyjazd" in f_mode:
                    df_bilans = df_bilans[~df_bilans['dom'].astype(str).str.lower().isin(['1', 'true', 'dom', 'tak'])]

                w, d, l, gf, ga = 0, 0, 0, 0, 0
                seq = []  # Do serii
                for _, r in df_bilans.iterrows():
                    res = parse_result(r.get('wynik'))
                    if res:
                        gf += res[0];
                        ga += res[1]
                        if res[0] > res[1]:
                            w += 1; seq.append('W')
                        elif res[0] == res[1]:
                            d += 1; seq.append('D')
                        else:
                            l += 1; seq.append('L')
                    else:
                        seq.append(None)

                tot = w + d + l
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mecze", tot)
                c2.metric("Bilans", f"{w}-{d}-{l}")
                c3.metric("Bramki", f"{gf}:{ga}", delta=gf - ga)
                c4.metric("Skuteczność", f"{(w / tot * 100):.1f}%" if tot else "0%")
                st.divider()

                # --- [2] FREKWENCJA (UKRYWANA DLA WYJAZDÓW) ---
                if "Wyjazd" not in f_mode:
                    st.markdown("### 🏟️ Statystyki Frekwencji (Mecze Domowe)")
                    col_att = next(
                        (c for c in df_stats.columns if c.lower() in ['widzów', 'frekwencja', 'widzow', 'kibiców']),
                        None)

                    if col_att:
                        # Filtruj domowe
                        home_keywords = ['1', '1.0', 'true', 'tak', 'dom', 'gospodarz', 'u siebie']
                        df_stats['is_home'] = df_stats['dom'].astype(str).str.lower().str.strip().apply(
                            lambda x: x in home_keywords)
                        df_home = df_stats[df_stats['is_home']].copy()

                        if not df_home.empty:
                            df_home['Widzów_Num'] = pd.to_numeric(
                                df_home[col_att].astype(str).str.replace(r'\D', '', regex=True),
                                errors='coerce').fillna(0).astype(int)
                            df_home = df_home[df_home['Widzów_Num'] > 0]

                            if not df_home.empty:
                                avg_total = df_home['Widzów_Num'].mean()
                                max_total = df_home.loc[df_home['Widzów_Num'].idxmax()]

                                fm1, fm2 = st.columns(2)
                                fm1.metric("Średnia Frekwencja (Sezon)", f"{int(avg_total):,}".replace(",", " "))
                                fm2.metric("Rekord Frekwencji", f"{int(max_total['Widzów_Num']):,}".replace(",", " "),
                                           f"{max_total.get('rywal', '')} ({max_total['dt_obj'].strftime('%d.%m')})")
                                st.write("")

                                df_home['Miesiąc_Idx'] = df_home['dt_obj'].dt.month
                                pl_months = {1: 'Styczeń', 2: 'Luty', 3: 'Marzec', 4: 'Kwiecień', 5: 'Maj',
                                             6: 'Czerwiec',
                                             7: 'Lipiec', 8: 'Sierpień', 9: 'Wrzesień', 10: 'Październik',
                                             11: 'Listopad', 12: 'Grudzień'}

                                freq_stats = []
                                for m_idx in sorted(df_home['Miesiąc_Idx'].unique()):
                                    sub = df_home[df_home['Miesiąc_Idx'] == m_idx]
                                    top3 = sub.nlargest(3, 'Widzów_Num')
                                    # [DODANE] Medale w TOP 3
                                    emojis = ['🥇', '🥈', '🥉']
                                    top3_txt = []
                                    for i, (idx, r) in enumerate(top3.iterrows()):
                                        ico = emojis[i] if i < 3 else ""
                                        top3_txt.append(f"{ico} **{r['Widzów_Num']}** ({r.get('rywal', '?')})")

                                    freq_stats.append({
                                        "Miesiąc": pl_months.get(m_idx, str(m_idx)),
                                        "Mecze": len(sub),
                                        "Średnia": sub['Widzów_Num'].mean(),
                                        "TOP 3 Frekwencji": ", ".join(top3_txt)
                                    })

                                df_freq = pd.DataFrame(freq_stats)
                                st.bar_chart(df_freq.set_index("Miesiąc")['Średnia'], color="#28a745")
                                st.dataframe(
                                    df_freq, use_container_width=True, hide_index=True,
                                    column_config={
                                        "Średnia": st.column_config.NumberColumn("Średnia", format="%.0f"),
                                        "Mecze": st.column_config.NumberColumn("Mecze", format="%d"),
                                        "TOP 3 Frekwencji": st.column_config.TextColumn("Najwyższe wyniki",
                                                                                        width="large")
                                    }
                                )
                            else:
                                st.info("Znaleziono mecze domowe, ale brak danych liczbowych o widzach.")
                        else:
                            st.info("Nie znaleziono meczów domowych.")
                    else:
                        st.warning("Nie znaleziono kolumny 'Widzów' w pliku.")
                    st.divider()

                # --- [3] SERIE (PRZYWRÓCONE I ROZBUDOWANE) ---
                st.markdown("### 🔥 Serie i Passy")


                def get_streak_with_breaker(df_source, sequence, target_types):
                    max_streak = []
                    current_streak = []
                    # Reset indeksu, żeby łatwiej znaleźć następny mecz
                    temp_df = df_source.reset_index(drop=True)
                    breaker_match = None
                    final_breaker = None

                    for i, code in enumerate(sequence):
                        if code in target_types:
                            current_streak.append(temp_df.iloc[i])
                        else:
                            if len(current_streak) > len(max_streak):
                                max_streak = current_streak
                                # Ten mecz przerwał serię (jest pod indeksem i)
                                if i < len(temp_df):
                                    final_breaker = temp_df.iloc[i]
                            current_streak = []

                    if len(current_streak) > len(max_streak):
                        max_streak = current_streak
                        final_breaker = None

                    return (pd.DataFrame(max_streak) if max_streak else pd.DataFrame(), final_breaker)


                # Obliczanie serii
                s_win, b_win = get_streak_with_breaker(df_bilans, seq, ['W'])
                s_no_loss, b_no_loss = get_streak_with_breaker(df_bilans, seq, ['W', 'D'])
                s_loss, b_loss = get_streak_with_breaker(df_bilans, seq, ['L'])
                s_no_win, b_no_win = get_streak_with_breaker(df_bilans, seq, ['L', 'D'])

                # Metryki
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Seria Zwycięstw", len(s_win))
                k2.metric("Bez Porażki", len(s_no_loss))
                k3.metric("Seria Porażek", len(s_loss))
                k4.metric("Bez Zwycięstwa", len(s_no_win))

                with st.expander("🔎 Pokaż szczegóły serii"):
                    ts1, ts2, ts3, ts4 = st.tabs(["Zwycięstwa", "Bez Porażki", "Porażki", "Bez Zwycięstwa"])


                    def show_streak_table(d, breaker, is_negative_streak=False):
                        if not d.empty:
                            d['Gdzie'] = d['dom'].apply(
                                lambda x: "🏠" if str(x).lower() in ['1', 'true', 'dom', 'tak'] else "🚌")
                            d['Data'] = d['dt_obj'].dt.strftime('%d.%m.%Y')
                            st.dataframe(d[['Data', 'rywal', 'wynik', 'Gdzie']], hide_index=True,
                                         use_container_width=True)

                            # Informacja o przerwaniu serii
                            if breaker is not None:
                                b_res = str(breaker.get('wynik', ''))
                                b_opp = str(breaker.get('rywal', ''))
                                b_date = breaker['dt_obj'].strftime('%d.%m.%Y')

                                # LOGIKA KOLORÓW:
                                # Jeśli seria była negatywna (np. Porażki), to jej przerwanie jest DOBRE (Zielony ptaszek)
                                # Jeśli seria była pozytywna (np. Zwycięstwa), to jej przerwanie jest ZŁE (Czerwony X)
                                if is_negative_streak:
                                    st.success(f"✅ Seria przełamana: {b_date} vs **{b_opp}** ({b_res})")
                                else:
                                    st.error(f"❌ Seria przerwana: {b_date} vs **{b_opp}** ({b_res})")
                            else:
                                if is_negative_streak:
                                    st.error("⚠️ Seria trwa do końca analizowanego okresu.")
                                else:
                                    st.success("🔥 Seria trwa do końca analizowanego okresu.")
                        else:
                            st.info("Brak serii.")


                    with ts1:
                        show_streak_table(s_win, b_win, is_negative_streak=False)
                    with ts2:
                        show_streak_table(s_no_loss, b_no_loss, is_negative_streak=False)
                    with ts3:
                        show_streak_table(s_loss, b_loss, is_negative_streak=True)
                    with ts4:
                        show_streak_table(s_no_win, b_no_win, is_negative_streak=True)

            else:
                st.error("Brak pliku mecze.csv")

elif opcja == "🏆 Rekordy & TOP":
    st.header("🏆 Sala Chwały i Rekordy TSP")

    # [0] ROUTER
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do Rekordów", key="back_from_player_rec"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # [1] GŁÓWNY WIDOK
    else:
        df_p = load_data("pilkarze.csv")
        df_w = load_details("wystepy.csv")
        df_m = load_data("mecze.csv")

        if df_p is None or df_w is None:
            st.error("Brak plików danych (pilkarze.csv / wystepy.csv).")
        else:
            if 'filter_seasons' in globals():
                df_w = filter_seasons(df_w, 'Sezon') if 'Sezon' in df_w.columns else df_w
                if df_m is not None: df_m = filter_seasons(df_m, 'sezon')

            # --- A. PRZYGOTOWANIE DANYCH ---
            for col, new_col in [('Gole', 'Gole_Num'), ('Minuty', 'Min_Num'), ('Czerwone', 'R_Num'),
                                 ('Żółte', 'Y_Num')]:
                df_w[new_col] = pd.to_numeric(df_w[col], errors='coerce').fillna(0).astype(int)

            df_w['join_key'] = df_w['Zawodnik_Clean'].astype(str).str.lower().str.strip()

            # Normalizacja pilkarze.csv
            col_map = {
                'kraj': 'Narodowość', 'Kraj': 'Narodowość', 
                'narodowość': 'Narodowość', 'narodowosc': 'Narodowość',
                'Pozycja': 'pozycja', 'imię i nazwisko': 'nazwisko'
            }
            df_p.rename(columns={k: v for k, v in col_map.items() if k in df_p.columns}, inplace=True)
            if 'nazwisko' in df_p.columns: df_p.rename(columns={'nazwisko': 'imię i nazwisko'}, inplace=True)

            # Zabezpieczenie braku kolumn
            if 'Narodowość' not in df_p.columns: df_p['Narodowość'] = '-'
            if 'pozycja' not in df_p.columns: df_p['pozycja'] = '-'

            df_p['join_key'] = df_p['imię i nazwisko'].astype(str).str.lower().str.strip()

            # Sortujemy tak, żeby mieć najlepsze dane na górze (jeśli są duplikaty)
            df_p['has_nation'] = df_p['Narodowość'].apply(
                lambda x: 0 if str(x).lower() in ['-', 'nan', '', 'none', 'null'] else 1)
            df_p = df_p.sort_values('has_nation', ascending=False)
            df_p_dates = df_p.drop_duplicates(subset=['join_key']).copy()

            # --- B. STATYSTYKI BRAMKARZY ---
            gks = df_p_dates[df_p_dates['pozycja'].astype(str).str.lower().str.contains('bramkarz|gk', na=False)][
                'join_key'].unique()
            gk_stats = []
            if len(gks) > 0:
                df_gk_w = df_w[df_w['join_key'].isin(gks)].copy()
                for player_key, group in df_gk_w.groupby('join_key'):
                    real_name = group.iloc[0]['Zawodnik_Clean']
                    matches, clean_sheets, conceded_total = 0, 0, 0
                    for _, r in group.iterrows():
                        try:
                            mins = r['Min_Num']
                            if mins > 0:
                                matches += 1
                                res = str(r.get('Wynik', ''))
                                parts = re.split(r'[:\-]', res)
                                if len(parts) >= 2:
                                    g1, g2 = int(parts[0]), int(parts[1])
                                    role = str(r.get('Rola', '')).lower()
                                    conc = g2 if ('gospodarz' in role or 'dom' in role) else g1
                                    conceded_total += conc
                                    if mins >= 45 and conc == 0: clean_sheets += 1
                        except:
                            continue
                    if matches > 0:
                        gk_stats.append({'Zawodnik_Clean': real_name, 'join_key': player_key, 'Mecze': matches,
                                         'Czyste Konta': clean_sheets, 'Wpuszczone': conceded_total,
                                         'Średnia': conceded_total / matches})


            # --- C. LATA GRY ---
            def format_tenure_smart(seasons_series):
                years = sorted(list(set([int(str(s).split('/')[0]) for s in seasons_series if '/' in str(s)])))
                if not years: return "-"
                ranges = []
                start = prev = years[0]
                for y in years[1:]:
                    if y == prev + 1:
                        prev = y
                    else:
                        ranges.append(f"{start}-{prev + 1}" if start != prev else f"{start}")
                        start = prev = y
                ranges.append(f"{start}-{prev + 1}" if start != prev else f"{start}")
                return ", ".join(ranges)


            tenure_map = df_w[['join_key', 'Sezon']].drop_duplicates().groupby('join_key')['Sezon'].apply(
                format_tenure_smart).to_dict()
            df_p_dates['Lata gry'] = df_p_dates['join_key'].map(tenure_map).fillna("-")

            # --- D. AGREGACJA ---
            agg = df_w.groupby('join_key').agg({
                'Sezon': 'nunique', 'Gole_Num': 'sum', 'R_Num': 'sum', 'Y_Num': 'sum', 'Min_Num': 'sum',
                'Zawodnik_Clean': 'first'
            }).reset_index()
            agg.rename(columns={'Sezon': 'Sezony_Liczba'}, inplace=True)
            m_counts = df_w.groupby('join_key').size().reset_index(name='Mecze_Liczba')
            agg = pd.merge(agg, m_counts, on='join_key')

            # Łączenie z profilem (Left Join)
            # 1. Najpierw przygotujemy kolumnę z manualną liczbą meczów w df_p_dates
            def get_manual_matches(row):
                for c in ['suma', 'mecze', 'liczba']:
                    if c in row.index:
                        try:
                            val = int(row[c])
                            if val > 0: return val
                        except:
                            pass
                return 0

            df_p_dates['Manual_Matches'] = df_p_dates.apply(get_manual_matches, axis=1)

            # [ZMIANA] Używamy OUTER JOIN, aby nie gubić piłkarzy, którzy są tylko w pilkarze.csv (np. przez błędy w nazwisku)
            full_agg = pd.merge(agg, df_p_dates[['join_key', 'Narodowość', 'pozycja', 'Lata gry', 'Manual_Matches']],
                                on='join_key', how='outer')

            # Wypełniamy braki zerami, żeby max() działał poprawnie
            full_agg['Mecze_Liczba'] = full_agg['Mecze_Liczba'].fillna(0)
            full_agg['Manual_Matches'] = full_agg['Manual_Matches'].fillna(0)
            
            # 2. Obliczamy ostateczną liczbę meczów (MAX z wyliczonych i manualnych)
            full_agg['Total_Matches'] = full_agg[['Mecze_Liczba', 'Manual_Matches']].max(axis=1).astype(int)

            # --- E. LISTY ODZNAK (POPRAWIONE) ---

            # Klub 100
            list_club100 = full_agg[full_agg['Total_Matches'] >= 100]['Zawodnik_Clean'].tolist()

            # Weteran
            list_veteran = full_agg[full_agg['Sezony_Liczba'] >= 5]['Zawodnik_Clean'].tolist()

            # Żelazne Płuca
            list_lungs = full_agg[full_agg['Min_Num'] > 5000]['Zawodnik_Clean'].tolist()

            # Bad Boy
            list_badboy = full_agg[full_agg['R_Num'] >= 2]['Zawodnik_Clean'].tolist()

            # [POPRAWKA] Dżentelmen: Min. 30 meczów, 0 czerwonych ORAZ mniej niż 5 żółtych
            list_gentleman = full_agg[
                (full_agg['Total_Matches'] >= 30) &
                (full_agg['R_Num'] == 0) &
                (full_agg['Y_Num'] < 5)
                ]['Zawodnik_Clean'].tolist()

            # Zagraniczny Filar
            full_agg['Narodowość_Str'] = full_agg['Narodowość'].fillna('').astype(str).str.lower().str.strip()
            mask_foreign = (
                    (full_agg['Total_Matches'] >= 50) &
                    (full_agg['Narodowość_Str'] != '') &
                    (full_agg['Narodowość_Str'] != '-') &
                    (full_agg['Narodowość_Str'] != 'nan') &
                    (~full_agg['Narodowość_Str'].str.contains('pol'))
            )
            list_foreign = full_agg[mask_foreign]['Zawodnik_Clean'].tolist()

            # Awans
            promo_years = ['2010/2011', '2010/11', '2019/2020', '2019/20']
            list_promo = df_w[df_w['Sezon'].isin(promo_years)]['Zawodnik_Clean'].unique().tolist()

            # Hat-trick
            list_hattrick = df_w[df_w['Gole_Num'] >= 3]['Zawodnik_Clean'].unique().tolist()

            # [POPRAWKA] Super Joker: Obliczamy sumę goli strzelonych TYLKO jako rezerwowy
            # Filtrujemy wejścia z ławki
            subs_only = df_w[df_w['Status'] == 'Wszedł'].copy()
            # Grupujemy po nazwisku i sumujemy gole
            joker_stats = subs_only.groupby('Zawodnik_Clean')['Gole_Num'].sum()
            # Wybieramy tych, którzy mają 3 lub więcej goli z ławki
            list_joker = joker_stats[joker_stats >= 5].index.tolist()

            # Zadaniowiec
            sub_c = df_w[df_w['Status'] == 'Wszedł'].groupby('join_key').size()
            list_taskmaster = df_w[df_w['join_key'].isin(sub_c[sub_c >= 20].index)]['Zawodnik_Clean'].unique().tolist()

            # Bramkarze
            list_wall = [x['Zawodnik_Clean'] for x in gk_stats if x['Czyste Konta'] >= 20]
            list_sure = [x['Zawodnik_Clean'] for x in gk_stats if x['Czyste Konta'] >= 10]

            # --- F. WIDOK ---
            tab_badges, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                "🏅 Odznaki", "👤 Występy", "👶👴 Wiek", "⚽ Strzelcy", "🏟️ Wyniki", "🟥🟨 Kartki", "🧤 Bramkarze"
            ])


            def show_badge_group(title, player_list, badge_icon, description):
                count = len(player_list)
                with st.expander(f"{badge_icon} {title} ({count})", expanded=False):
                    st.info(f"💡 **Znaczenie:** {description}")
                    if player_list:
                        p_df = pd.DataFrame({'Zawodnik': sorted(list(set(player_list)))})
                        p_df['join_key'] = p_df['Zawodnik'].astype(str).str.lower().str.strip()
                        p_df = pd.merge(p_df, df_p_dates[['join_key', 'Lata gry']], on='join_key', how='left')
                        st.dataframe(p_df[['Zawodnik', 'Lata gry']], hide_index=True, use_container_width=True)
                    else:
                        st.caption("Brak zawodników.")


            with tab_badges:
                st.subheader("🏅 Sala Chwały - Odznaki Specjalne")
                c1, c2, c3 = st.columns(3)
                with c1:
                    show_badge_group("Klub 100", list_club100, "💯", "Min. 100 oficjalnych meczów.")
                    show_badge_group("Weteran", list_veteran, "🦅", "Min. 5 różnych sezonów w klubie.")
                    show_badge_group("Awans", list_promo, "🚀", "Członkowie drużyn awansujących (2011, 2020).")
                    show_badge_group("Zagraniczny Filar", list_foreign, "🌍",
                                     "Obcokrajowcy z min. 50 meczami (bez polskiego paszportu).")
                with c2:
                    show_badge_group("Wielki Mur", list_wall, "🧱", "Bramkarze: 20+ czystych kont.")
                    show_badge_group("Pewny Punkt", list_sure, "🧤", "Bramkarze: 10+ czystych kont.")
                    show_badge_group("Hat-trick Hero", list_hattrick, "🎩", "Strzelcy 3 goli w jednym meczu.")
                    show_badge_group("Super Joker", list_joker, "🃏", "Rezerwowi z min. 5 golami po wejściu.")
                with c3:
                    show_badge_group("Dżentelmen", list_gentleman, "⚖️", "Min. 50 meczów bez czerwonej kartki.")
                    show_badge_group("Bad Boy", list_badboy, "🟥", "Min. 2 czerwone kartki.")
                    show_badge_group("Żelazne Płuca", list_lungs, "🚂", "Ponad 5000 minut na boisku.")
                    show_badge_group("Zadaniowiec", list_taskmaster, "🔄", "Min. 20 wejść z ławki.")


            def get_medals(df_in):
                df_x = df_in.copy().reset_index(drop=True)
                df_x.index += 1
                df_x.insert(0, 'Miejsce', df_x.index.map(
                    lambda x: f"🥇" if x == 1 else (f"🥈" if x == 2 else (f"🥉" if x == 3 else f"{x}."))))
                return df_x


            # --- POZOSTAŁE ZAKŁADKI (BEZ ZMIAN) ---
            with tab1:
                st.subheader("👕 Najwięcej Występów")
                top_m = full_agg.sort_values('Mecze_Liczba', ascending=False).head(20)
                st.dataframe(get_medals(top_m)[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Mecze_Liczba']],
                             hide_index=True, use_container_width=True,
                             column_config={"Mecze_Liczba": st.column_config.ProgressColumn("Mecze", format="%d")})

            with tab2:
                df_age = df_w.copy()
                df_age['Data_Sort'] = pd.to_datetime(df_age['Data_Sort'])
                df_age = pd.merge(df_age, df_p_dates[['join_key', 'data urodzenia', 'pozycja']], on='join_key',
                                  how='inner')
                df_age['dt_ur'] = pd.to_datetime(df_age['data urodzenia'], errors='coerce')
                df_age['Age_Days'] = (df_age['Data_Sort'] - df_age['dt_ur']).dt.days
                df_age_valid = df_age.dropna(subset=['Age_Days']).copy()
                if not df_age_valid.empty:
                    df_age_valid['Wiek_Txt'] = df_age_valid['Age_Days'].apply(
                        lambda d: f"{int(d // 365.25)} lat, {int(d % 365.25)} dni")
                    c_y, c_o = st.columns(2)
                    with c_y:
                        st.markdown("#### 👶 Najmłodsi Debiutanci")
                        young = df_age_valid.loc[df_age_valid.groupby('join_key')['Age_Days'].idxmin()]
                        young = get_medals(young[young['Age_Days'] > 3650].sort_values('Age_Days').head(10))
                        st.dataframe(young[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Wiek_Txt', 'Data_Sort']],
                                     hide_index=True, use_container_width=True,
                                     column_config={"Data_Sort": st.column_config.DateColumn("Data")})
                    with c_o:
                        st.markdown("#### 👴 Najstarsi")
                        old = df_age_valid.loc[df_age_valid.groupby('join_key')['Age_Days'].idxmax()]
                        old = get_medals(old[old['Age_Days'] < 22000].sort_values('Age_Days', ascending=False).head(10))
                        st.dataframe(old[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Wiek_Txt', 'Data_Sort']],
                                     hide_index=True, use_container_width=True,
                                     column_config={"Data_Sort": st.column_config.DateColumn("Data")})

            with tab3:
                st.subheader("⚽ Królowie Strzelców")
                top_g = full_agg[full_agg['Gole_Num'] > 0].sort_values('Gole_Num', ascending=False).head(20)
                st.dataframe(get_medals(top_g)[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Gole_Num']],
                             hide_index=True, use_container_width=True,
                             column_config={"Gole_Num": st.column_config.NumberColumn("Gole", format="%d ⚽")})

            with tab4:
                c_hat, c_res = st.columns(2)
                with c_hat:
                    st.markdown("#### 🎩 Hat-tricki")
                    hats = df_w[df_w['Gole_Num'] >= 3].sort_values('Data_Sort', ascending=False)
                    if not hats.empty:
                        hats = pd.merge(hats, df_p_dates[['join_key', 'pozycja']], on='join_key', how='left')
                        st.dataframe(
                            hats[['Sezon', 'Data_Sort', 'pozycja', 'Zawodnik_Clean', 'Gole_Num', 'Przeciwnik']],
                            hide_index=True, use_container_width=True,
                            column_config={"Data_Sort": st.column_config.DateColumn("Data")})
                    else:
                        st.info("Brak hat-tricków.")
                with c_res:
                    st.markdown("#### 🚀 Najwyższe Zwycięstwa")
                    if df_m is not None:
                        def get_diff(x):
                            try:
                                p = x.split(':') if ':' in x else (x.split('-') if '-' in x else [])
                                return int(p[0]) - int(p[1]) if len(p) == 2 else -99
                            except:
                                return -99


                        df_m['Diff'] = df_m['wynik'].apply(get_diff)
                        st.dataframe(get_medals(df_m[df_m['Diff'] > 0].sort_values('Diff', ascending=False).head(10))[
                                         ['Miejsce', 'sezon', 'rywal', 'wynik']], hide_index=True,
                                     use_container_width=True)

            with tab5:
                col_y, col_r = st.columns(2)
                with col_y:
                    st.markdown("#### 🟨 Najwięcej Żółtych")
                    top_y = full_agg[full_agg['Y_Num'] > 0].sort_values('Y_Num', ascending=False).head(15)
                    st.dataframe(get_medals(top_y)[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Y_Num']],
                                 hide_index=True, use_container_width=True, column_config={
                            "Y_Num": st.column_config.ProgressColumn("Żółte", format="%d",
                                                                     max_value=int(top_y['Y_Num'].max()))})
                with col_r:
                    st.markdown("#### 🟥 Najwięcej Czerwonych")
                    top_r = full_agg[full_agg['R_Num'] > 0].sort_values('R_Num', ascending=False).head(15)
                    st.dataframe(get_medals(top_r)[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'R_Num']],
                                 hide_index=True, use_container_width=True)

            with tab6:
                st.subheader("🧤 Statystyki Bramkarskie")
                if gk_stats:
                    df_gk_stats = pd.DataFrame(gk_stats)
                    df_gk_stats = pd.merge(df_gk_stats, df_p_dates[['join_key', 'pozycja', 'Lata gry']], on='join_key',
                                           how='left')
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("#### 🧱 Najwięcej Czystych Kont")
                        top_cs = get_medals(
                            df_gk_stats.sort_values(['Czyste Konta', 'Mecze'], ascending=[False, True]).head(10))
                        st.dataframe(top_cs[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Czyste Konta']],
                                     hide_index=True, use_container_width=True, column_config={
                                "Czyste Konta": st.column_config.ProgressColumn("CS", format="%d", max_value=int(
                                    df_gk_stats['Czyste Konta'].max()))})
                    with c2:
                        st.markdown("#### 🛡️ Najmniej wpuszczonych/mecz (min. 10)")
                        best_avg = df_gk_stats[df_gk_stats['Mecze'] >= 10].sort_values('Średnia').head(10)
                        st.dataframe(
                            get_medals(best_avg)[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Średnia']],
                            hide_index=True, use_container_width=True,
                            column_config={"Średnia": st.column_config.NumberColumn("Śr.", format="%.2f")})

                    st.divider()
                    st.markdown("### ⚠️ Negatywne Rekordy")
                    c3, c4 = st.columns(2)
                    with c3:
                        st.markdown("#### ⚽ Najwięcej wpuszczonych goli")
                        top_conceded = get_medals(df_gk_stats.sort_values('Wpuszczone', ascending=False).head(10))
                        st.dataframe(
                            top_conceded[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Wpuszczone', 'Mecze']],
                            hide_index=True, use_container_width=True,
                            column_config={"Wpuszczone": st.column_config.NumberColumn("Wpuszczone", format="%d ⚽")})
                    with c4:
                        st.markdown("#### 📈 Najwyższa średnia wpuszczonych (min. 10 spotkań)")
                        df_avg_worst = df_gk_stats[df_gk_stats['Mecze'] >= 10].sort_values('Średnia',
                                                                                           ascending=False).head(10)
                        df_avg_worst = get_medals(df_avg_worst)
                        st.dataframe(
                            df_avg_worst[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Średnia', 'Mecze']],
                            hide_index=True, use_container_width=True,
                            column_config={"Średnia": st.column_config.NumberColumn("Śr. goli", format="%.2f")})
# =========================================================
# MODUŁ: TRENERZY (ODDZIELNA SEKCJA)
# =========================================================
elif opcja == "Trenerzy":
    if 'coach_view_mode' not in st.session_state:
        st.session_state['coach_view_mode'] = 'list'
    if 'selected_coach' not in st.session_state:
        st.session_state['selected_coach'] = None

    if st.session_state['coach_view_mode'] == 'profile':
        if st.button("⬅️ Wróć do listy trenerów"):
            st.session_state['coach_view_mode'] = 'list'
            st.session_state['selected_coach'] = None
            st.rerun()

        st.divider()
        render_coach_profile(st.session_state['selected_coach'])

    else:
        st.header("👔 Centrum Trenerów TSP")
        df = load_data("trenerzy.csv")

        if df is not None:
            def parse_date_safe(val):
                s = str(val).strip().lower()
                if s in ['-', 'nan', '', 'obecnie']: return pd.NaT
                try:
                    return pd.to_datetime(s, dayfirst=True)
                except:
                    return pd.NaT


            if 'początek' in df.columns:
                df['początek_dt'] = df['początek'].apply(parse_date_safe)
            else:
                df['początek_dt'] = pd.NaT

            if 'koniec' in df.columns:
                df['koniec_dt'] = df['koniec'].apply(parse_date_safe)
            else:
                df['koniec_dt'] = pd.NaT

            for col in ['mecze', 'punkty']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            df = prepare_flags(df)

            col_search, col_space = st.columns([1, 2])
            with col_search:
                all_coaches = sorted(df['imię i nazwisko'].astype(str).unique())
                selected_from_list = st.selectbox("🔍 Znajdź profil trenera:", [""] + all_coaches)
                if selected_from_list:
                    st.session_state['selected_coach'] = selected_from_list
                    st.session_state['coach_view_mode'] = 'profile'
                    st.rerun()

            st.divider()
            t1, t2, t3 = st.tabs(["📜 Lista Trenerów", "🏆 Rankingi Wszechczasów", "⚔️ Porównywarka"])

            with t1:
                st.subheader("Historia Zatrudnienia")
                df_view = df.sort_values('początek_dt', ascending=False)
                cols_possible = ['funkcja', 'imię i nazwisko', 'Narodowość', 'Flaga', 'początek', 'koniec',
                                 'mecze', 'punkty']
                cols_final = [c for c in cols_possible if c in df_view.columns]

                st.dataframe(df_view[cols_final], use_container_width=True, hide_index=True,
                             column_config={"Flaga": st.column_config.ImageColumn("Flaga", width="small"),
                                            "mecze": st.column_config.NumberColumn("Mecze", format="%d"),
                                            "punkty": st.column_config.NumberColumn("Punkty", format="%.0f")})

            with t2:
                st.subheader("📊 Tabela Wszechczasów")
                if 'punkty' in df.columns and 'mecze' in df.columns:
                    agg = df.groupby(['imię i nazwisko', 'Narodowość', 'Flaga'], as_index=False)[
                        ['mecze', 'punkty']].sum()
                    agg['Śr. Pkt'] = (agg['punkty'] / agg['mecze']).fillna(0)

                    sort_mode = st.radio("Sortuj według:", ["Punkty (Suma)", "Mecze (Liczba)",
                                                            "Średnia Punktów (min. 5 spotkań)"],
                                         horizontal=True)

                    if "Średnia" in sort_mode:
                        agg_sorted = agg[agg['mecze'] >= 5].sort_values('Śr. Pkt', ascending=False)
                        st.caption("⚠️ *Ranking średniej uwzględnia tylko trenerów z min. 5 meczami.*")
                    elif "Mecze" in sort_mode:
                        agg_sorted = agg.sort_values('mecze', ascending=False)
                    else:
                        agg_sorted = agg.sort_values('punkty', ascending=False)

                    st.dataframe(agg_sorted, use_container_width=True, hide_index=True,
                                 column_config={"Flaga": st.column_config.ImageColumn("Flaga", width="small"),
                                                "Śr. Pkt": st.column_config.ProgressColumn("Średnia",
                                                                                           format="%.2f",
                                                                                           min_value=0,
                                                                                           max_value=3),
                                                "mecze": st.column_config.NumberColumn("Mecze 🏟️"),
                                                "punkty": st.column_config.NumberColumn("Pkt 📈")})
                else:
                    st.warning("Brak kolumn 'mecze' lub 'punkty' w pliku trenerzy.csv")

            with t3:
                st.markdown("### 🆚 Porównaj bilans trenerów")
                sel_compare = st.multiselect("Wybierz trenerów (max 3):", all_coaches,
                                             default=all_coaches[:2] if len(all_coaches) > 1 else None)

                if sel_compare:
                    comp_data = []
                    mecze_df = load_data("mecze.csv")
                    if mecze_df is not None:
                        col_m_date = next((c for c in mecze_df.columns if 'data' in c and 'sort' not in c), None)
                        if col_m_date:
                            mecze_df['dt_temp'] = pd.to_datetime(mecze_df[col_m_date], dayfirst=True, errors='coerce')
                            for coach in sel_compare:
                                coach_rows = df[df['imię i nazwisko'] == coach]
                                mask = pd.Series([False] * len(mecze_df))
                                for _, c_row in coach_rows.iterrows():
                                    start = c_row['początek_dt']
                                    end = c_row['koniec_dt']
                                    if pd.isna(start): continue
                                    if pd.isna(end): end = pd.Timestamp.now() + pd.Timedelta(days=365)
                                    mask |= (mecze_df['dt_temp'] >= start) & (mecze_df['dt_temp'] <= end)

                                cm = mecze_df[mask]
                                w, d, l, gf, ga, pts_sum = 0, 0, 0, 0, 0, 0
                                if not cm.empty:
                                    for _, row_match in cm.iterrows():
                                        res = parse_result(row_match.get('wynik'))
                                        if res:
                                            gf += res[0];
                                            ga += res[1]
                                            if res[0] > res[1]:
                                                w += 1; pts_sum += 3
                                            elif res[0] == res[1]:
                                                d += 1; pts_sum += 1
                                            else:
                                                l += 1

                                total_m = w + d + l
                                avg_pts = pts_sum / total_m if total_m > 0 else 0
                                win_pct = (w / total_m * 100) if total_m > 0 else 0
                                comp_data.append(
                                    {"Trener": coach, "Mecze": total_m, "Zwycięstwa": w, "Remisy": d,
                                     "Porażki": l, "Bramki": f"{gf}:{ga}", "Średnia Pkt": avg_pts,
                                     "% Zwycięstw": win_pct})

                            if comp_data:
                                res_df = pd.DataFrame(comp_data).set_index("Trener")
                                # --- TU BYŁ BŁĄD, ZMIENIONO NA COLUMN CONFIG ---
                                st.dataframe(
                                    res_df,
                                    use_container_width=True,
                                    column_config={
                                        "Średnia Pkt": st.column_config.ProgressColumn(
                                            "Średnia Pkt", format="%.2f", min_value=0, max_value=3
                                        ),
                                        "% Zwycięstw": st.column_config.ProgressColumn(
                                            "% Zwycięstw", format="%.1f%%", min_value=0, max_value=100
                                        )
                                    }
                                )

                                if HAS_PLOTLY:
                                    fig = go.Figure()
                                    fig.add_trace(go.Bar(x=res_df.index, y=res_df['Średnia Pkt'], name='Średnia Pkt',
                                                         marker_color='#2ecc71'))
                                    fig.add_trace(
                                        go.Bar(x=res_df.index, y=res_df['% Zwycięstw'] / 33, name='Index Wygranych',
                                               marker_color='#3498db', opacity=0.5))
                                    fig.update_layout(title="Porównanie efektywności", barmode='group')
                                    st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.warning("Nie znaleziono meczów.")
                        else:

                            st.error("Brak kolumny z datą w mecze.csv")

# Dodaj do listy opcji w sidebarze (na górze pliku):
# menu_options = [..., "Strefa Kibica"]

# ... (Na dole pliku, nowy blok elif) ...

# Dodaj do listy opcji w sidebarze (na górze pliku):
# menu_options = [..., "Strefa Kibica"]

# ... (Na dole pliku, nowy blok elif) ...

elif opcja == "Strefa Kibica":
    st.header(f"👋 Witaj w Strefie Kibica, {st.session_state['username']}!")

    strefa_tabs = st.tabs(["Mój Profil", "⚽ Moja Jedenastka", "🧠 Quiz Wiedzy"])

    # --- TAB 1: MÓJ PROFIL ---
    with strefa_tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Moje Statystyki")
            my_att = run_query("SELECT count(*) FROM attendance WHERE username=?", (st.session_state['username'],),
                               fetch=True)
            st.metric("Zaliczonych meczów", my_att[0][0] if my_att else 0)

            st.markdown("#### ❤️ Ulubieni Piłkarze")
            favs = run_query("SELECT player_name FROM favorites WHERE username=?", (st.session_state['username'],),
                             fetch=True)
            if favs:
                for f in favs:
                    if st.button(f"👤 {f[0]}", key=f"my_fav_{f[0]}"):
                        st.session_state['cm_selected_player'] = f[0]
                        st.rerun()
            else:
                st.info("Nie dodałeś jeszcze nikogo do ulubionych. Wejdź w profil zawodnika i kliknij serduszko!")

        with c2:
            st.subheader("Ostatnie mecze, na których byłeś")
            att_list = run_query("SELECT match_id FROM attendance WHERE username=? ORDER BY rowid DESC LIMIT 5",
                                 (st.session_state['username'],), fetch=True)
            if att_list:
                for a in att_list:
                    st.write(f"🏟️ {a[0]}")
            else:
                st.caption("Brak danych.")

    # --- TAB 2: DREAM TEAM ---
    with strefa_tabs[1]:
        st.subheader("Stwórz swoją legendarną jedenastkę TSP")

        # Pobierz listę wszystkich piłkarzy do selectboxów
        df_all_p = load_data("pilkarze.csv")
        if df_all_p is not None:
            all_names = sorted(df_all_p['imię i nazwisko'].unique().tolist())

            # Pobierz zapisaną
            saved_dt = run_query("SELECT * FROM dream_team WHERE username=?", (st.session_state['username'],),
                                 fetch=True)
            defaults = [""] * 12
            if saved_dt:
                defaults = saved_dt[0][1:]  # pomijamy username

            with st.form("dream_team_form"):
                formation = st.selectbox("Formacja", ["1-4-4-2", "1-4-3-3", "1-3-5-2"], index=0)  # Uproszczenie

                c_gk = st.columns(3)
                with c_gk[1]:
                    gk = st.selectbox("Bramkarz", [""] + all_names,
                                      index=all_names.index(defaults[1]) if defaults[1] in all_names else 0)

                st.markdown("---")
                st.caption("Obrona")
                cd1, cd2, cd3, cd4 = st.columns(4)
                d1 = cd1.selectbox("Lewy Obr.", [""] + all_names, key="d1")
                d2 = cd2.selectbox("Środek Obr.", [""] + all_names, key="d2")
                d3 = cd3.selectbox("Środek Obr.", [""] + all_names, key="d3")
                d4 = cd4.selectbox("Prawy Obr.", [""] + all_names, key="d4")

                st.markdown("---")
                st.caption("Pomoc")
                cm1, cm2, cm3, cm4 = st.columns(4)
                m1 = cm1.selectbox("Lewy Pom.", [""] + all_names, key="m1")
                m2 = cm2.selectbox("Środek Pom.", [""] + all_names, key="m2")
                m3 = cm3.selectbox("Środek Pom.", [""] + all_names, key="m3")
                m4 = cm4.selectbox("Prawy Pom.", [""] + all_names, key="m4")

                st.markdown("---")
                st.caption("Atak")
                cf1, cf2 = st.columns(2)
                f1 = cf1.selectbox("Napastnik 1", [""] + all_names, key="f1")
                f2 = cf2.selectbox("Napastnik 2", [""] + all_names, key="f2")

                if st.form_submit_button("💾 Zapisz Skład"):
                    run_query("REPLACE INTO dream_team VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (st.session_state['username'], formation, gk, d1, d2, d3, d4, m1, m2, m3, m4, f1, f2))
                    st.success("Zapisano Twoją jedenastkę!")

    # --- TAB 3: QUIZ ---
        # --- TAB 3: SPOŁECZNOŚCIOWY QUIZ ---
        with strefa_tabs[2]:
            st.subheader("🧠 Społecznościowy Quiz Wiedzy")

            # --- SEKCJA 1: DODAJ WŁASNE PYTANIE ---
            with st.expander("➕ Dodaj własne pytanie do puli", expanded=False):
                st.info("Dodaj pytanie, aby inni kibice mogli się sprawdzić! Ty nie wylosujesz swojego pytania.")
                with st.form("add_quiz_q_form"):
                    q_text = st.text_input("Treść pytania", placeholder="N.p. Kto strzelił gola w meczu z...")
                    c_opt = st.columns(3)
                    o_a = c_opt[0].text_input("Opcja A")
                    o_b = c_opt[1].text_input("Opcja B")
                    o_c = c_opt[2].text_input("Opcja C")

                    correct_opt = st.selectbox("Poprawna odpowiedź", ["A", "B", "C"])

                    if st.form_submit_button("Wyślij pytanie"):
                        if q_text and o_a and o_b and o_c:
                            # Ustalanie która treść jest poprawna
                            final_ans = o_a if correct_opt == "A" else (o_b if correct_opt == "B" else o_c)

                            run_query("""INSERT INTO user_questions (author, q, op_a, op_b, op_c, ans) 
                                         VALUES (?, ?, ?, ?, ?, ?)""",
                                      (st.session_state['username'], q_text, o_a, o_b, o_c, final_ans))
                            st.success("Dziękujemy! Twoje pytanie trafiło do bazy.")
                        else:
                            st.error("Uzupełnij wszystkie pola.")

            st.divider()

            # --- SEKCJA 2: ROZWIĄŻ QUIZ ---
            # Obsługa stanu quizu (żeby pytania nie zmieniały się przy kliknięciu)
            if 'quiz_active' not in st.session_state: st.session_state['quiz_active'] = False
            if 'quiz_questions' not in st.session_state: st.session_state['quiz_questions'] = []
            if 'quiz_score' not in st.session_state: st.session_state['quiz_score'] = 0

            # Przycisk startu
            if not st.session_state['quiz_active']:
                st.write("Sprawdź swoją wiedzę, odpowiadając na pytania innych kibiców!")
                if st.button("🚀 Rozpocznij Quiz (5 pytań)"):
                    # 1. Pobierz pytania z bazy, gdzie AUTOR != JA
                    # Dodajemy też kilka pytań "systemowych", żeby quiz nie był pusty na start
                    import random

                    # Pytania systemowe (zawsze dostępne)
                    base_questions = [
                        ("SYSTEM", "W którym roku TSP awansowało po raz pierwszy do Ekstraklasy?", "2009", "2010",
                         "2011", "2011"),
                        ("SYSTEM", "Kto jest najlepszym strzelcem w historii klubu?", "Robert Demjan", "Damian Chmiel",
                         "Fabian Pawela", "Robert Demjan"),
                        ("SYSTEM", "Maskotka klubu to:", "Góral", "Reksio", "Beskid", "Reksio")
                    ]

                    # Pytania użytkowników (z wykluczeniem autora)
                    db_qs = run_query("SELECT author, q, op_a, op_b, op_c, ans FROM user_questions WHERE author != ?",
                                      (st.session_state['username'],), fetch=True)

                    # Połączenie puli
                    full_pool = base_questions + (db_qs if db_qs else [])

                    # Losowanie 5 pytań (lub mniej, jeśli pula jest mała)
                    k = min(5, len(full_pool))
                    if k > 0:
                        st.session_state['quiz_questions'] = random.sample(full_pool, k)
                        st.session_state['quiz_active'] = True
                        st.session_state['quiz_score'] = 0
                        st.rerun()
                    else:
                        st.warning("Baza pytań jest pusta. Bądź pierwszy i dodaj pytanie powyżej!")

            # Wyświetlanie pytań (jeśli quiz aktywny)
            else:
                with st.form("quiz_solving_form"):
                    for i, (auth, q, oa, ob, oc, ans) in enumerate(st.session_state['quiz_questions']):
                        st.markdown(f"**{i + 1}. {q}**")
                        if auth != "SYSTEM":
                            st.caption(f"Autor pytania: @{auth}")

                        # Mieszamy odpowiedzi, żeby nie zawsze A było A (opcjonalne, tutaj proste)
                        opts = [oa, ob, oc]
                        # Używamy klucza 'ans', żeby potem sprawdzić
                        sel = st.radio(f"Wybierz:", opts, key=f"q_answ_{i}", index=None)

                    submitted = st.form_submit_button("Sprawdź wyniki")

                    if submitted:
                        score = 0
                        total = len(st.session_state['quiz_questions'])

                        st.write("---")
                        st.subheader("Wyniki:")

                        all_answered = True
                        for i, (auth, q, oa, ob, oc, proper_ans) in enumerate(st.session_state['quiz_questions']):
                            user_ans = st.session_state.get(f"q_answ_{i}")
                            if not user_ans:
                                all_answered = False

                            if user_ans == proper_ans:
                                score += 1
                                st.success(f"Pytanie {i + 1}: ✅ Dobrze! ({proper_ans})")
                            else:
                                st.error(f"Pytanie {i + 1}: ❌ Źle. Prawidłowa: {proper_ans}")

                        if all_answered:
                            st.metric("Twój wynik", f"{score} / {total}")

                            # Zapis wyniku do bazy
                            run_query("INSERT INTO quiz_results VALUES (?, ?, ?)",
                                      (st.session_state['username'], score, str(datetime.date.today())))

                            if score == total:
                                st.balloons()
                                st.write("🥇 Brawo! Bezbłędnie!")
                        else:
                            st.warning("Nie zaznaczyłeś odpowiedzi we wszystkich pytaniach, ale wynik policzyliśmy.")

                        # Reset
                        if st.button("Zakończ / Spróbuj ponownie"):
                            st.session_state['quiz_active'] = False
                            st.session_state['quiz_questions'] = []
                            st.rerun()

elif opcja == "🕵️ Ciemne Karty Historii":
    # --- ZABEZPIECZENIE PRZED GOŚĆMI (Dostęp do całego modułu) ---
    if st.session_state.get('username') == 'guest' or not st.session_state.get('logged_in'):
        st.error("⛔ Odmowa dostępu.")
        st.info("Ta sekcja jest ukryta dla konta gościnnego. Wymagane uprawnienia administratora.")
    else:
        st.header("🕵️ Ciemne Karty Historii (2003-2006)")

        st.error("""
        **⚠️ OSTRZEŻENIE HISTORYCZNE**
        Poniższe dane dotyczą udowodnionego procederu korupcyjnego (tzw. "afera fryzjera"), w którym brał udział klub Podbeskidzie Bielsko-Biała. 
        Wydarzenia te zostały potwierdzone przez prokuraturę i organy dyscyplinarne PZPN.
        """)

        col_text, col_facts = st.columns([2, 1])

        with col_text:
            st.markdown("""
            ### 📉 Konsekwencje prawne i sportowe
            W wyniku śledztwa dotyczącego ustawiania meczów w dawnej II lidze, klub został ukarany przez Wydział Dyscypliny PZPN:

            * **Kara punktowa:** Odjęcie **6 punktów** na starcie sezonu 2007/2008.
            * **Kara finansowa:** 50 tysięcy złotych.
            * **Wyroki:** Zarzuty i wyroki usłyszeli ówcześni działacze (m.in. prezes Stanisław P., kierownik Jerzy W.) oraz sędziowie i obserwatorzy.
            """)

        with col_facts:
            st.info("""
            **Legenda Statusu:**
            * 🔴 **Kupiony:** Wręczono łapówkę.
            * 🟠 **Próba kupna:** Złożono propozycję, ale pieniądze nie zostały przekazane (np. przez wynik).
            """)

        st.divider()
        st.subheader("📋 Kalendarium Korupcji")

        # DANE O KORUPCJI
        corruption_data = [
            {
                "Sezon": "2003/04", "Data": "30.08.2003", "Rywal": "Ruch Chorzów", "Wynik": "2:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Prezes Stanisław P. wręczył 15 tys. zł łapówki sędziemu Piotrowi K."
            },
            {
                "Sezon": "2003/04", "Data": "12.10.2003", "Rywal": "KSZO Ostrowiec Św.", "Wynik": "0:1",
                "Status": "🟠 Próba kupna", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia przyjął propozycję 7 tys. zł, ale ich nie dostał, bo Podbeskidzie przegrało."
            },
            {
                "Sezon": "2003/04", "Data": "18.10.2003", "Rywal": "Zagłębie Lubin", "Wynik": "4:2",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Prezes przekazał sędziemu Marcinowi P. 10 tys. zł po meczu."
            },
            {
                "Sezon": "2003/04", "Data": "25.10.2003", "Rywal": "GKS Bełchatów", "Wynik": "2:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Marcin N. otrzymał 10-15 tys. zł przekazem po meczu."
            },
            {
                "Sezon": "2003/04", "Data": "27.03.2004", "Rywal": "Polar Wrocław", "Wynik": "2:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Prezes wręczył 10 tys. zł sędziemu, którego Ryszard F. nazwał 'swoim synkiem'."
            },
            {
                "Sezon": "2003/04", "Data": "29.04.2004", "Rywal": "Jagiellonia Białystok", "Wynik": "2:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia otrzymał 5 tys. zł, opłacony został także obserwator PZPN."
            },
            {
                "Sezon": "2003/04", "Data": "06.06.2004", "Rywal": "Aluminium Konin", "Wynik": "1:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Łukasz B. otrzymał 10 tys. zł dwa tygodnie po meczu."
            },
            {
                "Sezon": "2004/05", "Data": "31.07.2004", "Rywal": "ŁKS Łódź", "Wynik": "0:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Wręczono 15 tys. zł przed meczem, sędzia musiał zwrócić 5 tys. zł z powodu remisu."
            },
            {
                "Sezon": "2004/05", "Data": "05.09.2004", "Rywal": "Radomiak Radom", "Wynik": "1:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Mariusz S. i obserwatorzy opłaceni (łącznie ok. 15 tys. zł)."
            },
            {
                "Sezon": "2004/05", "Data": "02.10.2004", "Rywal": "Świt Nowy Dwór Maz.", "Wynik": "1:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Obiecane 10 tys. zł, wypłacone 5 tys. zł z powodu remisu."
            },
            {
                "Sezon": "2004/05", "Data": "16.10.2004", "Rywal": "KSZO Ostrowiec Św.", "Wynik": "2:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Piotr K. otrzymał 10 tys. zł po meczu."
            },
            {
                "Sezon": "2004/05", "Data": "30.10.2004", "Rywal": "Piast Gliwice", "Wynik": "1:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Adam K. otrzymał 10 tys. zł po meczu."
            },
            {
                "Sezon": "2004/05", "Data": "07.11.2004", "Rywal": "Zagłębie Sosnowiec", "Wynik": "3:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Paweł S. otrzymał 10 tys. zł po meczu."
            },
            {
                "Sezon": "2004/05", "Data": "14.11.2004", "Rywal": "MKS Mława", "Wynik": "2:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia Sławomir P. otrzymał 10 tys. zł od działacza."
            },
            {
                "Sezon": "2004/05", "Data": "16.04.2005", "Rywal": "Szczakowianka Jaworzno", "Wynik": "2:1",
                "Status": "🟠 Próba kupna", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia zgodził się na 15 tys. zł, ale nie dostał pieniędzy przez aresztowania działaczy."
            },
            {
                "Sezon": "2004/05", "Data": "23.04.2005", "Rywal": "Ruch Chorzów", "Wynik": "0:0",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia dostał min. 3 tys. zł za remis (obiecane 10 tys. zł za wygraną)."
            },
            {
                "Sezon": "2004/05", "Data": "04.06.2005", "Rywal": "Piast Gliwice", "Wynik": "0:2",
                "Status": "🟠 Próba kupna", "Zawodnicy (TSP)": "—",
                "Opis": "Sędzia przyjął propozycję 'dużej premii', ale jej nie dostał z powodu porażki Podbeskidzia."
            },
            {
                "Sezon": "2005/06", "Data": "15.04.2006", "Rywal": "Radomiak Radom", "Wynik": "2:1",
                "Status": "🔴 Kupiony", "Zawodnicy (TSP)": "Paweł S., Dariusz K., Mariusz S., Tomasz G.",
                "Opis": "Łapówka (5 tys. zł) dla gracza rywali (Piotra D.) za odpuszczenie meczu."
            },
            {
                "Sezon": "2005/06", "Data": "05.05.2006", "Rywal": "ŁKS Łódź", "Wynik": "1:0",
                "Status": "🔴 Kupiony",
                "Zawodnicy (TSP)": "Grzegorz P., Łukasz G., Łukasz M., Piotr K., Mariusz S., Dariusz K., Marcin H.",
                "Opis": "Zawodnicy zrzucili się ze swojej premii meczowej na 10 tys. zł łapówki dla sędziego Piotra W."
            }
        ]

        df_corr = pd.DataFrame(corruption_data)

        # Wyświetlanie tabeli
        st.dataframe(
            df_corr,
            hide_index=True,
            use_container_width=True,
            height=400,
            column_config={
                "Sezon": st.column_config.TextColumn("Sezon", width="small"),
                "Data": st.column_config.TextColumn("Data", width="small"),
                "Rywal": st.column_config.TextColumn("Rywal", width="medium"),
                "Wynik": st.column_config.TextColumn("Wynik", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Zawodnicy (TSP)": st.column_config.TextColumn("Zaangażowani Zawodnicy TSP", width="large"),
                "Opis": st.column_config.TextColumn("Szczegóły zdarzenia", width="large"),
            }
        )

        # =========================================================
        # ZWERYFIKOWANI INWESTORZY (TYLKO DLA WYBRANYCH)
        # =========================================================
        authorized_users = ['Djero', 'KKowalski', 'JFilip']
        current_user = st.session_state.get('username')

        if current_user in authorized_users:
            st.markdown("---")
            st.subheader("🕵️ Zweryfikowani 'Kreatywni Inwestorzy'")
            st.info(
                "Na podstawie akt sądowych oraz dostępnych danych historycznych, poniżej znajduje się lista zidentyfikowanych zawodników biorących udział w zrzutkach (tzw. 'inwestycjach').")

            # Mapowanie skrótów na pełne nazwiska
            verified_map = {
                "Paweł S.": "Paweł Sibik",
                "Dariusz K.": "Dariusz Kołodziej",
                "Mariusz S.": "Mariusz Sacha",
                "Tomasz G.": "Tomasz Górkiewicz",
                "Grzegorz P.": "Grzegorz Pater",
                "Łukasz G.": "Łukasz Gorszkow",
                "Łukasz M.": "Łukasz Merda",
                "Piotr K.": "Piotr Koman",
                "Marcin H.": "Marcin Hirsz"
            }

            # Pobranie danych o sezonach z wystepy.csv
            df_w_hist = load_details("wystepy.csv")

            if df_w_hist is not None:
                def get_player_seasons(p_name):
                    p_rows = df_w_hist[df_w_hist['Zawodnik_Clean'] == p_name]
                    if p_rows.empty: return "Brak w bazie"
                    if 'Sezon' not in p_rows.columns: return "Brak danych"
                    seasons = sorted(p_rows['Sezon'].unique().tolist())
                    return ", ".join(seasons)
            else:
                def get_player_seasons(p_name):
                    return "Brak pliku wystepy.csv"

            # Generowanie kart (KAFELKÓW)
            cols_inv = st.columns(4)
            idx = 0

            for abbr, full_name in verified_map.items():
                seasons_txt = get_player_seasons(full_name)

                # UWAGA: Kod HTML jest "spłaszczony" (bez wcięć), aby Streamlit
                # nie interpretował go jako bloku kodu (co powoduje wyświetlanie tekstu zamiast grafiki).
                card_html = f"""<div style="border: 1px solid #d63031; border-radius: 10px; padding: 15px; text-align: center; background-color: rgba(214, 48, 49, 0.08); margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); color: inherit;">
                    <div style="font-size: 28px; margin-bottom: 5px;">💸</div>
                    <div style="font-weight: bold; font-size: 1.1em; margin-bottom: 5px;">{full_name}</div>
                    <div style="font-size: 0.85em; opacity: 0.7; margin-bottom: 8px;">({abbr})</div>
                    <div style="background-color: #d63031; color: white; padding: 4px 8px; border-radius: 15px; font-size: 0.75em; font-weight: bold; display: inline-block; margin-bottom: 8px;">KREATYWNY INWESTOR</div>
                    <div style="font-size: 0.8em; border-top: 1px dashed #d63031; padding-top: 5px;">
                        <strong>Sezony:</strong><br>{seasons_txt}
                    </div>
                </div>"""

                with cols_inv[idx % 4]:
                    st.markdown(card_html, unsafe_allow_html=True)
                idx += 1