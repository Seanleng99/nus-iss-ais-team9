from typing import Literal

import streamlit as st

from ui.i18n import ui_message, ui_text

InsightType = Literal["trend", "pattern", "anomaly", "opportunity"]


def _navigate_to_coach_with_question(question: str) -> None:
    """Store question and navigate to Coach page via query params."""
    st.session_state.pending_coach_question = question
    st.session_state.navigate_to_coach = True
    st.query_params["page"] = "coach"
    st.rerun()


def _check_navigation() -> None:
    """Check if navigation to Coach is requested."""
    if st.session_state.get("navigate_to_coach"):
        st.session_state.navigate_to_coach = False
        st.query_params["page"] = "coach"
        st.rerun()


def render_spending_insights_section(insights: list[dict]) -> None:
    """
    Renders the Spending Insights section with dashboard-style cards.
    
    Args:
        insights: List of SpendingInsight dicts from backend
    """
    if not insights:
        st.info(ui_text('No spending insights available yet. Add transactions to get started.'))
        return
    
    # Split insights by type for prioritized display
    anomalies = [i for i in insights if i["insight_type"] == "anomaly"]
    trends = [i for i in insights if i["insight_type"] == "trend"]
    patterns = [i for i in insights if i["insight_type"] == "pattern"]
    opportunities = [i for i in insights if i["insight_type"] == "opportunity"]
    
    # Priority order: anomalies > trends > patterns > opportunities
    priority_insights = (anomalies + trends + patterns + opportunities)[:5]
    
    # Render header with emoji icon
    st.markdown(
        '<div class="spending-insights-header">'
        '<span style="font-size: 20px; margin-right: 8px;">📊</span>'
        '<span>' + ui_text("Spending Insights") + '</span>'
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
    Renders a single insight card with type-specific styling, explanations, and suggestions.
    
    Args:
        insight: SpendingInsight dict with keys:
            - insight_type: "trend" | "pattern" | "anomaly" | "opportunity"
            - title: str
            - description: str
            - confidence: float
            - severity: str | None
            - suggested_action: str | None
            - explanation: str | None (why this matters)
            - educational_context: str | None (learning info)
    """
    # These fields are deterministic analyzer messages. Historical Coach prose
    # and user-authored descriptions are rendered separately without translation.
    insight = {**insight, **{
        field: ui_message(insight[field]) for field in (
            "title", "description", "explanation", "suggested_action", "educational_context"
        ) if insight.get(field)
    }}
    # Type-specific styling with enhanced metadata (using emoji icons for reliability)
    type_config = {
        "trend": {
            "icon": "📈",
            "color": "#18794e",  # Green for trends
            "bg_color": "#f0fdf4",
            "label": "Spending Trend",
            "prompt_suggestion": "Ask: 'How can I manage this trend?'",
        },
        "anomaly": {
            "icon": "⚠️",
            "color": "#dc2626",  # Red for anomalies
            "bg_color": "#fef2f2",
            "label": "Unusual Spending",
            "prompt_suggestion": "Ask: 'Where can I reduce unexpected expenses?'",
        },
        "pattern": {
            "icon": "📅",
            "color": "#2563eb",  # Blue for patterns
            "bg_color": "#eff6ff",
            "label": "Spending Pattern",
            "prompt_suggestion": "Ask: 'Is this pattern normal?'",
        },
        "opportunity": {
            "icon": "💡",
            "color": "#d97706",  # Amber for opportunities
            "bg_color": "#fffbeb",
            "label": "Saving Opportunity",
            "prompt_suggestion": "Ask: 'How much can I save by following this?'",
        },
    }
    
    config = type_config.get(insight["insight_type"], type_config["trend"])
    config = {**config, "label": ui_text(config["label"])}
    
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
                    <span style="font-size: 24px; margin-right: 8px;">
                        {config['icon']}
                    </span>
                    <div>
                        <div style="font-size: 11px; color: {config['color']}; text-transform: uppercase; letter-spacing: 0.5px;">
                            {config['label']}
                        </div>
                        <strong style="color: {config['color']}; font-size: 16px;">{insight['title']}</strong>
                    </div>
                </div>
                <p style="font-size: 14px; color: #374151; margin: 8px 0;">
                    {insight['description'].replace('weekday_weekend', 'weekend vs weekday').replace('day_of_week', 'specific day')}
                </p>
                <div style="font-size: 12px; color: #6b7280; margin-top: 8px;">
                    <span style="display: inline-block; padding: 2px 8px; background: rgba(0,0,0,0.05); border-radius: 12px;">
                        {ui_text('Confidence')}: {insight['confidence']:.0%}
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        # Section 1: Why this matters (Explanation)
        if insight.get("explanation"):
            with st.expander(ui_text('📖 Why this matters'), expanded=False):
                st.info(insight["explanation"])
        
        # Section 2: What you can do (Actionable suggestions)
        if insight.get("suggested_action"):
            with st.expander(ui_text('💡 What you can do'), expanded=False):
                st.success(insight["suggested_action"])
                
                # Create clickable button that navigates to Coach with the question
                prompt_text = ui_text(config['prompt_suggestion'].replace("Ask: '", "").replace("'", ""))
                button_key = f"coach-prompt-{insight['insight_id']}"
                
                if st.button(
                    f"💬 {prompt_text}",
                    key=button_key,
                    use_container_width=True,
                    type="primary"
                ):
                    # Build context from the insight
                    context = {
                        "insight_type": insight.get("insight_type", "spending"),
                        "title": insight.get("title", ""),
                        "description": insight.get("description", ""),
                        "category": insight.get("category", ""),
                        "confidence": insight.get("confidence", 0),
                    }
                    
                    # Format question naturally with context (no internal system details)
                    full_question = (
                        f"I noticed this in my spending insights:\n\n"
                        f"**{context['title']}**\n\n"
                        f"{context['description']}\n\n"
                    )
                    if context.get("category"):
                        full_question += f"This is about my {context['category'].title()} spending.\n\n"
                    full_question += (
                        f"Can you help me understand: {prompt_text}\n\n"
                        f"Please analyze my transaction data and give me specific insights about this."
                    )
                    
                    # Navigate to Coach with the question
                    _navigate_to_coach_with_question(full_question)
        
        # Section 3: Learn more (Educational context)
        if insight.get("educational_context"):
            with st.expander(ui_text('🎓 Learn more'), expanded=False):
                st.markdown(insight["educational_context"])
        
        # Quick action buttons (if no expanders shown, show at least one action)
        if not any([insight.get("explanation"), insight.get("suggested_action"), insight.get("educational_context")]):
            # Default prompt for insights without extra metadata
            st.caption(ui_text('💬 **Ask the Coach:** {v0}', v0=config['prompt_suggestion']))
