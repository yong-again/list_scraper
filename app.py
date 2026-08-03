"""Listhammer 메타 통계 대시보드 (Streamlit).

army_list/ 폴더의 *_army_list.xlsx 파일들을 읽어 팩션별 통계를 웹으로 표시한다.

실행:
    .venv/bin/streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from list_scraper import (
    ROLE_PRECEDENCE,
    enhancement_counts,
    enrich_units_df,
    load_unit_points,
    load_unit_roles,
)

ARMY_LIST_DIR = Path("army_list")

# 팔레트 (dataviz 기준: 단일 색조 막대 + 차분한 축/그리드)
PRIMARY = "#2a78d6"
NEGATIVE = "#d1743f"  # 발산 막대의 음수(평균보다 적게 쓴 쪽) 대비 색조
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

st.set_page_config(page_title="Listhammer 메타 대시보드", page_icon="⚔️", layout="wide")


# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------

def available_factions() -> dict[str, Path]:
    files = sorted(f for f in ARMY_LIST_DIR.glob("*_army_list.xlsx")
                   if not f.name.startswith("~$"))  # Excel이 열려 있을 때 생기는 잠금 파일 제외
    return {f.stem.removesuffix("_army_list").replace("_", " "): f for f in files}


@st.cache_data(show_spinner="데이터 로딩 중...")
def load_faction(path_str: str, faction: str) -> pd.DataFrame:
    df = pd.read_excel(path_str, sheet_name="아미 리스트")
    return enrich_units_df(df, load_unit_roles(faction), load_unit_points(faction))


@st.cache_data
def build_zip(files_with_mtime: tuple) -> bytes:
    """전체 팩션 xlsx를 하나의 zip으로 묶는다 (mtime이 캐시 키에 포함되어 갱신 시 재생성)."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path_str, _ in files_with_mtime:
            z.write(path_str, Path(path_str).name)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 차트 헬퍼 — 수평 막대 (단일 색조, 값 직접 라벨, 툴팁)
# ---------------------------------------------------------------------------

def hbar(data: pd.DataFrame, value: str, label: str, tooltip: list, fmt: str = "d") -> alt.Chart:
    axis_fmt = ".0%" if fmt == "%" else fmt
    base = alt.Chart(data).encode(
        y=alt.Y(f"{label}:N", sort="-x", title=None,
                axis=alt.Axis(labelColor=INK_2, labelLimit=300, labelFontSize=13)),
        x=alt.X(f"{value}:Q", title=None,
                axis=alt.Axis(labelColor=MUTED, gridColor=GRID, format=axis_fmt, tickCount=5)),
        tooltip=tooltip,
    )
    bars = base.mark_bar(size=16, cornerRadiusEnd=4, color=PRIMARY)
    labels = base.mark_text(align="left", dx=5, color=INK_2, fontSize=12).encode(
        text=alt.Text(f"{value}:Q", format=axis_fmt))
    return ((bars + labels)
            .properties(height=alt.Step(32))
            .configure_view(strokeWidth=0)
            .configure_axis(domainColor=BASELINE, tickColor=BASELINE))


def dbar(data: pd.DataFrame, value: str, label: str, tooltip: list) -> alt.Chart:
    """0을 기준으로 좌우로 갈리는 발산 막대 — '평균 대비 얼마나 더/덜'을 표현.

    양수는 기본 색조, 음수는 대비 색조로 칠하고 값 라벨을 막대 바깥쪽에 둔다.
    """
    order = data.sort_values(value, ascending=False)[label].tolist()
    # 값 라벨이 막대 바깥에 붙으므로 축 범위에 여유를 둬야 축 레이블과 겹치지 않는다
    lim = float(data[value].abs().max() or 0) * 1.3 or 0.01
    base = alt.Chart(data).encode(
        y=alt.Y(f"{label}:N", sort=order, title=None,
                axis=alt.Axis(labelColor=INK_2, labelLimit=300, labelFontSize=13)),
        x=alt.X(f"{value}:Q", title=None, scale=alt.Scale(domain=[-lim, lim], nice=False),
                axis=alt.Axis(labelColor=MUTED, gridColor=GRID, format="+.0%", tickCount=5)),
        tooltip=tooltip,
    )
    bars = base.mark_bar(size=16).encode(
        color=alt.condition(f"datum.{value} >= 0", alt.value(PRIMARY), alt.value(NEGATIVE)))
    pos = (base.transform_filter(f"datum.{value} >= 0")
           .mark_text(align="left", dx=5, color=INK_2, fontSize=12)
           .encode(text=alt.Text(f"{value}:Q", format="+.0%")))
    neg = (base.transform_filter(f"datum.{value} < 0")
           .mark_text(align="right", dx=-5, color=INK_2, fontSize=12)
           .encode(text=alt.Text(f"{value}:Q", format="+.0%")))
    rule = alt.Chart(pd.DataFrame({"z": [0]})).mark_rule(color=BASELINE).encode(x="z:Q")
    return ((bars + pos + neg + rule)
            .properties(height=alt.Step(32))
            .configure_view(strokeWidth=0)
            .configure_axis(domainColor=BASELINE, tickColor=BASELINE))


def section(title: str, caption: str = "") -> None:
    st.subheader(title)
    if caption:
        st.caption(caption)


def frac(label: str, numerator: str, denominator: str) -> None:
    """'라벨 = 분자/분모' 형태의 정의식을 CSS로 조판.

    st.latex(KaTeX)는 수식 폰트 기준으로 높이를 잡아 한글 글자의 위/아래가
    잘리므로 쓰지 않는다. numerator/denominator는 <b> 등 간단한 태그 허용.
    """
    st.markdown(
        f"""
        <div style="display:flex; justify-content:center; align-items:center; gap:.55rem;
                    margin:.4rem 0 .2rem; font-size:.85rem; color:{INK_2}; line-height:1.6;">
          <span>{label}</span><span>=</span>
          <span style="display:inline-flex; flex-direction:column; text-align:center;">
            <span style="padding:0 .5rem .15rem;">{numerator}</span>
            <span style="padding:.15rem .5rem 0; border-top:1px solid {BASELINE};">
              {denominator}</span>
          </span>
        </div>
        """,
        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 사이드바 — 팩션 선택 & 필터
# ---------------------------------------------------------------------------

factions = available_factions()
if not factions:
    st.error(f"`{ARMY_LIST_DIR}/` 폴더에 *_army_list.xlsx 파일이 없습니다. "
             "먼저 `python list_scraper.py --faction \"...\"` 으로 데이터를 수집하세요.")
    st.stop()

with st.sidebar:
    st.title("⚔️ Listhammer 메타")
    faction = st.selectbox("팩션", list(factions))
    d_all = load_faction(str(factions[faction]), faction)

    from datetime import datetime
    mtime = datetime.fromtimestamp(factions[faction].stat().st_mtime)
    st.caption(f"데이터 갱신: {mtime:%Y-%m-%d %H:%M}")

    st.download_button(
        "📥 Excel 리포트 다운로드",
        factions[faction].read_bytes(),
        file_name=factions[faction].name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="아미 리스트 / 팩션 룰(번역) / 통계 분석 3개 시트 포함",
        use_container_width=True,
    )
    if len(factions) > 1:
        st.download_button(
            "📦 전체 팩션 ZIP 다운로드",
            build_zip(tuple(sorted((str(p), p.stat().st_mtime) for p in factions.values()))),
            file_name="army_lists_all.zip",
            mime="application/zip",
            use_container_width=True,
        )

    formations = sorted(d_all["formation"].unique())
    picked_formations = st.multiselect("배틀 포메이션 필터", formations, default=formations)

    top_n = st.slider("유닛 순위 표시 개수", min_value=5, max_value=20, value=10, step=1)
    st.caption("데이터 출처: listhammer.info (대회 리스트) · wahapedia (역할 분류)")

d = d_all[d_all["formation"].isin(picked_formations)]
lists = d.drop_duplicates("list_id")
n_lists = len(lists)

st.title(f"{faction} — 메타 통계")
if n_lists == 0:
    st.warning("선택한 필터에 해당하는 리스트가 없습니다.")
    st.stop()


# ---------------------------------------------------------------------------
# 개요 지표
# ---------------------------------------------------------------------------

terrain_rate = lists["faction_terrain"].fillna("").astype(str).str.strip().ne("").mean()
drops = pd.to_numeric(lists["drops"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("분석 리스트 수", f"{n_lists}개")
m2.metric("참가 이벤트 수", f"{lists['event'].nunique()}개")
m3.metric("평균 승수", f"{lists['wins'].mean():.2f}승",
          help=f"평균 패수 {lists['losses'].mean():.2f}패")
m4.metric("평균 드랍 수", f"{drops.mean():.2f}")
m5.metric("팩션 터레인 채용률", f"{terrain_rate:.0%}")

st.divider()


# ---------------------------------------------------------------------------
# 배틀 포메이션
# ---------------------------------------------------------------------------

section("배틀 포메이션", "필터와 무관하게 전체 리스트 기준")
all_lists = d_all.drop_duplicates("list_id")
fmt_stats = (all_lists.groupby("formation")
             .agg(리스트수=("list_id", "count"), 평균승수=("wins", "mean"), 평균패수=("losses", "mean"))
             .sort_values("리스트수", ascending=False).reset_index()
             .rename(columns={"formation": "배틀포메이션"}))

c1, c2 = st.columns([3, 2])
with c1:
    st.altair_chart(
        hbar(fmt_stats, "리스트수", "배틀포메이션",
             tooltip=[alt.Tooltip("배틀포메이션:N", title="포메이션"),
                      alt.Tooltip("리스트수:Q", title="리스트 수"),
                      alt.Tooltip("평균승수:Q", title="평균 승수", format=".2f")]),
        use_container_width=True)
with c2:
    st.dataframe(fmt_stats.round(2), hide_index=True, use_container_width=True)

    st.markdown("**팩션 터레인**")
    terr = lists["faction_terrain"].fillna("").astype(str).str.strip()
    terr_names = terr.mask(terr == "", "(미채용)").str.replace(r"\s*\(\d+[^)]*\)$", "", regex=True)
    terr_t = terr_names.value_counts().reset_index()
    terr_t.columns = ["팩션 터레인", "리스트수"]
    terr_t["비율"] = (terr_t["리스트수"] / n_lists).map("{:.0%}".format)
    st.dataframe(terr_t, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# 유닛 채용률 (전체 + 역할별 탭)
# ---------------------------------------------------------------------------

section("가장 많이 쓰인 유닛",
        f"채용률 = 해당 유닛을 포함한 리스트 비율 (분석 리스트 {n_lists}개 기준) · "
        "포인트 = 워스크롤 기준 포인트 (Battle Profiles 반영, 증강 미포함)")


def unit_stats(sub: pd.DataFrame, top: int) -> pd.DataFrame:
    g = (sub.groupby("base_unit")
         .agg(채용리스트수=("list_id", "nunique"), 총채용횟수=("list_id", "count"),
              포인트=("unit_points", "first"),
              관측포인트=("points", lambda s: m.iat[0] if not (m := s.mode()).empty else pd.NA))
         .sort_values(["채용리스트수", "총채용횟수"], ascending=False).head(top).reset_index()
         .rename(columns={"base_unit": "유닛"}))
    g["채용률"] = g["채용리스트수"] / n_lists
    g["포인트"] = g["포인트"].fillna(g["관측포인트"]).fillna(0).astype(int)
    return g


roles_present = [r for r in ROLE_PRECEDENCE + ["기타"] if r in set(d["role"])]
tabs = st.tabs(["전체"] + roles_present)
for tab, role in zip(tabs, [None] + roles_present):
    with tab:
        sub = d if role is None else d[d["role"] == role]
        g = unit_stats(sub, top_n)
        st.altair_chart(
            hbar(g, "채용률", "유닛", fmt="%",
                 tooltip=[alt.Tooltip("유닛:N"),
                          alt.Tooltip("채용률:Q", format=".0%"),
                          alt.Tooltip("채용리스트수:Q", title="채용 리스트 수"),
                          alt.Tooltip("총채용횟수:Q", title="총 채용 횟수"),
                          alt.Tooltip("포인트:Q", title="포인트 (기준)")]),
            use_container_width=True)


# ---------------------------------------------------------------------------
# 영웅 시너지 — 같은 리스트에 함께 쓰인 유닛 (리스트 전체 기준, 연대 무관)
# ---------------------------------------------------------------------------

section("영웅 시너지 — 같은 리스트에 함께 쓰인 유닛",
        "**리스트 전체** 기준 — 연대(Regiment) 소속과 무관하게, 이 영웅을 넣은 리스트에 "
        "같이 담긴 유닛을 집계합니다. 같은 연대 안에 넣었는지는 아래 "
        "'연대(Regiment) 구성 분석' 섹션에서 확인하세요.")

# 유닛별 전체 채용률 (같은 리스트 채용률과 비교해 시너지 지수 산출) & 역할 매핑
unit_lists = d.drop_duplicates(["list_id", "base_unit"])
overall_rate = unit_lists.groupby("base_unit")["list_id"].nunique() / n_lists
role_map = d.drop_duplicates("base_unit").set_index("base_unit")["role"]

heroes = (unit_lists[unit_lists["role"] == "HERO"]
          .groupby("base_unit")["list_id"].nunique()
          .sort_values(ascending=False))

if heroes.empty:
    st.info("영웅 데이터가 없습니다.")
else:
    hero = st.selectbox("영웅 선택", list(heroes.index),
                        format_func=lambda h: f"{h}  ({heroes[h]}개 리스트 · {heroes[h] / n_lists:.0%})")
    hero_lists = set(unit_lists.loc[unit_lists["base_unit"] == hero, "list_id"])
    n_hero = len(hero_lists)

    wins_by_list = lists.set_index("list_id")["wins"]
    co = unit_lists[unit_lists["list_id"].isin(hero_lists) & (unit_lists["base_unit"] != hero)].copy()
    co["_wins"] = co["list_id"].map(wins_by_list)
    grp = co.groupby("base_unit")
    syn = pd.DataFrame({"같은리스트수": grp["list_id"].nunique(),
                        "평균승수": grp["_wins"].mean()}).reset_index().rename(columns={"base_unit": "유닛"})
    syn["같은리스트채용률"] = syn["같은리스트수"] / n_hero
    syn["전체채용률"] = syn["유닛"].map(overall_rate)
    syn["시너지지수"] = syn["같은리스트채용률"] / syn["전체채용률"]
    syn["역할"] = syn["유닛"].map(role_map)

    st.caption(f"**{hero}** 을(를) 넣은 리스트 **{n_hero}개** 기준 "
               f"(전체 {n_lists}개 중) · 연대 소속 무관")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**같은 리스트 채용률** — 이 영웅을 넣은 리스트 중 해당 유닛도 있는 비율")
        top_co = syn.sort_values(["같은리스트수", "같은리스트채용률"], ascending=False).head(top_n)
        st.altair_chart(
            hbar(top_co, "같은리스트채용률", "유닛", fmt="%",
                 tooltip=[alt.Tooltip("유닛:N"), alt.Tooltip("역할:N"),
                          alt.Tooltip("같은리스트채용률:Q", format=".0%",
                                      title="같은 리스트 채용률"),
                          alt.Tooltip("같은리스트수:Q", title="함께 든 리스트 수"),
                          alt.Tooltip("시너지지수:Q", format=".2f", title="시너지 지수"),
                          alt.Tooltip("평균승수:Q", format=".2f", title="평균 승수")]),
            use_container_width=True)
        frac("같은 리스트 채용률",
             f"{hero} <b>와 이 유닛</b>이 함께 든 리스트 수",
             f"{hero} 이(가) 든 리스트 수 ({n_hero}개)")
    with c2:
        min_co = max(2, round(n_hero * 0.15))
        st.markdown(f"**시너지 지수 TOP** (함께 {min_co}회 이상)")
        synergy = (syn[syn["같은리스트수"] >= min_co]
                   .sort_values("시너지지수", ascending=False)
                   .head(top_n)[["유닛", "역할", "같은리스트채용률", "시너지지수", "평균승수"]]
                   .rename(columns={"같은리스트채용률": "같은 리스트 채용률"}))
        if synergy.empty:
            st.info("표본이 적어 시너지 지수를 계산할 수 없습니다.")
        else:
            st.dataframe(
                synergy.style.format({"같은 리스트 채용률": "{:.0%}", "시너지지수": "{:.2f}×",
                                      "평균승수": "{:.2f}승"}),
                hide_index=True, use_container_width=True)
        frac("시너지 지수", "같은 리스트 채용률", "이 유닛의 <b>전체</b> 채용률")
        st.caption("1보다 크면 단순 인기 유닛이 아니라 이 영웅과 특별히 자주 짝지어지는 조합 · "
                   "평균 승수는 두 유닛이 함께 든 리스트들의 평균")


# ---------------------------------------------------------------------------
# 자주 함께 쓰이는 조합 — 유닛 쌍 순위 (히트맵은 접이식 고급 보기)
# ---------------------------------------------------------------------------

section("자주 함께 쓰이는 조합 TOP",
        "같은 리스트에 자주 함께 담긴 **두 유닛 조합** 순위 · "
        "이 팩션의 대표적인 유닛 궁합을 보여줍니다.")

hm_units = (unit_lists.groupby("base_unit")["list_id"].nunique()
            .sort_values(ascending=False).head(top_n).index.tolist())
sets = {u: set(unit_lists.loc[unit_lists["base_unit"] == u, "list_id"]) for u in hm_units}

# 조합은 순서가 없으므로 (A,B)를 한 번만 — 순위 목록에서 같은 쌍이 두 번 나오지 않게
pairs = []
for i, a in enumerate(hm_units):
    for bb in hm_units[i + 1:]:
        inter = len(sets[a] & sets[bb])
        union = len(sets[a] | sets[bb])
        pairs.append({"조합": f"{a} + {bb}", "유닛A": a, "유닛B": bb,
                      "함께강도": inter / union if union else 0.0,
                      "함께리스트수": inter, "동시비율": inter / n_lists})
combo = pd.DataFrame(pairs)

if combo.empty or combo["함께리스트수"].sum() == 0:
    st.info("조합 데이터가 부족합니다.")
else:
    tab_str, tab_cnt = st.tabs(["궁합 강도 순", "함께 쓴 리스트 수 순"])
    with tab_str:
        top_pair = combo.sort_values("함께강도", ascending=False).head(top_n)
        st.altair_chart(
            hbar(top_pair, "함께강도", "조합", fmt="%",
                 tooltip=[alt.Tooltip("조합:N"),
                          alt.Tooltip("함께강도:Q", format=".0%", title="궁합 강도"),
                          alt.Tooltip("함께리스트수:Q", title="함께 쓴 리스트 수"),
                          alt.Tooltip("동시비율:Q", format=".0%", title="전체 대비 비율")]),
            use_container_width=True)
        frac("궁합 강도",
             "두 유닛을 <b>모두</b> 넣은 리스트 수",
             "두 유닛 중 <b>하나라도</b> 넣은 리스트 수")
        st.caption("분모로 나눠 인기도 차이를 보정 — 둘 다 흔해서 겹친 게 아니라 "
                   "실제로 '붙어 다니는' 조합이 위로 올라옵니다.")
    with tab_cnt:
        top_cnt = combo.sort_values("함께리스트수", ascending=False).head(top_n)
        st.altair_chart(
            hbar(top_cnt, "함께리스트수", "조합",
                 tooltip=[alt.Tooltip("조합:N"),
                          alt.Tooltip("함께리스트수:Q", title="함께 쓴 리스트 수"),
                          alt.Tooltip("함께강도:Q", format=".0%", title="궁합 강도"),
                          alt.Tooltip("동시비율:Q", format=".0%", title="전체 대비 비율")]),
            use_container_width=True)
        st.caption(f"보정 없이 실제로 함께 담긴 리스트 개수 (분석 리스트 {n_lists}개 중) — "
                   "인기 유닛끼리의 조합이 위로 올라옵니다.")

    with st.expander("고급 보기 — 전체 조합 히트맵 (행렬)"):
        st.caption("가로·세로 모두 같은 상위 유닛 목록인 대칭 표입니다. 세로에서 유닛을 찾고 "
                   "가로 번호로 상대 유닛을 짚으면 그 칸이 두 유닛의 궁합 강도입니다 "
                   "(칸에 마우스를 올리면 이름 표시) · 대각선 빈칸은 자기 자신이라 제외")
        # 가로축에 긴 유닛명을 회전 배치하면 Vega가 겹치는 라벨을 자동 생략해 축 개수가
        # 달라 보인다 → 세로축은 "번호. 이름", 가로축은 같은 번호만 표시해 대칭을 드러냄
        num = {u: i + 1 for i, u in enumerate(hm_units)}
        y_order = [f"{num[u]}. {u}" for u in hm_units]
        x_order = [str(num[u]) for u in hm_units]
        cells = []
        for a in hm_units:
            for bb in hm_units:
                if a == bb:
                    continue
                inter = len(sets[a] & sets[bb])
                union = len(sets[a] | sets[bb])
                cells.append({"가로": str(num[a]), "세로": f"{num[bb]}. {bb}",
                              "유닛A": a, "유닛B": bb,
                              "jaccard": inter / union if union else 0.0,
                              "함께리스트수": inter})
        hm = pd.DataFrame(cells)
        heat = (alt.Chart(hm).mark_rect(stroke="#ffffff", strokeWidth=1).encode(
            x=alt.X("가로:N", sort=x_order, title="가로축 = 세로축과 같은 유닛 (번호)",
                    axis=alt.Axis(labelAngle=0, labelColor=INK_2, labelFontSize=12,
                                  titleColor=MUTED, titleFontSize=11, titleFontWeight="normal",
                                  orient="top", labelOverlap=False)),
            y=alt.Y("세로:N", sort=y_order, title=None,
                    axis=alt.Axis(labelColor=INK_2, labelLimit=260, labelFontSize=11,
                                  labelOverlap=False)),
            color=alt.Color("jaccard:Q", title="궁합 강도",
                            scale=alt.Scale(scheme="blues"),
                            legend=alt.Legend(format=".0%", gradientLength=140)),
            tooltip=[alt.Tooltip("유닛B:N", title="세로 유닛"),
                     alt.Tooltip("유닛A:N", title="가로 유닛"),
                     alt.Tooltip("jaccard:Q", format=".0%", title="궁합 강도"),
                     alt.Tooltip("함께리스트수:Q", title="함께 쓴 리스트 수")])
            .properties(height=alt.Step(28))
            .configure_view(strokeWidth=0)
            .configure_axis(domainColor=BASELINE, tickColor=BASELINE))
        st.altair_chart(heat, use_container_width=True)


# ---------------------------------------------------------------------------
# 연대(Regiment) 구성 분석 — 누가 누구를 데리고 로스터를 짜는가
# ---------------------------------------------------------------------------

section("연대(Regiment) 구성 분석",
        "**같은 연대 안** 기준 — 아미 리스트는 장군 연대 + 연대 1·2·3…으로 짜이고 각 연대는 "
        "영웅(리더)이 이끕니다. 위 '영웅 시너지'가 리스트 전체를 봤다면, 여기서는 "
        "이 영웅이 **직접 이끄는 연대에 편성된** 유닛만 집계합니다.")

d_reg = d.copy()
d_reg["reg_id"] = d_reg["list_id"] + " ‖ " + d_reg["regiment"].astype(str)
reg_leader = d_reg[d_reg["role"] == "HERO"].groupby("reg_id")["base_unit"].first()  # 연대 첫 영웅 = 리더
reg_size = d_reg.groupby("reg_id").size()
reg_wins = d_reg.groupby("reg_id")["wins"].first()
lead_counts = reg_leader.value_counts()

m1, m2, m3 = st.columns(3)
m1.metric("평균 연대 수 / 리스트", f"{d_reg['reg_id'].nunique() / n_lists:.1f}개")
m2.metric("평균 연대 크기", f"{reg_size.mean():.1f}유닛",
          help="리더 영웅 포함, 연대 하나에 담긴 유닛 행 수")
m3.metric("최다 연대 리더", lead_counts.index[0] if not lead_counts.empty else "-",
          help=f"{lead_counts.iloc[0]}개 연대를 이끔" if not lead_counts.empty else None)

if lead_counts.empty:
    st.info("연대 리더(영웅) 데이터가 없습니다.")
else:
    leader = st.selectbox("연대 리더(영웅) 선택", list(lead_counts.index),
                          format_func=lambda h: f"{h}  ({lead_counts[h]}개 연대)",
                          key="reg_leader")
    my_regs = reg_leader[reg_leader == leader].index
    n_myreg = len(my_regs)

    body = d_reg[d_reg["reg_id"].isin(my_regs) & (d_reg["base_unit"] != leader)].copy()
    body = body.drop_duplicates(["reg_id", "base_unit"])
    body["_wins"] = body["reg_id"].map(reg_wins)
    grp = body.groupby("base_unit")
    foll = pd.DataFrame({"같은연대수": grp["reg_id"].nunique(),
                         "평균승수": grp["_wins"].mean()}).reset_index().rename(columns={"base_unit": "유닛"})
    foll["같은연대편성률"] = foll["같은연대수"] / n_myreg
    foll["역할"] = foll["유닛"].map(role_map)

    st.caption(f"**{leader}** 이(가) 이끈 연대 **{n_myreg}개** 기준 · "
               f"평균 크기 {reg_size.loc[my_regs].mean():.1f}유닛 · "
               f"평균 승수 {reg_wins.loc[my_regs].mean():.2f}승")

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**같은 연대 편성률** — 이 영웅의 연대 중 해당 유닛이 같이 편성된 비율")
        top_foll = foll.sort_values("같은연대수", ascending=False).head(top_n)
        if top_foll.empty:
            st.info("이 리더의 연대에 함께 편성된 유닛이 없습니다.")
        else:
            st.altair_chart(
                hbar(top_foll, "같은연대편성률", "유닛", fmt="%",
                     tooltip=[alt.Tooltip("유닛:N"), alt.Tooltip("역할:N"),
                              alt.Tooltip("같은연대편성률:Q", format=".0%",
                                          title="같은 연대 편성률"),
                              alt.Tooltip("같은연대수:Q", title="함께 편성된 연대 수"),
                              alt.Tooltip("평균승수:Q", format=".2f", title="평균 승수")]),
                use_container_width=True)
        frac("같은 연대 편성률",
             f"{leader} <b>와 같은 연대</b>에 편성된 횟수",
             f"{leader} 이(가) 이끈 연대 수 ({n_myreg}개)")
    with c2:
        st.markdown("**연대 구성 상세**")
        tbl = (foll.sort_values("같은연대수", ascending=False).head(top_n)
               [["유닛", "역할", "같은연대편성률", "평균승수"]]
               .rename(columns={"같은연대편성률": "같은 연대 편성률"}))
        if not tbl.empty:
            st.dataframe(
                tbl.style.format({"같은 연대 편성률": "{:.0%}", "평균승수": "{:.2f}승"}),
                hide_index=True, use_container_width=True)
        st.caption("리스트에는 같이 있어도 다른 연대에 넣었다면 여기서는 집계되지 않습니다 · "
                   "평균 승수는 해당 연대가 속한 리스트들의 평균")


# ---------------------------------------------------------------------------
# 장군 선택별 리스트 성향 — 장군을 바꾸면 나머지 구성이 어떻게 달라지는가
# ---------------------------------------------------------------------------

section("장군 선택별 리스트 성향",
        "장군(General)을 누구로 두느냐에 따라 나머지 로스터가 어떻게 달라지는지 · "
        "절대 채용률은 인기 순위를 반복하므로 **팩션 평균과의 차이** (%p)로 표시합니다.")

MIN_GEN_LISTS = 3  # 장군별 표본이 이보다 작으면 편차가 노이즈에 가까워 선택지에서 제외

gen_rows = (d[d["notes"].fillna("").str.contains(r"\bGeneral\b")]
            .drop_duplicates(["list_id", "base_unit"]))
gen_of_list = gen_rows.groupby("list_id")["base_unit"].first()  # 리스트당 장군 1명

d_g = d.copy()
d_g["general"] = d_g["list_id"].map(gen_of_list)
ul_g = d_g.drop_duplicates(["list_id", "base_unit"])
gen_counts = ul_g.drop_duplicates("list_id")["general"].value_counts()
eligible = gen_counts[gen_counts >= MIN_GEN_LISTS]

if eligible.empty:
    st.info(f"장군별 리스트가 {MIN_GEN_LISTS}개 이상인 경우가 없어 비교할 표본이 부족합니다. "
            f"(최다 장군 {gen_counts.iloc[0]}개)" if not gen_counts.empty else "장군 데이터가 없습니다.")
else:
    def g_lists_of(g: str) -> set:
        return set(ul_g.loc[ul_g["general"] == g, "list_id"])

    def rate_of(ls: set) -> pd.Series:
        """리스트 집합 안에서의 유닛별 채용률."""
        return ul_g[ul_g["list_id"].isin(ls)].groupby("base_unit")["list_id"].nunique() / len(ls)

    def aide_counts(ls: set) -> pd.Series:
        """장군 연대 밖의 연대를 이끄는 영웅별 연대 수."""
        sr = d_g[d_g["list_id"].isin(ls)].copy()
        sr["reg_id"] = sr["list_id"] + " ‖ " + sr["regiment"].astype(str)
        is_gen_reg = sr["regiment"].astype(str).str.contains("General", case=False)
        lead = (sr[(sr["role"] == "HERO") & ~is_gen_reg]
                .groupby("reg_id")["base_unit"].first())
        return lead.value_counts()

    def diverge_pick(frame: pd.DataFrame, col: str) -> pd.DataFrame:
        """증가·감소 양쪽 상위를 뽑아 발산 막대용 데이터로."""
        half = max(3, top_n // 2)
        out = pd.concat([frame.nlargest(half, col), frame.nsmallest(half, col)])
        return out.drop_duplicates("유닛")[lambda x: x[col].abs() > 0.001]

    tab_base, tab_vs = st.tabs(["팩션 평균과 비교", "장군 A vs B 직접 비교"])

    with tab_base:
        general = st.selectbox(
            "장군 선택", list(eligible.index),
            format_func=lambda g: f"{g}  ({eligible[g]}개 리스트 · {eligible[g] / n_lists:.0%})",
            key="general_pick")
        g_lists = g_lists_of(general)
        n_g = len(g_lists)
        g_lists_df = lists[lists["list_id"].isin(g_lists)]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("이 장군 리스트 수", f"{n_g}개", help=f"전체 {n_lists}개 중")
        k2.metric("평균 승수", f"{g_lists_df['wins'].mean():.2f}승",
                  delta=f"{g_lists_df['wins'].mean() - lists['wins'].mean():+.2f} vs 팩션 평균")
        g_drops = pd.to_numeric(g_lists_df["drops"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
        k3.metric("평균 드랍 수", f"{g_drops.mean():.2f}",
                  delta=f"{g_drops.mean() - drops.mean():+.2f}", delta_color="inverse")
        k4.metric("평균 연대 수", f"{d_g[d_g['list_id'].isin(g_lists)].groupby('list_id')['regiment'].nunique().mean():.1f}개")

        # 편차: 이 장군 리스트에서의 채용률 − 팩션 전체 채용률 (장군 본인은 항상 100%라 제외)
        dev = pd.DataFrame({"장군채용률": rate_of(g_lists),
                            "전체채용률": overall_rate}).dropna(subset=["장군채용률"])
        dev["전체채용률"] = dev["전체채용률"].fillna(0.0)
        dev = dev.drop(index=general, errors="ignore")
        dev["차이"] = dev["장군채용률"] - dev["전체채용률"]
        dev = dev.reset_index().rename(columns={"base_unit": "유닛"})
        dev["역할"] = dev["유닛"].map(role_map)
        picked = diverge_pick(dev, "차이")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("**팩션 평균 대비 채용률 차이** — 오른쪽(파랑)은 더 많이, 왼쪽(주황)은 덜 씀")
            if picked.empty:
                st.info("팩션 평균과 뚜렷한 차이를 보이는 유닛이 없습니다.")
            else:
                st.altair_chart(
                    dbar(picked, "차이", "유닛",
                         tooltip=[alt.Tooltip("유닛:N"), alt.Tooltip("역할:N"),
                                  alt.Tooltip("차이:Q", format="+.0%", title="평균 대비 차이"),
                                  alt.Tooltip("장군채용률:Q", format=".0%", title="이 장군일 때"),
                                  alt.Tooltip("전체채용률:Q", format=".0%", title="팩션 전체")]),
                    use_container_width=True)
                st.caption(f"예: +20%p = 팩션 전체보다 이 장군 리스트에서 20%p 더 자주 채용 · "
                           f"표본 {n_g}개라 1개 리스트가 약 {1 / n_g:.0%}p를 움직입니다")
        with c2:
            st.markdown("**함께 쓰는 부관 영웅** — 장군 연대 밖의 연대를 이끄는 영웅")
            ac = aide_counts(g_lists)
            if ac.empty:
                st.info("부관 영웅 데이터가 없습니다.")
            else:
                aide = ac.head(top_n).rename("연대수").reset_index()
                aide.columns = ["부관 영웅", "연대수"]
                aide["비율"] = aide["연대수"] / n_g
                st.dataframe(aide.style.format({"비율": "{:.0%}"}),
                             hide_index=True, use_container_width=True)
                st.caption("비율 = 이 장군 리스트당 해당 영웅이 연대를 이끈 비율 "
                           "(한 리스트에 여러 연대가 있어 100%를 넘을 수 있음)")

    with tab_vs:
        if len(eligible) < 2:
            st.info("비교할 장군이 2명 이상 필요합니다 "
                    f"(리스트 {MIN_GEN_LISTS}개 이상인 장군이 {len(eligible)}명).")
        else:
            opts = list(eligible.index)
            s1, s2 = st.columns(2)
            ga = s1.selectbox("장군 A", opts, index=0,
                              format_func=lambda g: f"{g} ({eligible[g]}개)", key="gen_a")
            gb = s2.selectbox("장군 B", opts, index=1,
                              format_func=lambda g: f"{g} ({eligible[g]}개)", key="gen_b")
            if ga == gb:
                st.warning("서로 다른 두 장군을 선택하세요.")
            else:
                la, lb = g_lists_of(ga), g_lists_of(gb)
                na, nb = len(la), len(lb)
                la_df, lb_df = lists[lists["list_id"].isin(la)], lists[lists["list_id"].isin(lb)]

                def dnum(df):
                    return pd.to_numeric(df["drops"].astype(str).str.extract(r"(\d+)")[0],
                                         errors="coerce").mean()

                st.markdown(f"**A** = {ga} · **B** = {gb}")
                reg_a = d_g[d_g["list_id"].isin(la)].groupby("list_id")["regiment"].nunique().mean()
                reg_b = d_g[d_g["list_id"].isin(lb)].groupby("list_id")["regiment"].nunique().mean()
                summary = pd.DataFrame([
                    {"항목": "리스트 수", "A": na, "B": nb, "차이 (A−B)": na - nb},
                    {"항목": "평균 승수", "A": la_df["wins"].mean(), "B": lb_df["wins"].mean(),
                     "차이 (A−B)": la_df["wins"].mean() - lb_df["wins"].mean()},
                    {"항목": "평균 드랍 수", "A": dnum(la_df), "B": dnum(lb_df),
                     "차이 (A−B)": dnum(la_df) - dnum(lb_df)},
                    {"항목": "평균 연대 수", "A": reg_a, "B": reg_b, "차이 (A−B)": reg_a - reg_b},
                ])

                def fmt_n(v, sign=False):
                    """정수는 소수점 없이 (리스트 수가 '17.00'으로 보이지 않게)."""
                    spec = "+" if sign else ""
                    return (f"{v:{spec}.0f}" if float(v).is_integer() else f"{v:{spec}.2f}")

                st.dataframe(
                    summary.style.format({"A": fmt_n, "B": fmt_n,
                                          "차이 (A−B)": lambda v: fmt_n(v, sign=True)}),
                    hide_index=True, use_container_width=True)

                # A·B 어느 쪽에도 없는 유닛은 비교 대상이 아니므로 합집합만, 두 장군 본인은 제외
                cmp_df = pd.DataFrame({"A채용률": rate_of(la), "B채용률": rate_of(lb)}).fillna(0.0)
                cmp_df = cmp_df.drop(index=[g for g in (ga, gb) if g in cmp_df.index],
                                     errors="ignore")
                cmp_df["차이"] = cmp_df["A채용률"] - cmp_df["B채용률"]
                cmp_df = cmp_df.reset_index().rename(columns={"base_unit": "유닛"})
                cmp_df["역할"] = cmp_df["유닛"].map(role_map)
                pick2 = diverge_pick(cmp_df, "차이")

                c1, c2 = st.columns([3, 2])
                with c1:
                    st.markdown("**채용률 차이 (A − B)** — 오른쪽(파랑)은 **A** 쪽, "
                                "왼쪽(주황)은 **B** 쪽에서 더 많이 쓰는 유닛")
                    if pick2.empty:
                        st.info("두 장군 사이에 뚜렷한 구성 차이가 없습니다.")
                    else:
                        st.altair_chart(
                            dbar(pick2, "차이", "유닛",
                                 tooltip=[alt.Tooltip("유닛:N"), alt.Tooltip("역할:N"),
                                          alt.Tooltip("차이:Q", format="+.0%", title="A−B 차이"),
                                          alt.Tooltip("A채용률:Q", format=".0%", title=f"A · {ga}"),
                                          alt.Tooltip("B채용률:Q", format=".0%", title=f"B · {gb}")]),
                            use_container_width=True)
                        st.caption(f"표본 A {na}개 / B {nb}개 — 리스트 1개가 각각 "
                                   f"{1 / na:.0%}p / {1 / nb:.0%}p를 움직입니다")
                with c2:
                    st.markdown("**부관 영웅 비교** — 장군 연대 밖의 연대를 이끄는 영웅")
                    aa, ab = aide_counts(la), aide_counts(lb)
                    if aa.empty and ab.empty:
                        st.info("부관 영웅 데이터가 없습니다.")
                    else:
                        cmp_aide = pd.DataFrame({"A": aa / na, "B": ab / nb}).fillna(0.0)
                        cmp_aide["차이"] = cmp_aide["A"] - cmp_aide["B"]
                        cmp_aide = (cmp_aide.reindex(cmp_aide["차이"].abs()
                                                     .sort_values(ascending=False).index)
                                    .head(top_n).reset_index())
                        cmp_aide.columns = ["부관 영웅", "A", "B", "차이"]
                        st.dataframe(
                            cmp_aide.style.format({"A": "{:.0%}", "B": "{:.0%}", "차이": "{:+.0%}"}),
                            hide_index=True, use_container_width=True)
                        st.caption("차이가 큰 순서 · 값은 리스트당 해당 영웅이 연대를 이끈 비율 · "
                                   "장군 본인은 자기 연대를 이끌기 때문에 0%로 나옵니다")

    with st.expander("장군별 요약 비교 (표)"):
        rows = []
        for g in eligible.index:
            gl = set(ul_g.loc[ul_g["general"] == g, "list_id"])
            ldf = lists[lists["list_id"].isin(gl)]
            gd = pd.to_numeric(ldf["drops"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
            rows.append({"장군": g, "리스트수": len(gl), "채용률": len(gl) / n_lists,
                         "평균승수": ldf["wins"].mean(), "평균패수": ldf["losses"].mean(),
                         "평균드랍": gd.mean()})
        st.dataframe(
            pd.DataFrame(rows).sort_values("리스트수", ascending=False)
              .style.format({"채용률": "{:.0%}", "평균승수": "{:.2f}",
                             "평균패수": "{:.2f}", "평균드랍": "{:.2f}"}),
            hide_index=True, use_container_width=True)
        st.caption(f"리스트 {MIN_GEN_LISTS}개 이상인 장군만 · 표본이 작으니 평균 승수 차이는 참고용")


# ---------------------------------------------------------------------------
# 강화 & 장군
# ---------------------------------------------------------------------------

c1, c2 = st.columns(2)

with c1:
    section("가장 많이 쓰인 강화", "아티팩트 · 히로익 트레잇 · 엔드린워크 등 (장비 옵션 제외)")
    enh = enhancement_counts(d).head(top_n).rename(columns={"채용_횟수": "채용횟수"})
    if enh.empty:
        st.info("강화 데이터가 없습니다.")
    else:
        st.altair_chart(
            hbar(enh, "채용횟수", "강화",
                 tooltip=[alt.Tooltip("강화:N"), alt.Tooltip("채용횟수:Q", title="채용 횟수")]),
            use_container_width=True)

with c2:
    section("장군(General) 선택", "리스트에서 장군으로 지정된 유닛")
    gen = d[d["notes"].fillna("").str.contains(r"\bGeneral\b")]
    gen_t = gen["base_unit"].value_counts().reset_index()
    gen_t.columns = ["유닛", "리스트수"]
    gen_t["비율"] = gen_t["리스트수"] / n_lists
    if gen_t.empty:
        st.info("장군 데이터가 없습니다.")
    else:
        st.altair_chart(
            hbar(gen_t.head(top_n), "리스트수", "유닛",
                 tooltip=[alt.Tooltip("유닛:N"), alt.Tooltip("리스트수:Q", title="리스트 수"),
                          alt.Tooltip("비율:Q", format=".0%")]),
            use_container_width=True)


# ---------------------------------------------------------------------------
# 로스터 추천 — 실전 템플릿(사례 기반) + 통계 기반 코어 유닛
# ---------------------------------------------------------------------------

st.divider()
section("로스터 추천",
        "대회 데이터에서 뽑은 출발점 · **실전 템플릿**은 실제로 쓰인 합법 리스트를 그대로 보여주고, "
        "**코어 유닛**은 채용률 통계를 예산에 맞춰 요약합니다.")

tab_tpl, tab_core = st.tabs(["실전 템플릿 (대회 리스트)", "통계 기반 코어 유닛"])

with tab_tpl:
    f1, f2 = st.columns([2, 1])
    gen_opts = ["전체"] + list(gen_counts.index) if not gen_counts.empty else ["전체"]
    pick_gen = f1.selectbox("장군으로 좁히기", gen_opts, key="tpl_gen")
    n_show = f2.slider("보여줄 리스트 수", 1, 10, 3, key="tpl_n")

    cand = lists.copy()
    cand["general"] = cand["list_id"].map(gen_of_list)
    if pick_gen != "전체":
        cand = cand[cand["general"] == pick_gen]

    cand = cand.sort_values(["wins", "losses"], ascending=[False, True], na_position="last")
    if cand.empty:
        st.info("조건에 맞는 리스트가 없습니다.")
    else:
        st.caption(f"성적 순 상위 {min(n_show, len(cand))}개 · 조건에 맞는 리스트 {len(cand)}개 "
                   "· 포인트·연대 구성·강화가 원본 그대로입니다")
        for _, row in cand.head(n_show).iterrows():
            body = d[d["list_id"] == row["list_id"]]
            w, l = row["wins"], row["losses"]
            score = f"{w:.0f}승 {l:.0f}패" if pd.notna(w) and pd.notna(l) else "전적 미상"
            title = f"{score} · {row['player']} · {row['formation']} · {body['points'].sum():.0f}pt"
            with st.expander(title):
                st.caption(f"**{row['list_title'] or '(제목 없음)'}** · {row['event']} "
                           f"({row['date']}) · 드랍 {row['drops']}"
                           + (f" · 장군 {row['general']}" if pd.notna(row.get("general")) else ""))
                if pd.notna(row["faction_terrain"]) and str(row["faction_terrain"]).strip():
                    st.caption(f"팩션 터레인: {row['faction_terrain']}")
                roster = (body[["regiment", "unit", "points", "notes"]]
                          .rename(columns={"regiment": "연대", "unit": "유닛",
                                           "points": "포인트", "notes": "상세"}))
                roster["상세"] = roster["상세"].fillna("")
                st.dataframe(roster.style.format({"포인트": "{:.0f}"}),
                             hide_index=True, use_container_width=True)
                st.download_button(
                    "이 리스트 CSV", roster.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{row['player']}_list.csv".replace(" ", "_"),
                    mime="text/csv", key=f"dl_{row['list_id']}")

with tab_core:
    b1, b2 = st.columns([1, 2])
    budget = b1.number_input("포인트 예산", min_value=500, max_value=3000, value=2000, step=50)
    core_gen = b2.selectbox("장군 기준 (선택 시 그 장군 리스트의 통계 사용)",
                            ["전체 리스트"] + (list(gen_counts.index) if not gen_counts.empty else []),
                            key="core_gen")

    scope = d if core_gen == "전체 리스트" else d[d["list_id"].map(gen_of_list) == core_gen]
    scope_lists = scope["list_id"].nunique()
    su = scope.drop_duplicates(["list_id", "base_unit"])
    # 워스크롤 기준 포인트 우선, 없으면 관측 최소값(증강 미포함에 가장 가까움)
    pts_map = d.groupby("base_unit")["unit_points"].first()
    obs_min = d.groupby("base_unit")["points"].min()
    cand_u = (su.groupby("base_unit")
              .agg(채용리스트수=("list_id", "nunique"),
                   평균승수=("wins", "mean")).reset_index())
    cand_u["채용률"] = cand_u["채용리스트수"] / max(scope_lists, 1)
    cand_u["포인트"] = cand_u["base_unit"].map(pts_map).fillna(
        cand_u["base_unit"].map(obs_min))
    cand_u["역할"] = cand_u["base_unit"].map(role_map)
    cand_u = cand_u.dropna(subset=["포인트"]).sort_values(
        ["채용률", "평균승수"], ascending=False)

    # 채용률 높은 순으로 예산이 허용하는 만큼 누적 (규칙 검증 아님 — 통계 요약)
    picked_rows, spent = [], 0.0
    for _, r in cand_u.iterrows():
        if spent + r["포인트"] <= budget:
            picked_rows.append(r)
            spent += r["포인트"]
    core = pd.DataFrame(picked_rows)

    st.caption(f"기준 리스트 {scope_lists}개"
               + ("" if core_gen == "전체 리스트" else f" (장군: {core_gen})"))
    if core.empty:
        st.info("예산 안에 들어가는 유닛이 없습니다.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("제안 유닛 수", f"{len(core)}개")
        m2.metric("합계 포인트", f"{spent:.0f}pt", delta=f"잔여 {budget - spent:.0f}pt",
                  delta_color="off")
        m3.metric("평균 채용률", f"{core['채용률'].mean():.0%}")
        show = (core[["base_unit", "역할", "포인트", "채용률", "평균승수"]]
                .rename(columns={"base_unit": "유닛"}))
        st.dataframe(
            show.style.format({"포인트": "{:.0f}", "채용률": "{:.0%}", "평균승수": "{:.2f}승"}),
            hide_index=True, use_container_width=True)
        st.warning("**규칙 검증은 하지 않습니다** — 채용률 순으로 예산까지 채운 통계 요약이라 "
                   "연대 편성 규칙(Regiment Options)·유닛 수 제한·중복 제약을 반영하지 않습니다. "
                   "실제 리스트를 짤 때는 '실전 템플릿' 탭을 출발점으로 쓰고 빌더에서 검증하세요.")


# ---------------------------------------------------------------------------
# 원본 데이터 (표 보기 + 다운로드)
# ---------------------------------------------------------------------------

st.divider()
with st.expander(f"원본 데이터 보기 ({len(d)}개 유닛 행)"):
    show_cols = ["player", "event", "date", "result", "formation", "list_title",
                 "regiment", "unit", "points", "role", "notes"]
    st.dataframe(d[[c for c in show_cols if c in d.columns]],
                 hide_index=True, use_container_width=True)
    st.download_button("CSV 다운로드",
                       d.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{faction.replace(' ', '_')}_stats.csv", mime="text/csv")
