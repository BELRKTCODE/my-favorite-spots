import math
import os
import re
from urllib.parse import unquote
from bs4 import BeautifulSoup
import pandas as pd
import requests
import streamlit as st

# 画面のタイトルと設定
st.set_page_config(page_title="マイお気に入りスポット", layout="wide")
st.title("📍 My Favorite Spots & Cafe List")
st.caption(
    "Googleマップのリンクを貼るだけ！店名・店舗写真・住所・距離を全自動取得！"
)

# データを保存するファイル名
CSV_FILE = "spots.csv"

# 「No Image」代替画像のURL
NO_IMAGE_URL = "https://placehold.jp/333333/ffffff/500x300.png?text=No%20Image"

# 網羅的なジャンル選択肢
GENRE_PRESETS = [
    "カフェ・喫茶店",
    "ラーメン・つけ麺",
    "ご飯・定食・和食",
    "洋食・フレンチ・イタリアン",
    "中華料理",
    "アジアン・エスニック",
    "焼肉・肉料理",
    "居酒屋・バル",
    "バー・お酒",
    "スイーツ・パン",
    "病院・クリニック・薬局",
    "温泉・サウナ",
    "観光・名所・公園",
    "ショッピング・買い物",
    "エンタメ・体験",
    "その他",
]

# 簡易現在地プリセット（緯度, 経度）
LOCATION_PRESETS = {
    "練馬駅": (35.7377, 139.6538),
    "西東京市（田無駅）": (35.7274, 139.5408),
    "渋谷駅": (35.6580, 139.7016),
    "新宿駅": (35.6896, 139.7006),
    "所沢駅": (35.7867, 139.4730),
    "池袋駅": (35.7295, 139.7109),
    "東京駅": (35.6812, 139.7671),
}


# 1. URLから「店名」「店舗写真（※地図画像は絶対排除）」「リダイレクト後のURL」「緯度経度」を自動解析
def fetch_place_details_from_url(url):
    if not url or pd.isna(url) or url.strip() == "":
        return "", "", "", 0.0, 0.0

    target_url = url.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9",
    }
    extracted_title = ""
    extracted_img = ""

    try:
        resp = requests.get(
            target_url, allow_redirects=True, headers=headers, timeout=5
        )
        final_url = resp.url

        # A. URL構造から店名を抽出
        place_match = re.search(r"/maps/place/([^/@?]+)", final_url)
        if place_match:
            raw_place_name = place_match.group(1)
            decoded_name = unquote(raw_place_name).replace("+", " ")
            if decoded_name and decoded_name.lower() not in [
                "google maps",
                "google マップ",
            ]:
                extracted_title = decoded_name

        soup = BeautifulSoup(resp.text, "html.parser")

        # B. 店名取得（タイトルタグ補助）
        if not extracted_title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                extracted_title = og_title["content"]
            elif soup.title:
                extracted_title = soup.title.string

            if extracted_title:
                extracted_title = re.sub(
                    r"\s*-\s*Google\s*(マップ|Maps).*", "", extracted_title
                )
                extracted_title = re.sub(
                    r"^\s*Google\s*(マップ|Maps)\s*-\s*", "", extracted_title
                )

        # C. 実際の店舗写真（雰囲気画像）のみを抽出（地図画像は排除）
        photo_matches = re.findall(
            r"https://lh\d+\.googleusercontent\.com/p/[A-Za-z0-9_-]+",
            resp.text,
        )
        if photo_matches:
            extracted_img = photo_matches[0] + "=w600-h400-k-no"

    except Exception:
        final_url = target_url

    if extracted_title.strip().lower() in ["google maps", "google マップ", ""]:
        extracted_title = ""

    lat, lon = extract_lat_lon(final_url)
    return (
        extracted_title.strip(),
        extracted_img.strip(),
        final_url,
        lat,
        lon,
    )


# 2. 緯度経度抽出
def extract_lat_lon(url):
    if not url:
        return 0.0, 0.0
    match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match:
        return float(match.group(1)), float(match.group(2))
    match_q = re.search(r"q=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match_q:
        return float(match_q.group(1)), float(match_q.group(2))
    match_ll = re.search(r"ll=(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if match_ll:
        return float(match_ll.group(1)), float(match_ll.group(2))
    return 0.0, 0.0


# 3. 都道府県・市区町村を自動取得
def get_detailed_address(lat, lon):
    if lat == 0 or lon == 0:
        return "都道府県未指定", "市区町村未指定"
    try:
        headers = {"User-Agent": "MyFavoriteSpotsApp/1.0"}
        api_url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&accept-language=ja"
        res = requests.get(api_url, headers=headers, timeout=3).json()
        address = res.get("address", {})

        pref = (
            address.get("province")
            or address.get("state")
            or "都道府県未指定"
        )
        city = (
            address.get("city")
            or address.get("suburb")
            or address.get("city_district")
            or address.get("town")
            or address.get("ward")
            or address.get("county")
            or "市区町村未指定"
        )
        return pref, city
    except Exception:
        return "都道府県未指定", "市区町村未指定"


# 4. 2点間の距離計算 (km)
def calculate_distance(lat1, lon1, lat2, lon2):
    if (
        pd.isna(lat1)
        or pd.isna(lon1)
        or pd.isna(lat2)
        or pd.isna(lon2)
        or lat1 == 0
        or lat2 == 0
    ):
        return None
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


# 初期サンプルデータ
initial_data = [
    {
        "id": 1,
        "店名": "東映アニメーションミュージアム",
        "ジャンル": "観光・名所・公園",
        "都道府県": "東京都",
        "市区町村": "練馬区",
        "特徴": "アニメ作品の展示や体験コーナーが楽しめるスポット！",
        "画像URL": "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=500",
        "マップURL": "https://maps.app.goo.gl/",
        "lat": 35.7533,
        "lon": 139.5971,
        "訪問回数": 0,
        "平均評価": 0.0,
        "評価履歴": "",
    },
    {
        "id": 2,
        "店名": "Cafe & Bakery 三軒茶屋",
        "ジャンル": "カフェ・喫茶店",
        "都道府県": "東京都",
        "市区町村": "世田谷区",
        "特徴": "静かで落ち着いた雰囲気。クロワッサンとラテが絶品！",
        "画像URL": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?w=500",
        "マップURL": "https://maps.google.com/?q=35.6431,139.6711",
        "lat": 35.6431,
        "lon": 139.6711,
        "訪問回数": 2,
        "平均評価": 4.5,
        "評価履歴": "4.0,5.0",
    },
]

# CSV読み込み・構造更新
if not os.path.exists(CSV_FILE):
    pd.DataFrame(initial_data).to_csv(CSV_FILE, index=False)

df = pd.read_csv(CSV_FILE)

# 互換性チェック
if "都道府県" not in df.columns:
    df["都道府県"] = "東京都"
if "市区町村" not in df.columns:
    df["市区町村"] = df["エリア"] if "エリア" in df.columns else "未指定"
if "評価履歴" not in df.columns:
    df["評価履歴"] = ""

for col, default in [
    ("id", 1),
    ("訪問回数", 0),
    ("平均評価", 0.0),
    ("lat", 0.0),
    ("lon", 0.0),
]:
    if col not in df.columns:
        df[col] = default


def save_data(updated_df):
    updated_df.to_csv(CSV_FILE, index=False)


# --------------------------------------------------
# 1. 現在地の設定（サイドバー）
# --------------------------------------------------
st.sidebar.header("📍 現在地の設定")
current_loc_name = st.sidebar.selectbox(
    "あなたの今いる場所を選択:", list(LOCATION_PRESETS.keys())
)
user_lat, user_lon = LOCATION_PRESETS[current_loc_name]

st.sidebar.caption(f"現在の設定座標: Lat {user_lat}, Lon {user_lon}")
st.sidebar.divider()

# --------------------------------------------------
# 2. 新しいスポットを追加するフォーム
# --------------------------------------------------
with st.expander(
    "➕ 行きたいスポットを追加する（Googleマップリンクで全自動！）", expanded=False
):
    with st.form("add_spot_form", clear_on_submit=True):
        st.markdown("**🔗 Googleマップ共有URLを貼り付け（必須）**")
        new_map_url = st.text_input(
            "Googleマップ共有URL*",
            placeholder="「共有」からコピーしたリンクを貼り付けてください",
        )

        st.markdown("---")
        st.caption(
            "※「店名」や「画像URL」を空欄にして追加すると、マップのリンクから自動取得します！"
        )
        new_name = st.text_input(
            "店名・スポット名（空欄ならマップから自動解析）"
        )

        col_input1, col_input2 = st.columns(2)
        with col_input1:
            new_genre = st.selectbox("ジャンル*", GENRE_PRESETS)
        with col_input2:
            new_img_url = st.text_input(
                "Web画像アドレス（空欄なら店舗写真を自動取得）",
                placeholder="https://example.com/image.jpg",
            )

        new_memo = st.text_area(
            "特徴・行きたい理由（任意）", placeholder="雰囲気や気になるメニューなど..."
        )

        submitted = st.form_submit_button("リストに自動追加する 🚀")

        if submitted:
            if not new_map_url:
                st.error("Googleマップの共有URLを入力してください！")
            else:
                with st.spinner("マップリンクから店舗写真・住所・店名を自動解析中..."):
                    (
                        auto_title,
                        auto_img,
                        final_url,
                        extracted_lat,
                        extracted_lon,
                    ) = fetch_place_details_from_url(new_map_url)

                    final_name = (
                        new_name.strip()
                        if new_name and new_name.strip() != ""
                        else (
                            auto_title
                            if auto_title
                            else "新しく追加したスポット"
                        )
                    )

                    final_img = (
                        new_img_url.strip()
                        if new_img_url and new_img_url.strip() != ""
                        else (auto_img if auto_img else NO_IMAGE_URL)
                    )

                    auto_pref, auto_city = get_detailed_address(
                        extracted_lat, extracted_lon
                    )

                    new_id = df["id"].max() + 1 if not df.empty else 1

                    new_row = pd.DataFrame(
                        [
                            {
                                "id": new_id,
                                "店名": final_name,
                                "ジャンル": new_genre,
                                "都道府県": auto_pref,
                                "市区町村": auto_city,
                                "特徴": new_memo if new_memo else "メモなし",
                                "画像URL": final_img,
                                "マップURL": new_map_url,
                                "lat": extracted_lat,
                                "lon": extracted_lon,
                                "訪問回数": 0,
                                "平均評価": 0.0,
                                "評価履歴": "",
                            }
                        ]
                    )
                    df = pd.concat([df, new_row], ignore_index=True)
                    save_data(df)
                    st.success(
                        f"「{final_name}」を【{auto_pref} {auto_city}】のスポットとして登録しました！"
                    )
                    st.rerun()

# --------------------------------------------------
# 3. 距離計算と2段階フィルタリング・並び替え（件数カウント表示機能付き！）
# --------------------------------------------------
df["距離_km"] = df.apply(
    lambda r: calculate_distance(user_lat, user_lon, r["lat"], r["lon"]),
    axis=1,
)

st.sidebar.header("🔍 絞り込み・並び替え")

# A. 訪問ステータス
status_filter = st.sidebar.radio(
    "訪問状況", ["すべて表示", "未訪問のみ 🚩", "訪問済みのみ ⭐"]
)

if status_filter == "未訪問のみ 🚩":
    filtered_df = df[df["訪問回数"] == 0]
elif status_filter == "訪問済みのみ ⭐":
    filtered_df = df[df["訪問回数"] > 0]
else:
    filtered_df = df.copy()

# B. ジャンル絞り込み（件数表示付き！）
current_genres = sorted(list(df["ジャンル"].dropna().unique()))
genre_counts = df["ジャンル"].value_counts().to_dict()

selected_genre = st.sidebar.multiselect(
    "1. ジャンルで選ぶ",
    options=current_genres,
    default=current_genres,
    format_func=lambda x: f"{x} ({genre_counts.get(x, 0)}件)",
)

# C. 階層エリア絞り込み（件数表示付き！）
all_prefs = sorted(list(df["都道府県"].dropna().unique()))
pref_counts = df["都道府県"].value_counts().to_dict()

selected_pref = st.sidebar.multiselect(
    "2. 都道府県で選ぶ",
    options=all_prefs,
    default=all_prefs,
    format_func=lambda x: f"{x} ({pref_counts.get(x, 0)}件)",
)

# 選択された都道府県内での市区町村データと件数を抽出
df_pref_filtered = df[df["都道府県"].isin(selected_pref)]
available_cities = sorted(
    list(df_pref_filtered["市区町村"].dropna().unique())
)
city_counts = df_pref_filtered["市区町村"].value_counts().to_dict()

selected_city = st.sidebar.multiselect(
    "3. 市区町村で選ぶ（詳細絞り込み）",
    options=available_cities,
    default=available_cities,
    format_func=lambda x: f"{x} ({city_counts.get(x, 0)}件)",
)

# フィルター適用
filtered_df = filtered_df[
    (filtered_df["ジャンル"].isin(selected_genre))
    & (filtered_df["都道府県"].isin(selected_pref))
    & (filtered_df["市区町村"].isin(selected_city))
]

# D. 並び替え
sort_option = st.sidebar.selectbox(
    "並び替え",
    [
        "現在地から近い順 📍",
        "登録が新しい順",
        "評価が高い順 ⭐",
        "訪問回数が多い順 🏃",
    ],
)

if sort_option == "現在地から近い順 📍":
    filtered_df = filtered_df.sort_values(
        by="距離_km", ascending=True, na_position="last"
    )
elif sort_option == "評価が高い順 ⭐":
    filtered_df = filtered_df.sort_values(by="平均評価", ascending=False)
elif sort_option == "訪問回数が多い順 🏃":
    filtered_df = filtered_df.sort_values(by="訪問回数", ascending=False)
else:
    filtered_df = filtered_df.sort_values(by="id", ascending=False)

# --------------------------------------------------
# 4. メイン画面にカード形式で表示
# --------------------------------------------------
st.subheader(
    f"スポット一覧（現在地: {current_loc_name} / 該当{len(filtered_df)}件）"
)

if filtered_df.empty:
    st.info("条件に一致するスポットがありません。")
else:
    cols = st.columns(2)
    for index, row in filtered_df.reset_index(drop=True).iterrows():
        with cols[index % 2]:
            img_url = (
                row["画像URL"]
                if pd.notna(row["画像URL"]) and row["画像URL"] != ""
                else NO_IMAGE_URL
            )
            st.image(img_url, use_container_width=True)

            dist_text = (
                f"📏 **現在地から {row['距離_km']} km**"
                if pd.notna(row["距離_km"])
                else "📏 距離不明"
            )
            st.markdown(f"### {row['店名']}")
            st.caption(dist_text)

            if row["訪問回数"] == 0:
                rating_text = "🚩 **未訪問**"
            else:
                stars = "★" * int(row["平均評価"]) + (
                    "☆" if row["平均評価"] % 1 >= 0.5 else ""
                )
                rating_text = f"⭐ **{row['平均評価']:.1f}** ({stars})  |  🏃 **{int(row['訪問回数'])}回訪問**"

            st.markdown(rating_text)
            st.write(
                f"🏷️ **ジャンル**: {row['ジャンル']}  |  📍 **住所**: {row['都道府県']} {row['市区町村']}"
            )
            st.write(f"📝 {row['特徴']}")

            map_url = (
                row["マップURL"]
                if pd.notna(row["マップURL"]) and row["マップURL"] != ""
                else "https://maps.google.com"
            )
            st.link_button("Googleマップで開く 🗺", map_url)

            # 操作パネル
            with st.expander("📝 行ってきた！訪問記録をつける"):
                with st.form(f"visit_form_{row['id']}"):
                    st.write("今回の満足度を0.5刻みで評価：")
                    rating_options = [round(x * 0.5, 1) for x in range(1, 11)]
                    new_rating = st.select_slider(
                        "評価 (★)",
                        options=rating_options,
                        value=4.0,
                        key=f"slider_{row['id']}",
                    )

                    if st.form_submit_button("評価を記録 🚀"):
                        history_str = (
                            str(row["評価履歴"])
                            if pd.notna(row["評価履歴"])
                            and str(row["評価履歴"]).strip() != ""
                            else ""
                        )
                        history_list = (
                            [float(x) for x in history_str.split(",")]
                            if history_str
                            else []
                        )

                        history_list.append(new_rating)
                        new_history_str = ",".join(
                            [str(x) for x in history_list]
                        )

                        new_visits = len(history_list)
                        new_avg = round(sum(history_list) / new_visits, 1)

                        df.loc[df["id"] == row["id"], "訪問回数"] = new_visits
                        df.loc[df["id"] == row["id"], "平均評価"] = new_avg
                        df.loc[df["id"] == row["id"], "評価履歴"] = (
                            new_history_str
                        )
                        save_data(df)
                        st.success(f"評価 ★{new_rating} を記録しました！")
                        st.rerun()

                # 1歩戻る（直前の訪問記録を取り消す）
                if row["訪問回数"] > 0:
                    st.markdown("---")
                    if st.button(
                        "↩️ 直前の記録を取り消す（1個戻る）",
                        key=f"undo_visit_{row['id']}",
                    ):
                        history_str = (
                            str(row["評価履歴"])
                            if pd.notna(row["評価履歴"])
                            and str(row["評価履歴"]).strip() != ""
                            else ""
                        )
                        history_list = (
                            [float(x) for x in history_str.split(",")]
                            if history_str
                            else []
                        )

                        if history_list:
                            removed_val = history_list.pop()
                            if history_list:
                                new_visits = len(history_list)
                                new_avg = round(
                                    sum(history_list) / new_visits, 1
                                )
                                new_history_str = ",".join(
                                    [str(x) for x in history_list]
                                )
                            else:
                                new_visits = 0
                                new_avg = 0.0
                                new_history_str = ""

                            df.loc[df["id"] == row["id"], "訪問回数"] = (
                                new_visits
                            )
                            df.loc[df["id"] == row["id"], "平均評価"] = new_avg
                            df.loc[df["id"] == row["id"], "評価履歴"] = (
                                new_history_str
                            )
                            save_data(df)
                            st.info(
                                f"直前の評価 ★{removed_val} を取り消しました。"
                            )
                            st.rerun()

            with st.expander("✏️ 登録情報を編集・削除する"):
                with st.form(f"edit_form_{row['id']}"):
                    edit_name = st.text_input("店名", value=row["店名"])

                    genre_idx = (
                        GENRE_PRESETS.index(row["ジャンル"])
                        if row["ジャンル"] in GENRE_PRESETS
                        else 0
                    )
                    edit_genre = st.selectbox(
                        "ジャンル",
                        GENRE_PRESETS,
                        index=genre_idx,
                        key=f"edit_genre_{row['id']}",
                    )

                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_pref = st.text_input(
                            "都道府県", value=row["都道府県"]
                        )
                    with col_e2:
                        edit_city = st.text_input(
                            "市区町村", value=row["市区町村"]
                        )

                    edit_memo = st.text_area(
                        "特徴・メモ",
                        value=row["特徴"] if pd.notna(row["特徴"]) else "",
                    )
                    edit_map_url = st.text_input(
                        "GoogleマップURL",
                        value=(
                            row["マップURL"] if pd.notna(row["マップURL"]) else ""
                        ),
                    )
                    edit_img_url = st.text_input(
                        "画像URL",
                        value=(
                            row["画像URL"] if pd.notna(row["画像URL"]) else ""
                        ),
                    )

                    if st.form_submit_button("変更を保存 💾"):
                        _, _, _, new_lat, new_lon = (
                            fetch_place_details_from_url(edit_map_url)
                        )

                        df.loc[df["id"] == row["id"], "店名"] = edit_name
                        df.loc[df["id"] == row["id"], "ジャンル"] = edit_genre
                        df.loc[df["id"] == row["id"], "都道府県"] = edit_pref
                        df.loc[df["id"] == row["id"], "市区町村"] = edit_city
                        df.loc[df["id"] == row["id"], "特徴"] = edit_memo
                        df.loc[df["id"] == row["id"], "マップURL"] = edit_map_url
                        df.loc[df["id"] == row["id"], "画像URL"] = edit_img_url
                        if new_lat != 0:
                            df.loc[df["id"] == row["id"], "lat"] = new_lat
                            df.loc[df["id"] == row["id"], "lon"] = new_lon

                        save_data(df)
                        st.success("スポット情報を更新しました！")
                        st.rerun()

                # スポット削除機能
                st.markdown("---")
                delete_confirm = st.checkbox(
                    "このスポットを削除する準備", key=f"del_chk_{row['id']}"
                )
                if delete_confirm:
                    if st.button(
                        "🗑️️ 本当に削除する",
                        key=f"del_btn_{row['id']}",
                        type="primary",
                    ):
                        df = df[df["id"] != row["id"]]
                        save_data(df)
                        st.success("スポットを削除しました。")
                        st.rerun()

            st.divider()