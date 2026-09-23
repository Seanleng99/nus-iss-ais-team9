from datetime import date, timedelta
from dataclasses import asdict, dataclass
from statistics import mean, stdev
from collections import defaultdict
from typing import Literal
from app.api.financial_schemas import SpendingInsight


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
            if weekend_pct > 45:
                description = f"You spend {weekend_pct:.0f}% of your money on weekends"
            else:
                description = f"You spend {weekday_pct:.0f}% of your money on weekdays"
            patterns.append(TemporalPatternResult(
                pattern_type="weekday_weekend",
                description=description,
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
                description = f"You tend to spend more on {day_name(max_day)}s ({daily_averages[max_day]:.1f} avg vs {overall_avg:.1f} daily avg)"
                patterns.append(TemporalPatternResult(
                    pattern_type="day_of_week",
                    description=description,
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
            explanation = (
                f"This trend indicates a consistent change in your {trend['category']} spending. "
                f"A {trend['direction']} of {abs(trend['change_percent']):.0f}% over one month "
                f"could significantly impact your budget if it continues."
            )
            
            if trend["direction"] == "increased":
                suggested_action = (
                    f"Consider reviewing your {trend['category']} expenses to identify areas where you can cut back. "
                    f"Set a monthly budget limit for this category and track your progress."
                )
            else:
                suggested_action = (
                    f"Great job reducing your {trend['category']} spending! "
                    f"Consider redirecting these savings to your emergency fund or investment goals."
                )
            
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
                suggested_action=suggested_action,
                severity=None,
                explanation=explanation,
                educational_context=(
                    f"**Understanding spending trends:** Tracking month-over-month changes helps you "
                    f"identify habits early. A 10-20% change is normal, but anything above 30% may warrant attention."
                ),
            ))
    
    # Generate insights from anomalies
    for anomaly in analysis_result.get("anomalies", [])[:2]:
        explanation = (
            f"This expense stands out significantly from your typical {anomaly['category']} spending pattern. "
            f"Statistical analysis shows it's {anomaly['deviation_percent']:.0f}% above your normal range, "
            f"which occurs in less than 5% of typical spending behavior."
        )
        
        if anomaly["severity"] == "high":
            suggested_action = (
                f"⚠️ **High priority:** Review this ${anomaly['amount']:.2f} expense immediately. "
                f"Consider if this was a one-time purchase or if it indicates a change in spending habits. "
                f"If unplanned, look for ways to offset this in other categories this month."
            )
        else:
            suggested_action = (
                f"💡 **Consider:** While this ${anomaly['amount']:.2f} expense is higher than usual, "
                f"it may be a planned or necessary purchase. Review to ensure it fits your overall budget goals."
            )
        
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
            suggested_action=suggested_action,
            severity=anomaly["severity"],
            explanation=explanation,
            educational_context=(
                f"**What is a spending anomaly?** Anomalies are expenses that deviate significantly "
                f"from your normal patterns. They're not necessarily bad—could be emergencies, celebrations, "
                f"or investments. The key is to be aware and intentional about them."
            ),
        ))
    
    # Generate insights from temporal patterns
    for pattern in analysis_result.get("temporal_patterns", [])[:2]:
        # Use friendly pattern name instead of technical term
        pattern_type = pattern["pattern_type"]
        if "weekend" in pattern_type.lower():
            friendly_pattern = "weekend vs weekday habits"
        elif "day_of_week" in pattern_type.lower():
            friendly_pattern = "specific days of the week"
        else:
            friendly_pattern = "timing patterns"
        
        explanation = (
            f"Your spending shows a consistent pattern based on {friendly_pattern}. "
            f"This {pattern['variance_percent']:.0f}% variance suggests your spending behavior changes "
            f"predictably during certain times, which can be leveraged for better budget planning."
        )
        
        if "weekend" in pattern_type.lower() or "weekday" in pattern_type.lower():
            suggested_action = (
                f"📅 **Weekend planning:** Since you tend to spend more during weekends, "
                f"try setting a weekend-specific budget or planning activities in advance "
                f"to avoid impulse spending. Consider meal prepping to reduce dining out."
            )
            educational_context = (
                f"**Weekend spending patterns:** Many people spend 20-40% more on weekends due to "
                f"social activities, dining out, and leisure. Being aware of this pattern helps you "
                f"plan ahead and make conscious spending decisions."
            )
        else:
            suggested_action = (
                f"📊 **Pattern awareness:** Now that you know your spending varies by timing, "
                f"try to plan larger purchases during your lower-spending periods to stay within budget."
            )
            educational_context = (
                f"**Temporal spending patterns:** Understanding when you spend more helps you "
                f"anticipate and plan for high-spending periods, making it easier to stay on track with your financial goals."
            )
        
        insights.append(SpendingInsight(
            insight_id=f"pattern_{pattern_type}",
            insight_type="pattern",
            title=pattern["description"],
            description=(
                f"You tend to spend {pattern['variance_percent']:.0f}% more/less "
                f"during this period compared to your baseline."
            ),
            category=None,
            confidence=pattern["confidence"],
            data_refs=[
                f"pattern_type:{friendly_pattern}",
                f"variance:{pattern['variance_percent']}%",
            ],
            suggested_action=suggested_action,
            severity=None,
            explanation=explanation,
            educational_context=educational_context,
        ))
    
    # Sort by confidence and return top 5
    insights.sort(key=lambda i: i.confidence, reverse=True)
    return insights[:5]
