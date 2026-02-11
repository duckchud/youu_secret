from stock.stock_daily import WeeklyStockReport

BASE_DIR = r'W:/공용 드라이브/02. 재고/01. 재고현황 (일자별)'

if __name__ == "__main__":
    report = WeeklyStockReport(base_dir=BASE_DIR)
    report.run()