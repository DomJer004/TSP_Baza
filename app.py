import streamlit as st
import pandas as pd
import datetime
import re
import os
import time
import calendar
import sqlite3
import hashlib
import random

# --- DODAJ TO JEŚLI BRAKUJE ---
try:
    import folium
    from streamlit_folium import st_folium
except ImportError:
    st.error("Brakuje bibliotek do mapy. Zainstaluj je komendą: pip install folium streamlit-folium")

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

    # Tabela pytań użytkowników
    c.execute('''CREATE TABLE IF NOT EXISTS user_questions 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      question TEXT, 
                      correct_ans TEXT, 
                      wrong_a TEXT, 
                      wrong_b TEXT, 
                      author TEXT,
                      added_date TEXT)''')

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
# GLOBALNE STYLE CSS (DARK MODE FIX)
# ==========================================
def apply_custom_css():
    st.markdown("""
        <style>
        /* 1. Kafelki w Kalendarzu */
        .cal-card {
            background-color: var(--secondary-background-color); 
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
            border: 2px solid #28a745; 
            background-color: rgba(40, 167, 69, 0.15); 
        }

        /* 3. Poprawa widoczności metryk */
        [data-testid="stMetricValue"] {
            font-weight: bold;
        }
        /* --- MOBILE TWEAKS --- */
        @media (max-width: 640px) {
            .block-container {
                padding-top: 2rem !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.5rem !important;
            }

            [data-testid="stDataFrame"] th:first-child {
                display: none;
            }

            .cal-card {
                font-size: 0.8rem;
                padding: 2px;
            }

            h1 { font-size: 1.8rem !important; }
            h2 { font-size: 1.5rem !important; }
            h3 { font-size: 1.3rem !important; }
        }
        </style>
    """, unsafe_allow_html=True)


apply_custom_css()  # Uruchomienie stylów

# --- 2. ZARZĄDZANIE SESJĄ I NAWIGACJA (Router) ---
if 'uploader_key' not in st.session_state: st.session_state['uploader_key'] = 0
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = True
if 'username' not in st.session_state: st.session_state['username'] = "Kibic"
if 'role' not in st.session_state: st.session_state['role'] = 'admin'

# Zmienne do nawigacji (kliknięcie w piłkarza)
if 'cm_selected_player' not in st.session_state: st.session_state['cm_selected_player'] = None


def navigate_to_player(name):
    """Funkcja pomocnicza do otwierania profilu"""
    clean_name = str(name).replace("Ⓜ️", "").replace("🤕", "").strip()
    st.session_state['cm_selected_player'] = clean_name
    st.rerun()


# --- KONFIGURACJA GLOBALNA ---
IGNORED_SEASONS = ["1995/96", "1996/97", "1995/1996", "1996/1997"]


def filter_seasons(df, col_name='Sezon'):
    """Usuwa z DataFrame rekordy z ignorowanych sezonów."""
    if df is None or col_name not in df.columns:
        return df
    return df[~df[col_name].isin(IGNORED_SEASONS)].copy()


# --- GŁÓWNA APLIKACJA ---
st.title("⚽ Baza Danych TSP - Centrum Wiedzy")

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except:
    HAS_PLOTLY = False

# --- MAPOWANIE KRAJÓW ---
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
    df_uv = load_data("pilkarze.csv")
    df_long = load_data("pilkarze.csv")
    df_strzelcy = load_data("strzelcy.csv")
    df_det_goals = load_details("wystepy.csv")

    if df_uv is None:
        st.error("Brak pliku pilkarze.csv")
        return

    df_uv = prepare_flags(df_uv)

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

    badges = get_player_record_badges(player_name, df_w=df_det_goals, df_p=df_uv_sorted)
    if badges:
        st.write("")
        badges_html = ""
        for b in badges:
            badges_html += f"""<span style="background-color: {b['color']}20; border: 1px solid {b['color']}; color: {b['color']}; padding: 4px 10px; border-radius: 15px; font-size: 0.9rem; font-weight: bold; margin-right: 5px; margin-bottom: 5px; display: inline-block;">{b['icon']} {b['text']}</span>"""
        st.markdown(badges_html, unsafe_allow_html=True)
        st.write("")

    debut_txt = "-"
    last_txt = "-"
    p_hist = pd.DataFrame()
    if df_det_goals is not None:
        p_hist = df_det_goals[df_det_goals['Zawodnik_Clean'] == player_name].copy()
        if not p_hist.empty and 'Data_Sort' in p_hist.columns:
            p_hist = p_hist.sort_values('Data_Sort', ascending=True)

            fm = p_hist.iloc[0]
            d_dt = pd.to_datetime(fm['Data_Sort'])
            d_str = d_dt.strftime('%d.%m.%Y') if pd.notna(d_dt) else "-"
            debut_txt = f"{d_str} vs {fm.get('Przeciwnik', '')}\n{calculate_exact_age_str(birth_date, d_dt) if birth_date else ''}"

            lm = p_hist.iloc[-1]
            l_dt = pd.to_datetime(lm['Data_Sort'])
            l_str = l_dt.strftime('%d.%m.%Y') if pd.notna(l_dt) else "-"
            last_txt = f"{l_str} vs {lm.get('Przeciwnik', '')}\n{calculate_exact_age_str(birth_date, l_dt) if birth_date else ''}"

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

    st.markdown("---")
    st.subheader("📜 Szczegółowa historia meczowa")
    st.caption("ℹ️ Kliknij w wiersz tabeli, aby zobaczyć pełny raport meczowy.")

    if not p_hist.empty:
        if 'Data_Sort' in p_hist.columns:
            p_hist = p_hist.sort_values('Data_Sort', ascending=False)

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

        cols_base = ['Data_Sort', 'Przeciwnik', 'Wynik', 'Rola', 'Status', 'Minuty']
        target = cols_base + (['Wpuszczone', 'Czyste konto'] if is_gk else ['Gole']) + ['Żółte', 'Czerwone']
        final_cols = [c for c in target if c in p_hist.columns]

        if 'Sezon' in p_hist.columns:
            unique_seasons = p_hist['Sezon'].unique()

            for sezon in unique_seasons:
                with st.expander(f"📂 Sezon {sezon}", expanded=True):
                    season_df = p_hist[p_hist['Sezon'] == sezon].copy()

                    event = st.dataframe(
                        season_df[final_cols].reset_index(drop=True),
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"hist_pl_{player_name}_{sezon}",
                        column_config={
                            "Data_Sort": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                            "Gole": st.column_config.NumberColumn("Gole", format="%d ⚽"),
                            "Wpuszczone": st.column_config.NumberColumn("Wpuszczone", format="%d ❌"),
                            "Minuty": st.column_config.NumberColumn("Minuty", format="%d'"),
                            "Żółte": st.column_config.NumberColumn("Żółte", format="%d 🟨"),
                            "Czerwone": st.column_config.NumberColumn("Czerwone", format="%d 🟥")
                        }
                    )

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
            st.dataframe(p_hist[final_cols], use_container_width=True)

    else:
        st.info("Brak historii meczowej.")

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
    df_t = load_data("trenerzy.csv")
    df_m = load_data("mecze.csv")
    df_details = load_details("wystepy.csv")

    if df_t is None:
        st.error("Brak pliku trenerzy.csv")
        return

    df_t = prepare_flags(df_t)

    coach_rows = df_t[df_t['imię i nazwisko'] == coach_name].copy()
    if coach_rows.empty:
        st.warning(f"Nie znaleziono trenera: {coach_name}")
        return

    base_info = coach_rows.iloc[0]

    def safe_parse_date(val):
        s = str(val).strip().lower()
        if s in ['-', 'nan', '', 'obecnie', 'null']:
            return pd.NaT
        try:
            return pd.to_datetime(s, dayfirst=True)
        except:
            pass
        try:
            return pd.to_datetime(s, format='%Y-%m-%d')
        except:
            pass
        try:
            return pd.to_datetime(s)
        except:
            return pd.NaT

    matches_mask = pd.Series([False] * len(df_m)) if df_m is not None else pd.Series([], dtype=bool)
    tenure_list = []

    if df_m is not None:
        col_m_date = next((c for c in df_m.columns if c in ['data meczu', 'data', 'dt_obj']), None)

        if col_m_date:
            df_m['dt_temp'] = df_m[col_m_date].apply(safe_parse_date)

            for _, row in coach_rows.iterrows():
                s_date = safe_parse_date(row.get('początek'))
                e_date = safe_parse_date(row.get('koniec'))

                is_curr = False
                if pd.isna(e_date):
                    e_date = pd.Timestamp.today() + pd.Timedelta(days=365)
                    is_curr = True

                s_txt = s_date.strftime('%d.%m.%Y') if pd.notna(s_date) else "?"
                e_txt = "obecnie" if is_curr else (e_date.strftime('%d.%m.%Y') if pd.notna(row.get('koniec')) else "?")

                if pd.notna(s_date):
                    tenure_list.append(f"{s_txt} — {e_txt}")
                    current_mask = (df_m['dt_temp'] >= s_date) & (df_m['dt_temp'] <= e_date)
                    matches_mask |= current_mask

    coach_matches = df_m[matches_mask].sort_values('dt_temp',
                                                   ascending=False) if not matches_mask.empty else pd.DataFrame()

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
        pts = (wins * 3) + draws
        ppg_val = pts / total if total > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Mecze", total)
        k2.metric("Bilans", f"{wins}-{draws}-{losses}")
        k3.metric("Średnia pkt", f"{ppg_val:.2f}")
        k4.metric("Bramki", f"{gf}:{ga}")

        st.divider()
        st.subheader("📜 Historia Meczów (Sezonami)")
        st.caption("ℹ️ Kliknij w wiersz tabeli, aby zobaczyć szczegóły meczu.")

        display_df = coach_matches.copy()
        display_df['Data'] = display_df['dt_temp']
        display_df['Gdzie'] = display_df['dom'].apply(
            lambda x: "🏠" if str(x).lower() in ['1', 'true', 'dom', 'tak'] else "🚌")

        if 'sezon' not in display_df.columns:
            display_df['sezon'] = "Nieznany"

        unique_seasons = display_df['sezon'].unique()

        for sezon in unique_seasons:
            with st.expander(f"📂 Sezon {sezon}", expanded=True):
                season_matches = display_df[display_df['sezon'] == sezon].copy()

                cols_needed = ['Data', 'rywal', 'wynik', 'Gdzie', 'rozgrywki']
                final_cols = [c for c in cols_needed if c in season_matches.columns]

                event = st.dataframe(
                    season_matches[final_cols].style.map(color_results_logic, subset=[
                        'wynik'] if 'wynik' in season_matches.columns else None),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"coach_hist_{sezon}",
                    column_config={
                        "Data": st.column_config.DateColumn("Data", format="DD.MM.YYYY"),
                        "rywal": st.column_config.TextColumn("Rywal"),
                        "wynik": st.column_config.TextColumn("Wynik"),
                        "Gdzie": st.column_config.TextColumn("D/W", width="small")
                    }
                )

                if event.selection.rows:
                    idx = event.selection.rows[0]
                    selected_match = season_matches.iloc[idx]

                    st.markdown("---")
                    st.markdown(f"#### 🔎 Raport meczowy")

                    found_squad = pd.DataFrame()
                    if df_details is not None and 'Data_Sort' in df_details.columns:
                        found_squad = df_details[
                            df_details['Data_Sort'].dt.date == selected_match['Data'].date()].copy()

                    if not found_squad.empty:
                        found_squad = found_squad.sort_values('File_Order')
                        real_label = found_squad.iloc[0]['Mecz_Label']
                        render_match_report_logic(real_label, found_squad)
                    else:
                        st.warning("Brak szczegółowego składu (wystepy.csv). Wyświetlam dostępne dane ogólne:")
                        raw_scorers = str(selected_match.get('strzelcy', '-'))
                        if raw_scorers not in ['-', 'nan', '']:
                            st.markdown(f"**⚽ Strzelcy:** {raw_scorers}")
                        else:
                            st.info("Brak danych o strzelcach.")

    else:
        st.info("Brak zarejestrowanych meczów w bazie dla tego trenera.")


CITY_COORDS = {
    'Andrychów': [49.854, 19.342], 'Bełchatów': [51.368, 19.360], 'Białystok': [53.132, 23.168],
    'Bielawa': [50.683, 16.617], 'Bieruń': [50.089, 19.092], 'Boguchwała': [49.983, 21.933],
    'Brenna': [49.725, 18.917], 'Bydgoszcz': [53.123, 18.008], 'Bytom': [50.348, 18.933],
    'Bytów': [54.173, 17.494], 'Chełmek': [50.100, 19.250], 'Chojnice': [53.696, 17.557],
    'Chorzów': [50.297, 18.953], 'Chrzanów': [50.133, 19.400], 'Chybie': [49.900, 18.833],
    'Czermno': [51.050, 20.033], 'Częstochowa': [50.811, 19.120], 'Dankowice': [49.933, 19.150],
    'Drezdenko': [52.833, 15.833], 'Elbląg': [54.152, 19.408], 'Gdańsk': [54.352, 18.646],
    'Gdynia': [54.518, 18.530], 'Gliwice': [50.294, 18.671], 'Gorzyce': [50.667, 21.833],
    'Gorzów Wielkopolski': [52.736, 15.228], 'Gracze': [50.667, 17.550], 'Grodzisk Mazowiecki': [52.100, 20.633],
    'Grodzisk Wielkopolski': [52.233, 16.367], 'Grudziądz': [53.484, 18.753], 'Głogów': [51.663, 16.084],
    'Janikowo': [52.750, 18.117], 'Jastrzębie': [49.951, 18.591], 'Jaworzno': [50.200, 19.267],
    'Kaczyce': [49.817, 18.600], 'Kalisz': [51.767, 18.083], 'Katowice': [50.264, 19.023],
    'Kielce': [50.866, 20.628], 'Klecza': [49.883, 19.533], 'Kleczew': [52.367, 18.167],
    'Kluczbork': [50.973, 18.214], 'Knurów': [50.217, 18.683], 'Konin': [52.217, 18.250],
    'Kraków': [50.064, 19.945], 'Krzanowice': [50.017, 18.133], 'Kędzierzyn-Koźle': [50.350, 18.217],
    'Kęty': [49.883, 19.217], 'Legnica': [51.207, 16.155], 'Libiąż': [50.100, 19.317],
    'Lubin': [51.398, 16.200], 'Lublin': [51.246, 22.568], 'Lędziny': [50.117, 19.117],
    'Mielec': [50.287, 21.421], 'Milówka': [49.567, 19.083], 'Mława': [53.117, 20.383],
    'Nieciecza': [50.158, 20.849], 'Niedobczyce': [50.067, 18.483], 'Niepołomice': [50.033, 20.217],
    'Niwka': [50.250, 19.167], 'Nowa Wieś': [49.900, 19.167], 'Nowe Miasto Lubawskie': [53.417, 19.600],
    'Nowy Dwór Mazowiecki': [52.433, 20.717], 'Nowy Sącz': [49.621, 20.697], 'Nowy Targ': [49.483, 20.033],
    'Oleśnica': [51.200, 17.383], 'Olsztyn': [53.778, 20.480], 'Opoczno': [51.383, 20.283],
    'Opole': [50.675, 17.921], 'Ostrowiec Świętokrzyski': [50.929, 21.385], 'Otwock': [52.100, 21.267],
    'Oświęcim': [50.033, 19.217], 'Piotrków Trybunalski': [51.400, 19.700], 'Pisarzowice': [49.900, 19.133],
    'Polkowice': [51.501, 16.072], 'Porąbka': [49.817, 19.217], 'Poznań': [52.406, 16.925],
    'Pruszków': [52.170, 20.806], 'Puławy': [51.417, 21.967], 'Płock': [52.546, 19.706],
    'Radzionków': [50.383, 18.900], 'Ruda Śląska': [50.267, 18.850], 'Rzeszów': [50.041, 21.999],
    'Sanok': [49.550, 22.200], 'Siedlce': [52.167, 22.290], 'Siersza': [50.183, 19.450],
    'Skierniewice': [51.950, 20.150], 'Skoczów': [49.800, 18.783], 'Sosnowiec': [50.286, 19.104],
    'Stalowa Wola': [50.582, 22.053], 'Stanisław': [49.867, 19.567], 'Strumień': [49.917, 18.767],
    'Stróże': [49.658, 20.963], 'Sucha Beskidzka': [49.733, 19.600], 'Suwałki': [54.099, 22.927],
    'Szczecin': [53.428, 14.552], 'Turek': [52.017, 18.500], 'Tychy': [50.123, 18.991],
    'Ustroń': [49.717, 18.817], 'Wadowice': [49.883, 19.483], 'Warszawa': [52.229, 21.012],
    'Wałbrzych': [50.767, 16.283], 'Wieprz': [49.900, 19.317], 'Wikielec': [53.583, 19.517],
    'Wodzisław Śląski': [50.003, 18.466], 'Wrocław': [51.107, 17.038], 'Węgierska Górka': [49.608, 19.117],
    'Włocławek': [52.650, 19.067], 'Zabierzów': [50.117, 19.800], 'Zabrze': [50.301, 18.785],
    'Zamość': [50.717, 23.250], 'Zawiercie': [50.483, 19.417], 'Zembrzyce': [49.767, 19.583],
    'Zielona Góra': [51.933, 15.500], 'Ząbki': [52.283, 21.117], 'Łomża': [53.183, 22.083],
    'Łowicz': [52.117, 19.950], 'Łódź': [51.759, 19.456], 'Łęczna': [51.301, 22.879],
    'Świebodzin': [52.250, 15.533], 'Świnoujście': [53.910, 14.247], 'Żagań': [51.617, 15.317],
    'Żary': [51.633, 15.133], 'Żywiec': [49.683, 19.200]
}

st.markdown("""
<style>
    .soccer-pitch {
        background: linear-gradient(0deg, #2c8f55 0%, #3e9c66 100%);
        border: 4px solid white;
        border-radius: 8px;
        padding: 40px 10px;
        min-height: 900px; 
        position: relative;
        box-shadow: inset 0 0 50px rgba(0,0,0,0.5);
        margin-bottom: 30px;
    }
    .pitch-line-center {
        position: absolute; top: 50%; left: 0; right: 0;
        height: 2px; background: rgba(255,255,255,0.4);
    }
    .pitch-circle {
        position: absolute; top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 150px; height: 150px;
        border: 2px solid rgba(255,255,255,0.4);
        border-radius: 50%;
    }
    .fut-card {
        background: linear-gradient(135deg, #1e1e1e 0%, #2a2a2a 100%);
        border: 1px solid #d4af37; 
        border-radius: 6px;
        padding: 8px 4px;
        text-align: center;
        width: 130px; 
        margin: 0 auto; 
        box-shadow: 0 4px 10px rgba(0,0,0,0.4);
        color: white;
        transition: transform 0.2s;
    }
    .fut-card:hover { transform: scale(1.05); z-index: 10; }
    .fut-pos { font-size: 10px; color: #aaa; text-transform: uppercase; letter-spacing: 1px; }
    .fut-name { font-weight: bold; font-size: 13px; margin: 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fut-stats { font-size: 11px; color: #d4af37; }
    .fut-flag { width: 24px; height: 16px; border-radius: 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); margin-bottom: 2px; }
</style>
""", unsafe_allow_html=True)


def render_pitch_card(player_name, role):
    if not player_name:
        return """
        <div style="width:130px; height:80px; border:2px dashed rgba(255,255,255,0.2); border-radius:6px; margin:0 auto;"></div>
        """

    df_p = load_data("pilkarze.csv")
    df_w = load_details("wystepy.csv")

    clean_name = str(player_name).strip()
    nat_img = ""
    stats_txt = "0 M / 0 G"

    if df_p is not None:
        row = df_p[df_p['imię i nazwisko'] == clean_name]
        if not row.empty:
            r = row.iloc[0]
            f_url = get_flag_url(r.get('Narodowość', '-'))
            if f_url:
                nat_img = f'<img src="{f_url}" class="fut-flag">'
            else:
                nat_img = '<span style="font-size:16px;">🏳️</span>'

            m, g = 0, 0
            if df_w is not None:
                p_s = df_w[df_w['Zawodnik_Clean'] == clean_name]
                if not p_s.empty:
                    m = len(p_s)
                    g = int(p_s['Gole'].sum())
            else:
                try:
                    m = int(pd.to_numeric(r.get('mecze'), errors='coerce') or 0)
                    g = int(pd.to_numeric(r.get('gole'), errors='coerce') or 0)
                except:
                    pass

            stats_txt = f"{m} M / {g} ⚽"

    return f"""
    <div class="fut-card">
        <div class="fut-pos">{role}</div>
        <div>{nat_img}</div>
        <div class="fut-name" title="{clean_name}">{clean_name}</div>
        <div class="fut-stats">{stats_txt}</div>
    </div>
    """


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

        # --- 1.5 KOREKTA SEZONU COVID-19 (LIPEC 2020) ---
        if 'Sezon' in df.columns and 'Data_Sort' in df.columns:
            mask_covid = (df['Data_Sort'].dt.year == 2020) & (df['Data_Sort'].dt.month == 7)
            df.loc[mask_covid, 'Sezon'] = df.loc[mask_covid, 'Sezon'].astype(str).replace({
                '2020/2021': '2019/2020',
                '2020/21': '2019/20',
                '20/21': '19/20'
            })

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

        # --- LOGIKA MINUT (POPRAWIONA O DOGRYWKI I KARNE) ---
        def calc_mins(row):
            status = str(row.get('Status', '')).strip()
            entry, exit_t, curr = row['Wejście'], row['Zejście'], row['Minuty']
            res_s = str(row.get('Wynik', '')).lower()

            # Dodano rozpoznawanie rzutów karnych ("k.")
            is_extra_time = ('pd.' in res_s or 'dogr.' in res_s or 'k.' in res_s)

            if is_extra_time:
                full = 120
            else:
                full = 90
                if curr > 90: full = curr

            ev_min = 0
            real = curr

            if status == 'Wszedł':
                ev_min = entry
            elif status in ['Zszedł', 'Czerwona kartka', 'Czerwona']:
                ev_min = exit_t if exit_t > 0 else curr

            if status in ['Czerwona kartka', 'Czerwona'] or row['Czerwone'] > 0:
                red_minute = exit_t if exit_t > 0 else curr
                if red_minute > 0:
                    real = (red_minute - entry) if entry > 0 else red_minute
                else:
                    real = curr if curr <= full else full

            elif status in ['Cały mecz', 'Grał'] and entry == 0 and exit_t == 0:
                real = curr if curr > 0 else full

            elif status == 'Zszedł':
                if exit_t > 0:
                    real = (exit_t - entry) if entry > 0 else exit_t
                else:
                    real = curr

            elif status == 'Wszedł' and exit_t == 0:
                if entry > 0:
                    calc = full - entry
                    real = calc if calc > 0 else 1
                else:
                    real = curr

            if real > 120:
                real = 120

            return pd.Series([ev_min, real])

        df[['Minuta_Zmiany_Real', 'Minuty']] = df.apply(calc_mins, axis=1)
        return df
    except Exception as e:
        return None
def get_flag_url(name):
    if not isinstance(name, str) or pd.isna(name) or name.strip() in ['-', '']: return None
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
    if pd.isna(nat_string) or str(nat_string).strip() in ['-', '', 'nan']: return ""
    parts = [p.strip() for p in str(nat_string).split('/')]
    imgs = ""
    for country_name in parts:
        url = get_flag_url(country_name)
        if url:
            imgs += f'<img src="{url}" title="{country_name}" style="height: 24px; border: 1px solid #ddd; border-radius: 4px; margin-right: 6px;">'
    if not imgs: return ""
    return f'<div style="display:flex; align-items:center; margin-top:8px;">{imgs}</div>'


def prepare_flags(df, col='narodowość'):
    target_col = col
    if target_col not in df.columns:
        poss = [c for c in df.columns if c.lower() in ['kraj', 'narodowosc', 'narodowość']]
        if poss: target_col = poss[0]

    if target_col in df.columns:
        df['Flaga'] = df[target_col].apply(get_flag_url)
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

        int_candidates = [
            'wiek', 'suma', 'liczba', 'mecze', 'gole', 'punkty', 'minuty', 'numer',
            'asysty', 'żółte kartki', 'czerwone kartki', 'kanadyjka',
            'gole samobójcze', 'asysta 2. stopnia', 'sprokurowany karny', 'wywalczony karny',
            'karny', 'niestrzelony karny', 'główka', 'lewa', 'prawa', 'czyste konta',
            'obronione karne', 'wpuszczone gole', 'obronione rzuty karne'
        ]

        for col in df.columns:
            if col in int_candidates or 'kartki' in col or 'gole' in col or 'karny' in col:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                df[col] = df[col].astype(int)

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


def parse_result(val):
    if not isinstance(val, str): return None
    clean_val = val.lower().replace(" ", "")
    pen_match = re.search(r'\(?k\.?(\d+)[:\-](\d+)\)?', clean_val)
    if pen_match:
        return int(pen_match.group(1)), int(pen_match.group(2))
    clean_val = clean_val.replace("pd.", "").replace("dogr.", "")
    clean_val = re.sub(r'\(.*?\)', '', clean_val)
    score_match = re.search(r'(\d+)[:\-](\d+)', clean_val)
    if score_match:
        return int(score_match.group(1)), int(score_match.group(2))
    return None


def render_match_report_logic(match_label, squad_df):
    target_date = None
    rival_raw = ""
    competition_info = ""  # Nowa zmienna dla rozgrywek

    if not squad_df.empty:
        if 'Data_Sort' in squad_df.columns:
            try:
                dt_val = squad_df.iloc[0]['Data_Sort']
                if pd.notna(dt_val):
                    target_date = pd.to_datetime(dt_val).date()
            except:
                pass

        if 'Przeciwnik' in squad_df.columns:
            rival_raw = str(squad_df.iloc[0]['Przeciwnik']).strip()
        elif 'Gospodarz' in squad_df.columns and 'Gość' in squad_df.columns:
            h = str(squad_df.iloc[0]['Gospodarz'])
            g = str(squad_df.iloc[0]['Gość'])
            my_aliases = ['podbeskidzie', 'tsp', 'bielsko']
            if any(x in h.lower() for x in my_aliases):
                rival_raw = g
            elif any(x in g.lower() for x in my_aliases):
                rival_raw = h
            else:
                rival_raw = g

    if not target_date:
        try:
            date_part = match_label.split('|')[0].strip()
            target_date = pd.to_datetime(date_part, dayfirst=True).date()
        except:
            pass

    def aggressive_date_parse(val):
        if pd.isna(val) or str(val).strip() in ['', '-', 'nan']: return None
        s = str(val).strip().lower()
        if ',' in s: s = s.split(',', 1)[1].strip()
        if ':' in s and len(s.split()) > 1: s = " ".join(s.split()[:-1])

        months_map = {
            'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
            'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
            'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12'
        }
        for pl, digit in months_map.items():
            if pl in s:
                s = s.replace(pl, digit)
                break

        s = re.sub(r'\s+', '.', s).strip()
        for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y.%m.%d', '%d %m %Y']:
            try:
                return pd.to_datetime(s, format=fmt).date()
            except:
                continue
        try:
            return pd.to_datetime(s).date()
        except:
            return None

    raw_scorers = "-"
    df_matches = load_data("mecze.csv")

    if df_matches is not None and target_date:
        col_d = next((c for c in df_matches.columns if c in ['data meczu', 'data', 'dt_obj']), None)
        if col_d:
            df_matches['clean_date'] = df_matches[col_d].apply(aggressive_date_parse)
            s_win = target_date - datetime.timedelta(days=1)
            e_win = target_date + datetime.timedelta(days=1)
            match_row = df_matches[(df_matches['clean_date'] >= s_win) & (df_matches['clean_date'] <= e_win)]

            if len(match_row) > 1 and rival_raw:
                def norm(txt):
                    return str(txt).lower().replace('ks ', '').replace('mks ', '').replace('gks ', '').strip()

                r_target = norm(rival_raw)
                if 'rywal' in match_row.columns:
                    match_row = match_row[
                        match_row['rywal'].apply(lambda x: r_target in norm(x) or norm(x) in r_target)]

            if not match_row.empty:
                # 1. Pobieranie strzelców
                raw_scorers_val = match_row.iloc[0].get('strzelcy', '-')
                if raw_scorers_val not in ['-', 'nan', '', 'NaN']:
                    raw_scorers = str(raw_scorers_val)

                # 2. Szukanie Rozgrywek (np. Puchar Polski, Liga, Baraże)
                comp_col = next(
                    (c for c in match_row.columns if c.lower().strip() in ['rozgrywki', 'liga', 'kolejka', 'typ']),
                    None)
                if comp_col:
                    comp_val = str(match_row.iloc[0][comp_col]).strip()
                    if comp_val and comp_val.lower() not in ['nan', '-', '']:
                        competition_info = f" | 🏆 {comp_val}"

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

    try:
        parts = match_label.split('|')
        info_s = parts[1].strip() if len(parts) > 1 else match_label
        date_s = parts[0].strip()
    except:
        info_s = match_label
        date_s = str(target_date) if target_date else "-"

    avg_age_str = ""
    df_p_bio = load_data("pilkarze.csv")
    if df_p_bio is not None and target_date and not squad_df.empty:
        df_p_bio['join_key'] = df_p_bio['imię i nazwisko'].astype(str).str.lower().str.strip()
        col_b = next((c for c in df_p_bio.columns if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
        if col_b:
            starters = squad_df[
                (squad_df['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka', 'Czerwona'])) & (
                        squad_df['Status'] != 'Wszedł')].copy()
            starters['join_key'] = starters['Zawodnik_Clean'].astype(str).str.lower().str.strip()
            merged_starters = pd.merge(starters, df_p_bio[['join_key', col_b]], on='join_key', how='left')

            def calc_age_at_match(row):
                if pd.isna(row[col_b]): return None
                try:
                    bdate = pd.to_datetime(row[col_b], dayfirst=True)
                    mdate = pd.to_datetime(target_date)
                    return (mdate - bdate).days / 365.25
                except:
                    return None

            merged_starters['age_at_match'] = merged_starters.apply(calc_age_at_match, axis=1)
            valid_ages = merged_starters['age_at_match'].dropna()

            if len(valid_ages) >= 8:
                mean_age = valid_ages.mean()
                mean_age_fmt = f"{mean_age:.2f}".replace('.', ',')
                avg_age_str = f" | 📊 Śr. wieku XI: <b>{mean_age_fmt} lat</b>"

    st.markdown(f"""
    <div style="text-align: center; padding: 15px; background-color: rgba(40, 167, 69, 0.1); border: 1px solid #28a745; border-radius: 8px; margin-bottom: 10px;">
        <h3 style="margin:0; color: var(--text-color);">{info_s}</h3>
        <p style="color: gray; margin: 4px 0 0 0; font-size: 0.85em;">📅 {date_s}{competition_info}{avg_age_str}</p>
    </div>
    """, unsafe_allow_html=True)

    if raw_scorers and raw_scorers != '-' and str(raw_scorers).lower() != 'nan':
        st.markdown("#### 🥅 Strzelcy")
        scorers_list = extract_scorers_list(raw_scorers)
        if scorers_list:
            cols_sc = st.columns(4)
            for idx, item in enumerate(scorers_list):
                col_idx = idx % 4
                with cols_sc[col_idx]:
                    if item['is_own']:
                        st.error(item['display'])
                    else:
                        if st.button(item['display'],
                                     key=f"rep_sc_{match_label}_{idx}_{item['link_name']}_{st.session_state.get('uploader_key', 0)}",
                                     use_container_width=True):
                            st.session_state['cm_selected_player'] = item['link_name']
                            st.rerun()
        else:
            st.write(raw_scorers)
        st.divider()

    if coach_name:
        _, c_btn, _ = st.columns([1, 2, 1])
        with c_btn:
            if st.button(f"👔 Trener: {coach_name}",
                         key=f"coach_btn_{match_label}_fix_{st.session_state.get('uploader_key', 0)}",
                         use_container_width=True):
                st.session_state['selected_coach'] = coach_name
                st.session_state['coach_view_mode'] = 'profile'
                st.session_state['opcja'] = 'Trenerzy'
                st.rerun()

    if squad_df.empty:
        st.warning("Brak szczegółowego składu.")
        return

    map_in_to_out = {}
    map_out_to_in = {}

    sort_c = 'Minuta_Zmiany_Real' if 'Minuta_Zmiany_Real' in squad_df.columns else 'Wejście'
    in_rows = squad_df[squad_df['Status'] == 'Wszedł'].sort_values(sort_c)
    out_rows = squad_df[squad_df['Status'] == 'Zszedł'].sort_values(sort_c)
    used_out = []

    for _, row_in in in_rows.iterrows():
        t_in = row_in.get(sort_c, 0)
        cands = out_rows[~out_rows.index.isin(used_out)].copy()
        cands['diff'] = (cands.get(sort_c, 999) - t_in).abs()
        cands = cands[cands['diff'] <= 5].sort_values('diff')

        if not cands.empty:
            best = cands.iloc[0]
            map_in_to_out[row_in['Zawodnik_Clean']] = best['Zawodnik_Clean']
            map_out_to_in[best['Zawodnik_Clean']] = row_in['Zawodnik_Clean']
            used_out.append(best.name)

    def render_row(row, is_sub=False):
        c1, c2, c3 = st.columns([1, 4, 3])
        mins = int(row.get('Minuty', 0))
        entry = int(row.get('Minuta_Zmiany_Real', 0)) if is_sub else 0
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
        if r > 0 or status in ['Czerwona kartka', 'Czerwona']: evs.append("🟥")

        if is_sub:
            rep = map_in_to_out.get(name)
            txt = f"za: {rep}" if rep else "Wejście"
            evs.append(f"<small style='color:#28a745'>⬆️ {txt}</small>")
        elif status == 'Zszedł':
            rep = map_out_to_in.get(name)
            txt = f"zm: {rep}" if rep else "Zejście"
            out_min = int(row.get('Minuta_Zmiany_Real', 0))
            t_info = f"({out_min}')" if out_min > 0 else ""
            evs.append(f"<small style='color:#dc3545'>⬇️ {txt} {t_info}</small>")
        elif status in ['Czerwona kartka', 'Czerwona']:
            out_min = int(row.get('Minuta_Zmiany_Real', 0))
            if out_min == 0 and mins > 0: out_min = mins
            t_info = f"({out_min}')" if out_min > 0 else ""
            evs.append(f"<small style='color:#dc3545'>🟥 Zejście {t_info}</small>")

        with c3:
            if evs: st.markdown(" ".join(evs), unsafe_allow_html=True)

    starters = squad_df[(squad_df['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka', 'Czerwona'])) & (
            squad_df['Status'] != 'Wszedł')].sort_values('File_Order')
    subs = squad_df[squad_df['Status'] == 'Wszedł'].sort_values(
        'Minuta_Zmiany_Real' if 'Minuta_Zmiany_Real' in squad_df.columns else 'Wejście')
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
        if any(x in part.lower() for x in ['(s)', 's.', 'sam.']):
            icon = "🔴"
            is_own = True
        elif any(x in part.lower() for x in ['(k)', 'k.', 'karny']):
            icon = "⚽🥅"

        clean_name_candidate = re.sub(r'\(.*?\)', '', part)
        clean_name_candidate = re.sub(r'\d+', '', clean_name_candidate)
        clean_name_candidate = clean_name_candidate.replace("s.", "").replace("k.", "").replace("'", "").strip()

        has_letters = bool(re.search(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{2,}', clean_name_candidate))
        display_text = part
        link_name = ""

        if has_letters:
            last_valid_name = clean_name_candidate
            link_name = clean_name_candidate
            display_text = f"{icon} {part}"
        else:
            if last_valid_name:
                link_name = last_valid_name
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
    if not isinstance(scorers_str, str) or pd.isna(scorers_str) or scorers_str.strip() in ['-', '']:
        return "<span style='color: gray; font-style: italic;'>Brak bramek / Brak danych</span>"
    parts = scorers_str.split(',')
    html_parts = []
    for part in parts:
        part = part.strip()
        if not part: continue
        icon = "⚽"
        style = ""
        suffix = ""
        if any(x in part.lower() for x in ['(s)', 's.', 'sam.']):
            icon = "🔴"
            suffix = " (sam.)"
            part = re.sub(r'\(s\)|s\.|sam\.', '', part, flags=re.IGNORECASE).strip()
            style = "color: #dc3545;"
        elif any(x in part.lower() for x in ['(k)', 'k.', 'karny']):
            icon = "⚽🥅"
            part = re.sub(r'\(k\)|k\.|karny', '', part, flags=re.IGNORECASE).strip()
            style = "font-weight: bold; color: #28a745;"
        html_parts.append(f"<span style='{style}'>{icon} {part}{suffix}</span>")
    return " | ".join(html_parts)


def get_minutes_map(scorers_str):
    if not isinstance(scorers_str, str) or pd.isna(scorers_str): return {}
    mapping = {}
    parts = scorers_str.split(',')
    last_valid_name = None

    for part in parts:
        part = part.strip()
        if not part: continue
        is_pen = any(x in part.lower() for x in ['(k)', 'k.', 'karny'])
        is_own = any(x in part.lower() for x in ['(s)', 's.', 'sam.'])
        mins_match = re.search(r'(\d+)', part)
        minutes_txt = mins_match.group(1) if mins_match else ""

        name_candidate = re.sub(r'\d+', '', part)
        name_candidate = re.sub(r'[\(\)]', '', name_candidate)
        name_candidate = re.sub(r'(k\.|s\.|sam\.|karny)', '', name_candidate, flags=re.IGNORECASE).strip()
        name_candidate = name_candidate.replace("'", "").strip()

        has_letters = bool(re.search(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{2,}', name_candidate))
        final_key_name = None

        if has_letters:
            last_valid_name = name_candidate
            final_key_name = name_candidate
        elif last_valid_name:
            final_key_name = last_valid_name

        if not final_key_name: continue

        final_note = ""
        if minutes_txt: final_note = f"{minutes_txt}'"
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
    if pd.isna(birth_date) or pd.isna(event_date): return ""
    try:
        b = pd.to_datetime(birth_date).date()
        e = pd.to_datetime(event_date).date()
        years = e.year - b.year
        if (e.month, e.day) < (b.month, b.day): years -= 1
        if (e.month, e.day) < (b.month, b.day):
            last_bday = datetime.date(e.year - 1, b.month, b.day)
        else:
            last_bday = datetime.date(e.year, b.month, b.day)
        delta = e - last_bday
        days = delta.days
        return f"({years} lat, {days // 30} mies., {days % 30} dni)"
    except:
        return ""


def get_player_record_badges(player_name, df_w=None, df_p=None):
    badges = []
    try:
        if df_w is None: df_w = load_details("wystepy.csv")
        if df_p is None: df_p = load_data("pilkarze.csv")

        p_data = df_w[df_w['Zawodnik_Clean'] == player_name].copy()
        if p_data.empty: return []

        matches = len(p_data)
        goals = p_data['Gole'].sum()
        reds = p_data['Czerwone'].sum() + len(p_data[p_data['Status'] == 'Czerwona kartka'])
        yellows = p_data['Żółte'].sum()

        if matches >= 100:
            badges.append({"icon": "💯", "text": f"Klub 100 ({matches} spotkań)", "color": "#d63031"})
        if matches >= 30 and reds == 0 and yellows < 5:
            badges.append({"icon": "⚖️", "text": "Prawdziwy Dżentelmen (Fair Play)", "color": "#16a085"})
        if reds >= 2:
            badges.append({"icon": "🟥", "text": f"Bad Boy ({int(reds)} cz. kartki)", "color": "#e74c3c"})
        bench_goals = p_data[p_data['Status'] == 'Wszedł']['Gole'].sum()
        if bench_goals >= 3:
            badges.append({"icon": "🃏", "text": f"Super Joker ({int(bench_goals)} goli z ławki)", "color": "#e67e22"})
        if any(p_data['Gole'] >= 3):
            cnt = len(p_data[p_data['Gole'] >= 3])
            badges.append({"icon": "🎩", "text": f"Hat-trick Hero ({cnt}x)", "color": "#2ecc71"})
        clean_sheets = 0
        for _, r in p_data.iterrows():
            if r['Minuty'] >= 45 and '0' in str(r['Wynik']) and (
                    '0' in str(r['Wynik']).split('-')[0] or '0' in str(r['Wynik']).split('-')[1]):
                clean_sheets += 1
        if clean_sheets >= 15:
            badges.append({"icon": "🧱", "text": f"Murarz ({clean_sheets} czystych kont)", "color": "#2c3e50"})
        if 'Sezon' in p_data.columns:
            seasons = p_data['Sezon'].unique()
            if any(s in ['2010/2011', '2010/11'] for s in seasons):
                badges.append({"icon": "🚀", "text": "Awans do Ekstraklasy 2011", "color": "#f1c40f"})
            if any(s in ['2019/2020', '2019/20'] for s in seasons):
                badges.append({"icon": "🚀", "text": "Awans do Ekstraklasy 2020", "color": "#f1c40f"})
    except:
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

menu_options = [
    "Kalendarz",
    "Aktualny Sezon (25/26)",
    "Składy Historyczne",
    "Centrum Zawodników",
    "Centrum Meczowe",
    "🏆 Rekordy & TOP",
    "Trenerzy",
    "🎮 Zgadnij Skład"  # <--- DODAJ TĘ LINIJKĘ
]

opcja = st.sidebar.radio("Moduł:", menu_options)

# ==========================================
# GŁÓWNA LOGIKA MODUŁÓW (ROUTING)
# ==========================================

if opcja == "Kalendarz":
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

    # 4. GŁÓWNY WIDOK KALENDARZA
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


        # --- NOWA FUNKCJA PARSUJĄCA POLSKIE DATY ---
        def parse_pl_date(date_str):
            if pd.isna(date_str): return pd.NaT
            s = str(date_str).strip().lower()

            # Usunięcie dnia tygodnia (np. "sobota, ")
            if ',' in s:
                s = s.split(',', 1)[1].strip()

            months_map = {
                'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
                'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
                'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12'
            }

            for pl, digit in months_map.items():
                if pl in s:
                    s = s.replace(pl, digit)
                    break

            # Ustandaryzowanie do formatu d.m.Y
            s = re.sub(r'\s+', '.', s).strip()

            for fmt in ['%d.%m.%Y', '%d %m %Y', '%Y-%m-%d']:
                try:
                    return pd.to_datetime(s, format=fmt)
                except:
                    continue
            try:
                return pd.to_datetime(s)
            except:
                return pd.NaT


        # --- ALERT DNIA MECZOWEGO ---
        match_today_alert = None
        if df_m is not None:
            col_date_m = next((c for c in df_m.columns if 'data' in c and 'sort' not in c), None)
            if col_date_m:
                # Zamiana standardowego to_datetime na nową funkcję
                df_m['dt_obj'] = df_m[col_date_m].apply(parse_pl_date)

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
    st.header("📊 Kadra i Statystyki 2025/2026")
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do kadry"): st.session_state['cm_selected_player'] = None; st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])
    else:
        df = load_data("25_26.csv")
        if df is not None:
            if 'status' in df.columns:
                df['is_youth'] = df['status'].astype(str).str.contains(r'\(M\)', case=False, regex=True)
                df.loc[df['is_youth'], 'imię i nazwisko'] = "Ⓜ️ " + df.loc[df['is_youth'], 'imię i nazwisko']
            else:
                df['is_youth'] = False

            numeric_cols = [
                'mecze', 'minuty', 'gole', 'asysty', 'żółte kartki', 'czerwone kartki',
                'kanadyjka', 'gole samobójcze', 'asysta 2. stopnia', 'sprokurowany karny',
                'wywalczony karny', 'karny', 'niestrzelony karny', 'główka', 'lewa', 'prawa',
                'czyste konta', 'obronione karne'
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

            df = prepare_flags(df)
            if 'Flaga' in df.columns:
                df['Flaga'] = df['Flaga'].fillna("https://upload.wikimedia.org/wikipedia/commons/c/ca/1x1.png")

            total_players = len(df)
            total_goals = df['gole'].sum() if 'gole' in df.columns else 0

            top_scorer_name, top_scorer_goals = "-", 0
            if 'gole' in df.columns and total_goals > 0:
                top_row = df.loc[df['gole'].idxmax()]
                top_scorer_name = str(top_row['imię i nazwisko']).replace("Ⓜ️ ", "")
                top_scorer_goals = top_row['gole']

            top_assist_name, top_assist_val = "-", 0
            if 'asysty' in df.columns and df['asysty'].sum() > 0:
                ast_row = df.loc[df['asysty'].idxmax()]
                top_assist_name = str(ast_row['imię i nazwisko']).replace("Ⓜ️ ", "")
                top_assist_val = ast_row['asysty']

            most_mins_name, most_mins_val = "-", 0
            if 'minuty' in df.columns and df['minuty'].sum() > 0:
                min_row = df.loc[df['minuty'].idxmax()]
                most_mins_name = str(min_row['imię i nazwisko']).replace("Ⓜ️ ", "")
                most_mins_val = min_row['minuty']

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Wielkość Kadry", total_players)
            m2.metric("Zdobyte Gole", total_goals)
            m3.metric("Król Strzelców", f"{top_scorer_name}", f"{top_scorer_goals} ⚽" if top_scorer_goals > 0 else None)
            m4.metric("Król Asyst", f"{top_assist_name}", f"{top_assist_val} 🅰️" if top_assist_val > 0 else None)
            m5.metric("Najwięcej Minut", f"{most_mins_name}", f"{most_mins_val}'" if most_mins_val > 0 else None)
            st.divider()

            tab_kadra, tab_wizualizacje = st.tabs(["📝 Zespół", "📈 Wizualizacje szczegółowe"])

            with tab_kadra:
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                search_q = c1.text_input("🔍 Szukaj:", placeholder="Nazwisko...")
                view_mode = c2.selectbox("Kategoria statystyk:", [
                    "Podstawowe (Mecze, Gole, Asysty)",
                    "Ofensywa (Typy goli, karne, asysty 2.st)",
                    "Kary i Defensywa (Kartki, karne, czyste konta)"
                ])
                sort_by = c3.selectbox("Sortuj:", ["Nr", "Mecze", "Gole", "Asysty", "Kanadyjka", "Minuty", "Kartki",
                                                   "Czyste konta"])
                show_only_youth = c4.checkbox("Tylko Młodzieżowcy")

                df_view = df.copy()
                if show_only_youth: df_view = df_view[df_view['is_youth']]
                if search_q: df_view = df_view[
                    df_view.astype(str).apply(lambda x: x.str.contains(search_q, case=False)).any(axis=1)]

                s_col_map = {
                    'Nr': 'numer', 'Mecze': 'mecze', 'Gole': 'gole', 'Asysty': 'asysty',
                    'Kanadyjka': 'kanadyjka', 'Minuty': 'minuty', 'Kartki': 'żółte kartki',
                    'Czyste konta': 'czyste konta'
                }
                s_col = s_col_map.get(sort_by, 'numer')
                if s_col in df_view.columns:
                    df_view = df_view.sort_values(s_col, ascending=(s_col == 'numer'))

                col_config = {
                    "Flaga": st.column_config.ImageColumn("Kraj", width="small"),
                    "mecze": st.column_config.ProgressColumn("Mecze", format="%d", min_value=0,
                                                             max_value=int(df['mecze'].max() or 1)),
                    "gole": st.column_config.NumberColumn("Gole", format="%d ⚽"),
                    "asysty": st.column_config.NumberColumn("Asysty", format="%d 🅰️"),
                    "kanadyjka": st.column_config.NumberColumn("Kanadyjka", format="%d 🎯"),
                    "minuty": st.column_config.NumberColumn("Minuty", format="%d'"),
                    "żółte kartki": st.column_config.NumberColumn("Żółte", format="%d 🟨"),
                    "czerwone kartki": st.column_config.NumberColumn("Czerwone", format="%d 🟥"),
                    "czyste konta": st.column_config.NumberColumn("Czyste Konta", format="%d 🧤"),
                    "obronione karne": st.column_config.NumberColumn("Obronione Karne", format="%d 🚫"),
                    "karny": st.column_config.NumberColumn("Gole z Karnego", format="%d 🥅"),
                    "niestrzelony karny": st.column_config.NumberColumn("Niestrzelone Karne", format="%d ❌"),
                    "wywalczony karny": st.column_config.NumberColumn("Wywalczone Karne", format="%d 🎯"),
                    "sprokurowany karny": st.column_config.NumberColumn("Sprokurowane Karne", format="%d ⚠️"),
                    "główka": st.column_config.NumberColumn("Główka", format="%d 👤"),
                    "lewa": st.column_config.NumberColumn("Lewa noga", format="%d 🦶"),
                    "prawa": st.column_config.NumberColumn("Prawa noga", format="%d 🦶"),
                    "asysta 2. stopnia": st.column_config.NumberColumn("Asysta 2. st.", format="%d 🥈"),
                    "gole samobójcze": st.column_config.NumberColumn("Samobóje", format="%d 🔴")
                }


                def show_interactive_table(data_frame_raw, view_category, key_suffix=""):
                    data_frame = data_frame_raw.copy()
                    base_cols = ['numer', 'imię i nazwisko', 'Flaga', 'pozycja', 'mecze', 'minuty']

                    if view_category == "Podstawowe (Mecze, Gole, Asysty)":
                        stat_cols = ['gole', 'asysty', 'kanadyjka', 'żółte kartki', 'czerwone kartki']
                    elif view_category == "Ofensywa (Typy goli, karne, asysty 2.st)":
                        stat_cols = ['gole', 'lewa', 'prawa', 'główka', 'karny', 'niestrzelony karny',
                                     'wywalczony karny', 'asysty', 'asysta 2. stopnia']
                    else:
                        stat_cols = ['żółte kartki', 'czerwone kartki', 'gole samobójcze', 'sprokurowany karny',
                                     'czyste konta', 'obronione karne']

                    cols = base_cols + stat_cols
                    f_cols = [c for c in cols if c in data_frame.columns]
                    subset_to_highlight = [c for c in ['mecze', 'gole', 'asysty', 'kanadyjka', 'minuty', 'czyste konta']
                                           if c in f_cols]

                    event = st.dataframe(
                        data_frame[f_cols].style.highlight_max(
                            subset=subset_to_highlight,
                            color='#28a74530', axis=0
                        ),
                        use_container_width=True,
                        hide_index=True,
                        column_config=col_config,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"tab_kadra_{key_suffix}_{view_category}"
                    )
                    if event.selection.rows:
                        st.session_state['cm_selected_player'] = str(
                            data_frame.iloc[event.selection.rows[0]]['imię i nazwisko']).replace("Ⓜ️ ", "").strip()
                        st.rerun()


                st.markdown("ℹ️ *Kliknij w zawodnika, aby otworzyć jego pełny profil.*")
                pos_view = st.checkbox("Podziel tabelę na formacje (Bramkarze, Obrońcy, itd.)")

                if not pos_view:
                    show_interactive_table(df_view, view_mode, "main")
                else:
                    if 'pozycja' in df_view.columns:
                        # Inteligentne grupowanie pozycji
                        df_view['Grupa_Pozycji'] = "Inne"
                        df_view.loc[df_view['pozycja'].astype(str).str.contains('bram|gk', case=False,
                                                                                na=False), 'Grupa_Pozycji'] = 'Bramkarz'
                        df_view.loc[df_view['pozycja'].astype(str).str.contains('obr|def', case=False,
                                                                                na=False), 'Grupa_Pozycji'] = 'Obrońca'
                        df_view.loc[df_view['pozycja'].astype(str).str.contains('pom|mid', case=False,
                                                                                na=False), 'Grupa_Pozycji'] = 'Pomocnik'
                        df_view.loc[df_view['pozycja'].astype(str).str.contains('nap|ata|for', case=False,
                                                                                na=False), 'Grupa_Pozycji'] = 'Napastnik'

                        for pos in ["Bramkarz", "Obrońca", "Pomocnik", "Napastnik", "Inne"]:
                            sub = df_view[df_view['Grupa_Pozycji'] == pos]
                            if not sub.empty:
                                st.markdown(f"### {pos}")
                                show_interactive_table(sub, view_mode, f"pos_{pos}")

            with tab_wizualizacje:
                st.subheader("Wkład Zespołu i Styl Gry")
                if HAS_PLOTLY:
                    col_w1, col_w2 = st.columns(2)
                    with col_w1:
                        if 'kanadyjka' in df.columns and df['kanadyjka'].sum() > 0:
                            df_kan = df[df['kanadyjka'] > 0].sort_values('kanadyjka', ascending=True).tail(10)
                            fig_kan = go.Figure()
                            fig_kan.add_trace(go.Bar(
                                y=df_kan['imię i nazwisko'].str.replace("Ⓜ️ ", ""),
                                x=df_kan['gole'],
                                name='Gole',
                                orientation='h',
                                marker=dict(color='#2ecc71')
                            ))
                            fig_kan.add_trace(go.Bar(
                                y=df_kan['imię i nazwisko'].str.replace("Ⓜ️ ", ""),
                                x=df_kan['asysty'],
                                name='Asysty',
                                orientation='h',
                                marker=dict(color='#f1c40f')
                            ))
                            fig_kan.update_layout(title="TOP 10: Klasyfikacja Kanadyjska (G+A)", barmode='stack',
                                                  height=400)
                            st.plotly_chart(fig_kan, use_container_width=True)

                    with col_w2:
                        if 'minuty' in df.columns:
                            df_mins = df[df['minuty'] > 0].sort_values('minuty', ascending=True).tail(10)
                            fig_mins = go.Figure()
                            fig_mins.add_trace(go.Bar(
                                y=df_mins['imię i nazwisko'].str.replace("Ⓜ️ ", ""),
                                x=df_mins['minuty'],
                                name='Minuty na boisku',
                                orientation='h',
                                marker=dict(color='#3498db')
                            ))
                            fig_mins.update_layout(title="TOP 10: Najbardziej wyeksploatowani gracze", height=400)
                            st.plotly_chart(fig_mins, use_container_width=True)

                    g_lewa = df['lewa'].sum() if 'lewa' in df.columns else 0
                    g_prawa = df['prawa'].sum() if 'prawa' in df.columns else 0
                    g_glowa = df['główka'].sum() if 'główka' in df.columns else 0

                    if g_lewa + g_prawa + g_glowa > 0:
                        st.divider()
                        st.subheader("Jak strzelamy gole?")
                        fig_pie = px.pie(
                            names=['Lewa noga', 'Prawa noga', 'Główka'],
                            values=[g_lewa, g_prawa, g_glowa],
                            color_discrete_sequence=['#e74c3c', '#3498db', '#f1c40f']
                        )
                        fig_pie.update_layout(height=400)
                        st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.info("Brak zainstalowanej biblioteki Plotly do wyświetlania wykresów szczegółowych.")
        else:
            st.error("Brak pliku 25_26.csv. Upewnij się, że plik znajduje się w katalogu głównym.")

elif opcja == "Składy Historyczne":
    st.header("🗂️ Składy Historyczne")
    
    # ROUTER PROFILU ZAWODNIKA
    if st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do składu"): 
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])
        
    # GŁÓWNY WIDOK
    else:
        df_det = load_details("wystepy.csv")
        df_bio = load_data("pilkarze.csv")
        if 'filter_seasons' in globals(): 
            df_det = filter_seasons(df_det, 'Sezon')

        if df_det is None or df_bio is None:
            st.error("Brak plików danych (wystepy.csv / pilkarze.csv).")
        else:
            seasons = sorted(df_det['Sezon'].dropna().unique(), reverse=True)
            sel_season = st.selectbox("Wybierz Sezon:", seasons)
            show_only_youth = st.checkbox("Tylko Młodzieżowcy (rocznikowo)")

            # --- LOGIKA TRANSFERÓW (RÓŻNICA WZGLĘDEM POPRZEDNIEGO SEZONU) ---
            idx = seasons.index(sel_season)
            prev_season = seasons[idx + 1] if idx + 1 < len(seasons) else None

            season_data = df_det[df_det['Sezon'] == sel_season].copy()
            curr_players = set(season_data['Zawodnik_Clean'].unique())

            if prev_season:
                prev_data = df_det[df_det['Sezon'] == prev_season]
                prev_players = set(prev_data['Zawodnik_Clean'].unique())
                
                przyszli = curr_players - prev_players
                odeszli = prev_players - curr_players
                
                st.markdown(f"### 🔄 Zmiany w kadrze (względem sezonu {prev_season})")
                c_in, c_out = st.columns(2)
                with c_in:
                    txt_in = ", ".join(sorted(list(przyszli))) if przyszli else "Brak"
                    st.success(f"**🟢 Przyszli ({len(przyszli)}):** {txt_in}")
                with c_out:
                    txt_out = ", ".join(sorted(list(odeszli))) if odeszli else "Brak"
                    st.error(f"**🔴 Odeszli ({len(odeszli)}):** {txt_out}")
                st.divider()

            # --- PRZYGOTOWANIE TABELI SKŁADU ---
            agg = season_data.groupby('Zawodnik_Clean').agg(
                {'Minuty': 'sum', 'Mecz_Label': 'nunique', 'Gole': 'sum', 'Żółte': 'sum', 'Czerwone': 'sum'}
            ).reset_index()
            agg.rename(columns={'Mecz_Label': 'Mecze'}, inplace=True)

            df_bio_unique = df_bio.drop_duplicates(subset=['imię i nazwisko']).copy()
            df_bio_unique['join_key'] = df_bio_unique['imię i nazwisko'].astype(str).str.strip()
            df_bio_unique = prepare_flags(df_bio_unique)

            merged = pd.merge(agg, df_bio_unique, left_on='Zawodnik_Clean', right_on='join_key', how='left')
            merged['Zawodnik_Display'] = merged['Zawodnik_Clean']
            
            # --- LOGIKA MŁODZIEŻOWCA (Wiek + Narodowość) ---
            def get_youth_threshold(season_str):
                try:
                    s_year = int(str(season_str).split('/')[0].strip()[-4:])
                    if s_year >= 2024:
                        return s_year - 20  # 2025->2005, 2024->2004
                    else:
                        return s_year - 19  # 2023->2004, 2022->2003, 2021->2002 itd.
                except:
                    return 2000

            youth_year = get_youth_threshold(sel_season)
            
            col_b = next((c for c in merged.columns if c in ['data urodzenia', 'urodzony', 'data_ur']), None)
            if col_b:
                def check_youth_age(date_val):
                    if pd.isna(date_val) or str(date_val).strip() in ['-', '', 'nan']: return False
                    try:
                        dt = pd.to_datetime(date_val, dayfirst=True)
                        return dt.year >= youth_year
                    except:
                        return False
                
                merged['is_youth_age'] = merged[col_b].apply(check_youth_age)
                
                def apply_youth_icon(row):
                    if not row['is_youth_age']:
                        return row['Zawodnik_Clean']
                    
                    nat = str(row.get('Narodowość', '')).lower()
                    if 'polska' in nat or 'pol' in nat:
                        return "Ⓜ️ " + row['Zawodnik_Clean']
                    else:
                        return "🌍Ⓜ️ " + row['Zawodnik_Clean']
                        
                merged['Zawodnik_Display'] = merged.apply(apply_youth_icon, axis=1)
                merged['is_youth'] = merged['is_youth_age'] # Używane do checkboxa (pokazuje obie grupy)
            else:
                merged['is_youth'] = False

            # Filtr jeśli zaznaczono checkbox
            if show_only_youth:
                merged = merged[merged['is_youth']]
                if merged.empty:
                    st.warning(f"Brak młodzieżowców (rocznik {youth_year} i młodsi) w danych dla sezonu {sel_season}.")

            # Sortowanie i dodanie kolumny Lp.
            merged = merged.sort_values(by=['Mecze', 'Minuty'], ascending=[False, False]).reset_index(drop=True)
            merged.insert(0, 'Lp.', range(1, len(merged) + 1))

            st.markdown(f"### 👥 Występy w sezonie {sel_season}")
            if not show_only_youth:
                st.caption(f"ℹ️ Znak Ⓜ️ oznacza polskiego młodzieżowca (ur. w {youth_year} r. i młodsi), a 🌍Ⓜ️ zagranicznego gracza w tym samym wieku.")
            
            # Interaktywna tabela z flagami
            event_hist = st.dataframe(
                merged[['Lp.', 'Flaga', 'Zawodnik_Display', 'pozycja', 'Mecze', 'Minuty', 'Gole', 'Żółte', 'Czerwone']], 
                use_container_width=True, 
                hide_index=True,
                on_select="rerun", 
                selection_mode="single-row",
                key=f"hist_squad_{sel_season}",
                column_config={
                    "Lp.": st.column_config.NumberColumn("Lp.", format="%d"),
                    "Flaga": st.column_config.ImageColumn("Kraj", width="small"),
                    "Zawodnik_Display": st.column_config.TextColumn("Imię i nazwisko"),
                    "pozycja": st.column_config.TextColumn("Pozycja"),
                    "Mecze": st.column_config.ProgressColumn("Mecze", format="%d", min_value=0, max_value=int(merged['Mecze'].max() or 1)),
                    "Minuty": st.column_config.NumberColumn("Minuty", format="%d'"),
                    "Gole": st.column_config.NumberColumn("Gole", format="%d ⚽"),
                    "Żółte": st.column_config.NumberColumn("Żółte", format="%d 🟨"),
                    "Czerwone": st.column_config.NumberColumn("Czerwone", format="%d 🟥")
                }
            )
            
            # Obsługa kliknięcia (router)
            if event_hist.selection.rows:
                st.session_state['cm_selected_player'] = merged.iloc[event_hist.selection.rows[0]]['Zawodnik_Clean']
                st.rerun()

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

        # --- ZAKŁADKI ---
        tab1, tab2, tab3, tab4 = st.tabs(["📝 Raporty", "🆚 Analiza Rywala", "📊 Statystyki", "🗺️ Mapa Wyjazdów"])

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
                if 'Data_Sort' in unique_matches.columns:
                    unique_matches = unique_matches.sort_values('Data_Sort', ascending=False)


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
                                st.warning("Brak szczegółów składu dla tego meczu.")
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
                seq = []  # Do badana passy
                for _, r in df_bilans.iterrows():
                    res = parse_result(r.get('wynik'))
                    if res:
                        gf += res[0];
                        ga += res[1]
                        if res[0] > res[1]:
                            w += 1;
                            seq.append('W')
                        elif res[0] == res[1]:
                            d += 1;
                            seq.append('D')
                        else:
                            l += 1;
                            seq.append('L')
                    else:
                        seq.append(None)

                tot = w + d + l
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mecze", tot)
                c2.metric("Bilans", f"{w}-{d}-{l}")
                c3.metric("Bramki", f"{gf}:{ga}", delta=gf - ga)
                c4.metric("Skuteczność", f"{(w / tot * 100):.1f}%" if tot else "0%")
                st.divider()

                # --- [2] FREKWENCJA ---
                if "Wyjazd" not in f_mode:
                    st.markdown("### 🏟️ Statystyki Frekwencji (Mecze Domowe)")
                    col_att = next(
                        (c for c in df_stats.columns if c.lower() in ['widzów', 'frekwencja', 'widzow', 'kibiców']),
                        None)

                    if col_att:
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
                                fm1.metric("Średnia Frekwencja", f"{int(avg_total):,}".replace(",", " "))

                                if pd.notna(max_total.get('dt_obj')):
                                    rekord_data = max_total['dt_obj'].strftime('%d.%m.%Y')
                                else:
                                    rekord_data = "?"

                                fm2.metric("Rekord Frekwencji", f"{int(max_total['Widzów_Num']):,}".replace(",", " "),
                                           f"{max_total.get('rywal', '')} ({rekord_data})")
                                st.write("")

                                df_home['Miesiąc_Idx'] = df_home['dt_obj'].dt.month
                                pl_months = {1: 'Styczeń', 2: 'Luty', 3: 'Marzec', 4: 'Kwiecień', 5: 'Maj',
                                             6: 'Czerwiec', 7: 'Lipiec', 8: 'Sierpień', 9: 'Wrzesień',
                                             10: 'Październik', 11: 'Listopad', 12: 'Grudzień'}

                                freq_stats = []
                                sorted_months = sorted(df_home['Miesiąc_Idx'].unique())

                                for m_idx in sorted_months:
                                    sub = df_home[df_home['Miesiąc_Idx'] == m_idx]
                                    top3 = sub.nlargest(3, 'Widzów_Num')
                                    emojis = ['🥇', '🥈', '🥉']
                                    top3_txt = []
                                    for i, (idx, r) in enumerate(top3.iterrows()):
                                        ico = emojis[i] if i < 3 else ""
                                        top3_txt.append(f"{ico} 👥 {r['Widzów_Num']} ({r.get('rywal', '?')})")

                                    freq_stats.append({
                                        "Miesiąc_Idx": m_idx,
                                        "Miesiąc": pl_months.get(m_idx, str(m_idx)),
                                        "Mecze": len(sub),
                                        "Średnia": sub['Widzów_Num'].mean(),
                                        "TOP 3 Frekwencji": ", ".join(top3_txt)
                                    })

                                df_freq = pd.DataFrame(freq_stats)
                                st.bar_chart(df_freq.set_index("Miesiąc")['Średnia'])
                                st.dataframe(
                                    df_freq.drop(columns=['Miesiąc_Idx']),
                                    use_container_width=True, hide_index=True,
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

                # --- [3] SERIE ---
                st.markdown("### 🔥 Serie i Passy")


                def get_streak_with_breaker(df_source, sequence, target_types):
                    max_streak = []
                    current_streak = []
                    temp_df = df_source.reset_index(drop=True)
                    final_breaker = None

                    for i, code in enumerate(sequence):
                        if code in target_types:
                            current_streak.append(temp_df.iloc[i])
                        else:
                            if len(current_streak) > len(max_streak):
                                max_streak = current_streak
                                if i < len(temp_df):
                                    final_breaker = temp_df.iloc[i]
                            current_streak = []

                    if len(current_streak) > len(max_streak):
                        max_streak = current_streak
                        final_breaker = None

                    return (pd.DataFrame(max_streak) if max_streak else pd.DataFrame(), final_breaker)


                s_win, b_win = get_streak_with_breaker(df_bilans, seq, ['W'])
                s_no_loss, b_no_loss = get_streak_with_breaker(df_bilans, seq, ['W', 'D'])
                s_loss, b_loss = get_streak_with_breaker(df_bilans, seq, ['L'])
                s_no_win, b_no_win = get_streak_with_breaker(df_bilans, seq, ['L', 'D'])

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

                            if breaker is not None:
                                b_res = str(breaker.get('wynik', ''))
                                b_opp = str(breaker.get('rywal', ''))
                                try:
                                    b_date = pd.to_datetime(breaker['dt_obj']).strftime('%d.%m.%Y') if pd.notna(
                                        breaker.get('dt_obj')) else "Nieznana data"
                                except:
                                    b_date = "Nieznana data"

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

        # --- TAB 4: MAPA WYJAZDÓW ---
        with tab4:
            st.subheader("🗺️ Mapa Historycznych Wyjazdów")
            if df_m is not None:
                away_matches = df_m[
                    ~df_m['dom'].astype(str).str.lower().isin(['1', 'true', 'dom', 'tak', 'u siebie'])].copy()


                def detect_city(row):
                    txt = (str(row.get('miejsce rozgrywania', '')) + " " + str(row.get('rywal', ''))).lower()
                    for city_key in CITY_COORDS.keys():
                        if city_key.lower() in txt: return city_key
                    return None


                away_matches['Detected_City'] = away_matches.apply(detect_city, axis=1)
                map_data = away_matches.dropna(subset=['Detected_City'])

                if not map_data.empty:
                    c_map, c_legend = st.columns([3, 1])
                    with c_legend:
                        st.info("Kliknij kropkę na mapie, a potem wybierz mecz z tabeli poniżej, żeby zobaczyć raport!")
                        st.markdown("**Legenda:**\n🟢 < 3 mecze\n🟠 3-10 meczów\n🔴 > 10 meczów")

                    with c_map:
                        try:
                            m = folium.Map(location=[52.0, 19.14], zoom_start=6, tiles="CartoDB dark_matter")
                            stats = map_data.groupby('Detected_City').size().reset_index(name='count')

                            for _, r in stats.iterrows():
                                city = r['Detected_City']
                                count = r['count']
                                coords = CITY_COORDS.get(city)
                                color = "#e74c3c" if count > 10 else "#f39c12" if count >= 3 else "#2ecc71"

                                if coords:
                                    folium.CircleMarker(
                                        location=coords, radius=5 + (count * 0.4), color=color,
                                        fill=True, fill_color=color, fill_opacity=0.7,
                                        popup=city, tooltip=f"{city.title()} ({count})"
                                    ).add_to(m)

                            output = st_folium(m, width="100%", height=500)

                            clicked_city = None
                            if output.get("last_object_clicked_popup"):
                                clicked_city = output["last_object_clicked_popup"]

                            if clicked_city:
                                st.divider()
                                st.markdown(f"### 🏟️ Mecze w: {clicked_city.title()}")
                                city_matches = map_data[map_data['Detected_City'] == clicked_city].sort_values('dt_obj',
                                                                                                               ascending=False).copy()
                                city_matches['Data'] = city_matches['dt_obj'].dt.strftime('%d.%m.%Y')

                                sel_row = st.dataframe(
                                    city_matches[['Data', 'sezon', 'rywal', 'wynik']],
                                    hide_index=True, use_container_width=True, on_select="rerun",
                                    selection_mode="single-row"
                                )

                                if sel_row.selection.rows:
                                    idx = sel_row.selection.rows[0]
                                    sel_date = city_matches.iloc[idx]['dt_obj'].date()
                                    st.markdown("---")
                                    st.subheader("📑 Raport meczowy")

                                    if df_det_sq is not None and 'Data_Sort' in df_det_sq.columns:
                                        m_sq = df_det_sq[df_det_sq['Data_Sort'].dt.date == sel_date]
                                        if not m_sq.empty:
                                            lbl = m_sq.iloc[0]['Mecz_Label']
                                            render_match_report_logic(lbl, m_sq.sort_values('File_Order'))
                                        else:
                                            st.warning("Brak raportu (składu) dla tego meczu.")
                        except Exception as e:
                            st.error(f"Błąd ładowania mapy: {e}")

elif opcja == "🏆 Rekordy & TOP":
    st.header("🏆 Sala Chwały i Rekordy TSP")

    # [0] ROUTER (Obsługuje powroty i wyświetlanie profilu gracza / meczu)
    if st.session_state.get('cm_selected_match'):
        if st.button("⬅️ Wróć do Rekordów", key="back_from_match_rec"):
            st.session_state['cm_selected_match'] = None
            st.rerun()
        st.divider()
        df_det_sq = load_details("wystepy.csv")
        m_label = st.session_state['cm_selected_match']
        match_squad = df_det_sq[df_det_sq['Mecz_Label'] == m_label].copy().sort_values('File_Order')
        render_match_report_logic(m_label, match_squad)

    elif st.session_state.get('cm_selected_player'):
        if st.button("⬅️ Wróć do Rekordów", key="back_from_player_rec"):
            st.session_state['cm_selected_player'] = None
            st.rerun()
        st.divider()
        render_player_profile(st.session_state['cm_selected_player'])

    # [1] GŁÓWNY WIDOK
    else:
        def robust_date_parse(val):
            if pd.isna(val) or str(val).strip() in ['', '-', 'nan']: return None
            s = str(val).strip().lower()
            if ',' in s: s = s.split(',', 1)[1].strip()
            if ':' in s and len(s.split()) > 1: s = " ".join(s.split()[:-1])

            months_map = {
                'stycznia': '01', 'lutego': '02', 'marca': '03', 'kwietnia': '04',
                'maja': '05', 'czerwca': '06', 'lipca': '07', 'sierpnia': '08',
                'września': '09', 'października': '10', 'listopada': '11', 'grudnia': '12'
            }
            for pl, digit in months_map.items():
                if pl in s:
                    s = s.replace(pl, digit)
                    break

            s = re.sub(r'\s+', '.', s).strip()
            for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y.%m.%d', '%d %m %Y']:
                try:
                    return pd.to_datetime(s, format=fmt).date()
                except:
                    continue
            try:
                return pd.to_datetime(s).date()
            except:
                return None


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

            col_map = {
                'kraj': 'Narodowość', 'Kraj': 'Narodowość',
                'narodowość': 'Narodowość', 'narodowosc': 'Narodowość',
                'Pozycja': 'pozycja', 'imię i nazwisko': 'nazwisko'
            }
            df_p.rename(columns={k: v for k, v in col_map.items() if k in df_p.columns}, inplace=True)
            if 'nazwisko' in df_p.columns: df_p.rename(columns={'nazwisko': 'imię i nazwisko'}, inplace=True)

            if 'Narodowość' not in df_p.columns: df_p['Narodowość'] = '-'
            if 'pozycja' not in df_p.columns: df_p['pozycja'] = '-'

            df_p['join_key'] = df_p['imię i nazwisko'].astype(str).str.lower().str.strip()

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

            full_agg = pd.merge(agg, df_p_dates[['join_key', 'Narodowość', 'pozycja', 'Lata gry', 'Manual_Matches']],
                                on='join_key', how='outer')

            full_agg['Mecze_Liczba'] = full_agg['Mecze_Liczba'].fillna(0)
            full_agg['Manual_Matches'] = full_agg['Manual_Matches'].fillna(0)
            full_agg['Total_Matches'] = full_agg[['Mecze_Liczba', 'Manual_Matches']].max(axis=1).astype(int)

            # --- E. LISTY ODZNAK ---
            list_club100 = full_agg[full_agg['Total_Matches'] >= 100]['Zawodnik_Clean'].tolist()
            list_veteran = full_agg[full_agg['Sezony_Liczba'] >= 5]['Zawodnik_Clean'].tolist()
            list_lungs = full_agg[full_agg['Min_Num'] > 5000]['Zawodnik_Clean'].tolist()
            list_badboy = full_agg[full_agg['R_Num'] >= 2]['Zawodnik_Clean'].tolist()
            list_gentleman = \
                full_agg[(full_agg['Total_Matches'] >= 30) & (full_agg['R_Num'] == 0) & (full_agg['Y_Num'] < 5)][
                    'Zawodnik_Clean'].tolist()

            full_agg['Narodowość_Str'] = full_agg['Narodowość'].fillna('').astype(str).str.lower().str.strip()
            mask_foreign = ((full_agg['Total_Matches'] >= 50) & (full_agg['Narodowość_Str'] != '') & (
                    full_agg['Narodowość_Str'] != '-') & (full_agg['Narodowość_Str'] != 'nan') & (
                                ~full_agg['Narodowość_Str'].str.contains('pol')))
            list_foreign = full_agg[mask_foreign]['Zawodnik_Clean'].tolist()

            promo_years = ['2010/2011', '2010/11', '2019/2020', '2019/20']
            list_promo = df_w[df_w['Sezon'].isin(promo_years)]['Zawodnik_Clean'].unique().tolist()
            list_hattrick = df_w[df_w['Gole_Num'] >= 3]['Zawodnik_Clean'].unique().tolist()

            subs_only = df_w[df_w['Status'] == 'Wszedł'].copy()
            joker_stats = subs_only.groupby('Zawodnik_Clean')['Gole_Num'].sum()
            list_joker = joker_stats[joker_stats >= 5].index.tolist()

            sub_c = df_w[df_w['Status'] == 'Wszedł'].groupby('join_key').size()
            list_taskmaster = df_w[df_w['join_key'].isin(sub_c[sub_c >= 20].index)]['Zawodnik_Clean'].unique().tolist()

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

                        event_b = st.dataframe(p_df[['Zawodnik', 'Lata gry']], hide_index=True,
                                               use_container_width=True,
                                               on_select="rerun", selection_mode="single-row", key=f"badge_{title}")
                        if event_b.selection.rows:
                            st.session_state['cm_selected_player'] = p_df.iloc[event_b.selection.rows[0]]['Zawodnik']
                            st.rerun()
                    else:
                        st.caption("Brak zawodników.")


            with tab_badges:
                st.subheader("🏅 Sala Chwały - Odznaki Specjalne")
                c1, c2, c3 = st.columns(3)
                with c1:
                    show_badge_group("Klub 100", list_club100, "💯", "Min. 100 oficjalnych meczów.")
                    show_badge_group("Weteran", list_veteran, "🦅", "Min. 5 różnych sezonów w klubie.")
                    show_badge_group("Awans", list_promo, "🚀", "Członkowie drużyn awansujących (2011, 2020).")
                    show_badge_group("Zagraniczny Filar", list_foreign, "🌍", "Obcokrajowcy z min. 50 meczami.")
                with c2:
                    show_badge_group("Wielki Mur", list_wall, "🧱", "Bramkarze: 20+ czystych kont.")
                    show_badge_group("Pewny Punkt", list_sure, "🧤", "Bramkarze: 10+ czystych kont.")
                    show_badge_group("Hat-trick Hero", list_hattrick, "🎩", "Strzelcy 3 goli w jednym meczu.")
                    show_badge_group("Super Joker", list_joker, "🃏", "Rezerwowi z min. 5 golami po wejściu.")
                with c3:
                    show_badge_group("Dżentelmen", list_gentleman, "⚖️",
                                     "Min. 50 meczów bez czerwonej kartki i poniżej 5 żółtych.")
                    show_badge_group("Bad Boy", list_badboy, "🟥", "Min. 2 czerwone kartki.")
                    show_badge_group("Żelazne Płuca", list_lungs, "🚂", "Ponad 5000 minut na boisku.")
                    show_badge_group("Zadaniowiec", list_taskmaster, "🔄", "Min. 20 wejść z ławki.")


            def get_medals(df_in):
                df_x = df_in.copy().reset_index(drop=True)
                df_x.index += 1
                df_x.insert(0, 'Miejsce', df_x.index.map(
                    lambda x: f"🥇" if x == 1 else (f"🥈" if x == 2 else (f"🥉" if x == 3 else f"{x}."))))
                return df_x


            with tab1:
                st.subheader("👕 Najwięcej Występów")
                top_m = full_agg.sort_values('Mecze_Liczba', ascending=False).head(20)
                top_m_medals = get_medals(top_m)
                ev_t1 = st.dataframe(top_m_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Mecze_Liczba']],
                                     hide_index=True, use_container_width=True,
                                     column_config={
                                         "Mecze_Liczba": st.column_config.ProgressColumn("Mecze", format="%d")},
                                     on_select="rerun", selection_mode="single-row", key="tab1_top")

                if ev_t1.selection.rows:
                    st.session_state['cm_selected_player'] = top_m_medals.iloc[ev_t1.selection.rows[0]][
                        'Zawodnik_Clean']
                    st.rerun()

            with tab2:
                st.subheader("👶👴 Wiek Zawodników i Drużyn")

                # --- WIEK INDYWIDUALNY ---
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
                        young_medals = get_medals(young[young['Age_Days'] > 3650].sort_values('Age_Days').head(10))
                        ev_y = st.dataframe(
                            young_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Wiek_Txt', 'Data_Sort']],
                            hide_index=True, use_container_width=True,
                            column_config={"Data_Sort": st.column_config.DateColumn("Data")},
                            on_select="rerun", selection_mode="single-row", key="tab2_young")
                        if ev_y.selection.rows:
                            st.session_state['cm_selected_player'] = young_medals.iloc[ev_y.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

                    with c_o:
                        st.markdown("#### 👴 Najstarsi")
                        old = df_age_valid.loc[df_age_valid.groupby('join_key')['Age_Days'].idxmax()]
                        old_medals = get_medals(
                            old[old['Age_Days'] < 22000].sort_values('Age_Days', ascending=False).head(10))
                        ev_o = st.dataframe(
                            old_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Wiek_Txt', 'Data_Sort']],
                            hide_index=True, use_container_width=True,
                            column_config={"Data_Sort": st.column_config.DateColumn("Data")},
                            on_select="rerun", selection_mode="single-row", key="tab2_old")
                        if ev_o.selection.rows:
                            st.session_state['cm_selected_player'] = old_medals.iloc[ev_o.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

                # --- ŚREDNI WIEK DRUŻYNY ---
                st.divider()
                st.markdown("### 📊 Najmłodsze i Najstarsze Wyjściowe Jedenastki")

                starters_all = df_w[(df_w['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka'])) & (
                        df_w['Status'] != 'Wszedł')].copy()
                starters_all = pd.merge(starters_all, df_p_dates[['join_key', 'data urodzenia']], on='join_key',
                                        how='inner')
                starters_all['dt_ur'] = pd.to_datetime(starters_all['data urodzenia'], errors='coerce')
                starters_all['Data_Sort'] = pd.to_datetime(starters_all['Data_Sort'], errors='coerce')

                starters_all['Age_Years'] = (starters_all['Data_Sort'] - starters_all['dt_ur']).dt.days / 365.25
                starters_all = starters_all.dropna(subset=['Age_Years'])

                if not starters_all.empty:
                    team_age = starters_all.groupby('Mecz_Label').agg(
                        Avg_Age=('Age_Years', 'mean'),
                        Valid_Players=('Age_Years', 'count'),
                        Data_Sort=('Data_Sort', 'first'),
                        Sezon=('Sezon', 'first')
                    ).reset_index()

                    team_age = team_age[team_age['Valid_Players'] >= 8].copy()

                    if not team_age.empty:
                        team_age['Przeciwnik'] = team_age['Mecz_Label'].apply(
                            lambda x: x.split('|')[1].strip() if '|' in x else x)

                        col_y_team, col_o_team = st.columns(2)
                        with col_y_team:
                            st.markdown("#### 🍼 Najmłodsza XI")
                            youngest_xi = get_medals(team_age.sort_values('Avg_Age').head(10))
                            ev_yxi = st.dataframe(youngest_xi[['Miejsce', 'Sezon', 'Przeciwnik', 'Avg_Age']],
                                                  hide_index=True, use_container_width=True,
                                                  column_config={
                                                      "Avg_Age": st.column_config.NumberColumn("Śr. wieku",
                                                                                               format="%.2f lat")},
                                                  on_select="rerun", selection_mode="single-row", key="tab2_yxi")
                            if ev_yxi.selection.rows:
                                st.session_state['cm_selected_match'] = youngest_xi.iloc[ev_yxi.selection.rows[0]][
                                    'Mecz_Label']
                                st.rerun()

                        with col_o_team:
                            st.markdown("#### 🧓 Najstarsza XI")
                            oldest_xi = get_medals(team_age.sort_values('Avg_Age', ascending=False).head(10))
                            ev_oxi = st.dataframe(oldest_xi[['Miejsce', 'Sezon', 'Przeciwnik', 'Avg_Age']],
                                                  hide_index=True, use_container_width=True,
                                                  column_config={
                                                      "Avg_Age": st.column_config.NumberColumn("Śr. wieku",
                                                                                               format="%.2f lat")},
                                                  on_select="rerun", selection_mode="single-row", key="tab2_oxi")
                            if ev_oxi.selection.rows:
                                st.session_state['cm_selected_match'] = oldest_xi.iloc[ev_oxi.selection.rows[0]][
                                    'Mecz_Label']
                                st.rerun()
                    else:
                        st.info("Brak wystarczających danych z datami urodzenia do obliczenia średnich zespołu.")

            with tab3:
                st.subheader("⚽ Królowie Strzelców")
                top_g = full_agg[full_agg['Gole_Num'] > 0].sort_values('Gole_Num', ascending=False).head(20)
                top_g_medals = get_medals(top_g)
                ev_t3 = st.dataframe(top_g_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Gole_Num']],
                                     hide_index=True, use_container_width=True,
                                     column_config={"Gole_Num": st.column_config.NumberColumn("Gole", format="%d ⚽")},
                                     on_select="rerun", selection_mode="single-row", key="tab3_top")
                if ev_t3.selection.rows:
                    st.session_state['cm_selected_player'] = top_g_medals.iloc[ev_t3.selection.rows[0]][
                        'Zawodnik_Clean']
                    st.rerun()

            with tab4:
                c_hat, c_res = st.columns(2)
                with c_hat:
                    st.markdown("#### 🎩 Hat-tricki")
                    hats = df_w[df_w['Gole_Num'] >= 3].sort_values('Data_Sort', ascending=False)
                    if not hats.empty:
                        hats = pd.merge(hats, df_p_dates[['join_key', 'pozycja']], on='join_key', how='left')
                        ev_hats = st.dataframe(
                            hats[['Sezon', 'Data_Sort', 'pozycja', 'Zawodnik_Clean', 'Gole_Num', 'Przeciwnik']],
                            hide_index=True, use_container_width=True,
                            column_config={"Data_Sort": st.column_config.DateColumn("Data")},
                            on_select="rerun", selection_mode="single-row", key="tab4_hats")

                        if ev_hats.selection.rows:
                            st.session_state['cm_selected_match'] = hats.iloc[ev_hats.selection.rows[0]]['Mecz_Label']
                            st.rerun()
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

                        # Parsujemy daty dla df_m, żeby móc powiązać wynik z plikiem wystepy.csv
                        col_d = next((c for c in df_m.columns if c in ['data meczu', 'data', 'dt_obj']), None)
                        if col_d:
                            df_m['clean_date'] = df_m[col_d].apply(robust_date_parse)

                        top_wins = df_m[df_m['Diff'] > 0].sort_values('Diff', ascending=False).head(10)
                        top_wins_medals = get_medals(top_wins)

                        ev_wins = st.dataframe(top_wins_medals[['Miejsce', 'sezon', 'rywal', 'wynik']], hide_index=True,
                                               use_container_width=True, on_select="rerun", selection_mode="single-row",
                                               key="tab4_wins")

                        if ev_wins.selection.rows:
                            sel_idx = ev_wins.selection.rows[0]
                            sel_date = top_wins_medals.iloc[sel_idx].get('clean_date')
                            if pd.notna(sel_date):
                                found = df_w[df_w['Data_Sort'].dt.date == sel_date]
                                if not found.empty:
                                    st.session_state['cm_selected_match'] = found.iloc[0]['Mecz_Label']
                                    st.rerun()
                                else:
                                    st.warning("Brak raportu ze składem dla tego meczu.")

            with tab5:
                col_y, col_r = st.columns(2)
                with col_y:
                    st.markdown("#### 🟨 Najwięcej Żółtych (TOP 15)")
                    top_y = full_agg[full_agg['Y_Num'] > 0].sort_values('Y_Num', ascending=False).head(15)
                    top_y_medals = get_medals(top_y)
                    ev_y = st.dataframe(top_y_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Y_Num']],
                                 hide_index=True, use_container_width=True, column_config={
                            "Y_Num": st.column_config.ProgressColumn("Żółte", format="%d", max_value=int(top_y['Y_Num'].max()))},
                                 on_select="rerun", selection_mode="single-row", key="tab5_y")
                    if ev_y.selection.rows:
                        st.session_state['cm_selected_player'] = top_y_medals.iloc[ev_y.selection.rows[0]]['Zawodnik_Clean']
                        st.rerun()

                with col_r:
                    st.markdown("#### 🟥 Wszystkie Czerwone Kartki")
                    # Usunięto limit (.head(15)), wyświetlamy wszystkich!
                    top_r = full_agg[full_agg['R_Num'] > 0].sort_values('R_Num', ascending=False)
                    if not top_r.empty:
                        top_r_medals = get_medals(top_r)
                        ev_r = st.dataframe(top_r_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'R_Num']],
                                     hide_index=True, use_container_width=True,
                                     on_select="rerun", selection_mode="single-row", key="tab5_r")
                        if ev_r.selection.rows:
                            st.session_state['cm_selected_player'] = top_r_medals.iloc[ev_r.selection.rows[0]]['Zawodnik_Clean']
                            st.rerun()
                    else:
                        st.info("Brak czerwonych kartek w bazie.")

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
                        ev_cs = st.dataframe(
                            top_cs[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Czyste Konta']],
                            hide_index=True, use_container_width=True, column_config={
                                "Czyste Konta": st.column_config.ProgressColumn("CS", format="%d", max_value=int(
                                    df_gk_stats['Czyste Konta'].max()))},
                            on_select="rerun", selection_mode="single-row", key="tab6_cs")
                        if ev_cs.selection.rows:
                            st.session_state['cm_selected_player'] = top_cs.iloc[ev_cs.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

                    with c2:
                        st.markdown("#### 🛡️ Najmniej wpuszczonych/mecz (min. 10)")
                        best_avg = df_gk_stats[df_gk_stats['Mecze'] >= 10].sort_values('Średnia').head(10)
                        best_avg_medals = get_medals(best_avg)
                        ev_ba = st.dataframe(
                            best_avg_medals[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Średnia']],
                            hide_index=True, use_container_width=True,
                            column_config={"Średnia": st.column_config.NumberColumn("Śr.", format="%.2f")},
                            on_select="rerun", selection_mode="single-row", key="tab6_ba")
                        if ev_ba.selection.rows:
                            st.session_state['cm_selected_player'] = best_avg_medals.iloc[ev_ba.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

                    st.divider()
                    st.markdown("### ⚠️ Negatywne Rekordy")
                    c3, c4 = st.columns(2)
                    with c3:
                        st.markdown("#### ⚽ Najwięcej wpuszczonych goli")
                        top_conceded = get_medals(df_gk_stats.sort_values('Wpuszczone', ascending=False).head(10))
                        ev_tc = st.dataframe(
                            top_conceded[['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Wpuszczone', 'Mecze']],
                            hide_index=True, use_container_width=True,
                            column_config={"Wpuszczone": st.column_config.NumberColumn("Wpuszczone", format="%d ⚽")},
                            on_select="rerun", selection_mode="single-row", key="tab6_tc")
                        if ev_tc.selection.rows:
                            st.session_state['cm_selected_player'] = top_conceded.iloc[ev_tc.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

                    with c4:
                        st.markdown("#### 📈 Najwyższa średnia wpuszczonych (min. 10 spotkań)")
                        df_avg_worst = df_gk_stats[df_gk_stats['Mecze'] >= 10].sort_values('Średnia',
                                                                                           ascending=False).head(10)
                        df_avg_worst_medals = get_medals(df_avg_worst)
                        ev_wa = st.dataframe(
                            df_avg_worst_medals[
                                ['Miejsce', 'pozycja', 'Zawodnik_Clean', 'Lata gry', 'Średnia', 'Mecze']],
                            hide_index=True, use_container_width=True,
                            column_config={"Średnia": st.column_config.NumberColumn("Śr. goli", format="%.2f")},
                            on_select="rerun", selection_mode="single-row", key="tab6_wa")
                        if ev_wa.selection.rows:
                            st.session_state['cm_selected_player'] = df_avg_worst_medals.iloc[ev_wa.selection.rows[0]][
                                'Zawodnik_Clean']
                            st.rerun()

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
                cols_possible = ['funkcja', 'imię i nazwisko', 'Narodowość', 'Flaga', 'początek', 'koniec', 'mecze',
                                 'punkty']
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

                    sort_mode = st.radio("Sortuj według:",
                                         ["Punkty (Suma)", "Mecze (Liczba)", "Średnia Punktów (min. 5 spotkań)"],
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
                                                "Śr. Pkt": st.column_config.ProgressColumn("Średnia", format="%.2f",
                                                                                           min_value=0, max_value=3),
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
                                                w += 1;
                                                pts_sum += 3
                                            elif res[0] == res[1]:
                                                d += 1;
                                                pts_sum += 1
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
                                st.dataframe(
                                    res_df,
                                    use_container_width=True,
                                    column_config={
                                        "Średnia Pkt": st.column_config.ProgressColumn("Średnia Pkt", format="%.2f",
                                                                                       min_value=0, max_value=3),
                                        "% Zwycięstw": st.column_config.ProgressColumn("% Zwycięstw", format="%.1f%%",
                                                                                       min_value=0, max_value=100)
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

elif opcja == "🎮 Zgadnij Skład":
    import unicodedata


    def normalize_name(name):
        if not isinstance(name, str): return ""
        s = name.lower().strip()
        s = s.replace('ł', 'l').replace('ø', 'o').replace('đ', 'd').replace('ß', 'ss').replace('æ', 'ae')
        s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        return s


    st.header("🎮 Strefa Gier TSP")

    tab_mecz, tab_kontra, tab_kolo = st.tabs(["🏟️ Meczowa Jedenastka", "🧩 Jedenastka Powiązań", "🎡 Koło Fortuny"])

    df_w = load_details("wystepy.csv")
    df_p = load_data("pilkarze.csv")
    df_m = load_data("mecze.csv")

    if df_w is None or df_p is None:
        st.error("Brak plików wystepy.csv lub pilkarze.csv do uruchomienia gry.")
    else:
        # --- PRZYGOTOWANIE ZNORMALIZOWANEJ LISTY WYSZUKIWANIA ---
        all_player_names_raw = sorted(df_p['imię i nazwisko'].dropna().astype(str).unique().tolist())
        all_player_names = []
        for name in all_player_names_raw:
            norm = normalize_name(name)
            if name.lower() != norm.lower():
                all_player_names.append(f"{name} [{norm}]")
            else:
                all_player_names.append(name)

        era_options = {
            "Wszystkie": (1900, 2100),
            "Przed awansem (do 2011)": (1900, 2010),
            "I Ekstraklasa (11/12 - 15/16)": (2011, 2015),
            "Odbudowa (16/17 - 19/20)": (2016, 2019),
            "Obecna (od 20/21)": (2020, 2100)
        }


        def get_season_year(sezon_str):
            try:
                return int(str(sezon_str).split('/')[0].strip()[-4:])
            except:
                return 2000


        # ==========================================
        # GRA 1: MECZOWA JEDENASTKA
        # ==========================================
        with tab_mecz:
            st.markdown("Wylosuj historyczny mecz z wybranej ery i odgadnij wyjściową jedenastkę!")

            if 'quiz_active' not in st.session_state: st.session_state['quiz_active'] = False
            if 'quiz_guessed' not in st.session_state: st.session_state['quiz_guessed'] = []

            if not st.session_state['quiz_active']:
                sel_era_mecz = st.selectbox("Wybierz Erę:", list(era_options.keys()), key="era_mecz")
                min_yr, max_yr = era_options[sel_era_mecz]

                if st.button("🎲 Wylosuj Mecz i Rozpocznij Grę", use_container_width=True, type="primary"):
                    starters = df_w[
                        (df_w['Status'].isin(['Cały mecz', 'Zszedł', 'Grał', 'Czerwona kartka', 'Czerwona'])) & (
                                    df_w['Status'] != 'Wszedł')].copy()

                    # Filtrowanie po erze
                    starters['S_Year'] = starters['Sezon'].apply(get_season_year)
                    starters = starters[(starters['S_Year'] >= min_yr) & (starters['S_Year'] <= max_yr)]

                    match_counts = starters.groupby('Mecz_Label').size()
                    valid_matches = match_counts[match_counts == 11].index.tolist()

                    if valid_matches:
                        chosen_match = random.choice(valid_matches)
                        st.session_state['quiz_match'] = chosen_match

                        squad = starters[starters['Mecz_Label'] == chosen_match]['Zawodnik_Clean'].tolist()
                        df_p_c = df_p.copy()
                        df_p_c['join_key'] = df_p_c['imię i nazwisko'].astype(str).str.lower().str.strip()
                        df_p_c = prepare_flags(df_p_c)

                        target_players = []
                        for p in squad:
                            p_norm = str(p).lower().strip()
                            p_data = df_p_c[df_p_c['join_key'] == p_norm]
                            if not p_data.empty:
                                row = p_data.iloc[0]
                                pos = str(row.get('pozycja', '-')).capitalize()
                                flag = row.get('Flaga', None)
                                exact_name = str(row.get('imię i nazwisko', p))
                            else:
                                pos = "Nieznana"
                                flag = None
                                exact_name = str(p)

                            p_l = pos.lower()
                            if 'bram' in p_l or 'gk' in p_l:
                                sort_pos = 1
                            elif 'obr' in p_l or 'def' in p_l:
                                sort_pos = 2
                            elif 'pom' in p_l or 'mid' in p_l:
                                sort_pos = 3
                            elif 'nap' in p_l or 'for' in p_l:
                                sort_pos = 4
                            else:
                                sort_pos = 5

                            target_players.append({
                                'name': exact_name, 'pos': pos, 'sort_pos': sort_pos, 'flag': flag
                            })

                        target_players.sort(key=lambda x: x['sort_pos'])
                        st.session_state['quiz_target'] = target_players
                        st.session_state['quiz_guessed'] = []
                        st.session_state['quiz_active'] = True
                        st.session_state['quiz_give_up'] = False
                        st.rerun()
                    else:
                        st.error("Brak w bazie meczów z kompletną wyjściową jedenastką dla wybranej ery.")

            if st.session_state.get('quiz_active'):
                match_label = st.session_state['quiz_match']
                target_squad = st.session_state['quiz_target']
                guessed = st.session_state['quiz_guessed']

                try:
                    parts = match_label.split('|')
                    info_s = parts[1].strip() if len(parts) > 1 else match_label
                    date_s = parts[0].strip()
                except:
                    info_s = match_label;
                    date_s = "-"

                st.markdown(f"""
                <div style="text-align: center; padding: 15px; background-color: rgba(52, 152, 219, 0.15); border: 2px solid #3498db; border-radius: 8px; margin-bottom: 20px;">
                    <h2 style="margin:0; color: var(--text-color);">{info_s}</h2>
                    <p style="color: gray; margin: 4px 0 0 0;">📅 {date_s}</p>
                </div>
                """, unsafe_allow_html=True)

                progress = len(guessed) / 11
                st.progress(progress)
                st.write(f"**Odgadnięto:** {len(guessed)}/11")

                if not st.session_state.get('quiz_give_up') and len(guessed) < 11:
                    with st.form(key="quiz_form", clear_on_submit=True):
                        col_inp, col_btn, col_give = st.columns([3, 1, 1])
                        with col_inp:
                            guess_input = st.selectbox("Wybierz gracza", options=[""] + all_player_names,
                                                       label_visibility="collapsed")
                        with col_btn:
                            submit_guess = st.form_submit_button("Sprawdź", use_container_width=True)
                        with col_give:
                            give_up = st.form_submit_button("Poddaję się 🏳️", use_container_width=True)

                    if give_up:
                        st.session_state['quiz_give_up'] = True
                        st.rerun()

                    if submit_guess and guess_input:
                        guess_clean = guess_input.split(' [')[0].strip()
                        hit = False
                        for p in target_squad:
                            if p['name'] not in guessed and guess_clean == p['name']:
                                st.session_state['quiz_guessed'].append(p['name'])
                                st.success(f"Trafiony: **{p['name']}**!")
                                hit = True
                                time.sleep(0.5)
                                st.rerun()
                        if not hit:
                            if guess_clean in guessed:
                                st.warning("Ten zawodnik został już odgadnięty!")
                            else:
                                st.error("Pudło! Ten gracz nie zagrał w tym meczu.")

                if len(guessed) == 11:
                    st.balloons()
                    st.success("🎉 Niesamowite! Odgadłeś całą jedenastkę!")
                elif st.session_state.get('quiz_give_up'):
                    st.error("Gra przerwana. Oto pełny skład:")

                if len(guessed) == 11 or st.session_state.get('quiz_give_up'):
                    if st.button("🔄 Zagraj jeszcze raz", use_container_width=True):
                        st.session_state['quiz_active'] = False
                        st.rerun()

                st.divider()

                for p in target_squad:
                    is_guessed = p['name'] in guessed
                    is_revealed = is_guessed or st.session_state.get('quiz_give_up')
                    flag_html = f'<img src="{p["flag"]}" width="30" style="border-radius: 3px; border: 1px solid #aaa;">' if \
                    p['flag'] else '🏳️'

                    if is_revealed:
                        bg_color = "rgba(40, 167, 69, 0.2)" if is_guessed else "rgba(220, 53, 69, 0.2)"
                        border_color = "#28a745" if is_guessed else "#dc3545"
                        name_display = p['name']
                    else:
                        bg_color = "rgba(255, 255, 255, 0.05)"
                        border_color = "#666"
                        name_display = "❓❓❓"

                    st.markdown(f"""
                    <div style="display: flex; align-items: center; padding: 10px; margin-bottom: 8px; background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 5px;">
                        <div style="width: 50px; text-align: center; margin-right: 15px;">{flag_html}</div>
                        <div style="width: 100px; font-weight: bold; color: gray; font-size: 0.9em;">{p['pos']}</div>
                        <div style="flex-grow: 1; font-size: 1.1em; font-weight: bold; letter-spacing: 1px;">{name_display}</div>
                    </div>
                    """, unsafe_allow_html=True)

        # ==========================================
        # GRA 2: WYZWANIE: JEDENASTKA POWIĄZAŃ
        # ==========================================
        with tab_kontra:
            st.markdown(
                "Skompletuj jedenastkę zawodników. Każdy gracz musi pasować do opisu na karcie i **nikt nie może się powtarzać na boisku!** Masz ograniczoną liczbę błędów!")

            sel_era_kontra = st.selectbox("Ogranicz bazę do Ery:", list(era_options.keys()), key="era_kontra")

            if 'kontra_challenges' not in st.session_state: st.session_state['kontra_challenges'] = []
            if 'kontra_used_players' not in st.session_state: st.session_state['kontra_used_players'] = []
            if 'kontra_mistakes' not in st.session_state: st.session_state['kontra_mistakes'] = 0
            if 'kontra_game_over' not in st.session_state: st.session_state['kontra_game_over'] = False


            def generate_kontra_challenges(era_key):
                min_yr, max_yr = era_options[era_key]

                df_coaches = load_data("trenerzy.csv")
                coaches_list = []
                if df_coaches is not None:
                    for _, c_row in df_coaches.iterrows():
                        c_name = str(c_row.get('imię i nazwisko', 'Nieznany'))
                        s_val = str(c_row.get('początek', '')).strip()
                        e_val = str(c_row.get('koniec', '')).strip()
                        try:
                            c_start = pd.to_datetime(s_val, dayfirst=True) if s_val not in ['', '-',
                                                                                            'nan'] else pd.Timestamp.min
                        except:
                            c_start = pd.Timestamp.min
                        try:
                            c_end = pd.to_datetime(e_val, dayfirst=True) if e_val not in ['', '-', 'nan',
                                                                                          'obecnie'] else pd.Timestamp.now() + pd.Timedelta(
                                days=365)
                        except:
                            c_end = pd.Timestamp.now() + pd.Timedelta(days=365)
                        coaches_list.append((c_name, c_start, c_end))

                df_w_c = df_w.copy()
                df_w_c['S_Year'] = df_w_c['Sezon'].apply(get_season_year)
                # Filtrowanie bazy występów po Erze
                df_w_c = df_w_c[(df_w_c['S_Year'] >= min_yr) & (df_w_c['S_Year'] <= max_yr)]

                df_w_c['Data_Sort'] = pd.to_datetime(df_w_c['Data_Sort'], errors='coerce')
                df_w_c['join_key'] = df_w_c['Zawodnik_Clean'].astype(str).str.lower().str.strip()

                player_dates = df_w_c.groupby('join_key')['Data_Sort'].apply(lambda x: x.dropna().tolist()).to_dict()
                player_seasons = df_w_c.groupby('join_key')['Sezon'].apply(lambda x: set(x.dropna())).to_dict()

                agg = df_w_c.groupby('Zawodnik_Clean').agg(
                    {'Mecz_Label': 'nunique', 'Gole': 'sum', 'Czerwone': 'sum'}).reset_index()
                df_p_c = df_p.copy()
                df_p_c['join_key'] = df_p_c['imię i nazwisko'].astype(str).str.lower().str.strip()
                agg['join_key'] = agg['Zawodnik_Clean'].astype(str).str.lower().str.strip()
                merged = pd.merge(agg, df_p_c, on='join_key', how='left')

                catalog = []
                for _, r in merged.iterrows():
                    name = str(r.get('imię i nazwisko', r['Zawodnik_Clean']))
                    j_key = r['join_key']
                    tags = {'nat': [], 'pos': [], 'stat': [], 'age': [], 'coach': [], 'season': []}

                    nat = str(r.get('Narodowość', '-'))
                    if nat not in ['-', 'nan', '']:
                        kraj = nat.split('/')[0].strip()
                        tags['nat'].append(f"Kraj: {kraj}")
                        if 'Polska' not in nat: tags['nat'].append("Obcokrajowiec")

                    pos = str(r.get('pozycja', '-')).lower()
                    if 'bram' in pos or 'gk' in pos: tags['pos'].append("Bramkarz")
                    if 'obr' in pos or 'def' in pos: tags['pos'].append("Obrońca")
                    if 'pom' in pos or 'mid' in pos: tags['pos'].append("Pomocnik")
                    if 'nap' in pos or 'for' in pos: tags['pos'].append("Napastnik")

                    m = r['Mecz_Label']
                    if m >= 100:
                        tags['stat'].append("100+ występów")
                    elif m >= 50:
                        tags['stat'].append("50+ występów")

                    g = r['Gole']
                    if g >= 20:
                        tags['stat'].append("Strzelił 20+ goli")
                    elif g >= 10:
                        tags['stat'].append("Strzelił 10+ goli")
                    elif g >= 5:
                        tags['stat'].append("Strzelił 5+ goli")
                    if g == 0 and m >= 20: tags['stat'].append("Brak goli (min. 20 spotkań)")
                    if r['Czerwone'] >= 1: tags['stat'].append("Obejrzał czerwoną kartkę")

                    birth = r.get('data urodzenia', None)
                    if pd.notna(birth) and str(birth) not in ['-', 'nan']:
                        try:
                            yr = pd.to_datetime(birth).year
                            if yr < 1980:
                                tags['age'].append("Urodzony przed 1980 r.")
                            elif 1980 <= yr <= 1984:
                                tags['age'].append("Rocznik 1980-1984")
                            elif 1985 <= yr <= 1989:
                                tags['age'].append("Rocznik 1985-1989")
                            elif 1990 <= yr <= 1994:
                                tags['age'].append("Rocznik 1990-1994")
                            elif 1995 <= yr <= 1999:
                                tags['age'].append("Rocznik 1995-1999")
                            elif yr >= 2000:
                                tags['age'].append("Urodzony po 2000 r.")
                        except:
                            pass

                    my_dates = player_dates.get(j_key, [])
                    my_coaches = set()
                    for d in my_dates:
                        for c_name, c_start, c_end in coaches_list:
                            if c_start <= d <= c_end:
                                my_coaches.add(f"Grał u: {c_name.split()[-1]}")
                    if my_coaches:
                        tags['coach'].append(random.choice(list(my_coaches)))

                    my_seasons = player_seasons.get(j_key, set())
                    if my_seasons:
                        for s in random.sample(list(my_seasons), min(2, len(my_seasons))):
                            tags['season'].append(f"Sezon: {s}")

                    catalog.append({
                        'name': name, 'tags': tags,
                        'flag': get_flag_url(nat) if 'get_flag_url' in globals() else None
                    })

                valid_pairs = []
                formation = ['Bramkarz', 'Obrońca', 'Obrońca', 'Obrońca', 'Obrońca',
                             'Pomocnik', 'Pomocnik', 'Pomocnik', 'Pomocnik', 'Napastnik', 'Napastnik']

                for target_pos in formation:
                    sub_catalog = [p for p in catalog if target_pos in p['tags']['pos']]
                    if not sub_catalog: continue

                    attempts = 0
                    found = False
                    while not found and attempts < 1500:
                        attempts += 1
                        p = random.choice(sub_catalog)
                        avail_cats = [c for c in p['tags'].keys() if c != 'pos' and p['tags'][c]]
                        if not avail_cats: continue

                        num_conds = random.choices([1, 2], weights=[0.25, 0.75])[0]
                        if num_conds == 1:
                            c1 = random.choice(avail_cats)
                            pair = [random.choice(p['tags'][c1])]
                        else:
                            if len(avail_cats) >= 2:
                                c1, c2 = random.sample(avail_cats, 2)
                                pair = [random.choice(p['tags'][c1]), random.choice(p['tags'][c2])]
                            else:
                                c1 = avail_cats[0]
                                if len(p['tags'][c1]) >= 2:
                                    pair = random.sample(p['tags'][c1], 2)
                                else:
                                    pair = [p['tags'][c1][0]]

                        matching_players = []
                        for pl in sub_catalog:
                            pl_all_tags = []
                            for v in pl['tags'].values(): pl_all_tags.extend(v)
                            if all(t in pl_all_tags for t in pair):
                                matching_players.append(pl)

                        count = len(matching_players)

                        min_req = 4 if attempts < 1000 else 1

                        if count >= min_req and count <= 40:
                            pair_set = set(pair)
                            if not any(set(x['pair']) == pair_set and x['pos'] == target_pos for x in valid_pairs):
                                if count <= 4:
                                    rar = "👑 Legendarny"
                                elif count <= 8:
                                    rar = "🟣 Epicki"
                                elif count <= 15:
                                    rar = "🔵 Rzadki"
                                else:
                                    rar = "⚪ Zwykły"

                                unique_names = sorted(list(set(x['name'] for x in matching_players)))

                                valid_pairs.append({
                                    'pos': target_pos,
                                    'pair': pair,
                                    'valid_names': unique_names,
                                    'valid_full_data': matching_players,
                                    'rarity': rar,
                                    'count': count,
                                    'solved': False,
                                    'guessed_name': None,
                                    'guessed_flag': None
                                })
                                found = True
                return valid_pairs


            col_btn1, col_btn2 = st.columns([1, 2])
            with col_btn1:
                if st.button("🔄 Wylosuj Nową Jedenastkę", type="primary"):
                    with st.spinner("Tasowanie kart..."):
                        st.session_state['kontra_challenges'] = generate_kontra_challenges(sel_era_kontra)
                        st.session_state['kontra_used_players'] = []
                        st.session_state['kontra_mistakes'] = 0
                        st.session_state['kontra_game_over'] = False
                        st.rerun()
            with col_btn2:
                if st.button("🏳️ Poddaję się", type="secondary"):
                    st.session_state['kontra_game_over'] = True
                    st.rerun()

            if not st.session_state['kontra_challenges']:
                st.session_state['kontra_challenges'] = generate_kontra_challenges(sel_era_kontra)

            # --- PANEL ŻYĆ / BŁĘDÓW ---
            max_mistakes = 15
            current_mistakes = st.session_state.get('kontra_mistakes', 0)
            lives_left = max_mistakes - current_mistakes

            if lives_left <= 0:
                st.session_state['kontra_game_over'] = True

            game_over = st.session_state.get('kontra_game_over', False)

            if game_over:
                st.error("💀 Koniec Gry! Zobacz odpowiedzi do nieodgadniętych kart.")
            else:
                st.info(f"❤️ Pozostało szans: **{lives_left}** / {max_mistakes}")

            st.divider()


            def render_kontra_card(idx, chal):
                cond_text = " + ".join(chal['pair'])
                st.markdown(f"""
                <div style='text-align:center; background-color: var(--secondary-background-color); padding:10px; border-radius:8px; border:1px solid var(--text-color); margin-bottom:10px; min-height: 90px; display:flex; flex-direction:column; justify-content:center;'>
                    <span style='font-size:0.85em; font-weight:bold; color:#d4af37;'>{cond_text}</span>
                </div>
                """, unsafe_allow_html=True)

                if chal['solved']:
                    flag_html = f'<img src="{chal["guessed_flag"]}" style="width:20px; border-radius:2px; margin-right:5px;">' if \
                    chal['guessed_flag'] else '🏁'
                    st.markdown(f"""
                    <div style='text-align:center; background:#28a74530; border:1px solid #28a745; padding:8px; border-radius:5px;'>
                        {flag_html} <b>{chal['guessed_name']}</b><br>
                        <small style="color:gray;">{chal['rarity']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                elif game_over:
                    st.markdown(f"""
                    <div style='text-align:center; background:#dc354530; border:1px solid #dc3545; padding:8px; border-radius:5px;'>
                        <small style="color:#ffcccc; font-weight:bold;">Pasujący m.in.:</small><br>
                        <span style="font-size: 0.8em;">{', '.join(chal['valid_names'][:3])}</span>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    guess_k = st.selectbox("Wybierz gracza", options=[""] + all_player_names, key=f"k_sel_{idx}",
                                           label_visibility="collapsed")
                    if st.button("Sprawdź", key=f"k_btn_{idx}", use_container_width=True):
                        if guess_k:
                            guess_clean = guess_k.split(' [')[0].strip()
                            if guess_clean in st.session_state['kontra_used_players']:
                                st.session_state['kontra_mistakes'] += 1
                                st.toast(f"❌ Błąd! {guess_clean} jest już w jedenastce.", icon="❌")
                                st.rerun()
                            else:
                                hit_player = next((p for p in chal['valid_full_data'] if guess_clean == p['name']),
                                                  None)
                                if hit_player:
                                    chal['solved'] = True
                                    chal['guessed_name'] = hit_player['name']
                                    chal['guessed_flag'] = hit_player['flag']
                                    st.session_state['kontra_used_players'].append(hit_player['name'])

                                    if all(c['solved'] for c in st.session_state['kontra_challenges']):
                                        st.balloons()
                                    st.rerun()
                                else:
                                    st.session_state['kontra_mistakes'] += 1
                                    st.toast("❌ Pudło! Gracz nie pasuje do opisu.", icon="❌")
                                    st.rerun()
                        else:
                            st.toast("⚠️ Najpierw wybierz gracza z listy.", icon="⚠️")


            challenges = st.session_state['kontra_challenges']
            if len(challenges) == 11:
                st.markdown("<h4 style='text-align:center; margin-top:20px;'>🧤 Bramkarz</h4>", unsafe_allow_html=True)
                c_gk1, c_gk2, c_gk3 = st.columns([1, 2, 1])
                with c_gk2:
                    render_kontra_card(0, challenges[0])

                st.markdown("<h4 style='text-align:center; margin-top:20px;'>🛡️ Obrońcy</h4>", unsafe_allow_html=True)
                cols_def = st.columns(4)
                for i in range(4):
                    with cols_def[i]: render_kontra_card(i + 1, challenges[i + 1])

                st.markdown("<h4 style='text-align:center; margin-top:20px;'>🎯 Pomocnicy</h4>", unsafe_allow_html=True)
                cols_mid = st.columns(4)
                for i in range(4):
                    with cols_mid[i]: render_kontra_card(i + 5, challenges[i + 5])

                st.markdown("<h4 style='text-align:center; margin-top:20px;'>⚽ Napastnicy</h4>", unsafe_allow_html=True)
                c_att1, c_att2, c_att3, c_att4 = st.columns([1, 2, 2, 1])
                with c_att2:
                    render_kontra_card(9, challenges[9])
                with c_att3:
                    render_kontra_card(10, challenges[10])
            else:
                st.error("Błąd generowania jedenastki.")

        # ==========================================
        # GRA 3: KOŁO FORTUNY (Zgadnij Zawodnika)
        # ==========================================
        with tab_kolo:
            st.markdown(
                "Odgadnij nazwisko ukrytego zawodnika, podając po jednej literze. Możesz zaryzykować i wpisać całe hasło!")

            if 'kf_active' not in st.session_state: st.session_state['kf_active'] = False
            if 'kf_target_name' not in st.session_state: st.session_state['kf_target_name'] = ""
            if 'kf_target_norm' not in st.session_state: st.session_state['kf_target_norm'] = ""
            if 'kf_guessed_letters' not in st.session_state: st.session_state['kf_guessed_letters'] = set()
            if 'kf_mistakes' not in st.session_state: st.session_state['kf_mistakes'] = 0

            if not st.session_state['kf_active']:
                if st.button("🎲 Wylosuj Gracza i Graj", use_container_width=True, type="primary"):
                    # Losujemy tylko z graczy z min 10 meczami, zeby nie bylo zbyt trudno
                    df_w_agg = df_w.groupby('Zawodnik_Clean').size()
                    valid_for_kf = df_w_agg[df_w_agg >= 10].index.tolist()
                    if valid_for_kf:
                        target = random.choice(valid_for_kf)
                        st.session_state['kf_target_name'] = target
                        st.session_state['kf_target_norm'] = normalize_name(target)
                        st.session_state['kf_guessed_letters'] = set()
                        st.session_state['kf_mistakes'] = 0
                        st.session_state['kf_active'] = True
                        st.rerun()
                    else:
                        st.error("Brak zawodników spełniających kryteria.")

            if st.session_state.get('kf_active'):
                target_norm = st.session_state['kf_target_norm']
                target_original = st.session_state['kf_target_name']
                guessed = st.session_state['kf_guessed_letters']
                mistakes = st.session_state['kf_mistakes']
                max_mistakes = 7

                # Budowanie ukrytego słowa
                display_word = ""
                won = True
                for char, norm_char in zip(target_original, target_norm):
                    if norm_char == ' ':
                        display_word += "&nbsp;&nbsp;"
                    elif norm_char == '-':
                        display_word += "- "
                    elif norm_char in guessed:
                        display_word += f"{char.upper()} "
                    else:
                        display_word += "_ "
                        won = False

                st.markdown(f"""
                <div style="text-align:center; padding:30px; font-size: 2em; letter-spacing: 5px; font-family: monospace; background: var(--secondary-background-color); border: 1px solid #444; border-radius: 10px; margin-bottom: 20px;">
                    {display_word}
                </div>
                """, unsafe_allow_html=True)

                if won:
                    st.success(f"🎉 Gratulacje! Odgadłeś: **{target_original}**")
                    if st.button("🔄 Zagraj ponownie"):
                        st.session_state['kf_active'] = False
                        st.rerun()
                elif mistakes >= max_mistakes:
                    st.error(f"💀 Koniec gry! Prawidłowa odpowiedź to: **{target_original}**")
                    if st.button("🔄 Zagraj ponownie"):
                        st.session_state['kf_active'] = False
                        st.rerun()
                else:
                    st.warning(f"Błędy: **{mistakes}** / {max_mistakes}")

                    with st.form(key="kf_form", clear_on_submit=True):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            kf_input = st.text_input("Zgadnij literę lub całe hasło:", max_chars=30)
                        with c2:
                            st.write("")
                            st.write("")
                            submit_kf = st.form_submit_button("Zgadnij", use_container_width=True)

                    if submit_kf and kf_input:
                        guess_clean = normalize_name(kf_input)

                        # Całe hasło
                        if len(guess_clean) > 1:
                            if guess_clean == target_norm.replace(' ', '').replace('-',
                                                                                   '') or guess_clean == target_norm:
                                for c in target_norm: st.session_state['kf_guessed_letters'].add(c)
                                st.rerun()
                            else:
                                st.session_state['kf_mistakes'] += 1
                                st.error("Złe hasło!")
                                time.sleep(0.5)
                                st.rerun()
                        # Pojedyncza litera
                        elif len(guess_clean) == 1:
                            if guess_clean in target_norm:
                                if guess_clean not in guessed:
                                    st.session_state['kf_guessed_letters'].add(guess_clean)
                                    st.rerun()
                                else:
                                    st.warning("Ta litera została już odgadnięta.")
                            else:
                                st.session_state['kf_mistakes'] += 1
                                st.error(f"Brak litery '{kf_input.upper()}'")
                                time.sleep(0.5)
                                st.rerun()
