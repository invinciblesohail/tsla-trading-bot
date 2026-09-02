"""
TSLA Bot Dashboard v2 - ES (Spanish UI translation)
All user-facing text translated to Spanish. Underlying data VALUES
(tipo_decision: ENTRY/NO-ENTRY/NO-SETUP, resultado: WIN/LOSS,
filtro_bloqueador: fuera_sesion/posicion_abierta/etc.) are left unchanged
since they are literal stored CSV data per the client's own logging spec,
not free UI text - translating them would require changing
decision_logger.py too and risks breaking filters/matching against
existing data.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
import pytz

from tsla_bot import config

st.set_page_config(page_title="Bot TSLA 3-Factores", layout="wide", page_icon="")

# ============================================================
# CSS PERSONALIZADO
# ============================================================
st.markdown("""
<style>
.status-pill {
    display: inline-block; padding: 4px 14px; border-radius: 999px;
    font-size: 0.85em; font-weight: 600; margin-bottom: 4px;
}
.pill-green { background-color: rgba(16, 217, 138, 0.15); color: #10D98A; border: 1px solid #10D98A; }
.pill-red { background-color: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid #EF4444; }
.pill-yellow { background-color: rgba(245, 158, 11, 0.15); color: #F59E0B; border: 1px solid #F59E0B; }
.log-terminal {
    background-color: #05070C; border: 1px solid #262B36; border-radius: 8px;
    padding: 12px; font-family: 'Courier New', monospace; font-size: 0.82em;
    color: #9CA3AF; max-height: 320px; overflow-y: auto; white-space: pre-wrap;
}
.sidebar-label { color: #9CA3AF; font-size: 0.85em; margin-bottom: 0px; }
.sidebar-value { color: #E5E7EB; font-size: 1.0em; margin-top: 0px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

NY_TZ = pytz.timezone("America/New_York")


# ============================================================
# PANTALLA DE INICIO DE SESIÓN
# ============================================================
def login_screen():
    st.markdown("<div style='height: 80px'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown(
            "<div style='text-align:center'><span style='font-size:3em'>***</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<h2 style='text-align:center; margin-bottom:0;'>Bot TSLA 3-Factores</h2>"
            "<p style='text-align:center; color:#9CA3AF; letter-spacing:1px;'>SISTEMA DE TRADING SIMULADO (PAPER)</p>",
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input("USUARIO")
            password = st.text_input("CONTRASEÑA", type="password")
            submitted = st.form_submit_button("Iniciar Sesión", use_container_width=True)
            if submitted:
                if username == config.DASHBOARD_USERNAME and password == config.DASHBOARD_PASSWORD:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("Usuario o contraseña inválidos.")


if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    login_screen()
    st.stop()


# ============================================================
# CARGA DE DATOS
# ============================================================
@st.cache_data(ttl=30)
def load_data():
    path = "./logs/tsla_decisiones_master.csv"
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        df.columns = df.columns.str.strip()
        if df.empty:
            return df
        df["fecha"] = pd.to_datetime(df["fecha"])
        df["datetime_et"] = pd.to_datetime(df["fecha"].astype(str) + " " + df["hora_et"].astype(str))
        return df
    except Exception as e:
        st.error(f"Error al cargar el CSV maestro: {e}")
        return None


def get_heartbeat_status():
    if not os.path.exists(config.HEARTBEAT_FILE):
        return False, None
    try:
        with open(config.HEARTBEAT_FILE) as f:
            ts = pd.Timestamp(f.read().strip())
        age = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
        return age < config.HEARTBEAT_STALE_SECONDS, ts
    except Exception:
        return False, None


def get_market_status():
    now_et = datetime.now(NY_TZ)
    if now_et.weekday() >= 5:
        return False, now_et
    start = now_et.replace(hour=config.MARKET_OPEN_TIME[0], minute=config.MARKET_OPEN_TIME[1], second=0, microsecond=0)
    end = now_et.replace(hour=config.MARKET_CLOSE_TIME[0], minute=config.MARKET_CLOSE_TIME[1], second=0, microsecond=0)
    return start <= now_et < end, now_et


def read_recent_logs(n_lines=60):
    log_path = f"{config.LOG_DIR}/tsla_engine.log"
    if not os.path.exists(log_path):
        return "Aún no se encontró el registro del motor."
    with open(log_path, "r", errors="ignore") as f:
        lines = f.readlines()
    return "".join(lines[-n_lines:]) if lines else "(el archivo de registro está vacío)"


df = load_data()

# ============================================================
# BARRA LATERAL - conexión, estado del mercado, hora NY, Gateway
# ============================================================
with st.sidebar:
    st.markdown("### Bot TSLA")
    st.caption("Sistema de Trading Simulado - 3 Factores")
    st.markdown("---")

    connected, hb_ts = get_heartbeat_status()
    if connected:
        st.markdown('<span class="status-pill pill-green">● CONECTADO</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-pill pill-red">● DESCONECTADO</span>', unsafe_allow_html=True)

    st.markdown("---")

    market_open, now_et = get_market_status()
    if market_open:
        st.markdown('<p class="sidebar-label">Mercado</p>'
                     '<p class="sidebar-value">🟢 Mercado Abierto</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="sidebar-label">Mercado</p>'
                     '<p class="sidebar-value">🟡 Mercado Cerrado</p>', unsafe_allow_html=True)

    st.markdown(f'<p class="sidebar-label">Hora NY</p>'
                f'<p class="sidebar-value">{now_et.strftime("%H:%M:%S")}</p>', unsafe_allow_html=True)

    st.markdown(f'<p class="sidebar-label">Gateway</p>'
                f'<p class="sidebar-value">{config.IB_HOST}:{config.IB_PORT} (paper)</p>', unsafe_allow_html=True)

    if hb_ts is not None:
        st.markdown(f'<p class="sidebar-label">Última señal (heartbeat)</p>'
                     f'<p class="sidebar-value">{hb_ts.tz_convert(NY_TZ).strftime("%d %b %Y, %H:%M:%S")}</p>',
                     unsafe_allow_html=True)

    st.markdown("---")
    if st.button("🔄 Actualizar"):
        st.cache_data.clear()
        st.rerun()
    if st.button("Cerrar sesión"):
        st.session_state["authenticated"] = False
        st.rerun()


# ============================================================
# PRINCIPAL
# ============================================================
st.markdown("## 📈 Monitor de Trading en Vivo")

if df is None:
    st.info("Esperando a que el motor inicie (aún no se encuentra logs/tsla_decisiones_master.csv).")
    st.stop()
if df.empty:
    st.info("El motor está funcionando, pero aún no se han registrado decisiones.")
    st.stop()

entries = df[df["tipo_decision"] == "ENTRY"].copy()
closed = entries[entries["resultado"].notna() & (entries["resultado"] != "")].copy()
open_trades = entries[entries["resultado"].isna() | (entries["resultado"] == "")].copy()
no_entry = df[df["tipo_decision"] == "NO-ENTRY"].copy()
no_setup = df[df["tipo_decision"] == "NO-SETUP"].copy()

# ---------------- Posición abierta ----------------
tab_open, tab_closed = st.tabs([f"📂 Posición Abierta ({len(open_trades)})", f"✅ Operaciones Cerradas ({len(closed)})"])

with tab_open:
    if open_trades.empty:
        st.caption("Sin posición abierta.")
    else:
        show_cols = ["fecha", "hora_et", "direccion", "precio_entrada", "stop", "target", "acciones", "riesgo_usd"]
        st.dataframe(open_trades[show_cols], use_container_width=True, hide_index=True)

with tab_closed:
    if closed.empty:
        st.caption("Aún no hay operaciones cerradas.")
    else:
        show_cols = ["fecha", "hora_et", "direccion", "precio_entrada", "precio_salida",
                     "motivo_salida", "resultado", "pnl_usd", "pnl_pct", "overnight"]
        display = closed[show_cols].sort_values("fecha", ascending=False).copy()

        def color_pnl(val):
            try:
                v = float(val)
                color = "#10D98A" if v > 0 else ("#EF4444" if v < 0 else "#9CA3AF")
                return f"color: {color}"
            except (ValueError, TypeError):
                return ""

        styled = display.style.map(color_pnl, subset=["pnl_usd", "pnl_pct"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

st.markdown("---")

# ---------------- Tarjetas de métricas ----------------
if not closed.empty:
    wins = closed[closed["resultado"] == "WIN"]
    losses = closed[closed["resultado"] == "LOSS"]
    win_rate = len(wins) / len(closed) * 100

    gross_win_usd = wins["pnl_usd"].sum()
    gross_loss_usd = abs(losses["pnl_usd"].sum())
    pf_dollars = gross_win_usd / gross_loss_usd if gross_loss_usd > 0 else float("inf")

    gross_win_pct = wins["pnl_pct"].sum()
    gross_loss_pct = abs(losses["pnl_pct"].sum())
    pf_normalized = gross_win_pct / gross_loss_pct if gross_loss_pct > 0 else float("inf")

    net_pnl = closed["pnl_usd"].sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Operaciones Cerradas", len(closed))
    col2.metric("Tasa de Acierto", f"{win_rate:.1f}%")
    col3.metric("FB ($, compuesto)", f"{pf_dollars:.2f}")
    col4.metric("FB (%, ventaja real)", f"{pf_normalized:.2f}")
    col5.metric("PnL Neto", f"${net_pnl:,.2f}")

st.markdown("---")

# ---------------- Curva de capital ----------------
if not closed.empty:
    closed_sorted = closed.sort_values("datetime_et").copy()
    closed_sorted["cum_pnl"] = closed_sorted["pnl_usd"].cumsum()
    fig_equity = px.line(closed_sorted, x="datetime_et", y="cum_pnl",
                          title="PnL Acumulado (operaciones cerradas)",
                          template="plotly_dark",
                          color_discrete_sequence=["#3B82F6"])
    fig_equity.update_layout(yaxis_title="PnL Acumulado ($)", xaxis_title="Tiempo",
                              paper_bgcolor="#0B0E14", plot_bgcolor="#0B0E14")
    st.plotly_chart(fig_equity, use_container_width=True)

st.markdown("---")

# ---------------- Por qué no se abrieron operaciones ----------------
st.markdown("### 🚧 Por qué no se abrieron operaciones")
col_a, col_b = st.columns(2)

with col_a:
    if not no_entry.empty:
        reason_counts = no_entry["filtro_bloqueador"].value_counts().reset_index()
        reason_counts.columns = ["motivo", "cantidad"]
        fig_reasons = px.bar(reason_counts, x="motivo", y="cantidad",
                              title=f"Motivos de NO-ENTRADA (n={len(no_entry)})",
                              template="plotly_dark",
                              color_discrete_sequence=["#EF4444"])
        fig_reasons.update_layout(paper_bgcolor="#0B0E14", plot_bgcolor="#0B0E14")
        st.plotly_chart(fig_reasons, use_container_width=True)
    else:
        st.info("Aún no se han registrado decisiones NO-ENTRY.")

with col_b:
    total_decisions = len(df)
    breakdown = pd.DataFrame({
        "tipo": ["ENTRY", "NO-ENTRY", "NO-SETUP"],
        "cantidad": [len(entries), len(no_entry), len(no_setup)],
    })
    fig_breakdown = px.pie(breakdown, values="cantidad", names="tipo",
                            title=f"Todas las decisiones (n={total_decisions})",
                            hole=0.4,
                            color_discrete_sequence=["#10D98A", "#EF4444", "#787B86"])
    fig_breakdown.update_layout(paper_bgcolor="#0B0E14", plot_bgcolor="#0B0E14")
    st.plotly_chart(fig_breakdown, use_container_width=True)

st.markdown("---")

# ---------------- Discriminación de factores ----------------
st.markdown("### 🔍 Comparación de puntaje por factor: Ganancias vs Pérdidas")
if not closed.empty and len(wins) > 0 and len(losses) > 0:
    def side_score(row, factor):
        col = f"{factor}_call" if row["direccion"] == "CALL" else f"{factor}_put"
        return row[col]

    factor_rows = []
    for label, subset in [("GANANCIA", wins), ("PÉRDIDA", losses)]:
        for factor in ["trend", "bb", "space"]:
            vals = subset.apply(lambda r: side_score(r, factor), axis=1)
            factor_rows.append({"Resultado": label, "Factor": factor, "Puntaje Promedio": vals.mean()})
    factor_df = pd.DataFrame(factor_rows)

    fig_factors = px.bar(factor_df, x="Factor", y="Puntaje Promedio", color="Resultado",
                          barmode="group", title="Puntaje promedio por factor (del lado operado): Ganancia vs Pérdida",
                          template="plotly_dark",
                          color_discrete_map={"GANANCIA": "#10D98A", "PÉRDIDA": "#EF4444"})
    fig_factors.update_layout(paper_bgcolor="#0B0E14", plot_bgcolor="#0B0E14")
    st.plotly_chart(fig_factors, use_container_width=True)
    st.caption("Un factor con promedios similares entre ganancias y pérdidas no está discriminando bien - "
               "candidato a reponderar, según el motivo que dio el cliente para pedir este análisis.")
else:
    st.info("Se necesitan tanto ganancias como pérdidas registradas para comparar la discriminación de factores.")

st.markdown("---")

# ---------------- Nocturno vs Intradía ----------------
st.markdown("### Nocturno vs Intradía")
if not closed.empty:
    overnight_pnl = closed.groupby("overnight")["pnl_usd"].agg(["count", "sum", "mean"]).reset_index()
    overnight_pnl.columns = ["¿Nocturno?", "Operaciones", "PnL Total", "PnL Promedio"]
    st.dataframe(overnight_pnl, use_container_width=True, hide_index=True)

st.markdown("---")

# ---------------- Registros del sistema ----------------
st.markdown("### egistros del Sistema")
log_text = read_recent_logs(60)
st.markdown(f'<div class="log-terminal">{log_text}</div>', unsafe_allow_html=True)

st.markdown("---")

# ---------------- Registro completo de decisiones ----------------
st.markdown("### Registro Completo de Decisiones")

TIPO_LABELS_ES = {"ENTRY": "ENTRADA", "NO-ENTRY": "NO-ENTRADA", "NO-SETUP": "SIN CONFIGURACIÓN"}
decision_filter = st.multiselect(
    "Filtrar por tipo de decisión",
    options=["ENTRY", "NO-ENTRY", "NO-SETUP"],
    default=["ENTRY", "NO-ENTRY", "NO-SETUP"],
    format_func=lambda x: TIPO_LABELS_ES.get(x, x),
)
display_df = df[df["tipo_decision"].isin(decision_filter)].sort_values("datetime_et", ascending=False)
st.dataframe(display_df.drop(columns=["datetime_et"]), use_container_width=True, hide_index=True)
