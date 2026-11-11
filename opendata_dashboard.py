import io

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="臺南市停車場分析", page_icon="🅿️", layout="wide")

# 臺南市政府資料開放平台 - 停車場 CSV
DEFAULT_URL = (
    "https://data.tainan.gov.tw/File/ResourceCsvDownload/"
    "24b8d897-7971-45f9-8489-b4918ee41ed7"
)
COLORS = px.colors.qualitative.Bold  # 鮮豔配色


# ------------------------------------------------------------------
# 抓資料 (requests.get) 與前處理
# ------------------------------------------------------------------
def decode_bytes(raw: bytes) -> pd.DataFrame:
    """政府資料常見編碼：UTF-8(含BOM)、Big5，逐一嘗試。"""
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)))
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("無法判斷 CSV 編碼，請確認檔案格式")


@st.cache_data(ttl=3600, show_spinner="正在抓取資料...")
def fetch_csv(csv_url: str) -> pd.DataFrame:
    resp = requests.get(csv_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    return decode_bytes(resp.content)


def prepare(raw: pd.DataFrame):
    """清理欄位、-1 視為缺值、從地址抓出行政區、偵測經緯度。"""
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # 數值欄位的 -1 通常代表「沒有資料」，改成缺值避免圖表失真
    for c in df.select_dtypes("number").columns:
        df[c] = df[c].where(df[c] != -1)

    # 行政區：從地址「臺南市XX區」抓出
    addr_col = next((c for c in df.columns if "地址" in c), None)
    if addr_col:
        df["行政區"] = (
            df[addr_col].astype(str).str.extract(r"市([^市區]{1,3}區)")[0].fillna("未知")
        )

    # 經緯度偵測
    lat = next((c for c in df.columns if "緯" in c or c.lower() in ("lat", "latitude")), None)
    lon = next((c for c in df.columns if "經" in c or c.lower() in ("lon", "lng", "longitude")), None)
    if lat and lon:
        df[lat] = pd.to_numeric(df[lat], errors="coerce")
        df[lon] = pd.to_numeric(df[lon], errors="coerce")
    else:
        lat = lon = None
    return df, lat, lon


# ------------------------------------------------------------------
# 側邊欄：資料來源 + 篩選
# ------------------------------------------------------------------
st.sidebar.header("資料")
url = st.sidebar.text_input("CSV 下載網址", value=DEFAULT_URL)
uploaded = st.sidebar.file_uploader("或上傳 CSV 檔", type="csv")
if st.sidebar.button("🔄 重新下載資料", use_container_width=True):
    st.cache_data.clear()

df = None
try:
    if uploaded is not None:
        df = decode_bytes(uploaded.getvalue())
    elif url.strip():
        df = fetch_csv(url.strip())
except Exception as e:
    st.error(f"讀取失敗：{e}")

if df is None:
    st.info("👈 請在左側貼上 CSV 網址，或上傳 CSV 檔。")
    st.stop()

df, lat_col, lon_col = prepare(df)

type_col = "停車場型態" if "停車場型態" in df.columns else None
name_col = next((c for c in df.columns if "名稱" in c), df.columns[0])
district_col = "行政區" if "行政區" in df.columns else None

# 數值欄位（排除代碼、編號、經緯度這類不適合統計的欄位）
skip = ("代碼", "編號", "代號", "ID", "id")
num_cols = [
    c
    for c in df.select_dtypes("number").columns
    if not any(k in c for k in skip) and c not in (lat_col, lon_col)
]

st.sidebar.header("篩選條件")
filtered = df
if type_col:
    types = sorted(df[type_col].dropna().unique())
    pick_types = st.sidebar.multiselect("停車場型態", types, default=types)
    filtered = filtered[filtered[type_col].isin(pick_types)]
if district_col:
    districts = sorted(df[district_col].dropna().unique())
    pick_dist = st.sidebar.multiselect("行政區", districts, default=districts)
    filtered = filtered[filtered[district_col].isin(pick_dist)]
keyword = st.sidebar.text_input("關鍵字（名稱、地址…）")
if keyword:
    mask = filtered.astype(str).apply(
        lambda col: col.str.contains(keyword, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if filtered.empty:
    st.warning("沒有符合條件的資料，請調整左側篩選條件。")
    st.stop()

# ------------------------------------------------------------------
# 標題與 KPI
# ------------------------------------------------------------------
st.title("🅿️ 臺南市停車場資料分析")
st.caption("資料來源：臺南市政府資料開放平台（CSV，使用 requests.get() 即時抓取）")

k1, k2, k3, k4 = st.columns(4)
k1.metric("停車場數", f"{len(filtered):,}")
k2.metric("型態數", filtered[type_col].nunique() if type_col else "-")
k3.metric("行政區數", filtered[district_col].nunique() if district_col else "-")
if num_cols:
    main_num = max(num_cols, key=lambda c: filtered[c].notna().sum())
    k4.metric(f"{main_num}（合計）", f"{filtered[main_num].sum():,.0f}")
else:
    k4.metric("欄位數", len(filtered.columns))

# 只有一種型態時，用行政區上色，圖表才有多種顏色
multi_type = bool(type_col) and filtered[type_col].nunique() > 1
color_col = type_col if multi_type else district_col
PALETTE = COLORS + px.colors.qualitative.Safe + px.colors.qualitative.Vivid

tabs = st.tabs(["🥧 總覽", "🏆 排行", "📊 數值分布", "🗺️ 地圖", "📋 資料表"])

# ------------------------------------------------------------------
# 總覽
# ------------------------------------------------------------------
with tabs[0]:
    left, right = st.columns(2)
    with left:
        pie_col = type_col if multi_type else district_col
        if pie_col:
            st.subheader("各型態占比" if multi_type else "各行政區占比（前 10 名）")
            cnt = filtered[pie_col].value_counts().head(10).reset_index()
            cnt.columns = [pie_col, "數量"]
            fig = px.pie(
                cnt, names=pie_col, values="數量", hole=0.45,
                color_discrete_sequence=PALETTE,
            )
            fig.update_traces(textinfo="label+percent")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("找不到可分類的欄位")
    with right:
        st.subheader("各行政區停車場數量")
        if district_col:
            cnt = (
                filtered.groupby(district_col).size()
                .reset_index(name="數量")
                .sort_values("數量", ascending=False)
            )
            fig = px.bar(
                cnt, x=district_col, y="數量", color=district_col, text="數量",
                color_discrete_sequence=PALETTE,
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("找不到「地址」欄位，無法統計行政區")

# ------------------------------------------------------------------
# 排行
# ------------------------------------------------------------------
with tabs[1]:
    if num_cols:
        c1, c2 = st.columns(2)
        metric = c1.selectbox("排行依據（數值欄位）", num_cols)
        top_n = c2.slider("顯示前幾名", 5, 30, 10)
        top = filtered.dropna(subset=[metric]).nlargest(top_n, metric)
        if top.empty:
            st.info("這個欄位沒有有效數值（可能全是 -1）")
        else:
            fig = px.bar(
                top.sort_values(metric), x=metric, y=name_col, orientation="h",
                color=color_col, color_discrete_sequence=PALETTE,
            )
            fig.update_layout(height=max(350, top_n * 32))
            st.plotly_chart(fig, width="stretch")
    else:
        st.info("沒有可用的數值欄位")

# ------------------------------------------------------------------
# 數值分布
# ------------------------------------------------------------------
with tabs[2]:
    if num_cols:
        metric = st.selectbox("數值欄位", num_cols, key="dist")
        data = filtered.dropna(subset=[metric])
        if data.empty:
            st.info("這個欄位沒有有效數值（可能全是 -1）")
        else:
            a, b = st.columns(2)
            with a:
                st.subheader("直方圖")
                st.plotly_chart(
                    px.histogram(
                        data, x=metric, nbins=20, color=color_col,
                        color_discrete_sequence=PALETTE,
                    ),
                    width="stretch",
                )
            with b:
                st.subheader("各型態箱型圖" if multi_type else "各行政區箱型圖")
                st.plotly_chart(
                    px.box(
                        data, x=color_col, y=metric, color=color_col,
                        color_discrete_sequence=PALETTE,
                    ) if color_col else px.box(data, y=metric),
                    width="stretch",
                )
        if len(num_cols) >= 2:
            st.subheader("兩個數值欄位的關係")
            x, y = st.columns(2)
            xc = x.selectbox("X 軸", num_cols, index=0, key="sx")
            yc = y.selectbox("Y 軸", num_cols, index=1, key="sy")
            st.plotly_chart(
                px.scatter(
                    filtered, x=xc, y=yc, color=color_col, hover_name=name_col,
                    color_discrete_sequence=PALETTE,
                ),
                width="stretch",
            )
    else:
        st.info("沒有可用的數值欄位")

# ------------------------------------------------------------------
# 地圖
# ------------------------------------------------------------------
with tabs[3]:
    if lat_col and lon_col:
        pts = filtered.dropna(subset=[lat_col, lon_col])
        pts = pts[pts[lat_col].between(21, 26) & pts[lon_col].between(119, 123)]
        st.write(f"共 {len(pts)} 個有座標的停車場")
        st.map(pts, latitude=lat_col, longitude=lon_col)
    else:
        st.info("這份資料沒有經緯度欄位，無法畫地圖。")

# ------------------------------------------------------------------
# 資料表
# ------------------------------------------------------------------
with tabs[4]:
    st.write(f"符合 {len(filtered):,} 筆")
    st.dataframe(filtered, width="stretch")
    st.download_button(
        "⬇️ 下載篩選後的 CSV",
        filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name="tainan_parking.csv",
        mime="text/csv",
    )
    if num_cols:
        st.subheader("數值欄位統計")
        st.dataframe(filtered[num_cols].describe().T, width="stretch")
