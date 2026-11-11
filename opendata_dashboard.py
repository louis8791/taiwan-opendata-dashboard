import io

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="政府開放資料視覺化", page_icon="📊", layout="wide")
st.title("📊 政府資料開放平台 CSV 視覺化")

# ------------------------------------------------------------------
# 1. 取得資料來源
# ------------------------------------------------------------------
# 到 https://data.gov.tw/dataset/102773 頁面，在「資料資源」的 CSV 按鈕
# 上按右鍵 → 複製連結網址，貼到下面 DEFAULT_URL
DEFAULT_URL = "https://data.tainan.gov.tw/File/ResourceCsvDownload/24b8d897-7971-45f9-8489-b4918ee41ed7"

st.sidebar.header("資料來源")
url = st.sidebar.text_input("CSV 下載網址", value=DEFAULT_URL)
uploaded = st.sidebar.file_uploader("或上傳 CSV 檔", type="csv")


@st.cache_data(ttl=3600, show_spinner="正在抓取資料...")
def fetch_csv(csv_url: str) -> pd.DataFrame:
    """用 requests.get() 抓 CSV，再轉成 DataFrame。"""
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(csv_url, headers=headers, timeout=30)
    resp.raise_for_status()  # 不是 200 就丟出錯誤
    return decode_bytes(resp.content)


def decode_bytes(raw: bytes) -> pd.DataFrame:
    """政府資料常見編碼：UTF-8(含BOM)、Big5，逐一嘗試。"""
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)))
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("無法判斷 CSV 編碼，請確認檔案格式")


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

# ------------------------------------------------------------------
# 2. 資料概觀
# ------------------------------------------------------------------
df.columns = [str(c).strip() for c in df.columns]
num_cols = df.select_dtypes("number").columns.tolist()
cat_cols = [c for c in df.columns if c not in num_cols]

c1, c2, c3 = st.columns(3)
c1.metric("資料筆數", f"{len(df):,}")
c2.metric("欄位數", len(df.columns))
c3.metric("數值欄位數", len(num_cols))

tab_data, tab_stat, tab_chart = st.tabs(["📄 原始資料", "📈 統計摘要", "🎨 圖表"])

with tab_data:
    keyword = st.text_input("關鍵字搜尋（搜尋所有欄位）")
    view = df
    if keyword:
        mask = df.astype(str).apply(
            lambda col: col.str.contains(keyword, case=False, na=False)
        ).any(axis=1)
        view = df[mask]
    st.write(f"符合 {len(view):,} 筆")
    st.dataframe(view, use_container_width=True)
    st.download_button(
        "⬇️ 下載 CSV",
        view.to_csv(index=False).encode("utf-8-sig"),
        file_name="data.csv",
        mime="text/csv",
    )

with tab_stat:
    st.subheader("欄位型態與缺值")
    info = pd.DataFrame(
        {
            "型態": df.dtypes.astype(str),
            "缺值數": df.isna().sum(),
            "不重複值數": df.nunique(),
        }
    )
    st.dataframe(info, use_container_width=True)
    if num_cols:
        st.subheader("數值欄位統計")
        st.dataframe(df[num_cols].describe().T, use_container_width=True)

# ------------------------------------------------------------------
# 3. 圖表
# ------------------------------------------------------------------
with tab_chart:
    chart_type = st.selectbox(
        "圖表類型", ["長條圖", "折線圖", "圓餅圖", "直方圖", "散佈圖"]
    )
    all_cols = df.columns.tolist()

    try:
        if chart_type in ("長條圖", "折線圖"):
            x = st.selectbox("X 軸", all_cols)
            y = st.selectbox("Y 軸（數值）", num_cols) if num_cols else None
            if y is None:
                st.warning("沒有數值欄位，改用 X 軸的次數統計。")
                counts = df[x].value_counts().head(30).reset_index()
                counts.columns = [x, "次數"]
                fig = px.bar(counts, x=x, y="次數")
            else:
                agg = st.radio("相同 X 值的處理", ["加總", "平均", "不處理"], horizontal=True)
                data = df
                if agg == "加總":
                    data = df.groupby(x, as_index=False)[y].sum()
                elif agg == "平均":
                    data = df.groupby(x, as_index=False)[y].mean()
                data = data.head(200)
                fig = (px.bar if chart_type == "長條圖" else px.line)(data, x=x, y=y)

        elif chart_type == "圓餅圖":
            col = st.selectbox("分類欄位", cat_cols or all_cols)
            top_n = st.slider("顯示前幾名", 3, 20, 10)
            counts = df[col].value_counts().head(top_n).reset_index()
            counts.columns = [col, "次數"]
            fig = px.pie(counts, names=col, values="次數")

        elif chart_type == "直方圖":
            if not num_cols:
                st.warning("沒有數值欄位可畫直方圖。")
                st.stop()
            col = st.selectbox("數值欄位", num_cols)
            bins = st.slider("組數", 5, 100, 20)
            fig = px.histogram(df, x=col, nbins=bins)

        else:  # 散佈圖
            if len(num_cols) < 2:
                st.warning("散佈圖需要至少兩個數值欄位。")
                st.stop()
            x = st.selectbox("X 軸", num_cols, index=0)
            y = st.selectbox("Y 軸", num_cols, index=1)
            color = st.selectbox("顏色分組（可不選）", [None] + cat_cols)
            fig = px.scatter(df, x=x, y=y, color=color)

        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"繪圖失敗：{e}")
