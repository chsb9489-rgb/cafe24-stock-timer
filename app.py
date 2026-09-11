import streamlit as st
import pandas as pd
import datetime
import io

st.set_page_config(
    page_title="재고 소진 예측 & 발주 알림 타이머",
    page_icon="⏰",
    layout="wide"
)

st.title("⏰ 재고 소진 예측 & 자동 발주 알림 타이머")
st.caption("최근 판매 속도를 분석하여 품절 임박 D-Day를 예측하고 공급처 전달용 발주서를 자동으로 생성합니다.")

with st.expander("ℹ️ 사용 가이드 및 유의사항"):
    st.markdown("""
    ### 📌 **필요한 파일**
    1. **현재 재고 목록 엑셀**: `상품명`, `현재재고` 열 포함
    2. **최근 판매 내역 엑셀**: `상품명`, `수량`, `주문일자` 열 포함

    ### 💡 **주요 기능**
    * **일평균 판매량 분석**: 설정한 기간(기본 14일) 동안의 판매 속도 측정
    * **품절 D-Day 예측**: (현재재고 ÷ 일평균판매량) 기반 소진 예상일 산출
    * **임박/품절 경고 및 발주서 자동 생성**: 안전재고 기준 미달 상품을 자동 발주 목록으로 정제
    """)

# 사이드바 설정
with st.sidebar:
    st.header("⚙️ 예측 및 발주 설정")
    analysis_days = st.number_input("분석 기준 기간 (일)", min_value=1, value=14, step=1)
    safety_days = st.number_input("목표 안전 재고 유지 기간 (일)", min_value=1, value=30, step=1)
    alert_threshold_days = st.number_input("발주 알림 경고 기준 (D-Day 이하)", min_value=1, value=7, step=1)

col1, col2 = st.columns(2)
with col1:
    stock_file = st.file_uploader("1. 현재 재고 엑셀 (.xlsx, .xls)", type=["xlsx", "xls"])
with col2:
    sales_file = st.file_uploader("2. 최근 판매 내역 엑셀 (.xlsx, .xls)", type=["xlsx", "xls"])

if stock_file is not None and sales_file is not None:
    try:
        df_stock = pd.read_excel(stock_file)
        df_sales = pd.read_excel(sales_file)

        # 컬럼 유연 매핑
        stock_prod_col = next((c for c in ['상품명', '상품명(필수)', '품목명'] if c in df_stock.columns), None)
        stock_qty_col = next((c for c in ['현재재고', '재고수량', '재고', '수량'] if c in df_stock.columns), None)

        sales_prod_col = next((c for c in ['상품명', '상품명(필수)', '품목명'] if c in df_sales.columns), None)
        sales_qty_col = next((c for c in ['수량', '주문수량', '구매수량'] if c in df_sales.columns), None)

        if not stock_prod_col or not stock_qty_col:
            st.error("❌ 재고 엑셀에서 '상품명' 및 '현재재고' 열을 찾을 수 없습니다.")
            st.stop()

        if not sales_prod_col or not sales_qty_col:
            st.error("❌ 판매 엑셀에서 '상품명' 및 '수량' 열을 찾을 수 없습니다.")
            st.stop()

        # 전처리
        df_stock[stock_qty_col] = pd.to_numeric(df_stock[stock_qty_col], errors='coerce').fillna(0)
        df_sales[sales_qty_col] = pd.to_numeric(df_sales[sales_qty_col], errors='coerce').fillna(0)

        # 상품별 판매량 집계
        sales_sum = df_sales.groupby(sales_prod_col)[sales_qty_col].sum().reset_index()
        sales_sum.rename(columns={sales_prod_col: '상품명', sales_qty_col: '총판매수량'}, inplace=True)

        # 재고 데이터 합치기
        df_stock_clean = df_stock[[stock_prod_col, stock_qty_col]].copy()
        df_stock_clean.rename(columns={stock_prod_col: '상품명', stock_qty_col: '현재재고'}, inplace=True)

        merged = pd.merge(df_stock_clean, sales_sum, on='상품명', how='left').fillna(0)

        # 계산 로직
        merged['일평균판매량'] = (merged['총판매수량'] / analysis_days).round(2)
        
        # 소진 일수 계산 (0 나눔 방지)
        merged['품절예상일수(D-Day)'] = merged.apply(
            lambda x: round(x['현재재고'] / x['일평균판매량'], 1) if x['일평균판매량'] > 0 else 999, axis=1
        )
        
        # 필요 발주 수량 (안전재고 유지 기간 기준)
        merged['목표재고량'] = (merged['일평균판매량'] * safety_days).round(0)
        merged['추천발주수량'] = merged.apply(
            lambda x: max(0, int(x['목표재고량'] - x['현재재고'])), axis=1
        )

        # 상태 구분
        def get_status(d_day):
            if d_day <= 0:
                return "🔴 품절"
            elif d_day <= alert_threshold_days:
                return "🟡 발주 필요 (임박)"
            else:
                return "🟢 양호"

        merged['상태'] = merged['품절예상일수(D-Day)'].apply(get_status)

        # 요약 메트릭
        st.divider()
        st.subheader("📊 재고 소진 현황 요약")

        out_of_stock = (merged['상태'] == "🔴 품절").sum()
        reorder_needed = (merged['상태'] == "🟡 발주 필요 (임박)").sum()
        healthy = (merged['상태'] == "🟢 양호").sum()

        m1, m2, m3 = st.columns(3)
        m1.metric("🔴 품절 상품", f"{out_of_stock} 개")
        m2.metric("🟡 발주 필요 (D-Day 임박)", f"{reorder_needed} 개")
        m3.metric("🟢 안전 재고 상품", f"{healthy} 개")

        st.divider()
        st.subheader("📋 전체 상품 소진 예측 리포트")
        
        # 정렬: 품절/임박 상품이 상단으로
        result_df = merged.sort_values(by='품절예상일수(D-Day)', ascending=True)
        st.dataframe(result_df, use_container_width=True)

        # 발주 대상만 추출
        order_target = result_df[result_df['추천발주수량'] > 0][['상품명', '현재재고', '일평균판매량', '품절예상일수(D-Day)', '추천발주수량']]

        st.divider()
        st.subheader("📥 자동 생성 발주서 다운로드")
        st.caption("※ 추천 발주 수량이 1개 이상인 상품만 정제하여 엑셀 형태로 추출합니다.")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            result_df.to_excel(writer, sheet_name='전체재고소진예측', index=False)
            order_target.to_excel(writer, sheet_name='자동발주서', index=False)

        st.download_button(
            label="📄 자동 생성 발주서 엑셀 다운로드",
            data=output.getvalue(),
            file_name=f"auto_order_sheet_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"데이터 처리 중 오류가 발생했습니다: {e}")
else:
    st.info("👆 현재 재고 엑셀과 최근 판매 내역 엑셀 두 파일을 모두 업로드해 주세요.")