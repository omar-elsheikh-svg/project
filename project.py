import os
import re
import sys
from urllib import response
import pandas as pd
from collections import Counter
from itertools import combinations
from google import genai
from google.genai import types
import json
import os
from google import genai
from google.genai import types


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned.columns = [
        str(col).strip().replace("\n", " ").replace("\r", "") for col in cleaned.columns
    ]
    cleaned.dropna(how="all", inplace=True)

    for col in list(cleaned.columns):
        null_rate = cleaned[col].isnull().mean()

        if null_rate > 0.50:
            cleaned.drop(columns=[col], inplace=True)
            continue

        if pd.api.types.is_numeric_dtype(cleaned[col]):
            med = cleaned[col].median()
            cleaned[col] = cleaned[col].fillna(med if pd.notnull(med) else 0)
        elif (
            pd.api.types.is_datetime64_any_dtype(cleaned[col]) or "date" in col.lower()
        ):
            cleaned[col] = cleaned[col].ffill().bfill()
        else:
            cleaned[col] = cleaned[col].astype(str).str.strip()
            cleaned[col] = cleaned[col].replace(
                ["nan", "None", "NaN", "null", ""], "Unknown"
            )

    cleaned.reset_index(drop=True, inplace=True)
    return cleaned


def features_finder(df: pd.DataFrame) -> pd.DataFrame:
    mapping_rules = {
        "order_id": r"(order|invoice|bill|receipt|فاتور|فوتير|معرف|مسلسل|مُسلسل|المسلسل|الرقم|كود)",
        "date_time": r"(date|time|timestamp|تاريخ|وقت|توقيت|زمن)",
        "product_name": r"(product|item|sku|name|صنف|أصناف|منتج|بضاع|سلع|العنصر|الاسم|الوصف|description)",
        "quantity": r"(qty|quantity|count|amount|الكمية|العدد|قطعة|القطع|قطع)",
        "unit_price": r"(price|rate|cost|سعر|السعر|القيمة|مبلغ|المبلغ|ثمن|القطعة)",
        "product_cost": r"(product[-_\s]*cost|buying[-_\s]*price|تكلفة|التكلفة|شراء)",
        "city": r"(city|governorate|location|address|state|محافظ|مدين|عنوان|منطق|بلد)",
    }

    renamed_columns = {}

    for col in df.columns:
        col_clean = str(col).strip().lower()
        for target_key, pat in mapping_rules.items():
            if target_key not in renamed_columns.values():
                if re.search(pat, col_clean, re.IGNORECASE):
                    renamed_columns[col] = target_key
                    break

    df = df.rename(columns=renamed_columns).copy()

    required = ["order_id", "date_time", "product_name", "quantity", "unit_price"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"Missing mandatory fields: {missing}")

    selected = [c for c in mapping_rules.keys() if c in df.columns]
    data = df[selected].copy()

    data["quantity"] = pd.to_numeric(data["quantity"], errors="coerce").fillna(0)
    data["unit_price"] = pd.to_numeric(data["unit_price"], errors="coerce").fillna(0.0)

    if "product_cost" in data.columns:
        data["product_cost"] = pd.to_numeric(
            data["product_cost"], errors="coerce"
        ).fillna(0.0)

    return data


def calculate_all_insights(df: pd.DataFrame) -> dict:
    df = df.copy()
    results = {}

    df["total_sales"] = df["quantity"] * df["unit_price"]

    if "product_cost" in df.columns:
        df["total_cost"] = df["quantity"] * df["product_cost"]

    rev = float(df["total_sales"].sum())
    orders_cnt = int(df["order_id"].nunique())
    aov_val = rev / orders_cnt if orders_cnt > 0 else 0.0

    results["general_metrics"] = {
        "total_revenue": round(rev, 2),
        "total_orders": orders_cnt,
        "average_order_value": round(aov_val, 2),
    }

    order_sizes = df.groupby("order_id").size()
    single_orders = int((order_sizes == 1).sum())
    multi_orders = int((order_sizes > 1).sum())
    results["basket_size_analysis"] = {
        "single_item_orders": single_orders,
        "multi_item_orders": multi_orders,
        "single_item_percentage": round(
            single_orders / orders_cnt * 100 if orders_cnt else 0.0, 2
        ),
        "multi_item_percentage": round(
            multi_orders / orders_cnt * 100 if orders_cnt else 0.0, 2
        ),
    }

    if "product_cost" in df.columns:
        cst = float(df["total_cost"].sum())
        profit = rev - cst
        margin = (profit / rev) * 100 if rev > 0 else 0.0

        results["general_metrics"]["net_profit"] = round(profit, 2)
        results["general_metrics"]["profit_margin_percentage"] = round(margin, 2)

    product_stats = (
        df.groupby("product_name")
        .agg(units_sold=("quantity", "sum"), revenue_generated=("total_sales", "sum"))
        .reset_index()
    )

    top_items = product_stats.sort_values(by="revenue_generated", ascending=False).head(
        5
    )
    slow_items = product_stats.sort_values(by="units_sold", ascending=True).head(5)

    results["products_analysis"] = {
        "top_5_products": top_items.to_dict(orient="records"),
        "dead_stock_candidates": slow_items.to_dict(orient="records"),
    }

    basket_groups = df.groupby("order_id")["product_name"].apply(list).values
    pair_counts = Counter()

    for item_list in basket_groups:
        items_unique = sorted(list(set(item_list)))
        if len(items_unique) > 1:
            for pair in combinations(items_unique, 2):
                pair_counts[pair] += 1

    cross_sell = []
    for pair, count in pair_counts.most_common(5):
        cross_sell.append(
            {"product_1": pair[0], "product_2": pair[1], "times_bought_together": count}
        )

    results["cross_selling_opportunities"] = cross_sell

    try:
        df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce")
        if not df["date_time"].isnull().all():
            df["hour"] = df["date_time"].dt.hour
            df["day_name"] = df["date_time"].dt.day_name()

            p_hour = df.groupby("hour")["order_id"].nunique().idxmax()
            p_day = df.groupby("day_name")["order_id"].nunique().idxmax()
            hourly_orders = (
                df.groupby("hour")["order_id"]
                .nunique()
                .reindex(range(24), fill_value=0)
            )

            results["time_analysis"] = {
                "peak_hour_24h_format": int(p_hour),
                "peak_day_of_week": str(p_day),
                "hourly_order_counts": [
                    {"hour": int(hour), "orders": int(count)}
                    for hour, count in hourly_orders.items()
                ],
            }
    except Exception:
        results["time_analysis"] = None

    if "city" in df.columns:
        city_stats = df.groupby("city")["total_sales"].sum().reset_index()
        top_locs = city_stats.sort_values(by="total_sales", ascending=False).head(3)
        results["geographic_analysis"] = top_locs.to_dict(orient="records")

    return results


def format_executive_summary(
    insights: dict, output_file: str = "executive_summary.txt"
) -> str:
    def format_number(value) -> str:
        if isinstance(value, float):
            return f"{value:,.2f}"
        return f"{value:,}" if isinstance(value, int) else str(value)

    def format_money(value) -> str:
        return f"{float(value):,.2f}"

    lines = [
        "=" * 72,
        "EXECUTIVE SALES SUMMARY",
        "=" * 72,
    ]

    metrics = insights.get("general_metrics", {})
    lines.extend(
        [
            "\nKEY PERFORMANCE INDICATORS",
            "-" * 72,
            f"Total revenue:          {format_money(metrics.get('total_revenue', 0))}",
            f"Total orders:           {format_number(metrics.get('total_orders', 0))}",
            f"Average order value:    {format_money(metrics.get('average_order_value', 0))}",
        ]
    )

    if "net_profit" in metrics:
        lines.extend(
            [
                f"Net profit:             {format_money(metrics['net_profit'])}",
                f"Profit margin:          {format_number(metrics.get('profit_margin_percentage', 0))}%",
            ]
        )

    products = insights.get("products_analysis", {})
    lines.extend(["\nTOP PRODUCTS BY REVENUE", "-" * 72])
    top_products = products.get("top_5_products", [])
    if top_products:
        for index, product in enumerate(top_products, start=1):
            lines.append(
                f"{index}. {product.get('product_name', 'Unknown')}: "
                f"{format_number(product.get('units_sold', 0))} units, "
                f"{format_money(product.get('revenue_generated', 0))} revenue"
            )
    else:
        lines.append("No product data available.")

    lines.extend(["\nSLOW-MOVING PRODUCTS", "-" * 72])
    slow_products = products.get("dead_stock_candidates", [])
    if slow_products:
        for product in slow_products:
            lines.append(
                f"- {product.get('product_name', 'Unknown')}: "
                f"{format_number(product.get('units_sold', 0))} units sold"
            )
    else:
        lines.append("No slow-moving product data available.")

    lines.extend(["\nCROSS-SELLING OPPORTUNITIES", "-" * 72])
    cross_sell = insights.get("cross_selling_opportunities", [])
    if cross_sell:
        for opportunity in cross_sell:
            lines.append(
                f"- {opportunity.get('product_1', 'Unknown')} + "
                f"{opportunity.get('product_2', 'Unknown')}: "
                f"{format_number(opportunity.get('times_bought_together', 0))} orders"
            )
    else:
        lines.append("No cross-selling pattern found.")

    time_analysis = insights.get("time_analysis")
    lines.extend(["\nTIME ANALYSIS", "-" * 72])
    if time_analysis:
        lines.append(
            f"Peak hour: {time_analysis.get('peak_hour_24h_format', 'Unknown')}:00"
        )
        lines.append(f"Peak day:  {time_analysis.get('peak_day_of_week', 'Unknown')}")
    else:
        lines.append("No valid date/time data available.")

    lines.extend(["\nTOP LOCATIONS BY REVENUE", "-" * 72])
    locations = insights.get("geographic_analysis", [])
    if locations:
        for index, location in enumerate(locations, start=1):
            lines.append(
                f"{index}. {location.get('city', 'Unknown')}: "
                f"{format_money(location.get('total_sales', 0))} revenue"
            )
    else:
        lines.append("No geographic data available.")

    lines.extend(["\n" + "=" * 72, "END OF REPORT", "=" * 72])
    report = "\n".join(lines) + "\n"

    with open(output_file, "w", encoding="utf-8") as report_handle:
        report_handle.write(report)

    return report


def main():
    file_path = input("Enter file path (CSV or XLSX): ").strip()

    if not os.path.exists(file_path):
        sys.exit(f"Error: File '{file_path}' does not exist.")

    try:
        if file_path.endswith(".csv"):
            raw_data = pd.read_csv(file_path)
        elif file_path.endswith(".xlsx"):
            raw_data = pd.read_excel(file_path)
        else:
            sys.exit("Error: File format must be .csv or .xlsx")
    except Exception as err:
        sys.exit(f"Error reading dataset: {err}")

    cleaned = clean_df(raw_data)

    try:
        structured_data = features_finder(cleaned)
        insights = calculate_all_insights(structured_data)

        print(insights)
        return insights
    except ValueError as err:
        sys.exit(f"Data Processing Error: {err}")


if __name__ == "__main__":
    main()
