from datetime import date, timedelta
from dataclasses import asdict, dataclass
from statistics import mean, stdev
from collections import defaultdict
from typing import Literal
from app.schemas.dashboard import SpendingInsight


@dataclass
class TrendResult:
    category: str
    current_amount: float
    previous_amount: float
    change_percent: float
    direction: Literal["increased", "decreased", "stable"]
    significance: Literal["low", "moderate", "high"]


@dataclass
class TemporalPatternResult:
    pattern_type: Literal["weekday_weekend", "day_of_week"]
    description: str
    variance_percent: float
    confidence: float


@dataclass
class AnomalyResult:
    category: str
    amount: float
    expected_amount: float
    deviation_percent: float
    z_score: float | None
    severity: Literal["low", "medium", "high"]
    occurred_on: date


def aggregate_by_category(transactions: list[dict]) -> dict[str, float]:
    """Sum amounts by category."""
    totals = defaultdict(float)
    for txn in transactions:
        category = txn.get("category", "other")
        amount = txn["amount"]["amount"]
        totals[category] += amount
    return dict(totals)


def compute_category_trends(
    current: list[dict],
    previous: list[dict],
) -> list[TrendResult]:
    """Calculate month-over-month category trends."""
    current_totals = aggregate_by_category(current)
    previous_totals = aggregate_by_category(previous)
    
    trends = []
    all_categories = set(current_totals.keys()) | set(previous_totals.keys())
    
    for category in all_categories:
        current_amount = current_totals.get(category, 0.0)
        previous_amount = previous_totals.get(category, 0.0)
        
        if previous_amount == 0:
            change_percent = 100.0 if current_amount > 0 else 0.0
        else:
            change_percent = ((current_amount - previous_amount) / previous_amount) * 100
        
        if change_percent > 5:
            direction = "increased"
        elif change_percent < -5:
            direction = "decreased"
        else:
            direction = "stable"
        
        if abs(change_percent) > 30:
            significance = "high"
        elif abs(change_percent) > 15:
            significance = "moderate"
        else:
            significance = "low"
        
        trends.append(TrendResult(
            category=category,
            current_amount=round(current_amount, 2),
            previous_amount=round(previous_amount, 2),
            change_percent=round(change_percent, 1),
            direction=direction,
            significance=significance,
        ))
    
    return sorted(trends, key=lambda t: abs(t.change_percent), reverse=True)


def is_weekday(d: date) -> bool:
    """Check if date is Monday-Friday."""
    return d.weekday() < 5


def day_name(weekday: int) -> str:
    """Convert weekday int to name."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[weekday]


def detect_temporal_patterns(transactions: list[dict]) -> list[TemporalPatternResult]:
    """Detect temporal spending patterns."""
    if not transactions:
        return []
    
    patterns = []
    
    # Weekday vs Weekend analysis
    weekday_total = 0.0
    weekend_total = 0.0
    
    for txn in transactions:
        txn_date = date.fromisoformat(txn["occurred_on"])
        amount = txn["amount"]["amount"]
        if is_weekday(txn_date):
            weekday_total += amount
        else:
            weekend_total += amount
    
    total = weekday_total + weekend_total
    if total > 0:
        weekday_pct = (weekday_total / total) * 100
        weekend_pct = (weekend_total / total) * 100
        
        # Detect significant deviation (>60/40 split)
        if weekend_pct > 45 or weekday_pct > 75:
            variance = abs(weekend_pct - 29)  # baseline: 29% weekend
            patterns.append(TemporalPatternResult(
                pattern_type="weekday_weekend",
                description="Weekend spending concentration" if weekend_pct > 45 else "Weekday spending concentration",
                variance_percent=round(variance, 1),
                confidence=0.85,
            ))
    
    # Day-of-week distribution
    day_totals = {i: 0.0 for i in range(7)}
    day_counts = {i: 0 for i in range(7)}
    
    for txn in transactions:
        txn_date = date.fromisoformat(txn["occurred_on"])
        day_totals[txn_date.weekday()] += txn["amount"]["amount"]
        day_counts[txn_date.weekday()] += 1
    
    # Detect if any day is significantly higher than average
    if len(day_totals) >= 3:
        daily_averages = [
            day_totals[d] / day_counts[d] if day_counts[d] > 0 else 0
            for d in range(7)
        ]
        non_zero = [avg for avg in daily_averages if avg > 0]
        
        if len(non_zero) >= 2:
            overall_avg = mean(non_zero)
            if len(non_zero) >= 3 and stdev(non_zero) > overall_avg * 0.3:
                max_day = max(range(7), key=lambda d: daily_averages[d])
                variance = ((daily_averages[max_day] - overall_avg) / overall_avg) * 100 if overall_avg > 0 else 0
                patterns.append(TemporalPatternResult(
                    pattern_type="day_of_week",
                    description=f"High spending on {day_name(max_day)}",
                    variance_percent=round(abs(variance), 1),
                    confidence=0.75,
                ))
    
    return patterns


def group_by_category_monthly(
    transactions: list[dict],
    months: int = 6,
) -> dict[str, list[float]]:
    """Group transactions by category and month."""
    category_months = defaultdict(lambda: defaultdict(float))
    
    for txn in transactions:
        category = txn.get("category", "other")
        txn_date = date.fromisoformat(txn["occurred_on"])
        amount = txn["amount"]["amount"]
        month_key = txn_date.replace(day=1)
        category_months[category][month_key] += amount
    
    # Convert to list of monthly amounts per category
    result = {}
    for category, monthly_data in category_months.items():
        sorted_months = sorted(monthly_data.keys())[-months:]
        result[category] = [monthly_data[m] for m in sorted_months]
    
    return result


def detect_anomalies(
    transactions: list[dict],
    current_month_start: date,
) -> list[AnomalyResult]:
    """Detect statistical anomalies in spending."""
    category_history = group_by_category_monthly(transactions, months=6)
    
    anomalies = []
    for category, monthly_amounts in category_history.items():
        if len(monthly_amounts) < 3:
            continue  # Insufficient history
        
        current_amount = monthly_amounts[-1]
        historical = monthly_amounts[:-1]
        
        if len(historical) < 2:
            continue
        
        avg = mean(historical)
        std = stdev(historical)
        
        if std == 0 or avg == 0:
            continue
        
        z_score = (current_amount - avg) / std
        
        if abs(z_score) > 2.0:
            deviation = ((current_amount - avg) / avg) * 100
            
            if abs(z_score) > 3.0:
                severity = "high"
            elif abs(z_score) > 2.5:
                severity = "medium"
            else:
                severity = "low"
            
            anomalies.append(AnomalyResult(
                category=category,
                amount=round(current_amount, 2),
                expected_amount=round(avg, 2),
                deviation_percent=round(deviation, 1),
                z_score=round(z_score, 2),
                severity=severity,
                occurred_on=current_month_start,
            ))
    
    return sorted(anomalies, key=lambda a: abs(a.z_score or 0), reverse=True)


def filter_transactions(
    transactions: list[dict],
    start_date: date,
    end_date: date | None = None,
) -> list[dict]:
    """Filter transactions by date range."""
    filtered = []
    for txn in transactions:
        txn_date = date.fromisoformat(txn["occurred_on"])
        if txn_date < start_date:
            continue
        if end_date and txn_date > end_date:
            continue
        filtered.append(txn)
    return filtered


def assess_data_quality(transactions: list[dict]) -> str:
    """Assess data quality based on transaction history."""
    if not transactions:
        return "insufficient"
    
    months = set()
    for txn in transactions:
        txn_date = date.fromisoformat(txn["occurred_on"])
        months.add(txn_date.replace(day=1))
    
    months_count = len(months)
    
    if months_count >= 6:
        return "excellent"
    elif months_count >= 3:
        return "good"
    elif months_count >= 1:
        return "limited"
    else:
        return "insufficient"


def calculate_months_available(transactions: list[dict]) -> int:
    """Calculate number of months with transaction data."""
    if not transactions:
        return 0
    
    months = set()
    for txn in transactions:
        txn_date = date.fromisoformat(txn["occurred_on"])
        months.add(txn_date.replace(day=1))
    
    return len(months)


def analyze_spending_patterns(
    transactions: list[dict],
    current_month_start: date,
) -> dict:
    """
    Main entry point for spending analysis.
    Returns structured data for insight generation.
    """
    # Split into current vs previous month
    previous_month_start = current_month_start - timedelta(days=current_month_start.day)
    previous_month_end = current_month_start - timedelta(days=1)
    
    current_month_txns = filter_transactions(transactions, current_month_start)
    previous_month_txns = filter_transactions(
        transactions,
        previous_month_start,
        previous_month_end,
    )
    
    # Run all analyses
    category_trends = compute_category_trends(current_month_txns, previous_month_txns)
    temporal_patterns = detect_temporal_patterns(current_month_txns)
    anomalies = detect_anomalies(transactions, current_month_start)
    data_quality = assess_data_quality(transactions)
    months_analyzed = calculate_months_available(transactions)
    
    return {
        "category_trends": [asdict(t) for t in category_trends],
        "temporal_patterns": [asdict(p) for p in temporal_patterns],
        "anomalies": [asdict(a) for a in anomalies],
        "data_quality": data_quality,
        "months_analyzed": months_analyzed,
    }


def _generate_insights(analysis_result: dict) -> list[SpendingInsight]:
    """Convert statistical analysis to insight objects."""
    insights = []
    
    # Generate insights from trends
    for trend in analysis_result.get("category_trends", [])[:3]:
        if trend["significance"] in ["high", "moderate"]:
            insights.append(SpendingInsight(
                insight_id=f"trend_{trend['category']}_{trend['direction']}",
                insight_type="trend",
                title=f"{trend['category'].title()} spending {trend['direction']} {abs(trend['change_percent']):.0f}%",
                description=(
                    f"Your {trend['category']} expenses changed from "
                    f"${trend['previous_amount']:.2f} to ${trend['current_amount']:.2f} "
                    f"this month."
                ),
                category=trend["category"],
                confidence=0.85 if trend["significance"] == "high" else 0.70,
                data_refs=[
                    f"category:{trend['category']}",
                    f"change:{trend['change_percent']}%",
                ],
                suggested_action=None,
                severity=None,
            ))
    
    # Generate insights from anomalies
    for anomaly in analysis_result.get("anomalies", [])[:2]:
        insights.append(SpendingInsight(
            insight_id=f"anomaly_{anomaly['category']}_{anomaly['occurred_on']}",
            insight_type="anomaly",
            title=f"Unusual {anomaly['category']} expense",
            description=(
                f"A ${anomaly['amount']:.2f} {anomaly['category']} expense is "
                f"{anomaly['deviation_percent']:.0f}% higher than your "
                f"historical average of ${anomaly['expected_amount']:.2f}."
            ),
            category=anomaly["category"],
            confidence=0.90 if anomaly["severity"] == "high" else 0.75,
            data_refs=[
                f"amount:{anomaly['amount']}",
                f"expected:{anomaly['expected_amount']}",
            ],
            suggested_action="Review this expense to confirm it aligns with your budget.",
            severity=anomaly["severity"],
        ))
    
    # Generate insights from temporal patterns
    for pattern in analysis_result.get("temporal_patterns", [])[:2]:
        insights.append(SpendingInsight(
            insight_id=f"pattern_{pattern['pattern_type']}",
            insight_type="pattern",
            title=pattern["description"],
            description=(
                f"You tend to spend {pattern['variance_percent']:.0f}% more/less "
                f"during this period compared to your baseline."
            ),
            category=None,
            confidence=pattern["confidence"],
            data_refs=[
                f"pattern_type:{pattern['pattern_type']}",
                f"variance:{pattern['variance_percent']}%",
            ],
            suggested_action=None,
            severity=None,
        ))
    
    # Sort by confidence and return top 5
    insights.sort(key=lambda i: i.confidence, reverse=True)
    return insights[:5]
