"""
[ loaders.py ]
- 엑셀 / CSV 읽기
- 컬럼명 정리
- 타입 캐스팅
- 원본 데이터 형태 보존
- 특정 날짜 기준, 하루치 재고 관련 입력 데이터 로드

"""
# =========================
# 기본 라이브러리
# =========================
import os
import glob
import pandas as pd

class StockDataLoader:
    """
    주간 재고 리포트에 필요한 원천 데이터를
    파일에서 읽어 DataFrame으로 만드는 클래스
    """
    # 필수 파일용
    @staticmethod
    def find_required_file(pattern):
        """필수 파일을 검색하고 없으면 오류 발생"""
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"❌ 필수 파일 없음: {pattern}")
        return files[0]

    # 선택 파일용
    @staticmethod
    def find_optional_file(pattern):
        """선택 파일을 검색하고 없으면 None 반환"""
        files = glob.glob(pattern)
        if not files:
            print(f"⚠️ 파일 없음 → 스킵: {pattern}")
            return None
        return files[0]

    # apply_column_map : 공통 컬럼 처리 함수(monthly_adjustment_df 제외), 공통 사용이라 메서드 선언
    @staticmethod
    def apply_column_map(
        df,
        column_map,
        select_cols=None,
        drop_missing=False
    ):
        """
        1. 컬럼 공백 정리
        2. 컬럼명 표준화
        3. 필요한 컬럼만 선택
        """
        df = df.copy()

        # 1. 컬럼명 정규화
        df.columns = (
            df.columns
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )

        # 2. 컬럼 매핑
        df = df.rename(columns=column_map)

        # 3. 컬럼 선택
        if select_cols is not None:
            exist_cols = [c for c in select_cols if c in df.columns]
            df = df[exist_cols]

            if drop_missing:
                missing = set(select_cols) - set(exist_cols)
                if missing:
                    raise KeyError(f"누락 컬럼: {missing}")

        return df

    # 공통컬럼 세트 정의
    BASE_COLS = ["매장명", "매장코드", "상품코드", "상품명", "시즌"]
    STOCK_COLS = BASE_COLS + ["Biz", "수량", "금액"]

    # 컬럼명 매핑
    COLUMN_MAP = {
        # 매장
        "매장명": "매장명",
        "출고매장": "매장명",
        "TO매장명": "매장명",
        "매장번호": "매장코드",
        "매장코드": "매장코드",
        "TO매장코드": "매장코드",
        "매장코드.1" : "매장코드",

        # 상품
        "상품코드[GPC-STYLE-COLOR-SIZE]" : "상품코드",
        "상품코드" : "상품코드",
        "상품명" : "상품명",

        # 시즌 / Biz
        "시즌": "시즌",
        "SEASON": "시즌",
        "현시즌코드": "시즌",
        "시즌코드": "시즌",
        "Biz": "Biz",
        "BIZ": "Biz",
        "BIZ구분": "Biz",

        # 수량
        "가용재고": "수량",
        "이동확정수량": "수량",
        "본사출고수량": "수량",

        # 금액
        "소비자 총액": "금액",
        "이동금액": "금액",
        "소비자가": "금액",
    }

    def __init__(self, base_dir):
        self.base_dir = base_dir


    # base_stock_snapshot_df : 기준 재고 스냅샷
    def load_stock_detail_excel(self, file_path: str) -> pd.DataFrame:
        """
        타점현재고현황_상세정보 엑셀 파일을 읽어
        리포트용 DataFrame으로 정제하여 반환
        (공유드라이브 읽기 전용)
        """
        # 1. 엑셀 로드
        df_raw_base_stock_snapshot_df = pd.read_excel(
            file_path,
            engine="calamine",
            usecols=[
                 "매장명", "매장이름", "상품코드[GPC-STYLE-COLOR-SIZE]", " 상품명", "시즌", "가용재고", "소비자 총액 ", "Biz"
            ]
        )

        # 2. 컬럼명 표준화 (필수 컬럼 검사 없이)
        base_stock_snapshot_df = StockDataLoader.apply_column_map(
            df_raw_base_stock_snapshot_df,
            column_map=self.COLUMN_MAP,
            select_cols=None,  # 모든 컬럼을 우선 유지
            drop_missing=False
        )

        # 3. '매장코드' 생성 (이 단계에서 컬럼이 만들어짐)
        mask = base_stock_snapshot_df["매장명"].str.contains(r"\[.*?\]", na=False)
        extracted_df = base_stock_snapshot_df.loc[mask, "매장명"].str.extract(r"\[(.*?)\]\s*(.*)")
        if not extracted_df.empty:
            base_stock_snapshot_df.loc[mask, "매장코드"] = extracted_df[0]
            base_stock_snapshot_df.loc[mask, "매장명"] = extracted_df[1]

        base_stock_snapshot_df["매장명"] = base_stock_snapshot_df["매장명"].str.strip()

        # 4. 최종적으로 필요한 컬럼 선택 및 검사
        missing_cols = set(self.STOCK_COLS) - set(base_stock_snapshot_df.columns)
        if missing_cols:
            raise KeyError(f"누락 컬럼: {missing_cols}")
        base_stock_snapshot_df = base_stock_snapshot_df[self.STOCK_COLS]

        # 5. 타입 지정 (표준 컬럼 기준)
        base_stock_snapshot_df = base_stock_snapshot_df.astype({
            "매장명": "string",
            "매장코드": "string",
            "상품코드": "string",
            "상품명": "string",
            "시즌": "string",
            "Biz": "string",
            "수량": "Int32",
            "금액": "Int64"
        })

        return base_stock_snapshot_df

    # store_transfer_from_df : 매장간 이동 (출고 기준)
    def load_store_transfer_out_excel(self, file_path: str) -> pd.DataFrame:
        """매장간 이동(출고 기준) 데이터 로드"""
        # 데이터 로드
        df_raw_store_transfer_from_df = pd.read_excel(
            file_path,
            engine="calamine",
            usecols=[
                "BIZ", "SEASON", "상품코드", "상품명", "이동확정수량", "이동금액", "출고매장", "매장코드.1"
            ]
        )

        # 공통 컬럼 표준화
        store_transfer_from_df = StockDataLoader.apply_column_map(
            df_raw_store_transfer_from_df,
            column_map=self.COLUMN_MAP,
            select_cols=self.STOCK_COLS,
            drop_missing=True
        )

        # 타입 지정
        store_transfer_from_df = store_transfer_from_df.astype({
            "매장명": "string",     # 출고매장 → 매장명
            "매장코드": "string",   # 매장코드.1 → 매장코드
            "상품코드": "string",
            "상품명": "string",
            "시즌": "string",
            "Biz": "string",
            "수량": "Int32",        # 이동확정수량 → 수량
            "금액": "Int64"         # 이동금액 → 금액
        })

        return store_transfer_from_df

    # unfulfilled_order_df : 지시 / 이행 현황 (입고 기준) -> (Biz, 금액 없음)
    def load_order_fulfillment_excel(self, file_path: str) -> pd.DataFrame:
        """지시/이행 현황 데이터 로드 및 미이행 수량 계산"""
        # 데이터 로드
        df_raw_unfulfilled_order_df = pd.read_excel(
            file_path,
            engine="calamine",
            usecols=[
                "TO매장코드", "TO매장명", "시즌", "상품코드", "상품명", "지시수량", "이행수량", "거절수량"
            ]
        )

        # 공통 컬럼 표준화
        unfulfilled_order_df = StockDataLoader.apply_column_map(
            df_raw_unfulfilled_order_df,
            column_map=self.COLUMN_MAP,
            select_cols=self.BASE_COLS + ["지시수량", "이행수량", "거절수량"],
            drop_missing=True
        )

        # 타입 지정
        unfulfilled_order_df = unfulfilled_order_df.astype({
            "매장명": "string",
            "매장코드": "string",
            "상품코드": "string",
            "상품명": "string",
            "시즌": "string",
            "지시수량": "Int32",
            "이행수량": "Int32",
            "거절수량": "Int32"
        })

        # 4️⃣ unfulfilled_order_df 전용 전처리: 미이행 수량 계산
        unfulfilled_order_df = unfulfilled_order_df.copy()

        unfulfilled_order_df["미이행수량"] = (
            unfulfilled_order_df["지시수량"]
            - unfulfilled_order_df["이행수량"]
            - unfulfilled_order_df["거절수량"]
            )

        # 미이행 수량이 0인 행 제거
        unfulfilled_order_df = unfulfilled_order_df[unfulfilled_order_df["미이행수량"] != 0]

        # 5️⃣ unfulfilled_order_df 전용 전처리: 상품코드 정규화
        def normalize_product_code(code):
            if pd.isna(code):
                return None

            x = str(code).strip().replace(" ", "")

            # 기대 포맷: 2 + 6 + 3 + 3 = 14자리
            if len(x) == 14:
                return f"{x[:2]}-{x[2:8]}-{x[8:11]}-  {x[11:]}"
            return code  # 정규화 실패 시 원본 유지

        unfulfilled_order_df["상품코드"] = unfulfilled_order_df["상품코드"].apply(normalize_product_code)
        return unfulfilled_order_df

    # pending_inbound_df : 본사 출고 (입고 미확정)
    def load_hq_shipment_pending_excel(self, file_path: str) -> pd.DataFrame:
        """본사 출고(입고 미확정) 데이터 로드"""

        # 데이터 로드
        df_raw_pending_inbound_df = pd.read_excel(
            file_path,
            engine="calamine",
            usecols=[
                "매장번호", "매장명", "BIZ구분", "현시즌코드", "상품코드", "상품명", "본사출고수량", "소비자가"
            ]
        )

        # 공통 컬럼 표준화
        pending_inbound_df = StockDataLoader.apply_column_map(
            df_raw_pending_inbound_df,
            column_map=self.COLUMN_MAP,
            select_cols=self.STOCK_COLS,
            drop_missing=True
        )

        # 타입 지정
        pending_inbound_df = pending_inbound_df.astype({
            "매장명": "string",
            "매장코드": "string",   # 매장번호 → 매장코드
            "상품코드": "string",
            "상품명": "string",
            "시즌": "string",
            "Biz": "string",
            "수량": "Int32",        # 본사출고수량 → 수량
            "금액": "Int64"         # 소비자가 → 금액
        })

        return pending_inbound_df

    # monthly_adjustment_df : 월수불 (반품 / CSC / 클레임)
    def load_monthly_adjustment_csv(self, file_path: str) -> pd.DataFrame:
        """월수불(CSC/클레임) 데이터 로드"""

        # CSV 로드
        df_raw_monthly_adjustment_df = pd.read_csv(
            file_path,
            encoding="cp949",
            low_memory=False,
            usecols=[
                "매장코드", "매장명", "Biz",
                "상품코드", "상 품 명",
                "소비자가", "시즌코드",
                "CSC반품", "클레임"
            ],
            dtype={
                "매장코드": "string",
                "매장명": "string",
                "Biz": "string",
                "상품코드": "string",
                "상 품 명": "string",
                "소비자가": "Int64",
                "시즌코드": "string",
                "CSC반품": "Int32",
                "클레임": "Int64",
            }
        )

        # 마지막 합계행 제거
        monthly_adjustment_df = df_raw_monthly_adjustment_df.iloc[:-1].copy()

        # 컬럼명 정리 (공백 제거 + 명시적 리네이밍)
        monthly_adjustment_df = monthly_adjustment_df.rename(columns={
            "상 품 명": "상품명",
            "시즌코드": "시즌",
            "소비자가": "단가_소비자가"
        })

        # 필요한 컬럼만 명시적으로 선택
        monthly_adjustment_df = monthly_adjustment_df[
            [
                "매장명",
                "매장코드",
                "상품코드",
                "상품명",
                "시즌",
                "Biz",
                "CSC반품",
                "클레임",
                "단가_소비자가"
            ]
        ]

        # 타입 재확인
        monthly_adjustment_df = monthly_adjustment_df.astype({
            "매장명": "string",
            "매장코드": "string",
            "상품코드": "string",
            "상품명": "string",
            "시즌": "string",
            "Biz": "string",
            "CSC반품": "Int32",
            "클레임": "Int64",
            "단가_소비자가": "Int64"
        })

        return monthly_adjustment_df

    # csc_claim_df : monthly_adjustment_df 에서 CSC, 클레임만 있는 데이터만 추출
    def build_csc_claim_df(self, monthly_adjustment_df: pd.DataFrame) -> pd.DataFrame:
        """
        monthly_adjustment_df(월수불 원본)에서 CSC / 클레임 발생 데이터만 추출
        """
        csc_claim_df = monthly_adjustment_df.loc[
            (monthly_adjustment_df["CSC반품"] != 0) | (monthly_adjustment_df["클레임"] != 0)
        ].copy()

        csc_claim_df["Zone_제외"] = csc_claim_df["CSC반품"] + csc_claim_df["클레임"]

        return csc_claim_df

    def empty_stock_df(self) -> pd.DataFrame:
        """선택 파일이 없을 때 사용하는 빈 재고 DataFrame"""
        return pd.DataFrame(
            columns=["매장명", "매장코드", "상품코드", "상품명", "시즌", "Biz", "수량", "금액"]
        )

    # 하루치 재고 관련 입력 데이터 로드 험수
    def load_daily_inputs(self, snapshot_date) -> dict:
        """
        특정 날짜 기준, 하루치 재고 관련 입력 데이터 로드
        (I/O 전담)
        """

        d = snapshot_date
        base_path = os.path.join(
            self.base_dir,
            str(d.year),
            f"{d.month}월",
            d.strftime("%m%d")
        )

        base_stock_snapshot_df = self.load_stock_detail_excel(
            self.find_required_file(
                os.path.join(base_path, "타점현재고현황_상세정보_*.xlsx")
            )
        )

        store_transfer_from_df = self.load_store_transfer_out_excel(
            self.find_required_file(
                os.path.join(base_path, "매장간이동_FROM확정_*.xlsx")
            )
        )

        unfulfilled_order_df = self.load_order_fulfillment_excel(
            self.find_required_file(
                os.path.join(base_path, "지시이행현황_*.xlsx")
            )
        )

        monthly_adjustment_df = self.load_monthly_adjustment_csv(
            self.find_required_file(
                os.path.join(base_path, "카테고리월수불_*.csv")
            )
        )

        path_pending = self.find_optional_file(
            os.path.join(base_path, "입고미확정_*.xlsx")
        )

        pending_inbound_df = (
            self.load_hq_shipment_pending_excel(path_pending)
            if path_pending else self.empty_stock_df()
        )

        csc_claim_df = self.build_csc_claim_df(monthly_adjustment_df)

        return {
            "base_stock": base_stock_snapshot_df,
            "store_transfer": store_transfer_from_df,
            "unfulfilled_order": unfulfilled_order_df,
            "pending_inbound": pending_inbound_df,
            "monthly_adjustment": monthly_adjustment_df,
            "csc_claim": csc_claim_df,
        }
