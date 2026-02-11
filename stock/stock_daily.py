# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring
# flake8: noqa

"""
[ WeeklyStockReport ]
- 날짜 기준 설정
- 증감 계산
- CSC / 시즌 / Biz 구분
- 매장/창고 구분
- KPI 및 summary 계산
- 시각화 / HTML

"""

# =========================
# 기본 라이브러리
# =========================
import os
import datetime
import sys

from pathlib import Path
from functools import partial
from jinja2 import Environment, FileSystemLoader
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from dotenv import load_dotenv
load_dotenv()

from .email_utils import send_report_email
from .loaders import StockDataLoader
from .plots import build_season_plot

# email_utils.py가 있는 상위 폴더(code/reserve_stock)를 시스템 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# =========================
# 경로 설정
# =========================
DATA_BASE_DIR = r"W:/공용 드라이브/02. 재고/01. 재고현황 (일자별)"
TEMPLATE_DIR = Path(__file__).resolve().parents
DAILY_STOCK_TEMPLATE = "daily_stock_report.j2"

# =========================
# 리포트 발송 설정
# =========================
SEND_EMAIL_ENABLED = True # 이메일 발송을 원할 경우 True로 변경
RECIPIENT_EMAILS = [ "dae-yeon202201000105@dae-yeon.co.kr", "woodong.kim@dae-yeon.co.kr" ] # "hyunji.shim@dae-yeon.co.kr",
EMAIL_SUBJECT_TEMPLATE = "[{date:%y%m%d}] 주간 재고 데이터 현황 리포트"

# =========================
# 주간 리포트 클래스
# =========================
class WeeklyStockReport:
    """주간 재고 데이터 스냅샷 리포트를 생성하는 클래스"""

    # 공통 상수 생성
    SEASON_ORDER = {"SP": 0, "SU": 1, "FA": 2, "HO": 3}
    SEASON_MONTH_MAP = {
            "SP": (1, 3),
            "SU": (4, 6),
            "FA": (7, 9),
            "HO": (10, 12),
        }

    STOCK_KEY = ["매장코드", "매장명", "상품코드", "상품명", "시즌"]

    #----------------------------------------------
    # 재고 증감 계산 파이프라인 (Business Logic Layer)
    #----------------------------------------------
    def __init__(self, base_dir, snapshot_date=None):
        self.data_base_dir = base_dir
        self.snapshot_date = snapshot_date or datetime.date.today() # 기준 날짜
        self.last_year_date = self._get_same_day_last_year(self.snapshot_date)
        self.loader = StockDataLoader(base_dir) # loaders.py 클래스 사용

        # 임시 추가
        self.current_df: pd.DataFrame | None = None
        self.last_year_df: pd.DataFrame | None = None
        self.summary: pd.DataFrame | None = None

    def season_to_date_range(self, season_code: str):
        """
        시즌코드(예: 26SP)를 실제 시작일 / 종료일로 변환
        """
        year = 2000 + int(season_code[:2])
        season = season_code[2:]

        start_month, end_month = self.SEASON_MONTH_MAP[season]
        start_date = datetime.date(year, start_month, 1)

        # 종료일: 해당 월의 마지막 날
        if end_month == 12:
            end_date = datetime.date(year, 12, 31)
        else:
            end_date = datetime.date(year, end_month + 1, 1) - datetime.timedelta(days=1)

        return start_date, end_date

    def get_current_season(self) -> str:
        """
        시즌을 날짜로 자동 계산하는 함수
        """
        y = self.snapshot_date.year % 100
        m = self.snapshot_date.month

        if m <= 3:
            return f"{y:02d}SP"
        elif m <= 6:
            return f"{y:02d}SU"
        elif m <= 9:
            return f"{y:02d}FA"
        else:
            return f"{y:02d}HO"

    def normalize_season(self, season: str) -> str | None:
        """
        시즌 문자열을 'YYSP' 형태로 보정
        - 'HO' → 기준연도 HO
        - '25HO' → 그대로
        - 이상한 값 → None
        """
        if not isinstance(season, str):
            return None

        season = season.strip()

        # 정상 포맷: 25SP, 26HO
        if len(season) == 4 and season[:2].isdigit():
            return season

        # 시즌만 있는 경우: SP, SU, FA, HO
        if season in self.SEASON_ORDER:
            year = self.snapshot_date.year % 100
            return f"{year:02d}{season}"

        return None

    def season_to_index(self, season: str) -> int | None:
        season = self.normalize_season(season)
        if season is None:
            return None

        year = int(season[:2])
        quarter = self.SEASON_ORDER[season[2:]]
        return year * 4 + quarter

    def classify_season(self, season: str, base_season: str) -> str:
        """
        시즌을 분류하는 함수
        """
        season = self.normalize_season(season)
        base_season = self.normalize_season(base_season)

        # 파싱 실패 → 올드시즌
        if season is None or base_season is None:
            return "올드시즌"

        idx = self.season_to_index(season)
        base = self.season_to_index(base_season)

         # 파싱 실패 → 올드시즌
        if idx is None or base is None:
            return "올드시즌"

        diff = idx - base

        # 인시즌: 직전, 현재, 다음
        if diff in (-1, 0, 1):
            return "인시즌"

        # 이월시즌: 1년 이내 과거 (인시즌 제외)
        elif -4 <= diff <= -2:
            return "이월시즌"

        # 그 외
        else:
            return "올드시즌"

    # -------------------------
    # 작년 날짜 가져오기
    # -------------------------
    def _get_same_day_last_year(self, snapshot_date: datetime.date) -> datetime.date:
        """
        기준일(snapshot_date) 기준 전년 동일 날짜 반환
        (예: 2026-01-01 → 2025-01-01)
        """
        try:
            return snapshot_date.replace(year=snapshot_date.year - 1)
        except ValueError:
            # 2월 29일 → 2월 28일 보정
            return snapshot_date.replace(year=snapshot_date.year - 1, day=28)

    def _get_week_string(self):
        return self.snapshot_date.strftime("%y.%m.%d") + " 기준"

    # ==================================================
    # 내부 헬퍼 함수들 (delta 파이프라인 구성요소)
    # ==================================================
    def _build_event_delta(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        return (
            df
            .groupby(self.STOCK_KEY, as_index=False)
            .agg({"수량": "sum", "금액": "sum"})
        )

    def _enrich_unfulfilled_with_master(
        self,
        df: pd.DataFrame,
        monthly_df: pd.DataFrame
    ) -> pd.DataFrame:

        code_master = (
            monthly_df
            .groupby("상품코드", as_index=False)
            .agg(
                Biz=("Biz", "first"),
                단가=("단가_소비자가", "first")
            )
        )

        name_master = (
            monthly_df
            .groupby("상품명", as_index=False)
            .agg(
                Biz=("Biz", "first"),
                단가=("단가_소비자가", "first")
            )
        )

        df = df.merge(code_master, on="상품코드", how="left")

        mask = df["Biz"].isna()
        df.loc[mask, ["Biz", "단가"]] = (
            df.loc[mask, ["상품명"]]
            .merge(name_master, on="상품명", how="left")[["Biz", "단가"]]
            .values
        )

        return df

    def _build_unfulfilled_delta(
        self,
        unfulfilled_df: pd.DataFrame,
        monthly_adjustment_df: pd.DataFrame
    ) -> pd.DataFrame:

        df = (
            unfulfilled_df
            .groupby(self.STOCK_KEY, as_index=False)
            .agg({"미이행수량": "sum"})
        )

        df = self._enrich_unfulfilled_with_master(df, monthly_adjustment_df)

        return (
            df
            .assign(
                수량=lambda x: x["미이행수량"],
                금액=lambda x: x["미이행수량"] * x["단가"]
            )
            [self.STOCK_KEY + ["Biz", "수량", "금액"]]
        )

    def _build_csc_label(self, csc_claim_df: pd.DataFrame) -> pd.DataFrame:
        return (
            csc_claim_df
            .groupby(self.STOCK_KEY, as_index=False)
            .agg(csc_qty=("Zone_제외", "sum"))
            .assign(has_csc_claim=lambda x: x["csc_qty"] != 0)
        )

    # ==================================================
    # 재고 증감 계산 파이프라인 (증감 요인만 담당)
    # ==================================================
    def build_stock_delta_pipeline(
        self,
        store_transfer_from_df: pd.DataFrame,
        unfulfilled_order_df: pd.DataFrame,
        pending_inbound_df: pd.DataFrame,
        monthly_adjustment_df: pd.DataFrame,
        csc_claim_df: pd.DataFrame
    ) -> dict[str, pd.DataFrame]:

        delta_frames = []

        delta_frames.append(
            self._build_event_delta(store_transfer_from_df)
        )

        delta_frames.append(
            self._build_unfulfilled_delta(
                unfulfilled_order_df,
                monthly_adjustment_df
            )
        )

        if not pending_inbound_df.empty:
            delta_frames.append(
                self._build_event_delta(pending_inbound_df)
            )

        delta_all = pd.concat(delta_frames, ignore_index=True)

        delta_sum = (
            delta_all
            .groupby(self.STOCK_KEY, as_index=False)
            .sum()
            .rename(columns={
                "수량": "수량_delta",
                "금액": "금액_delta"
            })
        )

        csc_label = self._build_csc_label(csc_claim_df)

        return {
            "delta_all": delta_all,
            "delta_sum": delta_sum,
            "csc_label": csc_label
        }

    # ==================================================
    # 기준 재고 + 증감 → 최종 재고
    # ==================================================
    def build_final_stock(
        self,
        base_stock_snapshot_df: pd.DataFrame,
        delta_sum: pd.DataFrame
    ) -> pd.DataFrame:

        delta_sum = delta_sum.drop(columns=["Biz"], errors="ignore")

        stock_final = base_stock_snapshot_df.merge(
            delta_sum,
            on=self.STOCK_KEY,
            how="left"
        )

        stock_final["수량"] = (
            stock_final["수량"] + stock_final["수량_delta"].fillna(0)
        )

        stock_final["금액"] = (
            stock_final["금액"] + stock_final["금액_delta"].fillna(0)
        )

        return stock_final[self.STOCK_KEY + ["Biz", "수량", "금액"]]

    # ==================================================
    # CSC 라벨 부착 / 확정
    # ==================================================
    def attach_csc_label(
        self,
        stock_final: pd.DataFrame,
        csc_claim_df: pd.DataFrame
    ) -> pd.DataFrame:

        csc_label = self._build_csc_label(csc_claim_df)

        return (
            stock_final
            .merge(csc_label, on=self.STOCK_KEY, how="left")
            .assign(
                csc_qty=lambda x: x["csc_qty"].fillna(0),
                has_csc_claim=lambda x: x["has_csc_claim"].fillna(False)
            )
        )

    # 최종 데이터프레임 생성
    def build_stock_final_by_date(self, snapshot_date):
        dfs = self.loader.load_daily_inputs(snapshot_date)

        delta = self.build_stock_delta_pipeline(
            dfs["store_transfer"],
            dfs["unfulfilled_order"],
            dfs["pending_inbound"],
            dfs["monthly_adjustment"],
            dfs["csc_claim"],
        )

        stock_final = self.build_final_stock(
            dfs["base_stock"],
            delta["delta_sum"]
        )

        stock_final = self.attach_csc_label(stock_final, dfs["csc_claim"])
        stock_final["snapshot_date"] = snapshot_date
        return self.preprocess_final_stock(stock_final)

    def preprocess_final_stock(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 매장명 보정
        df.loc[df["매장명"] == "북부천", "매장명"] = "아이즈빌부평"

        # Biz 정규화
        df["Biz"] = np.where(
            df["Biz"].isin(["AP", "FW", "EQ"]),
            df["Biz"],
            "ETC"
        )

        # 매장 / 창고 구분
        df["store_type"] = np.where(
            df["매장명"].isin(["DCOM신세계닷", "창고북부천"]),
            "창고",
            "매장"
        )

        # CSC
        df["csc_qty"] = df.get("csc_qty", 0).fillna(0)
        df["has_csc_claim"] = df["csc_qty"] != 0

        # 시즌 분류
        base_season = self.get_current_season()
        df["시즌구분_최종"] = df["시즌"].apply(
            lambda x: self.classify_season(x, base_season)
        )

        return df

    # 정수 집계용 포맷 함수
    def _fmt_series(self, s: pd.Series, unit: int = 1) -> pd.Series:
        return (s / unit).round().astype("Int64").map(lambda x: f"{x:,}")

    # 조건부 수량/금액 포맷 함수 (값 단위)
    def _fmt_stock_qty(
        self,
        x: float,
        unit: int,
        fmt: str = "{:,.1f}",
        unit_label: str = "",
        small_label: str = ""
    ) -> str:
        if pd.isna(x) or x == 0:
            return f"0{small_label}"

        if abs(x) < unit:
            return f"{int(x):,}{small_label}"

        v = x / unit

        if abs(v) < 1:
            return f"{fmt.format(v)}{unit_label}"

        return f"{int(round(v)):,}{unit_label}"

    # KPI 비교 함수
    def build_kpi_summary(self, current_df: pd.DataFrame, last_year_df: pd.DataFrame) -> dict:
        """
        전체 KPI + 전년 대비 + CSC KPI 통합, SKU 기준: 상품코드[3:13]
        """
        def calc(df):
            return {
                "qty": df["수량"].sum(),
                "amt": df["금액"].sum(),
                "sku": df["상품코드"].str[3:13].nunique(),
            }

        cur = calc(current_df)
        prev = calc(last_year_df)

        # diff
        qty_diff = cur["qty"] - prev["qty"]
        amt_diff = cur["amt"] - prev["amt"]

        # CSC
        csc_df = current_df[current_df["has_csc_claim"]]
        csc_qty = csc_df["수량"].sum()
        csc_amt = csc_df["금액"].sum()
        csc_sku = csc_df["상품코드"].str[3:13].nunique()

        return {
            "snapshot_date": self.snapshot_date.strftime("%y.%m.%d"),
            "last_year_date": self.last_year_date.strftime("%y.%m.%d"),

            # 숫자만 반환 (단위 변환만)
            "qty_current": round(cur["qty"] / 10_000),
            "qty_last_year": round(prev["qty"] / 10_000),
            "qty_diff": round(qty_diff / 10_000),
            "qty_diff_rate": round(qty_diff / prev["qty"] * 100) if prev["qty"] else None,

            "amt_current": round(cur["amt"] / 100_000_000),
            "amt_last_year": round(prev["amt"] / 100_000_000),
            "amt_diff": round(amt_diff / 100_000_000),
            "amt_diff_rate": round(amt_diff / prev["amt"] * 100) if prev["amt"] else None,

            "sku_current": cur["sku"],
            "sku_last_year": prev["sku"],
            "sku_diff": cur["sku"] - prev["sku"],

            "csc_qty_current": round(csc_qty / 10_000),
            "csc_amt_current": round(csc_amt / 100_000_000),

            # CSC 원단위
            "csc_qty_raw" : csc_qty,         # 개
            "csc_amt_raw" : csc_amt,         # 원
            "csc_sku_current": csc_sku,
        }

    # 요약 데이터 생성
    def summarize_current_stock(self, final_stock_df: pd.DataFrame) -> dict:
        # 공통
        biz_order = ["AP", "FW", "EQ", "ETC"]
        csc_mask = final_stock_df["has_csc_claim"]

        # SKU 계산 공통 함수
        def sku_nunique(s: pd.Series) -> int:
            return s.astype(str).str[3:13].nunique()

        # ======================
        # Biz 요약
        # ======================
        biz_summary_df = (
            final_stock_df
            .groupby("Biz", as_index=False)
            .agg(
                total_qty=("수량", "sum"),
                total_amt=("금액", "sum"),
                total_sku=("상품코드", sku_nunique),

                # CSC는 has_csc_claim 기준
                csc_qty=("수량", lambda x: x[csc_mask.loc[x.index]].sum()),
                csc_amt=("금액", lambda x: x[csc_mask.loc[x.index]].sum()),
                csc_sku=("상품코드", lambda x: sku_nunique(x[csc_mask.loc[x.index]])),
            )
        )

        biz_summary_df["Biz"] = pd.Categorical(
            biz_summary_df["Biz"], categories=biz_order, ordered=True
        )
        biz_summary_df = biz_summary_df.sort_values("Biz")

        # 포맷
        biz_summary_df["재고수량_만개"] = self._fmt_series(biz_summary_df["total_qty"], 10_000)
        biz_summary_df["재고금액_억원"] = self._fmt_series(biz_summary_df["total_amt"], 100_000_000)
        biz_summary_df["SKU_개"] = self._fmt_series(biz_summary_df["total_sku"])

        biz_summary_df["비율(%)"] = (
            biz_summary_df["total_qty"] / biz_summary_df["total_qty"].sum() * 100
        ).round().astype("Int64")

        # CSC (소수점 허용)
        biz_summary_df["CSC수량_만개"] =  biz_summary_df["csc_qty"].map(
            lambda x: self._fmt_stock_qty(
                x,
                unit=10_000,
                fmt="{:,.1f}",
                unit_label="만개",
                small_label="개",
            )
        )
        biz_summary_df["CSC금액_억원"] = biz_summary_df["csc_amt"].map(
            lambda x: self._fmt_stock_qty(
                x,
                unit=100_000_000,
                fmt="{:,.1f}",
                unit_label="억원",
                small_label="원",
            )
        )
        biz_summary_df["CSC_SKU_개"] = biz_summary_df["csc_sku"].astype(int).map("{:,}".format)

        # ======================
        # 시즌 요약
        # ======================
        season_order = ["인시즌", "이월시즌", "올드시즌"]

        season_summary_df = (
            final_stock_df
            .groupby("시즌구분_최종", as_index=False)
            .agg(
                season_qty=("수량", "sum"),
                season_price=("금액", "sum"),
                season_sku=("상품코드", sku_nunique),

                season_csc_qty=("csc_qty", "sum"),
                season_csc_price=("금액", lambda x: x[csc_mask.loc[x.index]].sum()),
            )
            .set_index("시즌구분_최종")
            .reindex(season_order)
            .reset_index()
        )

        season_summary_df["재고수량_만개"] = self._fmt_series(season_summary_df["season_qty"], 10_000)
        season_summary_df["재고금액_억원"] = self._fmt_series(season_summary_df["season_price"], 100_000_000)
        season_summary_df["SKU_개"] = self._fmt_series(season_summary_df["season_sku"])

        season_summary_df["CSC수량_만개"] = season_summary_df["season_csc_qty"].map(
            lambda x: self._fmt_stock_qty(
                x,
                unit=10_000,
                fmt="{:,.1f}",
                unit_label="만개",
                small_label="개",
            )
        )
        season_summary_df["CSC금액_억원"] = season_summary_df["season_csc_price"].map(
            lambda x: self._fmt_stock_qty(
                x,
                unit=100_000_000,
                fmt="{:,.1f}",
                unit_label="억원",
                small_label="원",
            )
        )


        # ======================
        # 매장 / 창고 요약
        # ======================
        store_wh_summary_df = (
            final_stock_df
            .groupby("store_type", as_index=False)
            .agg(
                stock_qty=("수량", "sum"),
                stock_price=("금액", "sum"),
                stock_sku=("상품코드", sku_nunique),
            )
        )

        store_wh_summary_df["재고수량_만개"] = self._fmt_series(store_wh_summary_df["stock_qty"], 10_000)
        store_wh_summary_df["재고금액_억원"] = self._fmt_series(store_wh_summary_df["stock_price"], 100_000_000)
        store_wh_summary_df["SKU_개"] = self._fmt_series(store_wh_summary_df["stock_sku"])

        return {
            # HTML
            "biz_summary_records": biz_summary_df.to_dict("records"),
            "season_summary_records": season_summary_df.to_dict("records"),
            "store_wh_summary_records": store_wh_summary_df.to_dict("records"),

            # Plot / 분석
            "biz_summary_df": biz_summary_df,
            "final_season_summary_df": season_summary_df,
            "store_wh_summary_df": store_wh_summary_df,
        }

    # 시즌 구분별 : CSC 시즌별 집계 만들기
    def build_season_csc_summary(self, final_stock_df: pd.DataFrame) -> pd.DataFrame:
        """
        시즌별 CSC 수량 집계 (창고 기준)
        """
        return (
            final_stock_df
            .loc[
                (final_stock_df["store_type"] == "창고") &
                (final_stock_df["has_csc_claim"])
            ]
            .groupby("시즌구분_최종", as_index=False)
            .agg(season_csc_qty=("csc_qty", "sum"))
        )

    # 매장/창고별 데이터 테이블로 요약
    def summarize_store_wh_compare(self, current_final_stock_df: pd.DataFrame, last_year_final_stock_df: pd.DataFrame) -> list[dict]:
        def agg(df):
            return (
                df.groupby("store_type")
                .agg(
                    qty=("수량", "sum"),
                    amt=("금액", "sum"),
                    sku=("상품코드", lambda x: (x.astype(str).str[3:13].nunique())),
                )
            )

        cur = agg(current_final_stock_df)
        prev = agg(last_year_final_stock_df)

        result = []

        for store in cur.index:
            cur_row = cur.loc[store]
            prev_row = prev.loc[store] if store in prev.index else None

            qty_rate = (
                (cur_row.qty - prev_row.qty) / prev_row.qty * 100
                if prev_row is not None and prev_row.qty != 0 else None
            )

            amt_rate = (
                (cur_row.amt - prev_row.amt) / prev_row.amt * 100
                if prev_row is not None and prev_row.amt != 0 else None
            )

            result.append({
                "store_type": store,
                "qty_current": self._fmt_series(pd.Series([cur_row.qty]), unit=10_000).iloc[0],
                "qty_rate": round(qty_rate) if qty_rate is not None else None,
                "amt_current":self._fmt_series(pd.Series([cur_row.amt]), unit=100_000_000).iloc[0],
                "amt_rate": round(amt_rate) if amt_rate is not None else None,
                "sku_current":self._fmt_series(pd.Series([cur_row.sku]), unit=1).iloc[0],
            })

        return result

    # 최종 단계 통합
    def _analyze(self, current_df, last_year_df) -> dict:
        return {
            "snapshot_date": self.snapshot_date.strftime("%y.%m.%d"),
            "last_year_date": self.last_year_date.strftime("%y.%m.%d"),

            "kpi_summary": self.build_kpi_summary(current_df, last_year_df),
            **self.summarize_current_stock(current_df),

            "season_plot_img": build_season_plot(
                current_df,
                fmt_value=partial(
                self._fmt_stock_qty,
                unit=10_000,
                fmt="{:,.1f}",
                unit_label="만개",
                small_label="개",
                ),
            ),
            "store_wh_compare": self.summarize_store_wh_compare(current_final_stock_df=current_df,last_year_final_stock_df=last_year_df),
        }

    def render_html(self, summary: dict):
        """
        분석 결과(summary)를 HTML 리포트로 렌더링
        """

        env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=True
        )

        template = env.get_template(DAILY_STOCK_TEMPLATE)

        kpi = summary["kpi_summary"]

        html = template.render(
            week_str=self._get_week_string(),
            snapshot_date=summary["snapshot_date"],
            last_year_date=kpi["last_year_date"],

            qty_current=kpi["qty_current"],
            qty_last_year=kpi["qty_last_year"],
            qty_diff=kpi["qty_diff"],
            qty_diff_rate=kpi["qty_diff_rate"],

            amt_current=kpi["amt_current"],
            amt_last_year=kpi["amt_last_year"],
            amt_diff=kpi["amt_diff"],
            amt_diff_rate=kpi["amt_diff_rate"],

            sku_current=kpi["sku_current"],
            sku_last_year=kpi["sku_last_year"],
            sku_diff=kpi["sku_diff"],

            # CSC KPI
            csc_qty_current=kpi["csc_qty_current"],
            csc_amt_current=kpi["csc_amt_current"],
            csc_sku_current=kpi["csc_sku_current"],

            # CSC (단위 판단용)
            csc_qty_raw=kpi["csc_qty_raw"],
            csc_amt_raw=kpi["csc_amt_raw"],


            biz_summary=summary["biz_summary_records"],
            store_wh_compare=summary["store_wh_compare"],
            season_summary=summary["season_summary_records"],
            season_plot_img=summary["season_plot_img"],
        )

        return html

    def run(self):
        try:
            # 1️⃣ 현재 / 작년 날짜
            current_date = self.snapshot_date
            last_year_date = self._get_same_day_last_year(current_date)

            # 2️⃣ 데이터 생성 (같은 로직, 날짜만 다름)
            current_df = self.build_stock_final_by_date(current_date)
            last_year_df = self.build_stock_final_by_date(last_year_date)

            self.current_df = current_df
            self.last_year_df = last_year_df
            summary = self._analyze(current_df, last_year_df)
            self.summary = summary

            # 날짜 상태 설정(여기서만 설정)
            self.snapshot_date = current_date
            self.last_year_date = last_year_date

            # 3️⃣ 분석
            summary = self._analyze(current_df, last_year_df)

            # 4️⃣ HTML 렌더링
            html_body = self.render_html(summary)

            # 5️⃣ 이메일 발송
            if SEND_EMAIL_ENABLED:
                send_report_email(
                    recipient_email=",".join(RECIPIENT_EMAILS),
                    subject=EMAIL_SUBJECT_TEMPLATE.format(date=self.snapshot_date),
                    html_body=html_body
                )

            print("✅ 리포트 생성 및 이메일 발송 완료")

        except FileNotFoundError as e:
            print(f"❌ 파일을 찾을 수 없습니다: {e}")
