import pandas as pd
import streamlit as st
import plotly.graph_objects as go

REQUIRED_COLUMNS = [
    "账户名称",
    "证券公司名称",
    "交易日期",
    "证券简称",
    "买卖标志",
    "成交数量",
]

COLUMN_ALIASES = {
    "账户名称": ["账户名称", "account_name", "account"],
    "证券公司名称": ["证券公司名称", "broker_name", "券商名称", "证券公司"],
    "交易日期": ["交易日期", "trade_date", "date"],
    "证券简称": ["证券简称", "security_name", "stock_name", "简称"],
    "买卖标志": ["买卖标志", "trade_flag", "bs_flag", "direction"],
    "成交数量": ["成交数量", "trade_quantity", "quantity"],
}

st.set_page_config(page_title="指定标的持仓变动分析", layout="wide")
st.title("指定标的持仓变动可视化")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    column_map = {}
    for col in df.columns:
        name = str(col).strip()
        normalized = None
        for canonical, aliases in COLUMN_ALIASES.items():
            if name == canonical or name in aliases:
                normalized = canonical
                break
        column_map[col] = normalized or name
    return df.rename(columns=column_map)


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        raise ValueError("请先上传证券流水文件。")

    file_name = uploaded_file.name.lower()
    if file_name.endswith(".csv"):
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
    elif file_name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("仅支持 CSV / XLSX / XLS 文件格式。")

    df = normalize_columns(df)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"缺少必要字段：{', '.join(missing)}")
    return df


def normalize_flag(value):
    if pd.isna(value):
        return None
    s = str(value).strip().upper()
    mapping = {
        "B": "B",
        "BUY": "B",
        "BUYING": "B",
        "买": "B",
        "买入": "B",
        "S": "S",
        "SELL": "S",
        "卖": "S",
        "卖出": "S",
    }
    return mapping.get(s)


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result.columns = [str(c).strip() for c in result.columns]

    # 删除整行为空的记录
    result = result.dropna(how='all')

    for col in ["账户名称", "证券公司名称", "证券简称", "买卖标志"]:
        if col in result.columns:
            result[col] = result[col].fillna("").astype(str).str.strip()

    if result["账户名称"].str.strip().eq("").any():
        raise ValueError("账户名称中存在空值，请检查原始数据。")

    result["交易日期"] = pd.to_datetime(result["交易日期"], errors="coerce")
    if result["交易日期"].isna().any():
        raise ValueError("存在无法解析的交易日期，请检查数据格式。")

    result["成交数量"] = pd.to_numeric(result["成交数量"], errors="coerce")
    if result["成交数量"].isna().any():
        raise ValueError("存在无法转换为数字的成交数量，请检查数据格式。")

    # 先标准化买卖标志
    result["买卖标志"] = result["买卖标志"].map(normalize_flag)
    
    # 删除买卖标志为空的行（包括原始数据中的空白行）
    result = result.dropna(subset=["买卖标志"])

    result = result.sort_values("交易日期").reset_index(drop=True)
    return result


def filter_transactions(df: pd.DataFrame, account_name: str, company_name: str, target_name: str):
    account_value = str(account_name).strip()
    target_value = str(target_name).strip()
    company_value = str(company_name).strip() if company_name else ""

    if company_value:
        filtered = df[
            (df["账户名称"] == account_value)
            & (df["证券公司名称"].fillna("").str.strip() == company_value)
            & (df["证券简称"].str.strip() == target_value)
        ]
    else:
        filtered = df[
            (df["账户名称"] == account_value)
            & (df["证券简称"].str.strip() == target_value)
        ]

    return filtered


def calculate_daily_position(filtered: pd.DataFrame):
    if filtered.empty:
        raise ValueError("未找到指定账户或指定标的的交易记录，请检查查询条件。")

    filtered = filtered.copy()
    filtered["当日买入"] = filtered["成交数量"].where(filtered["买卖标志"] == "B", 0)
    filtered["当日卖出"] = filtered["成交数量"].where(filtered["买卖标志"] == "S", 0)

    daily = filtered.groupby("交易日期", as_index=False).agg(
        当日买入=("当日买入", "sum"),
        当日卖出=("当日卖出", "sum"),
    )
    daily["当日净变化"] = daily["当日买入"] - daily["当日卖出"]
    daily["当日持仓"] = daily["当日净变化"].cumsum()
    daily = daily.sort_values("交易日期").reset_index(drop=True)
    return filtered, daily


def analyze_position(df: pd.DataFrame, account_name: str, company_name: str, target_name: str):
    if not account_name or not str(account_name).strip():
        raise ValueError("账户名称不能为空。")
    if not target_name or not str(target_name).strip():
        raise ValueError("指定标的不能为空。")

    filtered = filter_transactions(df, account_name, company_name, target_name)
    return calculate_daily_position(filtered)


def analyze_multiple_positions(df: pd.DataFrame, account_names: list, company_name: str, target_name: str):
    if not account_names:
        raise ValueError("请至少选择一个账户名称。")
    if not target_name or not str(target_name).strip():
        raise ValueError("指定标的不能为空。")

    results = {}
    missing_accounts = []

    for account_name in account_names:
        filtered = filter_transactions(df, account_name, company_name, target_name)
        if filtered.empty:
            missing_accounts.append(account_name)
            continue
        _, daily = calculate_daily_position(filtered)
        results[account_name] = daily

    if not results:
        raise ValueError("未找到任何选中账户对应的交易记录，请检查账户名和查询条件。")

    if missing_accounts:
        st.warning(f"以下账户未找到对应记录，已跳过：{', '.join(missing_accounts)}")

    return results


def fill_missing_dates(daily_df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    """用前向填充的方式填补缺失的日期，使持仓线连续。"""
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    filled_df = pd.DataFrame({"交易日期": date_range})
    filled_df = filled_df.merge(daily_df, on="交易日期", how="left")
    filled_df["当日持仓"] = filled_df["当日持仓"].fillna(method="ffill")
    return filled_df


if "raw_df" not in st.session_state:
    st.session_state.raw_df = None

uploaded_file = st.file_uploader("证券流水文件", type=["csv", "xlsx", "xls"])

if uploaded_file is not None:
    try:
        raw_df = read_uploaded_file(uploaded_file)
        prepared_df = prepare_dataframe(raw_df)
        st.session_state.raw_df = prepared_df
        st.success(f"文件已成功导入。有效记录数：{len(prepared_df)}")
    except ValueError as exc:
        st.error(str(exc))
        st.session_state.raw_df = None

if st.session_state.raw_df is not None:
    df = st.session_state.raw_df

    st.subheader("数据概览")
    col1, col2, col3 = st.columns(3)
    col1.metric("流水记录数", len(df))
    col2.metric("账户数量", int(df["账户名称"].nunique()))
    col3.metric("证券数量", int(df["证券简称"].nunique()))

    # 分析模式选择
    st.subheader("分析模式")
    mode = st.radio("选择分析模式：", ["单账户分析", "多账户对比"], horizontal=True)

    with st.form("analysis_form"):
        if mode == "单账户分析":
            account_name = st.text_input("账户名称：")
            company_name = st.text_input("证券公司名称（可为空）：")
            target_options = sorted(df["证券简称"].dropna().unique().tolist())
            target_name = st.selectbox("指定标的：", options=target_options, index=0 if target_options else None)
            submitted = st.form_submit_button("开始分析")
        else:  # 多账户对比
            account_options = sorted(df["账户名称"].dropna().unique().tolist())
            selected_accounts = st.multiselect(
                "账户名称（可多选）：",
                options=account_options,
                default=account_options[:min(3, len(account_options))] if account_options else [],
            )
            company_name = st.text_input("证券公司名称（可为空）：")
            target_options = sorted(df["证券简称"].dropna().unique().tolist())
            target_name = st.selectbox("指定标的：", options=target_options, index=0 if target_options else None)
            submitted = st.form_submit_button("开始分析")

    if submitted:
        try:
            if mode == "单账户分析":
                filtered, daily = analyze_position(df, account_name, company_name, target_name)

                if (daily["当日持仓"] < 0).any():
                    st.warning("计算结果出现负持仓，请检查原始流水或查询条件。")

                st.subheader("分析结果")
                summary_cols = st.columns(8)
                summary_cols[0].metric("账户", account_name)
                summary_cols[1].metric("证券公司", company_name if company_name else "全部")
                summary_cols[2].metric("标的", target_name)
                summary_cols[3].metric("交易笔数", int(len(filtered)))
                summary_cols[4].metric("首次交易日期", filtered["交易日期"].min().strftime("%Y-%m-%d"))
                summary_cols[5].metric("最后交易日期", filtered["交易日期"].max().strftime("%Y-%m-%d"))
                summary_cols[6].metric("当前持仓", int(daily["当日持仓"].iloc[-1]))
                summary_cols[7].metric("最高持仓", int(daily["当日持仓"].max()))

                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=daily["交易日期"],
                        y=daily["当日持仓"],
                        mode="lines+markers",
                        name=account_name,
                        line={"width": 2},
                        marker={"size": 7},
                    )
                )
                fig.update_layout(
                    title=f"{account_name} - {target_name} 持仓变化",
                    xaxis_title="交易日期",
                    yaxis_title="持仓数量",
                    template="plotly_white",
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)

                result_table = daily[["交易日期", "当日买入", "当日卖出", "当日净变化", "当日持仓"]].copy()
                result_table["交易日期"] = result_table["交易日期"].dt.strftime("%Y-%m-%d")
                st.subheader("持仓明细表")
                st.dataframe(result_table, use_container_width=True)

            else:  # 多账户对比
                if not selected_accounts:
                    raise ValueError("请至少选择一个账户名称。")

                results = analyze_multiple_positions(df, selected_accounts, company_name, target_name)

                if any((daily["当日持仓"] < 0).any() for daily in results.values()):
                    st.warning("计算结果出现负持仓，请检查原始流水或查询条件。")

                st.subheader("多账户持仓对比")
                
                # 获取全局的最早和最晚交易日期
                all_dates = pd.concat([daily["交易日期"] for daily in results.values()])
                global_start_date = all_dates.min()
                global_end_date = all_dates.max()
                
                # 为每个账户的数据填充缺失日期，使用前向填充
                filled_results = {}
                for account_name_temp, daily in results.items():
                    filled_results[account_name_temp] = fill_missing_dates(daily, global_start_date, global_end_date)

                # 绘制多账户折线图
                fig = go.Figure()
                colors = [
                    "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
                    "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
                ]
                
                for idx, account_name_temp in enumerate(selected_accounts):
                    if account_name_temp in filled_results:
                        color = colors[idx % len(colors)]
                        filled_daily = filled_results[account_name_temp]
                        fig.add_trace(
                            go.Scatter(
                                x=filled_daily["交易日期"],
                                y=filled_daily["当日持仓"],
                                mode="lines+markers",
                                name=account_name_temp,
                                line={"width": 2, "color": color},
                                marker={"size": 5},
                                connectgaps=True,
                            )
                        )
                
                fig.update_layout(
                    title=f"{target_name} - 多账户持仓对比",
                    xaxis_title="交易日期",
                    yaxis_title="持仓数量",
                    template="plotly_white",
                    hovermode="x unified",
                    legend_title="账户名称",
                    height=500,
                )
                st.plotly_chart(fig, use_container_width=True)

                # 对比汇总表
                st.subheader("对比汇总")
                summary_rows = []
                for account_name_temp in selected_accounts:
                    if account_name_temp not in results:
                        continue
                    daily = results[account_name_temp]
                    summary_rows.append({
                        "账户": account_name_temp,
                        "证券公司": company_name if company_name else "全部",
                        "标的": target_name,
                        "交易笔数": len(filter_transactions(df, account_name_temp, company_name, target_name)),
                        "首次交易日期": daily["交易日期"].min().strftime("%Y-%m-%d"),
                        "最后交易日期": daily["交易日期"].max().strftime("%Y-%m-%d"),
                        "当前持仓": int(daily["当日持仓"].iloc[-1]),
                        "最高持仓": int(daily["当日持仓"].max()),
                    })

                if summary_rows:
                    summary_df = pd.DataFrame(summary_rows)
                    st.dataframe(summary_df, use_container_width=True)

        except ValueError as exc:
            st.error(str(exc))
else:
    st.info("请先上传证券流水文件，然后选择分析模式进行分析。")

st.caption("说明：本工具支持单账户分析和多账户持仓对比，暂不包含收益率、成本价、盈亏等其他分析功能。")
