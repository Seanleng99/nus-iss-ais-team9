import streamlit as st
from typing import Literal

InsightType = Literal["trend", "pattern", "anomaly", "opportunity"]


def render_spending_insights_section(insights: list[dict]) -> None:
    """
    Renders the Spending Insights section with dashboard-style cards.
    
    Args:
        insights: List of SpendingInsight dicts from backend
    """
    if not insights:
        st.info("No spending insights available yet. Add transactions to get started.")
        return
    
    # Split insights by type for prioritized display
    anomalies = [i for i in insights if i["insight_type"] == "anomaly"]
    trends = [i for i in insights if i["insight_type"] == "trend"]
    patterns = [i for i in insights if i["insight_type"] == "pattern"]
    opportunities = [i for i in insights if i["insight_type"] == "opportunity"]
    
    # Priority order: anomalies > trends > patterns > opportunities
    priority_insights = (anomalies + trends + patterns + opportunities)[:5]
    
    # Render header
    st.markdown(
        '<div class="spending-insights-header">'
        '<span class="material-icons">insights</span>'
        '<span>Spending Insights</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    
    # Create card columns (3 per row)
    cols_per_row = 3
    for i in range(0, len(priority_insights), cols_per_row):
        row_insights = priority_insights[i : i + cols_per_row]
        cols = st.columns(len(row_insights))
        
        for col, insight in zip(cols, row_insights):
            with col:
                render_insight_card(insight)


def render_insight_card(insight: dict) -> None:
    """
    Renders a single insight card with type-specific styling.
    
    Args:
        insight: SpendingInsight dict with keys:
            - insight_type: "trend" | "pattern" | "anomaly" | "opportunity"
            - title: str
            - description: str
            - confidence: float
            - severity: str | None
            - suggested_action: str | None
    """
    # Type-specific styling
    type_config = {
        "trend": {
            "icon": "trending_up",
            "color": "#18794e",  # Green for trends
            "bg_color": "#f0fdf4",
        },
        "anomaly": {
            "icon": "warning",
            "color": "#dc2626",  # Red for anomalies
            "bg_color": "#fef2f2",
        },
        "pattern": {
            "icon": "schedule",
            "color": "#2563eb",  # Blue for patterns
            "bg_color": "#eff6ff",
        },
        "opportunity": {
            "icon": "lightbulb",
            "color": "#d97706",  # Amber for opportunities
            "bg_color": "#fffbeb",
        },
    }
    
    config = type_config.get(insight["insight_type"], type_config["trend"])
    
    # Card container with custom styling
    with st.container():
        st.markdown(
            f"""
            <div class="insight-card" style="
                background-color: {config['bg_color']};
                border-left: 4px solid {config['color']};
                border-radius: 8px;
                padding: 16px;
                margin: 8px 0;
            ">
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span class="material-icons" style="color: {config['color']}; margin-right: 8px;">
                        {config['icon']}
                    </span>
                    <strong style="color: {config['color']};">{insight['title']}</strong>
                </div>
                <p style="font-size: 14px; color: #374151; margin: 8px 0;">
                    {insight['description']}
                </p>
                <div style="font-size: 12px; color: #6b7280;">
                    Confidence: {insight['confidence']:.0%}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Optional: Action suggestion in expander
        if insight.get("suggested_action"):
            with st.expander("💡 What you can do"):
                st.write(insight["suggested_action"])
