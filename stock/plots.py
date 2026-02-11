import io
import base64
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from typing import Callable


def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    return img_base64

def build_season_plot(df: pd.DataFrame, fmt_value: Callable[..., str],  ) -> str:
    """
    시즌별 재고 + CSC 수량/금액 그래프 → base64
    - 좌측 : 수량(만개)
    - 우측 : 금액(억원)
    - CSC 비중 라벨 포함
    - 반환 : base64 png
    """
    # 변수 지정
    in_season_label = None

    # =========================
    # 1️⃣ 시즌 요약 집계
    # =========================
    season_order = ["인시즌", "이월시즌", "올드시즌"]

    summary = (
        df.groupby("시즌구분_최종", as_index=False)
        .agg(
            season_qty=("수량", "sum"),
            season_price=("금액", "sum"),
            season_sku=("상품코드", lambda x: x.astype(str).str[3:13].nunique()),
            season_csc_qty=("csc_qty", "sum"),
            season_csc_price=("금액", lambda x: x[df.loc[x.index, "has_csc_claim"]].sum()),
        )
        .set_index("시즌구분_최종")
        .reindex(season_order)
        .reset_index()
        .fillna(0)
    )

    if in_season_label is None:
        in_season_codes = (
            df.loc[df["시즌구분_최종"] == "인시즌", "시즌"]
            .dropna()
            .unique()
        )
        in_season_label = ", ".join(sorted(in_season_codes)) if len(in_season_codes) else "-"

    # =========================
    # 2️⃣ 단위 변환
    # =========================
    qty_10k = summary["season_qty"] / 10_000
    csc_qty_10k = summary["season_csc_qty"] / 10_000
    amt_100m = summary["season_price"] / 100_000_000
    csc_amt_100m = summary["season_csc_price"] / 100_000_000
    csc_qty_ratio = (summary["season_csc_qty"] / summary["season_qty"] * 100).fillna(0)

    x = np.arange(len(summary))
    width = 0.35

    # =========================
    # 3️⃣ Plot
    # =========================
    fig, ax1 = plt.subplots(figsize=(5.6, 2.8))
    ax2 = ax1.twinx()

    # 수량 (전체)
    bars_qty = ax1.bar(
        x - width / 2,
        qty_10k,
        width,
        color="#595757",
        alpha=0.5,
        label="재고수량"
    )

    # 수량 (CSC)
    bars_csc_qty = ax1.bar(
        x - width / 2,
        csc_qty_10k,
        width,
        color="#595757",
        label="CSC 재고수량"
    )

    # 금액 (전체)
    bars_amt = ax2.bar(
        x + width / 2,
        amt_100m,
        width,
        color="#ed6c00",
        alpha=0.5,
        label="재고금액"
    )

    # 금액 (CSC)
    bars_csc_amt = ax2.bar(
        x + width / 2,
        csc_amt_100m,
        width,
        color="#ed6c00",
        label="CSC 재고금액"
    )

    # =========================
    # 4️⃣ 라벨
    # =========================
    offset_qty = max(qty_10k.max(), 1) * 0.03
    offset_amt = max(amt_100m.max(), 1) * 0.03

    # 핵심 공통 로직
    def draw_labels(ax, bars, labels, offset, **style):
        # Allow per-call fontsize override via style.
        fontsize = style.pop("fontsize", 8)
        for bar, label in zip(bars, labels):
            h = bar.get_height()
            if h > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h + offset,
                    label,
                    ha="center",
                    va="bottom",
                    fontsize=fontsize,
                    **style
                )

    # 수량 라벨 (CSC 비율 포함)
    qty_labels = [
        f"{q:,.0f}만개\n(CSC {r:.0f}%)" if r > 0 else f"{q:,.0f}만개"
        for q, r in zip(qty_10k, csc_qty_ratio)
    ]

    draw_labels(ax1, bars_qty, qty_labels, offset_qty)

    # CSC 수량 라벨
    csc_qty_labels = [
        f"CSC {fmt_value(q * 10_000, unit=10_000)}"
        if q > 0 else ""
        for q in csc_qty_10k
    ]
    draw_labels(ax1, bars_csc_qty, csc_qty_labels, offset_qty * 0.3, fontweight="bold", fontsize=6)

    # 전체 금액 라벨
    amt_labels = [
        f"{a:,.0f}억원" if a > 0 else ""
        for a in amt_100m
    ]
    draw_labels(ax2, bars_amt, amt_labels, offset_amt)

    # CSC 금액 라벨
    csc_amt_labels = [
        f"CSC {fmt_value(a * 100_000_000, unit=100_000_000, unit_label='억원', small_label='원')}"
        if a > 0 else ""
        for a in csc_amt_100m
    ]

    draw_labels(ax2, bars_csc_amt, csc_amt_labels, offset_amt * 0.4, color="#ed6c00", fontweight="bold", fontsize=6)

    # =========================
    # 5️⃣ 축 / 범례
    # =========================
    ax1.set_xticks(x)
    ax1.set_xticklabels(
        [
            (
                f"{row['시즌구분_최종']}\n"
                f"({in_season_label})\n"
                f"SKU {int(row['season_sku']):,}개"
                if row["시즌구분_최종"] == "인시즌"
                else f"{row['시즌구분_최종']}\nSKU {int(row['season_sku']):,}개"
            )
            for _, row in summary.iterrows()
        ],
        fontsize=8
    )


    ax1.set_ylabel("재고수량 (만개)", fontsize=8)
    ax2.set_ylabel("재고금액 (억원)", fontsize=8)

    legend = [
        Line2D([0], [0], color="#595757", alpha=0.5, lw=4, label="전체 재고수량"),
        Line2D([0], [0], color="#ed6c00", alpha=0.5, lw=4, label="전체 재고금액"),
        Line2D([0], [0], color="#595757", lw=4, label="CSC 재고수량"),
        Line2D([0], [0], color="#ed6c00", lw=4, label="CSC 재고금액"),
    ]

    ax1.legend(handles=legend, frameon=False, fontsize=8)
    ax1.set_ylim(0, qty_10k.max() * 1.4)
    ax2.set_ylim(0, amt_100m.max() * 1.2)
    plt.tight_layout()

    # =========================
    # 6️⃣ base64 변환
    # =========================
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)

    return img_base64
